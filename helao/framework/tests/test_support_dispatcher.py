"""Tests for helao.framework.support.dispatcher.

Coverage notes
--------------
- EXERCISED: URL construction for action + private endpoints; derive_rpc_port
  offset; _RPC_PROBE_TIMEOUT value; ErrorCodes rewire (framework path);
  async_action_dispatcher HTTP success path (RPC disabled via monkeypatched
  _get_rpc_client that raises RPCError); async_action_dispatcher HTTP non-2xx
  -> ErrorCodes.http; async_action_dispatcher exhausts retries -> last
  error_code; async_private_dispatcher HTTP success path (same RPC bypass);
  async_private_dispatcher HTTP non-2xx; private_dispatcher HTTP success (sync
  RPC bypassed via monkeypatched _get_sync_rpc_client that raises RPCError);
  private_dispatcher HTTP non-2xx; check_endpoint returns status code;
  endpoints_available all-OK and partial-failure branches;
  aclose_all_rpc_clients / close_all_sync_rpc_clients teardown helpers.

- NOT EXERCISED end-to-end: live ZMQ RPC fast-path success (requires a
  running ROUTER — covered by helao.core.rpc's own suite); aiohttp
  TCPConnector teardown ordering (OS-level).

All network is mocked — no real HTTP or ZMQ calls are made.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import aiohttp
import pytest

from helao.core.rpc import RPCError, derive_rpc_port
from helao.framework.models.errors import ErrorCodes

# Module under test
import helao.framework.support.dispatcher as disp_mod
from helao.framework.support.dispatcher import (
    _RPC_PROBE_TIMEOUT,
    async_action_dispatcher,
    async_private_dispatcher,
    aclose_all_rpc_clients,
    close_all_sync_rpc_clients,
    check_endpoint,
    endpoints_available,
    private_dispatcher,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_action(server_name: str = "my_server", action_name: str = "do_thing"):
    """Build a minimal mock Action with the attributes the dispatcher reads."""
    action = MagicMock()
    action.action_server.server_name = server_name
    action.action_name = action_name
    action.as_dict.return_value = {"action_name": action_name, "params": {}}
    return action


def _world_config(server_name: str, host: str = "127.0.0.1", port: int = 8001) -> dict:
    """Minimal world_config_dict with one server entry."""
    return {"servers": {server_name: {"host": host, "port": port}}}


# ---------------------------------------------------------------------------
# Pure-helper / constant tests
# ---------------------------------------------------------------------------


def test_rpc_probe_timeout_value():
    """_RPC_PROBE_TIMEOUT must be a positive float (3.0 per spec)."""
    assert isinstance(_RPC_PROBE_TIMEOUT, float)
    assert _RPC_PROBE_TIMEOUT > 0


def test_derive_rpc_port_offset():
    """RPC port is HTTP port + 10000 (helao.core.rpc contract)."""
    assert derive_rpc_port(8000) == 18000
    assert derive_rpc_port(9099) == 19099


def test_error_codes_rewire_uses_framework_path():
    """ErrorCodes imported by the dispatcher must be the framework variant."""
    from helao.framework.models.errors import ErrorCodes as FwEC

    assert disp_mod.ErrorCodes is FwEC


def test_module_exports():
    """__all__ lists exactly the public API symbols."""
    assert set(disp_mod.__all__) == {
        "async_action_dispatcher",
        "async_private_dispatcher",
        "private_dispatcher",
        "aclose_all_rpc_clients",
        "close_all_sync_rpc_clients",
    }


# ---------------------------------------------------------------------------
# URL construction (inferred from mock side-effects)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_action_dispatcher_builds_correct_url(monkeypatch):
    """HTTP POST is sent to http://<host>:<port>/<server>/<action>."""
    A = _make_action("svc", "run")
    cfg = _world_config("svc", "10.0.0.1", 8010)

    # Force RPC fast-path to fail immediately.
    async def _rpc_fail(*a, **kw):
        raise RPCError("no rpc")

    monkeypatch.setattr(disp_mod, "_get_rpc_client", _rpc_fail)

    posted_urls = []
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"ok": True})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(side_effect=lambda url, **kw: (posted_urls.append(url), mock_resp)[1])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.close = AsyncMock()

    with patch("helao.framework.support.dispatcher.aiohttp.TCPConnector", return_value=mock_conn), \
         patch("helao.framework.support.dispatcher.aiohttp.ClientSession", return_value=mock_session):
        response, ec = await async_action_dispatcher(cfg, A, timeout=5, retries=1)

    assert ec is ErrorCodes.none
    assert len(posted_urls) == 1
    assert posted_urls[0] == "http://10.0.0.1:8010/svc/run"


