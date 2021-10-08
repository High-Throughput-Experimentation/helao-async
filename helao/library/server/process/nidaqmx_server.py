
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


from helao.core.server import make_process_serv, setup_process
from helao.library.driver.nidaqmx_driver import cNIMAX
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
    dev_FSWBCDCmditems = make_str_enum("dev_FSWBCDCmd",{key:key for key in dev_FSWBCDCmd.keys()})
    dev_CellCurrent = app.server_params.get("dev_CellCurrent",dict())
    # dev_CellCurrentitems = make_str_enum("dev_CellCurrent",{key:key for key in dev_CellCurrent.keys()})
    dev_CellVoltage = app.server_params.get("dev_CellVoltage",dict())
    # dev_CellVoltageitems = make_str_enum("dev_CellVoltage",{key:key for key in dev_CellVoltage.keys()})
    dev_ActiveCellsSelection = app.server_params.get("dev_ActiveCellsSelection",dict())
    dev_ActiveCellsSelectionitems = make_str_enum("dev_ActiveCellsSelection",{key:key for key in dev_ActiveCellsSelection.keys()})
    dev_MasterCellSelect = app.server_params.get("dev_MasterCellSelect",dict())
    dev_MasterCellSelectitems = make_str_enum("dev_MasterCellSelect",{key:key for key in dev_MasterCellSelect.keys()})
    dev_FSW = app.server_params.get("dev_FSW",dict())
    dev_FSWitems = make_str_enum("dev_FSW",{key:key for key in dev_FSW.keys()})
    # dev_RSHTTLhandshake = app.server_params.get("dev_RSHTTLhandshake",dict())
    

    if dev_MasterCellSelect:
        @app.post(f"/{servKey}/select_master_cell")
        async def select_master_cell(
                                     request: Request, 
                                     cell: Optional[dev_MasterCellSelectitems],
                                     on: Optional[bool] = True
                                    ):
            A = await setup_process(request)
            active = await app.base.contain_process(A)
            # some additional params in order to call the same driver functions 
            # for all DO actions
            A.process_abbr = "mcell"
            A.process_params["do_port"] = dev_MasterCellSelect[A.process_params["cell"]]
            A.process_params["do_name"] = A.process_params["cell"]
            await active.enqueue_data({"cell": await app.driver.digital_out(**A.process_params)})
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_ActiveCellsSelection:
        @app.post(f"/{servKey}/active_cells")
        async def active_cells(
                               request: Request,
                               cell: Optional[dev_ActiveCellsSelectionitems],
                               on: Optional[bool] = True
                              ):
            A = await setup_process(request)
            active = await app.base.contain_process(A)
            # some additional params in order to call the same driver functions 
            # for all DO actions
            A.process_abbr = "acell"
            A.process_params["do_port"] = dev_ActiveCellsSelection[A.process_params["cell"]]
            A.process_params["do_name"] = A.process_params["cell"]
            await active.enqueue_data({"cell": await app.driver.digital_out(**A.process_params)})
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
            active = await app.base.contain_process(A)
            # some additional params in order to call the same driver functions 
            # for all DO actions
            A.process_abbr = "pump"
            A.process_params["do_port"] = dev_pump[A.process_params["pump"]]
            A.process_params["do_name"] = A.process_params["pump"]
            await active.enqueue_data({"pump": await app.driver.digital_out(**A.process_params)})
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_gasflowvalve:
        @app.post(f"/{servKey}/gas_flow_valve")
        async def gas_flow_valve(
                                request: Request, 
                                gasflowvalve: Optional[dev_gasflowvalveitems],
                                on: Optional[bool] = True
                                ):
            A = await setup_process(request)
            active = await app.base.contain_process(A)
            # some additional params in order to call the same driver functions 
            # for all DO actions
            A.process_abbr = "gfv"
            A.process_params["do_port"] = dev_gasflowvalve[A.process_params["gasflowvalve"]]
            A.process_params["do_name"] = A.process_params["gasflowvalve"]
            await active.enqueue_data({"gasflowvalve": await app.driver.digital_out(**A.process_params)})
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_liquidflowvalve:
        @app.post(f"/{servKey}/liquid_flow_valve")
        async def liquid_flow_valve(
                                    request: Request, 
                                    liquidflowvalve: Optional[dev_liquidflowvalveitems],
                                    on: Optional[bool] = True
                                   ):
            A = await setup_process(request)
            active = await app.base.contain_process(A)
            # some additional params in order to call the same driver functions 
            # for all DO actions
            A.process_abbr = "lfv"
            A.process_params["do_port"] = dev_liquidflowvalve[A.process_params["liquidflowvalve"]]
            A.process_params["do_name"] = A.process_params["liquidflowvalve"]
            await active.enqueue_data({"liquidflowvalve": await app.driver.digital_out(**A.process_params)})
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_FSWBCDCmd:
        @app.post(f"/{servKey}/FSWBCD")
        async def FSWBCD(
                         request: Request,
                         BCDs: Optional[dev_FSWBCDCmditems],
                         on: Optional[bool] = True
                        ):
            A = await setup_process(request)
            active = await app.base.contain_process(A)
            # some additional params in order to call the same driver functions 
            # for all DO actions
            A.process_abbr = "FSWBCD"
            A.process_params["do_port"] = dev_FSWBCDCmd[A.process_params["BCDs"]]
            A.process_params["do_name"] = A.process_params["BCDs"]
            await active.enqueue_data({"BCDs": await app.driver.digital_out(**A.process_params)})
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_FSW:
        @app.post(f"/{servKey}/FSW")
        async def FSW(
                      request: Request,
                      FSW: Optional[dev_FSWitems],
                     ):
            A = await setup_process(request)
            active = await app.base.contain_process(A)
            # some additional params in order to call the same driver functions 
            # for all DI actions
            A.process_abbr = "FSW"
            A.process_params["di_port"] = dev_FSW[A.process_params["FSW"]]
            A.process_params["di_name"] = A.process_params["FSW"]
            await active.enqueue_data({"FSW": await app.driver.digital_in(**A.process_params)})
            finished_act = await active.finish()
            return finished_act.as_dict()


    if dev_CellCurrent and dev_CellVoltage:
        @app.post(f"/{servKey}/cell_IV")
        async def cell_IV(
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
