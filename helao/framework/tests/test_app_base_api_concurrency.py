"""Concurrency-middleware + estop-handler tests for ``app/base_api.py`` (SP8 WS-E).

Covers the action-collision ``app_entry`` middleware, the queue structures on
:class:`FrameworkBase`, the queue-drain wiring in the status push loop, and the
e-stop HTTP exception handler.

ANTI-HANG DISCIPLINE: the Sonnet-era WS-E middleware was the suspected cause of a
pytest hang (body re-read vs the status drain). EVERY test that drives a request
through the middleware is wrapped in ``asyncio.wait_for(...)`` so a hang fails
fast (raises ``TimeoutError``) instead of blocking the suite.
"""
import asyncio
import uuid as _uuid
from datetime import datetime

import httpx
import pytest

from helao.framework.models.action import ActionModel
from helao.framework.models.action_start_condition import ActionStartCondition
from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.domain.run_models import RunAction
from helao.framework.domain.executor import Executor
from helao.framework.app.base_api import (
    ACTION_CTX,
    BaseAPI,
    FrameworkBase,
)
from helao.framework.tests.conftest import asgi_lifespan

#: hard ceiling for any request driven through the middleware (anti-hang guard).
REQ_TIMEOUT = 8.0


def _register_do_endpoint(app, server_key, *, ran):
    """Register an action endpoint that records that it actually ran."""

    @app.post(f"/{server_key}/do", tags=["action"])
    async def do(action: RunAction):
        now = datetime.now()
        ctx_action = ACTION_CTX.get().action
        ctx_action.action_uuid = _uuid.uuid4()
        ctx_action.action_timestamp = now
        ctx_action.sequence_timestamp = now
        ctx_action.experiment_timestamp = now
        ctx_action.sequence_name = "seq"
        ctx_action.experiment_name = "exp"
        ctx_action.action_output_dir = f"{ctx_action.action_uuid}"
        ctx_action.save_act = False
        ctx_action.save_data = False
        active = await app.state.base.setup_and_contain_action()
        executor = Executor(active=active)

        async def _exec(self):
            return {"data": {}, "error": ErrorCodes.none}

        executor.set_exec(_exec)
        result = await active.action_loop_task(executor)
        ran.append(result.action_uuid)
        status = (
            "finished"
            if HloStatus.finished in result.action_status
            else str(result.action_status)
        )
        return {"uuid": str(result.action_uuid), "status": status, "ran": True}


# --- passthrough: THE anti-hang test --------------------------------------


@pytest.mark.asyncio
async def test_passthrough_idle_endpoint_runs_and_returns(tmp_path):
    """POST to an idle endpoint passes through the middleware and runs (no hang)."""
    ran = []
    app = BaseAPI(server_key="SIM", save_root=str(tmp_path))
    _register_do_endpoint(app, "SIM", ran=ran)

    async with asgi_lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await asyncio.wait_for(
                client.post("/SIM/do", json={"action": {"action_name": "do"}}),
                timeout=REQ_TIMEOUT,
            )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ran"] is True
    assert body["status"] == "finished"
    # the endpoint body re-read the action from the (rewound) request body
    assert len(ran) == 1


@pytest.mark.asyncio
async def test_head_request_returns_200_via_middleware(tmp_path):
    """A bare HEAD probe returns 200 immediately (no call_next, no hang)."""
    app = BaseAPI(server_key="SIM", save_root=str(tmp_path))
    _register_do_endpoint(app, "SIM", ran=[])
    async with asgi_lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await asyncio.wait_for(
                client.head("/SIM/do"), timeout=REQ_TIMEOUT
            )
    assert resp.status_code == 200


# --- collision (same endpoint busy) ---------------------------------------


