"""Tests for ``FsSyncStorage`` (real-filesystem ``SyncStorage`` adapter).

Uses the pytest ``tmp_path`` fixture (real dirs). A small fake RUNS tree is
built under ``tmp_path`` and exercised against the legacy on-disk conventions.
"""
import zipfile
from pathlib import Path

import pytest

from helao.framework.adapters.fs_sync_storage import FsSyncStorage
from helao.framework.ports.sync_storage import SyncStorage
from helao.framework.support.yml_tools import yml_load


@pytest.fixture
def store() -> FsSyncStorage:
    return FsSyncStorage()


def _touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _make_runs_tree(root: Path, runs: str = "RUNS_FINISHED") -> dict:
    """Build a minimal week/date/seq/exp/act tree; return key paths."""
    base = root / runs / "wk" / "date"
    seqdir = base / "seq"
    expdir = seqdir / "exp"
    actdir = expdir / "act"
    seq_yml = _touch(seqdir / "000101.010101000000-seq.yml")
    exp_yml = _touch(expdir / "000101.010102000000-exp.yml")
    act_yml = _touch(actdir / "000101.010103000000-act.yml")
    return {
        "base": base,
        "seqdir": seqdir,
        "expdir": expdir,
        "actdir": actdir,
        "seq_yml": seq_yml,
        "exp_yml": exp_yml,
        "act_yml": act_yml,
        "finished_root": root / runs,
    }


# --- protocol conformance ---


def test_conforms_to_protocol(store):
    assert isinstance(store, SyncStorage)


# --- yml round trip ---


def test_yml_round_trip(tmp_path, store):
    p = tmp_path / "RUNS_FINISHED" / "x-seq.yml"
    p.parent.mkdir(parents=True)
    data = {"file_type": "sequence", "name": "demo", "nullfield": None, "n": 3}
    store.write_yml(p, data)
    text = p.read_text(encoding="utf-8")
    # byte conventions: None renders as literal null, ends with newline
    assert "null" in text
    assert text.endswith("\n")
    loaded = store.read_yml(p)
    assert loaded["file_type"] == "sequence"
    assert loaded["name"] == "demo"
    assert loaded["nullfield"] is None
    assert loaded["n"] == 3


# --- prg round trip + missing ---


def test_prg_round_trip_and_missing(tmp_path, store):
    prg = tmp_path / "RUNS_SYNCED" / "deep" / "x-seq.prg"
    assert store.read_prg(prg) == {}  # missing -> {}
    payload = {"yml": "x", "api": False, "s3": False, "files_pending": []}
    store.write_prg(prg, payload)  # creates parents
    assert prg.exists()
    assert store.read_prg(prg) == payload


def test_remove_prg_idempotent(tmp_path, store):
    prg = _touch(tmp_path / "a.prg")
    store.remove_prg(prg)
    assert not prg.exists()
    store.remove_prg(prg)  # missing_ok


# --- move_to_synced ---


def test_move_to_synced(tmp_path, store):
    t = _make_runs_tree(tmp_path, "RUNS_FINISHED")
    src = t["seq_yml"]
    dst = store.move_to_synced(src)
    assert not src.exists()  # source gone
    assert dst.exists()
    # destination at correct RUNS_SYNCED relpath
    assert "RUNS_SYNCED" in dst.parts
    assert dst == tmp_path / "RUNS_SYNCED" / "wk" / "date" / "seq" / src.name


def test_move_to_synced_missing_source_noop(tmp_path, store):
    src = tmp_path / "RUNS_FINISHED" / "wk" / "date" / "seq" / "ghost-seq.yml"
    dst = store.move_to_synced(src)
    assert dst == tmp_path / "RUNS_SYNCED" / "wk" / "date" / "seq" / "ghost-seq.yml"
    assert not dst.exists()


def test_move_to_synced_already_synced_noop(tmp_path, store):
    src = _touch(tmp_path / "RUNS_SYNCED" / "wk" / "x-seq.yml")
    dst = store.move_to_synced(src)
    assert dst == src
    assert src.exists()  # not moved


# --- revert_to_finished ---


def test_revert_to_finished(tmp_path, store):
    src = _touch(tmp_path / "RUNS_SYNCED" / "wk" / "date" / "seq" / "x-seq.yml")
    dst = store.revert_to_finished(src)
    assert not src.exists()
    assert dst.exists()
    assert dst == tmp_path / "RUNS_FINISHED" / "wk" / "date" / "seq" / "x-seq.yml"


def test_revert_to_finished_requires_synced(tmp_path, store):
    src = _touch(tmp_path / "RUNS_FINISHED" / "x-seq.yml")
    with pytest.raises(ValueError):
        store.revert_to_finished(src)


# --- move_tree ---


def test_move_tree(tmp_path, store):
    src = tmp_path / "src" / "node"
    _touch(src / "a.txt")
    _touch(src / "sub" / "b.txt")
    dst = tmp_path / "dst" / "moved"
    out = store.move_tree(src, dst)
    assert out == dst
    assert not src.exists()
    assert (dst / "a.txt").exists()
    assert (dst / "sub" / "b.txt").exists()


# --- zip_dir ---