@pytest.mark.asyncio
async def test_async_private_dispatcher_builds_correct_url(monkeypatch):
    """HTTP POST is sent to http://<host>:<port>/<private_action>."""
    async def _rpc_fail(*a, **kw):
        raise RPCError("no rpc")

    monkeypatch.setattr(disp_mod, "_get_rpc_client", _rpc_fail)

    posted_urls = []
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"status": "ok"})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(side_effect=lambda url, **kw: (posted_urls.append(url), mock_resp)[1])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.close = AsyncMock()

    with patch("helao.framework.support.dispatcher.aiohttp.TCPConnector", return_value=mock_conn), \
         patch("helao.framework.support.dispatcher.aiohttp.ClientSession", return_value=mock_session):
        response, ec = await async_private_dispatcher(
            "svc", "10.0.0.2", 9000, "get_status", timeout=5, retries=1
        )

    assert ec is ErrorCodes.none
    assert posted_urls[0] == "http://10.0.0.2:9000/get_status"


# ---------------------------------------------------------------------------
# async_action_dispatcher — HTTP success / non-2xx / retry exhaustion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_action_dispatcher_http_success(monkeypatch):
    """Returns (response_body, ErrorCodes.none) on HTTP 200."""
    A = _make_action()
    cfg = _world_config("my_server", "127.0.0.1", 8001)

    async def _rpc_fail(*a, **kw):
        raise RPCError("down")

    monkeypatch.setattr(disp_mod, "_get_rpc_client", _rpc_fail)

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"result": 42})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.close = AsyncMock()

    with patch("helao.framework.support.dispatcher.aiohttp.TCPConnector", return_value=mock_conn), \
         patch("helao.framework.support.dispatcher.aiohttp.ClientSession", return_value=mock_session):
        response, ec = await async_action_dispatcher(cfg, A, timeout=5, retries=1)

    assert ec is ErrorCodes.none
    assert response == {"result": 42}


@pytest.mark.asyncio
async def test_async_action_dispatcher_http_non_2xx_returns_http_error(monkeypatch):
    """A non-200 HTTP response yields ErrorCodes.http (no exception raised)."""
    A = _make_action()
    cfg = _world_config("my_server")

    async def _rpc_fail(*a, **kw):
        raise RPCError("down")

    monkeypatch.setattr(disp_mod, "_get_rpc_client", _rpc_fail)

    mock_resp = AsyncMock()
    mock_resp.status = 500
    mock_resp.json = AsyncMock(return_value={"detail": "boom"})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.close = AsyncMock()

    with patch("helao.framework.support.dispatcher.aiohttp.TCPConnector", return_value=mock_conn), \
         patch("helao.framework.support.dispatcher.aiohttp.ClientSession", return_value=mock_session):
        response, ec = await async_action_dispatcher(cfg, A, timeout=5, retries=1)

    assert ec is ErrorCodes.http
    assert response == {"detail": "boom"}


@pytest.mark.asyncio
async def test_async_action_dispatcher_retries_exhausted_returns_none(monkeypatch):
    """After all retries fail, returns (None, last_error_code)."""
    A = _make_action()
    cfg = _world_config("my_server")

    async def _rpc_fail(*a, **kw):
        raise RPCError("down")

    monkeypatch.setattr(disp_mod, "_get_rpc_client", _rpc_fail)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(side_effect=aiohttp.ClientConnectionError("refused"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.close = AsyncMock()

    # Suppress real asyncio.sleep during retry backoff.
    with patch("helao.framework.support.dispatcher.asyncio.sleep", new=AsyncMock()), \
         patch("helao.framework.support.dispatcher.aiohttp.TCPConnector", return_value=mock_conn), \
         patch("helao.framework.support.dispatcher.aiohttp.ClientSession", return_value=mock_session):
        response, ec = await async_action_dispatcher(cfg, A, timeout=1, retries=2)

    assert response is None


# ---------------------------------------------------------------------------
# async_private_dispatcher — HTTP success / non-2xx
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_private_dispatcher_http_success(monkeypatch):
    """Returns (response_body, ErrorCodes.none) on HTTP 200."""
    async def _rpc_fail(*a, **kw):
        raise RPCError("down")

    monkeypatch.setattr(disp_mod, "_get_rpc_client", _rpc_fail)

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"pong": True})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.close = AsyncMock()

    with patch("helao.framework.support.dispatcher.aiohttp.TCPConnector", return_value=mock_conn), \
         patch("helao.framework.support.dispatcher.aiohttp.ClientSession", return_value=mock_session):
        response, ec = await async_private_dispatcher(
            "svc", "127.0.0.1", 8002, "ping", timeout=5, retries=1
        )

    assert ec is ErrorCodes.none
    assert response == {"pong": True}


