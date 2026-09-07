"""Reading and patching EC-Lab .mps settings text.

.mps is the only way parameters reach a channel: LoadSettings takes a file
path and nothing in the OLE COM API builds a technique from arguments. So a
wrong substitution here is a wrong experiment on a real cell, with no error
from either EC-Lab or the API -- which is why this module is pure text with no
COM dependency, and why it is the most heavily tested unit in the package.

Most of these run against two **real GUI-authored files** rather than a
synthetic fixture. That matters: every one of the format's traps -- CRLF, the
latin-1 superscripts, a value containing a space, header lines shaped like
parameter rows, a caption repeated four times in one block -- was found by
running an earlier version of this parser over them, not by reading the
vendor manual.
"""

import io
from pathlib import Path

import pytest

from helao.deploy.hte.drivers.pstat.biologic_ole import mps_template as mt

FIXTURES = Path("helao/deploy/hte/tests/fixtures/ole")
CV = FIXTURES / "CV.mps"  # real: one Cyclic Voltammetry technique
TI_CV_TO = FIXTURES / "TI_CV_TO.mps"  # real: Trigger In, CV, Trigger Out
SYNTHETIC = FIXTURES / "synthetic_CA.mps"  # two sequence columns; see below


@pytest.fixture
def cv() -> mt.MpsDocument:
    return mt.load(CV)


@pytest.fixture
def triggered() -> mt.MpsDocument:
    return mt.load(TI_CV_TO)


@pytest.fixture
def doc() -> mt.MpsDocument:
    """The synthetic two-sequence CA file.

    Kept alongside the real ones because neither real file has a
    multi-sequence technique, and column indexing has to be covered.
    """
    return mt.load(SYNTHETIC)


# -- encoding and round-trip ------------------------------------------------


@pytest.mark.parametrize("path", [CV, TI_CV_TO])
def test_a_real_file_round_trips_byte_for_byte(path):
    """The whole patcher rests on this. CRLF and latin-1 both matter."""
    assert mt.render(mt.load(path)).encode(mt.ENCODING) == path.read_bytes()


@pytest.mark.parametrize("path", [CV, TI_CV_TO])
def test_the_real_files_are_not_utf8(path):
    """0xB2/0xB3 -- the superscripts in `0.001 cm²` and `0.001 cm³`."""
    with pytest.raises(UnicodeDecodeError):
        path.read_bytes().decode("utf-8")


@pytest.mark.parametrize("path", [CV, TI_CV_TO])
def test_the_real_files_use_crlf(path):
    raw = path.read_bytes()
    assert raw.count(b"\r\n") == raw.count(b"\n") > 0


def test_universal_newline_translation_would_break_the_round_trip():
    """Pins why load() passes newline="": the default silently rewrites CRLF.

    Without this test the bug reappears the moment someone simplifies load()
    back to Path.read_text(), and it fails nowhere visible -- the patched file
    just stops matching the one EC-Lab wrote.
    """
    with io.open(CV, "r", encoding=mt.ENCODING) as handle:  # newline=None
        translated = handle.read()
    assert mt.render(mt.loads(translated)).encode(mt.ENCODING) != CV.read_bytes()


def test_write_patched_preserves_crlf_and_high_bytes(tmp_path):
    dest = tmp_path / "out.mps"
    mt.write_patched(mt.load(CV), dest)
    assert dest.read_bytes() == CV.read_bytes()


# -- technique blocks -------------------------------------------------------


def test_a_single_technique_file_has_one_block(cv):
    blocks = mt.technique_blocks(cv)
    assert [b.name for b in blocks] == ["Cyclic Voltammetry"]
    assert mt.n_techniques(cv) == 1


def test_the_triggered_file_has_three_blocks_in_order(triggered):
    assert [b.name for b in mt.technique_blocks(triggered)] == [
        "Trigger In",
        "Cyclic Voltammetry",
        "Trigger Out",
    ]


def test_a_header_line_shaped_like_a_row_is_not_one(cv):
    """`Reference electrode : SCE ...` passes a naive column test.

    It is 19 characters, then a space at column 19 and a colon at 20 -- so an
    unscoped parser reads it as a row with seven columns, and n_sequences
    returns 7 for a single-sequence file.
    """
    with pytest.raises(mt.MpsParameterNotFound):
        mt.get_param(cv, "Reference electrode")
    with pytest.raises(mt.MpsParameterNotFound):
        mt.get_param(cv, "Characteristic mass")


def test_n_sequences_is_one_for_the_real_single_sequence_files(cv, triggered):
    assert mt.n_sequences(cv) == 1
    assert mt.n_sequences(triggered) == 1


# -- reading values ---------------------------------------------------------


def test_the_cv_vertices_read_back(cv):
    assert mt.get_param(cv, "Ei (V)") == "0.000"
    assert mt.get_param(cv, "E1 (V)") == "1.000"
    assert mt.get_param(cv, "E2 (V)") == "-1.000"
    assert mt.get_param(cv, "Ef (V)") == "0.000"


def test_the_scan_rate_is_a_magnitude_and_a_unit_row(cv):
    assert mt.get_param(cv, "dE/dt") == "20.000"
    assert mt.get_param(cv, "dE/dt unit") == "mV/s"


def test_bandwidth_reads_back_as_a_bare_integer(cv):
    assert mt.get_param(cv, "Bandwidth") == "8"


def test_a_label_containing_spaces_is_matched_whole(cv):
    """`E range min (V)` must not be confused with `E range max (V)`."""
    assert mt.get_param(cv, "E range min (V)") == "-2.500"
    assert mt.get_param(cv, "E range max (V)") == "2.500"


