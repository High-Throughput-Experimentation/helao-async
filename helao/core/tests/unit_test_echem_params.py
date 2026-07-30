"""Equivalence + enforcement proof for the shared echem authoring enums.

Standalone script (not pytest), matching the other helao.core.tests
unit_test_* modules; invoked directly or via run_unit_tests.py. Exits
non-zero on any failure.
"""

__all__ = ["echem_params_unit_test"]

import sys
import traceback

from helao.core.models.echem_params import (
    BubbleGas,
    PotentialVersus,
    RefType,
    WEVersus,
    ref_offset,
    resolve_bubble_gas,
    resolve_potential_versus,
    resolve_ref_type,
    resolve_we_versus,
)
from helao.core.tests._test_utils import TestReporter
from helao.helpers.constants import REF_TABLE


def _raises_value_error(fn):
    try:
        fn()
    except ValueError:
        return True
    except Exception:
        return False
    return False


def _check_surface(reporter):
    reporter.section("enum surface freeze")
    reporter.check(
        "RefType values == ['leakless', 'inhouse', 'rhe']",
        lambda: [m.value for m in RefType] == ["leakless", "inhouse", "rhe"],
    )
    reporter.check(
        "PotentialVersus values == ['rhe', 'oer']",
        lambda: [m.value for m in PotentialVersus] == ["rhe", "oer"],
    )
    reporter.check(
        "WEVersus values == ['ref', 'rhe']",
        lambda: [m.value for m in WEVersus] == ["ref", "rhe"],
    )
    reporter.check(
        "BubbleGas values == ['N2', 'O2']",
        lambda: [m.value for m in BubbleGas] == ["N2", "O2"],
    )


def _check_str_equality(reporter):
    reporter.section("str-equality + dict-key identity (wire safety)")
    reporter.check("PotentialVersus.oer == 'oer'", lambda: PotentialVersus.oer == "oer")
    reporter.check("WEVersus.ref == 'ref'", lambda: WEVersus.ref == "ref")
    reporter.check(
        "REF_TABLE[RefType.rhe] == REF_TABLE['rhe']",
        lambda: REF_TABLE[RefType.rhe] == REF_TABLE["rhe"],
    )
    reporter.check("BubbleGas.n2 == 'N2'", lambda: BubbleGas.n2 == "N2")


def _check_resolvers(reporter):
    reporter.section("resolver coercion + errors")
    reporter.check(
        "resolve_potential_versus('oer') is PotentialVersus.oer",
        lambda: resolve_potential_versus("oer") is PotentialVersus.oer,
    )
    reporter.check(
        "resolve_we_versus('rhe') is WEVersus.rhe",
        lambda: resolve_we_versus("rhe") is WEVersus.rhe,
    )
    reporter.check(
        "resolve_ref_type('inhouse') is RefType.inhouse",
        lambda: resolve_ref_type("inhouse") is RefType.inhouse,
    )
    reporter.check(
        "resolve_bubble_gas('N2') is BubbleGas.n2",
        lambda: resolve_bubble_gas("N2") is BubbleGas.n2,
    )
    reporter.check(
        "ref_offset('inhouse') == REF_TABLE['inhouse']",
        lambda: ref_offset("inhouse") == REF_TABLE["inhouse"],
    )
    reporter.check(
        "ref_offset('rhe') == REF_TABLE['rhe']",
        lambda: ref_offset("rhe") == REF_TABLE["rhe"],
    )
    reporter.check(
        "resolve_potential_versus('RHE') [wrong case] raises ValueError",
        lambda: _raises_value_error(lambda: resolve_potential_versus("RHE")),
    )
    reporter.check(
        "resolve_we_versus('oer') [wrong domain] raises ValueError",
        lambda: _raises_value_error(lambda: resolve_we_versus("oer")),
    )
    reporter.check(
        "ref_offset('bogus') raises ValueError",
        lambda: _raises_value_error(lambda: ref_offset("bogus")),
    )

    msg = None
    try:
        resolve_ref_type("bogus")
    except ValueError as exc:
        msg = str(exc)
    reporter.check(
        "resolve_ref_type error names all three valid members",
        lambda: msg is not None
        and all(v in msg for v in ("leakless", "inhouse", "rhe")),
    )


def echem_params_unit_test() -> bool:
    reporter = TestReporter("echem_params")
    try:
        _check_surface(reporter)
        _check_str_equality(reporter)
        _check_resolvers(reporter)
        return reporter.success()
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False


if __name__ == "__main__":
    ok = echem_params_unit_test()
    if ok:
        print("PASS: unit_test_echem_params — shared echem enums verified")
    sys.exit(0 if ok else 1)
