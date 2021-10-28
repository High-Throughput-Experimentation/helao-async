# shell: uvicorn motion_server:app --reload
""" A FastAPI service definition for a motion/IO server, e.g. Galil.

The motion/IO service defines RESTful methods for sending commmands and retrieving data
from a motion controller driver class such as 'galil_driver' or 'galil_simulate' using
FastAPI. The methods provided by this service are not device-specific. Appropriate code
must be written in the driver class to ensure that the service methods are generic, i.e.
calls to 'motion.*' are not device-specific. Currently inherits configuration from
driver code, and hard-coded to use 'galil' class (see "__main__").
"""

__all__ = ["makeApp"]

from typing import Optional, Union, List
from importlib import import_module
from fastapi import Request
from helaocore.server import make_process_serv, setup_process
from helao.library.driver.galil_driver import galil


def makeApp(confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config

    app = make_process_serv(
        config, 
        servKey, 
        servKey, 
        "Galil IO server", 
        version=2.0, 
        driver_class=galil
    )


    @app.post(f"/{servKey}/get_analog_in")
    async def get_analog_in(
                            request: Request,
                            port:Optional[int] = None
                           ):
        A = await setup_process(request)
        active = await app.base.contain_process(A,
                file_data_keys=["error_code", "port", "name", "type", "value"])
        await active.enqueue_data(app.driver.get_analog_in(**A.process_params))
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/set_analog_out")
    async def set_analog_out(
                             request: Request,
                             port:Optional[int] = None,
                             value:Optional[float] = None
                            ):
        A = await setup_process(request)
        active = await app.base.contain_process(A,
                file_data_keys=["error_code", "port", "name", "type", "value"])
        await active.enqueue_data(app.driver.set_analog_out(**A.process_params))
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/get_digital_in")
    async def get_digital_in(
                             request: Request,
                             port:Optional[int] = None
                            ):
        A = await setup_process(request)
        active = await app.base.contain_process(A,
                file_data_keys=["error_code", "port", "name", "type", "value"])
        await active.enqueue_data(app.driver.get_digital_in(**A.process_params))
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/get_digital_out")
    async def get_digital_out(
                              request: Request,
                              port:Optional[int] = None
                             ):
        A = await setup_process(request)
        active = await app.base.contain_process(A,
                file_data_keys=["error_code", "port", "name", "type", "value"])
        await active.enqueue_data(app.driver.get_digital_out(**A.process_params))
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/set_digital_out")
    async def set_digital_out(
                              request: Request,
                              port:Optional[int] = None, 
                              on:Optional[bool] = False
                             ):
        A = await setup_process(request)
        active = await app.base.contain_process(A,
                file_data_keys=["error_code", "port", "name", "type", "value"])
        await active.enqueue_data(app.driver.set_digital_out(**A.process_params))
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/reset")
    async def reset(request: Request):
        """resets galil device. only for emergency use!"""
        A = await setup_process(request)
        active = await app.base.contain_process(A, file_data_keys="reset")
        await active.enqueue_data({"reset":await app.driver.reset()})
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/estop")
    async def estop(request: Request, switch: Optional[bool] = True):
        # http://127.0.0.1:8001/motor/set/stop
        A = await setup_process(request)
        active = await app.base.contain_process(A, file_data_keys="estop")
        await active.enqueue_data({"estop":await app.driver.estop_io(switch)})
        finished_process = await active.finish()
        return finished_process.as_dict()

    
    @app.post("/shutdown")
    def post_shutdown():
        pass
    #    shutdown_event()


    @app.on_event("shutdown")
    def shutdown_event():
        app.driver.shutdown_event()

    return app
