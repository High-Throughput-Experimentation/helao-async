"""``--restore`` must come back as a clean, startable orchestrator.

``queues.pck`` carries ``globalstatusmodel`` whole, so a pickle written mid-run
holds ``loop_state=started`` / ``loop_intent=stop`` AND the uuids of actions that
were in flight. A fresh process has no dispatch loop and its action servers never
report the old uuids, so restoring either verbatim leaves a loop that cannot be
started and an ``active_dict`` that never empties. After restore the in-flight
actions are re-run under fresh uuids and the old uuids are retired to ``skipped``.
"""

import asyncio
from types import SimpleNamespace

from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.hlostatus import HloStatus
from helao.core.models.server import ActionServerModel, EndpointModel
from helao.core.models.orchstatus import LoopIntent, LoopStatus
from helao.core.tests.test_orch_dispatch_golden_master import (
    _PatchedOrchGlobals,
    _install_generic_libs,
    _install_recording_stubs,
    _make_fake_move_dir,
    _make_fake_to_s3,
    _make_fake_private_dispatcher,
    _make_orch,
    _mk_sequence,
    _seed_server_dict,
    make_fake_action_dispatcher,
)
from helao.hexagon.adapters.shared.logging_adapter import LegacyLoggingAdapter
from helao.hexagon.app.dispatch_loop import HexDispatchLoop
from helao.hexagon.app.wiring import PortWiring

NAMES = ["a0", "a1", "a2"]
TIMEOUT = 10


class _OkHealth:
    """Health port that reports every endpoint reachable (no real servers here)."""

    async def endpoints_available(self, urls):
        return [(u, True) for u in urls]


def _orch(root):
    orch = _make_orch(root)
    orch.hexagon_wiring = PortWiring(
        logging=LegacyLoggingAdapter(),
        health=_OkHealth(),  # type: ignore[arg-type]
        sync=SimpleNamespace(to_s3=_make_fake_to_s3()),  # type: ignore[arg-type]
    )
    orch._build_reducer()
    _install_recording_stubs(orch, [])
    _install_generic_libs(orch)
    orch.aloop = asyncio.get_running_loop()
    _seed_server_dict(orch, [("SRV1", n) for n in NAMES])
    return orch


def _patched(orch, trace, script=None):
    return _PatchedOrchGlobals(
        make_fake_action_dispatcher(orch, trace, script=script or {}),
        _make_fake_private_dispatcher(trace),
        _make_fake_move_dir(trace),
    )


async def _stop(drainer):
    task = drainer._task
    assert task is not None
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def _until(pred, what):
    async def poll():
        while not pred():
            await asyncio.sleep(0.02)

    try:
        await asyncio.wait_for(poll(), TIMEOUT)
    except asyncio.TimeoutError:
        raise AssertionError(f"timed out waiting for {what}")


# What a server-returned (live status) Action lacks: dispatch fills these onto
# queued actions at plan time, never onto the copy the action server reports.
_LINKAGE_FIELDS = (
    "sequence_uuid",
    "sequence_name",
    "sequence_label",
    "sequence_timestamp",
    "sequence_params",
    "sequence_output_dir",
    "sequence_status",
    "planned_experiments",
    "experiment_name",
    "experiment_params",
    "experiment_output_dir",
    "experiment_status",
)


def _strip_linkage(orch):
    """Blank the linkage fields on every live in-flight Action, as a real server does."""
    gsm = orch.globalstatusmodel
    live = list(gsm.active_dict.values())
    for srv in gsm.server_dict.values():
        for ep in srv.endpoints.values():
            live += list(ep.active_dict.values())
    for act in live:
        for name in _LINKAGE_FIELDS:
            setattr(
                act,
                name,
                type(act).model_fields[name].get_default(call_default_factory=True),
            )


