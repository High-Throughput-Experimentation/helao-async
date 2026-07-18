"""Port of unit_test_sync_process_recovery.py (6 scenarios) onto the NATIVE
SyncDriver (P2c T9). Mechanical translation: legacy `_make_driver` ->
`make_sync_driver(..., NativeSyncDriver)`, legacy `tempfile.TemporaryDirectory()`
-> pytest `tmp_path`, legacy `out["key"] = expr` -> `assert expr, "key"`. Proves
the native re-body reproduces the legacy process-recovery behavior
byte-for-byte (mirrors helao/core/tests/unit_test_sync_process_recovery.py).

The legacy test file is NOT modified and NOT imported for logic (mirrored only)."""

from pathlib import Path

import pytest

from helao.hexagon.adapters.native.sync_driver import SyncDriver as NativeSyncDriver
from helao.hexagon.adapters.native.sync_driver import HelaoYml
from helao.core.models.run_dir import RunDir
from helao.hexagon.tests.sync_fixtures import (
    make_sync_driver,
    teardown_driver,
    mk_uuid,
    act_meta,
    make_exp_tree,
    make_action,
    write_yml,
    ts,
)


@pytest.fixture(autouse=True)
def _hermetic_aws(monkeypatch):
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)


# --- 1. Legacy experiment: update_process must populate process_metas ------


@pytest.mark.asyncio
async def test_legacy_experiment_populates_process_metas(tmp_path):
    drv = make_sync_driver(str(tmp_path), NativeSyncDriver)
    try:
        root = Path(tmp_path)
        # no process_order_groups => legacy_experiment == True
        exp_yml = make_exp_tree(root, RunDir.FINISHED.value, mk_uuid(1001))
        a0 = make_action(exp_yml, 0, process_finish=False)
        a1 = make_action(exp_yml, 1, process_finish=True)  # finisher

        ep = drv.get_progress(exp_yml)
        assert ep.dict["legacy_experiment"] is True, "legacy_flag"

        drv.update_process(HelaoYml(a0), act_meta(0, False))
        ep = drv.update_process(HelaoYml(a1), act_meta(1, True))

        assert len(ep.dict["process_metas"]) > 0, "legacy_metas_populated"
        assert set(ep.dict["process_actions_done"].keys()) == {
            0,
            1,
        }, "legacy_actions_done"
        assert 1 in ep.dict["legacy_finisher_idxs"], "legacy_finisher_recorded"
    finally:
        await teardown_driver(drv)


# --- 2 & 3. Cross-run reconcile + idempotency ------------------------------


@pytest.mark.asyncio
async def test_cross_run_reconcile_and_idempotency(tmp_path):
    drv = make_sync_driver(str(tmp_path), NativeSyncDriver)
    try:
        root = Path(tmp_path)
        # exp in FINISHED, both contributing actions ALREADY in SYNCED
        # (cross-run resume: they'd never be re-enqueued). Fresh .prg.
        exp_yml = make_exp_tree(
            root, RunDir.FINISHED.value, mk_uuid(1002), process_order_groups={0: [0, 1]}
        )
        synced_exp_yml = make_exp_tree(
            root, RunDir.SYNCED.value, mk_uuid(1002), process_order_groups={0: [0, 1]}
        )
        make_action(synced_exp_yml, 0)
        make_action(synced_exp_yml, 1)

        ep = drv.get_progress(exp_yml)
        assert ep.dict["process_metas"] == {}, "reconcile_before_empty"

        ep = drv.reconcile_processes(ep)
        metas = ep.dict["process_metas"]
        assert 0 in metas, "reconcile_group_present"
        assert set(ep.dict["process_actions_done"].keys()) == {
            0,
            1,
        }, "reconcile_actions_done"
        assert (
            0 in metas and len(metas[0].get("dispatched_actions_abbr", [])) == 2
        ), "reconcile_both_dispatched"

        # idempotency: reconcile again must NOT double-count
        ep = drv.reconcile_processes(ep)
        assert len(ep.dict["process_metas"][0]["dispatched_actions_abbr"]) == 2 and set(
            ep.dict["process_actions_done"].keys()
        ) == {0, 1}, "reconcile_idempotent"
    finally:
        await teardown_driver(drv)


# --- 4. Phantom group is dropped, experiment can finish --------------------


