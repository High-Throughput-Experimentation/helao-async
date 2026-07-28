"""Routing-equivalence proof for the discriminated ``SampleUnion`` alias
(CARDS P3 sub-increment 3c, union half of T1 only).

Proves the shipped two-stage nested union (``TypedSampleUnion`` +
``NoneSample`` + ``SampleModel`` fallback, see ``CARDS_REFACTOR_P3C.md``
D1/§5.1) routes identically to a locally-built loose union over the §4
synthetic set, at both the bare-sample level and the
``ActionModel``/``ExperimentModel``/``ProcessModel`` field level, and that
the recursive ``AssemblySample.parts`` annotation resolves via
``model_rebuild()``.

No sample-status lifecycle checks here — that half of CARDS 3c task T1
(the ``SampleModel`` guarded status methods) is out of scope for this test
(see ``unit_test_sample_status.py``).

Not a pytest test: standalone script matching the convention of the other
``helao.core.tests.unit_test_*`` modules, invoked directly or via
``run_unit_tests.py``. Exits non-zero on any failure.
"""

__all__ = ["sample_union_unit_test"]

import sys
import traceback
from typing import Union

from pydantic import TypeAdapter

from helao.core.models.action import ActionModel
from helao.core.models.experiment import ExperimentModel
from helao.core.models.process import ProcessModel
from helao.core.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    SampleModel,
    SampleUnion,
    SolidSample,
    object_to_sample,
)
from helao.core.tests._test_utils import TestReporter

# Locally-built loose union, matching the pre-3c inline annotation exactly
# (version-agnostic proof, mirrors the corpus-replay harness in
# CARDS_REFACTOR_P3C.md §4).
LOOSE = TypeAdapter(
    Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample, SampleModel]
)
NESTED = TypeAdapter(SampleUnion)

# §4 synthetic set: one of everything + every D1 edge case.
SYNTHETIC = [
    ("liquid python-dump", LiquidSample(sample_no=1).model_dump()),
    ("liquid json-dump", LiquidSample(sample_no=1).model_dump(mode="json")),
    ("gas python-dump", GasSample(sample_no=2).model_dump()),
    ("solid python-dump", SolidSample(plate_id=2750, sample_no=3).model_dump()),
    (
        "assembly python-dump",
        AssemblySample(
            parts=[LiquidSample(sample_no=1), SolidSample(plate_id=1, sample_no=2)]
        ).model_dump(),
    ),
    ("none python-dump", NoneSample().model_dump()),
    ("none sample_type-null dict", {"sample_type": None}),
    (
        "MEA fallback dict",
        {"sample_type": "MEA", "global_label": "synthetic", "etc": {"k": 1}},
    ),
    ("weird tag dict", {"sample_type": "weird", "global_label": "synthetic"}),
    (
        "liquid tag-present invalid payload",
        {"sample_type": "liquid", "volume_ml": "not-a-float"},
    ),
]

# Declared delta (D1): tag-absent {} routes to AssemblySample under the loose
# union (smart mode fills the Literal default) but to NoneSample under the
# nested design (the discriminated core requires the tag to be present).
# This is the ONE excluded case in the routing-equivalence check below.
TAG_ABSENT = {}


def _outcome(ta, block):
    try:
        m = ta.validate_python(block)
        return ("ok", type(m).__name__, m.model_dump_json())
    except Exception as exc:  # noqa: BLE001
        return ("fail", type(exc).__name__, None)


def _check_routing_equivalence(reporter: TestReporter) -> None:
    reporter.section("routing equivalence: nested SampleUnion vs local loose union")
    for label, block in SYNTHETIC:
        lo = _outcome(LOOSE, block)
        hi = _outcome(NESTED, block)
        reporter.check(
            f"{label}: routed type equal ({lo[1]} vs {hi[1]})",
            lambda lo=lo, hi=hi: lo[1] == hi[1],
        )
        reporter.check(
            f"{label}: outcome+dump byte-equal",
            lambda lo=lo, hi=hi: lo == hi,
        )

    # declared delta: tag-absent {} routes to NoneSample under the shipped
    # nested SampleUnion (see D1 in CARDS_REFACTOR_P3C.md).
    tag_absent_loose = _outcome(LOOSE, TAG_ABSENT)
    tag_absent_nested = _outcome(NESTED, TAG_ABSENT)
    reporter.check(
        "tag-absent {}: loose union routes to AssemblySample (today's fallback pathology)",
        lambda: tag_absent_loose[1] == "AssemblySample",
    )
    reporter.check(
        "tag-absent {}: nested SampleUnion routes to NoneSample (declared D1 delta)",
        lambda: tag_absent_nested[0] == "ok" and tag_absent_nested[1] == "NoneSample",
    )


