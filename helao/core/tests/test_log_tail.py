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


def test_rotated_file_is_read_to_its_end_not_one_chunk(tmp_path, monkeypatch):
    monkeypatch.setattr(log_tail, "CHUNK", 256)
    f = tmp_path / "helao_g.jsonl"
    f.write_bytes(_line(0))
    _, cur = log_tail.tail_init(tmp_path)
    with open(f, "ab") as fh:
        fh.write(b"".join(_line(i) for i in range(1, 11)))  # > 3 * CHUNK unread
    os.rename(f, tmp_path / "helao_g_20261026T000000.jsonl")
    f.write_bytes(_line(20))
    recs, _ = log_tail.tail_poll(tmp_path, cur)
    assert [r["seq"] for r in recs] == [*range(1, 11), 20]


def test_file_absent_for_one_poll_keeps_its_tail(tmp_path):
    f = tmp_path / "helao_g.jsonl"
    f.write_bytes(_line(1))
    _, cur = log_tail.tail_init(tmp_path)
    with open(f, "ab") as fh:
        fh.write(_line(2))
    os.rename(f, tmp_path / "helao_g_20261026T000000.jsonl")
    recs, cur = log_tail.tail_poll(tmp_path, cur)  # no live file
    assert recs == []
    f.write_bytes(_line(3))
    recs, _ = log_tail.tail_poll(tmp_path, cur)
    assert [r["seq"] for r in recs] == [2, 3]


def test_vanishing_file_never_raises(tmp_path, monkeypatch):
    f = tmp_path / "helao_g.jsonl"
    f.write_bytes(_line(1))
    _, cur = log_tail.tail_init(tmp_path)
    real = log_tail.live_files
    monkeypatch.setattr(
        log_tail, "live_files", lambda d: real(d) + [tmp_path / "gone.jsonl"]
    )
    assert log_tail.tail_init(tmp_path)[0]
    recs, new = log_tail.tail_poll(tmp_path, cur)
    assert recs == [] and [c["path"] for c in new] == [str(f)]


def test_truncate_in_place_is_a_rotation(tmp_path):
    f = tmp_path / "helao_g.jsonl"
    f.write_bytes(_line(1) + _line(2) + _line(3))
    _, cur = log_tail.tail_init(tmp_path)
    f.write_bytes(_line(9))  # same inode, smaller than the cursor
    recs, _ = log_tail.tail_poll(tmp_path, cur)
    assert "may be missing" in recs[0]["msg"] and recs[-1]["seq"] == 9


def test_unrelated_rotated_file_is_not_read(tmp_path):
    f = tmp_path / "helao_g.jsonl"
    f.write_bytes(_line(1))
    _, cur = log_tail.tail_init(tmp_path)
    f.unlink()
    (tmp_path / "helao_g_20261026T000000.jsonl").write_bytes(_line(77))
    f.write_bytes(_line(5))
    recs, _ = log_tail.tail_poll(tmp_path, cur)
    assert 77 not in [r.get("seq") for r in recs] and "may be missing" in recs[0]["msg"]


def test_zero_inode_cursor_does_not_match_by_inode(tmp_path):
    f = tmp_path / "helao_g.jsonl"
    f.write_bytes(_line(1))
    (tmp_path / "helao_g_20261026T000000.jsonl").write_bytes(_line(77))
    cur = [{"path": str(f), "inode": 0, "offset": 0}]
    recs, _ = log_tail.tail_poll(tmp_path, cur)
    assert 77 not in [r.get("seq") for r in recs] and "may be missing" in recs[0]["msg"]


def test_skipped_rotation_is_noted(tmp_path):
    f = tmp_path / "helao_g.jsonl"
    f.write_bytes(_line(1))
    _, cur = log_tail.tail_init(tmp_path)
    old = tmp_path / "helao_g_20261026T000000.jsonl"
    os.rename(f, old)
    newer = tmp_path / "helao_g_20261026T010000.jsonl"
    newer.write_bytes(_line(2))
    os.utime(newer, (time.time() + 10, time.time() + 10))
    f.write_bytes(_line(3))
    recs, _ = log_tail.tail_poll(tmp_path, cur)
    assert any("rotation was skipped" in r.get("msg", "") for r in recs)


def test_non_dict_rows_and_null_ts_are_tolerated(tmp_path):
    (tmp_path / "A.jsonl").write_bytes(b'123\n[1]\n{"ts": null}\n' + _line(4))
    recs, _ = log_tail.tail_init(tmp_path)
    assert all(isinstance(r, dict) for r in recs) and len(recs) == 2
    assert recs[0] == {"ts": None}  # "" sorts first
    assert log_tail.to_rows(recs)
    assert log_tail.filter_records(recs, None, "DEBUG", "x") == []


def test_exc_is_joined_and_searched():
    r = json.loads(_line(1))
    r["exc"] = "Traceback ZeroDivisionError"
    assert log_tail.to_rows([r])[0][3] == "m1\nTraceback ZeroDivisionError"
    assert log_tail.filter_records([r], None, "DEBUG", "zerodivision") == [r]