@pytest.mark.asyncio
async def test_phantom_group_dropped_experiment_finishes(tmp_path):
    drv = make_sync_driver(str(tmp_path), NativeSyncDriver)
    try:
        root = Path(tmp_path)
        # group 1 is planned but its action (order 1) never dispatched/synced
        exp_yml = make_exp_tree(
            root,
            RunDir.FINISHED.value,
            mk_uuid(1003),
            process_order_groups={0: [0], 1: [1]},
        )
        synced_exp_yml = make_exp_tree(
            root,
            RunDir.SYNCED.value,
            mk_uuid(1003),
            process_order_groups={0: [0], 1: [1]},
        )
        make_action(synced_exp_yml, 0)  # only group 0 has an action

        ep = drv.get_progress(exp_yml)
        ep = drv.reconcile_processes(ep)
        s3_unf_before, _ = ep.list_unfinished_procs()
        assert set(s3_unf_before) == {0, 1}, "phantom_unfinished_before"

        ep = await drv.sync_process(ep, force=True)
        assert 1 not in ep.dict["process_groups"], "phantom_group_dropped"
        assert 0 in ep.dict["process_s3"], "phantom_real_group_synced"

        s3_unf_after, api_unf_after = ep.list_unfinished_procs()
        assert not s3_unf_after and not api_unf_after, "phantom_experiment_completes"
    finally:
        await teardown_driver(drv)


# --- 5. Split actions: same action_order, distinct uuids, all folded -------


@pytest.mark.asyncio
async def test_split_actions_all_folded(tmp_path):
    drv = make_sync_driver(str(tmp_path), NativeSyncDriver)
    try:
        root = Path(tmp_path)
        exp_yml = make_exp_tree(
            root, RunDir.FINISHED.value, mk_uuid(1004), process_order_groups={0: [0]}
        )

        def _split_meta(split: int) -> dict:
            m = act_meta(0, process_finish=False)
            # split actions share action_order but get a new uuid + split idx
            m["action_uuid"] = mk_uuid(2000 + split)
            m["action_split"] = split
            m["process_contrib"] = ["samples_out"]
            m["samples_out"] = [
                {
                    "global_label": f"sample_split_{split}",
                    "action_uuid": [m["action_uuid"]],
                }
            ]
            return m

        # two on-disk split ymls under one action_order dir family
        for split in (0, 1):
            ad = exp_yml.parent / f"0__{split}__srv__test_action"
            write_yml(ad / f"{ts(1 + split)}-act.yml", _split_meta(split))

        ep = drv.get_progress(exp_yml)
        for split in (0, 1):
            ay = (
                exp_yml.parent
                / f"0__{split}__srv__test_action"
                / f"{ts(1 + split)}-act.yml"
            )
            ep = drv.update_process(HelaoYml(ay), _split_meta(split))

        metas = ep.dict["process_metas"]
        assert (
            0 in metas and len(metas[0].get("dispatched_actions_abbr", [])) == 2
        ), "split_both_dispatched"
        labels = {s.get("global_label") for s in metas[0].get("samples_out", [])}
        assert labels == {
            "sample_split_0",
            "sample_split_1",
        }, "split_both_samples_kept"

        # replay must not double-count either split
        for split in (0, 1):
            ay = (
                exp_yml.parent
                / f"0__{split}__srv__test_action"
                / f"{ts(1 + split)}-act.yml"
            )
            ep = drv.update_process(HelaoYml(ay), _split_meta(split))
        assert (
            len(ep.dict["process_metas"][0]["dispatched_actions_abbr"]) == 2
        ), "split_idempotent"
    finally:
        await teardown_driver(drv)


# --- 6. Overlapping groups: one action_order in two groups -----------------


@pytest.mark.asyncio
async def test_overlapping_groups_both_built_and_synced(tmp_path):
    drv = make_sync_driver(str(tmp_path), NativeSyncDriver)
    try:
        root = Path(tmp_path)
        # action order 0 declared in BOTH group 0 and group 1
        exp_yml = make_exp_tree(
            root,
            RunDir.FINISHED.value,
            mk_uuid(1005),
            process_order_groups={0: [0], 1: [0]},
        )
        synced_exp_yml = make_exp_tree(
            root,
            RunDir.SYNCED.value,
            mk_uuid(1005),
            process_order_groups={0: [0], 1: [0]},
        )
        make_action(synced_exp_yml, 0)

        ep = drv.get_progress(exp_yml)
        ep = drv.reconcile_processes(ep)
        assert (
            0 in ep.dict["process_metas"] and 1 in ep.dict["process_metas"]
        ), "overlap_both_metas_built"

        ep = await drv.sync_process(ep, force=True)
        assert (
            0 in ep.dict["process_s3"] and 1 in ep.dict["process_s3"]
        ), "overlap_both_synced"
        s3_unf, api_unf = ep.list_unfinished_procs()
        assert not s3_unf and not api_unf, "overlap_experiment_completes"
    finally:
        await teardown_driver(drv)
