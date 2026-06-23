import zipfile
from pathlib import Path

import anyio
import pytest

from helao.framework.support.file_utils import (
    file_in_use,
    rm_tree,
    rm_tree_async,
    unzpickle,
    zip_dir,
    zpickle,
)


def test_file_in_use_nonexistent(tmp_path):
    assert file_in_use(tmp_path / "ghost.txt") is False


def test_file_in_use_not_locked(tmp_path):
    f = tmp_path / "real.txt"
    f.write_text("x")
    assert file_in_use(f) is False


def test_file_in_use_locked(tmp_path, monkeypatch):
    f = tmp_path / "locked.txt"
    f.write_text("x")

    def _raise(self, target):
        raise PermissionError("locked")

    monkeypatch.setattr(Path, "rename", _raise)
    assert file_in_use(f) is True


def test_rm_tree_empty_dir(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    rm_tree(d)
    assert not d.exists()


def test_rm_tree_with_files(tmp_path):
    d = tmp_path / "withfiles"
    d.mkdir()
    (d / "a.txt").write_text("a")
    (d / "b.txt").write_text("b")
    rm_tree(d)
    assert not d.exists()


def test_rm_tree_nested(tmp_path):
    d = tmp_path / "nested"
    sub = d / "sub"
    sub.mkdir(parents=True)
    (sub / "c.txt").write_text("c")
    (d / "d.txt").write_text("d")
    rm_tree(d)
    assert not d.exists()


@pytest.mark.asyncio
async def test_rm_tree_async_empty_str(tmp_path):
    d = tmp_path / "async_empty"
    d.mkdir()
    await rm_tree_async(str(d))
    assert not d.exists()


@pytest.mark.asyncio
async def test_rm_tree_async_pathlib_path(tmp_path):
    d = tmp_path / "async_pathlib"
    d.mkdir()
    (d / "x.txt").write_text("x")
    await rm_tree_async(d)
    assert not d.exists()


@pytest.mark.asyncio
async def test_rm_tree_async_anyio_path(tmp_path):
    d = tmp_path / "async_anyio"
    d.mkdir()
    (d / "y.txt").write_text("y")
    await rm_tree_async(anyio.Path(str(d)))
    assert not d.exists()


@pytest.mark.asyncio
async def test_rm_tree_async_nested(tmp_path):
    d = tmp_path / "async_nested"
    sub = d / "sub"
    sub.mkdir(parents=True)
    (sub / "z.txt").write_text("z")
    await rm_tree_async(str(d))
    assert not d.exists()


def test_zip_dir_normal(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello")
    (src / "b.txt").write_text("world")
    dest = tmp_path / "out.zip"
    zip_dir(src, dest)
    assert dest.exists()
    assert not src.exists()
    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
    assert "a.txt" in names
    assert "b.txt" in names


def test_zip_dir_skips_lock_files(tmp_path):
    src = tmp_path / "src2"
    src.mkdir()
    (src / "keep.txt").write_text("data")
    (src / "skip.lock").write_text("lock")
    dest = tmp_path / "out2.zip"
    zip_dir(src, dest)
    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
    assert "keep.txt" in names
    assert "skip.lock" not in names


def test_zip_dir_exception_leaves_source(tmp_path, monkeypatch):
    src = tmp_path / "src3"
    src.mkdir()
    (src / "f.txt").write_text("data")
    dest = tmp_path / "out3.zip"

    original_init = zipfile.ZipFile.__init__

    def bad_init(self, *args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(zipfile.ZipFile, "__init__", bad_init)
    zip_dir(src, dest)
    assert src.exists()


def test_zpickle_unzpickle_roundtrip(tmp_path):
    fpath = tmp_path / "data.zst"
    payload = {"key": [1, 2, 3], "nested": {"a": True}}
    result = zpickle(fpath, payload)
    assert result is True
    assert fpath.exists()
    loaded = unzpickle(fpath)
    assert loaded == payload


def test_zpickle_returns_true(tmp_path):
    fpath = tmp_path / "simple.zst"
    assert zpickle(fpath, 42) is True


def test_unzpickle_scalar(tmp_path):
    fpath = tmp_path / "scalar.zst"
    zpickle(fpath, "hello")
    assert unzpickle(fpath) == "hello"


def test_zpickle_unzpickle_list(tmp_path):
    fpath = tmp_path / "list.zst"
    data = list(range(1000))
    zpickle(fpath, data)
    assert unzpickle(fpath) == data
