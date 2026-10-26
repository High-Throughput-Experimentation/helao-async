"""The /logs page state (spec §4)."""

import json

from helao.ui.reflex import logs


def _line(seq, server="A", level="INFO"):
    return (
        json.dumps(
            {
                "ts": f"2026-10-26T00:00:{seq:02d}.000000Z",
                "level": level,
                "server": server,
                "pid": 1,
                "seq": seq,
                "msg": f"m{seq}",
            }
        )
        + "\n"
    ).encode()


def test_configure_logs_absolute_dir(tmp_path, monkeypatch):
    # a relative root must come back absolute: the Reflex process runs from _app/
    monkeypatch.chdir(tmp_path)
    logs.configure_logs({"root": "rel"}, "UI")
    assert logs._CONFIG["log_dir"] == str((tmp_path / "rel" / "LOGS").resolve())


def test_state_start_tick_filter_pause(tmp_path):
    d = tmp_path / "LOGS"
    d.mkdir()
    (d / "helao_g.jsonl").write_bytes(_line(1, "A") + _line(2, "B", "ERROR"))
    logs.configure_logs({"root": str(tmp_path)}, "UI")
    s = logs.LogsState()
    s.start()
    assert s.servers == ["A", "B"] and [r[2] for r in s.rows] == ["B", "A"]
    s.set_min_level("ERROR")
    assert [r[2] for r in s.rows] == ["B"]
    s.toggle_pause()
    with open(d / "helao_g.jsonl", "ab") as f:
        f.write(_line(3, "B", "ERROR"))
    s.tick()
    assert len(s.rows) == 1  # display frozen
    s.set_min_level("INFO")
    assert len(s.rows) == 2  # a filter change re-renders the frozen view
    s.set_min_level("ERROR")
    s.toggle_pause()
    assert len(s.rows) == 2  # polled while paused


def test_tick_before_start_shows_newest_rows(tmp_path, monkeypatch):
    d = tmp_path / "LOGS"
    d.mkdir()
    (d / "helao_g.jsonl").write_bytes(b"".join(_line(i) for i in range(10)))
    monkeypatch.setattr(logs, "MAX_ROWS", 3)
    logs.configure_logs({"root": str(tmp_path)}, "UI")
    s = logs.LogsState()
    s.tick()
    assert [r[3] for r in s.rows] == ["m9", "m8", "m7"]


def test_selected_server_stays_listed(tmp_path, monkeypatch):
    d = tmp_path / "LOGS"
    d.mkdir()
    (d / "helao_g.jsonl").write_bytes(_line(1, "A") + _line(2, "B"))
    monkeypatch.setattr(logs, "MAX_ROWS", 1)
    logs.configure_logs({"root": str(tmp_path)}, "UI")
    s = logs.LogsState()
    s.start()
    assert s.servers == ["B"]
    s.toggle_server("A", True)
    with open(d / "helao_g.jsonl", "ab") as f:
        f.write(_line(3, "B"))
    s.tick()
    assert s.servers == ["A", "B"]  # A aged out of the buffer but is selected
