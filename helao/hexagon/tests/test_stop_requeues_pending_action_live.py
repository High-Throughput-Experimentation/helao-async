"""A graceful stop must not run an action that has already left the queue.

`_launch_action` pops the head action BEFORE waiting on its start condition,
so for the whole of that wait the action exists only as a local variable.
`wait_for_interrupt(pending_action=...)` is the mechanism that puts it back
and tells the caller to bail; the parameter has existed since 2022 and no
production caller ever supplied it, so the re-queue branch was dead and a
/stop arriving mid-wait still dispatched the action once its condition was
met -- on an instrument, one more real CV or pump move after the operator
asked it to stop.

E-stop was never affected: `_dispatch_action_locked` re-checks
`loop_intent == estop or loop_state == estopped` inside the aiolock and
refuses. That in-lock guard covers estop only; plain `LoopIntent.stop`
passes straight through it, which is why this needed the re-queue instead.
"""

import asyncio

import pytest

from helao.hexagon.domain.models import LoopStatus
from helao.hexagon.tests.live_group import live_group, orch_call

WAIT_S = 8.0


@pytest.mark.asyncio
async def test_stop_during_start_condition_wait_requeues_instead_of_dispatching(
    tmp_path,
):
    from helao.helpers.premodels import ExperimentPlanMaker, Sequence
    from helao.helpers.time_utils import gen_uuid

    epm = ExperimentPlanMaker()
    epm.add(
        "TEST_sub_stop_during_condition_wait",
        {"wait_time": WAIT_S, "data_duration": 2.0},
    )
    async with live_group(str(tmp_path)) as g:
        seq = Sequence(
            sequence_name="TEST_sub_stop_during_condition_wait",
            sequence_label="stop-requeue",
            sequence_params={"wait_time": WAIT_S, "data_duration": 2.0},
            planned_experiments=epm.planned_experiments,
            sequence_uuid=gen_uuid(),
            dummy=True,
            simulation=True,
        )
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")

        # The window this test is about opens when the acquisition has been
        # POPPED and is blocked in its start-condition wait: the ORCH `wait`
        # is active and action_dq is empty, so the action exists only as a
        # local in _launch_action. Stopping any earlier is a different test --
        # the intent gate fires before `popleft()` and the action is never
        # popped at all, which is what made the first version of this pass
        # against the unfixed code.
        parked = False
        deadline = asyncio.get_event_loop().time() + WAIT_S
        while asyncio.get_event_loop().time() < deadline:
            active = {
                a.action_name for a in g.orch.globalstatusmodel.active_dict.values()
            }
            if "wait" in active and not g.orch.action_dq:
                parked = True
                break
            await asyncio.sleep(0.05)
        assert parked, (
            "the acquisition never reached its start-condition wait "
            f"(action_dq={[a.action_name for a in g.orch.action_dq]})"
        )

        # Popped, but not dispatched.
        assert "acquire_data" not in {
            a.action_name for a in g.orch.globalstatusmodel.active_dict.values()
        }

        await orch_call("stop")

        # Let the whole window elapse: without the re-queue the acquisition
        # dispatches the moment the ORCH wait frees its endpoint.
        settle = asyncio.get_event_loop().time() + WAIT_S + 6.0
        while asyncio.get_event_loop().time() < settle:
            if (
                g.orch.globalstatusmodel.loop_state == LoopStatus.stopped
                and not g.orch.globalstatusmodel.active_dict
            ):
                break
            await asyncio.sleep(0.25)

        dispatched = {
            meta.get("action_name") for meta in g.orch.action_history.values()
        }
        assert "acquire_data" not in dispatched, (
            "the acquisition ran after /stop: the popped action was never "
            f"pushed back (history={sorted(n for n in dispatched if n)})"
        )
        queued = [a.action_name for a in g.orch.action_dq]
        assert queued and queued[0] == "acquire_data", (
            "the popped action was not re-queued at the front of action_dq "
            f"(action_dq={queued})"
        )
