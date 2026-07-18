"""Live in-process group smoke: a real 1-experiment run drains to
RUNS_FINISHED through the hexagon graft over real transport. This is the
foundation every §10.3 in-process item builds on — if this hangs or fails,
fix the harness FIRST (systematic-debugging), never weaken it to a stub."""

import pytest

from helao.hexagon.domain.models import LoopStatus
from helao.hexagon.tests.live_group import (
    build_ws_sequence,
    live_group,
    orch_call,
    wait_for_glob,
    wait_parked,
)


@pytest.mark.asyncio
async def test_live_group_runs_one_experiment_to_finished(tmp_path):
    async with live_group(str(tmp_path)) as g:
        seq = build_ws_sequence(1, wait_time=1.0, data_duration=2.0)
        await orch_call("append_sequence", body={"sequence": seq.as_dict()})
        await orch_call("start")
        await wait_parked(g.orch, timeout_s=180.0)
        assert g.orch.globalstatusmodel.loop_state == LoopStatus.stopped
        # "parked" is loop-state only — the legacy finalize path fires
        # move_dir() as a fire-and-forget aloop.create_task (not awaited by
        # the code that flips loop_state), so the on-disk sync can lag the
        # parked signal by several seconds. Poll for the real artifacts.
        finished_dir = tmp_path / "RUNS_FINISHED"
        finished = await wait_for_glob(str(finished_dir), "*-seq.yml", timeout_s=60.0)
        assert finished, "sequence yml missing from RUNS_FINISHED"
        exp_ymls = await wait_for_glob(str(finished_dir), "*-exp.yml", timeout_s=60.0)
        assert len(exp_ymls) == 1
        # the graft is live: the runtime is the drainer's runtime
        assert g.runtime is g.orch_app.hexagon_graft.runtime
