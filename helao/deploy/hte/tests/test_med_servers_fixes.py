"""Regression tests for the medium-severity hte server/layout fixes."""

import asyncio
import base64
import time
import types

import pytest
from bokeh.document import Document

from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.deploy.hte.servers.action import gamry_server2, power_supply_server
from helao.deploy.hte.servers.action import spec_server

SERV_KEY = "PSTAT"


# gamry_server2: a poll exception must surface as errored, not UnboundLocalError
@pytest.mark.asyncio
async def test_gamry_poll_error_returns_errored():
    ex = object.__new__(gamry_server2.GamryExec)

    def boom(_rate):
        raise RuntimeError("driver gone")

    ex.driver = types.SimpleNamespace(get_data=boom)
    res = await ex._poll()
    assert res == {"error": ErrorCodes.critical_error, "status": HloStatus.errored}


# power_supply_server: sleeps must not block the event loop
@pytest.mark.asyncio
async def test_square_wave_exec_does_not_block_loop():
    ok = types.SimpleNamespace(response=power_supply_server.DriverResponseType.success)

    async def apply_voltage_async(**_):
        return ok

    driver = types.SimpleNamespace(
        set_output=lambda output_on: ok, apply_voltage_async=apply_voltage_async
    )
    ex = object.__new__(power_supply_server.SquareWaveExecutor)
    ex.driver = driver
    ex.action_params = {"voltage": 1.0, "sleep_time": 0.2}
    ex.active = types.SimpleNamespace(action_loop_running=True)

    ticks = []

    async def ticker():
        while True:
            ticks.append(1)
            await asyncio.sleep(0.01)

    t = asyncio.create_task(ticker())
    await asyncio.sleep(0)
    res = await ex._exec()
    t.cancel()
    assert res == {"error": ErrorCodes.none}
    assert len(ticks) > 10, f"loop ran only {len(ticks)} times; sleep blocked it"


# power_supply_server: a stop during the off phase must not re-energize the output
@pytest.mark.asyncio
async def test_square_wave_exec_stop_during_off_phase_stays_off():
    ok = types.SimpleNamespace(response=power_supply_server.DriverResponseType.success)
    calls = []

    async def apply_voltage_async(**_):
        calls.append("apply")
        return ok

    driver = types.SimpleNamespace(
        set_output=lambda output_on: calls.append(output_on) or ok,
        apply_voltage_async=apply_voltage_async,
    )
    ex = object.__new__(power_supply_server.SquareWaveExecutor)
    ex.driver = driver
    ex.action_params = {"voltage": 1.0, "sleep_time": 0.2}
    ex.active = types.SimpleNamespace(action_loop_running=True)

    task = asyncio.create_task(ex._exec())
    await asyncio.sleep(0.05)
    ex.active.action_loop_running = False  # what stop_action_task does on E-STOP
    await task
    assert calls == [False], calls


# spec_server.calibrate_intensity: a saturated peak must shorten integration time
async def _run_calibrate(peaks, int_time_ms):
    endpoints = {}

    class App:
        server = types.SimpleNamespace(server_name="SPEC")
        server_params = {}
        base = None

        def __init__(self):
            self.int_times = []
            peak_iter = iter(peaks)

            def acquire(**p):
                self.int_times.append(p["int_time_ms"])
                return {"peak_intensity": next(peak_iter)}

            self.driver = types.SimpleNamespace(
                connect=lambda: types.SimpleNamespace(status="ok"),
                pxwl=[],
                acquire_spec_adv=acquire,
            )

        def action(self, *a, **k):
            return lambda f: endpoints.setdefault(f.__name__, f)

        def post(self, *a, **k):
            return lambda f: f

    app = App()

    class DB:
        def __init__(self, *_):
            pass

        async def init_db(self):
            pass

    orig = spec_server.UnifiedSampleDataAPI
    spec_server.UnifiedSampleDataAPI = DB
    try:
        await spec_server.sm303_dyn_endpoints(app)
    finally:
        spec_server.UnifiedSampleDataAPI = orig

    params = dict(
        int_time_ms=int_time_ms,
        n_avg=1,
        peak_lower_wl=400,
        peak_upper_wl=750,
        target_peak_min=30000,
        target_peak_max=32000,
        max_iters=5,
        max_integration_time=150,
    )

    class Active:
        action = types.SimpleNamespace(action_params=params)

        async def enqueue_data_dflt(self, datadict):
            pass

        async def finish(self):
            return types.SimpleNamespace(as_dict=lambda: {})

    class Ctx:
        async def begin(self, **_):
            return Active()

    await endpoints["calibrate_intensity"](Ctx())
    return app.int_times


