"""Guard: every writer unit in the base deployment documents its outputs.

Also unit-tests the shared helper in helao/helpers/readme_outputs.py.
"""

from pathlib import Path

from helao.helpers.readme_outputs import missing_outputs_sections, unit_of


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_unit_of_groups_by_folder():
    assert unit_of(Path("servers/gamry/driver.py")) == Path("servers/gamry")
    assert unit_of(Path("servers/gamry/bokeh/vis.py")) == Path("servers/gamry")
    assert unit_of(Path("scripts/edax/converters.py")) == Path("scripts/edax")
    assert unit_of(Path("processors/libs/x.py")) == Path("processors")
    assert unit_of(Path("servers/__init__.py")) is None
    assert unit_of(Path("servers/gamry/tests/test_x.py")) is None
    assert unit_of(Path("experiments/x.py")) is None


def test_writer_without_readme_is_reported(tmp_path):
    _write(tmp_path, "servers/a/a_server.py", "await active.enqueue_data_dflt(d)\n")
    assert missing_outputs_sections(tmp_path) == ["servers/a"]


def test_readme_without_outputs_heading_is_reported(tmp_path):
    _write(tmp_path, "servers/a/a_server.py", "df.to_parquet(p)\n")
    _write(tmp_path, "servers/a/README.md", "# a\n\n## Params\n")
    assert missing_outputs_sections(tmp_path) == ["servers/a"]


def test_outputs_heading_satisfies(tmp_path):
    _write(tmp_path, "servers/a/a_server.py", 'action.action_params["v"] = 1\n')
    _write(
        tmp_path,
        "servers/a/README.md",
        "# a\n\n## Outputs\n\nNo data files or action results.\n",
    )
    assert missing_outputs_sections(tmp_path) == []


def test_non_writer_and_comparison_not_reported(tmp_path):
    _write(
        tmp_path,
        "servers/b/b_server.py",
        'if action.action_params["v"] == 1:\n    pass\n',
    )
    assert missing_outputs_sections(tmp_path) == []


def test_extra_units_required(tmp_path):
    _write(tmp_path, "scripts/notes/post.py", "client.post(url, json=n)\n")
    assert missing_outputs_sections(tmp_path, extra=["scripts/notes"]) == [
        "scripts/notes"
    ]


def test_base_deployment_writer_units_documented():
    root = Path(__file__).resolve().parents[1]
    assert missing_outputs_sections(root) == []
