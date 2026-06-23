"""Tests for the pure process-folding logic in ``domain/sync/process_fold``.

Ports and pins the behavior of the legacy syncer's ``update_process`` method
(``helao/core/drivers/data/sync_driver.py`` lines 1354-1502): the legacy-vs-modern
process-group lookup, process-meta construction, ``process_contrib`` merging, and
``samples_in``/``samples_out`` deduplication.

All functions under test are PURE (stdlib + framework models only, no I/O), so
these are plain synchronous ``def test_*`` with concrete dicts in / dicts out and
no mocks. The ``gen_uuid`` callable is injected to keep the domain deterministic.
"""
from helao.framework.domain.sync.process_fold import (
    find_process_group_index,
    make_process_meta,
    merge_process_contrib,
    deduplicate_samples,
    fold_action_into_process,
)


# --------------------------------------------------------------------------- #
# find_process_group_index                                                    #
# --------------------------------------------------------------------------- #
def test_find_group_modern_lookup():
    # modern: pidx is the group key whose contributor list contains action_order
    groups = {0: [0, 1], 1: [2, 3]}
    assert find_process_group_index(2, groups, is_legacy=False, finisher_idxs=[]) == 1
    assert find_process_group_index(0, groups, is_legacy=False, finisher_idxs=[]) == 0


def test_find_group_legacy_action_past_last_finisher_opens_new_group():
    # legacy 1382-1386: act_idx greater than every finisher -> new group at len(pf_idxs)
    finisher_idxs = [1, 4]
    assert find_process_group_index(7, {}, is_legacy=True, finisher_idxs=finisher_idxs) == 2


def test_find_group_legacy_action_within_a_finisher_window():
    # legacy 1385: pidx = index of the smallest finisher >= act_idx
    finisher_idxs = [1, 4]
    # act_idx 3 -> smallest finisher >= 3 is 4 (index 1)
    assert find_process_group_index(3, {}, is_legacy=True, finisher_idxs=finisher_idxs) == 1
    # act_idx 0 -> smallest finisher >= 0 is 1 (index 0)
    assert find_process_group_index(0, {}, is_legacy=True, finisher_idxs=finisher_idxs) == 0
    # act_idx exactly on a finisher boundary -> that finisher
    assert find_process_group_index(4, {}, is_legacy=True, finisher_idxs=finisher_idxs) == 1


# --------------------------------------------------------------------------- #
# make_process_meta                                                           #
# --------------------------------------------------------------------------- #
def _exp_meta():
    return {
        "yml": "seq/exp/exp.yml",
        "sequence_uuid": "seq-uuid",
        "experiment_uuid": "exp-uuid",
        "orchestrator": "orch",
        "access": "hte",
        "dummy": True,
        "simulation": False,
        "run_type": "eche",
        "campaign_name": "camp",
        "campaign_uuid": "camp-uuid",
        "run_id": "run-1",
        "data_request_id": "dr-1",
        "experiment_params": {"foo": 1},
        "experiment_name": "myexp",
        "process_list": [],
    }


def test_make_process_meta_copies_exp_fields_and_injects_uuid():
    exp = _exp_meta()
    meta = make_process_meta(
        exp, process_list=[], pidx=0, action_meta={}, gen_uuid=lambda s: f"UUID({s})"
    )
    # copied experiment-level fields
    assert meta["sequence_uuid"] == "seq-uuid"
    assert meta["experiment_uuid"] == "exp-uuid"
    assert meta["orchestrator"] == "orch"
    assert meta["access"] == "hte"
    assert meta["dummy"] is True
    assert meta["simulation"] is False
    assert meta["run_type"] == "eche"
    assert meta["campaign_name"] == "camp"
    assert meta["campaign_uuid"] == "camp-uuid"
    assert meta["run_id"] == "run-1"
    # data_request_id only copied when present
    assert meta["data_request_id"] == "dr-1"
    # derived fields
    assert meta["process_params"] == {"foo": 1}
    assert meta["technique_name"] == "myexp"  # falls back to experiment_name
    assert meta["process_group_index"] == 0
    assert meta["dispatched_actions_abbr"] == []
    # injected uuid used because process_list is empty
    assert meta["process_uuid"] == "UUID(exp-uuid__0)"


def test_make_process_meta_uses_process_list_when_present():
    exp = _exp_meta()
    meta = make_process_meta(
        exp,
        process_list=["plist-uuid-0", "plist-uuid-1"],
        pidx=1,
        action_meta={},
        gen_uuid=lambda s: "SHOULD-NOT-BE-USED",
    )
    assert meta["process_uuid"] == "plist-uuid-1"


def test_make_process_meta_omits_data_request_id_when_absent():
    exp = _exp_meta()
    del exp["data_request_id"]
    meta = make_process_meta(exp, [], 0, {}, gen_uuid=lambda s: "u")
    assert "data_request_id" not in meta


def test_make_process_meta_technique_name_prefers_explicit():
    exp = _exp_meta()
    exp["technique_name"] = "cv"
    meta = make_process_meta(exp, [], 0, {}, gen_uuid=lambda s: "u")
    assert meta["technique_name"] == "cv"


