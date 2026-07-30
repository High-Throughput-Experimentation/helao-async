"""Unit test for SyncDriver process-recovery / race-hardening fixes.

Regression guard for the "process index ... missing" sync failure that stranded
experiments in a permanent reset+re-enqueue loop (the manual workaround was to
move the experiment + child actions back to RUNS_FINISHED, delete .prg files,
and re-run finish_yml). Three distinct defects are covered:

  1. Legacy experiments: ``update_process`` populates ``process_metas`` for the
     legacy branch too (previously only the non-legacy branch did, so legacy
     experiments could never finish syncing).
  2. Cross-run / reset recovery: ``reconcile_processes`` rebuilds
     ``process_metas`` from the on-disk action ymls when the experiment ``.prg``
     is fresh/stale but the child actions already synced.
  3. Idempotency: replaying an already-folded action does not double-count.
  4. Phantom groups: a ``process_order_groups`` entry with no contributing
     action on disk is dropped by ``sync_process`` so the experiment finishes,
     instead of looping forever on ``reset_sync`` + re-enqueue.

Hermetic: no AWS configured (``s3`` is None), so uploads are
no-ops and nothing touches the network.
"""

__all__ = ["sync_process_recovery_unit_test"]

import asyncio
import os
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

from helao.core.drivers.data.sync_driver import SyncDriver
from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir
from helao.core.tests._test_utils import TestReporter
from helao.helpers.yml_tools import yml_dumps


