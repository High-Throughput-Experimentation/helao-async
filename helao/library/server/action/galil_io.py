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

from typing import Optional
from fastapi import Body
from importlib import import_module
from helaocore.server import makeActionServ
from helao.library.driver.galil_io_driver import galil
from helaocore.schema import Action


def makeApp(confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config

    app = makeActionServ(
        config=config, 
        server_key=servKey, 
        server_title=servKey, 
        description="Galil IO server", 
        version=2.0, 
        driver_class=galil
    )


    @app.post(f"/{servKey}/get_analog_in")
    async def get_analog_in(
                            action: Optional[Action] = \
                                    Body({}, embed=True),
                            port:Optional[int] = None
                           ):
        A = await app.base.setup_action()
        active = await app.base.contain_action(A,
                json_data_keys=["error_code", "port", "name", "type", "value"])
        await active.enqueue_data(app.driver.get_analog_in(**A.action_params))
        finished_action = await active.finish()
        return finished_action.as_dict()


    @app.post(f"/{servKey}/set_analog_out")
    async def set_analog_out(
                             action: Optional[Action] = \
                                     Body({}, embed=True),
                             port:Optional[int] = None,
                             value:Optional[float] = None
                            ):
        active = await app.base.setup_and_contain_action(
                                          json_data_keys = [
                                                            "error_code", 
                                                            "port", 
                                                            "name", 
                                                            "type", 
                                                            "value"
                                                           ],
                                          action_abbr = "set_ao"
        )
        await active.enqueue_data_dflt(datadict = \
                await app.driver.set_analog_out(**active.action.action_params))
        finished_action = await active.finish()
        return finished_action.as_dict()


    @app.post(f"/{servKey}/get_digital_in")
    async def get_digital_in(
                             action: Optional[Action] = \
                                     Body({}, embed=True),
                             port:Optional[int] = None
                            ):
        active = await app.base.setup_and_contain_action(
                                          json_data_keys = [
                                                            "error_code", 
                                                            "port", 
                                                            "name", 
                                                            "type", 
                                                            "value"
                                                           ],
                                          action_abbr = "get_di"
        )
        await active.enqueue_data_dflt(datadict = \
                await app.driver.get_digital_in(**active.action.action_params))
        finished_action = await active.finish()
        return finished_action.as_dict()


    @app.post(f"/{servKey}/get_digital_out")
    async def get_digital_out(
                              action: Optional[Action] = \
                                      Body({}, embed=True),
                              port:Optional[int] = None
                             ):
        active = await app.base.setup_and_contain_action(
                                          json_data_keys = [
                                                            "error_code", 
                                                            "port", 
                                                            "name", 
                                                            "type", 
                                                            "value"
                                                           ],
                                          action_abbr = "get_do"
        )
        await active.enqueue_data_dflt(datadict = \
               await app.driver.get_digital_out(**active.action.action_params))
        finished_action = await active.finish()
        return finished_action.as_dict()


    @app.post(f"/{servKey}/set_digital_out")
    async def set_digital_out(
                              action: Optional[Action] = \
                                      Body({}, embed=True),
                              port:Optional[int] = None, 
                              on:Optional[bool] = False
                             ):
        active = await app.base.setup_and_contain_action(
                                          json_data_keys = [
                                                            "error_code", 
                                                            "port", 
                                                            "name", 
                                                            "type", 
                                                            "value"
                                                           ],
                                          action_abbr = "set_do"
        )
        await active.enqueue_data_dflt(datadict = \
               await app.driver.set_digital_out(**active.action.action_params))
        finished_action = await active.finish()
        return finished_action.as_dict()


    @app.post(f"/{servKey}/reset")
    async def reset(
                    action: Optional[Action] = \
                            Body({}, embed=True),
                   ):
        """FOR EMERGENCY USE ONLY!
           resets galil device. 
        """
        active = await app.base.setup_and_contain_action(
                                          json_data_keys = [
                                                            "reset",
                                                           ],
                                          action_abbr = "reset"
        )
        await active.enqueue_data_dflt(datadict = \
                                       {"reset":await app.driver.reset()})
        finished_action = await active.finish()
        return finished_action.as_dict()

    
    @app.post("/shutdown")
    def post_shutdown():
        pass
    #    shutdown_event()


    @app.on_event("shutdown")
    def shutdown_event():
        app.driver.shutdown_event()

    return app
