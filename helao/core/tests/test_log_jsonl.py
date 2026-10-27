"""JSONL record serialization (spec §1)."""

import json
import logging
import sys

import pandas as pd
import pytest

from helao.helpers.log_jsonl import fingerprint, is_artifact, record_to_json


def _rec(msg="hello", level=logging.INFO, exc=None, **extra):
    r = logging.LogRecord(
        "PSTAT", level, "/x/action_host.py", 512, msg, None, exc, "setup"
    )
    r.created = 1_793_000_000.123456
    for k, v in extra.items():
        setattr(r, k, v)
    return r


def test_schema_keys_and_values():
    doc = json.loads(record_to_json(_rec(), 7))
    assert doc == {
        "ts": "2026-10-26T07:33:20.123456Z",
        "level": "INFO",
        "server": "PSTAT",
        "logger": "PSTAT",
        "pid": doc["pid"],
        "seq": 7,
        "func": "setup",
        "file": "action_host.py",
        "line": 512,
        "msg": "hello",
    }


def test_offset_shifts_ts():
    doc = json.loads(record_to_json(_rec(), 1, offset_seconds=2.5))
    assert doc["ts"] == "2026-10-26T07:33:22.623456Z"


def test_exc_present_only_with_traceback():
    assert "exc" not in json.loads(record_to_json(_rec(), 1))
    try:
        raise ValueError("boom")
    except ValueError:
        doc = json.loads(record_to_json(_rec(exc=sys.exc_info()), 1))
    assert doc["exc"].startswith("Traceback") and "ValueError: boom" in doc["exc"]


def test_extra_keys_included_when_set():
    doc = json.loads(
        record_to_json(_rec(event="artifact_final", sha256="ab", bytes=3), 1)
    )
    assert (doc["event"], doc["sha256"], doc["bytes"]) == ("artifact_final", "ab", 3)
    assert "reason" not in doc


def test_surrogates_and_newlines_stay_one_line(tmp_path):
    raw = record_to_json(_rec("a\nb\udcff\x00c"), 1)
    assert raw.endswith(b"\n") and raw.count(b"\n") == 1
    msg = json.loads(raw)["msg"]
    assert msg.startswith("a\nb") and "\\udcff" in msg
    p = tmp_path / "s.jsonl"  # a lone-surrogate JSON escape would break the file
    p.write_bytes(raw + record_to_json(_rec("ok"), 2))
    df = pd.read_json(p, lines=True, dtype=False)
    assert list(df["seq"]) == [1, 2] and "\\udcff" in df["msg"][0]


