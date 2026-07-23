"""Native Galil motion driver over the command-channel port (P3a galil-3, native-1).

Unlike the slice-3 ``GalilMotionHardwareAdapter`` (which delegated every call to
the legacy ``Galil``), ``NativeGalilMotion`` OWNS the motion logic: it issues
Galil command strings through a
:class:`~helao.hexagon.ports.galil_command_channel.GalilCommandChannel` and does
the coordinate/parse math itself, reusing the slice-1 ``TransformXY`` and slice-2
``JsonFileCalibrationStore``. Because the only vendor seam is the channel, the
command generation + TP/PA/SC parsing are unit-testable on Linux with a fake
channel; only the real gclib I/O is at-station.

native-1 (this module) implements connect/lifecycle, the simple command verbs
(stop/motor_off/motor_on/reset_controller/estop) and the position/status
queries. ``_motor_move`` and ``setaxisref`` (the 380-line transform-move
orchestration) are deferred to native-2 and raise ``NotImplementedError``
rather than silently no-op. NOT runtime-wired.
"""

from socket import gethostname
from typing import Any, List, Optional

import numpy as np

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
)
from helao.core.error import ErrorCodes
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


class NativeGalilMotion:
    """Galil motion driver implemented directly over a GalilCommandChannel."""

    def __init__(
        self,
        config: Optional[dict] = None,
        *,
        channel: GalilCommandChannel,
        base_hook: Any = None,
        position_sink: Any = None,
    ):
        # Disconnected construct: no channel.open(), no gclib, no I/O here.
        self.config_dict = config or {}
        self._channel = channel
        self._base_hook = base_hook
        # Optional aligner position-notify queue (object with async `put`);
        # preserves the legacy query -> update_aligner feed. None = no feed.
        self._position_sink = position_sink

        self.axis_id = self.config_dict.get("axis_id", {})
        self.dflt_matrix = np.matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        self.transform: Optional[TransformXY] = None
        self.galil_enabled: Optional[bool] = None
        self.motor_busy = False
        # shared aligner/motion mutual-exclusion lock (see legacy _motor_move)
        self.blocked = False

    def set_position_sink(self, sink: Any) -> None:
        self._position_sink = sink

    def get_all_axis(self) -> List[str]:
        return [ax for ax in self.axis_id]

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
        store = JsonFileCalibrationStore(
            states_root=getattr(helaodirs, "states_root", None),
            db_root=getattr(helaodirs, "db_root", None),
            hostname=gethostname().lower(),
        )
        plate = None
        if helaodirs is not None:
            plate = store.load_plate_calibration()
        if plate is None:
            plate = self.dflt_matrix
        store.save_plate_calibration(plate)

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

    # --- deferred to native-2 (fail loud, never silent no-op) -------------
    async def _motor_move(self, d_mm, axis, speed, mode, transformation) -> dict:
        raise NotImplementedError(
            "NativeGalilMotion._motor_move is deferred to galil native-2 "
            "(coordinate-transform move orchestration)"
        )

    async def setaxisref(self):
        raise NotImplementedError(
            "NativeGalilMotion.setaxisref is deferred to galil native-2 (homing)"
        )

    # --- helpers ----------------------------------------------------------
    async def _notify(self, msg: dict) -> None:
        if self._position_sink is not None:
            await self._position_sink.put(msg)