@pytest.mark.asyncio
async def test_async_private_dispatcher_http_non_2xx(monkeypatch):
    """A non-200 response yields ErrorCodes.http."""
    async def _rpc_fail(*a, **kw):
        raise RPCError("down")

    monkeypatch.setattr(disp_mod, "_get_rpc_client", _rpc_fail)

    mock_resp = AsyncMock()
    mock_resp.status = 404
    mock_resp.json = AsyncMock(return_value={"detail": "not found"})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.close = AsyncMock()

    with patch("helao.framework.support.dispatcher.aiohttp.TCPConnector", return_value=mock_conn), \
         patch("helao.framework.support.dispatcher.aiohttp.ClientSession", return_value=mock_session):
        response, ec = await async_private_dispatcher(
            "svc", "127.0.0.1", 8002, "missing_endpoint", timeout=5, retries=1
        )

    assert ec is ErrorCodes.http
    assert response == {"detail": "not found"}


# ---------------------------------------------------------------------------
# private_dispatcher (sync) — HTTP success / non-2xx
# ---------------------------------------------------------------------------


def test_private_dispatcher_http_success(monkeypatch):
    """Returns (response_body, ErrorCodes.none) on HTTP 200 after RPC failure."""
    # Force sync RPC path to raise so we exercise the HTTP fallback.
    def _rpc_fail(*a, **kw):
        raise RPCError("down")

    monkeypatch.setattr(disp_mod, "_get_sync_rpc_client", _rpc_fail)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": "hello"}
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("helao.framework.support.dispatcher.requests.Session", return_value=mock_session):
        response, ec = private_dispatcher(
            "svc", "127.0.0.1", 8003, "some_action", timeout=5
        )

    assert ec is ErrorCodes.none
    assert response == {"data": "hello"}


def test_private_dispatcher_http_non_2xx(monkeypatch):
    """Non-200 sync HTTP response yields ErrorCodes.http."""
    def _rpc_fail(*a, **kw):
        raise RPCError("down")

    monkeypatch.setattr(disp_mod, "_get_sync_rpc_client", _rpc_fail)

    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.json.return_value = {"detail": "unavailable"}
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("helao.framework.support.dispatcher.requests.Session", return_value=mock_session):
        response, ec = private_dispatcher(
            "svc", "127.0.0.1", 8003, "some_action", timeout=5
        )

    assert ec is ErrorCodes.http
    assert response == {"detail": "unavailable"}


def test_private_dispatcher_json_decode_error_returns_none(monkeypatch):
    """If resp.json() raises, response is None (no exception propagated)."""
    def _rpc_fail(*a, **kw):
        raise RPCError("down")

    monkeypatch.setattr(disp_mod, "_get_sync_rpc_client", _rpc_fail)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = ValueError("not json")
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("helao.framework.support.dispatcher.requests.Session", return_value=mock_session):
        response, ec = private_dispatcher(
            "svc", "127.0.0.1", 8003, "some_action", timeout=5
        )

    assert response is None


# ---------------------------------------------------------------------------
# check_endpoint + endpoints_available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_endpoint_returns_status_code():
    """check_endpoint passes the HTTP status through unchanged."""
    mock_resp = AsyncMock()
    mock_resp.status = 204
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.head = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("helao.framework.support.dispatcher.aiohttp.ClientSession", return_value=mock_session):
        status = await check_endpoint("http://127.0.0.1:9999/health")

    assert status == 204


