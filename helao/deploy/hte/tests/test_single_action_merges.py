"""Single-action experiment merges: load_solid_only, redundant unloads, OCV technique.

Each test fails if the merge it guards is undone or made inexact.
"""

import inspect

import pytest

from helao.deploy.hte.experiments import (
    ADSS_exp,
    ANEC_exp,
    ECHE_exp,
    ECHEUVIS_exp,
    ECMS_exp,
    HISPEC_exp,
    UVIS_exp,
)
from helao.deploy.hte.sequences import (
    ADSS_seq,
    ANEC_seq,
    ECHE_seq,
    ECMS_seq,
    HISPEC_seq,
    ECHEUVIS_seq,
    UVIS_T_seq,
)
from helao.helpers.premodels import Experiment

MASK = ("uuid", "timestamp", "time", "experiment", "action_order")


def _run(fn, **kw):
    return fn(Experiment(experiment_name=fn.__name__, experiment_params={}), **kw)


def _flat(actions):
    out = []
    for a in actions:
        d = a.model_dump(mode="json")
        out.append({k: v for k, v in d.items() if not any(m in k for m in MASK)})
    return out


def _names(seq_fn, **kw):
    return [e.experiment_name for e in seq_fn(**kw)]


@pytest.mark.parametrize("lib,pre", [(ANEC_exp, "ANEC"), (ECMS_exp, "ECMS")])
def test_load_solid_only_is_unload_then_load(lib, pre):
    kw = {"solid_plate_id": 7, "solid_sample_no": 3}
    got = _flat(_run(getattr(lib, f"{pre}_sub_load_solid_only"), **kw))
    want = _flat(_run(getattr(lib, f"{pre}_sub_unload_cell"))) + _flat(
        _run(getattr(lib, f"{pre}_sub_load_solid"), **kw)
    )
    assert got == want
    assert [g["action_name"] for g in got] == [
        "archive_custom_unloadall",
        "archive_custom_load",
    ]
    assert got[1]["action_params"]["load_sample_in"]["plate_id"] == 7


def test_ecms_load_solid_only_is_published():
    assert "ECMS_sub_load_solid_only" in ECMS_exp.EXPERIMENTS
    # the unmerged names stay published: queued sequences re-pair by name
    assert "ECMS_sub_unload_cell" in ECMS_exp.EXPERIMENTS
    assert "ECMS_sub_load_solid" in ECMS_exp.EXPERIMENTS


def _assert_no_pair(names, first, second):
    for a, b in zip(names, names[1:]):
        assert not (a == first and b == second), (first, second)


@pytest.mark.parametrize(
    "mod,pre,first,second",
    [
        (ANEC_seq, "ANEC", "ANEC_sub_unload_cell", "ANEC_sub_load_solid"),
        (ECMS_seq, "ECMS", "ECMS_sub_unload_cell", "ECMS_sub_load_solid"),
    ],
)
def test_sequences_use_load_solid_only(mod, pre, first, second):
    seen = 0
    for name in mod.SEQUENCES:
        try:
            names = _names(getattr(mod, name))
        except (
            Exception
        ):  # noqa: BLE001 - sequences needing args are not default-buildable
            continue
        _assert_no_pair(names, first, second)
        assert first not in names and second not in names, name
        seen += f"{pre}_sub_load_solid_only" in names
    assert seen >= 10


def test_redundant_unloads_removed():
    plans = [
        _names(ECHE_seq.ECHE_CA),
        _names(UVIS_T_seq.UVIS_T),
    ]
    follow = {
        "ECHE_sub_unloadall_customs": {"ECHE_sub_startup"},
        "UVIS_sub_unloadall_customs": {"UVIS_sub_startup", "UVIS_sub_shutdown"},
    }
    for names in plans:
        for a, b in zip(names, names[1:]):
            assert b not in follow.get(a, ()), (a, b)
    # the startups still begin with the identical unload, so the unload is not lost
    assert _names(ECHE_seq.ECHE_CA)[0] == "ECHE_sub_startup"
    for fn, name in [
        (ECHE_exp.ECHE_sub_startup, "ECHE_sub_unloadall_customs"),
        (UVIS_exp.UVIS_sub_startup, "UVIS_sub_unloadall_customs"),
    ]:
        first = _flat(_run(fn))[0]
        alone = _flat(_run(getattr(ECHE_exp if "ECHE" in name else UVIS_exp, name)))
        assert first == alone[0]


