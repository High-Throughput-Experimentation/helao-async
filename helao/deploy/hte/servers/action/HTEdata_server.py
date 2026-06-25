"""HTE data management action server.

Wraps the legacy ``HTEdata`` driver and exposes endpoints for reading and
writing platemap, screening-print, info-file, RCP and plate-XY-calibration
information for a given ``plate_id``.
"""

__all__ = ["makeApp"]


from typing import Optional
from fastapi import Body
from helao.framework.app.base_api import BaseAPI
from helao.framework.domain.run_models import Action
from helao.deploy.hte.drivers.data.HTEdata_legacy import HTEdata


def makeApp(server_key) -> BaseAPI:
    """Build the HTE data-management FastAPI app.

    Constructs a :class:`BaseAPI` instance backed by the :class:`HTEdata`
    driver and registers the plate/platemap/info/RCP/calibration endpoints
    under ``/<server_key>/...``.

    Args:
        server_key: Key identifying this server in the orchestration group
            config; used as the URL prefix and server title.

    Returns:
        The configured :class:`BaseAPI` application.
    """

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="HTE data management server",
        version=2.0,
        driver_classes=[HTEdata],
    )

    @app.post(f"/{server_key}/get_elements_plateid", tags=["action"])
    async def get_elements_plateid(
        plateid: Optional[int] = None,
    ):
        """Return the element list from the screening-print record in the plate info file."""
        active = await app.base.setup_and_contain_action()
        await active.enqueue_data_dflt(
            datadict={
                "elements": app.driver.get_elements_plateid(
                    **active.action.action_params
                )
            }
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/get_platemap_plateid", tags=["action"])
    async def get_platemap_plateid(
        plateid: Optional[int] = None,
    ):
        """Return the platemap for the requested ``plateid``."""
        active = await app.base.setup_and_contain_action()
        await active.enqueue_data_dflt(
            datadict={
                "platemap": app.driver.get_platemap_plateid(
                    **active.action.action_params
                )
            }
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/get_platexycalibration", tags=["action"])
    async def get_platexycalibration(
        plateid: Optional[int] = None,
    ):
        """Return the stored plate XY alignment matrix for ``plateid``."""
        active = await app.base.setup_and_contain_action()
        await active.enqueue_data_dflt(
            datadict={
                "platecal": app.driver.get_platexycalibration(
                    **active.action.action_params
                )
            }
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/save_platexycalibration", tags=["action"])
    async def save_platexycalibration(
        plateid: Optional[int] = None,
    ):
        """Persist the plate XY alignment matrix for ``plateid``."""
        active = await app.base.setup_and_contain_action()
        await active.enqueue_data_dflt(
            datadict={
                "platecal": app.driver.save_platexycalibration(
                    **active.action.action_params
                )
            }
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/check_plateid", tags=["action"])
    async def check_plateid(
        plateid: Optional[int] = None,
    ):
        """Check whether an info file exists for the given ``plateid``."""
        active = await app.base.setup_and_contain_action()
        await active.enqueue_data_dflt(
            datadict={
                "plateid": app.driver.check_plateid(**active.action.action_params)
            }
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/check_printrecord_plateid", tags=["action"])
    async def check_printrecord_plateid(
        plateid: Optional[int] = None,
    ):
        """Check whether a print record is present in the plate info file."""
        active = await app.base.setup_and_contain_action()
        await active.enqueue_data_dflt(
            datadict={
                "printrecord": app.driver.check_printrecord_plateid(
                    **active.action.action_params
                )
            }
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/check_annealrecord_plateid", tags=["action"])
    async def check_annealrecord_plateid(
        plateid: Optional[int] = None,
    ):
        """Check whether an anneal record is present in the plate info file."""
        active = await app.base.setup_and_contain_action()
        await active.enqueue_data_dflt(
            datadict={
                "annealrecord": app.driver.check_annealrecord_plateid(
                    **active.action.action_params
                )
            }
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/get_info_plateid", tags=["action"])
    async def get_info_plateid(
        plateid: Optional[int] = None,
    ):
        """Return the parsed info-file contents for ``plateid``."""
        active = await app.base.setup_and_contain_action()
        await active.enqueue_data_dflt(
            datadict={
                "info": app.driver.get_info_plateid(**active.action.action_params)
            }
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/get_rcp_plateid", tags=["action"])
    async def get_rcp_plateid(
        plateid: Optional[int] = None,
    ):
        """Return the RCP (recipe) record associated with ``plateid``."""
        active = await app.base.setup_and_contain_action()
        await active.enqueue_data_dflt(
            datadict={"rcp": app.driver.get_rcp_plateid(**active.action.action_params)}
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
