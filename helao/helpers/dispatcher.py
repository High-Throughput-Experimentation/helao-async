__all__ = ["async_action_dispatcher", "async_private_dispatcher", "private_dispatcher"]

import traceback
import aiohttp
import requests

from helao.helpers.premodels import Action
from helaocore.error import ErrorCodes

from helao.helpers.print_message import print_message


async def async_action_dispatcher(world_config_dict: dict, A: Action, params={}):
    """Request non-blocking action_dq which may run concurrently.

    Send action object to action server for experimenting.

    Args:
        A: an action type object contain action server name,
           endpoint, parameters

    Returns:
        Response string from http POST request to action server
    """
    actd = world_config_dict["servers"][A.action_server.server_name]
    act_addr = actd["host"]
    act_port = actd["port"]
    url = f"http://{act_addr}:{act_port}/{A.action_server.server_name}/{A.action_name}"
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            params=params,
            json={"action": A.as_dict()},
        ) as resp:
            error_code = ErrorCodes.none
            try:
                response = await resp.json()
                if resp.status != 200:
                    error_code = ErrorCodes.http
                    print_message(
                        actd,
                        "orchestrator",
                        f"{A.action_server.server_name}/{A.action_name} POST request returned status {resp.status}: '{response}', error={error_code}",
                        error=True,
                    )
            except Exception as e:
                tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                print_message(
                    actd,
                    "orchestrator",
                    f"{A.action_server.server_name}/{A.action_name} async_action_dispatcher could not decide response: '{resp}', error={repr(e), tb,}",
                    error=True,
                )
                response = None
            return response, error_code


async def async_private_dispatcher(
    world_config_dict: dict,
    server: str,
    private_action: str,
    params_dict: dict = {},
    json_dict: dict = {},
):
    """Request non-blocking private action which may run concurrently.

    Returns:
        Response string from http POST request to action server
    """

    actd = world_config_dict["servers"][server]
    act_addr = actd["host"]
    act_port = actd["port"]

    url = f"http://{act_addr}:{act_port}/{private_action}"

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            params=params_dict,
            json=json_dict,
        ) as resp:
            error_code = ErrorCodes.none
            try:
                response = await resp.json()
                if resp.status != 200:
                    error_code = ErrorCodes.http
                    print_message(
                        actd,
                        "orchestrator",
                        f"{server}/{private_action} POST request returned status {resp.status}: '{response}', error={repr(error_code)}",
                        error=True,
                    )
            except Exception as e:
                tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                print_message(
                    actd,
                    "orchestrator",
                    f"{server}/{private_action} async_private_dispatcher could not decide response: '{resp}', error={repr(e), tb}",
                    error=True,
                )
                response = None
            return response, error_code

def private_dispatcher(
    world_config_dict: dict,
    server: str,
    private_action: str,
    params_dict: dict,
    json_dict: dict,
):
    actd = world_config_dict["servers"][server]
    act_addr = actd["host"]
    act_port = actd["port"]

    url = f"http://{act_addr}:{act_port}/{private_action}"

    with requests.Session() as session:
        with session.post(
            url,
            params=params_dict,
            json=json_dict,
        ) as resp:
            error_code = ErrorCodes.none
            try:
                response = resp.json()
                if resp.status_code != 200:
                    error_code = ErrorCodes.http
                    print_message(
                        actd,
                        "orchestrator",
                        f"{server}/{private_action} POST request returned status {resp.status_code}: '{response}', error={repr(error_code)}",
                        error=True,
                    )
            except Exception as e:
                tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                print_message(
                    actd,
                    "orchestrator",
                    f"{server}/{private_action} async_private_dispatcher could not decide response: '{resp}', error={repr(e), tb}",
                    error=True,
                )
                response = None
            return response, error_code