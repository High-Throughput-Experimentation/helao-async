"""P7h: the saved-parameter port writes the same bytes the shared module does.

``previous_params.json`` is a cross-UI artifact -- one operator may write it
from Bokeh and another read it back from Reflex -- so the interesting property
is not "the adapter returns something plausible" but "the adapter and the
module are interchangeable over the same file". These tests write through one
face and read through the other, in both directions.
"""

import json
import os

import pytest

from helao.core.servers.operator import param_store as legacy
from helao.hexagon.adapters.vis.param_store import ParamStore
from helao.hexagon.ports.param_store import PARAM_KINDS, ParamStorePort
from helao.hexagon.tests.mirror_pin import module_functions, protocol_members


@pytest.fixture
def port() -> ParamStorePort:
    return ParamStore()


@pytest.fixture
def root(tmp_path) -> str:
    return str(tmp_path)


# --- the drift pin -----------------------------------------------------------


def test_the_port_and_the_module_declare_the_same_functions():
    """Set-equal both ways: a function added to either side alone fails."""
    module = module_functions(legacy)
    mirrored = protocol_members(ParamStorePort)
    assert module == mirrored, {
        "in the module only": sorted(module - mirrored),
        "in the port only": sorted(mirrored - module),
    }


def test_the_kinds_constant_is_mirrored_not_re_invented():
    """A third kind must not appear on one side only.

    ``kind`` is validated against this tuple in two places, and an unknown one
    is refused rather than raising. If the port's copy and the module's copy
    disagreed, a caller would write with a kind the store silently declines and
    read back ``{}`` forever, with a warning in a log nobody reads.
    """
    assert PARAM_KINDS == legacy.PARAM_KINDS == ("seq", "exp")


def test_the_adapter_satisfies_the_port(port):
    assert isinstance(port, ParamStorePort)


# --- the cross-face round trip ----------------------------------------------


def test_what_the_port_writes_the_module_reads(port, root):
    assert port.write_params(root, "seq", "cv", {"a": 1, "b": "two"}) is True
    assert legacy.read_params(root, "seq", "cv") == {"a": 1, "b": "two"}


def test_what_the_module_writes_the_port_reads(port, root):
    assert legacy.write_params(root, "exp", "measure", {"n": 3}) is True
    assert port.read_params(root, "exp", "measure") == {"n": 3}


def test_the_two_faces_produce_byte_identical_files(tmp_path):
    """Not just equal dicts -- equal bytes.

    A dict comparison would pass an adapter that reordered keys or changed the
    JSON separators, and the file is read by both UIs and by a human at a
    station. Two roots, the same writes, one ``read_bytes`` each.
    """
    via_port, via_module = str(tmp_path / "p"), str(tmp_path / "m")
    meta = {"label": "L", "campaign": "C"}
    ParamStore().write_params(via_port, "seq", "cv", {"a": 1}, meta)
    legacy.write_params(via_module, "seq", "cv", {"a": 1}, meta)

    with open(ParamStore().params_path(via_port), "rb") as fh:
        port_bytes = fh.read()
    with open(legacy.params_path(via_module), "rb") as fh:
        module_bytes = fh.read()
    assert port_bytes == module_bytes
    assert json.loads(port_bytes)["last_meta"] == meta


def test_the_port_locates_the_store_where_the_module_does(port, root):
    assert port.params_path(root) == legacy.params_path(root)
    assert port.params_path(root).endswith(
        os.path.join("STATES", "previous_params.json")
    )


# --- the two clauses the seam carries ---------------------------------------


def test_a_read_through_the_port_does_not_create_the_store(port, root):
    """Opening the operator must not write into an instrument's data tree."""
    assert port.read_params(root, "seq", "cv") == {}
    assert port.read_last_meta(root) == {}
    assert not os.path.exists(os.path.join(root, "STATES"))


def test_a_half_written_store_reads_empty_rather_than_raising(port, root):
    """A station losing power mid-write is a real outcome, not a hypothetical.

    The read must degrade to "nothing remembered", because it runs while the
    operator page is being built: a raise here is a blank page.
    """
    path = port.params_path(root)
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf8") as fh:
        fh.write('{"seq": {"cv": {"a": 1')  # truncated mid-object

    assert port.read_params(root, "seq", "cv") == {}
    assert port.read_last_meta(root) == {}


def test_an_unwritable_save_reports_false_instead_of_failing_the_enqueue(port):
    """Saving runs *as part of* enqueueing, so it must not be able to fail it.

    An empty root is the UI-only-server case: nowhere to persist, nothing
    written, and the caller is told so rather than left to assume.
    """
    assert port.write_params("", "seq", "cv", {"a": 1}) is False


def test_an_unknown_kind_is_refused_on_both_faces(port, root):
    assert port.write_params(root, "nope", "cv", {"a": 1}) is False
    assert legacy.write_params(root, "nope", "cv", {"a": 1}) is False
    assert port.read_params(root, "nope", "cv") == {}


def test_omitting_meta_leaves_the_campaign_the_operator_set(port, root):
    """Saving a sequence's parameters must not wipe an earlier campaign."""
    port.write_params(root, "seq", "cv", {"a": 1}, {"campaign": "C"})
    port.write_params(root, "exp", "measure", {"n": 3})
    assert port.read_last_meta(root) == {"campaign": "C"}


def test_form_values_renders_saved_values_as_form_strings(port):
    """The Reflex operator's inputs are all strings and parse back on enqueue."""
    assert port.form_values({"n": 3, "xs": [1, 2]}) == {"n": "3", "xs": "[1, 2]"}
    assert port.form_values(None) == {}
