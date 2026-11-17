"""/runners page helpers and launch gating."""

import asyncio
import subprocess
import sys

from helao.ui.reflex import runners

ENTRY = {
    "module": "m",
    "doc": "Demo.\n\n:param n: count",
    "args": ["n", "flag"],
    "defaults": [2, False],
    "argtypes": ["int", "bool"],
    "requires": None,
    "inferred": {},
}


def test_item_from_entry_maps_types():
    item = runners.item_from_entry(ENTRY)
    assert item["argtypes"] == [int, bool]
    assert item["args"] == ["n", "flag"]


def test_item_from_entry_unknown_type_is_unspecified():
    item = runners.item_from_entry({**ENTRY, "argtypes": ["list", "int"]})
    assert item["argtypes"] == ["unspecified", int]


def test_stored_values_drop_removed_params(monkeypatch):
    monkeypatch.setattr(
        runners, "read_params", lambda root, kind, name: {"n": 5, "gone": 1}
    )
    from helao.ui.reflex.operator import fields_for_item

    fields = fields_for_item(runners.item_from_entry(ENTRY))
    assert runners.stored_values("/r", "m", fields) == {"n": "5"}


def test_launch_refuses_bad_params(monkeypatch):
    called = []

    async def fake_launch(*a, **k):
        called.append(a)

    monkeypatch.setattr(runners.runner_procs, "launch", fake_launch)
    err = asyncio.run(
        runners.try_launch(
            {"root": "/r"}, ENTRY, {"n": "abc"}, "K", blocked=False, override=False
        )
    )
    assert err.startswith("n:") and called == []


def test_launch_blocked_without_override(monkeypatch):
    async def fake_launch(*a, **k):
        raise AssertionError("must not launch")

    monkeypatch.setattr(runners.runner_procs, "launch", fake_launch)
    err = asyncio.run(
        runners.try_launch({"root": "/r"}, ENTRY, {}, "K", blocked=True, override=False)
    )
    assert "requirement" in err


def test_launch_override_saves_and_launches(monkeypatch):
    saved, launched = [], []

    async def fake_launch(world, module, key, params):
        launched.append((module, key, params))

    monkeypatch.setattr(runners.runner_procs, "launch", fake_launch)
    monkeypatch.setattr(runners, "write_params", lambda *a, **k: saved.append(a))
    err = asyncio.run(
        runners.try_launch(
            {"root": "/r"}, ENTRY, {"n": "3"}, "K", blocked=True, override=True
        )
    )
    assert err == "" and launched == [("m", "K", {"n": 3, "flag": False})]
    assert saved[0][:3] == ("/r", "runner", "m")


def test_launch_taken_key_is_an_error_message(monkeypatch):
    async def fake_launch(*a, **k):
        raise ValueError("key K is already running")

    monkeypatch.setattr(runners.runner_procs, "launch", fake_launch)
    monkeypatch.setattr(runners, "write_params", lambda *a, **k: True)
    err = asyncio.run(
        runners.try_launch(
            {"root": "/r"}, ENTRY, {}, "K", blocked=False, override=False
        )
    )
    assert "already running" in err


def test_requirement_rows_use_declared_then_inferred(monkeypatch):
    async def fake_probe(servers, world):
        return {"S": ["go"]}, {"S": {}}

    monkeypatch.setattr(runners.runner_procs, "probe", fake_probe)
    world = {"servers": {"S": {}}}
    entry = {**ENTRY, "requires": {"S": ["go"]}, "inferred": {"T": ["x"]}}
    rows, note, blocked = asyncio.run(runners.check_requirements(world, entry))
    assert note == "declared" and not blocked
    assert rows[0][:3] == ["S", "go", "ok"]
    entry = {**ENTRY, "requires": None, "inferred": {"T": ["x"]}}
    rows, note, blocked = asyncio.run(runners.check_requirements(world, entry))
    assert note == "inferred, may be incomplete"
    assert rows[0][2] == "warn" and not blocked  # inferred never blocks
    rows, note, blocked = asyncio.run(runners.check_requirements(world, ENTRY))
    assert (rows, note, blocked) == ([], "none", False)
    entry = {**ENTRY, "requires": {"T": ["x"]}}
    rows, note, blocked = asyncio.run(runners.check_requirements(world, entry))
    assert blocked and rows[0][2] == "fail"


def test_page_renders():
    # event-binding errors surface at render, not import
    assert runners.runners_page() is not None


