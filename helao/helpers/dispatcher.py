"""Inter-server RPC/HTTP dispatch primitives.

Provides async and sync helpers for invoking action endpoints and private
admin endpoints on peer HELAO servers. Each helper tries a ZMQ RPC fast
path first and transparently falls back to HTTP if the peer's RPC
dispatcher is unreachable. Module-level caches keep one DEALER and one
REQ client per ``(host, port)`` peer and are torn down via
:func:`aclose_all_rpc_clients` and :func:`close_all_sync_rpc_clients`.
"""

__all__ = [
    "async_action_dispatcher",
    "async_private_dispatcher",
    "private_dispatcher",
    "aclose_all_rpc_clients",
    "close_all_sync_rpc_clients",
]

import asyncio
from typing import Dict, Tuple

import aiohttp
import requests
import zmq

from .premodels import Action
from helao.core.error import ErrorCodes
from helao.core.rpc import RPCClient, RPCSyncClient, RPCError, derive_rpc_port

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

# ---------------------------------------------------------------------------
# Module-level RPC client cache shared by every async_private_dispatcher call.
#
# DEALER sockets are persistent and concurrent-safe (id-correlated futures
# inside RPCClient), so one cached client per peer is both cheaper than
# spinning aiohttp sessions and avoids the aiohttp connector teardown churn.
# Process-level cleanup is the OS's job; callers that want graceful shutdown
# (e.g. test harnesses) can invoke ``aclose_all_rpc_clients()``.
# ---------------------------------------------------------------------------

_RPC_CLIENTS: Dict[Tuple[str, int], RPCClient] = {}
_RPC_CLIENTS_LOCK = asyncio.Lock()

# Sibling cache for the sync (``zmq.REQ``-backed) clients used by
# :func:`private_dispatcher`.  No async lock needed -- sync callers can't
# race on a single-threaded REQ socket the way async tasks can.
_SYNC_RPC_CLIENTS: Dict[Tuple[str, int], RPCSyncClient] = {}

# Short timeout for the RPC probe.  If the peer's dispatcher is up, replies
# arrive in <10 ms on localhost; if it's down, the DEALER socket happily
# queues messages without erroring, so a low timeout is the only way we
# learn to fall back.  Long-running calls should pass explicit timeout.
_RPC_PROBE_TIMEOUT = 3.0


def _query_safe(params: dict) -> dict:
    """Coerce a params dict into values aiohttp/yarl accept as query values.

    aiohttp's query-string encoder (yarl) accepts only ``str``/``int``/``float``
    and raises ``TypeError: Invalid variable type`` on anything else -- notably
    a ``bool`` action param such as ``external_trigger`` (``ANDOR/acquire``),
    which otherwise crashes the HTTP-fallback POST and gets swallowed by the
    retry loop as an escalating-sleep "hang". Map ``bool`` -> ``"true"``/
    ``"false"`` (FastAPI parses these back to ``bool`` on the server, and the
    action envelope's ``action_params`` -- which carries the real typed value
    and wins in ``_build_action_from_kwargs`` -- is unaffected), drop ``None``
    (yarl rejects it too; the endpoint default / envelope supplies it), and pass
    ``str``/``int``/``float`` through unchanged. Non-scalar values (list/dict)
    are left as-is: those belong in the action envelope body, not the query
    string, so they are out of scope for this coercion.
    """
    safe: dict = {}
    for key, val in (params or {}).items():
        if isinstance(val, bool):
            safe[key] = "true" if val else "false"
        elif val is None:
            continue
        else:
            safe[key] = val
    return safe


async def _get_rpc_client(host: str, port: int) -> RPCClient:
    """Return (or lazily create) the cached async RPC client for one peer.

    Args:
        host: Hostname or IP of the peer server.
        port: HTTP port; the matching RPC port is derived via
            :func:`derive_rpc_port`.

    Returns:
        The shared :class:`RPCClient` for ``(host, port)``.
    """
    key = (host, port)
    client = _RPC_CLIENTS.get(key)
    if client is not None:
        return client
    async with _RPC_CLIENTS_LOCK:
        client = _RPC_CLIENTS.get(key)
        if client is None:
            client = RPCClient(
                endpoint=f"tcp://{host}:{derive_rpc_port(port)}",
                default_timeout=_RPC_PROBE_TIMEOUT,
            )
            _RPC_CLIENTS[key] = client
    return client


async def aclose_all_rpc_clients() -> None:
    """Close and discard every cached async RPC client. Idempotent."""
    clients = list(_RPC_CLIENTS.values())
    _RPC_CLIENTS.clear()
    for client in clients:
        try:
            await client.close()
        except Exception:
            LOGGER.exception("error closing module-cached RPC client")


