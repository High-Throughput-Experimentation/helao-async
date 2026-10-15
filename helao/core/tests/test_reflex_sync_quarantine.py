"""The /quarantine page: config gate, rendering and handler wiring.

Handlers are bound off ``QuarantineState`` (``.fn``) onto a plain fake, as
``test_reflex_retire`` does. The logic they call is tested offline in
``test_sync_quarantine_page_logic.py``; this file tests the wiring.
"""

import asyncio

import pytest

from helao.ui.reflex import sync_quarantine as qr

pytestmark = pytest.mark.usefixtures("reflex_registration")

Q = qr.QuarantineState
TARGET = ("SYNC", "localhost", 8010)
Y1, Y2 = "/r/a-seq.yml", "/r/b-exp.yml"


def _entry(yml, name, immediate=True):
    return {
        "yml": yml,
        "path": f"/r/{name}",
        "kind": "experiment",
        "immediate": immediate,
        "quarantined_at": "t",
        "strikes": 3,
        "last_error": "e",
    }


E1, E2 = _entry(Y1, "dirA"), _entry(Y2, "dirB")


class _Fake:
    def __init__(self):
        self.rows = []
        self.status = ""
        self.message = ""
        self.gen = 0
        self.selected = ""
        self.selected_dir = ""
        self.confirm = ""
        self.reason = ""
        self.operator = ""
        self.armed = False
        self.busy = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    set_confirm = Q.set_confirm.fn
    set_reason = Q.set_reason.fn
    set_operator = Q.set_operator.fn
    select = Q.select.fn
    refresh = Q.refresh.fn
    release_row = Q.release_row.fn
    write_off = Q.write_off.fn


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setitem(qr._CONFIG, "enabled", True)
    monkeypatch.setitem(qr._CONFIG, "target", TARGET)


def _fetch_returns(monkeypatch, value, calls=None):
    async def fetch(target):
        if calls is not None:
            calls.append(target)
        return value

    monkeypatch.setattr(qr.sq, "fetch", fetch)


def _armed(monkeypatch, entries=(E1, E2)):
    """A state with rows loaded, Y1 selected and the form filled."""
    _fetch_returns(monkeypatch, list(entries))
    s = _Fake()
    asyncio.run(s.refresh())
    s.select(Y1, "dirA")
    s.set_confirm("dirA")
    s.set_reason("why")
    s.set_operator("op")
    assert s.armed is True
    return s


WORLD = {
    "servers": {
        "UI": {"params": {}},
        "SYNC": {"host": "localhost", "port": 8010, "fast": "x"},
    }
}


def _world(flag):
    import copy

    w = copy.deepcopy(WORLD)
    if flag != "missing":
        w["servers"]["UI"]["params"]["sync_quarantine"] = flag
    return w


@pytest.mark.parametrize("flag", ["true", 1, "missing"])
def test_configure_enables_only_on_literal_true(flag, monkeypatch):
    monkeypatch.setattr(qr.sq, "sync_target", lambda w: TARGET)
    qr.configure_quarantine(_world(flag), "UI")
    assert qr.quarantine_enabled() is False


def test_configure_needs_a_sync_and_true(monkeypatch):
    monkeypatch.setattr(qr.sq, "sync_target", lambda w: None)
    qr.configure_quarantine(_world(True), "UI")
    assert qr.quarantine_enabled() is False
    monkeypatch.setattr(qr.sq, "sync_target", lambda w: TARGET)
    qr.configure_quarantine(_world(True), "UI")
    assert qr.quarantine_enabled() is True
    assert qr._CONFIG["target"] == TARGET


@pytest.mark.parametrize("on", [True, False])
def test_page_renders_enabled_and_disabled(on, monkeypatch):
    monkeypatch.setitem(qr._CONFIG, "enabled", on)
    monkeypatch.setitem(qr._CONFIG, "target", TARGET)
    assert str(qr.sync_quarantine_page().render())


def test_refresh_unknown_vs_empty(enabled, monkeypatch):
    s = _Fake()
    s.rows = [["stale"] * 7]
    _fetch_returns(monkeypatch, None)
    asyncio.run(s.refresh())
    assert s.status == qr.UNREACHABLE and s.rows == []
    _fetch_returns(monkeypatch, [])
    asyncio.run(s.refresh())
    assert s.status == qr.NOTHING and s.rows == []
    assert qr.UNREACHABLE != qr.NOTHING


