"""Action-server host tests for ``app/base_api.py`` (SP7 Wave 2 Task D).

Covers the new FastAPI-facing surface:

* **T-wrap** — :func:`wrap_action_endpoint` sets/resets :data:`ACTION_CTX`
  around the call, and :func:`_build_action_from_kwargs` folds extra kwargs into
  ``action_params`` (the ported legacy behaviour).
* **T-host** — :class:`BaseAPI` builds a :class:`FrameworkBase`, instantiates a
  bare-helper driver against the base positionally, and exposes ``drivers`` /
  ``driver``.
* **T-action-endpoint** — an ``@app.post(..., tags=["action"])`` endpoint that
  calls the **no-arg** ``app.state.base.setup_and_contain_action()`` runs an
  action end-to-end driven in-process via ``httpx`` ASGITransport, proving the
  ACTION_CTX auto-wrap path.
"""
import asyncio
import uuid as _uuid
from datetime import datetime

import httpx
import pytest

from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.domain.run_models import RunAction
from helao.framework.domain.executor import Executor
from helao.framework.app.base_api import (
    ACTION_CTX,
    ActionContext,
    BaseAPI,
    FrameworkBase,
    wrap_action_endpoint,
    _build_action_from_kwargs,
)
from helao.framework.tests.conftest import asgi_lifespan


# --- T-wrap ----------------------------------------------------------------


def test_build_action_from_kwargs_folds_extra_into_params():
    action = RunAction(action_name="seed")
    built = _build_action_from_kwargs({"action": action, "extra": 7, "foo": "bar"})
    assert built is action
    assert built.action_params["extra"] == 7
    assert built.action_params["foo"] == "bar"


def test_build_action_from_kwargs_blank_when_no_action():
    built = _build_action_from_kwargs({"x": 1})
    assert isinstance(built, RunAction)
    assert built.action_params["x"] == 1


def test_wrap_action_endpoint_sets_and_resets_action_ctx():
    seen = {}

    async def endpoint(action: RunAction):
        ctx = ACTION_CTX.get()
        seen["ctx"] = ctx
        seen["endpoint_name"] = ctx.endpoint_name
        seen["action"] = ctx.action
        return "ok"

    wrapped = wrap_action_endpoint(endpoint)
    action = RunAction(action_name="wrapme")

    assert ACTION_CTX.get() is None
    result = asyncio.run(wrapped(action=action))
    assert result == "ok"
    # ctx populated during the call, with the endpoint name + the action
    assert isinstance(seen["ctx"], ActionContext)
    assert seen["endpoint_name"] == "endpoint"
    assert seen["action"] is action
    # reset after the call
    assert ACTION_CTX.get() is None


def test_wrap_action_endpoint_folds_extra_kwargs_into_params():
    captured = {}

    async def endpoint(action: RunAction, gain: int = 0):
        captured["action"] = ACTION_CTX.get().action
        return "ok"

    wrapped = wrap_action_endpoint(endpoint)
    action = RunAction(action_name="wrapme")
    asyncio.run(wrapped(action=action, gain=5))
    assert captured["action"].action_params["gain"] == 5


# --- T-host ----------------------------------------------------------------


class FakeBareDriver:
    """A bare-helper driver (not a ``HelaoDriver`` ABC) that stores the base."""

    def __init__(self, base):
        self.base = base


@pytest.mark.asyncio
async def test_baseapi_builds_base_and_bare_driver(tmp_path):
    app = BaseAPI(
        server_key="SIM",
        driver_classes=[FakeBareDriver],
        save_root=str(tmp_path),
    )
    assert isinstance(app.base, FrameworkBase)
    assert app.base.server_key == "SIM"
    # drivers are deferred to the startup hook (SP8 WS-C lifecycle); drive the
    # app through the ASGI lifespan to fire startup before asserting.
    async with asgi_lifespan(app):
        # driver instantiated, exposed via drivers + driver
        assert isinstance(app.driver, FakeBareDriver)
        assert app.drivers[0] is app.driver
        # bare helper got the base positionally
        assert app.driver.base is app.base


@pytest.mark.asyncio
async def test_baseapi_no_drivers(tmp_path):
    app = BaseAPI(server_key="SIM", save_root=str(tmp_path))
    async with asgi_lifespan(app):
        assert app.drivers == tuple()
        assert app.driver is None


def test_baseapi_dyn_endpoints_invoked(tmp_path):
    received = {}

    def dyn(app):
        received["app"] = app

    app = BaseAPI(
        server_key="SIM", save_root=str(tmp_path), dyn_endpoints=dyn
    )
    assert received["app"] is app


# --- T-action-endpoint -----------------------------------------------------


def _register_do_endpoint(app, server_key):
    """Register an action endpoint that drives a oneoff executor end-to-end.

    The endpoint takes an ``action`` param (so the route wrapper rebuilds a
    :class:`RunAction` into :data:`ACTION_CTX`), then calls the **no-arg**
    ``setup_and_contain_action()`` to prove the auto-wrap path.
    """

    @app.post(f"/{server_key}/do", tags=["action"])
    async def do(action: RunAction):
        now = datetime.now()
        # the route wrapper already set ACTION_CTX from the request body; fill in
        # the minimal runtime identity the lifecycle needs.
        ctx_action = ACTION_CTX.get().action
        file_conn = _uuid.uuid4()
        ctx_action.action_uuid = _uuid.uuid4()
        ctx_action.action_timestamp = now
        ctx_action.sequence_timestamp = now
        ctx_action.experiment_timestamp = now
        ctx_action.sequence_name = "seq"
        ctx_action.experiment_name = "exp"
        ctx_action.action_output_dir = f"{ctx_action.action_uuid}"
        ctx_action.save_act = True
        ctx_action.save_data = True
        ctx_action.file_conn_keys = [file_conn]

        active = await app.state.base.setup_and_contain_action(header="epoch_ns: 1")
        await active.open_file(file_conn, header="epoch_ns: 1")

        executor = Executor(active=active)

        async def _exec(self):
            return {"data": {"value": 1}, "error": ErrorCodes.none}

        executor.set_exec(_exec)
        result = await active.action_loop_task(executor)
        status = (
            "finished"
            if HloStatus.finished in result.action_status
            else str(result.action_status)
        )
        return {"uuid": str(result.action_uuid), "status": status}


@pytest.mark.asyncio
async def test_action_endpoint_no_arg_ctx_end_to_end(tmp_path):
    app = BaseAPI(server_key="SIM", save_root=str(tmp_path))
    _register_do_endpoint(app, "SIM")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        resp = await client.post("/SIM/do", json={"action": {"action_name": "do"}})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "finished"
    assert body["uuid"]
    # the endpoint produced an HLO file on disk via the no-arg ctx path
    assert list(tmp_path.rglob("*.hlo")), "endpoint wrote no .hlo file"
