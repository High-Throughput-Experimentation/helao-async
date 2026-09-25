"""FileInfo.file_name addresses a file relative to its record directory."""

from pathlib import Path

from helao.core.servers.active_data_file import _relative_file_name


def test_file_in_record_root_is_a_bare_name(tmp_path: Path):
    (tmp_path / "data.hlo").write_text("x")
    assert _relative_file_name(tmp_path / "data.hlo", tmp_path) == "data.hlo"


def test_file_in_subdirectory_keeps_its_subdirectory(tmp_path: Path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "instrument.spc").write_text("x")
    assert (
        _relative_file_name(sub / "instrument.spc", tmp_path) == "subdir/instrument.spc"
    )


def test_separator_is_always_forward_slash(tmp_path: Path):
    """Spec §9: stored paths are forward-slash on every platform."""
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    (sub / "c.spc").write_text("x")
    assert "\\" not in _relative_file_name(sub / "c.spc", tmp_path)


def test_file_outside_the_record_falls_back_to_its_basename(tmp_path: Path):
    """A writer handed an unrelated absolute path must not emit '../..' paths."""
    outside = tmp_path.parent / "elsewhere.spc"
    outside.write_text("x")
    assert _relative_file_name(outside, tmp_path) == "elsewhere.spc"
