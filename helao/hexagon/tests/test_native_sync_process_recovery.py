"""Process-recovery / race-hardening scenarios on the NATIVE SyncDriver:
legacy-experiment metas, cross-run reconcile, phantom and unrebuildable group
parking, splits, overlapping groups, and late-action reopen."""

from pathlib import Path

import pytest

from helao.core.models.run_dir import RunDir
from helao.hexagon.adapters.native.sync_driver import HelaoYml
from helao.hexagon.adapters.native.sync_driver import SyncDriver as NativeSyncDriver
from helao.hexagon.tests.sync_fixtures import (
    act_meta,
    make_action,
    make_exp_tree,
    make_sync_driver,
    mk_uuid,
    teardown_driver,
    ts,
    write_yml,
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


# --- 7. Unrebuildable group: meta gone AND its actions gone from disk ------


@pytest.mark.asyncio
async def test_unrebuildable_group_parked_experiment_finishes(tmp_path):
    """A group whose meta is gone and whose actions left disk must not loop.

    Scenario 4 parks a group that has *no* contributing action recorded, by
    recognising it as phantom. This is the same permanent loop reached from the
    other side: the actions *are* recorded in ``process_actions_done``, so the
    phantom test does not fire, and ``sync_process`` falls through to a
    ``continue`` that can never make progress -- the group stays in
    ``list_unfinished_procs`` forever, ``sync_yml`` keeps returning False, and the
    experiment is re-queued by whatever touches it next.

    Both halves of the state are reproduced because neither implies the other:
    ``process_metas`` lost while ``process_actions_done`` survived (the shape a
    .prg written before the scenario-1 legacy-metas fix has), and the
    contributing action ymls gone from every tree ``HelaoYml.children`` scans
    (they synced and were swept into the zipped sequence), so
    ``reconcile_processes`` has nothing to replay.
    """
    import shutil

    drv = make_sync_driver(str(tmp_path), NativeSyncDriver)
    try:
        root = Path(tmp_path)
        exp_yml = make_exp_tree(
            root,
            RunDir.FINISHED.value,
            mk_uuid(1006),
            process_order_groups={0: [0, 1]},
        )
        a0 = make_action(exp_yml, 0)
        a1 = make_action(exp_yml, 1, process_finish=True)

        drv.update_process(HelaoYml(a0), act_meta(0, False))
        ep = drv.update_process(HelaoYml(a1), act_meta(1, True))

        shutil.rmtree(a0.parent)
        shutil.rmtree(a1.parent)
        ep.dict["process_metas"] = {}
        ep.write_dict()

        ep = drv.get_progress(exp_yml)
        ep = drv.reconcile_processes(ep)
        # Preconditions, not the defect: reconcile has nothing to replay, so the
        # meta stays missing while the group still looks contributed-to.
        assert 0 not in ep.dict["process_metas"], "unrebuildable_meta_absent"
        assert set(ep.dict["process_actions_done"].keys()) == {
            0,
            1,
        }, "unrebuildable_actions_still_recorded"

        ep = await drv.sync_process(ep, force=True)

        assert (
            0 not in ep.dict["process_groups"] or 0 in ep.dict["process_s3"]
        ), "unrebuildable_group_parked"
        s3_unf, api_unf = ep.list_unfinished_procs()
        assert not s3_unf and not api_unf, "unrebuildable_experiment_completes"
    finally:
        await teardown_driver(drv)


# --- 5. A late action reopens an already-pushed process group --------------


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", [NativeSyncDriver], ids=["native"])
async def test_late_action_reopens_pushed_group_for_repush(tmp_path, cls):
    """A --restore re-run (or errored retry) shares action_order with the attempt
    that already synced. Its fold must reopen the group so the next pass pushes a
    process that lists the re-run; folding the same uuid again must not."""
    drv = make_sync_driver(str(tmp_path), cls)
    try:
        exp_yml = make_exp_tree(
            Path(tmp_path),
            RunDir.FINISHED.value,
            mk_uuid(1004),
            process_order_groups={0: [0, 1]},
        )
        a0 = make_action(exp_yml, 0)
        old = make_action(exp_yml, 1)
        drv.update_process(HelaoYml(a0), act_meta(0))
        ep = drv.update_process(HelaoYml(old), act_meta(1))

        # the group is pushed with only the old attempt
        ep = await drv.sync_process(ep)
        assert ep.list_unfinished_procs() == ([], [])
        (prc,) = list(exp_yml.parent.glob("0__*-prc.json"))
        assert mk_uuid(500) not in prc.read_text(encoding="utf-8")

        # the re-run: same action_order, new uuid, its own contribution
        rerun_meta = {
            **act_meta(1),
            "action_uuid": mk_uuid(500),
            "action_retry": 1,
            "action_params": {"rerun_only": 1},
        }
        rerun = make_action(exp_yml, 1)
        rerun.write_text(
            rerun.read_text(encoding="utf-8"), encoding="utf-8"
        )  # file exists on disk like a real one
        ep = drv.update_process(HelaoYml(rerun), rerun_meta)
        assert ep.list_unfinished_procs() == ([0], [0]), "group reopened"

        ep = await drv.sync_process(ep)
        assert ep.list_unfinished_procs() == ([], [])
        text = prc.read_text(encoding="utf-8")
        assert mk_uuid(500) in text and mk_uuid(1) in text, "both uuids listed"
        assert "rerun_only" in text, "re-run's contribution pushed"

        # folding the same uuid again is idempotent: nothing reopens
        ep = drv.update_process(HelaoYml(rerun), rerun_meta)
        assert ep.list_unfinished_procs() == ([], [])
    finally:
        await teardown_driver(drv)


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", [NativeSyncDriver], ids=["native"])
async def test_later_split_does_not_reopen_pushed_group(tmp_path, cls):
    """Splits share action_order and differ in action_split (and technique). A
    later split is not a re-attempt: the pushed group stays pushed, so there is
    one -prc.yml per process and its technique name does not flip."""
    drv = make_sync_driver(str(tmp_path), cls)
    try:
        exp_yml = make_exp_tree(
            Path(tmp_path),
            RunDir.FINISHED.value,
            mk_uuid(1005),
            process_order_groups={0: [0]},
        )
        act = make_action(exp_yml, 0)
        techs = ["tech_s0", "tech_s1"]
        split0 = {**act_meta(0), "technique_name": techs, "action_split": 0}
        split1 = {
            **split0,
            "action_uuid": mk_uuid(600),
            "action_split": 1,
            "action_params": {"split1_only": 1},
        }
        ep = drv.update_process(HelaoYml(act), split0)
        ep = await drv.sync_process(ep)
        assert ep.list_unfinished_procs() == ([], [])
        (prc,) = list(exp_yml.parent.glob("0__*-prc.json"))
        assert "tech_s0" in prc.name

        ep = drv.update_process(HelaoYml(act), split1)
        assert ep.list_unfinished_procs() == ([], []), "a later split must not reopen"
        ep = await drv.sync_process(ep)
        assert [p.name for p in exp_yml.parent.glob("0__*-prc.json")] == [prc.name]
    finally:
        await teardown_driver(drv)
