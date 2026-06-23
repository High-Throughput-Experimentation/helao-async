"""Admin/private endpoint tests for ``app/base_api.py`` (SP8 WS-B).

Covers the legacy-named admin endpoints mirrored onto :class:`BaseAPI`:
``get_status`` / ``get_config`` / ``endpoints`` / ``get_lbuf`` /
``list_executors`` / ``stop_executor`` / ``resend_active`` / ``shutdown``, the
``estop`` / ``stop`` action endpoints, and the HEAD mirror for every POST route
(used by the dispatcher's ``endpoints_available`` HEAD probes).

All endpoints are driven in-process via ``httpx`` ASGITransport.
"""
import asyncio
import uuid as _uuid

import httpx
import pytest

from helao.framework.domain.run_models import RunAction
from helao.framework.domain.executor import Executor
from helao.framework.app.base_api import BaseAPI
from helao.framework.tests.conftest import asgi_lifespan


def _make_app(tmp_path):
    return BaseAPI(server_key="SIM", save_root=str(tmp_path))


async def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# --- get_status -------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_status_reflects_actionservermodel(tmp_path):
    app = _make_app(tmp_path)
    async with asgi_lifespan(app):
        async with await _client(app) as client:
            resp = await client.post("/get_status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # the action-server model dump names this server
    assert body["action_server"]["server_name"] == "SIM"
    # driver status appended even when no driver is wired
    assert "_driver_status" in body


# --- get_config -------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_config_returns_server_cfg(tmp_path):
    app = _make_app(tmp_path)
    app.base.server_cfg["params"] = {"foo": 1}
    async with asgi_lifespan(app):
        async with await _client(app) as client:
            resp = await client.post("/get_config")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["params"]["foo"] == 1


# --- endpoints --------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoints_returns_fast_urls(tmp_path):
    app = _make_app(tmp_path)

    @app.post("/SIM/do", tags=["action"])
    async def do(action: RunAction):
        return {}

    async with asgi_lifespan(app):
        async with await _client(app) as client:
            resp = await client.post("/endpoints")
    assert resp.status_code == 200, resp.text
    paths = [u["path"] for u in resp.json()]
    assert "/SIM/do" in paths


# --- get_lbuf ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_lbuf_after_put_and_drain(tmp_path):
    app = _make_app(tmp_path)
    async with asgi_lifespan(app):
        base = app.base
        # put a value and let the live-buffer drain fold it in
        await base.put_lbuf({"chan": 42})
        for _ in range(100):
            if "chan" in base.live_buffer:
                break
            await asyncio.sleep(0.01)
        async with await _client(app) as client:
            resp = await client.post("/get_lbuf", json={"live_key": "chan"})
    assert resp.status_code == 200, resp.text
    val = resp.json()
    # value is the (value, timestamp) tuple -> list over JSON
    assert val[0] == 42


@pytest.mark.asyncio
async def test_get_lbuf_missing_key_returns_null(tmp_path):
    app = _make_app(tmp_path)
    async with asgi_lifespan(app):
        async with await _client(app) as client:
            resp = await client.post(
                "/get_lbuf", json={"live_key": "nope"}
            )
    assert resp.status_code == 200, resp.text
    assert resp.json() is None


# --- list_executors / stop_executor -----------------------------------------


class _FakeExecutor:
    def __init__(self):
        self.stopped = False

    def stop_action_task(self):
        self.stopped = True


@pytest.mark.asyncio
async def test_list_executors_returns_ids(tmp_path):
    app = _make_app(tmp_path)
    app.base.executors["exec-1"] = _FakeExecutor()
    async with asgi_lifespan(app):
        async with await _client(app) as client:
            resp = await client.post("/list_executors")
    assert resp.status_code == 200, resp.text
    assert "exec-1" in resp.json()


@pytest.mark.asyncio
async def test_stop_executor_calls_stop_and_reports_ok(tmp_path):
    app = _make_app(tmp_path)
    fake = _FakeExecutor()
    app.base.executors["exec-1"] = fake
    async with asgi_lifespan(app):
        async with await _client(app) as client:
            resp = await client.post(
                "/stop_executor", json={"executor_id": "exec-1"}
            )
    assert resp.status_code == 200, resp.text
    assert resp.json()["stopped"] is True
    assert fake.stopped is True


@pytest.mark.asyncio
async def test_stop_executor_missing_reports_missing(tmp_path):
    app = _make_app(tmp_path)
    async with asgi_lifespan(app):
        async with await _client(app) as client:
            resp = await client.post(
                "/stop_executor", json={"executor_id": "nope"}
            )
    assert resp.status_code == 200, resp.text
    assert resp.json()["stopped"] is False


# --- resend_active ----------------------------------------------------------


@pytest.mark.asyncio
async def test_resend_active_returns_active_dict(tmp_path):
    app = _make_app(tmp_path)
    base = app.base
    action = RunAction(action_name="do")
    action.action_uuid = _uuid.uuid4()

    class _Sess:
        def __init__(self, a):
            self.action = a

    base.actives[action.action_uuid] = _Sess(action)
    async with asgi_lifespan(app):
        async with await _client(app) as client:
            resp = await client.post(
                "/resend_active",
                json={"action_uuid": str(action.action_uuid)},
            )
    assert resp.status_code == 200, resp.text
    assert resp.json()["action_name"] == "do"


@pytest.mark.asyncio
async def test_resend_active_missing_returns_null(tmp_path):
    app = _make_app(tmp_path)
    async with asgi_lifespan(app):
        async with await _client(app) as client:
            resp = await client.post(
                "/resend_active",
                json={"action_uuid": str(_uuid.uuid4())},
            )
    assert resp.status_code == 200, resp.text
    assert resp.json() is None


# --- shutdown ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_returns_ok(tmp_path):
    app = _make_app(tmp_path)
    async with asgi_lifespan(app):
        async with await _client(app) as client:
            resp = await client.post("/shutdown")
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


# --- estop / stop -----------------------------------------------------------


@pytest.mark.asyncio
async def test_estop_latches_flag_and_stops_executors(tmp_path):
    app = _make_app(tmp_path)
    fake = _FakeExecutor()
    app.base.executors["exec-1"] = fake
    async with asgi_lifespan(app):
        async with await _client(app) as client:
            resp = await client.post("/SIM/estop", json={"switch": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["estop"] is True
    assert app.base.actionservermodel.estop is True
    assert fake.stopped is True


@pytest.mark.asyncio
async def test_stop_stops_all_executors(tmp_path):
    app = _make_app(tmp_path)
    fake = _FakeExecutor()
    app.base.executors["exec-1"] = fake
    async with asgi_lifespan(app):
        async with await _client(app) as client:
            resp = await client.post("/SIM/stop")
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert fake.stopped is True


# --- HEAD mirror ------------------------------------------------------------


@pytest.mark.asyncio
async def test_head_on_post_action_route_returns_200(tmp_path):
    app = _make_app(tmp_path)

    @app.post("/SIM/do", tags=["action"])
    async def do(action: RunAction):
        return {}

    async with asgi_lifespan(app):
        async with await _client(app) as client:
            resp = await client.head("/SIM/do")
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_head_on_admin_route_returns_200(tmp_path):
    app = _make_app(tmp_path)
    async with asgi_lifespan(app):
        async with await _client(app) as client:
            resp = await client.head("/get_status")
    assert resp.status_code == 200, resp.text
