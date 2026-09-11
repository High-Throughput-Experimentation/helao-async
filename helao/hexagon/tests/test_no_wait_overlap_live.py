"""The overlap gate for ``ActionStartCondition.no_wait``.

Real transport, real orchestrator, real action server (the same in-process
group as ``test_concurrency_live.py``): a blocking ORCH ``wait`` with a
``no_wait`` SIM ``acquire_data`` planned under it must be *simultaneously*
active. The two sit on different servers, so nothing an action server does
can serialise them -- if they never overlap, the orchestrator dispatched
them one after the other and no_wait was not honoured.

This is the behaviour the dispatch loop's history poll silently removed
between 2026-03-19 and the poll fix: ``action_history`` was only written
for actions that had reached a terminal status, so the poll after every
dispatch waited for the dispatched action to FINISH and every
start_condition collapsed to wait_for_all.
"""

import asyncio

import pytest

from helao.hexagon.tests.live_group import live_group, orch_call

WAIT_S = 6.0


@pytest.mark.asyncio
async def test_no_wait_action_overlaps_the_blocking_action_before_it(tmp_path):
    from helao.helpers.premodels import ExperimentPlanMaker, Sequence
    from helao.helpers.time_utils import gen_uuid

    epm = ExperimentPlanMaker()
    epm.add(
        "TEST_sub_no_wait_overlap",
        {"wait_time": WAIT_S, "data_duration": WAIT_S},
    )
    async with live_group(str(tmp_path)) as g:
        seq = Sequence(
            sequence_name="TEST_sub_no_wait_overlap",
            sequence_label="no-wait-overlap",
            sequence_params={"wait_time": WAIT_S, "data_duration": WAIT_S},
            planned_experiments=epm.planned_experiments,
            sequence_uuid=gen_uuid(),
            dummy=True,
            simulation=True,
        )
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")

        # Poll fast relative to the 6 s actions: the overlap window is most of
        # their duration when no_wait is honoured, and exactly zero when it is
        # not, so this does not race.
        overlapped = set()
        deadline = asyncio.get_event_loop().time() + 4 * WAIT_S
        while asyncio.get_event_loop().time() < deadline:
            names = {
                act.action_name for act in g.orch.globalstatusmodel.active_dict.values()
            }
            if len(names) > 1:
                overlapped = names
                break
            await asyncio.sleep(0.1)

        assert overlapped == {"wait", "acquire_data"}, (
            "no_wait did not overlap: the orchestrator dispatched the "
            f"actions serially (saw {overlapped or 'never more than one active'})"
        )
