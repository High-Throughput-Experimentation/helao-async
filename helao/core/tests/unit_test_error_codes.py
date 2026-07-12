"""Unit tests for :class:`helao.core.error.ErrorCodes`.

The dispatcher module test already covers ``ErrorCodes.none`` /
``ErrorCodes.http``; this module is the dedicated full-coverage gate
that asserts every documented member is present, exposes its name as a
distinct string value, and round-trips cleanly through that value.
"""

__all__ = ["error_codes_unit_test"]

import traceback

from helao.core.error import ErrorCodes
from helao.core.tests._test_utils import TestReporter


_EXPECTED_MEMBERS = {
    "none",
    "critical",
    "critical_error",
    "start_timeout",
    "continue_timeout",
    "done_timeout",
    "in_progress",
    "not_available",
    "ssh_error",
    "not_initialized",
    "bug",
    "cmd_error",
    "no_sample",
    "unspecified",
    "estop",
    "stop",
    "timeout",
    "setup",
    "numerical",
    "motor",
    "http",
    "not_allowed",
}


def error_codes_unit_test() -> bool:
    """Run all ErrorCodes assertions and report pass/fail."""
    reporter = TestReporter("error_codes")

    try:
        reporter.section("ErrorCodes membership")
        actual = {m.name for m in ErrorCodes}
        reporter.check(
            "every documented ErrorCodes member is present",
            lambda: _EXPECTED_MEMBERS.issubset(actual),
        )
        reporter.check(
            "no unexpected ErrorCodes members were added without test coverage",
            lambda: actual == _EXPECTED_MEMBERS,
        )

        reporter.section("ErrorCodes string values match their member names")
        for name in _EXPECTED_MEMBERS:
            reporter.check(
                f"ErrorCodes.{name}.value == '{name}'",
                (lambda name=name: ErrorCodes[name].value == name),
            )

        reporter.section("ErrorCodes round-trips through its string value")
        for code in ErrorCodes:
            reporter.check(
                f"ErrorCodes({code.value!r}) is ErrorCodes.{code.name}",
                (lambda code=code: ErrorCodes(code.value) is code),
            )

        reporter.section("ErrorCodes values are pairwise distinct")
        values = [c.value for c in ErrorCodes]
        reporter.check(
            "no duplicate ErrorCodes values",
            lambda: len(values) == len(set(values)),
        )

        reporter.section("ErrorCodes inherits from str (so JSON/dump treats it as text)")
        reporter.check(
            "ErrorCodes.none is a str instance",
            lambda: isinstance(ErrorCodes.none, str),
        )
        reporter.check(
            "ErrorCodes.none == 'none' compares as a string",
            lambda: ErrorCodes.none == "none",
        )

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False