@pytest.mark.asyncio
async def test_calibrate_intensity_shortens_when_saturated():
    int_times = await _run_calibrate([60000.0, 31000.0], 100)
    # second acquisition must be shorter than the first (100 ms) for a 2x overshoot
    assert int_times[1] < int_times[0], int_times


@pytest.mark.asyncio
async def test_calibrate_intensity_floors_at_one_ms():
    # persistently saturated: truncation would otherwise drive 3 ms to 0 ms
    int_times = await _run_calibrate([1e9] * 6, 3)
    assert min(int_times) >= 1, int_times


# aligner: a bad calibration upload must not overwrite the live alignment
def test_aligner_bad_matrix_file_keeps_live_matrix():
    from helao.deploy.hte.layouts import aligner

    calls, ticks = [], []
    al = object.__new__(aligner.Aligner)
    al.motor = types.SimpleNamespace(
        aligning_enabled=True,
        dflt_matrix="DFLT",
        update_plate_transfermatrix=lambda newtransfermatrix: calls.append(
            newtransfermatrix
        ),
    )
    al.vis = types.SimpleNamespace(
        doc=types.SimpleNamespace(add_next_tick_callback=ticks.append)
    )
    al.callback_calib_file_input(None, None, base64.b64encode(b"not json").decode())
    assert calls == []
    assert len(ticks) == 1


# visualizers
class _FakeVis:
    def __init__(self, serv_params=None):
        self.doc = Document()
        self.server_cfg = {"params": {}}
        self.world_cfg = {
            "servers": {
                SERV_KEY: {
                    "host": "127.0.0.1",
                    "port": 8004,
                    "params": serv_params or {},
                }
            }
        }


def _build(module, serv_params=None):
    async def _make():
        vis = module.C_vis(_FakeVis(serv_params), SERV_KEY)
        vis.IOloop_data_run = False
        vis.IOtask.cancel()
        return vis

    return asyncio.run(_make())


def test_biologic_vis_reads_num_channels_from_action_server_and_skips_extra():
    from helao.deploy.hte.servers.visualizer import biologic_vis

    vis = _build(biologic_vis, {"num_channels": 2})
    assert vis.num_channels == 2

    vis = _build(biologic_vis)  # one channel; a channel-1 package must be skipped
    pkg = types.SimpleNamespace(
        action_name=biologic_vis.VALID_ACTION_NAME[0],
        datamodel=types.SimpleNamespace(
            status=biologic_vis.VALID_DATA_STATUS[0],
            data={"u": {"channel": [1], "t_s": [0.0]}},
        ),
    )
    vis.add_points([pkg])


def test_spec_vis_survives_unreachable_spec_server(monkeypatch):
    from helao.deploy.hte.servers.visualizer import spec_vis

    def down(*a, **k):
        raise ConnectionError("spec server down")

    monkeypatch.setattr(spec_vis, "private_dispatcher", down)
    vis = _build(spec_vis)
    assert vis.wl == [] and vis.ev == []


def test_spec_vis_retries_wavelengths_after_startup_failure(monkeypatch):
    from helao.deploy.hte.servers.visualizer import spec_vis

    def down(*a, **k):
        raise ConnectionError("spec server down")

    monkeypatch.setattr(spec_vis, "private_dispatcher", down)
    vis = _build(spec_vis)
    monkeypatch.setattr(
        spec_vis, "private_dispatcher", lambda *a, **k: ([400.0, 500.0], None)
    )
    vis.add_points([])
    assert vis.wl == [400.0, 500.0] and len(vis.ev) == 2


# power_supply_server: every executor switches the output off before disconnect,
# even when set_output fails
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cls",
    [
        power_supply_server.ConstantCurrentSquareWaveExecutor,
        power_supply_server.ApplyVoltageExecutor,
        power_supply_server.SquareWaveExecutor,
    ],
)
@pytest.mark.parametrize("off_raises", [False, True])
async def test_power_supply_post_exec_output_off_before_disconnect(cls, off_raises):
    ok = types.SimpleNamespace(response=power_supply_server.DriverResponseType.success)
    calls = []

    def set_output(output_on):
        calls.append(("output", output_on))
        if off_raises:
            raise RuntimeError("supply gone")
        return ok

    ex = object.__new__(cls)
    ex.driver = types.SimpleNamespace(
        set_output=set_output, disconnect=lambda: calls.append("disconnect") or ok
    )
    res = await ex._post_exec()
    assert res == {"error": ErrorCodes.none}
    assert calls == [("output", False), "disconnect"]
