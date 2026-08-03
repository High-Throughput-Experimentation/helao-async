"""Tests for the operator's spec-file layer.

The parser is loaded from a path in the config and belongs to a deployment, so
these drive a stub parser written to a tmp file -- which is also the only way
to prove the loader actually loads one.
"""

import os

from helao.core.servers.operator import spec_parser as sp

PARSER_SOURCE = '''
"""A stand-in for a deployment's spec parser."""

import os


class SpecParser:
    PARAM_TYPES = {"plate_id": int, "note": str, "missing": float}

    def lister(self, folder):
        return sorted(
            os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".txt")
        )

    def list_params(self, path, backend):
        return {"plate_id": None, "note": None}

    def parser(self, path, backend, params=None, **kwargs):
        return {"path": path, "params": params, "kwargs": kwargs}
'''


def _parser_file(tmp_path, source=PARSER_SOURCE, name="stub_parser.py"):
    path = tmp_path / name
    path.write_text(source)
    return str(path)


def _spec_folder(tmp_path):
    folder = tmp_path / "specs"
    folder.mkdir()
    (folder / "b.txt").write_text("b")
    (folder / "a.txt").write_text("a")
    (folder / "notes.md").write_text("ignored")
    return str(folder)


def test_no_parser_configured_is_none():
    """Opt-in: most stations have no spec parser and the tab must say so."""
    assert sp.load_parser(None) is None
    assert sp.load_parser("") is None


def test_a_parser_path_that_does_not_exist_is_none(tmp_path):
    assert sp.load_parser(str(tmp_path / "nope.py")) is None


def test_load_parser_imports_the_deployment_parser(tmp_path):
    parser = sp.load_parser(_parser_file(tmp_path))
    assert parser is not None
    assert hasattr(parser, "parser")


def test_load_parser_caches_the_module(tmp_path):
    """Loading executes a module; a per-session reload would re-run its
    import side effects on every operator tab."""
    path = _parser_file(tmp_path)
    sp.clear_parser_cache()
    first = sp.load_parser(path)
    second = sp.load_parser(path)
    assert type(first) is type(second)


def test_a_parser_module_that_raises_is_none(tmp_path):
    """A broken parser must disable the tab, not take down the page."""
    path = _parser_file(tmp_path, "raise RuntimeError('boom')\n", "broken.py")
    sp.clear_parser_cache()
    assert sp.load_parser(path) is None


def test_a_module_without_a_specparser_class_is_none(tmp_path):
    path = _parser_file(tmp_path, "X = 1\n", "empty.py")
    sp.clear_parser_cache()
    assert sp.load_parser(path) is None


def test_spec_files_lists_only_what_the_parser_claims(tmp_path):
    parser = sp.load_parser(_parser_file(tmp_path))
    files = sp.spec_files(parser, _spec_folder(tmp_path))
    assert [os.path.basename(f) for f in files] == ["a.txt", "b.txt"]


def test_spec_files_without_a_folder_is_empty(tmp_path):
    parser = sp.load_parser(_parser_file(tmp_path))
    assert sp.spec_files(parser, None) == []
    assert sp.spec_files(parser, str(tmp_path / "nope")) == []


def test_spec_files_without_a_parser_is_empty(tmp_path):
    assert sp.spec_files(None, _spec_folder(tmp_path)) == []


def test_spec_files_survives_a_parser_that_raises(tmp_path):
    class Angry:
        def lister(self, folder):
            raise RuntimeError("nope")

    assert sp.spec_files(Angry(), _spec_folder(tmp_path)) == []


def test_spec_fields_are_the_declared_types_the_file_actually_uses(tmp_path):
    """PARAM_TYPES declares every parameter the parser understands;
    list_params says which ones this file needs. Prompting for the rest would
    ask the operator for values the spec has no use for."""
    parser = sp.load_parser(_parser_file(tmp_path))
    folder = _spec_folder(tmp_path)
    fields = sp.spec_fields(parser, os.path.join(folder, "a.txt"), backend=None)
    assert [f["name"] for f in fields] == ["plate_id", "note"]
    assert [f["kind"] for f in fields] == ["number", "text"]


def test_spec_fields_have_no_defaults(tmp_path):
    """Spec parameters are required; the Bokeh panel calls them 'Required
    sequence parameters' and starts them empty."""
    parser = sp.load_parser(_parser_file(tmp_path))
    folder = _spec_folder(tmp_path)
    fields = sp.spec_fields(parser, os.path.join(folder, "a.txt"), backend=None)
    assert all(f["default"] == "" for f in fields)


def test_spec_fields_survive_a_parser_that_cannot_read_the_file(tmp_path):
    class Angry:
        PARAM_TYPES = {"a": int}

        def list_params(self, path, backend):
            raise ValueError("bad spec")

    assert sp.spec_fields(Angry(), "x.txt", backend=None) == []


def test_spec_fields_without_a_parser_is_empty():
    assert sp.spec_fields(None, "x.txt", backend=None) == []


def test_build_spec_sequence_passes_params_and_kwargs(tmp_path):
    parser = sp.load_parser(_parser_file(tmp_path))
    built, error = sp.build_spec_sequence(
        parser, "spec.txt", backend=None, params={"plate_id": 6284}, kwargs={"k": 1}
    )
    assert error == ""
    assert built["params"] == {"plate_id": 6284}
    assert built["kwargs"] == {"k": 1}


def test_build_spec_sequence_reports_a_parser_failure(tmp_path):
    class Angry:
        def parser(self, path, backend, params=None, **kwargs):
            raise ValueError("spec is malformed")

    built, error = sp.build_spec_sequence(Angry(), "spec.txt", None, {}, {})
    assert built is None
    assert "malformed" in error


def test_build_spec_sequence_without_a_parser(tmp_path):
    built, error = sp.build_spec_sequence(None, "spec.txt", None, {}, {})
    assert built is None
    assert "no spec parser" in error


def test_build_spec_sequence_refuses_an_empty_spec_file(tmp_path):
    parser = sp.load_parser(_parser_file(tmp_path))
    built, error = sp.build_spec_sequence(parser, "", None, {}, {})
    assert built is None
    assert "no specification file" in error
