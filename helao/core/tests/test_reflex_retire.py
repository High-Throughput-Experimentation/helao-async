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
    """Asymmetric on purpose: PROCESS is 3 local but 2 in the API.

    The first version of this test used one process each way (1/1), which is
    symmetric and could not see the two columns swapped; the brief's 3/3 was not
    asserted either.

    Mutation: swap the columns to [t, len(in_api[t]), len(local[t])].
    """
    root, _ = enabled
    make_run_tree(
        str(root),
        "RUNS_SYNCED",
        "26.40/1001/seqA",
        sequence_uuid=U,
        label="LBL",
        experiments={E1: [(A1, P1), ("a2", "p2")], "e2": [("a3", "p3")]},
    )
    client = FakeMetadataClient(
        {
            "SEQUENCE": {U},
            "EXPERIMENT": {E1, "e2"},
            "ACTION": {A1, "a2", "a3"},
            "PROCESS": {P1, "p2"},
        },
        seq_processes={U: [P1, "p2"]},
    )
    monkeypatch.setattr(rr.api, "get_client", lambda: client)
    state = _FakeRetireState()
    state.uuid_text = U
    asyncio.run(_FakeRetireState.gather(state))
    assert state.error == ""
    assert state.counts == [
        ["EXPERIMENT", "2", "2"],
        ["ACTION", "3", "3"],
        ["PROCESS", "3", "2"],
        ["ANALYSIS", "0", "0"],
        ["SEQUENCE", "1", "present"],
    ]
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


def test_set_uuid_and_confirm_are_no_ops_while_busy(enabled, monkeypatch):
    """Mutation: drop the `if self.busy: return` guard in set_uuid/set_confirm."""
    state, _ = _gathered(enabled, monkeypatch)
    state.set_confirm("LBL")
    state.ledger = "L"
    state.busy = True
    state.set_uuid("other")
    state.set_confirm("zzz")
    assert state.uuid_text == U
    assert state._inv is not None
    assert state.ledger == "L"
    assert state.confirm_text == "LBL" and state.armed is True


def _armed(enabled, monkeypatch):
    state, client = _gathered(enabled, monkeypatch)
    state.set_confirm("LBL")
    return state, client


def test_do_retire_resets_progress_on_entering_retiring(enabled, monkeypatch):
    """Mutation: drop `self.progress = 0` from the retiring block."""
    state, _ = _armed(enabled, monkeypatch)
    state.progress = 57
    seen = {}

    async def fake_retire(client, root, inv, cb, ledger):
        seen["progress"], seen["phase"] = state.progress, state.phase
        return rr.retire_logic.RetireResult(True, ledger, {}, {}, {}, [])

    monkeypatch.setattr(rr.retire_logic, "retire", fake_retire)
    asyncio.run(_FakeRetireState.do_retire(state))
    assert seen == {"progress": 0, "phase": "retiring"}


def test_do_retire_get_client_failure_leaves_no_ledger(enabled, monkeypatch):
    """Mutation: set self.ledger before get_client, or drop the suffix."""
    state, _ = _armed(enabled, monkeypatch)

    def no_client():
        raise RuntimeError("spec fetch failed")

    monkeypatch.setattr(rr.api, "get_client", no_client)
    monkeypatch.setattr(rr.retire_logic, "retire", _boom)
    asyncio.run(_FakeRetireState.do_retire(state))
    assert state.phase == "failed"
    assert state.ledger == ""
    assert state.error == "spec fetch failed; no files were moved"
    assert state.busy is False and state._inv is None and state.armed is False


def test_do_retire_failed_result_reports_error(enabled, monkeypatch):
    """Mutation: map result.ok=False to phase "done", or leave busy/_inv set."""
    state, _ = _armed(enabled, monkeypatch)

    async def fake_retire(client, root, inv, cb, ledger):
        return rr.retire_logic.RetireResult(False, ledger, {}, {}, {}, [], "boom")

    monkeypatch.setattr(rr.retire_logic, "retire", fake_retire)
    asyncio.run(_FakeRetireState.do_retire(state))
    assert state.phase == "failed"
    assert state.error == "boom"
    assert state.busy is False and state._inv is None and state.armed is False


def test_non_uuid_gather_after_done_returns_to_idle(enabled, monkeypatch):
    """Mutation: drop `self.phase = "idle"` from the non-uuid branch."""
    state, _ = _armed(enabled, monkeypatch)
    asyncio.run(_FakeRetireState.do_retire(state))
    assert state.phase == "done"
    state.uuid_text = "nope"
    asyncio.run(_FakeRetireState.gather(state))
    assert state.error == "not a uuid"
    assert state.phase == "idle"


def test_gather_exception_leaves_idle_unarmed(enabled, monkeypatch):
    """Mutation: leave phase "gathering"/busy set when inventory raises."""
    root, _ = enabled
    _tree(root)
    client = _client()
    client.fail[("read", U)] = "500"
    monkeypatch.setattr(rr.api, "get_client", lambda: client)
    state = _FakeRetireState()
    state.uuid_text = U
    asyncio.run(_FakeRetireState.gather(state))
    assert "500" in state.error
    assert state.phase == "idle" and state.busy is False
    assert state.armed is False and state._inv is None


def test_gather_nothing_to_retire(enabled, monkeypatch):
    """Mutation: fill the vars (phase "gathered") even when nothing is found."""
    client = FakeMetadataClient({})
    monkeypatch.setattr(rr.api, "get_client", lambda: client)
    state = _FakeRetireState()
    state.uuid_text = U
    asyncio.run(_FakeRetireState.gather(state))
    assert state.status == "nothing to retire"
    assert state.phase == "idle" and state._inv is None and state.busy is False


def test_gather_api_only_warns(enabled, monkeypatch):
    """Mutation: drop the api_only warning."""
    client = FakeMetadataClient({"SEQUENCE": {U}})
    monkeypatch.setattr(rr.api, "get_client", lambda: client)
    state = _FakeRetireState()
    state.uuid_text = U
    asyncio.run(_FakeRetireState.gather(state))
    assert state.phase == "gathered"
    assert state.warnings == [
        "experiments/actions unknowable from API alone; "
        "processes may already be gone"
    ]
