"""Medium-severity driver fixes: nidaqmx Heatloop, power supply stop/estop,
alicat const-conc executor, legato poller lock, mecom setpoint, axiscam I/O.

Vendor hardware is not needed: each driver is built without I/O and its
instrument/serial/websocket seam replaced by a recorder.
"""

import asyncio
import time
import types

import pytest

from helao.core.drivers.helao_driver import DriverResponseType
from helao.core.error import ErrorCodes
from helao.deploy.hte.drivers.io.nidaqmx_driver import cNIMAX
from helao.deploy.hte.drivers.mfc.alicat_driver import MfcConstConcExec
from helao.deploy.hte.drivers.pump.legato_driver import KDS100
from helao.deploy.hte.drivers.sensor import axiscam_driver
from helao.deploy.hte.drivers.sensor.axiscam_driver import AxisCam, AxisCamExec
from helao.deploy.hte.drivers.temperature_control.mecom_driver import MeerstetterTEC


@pytest.mark.asyncio
async def test_heatloop_turns_every_heater_off_on_exit():
    drv = cNIMAX(
        config={
            "dev_heat": {"cellheater": "p0/line0", "res_heater": "p0/line1"},
            "dev_monitor": ["Ttemp_Ktc_in_cell_C", "Ttemp_Ttc_in_reservoir_C"],
        }
    )
    drv._get_lbuf = lambda key: (20.0, 0)
    writes = []

    async def _do(do_port=None, do_name="", on=False, **kw):
        writes.append((do_name, on))

    drv.set_digital_out = _do
    # duration 0: the loop body never runs, only the exit path
    await drv.Heatloop(0, 25, 30, 25, 30)
    assert ("cellheater", False) in writes
    assert ("res_heater", False) in writes


@pytest.mark.asyncio
async def test_power_supply_estop_writes_out0():
    from helao.deploy.hte.drivers.power_supply.power_supply_driver import (
        PowerSupplyDriver as PowerSupply,
    )

    drv = PowerSupply(config={"resource_name": "x"})
    sent = []
    drv.instrument = types.SimpleNamespace(write=sent.append)
    assert await drv.estop(switch=False) is False
    assert sent == []
    assert await drv.estop(switch=True) is True
    assert sent == ["OUT0"]
    assert drv.stop().response == DriverResponseType.success
    assert sent == ["OUT0", "OUT0"]


@pytest.mark.asyncio
async def test_estop_during_apply_voltage_leaves_output_off():
    from helao.deploy.hte.drivers.power_supply.power_supply_driver import (
        PowerSupplyDriver as PowerSupply,
    )
    from helao.deploy.hte.servers.action.power_supply_server import (
        ApplyVoltageExecutor,
    )

    drv = PowerSupply(config={"resource_name": "x"})
    sent = []
    drv.instrument = types.SimpleNamespace(write=sent.append)
    ex = ApplyVoltageExecutor.__new__(ApplyVoltageExecutor)
    ex.driver = drv
    ex.action_params = {"voltage": 3.0, "sleep_time": 0.2}
    task = asyncio.create_task(ex._exec())
    await asyncio.sleep(0.05)
    await drv.estop(switch=True)
    res = await task
    assert res["error"] == ErrorCodes.critical_error
    assert "OUT1" not in sent and sent[-1] == "OUT0"
    # release clears the latch
    await drv.estop(switch=False)
    assert drv.set_output(True).response == DriverResponseType.success


def _conc_exec(wsc):
    ex = MfcConstConcExec.__new__(MfcConstConcExec)
    ex.wsc = wsc
    ex.co2serv_key = "CO2"
    ex.device_name = "mfc1"
    ex.target_co2_ppm = 1e5
    ex.headspace_scc = 7.5
    ex.flowrate_sccm = 0.5
    ex.active = types.SimpleNamespace(driver=types.SimpleNamespace(fcs={"mfc1": 1}))
    return ex


@pytest.mark.asyncio
async def test_const_conc_without_co2_server_fails_pre_exec():
    ex = _conc_exec(wsc=None)
    assert (await ex._pre_exec())["error"] == ErrorCodes.critical_error


@pytest.mark.asyncio
async def test_eval_conc_does_not_block_loop_and_skips_empty_packet():
    def _slow_empty():
        time.sleep(0.3)
        return {}

    ex = _conc_exec(types.SimpleNamespace(read_messages=_slow_empty))
    ticks = 0

    async def _ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    t = asyncio.create_task(_ticker())
    result = await ex.eval_conc()
    t.cancel()
    assert result is None
    assert ticks >= 10


