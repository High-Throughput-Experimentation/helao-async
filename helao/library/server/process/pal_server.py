
__all__ = ["makeApp"]


from importlib import import_module
from socket import gethostname
from time import strftime

from fastapi import Request
from typing import Optional, List

from helaocore.server import make_process_serv, setup_process
from helao.library.driver.pal_driver import cPAL
from helao.library.driver.pal_driver import Spacingmethod
from helao.library.driver.pal_driver import PALtools
from helao.library.driver.pal_driver import MicroPalParams
from helao.library.driver.pal_driver import PAL_position
import helaocore.model.sample as hcms
from helaocore.helper import make_str_enum



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


    _cams = app.server_params.get("cams",dict())
    #_camsitems = make_str_enum("cams",{key:key for key in _cams.keys()})

    if "positions" in app.server_params:
        dev_custom = app.server_params["positions"].get("custom",dict())
    else:
        dev_custom = dict()
    dev_customitems = make_str_enum("dev_custom",{key:key for key in dev_custom.keys()})


    @app.post(f"/{servKey}/convert_DB")
    async def convert_DB(request: Request):
        await app.driver.convert_oldDB_to_sqllite()
        return {}

    if _cams:
        @app.post(f"/{servKey}/PAL_run_method")
        async def PAL_run_method(
            request: Request,
            micropal: Optional[list] = [
                MicroPalParams(**{
                "PAL_method":"fillfixed",
                "PAL_tool":"LS3",
                "PAL_volume_uL":500,
                "PAL_requested_source":PAL_position(**{
                    "position":"elec_res1",
                    "tray":None,
                    "slot":None,
                    "vial":None,
                    }),
                "PAL_requested_dest":PAL_position(**{
                    "position":"lcfc_res",
                    "tray":None,
                    "slot":None,
                    "vial":None,
                    }),
                "PAL_wash1":0,
                "PAL_wash2":0,
                "PAL_wash3":0,
                "PAL_wash4":0,
                }),
                MicroPalParams(**{
                "PAL_method":"fillfixed",
                "PAL_tool":"LS3",
                "PAL_volume_uL":500,
                "PAL_requested_source":PAL_position(**{
                    "position":"elec_res1",
                    "tray":None,
                    "slot":None,
                    "vial":None,
                    }),
                "PAL_requested_dest":PAL_position(**{
                    "position":"lcfc_res",
                    "tray":None,
                    "slot":None,
                    "vial":None,
                    }),
                "PAL_wash1":0,
                "PAL_wash2":0,
                "PAL_wash3":0,
                "PAL_wash4":0,
                }),
                ],
            PAL_totalruns: Optional[int] = 1,
            # its a necessary param, but as its the only dict, it partially breaks swagger
            PAL_sampleperiod: Optional[List[float]] = [0.0],
            PAL_spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
            PAL_spacingfactor: Optional[float] = 1.0,
            PAL_timeoffset: Optional[float] = 0.0,
            # scratch: Optional[List[None]] = [None], # temp fix so swagger still works
        ):
            """universal pal process"""
            A = await setup_process(request)
            active_dict = await app.driver.init_PAL_IOloop(A)
            return active_dict


    if "archive" in _cams:
        @app.post(f"/{servKey}/PAL_archive")
        async def PAL_archive(
            request: Request,
            micropal: Optional[list] = [
                MicroPalParams(**{
                "PAL_method":"archive",
                "PAL_tool":"LS3",
                "PAL_volume_uL":500,
                "PAL_requested_source":PAL_position(**{
                    "position":"lcfc_res",
                    }),
                "PAL_wash1":0,
                "PAL_wash2":0,
                "PAL_wash3":0,
                "PAL_wash4":0,
                }),
                ],
            PAL_totalruns: Optional[int] = 1,
            # its a necessary param, but as its the only dict, it partially breaks swagger
            PAL_sampleperiod: Optional[List[float]] = [0.0],
            PAL_spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
            PAL_spacingfactor: Optional[float] = 1.0,
            PAL_timeoffset: Optional[float] = 0.0,
        ):
            A = await setup_process(request)
            active_dict = await app.driver.init_PAL_IOloop(A)
            return active_dict


    if "fill" in _cams:
        @app.post(f"/{servKey}/PAL_fill")
        async def PAL_fill(
            request: Request,
            micropal: Optional[list] = [
                MicroPalParams(**{
                "PAL_method":"fill",
                "PAL_tool":"LS3",
                "PAL_volume_uL":500,
                "PAL_requested_source":PAL_position(**{
                    "position":"elec_res1",
                    }),
                "PAL_requested_dest":PAL_position(**{
                    "position":"lcfc_res",
                    }),
                "PAL_wash1":0,
                "PAL_wash2":0,
                "PAL_wash3":0,
                "PAL_wash4":0,
                }),
                ],
            scratch: Optional[List[None]] = [None], # temp fix so swagger still works
        ):
            """fills eche"""
            A = await setup_process(request)
            active_dict = await app.driver.init_PAL_IOloop(A)
            return active_dict


    if "fillfixed" in _cams:
        @app.post(f"/{servKey}/PAL_fillfixed")
        async def PAL_fillfixed(
            request: Request,
            micropal: Optional[list] = [
                MicroPalParams(**{
                "PAL_method":"fillfixed",
                "PAL_tool":"LS3",
                "PAL_volume_uL":500,
                "PAL_requested_source":PAL_position(**{
                    "position":"elec_res1",
                    }),
                "PAL_requested_dest":PAL_position(**{
                    "position":"lcfc_res",
                    }),
                "PAL_wash1":0,
                "PAL_wash2":0,
                "PAL_wash3":0,
                "PAL_wash4":0,
                }),
                ],
            scratch: Optional[List[None]] = [None], # temp fix so swagger still works
        ):
            """fills eche with hardcoded volume"""
            A = await setup_process(request)
            active_dict = await app.driver.init_PAL_IOloop(A)
            return active_dict


    if "deepclean" in _cams:
        @app.post(f"/{servKey}/PAL_deepclean")
        async def PAL_deepclean(
            request: Request, 
            micropal: Optional[list] = [
                MicroPalParams(**{
                "PAL_method":"deepclean",
                "PAL_tool":"LS3",
                "PAL_volume_uL":500,
                "PAL_wash1":1,
                "PAL_wash2":1,
                "PAL_wash3":1,
                "PAL_wash4":1,
                }),
                ],
            scratch: Optional[List[None]] = [None], # temp fix so swagger still works
        ):
            """cleans the PAL tool"""
            A = await setup_process(request)
            active_dict = await app.driver.init_PAL_IOloop(A)
            return active_dict


    if "dilute" in _cams:
        @app.post(f"/{servKey}/PAL_dilute")
        async def PAL_dilute(
            request: Request, 
            micropal: Optional[list] = [
                MicroPalParams(**{
                "PAL_method":"dilute",
                "PAL_tool":"LS3",
                "PAL_volume_uL":500,
                "PAL_requested_source":PAL_position(**{
                    "position":"elec_res2",
                    }),
                "repeat":1,
                "PAL_wash1":1,
                "PAL_wash2":1,
                "PAL_wash3":1,
                "PAL_wash4":1,
                }),
                ],
            scratch: Optional[List[None]] = [None], # temp fix so swagger still works
        ):
            A = await setup_process(request)
            active_dict = await app.driver.init_PAL_IOloop(A)
            return active_dict


    @app.post(f"/{servKey}/archive_tray_reset")
    async def archive_tray_reset(request: Request):
        """Resets app.driver vial table."""
        A = await setup_process(request)
        active = await app.base.contain_process(A, file_data_keys="trays")
        await active.enqueue_data({"trays": await app.driver.archive.reset_trays(**A.process_params)})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/archive_tray_new_position")
    async def archive_tray_new(
        request: Request, 
        req_vol: Optional[float] = None
    ):
        """Returns an empty vial position for given max volume.\n
        For mixed vial sizes the req_vol helps to choose the proper vial for sample volume.\n
        It will select the first empty vial which has the smallest volume that still can hold req_vol"""
        A = await setup_process(request)
        active = await app.base.contain_process(A, file_data_keys="vial_position")
        await active.enqueue_data({"position": await app.driver.archive.tray_new_position(**A.process_params)})
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/archive_tray_update_position")
    async def archive_tray_update_position(
        request: Request, 
        vial: Optional[int] = None,
        vol_mL: Optional[float] = None,
        liquid_sample_no: Optional[int] = None,
        tray: Optional[int] = None,
        slot: Optional[int] = None
    ):
        """Updates app.driver vial Table. If sucessful (vial-slot was empty) returns True, else it returns False."""
        A = await setup_process(request)
        active = await app.base.contain_process(A, file_data_keys="update")
        await active.enqueue_data({"update": await app.driver.archive.tray_update_position(**A.process_params)})
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/archive_tray_export_json")
    async def archive_tray_export_json(
        request: Request, 
        tray: Optional[int] = None, 
        slot: Optional[int] = None
    ):
        A = await setup_process(request)
        A.process_abbr = "traytojson"
        active = await app.base.contain_process(A,
            file_type="palvialtable_helao__file",
            file_data_keys=["table"],
        )
        await active.enqueue_data({"table": await app.driver.archive.tray_export_json(**A.process_params)})
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/archive_tray_export_icpms")
    async def archive_tray_export_icpms(
        request: Request, 
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        survey_runs: Optional[int] = None,
        main_runs: Optional[int] = None,
        rack: Optional[int] = None,
        dilution_factor: Optional[float] = None
    ):
        A = await setup_process(request)
        A.process_abbr = "traytoicpms"
        active = await app.base.contain_process(A)
        await app.driver.archive.tray_export_icpms(
             tray = tray,
             slot = slot,
             myactive = active,
             survey_runs = A.process_params.get("survey_runs", None),
             main_runs = A.process_params.get("main_runs", None),
             rack = A.process_params.get("rack", None),
             dilution_factor = A.process_params.get("dilution_factor", None),
        )
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/archive_tray_export_csv")
    async def archive_tray_export_csv(
        request: Request, 
        tray: Optional[int] = None,
        slot: Optional[int] = None
    ):
        A = await setup_process(request)
        A.process_abbr = "traytocsv"
        active = await app.base.contain_process(A)
        await app.driver.archive.tray_export_csv(
            tray = A.process_params.get("tray", None), 
            slot = A.process_params.get("slot", None),
            myactive = active
        )
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/archive_load_custom")
    async def archive_load_custom(
                                  request: Request,
                                  custom: Optional[dev_customitems],
                                  # custom: Optional[str] = "",
                                  vol_mL: Optional[float] = 0.0,
                                  load_samples_in: Optional[hcms.SampleList] = hcms.SampleList(samples=[hcms.LiquidSample(**{"sample_no":1,"machine_name":gethostname()})]),
                                  scratch: Optional[List[None]] = [None], # temp fix so swagger still works
                                 ):
        A = await setup_process(request)
        active = await app.base.contain_process(A, file_data_keys="loaded")
        loaded, sample = await app.driver.archive.custom_load(**A.process_params)
        if loaded:
            await active.append_sample(samples = [sample for sample in sample.samples],
                                IO="in"
                               )
        await active.enqueue_data({"loaded":loaded})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/archive_unload_custom")
    async def archive_unload_custom(
                                    request: Request,
                                    custom: Optional[dev_customitems],
                                    # custom: Optional[str] = ""
                                   ):
        A = await setup_process(request)
        active = await app.base.contain_process(A, file_data_keys="unloaded")
        unloaded, sample = await app.driver.archive.custom_unload(**A.process_params)
        if unloaded:
            await active.append_sample(samples = [sample for sample in sample.samples],
                                IO="out"
                               )
        await active.enqueue_data({"unloaded": unloaded})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/archive_unloadall_custom")
    async def archive_unloadall_custom(request: Request):
        A = await setup_process(request)
        active = await app.base.contain_process(A, file_data_keys="unloaded")
        unloaded, sample = await app.driver.archive.custom_unloadall(**A.process_params)
        if unloaded:
            await active.append_sample(samples = [sample for sample in sample.samples],
                                IO="out"
                               )
        await active.enqueue_data({"unloaded": unloaded})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/get_sample")
    async def get_sample(request: Request, 
                         fast_samples_in: Optional[hcms.SampleList] = hcms.SampleList(samples=[hcms.LiquidSample(**{"sample_no":1,"machine_name":gethostname()})]),
                         scratch: Optional[List[None]] = [None], # temp fix so swagger still works
                        ):
        """Positive sample_no will get it from the beginng, negative
        from the end of the db."""
        A = await setup_process(request)
        active = await app.base.contain_process(A, file_data_keys="sample")
        sample = await app.driver.get_sample(A.samples_in)
        await active.enqueue_data({'sample': sample.dict()})
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post(f"/{servKey}/new_sample")
    async def new_sample(request: Request, 
                         fast_samples_in: Optional[hcms.SampleList] = hcms.SampleList(samples=[hcms.LiquidSample(**{
                                              "machine_name":gethostname(),
                                              "source": None,
                                              "volume_ml": 0.0,
                                              "process_time": strftime("%Y%m%d.%H%M%S"),
                                              "chemical": [],
                                              "mass": [],
                                              "supplier": [],
                                              "lot_number": [],                             
                             })]),
                         scratch: Optional[List[None]] = [None], # temp fix so swagger still works
                        ):
        """use CAS for chemical if available. 
        Written on bottles of chemicals with all other necessary information.
        For empty DUID and AUID the UID will automatically created. 
        For manual entry leave DUID, AUID, process_time, 
        and process_params empty and servkey on "data".
        If its the very first liquid (no source in database exists) 
        leave source and source_mL empty."""
        A = await setup_process(request)
        active = await app.base.contain_process(A, file_data_keys="sample")
        sample = await app.driver.new_sample(A.samples_in)
        await active.enqueue_data({'sample': sample.dict()})
        finished_process = await active.finish()
        return finished_process.as_dict()


    @app.post("/shutdown")
    def post_shutdown():
        shutdown_event()


    @app.on_event("shutdown")
    def shutdown_event():
        return ""

    return app
