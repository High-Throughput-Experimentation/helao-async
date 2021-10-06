import aiohttp


async def async_private_dispatcher(
    world_config_dict: dict,
    server: str,
    private_process: str,
    params_dict: dict,
    json_dict: dict,
):
    """Request non-blocking private process which may run concurrently.

    Returns:
        Response string from http POST request to process server
    """

    actd = world_config_dict["servers"][server]
    act_addr = actd["host"]
    act_port = actd["port"]

    url = f"http://{act_addr}:{act_port}/{private_process}"

    # print(" ... params_dict", params_dict)
    # print(" ... json_dict", json_dict)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            params=params_dict,
            # data = data_dict,
            json=json_dict,
        ) as resp:
            response = await resp.json()
            return response