def test_make_process_meta_does_not_mutate_exp_meta():
    exp = _exp_meta()
    snapshot = dict(exp)
    make_process_meta(exp, [], 0, {}, gen_uuid=lambda s: "u")
    assert exp == snapshot


# --------------------------------------------------------------------------- #
# merge_process_contrib                                                        #
# --------------------------------------------------------------------------- #
def test_merge_contrib_scalar_replace_when_new():
    pm = {"dispatched_actions_abbr": []}
    act = {"action_foo": 42, "process_contrib": ["action_foo"]}
    out = merge_process_contrib(pm, act, act["process_contrib"])
    assert out["process_foo"] == 42


def test_merge_contrib_dict_update():
    pm = {"process_files": {"a": 1}, "dispatched_actions_abbr": []}
    act = {"action_files": {"b": 2}, "process_contrib": ["action_files"]}
    out = merge_process_contrib(pm, act, act["process_contrib"])
    assert out["process_files"] == {"a": 1, "b": 2}


def test_merge_contrib_list_extend():
    pm = {"process_tags": ["x"], "dispatched_actions_abbr": []}
    act = {"action_tags": ["y", "z"], "process_contrib": ["action_tags"]}
    out = merge_process_contrib(pm, act, act["process_contrib"])
    assert out["process_tags"] == ["x", "y", "z"]


def test_merge_contrib_skips_missing_keys():
    pm = {"dispatched_actions_abbr": []}
    act = {"process_contrib": ["action_missing"]}
    out = merge_process_contrib(pm, act, act["process_contrib"])
    assert "process_missing" not in out


def test_merge_contrib_does_not_mutate_inputs():
    pm = {"process_tags": ["x"], "dispatched_actions_abbr": []}
    act = {"action_tags": ["y"], "process_contrib": ["action_tags"]}
    pm_snap = {"process_tags": ["x"], "dispatched_actions_abbr": []}
    merge_process_contrib(pm, act, act["process_contrib"])
    assert pm == pm_snap


# --------------------------------------------------------------------------- #
# deduplicate_samples                                                          #
# --------------------------------------------------------------------------- #
def _dispatched():
    # action_uuid -> orch_submit_order
    return [
        {"action_uuid": "uuid-early", "orch_submit_order": 0},
        {"action_uuid": "uuid-late", "orch_submit_order": 5},
    ]


def test_dedup_samples_in_picks_earliest():
    samples = [
        {"global_label": "S1", "action_uuid": ["uuid-late"], "tag": "late"},
        {"global_label": "S1", "action_uuid": ["uuid-early"], "tag": "early"},
    ]
    out = deduplicate_samples(samples, _dispatched(), is_input=True)
    assert len(out) == 1
    assert out[0]["tag"] == "early"


def test_dedup_samples_out_picks_latest():
    samples = [
        {"global_label": "S1", "action_uuid": ["uuid-early"], "tag": "early"},
        {"global_label": "S1", "action_uuid": ["uuid-late"], "tag": "late"},
    ]
    out = deduplicate_samples(samples, _dispatched(), is_input=False)
    assert len(out) == 1
    assert out[0]["tag"] == "late"


def test_dedup_samples_skips_unlabeled():
    samples = [
        {"action_uuid": ["uuid-early"], "tag": "no-label"},
        {"global_label": "S1", "action_uuid": ["uuid-early"], "tag": "kept"},
    ]
    out = deduplicate_samples(samples, _dispatched(), is_input=True)
    assert len(out) == 1
    assert out[0]["tag"] == "kept"


def test_dedup_samples_distinct_labels_all_kept():
    samples = [
        {"global_label": "S1", "action_uuid": ["uuid-early"], "tag": "a"},
        {"global_label": "S2", "action_uuid": ["uuid-late"], "tag": "b"},
    ]
    out = deduplicate_samples(samples, _dispatched(), is_input=True)
    labels = {s["global_label"] for s in out}
    assert labels == {"S1", "S2"}


def test_dedup_samples_unknown_uuid_falls_back_to_position():
    # legacy 1482-1483: when no dispatched action matches, use list index as order
    samples = [
        {"global_label": "S1", "action_uuid": ["unknown-a"], "tag": "pos0"},
        {"global_label": "S1", "action_uuid": ["unknown-b"], "tag": "pos1"},
    ]
    # samples_in -> earliest position (index 0)
    out_in = deduplicate_samples(samples, _dispatched(), is_input=True)
    assert out_in[0]["tag"] == "pos0"
    # samples_out -> latest position (index 1)
    out_out = deduplicate_samples(samples, _dispatched(), is_input=False)
    assert out_out[0]["tag"] == "pos1"


# --------------------------------------------------------------------------- #
# fold_action_into_process — end to end                                       #
# --------------------------------------------------------------------------- #
def _prg_dict_modern():
    return {
        "yml": "seq/exp/exp.yml",
        "api": False,
        "s3": False,
        "process_actions_done": {},
        "process_groups": {0: [0, 1]},
        "process_metas": {},
        "process_s3": [],
        "process_api": [],
        "legacy_finisher_idxs": [],
        "legacy_experiment": False,
    }


