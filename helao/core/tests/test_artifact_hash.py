"""Artefact SHA-256 records (spec §5)."""

import asyncio
import hashlib
import json
import logging
import os

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
    log_artifact_hashes_sync(
        [tmp_path / "gone"], kind="data", owner_uuid="u", logger=lg
    )
    h.close()
    (r,) = _rows(tmp_path / "LOGS" / "SRV.jsonl")
    assert r["event"] == "artifact_hash_failed" and r["level"] == "WARNING"


def test_path_outside_root_is_absolute(tmp_path):
    h, lg = _setup(tmp_path)
    f = tmp_path / "x"
    f.write_text("1")
    log_artifact_hashes_sync(
        [f], kind="output", owner_uuid="u", root=str(tmp_path / "other"), logger=lg
    )
    h.close()
    assert _rows(tmp_path / "LOGS" / "SRV.jsonl")[0]["path"] == str(f.resolve())


def test_record_uuid():
    assert record_uuid({"action_uuid": "a"}) == "a"
    assert record_uuid({"process_uuid": "p"}) == "p"
    assert record_uuid({}) is None
