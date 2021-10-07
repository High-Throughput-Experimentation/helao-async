
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
from helao.library.driver.nidaqmx_driver import cNIMAX, pumpitems
import helao.core.model.sample as hcms

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


    @app.post(f"/{servKey}/run_task_GasFlowValves")
    async def run_task_GasFlowValves(
                                    request: Request, 
                                    valves: Optional[List[int]] = [],
                                    on: Optional[bool] = True
                                    ):
        """Provide list of Valves (number) separated by ,"""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data({"GasFlowValves": await app.driver.run_task_GasFlowValves(**A.process_params)})
        finished_act = await active.finish()
        return finished_act.as_dict()


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


    @app.post(f"/{servKey}/run_task_Pump")
    async def run_task_Pump(
                            request: Request, 
                            pump: Optional[pumpitems] = "PeriPump",
                            on: Optional[bool] = True
                            ):
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data({"pumps": await app.driver.run_task_Pump(**A.process_params)})
        finished_act = await active.finish()
        return finished_act.as_dict()


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


    @app.post(f"/{servKey}/run_task_FSW_error")
    async def run_task_FSW_error(request: Request):
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data({"FSW_error": await app.driver.run_task_getFSW("Error")})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/run_task_FSW_done")
    async def run_task_FSW_done(request: Request):
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data({"FSW_done": await app.driver.run_task_getFSW("Done")})
        finished_act = await active.finish()
        return finished_act.as_dict()


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
