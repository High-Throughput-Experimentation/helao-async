"""Start after Clear E-stop must run, not E-STOP again (real in-process group).

The estopped action stays in the orchestrator's stored endpoint status; the
first status from ANY endpoint after Start re-folded it into the finished
bucket and ingestion re-latched E-STOP on a uuid the operator had cleared.
"""

import asyncio

import pytest

from helao.core.models.hlostatus import HloStatus
from helao.hexagon.domain.models import LoopStatus
from helao.hexagon.tests.live_group import build_ws_sequence, live_group, orch_call


def _active_names(orch):
    return {a.action_name for a in orch.globalstatusmodel.active_dict.values()}


async def _until(pred, timeout, what):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if pred():
            return
        await asyncio.sleep(0.05)
    raise TimeoutError(what() if callable(what) else what)


@pytest.mark.asyncio
async def test_start_after_clear_estop_dispatches_and_stays_started(tmp_path):
    async with live_group(str(tmp_path)) as g:
        orch = g.orch
        gsm = orch.globalstatusmodel
        first = build_ws_sequence(2, wait_time=0.5, data_duration=20.0)
        await orch_call("append_sequence", body={"sequence": first.as_dict()})
        await orch_call("start")
        await _until(
            lambda: "acquire_data" in _active_names(orch), 30, "no SIM action running"
        )

        await orch_call("estop_orch")
        await _until(lambda: gsm.loop_state == LoopStatus.estopped, 10, "no estop")
        # SIM finalizes its running action as estopped
        await _until(
            lambda: gsm.find_hlostatus_in_finished(HloStatus.estopped),
            15,
            "SIM never reported its action estopped",
        )
        await orch_call("clear_estop")
        assert gsm.loop_state == LoopStatus.stopped
        first_run = {str(u) for u in orch.action_history}

        second = build_ws_sequence(1, wait_time=0.5, data_duration=1.0)
        await orch_call("append_sequence", body={"sequence": second.as_dict()})
        await orch_call("start")

        seen_states = set()

        def second_run_acquired():
            seen_states.add(gsm.loop_state)
            return any(
                meta.get("action_name") == "acquire_data" and str(u) not in first_run
                for u, meta in orch.action_history.items()
            )

        await _until(
            second_run_acquired,
            30,
            lambda: f"second run never reached SIM; loop states {seen_states}",
        )
        assert LoopStatus.estopped not in seen_states, seen_states
        assert gsm.loop_state == LoopStatus.started, gsm.loop_state


@pytest.mark.asyncio
async def test_late_estopped_status_after_clear_does_not_restop_on_start(tmp_path):
    """A slow server finishing its action past the E-STOP send timeout reports
    ``estopped`` AFTER Clear, while the loop is stopped. It is stale: Start must
    not latch on it."""
    from helao.core.models.server import ActionServerModel, EndpointModel
    from helao.helpers.premodels import Action

    async with live_group(str(tmp_path)) as g:
        orch = g.orch
        gsm = orch.globalstatusmodel
        late = Action(
            action_name="acquire_data",
            action_server=g.sim_app.server,
            orchestrator=gsm.orchestrator,
        )
        late.action_status = [HloStatus.estopped, HloStatus.finished]
        ep = EndpointModel(endpoint_name="acquire_data")
        ep.active_dict = {late.action_uuid: late}  # type: ignore[dict-item]
        await orch.update_status(
            ActionServerModel(
                action_server=g.sim_app.server, endpoints={"acquire_data": ep}
            )
        )
        assert gsm.loop_state == LoopStatus.stopped
        assert gsm.find_hlostatus_in_finished(HloStatus.estopped), "setup"

        seq = build_ws_sequence(1, wait_time=0.5, data_duration=1.0)
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")
        seen = set()

        def reached_sim():
            seen.add(gsm.loop_state)
            return any(
                m.get("action_name") == "acquire_data" and u != late.action_uuid
                for u, m in orch.action_history.items()
            )

        await _until(reached_sim, 30, lambda: f"never reached SIM; states {seen}")
        assert LoopStatus.estopped not in seen, seen
