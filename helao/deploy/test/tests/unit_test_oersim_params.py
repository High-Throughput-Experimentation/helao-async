"""Equivalence proof for the typed OERSIM param models (CARDS 3d, task T2).

Proves the pydantic models in :mod:`helao.deploy.test.param_models` are
byte-identical, in both shape and yml serialization, to the frozen legacy
dict literals they are meant to replace (see ``CARDS_REFACTOR_P3D.md`` §5-7),
and that ``check_condition``'s new :class:`~helao.deploy.test.param_models.StopCondition`
enum enforces the historical four-value wire contract while closing the
``stop_condtion`` typo hole (D2).

At this task (T2) ``OERSIM_exp.py``/``OERSIM_seq.py`` still author literal
dicts directly (T3 rewires them onto the models next) — check 2 below
therefore validates that those literal dicts, produced by actually calling
the experiment/sequence functions offline, equal the same frozen legacy
dicts that check 1 validates the models against. T3's gate re-runs check 2
against the rewired, model-backed functions.

Not a pytest test: standalone script matching the convention of the other
``helao.core.tests.unit_test_*`` modules (see ``unit_test_sample_union.py``),
invoked directly or via ``run_unit_tests.py``. Exits non-zero on any failure.

Import cost: this module (and everything it imports — ``param_models``,
``OERSIM_exp``, ``OERSIM_seq``, ``helao.helpers.yml_tools``) MUST NOT import
``gpsim_driver`` — that module drags in gpflow/TensorFlow, and this suite
runs before every ``launch.py`` invocation on every station.
"""

__all__ = ["oersim_params_unit_test"]

import sys
import traceback

from pydantic import ValidationError

import helao.helpers.premodels as premodels_mod
from helao.helpers.yml_tools import yml_dumps
from helao.core.tests._test_utils import TestReporter

from helao.deploy.test.param_models import (
    StopCondition,
    resolve_stop_condition,
    CPSIMChangePlateParams,
    GPSIMInitializePlateParams,
    GPSIMCheckConditionParams,
    OERSIMSubLoadPlateParams,
    OERSIMSubActivelearnParams,
    OERSIMActivelearnSeqParams,
)
from helao.deploy.test.experiments.OERSIM_exp import (
    OERSIM_sub_load_plate,
    OERSIM_sub_decision,
    OERSIM_sub_activelearn,
)
from helao.deploy.test.sequences.OERSIM_seq import OERSIM_activelearn

# --------------------------------------------------------------------------
# Frozen legacy dict builders (post-typo-fix spelling): literal, ordered
# dicts matching exactly what OERSIM_exp.py/OERSIM_seq.py author today. These
# are the arbiter (D6) — both the typed models (check 1) and the actual
# exp/seq function output (check 2) are compared against them.
# --------------------------------------------------------------------------


def _legacy_change_plate(plate_id):
    return {"plate_id": plate_id}


def _legacy_initialize_plate(num_random_points, reinitialize=False):
    return {"num_random_points": num_random_points, "reinitialize": reinitialize}


def _legacy_check_condition(
    stop_condition,
    thresh_value,
    repeat_experiment_name,
    repeat_experiment_params,
    repeat_experiment_kwargs,
):
    return {
        "stop_condition": stop_condition,
        "thresh_value": thresh_value,
        "repeat_experiment_name": repeat_experiment_name,
        "repeat_experiment_params": repeat_experiment_params,
        "repeat_experiment_kwargs": repeat_experiment_kwargs,
    }


def _legacy_load_plate(plate_id, init_random_points):
    return {"plate_id": plate_id, "init_random_points": init_random_points}


def _legacy_activelearn(
    init_random_points, stop_condition, thresh_value, repeat_experiment_kwargs
):
    return {
        "init_random_points": init_random_points,
        "stop_condition": stop_condition,
        "thresh_value": thresh_value,
        "repeat_experiment_kwargs": repeat_experiment_kwargs,
    }


def _legacy_activelearn_seq(init_random_points, stop_condition, thresh_value):
    return {
        "init_random_points": init_random_points,
        "stop_condition": stop_condition,
        "thresh_value": thresh_value,
    }


