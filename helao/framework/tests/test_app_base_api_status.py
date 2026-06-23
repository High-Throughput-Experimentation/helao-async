"""Action-server status-model + orch-push tests (SP8 Wave-1 WS-A).

Covers the orchestrator status-push surface wired onto :class:`FrameworkBase` /
:class:`BaseAPI`:

* **attach_client / detach_client** — subscriber-set bookkeeping + initial
  snapshot push via the (monkeypatched) dispatcher.
* **send_statuspackage / send_nbstatuspackage** — POST shape to the orch's
  ``update_status`` / ``update_nonblocking`` private endpoints.
* **init_endpoint_status** — registers an ``EndpointModel`` per ``/{server_key}/*``
  route.
* **END-TO-END** — driving an action through ``setup_and_contain_action`` + a
  oneoff executor causes the base's status drain to POST a status package whose
  ``actionservermodel`` shows the action in a terminal (finished) status.
"""
import asyncio
import uuid as _uuid
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.domain.run_models import RunAction
from helao.framework.domain.executor import Executor
from helao.framework.app import base_api as base_api_mod
from helao.framework.app.base_api import (
    ACTION_CTX,
    BaseAPI,
    FrameworkBase,
)


def _make_base(tmp_path, **cfg) -> FrameworkBase:
    """Build a BaseAPI and return its FrameworkBase, optionally with server_cfg."""
    app = BaseAPI(server_key="SIM", save_root=str(tmp_path))
    if cfg:
        app.base.server_cfg.update(cfg)
    return app.base


# --- identity / construction ------------------------------------------------


def test_base_has_status_surface(tmp_path):
    base = _make_base(tmp_path)
    # server identity built from server_key
    assert base.server.server_name == "SIM"
    # status model + client set + fast_urls present
    assert base.actionservermodel.action_server.server_name == "SIM"
    assert base.status_clients == set()
    assert base.fast_urls == []


# --- attach_client / detach_client ------------------------------------------


def test_attach_client_adds_key_and_pushes_status(tmp_path, monkeypatch):
    base = _make_base(tmp_path)
    mock = AsyncMock(return_value=({}, ErrorCodes.none))
    monkeypatch.setattr(base_api_mod, "async_private_dispatcher", mock)

    ok = asyncio.run(base.attach_client("ORCH", "127.0.0.1", 8001))

    assert ok is True
    assert ("ORCH", "127.0.0.1", 8001) in base.status_clients
    # dispatcher called once for the initial full snapshot
    assert mock.await_count == 1
    _, kwargs = mock.await_args
    assert kwargs["private_action"] == "update_status"
    assert kwargs["params_dict"]["regular_task"] == "true"
    assert "actionservermodel" in kwargs["json_dict"]


def test_attach_client_returns_false_on_dispatch_error(tmp_path, monkeypatch):
    base = _make_base(tmp_path)
    mock = AsyncMock(return_value=(None, ErrorCodes.http))
    monkeypatch.setattr(base_api_mod, "async_private_dispatcher", mock)

    ok = asyncio.run(base.attach_client("ORCH", "127.0.0.1", 8001))

    assert ok is False


def test_detach_client_removes_key_and_is_idempotent(tmp_path):
    base = _make_base(tmp_path)
    base.status_clients.add(("ORCH", "127.0.0.1", 8001))
    base.detach_client("ORCH", "127.0.0.1", 8001)
    assert ("ORCH", "127.0.0.1", 8001) not in base.status_clients
    # idempotent: removing again does not raise
    base.detach_client("ORCH", "127.0.0.1", 8001)


# --- send_statuspackage / send_nbstatuspackage ------------------------------


def test_send_statuspackage_full_snapshot(tmp_path, monkeypatch):
    base = _make_base(tmp_path)
    mock = AsyncMock(return_value=({}, ErrorCodes.none))
    monkeypatch.setattr(base_api_mod, "async_private_dispatcher", mock)

    asyncio.run(
        base.send_statuspackage("ORCH", "127.0.0.1", 8001, action_name=None)
    )
    _, kwargs = mock.await_args
    assert kwargs["private_action"] == "update_status"
    assert "actionservermodel" in kwargs["json_dict"]
    assert kwargs["params_dict"]["regular_task"] == "true"


def test_send_statuspackage_single_endpoint(tmp_path, monkeypatch):
    base = _make_base(tmp_path)
    mock = AsyncMock(return_value=({}, ErrorCodes.none))
    monkeypatch.setattr(base_api_mod, "async_private_dispatcher", mock)

    asyncio.run(
        base.send_statuspackage("ORCH", "127.0.0.1", 8001, action_name="do")
    )
    _, kwargs = mock.await_args
    assert kwargs["params_dict"]["regular_task"] == "false"


