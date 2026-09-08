"""EC-Lib 2.0 has no trigger technique, and this is the ratchet that says so.

Both sibling BioLogic backends honour the frozen ``TTLwait``/``TTLsend``/
``TTLduration`` parameters the same way, because neither SDK has a trigger
*call*: Trigger In and Trigger Out are **techniques**, so you bracket the
measurement with them.

- eclib does it by prepending a ``TI`` or ``TO`` ``.ecc`` technique
  (``easy_biologic/program.py::_run``, this repo's fork).
- olecom does it by splicing the ``TI``/``TO`` technique blocks into the
  ``.mps`` (``biologic_ole/mps_assemble.py``), bracketing rather than merely
  prepending, verified against a real GUI-authored ``TI_CV_TO.mps``.

**eclib2 cannot, because EC-Lib 2.0's technique vocabulary contains no
trigger technique to add.** ``BL_AddTechnique`` takes a
``TechniqueIdentifier``, and that enum holds nine measurement techniques plus
two loop controls -- no TI, TO or TOS, and no ``Trigger_Logic`` /
``Trigger_Duration`` parameter in any of the parameter enums. Note the
identifier space is EClib2's own, *not* EC-Lab's appendix 7.1 numbering (where
TI/TO are 38/39 and 88/89), so the appendix codes the OLE backend relies on do
not carry over.

So this file does not test a feature. It pins the *absence* that forces
eclib2's ``start_channel`` to refuse an active TTL request rather than ignore
it, and it is written to fail if BioLogic ever ships a trigger technique --
at which point the eclib/olecom bracketing approach becomes implementable here
and this file should be replaced by it.

The strict half needs a real SDK (``HELAO_ECLIB2_SDK_PATH``); the rest holds
anywhere, so the guarantee is not silently unchecked off-station.
"""

import os

import pytest

from helao.deploy.hte.drivers.pstat.biologic_eclib2 import technique as ec2tech
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import vendor
from helao.deploy.hte.drivers.pstat.biologic_eclib2.driver import BiologicEclib2Driver
from helao.hexagon.tests.biologic_eclib2_sample_params import params

SDK_PATH = os.environ.get("HELAO_ECLIB2_SDK_PATH")

#: Names a trigger technique would plausibly carry. Matched as substrings so a
#: future EC_SDK_TECHNIQUE_TRIGGER_IN or ..._TI is caught either way.
TRIGGER_TECHNIQUE_TOKENS = ("TRIGGER", "_TI", "_TO", "_TOS")

#: Parameters a trigger technique would need. EClib1's TI takes Trigger_Logic;
#: TO takes Trigger_Logic and Trigger_Duration.
TRIGGER_PARAM_TOKENS = ("TRIGGER_LOGIC", "TRIGGER_DURATION", "TRIGGER_DELAY")

#: Every vendor parameter enum a technique's settings can come from.
PARAMETER_ENUMS = (
    "FloatParameter",
    "FloatArrayParameter",
    "IntParameter",
    "IntArrayParameter",
    "BoolParameter",
    "BoolArrayParameter",
    "EnumParameter",
    "EnumArrayParameter",
)


# --------------------------------------------------------------------------
# holds without the SDK
# --------------------------------------------------------------------------


def test_this_backends_registry_names_no_trigger_technique():
    for identifier in ec2tech.READER_BY_IDENTIFIER:
        upper = identifier.upper()
        assert not any(token in upper for token in TRIGGER_TECHNIQUE_TOKENS), identifier


def test_the_loop_controls_are_the_only_non_measurement_techniques():
    # If a trigger technique existed it would live alongside these, since a
    # loop control is the one other thing EClib2 lets you add that does not
    # measure.
    assert ec2tech.LOOP_IDENTIFIERS == {
        "EC_SDK_TECHNIQUE_LOOP_START",
        "EC_SDK_TECHNIQUE_LOOP_END",
    }


def test_no_plan_this_backend_builds_can_contain_a_trigger():
    # Covers the multi-technique path too: run_plan assembles techniques from
    # the same registry, so it cannot smuggle one in either.
    for name in ec2tech.TECHNIQUE_NAMES:
        plan = ec2tech.build_plan(name, params(name))
        for tech in plan.techniques:
            upper = tech.identifier.upper()
            assert not any(
                token in upper for token in TRIGGER_TECHNIQUE_TOKENS
            ), f"{name} -> {tech.identifier}"
            for param in tech.params:
                assert not any(
                    token in param.name.upper() for token in TRIGGER_PARAM_TOKENS
                ), f"{name} -> {param.name}"


