# shell: uvicorn motion_server:app --reload
"""FastAPI action server for a Meerstetter thermoelectric cooler (TEC).

Wraps :class:`MeerstetterTEC` and the :class:`TECMonExec` / :class:`TECWaitExec`
executors to expose endpoints that record TEC telemetry, set the temperature
setpoint, enable/disable control, and wait for thermal stability.
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

from ...drivers.temperature_control.mecom_driver import (
    MeerstetterTEC,
    MeerstetterTECPoller,
    TECMonExec,
    TECWaitExec,
)


def makeApp(server_key) -> ActionHost:
    """Build the ActionHost app for the Meerstetter TEC.

    Args:
        server_key: Unique key identifying this server in the orchestration
            group.

    Returns:
        The configured ActionHost instance with TEC monitoring and control
        endpoints registered.
    """

    app = ActionHost(
        server_key=server_key,
        server_title=server_key,
        description="Sensor server",
        version=0.1,
        driver_classes=[MeerstetterTEC],
        poller_class=MeerstetterTECPoller,
    )

    @app.action()
    async def record_tec(
        ctx: ActionContext,
        duration: float = -1,
        acquisition_rate: float = 0.2,
        fast_samples_in: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
    ):
        """Stream TEC telemetry through a :class:`TECMonExec`.

        Does not change the setpoint or enable/disable the controller.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            duration: Recording duration in seconds; negative runs until
                cancelled.
            acquisition_rate: Polling period in seconds passed to the executor.
            fast_samples_in: Sample references associated with this action.

        Returns:
            The active action dictionary from ``start_executor``.
        """
        active = await ctx.begin()
        active.action.action_abbr = "TEC"
        executor = TECMonExec(
            active=active,
            oneoff=False,
            poll_rate=active.action.action_params["acquisition_rate"],
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.action()
    async def cancel_record_tec(ctx: ActionContext):
        """Stop any running ``record_tec`` executors.

        Does not change the setpoint or enable/disable the controller.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.

        Returns:
            The finished action dictionary.
        """
        active = await ctx.begin()
        for exec_id, executor in app.executors.items():
            if exec_id.split()[0] == "record_tec":
                executor.stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.action()
    async def set_temperature(
        ctx: ActionContext,
        target_temperature_degc: float = 25.0,
    ):
        """Write a new temperature setpoint to the TEC controller.

        Does not toggle the enable state.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            target_temperature_degc: Setpoint in degrees Celsius.

        Returns:
            The finished action dictionary.
        """
        active = await ctx.begin(action_abbr="setTEC")
        app.driver.set_temp(active.action.action_params["target_temperature_degc"])
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.action()
    async def enable_tec(ctx: ActionContext):
        """Enable the TEC controller output.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.

        Returns:
            The finished action dictionary.
        """
        active = await ctx.begin(action_abbr="enableTEC")
        app.driver.enable()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.action()
    async def disable_tec(ctx: ActionContext):
        """Disable the TEC controller output.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.

        Returns:
            The finished action dictionary.
        """
        active = await ctx.begin(action_abbr="disableTEC")
        app.driver.disable()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.action()
    async def wait_till_stable(
        ctx: ActionContext,
        acquisition_rate: float = 0.2,
    ):
        """Start a :class:`TECWaitExec` that returns once the TEC is stable.

        The executor polls the controller until ``temperature_is_stable``
        reports the stable state (integer ``2``).

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            acquisition_rate: Polling period in seconds passed to the executor.

        Returns:
            The active action dictionary from ``start_executor``.
        """
        active = await ctx.begin()
        active.action.action_abbr = "waitTEC"
        executor = TECWaitExec(
            active=active,
            oneoff=False,
            poll_rate=active.action.action_params["acquisition_rate"],
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.action()
    async def cancel_wait_till_stable(ctx: ActionContext):
        """Stop any running ``wait_till_stable`` executors.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.

        Returns:
            The finished action dictionary.
        """
        active = await ctx.begin()
        for exec_id, executor in app.executors.items():
            if exec_id.split()[0] == "wait_till_stable":
                executor.stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
