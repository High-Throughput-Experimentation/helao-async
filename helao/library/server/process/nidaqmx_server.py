
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
from typing import Optional, List, Union


from helao.core.server import make_process_serv, setup_process
from helao.library.driver.nidaqmx_driver import cNIMAX#, pumpitems
import helao.core.model.sample as hcms
from helao.core.helper import make_str_enum


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
    dev_pumpitems = make_str_enum("dev_pump",{key:key for key in dev_pump.keys()})


    dev_gasflowvalve = app.server_params.get("dev_gasflowvalve",dict())
    dev_gasflowvalveitems = make_str_enum("dev_gasflowvalve",{key:key for key in dev_gasflowvalve.keys()})
    
    dev_liquidflowvalve = app.server_params.get("dev_liquidflowvalve",dict())
    dev_liquidflowvalveitems = make_str_enum("dev_liquidflowvalve",{key:key for key in dev_liquidflowvalve.keys()})
    
    dev_FSWBCDCmd = app.server_params.get("dev_FSWBCDCmd",dict())   
    dev_CellCurrent = app.server_params.get("dev_CellCurrent",dict())
    dev_CellVoltage = app.server_params.get("dev_CellVoltage",dict())
    dev_ActiveCellsSelection = app.server_params.get("dev_ActiveCellsSelection",dict())
    dev_MasterCellSelect = app.server_params.get("dev_MasterCellSelect",dict())
    dev_FSW = app.server_params.get("dev_FSW",dict())
    # dev_RSHTTLhandshake = app.server_params.get("dev_RSHTTLhandshake",dict())
    

    # @app.post(f"/{servKey}/run_task_gasflowvalves")
    # async def run_task_gasflowvalves(
    #                                 request: Request, 
    #                                 valves: Optional[List[int]] = [],
    #                                 on: Optional[bool] = True
    #                                 ):
    #     """Provide list of Valves (number) separated by ,"""
    #     A = await setup_process(request)
    #     active = await app.base.contain_process(A)
    #     await active.enqueue_data({"gasflowvalves": await app.driver.run_task_gasflowvalves(**A.process_params)})
    #     finished_act = await active.finish()
    #     return finished_act.as_dict()

    if dev_MasterCellSelect:
        @app.post(f"/{servKey}/run_task_Master_Cell_Select")
        async def run_task_Master_Cell_Select(
                                             request: Request, 
                                             cells: Optional[List[int]] = [], 
                                             on: Optional[bool] = True
                                             ):
            """Provide list of Cells separated by ,"""
            A = await setup_process(request)
            active = await app.base.contain_process(A)
            await active.enqueue_data({"Master_Cell": await app.driver.run_task_Master_Cell_Select(**A.process_params)})
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_ActiveCellsSelection:
        @app.post(f"/{servKey}/run_task_Active_Cells_Selection")
        async def run_task_Active_Cells_Selection(
                                                 request: Request,
                                                 cells: Optional[List[int]] = [], 
                                                 on: Optional[bool] = True
                                                 ):
            """Provide list of Cells (number) separated by ,"""
            A = await setup_process(request)
            active = await app.base.contain_process(A)
            await active.enqueue_data({"Active_Cells": await app.driver.run_task_Active_Cells_Selection(**A.process_params)})
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_pump:
        @app.post(f"/{servKey}/run_task_pump")
        async def run_task_pump(
                                request: Request, 
                                pump: Optional[dev_pumpitems],
                                on: Optional[bool] = True
                                ):
            A = await setup_process(request)
            active = await app.base.contain_process(A)
            await active.enqueue_data({"pump": await app.driver.run_task_Pump(**A.process_params)})
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_gasflowvalve:
        @app.post(f"/{servKey}/run_task_gasflowvalve")
        async def run_task_gasflowvalve(
                                request: Request, 
                                gasflowvalve: Optional[dev_gasflowvalveitems],
                                on: Optional[bool] = True
                                ):
            A = await setup_process(request)
            active = await app.base.contain_process(A)
            await active.enqueue_data({"gasflowvalve": await app.driver.run_task_gasflowvalve(**A.process_params)})
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_liquidflowvalve:
        @app.post(f"/{servKey}/run_task_liquidflowvalve")
        async def run_task_liquidflowvalve(
                                request: Request, 
                                liquidflowvalve: Optional[dev_liquidflowvalveitems],
                                on: Optional[bool] = True
                                ):
            A = await setup_process(request)
            active = await app.base.contain_process(A)
            await active.enqueue_data({"liquidflowvalve": await app.driver.run_task_liquidflowvalve(**A.process_params)})
            finished_act = await active.finish()
            return finished_act.as_dict()

    if dev_FSWBCDCmd:
        @app.post(f"/{servKey}/run_task_FSWBCD")
        async def run_task_FSWBCD(
                                 request: Request,
                                 BCDs: Optional[str] = "",
                                 on: Optional[bool] = True
                                 ):
            A = await setup_process(request)
            active = await app.base.contain_process(A)
            await active.enqueue_data({"FSWBCD": await app.driver.run_task_FSWBCD(**A.process_params)})
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_FSW:
        @app.post(f"/{servKey}/run_task_FSW_error")
        async def run_task_FSW_error(request: Request):
            A = await setup_process(request)
            active = await app.base.contain_process(A)
            await active.enqueue_data({"FSW_error": await app.driver.run_task_getFSW("Error")})
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_FSW:
        @app.post(f"/{servKey}/run_task_FSW_done")
        async def run_task_FSW_done(request: Request):
            A = await setup_process(request)
            active = await app.base.contain_process(A)
            await active.enqueue_data({"FSW_done": await app.driver.run_task_getFSW("Done")})
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_CellCurrent and dev_CellVoltage:
        @app.post(f"/{servKey}/run_cell_IV")
        async def run_cell_IV(
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
            # A.save_data = True
            active_dict = await app.driver.run_cell_IV(A)
            return active_dict


    @app.post(f"/{servKey}/stop")
    async def stop(request: Request):
        """Stops measurement in a controlled way."""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data({"stop_result": await app.driver.stop()})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/estop")
    async def estop(
                   request: Request, 
                   switch: Optional[bool] = True
                   ):
        """Same as stop, but also sets estop flag."""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data({"estop_result": await app.driver.estop(**A.process_params)})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post("/shutdown")
    def post_shutdown():
        shutdown_event()

    @app.on_event("shutdown")
    def shutdown_event():
        return ""

    return app