# model class, frozen-dict builder, default kwargs, non-default kwargs
_MODEL_CASES = [
    (
        CPSIMChangePlateParams,
        _legacy_change_plate,
        {"plate_id": 0},
        {"plate_id": 2750},
    ),
    (
        GPSIMInitializePlateParams,
        _legacy_initialize_plate,
        {"num_random_points": 5, "reinitialize": False},
        {"num_random_points": 12, "reinitialize": True},
    ),
    (
        GPSIMCheckConditionParams,
        _legacy_check_condition,
        {
            "stop_condition": "max_iters",
            "thresh_value": 10,
            "repeat_experiment_name": "OERSIM_sub_activelearn",
            "repeat_experiment_params": {},
            "repeat_experiment_kwargs": {},
        },
        {
            "stop_condition": "max_ei",
            "thresh_value": 2.5,
            "repeat_experiment_name": "custom_exp",
            "repeat_experiment_params": {"a": 1},
            "repeat_experiment_kwargs": {"b": 2},
        },
    ),
    (
        OERSIMSubLoadPlateParams,
        _legacy_load_plate,
        {"plate_id": 0, "init_random_points": 5},
        {"plate_id": 2750, "init_random_points": 12},
    ),
    (
        OERSIMSubActivelearnParams,
        _legacy_activelearn,
        {
            "init_random_points": 5,
            "stop_condition": "max_iters",
            "thresh_value": 10,
            "repeat_experiment_kwargs": {},
        },
        {
            "init_random_points": 3,
            "stop_condition": "max_stdev",
            "thresh_value": 7.5,
            "repeat_experiment_kwargs": {"z": 9},
        },
    ),
    (
        OERSIMActivelearnSeqParams,
        _legacy_activelearn_seq,
        {"init_random_points": 5, "stop_condition": "max_iters", "thresh_value": 10},
        {"init_random_points": 8, "stop_condition": "none", "thresh_value": 42},
    ),
]


def _check_frozen_literal_equivalence(reporter: TestReporter) -> None:
    """Check 1: model_dump() == frozen legacy dict (order + yml bytes)."""
    reporter.section("frozen-literal dump equivalence (§7 check 1)")
    for model_cls, legacy_fn, default_kwargs, nondefault_kwargs in _MODEL_CASES:
        for label, kwargs in (
            ("defaults", default_kwargs),
            ("non-default", nondefault_kwargs),
        ):
            model = model_cls(**kwargs)
            dump = model.model_dump()
            legacy = legacy_fn(**kwargs)
            name = model_cls.__name__
            reporter.check(
                f"{name} [{label}]: model_dump() == frozen legacy dict",
                lambda dump=dump, legacy=legacy: dump == legacy,
            )
            reporter.check(
                f"{name} [{label}]: key order == frozen legacy dict order",
                lambda dump=dump, legacy=legacy: list(dump.keys())
                == list(legacy.keys()),
            )
            reporter.check(
                f"{name} [{label}]: yml_dumps bytes == frozen legacy dict yml_dumps bytes",
                lambda dump=dump, legacy=legacy: yml_dumps(dump) == yml_dumps(legacy),
            )


def _capture_actions(fn, **kwargs):
    """Call an OERSIM_exp experiment function and capture every ``Action`` it
    queues via ``ActionPlanMaker.add`` (across any nested ``apm`` instances),
    regardless of the function's return value.

    ``OERSIM_sub_load_plate`` does not return ``apm.planned_actions``, so
    capturing via a patched ``add`` (rather than relying on the return value)
    is the only way to inspect its planned actions offline; the same
    mechanism is used uniformly for the other three experiments so all four
    are exercised identically.
    """
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


def _action_by_name(actions, action_name):
    return next(a for a in actions if a.action_name == action_name)


