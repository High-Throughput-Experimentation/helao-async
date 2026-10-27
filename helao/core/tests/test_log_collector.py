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


def _start_collector(log_dir, prefix):
    """Start a collector on a free port. The probe port can be taken by another
    process between _free_port() closing it and bind, so retry on a new one."""
    for _ in range(10):
        ep = log_endpoint(_free_port())
        col = LogCollector(ep, log_dir, prefix)
        try:
            col.start()
            return ep, col
        except zmq.ZMQError:
            continue
    raise RuntimeError("no free port for the collector")


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
    ep, col = _start_collector(tmp_path, "grp")
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
    ep, a = _start_collector(tmp_path, "g")
    b = LogCollector(ep, tmp_path / "b", "g")
    made = []
    real = zmq.Context.instance().socket
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            zmq.Context.instance(),
            "socket",
            lambda *x, **k: made.append(real(*x, **k)) or made[-1],
        )
        with pytest.raises(zmq.ZMQError):
            b.start()
    assert made and all(m.closed for m in made)
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


def _rec(i, **kw):
    r = {
        "ts": f"2026-10-26T00:00:0{i}.000000Z",
        "level": "INFO",
        "server": "A",
        "pid": 1,
        "seq": i,
        "msg": str(i),
    }
    return {**r, **kw}


def _line(r):
    return (json.dumps(r) + "\n").encode()


def test_stop_respects_deadline_under_continuous_input(tmp_path):
    import threading

    ep, col = _start_collector(tmp_path, "g")
    thread = col._thread
    push = zmq.Context.instance().socket(zmq.PUSH)
    push.setsockopt(zmq.LINGER, 0)
    push.setsockopt(zmq.SNDTIMEO, 50)
    push.connect(ep)
    quit_ = threading.Event()
    data = _line(_rec(1))

    def pump():
        while not quit_.is_set():
            try:
                push.send(data)
            except zmq.ZMQError:
                pass

    t = threading.Thread(target=pump)
    t.start()
    time.sleep(0.3)
    t0 = time.monotonic()
    col.stop(drain_s=0.5)
    took = time.monotonic() - t0
    quit_.set()
    t.join()
    push.close(linger=0)
    assert took < 2.0
    assert not thread.is_alive()
    assert col._log._fh is None and col._sock.closed


def test_stop_without_start_is_noop(tmp_path):
    LogCollector(log_endpoint(1), tmp_path, "g").stop()


def test_resolve_log_port_range_and_rpc_ports():
    from helao.core.rpc.zmq_rpc import derive_rpc_port

    srv = {"A": {"host": "h", "port": 8001}}
    rpc = derive_rpc_port(8001)
    for bad in (0, 65536, -1, rpc):
        with pytest.raises(ValueError):
            resolve_log_port({"log_port": bad, "servers": srv})
    with pytest.raises(ValueError):
        resolve_log_port({"servers": {"A": {"host": "h", "port": 65535}}})
    # default steps over an RPC port
    cfg = {
        "servers": {
            "A": {"host": "h", "port": 8001},
            "B": {"host": "h", "port": rpc - 1},
        }
    }
    assert resolve_log_port(cfg) not in {8001, rpc - 1, rpc, derive_rpc_port(rpc - 1)}


def test_read_logs_partial_last_line_and_corrupt_middle(tmp_path, capsys):
    good = b"".join(_line(_rec(i)) for i in range(5))
    (tmp_path / "helao_g.jsonl").write_bytes(good + b'{"ts": "2026-10-26T00:0')
    assert list(read_logs(tmp_path)["seq"]) == [0, 1, 2, 3, 4]
    (tmp_path / "helao_g.jsonl").write_bytes(
        _line(_rec(0)) + b"not json\n" + _line(_rec(2))
    )
    assert list(read_logs(tmp_path)["seq"]) == [0, 2]
    err = capsys.readouterr().err
    assert "skipped 1" in err and "helao_g.jsonl" in err


def test_read_logs_dedup_key_includes_ts(tmp_path):
    a, b = _rec(1), _rec(1, ts="2026-10-26T00:00:09.000000Z")
    (tmp_path / "helao_g.jsonl").write_bytes(_line(a) + _line(b) + _line(a))
    assert len(read_logs(tmp_path)) == 2


def test_read_logs_skips_tmp_and_empty_dir(tmp_path):
    empty = read_logs(tmp_path)
    assert empty.empty and str(empty["ts"].dtype) == "datetime64[us, UTC]"
    assert str(empty["pid"].dtype) == "int64" and str(empty["seq"].dtype) == "int64"
    (tmp_path / "helao_g_20261026T000000.jsonl.gz.1.2.tmp").write_bytes(b"junk")
    assert read_logs(tmp_path).empty
    (tmp_path / "helao_g.jsonl").write_bytes(_line(_rec(0)))
    full = read_logs(tmp_path)
    assert str(full["ts"].dtype) == str(empty["ts"].dtype)
    assert str(full["pid"].dtype) == "int64"


def test_rpc_port_offset_mirrors_zmq_rpc():
    from helao.core.rpc import zmq_rpc
    from helao.helpers import log_collector

    assert log_collector.RPC_PORT_OFFSET == zmq_rpc.RPC_PORT_OFFSET


def test_resolve_log_port_avoids_plate_aligner_ports():
    servers = {
        "A": {
            "host": "h",
            "port": 8001,
            "params": {"enable_aligner": True, "bokeh_port": 8002},
        },
        # implicit aligner default: port + 1000 = 8001 is also taken by A's own port
        "B": {"host": "h", "port": 7501, "params": {"enable_aligner": True}},
    }
    assert resolve_log_port({"servers": servers}) == 8003  # 8002 is A's aligner
    with pytest.raises(ValueError):
        resolve_log_port({"log_port": 8002, "servers": servers})
    only_b = {"B": servers["B"]}  # implicit aligner at 8501
    assert resolve_log_port({"log_port": 8100, "servers": only_b}) == 8100
    with pytest.raises(ValueError):
        resolve_log_port({"log_port": 8501, "servers": only_b})


def test_resolve_log_port_null_aligner_bokeh_port():
    servers = {
        "A": {
            "host": "h",
            "port": 8001,
            "params": {"enable_aligner": True, "bokeh_port": None},
        }
    }
    # null bokeh_port == port + 1000 == 9001, which the log port must avoid
    assert resolve_log_port({"log_port": 9000, "servers": servers}) == 9000
    assert resolve_log_port({"servers": servers}) != 9001
    with pytest.raises(ValueError):
        resolve_log_port({"log_port": 9001, "servers": servers})
