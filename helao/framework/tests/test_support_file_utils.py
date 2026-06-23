"""Tests for helao.framework.support.file_utils.

Covers file_in_use, rm_tree, rm_tree_async, zip_dir, zpickle/unzpickle
round-trips with tmp_path fixtures.  No real locked handles (Windows-only
PermissionError path) so file_in_use is exercised for the False/exists branch
only.
"""

import asyncio
import zipfile
from pathlib import Path

import pytest

from helao.framework.support.file_utils import (
    file_in_use,
    rm_tree,
    rm_tree_async,
    unzpickle,
    zip_dir,
    zpickle,
)


# ---------------------------------------------------------------------------
# file_in_use
# ---------------------------------------------------------------------------


def test_file_in_use_returns_false_for_missing_path(tmp_path):
    """Non-existent path must return False without raising."""
    result = file_in_use(tmp_path / "no_such_file.txt")
    assert result is False


def test_file_in_use_returns_false_for_existing_unlocked_file(tmp_path):
    """An ordinary file that is not held open must return False."""
    f = tmp_path / "unlocked.txt"
    f.write_text("data")
    assert file_in_use(f) is False


def test_file_in_use_accepts_string_path(tmp_path):
    """file_in_use accepts a str path as well as a Path object."""
    f = tmp_path / "str_path.txt"
    f.write_text("ok")
    assert file_in_use(str(f)) is False


# ---------------------------------------------------------------------------
# rm_tree (synchronous)
# ---------------------------------------------------------------------------


def test_rm_tree_removes_nested_structure(tmp_path):
    """rm_tree deletes a tree of files and directories recursively."""
    root = tmp_path / "tree"
    (root / "sub1").mkdir(parents=True)
    (root / "sub1" / "deep").mkdir()
    (root / "sub1" / "file.txt").write_text("x")
    (root / "sub1" / "deep" / "nested.txt").write_text("y")
    (root / "file_at_root.bin").write_bytes(b"\x00\x01")

    rm_tree(root)

    assert not root.exists()


def test_rm_tree_removes_empty_directory(tmp_path):
    """rm_tree handles an empty directory (no children)."""
    empty = tmp_path / "empty"
    empty.mkdir()
    rm_tree(empty)
    assert not empty.exists()


def test_rm_tree_accepts_string_path(tmp_path):
    """rm_tree coerces a str argument to Path internally."""
    d = tmp_path / "str_dir"
    d.mkdir()
    (d / "f.txt").write_text("hi")
    rm_tree(str(d))
    assert not d.exists()


# ---------------------------------------------------------------------------
# rm_tree_async
# ---------------------------------------------------------------------------


def test_rm_tree_async_removes_nested_structure(tmp_path):
    """Async variant deletes the same structure as the sync version."""
    root = tmp_path / "async_tree"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "deep.dat").write_bytes(b"z" * 16)
    (root / "a" / "top.txt").write_text("data")

    asyncio.run(rm_tree_async(root))

    assert not root.exists()


def test_rm_tree_async_accepts_string_path(tmp_path):
    """rm_tree_async accepts a plain str and converts it to anyio.Path."""
    d = tmp_path / "async_str"
    d.mkdir()
    (d / "f.txt").write_text("hello")
    asyncio.run(rm_tree_async(str(d)))
    assert not d.exists()


def test_rm_tree_async_accepts_pathlib_path(tmp_path):
    """rm_tree_async accepts a pathlib.Path and converts it to anyio.Path."""
    d = tmp_path / "async_pathlib"
    d.mkdir()
    (d / "g.txt").write_text("world")
    asyncio.run(rm_tree_async(d))
    assert not d.exists()


# ---------------------------------------------------------------------------
# zip_dir
# ---------------------------------------------------------------------------


def test_zip_dir_archives_files_and_removes_source(tmp_path):
    """zip_dir creates a valid zip archive and deletes the source directory."""
    src = tmp_path / "to_zip"
    src.mkdir()
    (src / "readme.txt").write_text("hello")
    (src / "data.bin").write_bytes(b"\xde\xad\xbe\xef")

    archive = tmp_path / "archive.zip"
    zip_dir(src, archive)

    assert archive.exists()
    assert not src.exists()

    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    assert "readme.txt" in names
    assert "data.bin" in names