@pytest.mark.asyncio
async def test_eval_conc_computes_fill_from_packet():
    pkt = {"co2_ppm": ([0.0, 0.0], 0)}
    ex = _conc_exec(types.SimpleNamespace(read_messages=lambda: pkt))
    fill_time, fill_scc = await ex.eval_conc()
    assert fill_scc == pytest.approx(7.5 * 1e5 / 1e6)
    assert fill_time == pytest.approx(fill_scc / 0.5 * 60.0)


def test_legato_send_sync_skips_cycle_when_lock_held():
    d = KDS100.__new__(KDS100)
    d.sio = types.SimpleNamespace(write=lambda s: None)
    d.com_lock = True  # an async send() is mid-flight on this thread
    d.config_dict = {"pumps": {"one": {"address": 0}}}
    t0 = time.time()
    assert d._send_sync("one", "status") == []
    assert time.time() - t0 < 1.0
    assert d.com_lock is True  # the other holder's lock is untouched


def test_mecom_set_temp_accepts_int_setpoint():
    d = MeerstetterTEC.__new__(MeerstetterTEC)
    d.channel, d.address = 1, 2
    calls = []
    d.session = lambda: types.SimpleNamespace(
        set_parameter=lambda **kw: calls.append(kw)
    )
    d.set_temp(30)
    assert calls[0]["value"] == 30.0
    assert isinstance(calls[0]["value"], float)


def test_axiscam_get_has_timeout(monkeypatch):
    seen = {}

    class _Sess:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def get(self, url, **kw):
            seen.update(kw)
            return types.SimpleNamespace(content=b"jpg")

    monkeypatch.setattr(axiscam_driver.requests, "Session", _Sess)
    drv = AxisCam(config={"axis_ip": "1.2.3.4"})
    assert drv.acquire_image() == b"jpg"
    assert seen.get("timeout")


@pytest.mark.asyncio
async def test_axiscam_poll_does_not_block_loop():
    ex = AxisCamExec.__new__(AxisCamExec)
    ex.duration = -1
    ex.start_time = time.time()

    def _slow_image():
        time.sleep(0.3)
        return b"jpg"

    async def _write(img, t):
        return {}

    ex.active = types.SimpleNamespace(
        driver=types.SimpleNamespace(acquire_image=_slow_image)
    )
    ex.write_image = _write
    ticks = 0

    async def _ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    t = asyncio.create_task(_ticker())
    await ex._poll()
    t.cancel()
    assert ticks >= 10


@pytest.mark.asyncio
async def test_axiscam_poll_returns_errored_on_request_failure():
    from helao.core.models.hlostatus import HloStatus

    ex = AxisCamExec.__new__(AxisCamExec)
    ex.duration = -1
    ex.start_time = time.time()

    def _timeout():
        raise axiscam_driver.requests.Timeout("camera silent")

    ex.active = types.SimpleNamespace(
        driver=types.SimpleNamespace(acquire_image=_timeout)
    )
    out = await ex._poll()
    assert out["error"] == ErrorCodes.critical_error
    assert out["status"] == HloStatus.errored
    assert "camera silent" in out["message"]


@pytest.mark.asyncio
async def test_heatloop_turns_heaters_off_when_loop_raises():
    drv = cNIMAX(
        config={
            "dev_heat": {"cellheater": "p0/line0", "res_heater": "p0/line1"},
            "dev_monitor": ["Ttemp_Ktc_in_cell_C"],
        }
    )
    drv._get_lbuf = lambda key: (20.0, 0)  # no reservoir key -> KeyError in loop
    writes = []

    async def _do(do_port=None, do_name="", on=False, **kw):
        writes.append((do_name, on))

    drv.set_digital_out = _do
    with pytest.raises(KeyError):
        await drv.Heatloop(1, 25, 30, 25, 30)
    assert ("cellheater", False) in writes
    assert ("res_heater", False) in writes


def test_ws_read_messages_timeout_returns_empty_without_retry(monkeypatch):
    from helao.helpers import ws_utils

    seen = {}

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def recv(self, timeout=None):
            seen["timeout"] = timeout
            raise TimeoutError

    monkeypatch.setattr(ws_utils, "connect", lambda url: _Conn())
    monkeypatch.setattr(ws_utils.time, "sleep", lambda s: seen.setdefault("slept", s))
    assert ws_utils.WsSyncClient("h", 1, "p").read_messages() == {}
    assert seen["timeout"] and "slept" not in seen
