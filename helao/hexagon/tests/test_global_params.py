"""Fold-in/fold-out semantics of ``helao/hexagon/app/orch_global_params.py``."""

from helao.helpers.global_exports import resolve_global_exports
from helao.hexagon.app.orch_global_params import (
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


def test_collect_to_globals_list_form_output_precedes_params():
    g = {}
    collect_to_globals(
        _result_action(["x", "y", "shared", "absent"]),
        g,
        orch_key="ORCH",
        orch_host="127.0.0.1",
        orch_port=8001,
    )
    assert g == {"x": 1, "y": 2, "shared": "from_output"}


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


def test_resolver_prefers_output_and_renames():
    assert resolve_global_exports(
        {"k": "renamed", "only_p": "p2"},
        {"k": "stale_input", "only_p": 1},
        {"k": "result"},
    ) == {"renamed": "result", "p2": 1}


def test_resolver_ignores_missing_and_bad_shapes():
    assert resolve_global_exports(["absent"], {}, {}) == {}
    assert resolve_global_exports(None, {"a": 1}, {}) == {}