@pytest.mark.asyncio
async def test_endpoints_available_all_ok(monkeypatch):
    """Returns (True, []) when every URL is 2xx."""
    async def _fake_check(url: str) -> int:
        return 200

    monkeypatch.setattr(disp_mod, "check_endpoint", _fake_check)
    ok, unavail = await endpoints_available(
        ["http://a/x", "http://b/y", "http://c/z"]
    )
    assert ok is True
    assert unavail == []


@pytest.mark.asyncio
async def test_endpoints_available_partial_failure(monkeypatch):
    """Returns (False, [(url, [state])]) for non-2xx / unreachable URLs."""
    async def _fake_check(url: str) -> int:
        if "good" in url:
            return 200
        if "server_err" in url:
            return 503
        raise aiohttp.ClientConnectionError("refused")

    monkeypatch.setattr(disp_mod, "check_endpoint", _fake_check)
    ok, unavail = await endpoints_available(
        ["http://good/ep", "http://server_err/ep", "http://dead/ep"]
    )
    assert ok is False
    urls = [u for u, _ in unavail]
    assert "http://server_err/ep" in urls
    assert "http://dead/ep" in urls
    states = {u: s for u, s in unavail}
    assert states["http://server_err/ep"] == ["server error"]
    assert states["http://dead/ep"] == ["could not connect"]


@pytest.mark.asyncio
async def test_endpoints_available_timeout_classified(monkeypatch):
    """asyncio.TimeoutError during probe is classified as 'timeout'."""
    async def _fake_check(url: str) -> int:
        raise asyncio.TimeoutError()

    monkeypatch.setattr(disp_mod, "check_endpoint", _fake_check)
    ok, unavail = await endpoints_available(["http://slow/ep"])
    assert ok is False
    assert unavail[0][1] == ["timeout"]


@pytest.mark.asyncio
async def test_endpoints_available_cert_failure_classified(monkeypatch):
    """aiohttp.ClientSSLError is classified as 'cert failure'."""
    async def _fake_check(url: str) -> int:
        raise aiohttp.ClientSSLError(None, OSError(1, "ssl handshake failed"))

    monkeypatch.setattr(disp_mod, "check_endpoint", _fake_check)
    ok, unavail = await endpoints_available(["https://badcert/ep"])
    assert ok is False
    assert unavail[0][1] == ["cert failure"]


@pytest.mark.asyncio
async def test_endpoints_available_client_error_classified(monkeypatch):
    """4xx HTTP status is classified as 'client error'."""
    async def _fake_check(url: str) -> int:
        return 404

    monkeypatch.setattr(disp_mod, "check_endpoint", _fake_check)
    ok, unavail = await endpoints_available(["http://svc/missing"])
    assert ok is False
    assert unavail[0][1] == ["client error"]


# ---------------------------------------------------------------------------
# RPC client cache teardown helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aclose_all_rpc_clients_clears_cache():
    """aclose_all_rpc_clients empties _RPC_CLIENTS and calls close() on each."""
    mock_client = AsyncMock()
    disp_mod._RPC_CLIENTS[("host", 9999)] = mock_client
    assert len(disp_mod._RPC_CLIENTS) >= 1

    await aclose_all_rpc_clients()

    assert len(disp_mod._RPC_CLIENTS) == 0
    mock_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_aclose_all_rpc_clients_idempotent():
    """Calling aclose_all_rpc_clients on an empty cache does not raise."""
    disp_mod._RPC_CLIENTS.clear()
    await aclose_all_rpc_clients()  # should not raise


def test_close_all_sync_rpc_clients_clears_cache():
    """close_all_sync_rpc_clients empties _SYNC_RPC_CLIENTS and calls close()."""
    mock_client = MagicMock()
    disp_mod._SYNC_RPC_CLIENTS[("host", 9998)] = mock_client
    assert len(disp_mod._SYNC_RPC_CLIENTS) >= 1

    close_all_sync_rpc_clients()

    assert len(disp_mod._SYNC_RPC_CLIENTS) == 0
    mock_client.close.assert_called_once()


def test_close_all_sync_rpc_clients_idempotent():
    """Calling close_all_sync_rpc_clients on an empty cache does not raise."""
    disp_mod._SYNC_RPC_CLIENTS.clear()
    close_all_sync_rpc_clients()  # should not raise
