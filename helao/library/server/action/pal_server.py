__all__ = ["makeApp"]


from importlib import import_module
from socket import gethostname
from time import strftime

from fastapi import Request, Body
from typing import Optional, List

from helaocore.server import makeActionServ, setup_action
from helao.library.driver.pal_driver import PAL
from helao.library.driver.pal_driver import Spacingmethod
from helao.library.driver.pal_driver import PALtools
from helao.library.driver.pal_driver import PalMicroCam
from helao.library.driver.pal_driver import PALposition
from helaocore.model.sample import LiquidSample, SampleUnion
from helaocore.helper import make_str_enum



def makeApp(confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config

    app = makeActionServ(
        config,
        servKey,
        servKey,
        "PAL Autosampler Server",
        version=2.0,
        driver_class=PAL,
    )


    _cams = app.server_params.get("cams",dict())
    #_camsitems = make_str_enum("cams",{key:key for key in _cams.keys()})

    if "positions" in app.server_params:
        dev_custom = app.server_params["positions"].get("custom",dict())
    else:
        dev_custom = dict()
    dev_customitems = make_str_enum("dev_custom",{key:key for key in dev_custom.keys()})


    @app.post(f"/{servKey}/convert_v1DB")
    async def convert_v1DB(request: Request):
        # await app.driver.convert_oldDB_to_sqllite()
        await app.driver.unified_db.liquidAPI.old_jsondb_to_sqlitedb()
        return {}


    if _cams:
        @app.post(f"/{servKey}/PAL_run_method")
        async def PAL_run_method(
            request: Request,
            micropal: Optional[list] = [
                PalMicroCam(**{
                "method":"fillfixed",
                "tool":"LS3",
                "volume_ul":500,
                "requested_source":PALposition(**{
                    "position":"elec_res1",
                    "tray":None,
                    "slot":None,
                    "vial":None,
                    }),
                "requested_dest":PALposition(**{
                    "position":"lcfc_res",
                    "tray":None,
                    "slot":None,
                    "vial":None,
                    }),
                "wash1":0,
                "wash2":0,
                "wash3":0,
                "wash4":0,
                }),
                PalMicroCam(**{
                "method":"fillfixed",
                "tool":"LS3",
                "volume_ul":500,
                "requested_source":PALposition(**{
                    "position":"elec_res1",
                    "tray":None,
                    "slot":None,
                    "vial":None,
                    }),
                "requested_dest":PALposition(**{
                    "position":"lcfc_res",
                    "tray":None,
                    "slot":None,
                    "vial":None,
                    }),
                "wash1":0,
                "wash2":0,
                "wash3":0,
                "wash4":0,
                }),
                ],
            totalruns: Optional[int] = 1,
            # its a necessary param, but as its the only dict, it partially breaks swagger
            sampleperiod: Optional[List[float]] = [0.0],
            spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
            spacingfactor: Optional[float] = 1.0,
            timeoffset: Optional[float] = 0.0,
        ):
            """universal pal action"""
            A = await setup_action(request)
            active_dict = await app.driver.method_arbitrary(A)
            return active_dict


    if "archive" in _cams:
        @app.post(f"/{servKey}/PAL_archive")
        async def PAL_archive(
            request: Request,
            tool: Optional[PALtools] = None,
            source: Optional[dev_customitems] = None,
            volume_ul: Optional[int] = 200,
            sampleperiod: Optional[List[float]] =  Body([0.0], embed=True),
            spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
            spacingfactor: Optional[float] = 1.0,
            timeoffset: Optional[float] = 0.0,
            wash1: Optional[bool] = False,
            wash2: Optional[bool] = False,
            wash3: Optional[bool] = False,
            wash4: Optional[bool] = False,
        ):
            A = await setup_action(request)
            A.action_abbr = "archive"
            active_dict = await app.driver.method_archive(A)
            return active_dict


    if "fill" in _cams:
        @app.post(f"/{servKey}/PAL_fill")
        async def PAL_fill(
            request: Request,
            tool: Optional[PALtools] = None,
            source: Optional[dev_customitems] = None,
            dest: Optional[dev_customitems] = None,
            volume_ul: Optional[int] = 200,
            wash1: Optional[bool] = False,
            wash2: Optional[bool] = False,
            wash3: Optional[bool] = False,
            wash4: Optional[bool] = False,
        ):
            A = await setup_action(request)
            A.action_abbr = "fill"
            active_dict = await app.driver.method_fill(A)
            return active_dict


    if "fillfixed" in _cams:
        @app.post(f"/{servKey}/PAL_fillfixed")
        async def PAL_fillfixed(
            request: Request,
            tool: Optional[PALtools] = None,
            source: Optional[dev_customitems] = None,
            dest: Optional[dev_customitems] = None,
            volume_ul: Optional[int] = 200, # this value is only for prc, a fixed value is used
            wash1: Optional[bool] = False,
            wash2: Optional[bool] = False,
            wash3: Optional[bool] = False,
            wash4: Optional[bool] = False,
        ):
            A = await setup_action(request)
            A.action_abbr = "fillfixed"
            active_dict = await app.driver.method_fillfixed(A)
            return active_dict


    if "deepclean" in _cams:
        @app.post(f"/{servKey}/PAL_deepclean")
        async def PAL_deepclean(
            request: Request,
            tool: Optional[PALtools] = None,
            volume_ul: Optional[int] = 200, # this value is only for prc, a fixed value is used
        ):
            A = await setup_action(request)
            A.action_abbr = "deepclean"
            active_dict = await app.driver.method_deepclean(A)
            return active_dict


    if "dilute" in _cams:
        @app.post(f"/{servKey}/PAL_dilute")
        async def PAL_dilute(
            request: Request,
            tool: Optional[PALtools] = None,
            source: Optional[dev_customitems] = None,
            volume_ul: Optional[int] = 200,
            dest_tray: Optional[int] = 0,
            dest_slot: Optional[int] = 0,
            dest_vial: Optional[int] = 0,
            sampleperiod: Optional[List[float]] =  Body([0.0], embed=True),
            spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
            spacingfactor: Optional[float] = 1.0,
            timeoffset: Optional[float] = 0.0,
            wash1: Optional[bool] = True,
            wash2: Optional[bool] = True,
            wash3: Optional[bool] = True,
            wash4: Optional[bool] = True,
        ):
            A = await setup_action(request)
            A.action_abbr = "dilute"
            active_dict = await app.driver.method_dilute(A)
            return active_dict


    if "autodilute" in _cams:
        @app.post(f"/{servKey}/PAL_autodilute")
        async def PAL_autodilute(
            request: Request,
            tool: Optional[PALtools] = None,
            source: Optional[dev_customitems] = None,
            volume_ul: Optional[int] = 200,
            sampleperiod: Optional[List[float]] =  Body([0.0], embed=True),
            spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
            spacingfactor: Optional[float] = 1.0,
            timeoffset: Optional[float] = 0.0,
            wash1: Optional[bool] = True,
            wash2: Optional[bool] = True,
            wash3: Optional[bool] = True,
            wash4: Optional[bool] = True,
        ):
            A = await setup_action(request)
            A.action_abbr = "autodilute"
            active_dict = await app.driver.method_autodilute(A)
            return active_dict


    @app.post(f"/{servKey}/archive_tray_query_sample")
    async def archive_tray_query_sample(request: Request, 
                                      tray: Optional[int] = None,
                                      slot: Optional[int] = None,
                                      vial: Optional[int] = None,
                                     ):
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["sample", "error_code"],
                                          action_abbr = "query_sample"
        )
        error, sample = \
            await app.driver.archive.tray_query_sample(**active.action.action_params)

        await active.append_sample(samples = [sample],
                            IO="in"
                           )
        await active.enqueue_data_dflt(datadict = \
                                       {'sample': sample.as_dict(),
                                        'error_code':error}
                                      )
        active.action.action_params.update({"_fast_sample_in":sample.as_dict()})
        finished_action = await active.finish()
        return finished_action.as_dict()


    @app.post(f"/{servKey}/archive_tray_unloadall")
    async def archive_tray_unloadall(request: Request):
        """Resets app.driver vial table."""
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["unloaded","tray_dict"],
                                          action_abbr = "unload_sample"
        )
        unloaded, sample_in, sample_out, tray_dict = \
            await app.driver.archive.tray_unloadall(**active.action.action_params)
        await active.append_sample(
              samples = sample_in,
              IO="in")
        await active.append_sample(
              samples = sample_out,
              IO="out")
        await active.enqueue_data_dflt(datadict = \
                                       {"unloaded": unloaded,
                                        "tray_dict": tray_dict})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/archive_tray_unload")
    async def archive_tray_unload(
                                  request: Request,
                                  tray: Optional[int] = None, 
                                  slot: Optional[int] = None
                                 ):
        """Resets app.driver vial table."""
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["unloaded","tray_dict"],
                                          action_abbr = "unload_sample"
        )
        unloaded, sample_in, sample_out, tray_dict = \
            await app.driver.archive.tray_unload(**active.action.action_params)
        await active.append_sample(
              samples = sample_in,
              IO="in")
        await active.append_sample(
              samples = sample_out,
              IO="out")
        await active.enqueue_data_dflt(datadict = \
                                       {"unloaded": unloaded,
                                        "tray_dict": tray_dict})
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
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["tray", "slot", "vial"],
                                          # action_abbr = ""
        )
        await active.enqueue_data_dflt(datadict = \
                                       await app.driver.archive.tray_new_position(**active.action.action_params)
                                       )
        finished_action = await active.finish()
        return finished_action.as_dict()


    @app.post(f"/{servKey}/archive_tray_update_position")
    async def archive_tray_update_position(
        request: Request, 
        sample: Optional[SampleUnion] = Body(LiquidSample(**{"sample_no":1,"machine_name":gethostname()}), embed=True),
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
    ):
        """Updates app.driver vial Table. If sucessful (vial-slot was empty) returns True, else it returns False."""
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["update"],
                                          # action_abbr = ""
        )
        await active.enqueue_data_dflt(datadict = \
                                       {"update": await app.driver.archive.tray_update_position(**active.action.action_params),
                                       })
        finished_action = await active.finish()
        return finished_action.as_dict()


    @app.post(f"/{servKey}/archive_tray_export_json")
    async def archive_tray_export_json(
        request: Request, 
        tray: Optional[int] = None, 
        slot: Optional[int] = None
    ):
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = app.driver.archive.tray_get_keys(),
                                          action_abbr = "traytojson",
                                          file_type="palvialtable_helao__file",
        )
        await active.enqueue_data_dflt(datadict = \
                                       await app.driver.archive.tray_export_json(**active.action.action_params)
                                       )
        finished_action = await active.finish()
        return finished_action.as_dict()


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
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          action_abbr = "traytoicpms",
        )
        await app.driver.archive.tray_export_icpms(
             tray = tray,
             slot = slot,
             myactive = active,
             survey_runs = active.action.action_params.get("survey_runs", None),
             main_runs = active.action.action_params.get("main_runs", None),
             rack = active.action.action_params.get("rack", None),
             dilution_factor = active.action.action_params.get("dilution_factor", None),
        )
        finished_action = await active.finish()
        return finished_action.as_dict()


    @app.post(f"/{servKey}/archive_tray_export_csv")
    async def archive_tray_export_csv(
        request: Request, 
        tray: Optional[int] = None,
        slot: Optional[int] = None
    ):
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          action_abbr = "traytocsv",
        )

        await app.driver.archive.tray_export_csv(
            tray = active.action.action_params.get("tray", None), 
            slot = active.action.action_params.get("slot", None),
            myactive = active
        )
        finished_action = await active.finish()
        return finished_action.as_dict()


    @app.post(f"/{servKey}/archive_custom_load")
    async def archive_custom_load(
                                  request: Request,
                                  custom: Optional[dev_customitems] = None,
                                  load_sample_in: Optional[SampleUnion] = Body(LiquidSample(**{"sample_no":1,"machine_name":gethostname()}), embed=True),
                                 ):
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["loaded","customs_dict"],
                                          action_abbr = "load_sample",
        )
        loaded, loaded_sample, customs_dict = await app.driver.archive.custom_load(**active.action.action_params)
        if loaded:
            await active.append_sample(samples = [loaded_sample],
                                IO="in"
                               )
        await active.enqueue_data_dflt(datadict = \
                                       {"loaded":loaded,
                                        "customs_dict": customs_dict})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/archive_custom_unload")
    async def archive_custom_unload(
                                    request: Request,
                                    custom: Optional[dev_customitems] = None,
                                   ):
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["unloaded","customs_dict"],
                                          action_abbr = "unload_sample",
        )
        unloaded, sample_in, sample_out, customs_dict = \
            await app.driver.archive.custom_unload(**active.action.action_params)
        await active.append_sample(
              samples = sample_in,
              IO="in")
        await active.append_sample(
              samples = sample_out,
              IO="out")
        await active.enqueue_data_dflt(datadict = \
                                       {"unloaded": unloaded,
                                        "customs_dict": customs_dict})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/archive_custom_unloadall")
    async def archive_custom_unloadall(request: Request):
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["unloaded","customs_dict"],
                                          action_abbr = "unload_sample",
        )
        unloaded, sample_in, sample_out, customs_dict = \
            await app.driver.archive.custom_unloadall(**active.action.action_params)
        await active.append_sample(
              samples = sample_in,
              IO="in")
        await active.append_sample(
              samples = sample_out,
              IO="out")
        await active.enqueue_data_dflt(datadict = \
                                       {"unloaded": unloaded,
                                        "customs_dict": customs_dict})
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/archive_custom_query_sample")
    async def archive_custom_query_sample(request: Request, 
                                        custom: Optional[dev_customitems] = None,
                                       ):
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["sample", "error_code"],
                                          action_abbr = "query_sample",
        )
        error, sample = \
            await app.driver.archive.custom_query_sample(**active.action.action_params)
        await active.append_sample(samples = [sample],
                            IO="in"
                           )
        await active.enqueue_data_dflt(datadict = \
                                       {"sample": sample.as_dict(),
                                        "error_code":error})
        active.action.action_params.update({"_fast_sample_in":sample.as_dict()})
        finished_action = await active.finish()
        return finished_action.as_dict()


    @app.post(f"/{servKey}/db_get_sample")
    async def db_get_sample(request: Request, 
                         fast_samples_in: Optional[List[SampleUnion]] = \
           Body([LiquidSample(**{"sample_no":1,"machine_name":gethostname()})], embed=True),
                        ):
        """Positive sample_no will get it from the beginng, negative
        from the end of the db."""
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["sample"],
        )
        sample = await app.driver.db_get_sample(active.action.samples_in)
        await active.enqueue_data_dflt(datadict = \
                                       {'sample': sample.as_dict()})
        finished_action = await active.finish()
        return finished_action.as_dict()


    @app.post(f"/{servKey}/db_new_sample")
    async def db_new_sample(request: Request, 
                         fast_samples_in: Optional[List[SampleUnion]] = Body([LiquidSample(**{
                                              "machine_name":gethostname(),
                                              "source": [],
                                              "volume_ml": 0.0,
                                              "action_time": strftime("%Y%m%d.%H%M%S"),
                                              "chemical": [],
                                              "mass": [],
                                              "supplier": [],
                                              "lot_number": [],
                             })], embed=True),
                        ):
        """use CAS for chemical if available. 
        Written on bottles of chemicals with all other necessary information.
        For empty DUID and AUID the UID will automatically created. 
        For manual entry leave DUID, AUID, action_time, 
        and action_params empty and servkey on "data".
        If its the very first liquid (no source in database exists) 
        leave source and source_ml empty."""
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["sample"],
        )
        sample = await app.driver.db_new_sample(active.action.samples_in)
        await active.enqueue_data_dflt(datadict = \
                                       {'sample': sample.as_dict()})
        finished_action = await active.finish()
        return finished_action.as_dict()


    @app.post("/shutdown")
    def post_shutdown():
        shutdown_event()


    @app.on_event("shutdown")
    def shutdown_event():
        return ""

    return app
