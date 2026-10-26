"""LogCollector, log_port resolution, read_logs (spec §2, §3)."""

import json
import logging
import time

import pytest
import zmq

from helao.helpers.log_collector import LogCollector, log_endpoint, resolve_log_port
from helao.helpers.log_jsonl import JsonlSinkHandler, read_logs


def _free_port():
    s = zmq.Context.instance().socket(zmq.PULL)
    port = s.bind_to_random_port("tcp://127.0.0.1")
    s.close(linger=0)
    return port


def _logger(name, h):
    lg = logging.getLogger(name)
    lg.handlers[:] = [h]
    lg.setLevel(10)
    lg.propagate = False
    return lg


def test_resolve_log_port_default_skips_reflex_backend():
    cfg = {
        "servers": {
            "A": {"host": "127.0.0.1", "port": 8001},
            "UI": {"host": "127.0.0.1", "port": 8005, "reflex": "app"},
        }
    }
    assert resolve_log_port(cfg) == 8007


def test_resolve_log_port_explicit_and_collision():
    cfg = {"log_port": 9000, "servers": {"A": {"host": "h", "port": 8001}}}
    assert resolve_log_port(cfg) == 9000
    with pytest.raises(ValueError):
        resolve_log_port(
            {"log_port": 8001, "servers": {"A": {"host": "h", "port": 8001}}}
        )


def test_collector_writes_unified_file_and_ledger(tmp_path):
    ep = log_endpoint(_free_port())
    col = LogCollector(ep, tmp_path, "grp")
    col.start()
    h1 = JsonlSinkHandler("A", tmp_path, endpoint=ep)
    h2 = JsonlSinkHandler("B", tmp_path, endpoint=ep)
    _logger("A", h1).info("from A")
    _logger("B", h2).info("hash", extra={"event": "artifact_final", "sha256": "ff"})
    end = time.monotonic() + 5
    while time.monotonic() < end and not (
        (tmp_path / "helao_grp.jsonl").exists()
        and (tmp_path / "artifacts_grp.jsonl").exists()
    ):
        time.sleep(0.05)
    time.sleep(0.2)  # let the second record land after the first file appears
    h1.close()
    h2.close()
    col.stop()
    unified = [
        json.loads(x) for x in (tmp_path / "helao_grp.jsonl").read_bytes().splitlines()
    ]
    assert {r["server"] for r in unified} >= {"A", "B"}
    ledger = [
        json.loads(x)
        for x in (tmp_path / "artifacts_grp.jsonl").read_bytes().splitlines()
    ]
    assert [r["sha256"] for r in ledger] == ["ff"]
    assert not (tmp_path / "A.jsonl").exists()


def test_second_bind_fails(tmp_path):
    ep = log_endpoint(_free_port())
    a = LogCollector(ep, tmp_path, "g")
    a.start()
    with pytest.raises(zmq.ZMQError):
        LogCollector(ep, tmp_path / "b", "g").start()
    a.stop()


def test_read_logs_merges_dedups_sorts(tmp_path):
    import gzip

    recs = [
        {
            "ts": f"2026-10-26T00:00:0{i}.000000Z",
            "level": "INFO",
            "server": "A",
            "pid": 1,
            "seq": i,
            "msg": str(i),
        }
        for i in range(4)
    ]
    line = lambda r: (json.dumps(r) + "\n").encode()
    (tmp_path / "helao_g.jsonl").write_bytes(line(recs[3]) + line(recs[1]))
    with gzip.open(tmp_path / "helao_g_20261026T000000.jsonl.gz", "wb") as f:
        f.write(line(recs[0]) + line(recs[1]))
    (tmp_path / "A.jsonl").write_bytes(line(recs[2]))
    (tmp_path / "artifacts_g.jsonl").write_bytes(line({**recs[0], "seq": 99}))
    df = read_logs(tmp_path)
    assert list(df["seq"]) == [0, 1, 2, 3]
    assert list(read_logs(tmp_path, ledger=True)["seq"]) == [99]
    assert read_logs(tmp_path, server="nobody").empty
