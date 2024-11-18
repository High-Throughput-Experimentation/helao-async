""" A device class for the Galil motion controller, used by a FastAPI server instance.

The 'galil' device class exposes motion and I/O functions from the underlying 'gclib'
library. Class methods are specific to Galil devices. Device configuration is read from
config/config.py. 

This driver requires gclib to be installed. After installation, activate the helao
environment and run:

`python "c:\Program Files (x86)\Galil\gclib\source\wrappers\python\setup.py" install`

to install the python module.

"""

__all__ = ["Galil", "MoveModes", "TransformationModes"]

import numpy as np
import time
import asyncio
from functools import partial
import json
import os
from socket import gethostname
from copy import deepcopy
import traceback


from bokeh.server.server import Server

from helao.helpers import logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER
    
from helao.servers.base import Base
from helao.core.error import ErrorCodes
from helao.helpers.premodels import Action
from helao.servers.vis import HelaoVis
from helao.helpers.sample_api import UnifiedSampleDataAPI
from helao.helpers.active_params import ActiveParams
from helao.core.models.file import FileConnParams
from helao.core.models.sample import SolidSample

from helao.layouts.aligner import Aligner
from helao.drivers.motion.enum import MoveModes, TransformationModes

# install galil driver first
# (helao) c:\Program Files (x86)\Galil\gclib\source\wrappers\python>python setup.py install
import gclib


class cmd_exception(ValueError):
    def __init__(self, arg):
        self.args = arg


