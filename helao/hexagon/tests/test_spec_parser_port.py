"""P7h: the spec-parser port carries the degrade contract, not just the calls.

``load_parser`` executes a file named by a config key -- deployment code this
repo never sees, run inside the operator process. The contract that matters is
therefore about *failure*: five distinct ways for a parser to be unusable, all
of which must disable the Specs tab rather than take down the page. Each one
gets its own test with a real file on disk, because a mock cannot fail the way
``exec_module`` does.
"""

import os

import pytest

from helao.core.servers.operator import spec_parser as legacy
from helao.hexagon.adapters.vis.spec_parser import SpecParserGateway
from helao.hexagon.ports.spec_parser import SpecParserPort
from helao.hexagon.tests.mirror_pin import module_functions, protocol_members

WORKING_PARSER = '''
"""A parser shaped like the contract, for tests only."""

import os


class SpecParser:
    PARAM_TYPES = {"cycles": int, "note": str, "unused": float}

    def lister(self, folder):
        return sorted(
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.endswith(".spec")
        )

    def list_params(self, path, backend):
        return {"cycles": None, "note": None}

    def parser(self, path, backend, params=None, **kwargs):
        return {"built_from": os.path.basename(path), "params": params}
'''

RAISES_ON_IMPORT = "raise RuntimeError('this deployment parser is broken')\n"
NO_SPEC_PARSER = "class SomethingElse:\n    pass\n"
UNCONSTRUCTABLE = (
    "class SpecParser:\n"
    "    def __init__(self):\n"
    "        raise ValueError('needs a config this station has not got')\n"
)
RAISES_WHEN_USED = (
    "class SpecParser:\n"
    "    PARAM_TYPES = {'cycles': int}\n"
    "    def lister(self, folder):\n"
    "        raise OSError('mount is gone')\n"
    "    def list_params(self, path, backend):\n"
    "        raise KeyError('cycles')\n"
    "    def parser(self, path, backend, params=None, **kwargs):\n"
    "        raise ValueError('line 3 of the spec is malformed')\n"
)


@pytest.fixture
def port() -> SpecParserPort:
    return SpecParserGateway()


@pytest.fixture(autouse=True)
def _fresh_parser_cache():
    """Loading a parser caches the module by path; tests write new ones."""
    legacy.clear_parser_cache()
    yield
    legacy.clear_parser_cache()


def _write(tmp_path, name, source) -> str:
    path = tmp_path / name
    path.write_text(source, encoding="utf8")
    return str(path)


# --- the drift pin -----------------------------------------------------------


def test_the_port_and_the_module_declare_the_same_functions():
    """Set-equal both ways: a function added to either side alone fails."""
    module = module_functions(legacy)
    mirrored = protocol_members(SpecParserPort)
    assert module == mirrored, {
        "in the module only": sorted(module - mirrored),
        "in the port only": sorted(mirrored - module),
    }


def test_the_adapter_satisfies_the_port(port):
    assert isinstance(port, SpecParserPort)


# --- the working path, so the degrade tests are not vacuously green ---------


def test_a_working_parser_lists_files_fields_and_builds_a_sequence(port, tmp_path):
    """Everything below returns empty on failure, so prove the non-empty case.

    Without this, a port that returned ``[]`` unconditionally would pass every
    other test in the file.
    """
    parser_path = _write(tmp_path, "specparser.py", WORKING_PARSER)
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "b.spec").write_text("", encoding="utf8")
    (specs / "a.spec").write_text("", encoding="utf8")
    (specs / "notes.txt").write_text("", encoding="utf8")

    parser = port.load_parser(parser_path)
    assert parser is not None

    files = port.spec_files(parser, str(specs))
    assert [os.path.basename(f) for f in files] == ["a.spec", "b.spec"]

    fields = port.spec_fields(parser, files[0], backend=None)
    # Only the intersection of PARAM_TYPES and list_params: "unused" is
    # declared but this file does not use it, so it is not prompted for.
    assert [f["name"] for f in fields] == ["cycles", "note"]
    assert [f["kind"] for f in fields] == ["number", "text"]
    assert all(f["default"] == "" for f in fields)

    sequence, error = port.build_spec_sequence(
        parser, files[0], None, {"cycles": 2}, {}
    )
    assert error == ""
    assert sequence == {"built_from": "a.spec", "params": {"cycles": 2}}


def test_the_port_and_the_module_agree_on_a_working_parser(port, tmp_path):
    """The two faces are interchangeable over the same parser file."""
    parser_path = _write(tmp_path, "specparser.py", WORKING_PARSER)
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "a.spec").write_text("", encoding="utf8")

    via_port = port.spec_files(port.load_parser(parser_path), str(specs))
    via_module = legacy.spec_files(legacy.load_parser(parser_path), str(specs))
    assert via_port == via_module != []


