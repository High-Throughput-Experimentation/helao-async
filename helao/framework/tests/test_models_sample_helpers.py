"""Targeted coverage for the pure helper methods on the sample models.

The base `test_models_sample.py` covers construction and a few helpers; this
module drives the remaining uncovered branches: `exp_dict` on every subtype,
`create_initial_exp_dict` status coercion, `get_global_label` derivations and
the stored-label early returns, `zero_volume`/`destroy_sample` status
transitions, `validate_parts` `None` coercion, and `object_to_sample` from a
`BaseModel` instance.
"""
from uuid import uuid4

from helao.framework.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    SampleModel,
    SampleStatus,
    SampleType,
    object_to_sample,
)


# --------------------------------------------------------------------------- #
# create_initial_exp_dict / exp_dict on the base and each subtype
# --------------------------------------------------------------------------- #
def test_base_create_initial_exp_dict_coerces_scalar_status_to_list():
    s = SampleModel(machine_name="MyMachine", sample_no=3)
    # assign a non-list status to hit the coercion branch
    s.status = SampleStatus.created
    d = s.create_initial_exp_dict()
    assert isinstance(s.status, list)
    assert d["machine_name"] == "mymachine"  # lowered
    assert d["sample_no"] == 3
    assert d["status"] == [SampleStatus.created]


def test_base_create_initial_exp_dict_none_machine_name():
    d = SampleModel(sample_no=1).create_initial_exp_dict()
    assert d["machine_name"] is None


def test_base_exp_dict_delegates_to_create_initial():
    s = SampleModel(machine_name="m", sample_no=1)
    assert s.exp_dict() == s.create_initial_exp_dict()


def test_none_sample_exp_dict_minimal():
    d = NoneSample().exp_dict()
    assert d == {"global_label": None, "sample_type": None}


def test_liquid_exp_dict_includes_volume_ph_dilution():
    s = LiquidSample(machine_name="m", sample_no=1, volume_ml=2.0, ph=7.0, dilution_factor=3.0)
    d = s.exp_dict()
    assert d["volume_ml"] == 2.0
    assert d["ph"] == 7.0
    assert d["dilution_factor"] == 3.0


def test_solid_exp_dict_includes_plate_id():
    from helao.framework.models.sample import SolidSample

    s = SolidSample(machine_name="m", plate_id=4, sample_no=2)
    d = s.exp_dict()
    assert d["plate_id"] == 4


def test_gas_exp_dict_includes_volume_and_dilution():
    s = GasSample(machine_name="m", sample_no=1, volume_ml=5.0, dilution_factor=2.0)
    d = s.exp_dict()
    assert d["volume_ml"] == 5.0
    assert d["dilution_factor"] == 2.0


def test_assembly_exp_dict_lists_assembly_parts():
    part = LiquidSample(machine_name="m", sample_no=1)
    asm = AssemblySample(machine_name="m", parts=[part])
    d = asm.exp_dict()
    assert d["assembly_parts"] == ["m__liquid__1"]


# --------------------------------------------------------------------------- #
# get_global_label — stored-label early returns and derivations
# --------------------------------------------------------------------------- #
def test_base_get_global_label_returns_stored():
    assert SampleModel(global_label="stored").get_global_label() == "stored"


def test_liquid_get_global_label_returns_stored_when_set():
    assert LiquidSample(global_label="set").get_global_label() == "set"


def test_liquid_get_global_label_none_machine_name():
    s = LiquidSample(sample_no=2)
    assert s.get_global_label() == "None__liquid__2"


def test_gas_get_global_label_derived_and_stored():
    assert GasSample(machine_name="M", sample_no=9).get_global_label() == "m__gas__9"
    assert GasSample(global_label="g").get_global_label() == "g"


def test_solid_get_global_label_derived_and_stored():
    from helao.framework.models.sample import SolidSample

    s = SolidSample(machine_name="M", plate_id=1, sample_no=2)
    # the model_validator forces global_label, so get_global_label hits the
    # stored-label branch; clear it to exercise the derivation branch.
    derived = s.get_global_label()
    assert derived == "M__solid__1_2"
    s.global_label = None
    assert s.get_global_label() == "m__solid__1_2"


def test_assembly_get_global_label_derived_and_stored():
    asm = AssemblySample(machine_name="M", sample_position="cellX", sample_creation_timecode=42)
    assert asm.get_global_label() == "m__assembly__cellX__42"
    asm2 = AssemblySample(global_label="a", parts=[])
    assert asm2.get_global_label() == "a"


# --------------------------------------------------------------------------- #
# zero_volume / destroy_sample status transitions
# --------------------------------------------------------------------------- #
def test_zero_volume_removes_preserved_adds_destroyed():
    s = LiquidSample(volume_ml=3.0, status=[SampleStatus.preserved])
    s.zero_volume()
    assert s.volume_ml == 0
    assert SampleStatus.destroyed in s.status
    assert SampleStatus.preserved not in s.status


def test_zero_volume_noop_without_volume_ml_attr():
    s = SampleModel()
    # base SampleModel has no volume_ml attribute -> branch not taken, no error
    s.zero_volume()
    assert SampleStatus.destroyed not in s.status


def test_destroy_sample_on_already_destroyed_idempotent():
    s = GasSample(volume_ml=1.0, status=[SampleStatus.destroyed])
    s.destroy_sample()
    assert s.status.count(SampleStatus.destroyed) == 1
    assert s.volume_ml == 0


def test_get_vol_ml_default_zero_on_base():
    assert SampleModel().get_vol_ml() == 0.0


def test_get_dilution_factor_default_one_on_base():
    assert SampleModel().get_dilution_factor() == 1.0


# --------------------------------------------------------------------------- #
# validate_parts / object_to_sample branches
# --------------------------------------------------------------------------- #
def test_assembly_validate_parts_coerces_none_to_empty_list():
    asm = AssemblySample(parts=None)
    assert asm.parts == []


def test_assembly_get_assembly_parts_exp_dict_empty():
    assert AssemblySample(parts=[]).get_assembly_parts_exp_dict() == []


def test_object_to_sample_from_basemodel_instance():
    src = LiquidSample(machine_name="m", sample_no=5, volume_ml=1.5)
    out = object_to_sample(src)
    assert isinstance(out, LiquidSample)
    assert out.sample_type == SampleType.liquid
    assert out.sample_no == 5
