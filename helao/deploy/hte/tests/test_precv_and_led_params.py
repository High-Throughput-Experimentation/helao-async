"""ECHE_sub_preCV hold potential reaches run_CA; ADSS OCV_photo always turns the LED off."""

import helao.helpers.premodels as premodels_mod
from helao.deploy.hte.experiments.ADSS_exp import ADSS_sub_OCV_photo
from helao.deploy.hte.experiments.ECHE_exp import ECHE_sub_preCV
from helao.deploy.hte.sequences.ECHE_seq import ECHE_4CA_led_1CV_led
from helao.helpers.constants import REF_TABLE


def _capture(cls, attr, fn, **kwargs):
    captured = []
    orig_add = cls.add

    def patched_add(self, *a, **kw):
        orig_add(self, *a, **kw)
        captured.append(getattr(self, attr)[-1])

    cls.add = patched_add
    try:
        fn(**kwargs)
    finally:
        cls.add = orig_add
    return captured


def test_precv_run_ca_uses_gamry_param_names():
    acts = _capture(
        premodels_mod.ActionPlanMaker,
        "planned_actions",
        ECHE_sub_preCV,
        CA_potential=0.42,
        samplerate_sec=0.07,
    )
    params = next(a for a in acts if a.action_name == "run_CA").action_params
    assert params["Vval__V"] == 0.42
    assert params["AcqInterval__s"] == 0.07
    assert "Vval" not in params and "SampleRate" not in params


def test_4ca_seq_precv_potential_uses_ref_offset():
    exps = _capture(
        premodels_mod.ExperimentPlanMaker,
        "planned_experiments",
        ECHE_4CA_led_1CV_led,
        plate_sample_no_list=[2],
        solution_ph=7.0,
        ref_type="leakless",
        ref_offset__V=0.05,
        CV_Vinit_vsRHE=0.7,
        ref_vs_nhe=0.99,  # must no longer feed the hold potential
    )
    pre = next(e for e in exps if e.experiment_name == "ECHE_sub_preCV")
    expected = 0.7 - 0.05 - REF_TABLE["leakless"] - 0.059 * 7.0
    assert abs(pre.experiment_params["CA_potential"] - expected) < 1e-12


def test_adss_ocv_photo_led_off_without_insitu_aliquots():
    acts = _capture(
        premodels_mod.ActionPlanMaker,
        "planned_actions",
        ADSS_sub_OCV_photo,
        aliquot_insitu=False,
    )
    names = [a.action_name for a in acts]
    led = [
        (i, a.action_params["on"]) for i, a in enumerate(acts) if a.action_name == "led"
    ]
    assert [on for _, on in led] == [1, 0]
    assert led[1][0] > names.index("run_OCV")
