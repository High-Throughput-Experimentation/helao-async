"""Tests for the operator's saved-parameter store.

Extracted from bokeh_operator so the Reflex operator can offer the same
"load last parameters" affordance rather than growing a second reader of the
same file. These drive it directly against a tmp root.
"""

import json
import os

from helao.core.servers.operator import param_store as ps


def _root(tmp_path):
    return str(tmp_path)


def test_params_path_is_under_states(tmp_path):
    path = ps.params_path(_root(tmp_path))
    assert path.endswith(os.path.join("STATES", "previous_params.json"))


def test_read_params_on_a_missing_file_is_empty(tmp_path):
    assert ps.read_params(_root(tmp_path), "seq", "seq_a") == {}


def test_write_then_read_round_trips(tmp_path):
    root = _root(tmp_path)
    ps.write_params(root, "seq", "seq_a", {"alpha": 3})
    assert ps.read_params(root, "seq", "seq_a") == {"alpha": 3}


def test_write_does_not_create_the_file_until_asked(tmp_path):
    """Reading must not leave a file behind: the store lives under the config
    root, which on a station is the instrument's data tree."""
    root = _root(tmp_path)
    ps.read_params(root, "seq", "seq_a")
    assert not os.path.exists(ps.params_path(root))


def test_write_keeps_the_other_kind(tmp_path):
    root = _root(tmp_path)
    ps.write_params(root, "seq", "seq_a", {"alpha": 1})
    ps.write_params(root, "exp", "exp_a", {"beta": 2})
    assert ps.read_params(root, "seq", "seq_a") == {"alpha": 1}
    assert ps.read_params(root, "exp", "exp_a") == {"beta": 2}


def test_write_replaces_the_entry_for_one_name(tmp_path):
    root = _root(tmp_path)
    ps.write_params(root, "seq", "seq_a", {"alpha": 1})
    ps.write_params(root, "seq", "seq_a", {"alpha": 9})
    assert ps.read_params(root, "seq", "seq_a") == {"alpha": 9}


def test_write_keeps_other_names_of_the_same_kind(tmp_path):
    root = _root(tmp_path)
    ps.write_params(root, "seq", "seq_a", {"alpha": 1})
    ps.write_params(root, "seq", "seq_b", {"alpha": 2})
    assert ps.read_params(root, "seq", "seq_a") == {"alpha": 1}


def test_last_meta_round_trips(tmp_path):
    root = _root(tmp_path)
    meta = {"sequence_label": "L", "campaign_name": "C", "campaign_uuid": "U"}
    ps.write_params(root, "seq", "seq_a", {}, meta=meta)
    assert ps.read_last_meta(root) == meta


def test_last_meta_is_empty_without_a_file(tmp_path):
    assert ps.read_last_meta(_root(tmp_path)) == {}


def test_write_without_meta_leaves_the_previous_meta(tmp_path):
    """Saving a sequence's parameters must not wipe the label and campaign the
    operator set earlier."""
    root = _root(tmp_path)
    meta = {"sequence_label": "L", "campaign_name": "C", "campaign_uuid": ""}
    ps.write_params(root, "seq", "seq_a", {}, meta=meta)
    ps.write_params(root, "exp", "exp_a", {})
    assert ps.read_last_meta(root) == meta


def test_a_corrupt_file_reads_as_empty_rather_than_raising(tmp_path):
    """Half a JSON file is a real outcome of a station losing power mid-write.
    Raising here takes down the callback and the operator loses the button."""
    root = _root(tmp_path)
    path = ps.params_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf8") as handle:
        handle.write('{"seq": {"seq_a": {"alpha"')
    assert ps.read_params(root, "seq", "seq_a") == {}
    assert ps.read_last_meta(root) == {}


def test_a_corrupt_file_is_replaced_by_the_next_write(tmp_path):
    root = _root(tmp_path)
    path = ps.params_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf8") as handle:
        handle.write("not json")
    assert ps.write_params(root, "seq", "seq_a", {"alpha": 1}) is True
    assert ps.read_params(root, "seq", "seq_a") == {"alpha": 1}


def test_a_file_holding_a_list_reads_as_empty(tmp_path):
    """Valid JSON of the wrong shape: .get would raise AttributeError."""
    root = _root(tmp_path)
    path = ps.params_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf8") as handle:
        json.dump([1, 2, 3], handle)
    assert ps.read_params(root, "seq", "seq_a") == {}


def test_write_without_a_root_is_refused_rather_than_raising(tmp_path):
    """A config with no `root` is a UI-only server. Persisting is not possible
    and must not take down the enqueue that triggered it."""
    assert ps.write_params("", "seq", "seq_a", {"alpha": 1}) is False
    assert ps.read_params("", "seq", "seq_a") == {}


def test_write_refuses_an_unknown_kind(tmp_path):
    root = _root(tmp_path)
    assert ps.write_params(root, "nonsense", "x", {"a": 1}) is False
    assert not os.path.exists(ps.params_path(root))


def test_read_refuses_an_unknown_kind(tmp_path):
    assert ps.read_params(_root(tmp_path), "nonsense", "x") == {}


def test_params_are_stringified_for_the_form(tmp_path):
    """The Reflex form's values are all strings; a saved int must come back in
    a form the inputs can hold."""
    root = _root(tmp_path)
    ps.write_params(root, "seq", "seq_a", {"alpha": 3, "beta": [1, 2], "c": None})
    values = ps.form_values(ps.read_params(root, "seq", "seq_a"))
    assert values == {"alpha": "3", "beta": "[1, 2]", "c": "None"}


def test_form_values_on_nothing_is_empty():
    assert ps.form_values({}) == {}
    assert ps.form_values(None) == {}
