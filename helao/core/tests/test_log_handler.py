"""JsonlSinkHandler: dedup, ZMQ send, fallback, replay, marker, ledger (spec §1)."""

import json
import logging
import os
import time
from pathlib import Path

import zmq

from helao.helpers.log_jsonl import LEDGER_FRAME, JsonlSinkHandler


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
    h._pid = -1  # what a forked child observes
    lg = _logger("t_fork", h)
    lg.info("after fork")
    assert h._sock is not old_sock and h._pid == os.getpid()
    h.close()
    pull.close()
