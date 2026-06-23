import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
import zmq

import helao.framework.support.dispatcher as disp
from helao.core.rpc import RPCError
from helao.framework.models.errors import ErrorCodes


@pytest.fixture(autouse=True)
def _clear_rpc_caches():
    disp._RPC_CLIENTS.clear()
    disp._SYNC_RPC_CLIENTS.clear()
    yield
    disp._RPC_CLIENTS.clear()
    disp._SYNC_RPC_CLIENTS.clear()


def _action(server_name="SRV", action_name="run"):
    a = MagicMock()
    a.action_server.server_name = server_name
    a.action_name = action_name
    a.as_dict.return_value = {"action_name": action_name}
    return a


def _world(server_name="SRV", host="localhost", port=8000):
    return {"servers": {server_name: {"host": host, "port": port}}}


def _mock_aiohttp_session(status=200, json_body=None):
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_body or {"ok": True})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_conn = MagicMock()
    mock_conn.close = AsyncMock()
    return mock_session, mock_conn


# ── _get_rpc_client ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_rpc_client_creates_and_caches():
    with patch("helao.framework.support.dispatcher.RPCClient") as MockRPC:
        MockRPC.return_value = MagicMock()
        c1 = await disp._get_rpc_client("localhost", 8000)
        c2 = await disp._get_rpc_client("localhost", 8000)
        assert c1 is c2
        MockRPC.assert_called_once()


@pytest.mark.asyncio
async def test_get_rpc_client_different_hosts_create_separate():
    with patch("helao.framework.support.dispatcher.RPCClient") as MockRPC:
        MockRPC.side_effect = lambda **kw: MagicMock()
        c1 = await disp._get_rpc_client("host1", 8000)
        c2 = await disp._get_rpc_client("host2", 8000)
        assert c1 is not c2
        assert MockRPC.call_count == 2


# ── aclose_all_rpc_clients ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_aclose_all_rpc_clients_empty_noop():
    await disp.aclose_all_rpc_clients()


@pytest.mark.asyncio
async def test_aclose_all_rpc_clients_calls_close():
    mock_client = AsyncMock()
    disp._RPC_CLIENTS[("h", 1)] = mock_client
    await disp.aclose_all_rpc_clients()
    mock_client.close.assert_called_once()
    assert len(disp._RPC_CLIENTS) == 0


@pytest.mark.asyncio
async def test_aclose_all_rpc_clients_suppresses_close_error():
    mock_client = AsyncMock()
    mock_client.close.side_effect = RuntimeError("boom")
    disp._RPC_CLIENTS[("h", 1)] = mock_client
    await disp.aclose_all_rpc_clients()


# ── _get_sync_rpc_client ─────────────────────────────────────────────────────

def test_get_sync_rpc_client_creates_and_caches():
    with patch("helao.framework.support.dispatcher.RPCSyncClient") as MockSync:
        MockSync.return_value = MagicMock()
        c1 = disp._get_sync_rpc_client("localhost", 8001)
        c2 = disp._get_sync_rpc_client("localhost", 8001)
        assert c1 is c2
        MockSync.assert_called_once()


def test_get_sync_rpc_client_different_ports():
    with patch("helao.framework.support.dispatcher.RPCSyncClient") as MockSync:
        MockSync.side_effect = lambda **kw: MagicMock()
        disp._get_sync_rpc_client("localhost", 8001)
        disp._get_sync_rpc_client("localhost", 8002)
        assert MockSync.call_count == 2


# ── close_all_sync_rpc_clients ───────────────────────────────────────────────

def test_close_all_sync_rpc_clients_empty_noop():
    disp.close_all_sync_rpc_clients()


def test_close_all_sync_rpc_clients_calls_close():
    mock_client = MagicMock()
    disp._SYNC_RPC_CLIENTS[("h", 2)] = mock_client
    disp.close_all_sync_rpc_clients()
    mock_client.close.assert_called_once()
    assert len(disp._SYNC_RPC_CLIENTS) == 0