def test_a_value_containing_a_space_is_one_value_not_two_columns(triggered):
    """`Trigger  Rising Edge`. Splitting on whitespace yields two columns."""
    assert mt.get_param(triggered, "Trigger", technique=0) == "Rising Edge"
    assert mt.n_sequences(triggered, technique=0) == 1


# -- duplicate captions -----------------------------------------------------


def test_a_caption_repeated_within_one_block_needs_an_occurrence(cv):
    """Cyclic Voltammetry has four `vs.` rows, one per vertex."""
    assert [mt.get_param(cv, "vs.", occurrence=k) for k in range(4)] == [
        "Eoc",
        "Ref",
        "Ref",
        "Eoc",
    ]


def test_asking_past_the_last_occurrence_says_how_many_there_are(cv):
    with pytest.raises(mt.MpsParameterNotFound, match="occurs 4"):
        mt.get_param(cv, "vs.", occurrence=4)


def test_a_caption_repeated_across_blocks_is_selected_by_technique(triggered):
    """`Trigger` is in both the Trigger In and Trigger Out blocks."""
    assert mt.get_param(triggered, "Channel", technique=0) == "-1"
    assert mt.get_param(triggered, "td (h:m:s)", technique=2) == "0:00:0.0010"
    with pytest.raises(mt.MpsParameterNotFound, match="technique 0"):
        mt.get_param(triggered, "td (h:m:s)", technique=0)


def test_patching_without_a_technique_scope_hits_the_first_block(triggered):
    """Documented, not accidental -- and why the driver always passes one."""
    patched = mt.set_param(triggered, "Trigger", "Falling Edge")
    assert mt.get_param(patched, "Trigger", technique=0) == "Falling Edge"
    assert mt.get_param(patched, "Trigger", technique=2) == "Rising Edge"


def test_patching_a_scoped_row_leaves_its_namesakes_alone(triggered):
    patched = mt.set_param(triggered, "Trigger", "Falling Edge", technique=2)
    assert mt.get_param(patched, "Trigger", technique=0) == "Rising Edge"
    assert mt.get_param(patched, "Trigger", technique=2) == "Falling Edge"


# -- patching ---------------------------------------------------------------


def test_setting_a_parameter_changes_only_that_value(cv):
    patched = mt.set_param(cv, "E1 (V)", "0.750")
    assert mt.get_param(patched, "E1 (V)") == "0.750"
    assert mt.get_param(patched, "E2 (V)") == "-1.000"
    assert mt.get_param(patched, "Bandwidth") == "8"


def test_patching_changes_exactly_one_line_and_no_others(cv):
    before = mt.render(cv).splitlines()
    after = mt.render(mt.set_param(cv, "E1 (V)", "0.750")).splitlines()
    differing = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(differing) == 1
    assert len(before) == len(after)


def test_a_patched_row_keeps_its_trailing_padding(cv):
    """EC-Lab pads the value column to 20. rstrip breaks byte-identity."""
    patched = mt.set_param(cv, "E1 (V)", "0.750")
    line = [l for l in patched.lines if l.startswith("E1 (V)")][0]
    assert line.rstrip("\r\n") == "E1 (V)".ljust(20) + "0.750".ljust(20)


def test_a_same_width_patch_preserves_the_file_length(cv):
    patched = mt.set_param(cv, "E1 (V)", "0.750")
    assert len(mt.render(patched)) == len(mt.render(cv))


def test_the_document_is_immutable(cv):
    before = mt.render(cv)
    mt.set_param(cv, "E1 (V)", "0.750")
    assert mt.render(cv) == before


def test_an_absent_parameter_names_itself(cv):
    with pytest.raises(mt.MpsParameterNotFound, match="Nonesuch"):
        mt.get_param(cv, "Nonesuch")


def test_a_caption_longer_than_the_label_field_is_refused(cv):
    with pytest.raises(mt.MpsParameterNotFound, match="20-column"):
        mt.set_param(cv, "a" * 21, "1")


# -- multiple sequence columns ---------------------------------------------


def test_a_multi_sequence_parameter_reads_the_requested_column(doc):
    assert mt.get_param(doc, "Ei (V)", seq=0) == "0.000"
    assert mt.get_param(doc, "Ei (V)", seq=1) == "0.500"


def test_setting_one_sequence_leaves_the_other_alone(doc):
    patched = mt.set_param(doc, "Ei (V)", "1.250", seq=1)
    assert mt.get_param(patched, "Ei (V)", seq=0) == "0.000"
    assert mt.get_param(patched, "Ei (V)", seq=1) == "1.250"


def test_a_column_beyond_the_row_is_refused(doc):
    with pytest.raises(mt.MpsParameterNotFound, match="no seq 5"):
        mt.get_param(doc, "Ei (V)", seq=5)


def test_n_sequences_counts_the_widest_parameter_row(doc):
    assert mt.n_sequences(doc) == 2


def test_write_patched_creates_parents_and_returns_the_path(tmp_path, cv):
    dest = tmp_path / "nested" / "out.mps"
    written = mt.write_patched(mt.set_param(cv, "Bandwidth", "7"), dest)
    assert written == dest
    assert mt.get_param(mt.load(dest), "Bandwidth") == "7"


def test_loads_accepts_text_directly():
    doc = mt.loads(
        "Technique : 1\r\nOCV\r\n" + "tR (h:m:s)".ljust(20) + "0:00:5.0000\r\n"
    )
    assert mt.get_param(doc, "tR (h:m:s)") == "0:00:5.0000"
