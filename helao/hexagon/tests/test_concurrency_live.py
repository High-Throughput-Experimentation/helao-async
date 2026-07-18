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
from helao.hexagon.domain.orchestration import (
    ActionResultErrored,
    CloseOutExperimentCmd,
    FinishThenDispatchExperimentCmd,
    StatusChanged,
)
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


# =============================================================================
# Item 3: estop between decision and effect — three sub-races (DD-3)
# =============================================================================
def _assert_estopped_exp_yml(root: Path):
    """[finished, estopped] terminal status, exactly once each."""
    import yaml

    exp_ymls = list(Path(root).rglob("*-exp.yml"))
    assert exp_ymls, "estop finalizer produced no experiment yml"
    statuses = [
        yaml.safe_load(p.read_text()).get("experiment_status") for p in exp_ymls
    ]
    assert ["finished", "estopped"] in statuses, statuses
    for st in statuses:
        assert st.count("finished") == 1, st  # no duplicate finished


@pytest.mark.asyncio
async def test_item3a_estop_while_blocked_on_dispatch(tmp_path):
    """(a) estop lands while the drainer is BLOCKED inside the dispatch
    effect (standing for the dispatch lock). Trigger over REAL transport
    (/estop_orch). After release: the in-effect live re-check bails, no new
    action registers, the estop finalizer is sole."""
    async with live_group(str(tmp_path)) as g:
        orch, _ = g.orch, g.runtime
        clean_finishes, estop_finishes = _spy_finishers(orch)
        gate, entered = asyncio.Event(), asyncio.Event()
        orig_dispatch = orch.loop_task_dispatch_action

        async def gated_dispatch(*a, **k):
            entered.set()
            await gate.wait()
            return await orig_dispatch(*a, **k)

        orch.loop_task_dispatch_action = gated_dispatch
        seq = build_ws_sequence(1, wait_time=5.0, data_duration=2.0)
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")
        await asyncio.wait_for(entered.wait(), timeout=60)
        n_actions_before = len(orch.action_history)

        await orch_call("estop_orch")  # trigger-site cascade over real HTTP/RPC
        assert orch.globalstatusmodel.loop_state == LoopStatus.estopped
        assert len(estop_finishes) == 1  # finalizer already ran, exactly once

        gate.set()  # release the stalled effect
        await asyncio.sleep(2.0)
        # the released dispatch bailed: nothing new registered or dispatched
        assert len(orch.action_history) == n_actions_before
        assert len(clean_finishes) == 0  # clean close-out never fired
        assert len(estop_finishes) == 1  # STILL the sole finalizer
        assert orch.globalstatusmodel.loop_state == LoopStatus.estopped
        _assert_estopped_exp_yml(tmp_path)


@pytest.mark.asyncio
async def test_item3b_estop_between_decision_and_finish_then_dispatch(tmp_path):
    """(b) estop lands after the reducer decided FinishThenDispatchExperiment
    but before the runner executes it. The runner's live re-check (re-check
    #2) must bail; estop_finish_active stays the SOLE finalizer."""
    async with live_group(str(tmp_path)) as g:
        orch, runtime = g.orch, g.runtime
        clean_finishes, estop_finishes = _spy_finishers(orch)
        window, reached = asyncio.Event(), asyncio.Event()
        orig_execute = runtime.effects.execute

        async def gated_execute(cmd):
            if (
                isinstance(cmd, FinishThenDispatchExperimentCmd)
                and orch.active_experiment is not None
                and not reached.is_set()
            ):
                reached.set()
                await window.wait()  # decision made; effect not yet run
            return await orig_execute(cmd)

        runtime.effects.execute = gated_execute
        seq = build_ws_sequence(2, wait_time=1.0, data_duration=2.0)
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")
        await asyncio.wait_for(reached.wait(), timeout=120)
        n_exp_dq_at_gate = len(orch.experiment_dq)  # the not-yet-dispatched 2nd exp

        await orch_call("estop_orch")  # lands INSIDE the decision->effect window
        assert orch.globalstatusmodel.loop_state == LoopStatus.estopped
        window.set()
        await asyncio.sleep(2.0)
        assert len(estop_finishes) == 1
        assert len(clean_finishes) == 0  # re-check bailed; no clean finish ever
        # make the bailed re-check OBSERVABLE: if it had NOT bailed, the released
        # effect would fall through to loop_task_dispatch_experiment(), which
        # unconditionally pops experiment_dq and re-stages a NEW active_experiment
        # (dispatch_experiment()/_stage_experiment(), orch_dispatch.py:993-1025) --
        # regardless of estop_finish_active() having already cleared
        # active_experiment to None. Confirmed via fault injection (temporarily
        # neutering re-check #2 in orch_effects.py): experiment_dq goes 1->0 and
        # active_experiment gets repopulated with a fresh experiment when the
        # re-check is broken, vs. staying 1->1 / None when it works.
        assert len(orch.experiment_dq) == n_exp_dq_at_gate  # no extra exp dispatch
        assert orch.active_experiment is None  # nothing re-staged post-estop
        assert orch.globalstatusmodel.loop_state == LoopStatus.estopped
        _assert_estopped_exp_yml(tmp_path)


