"""Unit tests for the ``orch_unpack`` free functions + ``PLATE_API`` singleton
extracted from ``Orch`` (CARDS P5, Stage S6): sequence-unpacking cluster.

``seq_unpacker`` is already exercised (byte-for-byte, via the dispatch loop's
own sequence-to-experiment unpacking) by
``test_orch_dispatch_golden_master.py --check``; ``verify_plate_in_params`` is
gated behind ``PLATE_API.has_access`` at its ``orch.py`` call sites and that
harness forces ``has_access`` False for its whole run, so the plate-lookup
branch itself is never driven there. This module is the S6-specific
behavior-preservation gate for ``unpack_sequence`` (module-name resolution)
and ``verify_plate_in_params`` (the plate-lookup branch, both with and
without ``PLATE_API`` access).

Hermetic: no network, no disk I/O; ``PLATE_API`` is monkeypatched with a
``SimpleNamespace`` stand-in for the has-access/no-access branches (mirrors
the dispatch golden-master harness's own ``PLATE_API`` rebind technique) and
restored in a ``finally``.
"""

__all__ = ["orch_unpack_unit_test"]

from types import SimpleNamespace

from helao.core.servers import orch_unpack
from helao.core.tests._test_utils import TestReporter


def _check_unpack_sequence_name_in_lib() -> bool:
    calls = []

    def _factory(**kwargs):
        calls.append(kwargs)
        return ["exp1", "exp2"]

    result = orch_unpack.unpack_sequence("my_seq", {"a": 1}, {"my_seq": _factory})
    return result == ["exp1", "exp2"] and calls == [{"a": 1}]


def _check_unpack_sequence_name_absent() -> bool:
    result = orch_unpack.unpack_sequence(
        "missing_seq", {}, {"other_seq": lambda **kw: ["x"]}
    )
    return result == []


def _check_verify_plate_in_params_no_plate_key() -> bool:
    # no plate-id parameter present -> True regardless of PLATE_API state
    return orch_unpack.verify_plate_in_params({"unrelated": 1}) is True


def _check_verify_plate_in_params_no_access() -> bool:
    orig = orch_unpack.PLATE_API
    orch_unpack.PLATE_API = SimpleNamespace(has_access=False)
    try:
        result = orch_unpack.verify_plate_in_params({"plate_id": 42})
    finally:
        orch_unpack.PLATE_API = orig
    # no access -> logs a warning and plate_found stays False
    return result is False


def _check_verify_plate_in_params_valid_platemap() -> bool:
    calls = []

    def _get_platemap_plateid(pid_val):
        calls.append(pid_val)
        return {"some": "platemap"}

    orig = orch_unpack.PLATE_API
    orch_unpack.PLATE_API = SimpleNamespace(
        has_access=True, get_platemap_plateid=_get_platemap_plateid
    )
    try:
        result = orch_unpack.verify_plate_in_params({"plate_id": 7})
    finally:
        orch_unpack.PLATE_API = orig
    return result is True and calls == [7]


def _check_verify_plate_in_params_access_but_no_platemap() -> bool:
    orig = orch_unpack.PLATE_API
    orch_unpack.PLATE_API = SimpleNamespace(
        has_access=True, get_platemap_plateid=lambda pid_val: None
    )
    try:
        # solid_plate_id branch, has_access True but no platemap found for either key
        result = orch_unpack.verify_plate_in_params({"solid_plate_id": 3})
    finally:
        orch_unpack.PLATE_API = orig
    return result is False


def orch_unpack_unit_test() -> bool:
    reporter = TestReporter("orch_unpack")

    reporter.section("unpack_sequence")
    reporter.check(
        "name-in-lib invokes the factory with sequence_params and returns its result",
        _check_unpack_sequence_name_in_lib,
    )
    reporter.check(
        "name-absent-from-lib returns []",
        _check_unpack_sequence_name_absent,
    )

    reporter.section("verify_plate_in_params")
    reporter.check(
        "no plate-id parameter present -> True (no PLATE_API lookup needed)",
        _check_verify_plate_in_params_no_plate_key,
    )
    reporter.check(
        "plate-id present but PLATE_API.has_access False -> False (warns, no lookup)",
        _check_verify_plate_in_params_no_access,
    )
    reporter.check(
        "plate-id present, PLATE_API.has_access True, valid platemap found -> True",
        _check_verify_plate_in_params_valid_platemap,
    )
    reporter.check(
        "solid_plate_id present, PLATE_API.has_access True, no platemap found -> False",
        _check_verify_plate_in_params_access_but_no_platemap,
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if orch_unpack_unit_test() else 1)
