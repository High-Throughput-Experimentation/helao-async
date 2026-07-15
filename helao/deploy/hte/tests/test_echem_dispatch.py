"""Dispatch-hardening proof for hte echem reference-frame params.

Standalone script. Calls hte experiment functions offline, captures the
PSTAT run_CA/run_CV action_params via a patched ActionPlanMaker.add, and
asserts: (1) valid inputs produce the identical computed potential as
before, and (2) an out-of-catalog reference-frame value now raises a
catalogued ValueError instead of silently mis-handling / KeyError /
UnboundLocalError.

Covers potential_versus (ECHE_sub_CA), ref_type (ECHE_sub_CA), and WE_versus
(ECMS_sub_CV) dispatch. ANEC_exp.py's and ADSS_exp.py's ref_type/WE_versus
sites are hardened identically but are not exercised here — neither is
offline-importable on Linux (Windows-only gclib dependency); see the import
comment below.

Also covers ref_type dispatch in the hte SEQUENCE module ECHE_seq.py (Task
4b), via ECHE_CV's "ECHE_sub_preCV" experiment_params, captured with a
patched ExperimentPlanMaker.add.
"""

__all__ = ["echem_dispatch_test"]

import sys
import traceback

import helao.helpers.premodels as premodels_mod
from helao.helpers.constants import REF_TABLE
from helao.core.tests._test_utils import TestReporter
from helao.deploy.hte.experiments.ECHE_exp import ECHE_sub_CA
from helao.deploy.hte.sequences.ECHE_seq import ECHE_CV

# ANEC_exp.py is NOT offline-importable on Linux (it imports
# helao.deploy.hte.drivers.motion.galil_motion_driver -> gclib, a Windows-only
# dependency), same constraint hit for ADSS_exp.py in Task 2. Its WE_versus
# dispatch sites are hardened as construction-proof-only (source edit +
# py_compile), not exercised here. ECMS_exp.py has no such import and is used
# below to exercise the real WE_versus dispatch behavior.
from helao.deploy.hte.experiments.ECMS_exp import ECMS_sub_CV


def _capture_actions(fn, **kwargs):
    captured = []
    orig_add = premodels_mod.ActionPlanMaker.add

    def patched_add(self, *a, **kw):
        orig_add(self, *a, **kw)
        captured.append(self.planned_actions[-1])

    premodels_mod.ActionPlanMaker.add = patched_add
    try:
        fn(**kwargs)
    finally:
        premodels_mod.ActionPlanMaker.add = orig_add
    return captured


def _action_by_name(actions, name):
    return next(a for a in actions if a.action_name == name)


def _capture_experiments(fn, **kwargs):
    captured = []
    orig_add = premodels_mod.ExperimentPlanMaker.add

    def patched_add(self, *a, **kw):
        orig_add(self, *a, **kw)
        captured.append(self.planned_experiments[-1])

    premodels_mod.ExperimentPlanMaker.add = patched_add
    try:
        fn(**kwargs)
    finally:
        premodels_mod.ExperimentPlanMaker.add = orig_add
    return captured


def _experiment_by_name(experiments, name):
    return next(e for e in experiments if e.experiment_name == name)


def _raises_value_error(fn):
    try:
        fn()
    except ValueError:
        return True
    except Exception:
        return False
    return False


def _check_potential_versus(reporter):
    reporter.section("potential_versus dispatch (ECHE_sub_CA)")
    # Baseline kwargs match the real ECHE_sub_CA signature (ECHE_exp.py:510-523):
    # CA_potential, potential_versus, ref_type, ref_offset__V, solution_ph,
    # reservoir_electrolyte, reservoir_liquid_sample_no, solution_bubble_gas,
    # measurement_area, samplerate_sec, CA_duration_sec, gamry_i_range, comment.
    base = dict(
        CA_potential=1.0,
        ref_offset__V=0.0,
        solution_ph=7.0,
        ref_type="inhouse",
        samplerate_sec=0.1,
        CA_duration_sec=1.0,
        gamry_i_range="auto",
    )

    # vs rhe (default), ref_type inhouse -> uses the else branch:
    # potential = CA_potential - ref_offset__V + versus(0) - 0.059*ph - REF_TABLE['inhouse']
    actions = _capture_actions(ECHE_sub_CA, potential_versus="rhe", **base)
    run_ca = _action_by_name(actions, "run_CA")
    expected_rhe = 1.0 - 0.0 + 0.0 - 0.059 * 7.0 - REF_TABLE["inhouse"]
    reporter.check(
        "potential_versus='rhe' -> identical Vval__V",
        lambda a=run_ca, e=expected_rhe: a.action_params["Vval__V"] == e,
    )

    # vs oer adds 1.23
    actions = _capture_actions(ECHE_sub_CA, potential_versus="oer", **base)
    run_ca = _action_by_name(actions, "run_CA")
    expected_oer = 1.0 - 0.0 + 1.23 - 0.059 * 7.0 - REF_TABLE["inhouse"]
    reporter.check(
        "potential_versus='oer' -> identical Vval__V (+1.23)",
        lambda a=run_ca, e=expected_oer: a.action_params["Vval__V"] == e,
    )

    # unknown value now raises (was silently treated as rhe)
    reporter.check(
        "potential_versus='bogus' raises ValueError",
        lambda: _raises_value_error(
            lambda: _capture_actions(ECHE_sub_CA, potential_versus="bogus", **base)
        ),
    )


