
__all__ = ["makeApp"]

from typing import Optional
from fastapi import Body, Query
from importlib import import_module
from helaocore.server.base import makeActionServ
from helao.library.driver.galil_io_driver import Galil, TriggerType
from helaocore.schema import Action
from helaocore.error import ErrorCodes


async def galil_dyn_endpoints(app = None):
    servKey = app.base.server.server_name

    if app.driver.galil_enabled is True:

        if app.driver.dev_ai:
            @app.post(f"/{servKey}/get_analog_in")
            async def get_analog_in(
                                    action: Optional[Action] = \
                                            Body({}, embed=True),
                                    ai_item:Optional[app.driver.dev_aiitems] = None
                                   ):
                active = await app.base.setup_and_contain_action(
                                                  action_abbr = "get_ai"
                )
                active.action.action_params["ai_port"] = \
                    app.driver.dev_do[active.action.action_params["ai_item"]]
                active.action.action_params["ai_name"] = \
                    active.action.action_params["ai_item"]
                datadict = \
                    await app.driver.get_analog_in(**active.action.action_params)
                active.action.error_code = \
                    datadict.get("error_code", ErrorCodes.unspecified)
                await active.enqueue_data_dflt(datadict = datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()


        if app.driver.dev_ao:
            @app.post(f"/{servKey}/set_analog_out")
            async def set_analog_out(
                                     action: Optional[Action] = \
                                             Body({}, embed=True),
                                     ao_item:Optional[app.driver.dev_aoitems] = None,
                                     value:Optional[float] = None
                                    ):
                active = await app.base.setup_and_contain_action(
                                                  action_abbr = "set_ao"
                )
                active.action.action_params["ao_port"] = \
                    app.driver.dev_do[active.action.action_params["ao_item"]]
                active.action.action_params["ao_name"] = \
                    active.action.action_params["ao_item"]
                datadict = \
                    await app.driver.set_analog_out(**active.action.action_params)
                active.action.error_code = \
                    datadict.get("error_code", ErrorCodes.unspecified)
                await active.enqueue_data_dflt(datadict = datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

    
        if app.driver.dev_di:
            @app.post(f"/{servKey}/get_digital_in")
            async def get_digital_in(
                                     action: Optional[Action] = \
                                             Body({}, embed=True),
                                     di_item:Optional[app.driver.dev_diitems] = None
                                    ):
                active = await app.base.setup_and_contain_action(
                                                  action_abbr = "get_di"
                )
                active.action.action_params["di_port"] = \
                    app.driver.dev_do[active.action.action_params["di_item"]]
                active.action.action_params["di_name"] = \
                    active.action.action_params["di_item"]
                datadict = \
                    await app.driver.get_digital_in(**active.action.action_params)
                active.action.error_code = \
                    datadict.get("error_code", ErrorCodes.unspecified)
                await active.enqueue_data_dflt(datadict = datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()


        if app.driver.dev_do:
            @app.post(f"/{servKey}/get_digital_out")
            async def get_digital_out(
                                      action: Optional[Action] = \
                                              Body({}, embed=True),
                                      do_item:Optional[app.driver.dev_doitems] = None
                                     ):
                active = await app.base.setup_and_contain_action(
                                                  action_abbr = "get_do"
                )
                active.action.action_params["do_port"] = \
                    app.driver.dev_do[active.action.action_params["do_item"]]
                active.action.action_params["do_name"] = \
                    active.action.action_params["do_item"]
                datadict = \
                    await app.driver.get_digital_out(**active.action.action_params)
                active.action.error_code = \
                    datadict.get("error_code", ErrorCodes.unspecified)
                await active.enqueue_data_dflt(datadict = datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()


        if app.driver.dev_do:
            @app.post(f"/{servKey}/set_digital_out")
            async def set_digital_out(
                                      action: Optional[Action] = \
                                              Body({}, embed=True),
                                      do_item:Optional[app.driver.dev_doitems] = None, 
                                      on:Optional[bool] = False
                                     ):
                active = await app.base.setup_and_contain_action(
                                                  action_abbr = "set_do"
                )
                active.action.action_params["do_port"] = \
                    app.driver.dev_do[active.action.action_params["do_item"]]
                active.action.action_params["do_name"] = \
                    active.action.action_params["do_item"]
                datadict = \
                    await app.driver.set_digital_out(**active.action.action_params)
                active.action.error_code = \
                    datadict.get("error_code", ErrorCodes.unspecified)
                await active.enqueue_data_dflt(datadict = datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()


        if app.driver.dev_di \
        and app.driver.dev_do:
            @app.post(f"/{servKey}/set_digital_cycle")
            async def set_digital_cycle(
                                        action: Optional[Action] = \
                                              Body({}, embed=True),
                                        trigger_item:Optional[app.driver.dev_diitems] = "gamry_ttl0",
                                        triggertype:Optional[TriggerType] = TriggerType.risingedge,
                                        out_item:Optional[app.driver.dev_doitems] = "led",
                                        out_item_gamry:Optional[app.driver.dev_doitems] = "gamry_aux",
                                        t_on:Optional[float] = 1000,
                                        t_off:Optional[float] = 1000,
                                        mainthread:Optional[int] = Query(0, ge=0, le=8),
                                        subthread:Optional[int] = Query(1, ge=0, le=8)
                                     ):

                
                """Toggles output.\n
                   Args: \n
                       trigger_item: di on which the toggle starts\n
                       out_item: do_item for toggle output\n
                       out_item_gamry: do which is connected to gamry aux input\n
                       t_on: time (ms) out_item is on\n
                       t_off: time (ms) out_item is off"""
                active = await app.base.setup_and_contain_action()

                active.action.action_params["trigger_port"] = \
                    app.driver.dev_di[active.action.action_params["trigger_item"]]
                active.action.action_params["trigger_name"] = \
                    active.action.action_params["trigger_item"]

                active.action.action_params["out_port"] = \
                    app.driver.dev_do[active.action.action_params["out_item"]]
                active.action.action_params["out_name"] = \
                    active.action.action_params["out_item"]

                active.action.action_params["out_port_gamry"] = \
                    app.driver.dev_do[active.action.action_params["out_item_gamry"]]
                active.action.action_params["out_name_gamry"] = \
                    active.action.action_params["out_item_gamry"]


                datadict = \
                    await app.driver.set_digital_cycle(**active.action.action_params)
                active.action.error_code = \
                    datadict.get("error_code", ErrorCodes.unspecified)
                await active.enqueue_data_dflt(datadict = datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()


        if app.driver.dev_di \
        and app.driver.dev_do:
            @app.post(f"/{servKey}/stop_digital_cycle")
            async def stop_digital_cycle(
                                        action: Optional[Action] = \
                                              Body({}, embed=True),
                                     ):
                active = await app.base.setup_and_contain_action()


                datadict = \
                    await app.driver.stop_digital_cycle()
                active.action.error_code = \
                    datadict.get("error_code", ErrorCodes.unspecified)
                # await active.enqueue_data_dflt(datadict = datadict)
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
                                              action_abbr = "reset"
            )
            await active.enqueue_data_dflt(datadict = \
                                           {"reset":await app.driver.reset()})
            finished_action = await active.finish()
            return finished_action.as_dict()


def makeApp(confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config

    app = makeActionServ(
        config=config, 
        server_key=servKey, 
        server_title=servKey, 
        description="Galil IO server", 
        version=2.0, 
        driver_class=Galil,
        dyn_endpoints=galil_dyn_endpoints
    )


    
    @app.post("/shutdown")
    def post_shutdown():
        shutdown_event()


    @app.on_event("shutdown")
    def shutdown_event():
        app.base.print_message("IO shutdown")
        app.driver.shutdown_event()

    return app