def test_zip_dir_skips_lock_files(tmp_path):
    """Files ending in .lock must not appear in the resulting archive."""
    src = tmp_path / "skip_locks"
    src.mkdir()
    (src / "keep.txt").write_text("keep me")
    (src / "skip.lock").write_text("lock content")

    archive = tmp_path / "no_locks.zip"
    zip_dir(src, archive)

    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    assert "keep.txt" in names
    assert "skip.lock" not in names


def test_zip_dir_handles_nested_subdirectories(tmp_path):
    """zip_dir recurses into subdirectories."""
    src = tmp_path / "nested_zip"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "inner.txt").write_text("inner")

    archive = tmp_path / "nested.zip"
    zip_dir(src, archive)

    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    assert any("inner.txt" in n for n in names)


def test_zip_dir_accepts_string_paths(tmp_path):
    """zip_dir accepts str arguments as well as Path objects."""
    src = tmp_path / "str_zip"
    src.mkdir()
    (src / "f.txt").write_text("data")
    archive = tmp_path / "str_archive.zip"

    zip_dir(str(src), str(archive))

    assert archive.exists()
    assert not src.exists()


def test_zip_dir_leaves_source_on_error(tmp_path, monkeypatch):
    """When ZipFile construction raises, the source directory is preserved."""
    src = tmp_path / "error_zip"
    src.mkdir()
    (src / "file.txt").write_text("keep me")

    def _bad_zip(*a, **kw):
        raise OSError("forced failure")

    monkeypatch.setattr(zipfile, "ZipFile", _bad_zip)

    archive = tmp_path / "error.zip"
    zip_dir(src, archive)  # must not raise

    assert src.exists()
    assert (src / "file.txt").exists()


# ---------------------------------------------------------------------------
# zpickle / unzpickle round-trips
# ---------------------------------------------------------------------------

# NOTE: zpickle contains a known bug carried over faithfully from the legacy
# source: after the with-block closes it calls ``os.path.abspath(f)`` where
# ``f`` is the ZstdFile handle rather than the path.  The ``with`` block
# completes successfully (data is written and the file is flushed/closed)
# before the print statement runs, so the file IS valid on disk even though
# zpickle raises TypeError.  The tests below document this behaviour.


def _zpickle_write(fpath, data):
    """Write a zstd-compressed pickle directly, bypassing the buggy print."""
    import _pickle as cPickle
    import pyzstd

    with pyzstd.ZstdFile(fpath, "wb") as f:
        cPickle.dump(data, f)


def test_zpickle_raises_typeerror_due_to_known_bug(tmp_path):
    """zpickle raises TypeError on the os.path.abspath(file_handle) call.

    This is a pre-existing bug in the legacy source that is preserved by
    faithful porting.  Data is written before the error fires.
    """
    data = {"key": [1, 2, 3]}
    fpath = tmp_path / "buggy.zst"
    with pytest.raises(TypeError):
        zpickle(fpath, data)
    # File must still exist and be readable despite the exception.
    assert fpath.exists()


def test_zpickle_file_is_readable_after_error(tmp_path):
    """Despite raising, zpickle flushes valid data before the bug fires."""
    data = {"key": [1, 2, 3], "nested": {"a": True}}
    fpath = tmp_path / "data.zst"
    with pytest.raises(TypeError):
        zpickle(fpath, data)
    loaded = unzpickle(fpath)
    assert loaded == data


def test_unzpickle_round_trips_dict(tmp_path):
    """A dict written by the internal writer is loaded intact by unzpickle."""
    data = {"key": [1, 2, 3], "nested": {"a": True}}
    fpath = tmp_path / "data.zst"
    _zpickle_write(fpath, data)
    assert unzpickle(fpath) == data


def test_unzpickle_round_trips_list(tmp_path):
    """A list of mixed types survives a full round-trip through unzpickle."""
    data = [1, "two", 3.0, None, {"x": b"\xff"}]
    fpath = tmp_path / "list.zst"
    _zpickle_write(fpath, data)
    assert unzpickle(fpath) == data


def test_unzpickle_round_trips_bytes(tmp_path):
    """Raw bytes payload compresses and decompresses without corruption."""
    data = b"\x00\x01\x02" * 1024
    fpath = tmp_path / "bytes.zst"
    _zpickle_write(fpath, data)
    assert unzpickle(fpath) == data
