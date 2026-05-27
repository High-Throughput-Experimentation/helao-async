__all__ = [
    "async_action_dispatcher",
    "async_private_dispatcher",
    "private_dispatcher",
    "aclose_all_rpc_clients",
    "close_all_sync_rpc_clients",
]

import traceback
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


async def _get_rpc_client(host: str, port: int) -> RPCClient:
    """Return a cached :class:`RPCClient` for ``host:derive_rpc_port(port)``."""
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
    """Close every cached RPC client.  Idempotent."""
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
):
    """
    Asynchronously dispatches an action to the specified server and handles the response.

    Tries the ZMQ RPC fast-path first; on failure falls back to HTTP.

    .. note::

       RPC bypasses the action-queuing middleware in BaseAPI (which
       intercepts HTTP requests to ``/<server>/<action>`` and queues them
       when the endpoint is busy).  In normal HELAO operation the
       orchestrator's ``globalstatusmodel.endpoint_free()`` check prevents
       dispatching to busy endpoints, so the middleware is defense-in-depth
       that rarely fires; the RPC path relies on that orchestrator-side
       coordination rather than the per-request middleware.

    Args:
        world_config_dict (dict): A dictionary containing the configuration of the world, including server details.
        A (Action): An instance of the Action class containing details about the action to be dispatched.
        params (dict, optional): Additional parameters to be sent with the request. Defaults to an empty dictionary.

    Returns:
        tuple: A tuple containing the response from the server (or None if an error occurred) and an error code indicating the status of the request.

    Raises:
        Exception: If there is an issue with the request or response handling, an exception is caught and logged.
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
        result = await client.call(
            rpc_method,
            timeout=min(timeout, _RPC_PROBE_TIMEOUT),
            **rpc_args,
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
                    params=params,
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
):
    """
    Asynchronously dispatches a private action to a specified server.

    Tries the ZMQ RPC fast-path first; on failure (peer not listening, the
    method isn't registered, timeout, decode error) falls back to the legacy
    aiohttp HTTP path.  Callers don't need to do anything to opt in -- the
    fast path is taken whenever the peer's :class:`HelaoFastAPI` has an
    ``RPCDispatcher`` bound on ``derive_rpc_port(port)``.

    Args:
        server_key (str): The key identifying the server.
        host (str): The host address of the server.
        port (int): The port number of the server.
        private_action (str): The private action to be dispatched.
        params_dict (dict, optional): The dictionary of parameters to be sent in the request. Defaults to {}.
        json_dict (dict, optional): The dictionary of JSON data to be sent in the request. Defaults to {}.

    Returns:
        tuple: A tuple containing the response from the server and an error code.
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
        result = await client.call(
            private_action,
            timeout=min(timeout, _RPC_PROBE_TIMEOUT),
            **rpc_args,
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
                    params=params_dict,
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
    """Return a cached :class:`RPCSyncClient` for ``host:derive_rpc_port(port)``."""
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
    """Close every cached sync RPC client.  Idempotent."""
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
):
    """
    Sends a POST request to a specified server and handles the response.

    Tries the ZMQ RPC fast-path first via a synchronous ``zmq.REQ`` socket;
    on failure falls back to the legacy ``requests`` HTTP path.

    Args:
        server_key (str): Identifier for the server.
        server_host (str): Hostname or IP address of the server.
        server_port (int): Port number of the server.
        private_action (str): The action to be performed on the server.
        params_dict (dict, optional): Dictionary of URL parameters to append to the URL. Defaults to {}.
        json_dict (dict, optional): Dictionary to send in the body of the POST request as JSON. Defaults to {}.

    Returns:
        tuple: A tuple containing the response (either as a JSON object or string) and an error code.
    """
    # --- ZMQ RPC fast-path ----------------------------------------------
    rpc_args: dict = {}
    rpc_args.update(params_dict or {})
    rpc_args.update(json_dict or {})
    try:
        client = _get_sync_rpc_client(server_host, server_port)
        result = client.call(
            private_action,
            timeout=min(timeout, _RPC_PROBE_TIMEOUT),
            **rpc_args,
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
            params=params_dict,
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


async def check_endpoint(url: str):
    """
    Asynchronously checks the status of an endpoint by sending a HEAD request.

    Args:
        url (str): The URL of the endpoint to check.

    Returns:
        int: The HTTP status code of the response.
    """
    async with aiohttp.ClientSession() as session:
        async with session.head(url) as resp:
            return resp.status


async def endpoints_available(req_list: list):
    """
    Check the availability of a list of endpoints.

    This function takes a list of endpoint requests, checks their availability,
    and returns a tuple indicating whether all endpoints are available and a list
    of unavailable endpoints with their respective error states.

    Args:
        req_list (list): A list of endpoint requests to check.

    Returns:
        tuple: A tuple containing:
            - bool: True if all endpoints are available, False otherwise.
            - list: A list of tuples, each containing an unavailable endpoint request
                    and a list of error states.

    Error States:
        - 'success': The endpoint is available (HTTP status code 2xx).
        - 'client error': The endpoint returned a client error (HTTP status code 4xx).
        - 'server error': The endpoint returned a server error (HTTP status code 5xx).
        - 'no success': The endpoint returned a non-success status code.
        - 'cert failure': SSL certificate validation failed.
        - 'could not connect': Failed to connect to the endpoint.
        - 'timeout': The request to the endpoint timed out.
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
