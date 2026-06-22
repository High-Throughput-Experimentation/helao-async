"""Tests for the ported composite models: sample, file, process, analysis.

The sample-model assertions are a real-pytest port of the legacy
``helao/core/tests/unit_test_sample_models.py`` (formerly a single
bool-returning, print-driven function); each behavior is now its own
``test_*`` with ``assert``.
"""
from uuid import uuid4

import pytest

from helao.framework.models.sample import (
    LiquidSample,
    GasSample,
    SolidSample,
    AssemblySample,
    NoneSample,
    SampleModel,
    SampleList,
    SampleType,
    SampleStatus,
    object_to_sample,
)
from helao.framework.models.file import (
    HloFileGroup,
    HloHeaderModel,
    FileConnParams,
    FileConn,
    FileInfo,
)
from helao.framework.models.process import ProcessModel, ShortProcessModel
from helao.framework.models.analysis import (
    AnalysisModel,
    ShortAnalysisModel,
    AnalysisDataModel,
    AnalysisOutputModel,
)
from helao.framework.models.run_use import RunUse
from helao.framework.models.s3locator import S3Locator


# --------------------------------------------------------------------------- #
# Sample models — single samples (ported from unit_test_sample_models.py)
# --------------------------------------------------------------------------- #
def test_liquid_sample_type():
    assert LiquidSample().sample_type == "liquid"


def test_gas_sample_type():
    assert GasSample().sample_type == "gas"


def test_solid_sample_type():
    assert SolidSample().sample_type == "solid"


def test_solid_sample_default_machine_name_legacy():
    assert SolidSample().machine_name == "legacy"


def test_assembly_sample_type_single_part():
    assert AssemblySample(parts=[NoneSample()]).sample_type == "assembly"


def test_assembly_sample_type_nested():
    liquid = LiquidSample()
    gas = GasSample()
    solid = SolidSample()
    inner = AssemblySample(parts=[NoneSample()])
    outer = AssemblySample(parts=[gas, solid, liquid, inner])
    assert outer.sample_type == "assembly"


# --------------------------------------------------------------------------- #
# Sample models — SampleList from model instances
# --------------------------------------------------------------------------- #
@pytest.fixture
def sample_set():
    liquid = LiquidSample()
    gas = GasSample()
    solid = SolidSample()
    assembly = AssemblySample(parts=[NoneSample()])
    assembly2 = AssemblySample(parts=[gas, solid, liquid, assembly])
    return liquid, gas, solid, assembly, assembly2


def test_sample_list_from_instances_preserves_types(sample_set):
    liquid, gas, solid, assembly, assembly2 = sample_set
    sl = SampleList(samples=[liquid, gas, solid, assembly, assembly2])
    assert sl.samples[0].sample_type == "liquid"
    assert sl.samples[1].sample_type == "gas"
    assert sl.samples[2].sample_type == "solid"
    assert sl.samples[2].machine_name == "legacy"
    assert sl.samples[3].sample_type == "assembly"
    assert type(sl.samples[0]) is type(liquid)
    assert type(sl.samples[1]) is type(gas)
    assert type(sl.samples[2]) is type(solid)
    assert type(sl.samples[3]) is type(assembly)
    assert type(sl.samples[4]) is type(assembly2)


def test_sample_list_from_dicts_preserves_types(sample_set):
    liquid, gas, solid, assembly, assembly2 = sample_set
    sl = SampleList(
        samples=[
            liquid.model_dump(),
            gas.model_dump(),
            solid.model_dump(),
            assembly.model_dump(),
            assembly2.model_dump(),
        ]
    )
    assert sl.samples[0].sample_type == "liquid"
    assert sl.samples[1].sample_type == "gas"
    assert sl.samples[2].sample_type == "solid"
    assert sl.samples[2].machine_name == "legacy"
    assert sl.samples[3].sample_type == "assembly"
    assert type(sl.samples[0]) is type(liquid)
    assert type(sl.samples[1]) is type(gas)
    assert type(sl.samples[2]) is type(solid)
    assert type(sl.samples[3]) is type(assembly)
    assert type(sl.samples[4]) is type(assembly2)


# --------------------------------------------------------------------------- #
# Sample models — helpers / behavior
# --------------------------------------------------------------------------- #
def test_none_sample_get_global_label_is_none():
    assert NoneSample().get_global_label() is None


def test_liquid_get_global_label_derived_from_machine_and_no():
    s = LiquidSample(machine_name="testmachine", sample_no=7)
    assert s.get_global_label() == "testmachine__liquid__7"


def test_solid_root_validator_sets_global_label():
    s = SolidSample(machine_name="testmachine", plate_id=3, sample_no=9)
    assert s.global_label == "testmachine__solid__3_9"


