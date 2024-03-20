__all__ = ["makeApp"]


from socket import gethostname
from time import strftime

from fastapi import Body, Query
from typing import Optional, List, Union

from helao.servers.base_api import BaseAPI
from helao.drivers.robot.pal_driver import (
    PAL,
    Spacingmethod,
    PALtools,
    PalMicroCam,
    PALposition,
    GCsampletype,
    # SampleInheritance,
    # SampleStatus,
)
from helao.drivers.data.archive_driver import ScanDirection, ScanOperator

from helaocore.models.sample import (
    SampleType,
    LiquidSample,
    SampleUnion,
    NoneSample,
    SolidSample,
)
from helaocore.models.data import DataModel
from helao.helpers.make_str_enum import make_str_enum
from helao.helpers.premodels import Action
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, server_key, helao_root):
    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config,
        server_key,
        server_key,
        "PAL Autosampler Server",
        version=2.0,
        driver_class=PAL,
    )

    _cams = app.server_params.get("cams", {})
    # _camsitems = make_str_enum("cams",{key:key for key in _cams.keys()})
    # app.base.print_message(_cams)

    if "positions" in app.server_params:
        dev_custom = app.server_params["positions"].get("custom", {})
    else:
        dev_custom = {}
    dev_customitems = make_str_enum(
        "dev_custom", {key: key for key in dev_custom.keys()}
    )

    @app.post(f"/{server_key}/stop", tags=["action"])
    async def stop(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Stops measurement in a controlled way."""
        active = await app.base.setup_and_contain_action(action_abbr="stop")
        await active.enqueue_data_dflt(datadict={"stop": await app.driver.stop()})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/kill_PAL", tags=["action"])
    async def kill_PAL(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        active = await app.base.setup_and_contain_action()
        error_code = await app.driver.kill_PAL()
        active.action.error_code = error_code
        await active.enqueue_data_dflt(datadict={"error_code": error_code})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/convert_v1DB", tags=["action"])
    async def convert_v1DB(action: Action = Body({}, embed=True)):
        # await app.driver.convert_oldDB_to_sqllite()
        await app.driver.archive.unified_db.liquidAPI.old_jsondb_to_sqlitedb()
        return {}

    if _cams:

        @app.post(f"/{server_key}/PAL_run_method", tags=["action"])
        async def PAL_run_method(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            micropal: list = [
                PalMicroCam(
                    **{
                        "method": "fillfixed",
                        "tool": "LS3",
                        "volume_ul": 500,
                        "requested_source": PALposition(
                            **{
                                "position": "elec_res1",
                                "tray": None,
                                "slot": None,
                                "vial": None,
                            }
                        ),
                        "requested_dest": PALposition(
                            **{
                                "position": "lcfc_res",
                                "tray": None,
                                "slot": None,
                                "vial": None,
                            }
                        ),
                        "wash1": 0,
                        "wash2": 0,
                        "wash3": 0,
                        "wash4": 0,
                    }
                ),
                PalMicroCam(
                    **{
                        "method": "fillfixed",
                        "tool": "LS3",
                        "volume_ul": 500,
                        "requested_source": PALposition(
                            **{
                                "position": "elec_res1",
                                "tray": None,
                                "slot": None,
                                "vial": None,
                            }
                        ),
                        "requested_dest": PALposition(
                            **{
                                "position": "lcfc_res",
                                "tray": None,
                                "slot": None,
                                "vial": None,
                            }
                        ),
                        "wash1": 0,
                        "wash2": 0,
                        "wash3": 0,
                        "wash4": 0,
                    }
                ),
            ],
            totalruns: int = 1,
            # its a necessary param, but as its the only dict, it partially breaks swagger
            sampleperiod: List[float] = [0.0],
            spacingmethod: Spacingmethod = Spacingmethod.linear,
            spacingfactor: float = 1.0,
            timeoffset: float = 0.0,
        ):
            """universal pal action"""
            A = app.base.setup_action()
            active_dict = await app.driver.method_arbitrary(A)
            return active_dict

    if (
        "injection_custom_GC_liquid_start" in _cams
        or "injection_custom_GC_liquid_wait" in _cams
        or "injection_custom_GC_gas_start" in _cams
        or "injection_custom_GC_gas_wait" in _cams
        and "archive"
    ):

        @app.post(f"/{server_key}/PAL_ANEC_aliquot", tags=["action"])
        async def PAL_ANEC_aliquot(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            toolGC: PALtools = PALtools.HS2,
            toolarchive: PALtools = PALtools.LS3,
            source: dev_customitems = "cell1_we",
            volume_ul_GC: int = 300,
            volume_ul_archive: int = 500,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            A = app.base.setup_action()
            A.action_abbr = "GC_injection"
            active_dict = await app.driver.method_ANEC_aliquot(A)
            return active_dict

    if (
        "injection_custom_GC_liquid_start" in _cams
        or "injection_custom_GC_liquid_wait" in _cams
        or "injection_custom_GC_gas_start" in _cams
        or "injection_custom_GC_gas_wait" in _cams
    ):

        @app.post(f"/{server_key}/PAL_ANEC_GC", tags=["action"])
        async def PAL_ANEC_GC(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            toolGC: PALtools = PALtools.HS2,
            source: dev_customitems = "cell1_we",
            volume_ul_GC: int = 300,
        ):
            A = app.base.setup_action()
            A.action_abbr = "GC_injection"
            active_dict = await app.driver.method_ANEC_GC(A)
            return active_dict

    if (
        "injection_tray_GC_liquid_start" in _cams
        or "injection_tray_GC_liquid_wait" in _cams
        or "injection_tray_GC_gas_start" in _cams
        or "injection_tray_GC_gas_wait" in _cams
    ):

        @app.post(f"/{server_key}/PAL_injection_tray_GC", tags=["action"])
        async def PAL_injection_tray_GC(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            startGC: bool = True,
            sampletype: GCsampletype = "liquid",
            tool: PALtools = PALtools.LS1,
            source_tray: int = 1,
            source_slot: int = 1,
            source_vial: int = 1,
            dest: dev_customitems = None,
            volume_ul: int = 2,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            A = app.base.setup_action()
            A.action_abbr = "GC_injection"
            active_dict = await app.driver.method_injection_tray_GC(A)
            return active_dict

    if (
        "injection_custom_GC_liquid_start" in _cams
        or "injection_custom_GC_liquid_wait" in _cams
        or "injection_custom_GC_gas_start" in _cams
        or "injection_custom_GC_gas_wait" in _cams
    ):

        @app.post(f"/{server_key}/PAL_injection_custom_GC", tags=["action"])
        async def PAL_injection_custom_GC(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            startGC: bool = None,
            sampletype: GCsampletype = None,
            tool: PALtools = None,
            source: dev_customitems = None,
            dest: dev_customitems = None,
            volume_ul: int = 2,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            A = app.base.setup_action()
            A.action_abbr = "GC_injection"
            active_dict = await app.driver.method_injection_custom_GC(A)
            return active_dict

    if "injection_custom_HPLC" in _cams:

        @app.post(f"/{server_key}/PAL_injection_custom_HPLC", tags=["action"])
        async def PAL_injection_custom_HPLC(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            tool: PALtools = None,
            source: dev_customitems = None,
            dest: dev_customitems = None,
            volume_ul: int = 2,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            A = app.base.setup_action()
            A.action_abbr = "HPLC_injection"
            active_dict = await app.driver.method_injection_custom_HPLC(A)
            return active_dict

    if "injection_tray_HPLC" in _cams:

        @app.post(f"/{server_key}/PAL_injection_tray_HPLC", tags=["action"])
        async def PAL_injection_tray_HPLC(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            tool: PALtools = PALtools.LS1,
            source_tray: int = 1,
            source_slot: int = 1,
            source_vial: int = 1,
            dest: dev_customitems = None,
            volume_ul: int = 25,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            A = app.base.setup_action()
            A.action_abbr = "HPLC_injection"
            active_dict = await app.driver.method_injection_tray_HPLC(A)
            return active_dict

    #    if "transfer_tray_tray" in _cams:
    if "transfer_tray_tray" in _cams:

        @app.post(f"/{server_key}/PAL_transfer_tray_tray", tags=["action"])
        async def PAL_transfer_tray_tray(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            sampleperiod: List[float] = Body([0.0], embed=True),
            spacingmethod: Spacingmethod = Spacingmethod.linear,
            spacingfactor: float = 1.0,
            timeoffset: float = 0.0,
            tool: PALtools = None,
            volume_ul: int = 2,
            source_tray: int = 1,
            source_slot: int = 1,
            source_vial: int = 1,
            dest_tray: int = 1,
            dest_slot: int = 1,
            dest_vial: int = 1,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            A = app.base.setup_action()
            A.action_abbr = "transfer"
            active_dict = await app.driver.method_transfer_tray_tray(A)
            return active_dict

    #    if "transfer_tray_custom" in _cams:
    if "transfer_tray_custom" in _cams:

        @app.post(f"/{server_key}/PAL_transfer_tray_custom", tags=["action"])
        async def PAL_transfer_tray_custom(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            sampleperiod: List[float] = Body([0.0], embed=True),
            spacingmethod: Spacingmethod = Spacingmethod.linear,
            spacingfactor: float = 1.0,
            timeoffset: float = 0.0,
            tool: PALtools = None,
            volume_ul: int = 2,
            source_tray: int = 1,
            source_slot: int = 1,
            source_vial: int = 1,
            dest: dev_customitems = None,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            A = app.base.setup_action()
            A.action_abbr = "transfer"
            active_dict = await app.driver.method_transfer_tray_custom(A)
            return active_dict

    #    if "transfer_custom_tray" in _cams:
    if "transfer_custom_tray" in _cams:

        @app.post(f"/{server_key}/PAL_transfer_custom_tray", tags=["action"])
        async def PAL_transfer_custom_tray(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            sampleperiod: List[float] = Body([0.0], embed=True),
            spacingmethod: Spacingmethod = Spacingmethod.linear,
            spacingfactor: float = 1.0,
            timeoffset: float = 0.0,
            tool: PALtools = None,
            volume_ul: int = 2,
            source: dev_customitems = None,
            dest_tray: int = 1,
            dest_slot: int = 1,
            dest_vial: int = 1,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            A = app.base.setup_action()
            A.action_abbr = "transfer"
            active_dict = await app.driver.method_transfer_custom_tray(A)
            return active_dict

    if "transfer_custom_custom" in _cams:

        @app.post(f"/{server_key}/PAL_transfer_custom_custom", tags=["action"])
        async def PAL_transfer_custom_custom(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            sampleperiod: List[float] = Body([0.0], embed=True),
            spacingmethod: Spacingmethod = Spacingmethod.linear,
            spacingfactor: float = 1.0,
            timeoffset: float = 0.0,
            tool: PALtools = None,
            volume_ul: int = 2,
            source: dev_customitems = None,
            dest: dev_customitems = None,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            A = app.base.setup_action()
            A.action_abbr = "transfer"
            active_dict = await app.driver.method_transfer_custom_custom(A)
            return active_dict

    if "archive" in _cams:

        @app.post(f"/{server_key}/PAL_archive", tags=["action"])
        async def PAL_archive(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            tool: PALtools = None,
            source: dev_customitems = None,
            volume_ul: int = 200,
            sampleperiod: List[float] = Body([0], embed=True),
            spacingmethod: Spacingmethod = Spacingmethod.linear,
            spacingfactor: float = 1.0,
            timeoffset: float = 0.0,
            wash1: bool = False,
            wash2: bool = False,
            wash3: bool = False,
            wash4: bool = False,
        ):
            A = app.base.setup_action()
            A.action_abbr = "archive"
            active_dict = await app.driver.method_archive(A)
            return active_dict

    # if "fill" in _cams:
    #     @app.post(f"/{server_key}/PAL_fill", tags=["action"])
    #     async def PAL_fill(
    #         action: Action = \
    #                 Body({}, embed=True),
    #         tool: PALtools = None,
    #         source: dev_customitems = None,
    #         dest: dev_customitems = None,
    #         volume_ul: int = 200,
    #         wash1: bool = False,
    #         wash2: bool = False,
    #         wash3: bool = False,
    #         wash4: bool = False,
    #     ):
    #         A =  app.base.setup_action()
    #         A.action_abbr = "fill"
    #         active_dict = await app.driver.method_fill(A)
    #         return active_dict

    # if "fillfixed" in _cams:
    #     @app.post(f"/{server_key}/PAL_fillfixed", tags=["action"])
    #     async def PAL_fillfixed(
    #         action: Action = \
    #                 Body({}, embed=True),
    #         tool: PALtools = None,
    #         source: dev_customitems = None,
    #         dest: dev_customitems = None,
    #         volume_ul: int = 200, # this value is only for exp, a fixed value is used
    #         wash1: bool = False,
    #         wash2: bool = False,
    #         wash3: bool = False,
    #         wash4: bool = False,
    #     ):
    #         A =  app.base.setup_action()
    #         A.action_abbr = "fillfixed"
    #         active_dict = await app.driver.method_fillfixed(A)
    #         return active_dict

    if "deepclean" in _cams:

        @app.post(f"/{server_key}/PAL_deepclean", tags=["action"])
        async def PAL_deepclean(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            tool: PALtools = None,
            volume_ul: Optional[
                int
            ] = 200,  # this value is only for exp, a fixed value is used
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = True,
        ):
            A = app.base.setup_action()
            A.action_abbr = "deepclean"
            active_dict = await app.driver.method_deepclean(A)
            return active_dict

    if "dilute" in _cams:

        @app.post(f"/{server_key}/PAL_dilute", tags=["action"])
        async def PAL_dilute(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            tool: PALtools = None,
            source: dev_customitems = None,
            volume_ul: int = 200,
            dest_tray: int = 0,
            dest_slot: int = 0,
            dest_vial: int = 0,
            sampleperiod: List[float] = Body([0.0], embed=True),
            spacingmethod: Spacingmethod = Spacingmethod.linear,
            spacingfactor: float = 1.0,
            timeoffset: float = 0.0,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = True,
        ):
            A = app.base.setup_action()
            A.action_abbr = "dilute"
            active_dict = await app.driver.method_dilute(A)
            return active_dict

    if "autodilute" in _cams:

        @app.post(f"/{server_key}/PAL_autodilute", tags=["action"])
        async def PAL_autodilute(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            tool: PALtools = None,
            source: dev_customitems = None,
            volume_ul: int = 200,
            sampleperiod: List[float] = Body([0.0], embed=True),
            spacingmethod: Spacingmethod = Spacingmethod.linear,
            spacingfactor: float = 1.0,
            timeoffset: float = 0.0,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = True,
        ):
            A = app.base.setup_action()
            A.action_abbr = "autodilute"
            active_dict = await app.driver.method_autodilute(A)
            return active_dict

    @app.post(f"/{server_key}/archive_tray_query_sample", tags=["action"])
    async def archive_tray_query_sample(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        tray: int = None,
        slot: int = None,
        vial: int = None,
    ):
        active = await app.base.setup_and_contain_action(action_abbr="query_sample")
        error_code, sample = await app.driver.archive.tray_query_sample(
            **active.action.action_params
        )
        active.action.error_code = error_code
        await active.append_sample(samples=[sample], IO="in")
        datadict = {"sample": sample.as_dict(), "error_code": error_code}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.action.action_params.update({"_fast_samples_in": [sample.as_dict()]})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_tray_unloadall", tags=["action"])
    async def archive_tray_unloadall(action: Action = Body({}, embed=True)):
        """Resets app.driver vial table."""
        active = await app.base.setup_and_contain_action(action_abbr="unload_sample")
        (
            unloaded,
            samples_in,
            samples_out,
            tray_dict,
        ) = await app.driver.archive.tray_unloadall(**active.action.action_params)
        await active.append_sample(samples=samples_in, IO="in")
        await active.append_sample(samples=samples_out, IO="out")
        datadict = {"unloaded": unloaded, "tray_dict": tray_dict}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/archive_tray_load", tags=["action"])
    async def archive_tray_load(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        load_sample_in: Union[SampleUnion, dict] = Body(
            LiquidSample(**{"sample_no": 1, "machine_name": gethostname().lower()}),
            embed=True,
        ),
        tray: int = None,
        slot: int = None,
        vial: int = None,
    ):
        active = await app.base.setup_and_contain_action(
            action_abbr="load_sample",
        )
        error_code, loaded_sample = await app.driver.archive.tray_load(
            **active.action.action_params
        )
        active.action.error_code = error_code
        if loaded_sample != NoneSample():
            await active.append_sample(samples=[loaded_sample], IO="in")
        datadict = {"error_code": error_code, "sample": loaded_sample.as_dict()}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/archive_tray_unload", tags=["action"])
    async def archive_tray_unload(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        tray: int = None,
        slot: int = None,
    ):
        """Resets app.driver vial table."""
        active = await app.base.setup_and_contain_action(action_abbr="unload_sample")
        (
            unloaded,
            samples_in,
            samples_out,
            tray_dict,
        ) = await app.driver.archive.tray_unload(**active.action.action_params)
        await active.append_sample(samples=samples_in, IO="in")
        await active.append_sample(samples=samples_out, IO="out")
        datadict = {"unloaded": unloaded, "tray_dict": tray_dict}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/archive_tray_new_position", tags=["action"])
    async def archive_tray_new(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        req_vol: float = None,
    ):
        """Returns an empty vial position for given max volume.
        For mixed vial sizes the req_vol helps to choose the proper vial for sample volume.
        It will select the first empty vial which has the smallest volume that still can hold req_vol
        """
        active = await app.base.setup_and_contain_action()
        datadict = await app.driver.archive.tray_new_position(
            **active.action.action_params
        )
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_tray_update_position", tags=["action"])
    async def archive_tray_update_position(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        sample: SampleUnion = Body(
            LiquidSample(**{"sample_no": 1, "machine_name": gethostname().lower()}),
            embed=True,
        ),
        tray: int = None,
        slot: int = None,
        vial: int = None,
    ):
        """Updates app.driver vial Table. If sucessful (vial-slot was empty) returns True, else it returns False."""
        active = await app.base.setup_and_contain_action()
        datadict = {
            "update": await app.driver.archive.tray_update_position(
                **active.action.action_params
            ),
        }
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_tray_export_json", tags=["action"])
    async def archive_tray_export_json(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        tray: int = None,
        slot: int = None,
    ):
        active = await app.base.setup_and_contain_action(
            action_abbr="traytojson",
            file_type="palvialtable_helao__file",
        )
        datadict = await app.driver.archive.tray_export_json(
            **active.action.action_params
        )
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_tray_export_icpms", tags=["action"])
    async def archive_tray_export_icpms(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        tray: int = None,
        slot: int = None,
        survey_runs: int = None,
        main_runs: int = None,
        rack: int = None,
        dilution_factor: float = None,
    ):
        active = await app.base.setup_and_contain_action(
            action_abbr="traytoicpms",
        )
        await app.driver.archive.tray_export_icpms(
            tray=active.action.action_params.get("tray", None),
            slot=active.action.action_params.get("slot", None),
            myactive=active,
            survey_runs=active.action.action_params.get("survey_runs", None),
            main_runs=active.action.action_params.get("main_runs", None),
            rack=active.action.action_params.get("rack", None),
            dilution_factor=active.action.action_params.get("dilution_factor", None),
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_tray_export_csv", tags=["action"])
    async def archive_tray_export_csv(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        tray: int = None,
        slot: int = None,
    ):
        active = await app.base.setup_and_contain_action(
            action_abbr="traytocsv",
        )

        await app.driver.archive.tray_export_csv(
            tray=active.action.action_params.get("tray", None),
            slot=active.action.action_params.get("slot", None),
            myactive=active,
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_custom_load_solid", tags=["action"])
    async def archive_custom_load_solid(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        custom: dev_customitems = None,
        sample_no: int = 1,
        plate_id: int = 1,
    ):
        active = await app.base.setup_and_contain_action(
            action_abbr="load_sample",
        )
        active.action.action_params["load_sample_in"] = SolidSample(
            **active.action.action_params
        )
        loaded, loaded_sample, customs_dict = await app.driver.archive.custom_load(
            **active.action.action_params
        )
        if loaded:
            await active.append_sample(samples=[loaded_sample], IO="in")
        datadict = {"loaded": loaded, "customs_dict": customs_dict}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/archive_custom_load", tags=["action"])
    async def archive_custom_load(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        custom: dev_customitems = None,
        load_sample_in: SampleUnion = Body(
            LiquidSample(**{"sample_no": 1, "machine_name": gethostname().lower()}),
            embed=True,
        ),
    ):
        active = await app.base.setup_and_contain_action(
            action_abbr="load_sample",
        )
        loaded, loaded_sample, customs_dict = await app.driver.archive.custom_load(
            **active.action.action_params
        )
        if loaded:
            await active.append_sample(samples=[loaded_sample], IO="in")
        datadict = {"loaded": loaded, "customs_dict": customs_dict}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/archive_custom_unload", tags=["action"])
    async def archive_custom_unload(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        custom: dev_customitems = None,
        destroy_liquid: bool = False,
        destroy_gas: bool = False,
        destroy_solid: bool = False,
        keep_liquid: bool = False,
        keep_solid: bool = False,
        keep_gas: bool = False,
    ):
        active = await app.base.setup_and_contain_action(
            action_abbr="unload_sample",
        )
        (
            unloaded,
            samples_in,
            samples_out,
            customs_dict,
        ) = await app.driver.archive.custom_unload(
            **active.action.action_params, action=active.action
        )
        await active.append_sample(samples=samples_in, IO="in")
        await active.append_sample(samples=samples_out, IO="out")
        datadict = {"unloaded": unloaded, "customs_dict": customs_dict}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/archive_custom_unloadall", tags=["action"])
    async def archive_custom_unloadall(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        destroy_liquid: bool = False,
        destroy_gas: bool = False,
        destroy_solid: bool = False,
        keep_liquid: bool = False,
        keep_solid: bool = False,
        keep_gas: bool = False,
    ):
        active = await app.base.setup_and_contain_action(
            action_abbr="unload_sample",
        )
        (
            unloaded,
            samples_in,
            samples_out,
            customs_dict,
        ) = await app.driver.archive.custom_unloadall(
            **active.action.action_params, action=active.action
        )
        await active.append_sample(samples=samples_in, IO="in")
        await active.append_sample(samples=samples_out, IO="out")
        await active.enqueue_data_dflt(
            datadict={"unloaded": unloaded, "customs_dict": customs_dict}
        )
        unloaded_solids = [s for s in samples_in if s.sample_type == SampleType.solid]
        print(unloaded_solids)
        unloaded_liquids = [s for s in samples_in if s.sample_type == SampleType.liquid]
        print(unloaded_liquids)
        first_unloaded_solid = unloaded_solids[0].as_dict() if unloaded_solids else None
        first_unloaded_liquid = (
            unloaded_liquids[0].as_dict() if unloaded_liquids else None
        )
        if first_unloaded_liquid is None:
            unloaded_vol = 0
        else:
            unloaded_vol = first_unloaded_liquid['volume_ml']
        active.action.action_params.update({"_unloaded_solid": first_unloaded_solid})
        active.action.action_params.update({"_unloaded_liquid": first_unloaded_liquid})
        active.action.action_params.update({"_unloaded_liquid_vol": unloaded_vol})
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/archive_custom_query_sample", tags=["action"])
    async def archive_custom_query_sample(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        custom: dev_customitems = None,
    ):
        active = await app.base.setup_and_contain_action(
            action_abbr="query_sample",
        )
        error_code, sample = await app.driver.archive.custom_query_sample(
            **active.action.action_params
        )
        active.action.error_code = error_code
        await active.append_sample(samples=[sample], IO="in")
        datadict = {"sample": sample.as_dict(), "error_code": error_code}
        active.action.action_params.update({"_fast_samples_in": [sample.as_dict()]})
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_custom_add_liquid", tags=["action"])
    async def archive_custom_add_liquid(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        custom: dev_customitems = None,
        source_liquid_in: LiquidSample = Body(
            LiquidSample(**{"sample_no": 1, "machine_name": gethostname().lower()}),
            embed=True,
        ),
        volume_ml: float = 0.0,
        combine_liquids: bool = False,
        dilute_liquids: bool = True,
    ):
        """Adds 'volume_ml' of 'source_liquid_in' to the sample 'custom'.
        Args:
             custom: custom position where liquid will be added
             source_liquid_in: the liquid from which volume_ml will be added
                               to custom
             volume_ml: the volume in ml which will be added
             combine_liquids: combines liquid in 'custom' and 'source_liquid_in'
                              in a new liquid
             dilute_liquids: calculates a dilutes factor (use with combine liquids)
        """

        active = await app.base.setup_and_contain_action(
            action_abbr="add_liquid",
        )
        (
            error_code,
            samples_in,
            samples_out,
        ) = await app.driver.archive.custom_add_liquid(
            custom=active.action.action_params["custom"],
            source_liquid_in=active.action.action_params["source_liquid_in"],
            volume_ml=active.action.action_params["volume_ml"],
            combine_liquids=active.action.action_params["combine_liquids"],
            dilute_liquids=active.action.action_params["dilute_liquids"],
            action=active.action,
        )
        active.action.error_code = error_code
        await active.append_sample(samples=samples_in, IO="in")
        await active.append_sample(samples=samples_out, IO="out")
        datadict = {"error_code": error_code}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/db_get_samples", tags=["action"])
    async def db_get_samples(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        fast_samples_in: List[SampleUnion] = Body(
            [LiquidSample(**{"sample_no": 1, "machine_name": gethostname().lower()})],
            embed=True,
        ),
    ):
        """Positive sample_no will get it from the beginng, negative
        from the end of the db."""
        active = await app.base.setup_and_contain_action()
        samples = await app.driver.archive.unified_db.get_samples(
            samples=active.action.samples_in
        )
        # clear samples_in
        active.action.samples_in = []
        await active.append_sample(samples=samples, IO="in")
        datadict = {"samples": [sample.as_dict() for sample in samples]}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/db_new_samples", tags=["action"])
    async def db_new_samples(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        fast_samples_in: List[SampleUnion] = Body(
            [
                LiquidSample(
                    **{
                        "machine_name": gethostname().lower(),
                        "source": [],
                        "volume_ml": 0.0,
                        "action_time": strftime("%Y%m%d.%H%M%S"),
                        "chemical": [],
                        "partial_molarity": [],
                        "supplier": [],
                        "lot_number": [],
                    }
                )
            ],
            embed=True,
        ),
    ):
        """use CAS for chemical if available.
        Written on bottles of chemicals with all other necessary information.
        For empty DUID and AUID the UID will automatically created.
        For manual entry leave DUID, AUID, action_time,
        and action_params empty and servkey on "data".
        If its the very first liquid (no source in database exists)
        leave source and source_ml empty.
        """
        active = await app.base.setup_and_contain_action()
        samples = await app.driver.archive.create_samples(
            reference_samples_in=active.action.samples_in, action=active.action
        )
        # clear samples_in and samples_out
        active.action.samples_in = []
        active.action.samples_out = []
        await active.append_sample(samples=samples, IO="out")
        sample_out_dicts = [sample.as_dict() for sample in samples]
        datadict = {"samples": sample_out_dicts}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        active.action.action_params["_fast_sample_out"] = sample_out_dicts[0]
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/generate_plate_sample_no_list", tags=["action"])
    async def generate_plate_sample_no_list(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plate_id: int = 1,
        sample_code: int = Query(0, ge=0, le=2),
        skip_n_samples: int = Query(0, ge=0),
        direction: ScanDirection = None,
        sample_nos: List[int] = [],
        sample_nos_operator: ScanOperator = None,
        # platemap_xys: List[Tuple[int, int]] = [],
        platemap_xys: list = [],
        platemap_xys_operator: ScanOperator = None,
    ):
        active = await app.base.setup_and_contain_action()
        await app.driver.archive.generate_plate_sample_no_list(
            active=active,
            plate_id=active.action.action_params.get("plate_id", None),
            sample_code=active.action.action_params.get("sample_code", None),
            skip_n_samples=active.action.action_params.get("skip_n_samples", None),
            direction=active.action.action_params.get("direction", None),
            sample_nos=active.action.action_params.get("sample_nos", None),
            sample_nos_operator=active.action.action_params.get(
                "sample_nos_operator", None
            ),
            platemap_xys=active.action.action_params.get("platemap_xys", None),
            platemap_xys_operator=active.action.action_params.get(
                "platemap_xys_operator", None
            ),
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/get_loaded_positions", tags=["action"])
    async def get_positions(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Returns position dict under action_params['_positions']."""
        active = await app.base.setup_and_contain_action()
        positions = app.driver.archive.positions
        tray_positions = {
            (traynum, slotnum, vialidx + 1): sample.global_label
            for traynum, slotdict in positions.trays_dict.items()
            for slotnum, vialtray in slotdict.items()
            for vialidx, (vialbool, sample) in enumerate(
                zip(vialtray.vials, vialtray.samples)
            )
            if vialbool
        }
        custom_positions = {
            customkey: custom.sample.global_label
            for customkey, custom in positions.customs_dict.items()
        }
        active.action.action_params.update(
            {
                "_positions": positions.as_dict(),
                "_tray_pos": tray_positions,
                "_custom_pos": custom_positions,
            }
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/list_new_samples", tags=["action"])
    async def list_new_samples(num_smps: int = 10, give_only: str = "false"):
        """List num_smps newest global sample labels from each local DB table."""
        give_bool = True if give_only == "true" else False
        solids = await app.driver.archive.unified_db.solidAPI.list_new_samples(
            limit=num_smps, give_only=give_bool
        )
        liquids = await app.driver.archive.unified_db.liquidAPI.list_new_samples(
            limit=num_smps, give_only=give_bool
        )
        gases = await app.driver.archive.unified_db.gasAPI.list_new_samples(
            limit=num_smps, give_only=give_bool
        )
        assemblies = await app.driver.archive.unified_db.assemblyAPI.list_new_samples(
            limit=num_smps, give_only=give_bool
        )
        return {
            "solid": solids,
            "liquid": liquids,
            "gas": gases,
            "assembly": assemblies,
        }

    return app
