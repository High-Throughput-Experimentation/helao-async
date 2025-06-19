__all__ = ["makeApp"]


# data management server for HTE
from typing import Optional
from fastapi import Body
from helao.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, server_key, helao_root):

    config = config_loader(confPrefix, helao_root)
    C = config["servers"]
    S = C[server_key]

    # check if 'mode' setting is present
    if not "mode" in S:
        print('"mode" not defined, switching to legacy mode.')
        S["mode"] = "legacy"

    if S["mode"] == "legacy":
        # print("Legacy data managament mode")
        from helao.drivers.data.HTEdata_legacy import HTEdata
    # elif S['mode'] == "modelyst":
    #     pass
    # print("Modelyst data managament mode")
    #    from HTEdata_modelyst import HTEdata
    # else:
    #     pass
    # print("Unknown data mode")
    #    from HTEdata_dummy import HTEdata

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="HTE data management server",
        version=2.0,
        driver_classes=[HTEdata],
    )

    @app.post(f"/{server_key}/get_elements_plateid", tags=["action"])
    async def get_elements_plateid(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plateid: Optional[int] = None,
    ):
        """Gets the elements from the screening print in the info file"""
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
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plateid: Optional[int] = None,
    ):
        """gets platemap"""
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
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plateid: Optional[int] = None,
    ):
        """gets saved plate alignment matrix"""
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
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plateid: Optional[int] = None,
    ):
        """saves alignment matrix"""
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
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plateid: Optional[int] = None,
    ):
        """checks that the plate_id (info file) exists"""
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
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plateid: Optional[int] = None,
    ):
        """checks that a print record exist in the info file"""
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
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plateid: Optional[int] = None,
    ):
        """checks that a anneal record exist in the info file"""
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
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plateid: Optional[int] = None,
    ):
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
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plateid: Optional[int] = None,
    ):
        active = await app.base.setup_and_contain_action()
        await active.enqueue_data_dflt(
            datadict={"rcp": app.driver.get_rcp_plateid(**active.action.action_params)}
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