def _write_yml(path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dumped = yml_dumps(meta)
    if isinstance(dumped, bytes):
        dumped = dumped.decode("utf-8")
    path.write_text(dumped, encoding="utf-8")


def _ts(second: int) -> str:
    """Filename timestamp stem that HelaoYml can parse (``%y%m%d.%H%M%S%f``)."""
    return datetime(2026, 6, 10, 12, 0, second, 100).strftime("%y%m%d.%H%M%S%f")


def _make_driver(tmp_root: str) -> SyncDriver:
    hd = HelaoDirs(
        root=Path(tmp_root),
        save_root=Path(tmp_root) / RunDir.ACTIVE.value,
        process_root=Path(tmp_root) / "PROCESSES",
    )
    cfg = {"aws_bucket": "test-bucket", "max_tasks": 1}
    return SyncDriver(cfg, hd)


def _uuid(tag: int) -> str:
    return f"00000000-0000-0000-0000-{tag:012d}"


def _exp_meta(uuid: str, process_order_groups=None) -> dict:
    meta = {
        "experiment_uuid": uuid,
        "experiment_name": "test_exp",
        "sequence_uuid": _uuid(999),
        "technique_name": "test_tech",
        "run_type": "test",
        "experiment_params": {"foo": "bar"},
    }
    if process_order_groups is not None:
        meta["process_order_groups"] = process_order_groups
    return meta


def _act_meta(order: int, process_finish: bool = False) -> dict:
    return {
        "action_uuid": _uuid(order),
        "action_name": "test_action",
        "action_order": order,
        "action_actual_order": order,
        "orch_submit_order": order,
        "action_split": 0,
        "action_timestamp": _ts(order + 1),
        "process_finish": process_finish,
        "process_contrib": ["action_params"],
        "action_params": {f"p{order}": order},
        "technique_name": "test_tech",
    }


def _make_exp_tree(root: Path, runs: str, exp_uuid: str, process_order_groups=None):
    """Create ``<root>/<runs>/26.23/0610/<seq>/<exp>/`` and return the exp yml path."""
    exp_dir = (
        root / runs / "26.23" / "0610" / f"{_ts(0)}__test__seq" / f"{_ts(0)}__test_exp"
    )
    exp_yml = exp_dir / f"{_ts(0)}-exp.yml"
    _write_yml(exp_yml, _exp_meta(exp_uuid, process_order_groups))
    return exp_yml


def _make_action(exp_yml: Path, order: int, process_finish: bool = False) -> Path:
    """Create a child action dir + yml under the experiment dir; return act yml."""
    act_dir = exp_yml.parent / f"{order}__0__srv__test_action"
    act_yml = act_dir / f"{_ts(order + 1)}-act.yml"
    _write_yml(act_yml, _act_meta(order, process_finish))
    return act_yml


async def _run_checks() -> dict:
    out = {}

    # --- 1. Legacy experiment: update_process must populate process_metas -----
    with tempfile.TemporaryDirectory() as tmp_root:
        drv = _make_driver(tmp_root)
        try:
            root = Path(tmp_root)
            # no process_order_groups => legacy_experiment == True
            exp_yml = _make_exp_tree(root, RunDir.FINISHED.value, _uuid(1001))
            a0 = _make_action(exp_yml, 0, process_finish=False)
            a1 = _make_action(exp_yml, 1, process_finish=True)  # finisher

            from helao.core.drivers.data.sync_driver import HelaoYml

            ep = drv.get_progress(exp_yml)
            out["legacy_flag"] = ep.dict["legacy_experiment"] is True

            drv.update_process(HelaoYml(a0), _act_meta(0, False))
            ep = drv.update_process(HelaoYml(a1), _act_meta(1, True))

            out["legacy_metas_populated"] = len(ep.dict["process_metas"]) > 0
            out["legacy_actions_done"] = set(
                ep.dict["process_actions_done"].keys()
            ) == {
                0,
                1,
            }
            out["legacy_finisher_recorded"] = 1 in ep.dict["legacy_finisher_idxs"]
        finally:
            for t in drv.syncer_loops.values():
                t.cancel()
            await asyncio.gather(*drv.syncer_loops.values(), return_exceptions=True)

    # --- 2 & 3. Cross-run reconcile + idempotency ----------------------------
    with tempfile.TemporaryDirectory() as tmp_root:
        drv = _make_driver(tmp_root)
        try:
            root = Path(tmp_root)
            # exp in FINISHED, both contributing actions ALREADY in SYNCED
            # (cross-run resume: they'd never be re-enqueued). Fresh .prg.
            exp_yml = _make_exp_tree(
                root,
                RunDir.FINISHED.value,
                _uuid(1002),
                process_order_groups={0: [0, 1]},
            )
            synced_exp_yml = _make_exp_tree(
                root, RunDir.SYNCED.value, _uuid(1002), process_order_groups={0: [0, 1]}
            )
            _make_action(synced_exp_yml, 0)
            _make_action(synced_exp_yml, 1)

            ep = drv.get_progress(exp_yml)
            out["reconcile_before_empty"] = ep.dict["process_metas"] == {}

            ep = drv.reconcile_processes(ep)
            metas = ep.dict["process_metas"]
            out["reconcile_group_present"] = 0 in metas
            out["reconcile_actions_done"] = set(
                ep.dict["process_actions_done"].keys()
            ) == {0, 1}
            out["reconcile_both_dispatched"] = (
                0 in metas and len(metas[0].get("dispatched_actions_abbr", [])) == 2
            )

            # idempotency: reconcile again must NOT double-count
            ep = drv.reconcile_processes(ep)
            out["reconcile_idempotent"] = len(
                ep.dict["process_metas"][0]["dispatched_actions_abbr"]
            ) == 2 and set(ep.dict["process_actions_done"].keys()) == {0, 1}
        finally:
            for t in drv.syncer_loops.values():
                t.cancel()
            await asyncio.gather(*drv.syncer_loops.values(), return_exceptions=True)

    # --- 4. Phantom group is dropped, experiment can finish ------------------
    with tempfile.TemporaryDirectory() as tmp_root:
        drv = _make_driver(tmp_root)
        try:
            root = Path(tmp_root)
            # group 1 is planned but its action (order 1) never dispatched/synced
            exp_yml = _make_exp_tree(
                root,
                RunDir.FINISHED.value,
                _uuid(1003),
                process_order_groups={0: [0], 1: [1]},
            )
            synced_exp_yml = _make_exp_tree(
                root,
                RunDir.SYNCED.value,
                _uuid(1003),
                process_order_groups={0: [0], 1: [1]},
            )
            _make_action(synced_exp_yml, 0)  # only group 0 has an action

            ep = drv.get_progress(exp_yml)
            ep = drv.reconcile_processes(ep)
            s3_unf_before, _ = ep.list_unfinished_procs()
            out["phantom_unfinished_before"] = set(s3_unf_before) == {0, 1}

            ep = await drv.sync_process(ep, force=True)
            out["phantom_group_dropped"] = 1 not in ep.dict["process_groups"]
            out["phantom_real_group_synced"] = 0 in ep.dict["process_s3"]

            s3_unf_after, api_unf_after = ep.list_unfinished_procs()
            out["phantom_experiment_completes"] = not s3_unf_after and not api_unf_after
        finally:
            for t in drv.syncer_loops.values():
                t.cancel()
            await asyncio.gather(*drv.syncer_loops.values(), return_exceptions=True)

    # --- 5. Split actions: same action_order, distinct uuids, all folded -----
    with tempfile.TemporaryDirectory() as tmp_root:
        drv = _make_driver(tmp_root)
        try:
            from helao.core.drivers.data.sync_driver import HelaoYml

            root = Path(tmp_root)
            exp_yml = _make_exp_tree(
                root, RunDir.FINISHED.value, _uuid(1004), process_order_groups={0: [0]}
            )

            def _split_meta(split: int) -> dict:
                m = _act_meta(0, process_finish=False)
                # split actions share action_order but get a new uuid + split idx
                m["action_uuid"] = _uuid(2000 + split)
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
                _write_yml(ad / f"{_ts(1 + split)}-act.yml", _split_meta(split))

            ep = drv.get_progress(exp_yml)
            for split in (0, 1):
                ay = (
                    exp_yml.parent
                    / f"0__{split}__srv__test_action"
                    / f"{_ts(1 + split)}-act.yml"
                )
                ep = drv.update_process(HelaoYml(ay), _split_meta(split))

            metas = ep.dict["process_metas"]
            out["split_both_dispatched"] = (
                0 in metas and len(metas[0].get("dispatched_actions_abbr", [])) == 2
            )
            labels = {s.get("global_label") for s in metas[0].get("samples_out", [])}
            out["split_both_samples_kept"] = labels == {
                "sample_split_0",
                "sample_split_1",
            }

            # replay must not double-count either split
            for split in (0, 1):
                ay = (
                    exp_yml.parent
                    / f"0__{split}__srv__test_action"
                    / f"{_ts(1 + split)}-act.yml"
                )
                ep = drv.update_process(HelaoYml(ay), _split_meta(split))
            out["split_idempotent"] = (
                len(ep.dict["process_metas"][0]["dispatched_actions_abbr"]) == 2
            )
        finally:
            for t in drv.syncer_loops.values():
                t.cancel()
            await asyncio.gather(*drv.syncer_loops.values(), return_exceptions=True)

    # --- 6. Overlapping groups: one action_order in two groups --------------
    with tempfile.TemporaryDirectory() as tmp_root:
        drv = _make_driver(tmp_root)
        try:
            root = Path(tmp_root)
            # action order 0 declared in BOTH group 0 and group 1
            exp_yml = _make_exp_tree(
                root,
                RunDir.FINISHED.value,
                _uuid(1005),
                process_order_groups={0: [0], 1: [0]},
            )
            synced_exp_yml = _make_exp_tree(
                root,
                RunDir.SYNCED.value,
                _uuid(1005),
                process_order_groups={0: [0], 1: [0]},
            )
            _make_action(synced_exp_yml, 0)

            ep = drv.get_progress(exp_yml)
            ep = drv.reconcile_processes(ep)
            out["overlap_both_metas_built"] = (
                0 in ep.dict["process_metas"] and 1 in ep.dict["process_metas"]
            )

            ep = await drv.sync_process(ep, force=True)
            out["overlap_both_synced"] = (
                0 in ep.dict["process_s3"] and 1 in ep.dict["process_s3"]
            )
            s3_unf, api_unf = ep.list_unfinished_procs()
            out["overlap_experiment_completes"] = not s3_unf and not api_unf
        finally:
            for t in drv.syncer_loops.values():
                t.cancel()
            await asyncio.gather(*drv.syncer_loops.values(), return_exceptions=True)

    return out


def sync_process_recovery_unit_test() -> bool:
    reporter = TestReporter("sync_process_recovery")
    saved_aws = os.environ.pop("AWS_CONFIG_PATH", None)
    try:
        res = asyncio.run(_run_checks())
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False
    finally:
        if saved_aws is not None:
            os.environ["AWS_CONFIG_PATH"] = saved_aws

    reporter.section("legacy experiment populates process_metas")
    reporter.check("legacy_experiment flag set", lambda: res["legacy_flag"])
    reporter.check(
        "process_metas populated (was empty pre-fix)",
        lambda: res["legacy_metas_populated"],
    )
    reporter.check("both actions recorded as done", lambda: res["legacy_actions_done"])
    reporter.check("finisher index recorded", lambda: res["legacy_finisher_recorded"])

    reporter.section("cross-run reconcile from on-disk actions")
    reporter.check(
        "process_metas empty before reconcile", lambda: res["reconcile_before_empty"]
    )
    reporter.check(
        "group rebuilt after reconcile", lambda: res["reconcile_group_present"]
    )
    reporter.check("both actions folded in", lambda: res["reconcile_actions_done"])
    reporter.check(
        "group has both dispatched actions", lambda: res["reconcile_both_dispatched"]
    )
    reporter.check(
        "reconcile is idempotent (no double-count)", lambda: res["reconcile_idempotent"]
    )

    reporter.section("phantom group dropped, experiment finishes")
    reporter.check(
        "both groups unfinished before", lambda: res["phantom_unfinished_before"]
    )
    reporter.check("phantom group dropped", lambda: res["phantom_group_dropped"])
    reporter.check("real group synced", lambda: res["phantom_real_group_synced"])
    reporter.check(
        "experiment completes (no infinite loop)",
        lambda: res["phantom_experiment_completes"],
    )

    reporter.section("split actions (same action_order) all folded")
    reporter.check(
        "both splits folded into process", lambda: res["split_both_dispatched"]
    )
    reporter.check("both splits' samples kept", lambda: res["split_both_samples_kept"])
    reporter.check("split fold is idempotent", lambda: res["split_idempotent"])

    reporter.section("overlapping process groups (action in 2 groups)")
    reporter.check("both group metas built", lambda: res["overlap_both_metas_built"])
    reporter.check("both groups synced", lambda: res["overlap_both_synced"])
    reporter.check(
        "experiment completes (no stall)", lambda: res["overlap_experiment_completes"]
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if sync_process_recovery_unit_test() else 1)
