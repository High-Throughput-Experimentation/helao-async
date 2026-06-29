"""TDD test for orchestrator built-in /wait writing a nested -act.yml.

Bug (TEST_consecutive_nonblocking): no ``-act.yml`` and no action subdirectories
appeared for sequences whose actions are all ORCH ``wait`` actions. The legacy
orchestrator ``/wait`` endpoint runs a normal action (``save_act=True``) so it
writes a ``-act.yml`` under the nested ``<seq>/<exp>/<action>`` tree.

Root cause: the framework ``/wait`` endpoint discarded the dispatched action's
full context and rebuilt a minimal action with ``save_act=False`` and a flat
``action_output_dir`` — so ``myinit`` never wrote a ``-act.yml`` nor created the
nested action dir.

RED test written BEFORE the fix — must FAIL before, PASS after.
"""
from uuid import UUID
from datetime import datetime
from pathlib import Path

import pytest

from helao.framework.domain.run_models import RunAction
from helao.framework.domain import lifecycle
from helao.framework.models.machine import MachineModel
from helao.framework.adapters.fs_storage import FsStorage
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.adapters.ntp_clock import NtpClock
from helao.framework.adapters.fakes.transport import FakeTransport
from helao.framework.app.orch_api import OrchPorts, makeOrchApp

FIXED_NOW = datetime(2026, 6, 27, 5, 0, 0)
WAIT_UUID = UUID("00000000-0000-0000-0000-0000000000bb")


def _nested_wait_action() -> RunAction:
    """A fully-stamped ORCH wait action as the dispatch loop would emit it."""
    a = RunAction(
        action_name="wait",
        action_uuid=WAIT_UUID,
        action_timestamp=FIXED_NOW,
        sequence_timestamp=FIXED_NOW,
        experiment_timestamp=FIXED_NOW,
        sequence_name="TEST_consecutive_noblocking",
        experiment_name="TEST_sub_noblocking",
        action_server=MachineModel(server_name="ORCH"),
        action_params={"waittime": 30.0},
        orch_submit_order=0,
    )
    a.sequence_output_dir = lifecycle.sequence_output_dir(a)
    a.experiment_output_dir = lifecycle.experiment_output_dir(a)
    a.action_output_dir = lifecycle.action_output_dir(a)
    return a


@pytest.mark.asyncio
async def test_orch_wait_writes_nested_act_yml(tmp_path):
    import httpx

    ports = OrchPorts(
        transport=FakeTransport(),
        storage=FsStorage(save_root=str(tmp_path)),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
    )
    # makeOrchApp co-locates its OWN FrameworkBase; pass save_root so that base
    # (which the /wait endpoint uses) writes under the test's tmp dir.
    app = makeOrchApp("ORCH", ports=ports, save_root=str(tmp_path))

    action = _nested_wait_action()
    # dispatch payload shape: {**action_params, "action": action.as_dict()}
    body = {"waittime": 30.0, "action": action.as_dict()}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/ORCH/wait", json=body)

    assert resp.status_code == 200, f"/ORCH/wait failed: {resp.status_code} {resp.text}"

    # myinit writes the -act.yml synchronously during contain_action, so it must
    # exist immediately after the POST returns — under the nested action dir.
    act_files = list(Path(tmp_path).rglob("*-act.yml"))
    assert act_files, (
        f"no -act.yml written for ORCH wait under {tmp_path}; "
        f"files: {[str(p) for p in Path(tmp_path).rglob('*')]}"
    )
    # the act file must live under the nested experiment dir, NOT a flat uuid dir
    rels = [str(p.relative_to(tmp_path)) for p in act_files]
    assert any(action.experiment_output_dir in r for r in rels), (
        f"-act.yml not under nested experiment dir {action.experiment_output_dir!r}; got {rels}"
    )
