"""Unit tests for helao.framework.support.file_mapper."""

import tempfile
import os
from pathlib import Path
from zipfile import ZipFile
import pytest
from helao.framework.support.file_mapper import FileMapper


@pytest.fixture
def temp_run_tree():
    """Create a temporary directory structure mimicking HELAO's RUNS_* layout."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create RUNS_ACTIVE directory structure
        active_dir = tmpdir / "RUNS_ACTIVE" / "2026.25" / "0624"
        active_dir.mkdir(parents=True)
        (active_dir / "test_file.txt").write_text("active content")
        (active_dir / "data.hlo").write_bytes(b"hlo_data")

        # Create RUNS_FINISHED directory structure
        finished_dir = tmpdir / "RUNS_FINISHED" / "2026.25" / "0624"
        finished_dir.mkdir(parents=True)
        (finished_dir / "test_file.txt").write_text("finished content")
        (finished_dir / "another_file.yaml").write_text("key: value")

        # Create RUNS_SYNCED directory structure with a zip
        synced_dir = tmpdir / "RUNS_SYNCED" / "2026.25" / "0624"
        synced_dir.mkdir(parents=True)
        zip_path = synced_dir / "exp1.zip"
        with ZipFile(zip_path, "w") as zf:
            zf.writestr("action1/data.hlo", b"zipped_hlo_data")
            zf.writestr("action1/metadata.yaml", "title: test")

        # Create PROCESSES directory
        processes_dir = tmpdir / "PROCESSES" / "2026.25" / "0624"
        processes_dir.mkdir(parents=True)
        (processes_dir / "log.txt").write_text("process log")

        yield tmpdir


def test_file_mapper_init_with_active_dir(temp_run_tree):
    """Test FileMapper initialization with a path in RUNS_ACTIVE."""
    active_path = temp_run_tree / "RUNS_ACTIVE" / "2026.25" / "0624"
    mapper = FileMapper(active_path)

    assert mapper.inputdir == active_path.absolute()
    assert mapper.inputfile is None
    assert "RUNS_ACTIVE" in mapper.inputparts
    assert mapper.prestr == str(temp_run_tree)
    assert mapper.states == ["ACTIVE", "FINISHED", "SYNCED", "DIAG", "NOSYNC"]


def test_file_mapper_init_with_file(temp_run_tree):
    """Test FileMapper initialization with a specific file."""
    file_path = temp_run_tree / "RUNS_ACTIVE" / "2026.25" / "0624" / "test_file.txt"
    mapper = FileMapper(file_path)

    assert mapper.inputfile == file_path.absolute()
    assert mapper.inputdir == file_path.parent.absolute()


def test_file_mapper_locate_in_active(temp_run_tree):
    """Test locating a file in RUNS_ACTIVE."""
    active_path = temp_run_tree / "RUNS_ACTIVE" / "2026.25" / "0624"
    mapper = FileMapper(active_path)

    result = mapper.locate("2026.25/0624/test_file.txt")
    assert result is not None
    assert result.exists()
    assert result.name == "test_file.txt"


def test_file_mapper_locate_fallback_to_finished(temp_run_tree):
    """Test that locate falls back to RUNS_FINISHED when file not in RUNS_ACTIVE."""
    # Only in FINISHED
    active_path = temp_run_tree / "RUNS_ACTIVE" / "2026.25" / "0624"
    mapper = FileMapper(active_path)

    result = mapper.locate("2026.25/0624/another_file.yaml")
    assert result is not None
    assert result.exists()
    assert "RUNS_FINISHED" in str(result)


def test_file_mapper_locate_in_zip(temp_run_tree):
    """Test locating a file inside a synced zip."""
    active_path = temp_run_tree / "RUNS_ACTIVE" / "2026.25" / "0624"
    mapper = FileMapper(active_path)

    # Locate a file that's inside the zip; test with full path structure
    result = mapper.locate("2026.25/0624/exp1/action1/metadata.yaml")
    assert result is not None
    assert isinstance(result, tuple)
    assert len(result) == 2
    zip_path, member = result
    assert zip_path.suffix == ".zip"
    assert "exp1.zip" in str(zip_path)


def test_file_mapper_locate_nonexistent(temp_run_tree):
    """Test that locate returns None for nonexistent files."""
    active_path = temp_run_tree / "RUNS_ACTIVE" / "2026.25" / "0624"
    mapper = FileMapper(active_path)

    result = mapper.locate("nonexistent_file.txt")
    assert result is None


def test_file_mapper_read_bytes_from_loose_file(temp_run_tree):
    """Test reading bytes from a loose file."""
    active_path = temp_run_tree / "RUNS_ACTIVE" / "2026.25" / "0624"
    mapper = FileMapper(active_path)

    content = mapper.read_bytes("2026.25/0624/data.hlo")
    assert content == b"hlo_data"


def test_file_mapper_read_bytes_from_zip(temp_run_tree):
    """Test reading bytes from a file inside a zip."""
    active_path = temp_run_tree / "RUNS_ACTIVE" / "2026.25" / "0624"
    mapper = FileMapper(active_path)

    content = mapper.read_bytes("2026.25/0624/exp1/action1/data.hlo")
    assert content == b"zipped_hlo_data"


def test_file_mapper_read_lines_loose(temp_run_tree):
    """Test reading lines from a loose text file."""
    active_path = temp_run_tree / "RUNS_ACTIVE" / "2026.25" / "0624"
    mapper = FileMapper(active_path)

    lines = mapper.read_lines("2026.25/0624/test_file.txt")
    assert lines == ["active content"]


def test_file_mapper_read_lines_from_zip(temp_run_tree):
    """Test reading lines from a file inside a zip."""
    active_path = temp_run_tree / "RUNS_ACTIVE" / "2026.25" / "0624"
    mapper = FileMapper(active_path)

    lines = mapper.read_lines("2026.25/0624/exp1/action1/metadata.yaml")
    assert lines[0] == "title: test"


def test_file_mapper_read_yml_loose(temp_run_tree):
    """Test reading and parsing YAML from a loose file."""
    active_path = temp_run_tree / "RUNS_ACTIVE" / "2026.25" / "0624"
    mapper = FileMapper(active_path)

    yml_dict = mapper.read_yml("2026.25/0624/another_file.yaml")
    assert isinstance(yml_dict, dict)
    assert yml_dict.get("key") == "value"


def test_file_mapper_read_yml_from_zip(temp_run_tree):
    """Test reading and parsing YAML from a file inside a zip."""
    active_path = temp_run_tree / "RUNS_ACTIVE" / "2026.25" / "0624"
    mapper = FileMapper(active_path)

    yml_dict = mapper.read_yml("2026.25/0624/exp1/action1/metadata.yaml")
    assert isinstance(yml_dict, dict)
    assert yml_dict.get("title") == "test"


def test_file_mapper_locate_processes_passthrough(temp_run_tree):
    """Test that PROCESSES paths are returned unchanged."""
    active_path = temp_run_tree / "RUNS_ACTIVE" / "2026.25" / "0624"
    mapper = FileMapper(active_path)

    result = mapper.locate("PROCESSES/2026.25/0624/log.txt")
    assert result == "PROCESSES/2026.25/0624/log.txt"


def test_file_mapper_read_bytes_not_found(temp_run_tree):
    """Test that read_bytes raises FileNotFoundError when file not found."""
    active_path = temp_run_tree / "RUNS_ACTIVE" / "2026.25" / "0624"
    mapper = FileMapper(active_path)

    with pytest.raises(FileNotFoundError):
        mapper.read_bytes("nonexistent_file.txt")


def test_file_mapper_read_yml_not_found(temp_run_tree):
    """Test that read_yml raises FileNotFoundError when file not found."""
    active_path = temp_run_tree / "RUNS_ACTIVE" / "2026.25" / "0624"
    mapper = FileMapper(active_path)

    with pytest.raises(FileNotFoundError):
        mapper.read_yml("nonexistent.yaml")