# --- the degrade contract: five ways to be unusable, none of them a raise ---


def test_no_parser_configured_is_none_not_a_raise(port):
    assert port.load_parser(None) is None
    assert port.load_parser("") is None


def test_a_missing_parser_file_is_none_not_a_raise(port, tmp_path):
    assert port.load_parser(str(tmp_path / "not_there.py")) is None


def test_a_parser_that_raises_while_importing_is_none_not_a_raise(port, tmp_path):
    """Deployment code runs at import. It failing must not reach the page."""
    assert port.load_parser(_write(tmp_path, "boom.py", RAISES_ON_IMPORT)) is None


def test_a_module_without_a_specparser_class_is_none_not_a_raise(port, tmp_path):
    assert port.load_parser(_write(tmp_path, "empty.py", NO_SPEC_PARSER)) is None


def test_a_specparser_that_cannot_be_constructed_is_none_not_a_raise(port, tmp_path):
    assert port.load_parser(_write(tmp_path, "ctor.py", UNCONSTRUCTABLE)) is None


def test_every_method_tolerates_no_parser_at_all(port):
    """The commonest station state: nothing configured, tab quietly absent."""
    assert port.spec_files(None, "/anywhere") == []
    assert port.spec_fields(None, "a.spec", None) == []
    sequence, error = port.build_spec_sequence(None, "a.spec", None, {}, {})
    assert sequence is None
    assert "no spec parser is configured" in error


def test_a_parser_that_raises_when_used_degrades_per_call(port, tmp_path):
    """Import succeeding does not mean the methods work; each is wrapped."""
    parser = port.load_parser(_write(tmp_path, "lame.py", RAISES_WHEN_USED))
    assert parser is not None
    assert port.spec_files(parser, str(tmp_path)) == []
    assert port.spec_fields(parser, "a.spec", None) == []


def test_a_failing_parse_reports_its_message_instead_of_swallowing_it(port, tmp_path):
    """The one place that does *not* degrade to silence.

    The spec file is the operator's own input, so "nothing happened" is
    unactionable -- the message names the file and carries the parser's own
    complaint.
    """
    parser = port.load_parser(_write(tmp_path, "lame.py", RAISES_WHEN_USED))
    sequence, error = port.build_spec_sequence(parser, "/specs/a.spec", None, {}, {})
    assert sequence is None
    assert "a.spec" in error
    assert "line 3 of the spec is malformed" in error


def test_no_file_selected_is_reported_rather_than_parsed(port, tmp_path):
    parser = port.load_parser(_write(tmp_path, "specparser.py", WORKING_PARSER))
    sequence, error = port.build_spec_sequence(parser, "", None, {}, {})
    assert sequence is None
    assert "no specification file is selected" in error


def test_absence_and_brokenness_are_indistinguishable_through_the_seam(port, tmp_path):
    """Recorded, not incidental -- and the reason Q10's answer is a gate test.

    A station cannot tell "no parser configured" from "the configured parser is
    broken": both are ``None`` and an empty Specs tab. Only something holding
    the *config* can distinguish them, which is why the gate lives in P7j and
    not here. Pinning it stops a later change from "improving" one branch into
    a raise on an instrument.
    """
    unconfigured = port.load_parser(None)
    broken = port.load_parser(_write(tmp_path, "boom.py", RAISES_ON_IMPORT))
    assert unconfigured is broken is None
    assert port.spec_files(unconfigured, str(tmp_path)) == port.spec_files(
        broken, str(tmp_path)
    )


def test_the_module_cache_is_shared_not_per_instance(port, tmp_path):
    """Loading a parser *runs* it, so two gateways must not import it twice.

    A per-instance cache would re-run a deployment's import side effects on
    every operator tab -- the thing the module-level cache exists to prevent.
    """
    counter = tmp_path / "imports.txt"
    source = (
        "with open(%r, 'a') as fh:\n"
        "    fh.write('x')\n"
        "class SpecParser:\n"
        "    PARAM_TYPES = {}\n" % str(counter)
    )
    parser_path = _write(tmp_path, "counted.py", source)

    SpecParserGateway().load_parser(parser_path)
    SpecParserGateway().load_parser(parser_path)
    legacy.load_parser(parser_path)
    assert counter.read_text() == "x"

    port.clear_parser_cache()
    SpecParserGateway().load_parser(parser_path)
    assert counter.read_text() == "xx"
