# shell: uvicorn motion_server:app --reload
"""Webcam (Axis IP camera) action server.

Wraps :class:`AxisCam` and exposes endpoints to start and cancel image-stream
acquisition via the :class:`AxisCamExec` executor.
"""

__all__ = ["makeApp"]

from typing import Union
from fastapi import Body
from helao.core.models.sample import (
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
)
from helao.core.servers.base_api import BaseAPI
from ...drivers.sensor.axiscam_driver import AxisCam, AxisCamExec


def makeApp(server_key) -> BaseAPI:
    """Build the webcam FastAPI app.

    Constructs a :class:`BaseAPI` backed by :class:`AxisCam` and registers the
    ``acquire_image`` and ``cancel_acquire_image`` endpoints.

    Args:
        server_key: Key identifying this server in the orchestration group.

    Returns:
        The configured :class:`BaseAPI` application.
    """

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Webcam server",
        version=0.1,
        driver_classes=[AxisCam],
    )

    @app.post(f"/{server_key}/acquire_image", tags=["action"])
    async def acquire_image(
        duration: float = -1,
        acquisition_rate: float = 1,
        fast_samples_in: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
    ):
        """Start an image-stream acquisition from the Axis webcam.

        Starts an :class:`AxisCamExec` (one-shot if ``duration == 0``,
        otherwise continuous at ``acquisition_rate`` polls/sec).
        """
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "acq_webcam"
        executor = AxisCamExec(
            active=active,
            oneoff=False if active.action.action_params["duration"] != 0 else True,
            poll_rate=active.action.action_params["acquisition_rate"],
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/cancel_acquire_image", tags=["action"])
    async def cancel_acquire_image():
        """Stop the running Axis webcam executor (registered as ``axis``)."""
        active = await app.base.setup_and_contain_action()
        app.base.executors["axis"].stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
