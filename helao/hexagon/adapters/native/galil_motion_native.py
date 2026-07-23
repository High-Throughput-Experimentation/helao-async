"""Native Galil motion driver over the command-channel port (P3a galil-3, native-1).

Unlike the slice-3 ``GalilMotionHardwareAdapter`` (which delegated every call to
the legacy ``Galil``), ``NativeGalilMotion`` OWNS the motion logic: it issues
Galil command strings through a
:class:`~helao.hexagon.ports.galil_command_channel.GalilCommandChannel` and does
the coordinate/parse math itself, reusing the slice-1 ``TransformXY`` and slice-2
``JsonFileCalibrationStore``. Because the only vendor seam is the channel, the
command generation + TP/PA/SC parsing are unit-testable on Linux with a fake
channel; only the real gclib I/O is at-station.

native-1 implemented connect/lifecycle, the simple command verbs
(stop/motor_off/motor_on/reset_controller/estop) and the position/status
queries. native-2 added ``_motor_move`` (coordinate-transform move
orchestration: motor/plate/instr frames × relative/absolute/homing, speed
clamp, ``SP``/``PR|PA|HM``/``BG`` sequence, settle-poll) and ``setaxisref``
(homing). native-3 completes the full galil-server surface so this can be the
sole ``app.driver``: it is now a ``HelaoDriver`` (with ``stop``/``reset``) and
adds the public ``motor_move(active)``, ``motor_disconnect``, calibration-matrix
management (``save``/``load``/``update``/``reset_plate_transfermatrix``) and the
``solid_get_platemap``/``solid_get_samples_xy`` platemap lookups. All faithfully
ported from the legacy driver. gclib I/O + at-station validation are the gate.
"""

import asyncio
import json
import os
import time
import traceback
from copy import deepcopy
from socket import gethostname
from typing import Any, List, Optional

import numpy as np

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)
from helao.core.error import ErrorCodes
from helao.core.models.sample import SolidSample
from helao.deploy.hte.drivers.motion.enum import MoveModes, TransformationModes
from helao.hexagon.adapters.legacy.calibration_store import JsonFileCalibrationStore
from helao.hexagon.domain.motion_transform import TransformXY
from helao.hexagon.ports.galil_command_channel import (
    GalilChannelError,
    GalilCommandChannel,
)

__all__ = ["NativeGalilMotion"]

_AXIS_LETTERS = "ABCDEFGH"
# Per-axis init register writes, verbatim from the legacy connect() sequence.
_AXIS_INIT = [("MT", 2), ("CE", 4), ("TW", 32000), ("SD", 256000)]


