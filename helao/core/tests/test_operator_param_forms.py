"""Tests for the operator's pure parameter-form logic.

Extracted from bokeh_operator so the Reflex operator can share it rather than
grow a second docstring parser that drifts. These test it directly; the Bokeh
operator's own suite reaches it only through UI callbacks.
"""

from pydantic import BaseModel

from helao.core.servers.operator import param_forms as pf


def test_parse_arg_docs_reads_a_plain_args_section():
    doc = "Summary.\n\nArgs:\n    alpha: first thing\n    beta: second thing\n"
    assert pf.parse_arg_docs(doc) == {"alpha": "first thing", "beta": "second thing"}


def test_parse_arg_docs_accepts_a_type_in_parentheses():
    doc = "Args:\n    alpha (int): a count\n"
    assert pf.parse_arg_docs(doc) == {"alpha": "a count"}


def test_parse_arg_docs_folds_continuation_lines():
    doc = "Args:\n    alpha: first line\n        second line\n"
    assert pf.parse_arg_docs(doc)["alpha"] == "first line second line"


def test_parse_arg_docs_stops_at_the_next_section():
    doc = "Args:\n    alpha: a thing\nReturns:\n    something else\n"
    assert set(pf.parse_arg_docs(doc)) == {"alpha"}


def test_parse_arg_docs_stops_at_a_blank_line():
    doc = "Args:\n    alpha: a thing\n\n    beta: not an arg\n"
    assert set(pf.parse_arg_docs(doc)) == {"alpha"}


def test_parse_arg_docs_skips_varargs():
    doc = "Args:\n    alpha: kept\n    *args: ignored\n    **kwargs: ignored\n"
    assert set(pf.parse_arg_docs(doc)) == {"alpha"}


def test_parse_arg_docs_on_no_docstring_is_empty():
    assert pf.parse_arg_docs("") == {}
    assert pf.parse_arg_docs(None) == {}


def test_version_hint_parts_includes_version_and_codehash():
    assert pf.version_hint_parts({"version": 2, "codehash": "abc"}) == ["v2", "abc"]


def test_version_hint_parts_omits_what_is_absent():
    assert pf.version_hint_parts({"version": 1}) == ["v1"]
    assert pf.version_hint_parts({"codehash": "abc"}) == ["abc"]
    assert pf.version_hint_parts({}) == []


def test_version_hint_parts_does_not_escape():
    """Escaping belongs to the Bokeh UI, which renders these into a Div. The
    Reflex operator renders them as text, where markup would be visible."""
    assert pf.version_hint_parts({"codehash": "a&b"}) == ["a&b"]


class _Item(BaseModel):
    """Minimal stand-in for the operator's return_sequence_lib model."""

    index: int
    sequence_name: str
    doc: str
    args: tuple
    defaults: tuple
    argtypes: tuple
    version: object = None
    codehash: object = None


def _lib(**funcs):
    return dict(funcs)


def test_build_lib_introspects_args_and_defaults():
    def seq_a(alpha: int = 3, beta: str = "x"):
        """Docstring.

        Args:
            alpha: a count
        """

    items, names = pf.build_lib(
        _lib(seq_a=seq_a),
        filter_type=None,
        config_key="sequence_params",
        world_cfg={},
        loaded_config_path="/cfg/a.yml",
        model_class=_Item,
        name_field="sequence_name",
    )
    assert names == ["seq_a"]
    assert items[0]["args"] == ("alpha", "beta")
    assert items[0]["defaults"] == (3, "x")


def test_build_lib_drops_the_framework_injected_parameter():
    """Experiment functions take an Experiment the operator must not prompt for."""

    class Marker:
        pass

    def exp_a(experiment: Marker, alpha: int = 1):
        """d"""

    items, _ = pf.build_lib(
        _lib(exp_a=exp_a),
        filter_type=Marker,
        config_key="experiment_params",
        world_cfg={},
        loaded_config_path="/cfg/b.yml",
        model_class=_Item,
        name_field="sequence_name",
    )
    assert items[0]["args"] == ("alpha",)


def test_build_lib_overlays_config_defaults():
    def seq_a(alpha: int = 3):
        """d"""

    items, _ = pf.build_lib(
        _lib(seq_a=seq_a),
        filter_type=None,
        config_key="sequence_params",
        world_cfg={"sequence_params": {"alpha": 99}},
        loaded_config_path="/cfg/c.yml",
        model_class=_Item,
        name_field="sequence_name",
    )
    assert items[0]["defaults"] == (99,)


def test_build_lib_caches_on_the_loaded_config_path():
    """The cache key carries the config path, so two configs in one process do
    not serve each other's defaults."""

    def seq_a(alpha: int = 1):
        """d"""

    common = dict(
        filter_type=None,
        config_key="sequence_params",
        model_class=_Item,
        name_field="sequence_name",
    )
    first, _ = pf.build_lib(
        _lib(seq_a=seq_a),
        world_cfg={"sequence_params": {"alpha": 11}},
        loaded_config_path="/cfg/one.yml",
        **common,
    )
    second, _ = pf.build_lib(
        _lib(seq_a=seq_a),
        world_cfg={"sequence_params": {"alpha": 22}},
        loaded_config_path="/cfg/two.yml",
        **common,
    )
    assert first[0]["defaults"] == (11,)
    assert second[0]["defaults"] == (22,)


def test_build_lib_returns_copies_so_a_caller_cannot_poison_the_cache():
    def seq_a(alpha: int = 1):
        """d"""

    args = dict(
        filter_type=None,
        config_key="sequence_params",
        world_cfg={},
        loaded_config_path="/cfg/d.yml",
        model_class=_Item,
        name_field="sequence_name",
    )
    first, names = pf.build_lib(_lib(seq_a=seq_a), **args)
    first[0]["doc"] = "MUTATED"
    names.append("bogus")
    second, names2 = pf.build_lib(_lib(seq_a=seq_a), **args)
    assert second[0]["doc"] != "MUTATED"
    assert names2 == ["seq_a"]
