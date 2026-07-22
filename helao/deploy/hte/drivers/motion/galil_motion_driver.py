"""Galil motion-controller driver used by a HELAO FastAPI action server.

Wraps the motion portion of the `gclib` library: opens a TCP connection to
the Galil controller at `galil_ip_str`, applies per-axis init commands
(`MT`, `CE`, `TW`, `SD`, `SH`), and exposes coroutines to move motors in
motor/plate/instrument frames, query position and motion status, home,
e-stop, and reset. The driver also owns a `TransformXY` helper that performs
the coordinate transforms between the motor, plate, and instrument frames,
and optionally hosts a Bokeh `Aligner` UI when `enable_aligner` is set.

Requires gclib (Windows). After installing the Galil toolkit, install the
Python module from the helao environment:

`python "c:\\Program Files (x86)\\Galil\\gclib\\source\\wrappers\\python\\setup.py" install`

Migration note (CARDS P4): construction (`__init__`) only stores `config`
and cheap config-derived attributes (K1/K8). Everything that needs the live
hosting `Base` -- persistent calibration file paths (K4), the aligner's
Bokeh host/port (K2/K8), opening the gclib connection, and starting the
aligner's Bokeh `Server` thread (K8) -- is deferred to `connect()`, which
the hosting server calls only after assigning `_base_hook` (mirrors
`thorlabs_kinesis.py`'s pattern, itself following the `leancat_driver.py`
precedent). The aligner's `Active` is no longer created by this driver
(K7b): the `/run_aligner` endpoint now calls `contain_action` itself and
hands the resulting `active` to `start_aligner_run`.
"""

__all__ = ["Galil", "MoveModes", "TransformationModes"]

import numpy as np
import time
import asyncio
import json
import os
from socket import gethostname
from copy import deepcopy
import traceback


from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.core.error import ErrorCodes
from helao.core.models.sample import SolidSample
from helao.core.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
)

# P3a galil-split slice-4: the Bokeh `Server`/`HelaoVis` construction and the
# `Aligner` import moved to the vis-layer host
# (`helao/hexagon/adapters/vis/galil_aligner_host.py`); the driver no longer
# hosts a Bokeh server, holds an Active, or exposes a `base` property (D6 fix).
from ...drivers.motion.enum import MoveModes, TransformationModes
from helao.hexagon.domain.motion_transform import TransformXY
from helao.hexagon.adapters.legacy.calibration_store import JsonFileCalibrationStore

# install galil driver first
# (helao) c:\Program Files (x86)\Galil\gclib\source\wrappers\python>python setup.py install


class cmd_exception(ValueError):
    """Raised when an invalid motion mode reaches the Galil command builder."""

    def __init__(self, arg):
        """Store the offending argument(s) on the exception."""
        self.args = arg


