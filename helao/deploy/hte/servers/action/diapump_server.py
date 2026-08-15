# shell: uvicorn motion_server:app --reload
"""Diaphragm pump (SIMDOS) action server.

Wraps the :class:`SIMDOS` driver and exposes endpoints for continuous-rate
pumping via the :class:`RunExec` executor, plus private endpoints to control
the driver's polling loop and direct pump start/stop.
"""

__all__ = ["makeApp"]


from typing import Optional

from helao.hexagon.app.action_context import ActionContext
from helao.hexagon.app.action_host import ActionHost

from ...drivers.pump.simdos_driver import SIMDOS, RunExec, SIMDOSPoller


def makeApp(server_key) -> ActionHost:
    """Build the diaphragm-pump FastAPI app.

    Constructs a :class:`ActionHost` backed by :class:`SIMDOS` and registers the
    ``run_continuous`` / ``cancel_run_continuous`` action endpoints plus the
    private polling and pump on/off endpoints.

    Args:
        server_key: Key identifying this server in the orchestration group.

    Returns:
        The configured :class:`ActionHost` application.
    """

    app = ActionHost(
        server_key=server_key,
        server_title=server_key,
        description="Diaphragm pump server",
        version=1.0,
        driver_classes=[SIMDOS],
        poller_class=SIMDOSPoller,
    )

    @app.post("/start_polling", tags=["private"])
    async def start_polling():
        """Start the SIMDOS driver's internal status polling loop."""
        await app.driver.start_polling()

    @app.post("/stop_polling", tags=["private"])
    async def stop_polling():
        """Stop the SIMDOS driver's internal status polling loop."""
        await app.driver.stop_polling()

    @app.post("/start_pump", tags=["private"])
    async def start_pump():
        """Start the pump directly via the driver (no action record)."""
        await app.driver.start_pump()

    @app.post("/stop_pump", tags=["private"])
    async def stop_pump():
        """Stop the pump directly via the driver (no action record)."""
        await app.driver.stop_pump()

    @app.action()
    async def run_continuous(
        ctx: ActionContext,
        rate_uL_min: int = 0,
        duration_sec: float = -1,
    ):
        """Pump continuously at ``rate_uL_min`` via a :class:`RunExec` executor.

        ``duration_sec`` of ``-1`` runs until ``cancel_run_continuous``.
        """
        active = await ctx.begin()
        executor = RunExec(active=active, oneoff=False, poll_rate=0.2)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.action()
    async def cancel_run_continuous(
        ctx: ActionContext,
        exec_id: Optional[str] = None,
    ):
        """Stop the targeted ``run_continuous`` executor, or all of them.

        If ``exec_id`` is provided only that executor is stopped; otherwise all
        executors whose id begins with ``run_continuous`` are stopped.
        """
        active = await ctx.begin()
        if active.action.action_params["exec_id"] is not None:
            app.stop_executor(active.action.action_params["exec_id"])
        else:
            app.stop_all_executor_prefix("run_continuous", {})
        finished_action = await active.finish()
        return finished_action.as_dict()

    # @app.post(f"/{server_key}/dispense_byvolume", tags=["action"])
    # async def dispense_byvolume(
    #     action: Action = Body({}, embed=True),
    #     action_version: int = 1,
    #     volume_uL: int = 0,
    #     dispense_duration_sec: int = 0,
    # ):
    # #     active = await ctx.begin()
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
    # #     active = await ctx.begin()
    # #     executor = RateExec(active=active, oneoff=False, poll_rate=0.2)
    # #     active_action_dict = active.start_executor(executor)
    # #     return active_action_dict
    #     pass

    return app
