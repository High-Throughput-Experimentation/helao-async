"""JsonlSinkHandler: dedup, ZMQ send, fallback, replay, marker, ledger (spec §1)."""

import json
import logging
import logging.config
import os
import threading
import time
from pathlib import Path

import pytest
import zmq

from helao.helpers.log_jsonl import HWM, LEDGER_FRAME, SOCK_BUF, JsonlSinkHandler


def _logger(name, handler):
    lg = logging.getLogger(name)
    lg.handlers[:] = [handler]
    lg.setLevel(10)
    lg.propagate = False
    return lg


def _read(path):
    p = Path(path)
    return [json.loads(x) for x in p.read_bytes().splitlines()] if p.exists() else []


def _pull(port=None):
    s = zmq.Context.instance().socket(zmq.PULL)
    s.setsockopt(zmq.LINGER, 0)
    if port is None:
        port = s.bind_to_random_port("tcp://127.0.0.1")
    else:
        s.bind(f"tcp://127.0.0.1:{port}")
    return s, port


def _recv_all(sock, timeout=2.0):
    out, end = [], time.monotonic() + timeout
    while time.monotonic() < end:
        if sock.poll(50):
            out.append(sock.recv_multipart())
        elif out:
            break
    return out


def test_no_endpoint_writes_own_file(tmp_path):
    h = JsonlSinkHandler("SRV", tmp_path)
    lg = _logger("t_noep", h)
    lg.info("one")
    lg.warning("two")
    h.close()
    rows = _read(tmp_path / "SRV.jsonl")
    assert [r["msg"] for r in rows] == ["one", "two"] and [r["seq"] for r in rows] == [
        1,
        2,
    ]


def test_sends_to_launcher_when_connected(tmp_path):
    pull, port = _pull()
    h = JsonlSinkHandler("SRV", tmp_path, endpoint=f"tcp://127.0.0.1:{port}")
    lg = _logger("t_send", h)
    lg.info("hello")
    frames = _recv_all(pull)
    assert len(frames) == 1 and json.loads(frames[0][0])["msg"] == "hello"
    assert not (tmp_path / "SRV.jsonl").exists()
    h.close()
    pull.close()


def test_artifact_records_use_ledger_frame_and_skip_dedup(tmp_path):
    pull, port = _pull()
    h = JsonlSinkHandler("SRV", tmp_path, endpoint=f"tcp://127.0.0.1:{port}")
    lg = _logger("t_ledger", h)
    for _ in range(3):
        lg.info("artifact_final act x", extra={"event": "artifact_final", "path": "x"})
    frames = _recv_all(pull)
    assert len(frames) == 3 and all(f[0] == LEDGER_FRAME for f in frames)
    h.close()
    pull.close()


def test_dedup_applies_and_summary_fields(tmp_path):
    h = JsonlSinkHandler("SRV", tmp_path)
    lg = _logger("t_dedup", h)
    for _ in range(20):
        lg.error("A")
        lg.error("B")
    lg.info("done")
    h.close()
    rows = _read(tmp_path / "SRV.jsonl")
    assert [r["msg"] for r in rows if "repeat_count" not in r] == [
        "A",
        "B",
        "A",
        "B",
        "done",
    ]
    (s,) = [r for r in rows if "repeat_count" in r]
    assert (s["repeat_count"], s["repeat_period"]) == (18, 2)


def test_same_message_different_exceptions_not_collapsed(tmp_path):
    h = JsonlSinkHandler("SRV", tmp_path)
    lg = _logger("t_exc", h)
    for exc in (ValueError, KeyError, ValueError, KeyError):
        try:
            raise exc("x")
        except Exception:
            lg.exception("failed")
    h.close()
    rows = _read(tmp_path / "SRV.jsonl")
    assert [r["exc"].splitlines()[-1].split(":")[0] for r in rows[:2]] == [
        "ValueError",
        "KeyError",
    ]


def test_launcher_loss_replays_then_falls_back_and_marks_on_reattach(tmp_path):
    pull, port = _pull()
    ep = f"tcp://127.0.0.1:{port}"
    h = JsonlSinkHandler("SRV", tmp_path, endpoint=ep, dedup_interval=0)
    lg = _logger("t_loss", h)
    for i in range(5):
        lg.info(f"m{i}")
    got = [json.loads(f[0])["seq"] for f in _recv_all(pull)]
    pull.close()  # launcher dies
    end = time.monotonic() + 5
    while time.monotonic() < end and not (tmp_path / "SRV.jsonl").exists():
        lg.info("probe")
        time.sleep(0.05)
    fb = _read(tmp_path / "SRV.jsonl")
    assert {r["seq"] for r in fb} >= set(range(1, 6))  # replayed (may duplicate)
    pull2, _ = _pull(port)  # a --reconnect launcher
    end, frames = time.monotonic() + 5, []
    while time.monotonic() < end and not frames:
        lg.info("back")
        frames = _recv_all(pull2, 0.3)
    msgs = [json.loads(f[-1])["msg"] for f in frames]
    assert any(m.endswith(f"records went to {tmp_path / 'SRV.jsonl'}") for m in msgs)
    assert got == [1, 2, 3, 4, 5]
    h.close()
    pull2.close()