def _check_authoring_path_equivalence(reporter: TestReporter) -> None:
    """Check 2: exp/seq function output == frozen legacy dict (order + yml bytes)."""
    reporter.section("authoring-path equivalence (§7 check 2)")

    for label, plate_id, init_random_points in (
        ("defaults", 0, 5),
        ("non-default", 2750, 12),
    ):
        actions = _capture_actions(
            OERSIM_sub_load_plate,
            plate_id=plate_id,
            init_random_points=init_random_points,
        )
        change_plate = _action_by_name(actions, "change_plate")
        initialize_plate = _action_by_name(actions, "initialize_plate")
        get_loaded_plate = _action_by_name(actions, "get_loaded_plate")

        legacy_change_plate = _legacy_change_plate(plate_id=plate_id)
        legacy_initialize_plate = _legacy_initialize_plate(
            num_random_points=init_random_points, reinitialize=False
        )
        reporter.check(
            f"OERSIM_sub_load_plate [{label}]: change_plate action_params == frozen dict",
            lambda a=change_plate, e=legacy_change_plate: a.action_params == e,
        )
        reporter.check(
            f"OERSIM_sub_load_plate [{label}]: change_plate yml bytes equal",
            lambda a=change_plate, e=legacy_change_plate: yml_dumps(a.action_params)
            == yml_dumps(e),
        )
        reporter.check(
            f"OERSIM_sub_load_plate [{label}]: initialize_plate action_params == frozen dict",
            lambda a=initialize_plate, e=legacy_initialize_plate: a.action_params == e,
        )
        reporter.check(
            f"OERSIM_sub_load_plate [{label}]: initialize_plate yml bytes equal",
            lambda a=initialize_plate, e=legacy_initialize_plate: yml_dumps(
                a.action_params
            )
            == yml_dumps(e),
        )
        reporter.check(
            f"OERSIM_sub_load_plate [{label}]: get_loaded_plate action_params stays empty",
            lambda a=get_loaded_plate: a.action_params == {},
        )

    for label, kwargs in (
        (
            "defaults",
            {
                "stop_condition": "max_iters",
                "thresh_value": 10,
                "repeat_experiment_name": "OERSIM_sub_activelearn",
                "repeat_experiment_params": {},
                "repeat_experiment_kwargs": {},
            },
        ),
        (
            "non-default",
            {
                "stop_condition": "max_ei",
                "thresh_value": 2.5,
                "repeat_experiment_name": "custom_exp",
                "repeat_experiment_params": {"a": 1},
                "repeat_experiment_kwargs": {"b": 2},
            },
        ),
    ):
        actions = _capture_actions(OERSIM_sub_decision, **kwargs)
        check_condition = _action_by_name(actions, "check_condition")
        legacy = _legacy_check_condition(**kwargs)
        reporter.check(
            f"OERSIM_sub_decision [{label}]: check_condition action_params == frozen dict",
            lambda a=check_condition, e=legacy: a.action_params == e,
        )
        reporter.check(
            f"OERSIM_sub_decision [{label}]: check_condition key order matches",
            lambda a=check_condition, e=legacy: list(a.action_params.keys())
            == list(e.keys()),
        )
        reporter.check(
            f"OERSIM_sub_decision [{label}]: check_condition yml bytes equal",
            lambda a=check_condition, e=legacy: yml_dumps(a.action_params)
            == yml_dumps(e),
        )

    for label, kwargs in (
        (
            "defaults",
            {
                "init_random_points": 5,
                "stop_condition": "max_iters",
                "thresh_value": 10,
                "repeat_experiment_kwargs": {},
            },
        ),
        (
            "non-default",
            {
                "init_random_points": 3,
                "stop_condition": "max_stdev",
                "thresh_value": 7.5,
                "repeat_experiment_kwargs": {"z": 9},
            },
        ),
    ):
        actions = _capture_actions(OERSIM_sub_activelearn, **kwargs)
        check_condition = _action_by_name(actions, "check_condition")
        # OERSIM_sub_activelearn builds repeat_experiment_params via
        # reflection over vars(apm.pars) (OERSIM_exp.py:186-190) — this
        # reflection dict stays verbatim (declared non-goal, D6/§5.1), so the
        # frozen legacy dict mirrors that reflection exactly rather than
        # asserting on it as a typed payload.
        expected_repeat_params = dict(kwargs)
        legacy = _legacy_check_condition(
            stop_condition=kwargs["stop_condition"],
            thresh_value=kwargs["thresh_value"],
            repeat_experiment_name="OERSIM_sub_activelearn",
            repeat_experiment_params=expected_repeat_params,
            repeat_experiment_kwargs=kwargs["repeat_experiment_kwargs"],
        )
        reporter.check(
            f"OERSIM_sub_activelearn [{label}]: check_condition action_params == frozen dict",
            lambda a=check_condition, e=legacy: a.action_params == e,
        )
        reporter.check(
            f"OERSIM_sub_activelearn [{label}]: check_condition yml bytes equal",
            lambda a=check_condition, e=legacy: yml_dumps(a.action_params)
            == yml_dumps(e),
        )

        measure_actions = [
            a
            for a in actions
            if a.action_name in ("acquire_point", "measure_cp", "update_model")
        ]
        reporter.check(
            f"OERSIM_sub_activelearn [{label}]: measure_CP actions stay empty-param",
            lambda acts=measure_actions: all(a.action_params == {} for a in acts),
        )

    for label, kwargs in (
        (
            "defaults",
            {
                "init_random_points": 5,
                "stop_condition": "max_iters",
                "thresh_value": 10,
            },
        ),
        (
            "non-default",
            {"init_random_points": 8, "stop_condition": "none", "thresh_value": 42},
        ),
    ):
        planned = OERSIM_activelearn(**kwargs)
        exp = planned[0]
        legacy = _legacy_activelearn_seq(**kwargs)
        reporter.check(
            f"OERSIM_activelearn seq [{label}]: experiment_params == frozen dict",
            lambda exp=exp, e=legacy: exp.experiment_params == e,
        )
        reporter.check(
            f"OERSIM_activelearn seq [{label}]: experiment_params key order matches",
            lambda exp=exp, e=legacy: list(exp.experiment_params.keys())
            == list(e.keys()),
        )
        reporter.check(
            f"OERSIM_activelearn seq [{label}]: experiment_params yml bytes equal",
            lambda exp=exp, e=legacy: yml_dumps(exp.experiment_params) == yml_dumps(e),
        )