_ACT_UUIDS = [
    "00000000-0000-0000-0000-000000000000",
    "11111111-1111-1111-1111-111111111111",
]


def _act_meta_modern(action_order=0):
    return {
        "action_order": action_order,
        "action_uuid": _ACT_UUIDS[action_order],
        "action_name": "doit",
        "action_timestamp": "2026-06-23T00:00:00",
        "orch_submit_order": action_order,
        "process_finish": False,
        "technique_name": "cv",
        "process_contrib": ["action_files", "samples_in"],
        "action_files": {"f": 1},
        "samples_in": [
            {"global_label": "S1", "action_uuid": [_ACT_UUIDS[0]]},
        ],
        "action_params": {},
    }


def test_fold_modern_end_to_end_builds_meta_and_records_action():
    exp = _exp_meta()
    prg = _prg_dict_modern()
    act = _act_meta_modern(action_order=0)

    out = fold_action_into_process(exp, prg, act, gen_uuid=lambda s: "U-%s" % s)

    # process meta created at pidx 0
    assert 0 in out["process_metas"]
    pm = out["process_metas"][0]
    assert pm["experiment_uuid"] == "exp-uuid"
    assert pm["process_group_index"] == 0
    assert pm["process_uuid"] == "U-exp-uuid__0"
    # contrib merged: action_files -> process_files
    assert pm["process_files"] == {"f": 1}
    # bare "samples_in" contrib key merges to "samples_in" (no action_ prefix
    # to rewrite) AND is eligible for dedup; single sample survives
    assert pm["samples_in"] == [{"global_label": "S1", "action_uuid": [_ACT_UUIDS[0]]}]
    # action recorded in dispatched_actions_abbr and process_actions_done
    assert len(pm["dispatched_actions_abbr"]) == 1
    assert 0 in out["process_actions_done"]
    # first action sets process_timestamp
    assert pm["process_timestamp"] == "2026-06-23T00:00:00"
    # technique from action overrides
    assert pm["technique_name"] == "cv"


def test_fold_prefixed_sample_contrib_is_not_deduped():
    # legacy quirk (line 1467): dedup only fires for the BARE "samples_in" key.
    # An "action_samples_out" contrib rewrites to "process_samples_out" and is
    # merged but never passed through dedup, so duplicate labels remain.
    exp = _exp_meta()
    prg = _prg_dict_modern()
    prg["process_groups"] = {0: [0]}
    act = _act_meta_modern(action_order=0)
    act["process_contrib"] = ["action_samples_out"]
    act["action_samples_out"] = [
        {"global_label": "S1", "action_uuid": [_ACT_UUIDS[0]], "tag": "a"},
        {"global_label": "S1", "action_uuid": [_ACT_UUIDS[0]], "tag": "b"},
    ]
    del act["samples_in"]
    out = fold_action_into_process(exp, prg, act, gen_uuid=lambda s: "u")
    pm = out["process_metas"][0]
    # both duplicates retained -> dedup did NOT run for the prefixed key
    assert len(pm["process_samples_out"]) == 2


def test_fold_does_not_mutate_inputs():
    exp = _exp_meta()
    prg = _prg_dict_modern()
    act = _act_meta_modern(action_order=0)

    import copy

    exp_snap = copy.deepcopy(exp)
    prg_snap = copy.deepcopy(prg)
    act_snap = copy.deepcopy(act)

    fold_action_into_process(exp, prg, act, gen_uuid=lambda s: "u")

    assert exp == exp_snap, "exp_meta mutated"
    assert prg == prg_snap, "prg_dict mutated"
    assert act == act_snap, "act_meta mutated"


def test_fold_legacy_registers_finisher_and_group():
    exp = _exp_meta()
    prg = {
        "yml": "seq/exp/exp.yml",
        "api": False,
        "s3": False,
        "process_actions_done": {},
        "process_groups": {},
        "process_metas": {},
        "process_s3": [],
        "process_api": [],
        "legacy_finisher_idxs": [],
        "legacy_experiment": True,
    }
    act = _act_meta_modern(action_order=0)
    act["process_finish"] = True

    out = fold_action_into_process(exp, prg, act, gen_uuid=lambda s: "u")

    # finisher recorded
    assert out["legacy_finisher_idxs"] == [0]
    # action appended to its computed process group
    # act_idx 0 == max finisher -> pidx 0 (index of smallest finisher >= 0)
    assert 0 in out["process_groups"]
    assert 0 in out["process_groups"][0]


def test_fold_legacy_does_not_build_modern_process_meta():
    # legacy branch in update_process does not construct process_metas
    exp = _exp_meta()
    prg = {
        "yml": "seq/exp/exp.yml",
        "api": False,
        "s3": False,
        "process_actions_done": {},
        "process_groups": {},
        "process_metas": {},
        "process_s3": [],
        "process_api": [],
        "legacy_finisher_idxs": [],
        "legacy_experiment": True,
    }
    act = _act_meta_modern(action_order=0)
    act["process_finish"] = True
    out = fold_action_into_process(exp, prg, act, gen_uuid=lambda s: "u")
    assert out["process_metas"] == {}