def test_never_blocks_when_collector_stops_reading(tmp_path):
    pull, port = _pull()
    pull.setsockopt(zmq.RCVHWM, 10)
    h = JsonlSinkHandler(
        "SRV", tmp_path, endpoint=f"tcp://127.0.0.1:{port}", dedup_interval=0
    )
    lg = _logger("t_block", h)
    t0 = time.monotonic()
    pad = "x" * 4000  # 40 MB total: more than the kernel and zmq buffers hold
    for i in range(10_000):
        lg.info(f"r{i} {pad}")
    assert time.monotonic() - t0 < 5.0
    assert len(_read(tmp_path / "SRV.jsonl")) > 0  # overflow spilled
    h.close()
    pull.close()


def test_fork_resets_socket_and_writers(tmp_path):
    pull, port = _pull()
    h = JsonlSinkHandler("SRV", tmp_path, endpoint=f"tcp://127.0.0.1:{port}")
    old_sock = h._sock
    lg = _logger("t_fork", h)
    lg.info("before fork")
    old_dedup = h.deduper
    h._spilled = 5
    h._pid = -1  # what a forked child observes
    lg.info("after fork")
    assert h._sock is not old_sock and h._pid == os.getpid()
    assert h.deduper is not old_dedup and h._spilled == 0
    assert [json.loads(e[0])["msg"] for e in h.recent] == ["after fork"]
    h.close()
    pull.close()


def test_survives_dictconfig_shutdown(tmp_path):
    pull, port = _pull()
    h = JsonlSinkHandler("SRV", tmp_path, endpoint=f"tcp://127.0.0.1:{port}")
    lg = _logger("t_dictcfg", h)
    lg.info("before")
    assert len(_recv_all(pull)) == 1
    # uvicorn.Config does this: logging.shutdown() closes every live handler
    logging.config.dictConfig({"version": 1, "disable_existing_loggers": False})
    if h not in lg.handlers:
        lg.addHandler(h)
    lg.info("after")
    frames = _recv_all(pull)
    assert [json.loads(f[-1])["msg"] for f in frames] == ["after"]
    assert not (tmp_path / "SRV.jsonl").exists()
    h.close()
    pull.close()


def test_emit_after_close_recreates_writers(tmp_path):
    h = JsonlSinkHandler("SRV", tmp_path)
    lg = _logger("t_reuse", h)
    lg.info("one")
    h.close()
    lg.info("two")
    h.close()
    assert [r["msg"] for r in _read(tmp_path / "SRV.jsonl")] == ["one", "two"]


def _rows(*socks_frames, path):
    out = {}
    for frames in socks_frames:
        for f in frames:
            d = json.loads(f[-1])
            out[(d["pid"], d["seq"])] = d
    for d in _read(path):
        out[(d["pid"], d["seq"])] = d
    return out


def test_replay_covers_everything_in_flight(tmp_path):
    pull, port = _pull_hwm()
    h = JsonlSinkHandler(
        "SRV", tmp_path, endpoint=f"tcp://127.0.0.1:{port}", dedup_interval=0
    )
    lg = _logger("t_inflight", h)
    i, after = 0, None
    while i < 100_000 and (after is None or i < after + 300):
        i += 1
        lg.info(f"short record {i}")
        if after is None and (tmp_path / "SRV.jsonl").exists():
            after = i
        if i % 500 == 0:
            time.sleep(0.01)  # let the io thread move bytes to the kernel
    assert after is not None, "sender never hit Again"
    got = [pull.recv_multipart() for _ in range(10)]  # a small prefix only
    pull.close()  # the launcher dies with its queue undrained
    time.sleep(0.3)
    end = time.monotonic() + 5
    while (
        time.monotonic() < end and "probe" not in (tmp_path / "SRV.jsonl").read_text()
    ):
        lg.info("probe")  # the first refused send triggers the replay
        time.sleep(0.05)
    n = h.seq
    h.close()
    rows = _rows(got, path=tmp_path / "SRV.jsonl")
    missing = set(range(1, n + 1)) - {k[1] for k in rows}
    assert not missing, f"{len(missing)} of {n} records lost"


def _pull_hwm():
    s = zmq.Context.instance().socket(zmq.PULL)
    s.setsockopt(zmq.LINGER, 0)
    s.setsockopt(zmq.RCVHWM, HWM)
    s.setsockopt(zmq.RCVBUF, SOCK_BUF)
    return s, s.bind_to_random_port("tcp://127.0.0.1")


