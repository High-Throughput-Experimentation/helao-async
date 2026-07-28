"""Byte-identity proof for guarded sample-status lifecycle methods (CARDS P3
sub-increment 3c, sample-status half only).

Mirrors ``unit_test_status_transitions.py`` (3a) but for the three
``SampleModel`` status methods added in 3c: ``append_sample_status``,
``remove_sample_status``, ``reset_sample_status``. For each sample subtype
(``NoneSample``, ``LiquidSample``, ``SolidSample``, ``GasSample``,
``AssemblySample``) and a range of start states, this builds two identical
instances, applies the legacy inline list operation (``.append()``,
``.remove()``, slice-assign) to one and the new guarded method to the other,
and asserts ``model_dump_json()`` is byte-identical. Also covers the
duplicate-append case and the remove-of-absent-status case, where both the
legacy op and the guarded method must raise ``ValueError`` identically.

No union/discriminator checks here — that half of CARDS 3c task T1 (the
``SampleUnion`` alias) is out of scope for this test (see
``CARDS_REFACTOR_P3C.md`` D1/D3).

Not a pytest test: standalone script matching the convention of the other
``helao.core.tests.unit_test_*`` modules, invoked directly or via
``run_unit_tests.py``. Exits non-zero on any failure.
"""

__all__ = ["sample_status_unit_test"]

import sys
import traceback

from helao.core.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    SampleStatus,
    SolidSample,
)
from helao.core.tests._test_utils import TestReporter

SUBTYPES = [NoneSample, LiquidSample, SolidSample, GasSample, AssemblySample]

START_STATES = [
    [],
    [SampleStatus.preserved],
    [SampleStatus.created, SampleStatus.preserved],
]

RESET_TARGETS = [
    (),
    (SampleStatus.destroyed,),
    (SampleStatus.created, SampleStatus.preserved),
]


def _assert_byte_identical(reporter: TestReporter, label: str, a, b) -> None:
    reporter.check(
        f"{label}: model_dump() byte-identical",
        lambda: a.model_dump() == b.model_dump(),
    )
    reporter.check(
        f"{label}: model_dump_json() byte-identical",
        lambda: a.model_dump_json() == b.model_dump_json(),
    )


def _check_append(reporter: TestReporter, model_cls) -> None:
    for start_state in START_STATES:
        for s in SampleStatus:
            a = model_cls(status=list(start_state))
            b = model_cls(status=list(start_state))
            a.status.append(s)  # legacy inline op
            b.append_sample_status(s)  # guarded method
            dup = " (duplicate)" if s in start_state else ""
            _assert_byte_identical(
                reporter,
                f"{model_cls.__name__}.append_sample_status start={list(start_state)} s={s.value}{dup}",
                a,
                b,
            )


def _check_remove(reporter: TestReporter, model_cls) -> None:
    for start_state in START_STATES:
        # normal case: remove a status present in start_state
        for s in start_state:
            a = model_cls(status=list(start_state))
            b = model_cls(status=list(start_state))
            a.status.remove(s)  # legacy inline op
            b.remove_sample_status(s)  # guarded method
            _assert_byte_identical(
                reporter,
                f"{model_cls.__name__}.remove_sample_status start={list(start_state)} old={s.value}",
                a,
                b,
            )

        # explicit remove-when-absent: both legacy op and guarded method must
        # raise ValueError identically (unlike guarded_replace, there is no
        # append-fallback for remove — this mirrors legacy `.remove()`).
        missing = SampleStatus.unloaded
        assert missing not in start_state
        a = model_cls(status=list(start_state))
        b = model_cls(status=list(start_state))

        def _try_legacy():
            try:
                a.status.remove(missing)
                return None
            except ValueError as exc:
                return type(exc)

        def _try_guarded():
            try:
                b.remove_sample_status(missing)
                return None
            except ValueError as exc:
                return type(exc)

        legacy_exc = _try_legacy()
        guarded_exc = _try_guarded()
        reporter.check(
            f"{model_cls.__name__}.remove_sample_status start={list(start_state)} old=unloaded(missing): "
            "both raise ValueError identically",
            lambda: legacy_exc is ValueError and guarded_exc is ValueError,
        )
        _assert_byte_identical(
            reporter,
            f"{model_cls.__name__}.remove_sample_status start={list(start_state)} old=unloaded(missing) "
            "(post-raise state)",
            a,
            b,
        )


def _check_reset(reporter: TestReporter, model_cls) -> None:
    for start_state in START_STATES:
        for new_statuses in RESET_TARGETS:
            a = model_cls(status=list(start_state))
            b = model_cls(status=list(start_state))
            a.status[:] = list(new_statuses)  # legacy inline op
            b.reset_sample_status(*new_statuses)  # guarded method
            _assert_byte_identical(
                reporter,
                f"{model_cls.__name__}.reset_sample_status start={list(start_state)} new={list(new_statuses)}",
                a,
                b,
            )


def sample_status_unit_test() -> bool:
    """Run all guarded sample-status byte-identity assertions and report pass/fail."""
    reporter = TestReporter("sample_status")

    try:
        for model_cls in SUBTYPES:
            reporter.section(
                f"{model_cls.__name__}.append_sample_status (sample_guarded_append)"
            )
            _check_append(reporter, model_cls)

            reporter.section(
                f"{model_cls.__name__}.remove_sample_status (sample_guarded_remove)"
            )
            _check_remove(reporter, model_cls)

            reporter.section(
                f"{model_cls.__name__}.reset_sample_status (sample_guarded_reset)"
            )
            _check_reset(reporter, model_cls)

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False


if __name__ == "__main__":
    ok = sample_status_unit_test()
    if ok:
        print(
            "PASS: unit_test_sample_status — all guarded sample-status transitions byte-identical"
        )
    sys.exit(0 if ok else 1)