async def _mid_run_pck(tmp_path, loop_intent=LoopIntent.stop, strip=False):
    """Run a real orchestrator until a1 is in flight (a0 done, a2 queued) and export.

    Returns (src, pck_path, in_flight_uuid).
    """
    src = _orch(tmp_path / "src")
    await src.add_sequence(
        _mk_sequence(
            [
                {
                    "experiment_name": "generic_exp",
                    "experiment_params": {
                        "actions_spec": [
                            {"server": "SRV1", "name": n, "params": {"k": n}}
                            for n in NAMES
                        ]
                    },
                }
            ]
        )
    )
    drainer = HexDispatchLoop(src._hex_runtime)
    with _patched(src, [], {"a1": {"skip_ping": True}}):
        drainer.start()
        await src.start_loop()
        await _until(
            lambda: any(
                a.action_name == "a1"
                for a in src.globalstatusmodel.active_dict.values()
            ),
            "a1 in flight",
        )
        await _stop(drainer)
    (old_uuid,) = src.globalstatusmodel.active_dict
    assert src.globalstatusmodel.active_dict[old_uuid].action_name == "a1"
    assert [a.action_name for a in src.action_dq] == ["a2"]
    assert src.active_experiment is not None and src.active_sequence is not None
    assert len(src.sequence_dq) == 0  # popped, as in a real mid-run export
    src.globalstatusmodel.loop_state = LoopStatus.started
    src.globalstatusmodel.loop_intent = loop_intent
    if strip:
        _strip_linkage(src)
    return src, src.export_queues(timestamp_pck=False), old_uuid


def test_restore_resets_loop_flags_keeps_progress(tmp_path):
    async def run():
        src, pck, _ = await _mid_run_pck(tmp_path)
        dst = _orch(tmp_path / "dst")
        dst.import_queues(pck_path=pck)
        gsm = dst.globalstatusmodel
        assert gsm.loop_state == LoopStatus.stopped
        assert gsm.loop_intent == LoopIntent.none
        assert dst.active_sequence is not None and src.active_sequence is not None
        assert dst.active_sequence.sequence_uuid == src.active_sequence.sequence_uuid
        assert dst.seq_model.sequence_uuid == dst.active_sequence.sequence_uuid
        assert dst.active_experiment is not None and src.active_experiment is not None
        assert (
            dst.active_experiment.experiment_uuid
            == src.active_experiment.experiment_uuid
        )

    asyncio.run(run())


def test_restore_then_start_reruns_inflight_action_and_finishes(tmp_path):
    async def run():
        src, pck, old_uuid = await _mid_run_pck(tmp_path)
        dst = _orch(tmp_path / "dst")
        dst.import_queues(pck_path=pck)
        gsm = dst.globalstatusmodel

        # retired, not left to wedge actions_idle()
        assert old_uuid not in gsm.active_dict
        assert old_uuid in gsm.nonactive_dict[HloStatus.skipped]
        assert HloStatus.errored not in gsm.nonactive_dict
        assert gsm.actions_idle()
        # re-run copy first, then the rest of the queue
        assert [a.action_name for a in dst.action_dq] == ["a1", "a2"]
        assert dst.action_dq[0].action_uuid is None
        assert dst.action_dq[0].action_retry == 1
        assert dst.last_action_uuid != str(old_uuid)

        trace: list = []
        drainer = HexDispatchLoop(dst._hex_runtime)
        with _patched(dst, trace):
            drainer.start()
            try:
                await dst.start_loop()
                await _until(
                    lambda: dst.active_experiment is None
                    and dst.globalstatusmodel.loop_state == LoopStatus.stopped,
                    "experiment to finish and loop to stop",
                )
            finally:
                await _stop(drainer)

        calls = [e for e in trace if e["event"] == "dispatch_call"]
        assert [c["action_name"] for c in calls] == ["a1", "a2"]
        assert calls[0]["params"]["k"] == "a1"
        # fresh attempt takes the next submit order, so it cannot collide with
        # the interrupted attempt's run directory
        assert calls[0]["submit_order"] == 2 and calls[1]["submit_order"] == 3
        assert old_uuid in dst.globalstatusmodel.nonactive_dict[HloStatus.skipped]

    asyncio.run(run())


def test_restored_rerun_stays_in_active_experiment_not_manual(tmp_path):
    """A server-returned in-flight copy has no sequence/experiment linkage; the
    re-run must get it back from the active sequence/experiment, or init_act turns
    it into a manual action under DIAG whose data lands in no process."""

    async def run():
        _, pck, _ = await _mid_run_pck(tmp_path, strip=True)
        dst = _orch(tmp_path / "dst")
        dst.import_queues(pck_path=pck)
        seq, exp = dst.active_sequence, dst.active_experiment
        assert seq is not None and exp is not None
        rerun = dst.action_dq[0]
        assert rerun.action_name == "a1"
        for name in _LINKAGE_FIELDS:
            src_obj = seq if name.startswith("sequence_") else exp
            if name == "planned_experiments":
                src_obj = seq
            assert getattr(rerun, name) == getattr(src_obj, name), name

        rerun.init_act()  # what dispatch staging does
        assert rerun.manual_action is False
        assert rerun.access != "manual"
        assert rerun.sequence_uuid == seq.sequence_uuid
        assert rerun.experiment_uuid == exp.experiment_uuid
        assert str(rerun.action_output_dir).startswith(str(exp.experiment_output_dir))
        assert "__manual" not in str(rerun.action_output_dir)
        assert "DIAG" not in str(rerun.action_output_dir)

    asyncio.run(run())


