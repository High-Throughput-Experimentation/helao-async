"""NativeGalilMotion + GalilCommandChannel tests (P3a galil-3 native-1).

Linux construct+unit tier. A FakeChannel stands in for gclib, so the command
strings the driver emits and its TP/PA/SC parsing are verified exactly, without
a controller. Real gclib I/O is at-station. Covers native-1 (lifecycle, simple
verbs, queries) and native-2 (`_motor_move` transform-move orchestration +
`setaxisref` homing).
"""

import asyncio
import types
from typing import Optional

import numpy as np
import pytest

from helao.core.drivers.helao_driver import HelaoDriver
from helao.core.error import ErrorCodes
from helao.hexagon.adapters.legacy.galil_command_channel import GclibCommandChannel
from helao.hexagon.adapters.native.galil_motion_native import NativeGalilMotion
from helao.hexagon.ports.galil_command_channel import (
    GalilChannelError,
    GalilCommandChannel,
)


class FakeChannel:
    """Records commands; returns programmed responses (default '0')."""

    def __init__(self, responses: Optional[dict] = None):
        self.commands: list = []
        self.opened: Optional[str] = None
        self.closed = False
        self._responses = responses or {}

    def open(self, connection_string: str) -> None:
        self.opened = connection_string

    def command(self, cmd: str) -> str:
        self.commands.append(cmd)
        r = self._responses.get(cmd, "0")
        if isinstance(r, list):
            return r.pop(0)
        return r

    def info(self) -> str:
        return "fake-info"

    def version(self) -> str:
        return "fake-1.0"

    def close(self) -> None:
        self.closed = True


AXIS_CFG = {
    "axis_id": {"x": "A", "y": "B"},
    "galil_ip_str": "192.168.200.234",
    "count_to_mm": {"A": 0.001, "B": 0.001},
}


def _drv(responses=None, config=None, **kw):
    ch = FakeChannel(responses=responses)
    d = NativeGalilMotion(config or dict(AXIS_CFG), channel=ch, **kw)
    return d, ch


# --------------------------------------------------------------------------
# Channel adapter
# --------------------------------------------------------------------------
def test_gclib_channel_constructs_without_gclib_and_conforms():
    ch = GclibCommandChannel()  # no gclib import at construction
    assert isinstance(ch, GalilCommandChannel)


def test_gclib_channel_command_before_open_fails_loud():
    ch = GclibCommandChannel()
    with pytest.raises(GalilChannelError, match="not open"):
        ch.command("TP")


def test_fake_channel_conforms_to_port():
    assert isinstance(FakeChannel(), GalilCommandChannel)


# --------------------------------------------------------------------------
# Disconnected construct
# --------------------------------------------------------------------------
def test_disconnected_construct():
    d, ch = _drv()
    assert d.galil_enabled is None
    assert d.transform is None
    assert ch.opened is None and ch.commands == []
    assert d.get_all_axis() == ["x", "y"]


# --------------------------------------------------------------------------
# connect: exact axis-init command sequence
# --------------------------------------------------------------------------
def test_connect_emits_legacy_init_sequence_motor_off():
    # MG _MO returns "1" (motor off) -> SH must be emitted before MT/CE/TW/SD
    d, ch = _drv(responses={"MG _MOA": "1", "MG _MOB": "1"})
    resp = d.connect()
    assert d.galil_enabled is True
    assert resp.response.value == "success"
    assert ch.opened == "192.168.200.234 --direct -s ALL"
    assert ch.commands == [
        "PF 10.4",
        "MG _MOA",
        "SHA",
        "MTA=2",
        "CEA=4",
        "TWA=32000",
        "SDA=256000",
        "MG _MOB",
        "SHB",
        "MTB=2",
        "CEB=4",
        "TWB=32000",
        "SDB=256000",
    ]
    assert d.transform is not None  # built from config M_instr default


def test_connect_skips_SH_when_motor_already_on():
    # MG _MO returns "0" (motor on) -> no SH emitted
    d, ch = _drv(responses={"MG _MOA": "0", "MG _MOB": "0"})
    d.connect()
    assert "SHA" not in ch.commands and "SHB" not in ch.commands
    assert "MTA=2" in ch.commands


def test_connect_without_ip_is_uninitialized_and_opens_nothing():
    cfg = dict(AXIS_CFG)
    cfg.pop("galil_ip_str")
    d, ch = _drv(config=cfg)
    resp = d.connect()
    assert d.galil_enabled is False
    assert resp.status.value == "uninitialized"
    assert ch.opened is None
    assert d.transform is not None  # transform still built pre-connection