def _check_type_fidelity(reporter: TestReporter) -> None:
    """Check 3: numeric fidelity + plain-str enum leakage."""
    reporter.section("type fidelity (§7 check 3)")

    int_dump = GPSIMCheckConditionParams(thresh_value=10).model_dump()
    float_dump = GPSIMCheckConditionParams(thresh_value=10.5).model_dump()
    reporter.check(
        "thresh_value=10 stays int in model_dump()",
        lambda: type(int_dump["thresh_value"]) is int
        and int_dump["thresh_value"] == 10,
    )
    reporter.check(
        "thresh_value=10.5 stays float in model_dump()",
        lambda: type(float_dump["thresh_value"]) is float
        and float_dump["thresh_value"] == 10.5,
    )

    str_dump = GPSIMCheckConditionParams(stop_condition="max_ei").model_dump()
    reporter.check(
        "stop_condition dumps as plain str (use_enum_values proof)",
        lambda: type(str_dump["stop_condition"]) is str,
    )

    enum_input = GPSIMCheckConditionParams(
        stop_condition=StopCondition.max_ei
    ).model_dump()
    string_input = GPSIMCheckConditionParams(stop_condition="max_ei").model_dump()
    reporter.check(
        "enum-input vs string-input dump identically",
        lambda: enum_input == string_input,
    )


def _check_enforcement(reporter: TestReporter) -> None:
    """Check 4: extra='forbid' + enum validation + resolve_stop_condition errors."""
    reporter.section("enforcement (§7 check 4)")

    def _raises_validation_error(fn):
        try:
            fn()
        except ValidationError:
            return True
        except Exception:
            return False
        return False

    reporter.check(
        "GPSIMCheckConditionParams(stop_condition='bogus') raises ValidationError",
        lambda: _raises_validation_error(
            lambda: GPSIMCheckConditionParams(stop_condition="bogus")
        ),
    )
    reporter.check(
        "GPSIMCheckConditionParams(stop_condtion='max_iters') [typo key] raises ValidationError",
        lambda: _raises_validation_error(
            lambda: GPSIMCheckConditionParams(stop_condtion="max_iters")
        ),
    )

    def _resolve_bogus_message():
        try:
            resolve_stop_condition("bogus")
        except ValueError as exc:
            return str(exc)
        return None

    bogus_msg = _resolve_bogus_message()
    reporter.check(
        "resolve_stop_condition('bogus') raises ValueError",
        lambda: bogus_msg is not None,
    )
    reporter.check(
        "resolve_stop_condition('bogus') message names all four valid values",
        lambda: bogus_msg is not None
        and all(v in bogus_msg for v in ("none", "max_iters", "max_stdev", "max_ei")),
    )
    reporter.check(
        "resolve_stop_condition('max_ei') is StopCondition.max_ei",
        lambda: resolve_stop_condition("max_ei") is StopCondition.max_ei,
    )


def _check_enum_surface(reporter: TestReporter) -> None:
    """Check 5: enum surface freeze."""
    reporter.section("enum surface freeze (§7 check 5)")
    reporter.check(
        "StopCondition values == ['none', 'max_iters', 'max_stdev', 'max_ei']",
        lambda: [m.value for m in StopCondition]
        == ["none", "max_iters", "max_stdev", "max_ei"],
    )


def oersim_params_unit_test() -> bool:
    """Run all OERSIM typed-param equivalence checks and report pass/fail."""
    reporter = TestReporter("oersim_params")

    try:
        _check_frozen_literal_equivalence(reporter)
        _check_authoring_path_equivalence(reporter)
        _check_type_fidelity(reporter)
        _check_enforcement(reporter)
        _check_enum_surface(reporter)

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False


if __name__ == "__main__":
    ok = oersim_params_unit_test()
    if ok:
        print("PASS: unit_test_oersim_params — typed OERSIM param models verified")
    sys.exit(0 if ok else 1)
