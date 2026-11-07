"""Each sequence's -seq record lists exactly its own experiments (live group).

Two queued sequences run back to back; the first one's last experiment must be
filed under the first sequence, not under the one that is active by the time
that experiment is finalized.
"""

import asyncio

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
        recs = await _seq_records(tmp_path, 2)
        # let the last move_dir settle, then re-read
        await asyncio.sleep(2.0)
        recs = await _seq_records(tmp_path, 2)

        # the -exp records say which sequence each experiment belongs to
        owner = {}
        for p in meta_glob(tmp_path, "exp", "**/*"):
            d = read_meta(p)
            owner[str(d["experiment_uuid"])] = str(d["sequence_uuid"])
        assert len(owner) == 4, owner
        for s in seqs:
            su = str(s.sequence_uuid)
            filed = {
                str(e["experiment_uuid"])
                for e in recs[su]["dispatched_experiments_abbr"]
            }
            own = {u for u, o in owner.items() if o == su}
            assert len(own) == 2 and filed == own, (su, filed, own)
        # in-memory: the last finished sequence is B and owns only its own
        last = orch.last_sequence
        assert {str(e.sequence_uuid) for e in last.dispatched_experiments} == {
            str(last.sequence_uuid)
        }
