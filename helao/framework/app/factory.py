"""``makeApp`` factory: assemble a FastAPI action *or* orchestrator server.

This is the framework port of the deployment ``makeApp(server_key)`` pattern.
The ``group`` argument (or a config lookup) selects the server kind:

* ``group="action"`` (default) — the SP4 minimal action app: a single action
  endpoint that builds a :class:`RunAction`, contains it through
  :class:`FrameworkBase`, drives a dummy :class:`Executor` end-to-end, and
  finishes it through the real ``FsStorage`` adapter.
* ``group="orchestrator"`` — the SP5 orchestrator app: assembles an
  :class:`OrchDriver` (via :func:`orch_api.makeOrchApp`) wired to the injected
  ports + experiment/sequence library maps, exposing the control endpoints.

FastAPI is imported HERE (app layer) only.
"""
from __future__ import annotations

import os
import tempfile
import uuid as _uuid
from datetime import datetime
from typing import Callable, Mapping, Optional

from fastapi import Body, FastAPI

from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.domain.executor import Executor
from helao.framework.domain.run_models import RunAction
from helao.framework.adapters.fs_storage import FsStorage
from helao.framework.adapters.ntp_clock import NtpClock
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.adapters.fakes.transport import FakeTransport
from helao.framework.app.base_api import ActionContext, FrameworkBase

__all__ = ["makeApp", "makeActionApp", "makeOrchestratorApp"]


def makeApp(
    server_key: str,
    save_root: Optional[str] = None,
    *,
    group: str = "action",
    transport=None,
    sequence_lib: Optional[Mapping[str, Callable]] = None,
    experiment_lib: Optional[Mapping[str, Callable]] = None,
    postprocessors=None,
    action_servers=None,
    servers_map=None,
) -> FastAPI:
    """Build the FastAPI app for ``server_key`` per ``group``.

    Args:
        server_key: Server identifier (route prefix; stamped on actions).
        save_root: Output root for the ``FsStorage`` adapter; a fresh temp dir
            is created when omitted.
        group: ``"action"`` (default) or ``"orchestrator"`` — selects the app
            kind. Unknown values fall back to the action app.
        transport: Optional transport adapter; a :class:`FakeTransport` is used
            when omitted (so tests/demos run with no network).
        sequence_lib: Sequence name -> factory map (orchestrator only).
        experiment_lib: Experiment name -> factory map (orchestrator only).
        postprocessors: HLO post-processor names (passed to the ports).
        action_servers: Map of server_key -> {host, port, ...} for heartbeat
            pings (orchestrator only; action-group subset of servers_map).
        servers_map: Full CONFIG ``servers`` map (all groups) for config-driven
            target resolution including ORCH self-dispatch (orchestrator only).

    Returns:
        A configured :class:`fastapi.FastAPI` instance.
    """
    if group == "orchestrator":
        return makeOrchestratorApp(
            server_key,
            save_root,
            transport=transport,
            sequence_lib=sequence_lib,
            experiment_lib=experiment_lib,
            postprocessors=postprocessors,
            action_servers=action_servers,
            servers_map=servers_map,
        )
    return makeActionApp(server_key, save_root)


def makeOrchestratorApp(
    server_key: str,
    save_root: Optional[str] = None,
    *,
    transport=None,
    sequence_lib: Optional[Mapping[str, Callable]] = None,
    experiment_lib: Optional[Mapping[str, Callable]] = None,
    postprocessors=None,
    action_servers=None,
    servers_map=None,
) -> FastAPI:
    """Assemble the orchestrator FastAPI app (an :class:`OrchDriver`).

    Wires ``FsStorage`` + ``QueueEventSink`` + ``NtpClock`` + a transport (a
    :class:`FakeTransport` when none is supplied) and the library maps into an
    :class:`helao.framework.app.orch_api.OrchPorts` bundle, then delegates to
    :func:`orch_api.makeOrchApp`.

    Args:
        servers_map: Full CONFIG ``servers`` map (all groups) for config-driven
            target resolution including ORCH self-dispatch. ``None``/empty keeps
            the existing MachineModel-based fallback behaviour (unit tests and
            in-process runners pass nothing here).
    """
    from helao.framework.app.orch_api import OrchPorts, makeOrchApp

    if save_root is None:
        save_root = tempfile.mkdtemp(prefix="helao_framework_orch_")
    os.makedirs(save_root, exist_ok=True)

    ports = OrchPorts(
        transport=transport if transport is not None else FakeTransport(),
        storage=FsStorage(save_root=save_root),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
        sequence_lib=sequence_lib,
        experiment_lib=experiment_lib,
        postprocessors=postprocessors,
        action_servers=action_servers,
        servers_map=servers_map,
    )
    app = makeOrchApp(server_key, ports=ports)
    app.state.save_root = save_root
    return app


def makeActionApp(server_key: str, save_root: Optional[str] = None) -> FastAPI:
    """Build a FastAPI app exposing one dummy-executor action endpoint.

    Args:
        server_key: Server identifier (used in the route prefix and stamped on
            actions).
        save_root: Output root for the ``FsStorage`` adapter; a fresh temp dir
            is created when omitted.

    Returns:
        A configured :class:`fastapi.FastAPI` instance. Posting to
        ``/{server_key}/run_dummy`` runs a oneoff dummy executor end-to-end and
        returns ``{"action_uuid", "status"}``.
    """
    if save_root is None:
        save_root = tempfile.mkdtemp(prefix="helao_framework_")
    os.makedirs(save_root, exist_ok=True)

    base = FrameworkBase(
        server_key=server_key,
        storage=FsStorage(save_root=save_root),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
        transport=FakeTransport(),
    )

    app = FastAPI(title=f"{server_key} (framework SP4)")
    app.state.base = base
    app.state.save_root = save_root

    @app.post(f"/{server_key}/run_dummy")
    async def run_dummy(value: int = Body(0, embed=True)) -> dict:
        """Contain and run a oneoff dummy action that records ``value``."""
        now = datetime.now()
        action_uuid = _uuid.uuid4()
        file_conn = _uuid.uuid4()
        action = RunAction(
            action_name="run_dummy",
            action_uuid=action_uuid,
            action_timestamp=now,
            sequence_timestamp=now,
            experiment_timestamp=now,
            sequence_name="seq",
            experiment_name="exp",
            action_output_dir=f"{action_uuid}",
            action_server={"server_name": server_key, "machine_name": "local"},
            save_act=True,
            save_data=True,
            file_conn_keys=[file_conn],
        )
        active = await base.setup_and_contain_action(
            ActionContext(action=action, endpoint_name="run_dummy"),
            header="epoch_ns: 1",
        )
        await active.open_file(file_conn, header="epoch_ns: 1")

        executor = Executor(active=active)

        async def _exec(self):
            return {"data": {"value": value}, "error": ErrorCodes.none}

        executor.set_exec(_exec)
        result = await active.action_loop_task(executor)

        status = (
            "finished"
            if HloStatus.finished in result.action_status
            else str(result.action_status)
        )
        return {"action_uuid": str(result.action_uuid), "status": status}

    return app
