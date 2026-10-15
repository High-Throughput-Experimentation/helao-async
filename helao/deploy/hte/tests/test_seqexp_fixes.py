"""Behavioural proofs for the sequence/experiment parameter fixes (offline)."""

import inspect

import pytest

from helao.deploy.hte.experiments import (
    ANEC_exp,
    CCSI_exp,
    CLAD_exp,
    ECHE_exp,
    ECMS_exp,
    HISPEC_exp,
)
from helao.deploy.hte.sequences import ADSS_seq, ANEC_seq, CLAD_seq, ECMS_seq


def _by(actions, server=None, name=None):
    return [
        a
        for a in actions
        if (server is None or a.action_server.server_name == server)
        and (name is None or a.action_name == name)
    ]


def _exps(seq, name):
    return [e for e in seq if e.experiment_name == name]


def test_clad_gas_only_load():
    acts = CLAD_exp.CLAD_sub_load_sample(gas_sample_no=3, gas_volume_ml=5.0)
    gas = _by(acts, name="archive_custom_add_gas")
    assert len(gas) == 1 and gas[0].action_params["source_gas_in"]["sample_no"] == 3
    acts = CLAD_exp.CLAD_sub_load_sample(liquid_sample_no=1, gas_volume_ml=5.0)
    assert not _by(acts, name="archive_custom_add_gas")


def test_ccsi_n2drain_always_closes_n2_supply():
    acts = CCSI_exp.CCSI_sub_n2drain(drain_recirculation=False)
    n2 = [
        a.action_params["on"]
        for a in _by(acts, "NI", "gasvalve")
        if a.action_params["gasvalve"] == "11-n2supply"
    ]
    assert n2 == [1, 0]


def test_ecms_volume_ul_converted_to_ml():
    for fn in (
        ECMS_exp.ECMS_sub_electrolyte_fill_cell,
        ECMS_exp.ECMS_sub_electrolyte_fill_cell_recirculation,
        ECMS_exp.ECMS_sub_final_clean_cell,
    ):
        acts = _by(fn(volume_ul_cell_liquid=600), name="archive_custom_add_liquid")
        assert acts[-1].action_params["volume_ml"] == pytest.approx(0.6), fn.__name__


def test_ecms_cali_second_drives_second_mfc():
    acts = ECMS_exp.ECMS_sub_cali_second()
    assert not [a for a in acts if a.action_server.server_name == "CALIBRATIONMFC"]
    assert len(_by(acts, "CALIBRATIONMFCSECOND")) == 2


@pytest.mark.parametrize(
    "fn,kw",
    [
        (ANEC_exp.ANEC_sub_OCV, {}),
        (ECHE_exp.ECHE_sub_OCV, {}),
        (HISPEC_exp.HISPEC_sub_OCV, {}),
        (ECMS_exp.ECMS_sub_pulseCA, {"run_OCV": True}),
    ],
)
def test_run_ocv_sends_acqinterval(fn, kw):
    ocv = _by(fn(**kw), name="run_OCV")
    assert ocv and all("AcqInterval__s" in a.action_params for a in ocv)
    assert not any("SampleRate" in a.action_params for a in ocv)


def test_adss_ref_cvs_get_floats():
    cv = [
        e.experiment_params
        for e in _exps(ADSS_seq.ADSS_PA_CV_TRI(), "ADSS_sub_CV")
        if e.experiment_params.get("run_use") == "ref"
    ]
    assert cv and all(isinstance(p["Vinit_vsRHE"], float) for p in cv)
    assert all(isinstance(p["scanrate_voltsec"], float) for p in cv)


def test_adss_testing_second_sample_load_uses_second_sample():
    seq = ADSS_seq.ADSS_PA_CVs_testing(second_sample_no=7)
    loads = [
        e.experiment_params["solid_sample_no"] for e in _exps(seq, "ADSS_sub_load")
    ]
    assert loads[-1] == 7


def test_clad_recirculate_duration_reaches_experiment():
    seq = CLAD_seq.CLAD_seq(plate_sample_no_list=[1], fill_recirc_fwd_duration_s=45)
    rec = _exps(seq, "ADSS_sub_recirculate")[0].experiment_params
    assert rec["wait_time_s"] == 45


@pytest.mark.parametrize(
    "fn,exp",
    [
        (ANEC_seq.ANEC_photo_CV, "ANEC_sub_photo_CV"),
        (ANEC_seq.ANEC_repeat_CV, "ANEC_sub_CV"),
        (ECMS_seq.ECMS_repeat_CV, "ECMS_sub_CV"),
        (ECMS_seq.ECMS_repeat_CV_recirculation, "ECMS_sub_CV"),
        (ECMS_seq.ECMS_repeat_CV_recirculation_mixedreactant, "ECMS_sub_CV"),
        (ECMS_seq.ECMS_CV_recirculation_mixedreactant, "ECMS_sub_CV"),
    ],
)
def test_ref_offset_forwarded(fn, exp):
    seq = fn(ref_offset=0.123)
    cvs = _exps(seq, exp)
    assert cvs and all(e.experiment_params["ref_offset__V"] == 0.123 for e in cvs)


