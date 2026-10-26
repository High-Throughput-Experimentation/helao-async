"""Artefact SHA-256 records (spec §5)."""

import asyncio
import hashlib
import json
import logging
import os
import threading
import time

import pytest

from helao.helpers import artifact_hash
from helao.helpers.artifact_hash import (
    log_artifact_hashes,
    log_artifact_hashes_sync,
    record_uuid,
)
from helao.helpers.log_jsonl import JsonlSinkHandler


def _setup(tmp_path):
    h = JsonlSinkHandler("SRV", tmp_path / "LOGS")
    lg = logging.getLogger("t_art")
    lg.handlers[:] = [h]
    lg.setLevel(10)
    lg.propagate = False
    return h, lg


def _rows(p):
    return [json.loads(x) for x in p.read_bytes().splitlines()] if p.exists() else []


def test_hashes_logged_to_log_and_ledger(tmp_path):
    h, lg = _setup(tmp_path)
    f = tmp_path / "RUNS" / "a.jsonl"
    f.parent.mkdir()
    f.write_bytes(b"x" * 1000)
    asyncio.run(
        log_artifact_hashes(
            [f], kind="data", owner_uuid="u1", root=str(tmp_path), logger=lg
        )
    )
    h.close()
    want = hashlib.sha256(b"x" * 1000).hexdigest()
    for p in (
        tmp_path / "LOGS" / "SRV.jsonl",
        tmp_path / "LOGS" / "artifacts_SRV.jsonl",
    ):
        (r,) = [r for r in _rows(p) if r.get("event") == "artifact_final"]
        assert (r["sha256"], r["bytes"], r["kind"], r["uuid"]) == (
            want,
            1000,
            "data",
            "u1",
        )
        assert r["path"] == os.path.join("RUNS", "a.jsonl")


def test_rewrite_event_and_reason(tmp_path):
    h, lg = _setup(tmp_path)
    f = tmp_path / "r-act.json"
    f.write_text("{}")
    log_artifact_hashes_sync(
        [f],
        kind="act",
        owner_uuid="u",
        event="artifact_rewritten",
        reason="set_plate_id",
        root=str(tmp_path),
        logger=lg,
    )
    h.close()
    (r,) = _rows(tmp_path / "LOGS" / "artifacts_SRV.jsonl")
    assert (r["event"], r["reason"]) == ("artifact_rewritten", "set_plate_id")


def test_missing_file_warns_never_raises(tmp_path):
    h, lg = _setup(tmp_path)
    gone = tmp_path / "gone"
    log_artifact_hashes_sync([gone], kind="data", owner_uuid="u", logger=lg)
    h.close()
    for p in (
        tmp_path / "LOGS" / "SRV.jsonl",
        tmp_path / "LOGS" / "artifacts_SRV.jsonl",
    ):
        (r,) = _rows(p)
        assert r["event"] == "artifact_hash_failed" and r["level"] == "WARNING"
        assert (r["path"], r["kind"], r["uuid"]) == (os.path.abspath(gone), "data", "u")


def _failed(tmp_path):
    return [
        r
        for r in _rows(tmp_path / "LOGS" / "SRV.jsonl")
        if r.get("event") == "artifact_hash_failed"
    ]


def test_bad_entries_never_raise(tmp_path):
    h, lg = _setup(tmp_path)
    d = tmp_path / "adir"
    d.mkdir()
    log_artifact_hashes_sync(
        [None, 5, d, "a\0b", b"bytes-gone"], kind="data", owner_uuid="u", logger=lg
    )
    h.close()
    rows = _failed(tmp_path)
    assert len(rows) == 5
    assert rows[0]["path"] == "None" and rows[1]["path"] == "5"
    assert rows[2]["reason"] == "not a regular file"


def test_paths_none_logs_one_warning(tmp_path):
    h, lg = _setup(tmp_path)
    log_artifact_hashes_sync(None, kind="data", owner_uuid="u", logger=lg)
    h.close()
    assert len(_failed(tmp_path)) == 1