def test_liquid_destroy_sample_zeroes_volume_and_marks_destroyed():
    s = LiquidSample(volume_ml=5.0)
    s.destroy_sample()
    assert s.volume_ml == 0
    assert SampleStatus.destroyed in s.status


def test_liquid_get_vol_and_dilution():
    s = LiquidSample(volume_ml=2.5, dilution_factor=4.0)
    assert s.get_vol_ml() == 2.5
    assert s.get_dilution_factor() == 4.0


def test_none_sample_get_vol_ml_is_none():
    assert NoneSample().get_vol_ml() is None


def test_assembly_exp_dict_lists_part_labels():
    liquid = LiquidSample(machine_name="m", sample_no=1)
    assembly = AssemblySample(machine_name="m", parts=[liquid])
    parts = assembly.get_assembly_parts_exp_dict()
    assert parts == ["m__liquid__1"]


def test_object_to_sample_coerces_dict():
    s = object_to_sample({"sample_type": "liquid", "sample_no": 2})
    assert isinstance(s, LiquidSample)
    assert s.sample_type == SampleType.liquid


def test_sample_model_round_trip():
    s = LiquidSample(machine_name="m", sample_no=1, volume_ml=3.0)
    again = LiquidSample(**s.model_dump())
    assert again.model_dump() == s.model_dump()


# --------------------------------------------------------------------------- #
# File models
# --------------------------------------------------------------------------- #
def test_hlo_file_group_members():
    assert HloFileGroup.helao_files == "helao_files"
    assert HloFileGroup.aux_files == "aux_files"


def test_hlo_header_defaults():
    h = HloHeaderModel()
    assert h.column_headings == []
    assert h.optional == {}
    assert h.epoch_ns is None


def test_file_conn_params_defaults():
    key = uuid4()
    p = FileConnParams(file_conn_key=key)
    assert p.file_conn_key == key
    assert p.file_type == "helao__file"
    assert p.file_group == HloFileGroup.helao_files
    assert isinstance(p.hloheader, HloHeaderModel)


def test_file_conn_params_requires_key():
    with pytest.raises(Exception):
        FileConnParams()


def test_file_conn_reset_and_deepcopy():
    p = FileConnParams(file_conn_key=uuid4())
    fc = FileConn(params=p, added_hlo_separator=True, file=object())
    copy = fc.deepcopy()
    assert copy.file is None
    assert copy.added_hlo_separator is True
    fc.reset_file_conn()
    assert fc.file is None
    assert fc.added_hlo_separator is False


def test_file_info_defaults_and_round_trip():
    fi = FileInfo(file_name="x.hlo", file_type="helao__file")
    assert fi.nosync is False
    assert fi.run_use is None
    assert fi.data_keys == []
    assert FileInfo(**fi.model_dump()).model_dump() == fi.model_dump()


# --------------------------------------------------------------------------- #
# Process models
# --------------------------------------------------------------------------- #
def test_short_process_model_defaults():
    sp = ShortProcessModel()
    assert sp.process_uuid is None
    assert sp.hlo_version is not None


def test_process_model_defaults_and_round_trip():
    pm = ProcessModel(process_uuid=uuid4())
    assert pm.access == "hte"
    assert pm.run_use == RunUse.data
    assert pm.dispatched_actions_abbr == []
    assert pm.samples_in == []
    assert ProcessModel(**pm.model_dump()).model_dump() == pm.model_dump()


# --------------------------------------------------------------------------- #
# Analysis models
# --------------------------------------------------------------------------- #
def test_short_analysis_model_defaults_timestamp():
    sa = ShortAnalysisModel()
    assert sa.analysis_timestamp is not None


def test_analysis_data_model_requires_action_uuid_and_path():
    adm = AnalysisDataModel(action_uuid=uuid4(), raw_data_path="/some/path")
    assert adm.run_use == RunUse.data
    with pytest.raises(Exception):
        AnalysisDataModel(raw_data_path="/some/path")


def test_analysis_output_model_requires_locator():
    loc = S3Locator(bucket="b", key="k", region="r")
    out = AnalysisOutputModel(
        analysis_output_path=loc, content_type="application/json", output_type="scalar"
    )
    assert out.analysis_output_path.url == "s3://b/k"


def test_analysis_model_round_trip():
    loc = S3Locator(bucket="b", key="k", region="r")
    am = AnalysisModel(
        analysis_uuid=uuid4(),
        analysis_name="demo",
        analysis_params={"a": 1},
        inputs=[AnalysisDataModel(action_uuid=uuid4(), raw_data_path="/p")],
        outputs=[
            AnalysisOutputModel(
                analysis_output_path=loc,
                content_type="application/json",
                output_type="scalar",
            )
        ],
    )
    assert am.access == "hte"
    assert AnalysisModel(**am.model_dump()).model_dump() == am.model_dump()
