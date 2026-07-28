"""Byte-identity proof for guarded lifecycle-transition methods (CARDS P3 sub-increment 3a).

For each of the three status-bearing models (:class:`ActionModel`,
:class:`ExperimentModel`, :class:`SequenceModel`) and each of the three
lifecycle primitives (append / replace / reset), this builds two identical
model instances, applies the legacy inline list operation to one and the new
guarded model method to the other, and asserts the resulting
``model_dump()``, ``model_dump_json()``, and YAML-dumped representations are
byte-identical. Parametrized across every :class:`HloStatus` member and
start states ``[]``, ``[active]``, ``[active, errored]``, plus explicit
duplicate-append and replace-when-missing cases.

Also asserts the combined ``model_json_schema()`` of the three models is
byte-identical to the pre-3a baseline captured at
``.omc/artifacts/p3a/schema_baseline.json`` — proving the new methods add
nothing to the pydantic schema and the fields stay ``List[HloStatus]``.

Not a pytest test: this is a standalone script (matching the convention of
the other ``helao.core.tests.unit_test_*`` modules) invoked directly or via
``run_unit_tests.py``. Exits non-zero on any failure; prints a PASS line on
full success.
"""

__all__ = ["status_transitions_unit_test"]

import json
import sys
import traceback
from pathlib import Path

from helao.core.models.action import ActionModel
from helao.core.models.experiment import ExperimentModel
from helao.core.models.hlostatus import HloStatus
from helao.core.models.sequence import SequenceModel
from helao.core.tests._test_utils import TestReporter
from helao.helpers.yml_tools import yml_dumps

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_BASELINE_PATH = REPO_ROOT / ".omc" / "artifacts" / "p3a" / "schema_baseline.json"

START_STATES = [
    [],
    [HloStatus.active],
    [HloStatus.active, HloStatus.errored],
]

RESET_TARGETS = [
    (),
    (HloStatus.finished,),
    (HloStatus.active, HloStatus.errored),
]

# (model_class, status_field, append_method, replace_method, reset_method)
MODEL_SPECS = [
    (
        ActionModel,
        "action_status",
        "append_action_status",
        "replace_action_status",
        "reset_action_status",
    ),
    (
        ExperimentModel,
        "experiment_status",
        "append_experiment_status",
        "replace_experiment_status",
        "reset_experiment_status",
    ),
    (
        SequenceModel,
        "sequence_status",
        "append_sequence_status",
        "replace_sequence_status",
        "reset_sequence_status",
    ),
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
    # yml_dumps(model_dump()) chokes on raw HloStatus enum members (ruamel has no
    # representer for the str-Enum subtype); as_dict() is the actual production
    # serialization pathway (HelaoDict, used for -act/-exp/-seq.yml output) and
    # coerces enums to plain strings the same way real runs do.
    reporter.check(
        f"{label}: yml_dumps(as_dict()) byte-identical",
        lambda: yml_dumps(a.as_dict()) == yml_dumps(b.as_dict()),
    )


def _check_append(
    reporter: TestReporter, model_cls, field: str, method_name: str
) -> None:
    for start_state in START_STATES:
        for s in HloStatus:
            a = model_cls(**{field: list(start_state)})
            b = model_cls(**{field: list(start_state)})
            getattr(a, field).append(s)  # legacy inline op
            getattr(b, method_name)(s)  # guarded method
            dup = " (duplicate)" if s in start_state else ""
            _assert_byte_identical(
                reporter,
                f"{model_cls.__name__}.{method_name} start={list(start_state)} s={s.value}{dup}",
                a,
                b,
            )


def _legacy_replace(status_list, old_status, new_status) -> None:
    """Mirror of Base.replace_status (base.py:997) for the legacy-side comparison."""
    if old_status in status_list:
        status_list[status_list.index(old_status)] = new_status
    else:
        status_list.append(new_status)


def _check_replace(
    reporter: TestReporter, model_cls, field: str, method_name: str
) -> None:
    for start_state in START_STATES:
        for new_status in HloStatus:
            # normal case: swap-in-place when HloStatus.active is present
            a = model_cls(**{field: list(start_state)})
            b = model_cls(**{field: list(start_state)})
            _legacy_replace(getattr(a, field), HloStatus.active, new_status)
            getattr(b, method_name)(HloStatus.active, new_status)
            _assert_byte_identical(
                reporter,
                f"{model_cls.__name__}.{method_name} start={list(start_state)} old=active new={new_status.value}",
                a,
                b,
            )

        # explicit replace-when-missing: old_status guaranteed absent from every start state
        missing_old = HloStatus.retired
        assert missing_old not in start_state
        a = model_cls(**{field: list(start_state)})
        b = model_cls(**{field: list(start_state)})
        _legacy_replace(getattr(a, field), missing_old, HloStatus.busy)
        getattr(b, method_name)(missing_old, HloStatus.busy)
        _assert_byte_identical(
            reporter,
            f"{model_cls.__name__}.{method_name} start={list(start_state)} old=retired(missing) new=busy (append fallback)",
            a,
            b,
        )


def _check_reset(
    reporter: TestReporter, model_cls, field: str, method_name: str
) -> None:
    for start_state in START_STATES:
        for new_statuses in RESET_TARGETS:
            a = model_cls(**{field: list(start_state)})
            b = model_cls(**{field: list(start_state)})
            getattr(a, field)[:] = list(new_statuses)  # legacy inline op
            getattr(b, method_name)(*new_statuses)  # guarded method
            _assert_byte_identical(
                reporter,
                f"{model_cls.__name__}.{method_name} start={list(start_state)} new={list(new_statuses)}",
                a,
                b,
            )


def _check_schema_freeze(reporter: TestReporter) -> None:
    current = json.dumps(
        [
            ActionModel.model_json_schema(),
            ExperimentModel.model_json_schema(),
            SequenceModel.model_json_schema(),
        ],
        indent=1,
        sort_keys=True,
        default=str,
    )
    reporter.check(
        f"schema freeze: model_json_schema() equals baseline ({SCHEMA_BASELINE_PATH})",
        lambda: SCHEMA_BASELINE_PATH.is_file()
        and current == SCHEMA_BASELINE_PATH.read_text(),
    )


def status_transitions_unit_test() -> bool:
    """Run all guarded-transition byte-identity assertions and report pass/fail."""
    reporter = TestReporter("status_transitions")

    try:
        for (
            model_cls,
            field,
            append_method,
            replace_method,
            reset_method,
        ) in MODEL_SPECS:
            reporter.section(f"{model_cls.__name__}.{append_method} (guarded_append)")
            _check_append(reporter, model_cls, field, append_method)

            reporter.section(f"{model_cls.__name__}.{replace_method} (guarded_replace)")
            _check_replace(reporter, model_cls, field, replace_method)

            reporter.section(f"{model_cls.__name__}.{reset_method} (guarded_reset)")
            _check_reset(reporter, model_cls, field, reset_method)

        reporter.section(
            "Schema freeze (methods must not appear in model_json_schema())"
        )
        _check_schema_freeze(reporter)

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False


if __name__ == "__main__":
    ok = status_transitions_unit_test()
    if ok:
        print(
            "PASS: unit_test_status_transitions — all guarded transitions byte-identical, schema unchanged"
        )
    sys.exit(0 if ok else 1)
