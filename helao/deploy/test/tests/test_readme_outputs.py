"""Guard: every writer unit in the test deployment documents its outputs."""

from pathlib import Path

from helao.helpers.readme_outputs import missing_outputs_sections

# wssim persists its live samples through the acquire_data executor; the regex misses it.
EXTRA: list[str] = ["servers/wssim"]


def test_writer_units_document_outputs():
    root = Path(__file__).resolve().parents[1]
    assert missing_outputs_sections(root, EXTRA) == []
