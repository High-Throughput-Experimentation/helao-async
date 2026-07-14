"""Dispatch-hardening proof for hte echem reference-frame params.

Standalone script. Calls hte experiment functions offline, captures the
PSTAT run_CA action_params via a patched ActionPlanMaker.add, and asserts:
(1) valid inputs produce the identical computed potential as before, and
(2) an out-of-catalog reference-frame value now raises a catalogued
ValueError instead of silently mis-handling / KeyError / UnboundLocalError.
"""

__all__ = ["echem_dispatch_test"]

import sys
import traceback

import helao.helpers.premodels as premodels_mod
from helao.helpers.constants import REF_TABLE
from helao.core.tests._test_utils import TestReporter
from helao.deploy.hte.experiments.ECHE_exp import ECHE_sub_CA


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


def echem_dispatch_test() -> bool:
    reporter = TestReporter("echem_dispatch")
    try:
        _check_potential_versus(reporter)
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
