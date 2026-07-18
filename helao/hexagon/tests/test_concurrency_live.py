"""§10.3 mandatory concurrency suite — in-process real-transport items
(1, 3, 5). Real hexagon ORCH (makeOrchApp graft) + real SIM (ws_simulator)
over real ZMQ RPC + HTTP; races injected via HexRuntime.handle from
concurrent tasks (DD-3). Launched-group items (2, 4, 6, 7) live in
helao/hexagon/tests/smoke/conc_items.py."""

import asyncio
import zipfile
from pathlib import Path

import pytest

from helao.hexagon.domain.models import LoopStatus
from helao.hexagon.domain.orchestration import StatusChanged
from helao.hexagon.tests.live_group import (
    build_ws_sequence,
    live_group,
    orch_call,
    wait_parked,
)


def _spy_finishers(orch):
    """Instance-rebind counting wrappers (the sanctioned wrap seam): count
    clean experiment finishes only when an experiment was actually active
    (the real finish_active_experiment no-ops otherwise), and count the
    estop finalizer. Returns (clean_finishes, estop_finishes) lists."""
    clean, estop = [], []
    orig_finish = orch.finish_active_experiment
    orig_estop_finish = orch.estop_finish_active

    async def spy_finish(*a, **k):
        if orch.active_experiment is not None:
            clean.append(1)
        return await orig_finish(*a, **k)

    async def spy_estop_finish(*a, **k):
        estop.append(1)
        return await orig_estop_finish(*a, **k)

    orch.finish_active_experiment = spy_finish
    orch.estop_finish_active = spy_estop_finish
    return clean, estop


def _count_exp_ymls(root: Path) -> int:
    """Count ``*-exp.yml`` artifacts wherever the sync pipeline currently
    holds them: still-loose files under ``RUNS_FINISHED``, or already rolled
    up into a per-sequence ``.zip`` under ``RUNS_SYNCED`` (SyncDriver zips the
    sequence directory once every file in it has synced — sync_driver.py's
    "Full sequence has synced, creating zip" step). Summing both locations
    makes the count robust to exactly where in that pipeline the run happens
    to sit when the assertion runs."""
    total = len(list((root / "RUNS_FINISHED").rglob("*-exp.yml")))
    for zip_path in (root / "RUNS_SYNCED").rglob("*.zip"):
        with zipfile.ZipFile(zip_path) as zf:
            total += sum(1 for name in zf.namelist() if name.endswith("-exp.yml"))
    return total


async def _wait_for_exp_yml_count(root: Path, expected: int, timeout_s: float) -> int:
    deadline = asyncio.get_event_loop().time() + timeout_s
    while True:
        count = _count_exp_ymls(root)
        if count >= expected or asyncio.get_event_loop().time() >= deadline:
            return count
        await asyncio.sleep(0.5)


# =============================================================================
# Item 1: lost wakeup / double drain
# =============================================================================
@pytest.mark.asyncio
async def test_item1_status_burst_no_double_drain(tmp_path):
    """Burst status-shaped events + wakes at the loop while a 2-experiment
    run is mid-flight. Single-drainer semantics: each experiment finishes
    exactly once, every dispatched action is unique, nothing double-pops."""
    async with live_group(str(tmp_path)) as g:
        orch, runtime = g.orch, g.runtime
        clean_finishes, _ = _spy_finishers(orch)
        dispatches = []
        orig_dispatch = orch.loop_task_dispatch_action

        async def spy_dispatch(*a, **k):
            dispatches.append(1)
            return await orig_dispatch(*a, **k)

        orch.loop_task_dispatch_action = spy_dispatch

        seq = build_ws_sequence(2, wait_time=1.0, data_duration=2.0)
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")

        stop_burst = asyncio.Event()

        async def burst():
            while not stop_burst.is_set():
                any_active = bool(orch.globalstatusmodel.active_dict)
                await runtime.handle(StatusChanged(any_active=any_active))
                runtime.loop_wake.set()  # the lost-wakeup provocation
                await asyncio.sleep(0.005)

        burst_task = asyncio.create_task(burst())
        try:
            await wait_parked(orch, timeout_s=240.0)
        finally:
            stop_burst.set()
            await burst_task

        # no duplicated FinishExperiment: exactly one clean finish per exp
        assert len(clean_finishes) == 2, clean_finishes
        # no double-popped queue: 2 exps x 4 actions, each dispatched once,
        # and each dispatch registered exactly one unique action uuid
        assert len(dispatches) == 8, dispatches
        assert len(orch.action_history) == 8
        # every action reached a finished timestamp (nothing stuck/lost)
        assert all(
            meta.get("action_finished_timestamp")
            for meta in orch.action_history.values()
        )
        # artifacts: exactly one exp yml per experiment, none duplicated.
        # "parked" (wait_parked) only certifies loop STATE — the legacy
        # finalize path fires move_dir() fire-and-forget and SyncDriver then
        # rolls the finished sequence up into a RUNS_SYNCED zip on its own
        # schedule (Task 2 carry), so poll rather than asserting immediately
        # after park, and count across both possible on-disk locations.
        exp_yml_count = await _wait_for_exp_yml_count(
            tmp_path, expected=2, timeout_s=60.0
        )
        assert exp_yml_count == 2, exp_yml_count
        assert orch.globalstatusmodel.loop_state == LoopStatus.stopped