def test_close_all_sync_rpc_clients_suppresses_error():
    mock_client = MagicMock()
    mock_client.close.side_effect = RuntimeError("boom")
    disp._SYNC_RPC_CLIENTS[("h", 2)] = mock_client
    disp.close_all_sync_rpc_clients()


# ── async_action_dispatcher ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_async_action_dispatcher_rpc_success():
    mock_rpc = AsyncMock()
    mock_rpc.call.return_value = {"ok": True}
    with patch("helao.framework.support.dispatcher._get_rpc_client", return_value=mock_rpc):
        result, err = await disp.async_action_dispatcher(_world(), _action())
    assert err == ErrorCodes.none
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_async_action_dispatcher_rpc_error_falls_back_to_http():
    mock_rpc = AsyncMock()
    mock_rpc.call.side_effect = RPCError("down")
    mock_session, mock_conn = _mock_aiohttp_session(200)
    with patch("helao.framework.support.dispatcher._get_rpc_client", return_value=mock_rpc), \
         patch("helao.framework.support.dispatcher.aiohttp.ClientSession", return_value=mock_session), \
         patch("helao.framework.support.dispatcher.aiohttp.TCPConnector", return_value=mock_conn):
        result, err = await disp.async_action_dispatcher(_world(), _action(), retries=1)
    assert err == ErrorCodes.none


@pytest.mark.asyncio
async def test_async_action_dispatcher_zmq_error_falls_back():
    mock_rpc = AsyncMock()
    mock_rpc.call.side_effect = zmq.ZMQError()
    mock_session, mock_conn = _mock_aiohttp_session(200)
    with patch("helao.framework.support.dispatcher._get_rpc_client", return_value=mock_rpc), \
         patch("helao.framework.support.dispatcher.aiohttp.ClientSession", return_value=mock_session), \
         patch("helao.framework.support.dispatcher.aiohttp.TCPConnector", return_value=mock_conn):
        result, err = await disp.async_action_dispatcher(_world(), _action(), retries=1)
    assert err == ErrorCodes.none


@pytest.mark.asyncio
async def test_async_action_dispatcher_http_non_200_exhausts_retries():
    mock_rpc = AsyncMock()
    mock_rpc.call.side_effect = asyncio.TimeoutError()
    mock_session, mock_conn = _mock_aiohttp_session(500)
    with patch("helao.framework.support.dispatcher._get_rpc_client", return_value=mock_rpc), \
         patch("helao.framework.support.dispatcher.aiohttp.ClientSession", return_value=mock_session), \
         patch("helao.framework.support.dispatcher.aiohttp.TCPConnector", return_value=mock_conn), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        result, err = await disp.async_action_dispatcher(_world(), _action(), retries=1, timeout=0.01)
    assert err != ErrorCodes.none


@pytest.mark.asyncio
async def test_async_action_dispatcher_http_exception_exhausts_retries():
    mock_rpc = AsyncMock()
    mock_rpc.call.side_effect = OSError("no route")
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.post.side_effect = Exception("conn refused")
    mock_conn = AsyncMock()
    mock_conn.close = AsyncMock()
    with patch("helao.framework.support.dispatcher._get_rpc_client", return_value=mock_rpc), \
         patch("helao.framework.support.dispatcher.aiohttp.ClientSession", return_value=mock_session), \
         patch("helao.framework.support.dispatcher.aiohttp.TCPConnector", return_value=mock_conn), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        result, err = await disp.async_action_dispatcher(_world(), _action(), retries=1, timeout=0.01)
    assert result is None


# ── async_private_dispatcher ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_async_private_dispatcher_rpc_success():
    mock_rpc = AsyncMock()
    mock_rpc.call.return_value = {"pong": True}
    with patch("helao.framework.support.dispatcher._get_rpc_client", return_value=mock_rpc):
        result, err = await disp.async_private_dispatcher("SRV", "localhost", 8000, "ping")
    assert err == ErrorCodes.none
    assert result == {"pong": True}


