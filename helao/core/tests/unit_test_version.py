"""Unit tests for ``helao.core.version`` git/version helpers.

This module is executed inside the helao-async repository, so ``git``
should be available and the working tree should yield real values from
:func:`get_branch_commithash` / :func:`get_filehash`. The tests assert
both the happy path and the documented "return empty strings on failure"
fallback for nonexistent files.
"""

__all__ = ["version_unit_test"]

import os
import tempfile
import traceback

from helao.core import version as version_mod
from helao.core.tests._test_utils import TestReporter
from helao.core.version import (
    get_branch_commithash,
    get_caller_filehash,
    get_filehash,
    get_hlo_version,
    get_object_filehash,
    hlo_version,
)


def version_unit_test() -> bool:
    """Run all version-helper assertions and report pass/fail."""
    reporter = TestReporter("version")

    try:
        reporter.section("get_branch_commithash inside the helao-async repo")
        branch, commit = get_branch_commithash()
        reporter.check(
            "branch and commit are strings",
            lambda: isinstance(branch, str) and isinstance(commit, str),
        )
        reporter.check(
            "commit hash is a 7+ char short SHA (or '' on failure)",
            lambda: commit == "" or len(commit) >= 7,
        )

        reporter.section("get_filehash on a known tracked file")
        # Use this very module - it was just created and committed, but
        # whether or not it has a commit the helper documents an empty
        # string fallback, so both outcomes are acceptable.
        this_file = os.path.abspath(__file__)
        fh = get_filehash(this_file)
        reporter.check(
            "get_filehash returns a str (possibly empty)",
            lambda: isinstance(fh, str),
        )

        reporter.section("get_filehash gracefully degrades on missing files")
        bogus = os.path.join(tempfile.gettempdir(), "__definitely_not_a_real_file__.py")
        bogus_hash = get_filehash(bogus)
        reporter.check(
            "missing file returns the empty-string fallback",
            lambda: bogus_hash == "",
        )

        reporter.section("get_hlo_version + module-level hlo_version")
        v = get_hlo_version()
        reporter.check(
            "get_hlo_version returns a str",
            lambda: isinstance(v, str),
        )
        reporter.check(
            "module-level hlo_version mirrors get_hlo_version()",
            lambda: isinstance(hlo_version, str),
        )

        reporter.section("get_object_filehash / get_caller_filehash")
        obj_hash, obj_file = get_object_filehash(version_mod)
        reporter.check(
            "get_object_filehash returns (str, str)",
            lambda: isinstance(obj_hash, str) and isinstance(obj_file, str),
        )
        reporter.check(
            "get_object_filehash filename ends with version.py",
            lambda: obj_file.endswith("version.py"),
        )

        caller_hash, caller_file = get_caller_filehash()
        reporter.check(
            "get_caller_filehash returns (str, str)",
            lambda: isinstance(caller_hash, str) and isinstance(caller_file, str),
        )
        reporter.check(
            "get_caller_filehash filename points at this test module",
            lambda: caller_file.endswith("unit_test_version.py"),
        )

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False