def _check_model_level(reporter: TestReporter) -> None:
    reporter.section(
        "model-level: ActionModel/ExperimentModel/ProcessModel dict samples"
    )
    sample_dicts = [
        LiquidSample(sample_no=1).model_dump(),
        GasSample(sample_no=2).model_dump(),
        SolidSample(plate_id=1, sample_no=3).model_dump(),
        AssemblySample(parts=[LiquidSample(sample_no=1)]).model_dump(),
        NoneSample().model_dump(),
        {"sample_type": "MEA", "global_label": "mea-fallback"},
    ]
    expected_types = [
        "LiquidSample",
        "GasSample",
        "SolidSample",
        "AssemblySample",
        "NoneSample",
        "SampleModel",
    ]

    for model_cls in (ActionModel, ExperimentModel, ProcessModel):
        m = model_cls(samples_in=list(sample_dicts), samples_out=list(sample_dicts))
        routed_in = [type(s).__name__ for s in m.samples_in]
        routed_out = [type(s).__name__ for s in m.samples_out]
        reporter.check(
            f"{model_cls.__name__}.samples_in routed types match expected",
            lambda routed_in=routed_in: routed_in == expected_types,
        )
        reporter.check(
            f"{model_cls.__name__}.samples_out routed types match expected",
            lambda routed_out=routed_out: routed_out == expected_types,
        )

        dumped = m.model_dump()
        revalidated = model_cls(**dumped)
        reporter.check(
            f"{model_cls.__name__}: model_dump() re-validates byte-identically",
            lambda m=m, revalidated=revalidated: m.model_dump_json()
            == revalidated.model_dump_json(),
        )


def _check_assembly_recursion(reporter: TestReporter) -> None:
    reporter.section("assembly recursion: nested AssemblySample-in-parts")

    inner_liquid = LiquidSample(sample_no=1)
    inner_solid = SolidSample(plate_id=1, sample_no=2)
    inner_assembly = AssemblySample(parts=[inner_liquid, inner_solid])
    outer_constructed = AssemblySample(
        parts=[inner_assembly, LiquidSample(sample_no=3)]
    )

    outer_dict = outer_constructed.model_dump()
    outer_from_dict = AssemblySample.model_validate(outer_dict)

    reporter.check(
        "nested assembly: constructed vs dict-validated model_dump() byte-identical",
        lambda: outer_constructed.model_dump() == outer_from_dict.model_dump(),
    )
    reporter.check(
        "nested assembly: constructed vs dict-validated model_dump_json() byte-identical",
        lambda: outer_constructed.model_dump_json()
        == outer_from_dict.model_dump_json(),
    )
    reporter.check(
        "nested assembly: inner part resolved as AssemblySample (proves model_rebuild recursion)",
        lambda: type(outer_from_dict.parts[0]).__name__ == "AssemblySample",
    )
    reporter.check(
        "nested assembly: inner-inner parts resolved as concrete subtypes",
        lambda: [type(p).__name__ for p in outer_from_dict.parts[0].parts]
        == ["LiquidSample", "SolidSample"],
    )

    # also validate through the shipped SampleUnion / NESTED adapter directly
    via_union = NESTED.validate_python(outer_dict)
    reporter.check(
        "nested assembly: routes to AssemblySample via shipped SampleUnion",
        lambda: type(via_union).__name__ == "AssemblySample",
    )
    reporter.check(
        "nested assembly: SampleUnion-routed dump matches constructed instance",
        lambda: via_union.model_dump_json() == outer_constructed.model_dump_json(),
    )


def _check_object_to_sample(reporter: TestReporter) -> None:
    reporter.section("object_to_sample: matches direct validation per subtype")

    cases = [
        ("liquid", LiquidSample(sample_no=1).model_dump(), LiquidSample),
        ("gas", GasSample(sample_no=2).model_dump(), GasSample),
        ("solid", SolidSample(plate_id=1, sample_no=3).model_dump(), SolidSample),
        (
            "assembly",
            AssemblySample(parts=[LiquidSample(sample_no=1)]).model_dump(),
            AssemblySample,
        ),
        ("none", NoneSample().model_dump(), NoneSample),
        ("MEA fallback", {"sample_type": "MEA", "global_label": "mea"}, SampleModel),
    ]

    for label, block, expected_cls in cases:
        via_helper = object_to_sample(block)
        via_direct = expected_cls.model_validate(block)
        reporter.check(
            f"object_to_sample({label}) returns {expected_cls.__name__}",
            lambda via_helper=via_helper, expected_cls=expected_cls: type(via_helper)
            is expected_cls,
        )
        reporter.check(
            f"object_to_sample({label}) matches direct validation",
            lambda via_helper=via_helper, via_direct=via_direct: via_helper.model_dump_json()
            == via_direct.model_dump_json(),
        )


def sample_union_unit_test() -> bool:
    """Run all SampleUnion routing-equivalence assertions and report pass/fail."""
    reporter = TestReporter("sample_union")

    try:
        _check_routing_equivalence(reporter)
        _check_model_level(reporter)
        _check_assembly_recursion(reporter)
        _check_object_to_sample(reporter)

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False


if __name__ == "__main__":
    ok = sample_union_unit_test()
    if ok:
        print("PASS: unit_test_sample_union — nested SampleUnion routing verified")
    sys.exit(0 if ok else 1)
