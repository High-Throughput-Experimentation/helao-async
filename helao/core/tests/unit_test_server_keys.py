"""Unit tests for syncer server-key resolution (SYNC; the DB key is retired).

No pytest; run with:

    conda run -n helao python -m helao.core.tests.unit_test_server_keys
"""

from helao.helpers.server_keys import (
    RETIRED_SYNC_SERVER_KEYS,
    SYNC_SERVER_KEY,
    get_sync_server_cfg,
    resolve_sync_server_key,
)


def test_resolves_sync_key():
    cfg = {"servers": {"ORCH": {}, "SYNC": {"params": {"a": 1}}}}
    assert resolve_sync_server_key(cfg) == "SYNC"
    print("test_resolves_sync_key PASS")


def test_retired_db_key_raises():
    """An unmigrated config must fail loudly, not silently stop syncing."""
    cfg = {"servers": {"ORCH": {}, "DB": {"params": {"a": 1}}}}
    for call in (resolve_sync_server_key, get_sync_server_cfg):
        try:
            call(cfg)
        except ValueError as exc:
            assert "DB" in str(exc) and SYNC_SERVER_KEY in str(exc), exc
        else:
            raise AssertionError(f"{call.__name__} accepted a retired DB key")
    print("test_retired_db_key_raises PASS")


def test_sync_present_ignores_stale_db_block():
    """A config carrying both keys resolves SYNC and does not raise."""
    cfg = {
        "servers": {"DB": {"params": {"old": True}}, "SYNC": {"params": {"new": True}}}
    }
    assert resolve_sync_server_key(cfg) == "SYNC"
    assert get_sync_server_cfg(cfg)["params"] == {"new": True}
    print("test_sync_present_ignores_stale_db_block PASS")


def test_absent_returns_none():
    """No syncer server -> None, which callers read as 'syncing not configured'."""
    assert resolve_sync_server_key({"servers": {"ORCH": {}}}) is None
    assert resolve_sync_server_key({}) is None
    assert resolve_sync_server_key(None) is None
    assert get_sync_server_cfg({"servers": {"ORCH": {}}}) == {}
    print("test_absent_returns_none PASS")


def test_preferred_key_wins():
    cfg = {"servers": {"SYNC": {"params": {"a": 1}}, "MYSYNC": {"params": {"b": 2}}}}
    assert resolve_sync_server_key(cfg, preferred="MYSYNC") == "MYSYNC"
    # a preferred key that is absent falls through to the normal order
    assert resolve_sync_server_key(cfg, preferred="NOPE") == "SYNC"
    print("test_preferred_key_wins PASS")


def test_retired_tuple_shape():
    assert SYNC_SERVER_KEY == "SYNC"
    assert "DB" in RETIRED_SYNC_SERVER_KEYS
    print("test_retired_tuple_shape PASS")


def run_all():
    test_resolves_sync_key()
    test_retired_db_key_raises()
    test_sync_present_ignores_stale_db_block()
    test_absent_returns_none()
    test_preferred_key_wins()
    test_retired_tuple_shape()
    print("ALL SERVER_KEYS TESTS PASS")


if __name__ == "__main__":
    run_all()