# --------------------------------------------------------------------------
# queries: TP/PA/SC parse
# --------------------------------------------------------------------------
def test_query_axis_position_parses_and_scales():
    d, ch = _drv(
        responses={"MG _MOA": "0", "MG _MOB": "0", "TP": "0,0", "PA ?,?": "1000, 2000"}
    )
    d.connect()
    out = asyncio.run(d.query_axis_position(["x", "y"]))
    assert "PA ?,?" in ch.commands
    assert out == {"ax": ["x", "y"], "position": [1.0, 2.0]}


def test_query_axis_position_unknown_axis_returns_none():
    d, ch = _drv(
        responses={"MG _MOA": "0", "MG _MOB": "0", "TP": "0,0", "PA ?,?": "1000, 2000"}
    )
    d.connect()
    out = asyncio.run(d.query_axis_position("z"))
    assert out == {"ax": [None], "position": [None]}


def test_query_axis_position_disabled_returns_empty():
    d, _ = _drv()
    assert asyncio.run(d.query_axis_position("x")) == {"ax": [], "position": []}


def test_query_axis_moving_classifies_stop_codes():
    d, ch = _drv(responses={"MG _MOA": "0", "MG _MOB": "0", "SC": "0, 1"})
    d.connect()
    out = asyncio.run(d.query_axis_moving(["x", "y"]))
    assert out["motor_status"] == ["moving", "stopped"]


# --------------------------------------------------------------------------
# simple command verbs
# --------------------------------------------------------------------------
def _connected(responses):
    base = {"MG _MOA": "0", "MG _MOB": "0", "TP": "0,0", "PA ?,?": "0, 0", "SC": "1, 1"}
    base.update(responses or {})
    d, ch = _drv(responses=base)
    d.connect()
    ch.commands.clear()
    return d, ch


def test_stop_axis_emits_ST():
    d, ch = _connected({})
    asyncio.run(d.stop_axis("x"))
    assert "STA" in ch.commands


def test_motor_off_emits_ST_then_MO():
    d, ch = _connected({})
    asyncio.run(d.motor_off("x"))
    assert ch.commands[0] == "STA" and ch.commands[1] == "MOA"


def test_motor_on_emits_SH_when_off():
    d, ch = _connected({"MG _MOA": "1"})
    asyncio.run(d.motor_on("x"))
    assert "SHA" in ch.commands


def test_reset_controller_emits_RS():
    d, ch = _connected({})
    assert asyncio.run(d.reset_controller()) == "0"
    assert ch.commands == ["RS"]


def test_estop_stops_and_disables_all_axes():
    d, ch = _connected({})
    assert asyncio.run(d.estop(True)) is True
    # every configured axis stopped (ST) and de-energized (MO)
    assert "STA" in ch.commands and "MOA" in ch.commands
    assert "STB" in ch.commands and "MOB" in ch.commands


def test_estop_false_is_noop():
    d, ch = _connected({})
    assert asyncio.run(d.estop(False)) is False
    assert ch.commands == []


# --------------------------------------------------------------------------
# lifecycle + position sink + deferred verbs
# --------------------------------------------------------------------------
def test_disconnect_and_shutdown_close_channel():
    d, ch = _connected({})
    d.disconnect()
    assert ch.closed is True and d.galil_enabled is False
    d2, ch2 = _connected({})
    assert d2.shutdown() == {"shutdown"} and ch2.closed is True


def test_position_sink_receives_query_feed():
    class _Q:
        def __init__(self):
            self.items = []

        async def put(self, msg):
            self.items.append(msg)

    q = _Q()
    d, ch = _drv(
        responses={"MG _MOA": "0", "MG _MOB": "0", "TP": "0,0", "PA ?,?": "1000, 2000"},
        position_sink=q,
    )
    d.connect()
    asyncio.run(d.query_axis_position(["x", "y"]))
    assert q.items and q.items[-1]["ax"] == ["x", "y"]


# --------------------------------------------------------------------------
# native-2: _motor_move + setaxisref (transform-move orchestration)
# --------------------------------------------------------------------------
def _move_responses(extra=None):
    # single x axis, stopped stop-code so the settle-poll breaks immediately
    base = {"MG _MOA": "0", "TP": "0", "PA ?": "0", "SC": "1"}
    base.update(extra or {})
    return base


