"""Single-action experiment merges: load_solid_only, redundant unloads, OCV technique.

Each test fails if the merge it guards is undone or made inexact.
"""

import pytest

from helao.deploy.hte.experiments import (
    ANEC_exp,
    ECHE_exp,
    ECHEUVIS_exp,
    ECMS_exp,
    UVIS_exp,
)
from helao.deploy.hte.sequences import (
    ANEC_seq,
    ECHE_seq,
    ECMS_seq,
    UVIS_DR_seq,
    UVIS_T_seq,
    UVIS_TR_seq,
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
        _names(UVIS_DR_seq.UVIS_DR),
        _names(UVIS_TR_seq.UVIS_TR),
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