def test_zip_dir(tmp_path, store):
    seqdir = tmp_path / "RUNS_SYNCED" / "wk" / "date" / "seq"
    _touch(seqdir / "000101.010101000000-seq.yml", "meta")
    _touch(seqdir / "exp" / "data.hlo", "rows")
    _touch(seqdir / "exp" / "stale.lock", "lock")  # skipped
    archive = store.zip_dir(seqdir)
    assert archive == seqdir.parent / f"{seqdir.name}.zip"
    assert archive.exists()
    assert not seqdir.exists()  # source removed on success
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
    assert "000101.010101000000-seq.yml" in names
    assert "exp/data.hlo" in names
    assert "exp/stale.lock" not in names  # .lock skipped


# --- cleanup_empty ---


def test_cleanup_empty_leaf_removed(tmp_path, store):
    # A directly-empty directory is rmdir'd and reports True.
    d = tmp_path / "leaf"
    d.mkdir()
    assert store.cleanup_empty(d) is True
    assert not d.exists()


def test_cleanup_empty_subtree(tmp_path, store):
    # Legacy try_remove_empty (740-773): a single pass rmdir's the empty
    # *leaf* (c), reports True for the whole subtree, but does NOT rmdir the
    # ancestors in the same pass (their `contents` were captured pre-recursion).
    d = tmp_path / "a" / "b" / "c"
    d.mkdir(parents=True)
    top = tmp_path / "a"
    assert store.cleanup_empty(top) is True
    assert not (tmp_path / "a" / "b" / "c").exists()  # empty leaf removed
    assert top.exists()  # ancestors survive this pass (faithful to legacy)


def test_cleanup_empty_preserves_nonempty(tmp_path, store):
    d = tmp_path / "a" / "b"
    d.mkdir(parents=True)
    _touch(d / "keep.txt")
    top = tmp_path / "a"
    assert store.cleanup_empty(top) is False
    assert (d / "keep.txt").exists()


# --- remove ---


def test_remove(tmp_path, store):
    f = _touch(tmp_path / "f.txt")
    store.remove(f)
    assert not f.exists()


# --- exists / file_size ---


def test_exists_and_file_size(tmp_path, store):
    f = _touch(tmp_path / "f.bin", "abcde")
    assert store.exists(f) is True
    assert store.exists(tmp_path / "nope") is False
    assert store.file_size(f) == 5


# --- list_pending glob depth + omit_manual ---


def test_list_pending_glob_depth_per_kind(tmp_path, store):
    t = _make_runs_tree(tmp_path, "RUNS_FINISHED")
    fr = t["finished_root"]
    seqs = store.list_pending(fr, "seq", omit_manual=False)
    exps = store.list_pending(fr, "exp", omit_manual=False)
    acts = store.list_pending(fr, "act", omit_manual=False)
    assert seqs == [t["seq_yml"]]
    assert exps == [t["exp_yml"]]
    assert acts == [t["act_yml"]]


def test_list_pending_omit_manual(tmp_path, store):
    # seq at correct depth containing the manual marker
    base = tmp_path / "RUNS_FINISHED" / "wk" / "date"
    normal = _touch(base / "seqA" / "000101.010101000000-seq.yml")
    manual = _touch(
        base / "manual_orch_seq_run" / "000101.010102000000-seq.yml"
    )
    fr = tmp_path / "RUNS_FINISHED"
    with_manual = store.list_pending(fr, "seq", omit_manual=False)
    without = store.list_pending(fr, "seq", omit_manual=True)
    assert set(with_manual) == {normal, manual}
    assert set(without) == {normal}


def test_list_pending_unknown_kind(tmp_path, store):
    with pytest.raises(ValueError):
        store.list_pending(tmp_path, "bogus", omit_manual=False)


# --- list_children sorted ---


def test_list_children_sorted_by_timestamp(tmp_path, store):
    parent = tmp_path / "RUNS_FINISHED" / "wk" / "date" / "seq"
    # create out of timestamp order
    later = _touch(parent / "expB" / "000101.010105000000-exp.yml")
    earlier = _touch(parent / "expA" / "000101.010102000000-exp.yml")
    children = store.list_children(parent)
    assert children == [earlier, later]  # oldest first


# --- hlo / misc / lock files ---


def test_hlo_and_lock_files_shallow(tmp_path, store):
    d = tmp_path / "actdir"
    _touch(d / "data.hlo")
    _touch(d / "run.lock")
    _touch(d / "x-act.yml")
    _touch(d / "sub" / "nested.hlo")  # not picked up (shallow)
    hlos = store.hlo_files(d)
    locks = store.lock_files(d)
    assert hlos == [d / "data.hlo"]
    assert locks == [d / "run.lock"]


def test_misc_files_action_recurses(tmp_path, store):
    d = tmp_path / "actdir"
    aux_top = _touch(d / "aux.csv")
    aux_nested = _touch(d / "sub" / "more.txt")
    _touch(d / "x-act.yml")  # excluded
    _touch(d / "data.hlo")  # excluded
    _touch(d / "run.lock")  # excluded
    misc = set(store.misc_files(d, "act"))
    assert misc == {aux_top, aux_nested}


def test_misc_files_experiment_shallow(tmp_path, store):
    d = tmp_path / "expdir"
    aux_top = _touch(d / "aux.csv")
    _touch(d / "sub" / "more.txt")  # NOT recursed for exp
    _touch(d / "x-exp.yml")  # excluded
    misc = set(store.misc_files(d, "exp"))
    assert misc == {aux_top}
