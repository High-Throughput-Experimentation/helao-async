"""Tailing JSONL logs for the /logs page (spec §4)."""

import json
import os
import time

from helao.ui.shared import log_tail


def _line(seq, server="A", level="INFO", msg=None, ts=None):
    ts = ts or f"2026-10-26T00:00:{seq % 60:02d}.000000Z"
    return (
        json.dumps(
            {
                "ts": ts,
                "level": level,
                "server": server,
                "pid": 1,
                "seq": seq,
                "msg": msg or f"m{seq}",
            }
        )
        + "\n"
    ).encode()


def test_init_reads_newest_n_and_poll_reads_appends(tmp_path):
    f = tmp_path / "helao_g.jsonl"
    f.write_bytes(b"".join(_line(i) for i in range(10)))
    recs, cur = log_tail.tail_init(tmp_path, n=3)
    assert [r["seq"] for r in recs] == [7, 8, 9]
    with open(f, "ab") as fh:
        fh.write(_line(10) + b'{"partial": ')
    recs, cur = log_tail.tail_poll(tmp_path, cur)
    assert [r["seq"] for r in recs] == [10]  # partial line waits
    with open(f, "ab") as fh:
        fh.write(
            b'1, "ts": "2026-10-26T00:01:00.000000Z", "server": "A", "pid": 1, "seq": 11, "level": "INFO", "msg": "x"}\n'
        )
    recs, _ = log_tail.tail_poll(tmp_path, cur)
    assert [r["seq"] for r in recs] == [11]


def test_rotation_finishes_renamed_file_then_new(tmp_path):
    f = tmp_path / "helao_g.jsonl"
    f.write_bytes(_line(1))
    _, cur = log_tail.tail_init(tmp_path)
    with open(f, "ab") as fh:
        fh.write(_line(2))  # written after the last poll
    os.rename(f, tmp_path / "helao_g_20261026T000000.jsonl")
    f.write_bytes(_line(3))
    recs, _ = log_tail.tail_poll(tmp_path, cur)
    assert [r["seq"] for r in recs] == [2, 3]


def test_rotation_with_plain_copy_gone_emits_warning_row(tmp_path):
    f = tmp_path / "helao_g.jsonl"
    f.write_bytes(_line(1))
    _, cur = log_tail.tail_init(tmp_path)
    f.unlink()
    f.write_bytes(_line(5))
    recs, _ = log_tail.tail_poll(tmp_path, cur)
    assert recs[0]["level"] == "WARNING" and "may be missing" in recs[0]["msg"]
    assert recs[-1]["seq"] == 5


def test_oversized_line_is_skipped_with_note(tmp_path, monkeypatch):
    monkeypatch.setattr(log_tail, "CHUNK", 128)  # > one 103-byte record
    f = tmp_path / "helao_g.jsonl"
    f.write_bytes(b"")
    _, cur = log_tail.tail_init(tmp_path)
    f.write_bytes(b'{"msg": "' + b"x" * 500 + b'"}\n' + _line(7))
    recs, cur = log_tail.tail_poll(tmp_path, cur)
    recs2, _ = log_tail.tail_poll(tmp_path, cur)
    allrecs = recs + recs2
    assert any("over" in r["msg"] and "skipped" in r["msg"] for r in allrecs)
    assert allrecs[-1]["seq"] == 7


def test_ignores_ledger_and_rotated_files(tmp_path):
    (tmp_path / "artifacts_g.jsonl").write_bytes(_line(1))
    (tmp_path / "helao_g_20261026T000000.jsonl").write_bytes(_line(2))
    (tmp_path / "A.jsonl").write_bytes(_line(3, server="A"))
    recs, _ = log_tail.tail_init(tmp_path)
    assert [r["seq"] for r in recs] == [3]


def test_merge_dedups_and_keeps_newest():
    a = [json.loads(_line(i)) for i in range(5)]
    m = log_tail.merge(a, a[3:] + [json.loads(_line(9))], keep=4)
    assert [r["seq"] for r in m] == [2, 3, 4, 9]


def test_merge_keeps_same_seq_from_a_different_process_lifetime():
    a = json.loads(_line(1, ts="2026-10-26T00:00:01.000000Z"))
    b = json.loads(_line(1, ts="2026-10-26T01:00:01.000000Z"))  # pid/seq reused later
    assert log_tail.merge([a], [b], keep=10) == [a, b]


def test_filter_and_rows():
    recs = [
        json.loads(_line(1, "A", "DEBUG")),
        json.loads(_line(2, "B", "ERROR", "disk full")),
    ]
    assert [r["seq"] for r in log_tail.filter_records(recs, None, "INFO", "")] == [2]
    assert log_tail.filter_records(recs, {"A"}, "DEBUG", "") == recs[:1]
    assert log_tail.filter_records(recs, None, "DEBUG", "DISK") == recs[1:]
    rows = log_tail.to_rows(recs)
    assert rows[0][2] == "B" and rows[0][4].startswith("#")  # newest first, colour
