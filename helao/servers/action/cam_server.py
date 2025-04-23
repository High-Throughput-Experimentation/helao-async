# shell: uvicorn motion_server:app --reload
""" Webcam server

"""

__all__ = ["makeApp"]

from typing import List, Union
from fastapi import Body
from helao.core.models.sample import AssemblySample, LiquidSample, GasSample,SolidSample, NoneSample
from helao.helpers.premodels import Action
from helao.servers.base_api import BaseAPI
from helao.drivers.sensor.axiscam_driver import AxisCam, AxisCamExec
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, server_key, helao_root):
    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Webcam server",
        version=0.1,
        driver_class=AxisCam,
    )

    @app.post(f"/{server_key}/acquire_image", tags=["action"])
    async def acquire_image(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        duration: float = -1,
        acquisition_rate: float = 1,
        fast_samples_in: List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]] = Body([], embed=True),
    ):
        """Record image stream from webcam."""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "acq_webcam"
        executor = AxisCamExec(
            active=active,
            oneoff=False,
            poll_rate=active.action.action_params["acquisition_rate"],
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/cancel_acquire_image", tags=["action"])
    async def cancel_acquire_image(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Stop image aqcuisition."""
        active = await app.base.setup_and_contain_action()
        app.base.executors["axis"].stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