@pytest.mark.asyncio
async def test_async_private_dispatcher_rpc_failure_http_success():
    mock_rpc = AsyncMock()
    mock_rpc.call.side_effect = RPCError("down")
    mock_session, mock_conn = _mock_aiohttp_session(200)
    with patch("helao.framework.support.dispatcher._get_rpc_client", return_value=mock_rpc), \
         patch("helao.framework.support.dispatcher.aiohttp.ClientSession", return_value=mock_session), \
         patch("helao.framework.support.dispatcher.aiohttp.TCPConnector", return_value=mock_conn):
        result, err = await disp.async_private_dispatcher("SRV", "localhost", 8000, "ping", retries=1)
    assert err == ErrorCodes.none


@pytest.mark.asyncio
async def test_async_private_dispatcher_http_non_200():
    mock_rpc = AsyncMock()
    mock_rpc.call.side_effect = zmq.ZMQError()
    mock_session, mock_conn = _mock_aiohttp_session(503)
    with patch("helao.framework.support.dispatcher._get_rpc_client", return_value=mock_rpc), \
         patch("helao.framework.support.dispatcher.aiohttp.ClientSession", return_value=mock_session), \
         patch("helao.framework.support.dispatcher.aiohttp.TCPConnector", return_value=mock_conn), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        result, err = await disp.async_private_dispatcher("SRV", "localhost", 8000, "ping", retries=1, timeout=0.01)
    assert err != ErrorCodes.none


# ── private_dispatcher ───────────────────────────────────────────────────────

def _sync_session_mock(status_code=200, json_body=None, json_raises=False):
    mock_resp = MagicMock()
    if json_raises:
        mock_resp.json.side_effect = Exception("bad json")
    else:
        mock_resp.json.return_value = json_body or {"data": 1}
    mock_resp.status_code = status_code
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_resp)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.post.return_value = mock_ctx
    return mock_session


def test_private_dispatcher_rpc_success():
    mock_client = MagicMock()
    mock_client.call.return_value = {"pong": True}
    with patch("helao.framework.support.dispatcher._get_sync_rpc_client", return_value=mock_client):
        result, err = disp.private_dispatcher("SRV", "localhost", 8000, "ping")
    assert err == ErrorCodes.none
    assert result == {"pong": True}


def test_private_dispatcher_rpc_failure_http_200():
    mock_client = MagicMock()
    mock_client.call.side_effect = RPCError("down")
    with patch("helao.framework.support.dispatcher._get_sync_rpc_client", return_value=mock_client), \
         patch("helao.framework.support.dispatcher.requests.Session", return_value=_sync_session_mock(200)):
        result, err = disp.private_dispatcher("SRV", "localhost", 8000, "ping")
    assert err == ErrorCodes.none


def test_private_dispatcher_rpc_failure_http_non_200():
    mock_client = MagicMock()
    mock_client.call.side_effect = OSError("down")
    with patch("helao.framework.support.dispatcher._get_sync_rpc_client", return_value=mock_client), \
         patch("helao.framework.support.dispatcher.requests.Session", return_value=_sync_session_mock(500)):
        result, err = disp.private_dispatcher("SRV", "localhost", 8000, "ping")
    assert err == ErrorCodes.http


def test_private_dispatcher_rpc_failure_http_json_error():
    mock_client = MagicMock()
    mock_client.call.side_effect = TimeoutError("timeout")
    with patch("helao.framework.support.dispatcher._get_sync_rpc_client", return_value=mock_client), \
         patch("helao.framework.support.dispatcher.requests.Session", return_value=_sync_session_mock(200, json_raises=True)):
        result, err = disp.private_dispatcher("SRV", "localhost", 8000, "ping")
    assert result is None


