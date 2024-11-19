__all__ = ["async_action_dispatcher", "async_private_dispatcher", "private_dispatcher"]

import traceback
import asyncio
import aiohttp
import requests

from helao.helpers.premodels import Action
from helao.core.error import ErrorCodes

from helao.helpers.print_message import print_message

from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER


async def async_action_dispatcher(world_config_dict: dict, A: Action, params={}, timeout=60):
    """
    Asynchronously dispatches an action to the specified server and handles the response.

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
    url = f"http://{act_addr}:{act_port}/{A.action_server.server_name}/{A.action_name}"
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    conn = aiohttp.TCPConnector(keepalive_timeout=0, enable_cleanup_closed=True, limit=1000)
    error_code = ErrorCodes.unspecified
    response = None
    async with aiohttp.ClientSession(timeout=client_timeout, connector=conn) as session:
        async with session.post(
            url,
            params=params,
            json={"action": A.as_dict()},
        ) as resp:
            try:
                response = await resp.json()
                error_code = ErrorCodes.none
                if resp.status != 200:
                    error_code = ErrorCodes.http
                    LOGGER.error(f"{A.action_server.server_name}/{A.action_name} POST request returned status {resp.status}: '{response}', error={error_code}")
            except Exception as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                LOGGER.error(f"{A.action_server.server_name}/{A.action_name} async_action_dispatcher could not decide response: '{resp}'), {tb}",)
            resp.close()
        await session.close()
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
):
    """
    Asynchronously dispatches a private action to a specified server.

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
    url = f"http://{host}:{port}/{private_action}"

    client_timeout = aiohttp.ClientTimeout(total=timeout)
    conn = aiohttp.TCPConnector(keepalive_timeout=0, enable_cleanup_closed=True, limit=1000)
    error_code = ErrorCodes.unspecified
    response = None
    async with aiohttp.ClientSession(timeout=client_timeout, connector=conn) as session:
        async with session.post(
            url,
            params=params_dict,
            json=json_dict,
        ) as resp:
            try:
                response = await resp.json()
                error_code = ErrorCodes.none
                if resp.status != 200:
                    error_code = ErrorCodes.http
                    LOGGER.error(f"{server_key}/{private_action} POST request returned status {resp.status}: '{response}')")
            except Exception as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                LOGGER.error(f"{server_key}/{private_action} async_private_dispatcher could not decide response: '{resp}'), {tb}")
            resp.close()
        await session.close()
    await asyncio.sleep(0)
    return response, error_code


def private_dispatcher(
    server_key: str,
    server_host: str,
    server_port: int,
    private_action: str,
    params_dict: dict = {},
    json_dict: dict = {},
):
    """
    Sends a POST request to a specified server and handles the response.

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
    url = f"http://{server_host}:{server_port}/{private_action}"

    with requests.Session() as session:
        with session.post(
            url,
            params=params_dict,
            json=json_dict,
        ) as resp:
            error_code = ErrorCodes.none
            try:
                try:
                    response = resp.json()
                except:
                    response = str(resp)
                if resp.status_code != 200:
                    error_code = ErrorCodes.http
                    LOGGER.error(f"{server_key}/{private_action} POST request returned status {resp.status_code}: '{response}')")
            except Exception as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                LOGGER.error(f"{server_key}/{private_action} async_private_dispatcher could not decide response: '{resp}'), {tb}")
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
                states.append('success')
            elif cent == 4:
                states.append('client error')
            elif cent == 5:
                states.append('server error')
            else:
                states.append('no success')
        except aiohttp.ClientSSLError:
            states.append('cert failure')
        except aiohttp.ClientConnectionError:
            states.append('could not connect')
        except asyncio.TimeoutError:
            states.append('timeout')
        responses.append(isavail)
    if not all(responses):
        badinds = [i for i,v in enumerate(responses) if not v]
        unavailable = [(req_list[i], [states[i]]) for i in badinds]
        LOGGER.info(f"Cannot dispatch actions because the following endpoints are unavailable: {unavailable}")
        return False, unavailable
    else:
        return True, []
