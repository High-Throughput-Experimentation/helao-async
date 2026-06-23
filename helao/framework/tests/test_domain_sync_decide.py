"""Tests for the pure sync-decision FSM in ``domain/sync/decide``.

Covers every ``SyncAction`` branch of :func:`decide_sync` (legacy
``helao/core/drivers/data/sync_driver.py`` lines 1027-1106), the
pending-file-list dedup (legacy 1108-1117), the hlo-vs-parquet size-threshold
plan (legacy 1123-1159), and the metadata patch (legacy 1229-1237). All pure
data in, value object / dict out -- no mocks, no I/O.
"""
from helao.framework.domain.sync.decide import (
    SyncAction,
    RequeueItem,
    SyncDecision,
    decide_sync,
    build_upload_file_list,
    hlo_upload_plan,
    patch_metadata,
)


# --------------------------------------------------------------------------- #
# decide_sync — every SyncAction branch                                       #
# --------------------------------------------------------------------------- #
def test_decide_not_exists_skips():
    d = decide_sync(
        exists=False,
        node_status="finished",
        child_statuses=[],
        already_synced=False,
        rank=5,
    )
    assert d.action is SyncAction.SKIP
    assert d.requeue == ()


def test_decide_already_synced_skips():
    # legacy: status == "synced" -> return True (nothing to do)
    d = decide_sync(
        exists=True,
        node_status="synced",
        child_statuses=[],
        already_synced=True,
        rank=5,
    )
    assert d.action is SyncAction.SKIP
    assert d.requeue == ()


def test_decide_already_synced_flag_skips_even_when_status_finished():
    d = decide_sync(
        exists=True,
        node_status="finished",
        child_statuses=[],
        already_synced=True,
        rank=5,
    )
    assert d.action is SyncAction.SKIP


def test_decide_active_soft_blocks():
    # legacy: status == "active" -> return False (cannot sync yet)
    d = decide_sync(
        exists=True,
        node_status="active",
        child_statuses=[],
        already_synced=False,
        rank=5,
    )
    assert d.action is SyncAction.SOFT_BLOCK
    assert d.requeue == ()


def test_decide_unsynced_children_requeue_ranks():
    # legacy lines 1082-1083: parent_rank = rank - 1, child_rank = rank - 2.
    # Children enqueue at child_rank (rank-2); self enqueues at parent_rank
    # (rank-1). Only non-synced children are re-queued.
    d = decide_sync(
        exists=True,
        node_status="finished",
        child_statuses=[
            ("seq/exp/a-act.yml", "finished"),
            ("seq/exp/b-act.yml", "synced"),
            ("seq/exp/c-act.yml", "finished"),
        ],
        already_synced=False,
        rank=5,
    )
    assert d.action is SyncAction.REQUEUE_CHILDREN
    # children at rank-2 == 3, self (relpath == "") at rank-1 == 4, self last
    assert d.requeue == (
        RequeueItem(relpath="seq/exp/a-act.yml", rank=3),
        RequeueItem(relpath="seq/exp/c-act.yml", rank=3),
        RequeueItem(relpath="", rank=4),
    )


def test_decide_active_child_also_requeues():
    # An "active" child is not "synced" -> still triggers REQUEUE_CHILDREN
    # (the legacy active_children short-circuit returns False; in the pure
    # decider a non-synced child uniformly maps to REQUEUE_CHILDREN per spec).
    d = decide_sync(
        exists=True,
        node_status="finished",
        child_statuses=[("seq/exp/a-act.yml", "active")],
        already_synced=False,
        rank=10,
    )
    assert d.action is SyncAction.REQUEUE_CHILDREN
    assert d.requeue == (
        RequeueItem(relpath="seq/exp/a-act.yml", rank=8),
        RequeueItem(relpath="", rank=9),
    )


def test_decide_all_children_synced_proceeds():
    d = decide_sync(
        exists=True,
        node_status="finished",
        child_statuses=[
            ("seq/exp/a-act.yml", "synced"),
            ("seq/exp/b-act.yml", "synced"),
        ],
        already_synced=False,
        rank=5,
    )
    assert d.action is SyncAction.PROCEED
    assert d.requeue == ()


def test_decide_finished_no_children_proceeds():
    # an action node: no children, finished -> proceed
    d = decide_sync(
        exists=True,
        node_status="finished",
        child_statuses=[],
        already_synced=False,
        rank=5,
    )
    assert d.action is SyncAction.PROCEED


def test_decision_is_frozen():
    d = decide_sync(
        exists=True,
        node_status="finished",
        child_statuses=[],
        already_synced=False,
        rank=5,
    )
    import dataclasses

    try:
        d.action = SyncAction.SKIP  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:  # pragma: no cover
        raise AssertionError("SyncDecision should be frozen")


