"""``--restore`` must come back as a clean, startable orchestrator.

``queues.pck`` carries ``globalstatusmodel`` whole, so a pickle written mid-run
holds ``loop_state=started`` / ``loop_intent=stop`` AND the uuids of actions that
were in flight. A fresh process has no dispatch loop and its action servers never
report the old uuids, so restoring either verbatim leaves a loop that cannot be
started and an ``active_dict`` that never empties. After restore the in-flight
actions are re-run under fresh uuids and the old uuids are retired to ``skipped``.
"""

import asyncio

from helao.core.models.hlostatus import HloStatus
from helao.core.models.orchstatus import LoopIntent, LoopStatus
from helao.core.tests.test_orch_dispatch_golden_master import (
    _PatchedOrchGlobals,
    _install_generic_libs,
    _install_recording_stubs,
    _make_fake_move_dir,
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
    orch.hexagon_wiring = PortWiring(logging=LegacyLoggingAdapter(), health=_OkHealth())  # type: ignore[arg-type]
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


async def _mid_run_pck(tmp_path, loop_intent=LoopIntent.stop):
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
