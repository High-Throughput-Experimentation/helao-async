# shell: uvicorn motion_server:app --reload
"""FastAPI action server for the CM-0134 dissolved-oxygen sensor.

Exposes endpoints to start and stop continuous O2 ppm acquisition backed by
the :class:`CM0134` driver and :class:`O2MonExec` executor.
"""

__all__ = ["makeApp"]

from typing import List, Union
from fastapi import Body
from helao.helpers.premodels import Action
from helao.core.servers.base_api import BaseAPI
from helao.core.models.sample import (
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
)
from ...drivers.sensor.cm0134_driver import CM0134, O2MonExec


def makeApp(server_key) -> BaseAPI:
    """Build the BaseAPI app for the CM-0134 O2 sensor.

    Constructs a FastAPI app bound to the CM0134 driver and registers
    endpoints to acquire and cancel O2 ppm measurements.

    Args:
        server_key: Unique key identifying this server in the orchestration
            group; used as the URL prefix and configuration lookup key.

    Returns:
        The configured BaseAPI instance ready for the launcher.
    """

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Sensor server",
        version=0.1,
        driver_classes=[CM0134],
    )

    @app.post(f"/{server_key}/acquire_o2", tags=["action"])
    async def acquire_o2(
        duration: float = -1,
        acquisition_rate: float = 0.2,
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
    ):
        """Start an O2MonExec to poll the O2 sensor at acquisition_rate.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            duration: Total acquisition duration in seconds; negative value
                runs until cancelled.
            acquisition_rate: Polling period in seconds passed to the executor.
            fast_samples_in: Sample references associated with this action.

        Returns:
            The active action dictionary returned by ``start_executor``.
        """
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
    ):
        """Stop any running ``acquire_o2`` executor.

        Iterates the server's executor registry and calls
        ``stop_action_task`` on each ``acquire_o2`` instance.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action()
        for exec_id, executor in app.base.executors.items():
            if exec_id.split()[0] == "acquire_o2":
                executor.stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