@pytest.mark.asyncio
async def test_collision_same_endpoint_is_queued(tmp_path):
    """With the endpoint's active_dict pre-populated, a POST is queued not run."""
    ran = []
    app = BaseAPI(server_key="SIM", save_root=str(tmp_path))
    _register_do_endpoint(app, "SIM", ran=ran)

    async with asgi_lifespan(app):
        base = app.base
        # subscribe BEFORE the request so we can observe the queued-action emit
        status_q = base.eventsink.subscribe()
        # mark the endpoint busy with a fake active action
        busy = ActionModel(action_name="do", action_uuid=_uuid.uuid4())
        base.actionservermodel.endpoints["do"].active_dict[busy.action_uuid] = busy

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await asyncio.wait_for(
                client.post("/SIM/do", json={"action": {"action_name": "do"}}),
                timeout=REQ_TIMEOUT,
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # queued: the action dict is returned, the endpoint did NOT run
        assert body.get("ran") is None or "ran" not in body
        assert body["action_params"]["queued_on_actserv"] is True
        # landed in the per-endpoint queue
        assert len(base.endpoint_queues["do"]) == 1
        queued_action, _ = base.endpoint_queues["do"][0]
        assert queued_action.action_name == "do"
        # the endpoint body never ran
        assert ran == []
        # status was emitted for the queued action (channel, payload)
        channel, payload = await asyncio.wait_for(status_q.get(), timeout=1.0)
        assert payload["action_params"]["queued_on_actserv"] is True


# --- allow_concurrent_actions False -> unified queue ----------------------


@pytest.mark.asyncio
async def test_concurrency_disabled_busy_uses_unified_queue(tmp_path):
    """allow_concurrent_actions False + any endpoint busy -> local_action_queue."""
    ran = []
    app = BaseAPI(server_key="SIM", save_root=str(tmp_path))
    _register_do_endpoint(app, "SIM", ran=ran)

    async with asgi_lifespan(app):
        base = app.base
        base.server_params["allow_concurrent_actions"] = False
        # the target endpoint itself is busy (so the idle short-circuit is not
        # taken) AND concurrency is disabled -> the unified queue is used rather
        # than the per-endpoint queue.
        busy = ActionModel(action_name="do", action_uuid=_uuid.uuid4())
        base.actionservermodel.endpoints["do"].active_dict[busy.action_uuid] = busy

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await asyncio.wait_for(
                client.post("/SIM/do", json={"action": {"action_name": "do"}}),
                timeout=REQ_TIMEOUT,
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["action_params"]["queued_on_actserv"] is True
        # unified queue, not the endpoint queue
        assert len(base.local_action_queue) == 1
        assert len(base.endpoint_queues["do"]) == 0
        assert ran == []


# --- estop handler --------------------------------------------------------


class _FakeExecutor:
    """Minimal executor stand-in recording ``stop_action_task`` calls."""

    def __init__(self, exec_id):
        self.exec_id = exec_id
        self.stopped = False

    def stop_action_task(self):
        self.stopped = True


class _FakeActive:
    """ActionSession stand-in recording set_estop calls."""

    def __init__(self):
        self.estopped = False
        self.action = RunAction(action_name="x", action_uuid=_uuid.uuid4())

    def set_estop(self):
        self.estopped = True
        self.action.action_status.append(HloStatus.estopped)


@pytest.mark.asyncio
async def test_estop_handler_stops_actives_and_executors(tmp_path):
    """An endpoint that raises triggers set_estop on actives + stop on executors."""
    app = BaseAPI(server_key="SIM", save_root=str(tmp_path))

    @app.post("/SIM/boom", tags=["action"])
    async def boom(action: RunAction):
        raise RuntimeError("kaboom")

    async with asgi_lifespan(app):
        base = app.base
        fake_active = _FakeActive()
        fake_exec = _FakeExecutor("e1")
        base.actives[fake_active.action.action_uuid] = fake_active
        base.executors["e1"] = fake_exec

        transport = httpx.ASGITransport(
            app=app, raise_app_exceptions=False
        )
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await asyncio.wait_for(
                client.post("/SIM/boom", json={"action": {"action_name": "boom"}}),
                timeout=REQ_TIMEOUT,
            )
        # default handler turns it into a 500
        assert resp.status_code == 500
        assert fake_active.estopped is True
        assert fake_exec.stopped is True


# --- queue drain ----------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_drain_dispatches_queued_action(tmp_path):
    """A queued action is drained (dispatched) when the endpoint goes idle.

    Drives the status-push drain directly: enqueue one action onto the endpoint
    queue, then feed a 'finished' status emission so the drain block fires and
    calls ``process_endpoint_queue``. The framework re-dispatch is in-process via
    a recorded dispatch hook (see what was implemented in the module docstring).
    """
    app = BaseAPI(server_key="SIM", save_root=str(tmp_path))
    _register_do_endpoint(app, "SIM", ran=[])
    dispatched = []

    async with asgi_lifespan(app):
        base = app.base
        # record what the drain re-dispatches instead of doing a real HTTP POST
        async def _record(action, extra):
            dispatched.append(action)

        base._redispatch_queued = _record  # type: ignore[attr-defined]

        # enqueue a queued action on the 'do' endpoint
        qact = RunAction(action_name="do", action_uuid=_uuid.uuid4())
        qact.action_params["queued_on_actserv"] = True
        base.endpoint_queues["do"].append((qact, {}))

        # emit a finished status for 'do' so the drain sees an idle endpoint
        finished = ActionModel(
            action_name="do",
            action_uuid=_uuid.uuid4(),
            action_status=[HloStatus.finished],
        )
        await base.eventsink.emit_status(finished.as_dict())

        # give the status-push task a few cooperative turns to drain
        for _ in range(50):
            if dispatched:
                break
            await asyncio.sleep(0.01)

    assert len(dispatched) == 1
    assert dispatched[0].action_name == "do"
    # the queue was consumed
    assert len(base.endpoint_queues["do"]) == 0
