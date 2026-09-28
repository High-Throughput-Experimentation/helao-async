"""The ``toggle_ttl`` / ``cancel_toggle_ttl`` actions on the NI-DAQmx server.

A TTL hold can outlast an HTTP request, so it runs as a :class:`TTLExec`
executor rather than inline in the endpoint. What matters is that the line is
driven high once at setup and low once at cleanup, whatever ends the hold, and
that a second hold on the same line is refused -- otherwise the first to finish
would drop the line under the second.

NI-DAQmx is a Windows-only vendor SDK, so the driver is stubbed at
``set_digital_out`` and ``ActionHost`` is replaced by a route-capturing fake.

Run directly (``python -m pytest`` on this file).
"""

import asyncio
from types import SimpleNamespace
from typing import Any

from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.deploy.hte.drivers.io.nidaqmx_driver import TTLExec, cNIMAX

DEV_TTL = {"trigger_out": "PXI-6284/port0/line5", "shutter": "PXI-6284/port0/line6"}


class _FakeDriver:
    def __init__(self, dev_ttl=DEV_TTL):
        self.dev_ttl = dev_ttl
        self.writes = []
        self.do_state = {}
        self.fail = False

    async def set_digital_out(self, do_port=None, do_name="", on=False, **kwargs):
        if self.fail:
            raise RuntimeError("DAQmx error")
        self.writes.append((do_name, do_port, on))
        self.do_state[do_name] = on
        return {"error_code": ErrorCodes.none, "name": do_name, "value": on}


class _FakeSession:
    def __init__(self, driver, params, executors):
        self.driver = driver
        self.action = SimpleNamespace(
            action_name="toggle_ttl",
            action_uuid=f"u{id(self)}",
            action_params=dict(params),
            error_code=ErrorCodes.none,
            exec_id=None,
            as_dict=lambda: {"error_code": self.action.error_code},
        )
        self.executors = executors
        self.executor = None
        self.stopped = False

    def start_executor(self, executor):
        self.executor = executor
        # what the runner does after _pre_exec succeeds
        self.executors[executor.exec_id] = self
        return {"started": executor.exec_id}

    def stop_action_task(self):
        self.stopped = True

    async def finish(self):
        return self.action


def _make_exec(duration, ttl="trigger_out"):
    driver = _FakeDriver()
    params = {"ttl": ttl, "duration": duration}
    session = _FakeSession(driver, params, {})
    return TTLExec(active=session, oneoff=False, poll_rate=0.01), driver


def test_ttl_exec_holds_high_for_duration_then_drops():
    executor, driver = _make_exec(duration=0.05)

    async def run():
        assert (await executor._pre_exec())["error"] == ErrorCodes.none
        assert driver.writes == [("trigger_out", DEV_TTL["trigger_out"], True)]
        assert (await executor._poll())["status"] == HloStatus.active
        await asyncio.sleep(0.06)
        assert (await executor._poll())["status"] == HloStatus.finished
        await executor._post_exec()

    asyncio.run(run())
    assert driver.writes[-1] == ("trigger_out", DEV_TTL["trigger_out"], False)
    assert len(driver.writes) == 2


def test_ttl_exec_without_duration_holds_until_stopped():
    executor, driver = _make_exec(duration=-1)
    executor.start_time -= 1e6  # any elapsed time

    async def run():
        await executor._pre_exec()
        assert (await executor._poll())["status"] == HloStatus.active
        # manual stop path: runner calls _manual_stop then _post_exec
        await executor._manual_stop()
        await executor._post_exec()

    asyncio.run(run())
    assert driver.do_state["trigger_out"] is False
    assert driver.writes[-1][2] is False


def test_ttl_exec_setup_failure_is_reported():
    executor, driver = _make_exec(duration=1)

    driver.fail = True
    assert asyncio.run(executor._pre_exec())["error"] == ErrorCodes.cmd_error


def test_estop_drives_ttl_lines_low():
    writes = []

    class _Recording(cNIMAX):
        async def set_digital_out(self, do_port=None, do_name="", on=False, **kw):
            writes.append((do_name, on))
            return {}

    driver = _Recording.__new__(_Recording)  # no connect(), no NI-DAQmx import
    driver.dev_led = driver.dev_pump = driver.dev_gasvalve = {}
    driver.dev_liquidvalve = driver.dev_heat = {}
    driver.dev_ttl = DEV_TTL
    driver.IO_measuring = False
    asyncio.run(driver.estop(True))
    assert sorted(writes) == [("shutter", False), ("trigger_out", False)]


# --------------------------------------------------------------------------
# server routes
# --------------------------------------------------------------------------


def _build_app(monkeypatch, server_params) -> Any:
    from helao.deploy.hte.servers.action import nidaqmx_server

    class _FakeHost:
        def __init__(self, **kwargs):
            self.server_params = server_params
            self.driver = _FakeDriver(server_params.get("dev_ttl", {}))
            self.executors = {}
            self.routes = {}

        def action(self, **kwargs):
            def deco(fn):
                self.routes[fn.__name__] = fn
                return fn

            return deco

        def post(self, path, **kwargs):
            def deco(fn):
                self.routes[path] = fn
                return fn

            return deco

    monkeypatch.setattr(nidaqmx_server, "ActionHost", _FakeHost)
    return nidaqmx_server.makeApp("NI")


def _ctx(app, **params):
    session = _FakeSession(app.driver, params, app.executors)

    async def begin(**kwargs):
        return session

    return SimpleNamespace(action=session.action, begin=begin), session


def test_ttl_routes_only_exist_when_dev_ttl_configured(monkeypatch):
    assert "toggle_ttl" not in _build_app(monkeypatch, {}).routes
    app = _build_app(monkeypatch, {"dev_ttl": DEV_TTL})
    assert {"toggle_ttl", "cancel_toggle_ttl"} <= set(app.routes)


def test_toggle_ttl_starts_executor_and_refuses_a_second_hold(monkeypatch):
    app = _build_app(monkeypatch, {"dev_ttl": DEV_TTL})
    ctx, session = _ctx(app, ttl="trigger_out", duration=-1)
    result = asyncio.run(app.routes["toggle_ttl"](ctx))
    assert "started" in result
    assert isinstance(session.executor, TTLExec)

    ctx2, session2 = _ctx(app, ttl="trigger_out", duration=5)
    result2 = asyncio.run(app.routes["toggle_ttl"](ctx2))
    assert result2["error_code"] == ErrorCodes.in_progress
    assert session2.executor is None

    # a different line is independent
    ctx3, session3 = _ctx(app, ttl="shutter", duration=5)
    asyncio.run(app.routes["toggle_ttl"](ctx3))
    assert session3.executor is not None


def test_cancel_toggle_ttl_filters_by_line(monkeypatch):
    app = _build_app(monkeypatch, {"dev_ttl": DEV_TTL})
    sessions = {}
    for ttl in DEV_TTL:
        ctx, sessions[ttl] = _ctx(app, ttl=ttl, duration=-1)
        asyncio.run(app.routes["toggle_ttl"](ctx))

    cancel_ctx, _ = _ctx(app, ttl="trigger_out")
    asyncio.run(app.routes["cancel_toggle_ttl"](cancel_ctx))
    assert sessions["trigger_out"].stopped and not sessions["shutter"].stopped

    cancel_all, _ = _ctx(app, ttl=None)
    asyncio.run(app.routes["cancel_toggle_ttl"](cancel_all))
    assert sessions["shutter"].stopped
