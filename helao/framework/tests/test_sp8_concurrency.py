"""SP8 WS-E: action-collision concurrency middleware + estop exception handler.

Covers the production middleware/exception surface added to the framework
``BaseAPI`` (ports ``helao.core.servers.base_api`` ``_make_app_entry_middleware``
and ``_make_http_exception_handler``):

* a ``HEAD`` request is short-circuited to a bare ``200`` by the middleware;
* an action ``POST`` to an idle endpoint reaches the endpoint and returns ``200``
  with the request body still readable downstream (body-reread is non-destructive);
* when the endpoint is busy **and** ``allow_concurrent_actions`` is false, the
  middleware returns the action as queued (``queued_on_actserv``) without executing
  the endpoint (queued-return — the framework has no later-dispatch loop to drain a
  real queue, so the legacy HTTP contract is preserved at the boundary);
* an unhandled exception raised inside a routed action endpoint e-stops every
  in-flight ``ActionSession`` (``estopped`` status + ``estop`` error code) and every
  running executor, returning a ``500``.
"""
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from helao.framework.app.server_api import BaseAPI
from helao.framework.domain.run_models import RunAction
from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus


# --- HEAD short-circuit -------------------------------------------------------


def test_head_request_passes_through_to_200(tmp_path):
    """A HEAD request returns a bare 200 from the middleware (no-op)."""
    app = BaseAPI("SRV", save_root=str(tmp_path))

    @app.post("/SRV/do_thing", tags=["action"])
    async def do_thing():
        return await app.base.setup_and_contain_action()

    with TestClient(app) as client:
        resp = client.head("/SRV/do_thing")
    assert resp.status_code == 200


# --- idle endpoint pass-through + body re-read --------------------------------


def test_action_post_idle_endpoint_reaches_endpoint_and_body_readable(tmp_path):
    """An action POST to an idle endpoint runs and the body is still readable."""
    app = BaseAPI("SRV", save_root=str(tmp_path))
    seen = {}

    # endpoint declares no action param -> the wrapper injects an embedded
    # ``action`` body param, so the orchestrator-shaped ``{"action": {...}}``
    # payload (which the middleware already consumed) must still parse and reach
    # ``setup_and_contain_action`` with its action_params intact.
    @app.post("/SRV/do_thing", tags=["action"])
    async def do_thing():
        active = await app.base.setup_and_contain_action()
        seen["duration"] = active.action.action_params.get("duration")
        return (await active.finish()).as_dict()

    with TestClient(app) as client:
        resp = client.post(
            "/SRV/do_thing",
            json={"action": {"action_params": {"duration": 0.1}}},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["action_name"] == "do_thing"
    # the body the middleware already consumed still reached the endpoint:
    # action_params survived the downstream re-read + parse.
    assert seen["duration"] == 0.1


def test_action_post_idle_endpoint_under_asgi_transport(tmp_path):
    """Body re-read holds under httpx ASGITransport (the wssim test path)."""
    app = BaseAPI("SRV", save_root=str(tmp_path))

    @app.post("/SRV/do_thing", tags=["action"])
    async def do_thing(action: RunAction):
        active = await app.base.setup_and_contain_action()
        return (await active.finish()).as_dict()

    async def _drive():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/SRV/do_thing", json={"action": {"action_params": {}}}
            )

    resp = asyncio.run(_drive())
    assert resp.status_code == 200, resp.text
    assert resp.json()["action_name"] == "do_thing"


# --- busy endpoint, concurrency disabled -> queued-return ---------------------


def test_busy_endpoint_no_concurrency_returns_queued_without_executing(tmp_path):
    """When busy + concurrency disabled, the action is returned queued, not run."""
    app = BaseAPI("SRV", save_root=str(tmp_path))
    # disable concurrency (legacy gate) on the live base.
    app.base.server_params["allow_concurrent_actions"] = False

    ran = {"count": 0}

    @app.post("/SRV/do_thing", tags=["action"])
    async def do_thing(action: RunAction):
        ran["count"] += 1
        active = await app.base.setup_and_contain_action()
        return (await active.finish()).as_dict()

    with TestClient(app) as client:
        # mark the endpoint busy: a live active entry in the status model.
        from helao.framework.models.action import ActionModel
        import uuid

        em = app.base.actionservermodel.endpoints["do_thing"]
        busy_uuid = uuid.uuid4()
        em.active_dict[busy_uuid] = ActionModel(
            action_uuid=busy_uuid, action_name="do_thing"
        )

        resp = client.post(
            "/SRV/do_thing", json={"action": {"action_params": {}}}
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # queued marker stamped, endpoint body never ran
    assert body["action_params"].get("queued_on_actserv") is True
    assert ran["count"] == 0


def test_busy_endpoint_concurrency_allowed_passes_through(tmp_path):
    """With concurrency allowed (default), a busy endpoint still runs."""
    app = BaseAPI("SRV", save_root=str(tmp_path))

    ran = {"count": 0}

    @app.post("/SRV/do_thing", tags=["action"])
    async def do_thing(action: RunAction):
        ran["count"] += 1
        active = await app.base.setup_and_contain_action()
        return (await active.finish()).as_dict()

    with TestClient(app) as client:
        from helao.framework.models.action import ActionModel
        import uuid

        em = app.base.actionservermodel.endpoints["do_thing"]
        busy_uuid = uuid.uuid4()
        em.active_dict[busy_uuid] = ActionModel(
            action_uuid=busy_uuid, action_name="do_thing"
        )
        resp = client.post("/SRV/do_thing", json={"action": {"action_params": {}}})

    assert resp.status_code == 200, resp.text
    assert ran["count"] == 1


# --- unhandled exception -> estop ---------------------------------------------


def test_unhandled_exception_estops_actives_and_executors_returns_500(tmp_path):
    """An exception in an action endpoint e-stops actives/executors and 500s."""
    app = BaseAPI("SRV", save_root=str(tmp_path))

    class _FakeSession:
        def __init__(self):
            self.stopped = False
            self.action = RunAction()

        def stop_action_task(self):
            self.stopped = True

    # pre-seed an in-flight active and a running executor
    active_session = _FakeSession()
    app.base.actives[active_session.action.action_uuid] = active_session
    exec_session = _FakeSession()
    app.base.executors["exec-1"] = exec_session

    @app.post("/SRV/boom", tags=["action"])
    async def boom(action: RunAction):
        raise ValueError("kaboom")

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post("/SRV/boom", json={"action": {"action_params": {}}})

    assert resp.status_code == 500
    # active session e-stopped
    assert HloStatus.estopped in active_session.action.action_status
    assert active_session.action.error_code == ErrorCodes.estop
    assert active_session.stopped is True
    # running executor signalled to stop
    assert exec_session.stopped is True


def test_estop_only_fires_for_routed_action_path(tmp_path):
    """A non-action route error must not e-stop the action machinery."""
    app = BaseAPI("SRV", save_root=str(tmp_path))

    class _FakeSession:
        def __init__(self):
            self.stopped = False
            self.action = RunAction()

        def stop_action_task(self):
            self.stopped = True

    active_session = _FakeSession()
    app.base.actives[active_session.action.action_uuid] = active_session

    @app.post("/not_action_boom", tags=["private"])
    async def boom():
        raise ValueError("kaboom")

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post("/not_action_boom")

    assert resp.status_code == 500
    # path did not start with /SRV/ -> active untouched
    assert HloStatus.estopped not in active_session.action.action_status
    assert active_session.stopped is False