def test_uvis_shutdown_still_starts_with_the_unload():
    first = _flat(_run(UVIS_exp.UVIS_sub_shutdown))[0]
    assert first == _flat(_run(UVIS_exp.UVIS_sub_unloadall_customs))[0]


@pytest.mark.parametrize(
    "fn,server,action,start",
    [
        # analyses read these experiments by first action / position
        (UVIS_exp.UVIS_sub_measure, "SAMPLE", "archive_custom_query_sample", "no_wait"),
        (
            ECHEUVIS_exp.ECHEUVIS_sub_OCV_led,
            "SAMPLE",
            "archive_custom_query_sample",
            "wait_for_all",
        ),
        (ECMS_exp.ECMS_sub_cali, "MFC", "set_flowrate", "no_wait"),
    ],
)
def test_first_action_pinned(fn, server, action, start):
    a = _run(fn)[0]
    assert (a.action_server.server_name, a.action_name, a.start_condition.name) == (
        server,
        action,
        start,
    )


def test_anec_ocv_records_ocv_technique():
    acts = _run(ANEC_exp.ANEC_sub_OCV)
    pstat = [a for a in acts if a.action_server.server_name == "PSTAT"]
    assert [a.technique_name for a in pstat] == ["OCV"]


# ---- tier 3: optional leading knobs on the target experiment ----


def test_drain_cell_unload_first_is_unloadall_then_drain():
    kw = {"DrainWait_s": 12, "ReturnLineReverseWait_s": 3}
    got = _flat(_run(ADSS_exp.ADSS_sub_drain_cell, unload_first=True, **kw))
    want = _flat(_run(ADSS_exp.ADSS_sub_unloadall_customs)) + _flat(
        _run(ADSS_exp.ADSS_sub_drain_cell, **kw)
    )
    assert got == want
    assert got[0]["action_name"] == "archive_custom_unloadall"


@pytest.mark.parametrize("n2", [True, False])
def test_drain_cell_n2flow_precedes_unload(n2):
    got = _flat(_run(ADSS_exp.ADSS_sub_drain_cell, N2flow=n2, unload_first=True))
    want = (
        _flat(_run(ADSS_exp.ADSS_sub_gasvalve_N2flow, open=n2))
        + _flat(_run(ADSS_exp.ADSS_sub_unloadall_customs))
        + _flat(_run(ADSS_exp.ADSS_sub_drain_cell))
    )
    assert got == want


@pytest.mark.parametrize("n2", [True, False])
def test_recirculate_n2flow_is_valve_then_recirculate(n2):
    kw = {"wait_time_s": 7}
    got = _flat(_run(ADSS_exp.ADSS_sub_recirculate, N2flow=n2, **kw))
    want = _flat(_run(ADSS_exp.ADSS_sub_gasvalve_N2flow, open=n2)) + _flat(
        _run(ADSS_exp.ADSS_sub_recirculate, **kw)
    )
    assert got == want


def test_adss_knobs_unset_add_nothing():
    # defaults keep the targets as they were: first action is their own
    assert _flat(_run(ADSS_exp.ADSS_sub_drain_cell))[0]["action_name"] == "pump"
    assert _flat(_run(ADSS_exp.ADSS_sub_recirculate))[0]["action_name"] == "gasvalve"
    assert len(_flat(_run(ADSS_exp.ADSS_sub_recirculate))) == 4
    assert len(_flat(_run(ADSS_exp.ADSS_sub_drain_cell))) == 15


def test_engage_unload_first_is_unloadall_then_engage():
    kw = {"flow_we": False, "flow_ce": False, "z_height": 2.0}
    got = _flat(_run(ECHEUVIS_exp.ECHEUVIS_sub_engage, unload_first=True, **kw))
    want = _flat(_run(ECHE_exp.ECHE_sub_unloadall_customs)) + _flat(
        _run(ECHEUVIS_exp.ECHEUVIS_sub_engage, **kw)
    )
    assert got == want
    assert _flat(_run(ECHEUVIS_exp.ECHEUVIS_sub_engage))[0]["action_name"] == "kmove"