def test_private_dispatcher_zmq_error_http_fallback():
    mock_client = MagicMock()
    mock_client.call.side_effect = zmq.ZMQError()
    with patch("helao.framework.support.dispatcher._get_sync_rpc_client", return_value=mock_client), \
         patch("helao.framework.support.dispatcher.requests.Session", return_value=_sync_session_mock(200)):
        result, err = disp.private_dispatcher("SRV", "localhost", 8000, "ping")
    assert err == ErrorCodes.none


# ── check_endpoint ───────────────────────────────────────────────────────────

def _mock_check_session(status):
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    mock_session = MagicMock()
    mock_session.head = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


@pytest.mark.asyncio
async def test_check_endpoint_returns_200():
    with patch("helao.framework.support.dispatcher.aiohttp.ClientSession",
               return_value=_mock_check_session(200)):
        status = await disp.check_endpoint("http://localhost/test")
    assert status == 200


@pytest.mark.asyncio
async def test_check_endpoint_returns_404():
    with patch("helao.framework.support.dispatcher.aiohttp.ClientSession",
               return_value=_mock_check_session(404)):
        status = await disp.check_endpoint("http://localhost/missing")
    assert status == 404


# ── endpoints_available ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_endpoints_available_all_2xx():
    with patch("helao.framework.support.dispatcher.check_endpoint", AsyncMock(return_value=200)):
        ok, unavail = await disp.endpoints_available(["http://a", "http://b"])
    assert ok is True
    assert unavail == []


@pytest.mark.asyncio
async def test_endpoints_available_4xx():
    with patch("helao.framework.support.dispatcher.check_endpoint", AsyncMock(return_value=404)):
        ok, unavail = await disp.endpoints_available(["http://a"])
    assert ok is False
    assert unavail[0][1] == ["client error"]


@pytest.mark.asyncio
async def test_endpoints_available_5xx():
    with patch("helao.framework.support.dispatcher.check_endpoint", AsyncMock(return_value=500)):
        ok, unavail = await disp.endpoints_available(["http://a"])
    assert ok is False
    assert unavail[0][1] == ["server error"]


@pytest.mark.asyncio
async def test_endpoints_available_3xx_no_success():
    with patch("helao.framework.support.dispatcher.check_endpoint", AsyncMock(return_value=301)):
        ok, unavail = await disp.endpoints_available(["http://a"])
    assert ok is False
    assert unavail[0][1] == ["no success"]


@pytest.mark.asyncio
async def test_endpoints_available_ssl_error():
    with patch("helao.framework.support.dispatcher.check_endpoint",
               AsyncMock(side_effect=aiohttp.ClientSSLError(MagicMock(), OSError("ssl")))):
        ok, unavail = await disp.endpoints_available(["http://a"])
    assert ok is False
    assert unavail[0][1] == ["cert failure"]


@pytest.mark.asyncio
async def test_endpoints_available_connection_error():
    with patch("helao.framework.support.dispatcher.check_endpoint",
               AsyncMock(side_effect=aiohttp.ClientConnectionError())):
        ok, unavail = await disp.endpoints_available(["http://a"])
    assert ok is False
    assert unavail[0][1] == ["could not connect"]


@pytest.mark.asyncio
async def test_endpoints_available_timeout():
    with patch("helao.framework.support.dispatcher.check_endpoint",
               AsyncMock(side_effect=asyncio.TimeoutError())):
        ok, unavail = await disp.endpoints_available(["http://a"])
    assert ok is False
    assert unavail[0][1] == ["timeout"]


@pytest.mark.asyncio
async def test_endpoints_available_mixed():
    async def _side_effect(url):
        if url == "http://good":
            return 200
        raise aiohttp.ClientConnectionError()

    with patch("helao.framework.support.dispatcher.check_endpoint", side_effect=_side_effect):
        ok, unavail = await disp.endpoints_available(["http://good", "http://bad"])
    assert ok is False
    assert len(unavail) == 1
    assert unavail[0][0] == "http://bad"