async def async_action_dispatcher(
    world_config_dict: dict,
    A: Action,
    params: dict = {},
    timeout: int = 60,
    retries: int = 5,
) -> tuple:
    """Dispatch an action to its action server, trying RPC then HTTP.

    Resolves the destination from ``world_config_dict['servers'][A.action_server.server_name]``,
    attempts a ZMQ RPC call to ``<server>/<action>``, and on any RPC error
    or timeout retries over HTTP. The HTTP fallback is the legacy path
    that runs through the action-queuing middleware in
    :class:`BaseAPI`; the RPC fast path bypasses that middleware and
    relies on orchestrator-side endpoint coordination instead.

    Args:
        world_config_dict: Loaded HELAO config dict containing the
            ``servers`` mapping.
        A: Action to dispatch; its ``action_server`` and ``action_name``
            select the destination endpoint.
        params: Extra query parameters merged into the RPC kwargs and the
            HTTP query string.
        timeout: Per-request timeout in seconds; capped by the RPC probe
            timeout when used for the fast path.
        retries: Maximum HTTP retry attempts before giving up.

    Returns:
        ``(response, error_code)`` where ``response`` is the decoded JSON
        body (or ``None`` on failure) and ``error_code`` is an
        :class:`ErrorCodes` value.
    """
    actd = world_config_dict["servers"][A.action_server.server_name]
    act_addr = actd["host"]
    act_port = actd["port"]

    # --- ZMQ RPC fast-path ----------------------------------------------
    rpc_method = f"{A.action_server.server_name}/{A.action_name}"
    rpc_args: dict = {}
    rpc_args.update(params or {})
    rpc_args["action"] = A.as_dict()
    try:
        client = await _get_rpc_client(act_addr, act_port)
        # Pass params via `args=` (not `**rpc_args`) so an action param named
        # `timeout` (e.g. ANDOR/acquire) cannot collide with call()'s own
        # `timeout` kwarg ("got multiple values for keyword argument 'timeout'").
        result = await client.call(
            rpc_method,
            timeout=min(timeout, _RPC_PROBE_TIMEOUT),
            args=rpc_args,
        )
        return result, ErrorCodes.none
    except (RPCError, asyncio.TimeoutError, zmq.ZMQError, OSError) as e:
        LOGGER.debug(
            f"RPC {rpc_method} fast-path failed "
            f"({type(e).__name__}: {e}); falling back to HTTP"
        )

    # --- HTTP fallback (legacy path with action-queuing middleware) ------
    url = f"http://{act_addr}:{act_port}/{A.action_server.server_name}/{A.action_name}"
    success = False
    retry_count = 0

    client_timeout = aiohttp.ClientTimeout(total=timeout)
    error_code = ErrorCodes.unspecified
    response = None

    while not success and retry_count < retries:
        conn = aiohttp.TCPConnector(
            force_close=True, enable_cleanup_closed=True, limit=1000
        )
        try:
            async with aiohttp.ClientSession(
                timeout=client_timeout, connector=conn
            ) as session:
                async with session.post(
                    url,
                    params=_query_safe(params),
                    json={"action": A.as_dict()},
                ) as resp:
                    response = await resp.json()
                    error_code = ErrorCodes.none
                    if resp.status != 200:
                        error_code = ErrorCodes.http
                        LOGGER.error(
                            f"{A.action_server.server_name}/{A.action_name} POST request returned status {resp.status}: '{response}', error={error_code}"
                        )
                        success = False
                    else:
                        success = True
        except Exception:
            retry_count += 1
            retry_wait = retry_count * timeout / 2
            LOGGER.warning(
                f"{A.action_server.server_name}/{A.action_name} encountered an error, sleeping for {retry_wait} seconds before retrying...",
                exc_info=True,
            )
            await asyncio.sleep(retry_wait)
            response = None
        finally:
            await conn.close()
    if not success:
        LOGGER.error(
            f"{A.action_server.server_name}/{A.action_name} async_action_dispatcher could not decide response: '{response}')",
            exc_info=True,
        )

    await asyncio.sleep(0)
    return response, error_code


