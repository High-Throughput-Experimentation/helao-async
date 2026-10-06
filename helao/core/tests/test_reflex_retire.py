"""The /retire page: config gate, rendering and handler behaviour.

The handlers are bound straight off ``RetireState`` (``.fn``) onto a plain fake,
as ``test_reflex_composition`` does: Reflex intercepts attribute assignment on a
real ``rx.State``. The logic they call lives in ``helao/ui/shared/retire.py``
and is tested offline in ``test_retire.py``; this file tests the wiring.
"""

import asyncio
import json
import os

import pytest

from helao.core.tests.retire_fakes import FakeMetadataClient, make_run_tree
from helao.ui.reflex import retire as rr

pytestmark = pytest.mark.usefixtures("reflex_registration")

U = "06a7e382-a773-731d-8000-d7e3e21eacec"
E1, A1, P1 = "e1", "a1", "p1"


class _FakeRetireState:
    """Plain attributes for every var, with the lock protocol Reflex supplies."""

    def __init__(self):
        self.uuid_text = ""
        self.status = ""
        self.error = ""
        self.counts: list = []
        self.label = ""
        self.campaign = ""
        self.confirm_text = ""
        self.armed = False
        self.busy = False
        self.progress = 0
        self.ledger = ""
        self.warnings: list = []
        self.moved: list = []
        self.phase = "idle"
        self.run_dirs: list = []
        self.analysis_dirs: list = []
        self._inv = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    gather = rr.RetireState.gather.fn  # type: ignore[attr-defined]
    do_retire = rr.RetireState.do_retire.fn  # type: ignore[attr-defined]
    set_uuid = rr.RetireState.set_uuid.fn  # type: ignore[attr-defined]
    set_confirm = rr.RetireState.set_confirm.fn  # type: ignore[attr-defined]


def _boom(*a, **k):
    raise AssertionError("must not be called")


@pytest.fixture
def enabled(tmp_path, monkeypatch):
    root, src = tmp_path / "root", tmp_path / "src"
    root.mkdir()
    src.mkdir()
    monkeypatch.setitem(rr._CONFIG, "enabled", True)
    monkeypatch.setitem(rr._CONFIG, "root", str(root))
    monkeypatch.setitem(rr._CONFIG, "sources_root", str(src))
    return root, src


def _tree(root, label="LBL"):
    make_run_tree(
        str(root),
        "RUNS_SYNCED",
        "26.40/1001/seqA",
        sequence_uuid=U,
        label=label,
        experiments={E1: [(A1, P1)]},
    )


def _client():
    return FakeMetadataClient(
        {
            "SEQUENCE": {U},
            "EXPERIMENT": {E1},
            "ACTION": {A1},
            "PROCESS": {P1},
        },
        seq_processes={U: [P1]},
    )


def _gathered(enabled, monkeypatch, label="LBL"):
    root, _ = enabled
    _tree(root, label)
    client = _client()
    monkeypatch.setattr(rr.api, "get_client", lambda: client)
    state = _FakeRetireState()
    state.uuid_text = U
    asyncio.run(_FakeRetireState.gather(state))
    return state, client


@pytest.mark.parametrize(
    "world, enables",
    [
        ({"root": "/r", "servers": {"UI": {"params": {"retire": True}}}}, True),
        ({"root": "/r", "servers": {"UI": {"params": {"retire": "true"}}}}, False),
        ({"root": "/r", "servers": {"UI": {"params": {"retire": 1}}}}, False),
        ({"root": "/r", "servers": {"UI": {"params": {}}}}, False),
        ({"root": "/r", "servers": []}, False),
        ({"root": "/r", "servers": {"UI": {"params": "retire"}}}, False),
        ({"servers": {"UI": {"params": {"retire": True}}}}, False),
    ],
)
def test_configure_enables_only_on_literal_true(world, enables, monkeypatch):
    """Mutation: `is True` -> truthiness lets "true" and 1 enable the page."""
    monkeypatch.setattr(rr, "_CONFIG", {})
    rr.configure_retire(world, "UI")
    assert rr.retire_enabled() is enables


def test_configure_reads_sources_root(monkeypatch):
    monkeypatch.setattr(rr, "_CONFIG", {})
    rr.configure_retire(
        {
            "root": "/r",
            "servers": {
                "UI": {"params": {"retire": True, "retire_sources_root": "/s"}}
            },
        },
        "UI",
    )
    assert rr._CONFIG["sources_root"] == "/s"
    rr.configure_retire(
        {"root": "/r", "servers": {"UI": {"params": {"retire": True}}}}, "UI"
    )
    assert rr._CONFIG["sources_root"] == ""


def test_page_renders_enabled_and_disabled(monkeypatch):
    monkeypatch.setitem(rr._CONFIG, "enabled", True)
    assert "Gather" in str(rr.retire_page())
    monkeypatch.setitem(rr._CONFIG, "enabled", False)
    text = str(rr.retire_page())
    assert "Retire is disabled on this station." in text
    assert "Gather" not in text


def test_gather_disabled_does_no_io(monkeypatch):
    """Mutation: drop the enabled check at the top of gather."""
    monkeypatch.setitem(rr._CONFIG, "enabled", False)
    monkeypatch.setattr(rr.api, "get_client", _boom)
    monkeypatch.setattr(rr.retire_logic, "locate", _boom)
    state = _FakeRetireState()
    state.uuid_text = U
    asyncio.run(_FakeRetireState.gather(state))
    assert (state.phase, state.error, state.busy) == ("idle", "", False)
    assert state.uuid_text == U


