"""Power distribution unit server"""

__all__ = ["makeApp"]

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from fastapi import Body
from helao.helpers.premodels import Action
from helao.core.drivers.helao_driver import DriverResponseType
from helao.core.servers.base_api import BaseAPI
from ...drivers.io.synaccess.driver import NetbooterDriver

from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus


def makeApp(server_key):

    # current plan is 1 mfc per COM

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="PDU server",
        version=0.1,
        driver_classes=[NetbooterDriver],
    )

    @app.post(f"/{server_key}/switch_outlet", tags=["action"])
    async def switch_outlet(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        outlet_number: int = 1,
        on: bool = False,
    ):
        """Switch on/off PDU outlet by number."""
        active = await app.base.setup_and_contain_action()
        driver_resp = app.driver.switch_outlet(
            outlet_number=active.action.action_params["outlet_number"],
            on=active.action.action_params["on"],
        )
        if driver_resp.response != DriverResponseType.success:
            active.action.action_status.append(HloStatus.errored)
            active.action.error_code = ErrorCodes.cmd_error
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/switch_all", tags=["action"])
    async def switch_all(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        on: bool = False,
    ):
        """Switch on/off PDU outlet by number."""
        active = await app.base.setup_and_contain_action()
        driver_resp = app.driver.switch_all(
            on=active.action.action_params["on"],
        )
        if driver_resp.response != DriverResponseType.success:
            active.action.action_status.append(HloStatus.errored)
            active.action.error_code = ErrorCodes.cmd_error
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