class NativeGalilMotion(HelaoDriver):
    """Galil motion driver implemented directly over a GalilCommandChannel.

    A ``HelaoDriver`` so the action server can construct it via
    ``driver_classes=[NativeGalilMotion]`` (BaseAPI calls ``(config=...)``); the
    command channel defaults to the real gclib-backed channel when none is
    injected (tests inject a fake).
    """

    def __init__(
        self,
        config: Optional[dict] = None,
        *,
        channel: Optional[GalilCommandChannel] = None,
        base_hook: Any = None,
        position_sink: Any = None,
    ):
        # Disconnected construct: no channel.open(), no gclib, no I/O here.
        super().__init__(config=config or {})
        self.config_dict = self.config
        if channel is None:
            # production default: the at-station gclib channel (lazy import so
            # this module still imports/constructs on Linux without gclib).
            from helao.hexagon.adapters.legacy.galil_command_channel import (
                GclibCommandChannel,
            )

            channel = GclibCommandChannel()
        self._channel: GalilCommandChannel = channel
        self._base_hook = base_hook
        # Optional aligner position-notify queue (object with async `put`);
        # preserves the legacy query -> update_aligner feed. None = no feed.
        self._position_sink = position_sink

        self.axis_id = self.config_dict.get("axis_id", {})
        self.dflt_matrix = np.matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        # aligner reads plate_transfermatrix; set to loaded/default in connect().
        self.plate_transfermatrix = self.dflt_matrix
        self.file_backup_transfermatrix: Optional[str] = None
        self.transform: Optional[TransformXY] = None
        self.galil_enabled: Optional[bool] = None
        self.motor_busy = False
        # aligner/motion compat lock (delegated by AlignerMotorContext); the
        # current _motor_move guards on motor_busy, not this.
        self.blocked = False

        self.motor_timeout = self.config_dict.get("timeout", 60)
        self.motor_max_speed_count_sec = self.config_dict.get(
            "max_speed_count_sec", 25000
        )
        self.motor_def_speed_count_sec = self.config_dict.get(
            "def_speed_count_sec", 10000
        )
        self._speed = self.motor_def_speed_count_sec

    def set_position_sink(self, sink: Any) -> None:
        self._position_sink = sink

    def get_all_axis(self) -> List[str]:
        return [ax for ax in self.axis_id]

    def _is_estopped(self) -> bool:
        """Read the server estop flag via the base hook (legacy parity)."""
        asm = getattr(self._base_hook, "actionservermodel", None)
        return bool(getattr(asm, "estop", False))

    # --- lifecycle --------------------------------------------------------
    def connect(self) -> DriverResponse:
        """Open the channel, run the axis-init sequence, and build the transform.

        Byte-identical command sequence to the legacy ``connect()``: ``PF 10.4``
        then, per configured axis letter, ``MG _MO<axl>`` -> ``SH<axl>`` if the
        motor is off, then the ``MT/CE/TW/SD`` register writes.
        """
        try:
            self._build_transform()
            galil_ip = self.config_dict.get("galil_ip_str", None)
            if not galil_ip:
                self.galil_enabled = False
                return DriverResponse(
                    response=DriverResponseType.success,
                    status=DriverStatus.uninitialized,
                )
            self._channel.open(f"{galil_ip} --direct -s ALL")
            self._channel.command("PF 10.4")
            for axl in self.axis_id.values():
                q = self._channel.command(f"MG _MO{axl}")
                if float(q) == 1:
                    self._channel.command(f"SH{axl}")
                for ac, av in _AXIS_INIT:
                    self._channel.command(f"{ac}{axl}={av}")
            self.galil_enabled = True
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except (GalilChannelError, Exception):
            self.galil_enabled = False
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )

    def _build_transform(self) -> None:
        """Load plate + instrument calibration and construct ``TransformXY``.

        Mirrors legacy connect(): plate matrix from
        ``<states_root>/<host>_last_plate_calib.json`` (default identity),
        instrument matrix from ``<db_root>/plate_calib/<host>_instrument_calib``
        or the config ``M_instr`` fallback.
        """
        helaodirs = getattr(self._base_hook, "helaodirs", None)
        states_root = getattr(helaodirs, "states_root", None)
        # legacy backup path used by update_plate_transfermatrix/save_transfermatrix
        self.file_backup_transfermatrix = (
            os.path.join(states_root, f"{gethostname().lower()}_last_plate_calib.json")
            if states_root is not None
            else None
        )
        store = JsonFileCalibrationStore(
            states_root=states_root,
            db_root=getattr(helaodirs, "db_root", None),
            hostname=gethostname().lower(),
        )
        plate = None
        if helaodirs is not None:
            plate = store.load_plate_calibration()
        if plate is None:
            plate = self.dflt_matrix
        store.save_plate_calibration(plate)
        self.plate_transfermatrix = plate

        m_instr = None
        if helaodirs is not None:
            mplate = store.load_instrument_calibration()
            if mplate is not None:
                m_instr = self._convert_mplate_to_minstr(mplate.tolist())
        if m_instr is None:
            m_instr = self.config_dict.get(
                "M_instr",
                [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            )
        self.transform = TransformXY(m_instr, self.axis_id)
        self.transform.update_Mplatexy(Mxy=plate)

    @staticmethod
    def _convert_mplate_to_minstr(mplate) -> list:
        """Embed a 3x3 plate matrix into a 4x4 instrument matrix (legacy parity)."""
        minstr = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        minstr[0][0:2] = mplate[0][0:2]
        minstr[1][0:2] = mplate[1][0:2]
        minstr[0][3] = mplate[0][2]
        minstr[1][3] = mplate[1][2]
        return minstr

    def get_status(self) -> DriverResponse:
        if not self.galil_enabled:
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.uninitialized
            )
        return DriverResponse(
            response=DriverResponseType.success,
            status=DriverStatus.busy if self.motor_busy else DriverStatus.ok,
        )

    def disconnect(self) -> DriverResponse:
        self.galil_enabled = False
        self._channel.close()
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    def shutdown(self) -> set:
        self.galil_enabled = False
        self._channel.close()
        return {"shutdown"}

    async def stop(self) -> DriverResponse:
        """HelaoDriver ABC: abort motion on every axis (device stays enabled)."""
        try:
            await self.stop_axis(self.get_all_axis())
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )

    def reset(self) -> DriverResponse:
        """HelaoDriver ABC: force-close and reopen the connection."""
        self.disconnect()
        return self.connect()

    # --- queries (pure parse over the channel) ----------------------------
    async def query_axis_position(self, axis, *args, **kwargs) -> dict:
        """Query absolute positions in motor mm (legacy TP->PA->scale/map)."""
        if not self.galil_enabled:
            return {"ax": [], "position": []}
        if not isinstance(axis, list):
            axis = [axis]
        q_tp = self._channel.command("TP")
        cmd = "PA " + ",".join("?" for _ in range(len(q_tp.split(","))))
        q = self._channel.command(cmd)
        axlett = _AXIS_LETTERS[0 : len(q.split(","))]
        inv_axis_id = {d: v for v, d in self.axis_id.items()}
        ax_abc_to_xyz = {l: inv_axis_id[l] for l in axlett if l in inv_axis_id}
        count_to_mm = self.config_dict.get("count_to_mm", {})
        pos = {
            axl: float(r) * count_to_mm.get(axl, 0)
            for axl, r in zip(axlett, q.split(", "))
        }
        axpos = {ax_abc_to_xyz.get(k, None): p for k, p in pos.items()}
        ret_ax: list = []
        ret_position: list = []
        for ax in axis:
            if ax in axpos:
                ret_ax.append(ax)
                ret_position.append(axpos[ax])
            else:
                ret_ax.append(None)
                ret_position.append(None)
        await self._notify(
            {
                "ax": list(axpos.keys()),
                "position": list(axpos.values()),
            }
        )
        return {"ax": ret_ax, "position": ret_position}

    async def query_axis_moving(self, axis, *args, **kwargs) -> dict:
        """Classify each axis moving/stopped from the ``SC`` stop-code register."""
        if not self.galil_enabled:
            return {"motor_status": [], "err_code": ErrorCodes.not_available}
        q = self._channel.command("SC")
        axlett = _AXIS_LETTERS[0 : len(q.split(","))]
        if not isinstance(axis, list):
            axis = [axis]
        ret_status: list = []
        ret_err_code: list = []
        qdict = dict(zip(axlett, q.split(", ")))
        for ax in axis:
            if ax in self.axis_id:
                axl = self.axis_id.get(ax, None)
                if axl in qdict:
                    r = qdict[axl]
                    # legacy: 0 -> "moving", 1 -> "stopped", else -> "stopped";
                    # err_code none in all three branches.
                    ret_status.append("moving" if int(r) == 0 else "stopped")
                    ret_err_code.append(ErrorCodes.none)
                else:
                    ret_status.append("invalid")
                    ret_err_code.append(ErrorCodes.unspecified)
            else:
                ret_status.append("invalid")
                ret_err_code.append(ErrorCodes.not_available)
        msg = {"motor_status": ret_status, "err_code": ret_err_code}
        await self._notify(msg)
        return msg

    # --- simple command verbs ---------------------------------------------
    async def stop_axis(self, axis) -> dict:
        """Halt the listed axes (``ST``) without disabling motors."""
        if self.galil_enabled:
            if not isinstance(axis, list):
                axis = [axis]
            for ax in axis:
                if ax in self.axis_id:
                    self._channel.command(f"ST{self.axis_id[ax]}")
        ret = await self.query_axis_moving(axis=axis)
        ret.update(await self.query_axis_position(axis=axis))
        return ret

    async def motor_off(self, axis, *args, **kwargs) -> dict:
        """Stop + de-energize (``ST`` then ``MO``) the listed motors."""
        if self.galil_enabled:
            if not isinstance(axis, list):
                axis = [axis]
            for ax in axis:
                if ax not in self.axis_id:
                    continue
                axl = self.axis_id[ax]
                for cmd in (f"ST{axl}", f"MO{axl}"):
                    self._channel.command(cmd)
        ret = await self.query_axis_moving(axis=axis)
        ret.update(await self.query_axis_position(axis=axis))
        return ret

    async def motor_on(self, axis, *args, **kwargs) -> dict:
        """Re-enable (``SH``) the listed motors if currently off."""
        if self.galil_enabled:
            if not isinstance(axis, list):
                axis = [axis]
            for ax in axis:
                if ax not in self.axis_id:
                    continue
                axl = self.axis_id[ax]
                q = self._channel.command(f"MG _MO{axl}")
                if float(q) == 1:
                    for cmd in (f"ST{axl}", f"SH{axl}"):
                        self._channel.command(cmd)
        ret = await self.query_axis_moving(axis=axis)
        ret.update(await self.query_axis_position(axis=axis))
        return ret

    async def reset_controller(self):
        """Send the Galil ``RS`` reset command (device-level emergency reset)."""
        if self.galil_enabled:
            return self._channel.command("RS")
        return ""

    async def estop(self, switch: bool, *args, **kwargs) -> bool:
        """Engage the motion e-stop: stop + de-energize every axis."""
        if switch:
            await self.stop_axis(self.get_all_axis())
            await self.motor_off(self.get_all_axis())
        return switch

    # --- coordinate-transform move orchestration (native-2) ---------------
    async def _motor_move(self, d_mm, axis, speed, mode, transformation) -> dict:
        """Transform coordinates, issue the per-axis move sequence, settle-poll.

        Faithful port of the legacy ``Galil._motor_move``: converts ``d_mm`` from
        the requested frame (motor/plate/instrument) to motor-axis counts via
        ``count_to_mm``, clamps speed, emits ``SP``/``PR|PA|HM``/``BG`` per axis,
        then polls ``query_axis_moving`` until every axis stops or the timeout
        fires. Same return dict + ErrorCodes semantics.
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
        # galil_enabled is True past the guard -> connect() ran -> transform set.
        assert self.transform is not None
        tf = self.transform

        if not isinstance(axis, list):
            axis = [axis]
        if not isinstance(d_mm, list):
            d_mm = [d_mm]

        stopping = False
        mode = MoveModes(mode)
        transformation = TransformationModes(transformation)

        tmpmotorpos = await self.query_axis_position(axis=self.get_all_axis())
        current_positionvec = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        req_positionvec: list = [None, None, None, None, None, None]
        reqdict = dict(zip(axis, d_mm))

        for idx, ax in enumerate(["x", "y", "z", "Rx", "Ry", "Rz"]):
            if ax in tmpmotorpos["ax"]:
                current_positionvec[idx] = tmpmotorpos["position"][
                    tmpmotorpos["ax"].index(ax)
                ]
                if ax in reqdict:
                    req_positionvec[idx] = reqdict[ax]

        if transformation == TransformationModes.motorxy:
            pass
        elif transformation == TransformationModes.platexy:
            motorxy = [0.0, 0.0, 1.0]
            motorxy[0] = current_positionvec[0]
            motorxy[1] = current_positionvec[1]
            current_platexy = tf.transform_motorxy_to_platexy(motorxy)
            if mode == MoveModes.relative:
                new_platexy = [0.0, 0.0, 1.0]
                if req_positionvec[0] is not None:
                    new_platexy[0] = current_platexy[0] + req_positionvec[0]
                else:
                    new_platexy[0] = current_platexy[0]
                if req_positionvec[1] is not None:
                    new_platexy[1] = current_platexy[1] + req_positionvec[1]
                else:
                    new_platexy[1] = current_platexy[1]
                new_motorxy = tf.transform_platexy_to_motorxy(new_platexy)
                axis = ["x", "y"]
                d_mm = [d for d in new_motorxy[0:2]]
                mode = MoveModes.absolute
            elif mode == MoveModes.absolute:
                new_platexy = [0.0, 0.0, 1.0]
                if req_positionvec[0] is not None:
                    new_platexy[0] = req_positionvec[0]
                else:
                    new_platexy[0] = current_platexy[0]
                if req_positionvec[1] is not None:
                    new_platexy[1] = req_positionvec[1]
                else:
                    new_platexy[1] = current_platexy[1]
                new_motorxy = tf.transform_platexy_to_motorxy(new_platexy)
                axis = ["x", "y"]
                d_mm = [d for d in new_motorxy[0:2]]
            elif mode == MoveModes.homing:
                pass
        elif transformation == TransformationModes.instrxy:
            current_instrxyz = tf.transform_motorxyz_to_instrxyz(
                current_positionvec[0:3]
            )
            if mode == MoveModes.relative:
                new_instrxyz = current_instrxyz
                for i in range(3):
                    if req_positionvec[i] is not None:
                        new_instrxyz[i] = new_instrxyz[i] + req_positionvec[i]
                new_motorxyz = tf.transform_instrxyz_to_motorxyz(new_instrxyz[0:3])
                axis = ["x", "y", "z"]
                d_mm = [d for d in new_motorxyz[0:3]]
                mode = MoveModes.absolute
            elif mode == MoveModes.absolute:
                new_instrxyz = current_instrxyz
                for i in range(3):
                    if req_positionvec[i] is not None:
                        new_instrxyz[i] = req_positionvec[i]
                new_motorxyz = tf.transform_instrxyz_to_motorxyz(new_instrxyz[0:3])
                axis = ["x", "y", "z"]
                d_mm = [d for d in new_motorxyz[0:3]]
            elif mode == MoveModes.homing:
                pass

        ret_moved_axis: list = []
        ret_speed: list = []
        ret_accepted_rel_dist: list = []
        ret_supplied_rel_dist: list = []
        ret_err_dist: list = []
        ret_err_code: list = []
        ret_counts: list = []
        timeofmove: list = []

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

        # remove not-configured axes
        for ax in deepcopy(axis):
            if ax not in self.axis_id:
                axis.pop(axis.index(ax))

        count_to_mm = self.config_dict.get("count_to_mm", {})
        for d, ax in zip(d_mm, axis):
            if len(ret_moved_axis) > 0:
                stopping = False
            if ax in self.axis_id:
                axl = self.axis_id[ax]
            else:
                ret_moved_axis.append(None)
                ret_speed.append(None)
                ret_accepted_rel_dist.append(None)
                ret_supplied_rel_dist.append(d)
                ret_err_dist.append(None)
                ret_err_code.append(ErrorCodes.setup)
                ret_counts.append(None)
                continue

            try:
                float_counts = d / count_to_mm[axl]
                counts = int(np.floor(float_counts))
                error_distance = count_to_mm[axl] * (float_counts - counts)
                if speed is None:
                    speed = self.motor_def_speed_count_sec
                else:
                    speed = int(np.floor(speed))
                if speed > self.motor_max_speed_count_sec:
                    speed = self.motor_max_speed_count_sec
                self._speed = speed
            except Exception:
                ret_moved_axis.append(None)
                ret_speed.append(None)
                ret_accepted_rel_dist.append(None)
                ret_supplied_rel_dist.append(d)
                ret_err_dist.append(None)
                ret_err_code.append(ErrorCodes.numerical)
                ret_counts.append(None)
                continue

            try:
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
                    cmd_seq.append(f"PA{axl}={counts}")
                else:
                    raise ValueError(f"invalid move mode {mode}")
                cmd_seq.append(f"BG{axl}")
                timeofmove.append(abs(counts / speed))
                for cmd in cmd_seq:
                    self._channel.command(cmd)
                ret_moved_axis.append(axl)
                ret_speed.append(speed)
                ret_accepted_rel_dist.append(None)
                ret_supplied_rel_dist.append(d)
                ret_err_dist.append(error_distance)
                ret_err_code.append(ErrorCodes.none)
                ret_counts.append(counts)
            except Exception:
                ret_moved_axis.append(None)
                ret_speed.append(None)
                ret_accepted_rel_dist.append(None)
                ret_supplied_rel_dist.append(d)
                ret_err_dist.append(None)
                ret_err_code.append(ErrorCodes.motor)
                ret_counts.append(None)
                continue

        if len(timeofmove) > 0:
            tmax = max(timeofmove)
            if tmax > 30 * 60:
                tmax = 30 * 60
        else:
            tmax = 0

        qmove: dict = {"motor_status": [], "err_code": []}
        if not self._is_estopped():
            tstart = time.time()
            while (
                time.time() - tstart < self.motor_timeout
            ) and not self._is_estopped():
                qmove = await self.query_axis_moving(axis=axis)
                await asyncio.sleep(0.5)
                if all(status == "stopped" for status in qmove["motor_status"]):
                    break
            if not self._is_estopped():
                if time.time() - tstart > self.motor_timeout:
                    await self.stop_axis(axis)
                newret_err_code = []
                for erridx, err_code in enumerate(ret_err_code):
                    if qmove["err_code"][erridx] != ErrorCodes.none:
                        newret_err_code.append(ErrorCodes.timeout)
                    else:
                        newret_err_code.append(err_code)
                ret_err_code = newret_err_code
            else:
                ret_err_code = [ErrorCodes.estop for _ in ret_err_code]
        else:
            ret_err_code = [ErrorCodes.estop for _ in ret_err_code]

        _ = await self.query_axis_position(axis=axis)

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

    async def setaxisref(self):
        """Home the linear axes, refine home, then zero absolute coords (``DP``).

        Faithful port of legacy ``setaxisref``: skips Rx/Ry/Rz; fast home ->
        2mm back-off -> slow home -> move to configured ``axis_zero`` -> ``DP``
        zero. Returns the final move result, or ``"error"`` if disabled.
        """
        if not self.galil_enabled:
            return "error"

        axis = self.get_all_axis()
        for rot in ("Rx", "Ry", "Rz"):
            if rot in axis:
                axis.remove(rot)

        if axis is not None:
            _ = await self._motor_move(
                d_mm=[0 for _ in axis],
                axis=axis,
                speed=self.motor_max_speed_count_sec,
                mode=MoveModes.homing,
                transformation=TransformationModes.motorxy,
            )
            _ = await self._motor_move(
                d_mm=[2 for _ in axis],
                axis=axis,
                speed=self.motor_max_speed_count_sec,
                mode=MoveModes.relative,
                transformation=TransformationModes.motorxy,
            )
            _ = await self._motor_move(
                d_mm=[0 for _ in axis],
                axis=axis,
                speed=1000,
                mode=MoveModes.homing,
                transformation=TransformationModes.motorxy,
            )
            retc2 = await self._motor_move(
                d_mm=[self.config_dict["axis_zero"][self.axis_id[ax]] for ax in axis],
                axis=axis,
                speed=None,
                mode=MoveModes.relative,
                transformation=TransformationModes.motorxy,
            )
            q = self._channel.command("TP")
            cmd = "DP " + ",".join("0" for _ in range(len(q.split(","))))
            self._channel.command(cmd)
            return retc2
        else:
            return "error"

    # --- public server-facing verbs ---------------------------------------
    async def motor_move(self, active) -> dict:
        """Public move entry: extract params from ``active`` and run ``_motor_move``.

        Guards concurrent moves with ``self.blocked`` (legacy parity).
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
        return {
            "moved_axis": None,
            "speed": None,
            "accepted_rel_dist": None,
            "supplied_rel_dist": None,
            "err_dist": None,
            "err_code": ErrorCodes.in_progress,
            "counts": None,
        }

    async def motor_disconnect(self) -> dict:
        """Close the channel and report the outcome (legacy motor_disconnect)."""
        try:
            self._channel.close()
        except GalilChannelError as exc:
            return {"connection": {"Unexpected GalilChannelError:", exc}}
        return {"connection": "motor_offline"}

    # --- calibration matrix management ------------------------------------
    def save_transfermatrix(self, file) -> None:
        """Write ``plate_transfermatrix`` to ``file`` as JSON (None = no-op)."""
        if file is not None:
            filedir, _ = os.path.split(file)
            if filedir and not os.path.exists(filedir):
                os.makedirs(filedir, exist_ok=True)
            with open(file, "w") as f:
                f.write(json.dumps(self.plate_transfermatrix.tolist()))

    def load_transfermatrix(self, file):
        """Read a JSON matrix from ``file`` (None if missing/malformed/wrong-shape)."""
        if os.path.exists(file):
            with open(file, "r") as f:
                try:
                    new_matrix = np.matrix(json.loads(f.readline()))
                    if new_matrix.shape != self.dflt_matrix.shape:
                        return None
                    return new_matrix
                except Exception:
                    traceback.print_exc()
                    return None
        return None

    def update_plate_transfermatrix(self, newtransfermatrix):
        """Replace the plate matrix, propagate to the transform, persist to disk."""
        if newtransfermatrix.shape != self.dflt_matrix.shape:
            matrix = self.dflt_matrix
        else:
            matrix = newtransfermatrix
        self.plate_transfermatrix = matrix
        if self.transform is not None:
            self.transform.update_Mplatexy(Mxy=self.plate_transfermatrix)
        self.save_transfermatrix(file=self.file_backup_transfermatrix)
        return self.plate_transfermatrix

    def reset_plate_transfermatrix(self):
        """Restore the plate transform matrix to the identity default."""
        self.update_plate_transfermatrix(newtransfermatrix=self.dflt_matrix)

    # --- platemap lookups (server owns unified_db; passed in) -------------
    async def solid_get_platemap(self, unified_db, plate_id=None, **kwargs) -> dict:
        return {
            "platemap": await unified_db.get_platemap([SolidSample(plate_id=plate_id)])
        }

    async def solid_get_samples_xy(
        self, unified_db, plate_id=None, sample_no=None, **kwargs
    ) -> dict:
        return {
            "platexy": await unified_db.get_samples_xy(
                [SolidSample(plate_id=plate_id, sample_no=sample_no)]
            )
        }

    # --- helpers ----------------------------------------------------------
    async def _notify(self, msg: dict) -> None:
        if self._position_sink is not None:
            await self._position_sink.put(msg)
