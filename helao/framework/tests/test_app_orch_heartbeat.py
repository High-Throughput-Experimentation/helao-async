"""Orchestrator status heartbeat (transport dispatch -> status_summary)."""
import asyncio

from helao.framework.adapters.fakes.transport import FakeTransport
from helao.framework.app.factory import makeApp
from helao.framework.models.errors import ErrorCodes
from helao.framework.ports.transport import DispatchResult


def _app(tmp_path, transport, action_servers):
    return makeApp("ORCH", save_root=str(tmp_path), group="orchestrator",
                   transport=transport, action_servers=action_servers)


def test_heartbeat_once_populates_status_summary(tmp_path):
    transport = FakeTransport()
    transport.script_by_endpoint["get_status"] = DispatchResult(
        response={"_driver_status": "ok",
                  "endpoints": {"run": {"active_dict": {"a": 1}}}},
        error=ErrorCodes.none,
    )
    app = _app(tmp_path, transport, {"MOTOR": {"host": "h", "port": 1}})
    driver = app.state.driver
    asyncio.run(driver._heartbeat_once())
    assert driver.state.status_summary["MOTOR"] == ("busy [run]", "ok")


def test_heartbeat_once_unreachable(tmp_path):
    transport = FakeTransport()
    transport.script_by_endpoint["get_status"] = DispatchResult(
        response=None, error=ErrorCodes.http,
    )
    app = _app(tmp_path, transport, {"MOTOR": {"host": "h", "port": 1}})
    driver = app.state.driver
    asyncio.run(driver._heartbeat_once())
    assert driver.state.status_summary["MOTOR"] == ("unreachable", "unknown")


def test_start_heartbeat_noop_when_no_servers(tmp_path):
    app = _app(tmp_path, FakeTransport(), {})
    driver = app.state.driver
    driver.start_heartbeat()
    assert getattr(driver, "_heartbeat_task", None) is None
    driver.stop_heartbeat()  # idempotent, no error


def test_get_status_summary_endpoint_reflects_heartbeat(tmp_path):
    from fastapi.testclient import TestClient
    transport = FakeTransport()
    transport.script_by_endpoint["get_status"] = DispatchResult(
        response={"_driver_status": "ok", "endpoints": {}}, error=ErrorCodes.none,
    )
    app = _app(tmp_path, transport, {"MOTOR": {"host": "h", "port": 1}})
    driver = app.state.driver
    asyncio.run(driver._heartbeat_once())
    client = TestClient(app)
    assert client.post("/get_status_summary").json() == {"MOTOR": ["idle", "ok"]}


def test_heartbeat_loop_survives_pass_exception(tmp_path):
    """A failing _heartbeat_once must not kill the loop (it logs + continues)."""
    import asyncio
    app = _app(tmp_path, FakeTransport(), {"MOTOR": {"host": "h", "port": 1}})
    driver = app.state.driver
    driver.heartbeat_interval = 0.01

    calls = {"n": 0}

    async def boom():
        calls["n"] += 1
        raise RuntimeError("transient ping failure")

    driver._heartbeat_once = boom

    async def _drive():
        driver.start_heartbeat()
        await asyncio.sleep(0.05)  # allow several loop iterations
        driver.stop_heartbeat()

    asyncio.run(_drive())
    assert calls["n"] >= 2, "loop did not survive the exception to retry"


def test_start_heartbeat_idempotent_and_schedules(tmp_path):
    """start_heartbeat creates one task for non-empty servers and is idempotent."""
    import asyncio
    app = _app(tmp_path, FakeTransport(), {"MOTOR": {"host": "h", "port": 1}})
    driver = app.state.driver
    driver.heartbeat_interval = 10.0  # keep the loop parked in sleep

    async def _drive():
        driver.start_heartbeat()
        task1 = driver._heartbeat_task
        assert task1 is not None and not task1.done()
        driver.start_heartbeat()  # idempotent: no new task
        assert driver._heartbeat_task is task1
        driver.stop_heartbeat()
        assert driver._heartbeat_task is None

    asyncio.run(_drive())