def test_bare_str_is_one_path(tmp_path):
    h, lg = _setup(tmp_path)
    f = tmp_path / "one"
    f.write_text("1")
    log_artifact_hashes_sync(
        str(f), kind="data", owner_uuid="u", root=str(tmp_path), logger=lg
    )
    h.close()
    rows = [
        r
        for r in _rows(tmp_path / "LOGS" / "SRV.jsonl")
        if r["event"] == "artifact_final"
    ]
    assert [r["path"] for r in rows] == ["one"]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no fifo")
def test_fifo_is_refused_not_opened(tmp_path):
    h, lg = _setup(tmp_path)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    log_artifact_hashes_sync([fifo], kind="data", owner_uuid="u", logger=lg)
    h.close()
    (r,) = _failed(tmp_path)
    assert r["reason"] == "not a regular file"


def test_windows_drive_mismatch_gives_absolute(tmp_path, monkeypatch):
    h, lg = _setup(tmp_path)
    f = tmp_path / "x"
    f.write_text("1")

    def boom(*a):
        raise ValueError("Paths don't have the same drive")

    monkeypatch.setattr(artifact_hash.os.path, "commonpath", boom)
    log_artifact_hashes_sync(
        [f], kind="data", owner_uuid="u", root=str(tmp_path), logger=lg
    )
    h.close()
    (r,) = _rows(tmp_path / "LOGS" / "SRV.jsonl")
    assert r["event"] == "artifact_final"
    assert r["path"] == os.path.abspath(f)


def test_async_hashes_on_worker_thread(tmp_path, monkeypatch):
    h, lg = _setup(tmp_path)
    f = tmp_path / "x"
    f.write_text("1")
    seen = []
    real = hashlib.file_digest

    def spy(*a, **k):
        seen.append(threading.get_ident())
        return real(*a, **k)

    monkeypatch.setattr(hashlib, "file_digest", spy)

    async def go():
        loop_tid = threading.get_ident()
        await log_artifact_hashes([f], kind="data", owner_uuid="u", logger=lg)
        return loop_tid

    loop_tid = asyncio.run(go())
    h.close()
    assert seen and seen[0] != loop_tid


def test_fallback_created_once_across_threads(monkeypatch):
    calls = []

    def slow_make(name):
        calls.append(name)
        time.sleep(0.2)
        return logging.getLogger("t_art_fb")

    monkeypatch.setattr(artifact_hash, "_FALLBACK", None)
    monkeypatch.setattr(artifact_hash.helao_logging, "LOGGER", None)
    monkeypatch.setattr(artifact_hash.helao_logging, "make_logger", slow_make)
    ts = [
        threading.Thread(target=artifact_hash._logger, args=(None,)) for _ in range(4)
    ]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(calls) == 1


def test_path_outside_root_is_absolute(tmp_path):
    h, lg = _setup(tmp_path)
    f = tmp_path / "x"
    f.write_text("1")
    log_artifact_hashes_sync(
        [f], kind="output", owner_uuid="u", root=str(tmp_path / "other"), logger=lg
    )
    h.close()
    assert _rows(tmp_path / "LOGS" / "SRV.jsonl")[0]["path"] == os.path.abspath(f)


def test_record_uuid():
    assert record_uuid({"action_uuid": "a"}) == "a"
    assert record_uuid({"process_uuid": "p"}) == "p"
    assert record_uuid({}) is None


def test_root_for_finds_the_root_above_run_trees(tmp_path):
    from helao.helpers.artifact_hash import root_for

    (tmp_path / "RUNS" / "a").mkdir(parents=True)
    (tmp_path / "ANALYSES").mkdir()
    assert root_for(tmp_path / "RUNS" / "a" / "x-act.json") == str(tmp_path)
    assert root_for(tmp_path / "ANALYSES") == str(tmp_path)
    assert root_for(tmp_path / "ANALYSES" / "x" / "y.json") == str(tmp_path)
    assert root_for(tmp_path / "other" / "y.json") is None


def test_root_for_survives_an_unlistable_ancestor(tmp_path, monkeypatch):
    from helao.helpers.artifact_hash import root_for

    def boom(_):
        raise PermissionError

    monkeypatch.setattr(os, "listdir", boom)
    assert root_for(tmp_path / "RUNS" / "x.json") is None