def test_slow_reader_does_not_duplicate_fallback_rows(tmp_path):
    pull = zmq.Context.instance().socket(zmq.PULL)
    pull.setsockopt(zmq.LINGER, 0)
    pull.setsockopt(zmq.RCVHWM, 100)
    pull.setsockopt(zmq.RCVBUF, SOCK_BUF)
    port = pull.bind_to_random_port("tcp://127.0.0.1")
    stop = threading.Event()

    def reader():  # alive, but slower than the sender
        while not stop.is_set():
            for _ in range(20):
                if pull.poll(0):
                    pull.recv_multipart()
            time.sleep(0.005)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    h = JsonlSinkHandler(
        "SRV", tmp_path, endpoint=f"tcp://127.0.0.1:{port}", dedup_interval=0
    )
    flips = []
    orig = h._replay
    h._replay = lambda: (flips.append(1), orig())
    lg = _logger("t_slow", h)
    pad = "x" * 500
    for i in range(6000):
        lg.info(f"r{i} {pad}")
    stop.set()
    t.join()
    h.close()
    pull.close()
    assert len(flips) >= 2, "the reader was never slow enough to flip"
    rows = _read(tmp_path / "SRV.jsonl")
    keys = [(r["pid"], r["seq"]) for r in rows]
    assert len(keys) == len(set(keys)) and keys


def test_dedup_collapses_on_send_path(tmp_path):
    pull, port = _pull()
    h = JsonlSinkHandler("SRV", tmp_path, endpoint=f"tcp://127.0.0.1:{port}")
    lg = _logger("t_dedup_send", h)
    for _ in range(20):
        lg.error("A")
        lg.error("B")
    lg.info("done")
    h.close()
    docs = [json.loads(f[-1]) for f in _recv_all(pull)]
    assert [d["msg"] for d in docs if "repeat_count" not in d] == [
        "A",
        "B",
        "A",
        "B",
        "done",
    ]
    (s,) = [d for d in docs if "repeat_count" in d]
    assert (s["repeat_count"], s["repeat_period"]) == (18, 2)
    assert not (tmp_path / "SRV.jsonl").exists()
    pull.close()


def test_failed_reconnect_spills_instead_of_losing(tmp_path, monkeypatch):
    pull, port = _pull()
    h = JsonlSinkHandler("SRV", tmp_path, endpoint=f"tcp://127.0.0.1:{port}")
    lg = _logger("t_reconn_fail", h)
    h.close()  # as logging.shutdown does

    def boom(*a, **k):
        raise zmq.ZMQError(zmq.ETERM)

    monkeypatch.setattr(h, "_connect", boom)
    lg.info("kept")
    assert [r["msg"] for r in _read(tmp_path / "SRV.jsonl")] == ["kept"]
    h.close()
    pull.close()


def test_connect_failure_closes_sockets(tmp_path, monkeypatch):
    ctx = zmq.Context.instance()
    made = []
    real = ctx.socket

    def spy(*a, **k):
        s = real(*a, **k)
        made.append(s)
        return s

    monkeypatch.setattr(ctx, "socket", spy)
    with pytest.raises(zmq.ZMQError):
        JsonlSinkHandler("X", tmp_path, endpoint="tcp://")
    monkeypatch.undo()
    assert made and all(s.closed for s in made)


def test_min_level_drops_ordinary_records_but_not_artefacts(tmp_path):
    h = JsonlSinkHandler("L", tmp_path, min_level=30)
    lg = _logger("t_minlevel", h)
    lg.info("quiet")
    lg.warning("loud")
    lg.info("hash", extra={"event": "artifact_final", "kind": "data"})
    h.close()
    assert [r["msg"] for r in _read(tmp_path / "L.jsonl") if "event" not in r] == [
        "loud"
    ]
    (led,) = _read(tmp_path / "artifacts_L.jsonl")
    assert led["event"] == "artifact_final"


def test_replay_spills_with_one_write_per_writer(tmp_path, monkeypatch):
    from helao.helpers import log_jsonl

    h = JsonlSinkHandler("R", tmp_path)
    lg = _logger("t_replay_many", h)
    for i in range(5):
        lg.info(f"m{i}")
    for e in h.recent:
        e[2] = True  # pretend all were sent
    calls = []
    real = log_jsonl.RotatingJsonlWriter.write_many
    monkeypatch.setattr(
        log_jsonl.RotatingJsonlWriter,
        "write_many",
        lambda self, lines: calls.append(len(lines)) or real(self, lines),
    )
    h._replay()
    h.close()
    assert calls == [5]
    assert len(_read(tmp_path / "R.jsonl")) == 10  # 5 original + 5 replayed


def test_make_logger_twice_leaves_one_sink_and_one_console(tmp_path, monkeypatch):
    from logging.handlers import QueueHandler

    from helao.helpers import helao_logging

    monkeypatch.delenv("HELAO_LOG_ENDPOINT", raising=False)
    cfg = {"webhook": "http://127.0.0.1:9/x", "payload": {}}
    for _ in range(2):
        lg = helao_logging.make_logger(
            "t_twice", log_dir=str(tmp_path), email_config=cfg
        )
    try:
        kinds = [type(h) for h in lg.handlers]
        assert kinds.count(JsonlSinkHandler) == 1
        assert kinds.count(logging.StreamHandler) == 1
        assert kinds.count(QueueHandler) == 1
    finally:
        for h in list(lg.handlers):
            lg.removeHandler(h)
            listener = getattr(h, "listener", None)
            if listener:
                listener.stop()
            h.close()
