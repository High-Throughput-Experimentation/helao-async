"""Offline tests for the Reflex-free sync quarantine logic."""

import asyncio

import pytest

from helao.core.error import ErrorCodes
from helao.ui.shared import sync_quarantine as sq

T = ("SYNC", "127.0.0.1", 8010)
YML = "/r/RUNS_FINISHED/a/b/c/c-exp.yml"


@pytest.fixture
def dispatched(monkeypatch):
    calls = []
    reply = {"value": ({}, ErrorCodes.none)}

    async def _fake(**kwargs):
        calls.append(kwargs)
        r = reply["value"]
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(sq, "async_private_dispatcher", _fake)
    return calls, reply


def test_sync_target_resolves_sync_key():
    cfg = {"servers": {"SYNC": {"host": "h", "port": 8010}}}
    assert sq.sync_target(cfg) == ("SYNC", "h", 8010)
    assert sq.sync_target({"servers": {"OTHER": {"host": "h", "port": 1}}}) is None
    assert sq.sync_target({"servers": {"SYNC": {"host": "h"}}}) is None
    assert sq.sync_target({"servers": {"DB": {"host": "h", "port": 1}}}) is None


def test_fetch_unreachable_is_unknown_not_empty(dispatched):
    _, reply = dispatched
    reply["value"] = RuntimeError("down")
    assert asyncio.run(sq.fetch(T)) is None
    reply["value"] = ({"quarantined": []}, ErrorCodes.unspecified)
    assert asyncio.run(sq.fetch(T)) is None
    reply["value"] = ({"running": []}, ErrorCodes.none)
    assert asyncio.run(sq.fetch(T)) is None
    reply["value"] = ({"quarantined": []}, ErrorCodes.none)
    assert asyncio.run(sq.fetch(T)) == []
    reply["value"] = ({"quarantined": [{"uuid": "a"}]}, ErrorCodes.none)
    assert asyncio.run(sq.fetch(T)) == [{"uuid": "a"}]


def test_incomplete_needs_experiment_and_hint():
    assert sq.incomplete({"kind": "experiment", "immediate": True}) is True
    assert sq.incomplete({"kind": "action", "immediate": True}) is False
    assert sq.incomplete({"kind": "experiment"}) is False
    assert sq.incomplete({"kind": "experiment", "immediate": "yes"}) is False


def test_rows_shape_and_truncation():
    e = {
        "kind": "experiment",
        "path": "RUNS_FINISHED/a/b/dir-name",
        "yml": YML,
        "quarantined_at": "t",
        "strikes": 3,
        "last_error": "x" * 500,
        "immediate": True,
    }
    (row,) = sq.rows([e])
    assert row == [
        YML,
        "dir-name",
        "incomplete process group",
        "t",
        "3",
        "x" * 200,
        "1",
    ]
    e2 = {"kind": "experiment", "path": "p/q", "quarantined_at": "u", "strikes": 1}
    assert sq.rows([e2]) == [["", "q", "parked — see last error", "u", "1", "", ""]]


def test_is_armed():
    assert sq.is_armed("d", " d ", "why", "me") is True
    assert sq.is_armed("d", "D", "why", "me") is False
    assert sq.is_armed("dir", "di", "why", "me") is False
    assert sq.is_armed("d", "d", "  ", "me") is False
    assert sq.is_armed("d", "d", "why", "") is False
    assert sq.is_armed("", "", "why", "me") is False


def _call(fn, *a):
    return asyncio.run(fn(T, *a))


def test_mutating_calls_report_the_route_answer(dispatched):
    calls, reply = dispatched
    reply["value"] = (
        {"ok": True, "status": "written off", "groups": {"1": [2]}},
        ErrorCodes.none,
    )
    ok, msg = _call(sq.write_off, YML, "why", "me")
    c = calls[-1]
    assert c["retries"] == 1 and c["timeout"] == 10
    assert c["private_action"] == "write_off"
    assert c["params_dict"] == {"yml_path": YML, "reason": "why", "operator": "me"}
    assert (ok, msg) == (True, "written off (process groups 1)")

    reply["value"] = (
        {"ok": True, "status": "written off", "groups": {1: [2]}},
        ErrorCodes.none,
    )
    assert _call(sq.write_off, YML, "why", "me") == (
        True,
        "written off (process groups 1)",
    )
    reply["value"] = (
        {"ok": True, "status": "written off", "groups": {10: [], 2: []}},
        ErrorCodes.none,
    )
    assert (
        _call(sq.write_off, YML, "why", "me")[1] == "written off (process groups 2, 10)"
    )
    reply["value"] = (
        {"ok": True, "status": "written off", "groups": {"a": [], 1: []}},
        ErrorCodes.none,
    )
    assert _call(sq.write_off, YML, "why", "me")[0] is True

    reply["value"] = (
        {"ok": True, "status": "written off", "warning": "not re-queued: X"},
        ErrorCodes.none,
    )
    ok, msg = _call(sq.write_off, YML, "why", "me")
    assert (ok, msg) == (True, "written off; WARNING: not re-queued: X")

    reply["value"] = (
        {"ok": True, "status": "requeued", "at": "T", "operator": "bob"},
        ErrorCodes.none,
    )
    assert _call(sq.write_off, YML, "why", "me") == (
        True,
        "already written off at T by bob; re-queued",
    )
    reply["value"] = ({"ok": True, "status": "already synced"}, ErrorCodes.none)
    assert _call(sq.write_off, YML, "why", "me") == (True, "already synced")

    reply["value"] = ({"ok": False, "error": "not in sync quarantine"}, ErrorCodes.none)
    assert _call(sq.write_off, YML, "why", "me") == (False, "not in sync quarantine")

    unknown = (None, "sent, outcome unknown — refresh")
    reply["value"] = RuntimeError("boom")
    assert _call(sq.write_off, YML, "why", "me") == unknown
    reply["value"] = ({"ok": True, "status": "written off"}, ErrorCodes.unspecified)
    assert _call(sq.write_off, YML, "why", "me") == unknown
    reply["value"] = ({"detail": "x"}, ErrorCodes.none)
    assert _call(sq.write_off, YML, "why", "me") == unknown

    # release: /finish_yml echoes the path on success
    reply["value"] = (YML, ErrorCodes.none)
    ok, msg = _call(sq.release, YML)
    c = calls[-1]
    assert c["retries"] == 1 and c["private_action"] == "finish_yml"
    assert c["params_dict"] == {"yml_path": YML}
    assert (ok, msg) == (True, "released; re-queued")
    reply["value"] = RuntimeError("boom")
    assert _call(sq.release, YML) == unknown
    reply["value"] = ("/other.yml", ErrorCodes.none)
    assert _call(sq.release, YML) == unknown
    reply["value"] = (YML, ErrorCodes.unspecified)
    assert _call(sq.release, YML) == unknown
    reply["value"] = ({"detail": "Not Found"}, ErrorCodes.none)
    assert _call(sq.release, YML) == unknown
