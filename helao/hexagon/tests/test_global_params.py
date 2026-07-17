"""Fold-in/fold-out semantics (orch_global_params.py, byte-identical port)."""

from helao.hexagon.domain.global_params import (
    apply_from_globals,
    collect_to_globals,
)
from helao.hexagon.domain.models import Action


def test_apply_from_globals_scalar_and_list_mapping():
    params = {}
    apply_from_globals(
        params,
        {"gk1": "pk1", "gk2": ["pk2a", "pk2b"], "missing": "pk3"},
        {"gk1": 11, "gk2": 22},
        logger_ctx="action",
    )
    # scalar mapping: params[v] = global[k]; list: fan out to every name
    assert params == {"pk1": 11, "pk2a": 22, "pk2b": 22}
    # missing global key skipped, target never created
    assert "pk3" not in params


def _result_action(to_global, **identity):
    act = Action(
        action_name="a",
        action_params={"x": 1, "shared": "from_params"},
        action_output={"y": 2, "shared": "from_output"},
        to_global_params=to_global,
    )
    act.orch_key = identity.get("orch_key", "ORCH")
    act.orch_host = identity.get("orch_host", "127.0.0.1")
    act.orch_port = identity.get("orch_port", 8001)
    return act


def test_collect_to_globals_list_form_params_precede_output():
    g = {}
    collect_to_globals(
        _result_action(["x", "y", "shared", "absent"]),
        g,
        orch_key="ORCH",
        orch_host="127.0.0.1",
        orch_port=8001,
    )
    assert g == {"x": 1, "y": 2, "shared": "from_params"}


def test_collect_to_globals_dict_form_renames():
    g = {}
    collect_to_globals(
        _result_action({"x": "renamed_x", "y": "renamed_y"}),
        g,
        orch_key="ORCH",
        orch_host="127.0.0.1",
        orch_port=8001,
    )
    assert g == {"renamed_x": 1, "renamed_y": 2}


def test_collect_to_globals_identity_guard_blocks_foreign_orch():
    g = {}
    collect_to_globals(
        _result_action(["x"], orch_key="OTHER"),
        g,
        orch_key="ORCH",
        orch_host="127.0.0.1",
        orch_port=8001,
    )
    assert g == {}


def test_collect_to_globals_port_compare_is_int():
    g = {}
    collect_to_globals(
        _result_action(["x"], orch_port="8001"),  # str port on the action
        g,
        orch_key="ORCH",
        orch_host="127.0.0.1",
        orch_port=8001,
    )
    assert g == {"x": 1}  # int(...) comparison verbatim from legacy
