"""General calculation server

Calc server is used for in-sequence data processing.

"""

__all__ = ["makeApp"]

import json
from typing import Optional, Union, List
from fastapi import Body

from helao.core.models.file import HloHeaderModel, HloFileGroup
from helao.helpers.premodels import Action
from helao.servers.base_api import BaseAPI
from helao.drivers.data.calc_driver import Calc
from helao.helpers.config_loader import config_loader

from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER


def makeApp(confPrefix, server_key, helao_root):
    config = config_loader(confPrefix, helao_root)
    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Calculation server",
        version=0.1,
        driver_class=Calc,
    )

    @app.post(f"/{server_key}/calc_uvis_abs", tags=["action"])
    async def calc_uvis_abs(
        action: Action = Body({}, embed=True),
        action_version: int = 2,
        ev_parts: list = [1.8, 2.2, 2.6, 3.0],
        bin_width: int = 3,
        window_length: int = 45,
        poly_order: int = 4,
        lower_wl: float = 370,
        upper_wl: float = 700,
        max_mthd_allowed: float = 1.2,
        max_limit: float = 0.99,
        min_mthd_allowed: float = -0.2,
        min_limit: float = 0.01,
        delta: float = 1.0,
    ):
        active = await app.base.setup_and_contain_action(action_abbr="calcAbs")
        datadict, arraydict = app.driver.calc_uvis_abs(active)
        await active.enqueue_data_dflt(datadict=datadict)
        for k, ad in arraydict.items():
            # convert ad to strings
            datalst = list(zip(*ad["data"]))
            smplabs = ad["sample_label"]
            uuidlst = ad["action_uuids"]
            fulllst = [smplabs, uuidlst] + datalst
            colnames = ["sample_label", "action_uuid"] + [
                f"idx_{i:04}" for i in range(len(datalst))
            ]
            jsondict = {k: v for k, v in zip(colnames, fulllst)}
            jsondata = json.dumps(jsondict)
            header = HloHeaderModel(
                action_name=active.action.action_name,
                column_headings=colnames,
                optional={"wl": ad["wavelength"]},
                epoch_ns=app.base.get_realtime_nowait(),
            )
            abbr = active.action.action_abbr
            subi = active.action.orch_submit_order
            acti = active.action.action_order
            retry = active.action.action_retry
            split = active.action.action_split
            suffix = f"{k}.hlo"
            await active.write_file(
                output_str=jsondata,
                file_type="helao_calc__file",
                filename=f"{abbr}.{subi}.{acti}.{retry}.{split}__{suffix}",
                file_group=HloFileGroup.helao_files,
                header=header.clean_dict(),
                file_sample_label=ad["sample_label"],
                json_data_keys=colnames,
                action=active.action,
            )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/check_co2_purge", tags=["action"])
    async def check_co2_purge(
        action: Action = Body({}, embed=True),
        action_version: int = 2,
        co2_ppm_thresh: float = 95000,
        purge_if: Union[str, float] = "below",
        present_syringe_volume_ul: float = 0,
        repeat_experiment_name: str = "CCSI_sub_headspace_purge_and_measure",
        repeat_experiment_params: dict = {},
        repeat_experiment_kwargs: dict = {},
    ):
        active = await app.base.setup_and_contain_action(action_abbr="checkCO2")
        result = await app.driver.check_co2_purge_level(active)
        LOGGER.info(f"result dict was: {result}")
        await active.enqueue_data_dflt(datadict=result)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/fill_syringe_volume_check", tags=["action"])
    async def fill_syringe_volume_check(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        check_volume_ul: float = 0,
        target_volume_ul: float = 0,
        present_volume_ul: float = 0,
        repeat_experiment_name: str = "CCSI_sub_fill_syringe",
        repeat_experiment_params: dict = {},
        repeat_experiment_kwargs: dict = {},
    ):
        active = await app.base.setup_and_contain_action(
            action_abbr="syringefillvolume"
        )
        result = await app.driver.fill_syringe_volume_check(active)
        LOGGER.info(f"result dict was: {result}")
        await active.enqueue_data_dflt(datadict=result)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/keep_min_ocv", tags=["action"])
    async def keep_min_ocv(
        action: Action = Body({}, embed=True),
        action_version: int = 2,
        min_offset_ocv: float = 0,
        new_ocv: float = 0,
        offset_value: float = -0.2,
    ):
        active = await app.base.setup_and_contain_action(action_abbr="keepMinOCV")
        result = (
            min(
                active.action.action_params["min_offset_ocv"]
                + active.action.action_params["offset_value"],
                active.action.action_params["new_ocv"],
            )
            - active.action.action_params["offset_value"]
        )

        LOGGER.info(f"minimum potential was: {result}")
        await active.enqueue_data_dflt(datadict=result)
        active.action.action_params["min_offset_ocv"] = result
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