def test_week_window_parser_with_operator_backend(monkeypatch):
    from helao.deploy.hte.specifications import week_window

    class Dat:
        yml = {"sequence_name": "CLAD_seq", "sequence_params": {}}

    monkeypatch.setattr(week_window, "HelaoData", lambda p: Dat())

    class Backend:  # operator backend: sequence_lib only, no *_lib codehash/path
        sequence_lib = {"CLAD_seq": CLAD_seq.CLAD_seq}
        sequence_codehash = {"CLAD_seq": "abc"}

    seq = week_window.WeekWindowSpecParser().parser("x.zip", Backend())
    assert seq.sequence_name == "CLAD_seq" and seq.sequence_codehash is None


def test_adss_clean_cell_infuses_requested_volume():
    from helao.deploy.hte.experiments import ADSS_exp

    acts = ADSS_exp.ADSS_sub_clean_cell(Clean_volume_ul=12000, Watercleancycle=False)
    infused = [a.action_params["volume_uL"] for a in _by(acts, name="infuse")]
    assert len(infused) == 2 and sum(infused) == 12000


@pytest.mark.parametrize("fn", [ADSS_seq.ADSS_PA_CV_TRI, ADSS_seq.ADSS_PA_CV_TRI_new])
def test_adss_cv_samplerate_not_scanrate(fn):
    cvs = [
        e.experiment_params
        for e in _exps(
            fn(testing_CV_scanrate_voltsec=0.31, testing_CV_samplerate_sec=0.017),
            "ADSS_sub_CV",
        )
        if e.experiment_params["scanrate_voltsec"] == 0.31
    ]
    assert cvs and all(p["samplerate_sec"] == 0.017 for p in cvs)


# ---- low round w2 ----


def test_adss_cv_rhe_reference_has_no_ph_term():
    from helao.deploy.hte.experiments import ADSS_exp

    def vinit(ref_type, ph):
        acts = ADSS_exp.ADSS_sub_CV(Vinit_vsRHE=0.5, ref_type=ref_type, ph=ph)
        return _by(acts, name="run_CV")[0].action_params["Vinit__V"]

    assert vinit("rhe", 1.0) == pytest.approx(0.5)
    assert vinit("rhe", 13.0) == pytest.approx(0.5)
    assert vinit("inhouse", 13.0) != pytest.approx(0.5)


def test_ccsi_load_gas_uses_custom_load_without_volume():
    acts = CCSI_exp.CCSI_sub_load_gas(reservoir_gas_sample_no=2, volume_ul_cell_gas=500)
    assert not _by(acts, name="archive_custom_add_gas")
    p = _by(acts, name="archive_custom_load")[0].action_params
    assert "volume_ml" not in p and p["load_sample_in"]["sample_no"] == 2


def test_ccsi_pressure_technique_name_spelling():
    from helao.deploy.hte.experiments import CSIL_exp

    for mod in (CCSI_exp, CSIL_exp):
        src = inspect.getsource(mod)
        assert "pressure_measurre" not in src and "pressure_measure" in src


def test_clad_seq_reference_position_override_reaches_experiment():
    seq = CLAD_seq.CLAD_seq(plate_sample_no_list=[1], reference_position="custom_ref")
    ref = _exps(seq, "CLAD_sub_reference_setup")[0].experiment_params
    assert ref["reference_position_name"] == "custom_ref"
    assert "reference_position" not in ref


def test_hispec_peis_ttl_explicitly_off():
    from helao.deploy.hte.sequences import HISPEC_seq

    for fn in (HISPEC_seq.HISPEC_CV, HISPEC_seq.HISPEC_EIS_only):
        peis = _exps(fn(gamrychannelwait=2, gamrychannelsend=3), "HISPEC_sub_PEIS")
        assert peis
        for e in peis:
            assert e.experiment_params["TTLwait"] == -1
            assert e.experiment_params["TTLsend"] == -1


def test_anec_create_and_load_liquid_sample_honours_tray():
    sig = inspect.signature(ANEC_seq.ANEC_create_and_load_liquid_sample)
    kw = {
        k: v.default
        for k, v in sig.parameters.items()
        if v.default is not inspect.Parameter.empty
    }
    kw["tray"] = 5
    exps = ANEC_seq.ANEC_create_and_load_liquid_sample(
        **{k: v for k, v in kw.items() if k in sig.parameters}
    )
    assert exps and all(e.experiment_params["tray"] == 5 for e in exps)


def test_ccsi_co2maintain_passes_waterfillwait_s():
    from helao.deploy.hte.sequences import CCSI_seq

    seq = CCSI_seq.CCSI_Solution_co2maintainconcentration(
        secondliquid_injection_FillWait=77
    )
    fills = [
        e.experiment_params
        for e in _exps(seq, "CCSI_sub_cellfill")
        if "WaterFillWait_s" in e.experiment_params
        and e.experiment_params["WaterFillWait_s"] == 77
    ]
    assert fills
