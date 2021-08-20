# data management server for HTE
from typing import Optional
from importlib import import_module
from fastapi import Request
from helao.core.server import makeActServ, setupAct


def makeApp(confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config
    C = config["servers"]
    S = C[servKey]

    # check if 'mode' setting is present
    if not 'mode' in S.keys():
        print('"mode" not defined, switching to legacy mode.')
        S['mode']= "legacy"


    if S['mode'] == "legacy":
        pass
        # print("Legacy data managament mode")
        from helao.library.driver.HTEdata_legacy import HTEdata
    elif S['mode'] == "modelyst":
        pass
        # print("Modelyst data managament mode")
    #    from HTEdata_modelyst import HTEdata
    else:
        pass
        # print("Unknown data mode")
    #    from HTEdata_dummy import HTEdata


    app = makeActServ(
        config, servKey, servKey, "HTE data management server", version=2.0, driver_class=HTEdata
    )

    @app.post(f"/{servKey}/get_elements_plateid")
    async def get_elements_plateid(request: Request, plateid: Optional[str]=None):
        """Gets the elements from the screening print in the info file"""
        A = await setupAct(request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data(app.driver.get_elements_plateid(**A.action_params))
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/get_platemap_plateid")
    async def get_platemap_plateid(request: Request, plateid: Optional[str]=None):
        """gets platemap"""
        A = await setupAct(request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data(app.driver.get_platemap_plateid(**A.action_params))
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/get_platexycalibration")
    async def get_platexycalibration(request: Request, plateid: Optional[str]=None):
        """gets saved plate alignment matrix"""
        A = await setupAct(request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data(app.driver.get_platexycalibration(**A.action_params))
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/save_platexycalibration")
    async def save_platexycalibration(request: Request, plateid: Optional[str]=None):
        """saves alignment matrix"""
        A = await setupAct(request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data(app.driver.save_platexycalibration(**A.action_params))
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/check_plateid")
    async def check_plateid(request: Request, plateid: Optional[str]=None):
        """checks that the plate_id (info file) exists"""
        A = await setupAct(request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data(app.driver.check_plateid(**A.action_params))
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/check_printrecord_plateid")
    async def check_printrecord_plateid(request: Request, plateid: Optional[str]=None):
        """checks that a print record exist in the info file"""
        A = await setupAct(request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data(app.driver.check_printrecord_plateid(**A.action_params))
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/check_annealrecord_plateid")
    async def check_annealrecord_plateid(request: Request, plateid: Optional[str]=None):
        """checks that a anneal record exist in the info file"""
        A = await setupAct(request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data(app.driver.check_annealrecord_plateid(**A.action_params))
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/get_info_plateid")
    async def get_info_plateid(request: Request, plateid: Optional[str]=None):
        A = await setupAct(request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data(app.driver.get_info_plateid(**A.action_params))
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/get_rcp_plateid")
    async def get_rcp_plateid(request: Request, plateid: Optional[str]=None):
        A = await setupAct(request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data(app.driver.get_rcp_plateid(**A.action_params))
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post("/shutdown")
    def post_shutdown():
        shutdown_event()


    @app.on_event("shutdown")
    def shutdown_event():
        return ""

    return app

        