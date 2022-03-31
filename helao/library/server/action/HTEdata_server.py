__all__ = ["makeApp"]


# data management server for HTE
from typing import Optional
from fastapi import Body
from importlib import import_module
from helaocore.server.base import makeActionServ
from helaocore.schema import Action
from helaocore.helper.config_loader import config_loader


def makeApp(confPrefix, servKey, helao_root):

    config = config_loader(confPrefix, helao_root)
    C = config["servers"]
    S = C[servKey]

    # check if 'mode' setting is present
    if not "mode" in S:
        print('"mode" not defined, switching to legacy mode.')
        S["mode"] = "legacy"

    if S["mode"] == "legacy":
        # print("Legacy data managament mode")
        from helao.library.driver.HTEdata_legacy import HTEdata
    # elif S['mode'] == "modelyst":
    #     pass
    # print("Modelyst data managament mode")
    #    from HTEdata_modelyst import HTEdata
    # else:
    #     pass
    # print("Unknown data mode")
    #    from HTEdata_dummy import HTEdata

    app = makeActionServ(
        config=config,
        server_key=servKey,
        server_title=servKey,
        description="HTE data management server",
        version=2.0,
        driver_class=HTEdata,
    )

    @app.post(f"/{servKey}/get_elements_plateid")
    async def get_elements_plateid(
        action: Optional[Action] = Body({}, embed=True),
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

    @app.post(f"/{servKey}/get_platemap_plateid")
    async def get_platemap_plateid(
        action: Optional[Action] = Body({}, embed=True),
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

    @app.post(f"/{servKey}/get_platexycalibration")
    async def get_platexycalibration(
        action: Optional[Action] = Body({}, embed=True),
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

    @app.post(f"/{servKey}/save_platexycalibration")
    async def save_platexycalibration(
        action: Optional[Action] = Body({}, embed=True),
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

    @app.post(f"/{servKey}/check_plateid")
    async def check_plateid(
        action: Optional[Action] = Body({}, embed=True),
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

    @app.post(f"/{servKey}/check_printrecord_plateid")
    async def check_printrecord_plateid(
        action: Optional[Action] = Body({}, embed=True),
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

    @app.post(f"/{servKey}/check_annealrecord_plateid")
    async def check_annealrecord_plateid(
        action: Optional[Action] = Body({}, embed=True),
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

    @app.post(f"/{servKey}/get_info_plateid")
    async def get_info_plateid(
        action: Optional[Action] = Body({}, embed=True),
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

    @app.post(f"/{servKey}/get_rcp_plateid")
    async def get_rcp_plateid(
        action: Optional[Action] = Body({}, embed=True),
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
