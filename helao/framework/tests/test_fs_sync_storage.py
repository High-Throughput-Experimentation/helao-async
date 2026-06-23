import json
from pathlib import Path
from zipfile import ZipFile
import pytest
from helao.framework.adapters.fs_sync_storage import FsSyncStorage
from helao.framework.adapters.s3_sync_storage import S3SyncStorage


# ── FsSyncStorage ─────────────────────────────────────────────────────────────

def test_write_read_yml_round_trip(tmp_path):
    store = FsSyncStorage()
    path = tmp_path / "test-seq.yml"
    data = {"key": "value", "number": 42}
    store.write_yml(path, data)
    loaded = store.read_yml(path)
    assert loaded["key"] == "value"
    assert loaded["number"] == 42


def test_write_read_prg_round_trip(tmp_path):
    store = FsSyncStorage()
    path = tmp_path / "test.prg"
    data = {"s3": True, "api": False, "yml": "/some/path.yml"}
    store.write_prg(path, data)
    assert store.read_prg(path) == data


def test_read_prg_missing_returns_empty(tmp_path):
    store = FsSyncStorage()
    assert store.read_prg(tmp_path / "nonexistent.prg") == {}


def test_remove_prg_deletes_file(tmp_path):
    store = FsSyncStorage()
    path = tmp_path / "test.prg"
    store.write_prg(path, {"s3": False})
    store.remove_prg(path)
    assert not path.exists()


def test_remove_prg_missing_is_noop(tmp_path):
    store = FsSyncStorage()
    store.remove_prg(tmp_path / "no.prg")  # must not raise


def test_move_tree_transfers_contents(tmp_path):
    src = tmp_path / "RUNS_FINISHED" / "seq1"
    src.mkdir(parents=True)
    (src / "test-act.yml").write_text("key: value")
    dst = tmp_path / "RUNS_SYNCED" / "seq1"
    store = FsSyncStorage()
    result = store.move_tree(src, dst)
    assert result == dst
    assert not src.exists()
    assert (dst / "test-act.yml").exists()


def test_zip_dir_creates_archive_and_removes_source(tmp_path):
    target = tmp_path / "seq_dir"
    target.mkdir()
    (target / "a.yml").write_text("hello")
    (target / "b.hlo").write_text("data")
    store = FsSyncStorage()
    zip_path = store.zip_dir(target)
    assert zip_path.exists()
    assert zip_path.suffix == ".zip"
    assert not target.exists()
    with ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert any("a.yml" in n for n in names)
    assert any("b.hlo" in n for n in names)


def test_zip_dir_skips_lock_files(tmp_path):
    target = tmp_path / "seq_dir"
    target.mkdir()
    (target / "data.hlo").write_text("x")
    (target / "data.hlo.lock").write_text("locked")
    store = FsSyncStorage()
    zip_path = store.zip_dir(target)
    with ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert not any(".lock" in n for n in names)


def test_list_ymls_finds_nested_ymls(tmp_path):
    root = tmp_path / "RUNS_FINISHED"
    (root / "seq1" / "exp1").mkdir(parents=True)
    (root / "seq1" / "test-seq.yml").touch()
    (root / "seq1" / "exp1" / "test-act.yml").touch()
    store = FsSyncStorage()
    ymls = store.list_ymls(root)
    assert len(ymls) == 2


def test_list_files_with_pattern(tmp_path):
    d = tmp_path / "dir"
    d.mkdir()
    (d / "a.hlo").touch()
    (d / "b.yml").touch()
    store = FsSyncStorage()
    hlos = store.list_files(d, "*.hlo")
    assert len(hlos) == 1
    assert hlos[0].name == "a.hlo"


def test_try_remove_empty_removes_empty_dir(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    store = FsSyncStorage()
    assert store.try_remove_empty(empty) is True
    assert not empty.exists()


def test_try_remove_empty_returns_false_for_nonempty(tmp_path):
    nonempty = tmp_path / "full"
    nonempty.mkdir()
    (nonempty / "f.txt").write_text("x")
    store = FsSyncStorage()
    assert store.try_remove_empty(nonempty) is False
    assert nonempty.exists()


def test_upload_stubs_return_correct_values(tmp_path):
    store = FsSyncStorage()
    f = tmp_path / "f.txt"
    f.write_text("x")
    assert store.upload_file(f, "key/f.txt") is True
    assert store.upload_bytes(b"data", "key/data") is True
    assert store.key_exists("key/f.txt") is False


# ── S3SyncStorage stub ────────────────────────────────────────────────────────

def test_s3_upload_file_raises_not_implemented(tmp_path):
    store = S3SyncStorage()
    f = tmp_path / "f.txt"
    f.write_text("x")
    with pytest.raises(NotImplementedError):
        store.upload_file(f, "bucket/key")


def test_s3_upload_bytes_raises_not_implemented():
    store = S3SyncStorage()
    with pytest.raises(NotImplementedError):
        store.upload_bytes(b"data", "bucket/key")


def test_s3_key_exists_raises_not_implemented():
    store = S3SyncStorage()
    with pytest.raises(NotImplementedError):
        store.key_exists("bucket/key")
