
__all__ = ["makeApp"]

# NIdaqmx server
# https://nidaqmx-python.readthedocs.io/en/latest/task.html
# http://127.0.0.1:8006/docs#/default
# https://readthedocs.org/projects/nidaqmx-python/downloads/pdf/stable/


# TODO:
# done - add wsdata with buffering for visualizers
# - add wsstatus
# - test what happens if NImax broswer has nothing configured and only lists the device
# - create tasks for action library
# - handshake as stream with interrupt

from importlib import import_module

from fastapi import Request, Body
from typing import Optional, List
from socket import gethostname


from helaocore.server import makeActionServ, setup_action
from helao.library.driver.nidaqmx_driver import cNIMAX
import helaocore.model.sample as hcms
from helaocore.helper import make_str_enum


def makeApp(confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config

    app = makeActionServ(
        config=config,
        server_key=servKey,
        server_title=servKey,
        description="NIdaqmx server",
        version=2.0,
        driver_class=cNIMAX,
    )


    dev_pump = app.server_params.get("dev_pump",dict())
    dev_pumpitems = make_str_enum("dev_pump",{key:key for key in dev_pump})


    dev_gasvalve = app.server_params.get("dev_gasvalve",dict())
    dev_gasvalveitems = make_str_enum("dev_gasvalve",{key:key for key in dev_gasvalve})
    
    dev_liquidvalve = app.server_params.get("dev_liquidvalve",dict())
    dev_liquidvalveitems = make_str_enum("dev_liquidvalve",{key:key for key in dev_liquidvalve})
    
    dev_led = app.server_params.get("dev_led",dict())
    dev_leditems = make_str_enum("dev_led",{key:key for key in dev_led})
    
    dev_fswbcd = app.server_params.get("dev_fswbcd",dict())
    dev_fswbcditems = make_str_enum("dev_fswbcd",{key:key for key in dev_fswbcd})
    dev_cellcurrent = app.server_params.get("dev_cellcurrent",dict())
    # dev_cellcurrentitems = make_str_enum("dev_cellcurrent",{key:key for key in dev_cellcurrent})
    dev_cellvoltage = app.server_params.get("dev_cellvoltage",dict())
    # dev_cellvoltageitems = make_str_enum("dev_cellvoltage",{key:key for key in dev_cellvoltage})
    dev_activecell = app.server_params.get("dev_activecell",dict())
    dev_activecellitems = make_str_enum("dev_activecell",{key:key for key in dev_activecell})
    dev_mastercell = app.server_params.get("dev_mastercell",dict())
    dev_mastercellitems = make_str_enum("dev_mastercell",{key:key for key in dev_mastercell})
    dev_fsw = app.server_params.get("dev_fsw",dict())
    dev_fswitems = make_str_enum("dev_fsw",{key:key for key in dev_fsw})
    # dev_RSHTTLhandshake = app.server_params.get("dev_RSHTTLhandshake",dict())
    

    if dev_mastercell:
        @app.post(f"/{servKey}/mastercell")
        async def mastercell(
                             request: Request, 
                             cell: Optional[dev_mastercellitems] = None,
                             on: Optional[bool] = True
                            ):
            active = await app.base.setup_and_contain_action(
                                              request = request,
                                              json_data_keys = [
                                                                "error_code", 
                                                                "port", 
                                                                "name", 
                                                                "type", 
                                                                "value"
                                                               ],
                                              action_abbr = "mcell"
            )
            # some additional params in order to call the same driver functions 
            # for all DO actions
            active.action.action_params["do_port"] = dev_mastercell[str(active.action.action_params["cell"])]
            active.action.action_params["do_name"] = active.action.action_params["cell"]
            await active.enqueue_data_dflt(datadict = \
                                           await app.driver.set_digital_out(**active.action.action_params))
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_activecell:
        @app.post(f"/{servKey}/activecell")
        async def activecell(
                             request: Request,
                             cell: Optional[dev_activecellitems] = None,
                             on: Optional[bool] = True
                            ):
            active = await app.base.setup_and_contain_action(
                                              request = request,
                                              json_data_keys = [
                                                                "error_code", 
                                                                "port", 
                                                                "name", 
                                                                "type", 
                                                                "value"
                                                               ],
                                              action_abbr = "acell"
            )
            # some additional params in order to call the same driver functions 
            # for all DO actions
            active.action.action_params["do_port"] = dev_activecell[str(active.action.action_params["cell"])]
            active.action.action_params["do_name"] = active.action.action_params["cell"]
            await active.enqueue_data_dflt(datadict = \
                                           await app.driver.set_digital_out(**active.action.action_params))
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_pump:
        @app.post(f"/{servKey}/pump")
        async def pump(
                       request: Request, 
                       pump: Optional[dev_pumpitems] = None,
                       on: Optional[bool] = True
                      ):
            active = await app.base.setup_and_contain_action(
                                              request = request,
                                              json_data_keys = [
                                                                "error_code", 
                                                                "port", 
                                                                "name", 
                                                                "type", 
                                                                "value"
                                                               ],
                                              action_abbr = "pump"
            )
            # some additional params in order to call the same driver functions 
            # for all DO actions
            active.action.action_params["do_port"] = dev_pump[str(active.action.action_params["pump"])]
            active.action.action_params["do_name"] = active.action.action_params["pump"]
            await active.enqueue_data_dflt(datadict = \
                                           await app.driver.set_digital_out(**active.action.action_params))
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_gasvalve:
        @app.post(f"/{servKey}/gasvalve")
        async def gasvalve(
                           request: Request, 
                           gasvalve: Optional[dev_gasvalveitems] = None,
                           on: Optional[bool] = True
                          ):
            active = await app.base.setup_and_contain_action(
                                              request = request,
                                              json_data_keys = [
                                                                "error_code", 
                                                                "port", 
                                                                "name", 
                                                                "type", 
                                                                "value"
                                                               ],
                                              action_abbr = "gfv"
            )
            # some additional params in order to call the same driver functions 
            # for all DO actions
            active.action.action_params["do_port"] = dev_gasvalve[str(active.action.action_params["gasvalve"])]
            active.action.action_params["do_name"] = active.action.action_params["gasvalve"]
            await active.enqueue_data_dflt(datadict = \
                                           await app.driver.set_digital_out(**active.action.action_params))
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_liquidvalve:
        @app.post(f"/{servKey}/liquidvalve")
        async def liquidvalve(
                              request: Request, 
                              liquidvalve: Optional[dev_liquidvalveitems] = None,
                              on: Optional[bool] = True
                             ):
            active = await app.base.setup_and_contain_action(
                                              request = request,
                                              json_data_keys = [
                                                                "error_code", 
                                                                "port", 
                                                                "name", 
                                                                "type", 
                                                                "value"
                                                               ],
                                              action_abbr = "lfv"
            )
            # some additional params in order to call the same driver functions 
            # for all DO actions
            active.action.action_params["do_port"] = dev_liquidvalve[str(active.action.action_params["liquidvalve"])]
            active.action.action_params["do_name"] = active.action.action_params["liquidvalve"]
            await active.enqueue_data_dflt(datadict = \
                                           await app.driver.set_digital_out(**active.action.action_params))
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_led:
        @app.post(f"/{servKey}/led")
        async def led(
                              request: Request, 
                              led: Optional[dev_leditems],
                              on: Optional[bool] = True
                             ):
            active = await app.base.setup_and_contain_action(
                                              request = request,
                                              json_data_keys = [
                                                                "error_code", 
                                                                "port", 
                                                                "name", 
                                                                "type", 
                                                                "value"
                                                               ],
                                              action_abbr = "led"
            )
            # some additional params in order to call the same driver functions 
            # for all DO actions
            active.action.action_params["do_port"] = dev_led[str(active.action.action_params["led"])]
            active.action.action_params["do_name"] = active.action.action_params["led"]
            await active.enqueue_data_dflt(datadict = \
                                           await app.driver.set_digital_out(**active.action.action_params))
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_fswbcd:
        @app.post(f"/{servKey}/fswbcd")
        async def fswbcd(
                         request: Request,
                         fswbcd: Optional[dev_fswbcditems] = None,
                         on: Optional[bool] = True
                        ):
            active = await app.base.setup_and_contain_action(
                                              request = request,
                                              json_data_keys = [
                                                                "error_code", 
                                                                "port", 
                                                                "name", 
                                                                "type", 
                                                                "value"
                                                               ],
                                              action_abbr = "fswbcd"
            )
            # some additional params in order to call the same driver functions 
            # for all DO actions
            active.action.action_params["do_port"] = dev_fswbcd[str(active.action.action_params["fswbcd"])]
            active.action.action_params["do_name"] = active.action.action_params["fswbcd"]
            await active.enqueue_data_dflt(datadict = \
                                           await app.driver.set_digital_out(**active.action.action_params))
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_fsw:
        @app.post(f"/{servKey}/fsw")
        async def fsw(
                      request: Request,
                      fsw: Optional[dev_fswitems] = None,
                     ):
            active = await app.base.setup_and_contain_action(
                                              request = request,
                                              json_data_keys = [
                                                                "error_code", 
                                                                "port", 
                                                                "name", 
                                                                "type", 
                                                                "value"
                                                               ],
                                              action_abbr = "fsw"
            )
            # some additional params in order to call the same driver functions 
            # for all DI actions
            active.action.action_params["di_port"] = dev_fsw[str(active.action.action_params["fsw"])]
            active.action.action_params["di_name"] = active.action.action_params["fsw"]
            await active.enqueue_data_dflt(datadict = \
                                           await app.driver.get_digital_in(**active.action.action_params))
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_cellcurrent and dev_cellvoltage:
        @app.post(f"/{servKey}/cellIV")
        async def cellIV(
                         request: Request, 
                      fast_samples_in: Optional[List[hcms.SampleUnion]] = \
                          Body(\
           [hcms.LiquidSample(**{"sample_no":1,"machine_name":gethostname()})], embed=True),
                         Tval: Optional[float] = 10.0,
                         SampleRate: Optional[float] = 1.0, 
                         TTLwait: Optional[int] = -1,  # -1 disables, else select TTL channel
                        ):
            """Runs multi cell IV measurement."""
            A = await setup_action(request)
            A.action_abbr = "multiCV"
            active_dict = await app.driver.run_cell_IV(A)
            return active_dict


    @app.post(f"/{servKey}/stop")
    async def stop(request: Request):
        """Stops measurement in a controlled way."""
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["stop"],
                                          action_abbr = "stop"
        )
        await active.enqueue_data_dflt(datadict = \
                                       {"stop": await app.driver.stop()})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/estop")
    async def estop(
                   request: Request, 
                   switch: Optional[bool] = True
                   ):
        """Same as stop, but also sets estop flag."""
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["estop"],
                                          action_abbr = "estop"
        )
        await active.enqueue_data_dflt(datadict = \
                                       {"estop": await app.driver.estop(**active.action.action_params)})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post("/shutdown")
    def post_shutdown():
        shutdown_event()

    @app.on_event("shutdown")
    def shutdown_event():
        return ""

    return app
