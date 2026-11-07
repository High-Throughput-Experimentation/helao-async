"""E-STOP during the Stop drain must stay latched.

Stop with a long action running drains in ``WaitAllActionsIdle`` /
``DrainForStop``: ``while loop_state != stopped: wait idle; loop_state = stopped``.
An E-STOP latched meanwhile was overwritten with ``stopped`` once the action
ended: servers stayed latched, ``/clear_estop`` refused, a second E-STOP no-oped.
"""

import asyncio

import pytest

from helao.hexagon.domain.models import LoopStatus
from helao.hexagon.tests.live_group import build_ws_sequence, live_group, orch_call


@pytest.mark.asyncio
async def test_estop_during_stop_drain_latch_survives(tmp_path):
    async with live_group(str(tmp_path)) as g:
        orch = g.orch
        gsm = orch.globalstatusmodel
        seq = build_ws_sequence(1, wait_time=0.5, data_duration=8.0)
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")
        t0 = asyncio.get_event_loop().time()
        while not any(
            a.action_name == "acquire_data" for a in gsm.active_dict.values()
        ):
            assert asyncio.get_event_loop().time() - t0 < 30
            await asyncio.sleep(0.05)
        await orch_call("stop")
        await asyncio.sleep(1.0)
        await orch_call("estop_orch")
        assert gsm.loop_state == LoopStatus.estopped
        t0 = asyncio.get_event_loop().time()
        while gsm.active_dict:
            assert asyncio.get_event_loop().time() - t0 < 10
            await asyncio.sleep(0.1)
        await asyncio.sleep(3.0)
        assert gsm.loop_state == LoopStatus.estopped, gsm.loop_state
        await orch_call("clear_estop")
        assert gsm.loop_state == LoopStatus.stopped
