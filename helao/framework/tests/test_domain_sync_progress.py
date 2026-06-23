"""Tests for the pure ``Progress`` value object in ``domain/sync/progress``.

Verifies the ``.prg`` payload schema is byte-compatible with the legacy syncer
(``helao/core/drivers/data/sync_driver.py`` lines 569-591), the pure predicates
(``s3_done``/``api_done``/``list_unfinished_procs``), the functional updaters
(``with_s3_done``/``with_api_done`` return NEW instances), and the
``should_push_process`` push-condition gate (legacy / modern / force branches).
"""
from helao.framework.domain.sync.progress import Progress, should_push_process


# --------------------------------------------------------------------------- #
# initial() schema                                                            #
# --------------------------------------------------------------------------- #
def test_initial_action_schema():
    prog = Progress.initial("a/b/act.yml", "action", {"yml": "a/b/act.yml"})
    d = prog.to_dict()
    assert d == {
        "yml": "a/b/act.yml",
        "api": False,
        "s3": False,
        "files_pending": [],
        "files_s3": {},
    }
    assert prog.yml_relpath == "a/b/act.yml"


def test_initial_experiment_schema_with_groups():
    groups = {0: [0, 1], 1: [2]}
    meta = {"yml": "a/b/exp.yml", "process_order_groups": groups}
    prog = Progress.initial("a/b/exp.yml", "experiment", meta)
    d = prog.to_dict()
    assert d == {
        "yml": "a/b/exp.yml",
        "api": False,
        "s3": False,
        "process_actions_done": {},
        "process_groups": groups,
        "process_metas": {},
        "process_s3": [],
        "process_api": [],
        "legacy_finisher_idxs": [],
        "legacy_experiment": False,  # process_groups present -> not legacy
    }


def test_initial_experiment_schema_no_groups_is_legacy():
    meta = {"yml": "a/b/exp.yml"}  # no process_order_groups
    prog = Progress.initial("a/b/exp.yml", "experiment", meta)
    d = prog.to_dict()
    assert d["process_groups"] == {}
    assert d["legacy_experiment"] is True


def test_initial_uses_meta_yml_key():
    prog = Progress.initial("x/y/act.yml", "action", {"yml": "resolved/target.yml"})
    assert prog.to_dict()["yml"] == "resolved/target.yml"


def test_initial_other_node_type_has_only_base_keys():
    prog = Progress.initial("a/b/seq.yml", "sequence", {"yml": "a/b/seq.yml"})
    assert prog.to_dict() == {"yml": "a/b/seq.yml", "api": False, "s3": False}


def test_initial_groups_are_copied_not_shared():
    groups = {0: [0, 1]}
    meta = {"yml": "e.yml", "process_order_groups": groups}
    prog = Progress.initial("e.yml", "experiment", meta)
    groups[0].append(99)
    # mutating the caller's dict must not bleed into the Progress payload
    assert prog.to_dict()["process_groups"] == {0: [0, 1]}


# --------------------------------------------------------------------------- #
# from_dict / to_dict                                                         #
# --------------------------------------------------------------------------- #
def test_from_dict_to_dict_round_trip():
    payload = {
        "yml": "a/b/act.yml",
        "api": True,
        "s3": False,
        "files_pending": ["f1"],
        "files_s3": {"f1": "key"},
    }
    prog = Progress.from_dict("a/b/act.yml", payload)
    assert prog.to_dict() == payload


def test_to_dict_returns_copy_not_internal_ref():
    payload = {"yml": "a/b/act.yml", "api": False, "s3": False, "process_s3": []}
    prog = Progress.from_dict("a/b/act.yml", payload)
    out = prog.to_dict()
    out["process_s3"].append(7)
    out["s3"] = True
    # the internal dict must be untouched
    assert prog.to_dict()["process_s3"] == []
    assert prog.to_dict()["s3"] is False


def test_from_dict_copies_input():
    payload = {"yml": "a.yml", "api": False, "s3": False, "process_s3": []}
    prog = Progress.from_dict("a.yml", payload)
    payload["process_s3"].append(1)
    payload["s3"] = True
    assert prog.to_dict()["process_s3"] == []
    assert prog.to_dict()["s3"] is False


# --------------------------------------------------------------------------- #
# s3_done / api_done                                                          #
# --------------------------------------------------------------------------- #
def test_s3_done_and_api_done_properties():
    prog = Progress.from_dict("a.yml", {"yml": "a.yml", "api": True, "s3": False})
    assert prog.api_done is True
    assert prog.s3_done is False


# --------------------------------------------------------------------------- #
# list_unfinished_procs                                                       #
# --------------------------------------------------------------------------- #
def _exp_progress(s3_done, api_done):
    return Progress.from_dict(
        "e.yml",
        {
            "yml": "e.yml",
            "api": False,
            "s3": False,
            "process_groups": {0: [0], 1: [1], 2: [2]},
            "process_s3": list(s3_done),
            "process_api": list(api_done),
            "process_actions_done": {},
            "process_metas": {},
            "legacy_finisher_idxs": [],
            "legacy_experiment": False,
        },
    )


