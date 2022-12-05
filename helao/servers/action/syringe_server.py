# shell: uvicorn motion_server:app --reload
""" A FastAPI service definition for a syringe pump server.

"""

__all__ = ["makeApp"]


from typing import Optional, List, Union
from fastapi import Body
import numpy as np
import asyncio


from helao.drivers.pump.legato_driver import KDS100, PumpExec
from helao.servers.base import makeActionServ
from helao.helpers.make_str_enum import make_str_enum
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

    @app.post(f"/{servKey}/stop")
    async def stop(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
    ):
        active = await app.base.setup_and_contain_action(action_abbr="stop")

        datadict = await app.driver.stop()

        active.action.error_code = app.base.get_main_error(
            datadict.get("err_code", ErrorCodes.unspecified)
        )
        await active.enqueue_data_dflt(datadict=datadict)
        finished_action = await active.finish()
        return finished_action.as_dict()

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
        active.executor = PumpExec(1, active)
        active_action_dict = active.start_executor()
        return active_action_dict

    @app.post(f"/{servKey}/withdraw")
    async def withdraw(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        rate_uL_sec: int = 0,
        volume_uL: int = 0,
    ):
        active = await app.base.setup_and_contain_action()
        active.executor = PumpExec(0, active)
        active_action_dict = active.start_executor()
        return active_action_dict

    return app