MOVE_CFG = {
    "axis_id": {"x": "A"},
    "galil_ip_str": "10.0.0.1",
    "count_to_mm": {"A": 0.001},
    "def_speed_count_sec": 10000,
    "max_speed_count_sec": 25000,
}


def test_motor_move_absolute_motorxy_emits_SP_PA_BG():
    d, ch = _drv(responses=_move_responses(), config=dict(MOVE_CFG))
    d.connect()
    ch.commands.clear()
    out = asyncio.run(d._motor_move([1.0], ["x"], None, "absolute", "motorxy"))
    # 1.0 mm / 0.001 (count_to_mm) = 1000 counts; default speed 10000
    assert "SPA=10000" in ch.commands
    assert "PAA=1000" in ch.commands
    assert "BGA" in ch.commands
    assert out["moved_axis"] == ["A"]
    assert out["counts"] == [1000]
    assert out["speed"] == [10000]
    assert out["err_code"] == [ErrorCodes.none]
    assert d.motor_busy is False  # released at the end


def test_motor_move_relative_uses_PR():
    d, ch = _drv(responses=_move_responses(), config=dict(MOVE_CFG))
    d.connect()
    ch.commands.clear()
    asyncio.run(d._motor_move([2.0], ["x"], None, "relative", "motorxy"))
    assert "PRA=2000" in ch.commands and "BGA" in ch.commands


def test_motor_move_clamps_speed_to_max():
    d, ch = _drv(responses=_move_responses(), config=dict(MOVE_CFG))
    d.connect()
    ch.commands.clear()
    asyncio.run(d._motor_move([1.0], ["x"], 99999, "absolute", "motorxy"))
    assert "SPA=25000" in ch.commands  # clamped to max_speed_count_sec


def test_motor_move_busy_guard_returns_in_progress():
    d, _ = _drv(responses=_move_responses(), config=dict(MOVE_CFG))
    d.connect()
    d.motor_busy = True
    out = asyncio.run(d._motor_move([1.0], ["x"], None, "absolute", "motorxy"))
    assert out["err_code"] == ErrorCodes.in_progress
    assert out["counts"] is None


def test_motor_move_estop_short_circuits():
    class _EstopHook:
        class actionservermodel:
            estop = True

    d, _ = _drv(
        responses=_move_responses(), config=dict(MOVE_CFG), base_hook=_EstopHook()
    )
    d.connect()
    out = asyncio.run(d._motor_move([1.0], ["x"], None, "absolute", "motorxy"))
    assert out["err_code"] == ErrorCodes.estop
    assert d.motor_busy is False


def test_setaxisref_homes_and_zeros():
    cfg = dict(MOVE_CFG)
    cfg["axis_zero"] = {"A": 5.0}
    d, ch = _drv(responses=_move_responses(), config=cfg)
    d.connect()
    ch.commands.clear()
    retc2 = asyncio.run(d.setaxisref())
    # homing moves emit HM; final absolute-zero via DP
    assert "HMA" in ch.commands
    assert "DP 0" in ch.commands
    assert isinstance(retc2, dict) and retc2["moved_axis"] == ["A"]


def test_setaxisref_disabled_returns_error():
    cfg = dict(MOVE_CFG)
    cfg.pop("galil_ip_str")
    d, _ = _drv(config=cfg)
    d.connect()  # no ip -> galil_enabled False
    assert asyncio.run(d.setaxisref()) == "error"


# --------------------------------------------------------------------------
# native-3: HelaoDriver surface + server-facing verbs (cut-over enablement)
# --------------------------------------------------------------------------
def test_is_helao_driver_and_default_channel():
    # driver_classes=[NativeGalilMotion] path: constructible from config alone,
    # HelaoDriver subclass, default channel is the real gclib-backed one.
    d = NativeGalilMotion({"axis_id": {"x": "A"}})
    assert type(d._channel).__name__ == "GclibCommandChannel"
    assert isinstance(d, HelaoDriver)


def _active(params):
    return types.SimpleNamespace(action=types.SimpleNamespace(action_params=params))