def test_send_nbstatuspackage_posts_actionmodel(tmp_path, monkeypatch):
    base = _make_base(tmp_path, host="10.0.0.5", port=9000)
    mock = AsyncMock(return_value=({}, ErrorCodes.none))
    monkeypatch.setattr(base_api_mod, "async_private_dispatcher", mock)

    action = RunAction(action_name="nb")
    asyncio.run(base.send_nbstatuspackage("ORCH", "127.0.0.1", 8001, action))
    _, kwargs = mock.await_args
    assert kwargs["private_action"] == "update_nonblocking"
    assert "actionmodel" in kwargs["json_dict"]
    assert kwargs["params_dict"]["server_host"] == "10.0.0.5"
    assert kwargs["params_dict"]["server_port"] == 9000


# --- init_endpoint_status ---------------------------------------------------


def test_init_endpoint_status_registers_endpoint_per_route(tmp_path):
    app = BaseAPI(server_key="SIM", save_root=str(tmp_path))

    @app.post("/SIM/do", tags=["action"])
    async def do(action: RunAction):
        return {}

    @app.post("/SIM/measure", tags=["action"])
    async def measure(action: RunAction):
        return {}

    asyncio.run(app.base.init_endpoint_status(app.routes))

    endpoints = app.base.actionservermodel.endpoints
    assert "do" in endpoints
    assert "measure" in endpoints
    # fast_urls populated with route descriptors
    paths = [u["path"] for u in app.base.fast_urls]
    assert "/SIM/do" in paths


# --- END-TO-END: action finish -> status pushed to orch ---------------------


def _register_do_endpoint(app, server_key):
    """Register an action endpoint that drives a oneoff executor end-to-end."""

    @app.post(f"/{server_key}/do", tags=["action"])
    async def do(action: RunAction):
        now = datetime.now()
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
async def test_status_drain_pushes_finished_to_orch(tmp_path):
    captured = []

    async def fake_dispatcher(**kwargs):
        captured.append(kwargs)
        return ({}, ErrorCodes.none)

    app = BaseAPI(server_key="SIM", save_root=str(tmp_path))
    _register_do_endpoint(app, "SIM")
    base = app.state.base

    # patch the dispatcher the base pushes through
    base_api_mod.async_private_dispatcher = fake_dispatcher  # type: ignore
    try:
        # start the status-drain (and live buffer) background tasks
        await base.myinit()
        await base.init_endpoint_status(app.routes)
        # register a fake orch client (this also pushes an initial snapshot)
        attached = await base.attach_client("ORCH", "127.0.0.1", 8001)
        assert attached is True

        # drive the action through to finished
        ctx_action = RunAction(action_name="do")
        from helao.framework.app.base_api import ActionContext

        token = ACTION_CTX.set(
            ActionContext(action=ctx_action, endpoint_name="do")
        )
        try:
            now = datetime.now()
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

            active = await base.setup_and_contain_action(header="epoch_ns: 1")
            await active.open_file(file_conn, header="epoch_ns: 1")
            executor = Executor(active=active)

            async def _exec(self):
                return {"data": {"value": 1}, "error": ErrorCodes.none}

            executor.set_exec(_exec)
            result = await active.action_loop_task(executor)
        finally:
            ACTION_CTX.reset(token)

        assert HloStatus.finished in result.action_status

        # let the status drain process queued emissions; bail fast on hang
        async def _wait_for_finished_push():
            while True:
                for kwargs in captured:
                    if kwargs.get("private_action") != "update_status":
                        continue
                    asm = kwargs["json_dict"].get("actionservermodel", {})
                    eps = asm.get("endpoints", {})
                    do_ep = eps.get("do")
                    if not do_ep:
                        continue
                    # finished bucket of the nonactive_dict holds the action
                    nonactive = do_ep.get("nonactive_dict", {})
                    if any(nonactive.values()):
                        return kwargs
                await asyncio.sleep(0.01)

        pushed = await asyncio.wait_for(_wait_for_finished_push(), timeout=5.0)
        # the package names the right server + carries the finished action
        asm = pushed["json_dict"]["actionservermodel"]
        assert asm["action_server"]["server_name"] == "SIM"
    finally:
        if base._status_task is not None:
            base._status_task.cancel()
        if base._live_task is not None:
            base._live_task.cancel()
