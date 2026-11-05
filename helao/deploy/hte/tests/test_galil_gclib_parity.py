"""The same driver calls produce the same controller traffic and results on
gclib wrapper 1.0 and 2.x (the logic is shared; this pins the channel layer)."""

import types

import pytest

from helao.deploy.hte.servers.galil_io.enum import TriggerType
from helao.deploy.hte.servers.galil_io.galil_io_driver import Galil
from helao.deploy.hte.servers.galil_motion.galil_command_channel_port import (
    GalilChannelError,
)
from helao.deploy.hte.servers.galil_motion.galil_motion_native import NativeGalilMotion
from helao.deploy.hte.servers.galil_motion.tests.fake_gclib import Wire, install

IO_CFG = {
    "galil_ip_str": "10.0.0.5",
    "dev_ai": {"ai1": 1},
    "dev_ao": {"ao1": 2},
    "dev_di": {"di1": 3, "gamry_ttl0": 4},
    "dev_do": {"do1": 5, "do2": 6},
}
IO_REPLIES = {"MG @AN[1]": " 1.2340", "MG @IN[3]": " 1.0000", "MG @OUT[5]": " 0.0000"}

MOTION_CFG = {
    "axis_id": {"x": "A", "y": "B"},
    "galil_ip_str": "10.0.0.7",
    "count_to_mm": {"A": 0.001, "B": 0.001},
    "def_speed_count_sec": 10000,
    "max_speed_count_sec": 25000,
    "axis_zero": {"A": 5.0, "B": 3.0},
    "timeout": 1,  # bounds settle loops so a fault fails fast instead of hanging
}
# stop code 1 so the settle-poll breaks at once; non-zero TP/PA for positions
MOTION_REPLIES = {
    "MG _MOA": "0",
    "MG _MOB": "0",
    "TP": "1000, 2000",
    "PA ?,?": "1000, 2000",
    "PA ?": "1000",
    "SC": "1, 1",
}


def _stable(x):
    return x  # no time-varying values in any result so far; nothing dropped


async def _io_session(monkeypatch, api):
    wire = Wire(dict(IO_REPLIES))
    install(monkeypatch, api, wire)
    drv = Galil(config={**IO_CFG, "gclib_api": api})
    out: list = [drv.connect().response]
    out.append(await drv.get_analog_in("ai1"))
    out.append(await drv.get_digital_in("di1"))
    out.append(await drv.get_digital_out("do1"))
    out.append(await drv.set_analog_out(1.5, "ao1"))
    out.append(await drv.set_digital_out(True, "do1"))
    out.append(await drv.set_digital_out(False, "do1"))
    out.append(
        await drv.set_digital_cycle(
            trigger_name="gamry_ttl0",
            triggertype=TriggerType.fallingedge,
            out_name="do1",
            toggle_init_delay=0.0,
            toggle_duty=0.5,
            toggle_period=2.0,
            toggle_duration=10.0,
        )
    )
    out.append(await drv.stop_digital_cycle())
    out.append(await drv.estop(True))
    out.append(drv.disconnect().response)
    return wire, [_stable(o) for o in out]


@pytest.mark.asyncio
async def test_io_parity(monkeypatch):
    w1, r1 = await _io_session(monkeypatch, "1")
    w2, r2 = await _io_session(monkeypatch, "2")
    assert w1.calls == w2.calls
    assert r1 == r2
    assert any(c[0] == "program" for c in w2.calls)  # the cycle downloaded a program
    assert all("\x00" not in p for p in w2.raw_programs)
    assert w2.gcaps is False
    assert w1.raw_open == "10.0.0.5 --direct -s ALL"


def _active(params):
    return types.SimpleNamespace(action=types.SimpleNamespace(action_params=params))


async def _motion_session(monkeypatch, api):
    wire = Wire(dict(MOTION_REPLIES))
    install(monkeypatch, api, wire)
    drv = NativeGalilMotion({**MOTION_CFG, "gclib_api": api})
    out: list = [drv.connect().response]
    out.append(await drv.query_axis_position(["x", "y"]))
    out.append(await drv.query_axis_position_counts(["x"]))
    out.append(await drv.query_axis_moving(["x"]))
    out.append(await drv.motor_on(["x"]))
    out.append(await drv.motor_off(["x"]))
    out.append(await drv.stop_axis(["x"]))
    out.append(
        await drv.motor_move(
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
    out.append(await drv.setaxisref())
    out.append(await drv.reset_controller())
    out.append(await drv.estop(True))
    out.append(await drv.motor_disconnect())
    out.append(drv.reset().response)
    out.append(drv.disconnect().response)
    return wire, [_stable(o) for o in out]


@pytest.mark.asyncio
async def test_motion_parity(monkeypatch):
    w1, r1 = await _motion_session(monkeypatch, "1")
    w2, r2 = await _motion_session(monkeypatch, "2")
    assert w1.calls == w2.calls
    assert r1 == r2
    assert ("command", "BGA") in w2.calls and ("command", "HMA") in w2.calls
    assert w2.gcaps is False
    assert w1.raw_open == "10.0.0.7 --direct -s ALL"


@pytest.mark.asyncio
async def test_io_error_parity(monkeypatch):
    runs = []
    for api in ("1", "2"):
        wire = Wire(dict(IO_REPLIES), fail_on={"MG @AN[1]"})
        install(monkeypatch, api, wire)
        drv = Galil(config={**IO_CFG, "gclib_api": api})
        drv.connect()
        try:
            res = _stable(await drv.get_analog_in("ai1"))
        except GalilChannelError as exc:  # the driver lets channel errors escape
            res = ("raised", type(exc).__name__, str(exc))
        runs.append((wire, res))
    assert runs[0][0].calls == runs[1][0].calls
    assert runs[0][1] == runs[1][1]
    assert runs[0][1][0] == "raised"


@pytest.mark.asyncio
async def test_motion_error_parity(monkeypatch):
    runs = []
    for api in ("1", "2"):
        wire = Wire(dict(MOTION_REPLIES), fail_on={"BGA"})
        install(monkeypatch, api, wire)
        drv = NativeGalilMotion({**MOTION_CFG, "gclib_api": api})
        drv.connect()
        res = await drv.motor_move(
            _active({"d_mm": [1.0], "axis": ["x"], "mode": "absolute"})
        )
        runs.append((wire, _stable(res)))
    assert runs[0][0].calls == runs[1][0].calls
    assert runs[0][1] == runs[1][1]
    assert ("command", "TC1") in runs[1][0].calls  # the error-code read happened