@pytest.mark.asyncio
async def test_item3c_estop_during_finalization_close_out(tmp_path):
    """(c) estop escalation (ActionResultErrored — the unguarded ingestion
    source) lands while the drainer is inside finalization's CloseOut
    effect window. Live re-check #3: the close-out re-checks LIVE loop_state
    and bails; single finalizer."""
    async with live_group(str(tmp_path)) as g:
        orch, runtime = g.orch, g.runtime
        clean_finishes, estop_finishes = _spy_finishers(orch)
        # a SECOND, unconditional spy layered on top of _spy_finishers's
        # active-experiment-gated one: clean_finishes only counts a call that
        # observed active_experiment is not None, which by design can never be
        # true once estop_finish_active has already cleared it -- so a bailed
        # re-check and a broken (never-bails) one look IDENTICAL to
        # clean_finishes. raw_finish_calls counts every call regardless,
        # making a spurious extra invocation observable.
        raw_finish_calls = []
        orig_finish_raw = orch.finish_active_experiment

        async def raw_spy_finish(*a, **k):
            raw_finish_calls.append(1)
            return await orig_finish_raw(*a, **k)

        orch.finish_active_experiment = raw_spy_finish
        window, reached = asyncio.Event(), asyncio.Event()
        orig_execute = runtime.effects.execute

        async def gated_execute(cmd):
            if isinstance(cmd, CloseOutExperimentCmd) and not reached.is_set():
                reached.set()
                await window.wait()  # finalization decided; close-out pending
            return await orig_execute(cmd)

        runtime.effects.execute = gated_execute
        seq = build_ws_sequence(1, wait_time=1.0, data_duration=2.0)
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")
        await asyncio.wait_for(reached.wait(), timeout=120)
        n_raw_finish_at_gate = len(raw_finish_calls)

        # concurrent estop through the reducer at its trigger site (DD-3):
        await runtime.handle(ActionResultErrored(reason="conc item3c"))
        assert orch.globalstatusmodel.loop_state == LoopStatus.estopped
        assert len(estop_finishes) == 1
        window.set()  # release the pending clean close-out
        await asyncio.sleep(2.0)
        assert len(clean_finishes) == 0  # close-out re-checked live and bailed
        assert len(estop_finishes) == 1  # sole finalizer, still
        # make the bailed re-check OBSERVABLE: should_close_out_experiment()
        # is only reached inside CloseOutExperimentCmd's handler, guarding the
        # sole call to finish_active_experiment() in that path -- so a broken
        # re-check (e.g. dropping the loop_state clause) shows up as one MORE
        # raw call than at the gate, even though clean_finishes can't see it
        # (active_experiment is already None by then). Confirmed via fault
        # injection (temporarily forcing the CloseOutExperimentCmd guard to
        # True in orch_effects.py): raw_finish_calls grows by 1 post-release
        # when the re-check is broken, vs. staying flat when it works.
        assert len(raw_finish_calls) == n_raw_finish_at_gate
        _assert_estopped_exp_yml(tmp_path)
