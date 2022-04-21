__all__ = ["makeApp"]


from importlib import import_module
from socket import gethostname
from time import strftime

from fastapi import Body, Query
from typing import Optional, List, Tuple

from helaocore.server.base import makeActionServ
from helao.library.driver.pal_driver import (
    PAL,
    Spacingmethod,
    PALtools,
    PalMicroCam,
    PALposition,
    GCsampletype,
    SampleInheritance,
    SampleStatus,
)
from helao.library.driver.archive_driver import ScanDirection, ScanOperator

from helaocore.model.sample import SampleType, LiquidSample, SampleUnion, NoneSample
from helaocore.helper.make_str_enum import make_str_enum
from helaocore.schema import Action
from helaocore.helper.config_loader import config_loader


def makeApp(confPrefix, servKey, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = makeActionServ(
        config,
        servKey,
        servKey,
        "PAL Autosampler Server",
        version=2.0,
        driver_class=PAL,
    )

    _cams = app.server_params.get("cams", dict())
    # _camsitems = make_str_enum("cams",{key:key for key in _cams.keys()})

    if "positions" in app.server_params:
        dev_custom = app.server_params["positions"].get("custom", dict())
    else:
        dev_custom = dict()
    dev_customitems = make_str_enum(
        "dev_custom", {key: key for key in dev_custom.keys()}
    )

    @app.post(f"/{servKey}/stop", tags=["public"])
    async def stop(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Stops measurement in a controlled way."""
        active = await app.base.setup_and_contain_action(action_abbr="stop")
        await active.enqueue_data_dflt(datadict={"stop": await app.driver.stop()})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/kill_PAL", tags=["public"])
    async def kill_PAL(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
    ):
        active = await app.base.setup_and_contain_action()
        error_code = await app.driver.kill_PAL()
        active.action.error_code = error_code
        await active.enqueue_data_dflt(datadict={"error_code": error_code})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/convert_v1DB", tags=["public_db"])
    async def convert_v1DB(action: Optional[Action] = Body({}, embed=True)):
        # await app.driver.convert_oldDB_to_sqllite()
        await app.driver.archive.unified_db.liquidAPI.old_jsondb_to_sqlitedb()
        return {}

    if _cams:

        @app.post(f"/{servKey}/PAL_run_method", tags=["public_PAL"])
        async def PAL_run_method(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            micropal: Optional[list] = [
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
            totalruns: Optional[int] = 1,
            # its a necessary param, but as its the only dict, it partially breaks swagger
            sampleperiod: Optional[List[float]] = [0.0],
            spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
            spacingfactor: Optional[float] = 1.0,
            timeoffset: Optional[float] = 0.0,
        ):
            """universal pal action"""
            A = await app.base.setup_action()
            active_dict = await app.driver.method_arbitrary(A)
            return active_dict

    if (
        "injection_custom_GC_liquid_start" in _cams
        or "injection_custom_GC_liquid_wait" in _cams
        or "injection_custom_GC_gas_start" in _cams
        or "injection_custom_GC_gas_wait" in _cams
        and "archive"
    ):

        @app.post(f"/{servKey}/PAL_ANEC_aliquot", tags=["PAL_ANEC"])
        async def PAL_ANEC_aliquot(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            toolGC: Optional[PALtools] = PALtools.HS2,
            toolarchive: Optional[PALtools] = PALtools.LS3,
            source: Optional[dev_customitems] = "cell1_we",
            volume_ul_GC: Optional[int] = 300,
            volume_ul_archive: Optional[int] = 500,
            wash1: Optional[bool] = True,
            wash2: Optional[bool] = True,
            wash3: Optional[bool] = True,
            wash4: Optional[bool] = False,
        ):
            A = await app.base.setup_action()
            A.action_abbr = "GC_injection"
            active_dict = await app.driver.method_ANEC_aliquot(A)
            return active_dict

    if (
        "injection_custom_GC_liquid_start" in _cams
        or "injection_custom_GC_liquid_wait" in _cams
        or "injection_custom_GC_gas_start" in _cams
        or "injection_custom_GC_gas_wait" in _cams
    ):

        @app.post(f"/{servKey}/PAL_ANEC_GC", tags=["PAL_ANEC"])
        async def PAL_ANEC_GC(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            toolGC: Optional[PALtools] = PALtools.HS2,
            source: Optional[dev_customitems] = "cell1_we",
            volume_ul_GC: Optional[int] = 300,
        ):
            A = await app.base.setup_action()
            A.action_abbr = "GC_injection"
            active_dict = await app.driver.method_ANEC_GC(A)
            return active_dict

    if (
        "injection_tray_GC_liquid_start" in _cams
        or "injection_tray_GC_liquid_wait" in _cams
        or "injection_tray_GC_gas_start" in _cams
        or "injection_tray_GC_gas_wait" in _cams
    ):

        @app.post(f"/{servKey}/PAL_injection_tray_GC", tags=["PAL_GC"])
        async def PAL_injection_tray_GC(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            startGC: Optional[bool] = None,
            sampletype: Optional[GCsampletype] = None,
            tool: Optional[PALtools] = None,
            source_tray: Optional[int] = 1,
            source_slot: Optional[int] = 1,
            source_vial: Optional[int] = 1,
            dest: Optional[dev_customitems] = None,
            volume_ul: Optional[int] = 2,
            wash1: Optional[bool] = True,
            wash2: Optional[bool] = True,
            wash3: Optional[bool] = True,
            wash4: Optional[bool] = False,
        ):
            A = await app.base.setup_action()
            A.action_abbr = "GC_injection"
            active_dict = await app.driver.method_injection_tray_GC(A)
            return active_dict

    if (
        "injection_custom_GC_liquid_start" in _cams
        or "injection_custom_GC_liquid_wait" in _cams
        or "injection_custom_GC_gas_start" in _cams
        or "injection_custom_GC_gas_wait" in _cams
    ):

        @app.post(f"/{servKey}/PAL_injection_custom_GC", tags=["PAL_GC"])
        async def PAL_injection_custom_GC(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            startGC: Optional[bool] = None,
            sampletype: Optional[GCsampletype] = None,
            tool: Optional[PALtools] = None,
            source: Optional[dev_customitems] = None,
            dest: Optional[dev_customitems] = None,
            volume_ul: Optional[int] = 2,
            wash1: Optional[bool] = True,
            wash2: Optional[bool] = True,
            wash3: Optional[bool] = True,
            wash4: Optional[bool] = False,
        ):
            A = await app.base.setup_action()
            A.action_abbr = "GC_injection"
            active_dict = await app.driver.method_injection_custom_GC(A)
            return active_dict

    if "injection_custom_HPLC" in _cams:

        @app.post(f"/{servKey}/PAL_injection_custom_HPLC", tags=["PAL_HPLC"])
        async def PAL_injection_custom_HPLC(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            tool: Optional[PALtools] = None,
            source: Optional[dev_customitems] = None,
            dest: Optional[dev_customitems] = None,
            volume_ul: Optional[int] = 2,
            wash1: Optional[bool] = True,
            wash2: Optional[bool] = True,
            wash3: Optional[bool] = True,
            wash4: Optional[bool] = False,
        ):
            A = await app.base.setup_action()
            A.action_abbr = "HPLC_injection"
            active_dict = await app.driver.method_injection_custom_HPLC(A)
            return active_dict

    if "injection_tray_HPLC" in _cams:

        @app.post(f"/{servKey}/PAL_injection_tray_HPLC", tags=["PAL_HPLC"])
        async def PAL_injection_tray_HPLC(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            tool: Optional[PALtools] = None,
            source_tray: Optional[int] = 1,
            source_slot: Optional[int] = 1,
            source_vial: Optional[int] = 1,
            dest: Optional[dev_customitems] = None,
            volume_ul: Optional[int] = 2,
            wash1: Optional[bool] = True,
            wash2: Optional[bool] = True,
            wash3: Optional[bool] = True,
            wash4: Optional[bool] = False,
        ):
            A = await app.base.setup_action()
            A.action_abbr = "HPLC_injection"
            active_dict = await app.driver.method_injection_tray_HPLC(A)
            return active_dict

    if "transfer_tray_tray" in _cams:

        @app.post(f"/{servKey}/PAL_transfer_tray_tray", tags=["PAL_transfer"])
        async def PAL_transfer_tray_tray(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            sampleperiod: Optional[List[float]] = Body([0.0], embed=True),
            spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
            spacingfactor: Optional[float] = 1.0,
            timeoffset: Optional[float] = 0.0,
            tool: Optional[PALtools] = None,
            volume_ul: Optional[int] = 2,
            source_tray: Optional[int] = 1,
            source_slot: Optional[int] = 1,
            source_vial: Optional[int] = 1,
            dest_tray: Optional[int] = 1,
            dest_slot: Optional[int] = 1,
            dest_vial: Optional[int] = 1,
            wash1: Optional[bool] = True,
            wash2: Optional[bool] = True,
            wash3: Optional[bool] = True,
            wash4: Optional[bool] = False,
        ):
            A = await app.base.setup_action()
            A.action_abbr = "transfer"
            active_dict = await app.driver.method_transfer_tray_tray(A)
            return active_dict

    if "transfer_tray_custom" in _cams:

        @app.post(f"/{servKey}/PAL_transfer_tray_custom", tags=["PAL_transfer"])
        async def PAL_transfer_tray_custom(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            sampleperiod: Optional[List[float]] = Body([0.0], embed=True),
            spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
            spacingfactor: Optional[float] = 1.0,
            timeoffset: Optional[float] = 0.0,
            tool: Optional[PALtools] = None,
            volume_ul: Optional[int] = 2,
            source_tray: Optional[int] = 1,
            source_slot: Optional[int] = 1,
            source_vial: Optional[int] = 1,
            dest: Optional[dev_customitems] = None,
            wash1: Optional[bool] = True,
            wash2: Optional[bool] = True,
            wash3: Optional[bool] = True,
            wash4: Optional[bool] = False,
        ):
            A = await app.base.setup_action()
            A.action_abbr = "transfer"
            active_dict = await app.driver.method_transfer_tray_custom(A)
            return active_dict

    if "transfer_custom_tray" in _cams:

        @app.post(f"/{servKey}/PAL_transfer_custom_tray", tags=["PAL_transfer"])
        async def PAL_transfer_custom_tray(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            sampleperiod: Optional[List[float]] = Body([0.0], embed=True),
            spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
            spacingfactor: Optional[float] = 1.0,
            timeoffset: Optional[float] = 0.0,
            tool: Optional[PALtools] = None,
            volume_ul: Optional[int] = 2,
            source: Optional[dev_customitems] = None,
            dest_tray: Optional[int] = 1,
            dest_slot: Optional[int] = 1,
            dest_vial: Optional[int] = 1,
            wash1: Optional[bool] = True,
            wash2: Optional[bool] = True,
            wash3: Optional[bool] = True,
            wash4: Optional[bool] = False,
        ):
            A = await app.base.setup_action()
            A.action_abbr = "transfer"
            active_dict = await app.driver.method_transfer_custom_tray(A)
            return active_dict

    if "transfer_custom_custom" in _cams:

        @app.post(f"/{servKey}/PAL_transfer_custom_custom", tags=["PAL_transfer"])
        async def PAL_transfer_custom_custom(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            sampleperiod: Optional[List[float]] = Body([0.0], embed=True),
            spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
            spacingfactor: Optional[float] = 1.0,
            timeoffset: Optional[float] = 0.0,
            tool: Optional[PALtools] = None,
            volume_ul: Optional[int] = 2,
            source: Optional[dev_customitems] = None,
            dest: Optional[dev_customitems] = None,
            wash1: Optional[bool] = True,
            wash2: Optional[bool] = True,
            wash3: Optional[bool] = True,
            wash4: Optional[bool] = False,
        ):
            A = await app.base.setup_action()
            A.action_abbr = "transfer"
            active_dict = await app.driver.method_transfer_custom_custom(A)
            return active_dict

    if "archive" in _cams:

        @app.post(f"/{servKey}/PAL_archive", tags=["public_PAL"])
        async def PAL_archive(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            tool: Optional[PALtools] = None,
            source: Optional[dev_customitems] = None,
            volume_ul: Optional[int] = 200,
            sampleperiod: Optional[List[float]] = Body([0.0], embed=True),
            spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
            spacingfactor: Optional[float] = 1.0,
            timeoffset: Optional[float] = 0.0,
            wash1: Optional[bool] = False,
            wash2: Optional[bool] = False,
            wash3: Optional[bool] = False,
            wash4: Optional[bool] = False,
        ):
            A = await app.base.setup_action()
            A.action_abbr = "archive"
            active_dict = await app.driver.method_archive(A)
            return active_dict

    # if "fill" in _cams:
    #     @app.post(f"/{servKey}/PAL_fill", tags=["public_PAL"])
    #     async def PAL_fill(
    #         action: Optional[Action] = \
    #                 Body({}, embed=True),
    #         tool: Optional[PALtools] = None,
    #         source: Optional[dev_customitems] = None,
    #         dest: Optional[dev_customitems] = None,
    #         volume_ul: Optional[int] = 200,
    #         wash1: Optional[bool] = False,
    #         wash2: Optional[bool] = False,
    #         wash3: Optional[bool] = False,
    #         wash4: Optional[bool] = False,
    #     ):
    #         A = await app.base.setup_action()
    #         A.action_abbr = "fill"
    #         active_dict = await app.driver.method_fill(A)
    #         return active_dict

    # if "fillfixed" in _cams:
    #     @app.post(f"/{servKey}/PAL_fillfixed", tags=["public_PAL"])
    #     async def PAL_fillfixed(
    #         action: Optional[Action] = \
    #                 Body({}, embed=True),
    #         tool: Optional[PALtools] = None,
    #         source: Optional[dev_customitems] = None,
    #         dest: Optional[dev_customitems] = None,
    #         volume_ul: Optional[int] = 200, # this value is only for prc, a fixed value is used
    #         wash1: Optional[bool] = False,
    #         wash2: Optional[bool] = False,
    #         wash3: Optional[bool] = False,
    #         wash4: Optional[bool] = False,
    #     ):
    #         A = await app.base.setup_action()
    #         A.action_abbr = "fillfixed"
    #         active_dict = await app.driver.method_fillfixed(A)
    #         return active_dict

    if "deepclean" in _cams:

        @app.post(f"/{servKey}/PAL_deepclean", tags=["public_PAL"])
        async def PAL_deepclean(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            tool: Optional[PALtools] = None,
            volume_ul: Optional[
                int
            ] = 200,  # this value is only for prc, a fixed value is used
            wash1: Optional[bool] = True,
            wash2: Optional[bool] = True,
            wash3: Optional[bool] = True,
            wash4: Optional[bool] = True,
        ):
            A = await app.base.setup_action()
            A.action_abbr = "deepclean"
            active_dict = await app.driver.method_deepclean(A)
            return active_dict

    if "dilute" in _cams:

        @app.post(f"/{servKey}/PAL_dilute", tags=["public_PAL"])
        async def PAL_dilute(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            tool: Optional[PALtools] = None,
            source: Optional[dev_customitems] = None,
            volume_ul: Optional[int] = 200,
            dest_tray: Optional[int] = 0,
            dest_slot: Optional[int] = 0,
            dest_vial: Optional[int] = 0,
            sampleperiod: Optional[List[float]] = Body([0.0], embed=True),
            spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
            spacingfactor: Optional[float] = 1.0,
            timeoffset: Optional[float] = 0.0,
            wash1: Optional[bool] = True,
            wash2: Optional[bool] = True,
            wash3: Optional[bool] = True,
            wash4: Optional[bool] = True,
        ):
            A = await app.base.setup_action()
            A.action_abbr = "dilute"
            active_dict = await app.driver.method_dilute(A)
            return active_dict

    if "autodilute" in _cams:

        @app.post(f"/{servKey}/PAL_autodilute", tags=["public_PAL"])
        async def PAL_autodilute(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            tool: Optional[PALtools] = None,
            source: Optional[dev_customitems] = None,
            volume_ul: Optional[int] = 200,
            sampleperiod: Optional[List[float]] = Body([0.0], embed=True),
            spacingmethod: Optional[Spacingmethod] = Spacingmethod.linear,
            spacingfactor: Optional[float] = 1.0,
            timeoffset: Optional[float] = 0.0,
            wash1: Optional[bool] = True,
            wash2: Optional[bool] = True,
            wash3: Optional[bool] = True,
            wash4: Optional[bool] = True,
        ):
            A = await app.base.setup_action()
            A.action_abbr = "autodilute"
            active_dict = await app.driver.method_autodilute(A)
            return active_dict

    @app.post(f"/{servKey}/archive_tray_query_sample", tags=["public_archive"])
    async def archive_tray_query_sample(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
    ):
        active = await app.base.setup_and_contain_action(action_abbr="query_sample")
        error_code, sample = await app.driver.archive.tray_query_sample(
            **active.action.action_params
        )
        active.action.error_code = error_code
        await active.append_sample(samples=[sample], IO="in")
        await active.enqueue_data_dflt(
            datadict={"sample": sample.as_dict(), "error_code": error_code}
        )
        active.action.action_params.update({"_fast_samples_in": [sample.as_dict()]})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/archive_tray_unloadall", tags=["public_archive"])
    async def archive_tray_unloadall(action: Optional[Action] = Body({}, embed=True)):
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
        await active.enqueue_data_dflt(
            datadict={"unloaded": unloaded, "tray_dict": tray_dict}
        )
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{servKey}/archive_tray_load", tags=["public_archive"])
    async def archive_tray_load(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        load_sample_in: Optional[SampleUnion] = Body(
            LiquidSample(**{"sample_no": 1, "machine_name": gethostname()}), embed=True
        ),
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
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
        await active.enqueue_data_dflt(
            datadict={"error_code": error_code, "sample": loaded_sample.as_dict()}
        )
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{servKey}/archive_tray_unload", tags=["public_archive"])
    async def archive_tray_unload(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
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
        await active.enqueue_data_dflt(
            datadict={"unloaded": unloaded, "tray_dict": tray_dict}
        )
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{servKey}/archive_tray_new_position", tags=["public_archive"])
    async def archive_tray_new(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        req_vol: Optional[float] = None,
    ):
        """Returns an empty vial position for given max volume.
        For mixed vial sizes the req_vol helps to choose the proper vial for sample volume.
        It will select the first empty vial which has the smallest volume that still can hold req_vol
        """
        active = await app.base.setup_and_contain_action()
        await active.enqueue_data_dflt(
            datadict=await app.driver.archive.tray_new_position(
                **active.action.action_params
            )
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/archive_tray_update_position", tags=["public_archive"])
    async def archive_tray_update_position(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        sample: Optional[SampleUnion] = Body(
            LiquidSample(**{"sample_no": 1, "machine_name": gethostname()}), embed=True
        ),
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
    ):
        """Updates app.driver vial Table. If sucessful (vial-slot was empty) returns True, else it returns False."""
        active = await app.base.setup_and_contain_action()
        await active.enqueue_data_dflt(
            datadict={
                "update": await app.driver.archive.tray_update_position(
                    **active.action.action_params
                ),
            }
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/archive_tray_export_json", tags=["public_archive"])
    async def archive_tray_export_json(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
    ):
        active = await app.base.setup_and_contain_action(
            action_abbr="traytojson",
            file_type="palvialtable_helao__file",
        )
        await active.enqueue_data_dflt(
            datadict=await app.driver.archive.tray_export_json(
                **active.action.action_params
            )
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/archive_tray_export_icpms", tags=["public_archive"])
    async def archive_tray_export_icpms(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        survey_runs: Optional[int] = None,
        main_runs: Optional[int] = None,
        rack: Optional[int] = None,
        dilution_factor: Optional[float] = None,
    ):
        active = await app.base.setup_and_contain_action(
            action_abbr="traytoicpms",
        )
        await app.driver.archive.tray_export_icpms(
            myactive=active,
            tray=active.action.action_params.get("tray", None),
            slot=active.action.action_params.get("slot", None),
            survey_runs=active.action.action_params.get("survey_runs", None),
            main_runs=active.action.action_params.get("main_runs", None),
            rack=active.action.action_params.get("rack", None),
            dilution_factor=active.action.action_params.get("dilution_factor", None),
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/archive_tray_export_csv", tags=["public_archive"])
    async def archive_tray_export_csv(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
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

    @app.post(f"/{servKey}/archive_custom_load", tags=["public_archive"])
    async def archive_custom_load(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        custom: Optional[dev_customitems] = None,
        load_sample_in: Optional[SampleUnion] = Body(
            LiquidSample(**{"sample_no": 1, "machine_name": gethostname()}), embed=True
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
        await active.enqueue_data_dflt(
            datadict={"loaded": loaded, "customs_dict": customs_dict}
        )
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{servKey}/archive_custom_unload", tags=["public_archive"])
    async def archive_custom_unload(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        custom: Optional[dev_customitems] = None,
        destroy_liquid: Optional[bool] = False,
        destroy_gas: Optional[bool] = False,
        destroy_solid: Optional[bool] = False,
        keep_liquid: Optional[bool] = False,
        keep_solid: Optional[bool] = False,
        keep_gas: Optional[bool] = False,
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
        await active.enqueue_data_dflt(
            datadict={"unloaded": unloaded, "customs_dict": customs_dict}
        )
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{servKey}/archive_custom_unloadall", tags=["public_archive"])
    async def archive_custom_unloadall(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        destroy_liquid: Optional[bool] = False,
        destroy_gas: Optional[bool] = False,
        destroy_solid: Optional[bool] = False,
        keep_liquid: Optional[bool] = False,
        keep_solid: Optional[bool] = False,
        keep_gas: Optional[bool] = False,
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
        unloaded_solids = [s for s in samples_out if s.sample_type == SampleType.solid]
        unloaded_liquids = [
            s for s in samples_out if s.sample_type == SampleType.liquid
        ]
        if unloaded_solids:
            first_unloaded_solid = unloaded_solids[0]
        else:
            first_unloaded_solid = NoneSample()
        active.action.action_params.update({"_unloaded_solid": first_unloaded_solid})
        active.action.action_params.update({"_unloaded_liquids": unloaded_liquids})
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{servKey}/archive_custom_query_sample", tags=["public_archive"])
    async def archive_custom_query_sample(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        custom: Optional[dev_customitems] = None,
    ):
        active = await app.base.setup_and_contain_action(
            action_abbr="query_sample",
        )
        error_code, sample = await app.driver.archive.custom_query_sample(
            **active.action.action_params
        )
        active.action.error_code = error_code
        await active.append_sample(samples=[sample], IO="in")
        await active.enqueue_data_dflt(
            datadict={"sample": sample.as_dict(), "error_code": error_code}
        )
        active.action.action_params.update({"_fast_samples_in": [sample.as_dict()]})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/archive_custom_add_liquid", tags=["public_archive"])
    async def archive_custom_add_liquid(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        custom: Optional[dev_customitems] = None,
        source_liquid_in: Optional[SampleUnion] = Body(
            LiquidSample(**{"sample_no": 1, "machine_name": gethostname()}), embed=True
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
        await active.enqueue_data_dflt(datadict={"error_code": error_code})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/db_get_samples", tags=["public_db"])
    async def db_get_samples(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        fast_samples_in: Optional[List[SampleUnion]] = Body(
            [LiquidSample(**{"sample_no": 1, "machine_name": gethostname()})],
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

        await active.enqueue_data_dflt(
            datadict={"samples": [sample.as_dict() for sample in samples]}
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/db_new_samples", tags=["public_db"])
    async def db_new_samples(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        fast_samples_in: Optional[List[SampleUnion]] = Body(
            [
                LiquidSample(
                    **{
                        "machine_name": gethostname(),
                        "source": [],
                        "volume_ml": 0.0,
                        "action_time": strftime("%Y%m%d.%H%M%S"),
                        "chemical": [],
                        "mass": [],
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
        await active.enqueue_data_dflt(
            datadict={"samples": [sample.as_dict() for sample in samples]}
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/generate_plate_sample_no_list", tags=["public_db"])
    async def generate_plate_sample_no_list(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        plate_id: Optional[int] = 1,
        sample_code: Optional[int] = Query(0, ge=0, le=2),
        skip_n_samples: Optional[int] = Query(0, ge=0),
        direction: Optional[ScanDirection] = None,
        sample_nos: Optional[List[int]] = [],
        sample_nos_operator: Optional[ScanOperator] = None,
        # platemap_xys: Optional[List[Tuple[int, int]]] = [],
        platemap_xys: Optional[list] = [],
        platemap_xys_operator: Optional[ScanOperator] = None,
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

    @app.post(f"/get_loaded_positions", tags=["private_archive"])
    def get_positions(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Returns position dict."""
        return app.base.driver.archive.positions

    return app
