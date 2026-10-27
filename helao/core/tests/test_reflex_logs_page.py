"""The /logs page state (spec §4)."""

import asyncio
import json
import threading

from helao.ui.reflex import logs


class FakeState:
    """Stands in for the StateProxy of a background event (``async with`` guards it)."""

    def __init__(self):
        self._all, self._frozen, self._cursors, self._busy = (), (), (), False
        self.rows, self.servers, self.selected = [], [], []
        self.min_level, self.text, self.paused = "INFO", "", False
        self.entered = 0

    async def __aenter__(self):
        self.entered += 1
        return self

    async def __aexit__(self, *exc):
        return False

    def start(self):
        asyncio.run(logs._load_bg(self, tick=False))

    def tick(self):
        asyncio.run(logs._load_bg(self, tick=True))

    def set_min_level(self, v):
        logs._set_min_level(self, v)

    def toggle_pause(self):
        logs._toggle_pause(self)

    def toggle_server(self, server, on=True):
        logs._toggle_server(self, server, on)


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
    s = FakeState()
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
    s = FakeState()
    s.tick()
    assert [r[3] for r in s.rows] == ["m9", "m8", "m7"]


def test_selected_server_stays_listed(tmp_path, monkeypatch):
    d = tmp_path / "LOGS"
    d.mkdir()
    (d / "helao_g.jsonl").write_bytes(_line(1, "A") + _line(2, "B"))
    monkeypatch.setattr(logs, "MAX_ROWS", 1)
    logs.configure_logs({"root": str(tmp_path)}, "UI")
    s = FakeState()
    s.start()
    assert s.servers == ["B"]
    s.toggle_server("A", True)
    with open(d / "helao_g.jsonl", "ab") as f:
        f.write(_line(3, "B"))
    s.tick()
    assert s.servers == ["A", "B"]  # A aged out of the buffer but is selected


def test_start_and_tick_do_file_io_off_the_event_loop_thread(tmp_path, monkeypatch):
    d = tmp_path / "LOGS"
    d.mkdir()
    (d / "helao_g.jsonl").write_bytes(_line(1))
    logs.configure_logs({"root": str(tmp_path)}, "UI")
    seen = {}

    def spy(name, real):
        def f(*a, **k):
            seen[name] = threading.get_ident()
            return real(*a, **k)

        return f

    monkeypatch.setattr(
        logs.log_tail, "tail_init", spy("init", logs.log_tail.tail_init)
    )
    monkeypatch.setattr(
        logs.log_tail, "tail_poll", spy("poll", logs.log_tail.tail_poll)
    )
    loop_thread = {}

    async def run(s):
        loop_thread["id"] = threading.get_ident()
        await logs._load_bg(s, tick=False)
        await logs._load_bg(s, tick=True)

    s = FakeState()
    asyncio.run(run(s))
    assert set(seen) == {"init", "poll"}
    assert all(t != loop_thread["id"] for t in seen.values())
    assert len(s.rows) == 1


def test_overlapping_tick_is_dropped_while_busy(tmp_path):
    d = tmp_path / "LOGS"
    d.mkdir()
    (d / "helao_g.jsonl").write_bytes(_line(1))
    logs.configure_logs({"root": str(tmp_path)}, "UI")
    s = FakeState()
    s._busy = True
    asyncio.run(logs._load_bg(s, tick=True))
    assert s.rows == [] and s._busy is True


def test_server_list_holds_server_keys_not_module_loggers(tmp_path):
    d = tmp_path / "LOGS"
    d.mkdir()
    lines = []
    for i, lg in enumerate(["api", "app", "state", "ingest"], 1):
        r = json.loads(_line(i, "UI"))
        r["logger"] = lg
        lines.append(json.dumps(r).encode() + b"\n")
    (d / "helao_g.jsonl").write_bytes(b"".join(lines))
    logs.configure_logs({"root": str(tmp_path)}, "UI")
    s = FakeState()
    s.start()
    assert s.servers == ["UI"]
    assert sorted(r[2] for r in s.rows) == [
        "UI \u00b7 api",
        "UI \u00b7 app",
        "UI \u00b7 ingest",
        "UI \u00b7 state",
    ]


def test_message_cell_collapses_and_rows_are_keyed_by_record():
    js = str(logs._row(logs.LogsState.rows[0]))
    assert 'jsx("details"' in js and 'jsx("summary"' in js
    assert '["textOverflow"] : "ellipsis"' in js and "&[open] > summary" in js
    # an index key would hand an expanded row's state to whichever row
    # slides into its place when newer records arrive
    assert "key:" in js and "at?.(5)" in js
