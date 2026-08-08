"""P7h: the browser's filesystem port walks and reads exactly as the modules do.

Q8 listed ``readers`` as pure logic; measured, it is the browser's only
fs-touching module (``open()`` and ``zipfile.ZipFile`` at ``readers.py:49-52``)
and ``state.load_selected`` reaches the filesystem *through* it
(``state.py:112``). ``sources`` is a 386-line tree walk. So one port covers both
faces, and these tests drive it over a real run tree on disk -- a mock cannot
reproduce a zip member, a half-written YAML, or a file that is indexed but not
present.
"""

import json
import os
import zipfile

import pytest
import yaml

from helao.core.models.run_dir import RunDir
from helao.core.servers.data_browser import readers, sources
from helao.core.servers.data_browser import state as dbstate
from helao.hexagon.adapters.vis.browser_source import BrowserSource
from helao.hexagon.ports.browser_source import BrowserSourcePort
from helao.hexagon.tests.mirror_pin import module_functions, protocol_members


@pytest.fixture
def port() -> BrowserSourcePort:
    return BrowserSource()


def _write_hlo(path):
    """Minimal HLO file: YAML header, ``%%`` marker, JSONL body."""
    with open(path, "w") as fh:
        fh.write("hlo_version: 1.0\n")
        fh.write("action_name: cv\n")
        fh.write("column_headings: [t_s, Ewe_V]\n")
        fh.write("%%\n")
        fh.write(json.dumps({"t_s": 0.0, "Ewe_V": 0.1}) + "\n")
        fh.write(json.dumps({"t_s": 1.0, "Ewe_V": 0.2}) + "\n")


@pytest.fixture
def run_tree(tmp_path) -> str:
    """A RUNS_FINISHED tree: one sequence, one experiment, one action, one file."""
    day = tmp_path / "RUNS_FINISHED" / "26.30" / "0801"
    seq = day / "120000__seq--cv__label"
    exp = seq / "260801.120000__exp--cv"
    act = exp / "0__0__PSTAT__cv"
    act.mkdir(parents=True)
    with open(seq / "260801.120000000000-seq.yml", "w") as fh:
        yaml.safe_dump({"sequence_name": "cv", "run_type": "test"}, fh)
    with open(exp / "260801.120000000000-exp.yml", "w") as fh:
        yaml.safe_dump({"experiment_name": "cv"}, fh)
    with open(act / "260801.120000000000-act.yml", "w") as fh:
        yaml.safe_dump({"action_name": "cv", "technique_name": "cv"}, fh)
    _write_hlo(str(act / "cv_data.hlo"))
    return str(tmp_path)


# --- the drift pin -----------------------------------------------------------


def test_the_port_and_the_two_modules_declare_the_same_functions():
    """Set-equal both ways across the union of ``readers`` and ``sources``.

    The union is of functions each module *defines*: ``sources`` imports
    ``make_zip_locator`` from ``readers``, and counting the re-export would
    demand the name twice and make the surface depend on import order.
    """
    modules = module_functions(readers, sources)
    mirrored = protocol_members(BrowserSourcePort)
    assert modules == mirrored, {
        "in the modules only": sorted(modules - mirrored),
        "in the port only": sorted(mirrored - modules),
    }


def test_both_modules_actually_contribute_to_the_mirrored_surface():
    """Guards the pin above against covering one module and calling it a union.

    If ``sources`` grew a leading underscore on both its public functions the
    equality would still hold -- against half the boundary. Naming the split
    makes that visible.
    """
    assert module_functions(readers) == {
        "make_zip_locator",
        "parse_locator",
        "read_dataset",
    }
    assert module_functions(sources) == {"build_source_index", "get_index"}


def test_the_adapter_satisfies_the_port(port):
    assert isinstance(port, BrowserSourcePort)


# --- the walk face -----------------------------------------------------------


def test_the_walk_through_the_port_equals_the_module_walk(run_tree, port):
    """Frame-equal, not merely "both non-empty"."""
    via_port = port.get_index(run_tree, RunDir.FINISHED, None, None)
    via_module = sources.get_index(run_tree, RunDir.FINISHED, None, None)
    assert list(via_port.columns) == sources.INDEX_COLUMNS
    assert not via_port.empty
    assert via_port.to_dict("records") == via_module.to_dict("records")


def test_the_walk_finds_the_run_and_names_it(run_tree, port):
    """Non-vacuity for every equality above: assert the content, once."""
    rows = port.get_index(run_tree, RunDir.FINISHED, None, None).to_dict("records")
    assert len(rows) == 1
    row = rows[0]
    # The sequence name is extracted from its directory name; the experiment
    # keeps the whole directory name; the technique comes off the action yml.
    assert (row["sequence"], row["experiment"], row["technique"]) == (
        "seq--cv",
        "260801.120000__exp--cv",
        "cv",
    )
    assert row["file_name"] == "cv_data.hlo"
    assert row["file_type"] == "hlo"
    assert row["available"] is True
    assert row["date"] == "26.30/0801"