def _all_names(mod, **kw):
    """Plans of every sequence at defaults (plus ``kw`` where the sequence accepts it)."""
    out = []
    for name in mod.SEQUENCES:
        fn = getattr(mod, name)
        accepted = inspect.signature(fn).parameters
        out.append((name, _names(fn, **{k: v for k, v in kw.items() if k in accepted})))
    assert out
    return out


@pytest.mark.parametrize(
    "mod,first,second",
    [
        (ADSS_seq, "ADSS_sub_unloadall_customs", "ADSS_sub_drain_cell"),
        (ADSS_seq, "ADSS_sub_gasvalve_N2flow", "ADSS_sub_recirculate"),
        (ADSS_seq, "ADSS_sub_gasvalve_N2flow", "ADSS_sub_drain_cell"),
        (HISPEC_seq, "ECHE_sub_unloadall_customs", "ECHEUVIS_sub_engage"),
        (ECHEUVIS_seq, "ECHE_sub_unloadall_customs", "ECHEUVIS_sub_engage"),
    ],
)
def test_tier3_pairs_are_folded(mod, first, second):
    # use_z_motor=True is the branch that engages the cell (not the default)
    seen = False
    for kw in ({}, {"use_z_motor": True}):
        for name, names in _all_names(mod, **kw):
            _assert_no_pair(names, first, second)
            seen = seen or second in names
    assert seen, f"{second} appears in no {mod.__name__} plan"


@pytest.mark.parametrize(
    "mod,seqs,shutdown",
    [
        (ECHEUVIS_seq, ["ECHEUVIS_multiCA_led"], "ECHEUVIS_sub_shutdown"),
        (HISPEC_seq, ["HISPEC_CV", "HISPEC_EIS_only"], "HISPEC_sub_shutdown"),
    ],
)
def test_no_unloadall_before_shutdown(mod, seqs, shutdown):
    seen = 0
    for use_z in (False, True):
        for name in seqs:
            names = _names(getattr(mod, name), use_z_motor=use_z)
            assert names[-1] == shutdown
            _assert_no_pair(names, "ECHE_sub_unloadall_customs", shutdown)
            seen += 1
    assert seen == 2 * len(seqs)


def test_shutdowns_still_start_with_the_identical_unload():
    want = _flat(_run(ECHE_exp.ECHE_sub_unloadall_customs))[0]
    for fn in (
        ECHEUVIS_exp.ECHEUVIS_sub_shutdown,
        HISPEC_exp.HISPEC_sub_shutdown,
    ):
        assert _flat(_run(fn))[0] == want


def test_shutdown_rel_move_is_rel_move_then_shutdown():
    kw = {"offset_x_mm": 2.5, "offset_y_mm": -1.5}
    got = _flat(
        _run(
            ECHE_exp.ECHE_sub_shutdown,
            rel_move_offset_x_mm=2.5,
            rel_move_offset_y_mm=-1.5,
        )
    )
    want = _flat(_run(ECHE_exp.ECHE_sub_rel_move, **kw)) + _flat(
        _run(ECHE_exp.ECHE_sub_shutdown)
    )
    assert got == want
    assert [g["action_name"] for g in got] == ["move", "archive_custom_unloadall"]


def test_shutdown_rel_move_unset_is_just_the_unload():
    got = _flat(_run(ECHE_exp.ECHE_sub_shutdown))
    assert got == _flat(_run(ECHE_exp.ECHE_sub_unloadall_customs))
    assert "ECHE_sub_rel_move" in ECHE_exp.EXPERIMENTS


def test_eche_move_is_one_shutdown_with_offsets():
    got = list(ECHE_seq.ECHE_move(move_x_mm=3.0, move_y_mm=4.0))
    assert [e.experiment_name for e in got] == ["ECHE_sub_shutdown"]
    assert got[0].experiment_params["rel_move_offset_x_mm"] == 3.0
    assert got[0].experiment_params["rel_move_offset_y_mm"] == 4.0