def test_merge_sorts_out_of_order_and_across_files():
    unified = [json.loads(_line(5, "A")), json.loads(_line(2, "A"))]
    fallback = [json.loads(_line(3, "B"))]
    assert [r["seq"] for r in log_tail.merge(unified, fallback, 10)] == [2, 3, 5]


def test_notes_are_not_deduped_and_show_as_logs():
    n = log_tail._note("x")
    assert log_tail.merge([n], [dict(n)], 10) == [n, n]
    assert log_tail.to_rows([n])[0][2] == "logs"


def test_init_on_file_larger_than_chunk_keeps_whole_newest_records(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(log_tail, "CHUNK", 512)
    (tmp_path / "helao_g.jsonl").write_bytes(b"".join(_line(i) for i in range(20)))
    recs, cur = log_tail.tail_init(tmp_path, n=3)
    assert [r["seq"] for r in recs] == [17, 18, 19]
    assert log_tail.tail_poll(tmp_path, cur)[0] == []


def test_poll_returns_at_most_one_chunk_per_file_then_continues(tmp_path, monkeypatch):
    monkeypatch.setattr(log_tail, "CHUNK", 512)
    f = tmp_path / "helao_g.jsonl"
    f.write_bytes(b"")
    _, cur = log_tail.tail_init(tmp_path)
    f.write_bytes(b"".join(_line(i) for i in range(20)))
    first, cur = log_tail.tail_poll(tmp_path, cur)
    assert 0 < len(first) < 20
    got = [r["seq"] for r in first]
    while True:
        more, cur = log_tail.tail_poll(tmp_path, cur)
        if not more:
            break
        got += [r["seq"] for r in more]
    assert got == list(range(20))


def test_non_str_fields_do_not_raise():
    recs = [
        {
            "ts": 5,
            "level": "INFO",
            "server": "A",
            "pid": 1,
            "seq": 1,
            "msg": 42,
            "exc": ["e"],
        },
        {
            "ts": "2026-10-26T00:00:01.000000Z",
            "level": "INFO",
            "server": "A",
            "pid": 1,
            "seq": 2,
            "msg": None,
        },
    ]
    merged = log_tail.merge([], recs, 10)
    assert len(merged) == 2
    assert len(log_tail.filter_records(merged, None, "INFO", "42")) == 1
    assert log_tail.to_rows(merged)[0][0] == "5"


def test_rotated_tail_is_capped_with_a_note(tmp_path, monkeypatch):
    monkeypatch.setattr(log_tail, "CHUNK", 256)
    monkeypatch.setattr(log_tail, "MAX_ROTATED_TAIL", 400)
    f = tmp_path / "helao_g.jsonl"
    f.write_bytes(_line(0))
    _, cur = log_tail.tail_init(tmp_path)
    with open(f, "ab") as fh:
        fh.write(b"".join(_line(i) for i in range(1, 31)))  # far over the cap
    rotated = tmp_path / "helao_g_20261026T000000.jsonl"
    os.rename(f, rotated)
    f.write_bytes(_line(99))
    recs, _ = log_tail.tail_poll(tmp_path, cur)
    notes = [r["msg"] for r in recs if r.get("_note")]
    assert any(
        m.endswith("of helao_g_20261026T000000.jsonl skipped (viewer fell behind)")
        and int(m.split()[0]) > 0
        for m in notes
    )
    seqs = [r["seq"] for r in recs if not r.get("_note")]
    assert seqs[-2:] == [30, 99] and 1 not in seqs  # the newest were kept
    assert len(seqs) <= 400 // len(_line(1)) + 3  # bounded by the cap


def test_rotated_name_match_is_anchored(tmp_path):
    live = tmp_path / "UI.jsonl"
    live.write_bytes(_line(1))
    _, cur = log_tail.tail_init(tmp_path)
    # the cursor's file is now an unrelated live file that merely shares the stem
    os.rename(live, tmp_path / "UI_backend.jsonl")
    live.write_bytes(_line(2))
    rows = log_tail._finish_rotated(live, cur[0])
    assert [r["msg"] for r in rows] == [
        "UI.jsonl rotated; records written just before may be missing"
    ]


def test_merge_keeps_records_differing_only_in_logger():
    a = {**json.loads(_line(1)), "logger": "api"}
    b = {**a, "logger": "app"}
    assert log_tail.merge([a], [b, dict(a)], keep=10) == [a, b]


def test_to_rows_server_cell_shows_logger_only_when_it_differs():
    base = {"ts": "t", "level": "INFO", "msg": "m"}
    recs = [
        {**base, "server": "S", "logger": "S"},
        {**base, "server": "S", "logger": "api"},
        {**base, "server": "S"},  # pre-logger record
    ]
    assert [r[2] for r in log_tail.to_rows(recs)] == ["S", "S \u00b7 api", "S"]


def test_text_search_matches_the_logger_name():
    recs = [
        {"server": "S", "logger": "dispatcher", "level": "INFO", "msg": "x"},
        {"server": "S", "logger": "api", "level": "INFO", "msg": "y"},
    ]
    got = log_tail.filter_records(recs, None, "INFO", "DISPATCH")
    assert [r["logger"] for r in got] == ["dispatcher"]