async def async_private_dispatcher(
    server_key: str,
    host: str,
    port: int,
    private_action: str,
    params_dict: dict = {},
    json_dict: dict = {},
    timeout: int = 60,
    retries: int = 5,
) -> tuple:
    """Call a private (non-action) endpoint on a peer server with RPC-then-HTTP fallback.

    The ZMQ RPC fast path is used when the peer's :class:`HelaoFastAPI`
    has an RPC dispatcher bound on ``derive_rpc_port(port)``; otherwise
    or on any RPC error the call is retried over HTTP. ``params_dict``
    and ``json_dict`` are merged into a single kwargs map for the RPC
    handler; the HTTP path sends them as query string and JSON body
    respectively.

    Args:
        server_key: Logging identifier for the destination server.
        host: Hostname or IP of the destination.
        port: HTTP port of the destination (the RPC port is derived from it).
        private_action: Endpoint path (without leading slash).
        params_dict: Query-parameter dict for the HTTP path / kwargs for RPC.
        json_dict: JSON body for the HTTP path / kwargs for RPC.
        timeout: Per-request timeout in seconds.
        retries: Maximum HTTP retry attempts before giving up.

    Returns:
        ``(response, error_code)`` mirroring :func:`async_action_dispatcher`.
    """
    # --- ZMQ RPC fast-path ----------------------------------------------
    # Merge HTTP-style query params + body dict into one kwargs map for the
    # remote handler.  FastAPI normally splits these apart; the RPC
    # dispatcher's _coerce_args matches by parameter name and rehydrates
    # pydantic models, so a simple merge is sufficient.
    rpc_args: dict = {}
    rpc_args.update(params_dict or {})
    rpc_args.update(json_dict or {})
    try:
        client = await _get_rpc_client(host, port)
        # `args=` (not `**rpc_args`) so a merged param/body key named `timeout`
        # cannot collide with call()'s own `timeout` kwarg.
        result = await client.call(
            private_action,
            timeout=min(timeout, _RPC_PROBE_TIMEOUT),
            args=rpc_args,
        )
        return result, ErrorCodes.none
    except (RPCError, asyncio.TimeoutError, zmq.ZMQError, OSError) as e:
        LOGGER.debug(
            f"RPC {server_key}/{private_action} fast-path failed "
            f"({type(e).__name__}: {e}); falling back to HTTP"
        )

    # --- HTTP fallback (legacy path) ------------------------------------
    url = f"http://{host}:{port}/{private_action}"
    success = False
    retry_count = 0

    client_timeout = aiohttp.ClientTimeout(total=timeout)
    error_code = ErrorCodes.unspecified
    response = None

    while not success and retry_count < retries:
        conn = aiohttp.TCPConnector(
            force_close=True, enable_cleanup_closed=True, limit=1000
        )
        try:
            async with aiohttp.ClientSession(
                timeout=client_timeout, connector=conn
            ) as session:
                async with session.post(
                    url,
                    params=_query_safe(params_dict),
                    json=json_dict,
                ) as resp:
                    response = await resp.json()
                    error_code = ErrorCodes.none
                    if resp.status != 200:
                        error_code = ErrorCodes.http
                        LOGGER.error(
                            f"{server_key}/{private_action} POST request returned status {resp.status}: '{response}')"
                        )
                        success = False
                    else:
                        success = True
        except Exception:
            retry_count += 1
            retry_wait = retry_count * timeout / 2
            LOGGER.warning(
                f"{server_key}/{private_action} POST request encountered an error, sleeping for {retry_wait} seconds before retrying...",
                exc_info=True,
            )
            await asyncio.sleep(retry_wait)
            response = None
        finally:
            await conn.close()
    if not success:
        LOGGER.error(
            f"{server_key}/{private_action} async_private_dispatcher could not decide response: '{response}')",
            exc_info=True,
        )
    await asyncio.sleep(0)
    return response, error_code


def _get_sync_rpc_client(host: str, port: int) -> RPCSyncClient:
    """Return (or lazily create) the cached sync RPC client for one peer.

    Args:
        host: Hostname or IP of the peer server.
        port: HTTP port; the matching RPC port is derived via
            :func:`derive_rpc_port`.

    Returns:
        The shared :class:`RPCSyncClient` for ``(host, port)``.
    """
    key = (host, port)
    client = _SYNC_RPC_CLIENTS.get(key)
    if client is None:
        client = RPCSyncClient(
            endpoint=f"tcp://{host}:{derive_rpc_port(port)}",
            default_timeout=_RPC_PROBE_TIMEOUT,
        )
        _SYNC_RPC_CLIENTS[key] = client
    return client


def close_all_sync_rpc_clients() -> None:
    """Close and discard every cached sync RPC client. Idempotent."""
    clients = list(_SYNC_RPC_CLIENTS.values())
    _SYNC_RPC_CLIENTS.clear()
    for client in clients:
        try:
            client.close()
        except Exception:
            LOGGER.exception("error closing module-cached sync RPC client")