def test_a_date_range_scopes_the_walk_on_both_faces(run_tree, port):
    """Lexicographic ``YY.WW/MMDD``; ``None`` bounds open."""
    assert len(port.get_index(run_tree, RunDir.FINISHED, "26.30/0801", None)) == 1
    assert len(port.get_index(run_tree, RunDir.FINISHED, "26.31/0101", None)) == 0
    assert len(sources.get_index(run_tree, RunDir.FINISHED, "26.31/0101", None)) == 0


def test_build_source_index_returns_the_same_indexer_the_module_builds(run_tree, port):
    assert type(port.build_source_index(run_tree, RunDir.FINISHED)) is type(
        sources.build_source_index(run_tree, RunDir.FINISHED)
    )


# --- the read face -----------------------------------------------------------


def test_reading_a_loose_file_through_the_port_equals_the_module_read(run_tree, port):
    locator = port.get_index(run_tree, RunDir.FINISHED, None, None).iloc[0]["locator"]
    assert port.read_dataset(locator) == readers.read_dataset(locator)
    _, data = port.read_dataset(locator)
    assert data == {"t_s": [0.0, 1.0], "Ewe_V": [0.1, 0.2]}


def test_a_zip_member_round_trips_through_locator_and_read(tmp_path, port):
    """The locator format *is* the contract: build one, parse it, read it."""
    member_src = tmp_path / "cv_data.hlo"
    _write_hlo(str(member_src))
    zip_path = str(tmp_path / "run.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(str(member_src), "seq/exp/act/cv_data.hlo")

    locator = port.make_zip_locator(zip_path, "seq/exp/act/cv_data.hlo")
    assert locator == readers.make_zip_locator(zip_path, "seq/exp/act/cv_data.hlo")
    assert port.parse_locator(locator) == ("zip", zip_path, "seq/exp/act/cv_data.hlo")

    _, data = port.read_dataset(locator)
    assert data == {"t_s": [0.0, 1.0], "Ewe_V": [0.1, 0.2]}


def test_a_loose_path_parses_as_a_file_locator(port):
    assert port.parse_locator("/data/cv_data.hlo") == ("file", "/data/cv_data.hlo")


def test_the_format_override_beats_the_extension(tmp_path, port):
    """Analysis outputs are named after an S3 key, so the extension lies.

    Measured, dispatching on the extension alone does not fail loudly here --
    the HLO reader *succeeds* on this JSON and returns a different shape:
    ``note``, which is metadata, comes back as a one-element data column and
    the metadata dict is empty. A caller then plots a string column and finds
    no metadata, with nothing raised anywhere. That is why ``fmt`` exists and
    why it has to survive the seam.
    """
    path = str(tmp_path / "s3key.hlo")  # JSON content, .hlo name
    with open(path, "w") as fh:
        json.dump({"wl_nm": [400, 500], "abs": [0.1, 0.2], "note": "x"}, fh)

    meta, data = port.read_dataset(path, fmt="json")
    assert data == {"wl_nm": [400, 500], "abs": [0.1, 0.2]}
    assert meta == {"note": "x"}

    wrong_meta, wrong_data = port.read_dataset(path)  # no override: read as HLO
    assert wrong_meta == {}
    assert dict(wrong_data) == {
        "wl_nm": [400, 500],
        "abs": [0.1, 0.2],
        "note": ["x"],
    }


def test_an_unsupported_format_raises_through_the_port(tmp_path, port):
    """The one raise the browser boundary keeps, and it must reach the caller.

    ``state.load_selected`` catches it and turns it into a per-file "skipped"
    reason. An adapter that swallowed it would drop the file from the browser
    with nothing said.
    """
    path = str(tmp_path / "thing.bin")
    with open(path, "wb") as fh:
        fh.write(b"\x00\x01")
    with pytest.raises(ValueError, match="unsupported data format"):
        port.read_dataset(path)


# --- the two faces meet: the pure caller still works over the port ----------


def test_state_load_selected_consumes_what_the_port_walked(run_tree, port):
    """``state`` is the pure caller Q8 says it is -- prove it end to end.

    The index comes off the walk face, the datasets come off the read face, and
    ``state`` (a plain module, no port) is what joins them.
    """
    index = port.get_index(run_tree, RunDir.FINISHED, None, None)
    datasets, skipped = dbstate.load_selected(index.reset_index(drop=True), [0])
    assert skipped == []
    assert len(datasets) == 1
    assert datasets[0].data == {"t_s": [0.0, 1.0], "Ewe_V": [0.1, 0.2]}
    assert datasets[0].technique == "cv"


def test_a_file_that_is_indexed_but_gone_is_reported_not_dropped(run_tree, port):
    """Unavailability is a row, not an omission -- and a skip reason downstream."""
    index = port.get_index(run_tree, RunDir.FINISHED, None, None)
    os.remove(index.iloc[0]["locator"])
    datasets, skipped = dbstate.load_selected(index.reset_index(drop=True), [0])
    assert datasets == []
    assert len(skipped) == 1 and "read error" in skipped[0][1]
