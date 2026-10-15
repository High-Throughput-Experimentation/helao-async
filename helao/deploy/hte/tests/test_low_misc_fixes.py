"""Offline proofs for small deferred fixes: PAL GC builders, ADSS, samples."""

from helao.deploy.hte.drivers.robot.enum import GCsampletype
from helao.deploy.hte.drivers.robot.pal_driver import PAL
from helao.deploy.hte.experiments import ADSS_exp, samples_exp


def _method(builder, params):
    return builder(None, params, []).microcams[0].method


def test_gc_builders_accept_defaults_enum_and_plain_strings():
    for b, stem in (
        (PAL.build_palcam_injection_tray_GC, "injection_tray_GC"),
        (PAL.build_palcam_injection_custom_GC, "injection_custom_GC"),
    ):
        assert _method(b, {}) == f"{stem}_none_start"
        assert _method(b, {"sampletype": "gas", "startGC": False}) == f"{stem}_gas_wait"
        assert (
            _method(b, {"sampletype": GCsampletype.liquid, "startGC": True})
            == f"{stem}_liquid_start"
        )


def test_adss_insitu_empty_aliquots_with_electrolyte_does_not_raise():
    acts = ADSS_exp.ADSS_sub_insitu_actions(
        insert_electrolyte_bool=True, aliquot_times_sec=[]
    )
    assert isinstance(acts, list)


def test_generate_sample_no_list_returns_its_action():
    acts = samples_exp.generate_sample_no_list()
    assert [a.action_name for a in acts] == ["generate_plate_sample_no_list"]
