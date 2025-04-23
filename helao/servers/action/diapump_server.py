# shell: uvicorn motion_server:app --reload
""" A FastAPI service definition for a diaphragm pump server.

"""

__all__ = ["makeApp"]


from typing import Optional
from fastapi import Body

from helao.drivers.pump.simdos_driver import SIMDOS, RunExec
from helao.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, server_key, helao_root):
    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Diaphragm pump server",
        version=1.0,
        driver_class=SIMDOS,
    )

    @app.post("/start_polling", tags=["private"])
    async def start_polling():
        await app.driver.start_polling()

    @app.post("/stop_polling", tags=["private"])
    async def stop_polling():
        await app.driver.stop_polling()

    @app.post("/start_pump", tags=["private"])
    async def start_pump():
        await app.driver.start()

    @app.post("/stop_pump", tags=["private"])
    async def stop_pump():
        await app.driver.stop()
    
    @app.post(f"/{server_key}/run_continuous", tags=["action"])
    async def run_continuous(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        rate_uL_min: int = 0,
        duration_sec: float = -1,
    ):
        active = await app.base.setup_and_contain_action()
        executor = RunExec(active=active, oneoff=False, poll_rate=0.2)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/cancel_run_continuous", tags=["action"])
    async def cancel_run_continuous(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            exec_id: Optional[str] = None,
        ):
            """Stop flowrate & acquisition for given device_name."""
            active = await app.base.setup_and_contain_action()
            if active.action.action_params["exec_id"] is not None:
                app.base.stop_executor(active.action.action_params["exec_id"])
            else:
                app.base.stop_all_executor_prefix("run_continuous", {})
            finished_action = await active.finish()
            return finished_action.as_dict()

    # @app.post(f"/{server_key}/dispense_byvolume", tags=["action"])
    # async def dispense_byvolume(
    #     action: Action = Body({}, embed=True),
    #     action_version: int = 1,
    #     volume_uL: int = 0,
    #     dispense_duration_sec: int = 0,
    # ):
    # #     active = await app.base.setup_and_contain_action()
    # #     executor = VolExec(active=active, oneoff=False, poll_rate=0.2)
    # #     active_action_dict = active.start_executor(executor)
    # #     return active_action_dict
    #     pass

    # @app.post(f"/{server_key}/dispense_byrate", tags=["action"])
    # async def dispense_byrate(
    #     action: Action = Body({}, embed=True),
    #     action_version: int = 1,
    #     rate_uL_min: int = 0,
    #     dispense_duration_sec: int = 0,
    # ):
    # #     active = await app.base.setup_and_contain_action()
    # #     executor = RateExec(active=active, oneoff=False, poll_rate=0.2)
    # #     active_action_dict = active.start_executor(executor)
    # #     return active_action_dict
    #     pass

    return app