def private_dispatcher(
    server_key: str,
    server_host: str,
    server_port: int,
    private_action: str,
    params_dict: dict = {},
    json_dict: dict = {},
    timeout: int = 180,
) -> tuple:
    """Synchronous variant of :func:`async_private_dispatcher`.

    Tries a synchronous ZMQ REQ-socket RPC call first and falls back to
    blocking :mod:`requests` HTTP if the RPC call fails.

    Args:
        server_key: Logging identifier for the destination server.
        server_host: Hostname or IP of the destination.
        server_port: HTTP port of the destination.
        private_action: Endpoint path (without leading slash).
        params_dict: Query-parameter dict.
        json_dict: JSON body dict.
        timeout: Request timeout in seconds.

    Returns:
        ``(response, error_code)``. ``response`` is the decoded JSON body
        (or ``None`` if decoding failed); ``error_code`` is an
        :class:`ErrorCodes` value.
    """
    # --- ZMQ RPC fast-path ----------------------------------------------
    rpc_args: dict = {}
    rpc_args.update(params_dict or {})
    rpc_args.update(json_dict or {})
    try:
        client = _get_sync_rpc_client(server_host, server_port)
        # `args=` (not `**rpc_args`) so a merged param/body key named `timeout`
        # cannot collide with call()'s own `timeout` kwarg.
        result = client.call(
            private_action,
            timeout=min(timeout, _RPC_PROBE_TIMEOUT),
            args=rpc_args,
        )
        return result, ErrorCodes.none
    except (RPCError, TimeoutError, zmq.ZMQError, OSError) as e:
        LOGGER.debug(
            f"RPC {server_key}/{private_action} sync fast-path failed "
            f"({type(e).__name__}: {e}); falling back to HTTP"
        )

    # --- HTTP fallback (legacy path) ------------------------------------
    url = f"http://{server_host}:{server_port}/{private_action}"

    with requests.Session() as session:
        with session.post(
            url,
            params=_query_safe(params_dict),
            json=json_dict,
            timeout=timeout,
        ) as resp:
            error_code = ErrorCodes.http
            try:
                response = resp.json()
                if resp.status_code == 200:
                    error_code = ErrorCodes.none
                else:
                    LOGGER.error(
                        f"{server_key}/{private_action} POST request returned status {resp.status_code}: '{response}')"
                    )
            except Exception:
                LOGGER.error(
                    f"{server_key}/{private_action} async_private_dispatcher could not decide response: '{resp}')",
                    exc_info=True,
                )
                response = None
            return response, error_code


async def check_endpoint(url: str) -> int:
    """Send a HEAD request to ``url`` and return its HTTP status code.

    Args:
        url: Absolute URL of the endpoint to probe.

    Returns:
        The HTTP status code returned by the server.
    """
    async with aiohttp.ClientSession() as session:
        async with session.head(url) as resp:
            return resp.status


async def endpoints_available(req_list: list) -> tuple:
    """Probe a list of endpoint URLs and report which are unreachable.

    Each URL is HEAD-requested via :func:`check_endpoint`; the HTTP status
    is classified into ``success``, ``client error``, ``server error``,
    ``no success``, ``cert failure``, ``could not connect``, or
    ``timeout``.

    Args:
        req_list: Endpoint URLs to probe.

    Returns:
        ``(all_available, unavailable)``. ``all_available`` is ``True`` when
        every URL returned a 2xx status. ``unavailable`` is a list of
        ``(url, [state])`` pairs for the URLs that failed; empty when all
        succeeded.
    """
    responses = []
    states = []
    for req in req_list:
        isavail = False
        try:
            status = await check_endpoint(req)
            cent = status // 100
            if cent == 2:
                isavail = True
                states.append("success")
            elif cent == 4:
                states.append("client error")
            elif cent == 5:
                states.append("server error")
            else:
                states.append("no success")
        except aiohttp.ClientSSLError:
            states.append("cert failure")
        except aiohttp.ClientConnectionError:
            states.append("could not connect")
        except asyncio.TimeoutError:
            states.append("timeout")
        responses.append(isavail)
    if not all(responses):
        badinds = [i for i, v in enumerate(responses) if not v]
        unavailable = [(req_list[i], [states[i]]) for i in badinds]
        LOGGER.info(
            f"Cannot dispatch actions because the following endpoints are unavailable: {unavailable}"
        )
        return False, unavailable
    else:
        return True, []