def test_refresh_skips_while_busy_and_drops_a_stale_selection(enabled, monkeypatch):
    s = _armed(monkeypatch)
    calls = []
    _fetch_returns(monkeypatch, [E2], calls)
    s.busy = True
    asyncio.run(s.refresh())
    assert calls == []
    s.busy = False
    asyncio.run(s.refresh())
    assert calls == [TARGET]
    assert (s.selected, s.confirm, s.armed) == ("", "", False)
    assert [r[0] for r in s.rows] == [Y2]


def test_refresh_keeps_a_selection_that_is_still_listed(enabled, monkeypatch):
    s = _armed(monkeypatch)
    _fetch_returns(monkeypatch, [E2, E1])
    asyncio.run(s.refresh())
    assert s.selected == Y1 and s.confirm == "dirA" and s.armed is True


def _spy(monkeypatch, result=(True, "ok")):
    calls = []

    async def wo(target, yml, reason, operator):
        calls.append(("write_off", yml, reason, operator))
        return result

    async def rel(target, yml):
        calls.append(("release", yml))
        return result

    monkeypatch.setattr(qr.sq, "write_off", wo)
    monkeypatch.setattr(qr.sq, "release", rel)
    return calls


def test_write_off_requires_armed_and_enabled(enabled, monkeypatch):
    s = _armed(monkeypatch)
    calls = _spy(monkeypatch)
    s.armed = False
    s.confirm = "wrong"  # the handler re-checks; the stale flag is not trusted
    asyncio.run(s.write_off())
    assert calls == []
    s.confirm = "dirA"
    monkeypatch.setitem(qr._CONFIG, "enabled", False)
    asyncio.run(s.write_off())
    assert calls == []
    monkeypatch.setitem(qr._CONFIG, "enabled", True)
    asyncio.run(s.write_off())
    assert calls == [("write_off", Y1, "why", "op")]


def test_write_off_refused_for_a_row_that_is_not_incomplete(enabled, monkeypatch):
    s = _armed(monkeypatch, [_entry(Y1, "dirA", immediate=False), E2])
    calls = _spy(monkeypatch)
    asyncio.run(s.write_off())
    assert calls == []


def test_actions_target_yml_not_index(enabled, monkeypatch):
    s = _armed(monkeypatch)  # Y1 is row 0
    calls = _spy(monkeypatch)
    _fetch_returns(monkeypatch, [E2, E1])  # reordered: Y1 is now row 1
    asyncio.run(s.refresh())
    asyncio.run(s.write_off())
    assert calls == [("write_off", Y1, "why", "op")]
    asyncio.run(s.release_row(Y2))
    assert calls[-1] == ("release", Y2)


def test_release_and_write_off_share_one_lock(enabled, monkeypatch):
    s = _armed(monkeypatch)
    calls = _spy(monkeypatch)

    async def held():
        await qr._LOCK.acquire()
        try:
            await s.release_row(Y2)
            first = s.message
            await s.write_off()
            return first, s.message
        finally:
            qr._LOCK.release()

    first, second = asyncio.run(held())
    assert calls == []
    assert first == second == qr.BUSY
    assert s.busy is False


def test_status_shows_the_shared_message(enabled, monkeypatch):
    s = _armed(monkeypatch)
    _spy(monkeypatch, (None, "sent, outcome unknown — refresh"))
    asyncio.run(s.write_off())
    assert s.message == "sent, outcome unknown — refresh"
    assert s.busy is False and s.selected == "" and s.armed is False
    assert qr._LOCK.locked() is False


def test_release_message_is_shown_verbatim(enabled, monkeypatch):
    s = _armed(monkeypatch)
    _spy(monkeypatch, (True, "released; re-queued"))
    asyncio.run(s.release_row(Y1))
    assert s.message == "released; re-queued"


def _page_text(monkeypatch):
    monkeypatch.setitem(qr._CONFIG, "enabled", True)
    monkeypatch.setitem(qr._CONFIG, "target", TARGET)
    return str(qr.sync_quarantine_page().render())


def test_row_without_yml_has_no_actions(monkeypatch):
    """The row's buttons sit inside a guard on its yml cell."""
    text = _page_text(monkeypatch)
    release = text.index("Release")
    guard = text.rfind("cond_state", 0, release)
    assert guard != -1
    assert '.at?.(0)?.valueOf?.() === ""' in text[guard:release]
    assert "Write off" in text[release:]


def test_every_foreach_var_carries_an_element_annotation():
    fields = Q.get_fields()
    assert fields["rows"].annotated_type == list[list[str]]


def _hold_fetch(monkeypatch, first, then):
    """A fetch whose first call blocks on a gate; later calls return *then*."""
    gate, n = asyncio.Event(), {"i": 0}

    async def fetch(target):
        n["i"] += 1
        if n["i"] == 1:
            await gate.wait()
            return first
        return then

    monkeypatch.setattr(qr.sq, "fetch", fetch)
    return gate