class FakeState:
    """Stands in for a RunnersState instance for the plain handlers."""

    def __init__(self):
        self.selected, self.doc, self.fields_rows, self.values = "", "", [], {}
        self.key, self.error, self.override = "", "", False
        self.req_rows, self.req_note, self.blocked, self._sig = [], "", False, ""


def _catalog(monkeypatch, **entries):
    monkeypatch.setattr(runners.runner_procs, "CATALOG", entries)
    monkeypatch.setattr(runners, "read_params", lambda *a: {})


def test_set_bool_sends_strings_that_coerce(monkeypatch):
    from helao.ui.reflex.operator import coerce_params, fields_for_item

    st = FakeState()
    fields = fields_for_item(runners.item_from_entry(ENTRY))
    runners.RunnersState.set_bool.fn(st, "flag", True)
    assert st.values["flag"] == "True"
    assert coerce_params(fields, st.values)[0]["flag"] is True
    runners.RunnersState.set_bool.fn(st, "flag", False)
    assert st.values["flag"] == "False"
    assert coerce_params(fields, st.values)[0]["flag"] is False


def test_select_blocks_launch_until_recheck(monkeypatch):
    _catalog(monkeypatch, a=ENTRY, b={**ENTRY, "module": "b"})
    st = FakeState()
    runners.RunnersState.select.fn(st, "a")
    st.blocked, st.req_note = False, "declared"  # a finished check on A
    runners.RunnersState.select.fn(st, "b")
    assert st.blocked and st.req_note == "checking" and st.req_rows == []
    assert st.values == {"n": "2", "flag": "False"}  # every field seeded
    err = asyncio.run(
        runners.try_launch({}, ENTRY, {}, "K", blocked=st.blocked, override=False)
    )
    assert "requirement" in err


def test_error_entry_never_reaches_write_or_launch(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not run")

    monkeypatch.setattr(runners, "write_params", boom)
    monkeypatch.setattr(runners.runner_procs, "launch", boom)
    err = asyncio.run(
        runners.try_launch(
            {},
            {**ENTRY, "error": "SyntaxError"},
            {},
            "K",
            blocked=False,
            override=False,
        )
    )
    assert "SyntaxError" in err


def test_bad_key_refused_first(monkeypatch):
    monkeypatch.setattr(runners, "write_params", lambda *a: 1 / 0)
    for key in ("", "a b", "a/b", "k;"):
        err = asyncio.run(
            runners.try_launch({}, ENTRY, {}, key, blocked=False, override=False)
        )
        assert "key" in err


def test_refresh_clears_errored_and_rebuilds_changed(monkeypatch):
    _catalog(monkeypatch, m=ENTRY)
    st = FakeState()
    runners.RunnersState.select.fn(st, "m")
    st.values["n"] = "9"
    assert runners._apply_refresh(st) is False and st.values["n"] == "9"
    changed = {
        **ENTRY,
        "args": ["n", "flag", "new"],
        "defaults": [2, False, 7],
        "argtypes": ["int", "bool", "int"],
    }
    _catalog(monkeypatch, m=changed)
    assert runners._apply_refresh(st) is True
    assert [r[0] for r in st.fields_rows] == ["n", "flag", "new"]
    assert st.values["new"] == "7" and st.blocked
    _catalog(monkeypatch, m={**ENTRY, "error": "gone bad"})
    assert runners._apply_refresh(st) is False
    assert st.selected == "" and st.fields_rows == []


def test_explicit_empty_requires_is_honoured(monkeypatch):
    async def fake_probe(*a):
        raise AssertionError("nothing to probe")

    monkeypatch.setattr(runners.runner_procs, "probe", fake_probe)
    entry = {**ENTRY, "requires": {}, "inferred": {"T": ["x"]}}
    assert asyncio.run(runners.check_requirements({}, entry)) == ([], "none", False)


def test_entry_rows_show_mtime(monkeypatch):
    _catalog(
        monkeypatch,
        m={**ENTRY, "mtime": 86400},
        n={**ENTRY, "module": "n", "mtime": None},
    )
    rows = runners._entry_rows()
    assert rows[1][4] == "" and len(rows[0][4]) == 19


def test_import_does_not_pull_micro_orch():
    code = (
        "import sys, helao.ui.reflex.runners;"
        "sys.exit('helao.core.runners.micro_orch' in sys.modules)"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_force_kill_enabled_only_while_stopping():
    text = str(runners.runners_page())
    kill = text[text.index("Force kill") - 300 : text.index("Force kill")]
    assert '=== "stopping"' in kill and '"running"' not in kill