class Galil(HelaoDriver):
    """Galil motion controller driver attached to a HELAO action server.

    Maintains the plate transformation matrix on disk (`<host>_last_plate_calib.json`),
    the instrument transformation matrix (`<host>_instrument_calib.json`), and a
    `TransformXY` helper. Public methods expose motion (`motor_move`,
    `stop_axis`, `motor_off`, `motor_on`), state queries (`query_axis_position`,
    `query_axis_moving`), homing/setup (`setaxisref`), and aligner-UI control.
    """

    def __init__(self, config: dict = {}):
        """Store config and config-derived attributes only; no device I/O, no
        Bokeh, and no `_base_hook`-dependent reads here (K1/K8).

        Args:
            config: Driver configuration (the server's `params` dict).
        """
        super().__init__(config=config)
        self.config_dict = self.config

        # Assigned externally (server startup, mirroring `thorlabs_kinesis.py`'s
        # `_base_hook` pattern) so `connect()` can read `helaodirs`/`server_cfg`
        # (K2/K4) without this driver ever holding a live `Base` reference at
        # construction time.
        self._base_hook = None

        self.dflt_matrix = np.matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])

        # Populated in connect(): the paths depend on self._base_hook.helaodirs
        # (K4), which isn't available until the server assigns the hook.
        self.file_backup_transfermatrix = None
        self.plate_transfermatrix = self.dflt_matrix
        self.M_instr = None
        self.transform = None

        self.motor_timeout = self.config_dict.get("timeout", 60)
        self.motor_max_speed_count_sec = self.config_dict.get(
            "max_speed_count_sec", 25000
        )
        self.motor_def_speed_count_sec = self.config_dict.get(
            "def_speed_count_sec", 10000
        )

        # need to check if config settings exist
        # else need to create empty ones
        self.axis_id = self.config_dict.get("axis_id", {})

        # gclib connection is opened in connect(), never here (K8)
        self.g = None
        self.galilcmd = None
        self.galil_enabled = None

        # block gamry -- also the shared mutual-exclusion lock between
        # `_motor_move` and a running plate alignment (driver-owned; the
        # vis-layer aligner host reads/clears it through AlignerMotorContext).
        self.blocked = False
        # is motor move busy?
        self.motor_busy = False

        # P3a galil-split slice-4: the Bokeh aligner + its Active are no longer
        # owned by the driver. The driver keeps only an optional position-notify
        # sink (the aligner's asyncio queue) that `update_aligner` feeds; the
        # vis-layer `GalilAlignerHost` sets it via `set_position_sink`. The old
        # `bokehapp`/`aligner`/`aligning_enabled`/`aligner_plateid`/
        # `aligner_active`/`aligner_enabled` attrs and the `base` property moved
        # to the host / AlignerMotorContext (D6 fix).
        self._position_sink = None

    def set_position_sink(self, sink) -> None:
        """Register (or clear with ``None``) the aligner position-notify queue.

        Called by the vis-layer ``GalilAlignerHost`` when it constructs the
        Bokeh ``Aligner``; ``update_aligner`` pushes motor position/status
        dicts here so the aligner's Bokeh widgets stay live.
        """
        self._position_sink = sink

    def connect(self) -> DriverResponse:
        """Load plate calibration, build the axis transform, open the gclib
        connection to the controller, and (if enabled) start the Bokeh
        aligner.

        Deferred here rather than `__init__` (K8) because the calibration
        file paths come from `self._base_hook.helaodirs` (K4) and the
        aligner's host/port come from `self._base_hook.server_cfg` (K2),
        neither of which exist until the hosting server assigns
        `_base_hook` post-construction; and because opening the gclib
        connection and starting the aligner's Bokeh `Server` thread must
        not happen at construction time (K8).

        Returns:
            `DriverResponse` reporting whether the Galil connection is enabled.
        """
        import gclib

        try:
            helaodirs = getattr(self._base_hook, "helaodirs", None)

            self.file_backup_transfermatrix = None
            if helaodirs is not None and helaodirs.states_root is not None:
                self.file_backup_transfermatrix = os.path.join(
                    helaodirs.states_root,
                    f"{gethostname().lower()}_last_plate_calib.json",
                )

            # P3a galil-split slice-2 (hexagon CalibrationStorePort): the
            # store computes the identical <states_root>/<host>_last_plate_
            # calib.json and <db_root>/plate_calib/<host>_instrument_calib.json
            # paths inline above/below; `save_transfermatrix`/
            # `load_transfermatrix` remain unchanged (still used by the
            # aligner's out-of-scope named-plate write and by
            # `update_plate_transfermatrix`).
            self._calib_store = JsonFileCalibrationStore(
                states_root=helaodirs.states_root if helaodirs is not None else None,
                db_root=helaodirs.db_root if helaodirs is not None else None,
                hostname=gethostname().lower(),
            )

            self.plate_transfermatrix = self._calib_store.load_plate_calibration()
            if self.plate_transfermatrix is None:
                self.plate_transfermatrix = self.dflt_matrix

            self._calib_store.save_plate_calibration(self.plate_transfermatrix)
            LOGGER.info(f"plate_transfermatrix is: \n{self.plate_transfermatrix}")

            self.M_instr = None
            if helaodirs is not None:
                Mplate = self._calib_store.load_instrument_calibration()

                if Mplate is not None:
                    self.M_instr = self.convert_Mplate_to_Minstr(Mplate=Mplate.tolist())

            if self.M_instr is None:
                LOGGER.info("Did not find refernce plate, loading Minstr from config")

                self.M_instr = self.config_dict.get(
                    "M_instr",
                    [
                        [1, 0, 0, 0],
                        [0, 1, 0, 0],
                        [0, 0, 1, 0],
                        [0, 0, 0, 1],
                    ],
                )
            LOGGER.info(f"Minstr is: {self.M_instr}")

            # Mplatexy is identity matrix by default
            self.transform = TransformXY(self.M_instr, self.axis_id)
            # only here for testing: will overwrite the default identity matrix
            self.transform.update_Mplatexy(Mxy=self.plate_transfermatrix)

            # if this is the main instance let us make a galil connection
            self.g = gclib.py()
            LOGGER.info(f"gclib version: {self.g.GVersion()}")
            # TODO: error checking here: Galil can crash an dcarsh program
            galil_ip = self.config_dict.get("galil_ip_str", None)
            self.galil_enabled = None
            self.galilcmd = None
            try:
                if galil_ip:
                    self.g.GOpen("%s --direct -s ALL" % (galil_ip))
                    LOGGER.info(self.g.GInfo())
                    self.galilcmd = self.g.GCommand  # alias the command callable
                    # The SH commands tells the controller to use the current
                    # motor position as the command position and to enable servo control here.
                    # The SH command changes the coordinate system.
                    # Therefore, all position commands given prior to SH,
                    # must be repeated. Otherwise, the controller produces incorrect motion.
                    self.galilcmd("PF 10.4")
                    axis_init = [
                        ("MT", 2),  # Specifies Step motor with active low step pulses
                        ("CE", 4),  # Configure Encoder: Normal pulse and direction
                        ("TW", 32000),  # Timeout for IN Position (MC) in ms
                        (
                            "SD",
                            256000,
                        ),  # sets the linear deceleration rate of the motors when a limit switch has been reached.
                    ]
                    for axl in self.axis_id.values():
                        cmd = f"MG _MO{axl}"
                        LOGGER.info(f"init axis {axl}: {cmd}")
                        q = self.galilcmd(cmd)
                        LOGGER.info(f"Motor off?: {q} {float(q)==1}")
                        if float(q) == 1:
                            cmd = f"SH{axl}"
                            LOGGER.info(f"init axis {axl}: {cmd}")
                            self.galilcmd(cmd)
                        for ac, av in axis_init:
                            cmd = f"{ac}{axl}={av}"
                            LOGGER.info(f"init axis {axl}: {cmd}")
                            self.galilcmd(cmd)

                    self.galil_enabled = True
                else:
                    LOGGER.error("no Galil IP configured")
                    self.galil_enabled = False
            except Exception:
                LOGGER.error("Galil connection error", exc_info=True)
                self.galil_enabled = False

            # P3a galil-split slice-4: the Bokeh aligner is no longer started
            # here. The action server constructs `GalilAlignerHost` after
            # connect() when `enable_aligner` is set (D6 fix).

            return DriverResponse(
                response=DriverResponseType.success,
                status=(
                    DriverStatus.ok
                    if self.galil_enabled
                    else DriverStatus.uninitialized
                ),
            )
        except Exception:
            LOGGER.error("connect failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )

    def get_status(self) -> DriverResponse:
        """Report whether the Galil connection is open, busy, or uninitialized."""
        if not self.galil_enabled:
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.uninitialized
            )
        return DriverResponse(
            response=DriverResponseType.success,
            status=DriverStatus.busy if self.motor_busy else DriverStatus.ok,
        )

    async def stop(self) -> DriverResponse:
        """Abort motion on every configured axis (device stays enabled)."""
        try:
            await self.stop_axis(self.get_all_axis())
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("stop failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )

    def reset(self) -> DriverResponse:
        """Force-close and reopen the Galil connection (ABC lifecycle method).

        This is distinct from the pre-migration `reset` device command (an
        emergency `RS` controller reset, preserved below as
        `reset_controller`); the ABC contract asks for "reinitialize the
        driver, force-closing any existing connection" (K1 naming
        collision -- see `reset_controller`).
        """
        self.disconnect()
        return self.connect()

    def disconnect(self) -> DriverResponse:
        """Release the Galil connection (ABC lifecycle method).

        Delegates to `shutdown` -- the action server's FastAPI shutdown
        event still looks up `shutdown`/`async_shutdown` by duck-typed
        `getattr` (`base_api.py`'s `shutdown_event`) regardless of
        `HelaoDriver` status, so both call paths close the same connection
        identically.
        """
        self.shutdown()
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    def convert_Mplate_to_Minstr(self, Mplate) -> list:
        """Embed a 3x3 plate matrix into a 4x4 instrument matrix.

        Copies the xy linear block and the xy offset column; leaves the
        z/rotation rows as identity.
        """
        Minstr = [
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ]
        # assign the xy part
        Minstr[0][0:2] = Mplate[0][0:2]
        Minstr[1][0:2] = Mplate[1][0:2]
        # assign offset part
        Minstr[0][3] = Mplate[0][2]
        Minstr[1][3] = Mplate[1][2]
        return Minstr

    async def setaxisref(self):
        """Home every linear axis, refine the home position, then zero absolute coords.

        Skips the rotational `Rx`/`Ry`/`Rz` axes. Performs a fast homing move,
        then a 2mm relative back-off, then a slow homing approach, then moves
        to the configured `axis_zero` offsets and zeros the encoder positions
        via `DP`.

        Returns:
            The result of the final relative move, or "error" if the
            controller is disabled.
        """
        if not self.galil_enabled:
            return "error"

        axis = self.get_all_axis()
        LOGGER.info(f"axis: {axis}")
        if "Rx" in axis:
            axis.remove("Rx")
        if "Ry" in axis:
            axis.remove("Ry")
        if "Rz" in axis:
            axis.remove("Rz")
        #            axis.pop(axis.index('Rz'))
        LOGGER.info(f"axis: {axis}")

        if axis is not None:
            # go slow to find the same position every time
            # first a fast move to find the switch
            _ = await self._motor_move(
                d_mm=[0 for ax in axis],
                axis=axis,
                speed=self.motor_max_speed_count_sec,
                mode=MoveModes.homing,
                transformation=TransformationModes.motorxy,
            )

            # move back 2mm
            _ = await self._motor_move(
                d_mm=[2 for ax in axis],
                axis=axis,
                speed=self.motor_max_speed_count_sec,
                mode=MoveModes.relative,
                transformation=TransformationModes.motorxy,
            )

            # approach switch again very slow to get better zero position
            _ = await self._motor_move(
                d_mm=[0 for ax in axis],
                axis=axis,
                speed=1000,
                mode=MoveModes.homing,
                transformation=TransformationModes.motorxy,
            )

            # move back to configured center coordinates
            retc2 = await self._motor_move(
                d_mm=[self.config_dict["axis_zero"][self.axis_id[ax]] for ax in axis],
                axis=axis,
                speed=None,
                mode=MoveModes.relative,
                transformation=TransformationModes.motorxy,
            )

            # set absolute zero to current position
            q = self.galilcmd("TP")  # query position of all axis
            # LOGGER.info(f"q1: {q}")
            cmd = "DP "
            for i in range(len(q.split(","))):
                if i == 0:
                    cmd += "0"
                else:
                    cmd += ",0"
            # LOGGER.info(f"cmd: {cmd}")

            # sets abs zero here
            _ = self.galilcmd(cmd)

            return retc2
        else:
            return "error"

    # P3a galil-split slice-4: `stop_aligner`, `run_aligner_precheck`, and
    # `start_aligner_run` moved to the vis-layer `GalilAlignerHost` (they own
    # the aligner session + its Active, which no longer live on the driver).
    # `blocked` (read/set by those verbs and by `_motor_move`) stays here as the
    # driver-owned shared lock; the host reaches it through AlignerMotorContext.

    async def motor_move(self, active) -> dict:
        """Public motor-move entry point that extracts params from `active.action`.

        Guards against concurrent moves with `self.blocked`. Forwards `d_mm`,
        `axis`, `speed`, `mode`, and `transformation` to `_motor_move`.

        Returns:
            The result dict from `_motor_move`, or an `in_progress` stub when
            the driver is already busy or disabled.
        """
        d_mm = active.action.action_params.get("d_mm", [])
        axis = active.action.action_params.get("axis", [])
        speed = active.action.action_params.get("speed", None)
        mode = active.action.action_params.get("mode", MoveModes.absolute)
        transformation = active.action.action_params.get(
            "transformation", TransformationModes.motorxy
        )
        if not self.blocked and self.galil_enabled:
            self.blocked = True
            retval = await self._motor_move(
                d_mm=d_mm,
                axis=axis,
                speed=speed,
                mode=mode,
                transformation=transformation,
            )
            self.blocked = False
            return retval
        else:
            return {
                "moved_axis": None,
                "speed": None,
                "accepted_rel_dist": None,
                "supplied_rel_dist": None,
                "err_dist": None,
                "err_code": ErrorCodes.in_progress,
                "counts": None,
            }

    async def _motor_move(self, d_mm, axis, speed, mode, transformation) -> dict:
        """Internal mover: transforms coordinates, issues `BG` per axis, and waits.

        Converts `d_mm` from the requested `transformation` frame (motor/plate/
        instrument) into motor-axis distances, computes counts using
        `count_to_mm`, clamps speed to `motor_max_speed_count_sec`, builds the
        Galil command sequence (with `ST/MO/SH/SP/PR|PA|HM/BG`), then polls
        `query_axis_moving` until every axis stops or the per-axis timeout
        expires.

        Returns:
            Dict with per-axis lists: `moved_axis`, `speed`, `accepted_rel_dist`,
            `supplied_rel_dist`, `err_dist`, `err_code`, `counts`. On estop or
            controller error, all values may be None and `err_code` reflects
            the failure.
        """
        if self.motor_busy or not self.galil_enabled:
            return {
                "moved_axis": None,
                "speed": None,
                "accepted_rel_dist": None,
                "supplied_rel_dist": None,
                "err_dist": None,
                "err_code": ErrorCodes.in_progress,
                "counts": None,
            }

        self.motor_busy = True

        # in order to enable easy mode for swagger:
        if not isinstance(axis, list):
            axis = [axis]
        if not isinstance(d_mm, list):
            d_mm = [d_mm]

        stopping = False  # no stopping of any movement by other actions
        mode = MoveModes(mode)
        transformation = TransformationModes(transformation)

        # need to get absolute motor position first
        tmpmotorpos = await self.query_axis_position(axis=self.get_all_axis())
        LOGGER.info(f"current absolute motor positions: {tmpmotorpos}")
        # don't use dicts as we do math on these vectors
        # x, y, z, Rx, Ry, Rz
        current_positionvec = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        # map the request to this
        # x, y, z, Rx, Ry, Rz
        req_positionvec = [None, None, None, None, None, None]

        reqdict = dict(zip(axis, d_mm))
        LOGGER.info(f"requested position ({mode}): {reqdict}")

        for idx, ax in enumerate(["x", "y", "z", "Rx", "Ry", "Rz"]):
            if ax in tmpmotorpos["ax"]:
                # for current_positionvec
                current_positionvec[idx] = tmpmotorpos["position"][
                    tmpmotorpos["ax"].index(ax)
                ]
                # for req_positionvec
                if ax in reqdict:
                    req_positionvec[idx] = reqdict[ax]

        LOGGER.info(f"motor position vector: {current_positionvec[0:3]}")
        LOGGER.info(f"requested position vector ({mode}) {req_positionvec}")

        if transformation == TransformationModes.motorxy:
            # nothing to do
            LOGGER.info(f"motion: got motorxy ({mode}), no transformation necessary")
        elif transformation == TransformationModes.platexy:
            LOGGER.info(f"motion: got platexy ({mode}), converting to motorxy")
            motorxy = [0, 0, 1]
            motorxy[0] = current_positionvec[0]
            motorxy[1] = current_positionvec[1]
            current_platexy = self.transform.transform_motorxy_to_platexy(motorxy)
            # transform.transform_motorxyz_to_instrxyz(current_positionvec[0:3])
            LOGGER.info(f"current plate position (calc from motor): {current_platexy}")
            if mode == MoveModes.relative:
                new_platexy = [0, 0, 1]

                if req_positionvec[0] is not None:
                    new_platexy[0] = current_platexy[0] + req_positionvec[0]
                else:
                    new_platexy[0] = current_platexy[0]

                if req_positionvec[1] is not None:
                    new_platexy[1] = current_platexy[1] + req_positionvec[1]
                else:
                    new_platexy[1] = current_platexy[1]

                LOGGER.info(f"new platexy (abs): {new_platexy}")
                new_motorxy = self.transform.transform_platexy_to_motorxy(new_platexy)
                LOGGER.info(f"new motorxy (abs): {new_motorxy}")
                axis = ["x", "y"]
                d_mm = [d for d in new_motorxy[0:2]]
                mode = MoveModes.absolute
            elif mode == MoveModes.absolute:
                new_platexy = [0, 0, 1]

                if req_positionvec[0] is not None:
                    new_platexy[0] = req_positionvec[0]
                else:
                    new_platexy[0] = current_platexy[0]

                if req_positionvec[1] is not None:
                    new_platexy[1] = req_positionvec[1]
                else:
                    new_platexy[1] = current_platexy[1]

                LOGGER.info(f"new platexy (abs): {new_platexy}")
                new_motorxy = self.transform.transform_platexy_to_motorxy(new_platexy)
                LOGGER.info(f"new motorxy (abs): {new_motorxy}")
                axis = ["x", "y"]
                d_mm = [d for d in new_motorxy[0:2]]

            elif mode == MoveModes.homing:
                # not coordinate conversoion needed as these are not used (but length is still checked)
                pass

            xyvec = [0, 0, 1]
            for i, ax in enumerate(axis):
                if ax == "x":
                    xyvec[0] = d_mm[0]
                if ax == "y":
                    xyvec[1] = d_mm[1]
        elif transformation == TransformationModes.instrxy:
            LOGGER.info(f"mode: {mode}")
            LOGGER.info(f"motion: got instrxyz ({mode}), converting to motorxy")
            current_instrxyz = self.transform.transform_motorxyz_to_instrxyz(
                current_positionvec[0:3]
            )
            LOGGER.info(
                f"current instrument position (calc from motor): {current_instrxyz}"
            )
            if mode == MoveModes.relative:
                new_instrxyz = current_instrxyz
                for i in range(3):
                    if req_positionvec[i] is not None:
                        new_instrxyz[i] = new_instrxyz[i] + req_positionvec[i]
                    else:
                        new_instrxyz[i] = new_instrxyz[i]
                LOGGER.info(f"new instrument position (abs): {new_instrxyz}")
                # transform from instrxyz to motorxyz
                new_motorxyz = self.transform.transform_instrxyz_to_motorxyz(
                    new_instrxyz[0:3]
                )
                LOGGER.info(f"new motor position (abs): {new_motorxyz}")
                axis = ["x", "y", "z"]
                d_mm = [d for d in new_motorxyz[0:3]]
                mode = MoveModes.absolute
            elif mode == MoveModes.absolute:
                new_instrxyz = current_instrxyz
                for i in range(3):
                    if req_positionvec[i] is not None:
                        new_instrxyz[i] = req_positionvec[i]
                    else:
                        new_instrxyz[i] = new_instrxyz[i]
                LOGGER.info(f"new instrument position (abs): {new_instrxyz}")
                new_motorxyz = self.transform.transform_instrxyz_to_motorxyz(
                    new_instrxyz[0:3]
                )
                LOGGER.info(f"new motor position (abs): {new_motorxyz}")
                axis = ["x", "y", "z"]
                d_mm = [d for d in new_motorxyz[0:3]]
            elif mode == MoveModes.homing:
                # not coordinate conversoion needed as these are not used (but length is still checked)
                pass

        LOGGER.info(f"final axis requested: {axis}")
        LOGGER.info(f"final d ({mode}) requested: {d_mm}")

        # return value arrays for multi axis movement
        ret_moved_axis = []
        ret_speed = []
        ret_accepted_rel_dist = []
        ret_supplied_rel_dist = []
        ret_err_dist = []
        ret_err_code = []
        ret_counts = []

        # expected time for each move, used for axis stop check
        timeofmove = []

        if self._is_estopped():
            self.motor_busy = False
            return {
                "moved_axis": None,
                "speed": None,
                "accepted_rel_dist": None,
                "supplied_rel_dist": None,
                "err_dist": None,
                "err_code": ErrorCodes.estop,
                "counts": None,
            }

        # remove not configured axis
        for ax in deepcopy(axis):
            if ax not in self.axis_id:
                LOGGER.info(f"'{ax}' is not in '{self.axis_id}', removing it.")
                axis.pop(axis.index(ax))

        # TODO: if same axis is moved twice
        for d, ax in zip(d_mm, axis):
            # need to remove stopping for multi-axis move
            if len(ret_moved_axis) > 0:
                stopping = False

            # first we check if we have the right axis specified
            # if 1:
            if ax in self.axis_id:
                axl = self.axis_id[ax]
            else:
                LOGGER.error(
                    f"motor setup error: '{ax}' is not in '{self.axis_id}'",
                    exc_info=True,
                )
                ret_moved_axis.append(None)
                ret_speed.append(None)
                ret_accepted_rel_dist.append(None)
                ret_supplied_rel_dist.append(d)
                ret_err_dist.append(None)
                ret_err_code.append(ErrorCodes.setup)
                ret_counts.append(None)
                continue

            # check if the motors are moving if so return an error message
            # recalculate the distance in mm into distance in counts
            # if 1:
            try:
                LOGGER.info(
                    f"count_to_mm: {axl}, {self.config_dict['count_to_mm'][axl]}"
                )
                float_counts = (
                    d / self.config_dict["count_to_mm"][axl]
                )  # calculate float dist from steupd

                counts = int(np.floor(float_counts))  # we can only mode full counts
                # save and report the error distance
                error_distance = self.config_dict["count_to_mm"][axl] * (
                    float_counts - counts
                )

                # check if a speed was upplied otherwise set it to standart
                if speed is None:
                    speed = self.motor_def_speed_count_sec
                else:
                    speed = int(np.floor(speed))

                if speed > self.motor_max_speed_count_sec:
                    speed = self.motor_max_speed_count_sec
                self._speed = speed
            except Exception:
                LOGGER.error(f"motor numerical error for axis '{ax}'", exc_info=True)
                # something went wrong in the numerical part so we give that as feedback
                ret_moved_axis.append(None)
                ret_speed.append(None)
                ret_accepted_rel_dist.append(None)
                ret_supplied_rel_dist.append(d)
                ret_err_dist.append(None)
                ret_err_code.append(ErrorCodes.numerical)
                ret_counts.append(None)
                continue

            try:
                # the logic here is that we assemble a command experiment
                # here we decide if we move relative, home, or move absolute
                if stopping:
                    cmd_seq = [
                        f"ST{axl}",
                        f"MO{axl}",
                        f"SH{axl}",
                        f"SP{axl}={speed}",
                    ]
                else:
                    cmd_seq = [f"SP{axl}={speed}"]
                if mode == MoveModes.relative:
                    cmd_seq.append(f"PR{axl}={counts}")
                elif mode == MoveModes.homing:
                    cmd_seq.append(f"HM{axl}")
                elif mode == MoveModes.absolute:
                    # now we want an abolute position
                    cmd_seq.append(f"PA{axl}={counts}")
                else:
                    raise cmd_exception
                cmd_seq.append(f"BG{axl}")
                # todo: fix this for absolute or relative move
                timeofmove.append(abs(counts / speed))

                # ret = ""
                # LOGGER.info(f"BUGCHECK: {cmd_seq}")
                # BUG
                # TODO
                # it can happen that it crashes below for some reasons
                # when more then two axis move are requested
                for cmd in cmd_seq:
                    _ = self.galilcmd(cmd)
                    # ret.join(_)
                # LOGGER.info(f"Galil cmd: {cmd_seq}")
                ret_moved_axis.append(axl)
                ret_speed.append(speed)
                ret_accepted_rel_dist.append(None)
                ret_supplied_rel_dist.append(d)
                ret_err_dist.append(error_distance)
                ret_err_code.append(ErrorCodes.none)
                ret_counts.append(counts)
                # time = counts/ counts_per_second

                # continue
            except Exception:
                LOGGER.error("motor error", exc_info=True)
                ret_moved_axis.append(None)
                ret_speed.append(None)
                ret_accepted_rel_dist.append(None)
                ret_supplied_rel_dist.append(d)
                ret_err_dist.append(None)
                ret_err_code.append(ErrorCodes.motor)
                ret_counts.append(None)
                continue

        # get max time until all axis are expected to have stopped
        LOGGER.info(f"timeofmove: {timeofmove}")
        if len(timeofmove) > 0:
            tmax = max(timeofmove)
            if tmax > 30 * 60:
                tmax = 30 * 60  # 30min hard limit
        else:
            tmax = 0

        # wait for expected axis move time before checking if axis stoppped
        LOGGER.info(f"axis expected to stop in {tmax} sec")

        if not self._is_estopped():

            # check if all axis stopped
            tstart = time.time()

            while (
                time.time() - tstart < self.motor_timeout
            ) and not self._is_estopped():
                qmove = await self.query_axis_moving(axis=axis)
                await asyncio.sleep(0.5)
                if all(status == "stopped" for status in qmove["motor_status"]):
                    break

            if not self._is_estopped():
                # stop of motor movement (motor still on)
                if time.time() - tstart > self.motor_timeout:
                    await self.stop_axis(axis)
                # check which axis had the timeout
                newret_err_code = []
                for erridx, err_code in enumerate(ret_err_code):
                    if qmove["err_code"][erridx] != ErrorCodes.none:
                        newret_err_code.append(ErrorCodes.timeout)
                        LOGGER.error("motor timeout error")
                    else:
                        newret_err_code.append(err_code)

                ret_err_code = newret_err_code
            else:
                # estop occured while checking axis end position
                ret_err_code = [ErrorCodes.estop for _ in ret_err_code]

        else:
            # estop was triggered while waiting for axis to stop
            ret_err_code = [ErrorCodes.estop for _ in ret_err_code]

        # read final position
        # updates ws buffer
        _ = await self.query_axis_position(axis=axis)

        # one return for all axis
        self.motor_busy = False
        return {
            "moved_axis": ret_moved_axis,
            "speed": ret_speed,
            "accepted_rel_dist": ret_accepted_rel_dist,
            "supplied_rel_dist": ret_supplied_rel_dist,
            "err_dist": ret_err_dist,
            "err_code": ret_err_code,
            "counts": ret_counts,
        }

    async def motor_disconnect(self) -> dict:
        """Close the gclib TCP connection and report the resulting state.

        Returns:
            Dict with a single `connection` field describing the outcome.
        """
        import gclib

        try:
            self.g.GClose()  # don't forget to close connections!
        except gclib.GclibError as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            return {"connection": {"Unexpected GclibError:", e}}
        return {"connection": "motor_offline"}

    async def query_axis_position(self, axis, *args, **kwargs) -> dict:
        """Query absolute axis positions and return them in motor mm.

        Reads `TP` to discover how many physical axes exist, then `PA ?,?,?...`
        for the absolute positions; the raw counts are scaled by
        `count_to_mm` and mapped back through the inverse of `axis_id`. The
        aligner UI is also notified.

        Args:
            axis: Single axis name or list of axis names to return.

        Returns:
            Dict with parallel `ax` and `position` lists in the requested order.
        """
        if not self.galil_enabled:
            LOGGER.error("Galil is disabled")
            return {"ax": [], "position": []}
        # convert single axis move to list
        if not isinstance(axis, list):
            axis = [axis]

        # first get the relative position (actual only the current position of the encoders)
        # to get how many axis are present
        qTP = self.galilcmd("TP")  # query position of all axis
        LOGGER.info(f"q (TP): {qTP}")
        cmd = "PA "
        for i in range(len(qTP.split(","))):
            if i == 0:
                cmd += "?"
            else:
                cmd += ",?"
        q = self.galilcmd(cmd)  # query position of all axis
        # _ = self.galilcmd("PF 10.4")  # set format
        # q = self.galilcmd("TP")  # query position of all axis
        LOGGER.info(f"q (PA): {q}")
        # now we need to map these outputs to the ABCDEFG... channels
        # and then map that to xyz so it is humanly readable
        axlett = "ABCDEFGH"
        axlett = axlett[0 : len(q.split(","))]
        inv_axis_id = {d: v for v, d in self.axis_id.items()}
        ax_abc_to_xyz = {
            l: inv_axis_id[l] for i, l in enumerate(axlett) if l in inv_axis_id
        }
        # this puts the counts back to motor mm
        pos = {
            axl: float(r) * self.config_dict["count_to_mm"].get(axl, 0)
            for axl, r in zip(axlett, q.split(", "))
        }
        # return the results through calculating things into mm
        axpos = {ax_abc_to_xyz.get(k, None): p for k, p in pos.items()}
        ret_ax = []
        ret_position = []
        for ax in axis:
            if ax in axpos:
                # self.update_wsmotorbuffersingle("position", ax, axpos[ax])
                ret_ax.append(ax)
                ret_position.append(axpos[ax])
            else:
                ret_ax.append(None)
                ret_position.append(None)

        msg_ret_ax = []
        msg_ret_position = []
        for ax, pos in axpos.items():
            msg_ret_ax.append(ax)
            msg_ret_position.append(pos)
        await self.update_aligner(msg={"ax": msg_ret_ax, "position": msg_ret_position})
        return {"ax": ret_ax, "position": ret_position}

    async def query_axis_moving(self, axis, *args, **kwargs) -> dict:
        """Query the `SC` stop-code register and classify each axis as moving or stopped.

        Args:
            axis: Single axis name or list of axis names.

        Returns:
            Dict with `motor_status` (per-axis "moving"/"stopped"/"invalid")
            and `err_code` (per-axis error code).
        """
        if not self.galil_enabled:
            LOGGER.error("Galil is disabled")
            return {"motor_status": [], "err_code": ErrorCodes.not_available}

        q = self.galilcmd("SC")
        axlett = "ABCDEFGH"
        axlett = axlett[0 : len(q.split(","))]
        # convert single axis move to list
        if not isinstance(axis, list):
            axis = [axis]
        ret_status = []
        ret_err_code = []
        qdict = dict(zip(axlett, q.split(", ")))
        for ax in axis:
            if ax in self.axis_id:
                axl = self.axis_id.get(ax, None)
                if axl in qdict:
                    r = qdict[axl]
                    if int(r) == 0:
                        # self.update_wsmotorbuffersingle("motor_status", ax, "moving")
                        # self.update_wsmotorbuffersingle("err_code", ax, int(r))
                        ret_status.append("moving")
                        ret_err_code.append(ErrorCodes.none)
                    elif int(r) == 1:
                        # self.update_wsmotorbuffersingle("motor_status", ax, "stopped")
                        # self.update_wsmotorbuffersingle("err_code", ax, int(r))
                        ret_status.append("stopped")
                        ret_err_code.append(ErrorCodes.none)
                    else:
                        # self.update_wsmotorbuffersingle("motor_status", ax, "stopped")
                        # self.update_wsmotorbuffersingle("err_code", ax, int(r))
                        # stopped due to error/issue
                        ret_status.append("stopped")
                        ret_err_code.append(ErrorCodes.none)
                else:
                    ret_status.append("invalid")
                    ret_err_code.append(ErrorCodes.unspecified)

            else:
                ret_status.append("invalid")
                ret_err_code.append(ErrorCodes.not_available)

        msg = {"motor_status": ret_status, "err_code": ret_err_code}
        await self.update_aligner(msg=msg)
        return msg

    async def reset_controller(self):
        """Send the Galil `RS` reset command, restoring saved state and parameters.

        Renamed from the pre-migration `reset` (K1: the ABC's `reset()`
        lifecycle method has different semantics -- force-close/reopen the
        connection -- so this device-level emergency reset command keeps
        its own name). The `/reset` endpoint calls this method, not the ABC
        `reset()`.
        """
        if self.galil_enabled:
            return self.galilcmd("RS")
        else:
            return ""

    def _is_estopped(self) -> bool:
        """Read the server's estop flag via the safe base hook.

        Server-side estop-flag bookkeeping (`actionservermodel.estop`) is
        owned by the action-server framework (`base_api.py`'s `/estop`
        endpoint sets it directly), so this driver only reads it -- and only
        through `self._base_hook` (never a live `self.base`), defaulting to
        `False` if the hook isn't wired up yet.
        """
        asm = getattr(self._base_hook, "actionservermodel", None)
        return bool(getattr(asm, "estop", False))

    async def estop(self, switch: bool, *args, **kwargs) -> bool:
        """Engage the motion emergency stop.

        Args:
            switch: True stops every axis and disables its motor, False is
                a no-op (server-side estop-flag bookkeeping is owned by the
                action-server framework, not the driver -- see
                `base_api.py`'s `/estop` endpoint, which calls this hook
                and then sets `actionservermodel.estop` itself).

        Returns:
            The `switch` value passed in.
        """
        LOGGER.info("Axis Estop")
        if switch:
            await self.stop_axis(self.get_all_axis())
            await self.motor_off(self.get_all_axis())
        return switch

    async def stop_axis(self, axis) -> dict:
        """Halt motion on the listed axes without disabling their motors.

        Args:
            axis: Single axis name or list of axis names.

        Returns:
            Combined `query_axis_moving` and `query_axis_position` dict.
        """
        if self.galil_enabled:
            # convert single axis move to list
            if not isinstance(axis, list):
                axis = [axis]
            for ax in axis:
                if ax in self.axis_id:
                    axl = self.axis_id[ax]
                    self.galilcmd(f"ST{axl}")

        ret = await self.query_axis_moving(axis=axis)
        ret.update(await self.query_axis_position(axis=axis))
        return ret

    async def motor_off(self, axis, *args, **kwargs) -> dict:
        """Stop and disable (de-energize) the listed motors for manual alignment.

        Args:
            axis: Single axis name or list of axis names.

        Returns:
            Combined `query_axis_moving` and `query_axis_position` dict.
        """
        if self.galil_enabled:
            # convert single axis move to list
            if not isinstance(axis, list):
                axis = [axis]

            for ax in axis:

                if ax in self.axis_id:
                    axl = self.axis_id[ax]
                else:
                    continue

                cmd_seq = [f"ST{axl}", f"MO{axl}"]

                for cmd in cmd_seq:
                    _ = self.galilcmd(cmd)

        ret = await self.query_axis_moving(axis=axis)
        ret.update(await self.query_axis_position(axis=axis))
        return ret

    def motor_off_shutdown(self, axis, *args, **kwargs):
        """Synchronous variant of `motor_off` used from `shutdown`."""
        if self.galil_enabled:
            if not isinstance(axis, list):
                axis = [axis]

            for ax in axis:

                if ax in self.axis_id:
                    axl = self.axis_id[ax]
                else:
                    continue

                cmd_seq = [f"ST{axl}", f"MO{axl}"]

                for cmd in cmd_seq:
                    _ = self.galilcmd(cmd)

    async def motor_on(self, axis, *args, **kwargs) -> dict:
        """Re-enable (`SH`) the listed motors after a manual alignment.

        Args:
            axis: Single axis name or list of axis names.

        Returns:
            Combined `query_axis_moving` and `query_axis_position` dict.
        """
        if self.galil_enabled:
            # convert single axis move to list
            if not isinstance(axis, list):
                axis = [axis]

            for ax in axis:

                if ax in self.axis_id:
                    axl = self.axis_id[ax]
                else:
                    continue

                cmd = f"MG _MO{axl}"
                q = self.galilcmd(cmd)
                if float(q) == 1:
                    LOGGER.error(f"turning on motor for axis '{axl}' ")
                    cmd_seq = [f"ST{axl}", f"SH{axl}"]

                    for cmd in cmd_seq:
                        _ = self.galilcmd(cmd)
                else:
                    LOGGER.error(f"motor for axis '{axl}' is already on")

        ret = await self.query_axis_moving(axis=axis)
        ret.update(await self.query_axis_position(axis=axis))
        return ret

    def get_all_axis(self) -> list:
        """Return every configured axis name."""
        return [ax for ax in self.axis_id]

    def shutdown(self) -> set:
        """Close the gclib connection on server shutdown.

        The aligner IO-task cancellation moved to `GalilAlignerHost.shutdown`
        (P3a slice-4); the action server invokes it alongside this on the
        FastAPI shutdown path.

        Returns:
            A single-element set containing "shutdown".
        """
        LOGGER.info("shutting down galil motion")
        self.galil_enabled = False
        try:
            # LOGGER.info("turning all motors off")
            # self.motor_off_shutdown(axis = self.get_all_axis())
            self.g.GClose()
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(f"could not close galil connection: {repr(e), tb,}")
        return {"shutdown"}

    async def update_aligner(self, msg):
        """Forward `msg` to the aligner's motor-position queue, if one is wired.

        The sink is the Bokeh aligner's `motorpos_q`, registered by
        `GalilAlignerHost` via `set_position_sink` (P3a slice-4). `None` when
        no aligner is hosted, so this is a no-op then.
        """
        if self._position_sink is not None:
            await self._position_sink.put(msg)

    def save_transfermatrix(self, file):
        """Write `self.plate_transfermatrix` to `file` as JSON.

        Creates the parent directory if needed; silently returns when `file`
        is None.
        """
        if file is not None:
            filedir, filename = os.path.split(file)
            LOGGER.info(f"saving calib '{filename}' to '{filedir}'")
            if not os.path.exists(filedir):
                os.makedirs(filedir, exist_ok=True)

            with open(file, "w") as f:
                f.write(json.dumps(self.plate_transfermatrix.tolist()))

    def load_transfermatrix(self, file):
        """Read a JSON-encoded transformation matrix from `file`.

        Returns:
            A `np.matrix` of the same shape as `self.dflt_matrix`, or None
            if the file is missing, malformed, or has the wrong shape.
        """
        if os.path.exists(file):
            with open(file, "r") as f:
                try:
                    data = f.readline()
                    new_matrix = np.matrix(json.loads(data))
                    if new_matrix.shape != self.dflt_matrix.shape:
                        LOGGER.error(f"matrix \n'{new_matrix}' has wrong shape")
                        return None
                    else:
                        LOGGER.info(f"loaded matrix \n'{new_matrix}'")
                        return new_matrix

                except Exception as e:
                    tb = "".join(
                        traceback.format_exception(type(e), e, e.__traceback__)
                    )
                    LOGGER.error(f"error loading matrix for '{file}': {repr(e), tb,}")
                    return None
        else:
            LOGGER.error(f"matrix file '{file}' not found")
            return None

    def update_plate_transfermatrix(self, newtransfermatrix):
        """Replace the plate matrix, propagate to `TransformXY`, and persist to disk.

        Falls back to the default identity matrix if the new matrix has the
        wrong shape. Returns the matrix that was actually stored.
        """
        if newtransfermatrix.shape != self.dflt_matrix.shape:
            LOGGER.error(
                f"matrix \n'{newtransfermatrix}' has wrong shape, using dflt.",
                exc_info=True,
            )
            matrix = self.dflt_matrix
        else:
            matrix = newtransfermatrix
        self.plate_transfermatrix = matrix
        self.transform.update_Mplatexy(Mxy=self.plate_transfermatrix)
        self.save_transfermatrix(file=self.file_backup_transfermatrix)
        LOGGER.info(f"updated plate_transfermatrix is: \n{self.plate_transfermatrix}")
        return self.plate_transfermatrix

    def reset_plate_transfermatrix(self):
        """Restore the plate transformation matrix to the identity default."""
        self.update_plate_transfermatrix(newtransfermatrix=self.dflt_matrix)

    async def solid_get_platemap(self, unified_db, plate_id=None, **kwargs) -> dict:
        """Look up the platemap for a solid sample by plate ID via the unified DB.

        Args:
            unified_db: `UnifiedSampleDataAPI` instance owned by the action
                server (K7/sm: the sample DB is server/app-level state, not
                driver state -- see `galil_motion.py`'s `app.unified_db`).
            plate_id: Plate ID to look up.
        """
        return {
            "platemap": await unified_db.get_platemap([SolidSample(plate_id=plate_id)])
        }

    async def solid_get_samples_xy(
        self,
        unified_db,
        plate_id=None,
        sample_no=None,
        **kwargs,
    ) -> dict:
        """Resolve the plate-frame xy coordinates of a solid sample via the unified DB.

        Args:
            unified_db: `UnifiedSampleDataAPI` instance owned by the action
                server (K7/sm, see `solid_get_platemap`).
            plate_id: Plate ID of the sample.
            sample_no: Sample number on the plate.
        """
        return {
            "platexy": await unified_db.get_samples_xy(
                [SolidSample(plate_id=plate_id, sample_no=sample_no)]
            )
        }
