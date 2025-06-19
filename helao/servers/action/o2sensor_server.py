# shell: uvicorn motion_server:app --reload
""" Serial sensor server

"""

__all__ = ["makeApp"]

from typing import List, Union
from fastapi import Body
from helao.helpers.premodels import Action
from helao.servers.base_api import BaseAPI
from helao.core.models.sample import AssemblySample, LiquidSample, GasSample,SolidSample, NoneSample
from helao.drivers.sensor.cm0134_driver import CM0134, O2MonExec
from helao.helpers.config_loader import CONFIG


def makeApp(server_key):
    config = CONFIG

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Sensor server",
        version=0.1,
        driver_class=CM0134,
    )

    @app.post(f"/{server_key}/acquire_o2", tags=["action"])
    async def acquire_o2(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        duration: float = -1,
        acquisition_rate: float = 0.2,
        fast_samples_in: List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]] = Body([], embed=True),
    ):
        """Record O2 ppm level."""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "O2"
        executor = O2MonExec(
            active=active,
            oneoff=False,
            poll_rate=active.action.action_params["acquisition_rate"],
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/cancel_acquire_o2", tags=["action"])
    async def cancel_acquire_o2(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Stop running O2 acquisition."""
        active = await app.base.setup_and_contain_action()
        for exec_id, executor in app.base.executors.items():
            if exec_id.split()[0] == "acquire_o2":
                executor.stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