async def _parked_head_orch(tmp_path):
    """Run until a1 (wait_for_server) is popped and parked, with a2 still queued.

    a0, acknowledged as active but never finished, keeps a1's condition false, so
    a1 is only a local in ``_launch_action`` for as long as the test holds it there.
    """
    src = _orch(tmp_path / "src")
    specs = [
        {
            "server": "SRV1",
            "name": "a0",
            "params": {},
            "start_condition": ActionStartCondition.no_wait,
        },
        {
            "server": "SRV1",
            "name": "a1",
            "params": {},
            "start_condition": ActionStartCondition.wait_for_server,
        },
        {"server": "SRV1", "name": "a2", "params": {}},
    ]
    await src.add_sequence(
        _mk_sequence(
            [
                {
                    "experiment_name": "generic_exp",
                    "experiment_params": {"actions_spec": specs},
                }
            ]
        )
    )
    trace: list = []
    inner = make_fake_action_dispatcher(src, trace, script={"a0": {"skip_ping": True}})

    async def dispatcher(world_cfg, A, params=None):
        # a0 is acknowledged as ACTIVE and then never finishes: the history poll
        # releases on that acknowledgement, and a1's condition stays false
        resp, code = await inner(world_cfg, A, params)
        if A.action_name == "a0" and resp is not None:
            live = A.model_copy(deep=True)
            live.action_uuid = resp["action_uuid"]
            live.action_status = [HloStatus.active]
            asm = ActionServerModel(
                action_server=live.action_server,
                endpoints={
                    "a0": EndpointModel(
                        endpoint_name="a0", active_dict={live.action_uuid: live}
                    )
                },
                last_action_uuid=live.action_uuid,
            )
            assert src.aloop is not None
            src.aloop.create_task(src.update_status(asm))
        return resp, code

    drainer = HexDispatchLoop(src._hex_runtime)
    with _PatchedOrchGlobals(
        dispatcher, _make_fake_private_dispatcher(trace), _make_fake_move_dir(trace)
    ):
        drainer.start()
        await src.start_loop()
        await _until(
            lambda: [a.action_name for a in src.action_dq] == ["a2"],
            "a1 popped (parked) with a2 still queued",
        )
        await asyncio.sleep(0.1)  # settled in the wait
        assert [a.action_name for a in src.action_dq] == ["a2"]
        assert [e["action_name"] for e in trace if e["event"] == "dispatch_call"] == [
            "a0"
        ]
        await _stop(drainer)
    return src


def test_export_while_head_parked_on_start_condition_restores_it_first_once(tmp_path):
    async def run():
        src = await _parked_head_orch(tmp_path)
        pck = src.export_queues(timestamp_pck=False)
        dst = _orch(tmp_path / "dst")
        dst.import_queues(pck_path=pck)
        # a0's re-run (in flight at export) leads, then the parked a1, then a2
        assert [a.action_name for a in dst.action_dq] == ["a0", "a1", "a2"]

    asyncio.run(run())


def test_export_does_not_duplicate_head_already_reinserted(tmp_path):
    async def run():
        src = await _parked_head_orch(tmp_path)
        head = src.parked_head_action
        assert head is not None and head.action_name == "a1"
        # a stop arrives mid-wait: wait_for_interrupt puts the head back itself
        src.globalstatusmodel.loop_intent = LoopIntent.stop
        src.interrupt_q.put_nowait(object())
        assert await src.wait_for_interrupt(pending_action=head) is False
        assert [a.action_name for a in src.action_dq] == ["a1", "a2"]
        pck = src.export_queues(timestamp_pck=False)
        dst = _orch(tmp_path / "dst")
        dst.import_queues(pck_path=pck)
        assert [a.action_name for a in dst.action_dq] == ["a0", "a1", "a2"]

    asyncio.run(run())


def test_export_without_parked_head_is_unchanged(tmp_path):
    async def run():
        src, pck, _ = await _mid_run_pck(tmp_path)
        assert src.parked_head_action is None
        dst = _orch(tmp_path / "dst")
        dst.import_queues(pck_path=pck)
        assert [a.action_name for a in dst.action_dq] == ["a1", "a2"]

    asyncio.run(run())
