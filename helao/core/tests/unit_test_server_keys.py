"""Unit tests for syncer server-key resolution (SYNC, with the legacy DB alias).

No pytest; run with:

    conda run -n helao python -m helao.core.tests.unit_test_server_keys
"""

from helao.helpers import server_keys
from helao.helpers.server_keys import (
    LEGACY_SYNC_SERVER_KEYS,
    SYNC_SERVER_KEY,
    get_sync_server_cfg,
    resolve_sync_server_key,
)


def test_resolves_sync_key():
    cfg = {"servers": {"ORCH": {}, "SYNC": {"params": {"a": 1}}}}
    assert resolve_sync_server_key(cfg) == "SYNC"
    print("test_resolves_sync_key PASS")


def test_resolves_legacy_db_key():
    """An unmigrated config must keep syncing rather than silently disabling."""
    cfg = {"servers": {"ORCH": {}, "DB": {"params": {"a": 1}}}}
    assert resolve_sync_server_key(cfg) == "DB"
    print("test_resolves_legacy_db_key PASS")


def test_sync_wins_over_legacy():
    cfg = {
        "servers": {"DB": {"params": {"old": True}}, "SYNC": {"params": {"new": True}}}
    }
    assert resolve_sync_server_key(cfg) == "SYNC"
    assert get_sync_server_cfg(cfg)["params"] == {"new": True}
    print("test_sync_wins_over_legacy PASS")


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


def test_legacy_warns_once_per_key():
    server_keys._WARNED.clear()
    warnings = []

    class _Rec:
        def warning(self, msg, *a, **k):
            warnings.append(msg)

    orig = server_keys._logger
    server_keys._logger = lambda: _Rec()
    try:
        cfg = {"servers": {"DB": {}}}
        for _ in range(3):
            assert resolve_sync_server_key(cfg) == "DB"
        assert len(warnings) == 1, warnings
        assert "DB" in warnings[0] and SYNC_SERVER_KEY in warnings[0]
        # the SYNC key never warns
        assert resolve_sync_server_key({"servers": {"SYNC": {}}}) == "SYNC"
        assert len(warnings) == 1, warnings
    finally:
        server_keys._logger = orig
        server_keys._WARNED.clear()
    print("test_legacy_warns_once_per_key PASS")


def test_legacy_tuple_shape():
    assert SYNC_SERVER_KEY == "SYNC"
    assert "DB" in LEGACY_SYNC_SERVER_KEYS
    print("test_legacy_tuple_shape PASS")


def run_all():
    test_resolves_sync_key()
    test_resolves_legacy_db_key()
    test_sync_wins_over_legacy()
    test_absent_returns_none()
    test_preferred_key_wins()
    test_legacy_warns_once_per_key()
    test_legacy_tuple_shape()
    print("ALL SERVER_KEYS TESTS PASS")


if __name__ == "__main__":
    run_all()