def test_round_trips_through_pandas(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_bytes(b"".join(record_to_json(_rec(f"m{i}"), i) for i in range(3)))
    df = pd.read_json(p, lines=True, dtype=False)
    assert list(df["seq"]) == [0, 1, 2]
    assert pd.to_datetime(df["ts"], utc=True).dt.tz is not None


def test_is_artifact_and_fingerprint():
    assert is_artifact(_rec(event="artifact_rewritten"))
    assert not is_artifact(_rec())
    a, b = _rec("same"), _rec("same")
    assert fingerprint(a) == fingerprint(b)
    assert fingerprint(_rec("same", level=logging.WARNING)) != fingerprint(a)
    try:
        raise KeyError("k")
    except KeyError:
        c = _rec("same", exc=sys.exc_info())
    assert fingerprint(c) != fingerprint(a)


import gzip
import os
import re
import threading
import time
from pathlib import Path

from helao.helpers import log_jsonl
from helao.helpers.log_jsonl import RotatingJsonlWriter


def _wait(pred, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def _lines(n, start=0):
    return [f'{{"seq": {i}}}\n'.encode() for i in range(start, start + n)]


def test_rotates_at_n_and_compresses_in_background(tmp_path):
    w = RotatingJsonlWriter(tmp_path, "helao_x", rotate_records=3, grace_s=0.2)
    for line in _lines(4):
        w.write(line)
    assert w.path.read_bytes() == b'{"seq": 3}\n'  # fresh live file at once
    assert _wait(lambda: list(tmp_path.glob("helao_x_*.jsonl.gz")))
    gz = next(tmp_path.glob("helao_x_*.jsonl.gz"))
    assert w.rotated_re.match(gz.name)
    assert gzip.open(gz).read() == b"".join(_lines(3))
    assert _wait(lambda: not list(tmp_path.glob("helao_x_*.jsonl")))  # grace over
    w.close()


def test_plain_copy_kept_during_grace(tmp_path):
    w = RotatingJsonlWriter(tmp_path, "s", rotate_records=1, grace_s=5.0)
    w.write(b"a\n")
    assert _wait(lambda: list(tmp_path.glob("s_*.jsonl.gz")))
    assert list(tmp_path.glob("s_*.jsonl"))  # still readable by a viewer
    w.close()


def test_leftover_plain_rotated_file_compressed_at_open(tmp_path):
    (tmp_path / "s_20260101T000000.jsonl").write_bytes(b"old\n")
    w = RotatingJsonlWriter(tmp_path, "s", grace_s=0)
    w.write(b"new\n")
    assert _wait(lambda: (tmp_path / "s_20260101T000000.jsonl.gz").exists())
    w.close()


def test_count_resumes_from_existing_live_file(tmp_path):
    (tmp_path / "s.jsonl").write_bytes(b"".join(_lines(2)))
    w = RotatingJsonlWriter(tmp_path, "s", rotate_records=3, grace_s=0)
    w.write(b"x\n")  # third record: rotates
    assert w.path.read_bytes() == b""
    w.close()


def test_retention_deletes_old_logs_not_ledger_or_other_stems(tmp_path):
    old = time.time() - 91 * 86400
    names = [
        "s_20250101T000000.jsonl.gz",
        "artifacts_s_20250101T000000.jsonl.gz",
        "s_2_20250101T000000.jsonl.gz",
    ]
    for n in names:
        (tmp_path / n).write_bytes(b"")
        os.utime(tmp_path / n, (old, old))
    young = tmp_path / f"s_{time.strftime('%Y%m%dT%H%M%S')}.jsonl.gz"
    young.write_bytes(b"")
    RotatingJsonlWriter(tmp_path, "s").write(b"x\n")
    RotatingJsonlWriter(tmp_path, "artifacts_s", retain_days=None).write(b"x\n")
    assert not (tmp_path / names[0]).exists()
    assert young.exists()
    assert (tmp_path / names[1]).exists() and (tmp_path / names[2]).exists()


def test_rotation_retries_when_rename_is_refused(tmp_path, monkeypatch, capsys):
    real = os.rename
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("in use")
        return real(src, dst)

    monkeypatch.setattr(log_jsonl.os, "rename", flaky)
    w = RotatingJsonlWriter(tmp_path, "s", rotate_records=2, grace_s=0)
    for line in _lines(2):
        w.write(line)  # rotation refused: keeps appending
    assert w.path.read_bytes() == b"".join(_lines(2))
    assert "rotation" in capsys.readouterr().err
    w._retry_at = 0  # make the retry due now
    w.write(b"z\n")
    assert w.path.read_bytes() == b""
    w.close()


def test_shared_writer_counts_live_file_and_survives_peer_rotation(tmp_path):
    a = RotatingJsonlWriter(tmp_path, "s", rotate_records=2, grace_s=60, shared=True)
    b = RotatingJsonlWriter(tmp_path, "s", rotate_records=10, grace_s=60, shared=True)
    a.write(b"a1\n")
    b.write(b"b1\n")  # a's count 1; live has 2 lines
    a.write(b"a2\n")  # a rotates
    b.write(b"b2\n")  # b must notice and reopen
    assert (tmp_path / "s.jsonl").read_bytes() == b"b2\n"
    rotated = next(tmp_path.glob("s_*.jsonl"))
    assert sorted(rotated.read_bytes().splitlines()) == [b"a1", b"a2", b"b1"]
    a.close()
    b.close()


from helao.helpers.log_jsonl import SequenceDeduper


def _run(d, seq):
    out = []
    for x in seq:
        out += d.feed(x, x)
    return out


def test_single_repeat_collapses():
    d = SequenceDeduper(interval=10, clock=lambda: 0.0)
    out = _run(d, "AAAAB") + d.flush()
    assert out == [
        ("record", "A"),
        ("record", "A"),
        ("summary", 1, 2, "A"),
        ("record", "B"),
    ]


def test_cycle_of_three_repeated_twenty_times():
    d = SequenceDeduper(interval=10, clock=lambda: 0.0)
    out = _run(d, "ABC" * 20 + "Z")
    records = [o[1] for o in out if o[0] == "record"]
    assert records == list("ABCABC") + ["Z"]
    assert ("summary", 3, 18, "C") in out


def test_broken_cycle_writes_summary_then_held_partial():
    d = SequenceDeduper(interval=10, clock=lambda: 0.0)
    out = _run(d, "ABCABCABCAB" + "Q")
    assert out[-4:] == [
        ("summary", 3, 1, "C"),
        ("record", "A"),
        ("record", "B"),
        ("record", "Q"),
    ]


def test_flush_reports_pending_count_and_partial():
    d = SequenceDeduper(interval=10, clock=lambda: 0.0)
    _run(d, "ABABABA")
    assert d.flush() == [("summary", 2, 1, "B"), ("record", "A")]
    assert d.flush() == []


def test_interval_yields_periodic_summaries():
    now = [0.0]
    d = SequenceDeduper(interval=10, clock=lambda: now[0])
    _run(d, "AA")  # cycle confirmed at t=0
    out = []
    for t in range(1, 25):
        now[0] = float(t)
        out += d.feed("A", "A")
    summaries = [o for o in out if o[0] == "summary"]
    assert [s[2] for s in summaries] == [10, 10]


def test_interval_zero_disables():
    d = SequenceDeduper(interval=0)
    assert [o[1] for o in _run(d, "AAAA")] == list("AAAA")


def test_longest_period_bound():
    d = SequenceDeduper(max_period=2, interval=10, clock=lambda: 0.0)
    out = _run(d, "ABC" * 4)
    assert all(o[0] == "record" for o in out)


def test_cycle_containing_adjacent_repeat_collapses():
    # "AAB"*20 + "Z": ABBA-style prefixes confirm p=1 first, but the history is
    # never cleared, so p=3 is confirmed at item 6 (6 records emitted). The
    # remaining 54 items are 18 whole cycles, all suppressed; Z closes it.
    d = SequenceDeduper(interval=10, clock=lambda: 0.0)
    out = _run(d, "AAB" * 20 + "Z")
    assert [o for o in out if o[0] == "summary"] == [("summary", 3, 18, "B")]
    assert sum(o[0] == "record" for o in out) == 61 - 54  # 7 incl. Z

    # "ABB"*20 + "Z": p=1 starts at item 3 (BB), breaks at item 4, p=3 is
    # confirmed at item 7 (7 emitted). Remaining 53 items = 17 whole cycles
    # (51 suppressed) + 2 held ("BB"), which are emitted after the summary.
    d = SequenceDeduper(interval=10, clock=lambda: 0.0)
    out = _run(d, "ABB" * 20 + "Z")
    assert [o for o in out if o[0] == "summary"] == [("summary", 3, 17, "A")]
    assert sum(o[0] == "record" for o in out) == 61 - 51  # 10


def test_unexpected_rename_error_keeps_writer_usable(tmp_path, monkeypatch):
    real = os.rename
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FileExistsError("exists")
        return real(src, dst)

    monkeypatch.setattr(log_jsonl.os, "rename", flaky)
    w = RotatingJsonlWriter(tmp_path, "s", rotate_records=2, grace_s=0)
    for line in _lines(5):
        w.write(line)  # must not raise
    assert w.path.read_bytes() == b"".join(_lines(5))
    w.close()


def test_next_write_never_waits_for_compressor(tmp_path, monkeypatch):
    gate = threading.Event()
    real = gzip.open

    def slow(*a, **k):
        gate.wait(10)
        return real(*a, **k)

    monkeypatch.setattr(log_jsonl.gzip, "open", slow)
    w = RotatingJsonlWriter(tmp_path, "s", rotate_records=2, grace_s=0)
    w.write(b"a\n")
    w.write(b"b\n")  # rotates; compressor now blocked
    w.write(b"c\n")  # must return
    assert w.path.read_bytes() == b"c\n"
    assert not list(tmp_path.glob("s_*.jsonl.gz"))
    gate.set()
    assert _wait(lambda: list(tmp_path.glob("s_*.jsonl.gz")))
    w.close()


def test_concurrent_compressors_produce_one_valid_gz(tmp_path):
    plain = tmp_path / "s_20260101T000000.jsonl"
    body = b"".join(
        f'{{"seq": {i}, "x": "{os.urandom(8).hex()}"}}\n'.encode()
        for i in range(150_000)
    )
    plain.write_bytes(body)
    barrier = threading.Barrier(2)
    writers = [RotatingJsonlWriter(tmp_path, "s", grace_s=0) for _ in range(2)]

    def go(w):
        barrier.wait()
        w.write(b"x\n")  # first write scans the dir and queues the rotated file

    gz = tmp_path / "s_20260101T000000.jsonl.gz"
    stop, partial = threading.Event(), []

    def watch():  # a .gz that exists must already be complete (temp + replace)
        while not stop.is_set():
            if gz.exists():
                try:
                    gzip.open(gz).read()
                except (EOFError, OSError):
                    partial.append(1)
            time.sleep(0.001)

    watcher = threading.Thread(target=watch)
    watcher.start()
    threads = [threading.Thread(target=go, args=(w,)) for w in writers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for w in writers:
        w.close()  # waits for the queued compressions
    stop.set()
    watcher.join()
    assert not partial
    assert gzip.open(gz).read() == body
    assert not list(tmp_path.glob("*.tmp"))
    assert not plain.exists()


def test_orphaned_compressor_tmp_swept_at_start(tmp_path):
    old = time.time() - 2 * 3600
    stale = tmp_path / "s_20260101T000000.jsonl.gz.1.2.tmp"
    fresh = tmp_path / "s_20260102T000000.jsonl.gz.1.2.tmp"
    other = tmp_path / "t_20260101T000000.jsonl.gz.1.2.tmp"
    for p in (stale, fresh, other):
        p.write_bytes(b"")
    for p in (stale, other):
        os.utime(p, (old, old))
    RotatingJsonlWriter(tmp_path, "s").write(b"x\n")
    assert not stale.exists() and fresh.exists() and other.exists()


def test_write_many_rotates_at_the_threshold_line(tmp_path):
    w = RotatingJsonlWriter(tmp_path, "m", rotate_records=3, grace_s=0.2)
    w.write_many(_lines(7))
    # 7 lines at N=3: two rotated files of exactly 3, 1 line live
    assert w.path.read_bytes() == b'{"seq": 6}\n'
    assert _wait(lambda: len(list(tmp_path.glob("m_*.jsonl*"))) == 2)
    got = sorted(
        gzip.open(p).read() if p.suffix == ".gz" else p.read_bytes()
        for p in tmp_path.glob("m_*.jsonl*")
    )
    assert got == sorted([b"".join(_lines(3)), b"".join(_lines(3, 3))])
    w.close()


def test_write_many_is_one_write_per_batch(tmp_path, monkeypatch):
    w = RotatingJsonlWriter(tmp_path, "o", rotate_records=100, shared=True)
    w.write(b"x\n")  # starts the writer
    opens = []
    real = open

    def counting(p, mode="r", *a, **k):
        if str(p).endswith("o.jsonl"):
            opens.append(mode)
        return real(p, mode, *a, **k)

    monkeypatch.setattr("builtins.open", counting)
    w.write_many([b"a\n"] * 10)
    assert opens == ["ab"]
    w.close()


def test_read_logs_reports_a_damaged_gz(tmp_path, capsys):
    from helao.helpers.log_jsonl import read_logs

    good = gzip.compress(
        b'{"ts":"2026-01-01T00:00:00Z","server":"s","pid":1,"seq":1}\n'
    )
    (tmp_path / "s_20260101T000000.jsonl.gz").write_bytes(good)
    (tmp_path / "s_20260102T000000.jsonl.gz").write_bytes(good[:-12])  # truncated
    df = read_logs(tmp_path)
    assert len(df) == 1
    assert "s_20260102T000000.jsonl.gz" in capsys.readouterr().err


@pytest.fixture
def no_server_key(monkeypatch):
    from helao.helpers import helao_logging

    monkeypatch.setattr(helao_logging, "SERVER_KEY", None)
    return helao_logging


def _named(name, seq=1):
    r = _rec()
    r.name = name
    return json.loads(record_to_json(r, seq))


def test_server_is_the_server_key_and_logger_is_the_module(no_server_key):
    no_server_key.set_server_key("PSTAT")
    doc = _named("dispatcher")
    assert (doc["server"], doc["logger"]) == ("PSTAT", "dispatcher")


def test_without_a_server_key_server_is_the_record_name(no_server_key):
    doc = _named("dispatcher")
    assert (doc["server"], doc["logger"]) == ("dispatcher", "dispatcher")


def test_read_logs_keeps_records_differing_only_in_logger(tmp_path):
    from helao.helpers.log_jsonl import read_logs

    base = {"ts": "2026-01-01T00:00:00Z", "level": "INFO", "server": "S", "pid": 1}
    a = {**base, "logger": "api", "seq": 1, "msg": "a"}
    b = {**base, "logger": "app", "seq": 1, "msg": "b"}
    old = {**base, "seq": 1, "msg": "old"}  # pre-logger record: no key
    lines = [a, b, a, old, dict(old)]  # a and old are replayed
    (tmp_path / "x.jsonl").write_text("".join(json.dumps(r) + "\n" for r in lines))
    df = read_logs(tmp_path)
    assert sorted(df["msg"]) == ["a", "b", "old"]


def test_env_server_key_applies_to_import_time_loggers(tmp_path):
    import os
    import subprocess

    code = (
        "import json,logging;"
        "from helao.helpers.log_jsonl import record_to_json;"
        "r=logging.LogRecord('xafs',20,'f.py',1,'m',None,None);"
        "print(json.loads(record_to_json(r,1))['server'])"
    )
    env = {**os.environ, "HELAO_SERVER_KEY": "PSTAT"}
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True
    )
    assert out.stdout.strip() == "PSTAT", out.stderr


def test_launchers_export_the_server_key_before_any_helao_import():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    for name in ("fast_launcher", "bokeh_launcher", "reflex_launcher"):
        tree = ast.parse((root / f"{name}.py").read_text(encoding="utf-8"))
        setter = first_helao = None
        for node in tree.body:
            if (
                isinstance(node, ast.If)
                and "HELAO_SERVER_KEY" in ast.unparse(node)
                and setter is None
            ):
                setter = node.lineno
            mod = getattr(node, "module", None) or ""
            names = [a.name for a in getattr(node, "names", [])]
            if (
                isinstance(node, (ast.Import, ast.ImportFrom))
                and first_helao is None
                and (
                    mod.startswith("helao") or any(n.startswith("helao") for n in names)
                )
            ):
                first_helao = node.lineno
        assert setter is not None, name
        assert "os.environ['HELAO_SERVER_KEY'] = sys.argv[2]" in ast.unparse(tree), name
        assert first_helao is None or setter < first_helao, name
