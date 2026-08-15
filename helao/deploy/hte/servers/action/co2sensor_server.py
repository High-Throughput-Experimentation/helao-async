# shell: uvicorn motion_server:app --reload
"""SprintIR CO2 sensor action server.

Wraps the serial-connected :class:`SprintIR` driver and exposes endpoints to
start and cancel CO2 ppm acquisition via the :class:`CO2MonExec` executor.
"""

__all__ = ["makeApp"]

from typing import Union

from fastapi import Body

from helao.core.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    SolidSample,
)
from helao.hexagon.app.action_context import ActionContext
from helao.hexagon.app.action_host import ActionHost

from ...drivers.sensor.sprintir_driver import CO2MonExec, SprintIR, SprintIRPoller


def makeApp(server_key) -> ActionHost:
    """Build the CO2 sensor action server.

    Constructs an :class:`ActionHost` backed by :class:`SprintIR` and registers
    the ``acquire_co2`` and ``cancel_acquire_co2`` endpoints.

    Args:
        server_key: Key identifying this server in the orchestration group.

    Returns:
        The configured :class:`ActionHost` application.
    """

    app = ActionHost(
        server_key=server_key,
        server_title=server_key,
        description="Sensor server",
        version=0.1,
        driver_classes=[SprintIR],
        poller_class=SprintIRPoller,
    )

    @app.action()
    async def acquire_co2(
        ctx: ActionContext,
        duration: float = -1,
        acquisition_rate: float = 0.2,
        fast_samples_in: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
    ):
        """Start CO2 ppm acquisition from the SprintIR sensor.

        Starts a :class:`CO2MonExec` polling at ``acquisition_rate`` Hz for up
        to ``duration`` seconds (``-1`` runs until cancelled).
        """
        active = await ctx.begin(action_abbr="CO2")
        executor = CO2MonExec(
            active=active,
            oneoff=False,
            poll_rate=active.action.action_params["acquisition_rate"],
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.action()
    async def cancel_acquire_co2(ctx: ActionContext):
        """Stop any active ``acquire_co2`` executors on this server."""
        active = await ctx.begin()
        for exec_id, executor in app.executors.items():
            if exec_id.split()[0] == "acquire_co2":
                executor.stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
