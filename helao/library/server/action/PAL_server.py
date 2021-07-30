from importlib import import_module

from helao.core.server import Action, makeActServ, setupAct
from helao.library.driver.PAL_driver import cPAL
from helao.library.driver.PAL_driver import PALmethods
from helao.library.driver.PAL_driver import Spacingmethod
from helao.library.driver.PAL_driver import PALtools


from fastapi import Request
from typing import Optional, List, Union

def makeApp(confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config

    app = makeActServ(
        config,
        servKey,
        servKey,
        "PAL Autosampler Server",
        version=2.0,
        driver_class=cPAL,
    )


    @app.post(f"/{servKey}/reset_PAL_system_vial_table")
    async def reset_PAL_system_vial_table(
        request: Request, 
        action_dict: dict = {}
    ):
        """Resets app.driver vial table. But will make a full dump to CSV first."""
        A = await setupAct(action_dict, request, locals())
        finished_act = await app.driver.reset_PAL_system_vial_table(A)
        return finished_act.as_dict()


    @app.post(f"/{servKey}/update_PAL_system_vial_table")
    async def update_PAL_system_vial_table(
        request: Request, 
        vial: Optional[int] = None,
        vol_mL: Optional[float] = None,
        liquid_sample_no: Optional[int] = None,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        action_dict: dict = {}
    ):
        """Updates app.driver vial Table. If sucessful (vial-slot was empty) returns True, else it returns False."""
        A = await setupAct(action_dict, request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data({"update": await app.driver.update_PAL_system_vial_table(**A.action_params)})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/get_vial_holder_table")
    async def get_vial_holder_table(
        request: Request, 
        tray: Optional[int] = None, 
        slot: Optional[int] = None, 
        action_dict: dict = {}
    ):
        A = await setupAct(action_dict, request, locals())
        finished_act = await app.driver.get_vial_holder_table(A)
        return finished_act.as_dict()


    @app.post(f"/{servKey}/write_vial_holder_table_CSV")
    async def write_vial_holder_table_CSV(
        request: Request, 
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        action_dict: dict = {}
    ):
        A = await setupAct(action_dict, request, locals())
        A.action_params["csv"] = True # signal subroutine to create a csv
        finished_act = await app.driver.get_vial_holder_table(A)
        return finished_act.as_dict()


    @app.post(f"/{servKey}/get_new_vial_position")
    async def get_new_vial_position(
        request: Request, 
        req_vol: Optional[float] = None,
        action_dict: dict = {}
    ):
        """Returns an empty vial position for given max volume.\n
        For mixed vial sizes the req_vol helps to choose the proper vial for sample volume.\n
        It will select the first empty vial which has the smallest volume that still can hold req_vol"""
        A = await setupAct(action_dict, request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data({"vial_position": await app.driver.get_new_vial_position(**A.action_params)})
        finished_act = await active.finish()
        return finished_act.as_dict()


    # relay_actuation_test2.cam
    # lcfc_archive.cam
    # lcfc_fill.cam
    # lcfc_fill_hardcodedvolume.cam
    @app.post(f"/{servKey}/run_method")
    async def run_method(
        request: Request, 
        liquid_sample_no_in: Optional[int],
        PAL_method: Optional[PALmethods] = PALmethods.fillfixed,  # lcfc_fill_hardcodedvolume.cam',
        PAL_tool: Optional[PALtools] = PALtools.LS3,
        PAL_source: Optional[str] = "elec_res1",
        PAL_volume_uL: Optional[int] = 500,  # uL
        PAL_totalvials: Optional[int] = 1,
        PAL_sampleperiod: Optional[List[float]] = [0.0],
        PAL_spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
        PAL_spacingfactor: Optional[float] = 1.0,
        PAL_timeoffset: Optional[float] = 0.0,
        PAL_wash1: Optional[bool] = False,
        PAL_wash2: Optional[bool] = False,
        PAL_wash3: Optional[bool] = False,
        PAL_wash4: Optional[bool] = False,
        action_dict: dict = {}
    ):
        A = await setupAct(action_dict, request, locals())
        A.action_params["dest_tray"] = None
        A.action_params["dest_slot"] = None
        A.action_params["dest_vial"] = None
        A.save_data = True
        active_dict = await app.driver.init_PAL_IOloop(A)
        return active_dict


    @app.post(f"/{servKey}/create_new_liquid_sample_no")
    async def create_new_liquid_sample_no(request: Request, 
                            source: Optional[str] = None,
                            # sourcevol_mL: Optional[str] = None,
                            volume_mL: Optional[float] = None,
                            action_time: Optional[str] = [],
                            chemical: Optional[List[str]] = [],  
                            mass: Optional[List[str]] = [],
                            supplier: Optional[List[str]] = [],
                            lot_number: Optional[List[str]] = [],
                            plate_id: int = None,
                            sample_no: int = None,
                            action_dict: dict = {}
                            ):
        '''use CAS for chemical if available. Written on bottles of chemicals with all other necessary information.\n
        For empty DUID and AUID the UID will automatically created. For manual entry leave DUID, AUID, action_time, and action_params empty and servkey on "data".\n
        If its the very first liquid (no source in database exists) leave source and source_mL empty.'''
        A = await setupAct(action_dict, request, locals())
        active = await app.base.contain_action(A)
        A.action_params["DUID"] = A.decision_uuid
        A.action_params["AUID"] = A.action_uuid
        await active.enqueue_data({'liquid_sample_no': await app.driver.create_new_liquid_sample_no(**A.action_params)})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/get_last_liquid_sample_no")
    async def get_last_liquid_sample_no(request: Request, action_dict: dict = {}):
        A = await setupAct(action_dict, request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data({'liquid_sample_no': await app.driver.get_last_liquid_sample_no()})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/get_liquid_sample_no")
    async def get_liquid_sample_no(request: Request, liquid_sample_no: Optional[int]=None, action_dict: dict = {}):
        A = await setupAct(action_dict, request, locals())
        active = await app.base.contain_action(A)
        await active.enqueue_data({'liquid_sample_no': await app.driver.get_liquid_sample_no(**A.action_params)})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post("/shutdown")
    def post_shutdown():
        shutdown_event()


    @app.on_event("shutdown")
    def shutdown_event():
        return ""

    return app