def test_motor_move_public_extracts_params_and_guards_blocked():
    d, ch = _drv(responses=_move_responses(), config=dict(MOVE_CFG))
    d.connect()
    ch.commands.clear()
    out = asyncio.run(
        d.motor_move(
            _active(
                {
                    "d_mm": [1.0],
                    "axis": ["x"],
                    "mode": "absolute",
                    "transformation": "motorxy",
                }
            )
        )
    )
    assert out["moved_axis"] == ["A"] and out["counts"] == [1000]
    assert d.blocked is False  # released after the move
    assert "PAA=1000" in ch.commands

    # a concurrent move (blocked already set) short-circuits
    d.blocked = True
    out2 = asyncio.run(d.motor_move(_active({"d_mm": [1.0], "axis": ["x"]})))
    assert out2["err_code"] == ErrorCodes.in_progress


def test_motor_disconnect_closes_channel():
    d, ch = _connected({})
    out = asyncio.run(d.motor_disconnect())
    assert ch.closed is True
    assert out == {"connection": "motor_offline"}


def test_update_and_reset_plate_transfermatrix():
    d, _ = _drv(responses=_move_responses(), config=dict(MOVE_CFG))
    d.connect()  # builds transform; file_backup None (no states_root) -> save no-op
    new = np.matrix([[1, 0, 5], [0, 1, 7], [0, 0, 1]])
    ret = d.update_plate_transfermatrix(newtransfermatrix=new)
    assert np.array_equal(ret, new)
    assert np.array_equal(d.plate_transfermatrix, new)
    # wrong shape -> falls back to identity default
    bad = np.matrix([[1, 0], [0, 1]])
    d.update_plate_transfermatrix(newtransfermatrix=bad)
    assert np.array_equal(d.plate_transfermatrix, d.dflt_matrix)
    # reset -> identity
    d.update_plate_transfermatrix(newtransfermatrix=new)
    d.reset_plate_transfermatrix()
    assert np.array_equal(d.plate_transfermatrix, d.dflt_matrix)


def test_solid_get_platemap_and_samples_xy_use_unified_db():
    class _DB:
        def __init__(self):
            self.calls = []

        async def get_platemap(self, samples):
            self.calls.append(("platemap", samples[0].plate_id))
            return ["PM"]

        async def get_samples_xy(self, samples):
            self.calls.append(("xy", samples[0].plate_id, samples[0].sample_no))
            return [[1.0, 2.0]]

    d, _ = _drv()
    db = _DB()
    pm = asyncio.run(d.solid_get_platemap(db, plate_id=6353))
    xy = asyncio.run(d.solid_get_samples_xy(db, plate_id=6353, sample_no=7))
    assert pm == {"platemap": ["PM"]}
    assert xy == {"platexy": [[1.0, 2.0]]}
    assert db.calls == [("platemap", 6353), ("xy", 6353, 7)]


def test_stop_and_reset_abc():
    d, ch = _connected({})
    resp = asyncio.run(d.stop())
    assert resp.response.value == "success"
    assert "STA" in ch.commands  # aborted the configured axis
    # reset = disconnect + reconnect
    ch.commands.clear()
    d.reset()
    assert d.galil_enabled is True


def test_build_transform_warns_on_missing_calibration(monkeypatch):
    """Absent plate + instrument calibration -> identity fallback logs WARNING.

    With no base hook, helaodirs is None so neither calibration file is read;
    both fall back to identity and _build_transform must warn on each (the
    diagnostic for a mis-placed plate_calib file that silently miscalibrates
    motor targets).
    """
    from helao.hexagon.adapters.native import galil_motion_native as mod

    d, _ = _drv()
    warnings: list = []
    monkeypatch.setattr(
        mod.LOGGER, "warning", lambda msg, *a, **k: warnings.append(str(msg))
    )
    d._build_transform()
    assert any("identity plate transform" in w for w in warnings)
    assert any("identity instrument transform" in w for w in warnings)
    assert np.allclose(np.asarray(d.plate_transfermatrix), np.eye(3))


def test_build_transform_no_warning_when_config_m_instr_present(monkeypatch):
    """A configured M_instr is a real transform -> no identity-instrument warning."""
    from helao.hexagon.adapters.native import galil_motion_native as mod

    cfg = dict(AXIS_CFG)
    cfg["M_instr"] = [[2, 0, 0, 0], [0, 2, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    d, _ = _drv(config=cfg)
    warnings: list = []
    monkeypatch.setattr(
        mod.LOGGER, "warning", lambda msg, *a, **k: warnings.append(str(msg))
    )
    d._build_transform()
    assert not any("identity instrument transform" in w for w in warnings)
    # plate is still absent here -> the plate warning is still expected
    assert any("identity plate transform" in w for w in warnings)