def test_a_tick_spanning_an_action_neither_resurrects_rows_nor_eats_the_message(
    enabled, monkeypatch
):
    """Mutation: drop the generation check in refresh (or write status for the message)."""
    _spy(monkeypatch, (True, "released; re-queued"))
    gate = _hold_fetch(monkeypatch, [E1], [])
    s = _Fake()
    s.rows = [qr.sq.rows([E1])[0]]

    async def go():
        tick = asyncio.create_task(s.refresh())
        await asyncio.sleep(0)
        await s.release_row(Y1)
        gate.set()
        await tick

    asyncio.run(go())
    assert s.rows == [] and s.message == "released; re-queued"


def test_message_survives_a_tick(enabled, monkeypatch):
    """Mutation: let refresh write the action message's var."""
    s = _armed(monkeypatch)
    _spy(monkeypatch, (True, "written off; WARNING: x"))
    asyncio.run(s.write_off())
    _fetch_returns(monkeypatch, [E2])
    asyncio.run(s.refresh())
    assert s.message == "written off; WARNING: x" and s.status == "1 quarantined"


@pytest.mark.parametrize("exc", [asyncio.CancelledError, RuntimeError])
def test_busy_and_lock_are_released_when_the_call_raises(enabled, monkeypatch, exc):
    """Mutation: reset busy only on the success path."""
    s = _armed(monkeypatch)

    async def boom(*a):
        raise exc

    monkeypatch.setattr(qr.sq, "release", boom)
    with pytest.raises(exc):
        asyncio.run(s.release_row(Y1))
    assert s.busy is False and qr._LOCK.locked() is False


def test_release_refuses_an_unlisted_yml(enabled, monkeypatch):
    """Mutation: drop the membership check in release_row."""
    s = _armed(monkeypatch)
    calls = _spy(monkeypatch)
    asyncio.run(s.release_row("/r/not-listed-seq.yml"))
    assert calls == []


def test_release_is_a_no_op_when_disabled(enabled, monkeypatch):
    """Mutation: drop the enabled check in _act."""
    s = _armed(monkeypatch)
    calls = _spy(monkeypatch)
    monkeypatch.setitem(qr._CONFIG, "enabled", False)
    asyncio.run(s.release_row(Y1))
    assert calls == []


def test_refresh_is_a_no_op_when_disabled(enabled, monkeypatch):
    """Mutation: drop the enabled check in refresh."""
    calls = []
    _fetch_returns(monkeypatch, [E1], calls)
    monkeypatch.setitem(qr._CONFIG, "enabled", False)
    asyncio.run(_Fake().refresh())
    assert calls == []


def test_refresh_drops_rows_when_an_action_starts_during_its_fetch(
    enabled, monkeypatch
):
    """Mutation: drop the post-fetch busy re-check (gen unchanged here)."""
    s = _Fake()
    gate = _hold_fetch(monkeypatch, [E1], [])

    async def go():
        tick = asyncio.create_task(s.refresh())
        await asyncio.sleep(0)
        s.busy = True
        gate.set()
        await tick

    asyncio.run(go())
    assert s.rows == []


@pytest.mark.parametrize("busy, on", [(True, True), (False, False)])
def test_form_handlers_are_no_ops_when_busy_or_disabled(enabled, monkeypatch, busy, on):
    """Mutation: drop the guard from select / set_confirm."""
    s = _armed(monkeypatch)
    s.busy = busy
    monkeypatch.setitem(qr._CONFIG, "enabled", on)
    s.select(Y2, "dirB")
    s.set_confirm("zzz")
    assert (s.selected, s.selected_dir, s.confirm) == (Y1, "dirA", "dirA")


def test_each_form_edit_rearms(enabled, monkeypatch):
    """Mutation: drop _rearm from set_confirm."""
    s = _Fake()
    s.selected, s.selected_dir = Y1, "dirA"
    s.set_reason("why")
    s.set_operator("op")
    assert s.armed is False
    s.set_confirm("dirA")
    assert s.armed is True
    s.set_confirm("dirX")
    assert s.armed is False


def test_write_off_arms_against_the_listed_dir_not_the_client_one(enabled, monkeypatch):
    """Mutation: arm against selected_dir."""
    s = _armed(monkeypatch)
    calls = _spy(monkeypatch)
    s.selected_dir, s.confirm = "forged", "forged"
    asyncio.run(s.write_off())
    assert calls == []