def test_gather_rejects_non_uuid(enabled, monkeypatch):
    """Mutation: skip the uuid.UUID parse and go straight to locate."""
    monkeypatch.setattr(rr.api, "get_client", _boom)
    monkeypatch.setattr(rr.retire_logic, "locate", _boom)
    state = _FakeRetireState()
    state.uuid_text = "../../etc"
    asyncio.run(_FakeRetireState.gather(state))
    assert state.error == "not a uuid"
    assert state.busy is False


def test_gather_fills_counts(enabled, monkeypatch):
    state, _ = _gathered(enabled, monkeypatch)
    assert state.error == ""
    assert state.counts[2] == ["PROCESS", "1", "1"]
    assert state.counts[-1] == ["SEQUENCE", "1", "present"]
    assert state.phase == "gathered"
    assert state.label == "LBL"
    assert state.busy is False


def test_gather_normalises_the_uuid(enabled, monkeypatch):
    """Mutation: use the raw text instead of str(uuid.UUID(...))."""
    root, _ = enabled
    _tree(root)
    client = _client()
    monkeypatch.setattr(rr.api, "get_client", lambda: client)
    state = _FakeRetireState()
    state.uuid_text = "  {" + U.upper() + "}  "
    asyncio.run(_FakeRetireState.gather(state))
    assert state.phase == "gathered"
    assert state.uuid_text == U


def test_set_uuid_clears_inventory_and_disarms(enabled, monkeypatch):
    """Mutation: set_uuid forgets to clear _inv or armed."""
    state, _ = _gathered(enabled, monkeypatch)
    state.set_confirm("LBL")
    assert state.armed
    state.set_uuid("x")
    assert state._inv is None
    assert state.armed is False
    assert state.counts == [] and state.label == "" and state.confirm_text == ""
    assert state.phase == "idle"


def test_confirm_must_equal_label_or_uuid_when_label_empty(enabled, monkeypatch):
    """Mutation: compare against the uuid even when a label exists."""
    state, _ = _gathered(enabled, monkeypatch)
    state.set_confirm("nope")
    assert state.armed is False and state.phase == "gathered"
    state.set_confirm("LBL")
    assert state.armed is True and state.phase == "armed"
    state.set_confirm(U)
    assert state.armed is False and state.phase == "gathered"

    state, _ = _gathered(enabled, monkeypatch, label="")
    assert state.label == ""
    state.set_confirm(U)
    assert state.armed is True and state.phase == "armed"


def test_do_retire_while_lock_held_reports_busy(enabled, monkeypatch):
    """Mutation: drop the locked() check (the second caller would wait)."""
    state, _ = _gathered(enabled, monkeypatch)
    state.set_confirm("LBL")
    monkeypatch.setattr(rr.retire_logic, "retire", _boom)

    async def main():
        await rr._RETIRE_LOCK.acquire()
        try:
            # bounded: a missing locked() check would wait here forever
            await asyncio.wait_for(_FakeRetireState.do_retire(state), 2)
        finally:
            rr._RETIRE_LOCK.release()

    asyncio.run(main())
    assert state.error == "a retire is already running"
    assert state.phase == "armed"


def test_do_retire_unarmed_does_nothing(enabled, monkeypatch):
    """Mutation: drop the phase == "armed" check."""
    state, client = _gathered(enabled, monkeypatch)
    monkeypatch.setattr(rr.retire_logic, "retire", _boom)
    asyncio.run(_FakeRetireState.do_retire(state))
    assert state.error == "gather and confirm first"
    assert client.calls == []


def test_do_retire_disabled_does_nothing(enabled, monkeypatch):
    """Mutation: drop the enabled check in do_retire."""
    state, _ = _gathered(enabled, monkeypatch)
    state.set_confirm("LBL")
    monkeypatch.setitem(rr._CONFIG, "enabled", False)
    monkeypatch.setattr(rr.retire_logic, "retire", _boom)
    asyncio.run(_FakeRetireState.do_retire(state))
    assert state.phase == "armed" and state.error == ""


def test_in_flight_state_file_blocks_gather(enabled, monkeypatch):
    """Mutation: skip the in_flight call."""
    root, src = enabled
    _tree(root)
    pdir = src / "batch1" / "processing"
    pdir.mkdir(parents=True)
    sf = pdir / "x.state.json"
    sf.write_text(json.dumps({"sequence_uuid": U}))
    monkeypatch.setattr(rr.api, "get_client", _boom)
    state = _FakeRetireState()
    state.uuid_text = U
    asyncio.run(_FakeRetireState.gather(state))
    assert state.error == f"batch conversion in flight: {sf}"
    assert state.phase == "idle" and state.busy is False


def test_do_retire_success_reports_ledger_and_moved(enabled, monkeypatch):
    state, client = _gathered(enabled, monkeypatch)
    state.set_confirm("LBL")
    asyncio.run(_FakeRetireState.do_retire(state))
    assert state.error == ""
    assert state.phase == "done"
    assert os.path.exists(state.ledger)
    assert len(state.moved) == 1
    assert state._inv is None and state.armed is False and state.busy is False
    assert ("delete", "SEQUENCE", U) in client.calls


def test_every_foreach_var_carries_an_element_annotation():
    fields = rr.RetireState.get_fields()
    assert fields["counts"].annotated_type == list[list[str]]
    for name in ("warnings", "moved", "run_dirs", "analysis_dirs"):
        assert fields[name].annotated_type == list[str], name
