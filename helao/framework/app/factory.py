"""``makeApp`` factory: assemble a minimal FastAPI action server.

This is the framework port of the deployment ``makeApp(server_key)`` pattern.
SP4 keeps it intentionally minimal (full orchestrator/driver assembly is SP5):
it constructs a real FastAPI app whose single action endpoint builds a
:class:`RunAction`, contains it through :class:`FrameworkBase`, drives a dummy
:class:`Executor` end-to-end, and finishes it — proving the wiring writes an HLO
file through the real ``FsStorage`` adapter.

FastAPI is imported HERE (app layer) only.
"""
from __future__ import annotations

import os
import tempfile
import uuid as _uuid
from datetime import datetime
from typing import Optional

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

__all__ = ["makeApp"]


def makeApp(server_key: str, save_root: Optional[str] = None) -> FastAPI:
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
