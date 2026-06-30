"""Unit tests for the OrchBackend port (abstract seam)."""
import inspect

import pytest

from helao.framework.ports.operator_backend import OrchBackend


def test_orchbackend_is_abstract():
    with pytest.raises(TypeError):
        OrchBackend()  # abstract — cannot instantiate


def test_orchbackend_method_surface():
    expected = {
        "unpack_sequence", "get_step_flags", "set_step_flag", "list_sequences",
        "list_experiments", "list_actions", "get_queue_object", "get_histories",
        "get_status_summary", "get_orch_state", "add_sequence", "add_split_sequences",
        "prepend_sequences", "move_sequence", "remove_sequence",
        "move_experiment", "remove_experiment", "move_action", "remove_action",
        "start", "stop",
        "skip", "estop", "clear_sequences", "clear_experiments", "clear_actions",
        "subscribe", "close",
    }
    members = {n for n, _ in inspect.getmembers(OrchBackend, predicate=callable)}
    assert expected <= members


def test_port_is_pure():
    src = inspect.getsource(OrchBackend.__module__ and __import__(
        "helao.framework.ports.operator_backend", fromlist=["x"]))
    text = inspect.getsource(__import__(
        "helao.framework.ports.operator_backend", fromlist=["x"]))
    for forbidden in ("helao.framework.adapters", "helao.helpers", "helao.core",
                      "import bokeh", "dispatcher", "ws_utils"):
        assert forbidden not in text, f"port imports forbidden: {forbidden}"
