"""WE_versus="ocv" on the ANEC/ECMS CA/CV/LSV experiments.

"ocv" leaves potentials untouched and asks the Gamry endpoint to measure OCV
first (versus_OCV=True + OCV_duration__s). "ref"/"rhe" plans carry neither key.
"""

import pytest

from helao.core.models.echem_params import ref_offset
from helao.deploy.hte.experiments import ANEC_exp, ECMS_exp
from helao.deploy.hte.sequences import ANEC_seq, ECMS_seq
from helao.helpers.premodels import Experiment

POT = {
    "WE_potential__V": -0.7,
    "WE_potential_init__V": -0.1,
    "WE_potential_apex1__V": -0.9,
    "WE_potential_apex2__V": -0.4,
    "WE_potential_final__V": -0.3,
}
VKEY = {
    "WE_potential__V": "Vval__V",
    "WE_potential_init__V": "Vinit__V",
    "WE_potential_apex1__V": "Vapex1__V",
    "WE_potential_apex2__V": "Vapex2__V",
    "WE_potential_final__V": "Vfinal__V",
}
CASES = [
    (ANEC_exp.ANEC_sub_CA, "run_CA"),
    (ANEC_exp.ANEC_sub_HeatCA, "run_CA"),
    (ANEC_exp.ANEC_sub_photo_CA, "run_CA"),
    (ANEC_exp.ANEC_sub_CV, "run_CV"),
    (ANEC_exp.ANEC_sub_HeatCV, "run_CV"),
    (ANEC_exp.ANEC_sub_photo_CV, "run_CV"),
    (ANEC_exp.ANEC_sub_photo_LSV, "run_LSV"),
    (ECMS_exp.ECMS_sub_CA, "run_CA"),
    (ECMS_exp.ECMS_sub_CA_CO2flow, "run_CA"),
]


def _pstat_params(fn, endpoint, **kw):
    import inspect

    accepted = inspect.signature(fn).parameters
    kw = {k: v for k, v in {**POT, **kw}.items() if k in accepted}
    exp = Experiment(experiment_name=fn.__name__, experiment_params={})
    acts = fn(exp, **kw)
    (act,) = [a for a in acts if a.action_name == endpoint]
    return kw, act.action_params


@pytest.mark.parametrize("fn,endpoint", CASES, ids=[c[0].__name__ for c in CASES])
def test_ocv_sets_versus_ocv_and_keeps_potentials(fn, endpoint):
    kw, params = _pstat_params(fn, endpoint, WE_versus="ocv", OCV_duration__s=7.0)
    assert params["versus_OCV"] is True
    assert params["OCV_duration__s"] == 7.0
    for name, key in VKEY.items():
        if name in kw and key in params:
            assert params[key] == kw[name]


@pytest.mark.parametrize("fn,endpoint", CASES, ids=[c[0].__name__ for c in CASES])
@pytest.mark.parametrize("versus", ["ref", "rhe"])
def test_ref_rhe_have_no_ocv_keys(fn, endpoint, versus):
    _, params = _pstat_params(fn, endpoint, WE_versus=versus)
    assert "versus_OCV" not in params and "OCV_duration__s" not in params


def test_ref_rhe_exact_params():
    kw = {"WE_potential__V": -0.7, "ref_offset__V": 0.1, "pH": 7.0}
    _, ref = _pstat_params(ANEC_exp.ANEC_sub_CA, "run_CA", WE_versus="ref", **kw)
    _, rhe = _pstat_params(ANEC_exp.ANEC_sub_CA, "run_CA", WE_versus="rhe", **kw)
    base = {"Tval__s": 0.1, "AcqInterval__s": 0.01, "IErange": "auto"}
    assert ref == {"Vval__V": pytest.approx(-0.8), **base}
    assert rhe == {
        "Vval__V": pytest.approx(-0.8 - 0.059 * 7.0 - ref_offset("leakless")),
        **base,
    }


def test_unknown_versus_raises_value_error_naming_values():
    with pytest.raises(ValueError, match="ref, rhe, ocv"):
        _pstat_params(ANEC_exp.ANEC_sub_CA, "run_CA", WE_versus="bogus")


def test_ecms_initiation_ecsa_expands_at_defaults():
    for e in ECMS_seq.ECMS_initiation_ECSA():
        fn = getattr(ECMS_exp, e.experiment_name)
        fn(
            Experiment(experiment_name=e.experiment_name, experiment_params={}),
            **e.experiment_params,
        )


def test_ecms_series_ca_expands_with_ocv():
    for e in ECMS_seq.ECMS_series_CA(WE_versus="ocv"):
        fn = getattr(ECMS_exp, e.experiment_name)
        fn(
            Experiment(experiment_name=e.experiment_name, experiment_params={}),
            **e.experiment_params,
        )


def _expand_pstat(seq_fn, endpoint, **kw):
    """PSTAT action params of every ``endpoint`` action the sequence plans."""
    out = []
    for e in seq_fn(**kw):
        fn = getattr(
            ANEC_exp if e.experiment_name.startswith("ANEC") else ECMS_exp,
            e.experiment_name,
        )
        exp = Experiment(experiment_name=e.experiment_name, experiment_params={})
        out += [
            a.action_params
            for a in fn(exp, **e.experiment_params)
            if a.action_name == endpoint
        ]
    return out


@pytest.mark.parametrize("versus_ocv,versus", [(False, "ocv"), (True, "ref")])
def test_ecms_cv_derives_versus_ocv(versus_ocv, versus):
    _, params = _pstat_params(
        ECMS_exp.ECMS_sub_CV, "run_CV", WE_versus=versus, versus_OCV=versus_ocv
    )
    assert params["versus_OCV"] is True


def test_ecms_cv_ref_keeps_versus_ocv_false_and_potentials():
    kw, params = _pstat_params(ECMS_exp.ECMS_sub_CV, "run_CV", WE_versus="ocv")
    assert params["Vinit__V"] == kw["WE_potential_init__V"]
    _, ref = _pstat_params(ECMS_exp.ECMS_sub_CV, "run_CV", WE_versus="ref")
    assert ref["versus_OCV"] is False and ref["OCV_duration__s"] == 0.0


@pytest.mark.parametrize(
    "seq_fn,endpoint",
    [
        (ECMS_seq.ECMS_series_CA, "run_CA"),
        (ECMS_seq.ECMS_repeat_CV, "run_CV"),
        (ANEC_seq.ANEC_series_CA, "run_CA"),
        (ANEC_seq.ANEC_repeat_CV, "run_CV"),
    ],
    ids=lambda v: getattr(v, "__name__", v),
)
def test_sequence_forwards_ocv_duration_to_pstat(seq_fn, endpoint):
    params = _expand_pstat(seq_fn, endpoint, WE_versus="ocv", OCV_duration__s=7.0)
    assert params
    for p in params:
        assert p["versus_OCV"] is True and p["OCV_duration__s"] == 7.0
