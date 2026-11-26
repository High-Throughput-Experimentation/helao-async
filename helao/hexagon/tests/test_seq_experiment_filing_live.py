"""Each sequence's -seq record lists exactly its own experiments (live group).

Two queued sequences run back to back; the first one's last experiment must be
filed under the first sequence, not under the one that is active by the time
that experiment is finalized.
"""

import asyncio
import json
from pathlib import Path

import pytest

from helao.helpers.meta_io import meta_glob, read_meta
from helao.hexagon.tests.live_group import (
    build_ws_sequence,
    live_group,
    orch_call,
    wait_parked,
)


async def _seq_records(root, n, timeout_s=60.0):
    """-seq records on disk under ``root``, keyed by sequence_uuid (waits for n)."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    while True:
        recs = {}
        for p in meta_glob(root, "seq", "**/*"):
            d = read_meta(p)
            recs[str(d["sequence_uuid"])] = d
        if len(recs) >= n:
            return recs
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(f"{len(recs)} seq records under {root}")
        await asyncio.sleep(0.5)


@pytest.mark.asyncio
async def test_each_sequence_files_only_its_own_experiments(tmp_path):
    async with live_group(str(tmp_path)) as g:
        orch = g.orch
        seqs = [build_ws_sequence(2, wait_time=0.3, data_duration=0.3) for _ in "AB"]
        for s in seqs:
            await orch_call("append_sequence", body={"sequence": s.as_dict()})
        await orch_call("start")
        await wait_parked(orch)
        # ``stopped`` is not parked: wait for the close-out itself
        deadline = asyncio.get_event_loop().time() + 30
        while orch.active_experiment is not None or orch.active_sequence is not None:
            assert asyncio.get_event_loop().time() < deadline, "close-out never ran"
            await asyncio.sleep(0.1)
        recs = await _seq_records(tmp_path, 2)

        # the -exp records say which sequence each experiment belongs to
        owner = {}
        for p in meta_glob(tmp_path, "exp", "**/*"):
            d = read_meta(p)
            owner[str(d["experiment_uuid"])] = str(d["sequence_uuid"])
        assert len(owner) == 4, owner
        for s in seqs:
            su = str(s.sequence_uuid)
            filed = {str(u) for u in recs[su]["experiment_list"]}
            assert "planned_experiments" not in recs[su]
            assert "dispatched_experiments_abbr" not in recs[su]
            own = {u for u, o in owner.items() if o == su}
            assert len(own) == 2 and filed == own, (su, filed, own)
        # in-memory: the last finished sequence is B and owns only its own
        last = orch.last_sequence
        assert {str(e.sequence_uuid) for e in last.dispatched_experiments} == {
            str(last.sequence_uuid)
        }
        # plan sidecars: one per sequence and per experiment, stripped
        seq_dirs = {
            str(read_meta(p)["sequence_uuid"]): Path(p).parent
            for p in meta_glob(tmp_path, "seq", "**/*")
        }
        for s in seqs:
            sdir = seq_dirs[str(s.sequence_uuid)]
            (plan_path,) = list(sdir.glob("*-seq.plan.json"))
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            assert len(plan["planned"]) == 2
            assert all("experiment_params" not in e for e in plan["planned"])
            assert plan_path.name in recs[str(s.sequence_uuid)]["aux_files"]
        for p in meta_glob(tmp_path, "exp", "**/*"):
            d = read_meta(p)
            (plan_path,) = list(Path(p).parent.glob("*-exp.plan.json"))
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            assert {e["action_uuid"] for e in plan["planned"]} == {
                str(u) for u in d["action_list"]
            }
            assert all("action_params" not in e for e in plan["planned"])
            assert plan_path.name in d["aux_files"]
            assert "planned_actions" not in d
