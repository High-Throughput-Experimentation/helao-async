"""FastAPI action server for a Synaccess Netbooter PDU.

Wraps :class:`NetbooterDriver` and exposes endpoints to switch individual
outlets or all outlets on/off.
"""

__all__ = ["makeApp"]

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.core.drivers.helao_driver import DriverResponseType
from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.hexagon.app.action_context import ActionContext
from helao.hexagon.app.action_host import ActionHost

from ...drivers.io.synaccess.driver import NetbooterDriver


def makeApp(server_key) -> ActionHost:
    """Build the ActionHost app for the Synaccess Netbooter PDU.

    Args:
        server_key: Unique key identifying this server in the orchestration
            group.

    Returns:
        The configured ActionHost instance with PDU outlet endpoints
        registered.
    """

    # current plan is 1 mfc per COM

    app = ActionHost(
        server_key=server_key,
        server_title=server_key,
        description="PDU server",
        version=0.1,
        driver_classes=[NetbooterDriver],
    )

    @app.action()
    async def switch_outlet(
        ctx: ActionContext,
        outlet_number: int = 1,
        on: bool = False,
    ):
        """Toggle a single PDU outlet on or off.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            outlet_number: One-based index of the outlet to switch.
            on: ``True`` to energize the outlet, ``False`` to de-energize.

        Returns:
            The finished action dictionary, marked errored if the driver
            response is not ``DriverResponseType.success``.
        """
        active = await ctx.begin()
        driver_resp = app.driver.switch_outlet(
            outlet_number=active.action.action_params["outlet_number"],
            on=active.action.action_params["on"],
        )
        if driver_resp.response != DriverResponseType.success:
            active.action.append_action_status(HloStatus.errored)
            active.action.error_code = ErrorCodes.cmd_error
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.action()
    async def switch_all(
        ctx: ActionContext,
        on: bool = False,
    ):
        """Toggle every PDU outlet on or off.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            on: ``True`` to energize all outlets, ``False`` to de-energize.

        Returns:
            The finished action dictionary, marked errored if the driver
            response is not ``DriverResponseType.success``.
        """
        active = await ctx.begin()
        driver_resp = app.driver.switch_all(
            on=active.action.action_params["on"],
        )
        if driver_resp.response != DriverResponseType.success:
            active.action.append_action_status(HloStatus.errored)
            active.action.error_code = ErrorCodes.cmd_error
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
