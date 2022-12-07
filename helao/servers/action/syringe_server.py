# shell: uvicorn motion_server:app --reload
""" A FastAPI service definition for a syringe pump server.

"""

__all__ = ["makeApp"]


from typing import Optional
from fastapi import Body

from helao.drivers.pump.legato_driver import KDS100, PumpExec
from helao.servers.base import makeActionServ
from helao.helpers.premodels import Action
from helaocore.error import ErrorCodes
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, servKey, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = makeActionServ(
        config=config,
        server_key=servKey,
        server_title=servKey,
        description="Syringe pump server",
        version=2.0,
        driver_class=KDS100,
    )

    @app.post("/start_polling")
    async def start_polling():
        await app.driver.start_polling()

    @app.post("/stop_polling")
    async def stop_polling():
        await app.driver.stop_polling()

    @app.post(f"/{servKey}/infuse")
    async def infuse(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        rate_uL_sec: int = 0,
        volume_uL: int = 0,
    ):
        active = await app.base.setup_and_contain_action()
        executor = PumpExec(direction=1, active=active, oneoff=False, poll_rate=0.02)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{servKey}/withdraw")
    async def withdraw(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        rate_uL_sec: int = 0,
        volume_uL: int = 0,
    ):
        active = await app.base.setup_and_contain_action()
        executor = PumpExec(direction=-1, active=active, oneoff=False, poll_rate=0.2)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post("/set_rate")
    def set_rate(pump_name: str, rate_uL_sec: int, direction: int):
        return app.driver.set_rate(pump_name, rate_uL_sec, direction)

    @app.post("/set_volume")
    def set_volume(pump_name: str, volume_uL: int):
        return app.driver.set_volume(pump_name, volume_uL)

    @app.post("/start_pump")
    def start_pump(pump_name: str, direction: int):
        return app.driver.start_pump(pump_name, direction)

    @app.post("/stop_pump")
    def stop_pump(pump_name: str):
        return app.driver.stop_pump(pump_name)

    @app.post("/clear_volume")
    def clear_volume(pump_name: str):
        return app.driver.clear_volume(pump_name)

    @app.post("/get_lbuf")
    def get_lbuf():
        return app.base.live_buffer
    return app
