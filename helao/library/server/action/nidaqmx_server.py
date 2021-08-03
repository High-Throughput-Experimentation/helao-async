# NIdaqmx server
# https://nidaqmx-python.readthedocs.io/en/latest/task.html
# http://127.0.0.1:8006/docs#/default
# https://readthedocs.org/projects/nidaqmx-python/downloads/pdf/stable/


# TODO:
# done - add wsdata with buffering for visualizers
# - add wsstatus
# - test what happens if NImax broswer has nothing configured and only lists the device
# done - Current and voltage stream with interrut handler?
# - create tasks for action library
# - handshake as stream with interrupt

from importlib import import_module

from fastapi import Request
from typing import Optional, List, Union


from helao.core.server import Action, makeActServ, setupAct
from helao.library.driver.nidaqmx_driver import cNIMAX, pumpitems


def makeApp(confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config

    app = makeActServ(
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
                                    on: Optional[bool] = True,
                                    action_dict: dict = {}
                                    ):
        """Provide list of Valves (number) separated by ,"""
        A = await setupAct(action_dict, request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data({"GasFlowValves": await app.driver.run_task_GasFlowValves(**A.action_params)})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/run_task_Master_Cell_Select")
    async def run_task_Master_Cell_Select(
                                         request: Request, 
                                         cells: Optional[List[int]] = [], 
                                         on: Optional[bool] = True,
                                         action_dict: dict = {}
                                         ):
        """Provide list of Cells separated by ,"""
        A = await setupAct(action_dict, request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data({"Master_Cell": await app.driver.run_task_Master_Cell_Select(**A.action_params)})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/run_task_Active_Cells_Selection")
    async def run_task_Active_Cells_Selection(
                                             request: Request,
                                             cells: Optional[List[int]] = [], 
                                             on: Optional[bool] = True,
                                             action_dict: dict = {}
                                             ):
        """Provide list of Cells (number) separated by ,"""
        A = await setupAct(action_dict, request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data({"Active_Cells": await app.driver.run_task_Active_Cells_Selection(**A.action_params)})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/run_task_Pumps")
    async def run_task_Pumps(
                            request: Request, 
                            pumps: Optional[pumpitems] = "PeriPump",
                            on: Optional[bool] = True,
                            action_dict: dict = {}
                            ):
        A = await setupAct(action_dict, request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data({"pumps": await app.driver.run_task_Pumps(**A.action_params)})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/run_task_FSWBCD")
    async def run_task_FSWBCD(
                             request: Request,
                             BCDs: Optional[str] = "",
                             on: Optional[bool] = True,
                             action_dict: dict = {}
                             ):
        A = await setupAct(action_dict, request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data({"FSWBCD": await app.driver.run_task_FSWBCD(**A.action_params)})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/run_task_FSW_error")
    async def run_task_FSW_error(
                                request: Request, 
                                action_dict: dict = {}
                                ):
        A = await setupAct(action_dict, request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data({"FSW_error": await app.driver.run_task_getFSW("Error")})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/run_task_FSW_done")
    async def run_task_FSW_done(
                                request: Request, 
                                action_dict: dict = {}
                               ):
        A = await setupAct(action_dict, request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data({"FSW_done": await app.driver.run_task_getFSW("Done")()})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/run_task_Cell_IV")
    async def run_task_Cell_IV(
                              request: Request, 
                              on: Optional[bool] = True, 
                              tstep: Optional[float] = 1.0,
                              action_dict: dict = {},
                              ):
        """Get the current/voltage measurement for each cell.
        Only active cells are plotted in visualizer."""
        A = await setupAct(action_dict, request, locals())
        A.save_data = True
        active_dict = await app.driver.run_task_Cell_IV(A)
        return active_dict


    @app.post(f"/{servKey}/stop")
    async def stop(
                  request: Request, 
                  action_dict: dict = {}
                  ):
        """Stops measurement in a controlled way."""
        A = await setupAct(action_dict, request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data({"stop_result": await app.driver.stop()})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/estop")
    async def estop(
                   request: Request, 
                   switch: Optional[bool] = True,
                   action_dict: dict = {}
                   ):
        """Same as stop, but also sets estop flag."""
        A = await setupAct(action_dict, request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data({"estop_result": await app.driver.estop(**A.action_params)})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post("/shutdown")
    def post_shutdown():
        shutdown_event()

    @app.on_event("shutdown")
    def shutdown_event():
        return ""

    return app
