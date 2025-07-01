# shell: uvicorn motion_server:app --reload
""" A FastAPI service definition for a syringe pump server.

"""

__all__ = ["makeApp"]


from fastapi import Body

from helao.drivers.pump.legato_driver import KDS100, PumpExec
from helao.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from helao.core.models.data import DataModel
from helao.core.error import ErrorCodes


def makeApp(server_key):

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Syringe pump server",
        version=2.0,
        driver_classes=[KDS100],
    )

    @app.post("/start_polling", tags=["private"])
    async def start_polling():
        await app.driver.start_polling()

    @app.post("/stop_polling", tags=["private"])
    async def stop_polling():
        await app.driver.stop_polling()

    @app.post(f"/{server_key}/infuse", tags=["action"])
    async def infuse(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        rate_uL_sec: int = 0,
        volume_uL: int = 0,
    ):
        active = await app.base.setup_and_contain_action()
        executor = PumpExec(direction=1, active=active, oneoff=False, poll_rate=0.2)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/withdraw", tags=["action"])
    async def withdraw(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        rate_uL_sec: int = 0,
        volume_uL: int = 0,
    ):
        active = await app.base.setup_and_contain_action()
        executor = PumpExec(direction=-1, active=active, oneoff=False, poll_rate=0.2)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/get_present_volume", tags=["action"])
    async def get_present_volume(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        active = await app.base.setup_and_contain_action()
        present_volume = app.driver.present_volume_ul
        datadict = {"present_volume_ul": present_volume, "error_code": ErrorCodes.none}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.action.action_params.update({"_present_volume_ul": present_volume})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/set_present_volume", tags=["private"])
    async def set_present_volume(volume_uL: float = 0):
        app.driver.present_volume_ul = volume_uL
        return {"present_volume_ul": volume_uL}

    @app.post(f"/get_present_volume", tags=["private"])
    async def get_present_volume_priv():
        return {"present_volume_ul": app.driver.present_volume_ul}

    @app.post("/set_rate", tags=["private"])
    async def set_rate(pump_name: str, rate_uL_sec: int, direction: int):
        return await app.driver.set_rate(pump_name, rate_uL_sec, direction)

    @app.post("/set_target_volume", tags=["private"])
    async def set_target_volume(pump_name: str, volume_uL: int):
        return await app.driver.set_target_volume(pump_name, volume_uL)

    @app.post("/start_pump", tags=["private"])
    async def start_pump(pump_name: str, direction: int):
        return await app.driver.start_pump(pump_name, direction)

    @app.post("/stop_pump", tags=["private"])
    async def stop_pump(pump_name: str):
        return await app.driver.stop_pump(pump_name)

    @app.post("/clear_volume", tags=["private"])
    async def clear_volume(pump_name: str):
        return await app.driver.clear_volume(pump_name)

    @app.post("/clear_target_volume", tags=["private"])
    async def clear_target_volume(pump_name: str):
        return await app.driver.clear_target_volume(pump_name)

    return app