class Galil:
    def __init__(self, action_serv: Base):

        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.unified_db = UnifiedSampleDataAPI(self.base)

        self.dflt_matrix = np.matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])

        self.file_backup_transfermatrix = None
        if self.base.helaodirs.states_root is not None:
            self.file_backup_transfermatrix = os.path.join(
                self.base.helaodirs.states_root,
                f"{gethostname().lower()}_last_plate_calib.json",
            )

        self.plate_transfermatrix = self.load_transfermatrix(
            file=self.file_backup_transfermatrix
        )
        if self.plate_transfermatrix is None:
            self.plate_transfermatrix = self.dflt_matrix

        self.save_transfermatrix(file=self.file_backup_transfermatrix)
        LOGGER.info(f"plate_transfermatrix is: \n{self.plate_transfermatrix}")

        self.M_instr = None
        Mplate = self.load_transfermatrix(
            file=os.path.join(
                self.base.helaodirs.db_root,
                "plate_calib",
                f"{gethostname().lower()}_instrument_calib.json",
            )
        )

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

        self.motor_timeout = self.config_dict.get("timeout", 60)
        self.motor_max_speed_count_sec = self.config_dict.get(
            "max_speed_count_sec", 25000
        )
        self.motor_def_speed_count_sec = self.config_dict.get(
            "def_speed_count_sec", 10000
        )

        # need to check if config settings exist
        # else need to create empty ones
        self.axis_id = self.config_dict.get("axis_id",{})

        # Mplatexy is identity matrix by default
        self.transform = TransformXY(self.base, self.M_instr, self.axis_id)
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
                self.base.print_message(self.g.GInfo())
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
        except Exception as e:
            tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            self.base.print_message(
                f"severe Galil error ... "
                f"please power cycle Galil and try again: "
                f"{repr(e), tb,}",
                error=True,
            )
            self.galil_enabled = False

        # block gamry
        self.blocked = False
        # is motor move busy?
        self.motor_busy = False
        self.bokehapp = None
        self.aligner = None
        self.aligning_enabled = False
        self.aligner_plateid = None
        self.aligner_active = None
        self.aligner_enabled = self.base.server_params.get("enable_aligner", False)
        if self.aligner_enabled and self.galil_enabled:
            self.start_aligner()

    def convert_Mplate_to_Minstr(self, Mplate):
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

    def start_aligner(self):
        servHost = self.base.server_cfg["host"]
        servPort = self.base.server_params.get(
            "bokeh_port", self.base.server_cfg["port"] + 1000
        )
        servPy = "Aligner"

        self.bokehapp = Server(
            {f"/{servPy}": partial(self.makeBokehApp, motor=self)},
            port=servPort,
            address=servHost,
            allow_websocket_origin=[f"{servHost}:{servPort}"],
        )
        LOGGER.info(f"started bokeh server {self.bokehapp}")
        self.bokehapp.start()
        # self.bokehapp.io_loop.add_callback(self.bokehapp.show, f"/{servPy}")

    def makeBokehApp(self, doc, motor):
        app = HelaoVis(
            config=self.base.world_cfg,
            server_key=self.base.server.server_name,
            doc=doc,
        )

        doc.aligner = Aligner(app.vis, motor)
        return doc

    async def setaxisref(self):
        # home all axis first
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

    async def stop_aligner(self) -> ErrorCodes:
        if self.aligner_enabled and self.aligner:
            self.aligner.stop_align()
            return ErrorCodes.none
        else:
            return ErrorCodes.not_available

    async def run_aligner(self, A: Action):
        if not self.blocked and self.galil_enabled:
            if not self.aligner_enabled or not self.aligner:
                A.error_code = ErrorCodes.not_available
                activeDict = A.as_dict()
            else:
                self.blocked = True
                self.aligner_plateid = A.action_params["plateid"]
                # A.error_code = ErrorCodes.none
                self.aligner_active = await self.base.contain_action(
                    ActiveParams(
                        action=A,
                        file_conn_params_dict={
                            self.base.dflt_file_conn_key(): FileConnParams(
                                # use dflt file conn key for first
                                # init
                                file_conn_key=self.base.dflt_file_conn_key(),
                                sample_global_labels=[],
                                file_type="aligner_helao__file",
                                # hloheader = HloHeaderModel(
                                #     optional = None
                                # ),
                            )
                        },
                    )
                )
                self.aligning_enabled = True
                activeDict = self.aligner_active.action.as_dict()

                _ = await self.query_axis_moving(axis=self.get_all_axis())

        else:
            A.error_code = ErrorCodes.in_progress
            activeDict = A.as_dict()
        return activeDict

    async def motor_move(self, active):
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

    async def _motor_move(self, d_mm, axis, speed, mode, transformation):
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

        error = ErrorCodes.none

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
            LOGGER.info(f"current instrument position (calc from motor): {current_instrxyz}")
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

        if self.base.actionservermodel.estop:
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
                self.base.print_message(
                    f"motor setup error: '{ax}' is not in '{self.axis_id}'",
                    error=True,
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
                LOGGER.info(f"count_to_mm: {axl}, {self.config_dict['count_to_mm'][axl]}")
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
            except Exception as e:
                tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                LOGGER.error(f"motor numerical error for axis '{ax}': {repr(e), tb,}")
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
            except Exception as e:
                tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                LOGGER.error(f"motor error: '", exc_info=True)
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
                tmax > 30 * 60  # 30min hard limit
        else:
            tmax = 0

        # wait for expected axis move time before checking if axis stoppped
        LOGGER.info(f"axis expected to stop in {tmax} sec")

        if not self.base.actionservermodel.estop:

            # check if all axis stopped
            tstart = time.time()

            while (
                time.time() - tstart < self.motor_timeout
            ) and not self.base.actionservermodel.estop:
                qmove = await self.query_axis_moving(axis=axis)
                await asyncio.sleep(0.5)
                if all(status == "stopped" for status in qmove["motor_status"]):
                    break

            if not self.base.actionservermodel.estop:
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

    async def motor_disconnect(self):
        try:
            self.g.GClose()  # don't forget to close connections!
        except gclib.GclibError as e:
            tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            return {"connection": {"Unexpected GclibError:", e}}
        return {"connection": "motor_offline"}

    async def query_axis_position(self, axis, *args, **kwargs):
        # this only queries the position of a single axis
        # server example:
        # http://127.0.0.1:8000/motor/query/position?axis=x
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

    async def query_axis_moving(self, axis, *args, **kwargs):
        # this functions queries the status of the axis
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
                pass

        msg = {"motor_status": ret_status, "err_code": ret_err_code}
        await self.update_aligner(msg=msg)
        return msg

    async def reset(self):
        # The RS command resets the state of the actionor to its power-on condition.
        # The previously saved state of the controller,
        # along with parameter values, and saved experiments are restored.
        if self.galil_enabled:
            return self.galilcmd("RS")
        else:
            return ""

    async def estop(self, switch: bool, *args, **kwargs):
        # this will estop the axis
        # set estop: switch=true
        # release estop: switch=false
        LOGGER.info("Axis Estop")
        if switch == True:
            await self.stop_axis(self.get_all_axis())
            await self.motor_off(self.get_all_axis())
            # set flag (move command need to check for it)
            self.base.actionservermodel.estop = True
        else:
            # need only to set the flag
            self.base.actionservermodel.estop = False
        return switch

    async def stop_axis(self, axis):
        # this will stop the current motion of the axis
        # but not turn off the motor
        # for stopping and turnuing off use moto_off

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

    async def motor_off(self, axis, *args, **kwargs):

        # sometimes it is useful to turn the motors off for manual alignment
        # this function does exactly that
        # It then returns the status
        # and the current position of all motors

        # an example would be:
        # http://127.0.0.1:8000/motor/stop
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

    async def motor_on(self, axis, *args, **kwargs):
        # sometimes it is useful to turn the motors back on for manual alignment
        # this function does exactly that
        # It then returns the status
        # and the current position of all motors
        # server example
        # http://127.0.0.1:8000/motor/on?axis=x

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

    def get_all_axis(self):
        return [ax for ax in self.axis_id]

    def shutdown(self):
        # this gets called when the server is shut down
        # or reloaded to ensure a clean
        # disconnect ... just restart or terminate the server
        # self.stop_axis(self.get_all_axis())
        LOGGER.info("shutting down galil motion")
        self.galil_enabled = False
        try:
            # LOGGER.info("turning all motors off")
            # self.motor_off_shutdown(axis = self.get_all_axis())
            self.g.GClose()
        except Exception as e:
            tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(f"could not close galil connection: {repr(e), tb,}")
        if self.aligner_enabled and self.aligner:
            self.aligner.IOtask.cancel()
        return {"shutdown"}

    async def update_aligner(self, msg):
        if self.aligner_enabled and self.aligner:
            await self.aligner.motorpos_q.put(msg)

    def save_transfermatrix(self, file):
        if file is not None:
            filedir, filename = os.path.split(file)
            LOGGER.info(f"saving calib '{filename}' to '{filedir}'")
            if not os.path.exists(filedir):
                os.makedirs(filedir, exist_ok=True)

            with open(file, "w") as f:
                f.write(json.dumps(self.plate_transfermatrix.tolist()))

    def load_transfermatrix(self, file):
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
                    tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                    LOGGER.error(f"error loading matrix for '{file}': {repr(e), tb,}")
                    return None
        else:
            LOGGER.error(f"matrix file '{file}' not found")
            return None

    def update_plate_transfermatrix(self, newtransfermatrix):
        if newtransfermatrix.shape != self.dflt_matrix.shape:
            self.base.print_message(
                f"matrix \n'{newtransfermatrix}' has wrong shape, using dflt.",
                error=True,
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
        self.update_plate_transfermatrix(newtransfermatrix=self.dflt_matrix)

    async def solid_get_platemap(self, plate_id: int = None, **kwargs) -> dict:
        return {
            "platemap": await self.unified_db.get_platemap(
                [SolidSample(plate_id=plate_id)]
            )
        }

    async def solid_get_samples_xy(
        self,
        plate_id: int = None,
        sample_no: int = None,
        **kwargs,
    ) -> dict:
        return {
            "platexy": await self.unified_db.get_samples_xy(
                [SolidSample(plate_id=plate_id, sample_no=sample_no)]
            )
        }


class TransformXY:
    # Updating plate calibration will automatically update the system transformation
    # matrix. When angles are changed updated them also here and run update_Msystem
    def __init__(self, action_serv: Base, Minstr, seq=None):
        self.base = action_serv
        # instrument specific matrix
        # motor to instrument
        self.Minstrxyz = np.asmatrix(Minstr)  # np.asmatrix(np.identity(4))
        self.Minstr = np.asmatrix(np.identity(4))
        self.Minstrinv = np.asmatrix(np.identity(4))
        # plate Matrix
        # instrument to plate
        self.Mplate = np.asmatrix(np.identity(4))
        self.Mplatexy = np.asmatrix(np.identity(3))
        # system Matrix
        # motor to plate
        self.M = np.asmatrix(np.identity(4))
        self.Minv = np.asmatrix(np.identity(4))
        # need to update the angles here each time the axis is rotated
        self.alpha = 0
        self.beta = 0
        self.gamma = 0
        self.seq = seq

        # pre calculates the system Matrix M
        self.update_Msystem()

    def transform_platexy_to_motorxy(self, platexy, *args, **kwargs):
        """simply calculates motorxy based on platexy
        plate warping (z) will be a different call"""
        if isinstance(platexy, str):
            platexy = [float(x.strip()) for x in platexy.split(",")]
        platexy = np.asarray(platexy)
        if len(platexy) == 2:
            platexy = np.insert(platexy, 2, 1)
        if len(platexy) == 3:
            platexy = np.insert(platexy, 2, 0)
        # for _ in range(4-len(platexy)):
        #     platexy = np.append(platexy,1)
        # LOGGER.info(" ... M:\n")
        # LOGGER.info(" ... xy:")
        motorxy = np.dot(self.M, platexy)
        motorxy = np.delete(motorxy, 2)
        motorxy = np.array(motorxy)[0]
        return motorxy

    def transform_motorxy_to_platexy(self, motorxy, *args, **kwargs):
        """simply calculates platexy from current motorxy"""
        if isinstance(motorxy, str):
            motorxy = [float(x.strip()) for x in motorxy.split(",")]
        motorxy = np.asarray(motorxy)
        print(motorxy)
        if len(motorxy) == 2:
            motorxy = np.insert(motorxy, 2, 1)
        if len(motorxy) == 3:
            motorxy = np.insert(motorxy, 2, 0)
        # LOGGER.info(" ... Minv:\n")
        # LOGGER.info(" ... xy:")
        platexy = np.dot(self.Minv, motorxy)
        platexy = np.delete(platexy, 2)
        platexy = np.array(platexy)[0]
        return platexy

    def transform_motorxyz_to_instrxyz(self, motorxyz, *args, **kwargs):
        """simply calculatesinstrxyz from current motorxyz"""
        motorxyz = np.asarray(motorxyz)
        if len(motorxyz) == 3:
            # append 1 at end
            motorxyz = np.append(motorxyz, 1)
        # LOGGER.info(" ... Minstrinv:\n")
        # LOGGER.info(" ... xyz:")
        instrxyz = np.dot(self.Minstrinv, motorxyz)
        return np.array(instrxyz)[0]

    def transform_instrxyz_to_motorxyz(self, instrxyz, *args, **kwargs):
        """simply calculates motorxyz from current instrxyz"""
        instrxyz = np.asarray(instrxyz)
        if len(instrxyz) == 3:
            instrxyz = np.append(instrxyz, 1)
        # LOGGER.info(" ... Minstr:\n")
        # LOGGER.info(" ... xyz:")

        motorxyz = np.dot(self.Minstr, instrxyz)
        return np.array(motorxyz)[0]

    def Rx(self):
        """returns rotation matrix around x-axis"""
        alphatmp = np.mod(self.alpha, 360)  # this actually takes care of neg. values
        # precalculate some common angles for better accuracy and speed
        if alphatmp == 0:  # or alphatmp == -0.0:
            return np.asmatrix(np.identity(4))
        elif alphatmp == 90:  # or alphatmp == -270:
            return np.matrix([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]])
        elif alphatmp == 180:  # or alphatmp == -180:
            return np.matrix([[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, 0], [0, 0, 0, 1]])
        elif alphatmp == 270:  # or alphatmp == -90:
            return np.matrix([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]])
        else:
            return np.matrix(
                [
                    [1, 0, 0, 0],
                    [
                        0,
                        np.cos(np.pi / 180 * alphatmp),
                        -1.0 * np.sin(np.pi / 180 * alphatmp),
                        0,
                    ],
                    [
                        0,
                        np.sin(np.pi / 180 * alphatmp),
                        np.cos(np.pi / 180 * alphatmp),
                        0,
                    ],
                    [0, 0, 0, 1],
                ]
            )

    def Ry(self):
        """returns rotation matrix around y-axis"""
        betatmp = np.mod(self.beta, 360)  # this actually takes care of neg. values
        # precalculate some common angles for better accuracy and speed
        if betatmp == 0:  # or betatmp == -0.0:
            return np.asmatrix(np.identity(4))
        elif betatmp == 90:  # or betatmp == -270:
            return np.matrix([[0, 0, 1, 0], [0, 1, 0, 0], [-1, 0, 0, 0], [0, 0, 0, 1]])
        elif betatmp == 180:  # or betatmp == -180:
            return np.matrix([[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, -1, 0], [0, 0, 0, 1]])
        elif betatmp == 270:  # or betatmp == -90:
            return np.matrix([[0, 0, -1, 0], [0, 1, 0, 0], [1, 0, 0, 0], [0, 0, 0, 1]])
        else:
            return np.matrix(
                [
                    [
                        np.cos(np.pi / 180 * self.beta),
                        0,
                        np.sin(np.pi / 180 * self.beta),
                        0,
                    ],
                    [0, 1, 0, 0],
                    [
                        -1.0 * np.sin(np.pi / 180 * self.beta),
                        0,
                        np.cos(np.pi / 180 * self.beta),
                        0,
                    ],
                    [0, 0, 0, 1],
                ]
            )

    def Rz(self):
        """returns rotation matrix around z-axis"""
        gammatmp = np.mod(self.gamma, 360)  # this actually takes care of neg. values
        # precalculate some common angles for better accuracy and speed
        if gammatmp == 0:  # or gammatmp == -0.0:
            return np.asmatrix(np.identity(4))
        elif gammatmp == 90:  # or gammatmp == -270:
            return np.matrix([[0, -1, 0, 0], [1, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        elif gammatmp == 180:  # or gammatmp == -180:
            return np.matrix([[-1, 0, 0, 0], [0, -1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        elif gammatmp == 270:  # or gammatmp == -90:
            return np.matrix([[0, 1, 0, 0], [-1, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        else:
            return np.matrix(
                [
                    [
                        np.cos(np.pi / 180 * gammatmp),
                        -1.0 * np.sin(np.pi / 180 * gammatmp),
                        0,
                        0,
                    ],
                    [
                        np.sin(np.pi / 180 * gammatmp),
                        np.cos(np.pi / 180 * gammatmp),
                        0,
                        0,
                    ],
                    [0, 0, 1, 0],
                    [0, 0, 0, 1],
                ]
            )

    def Mx(self):
        """returns Mx part of Minstr"""
        Mx = np.asmatrix(np.identity(4))
        Mx[0, 0:4] = self.Minstrxyz[0, 0:4]
        # LOGGER.info(" ... Mx")
        return Mx

    def My(self):
        """returns My part of Minstr"""
        My = np.asmatrix(np.identity(4))
        My[1, 0:4] = self.Minstrxyz[1, 0:4]
        # LOGGER.info(" ... My")
        return My

    def Mz(self):
        """returns Mz part of Minstr"""
        Mz = np.asmatrix(np.identity(4))
        Mz[2, 0:4] = self.Minstrxyz[2, 0:4]
        # LOGGER.info(" ... Mz")
        return Mz

    def Mplatewarp(self, platexy):
        """returns plate warp correction matrix (Z-correction.
        Only valid for a single platexy coordinate"""
        return np.asmatrix(np.identity(4))  # TODO, just returns identity matrix for now

    def update_Msystem(self):
        """updates the transformation matrix for new plate calibration or
        when angles are changed.
        Follows stacking experiment from bottom to top (plate)"""

        LOGGER.info("updating M")

        if self.seq is None:
            LOGGER.info("seq is empty, using default transformation")
            # default case, we simply have xy calibration
            self.M = np.dot(self.Minstrxyz, self.Mplate)
        else:
            self.Minstr = np.asmatrix(np.identity(4))
            # more complicated
            # check for some common experiments:
            Mcommon1 = (
                False  # to check against when common combinations are already found
            )
            axstr = ""
            for ax in self.seq:
                axstr += ax
            # check for xyz or xy (with no z)
            # experiment does not matter so should define it like this in the config
            # if we want to use this
            if axstr.find("xy") == 0 and axstr.find("z") <= 2:
                LOGGER.info("got xyz seq")
                self.Minstr = self.Minstrxyz
                Mcommon1 = True

            for ax in self.seq:
                if ax == "x" and not Mcommon1:
                    LOGGER.info("got x seq")
                    self.Minstr = np.dot(self.Minstr, self.Mx())
                elif ax == "y" and not Mcommon1:
                    LOGGER.info("got y seq")
                    self.Minstr = np.dot(self.Minstr, self.My())
                elif ax == "z" and not Mcommon1:
                    LOGGER.info("got z seq")
                    self.Minstr = np.dot(self.Minstr, self.Mz())
                elif ax == "Rx":
                    LOGGER.info("got Rx seq")
                    self.Minstr = np.dot(self.Minstr, self.Rx())
                elif ax == "Ry":
                    LOGGER.info("got Ry seq")
                    self.Minstr = np.dot(self.Minstr, self.Ry())
                elif ax == "Rz":
                    LOGGER.info("got Rz seq")
                    self.Minstr = np.dot(self.Minstr, self.Rz())

            self.M = np.dot(self.Minstr, self.Mplate)

            # precalculate the inverse as we also need it a lot
            try:
                self.Minv = self.M.I
            except Exception as e:
                tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                LOGGER.error(f"System Matrix singular ", exc_info=True)
                # use the -1 to signal inverse later --> platexy will then be [x,y,-1]
                self.Minv = np.matrix(
                    [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, -1]]
                )

            try:
                self.Minstrinv = self.Minstr.I
            except Exception as e:
                tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                LOGGER.error(f"Instrument Matrix singular ", exc_info=True)
                # use the -1 to signal inverse later --> platexy will then be [x,y,-1]
                self.Minstrinv = np.matrix(
                    [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, -1]]
                )

    def update_Mplatexy(self, Mxy, *args, **kwargs):
        """updates the xy part of the plate calibration"""
        Mxy = np.matrix(Mxy)
        # assign the xy part
        self.Mplate[0:2, 0:2] = Mxy[0:2, 0:2]
        # assign the last row (offsets), notice the difference in col (3x3 vs 4x4)
        #        self.Mplate[0:2,3] = Mxy[0:2,2] # something does not work with this one is a 1x2 the other 2x1 for some reason
        self.Mplate[0, 3] = Mxy[0, 2]
        self.Mplate[1, 3] = Mxy[1, 2]
        # self.Mplate[3,0:4] should always be 0,0,0,1 and should never change

        # update the system matrix so we save calculation time later
        self.update_Msystem()
        return True

    def get_Mplatexy(self):
        """returns the xy part of the platecalibration"""
        self.Mplatexy = np.asmatrix(np.identity(3))
        self.Mplatexy[0:2, 0:2] = self.Mplate[0:2, 0:2]
        self.Mplatexy[0, 2] = self.Mplate[0, 3]
        self.Mplatexy[1, 2] = self.Mplate[1, 3]
        return self.Mplatexy

    def get_Mplate_Msystem(self, Mxy, *args, **kwargs):
        """removes Minstr from Msystem to obtain Mplate for alignment"""
        Mxy = np.asarray(Mxy)
        Mglobal = np.asmatrix(np.identity(4))
        Mglobal[0:2, 0:2] = Mxy[0:2, 0:2]
        Mglobal[0, 3] = Mxy[0, 2]
        Mglobal[1, 3] = Mxy[1, 2]

        try:
            Minstrinv = self.Minstr.I
            Mtmp = np.dot(Minstrinv, Mglobal)
            self.Mplatexy = np.asmatrix(np.identity(3))
            self.Mplatexy[0:2, 0:2] = Mtmp[0:2, 0:2]
            self.Mplatexy[0, 2] = Mtmp[0, 3]
            self.Mplatexy[1, 2] = Mtmp[1, 3]

            return self.Mplatexy
        except Exception as e:
            tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(f"Instrument Matrix singular ", exc_info=True)
            # use the -1 to signal inverse later --> platexy will then be [x,y,-1]
            self.Minv = np.matrix([[0, 0, 0], [0, 0, 0], [0, 0, -1]])
