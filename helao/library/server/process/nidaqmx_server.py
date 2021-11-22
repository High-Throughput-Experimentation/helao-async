
__all__ = ["makeApp"]

# NIdaqmx server
# https://nidaqmx-python.readthedocs.io/en/latest/task.html
# http://127.0.0.1:8006/docs#/default
# https://readthedocs.org/projects/nidaqmx-python/downloads/pdf/stable/


# TODO:
# done - add wsdata with buffering for visualizers
# - add wsstatus
# - test what happens if NImax broswer has nothing configured and only lists the device
# done - Current and voltage stream with interrut handler?
# - create tasks for process library
# - handshake as stream with interrupt

from importlib import import_module

from fastapi import Request
from typing import Optional, List


from helaocore.server import make_process_serv, setup_process
from helao.library.driver.nidaqmx_driver import cNIMAX
import helaocore.model.sample as hcms
from helaocore.helper import make_str_enum


def makeApp(confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config

    app = make_process_serv(
        config,
        servKey,
        servKey,
        "NIdaqmx server",
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
                             cell: Optional[dev_mastercellitems],
                             on: Optional[bool] = True
                            ):
            A = await setup_process(request)
            # some additional params in order to call the same driver functions 
            # for all DO actions
            A.process_abbr = "mcell"
            A.process_params["do_port"] = dev_mastercell[A.process_params["cell"]]
            A.process_params["do_name"] = A.process_params["cell"]
            active = await app.base.contain_process(A, 
                file_data_keys=["error_code", "port", "name", "type", "value"])
            await active.enqueue_data(await app.driver.set_digital_out(**A.process_params))
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_activecell:
        @app.post(f"/{servKey}/activecell")
        async def activecell(
                             request: Request,
                             cell: Optional[dev_activecellitems],
                             on: Optional[bool] = True
                            ):
            A = await setup_process(request)
            # some additional params in order to call the same driver functions 
            # for all DO actions
            A.process_abbr = "acell"
            A.process_params["do_port"] = dev_activecell[A.process_params["cell"]]
            A.process_params["do_name"] = A.process_params["cell"]
            active = await app.base.contain_process(A,
                file_data_keys=["error_code", "port", "name", "type", "value"])
            await active.enqueue_data(await app.driver.set_digital_out(**A.process_params))
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_pump:
        @app.post(f"/{servKey}/pump")
        async def pump(
                       request: Request, 
                       pump: Optional[dev_pumpitems],
                       on: Optional[bool] = True
                      ):
            A = await setup_process(request)
            # some additional params in order to call the same driver functions 
            # for all DO actions
            A.process_abbr = "pump"
            A.process_params["do_port"] = dev_pump[A.process_params["pump"]]
            A.process_params["do_name"] = A.process_params["pump"]
            active = await app.base.contain_process(A,
                file_data_keys=["error_code", "port", "name", "type", "value"])
            await active.enqueue_data(await app.driver.set_digital_out(**A.process_params))
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_gasvalve:
        @app.post(f"/{servKey}/gasvalve")
        async def gasvalve(
                           request: Request, 
                           gasvalve: Optional[dev_gasvalveitems],
                           on: Optional[bool] = True
                          ):
            A = await setup_process(request)
            # some additional params in order to call the same driver functions 
            # for all DO actions
            A.process_abbr = "gfv"
            A.process_params["do_port"] = dev_gasvalve[A.process_params["gasvalve"]]
            A.process_params["do_name"] = A.process_params["gasvalve"]
            active = await app.base.contain_process(A,
                file_data_keys=["error_code", "port", "name", "type", "value"])
            await active.enqueue_data(await app.driver.set_digital_out(**A.process_params))
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_liquidvalve:
        @app.post(f"/{servKey}/liquidvalve")
        async def liquidvalve(
                              request: Request, 
                              liquidvalve: Optional[dev_liquidvalveitems],
                              on: Optional[bool] = True
                             ):
            A = await setup_process(request)
            # some additional params in order to call the same driver functions 
            # for all DO actions
            A.process_abbr = "lfv"
            A.process_params["do_port"] = dev_liquidvalve[A.process_params["liquidvalve"]]
            A.process_params["do_name"] = A.process_params["liquidvalve"]
            active = await app.base.contain_process(A,
                file_data_keys=["error_code", "port", "name", "type", "value"])
            await active.enqueue_data(await app.driver.set_digital_out(**A.process_params))
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_led:
        @app.post(f"/{servKey}/led")
        async def led(
                              request: Request, 
                              led: Optional[dev_leditems],
                              on: Optional[bool] = True
                             ):
            A = await setup_process(request)
            # some additional params in order to call the same driver functions 
            # for all DO actions
            A.process_abbr = "lfv"
            A.process_params["do_port"] = dev_led[A.process_params["led"]]
            A.process_params["do_name"] = A.process_params["led"]
            active = await app.base.contain_process(A,
                file_data_keys=["error_code", "port", "name", "type", "value"])
            await active.enqueue_data(await app.driver.set_digital_out(**A.process_params))
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_fswbcd:
        @app.post(f"/{servKey}/fswbcd")
        async def fswbcd(
                         request: Request,
                         fswbcd: Optional[dev_fswbcditems],
                         on: Optional[bool] = True
                        ):
            A = await setup_process(request)
            # some additional params in order to call the same driver functions 
            # for all DO actions
            A.process_abbr = "fswbcd"
            A.process_params["do_port"] = dev_fswbcd[A.process_params["fswbcd"]]
            A.process_params["do_name"] = A.process_params["fswbcd"]
            active = await app.base.contain_process(A,
                file_data_keys=["error_code", "port", "name", "type", "value"])
            await active.enqueue_data(await app.driver.set_digital_out(**A.process_params))
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_fsw:
        @app.post(f"/{servKey}/fsw")
        async def fsw(
                      request: Request,
                      fsw: Optional[dev_fswitems],
                     ):
            A = await setup_process(request)
            # some additional params in order to call the same driver functions 
            # for all DI actions
            A.process_abbr = "fsw"
            A.process_params["di_port"] = dev_fsw[A.process_params["fsw"]]
            A.process_params["di_name"] = A.process_params["fsw"]
            active = await app.base.contain_process(A,
                file_data_keys=["error_code", "port", "name", "type", "value"])
            await active.enqueue_data(await app.driver.get_digital_in(**A.process_params))
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_cellcurrent and dev_cellvoltage:
        @app.post(f"/{servKey}/cellIV")
        async def cellIV(
                         request: Request, 
                         fast_samples_in: Optional[hcms.SampleList] = \
                             hcms.SampleList(samples=[hcms.LiquidSample(**{"sample_no":1})]),
                         Tval: Optional[float] = 10.0,
                         SampleRate: Optional[float] = 1.0, 
                         TTLwait: Optional[int] = -1,  # -1 disables, else select TTL channel
                         scratch: Optional[List[None]] = [None], # temp fix so swagger still works
                        ):
            """Runs multi cell IV measurement."""
            A = await setup_process(request)
            A.process_abbr = "multiCV"
            active_dict = await app.driver.run_cell_IV(A)
            return active_dict


    @app.post(f"/{servKey}/stop")
    async def stop(request: Request):
        """Stops measurement in a controlled way."""
        A = await setup_process(request)
        active = await app.base.contain_process(A, file_data_keys="stop")
        await active.enqueue_data({"stop": await app.driver.stop()})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/estop")
    async def estop(
                   request: Request, 
                   switch: Optional[bool] = True
                   ):
        """Same as stop, but also sets estop flag."""
        A = await setup_process(request)
        active = await app.base.contain_process(A, file_data_keys="estop")
        await active.enqueue_data({"estop": await app.driver.estop(**A.process_params)})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post("/shutdown")
    def post_shutdown():
        shutdown_event()

    @app.on_event("shutdown")
    def shutdown_event():
        return ""

    return app
