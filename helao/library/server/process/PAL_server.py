from importlib import import_module
from socket import gethostname
from time import strftime

from helao.core.server import make_process_serv, setup_process
from helao.library.driver.PAL_driver import cPAL
from helao.library.driver.PAL_driver import PALmethods
from helao.library.driver.PAL_driver import Spacingmethod
from helao.library.driver.PAL_driver import PALtools
from helao.core.model import liquid_sample, gas_sample, solid_sample, assembly_sample, sample_list


from fastapi import Request
from typing import Optional, List, Union
import asyncio

def makeApp(confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config

    app = make_process_serv(
        config,
        servKey,
        servKey,
        "PAL Autosampler Server",
        version=2.0,
        driver_class=cPAL,
    )


    @app.post(f"/{servKey}/convert_DB")
    async def convert_DB(request: Request):
        await app.driver.convert_oldDB_to_sqllite()
        return {}


    @app.post(f"/{servKey}/PAL_run_method")
    async def PAL_run_method(
        request: Request, 
        fast_samples_in: Optional[sample_list] = sample_list(samples=[liquid_sample(**{"sample_no":1,"machine_name":gethostname()})]),
        PAL_method: Optional[PALmethods] = PALmethods.fillfixed,
        PAL_tool: Optional[PALtools] = PALtools.LS3,
        PAL_source: Optional[str] = "elec_res1",
        PAL_volume_uL: Optional[int] = 500,  # uL
        PAL_totalvials: Optional[int] = 1,
        # its a necessary param, but as its the only dict, it partially breaks swagger
        PAL_sampleperiod: Optional[List[float]] = [0.0],
        PAL_spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
        PAL_spacingfactor: Optional[float] = 1.0,
        PAL_timeoffset: Optional[float] = 0.0,
        PAL_wash1: Optional[bool] = False,
        PAL_wash2: Optional[bool] = False,
        PAL_wash3: Optional[bool] = False,
        PAL_wash4: Optional[bool] = False,
        scratch: Optional[List[None]] = [None], # temp fix so swagger still works
    ):
        """universal pal process"""
        A = await setup_process(request)
        active_dict = await app.driver.init_PAL_IOloop(A)
        return active_dict


    @app.post(f"/{servKey}/PAL_archive")
    async def PAL_archive(
        request: Request, 
        fast_samples_in: Optional[sample_list] = sample_list(samples=[liquid_sample(**{"sample_no":1,"machine_name":gethostname()})]),
        PAL_tool: Optional[PALtools] = PALtools.LS3,
        PAL_source: Optional[str] = "lcfc_res",
        PAL_volume_uL: Optional[int] = 500,  # uL
        PAL_totalvials: Optional[int] = 1,
        # its a necessary param, but as its the only dict, it partially breaks swagger
        PAL_sampleperiod: Optional[List[float]] = [0.0],
        PAL_spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
        PAL_spacingfactor: Optional[float] = 1.0,
        PAL_timeoffset: Optional[float] = 0.0,
        PAL_wash1: Optional[bool] = False,
        PAL_wash2: Optional[bool] = False,
        PAL_wash3: Optional[bool] = False,
        PAL_wash4: Optional[bool] = False,
        scratch: Optional[List[None]] = [None], # temp fix so swagger still works
    ):
        A = await setup_process(request)
        A.process_params["PAL_method"] =  PALmethods.archive.value
        active_dict = await app.driver.init_PAL_IOloop(A)
        
        return active_dict


    @app.post(f"/{servKey}/PAL_fill")
    async def PAL_fill(
        request: Request, 
        fast_samples_in: Optional[sample_list] = sample_list(samples=[liquid_sample(**{"sample_no":1,"machine_name":gethostname()})]),
        PAL_tool: Optional[PALtools] = PALtools.LS3,
        PAL_source: Optional[str] = "elec_res1",
        PAL_volume_uL: Optional[int] = 500,  # uL
        PAL_wash1: Optional[bool] = False,
        PAL_wash2: Optional[bool] = False,
        PAL_wash3: Optional[bool] = False,
        PAL_wash4: Optional[bool] = False,
        scratch: Optional[List[None]] = [None], # temp fix so swagger still works
    ):
        """fills eche"""
        A = await setup_process(request)
        A.process_params["PAL_method"] =  PALmethods.fill.value
        active_dict = await app.driver.init_PAL_IOloop(A)
        return active_dict


    @app.post(f"/{servKey}/PAL_fillfixed")
    async def PAL_fillfixed(
        request: Request, 
        fast_samples_in: Optional[sample_list] = sample_list(samples=[liquid_sample(**{"sample_no":1,"machine_name":gethostname()})]),
        PAL_tool: Optional[PALtools] = PALtools.LS3,
        PAL_source: Optional[str] = "elec_res1",
        PAL_volume_uL: Optional[int] = 500,  # uL
        PAL_wash1: Optional[bool] = False,
        PAL_wash2: Optional[bool] = False,
        PAL_wash3: Optional[bool] = False,
        PAL_wash4: Optional[bool] = False,
        scratch: Optional[List[None]] = [None], # temp fix so swagger still works
    ):
        """fills eche with hardcoded volume"""
        A = await setup_process(request)
        A.process_params["PAL_method"] =  PALmethods.fillfixed.value
        active_dict = await app.driver.init_PAL_IOloop(A)
        return active_dict


    @app.post(f"/{servKey}/PAL_deepclean")
    async def PAL_deepclean(
        request: Request, 
        PAL_tool: Optional[PALtools] = PALtools.LS3,
        PAL_volume_uL: Optional[int] = 500,  # uL
    ):
        """cleans the PAL tool"""
        A = await setup_process(request)
        A.process_params["PAL_method"] =  PALmethods.deepclean.value
        A.process_params["PAL_wash1"] =  True
        A.process_params["PAL_wash2"] =  True
        A.process_params["PAL_wash3"] =  True
        A.process_params["PAL_wash4"] =  True
        active_dict = await app.driver.init_PAL_IOloop(A)
        return active_dict


    @app.post(f"/{servKey}/PAL_dilute")
    async def PAL_dilute(
        request: Request, 
        fast_samples_in: Optional[sample_list] = sample_list(samples=[liquid_sample(**{"sample_no":1,"machine_name":gethostname()})]),
        PAL_tool: Optional[PALtools] = PALtools.LS3,
        PAL_source: Optional[str] = "elec_res2",
        PAL_volume_uL: Optional[int] = 500,  # uL
        PAL_totalvials: Optional[int] = 1,
        # its a necessary param, but as its the only dict, it partially breaks swagger
        # PAL_sampleperiod: Optional[List[float]] = [0.0],
        # PAL_spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
        # PAL_spacingfactor: Optional[float] = 1.0,
        PAL_timeoffset: Optional[float] = 0.0,
        PAL_wash1: Optional[bool] = False,
        PAL_wash2: Optional[bool] = False,
        PAL_wash3: Optional[bool] = False,
        PAL_wash4: Optional[bool] = False,
        scratch: Optional[List[None]] = [None], # temp fix so swagger still works
    ):
        A = await setup_process(request)
        A.process_params["PAL_method"] =  PALmethods.dilute.value
        active_dict = await app.driver.init_PAL_IOloop(A)
        return active_dict


    @app.post(f"/{servKey}/trayDB_reset")
    async def trayDB_reset(request: Request):
        """Resets app.driver vial table. But will make a full dump to CSV first."""
        A = await setup_process(request)
        finished_process = await app.driver.trayDB_reset(A)
        return finished_process.as_dict()


    @app.post(f"/{servKey}/trayDB_new")
    async def trayDB_new(
        request: Request, 
        req_vol: Optional[float] = None
    ):
        """Returns an empty vial position for given max volume.\n
        For mixed vial sizes the req_vol helps to choose the proper vial for sample volume.\n
        It will select the first empty vial which has the smallest volume that still can hold req_vol"""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data({"vial_position": await app.driver.trayDB_new(**A.process_params)})
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/trayDB_update")
    async def trayDB_update(
        request: Request, 
        vial: Optional[int] = None,
        vol_mL: Optional[float] = None,
        liquid_sample_no: Optional[int] = None,
        tray: Optional[int] = None,
        slot: Optional[int] = None
    ):
        """Updates app.driver vial Table. If sucessful (vial-slot was empty) returns True, else it returns False."""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data({"update": await app.driver.trayDB_update(**A.process_params)})
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/trayDB_get_db")
    async def trayDB_get_db(
        request: Request, 
        tray: Optional[int] = None, 
        slot: Optional[int] = None
    ):
        A = await setup_process(request)
        finished_process = await app.driver.trayDB_get_db(A)
        return finished_process.as_dict()


    @app.post(f"/{servKey}/trayDB_export_icpms")
    async def trayDB_export_icpms(
        request: Request, 
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        survey_runs: Optional[int] = None,
        main_runs: Optional[int] = None,
        rack: Optional[int] = None,
        dilution_factor: Optional[float] = None
    ):
        A = await setup_process(request)
        A.process_abbr = "export"
        A.process_params["icpms"] = True
        finished_process = await app.driver.trayDB_get_db(A)
        return finished_process.as_dict()


    @app.post(f"/{servKey}/trayDB_export_csv")
    async def trayDB_export_csv(
        request: Request, 
        tray: Optional[int] = None,
        slot: Optional[int] = None
    ):
        A = await setup_process(request)
        A.process_abbr = "export"
        A.process_params["csv"] = True # signal subroutine to create a csv
        finished_process = await app.driver.trayDB_get_db(A)
        return finished_process.as_dict()


    # @app.post(f"/{servKey}/liquid_sample_no_create_new")
    # async def liquid_sample_no_create_new(request: Request, 
    #                                       sample: Optional[liquid_sample] = liquid_sample(**{
    #                                           "machine_name":gethostname(),
    #                                           "source": None,
    #                                           "volume_mL": 0.0,
    #                                           "process_time": strftime("%Y%m%d.%H%M%S"),
    #                                           "chemical": [],
    #                                           "mass": [],
    #                                           "supplier": [],
    #                                           "lot_number": [],
    #                                           }),
    #                                       scratch: Optional[List[None]] = [None], # temp fix so swagger still works
    # ):
    #     '''use CAS for chemical if available. Written on bottles of chemicals with all other necessary information.\n
    #     For empty DUID and AUID the UID will automatically created. For manual entry leave DUID, AUID, process_time, and process_params empty and servkey on "data".\n
    #     If its the very first liquid (no source in database exists) leave source and source_mL empty.'''
    #     A = await setup_process(request)
    #     active = await app.base.contain_process(A)
    #     A.process_params["DUID"] = A.decision_uuid
    #     A.process_params["AUID"] = A.process_uuid
        
    #     sample = await app.driver.liquid_sample_no_create_new(sample)
    #     await active.enqueue_data({'liquid_sample': sample.dict()})
    #     finished_process = await active.finish()
    #     return finished_process.as_dict()


    @app.post(f"/{servKey}/liquid_sample_no_get_last")
    async def liquid_sample_no_get_last(request: Request):
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        sample = await app.driver.liquid_sample_no_get_last()
        await active.enqueue_data({'liquid_sample': sample.dict()})
        finished_process = await active.finish()
        return finished_process.as_dict()


    # @app.post(f"/{servKey}/liquid_sample_no_get")
    # async def liquid_sample_no_get(request: Request, 
    #                                fast_samples_in: Optional[sample_list] = sample_list(samples=[liquid_sample(**{"sample_no":1,"machine_name":gethostname()})]),
    #                                scratch: Optional[List[None]] = [None], # temp fix so swagger still works
    #                                ):
    #     A = await setup_process(request)
    #     active = await app.base.contain_process(A)
    #     sample = await app.driver.liquid_sample_no_get(sample)
    #     await active.enqueue_data({'liquid_sample': sample.dict()})
    #     finished_process = await active.finish()
    #     return finished_process.as_dict()


    @app.post("/shutdown")
    def post_shutdown():
        shutdown_event()


    @app.on_event("shutdown")
    def shutdown_event():
        return ""

    return app