@pytest.mark.parametrize("ttl", ["in", "out"])
def test_the_driver_refuses_an_active_ttl_request_rather_than_ignoring_it(ttl):
    # The consequence of the absence, and the reason it must be a refusal: a
    # station that believed it was triggering would collect data uncorrelated
    # with whatever it meant to synchronise against, and nothing would say so.
    driver = BiologicEclib2Driver(
        {"address": "127.0.0.1", "num_channels": 1, "simulate": True}
    )
    try:
        driver.connect()
        driver.setup(
            technique=ec2tech.resolve("OCV"),
            action_params=params("OCV", channel=0),
        )
        response = driver.start_channel(0, {"ttl": ttl, "ttl_duration": 1.0})
        assert response.response == "not_implemented"
        # Names the backends that can, so the message is actionable.
        assert "eclib" in response.message and "olecom" in response.message
    finally:
        driver.shutdown()


# --------------------------------------------------------------------------
# the strict half: against the shipped SDK
# --------------------------------------------------------------------------


@pytest.fixture
def constants():
    if not SDK_PATH:
        pytest.skip("set HELAO_ECLIB2_SDK_PATH to an unpacked biologic_ec_sdk root")
    vendor.unload()
    try:
        yield vendor.load_sdk(SDK_PATH).constants
    finally:
        vendor.unload()


def test_the_shipped_technique_enum_has_no_trigger_technique(constants):
    """If this fails, EC-Lib 2.0 grew a trigger technique -- go implement it.

    The eclib and olecom backends both bracket the measurement with TI/TO;
    once an identifier exists here, run_plan's builder already inserts
    non-measurement techniques around a span (that is how LOOP works), so the
    same shape applies.
    """
    names = [member.name for member in constants.TechniqueIdentifier]
    offenders = [
        name
        for name in names
        if any(token in name.upper() for token in TRIGGER_TECHNIQUE_TOKENS)
    ]
    assert not offenders, f"EC-Lib 2.0 now has trigger techniques: {offenders}"


def test_the_shipped_parameter_enums_have_no_trigger_parameter(constants):
    """The other half: a technique is useless without its trigger settings."""
    offenders = []
    for enum_name in PARAMETER_ENUMS:
        enum_cls = getattr(constants, enum_name, None)
        if enum_cls is None:
            continue
        for member in enum_cls:
            if any(token in member.name.upper() for token in TRIGGER_PARAM_TOKENS):
                offenders.append(f"{enum_name}.{member.name}")
    assert not offenders, f"EC-Lib 2.0 now has trigger parameters: {offenders}"


def test_the_technique_enum_is_not_appendix_7_1_numbering(constants):
    """Why the OLE backend's trigger codes cannot simply be reused.

    ``mps_assemble`` relies on EC-Lab appendix 7.1, where Trigger In and
    Trigger Out are 38/39 and 88/89. EClib2 numbers its own identifiers
    independently -- OCV is 100, CA 101, the loop controls 500/501 -- so those
    codes mean nothing here, and passing one to BL_AddTechnique would be a
    guess at firmware behaviour on hardware that polarises a cell.
    """
    by_name = {m.name: m.value for m in constants.TechniqueIdentifier}
    assert by_name["EC_SDK_TECHNIQUE_OCV"] == 100
    assert by_name["EC_SDK_TECHNIQUE_CA"] == 101
    assert by_name["EC_SDK_TECHNIQUE_LOOP_START"] == 500
    # None of the appendix 7.1 trigger codes are in use as identifiers here,
    # which is the point: they are not "missing entries", they are a different
    # namespace.
    assert set(by_name.values()).isdisjoint({38, 39, 88, 89})


def test_the_api_exposes_no_trigger_call_either(constants):
    """Not just techniques: there is no BL_* trigger entry point to use."""
    modules = vendor.load_sdk(SDK_PATH)
    names = [n for n in dir(modules.api_class) if n.startswith("BL_")]
    offenders = [
        n
        for n in names
        if any(token in n.upper() for token in ("TRIGGER", "TTL", "DIGITALOUT"))
    ]
    assert not offenders, f"EC-Lib 2.0 now has a trigger call: {offenders}"