def _check_ref_type(reporter):
    reporter.section("ref_type dispatch (ECHE_sub_CA)")
    # Baseline kwargs match the real ECHE_sub_CA signature (ECHE_exp.py:511-524),
    # same base values as _check_potential_versus.
    base = dict(
        CA_potential=1.0,
        ref_offset__V=0.0,
        solution_ph=7.0,
        samplerate_sec=0.1,
        CA_duration_sec=1.0,
        gamry_i_range="auto",
    )

    # leakless -> uses the else branch (ref_type != "rhe"):
    # potential = CA_potential - ref_offset__V + versus(0) - 0.059*ph - REF_TABLE['leakless']
    actions = _capture_actions(
        ECHE_sub_CA, potential_versus="rhe", ref_type="leakless", **base
    )
    run_ca = _action_by_name(actions, "run_CA")
    expected = 1.0 - 0.0 + 0.0 - 0.059 * 7.0 - REF_TABLE["leakless"]
    reporter.check(
        "ref_type='leakless' -> identical Vval__V",
        lambda a=run_ca, e=expected: a.action_params["Vval__V"] == e,
    )

    # unknown value now raises (was opaque KeyError)
    reporter.check(
        "ref_type='bogus' raises ValueError (was KeyError)",
        lambda: _raises_value_error(
            lambda: _capture_actions(
                ECHE_sub_CA, potential_versus="rhe", ref_type="bogus", **base
            )
        ),
    )


def _check_we_versus(reporter):
    reporter.section("WE_versus dispatch (ECMS_sub_CV)")
    # Baseline kwargs match the real ECMS_sub_CV signature (ECMS_exp.py:931-944):
    # WE_versus, ref_type, pH, WE_potential_init__V, WE_potential_apex1__V,
    # WE_potential_apex2__V, WE_potential_final__V, ScanRate_V_s, Cycles,
    # SampleRate, IErange, ref_offset__V, MS_equilibrium_time.
    base = dict(
        ref_type="inhouse",
        pH=7.0,
        WE_potential_init__V=1.0,
        ref_offset__V=0.0,
    )

    # vs ref: potential_init_vsRef = WE_potential_init__V - 1.0*ref_offset__V
    actions = _capture_actions(ECMS_sub_CV, WE_versus="ref", **base)
    run_cv = _action_by_name(actions, "run_CV")
    expected_ref = 1.0 - 1.0 * 0.0
    reporter.check(
        "WE_versus='ref' -> identical Vinit__V",
        lambda a=run_cv, e=expected_ref: a.action_params["Vinit__V"] == e,
    )

    # vs rhe: potential_init_vsRef = WE_potential_init__V - 1.0*ref_offset__V - 0.059*pH - REF_TABLE[ref_type]
    actions = _capture_actions(ECMS_sub_CV, WE_versus="rhe", **base)
    run_cv = _action_by_name(actions, "run_CV")
    expected_rhe = 1.0 - 1.0 * 0.0 - 0.059 * 7.0 - REF_TABLE["inhouse"]
    reporter.check(
        "WE_versus='rhe' -> identical Vinit__V",
        lambda a=run_cv, e=expected_rhe: a.action_params["Vinit__V"] == e,
    )

    # unknown value now raises (was UnboundLocalError on potential_init_vsRef)
    reporter.check(
        "WE_versus='bogus' raises ValueError",
        lambda: _raises_value_error(
            lambda: _capture_actions(ECMS_sub_CV, WE_versus="bogus", **base)
        ),
    )


def _check_seq_ref_type(reporter):
    reporter.section("ref_type dispatch (ECHE_seq.ECHE_CV -> ECHE_sub_preCV)")
    # Baseline kwargs match the real ECHE_CV signature (ECHE_seq.py:623-642);
    # a single sample keeps the internal loop to one "ECHE_sub_preCV" add.
    base = dict(
        plate_sample_no_list=[2],
        solution_ph=7.0,
        ref_offset__V=0.0,
        CV1_Vinit_vsRHE=0.7,
    )

    # leakless -> CA_potential = CV1_Vinit_vsRHE - ref_offset__V
    #             - REF_TABLE['leakless'] - 0.059*solution_ph
    experiments = _capture_experiments(ECHE_CV, ref_type="leakless", **base)
    pre_cv = _experiment_by_name(experiments, "ECHE_sub_preCV")
    expected = 0.7 - 1.0 * 0.0 - REF_TABLE["leakless"] - 0.059 * 7.0
    reporter.check(
        "ref_type='leakless' -> identical ECHE_sub_preCV CA_potential",
        lambda e=pre_cv, exp=expected: e.experiment_params["CA_potential"] == exp,
    )

    # unknown value now raises (was opaque KeyError)
    reporter.check(
        "ref_type='bogus' raises ValueError (was KeyError)",
        lambda: _raises_value_error(
            lambda: _capture_experiments(ECHE_CV, ref_type="bogus", **base)
        ),
    )


def echem_dispatch_test() -> bool:
    reporter = TestReporter("echem_dispatch")
    try:
        _check_potential_versus(reporter)
        _check_ref_type(reporter)
        _check_we_versus(reporter)
        _check_seq_ref_type(reporter)
        return reporter.success()
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False


if __name__ == "__main__":
    ok = echem_dispatch_test()
    if ok:
        print("PASS: test_echem_dispatch — hte reference-frame dispatch verified")
    sys.exit(0 if ok else 1)
