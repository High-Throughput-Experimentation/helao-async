"""Tests for helao.framework.support.constants."""
from helao.framework.support import constants


def test_ref_table_values():
    assert constants.REF_TABLE == {"leakless": 0.21, "inhouse": 0.21, "rhe": 0.0}


def test_reference_class_exists_with_annotations():
    assert hasattr(constants, "Reference")
    assert constants.Reference.__annotations__["name"] is str
    assert constants.Reference.__annotations__["Vnhe"] is float


def test_spec_map_values():
    assert constants.SPEC_MAP == {
        "T_UVVIS": ["T"],
        "DR_UVVIS": ["R"],
        "TR_UVVIS": ["T", "R"],
    }


def test_spec_server_dicts_use_expected_server_names():
    assert constants.SPEC_T_server["server_name"] == "SPEC_T"
    assert constants.SPEC_R_server["server_name"] == "SPEC_R"


def test_specsrv_map_wires_servers():
    assert constants.SPECSRV_MAP["T_UVVIS"] == [constants.SPEC_T_server]
    assert constants.SPECSRV_MAP["DR_UVVIS"] == [constants.SPEC_R_server]
    assert constants.SPECSRV_MAP["TR_UVVIS"] == [
        constants.SPEC_T_server,
        constants.SPEC_R_server,
    ]


def test_constants_uses_framework_machine_model():
    # Importing constants must pull MachineModel from the framework package.
    import helao.framework.support.constants as mod
    import inspect

    src = inspect.getsource(mod)
    assert "helao.framework.models.machine" in src
    assert "helao.core" not in src