def test_list_unfinished_procs_mixed():
    prog = _exp_progress(s3_done=[0], api_done=[0, 1])
    s3_unf, api_unf = prog.list_unfinished_procs()
    assert s3_unf == [1, 2]
    assert api_unf == [2]


def test_list_unfinished_procs_all_done():
    prog = _exp_progress(s3_done=[0, 1, 2], api_done=[0, 1, 2])
    assert prog.list_unfinished_procs() == ([], [])


def test_list_unfinished_procs_non_experiment_empty():
    prog = Progress.initial("a.yml", "action", {"yml": "a.yml"})
    assert prog.list_unfinished_procs() == ([], [])


# --------------------------------------------------------------------------- #
# with_s3_done / with_api_done  (functional, return NEW)                      #
# --------------------------------------------------------------------------- #
def test_with_s3_done_returns_new_instance_leaving_original():
    orig = Progress.from_dict("a.yml", {"yml": "a.yml", "api": False, "s3": False})
    updated = orig.with_s3_done()
    assert updated is not orig
    assert updated.s3_done is True
    assert orig.s3_done is False  # original untouched
    # original payload dict object is not shared with the new instance
    assert orig.to_dict()["s3"] is False


def test_with_api_done_returns_new_instance_leaving_original():
    orig = Progress.from_dict("a.yml", {"yml": "a.yml", "api": False, "s3": False})
    updated = orig.with_api_done()
    assert updated is not orig
    assert updated.api_done is True
    assert orig.api_done is False


def test_with_s3_done_explicit_false():
    orig = Progress.from_dict("a.yml", {"yml": "a.yml", "api": False, "s3": True})
    updated = orig.with_s3_done(False)
    assert updated.s3_done is False
    assert orig.s3_done is True


def test_with_s3_done_preserves_yml_relpath_and_other_keys():
    orig = Progress.initial("e.yml", "experiment", {"yml": "e.yml"})
    updated = orig.with_s3_done()
    assert updated.yml_relpath == "e.yml"
    assert updated.to_dict()["process_groups"] == {}


# --------------------------------------------------------------------------- #
# should_push_process                                                         #
# --------------------------------------------------------------------------- #
def test_should_push_force_overrides_everything():
    assert (
        should_push_process(
            pidx=0,
            process_groups={0: [5]},
            process_actions_done={},
            is_legacy=True,
            finisher_idxs=[],
            force=True,
        )
        is True
    )


def test_should_push_legacy_true_when_max_in_finisher_and_all_done():
    assert (
        should_push_process(
            pidx=0,
            process_groups={0: [0, 1, 2]},
            process_actions_done={0: "a", 1: "b", 2: "c"},
            is_legacy=True,
            finisher_idxs=[2],
            force=False,
        )
        is True
    )


def test_should_push_legacy_false_when_max_not_in_finisher():
    assert (
        should_push_process(
            pidx=0,
            process_groups={0: [0, 1, 2]},
            process_actions_done={0: "a", 1: "b", 2: "c"},
            is_legacy=True,
            finisher_idxs=[1],
            force=False,
        )
        is False
    )


def test_should_push_legacy_false_when_actions_not_all_done():
    assert (
        should_push_process(
            pidx=0,
            process_groups={0: [0, 1, 2]},
            process_actions_done={0: "a", 2: "c"},  # 1 missing
            is_legacy=True,
            finisher_idxs=[2],
            force=False,
        )
        is False
    )


def test_should_push_modern_true_when_all_done_and_meta_present():
    assert (
        should_push_process(
            pidx=1,
            process_groups={1: [3, 4]},
            process_actions_done={3: "a", 4: "b"},
            is_legacy=False,
            finisher_idxs=[],
            force=False,
            process_metas={1: {"process_uuid": "u"}},
        )
        is True
    )


def test_should_push_modern_false_when_meta_empty():
    assert (
        should_push_process(
            pidx=1,
            process_groups={1: [3, 4]},
            process_actions_done={3: "a", 4: "b"},
            is_legacy=False,
            finisher_idxs=[],
            force=False,
            process_metas={1: {}},
        )
        is False
    )


def test_should_push_modern_false_when_meta_missing():
    assert (
        should_push_process(
            pidx=1,
            process_groups={1: [3, 4]},
            process_actions_done={3: "a", 4: "b"},
            is_legacy=False,
            finisher_idxs=[],
            force=False,
            process_metas={},
        )
        is False
    )


def test_should_push_modern_false_when_actions_not_all_done():
    assert (
        should_push_process(
            pidx=1,
            process_groups={1: [3, 4]},
            process_actions_done={3: "a"},
            is_legacy=False,
            finisher_idxs=[],
            force=False,
            process_metas={1: {"process_uuid": "u"}},
        )
        is False
    )