# --------------------------------------------------------------------------- #
# build_upload_file_list — dedup (legacy 1108-1117)                           #
# --------------------------------------------------------------------------- #
def test_build_upload_file_list_appends_new_only():
    # legacy: pending += [hlo+misc not in pending and not in s3_dict]
    pending = ["a.hlo"]
    s3_dict = {"b.hlo": "raw_data/x/b.hlo.json"}
    hlo = ["a.hlo", "b.hlo", "c.hlo"]
    misc = ["d.txt"]
    out = build_upload_file_list(pending, s3_dict, hlo, misc)
    # a.hlo already pending (kept, not duplicated); b.hlo already in s3 (skip);
    # c.hlo + d.txt are new and appended in hlo-then-misc order.
    assert out == ["a.hlo", "c.hlo", "d.txt"]


def test_build_upload_file_list_does_not_mutate_input():
    pending = ["a.hlo"]
    out = build_upload_file_list(pending, {}, ["b.hlo"], [])
    assert pending == ["a.hlo"]  # original untouched
    assert out == ["a.hlo", "b.hlo"]


def test_build_upload_file_list_empty():
    assert build_upload_file_list([], {}, [], []) == []


def test_build_upload_file_list_no_duplicate_within_inputs():
    # a value appearing in both hlo and misc is only appended once
    out = build_upload_file_list([], {}, ["x"], ["x"])
    assert out == ["x"]


# --------------------------------------------------------------------------- #
# hlo_upload_plan — size threshold (legacy 1123-1159)                         #
# --------------------------------------------------------------------------- #
def test_hlo_plan_small_hlo_is_hlo():
    # legacy: hlo file < threshold -> upload as .json ("hlo" plan)
    assert hlo_upload_plan(file_size=1024, is_hlo=True) == "hlo"


def test_hlo_plan_at_default_threshold_is_parquet():
    # default threshold is 1_000_000_000; size == threshold -> parquet
    assert hlo_upload_plan(file_size=1_000_000_000, is_hlo=True) == "parquet"


def test_hlo_plan_just_below_default_threshold_is_hlo():
    assert hlo_upload_plan(file_size=1_000_000_000 - 1, is_hlo=True) == "hlo"


def test_hlo_plan_legacy_1gib_threshold_boundary():
    # pass the legacy 1024**3 (1 GiB) threshold to match byte-for-byte: legacy
    # comparison is strictly-less-than, so exactly 1 GiB -> parquet.
    assert hlo_upload_plan(file_size=1024**3, is_hlo=True, threshold=1024**3) == "parquet"
    assert hlo_upload_plan(file_size=1024**3 - 1, is_hlo=True, threshold=1024**3) == "hlo"


def test_hlo_plan_non_hlo_is_always_hlo_path():
    # non-hlo files are uploaded as-is regardless of size; legacy's else-branch
    # treats them as raw uploads -> the "hlo" (raw, no parquet) plan.
    assert hlo_upload_plan(file_size=1024**4, is_hlo=False) == "hlo"


def test_hlo_plan_custom_threshold():
    assert hlo_upload_plan(file_size=100, is_hlo=True, threshold=50) == "parquet"
    assert hlo_upload_plan(file_size=49, is_hlo=True, threshold=50) == "hlo"


# --------------------------------------------------------------------------- #
# patch_metadata — type conversion + technique extraction (legacy 1229-1237)  #
# --------------------------------------------------------------------------- #
def test_patch_metadata_renames_exid_key():
    # legacy MOD_PATCH: {"exid": "exec_id"}
    meta = {"exid": "abc", "action_uuid": "u"}
    out = patch_metadata(meta, "action", None)
    assert out == {"exec_id": "abc", "action_uuid": "u"}


def test_patch_metadata_does_not_mutate_original():
    meta = {"exid": "abc", "technique_name": "cv"}
    out = patch_metadata(meta, "action", None)
    assert meta == {"exid": "abc", "technique_name": "cv"}  # unchanged
    assert out is not meta


def test_patch_metadata_technique_list_split():
    # legacy 1234-1237: technique_name list -> element at action_split index
    meta = {"technique_name": ["cv", "cp", "ca"], "action_split": 1}
    out = patch_metadata(meta, "action", None)
    assert out["technique_name"] == "cp"


def test_patch_metadata_technique_list_default_split_zero():
    meta = {"technique_name": ["cv", "cp"]}  # no action_split -> index 0
    out = patch_metadata(meta, "action", None)
    assert out["technique_name"] == "cv"


def test_patch_metadata_scalar_technique_untouched():
    meta = {"technique_name": "cv"}
    out = patch_metadata(meta, "action", None)
    assert out["technique_name"] == "cv"


def test_patch_metadata_missing_technique_defaults_na():
    # legacy: meta.get("technique_name", "NA"); a scalar "NA" stays as-is.
    meta = {"action_uuid": "u"}
    out = patch_metadata(meta, "action", None)
    assert "technique_name" not in out  # not injected when absent and scalar


def test_patch_metadata_optional_technique_patch_callable():
    # technique_patch hook lets the caller substitute MODEL-level conversion
    # without coupling the pure domain to pydantic models.
    def patcher(d, node_type):
        d = dict(d)
        d["patched"] = node_type
        return d

    meta = {"exid": "x"}
    out = patch_metadata(meta, "experiment", patcher)
    assert out["exec_id"] == "x"
    assert out["patched"] == "experiment"
