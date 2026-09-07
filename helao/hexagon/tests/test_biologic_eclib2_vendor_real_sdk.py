"""Load the *real* EC-Lib 2.0 Python layer, when a copy is available.

Skipped unless ``HELAO_ECLIB2_SDK_PATH`` points at an unpacked
``biologic_ec_sdk`` root, since the SDK is licensed and not redistributable.

This file exists because the synthetic package in
``test_biologic_eclib2_vendor.py`` was initially written to match a *belief*
about the vendor's import style rather than the vendor's actual code, and
passed while the loader was broken against the shipped package. Every member
name the driver depends on is asserted here against the shipped enums, so a
name that this SDK build spells differently fails at test time rather than at
the first acquisition.

Nothing here loads the DLL, so it runs on Linux against a Windows SDK.
"""

import os

import pytest

from helao.hexagon.tests.biologic_eclib2_sample_params import params
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import enum as ec2enum
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import technique as ec2tech
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import vendor

SDK_PATH = os.environ.get("HELAO_ECLIB2_SDK_PATH")

pytestmark = pytest.mark.skipif(
    not SDK_PATH,
    reason="set HELAO_ECLIB2_SDK_PATH to an unpacked biologic_ec_sdk root",
)


@pytest.fixture
def modules():
    vendor.unload()
    try:
        yield vendor.load_sdk(SDK_PATH)
    finally:
        vendor.unload()


def test_the_shipped_package_loads(modules):
    assert modules.api_class.__name__ == "ECLibAPI"
    assert modules.error_class.__name__ == "EC_SDK_Runtime_Error"


def test_the_api_exposes_every_call_the_driver_makes(modules):
    for name in [
        "BL_Connect",
        "BL_Disconnect",
        "BL_TestConnection",
        "BL_LoadFirmware",
        "BL_CreateExperiment",
        "BL_DeleteExperiment",
        "BL_AddTechnique",
        "BL_LoadExperiment",
        "BL_UpdateExperiment",
        "BL_StartChannel",
        "BL_StopChannel",
        "BL_DownloadRawData",
        "BL_GetLiveValues",
        "BL_SetFloatParameter",
        "BL_SetFloatArrayParameter",
        "BL_SetIntParameter",
        "BL_SetBoolParameter",
        "BL_SetEnumParameter",
        "BL_SetEnumArrayParameter",
        "BL_SetIRange",
        "BL_SetERange",
        "BL_SetBandwidth",
        "BL_ProcessRawToOcvData",
        "BL_ProcessRawToCaData",
        "BL_ProcessRawToCpData",
        "BL_ProcessRawToCvData",
        "BL_ProcessRawToEisData",
    ]:
        assert callable(getattr(modules.api_class, name, None)), name


@pytest.mark.parametrize("caption", ec2enum.IRANGE_CAPTIONS)
def test_every_irange_caption_resolves_against_the_shipped_enums(modules, caption):
    mode, value = ec2enum.irange_plan(caption)
    assert vendor.member(modules.constants, "IRangeMode", mode) is not None
    assert vendor.member(modules.constants, "IRangeValue", value) is not None


@pytest.mark.parametrize("caption", sorted(ec2enum.ERANGE_CAPTIONS))
def test_every_erange_caption_resolves(modules, caption):
    name = ec2enum.erange_name(caption)
    assert vendor.member(modules.constants, "ERangeValue", name) is not None


@pytest.mark.parametrize("caption", sorted(ec2enum.BANDWIDTH_CAPTIONS))
def test_every_bandwidth_caption_resolves(modules, caption):
    name = ec2enum.bandwidth_name(caption)
    assert vendor.member(modules.constants, "BandwidthValue", name) is not None


def test_every_technique_identifier_the_registry_names_exists(modules):
    for identifier in ec2tech.READER_BY_IDENTIFIER:
        assert (
            vendor.member(modules.constants, "TechniqueIdentifier", identifier)
            is not None
        )


_KIND_TO_ENUM = {
    "float": "FloatParameter",
    "float_array": "FloatArrayParameter",
    "int": "IntParameter",
    "bool": "BoolParameter",
    "enum": "EnumParameter",
    "enum_array": "EnumArrayParameter",
}


@pytest.mark.parametrize("technique_name", ec2tech.TECHNIQUE_NAMES)
def test_every_parameter_the_registry_emits_exists_in_its_enum(modules, technique_name):
    # This is what would have caught the technique doc tables being wrong
    # about RECORD_EVERY_DT_MODE and EC_SDK_ANALOG_GAIN.
    plan = ec2tech.build_plan(technique_name, params(technique_name))
    for tech in plan.techniques:
        for param in tech.params:
            enum_name = _KIND_TO_ENUM[param.kind]
            assert (
                vendor.member(modules.constants, enum_name, param.name) is not None
            ), f"{enum_name}.{param.name}"


@pytest.mark.parametrize("technique_name", ec2tech.TECHNIQUE_NAMES)
def test_every_enum_valued_parameter_resolves_to_a_real_member(modules, technique_name):
    plan = ec2tech.build_plan(technique_name, params(technique_name))
    for tech in plan.techniques:
        for param in tech.params:
            if param.kind == "enum":
                # The only `enum` parameter is the sweep mode.
                assert (
                    vendor.member(modules.constants, "SweepMode", param.value)
                    is not None
                )
            elif param.kind == "enum_array":
                for value in param.value:
                    assert (
                        vendor.member(modules.constants, "VsInitial", value) is not None
                    )


def test_the_channel_state_enum_is_the_polarity_the_driver_assumes(modules):
    # The two shipped examples contradict each other on this: one prints
    # "running" for channel_state == EC_SDK_CHANNEL_STATE_RUNNING, the other
    # for channel_state == 0. The enum is what the driver trusts.
    state = modules.constants.ChannelState
    assert state["EC_SDK_CHANNEL_STATE_IDLE"].value == 0
    assert state["EC_SDK_CHANNEL_STATE_RUNNING"].value == 1


def test_the_eis_row_struct_has_every_field_the_data_layer_reads(modules):
    fields = set(modules.constants.EisData.__dataclass_fields__)
    assert {
        "frequency",
        "mod_ewe",
        "mod_iwe",
        "phase_we",
        "ewe_dc",
        "iwe_dc",
        "mod_ece",
        "mod_ice",
        "phase_ce",
        "ece_dc",
        "ice_dc",
        "time_in_s",
    } <= fields


def test_the_step_row_structs_use_the_average_field_names(modules):
    # The HTML docs call the CA/CP fields `ewe`/`i`; the shipped dataclasses
    # call them `ewe_average`/`i_average` on all three step techniques. The
    # data layer binds to the dataclasses.
    for name in ("CaData", "CpData", "CvData"):
        fields = set(getattr(modules.constants, name).__dataclass_fields__)
        assert {"time", "ewe_average", "i_average", "cycle"} <= fields, name


def test_the_ocv_row_struct_uses_the_plain_field_names(modules):
    fields = set(modules.constants.OcvData.__dataclass_fields__)
    assert {"time", "ewe"} <= fields
