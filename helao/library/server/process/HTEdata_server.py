
__all__ = ["makeApp"]


# data management server for HTE
from typing import Optional
from importlib import import_module
from fastapi import Request
from helaocore.server import make_process_serv, setup_process


def makeApp(confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config
    C = config["servers"]
    S = C[servKey]

    # check if 'mode' setting is present
    if not 'mode' in S:
        print('"mode" not defined, switching to legacy mode.')
        S['mode']= "legacy"


    if S['mode'] == "legacy":
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


    app = make_process_serv(
        config, servKey, servKey, "HTE data management server", version=2.0, driver_class=HTEdata
    )

    @app.post(f"/{servKey}/get_elements_plateid")
    async def get_elements_plateid(request: Request, plateid: Optional[int]=None):
        """Gets the elements from the screening print in the info file"""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(app.driver.get_elements_plateid(**A.process_params))
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/get_platemap_plateid")
    async def get_platemap_plateid(request: Request, plateid: Optional[int]=None):
        """gets platemap"""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(app.driver.get_platemap_plateid(**A.process_params))
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/get_platexycalibration") 
    async def get_platexycalibration(request: Request, plateid: Optional[int]=None):
        """gets saved plate alignment matrix"""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(app.driver.get_platexycalibration(**A.process_params))
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/save_platexycalibration")
    async def save_platexycalibration(request: Request, plateid: Optional[int]=None):
        """saves alignment matrix"""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(app.driver.save_platexycalibration(**A.process_params))
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/check_plateid")
    async def check_plateid(request: Request, plateid: Optional[int]=None):
        """checks that the plate_id (info file) exists"""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(app.driver.check_plateid(**A.process_params))
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/check_printrecord_plateid")
    async def check_printrecord_plateid(request: Request, plateid: Optional[int]=None):
        """checks that a print record exist in the info file"""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(app.driver.check_printrecord_plateid(**A.process_params))
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/check_annealrecord_plateid")
    async def check_annealrecord_plateid(request: Request, plateid: Optional[int]=None):
        """checks that a anneal record exist in the info file"""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(app.driver.check_annealrecord_plateid(**A.process_params))
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/get_info_plateid")
    async def get_info_plateid(request: Request, plateid: Optional[int]=None):
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(app.driver.get_info_plateid(**A.process_params))
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/get_rcp_plateid")
    async def get_rcp_plateid(request: Request, plateid: Optional[int]=None):
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(app.driver.get_rcp_plateid(**A.process_params))
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post("/shutdown")
    def post_shutdown():
        shutdown_event()


    @app.on_event("shutdown")
    def shutdown_event():
        return ""

    return app

        