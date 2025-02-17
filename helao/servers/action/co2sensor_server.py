# shell: uvicorn motion_server:app --reload
""" Serial sensor server

"""

__all__ = ["makeApp"]

from typing import Optional, List
from fastapi import Body
from helao.helpers.premodels import Action
from helao.servers.base_api import BaseAPI
from helao.core.models.sample import SampleUnion
from helao.drivers.sensor.sprintir_driver import SprintIR, CO2MonExec
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, server_key, helao_root):
    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Sensor server",
        version=0.1,
        driver_class=SprintIR,
    )

    @app.post(f"/{server_key}/acquire_co2", tags=["action"])
    async def acquire_co2(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        duration: float = -1,
        acquisition_rate: float = 0.2,
        fast_samples_in: List[SampleUnion] = Body([], embed=True),
    ):
        """Record CO2 ppm level."""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "CO2"
        executor = CO2MonExec(
            active=active,
            oneoff=False,
            poll_rate=active.action.action_params["acquisition_rate"],
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/cancel_acquire_co2", tags=["action"])
    async def cancel_acquire_co2(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Stop running CO2 acquisition."""
        active = await app.base.setup_and_contain_action()
        for exec_id, executor in app.base.executors.items():
            if exec_id.split()[0] == "acquire_co2":
                executor.stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
