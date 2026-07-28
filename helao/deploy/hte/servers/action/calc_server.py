"""In-sequence calculation action server.

Wraps :class:`Calc` and exposes endpoints used to derive intermediate values
from data already produced earlier in an experiment (UVIS absorbance,
CO2-purge checks, syringe-fill checks, OCV clamping, CP Ewe bounds). Unlike
``analysis_server`` it does not produce :class:`Analysis` records.
"""

__all__ = ["makeApp"]

import os
import json
import numpy as np
from time import time_ns
from typing import Union

from helao.core.models.file import HloHeaderModel, HloFileGroup
from helao.core.servers.base_api import BaseAPI, action_version
from helao.helpers.dispatcher import async_private_dispatcher
from ...drivers.data.calc_driver import Calc
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def makeApp(server_key) -> BaseAPI:
    """Build the calculation FastAPI app.

    Constructs a :class:`BaseAPI` backed by the :class:`Calc` driver and
    registers the ``calc_uvis_abs``, ``check_co2_purge``,
    ``fill_syringe_volume_check``, ``keep_min_ocv`` and
    ``check_CP_Ewe_bounds`` action endpoints.

    Args:
        server_key: Key identifying this server in the orchestration group.

    Returns:
        The configured :class:`BaseAPI` application.
    """
    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Calculation server",
        version=0.1,
        driver_classes=[Calc],
    )

    @app.post(f"/{server_key}/calc_uvis_abs", tags=["action"])
    @action_version(2)
    async def calc_uvis_abs(
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
        """Compute UVIS absorbance and per-energy bin metrics for the active sample.

        Calls :meth:`Calc.calc_uvis_abs`, enqueues the scalar results and
        writes one ``helao_calc__file`` per array key with the wavelength
        vector embedded in the file header.
        """
        active = await app.base.setup_and_contain_action(action_abbr="calcAbs")
        seq_absdir = os.path.join(
            str(active.base.helaodirs.save_root), active.action.get_sequence_dir()
        )
        datadict, arraydict = app.driver.calc_uvis_abs(
            seq_absdir, active.action.action_params
        )
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
                epoch_ns=app.base.get_realtime_nowait(time_ns()),
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
    @action_version(2)
    async def check_co2_purge(
        co2_ppm_thresh: float = 95000,
        purge_if: Union[str, float] = "below",
        present_syringe_volume_ul: float = 0,
        repeat_experiment_name: str = "CCSI_sub_headspace_purge_and_measure",
        repeat_experiment_params: dict = {},
        repeat_experiment_kwargs: dict = {},
    ):
        """Check the CO2 purge level against ``co2_ppm_thresh`` for headspace purge logic.

        Delegates to :meth:`Calc.check_co2_purge_level`; the returned dict is
        used by the experiment to decide whether to schedule a repeat purge.
        """
        active = await app.base.setup_and_contain_action(action_abbr="checkCO2")
        seq_absdir = os.path.join(
            str(active.base.helaodirs.save_root), active.action.get_sequence_dir()
        )
        p = active.action.action_params
        result = await app.driver.check_co2_purge_level(
            seq_absdir,
            p["co2_ppm_thresh"],
            p["purge_if"],
            p["present_syringe_volume_ul"],
            p["repeat_experiment_name"],
            p["repeat_experiment_params"],
            p["repeat_experiment_kwargs"],
        )
        insert_experiment_payload = result.pop("__insert_experiment__", None)
        LOGGER.info(f"result dict was: {result}")
        if insert_experiment_payload is not None:
            resp, error = await async_private_dispatcher(
                active.base.orch_key,
                active.base.orch_host,
                active.base.orch_port,
                "insert_experiment",
                params_dict={},
                json_dict=insert_experiment_payload,
            )
            LOGGER.info(f"insert_experiment got response: {resp}")
            LOGGER.info(f"insert_experiment returned error: {error}")
        await active.enqueue_data_dflt(datadict=result)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/fill_syringe_volume_check", tags=["action"])
    async def fill_syringe_volume_check(
        check_volume_ul: float = 0,
        target_volume_ul: float = 0,
        present_volume_ul: float = 0,
        repeat_experiment_name: str = "CCSI_sub_fill_syringe",
        repeat_experiment_params: dict = {},
        repeat_experiment_kwargs: dict = {},
    ):
        """Verify the syringe fill volume against target/check setpoints.

        Delegates to :meth:`Calc.fill_syringe_volume_check`; the returned dict
        is used by the experiment to decide whether to schedule a repeat fill.
        """
        active = await app.base.setup_and_contain_action(
            action_abbr="syringefillvolume"
        )
        p = active.action.action_params
        result = await app.driver.fill_syringe_volume_check(
            p["check_volume_ul"],
            p["target_volume_ul"],
            p["present_volume_ul"],
            p["repeat_experiment_name"],
            p["repeat_experiment_params"],
            p["repeat_experiment_kwargs"],
        )
        insert_experiment_payload = result.pop("__insert_experiment__", None)
        LOGGER.info(f"result dict was: {result}")
        if insert_experiment_payload is not None:
            resp, error = await async_private_dispatcher(
                active.base.orch_key,
                active.base.orch_host,
                active.base.orch_port,
                "insert_experiment",
                params_dict={},
                json_dict=insert_experiment_payload,
            )
            LOGGER.info(f"insert_experiment got response: {resp}")
            LOGGER.info(f"insert_experiment returned error: {error}")
        await active.enqueue_data_dflt(datadict=result)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/keep_min_ocv", tags=["action"])
    @action_version(2)
    async def keep_min_ocv(
        min_offset_ocv: float | bool = False,
        new_ocv: float | bool = False,
        lower_limit: float = 0.2,
        upper_limit: float = 1.2,
        offset_value: float = -0.2,
    ):
        """Return the smaller of an inherited OCV minimum and a freshly measured OCV.

        ``min_offset_ocv`` and ``new_ocv`` are expected to be propagated from a
        prior ``run_OCV`` via the orchestrator's global params. Missing values
        (``False``) are replaced with a high fallback so the comparison still
        produces a usable result. The output is clamped to
        ``[lower_limit, upper_limit]`` and stored back on the action params as
        ``min_offset_ocv``.
        """

        active = await app.base.setup_and_contain_action(action_abbr="keepMinOCV")
        try:
            if isinstance(active.action.action_params["min_offset_ocv"], bool):
                min_offset_ocv = 3
                LOGGER.warning(
                    "min_offset_ocv not found in global params, setting to 3"
                )
            else:
                min_offset_ocv = active.action.action_params["min_offset_ocv"]

            if isinstance(active.action.action_params["new_ocv"], bool):
                new_ocv = 3
                LOGGER.warning("HISPEC_OCV not found in global params! Run OCV first")
            else:
                new_ocv = active.action.action_params["new_ocv"] + offset_value

        except Exception as e:
            LOGGER.error(f"Error getting global params: {e}")
            print(
                f"Error getting global params in calc_server.py, try perhaps the host details set here are wrong: {e}"
            )
        result = min(min_offset_ocv, new_ocv)
        if result < lower_limit:
            result = lower_limit
            LOGGER.warning(
                f"minimum potential was below lower limit, setting to {lower_limit}"
            )
        elif result > upper_limit:
            result = upper_limit
            LOGGER.warning(
                f"minimum potential was above upper limit, setting to {upper_limit}"
            )

        LOGGER.info(f"minimum potential was: {result}")
        await active.enqueue_data_dflt(datadict={"result": result})
        active.action.action_params["min_offset_ocv"] = result
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/check_CP_Ewe_bounds", tags=["action"])
    @action_version(2)
    async def check_CP_Ewe_bounds(
        CP_Ewe_V__mean_final: float | bool = False,
        limted_Ewe_V__mean_final: float | bool = False,
        lower_limit: float = -1,
        upper_limit: float = 3,
    ):
        """Clamp the trailing-mean CP Ewe to ``[lower_limit, upper_limit]``.

        Reads ``CP_Ewe_V__mean_final`` from the inherited action params,
        substitutes ``0.4`` when missing, clamps it to the configured bounds
        and stores the clamped value back as ``CP_Ewe_V__mean_final``.
        """
        active = await app.base.setup_and_contain_action(action_abbr="CheckCPEweBounds")

        try:
            Ewe_V__mean_final = active.action.action_params["CP_Ewe_V__mean_final"]
            if not isinstance(Ewe_V__mean_final, (int, float, np.floating)):
                LOGGER.warning(
                    f"Ewe_V__mean_final not found in global params, setting to 0.4, value was: {Ewe_V__mean_final}"
                )
                Ewe_V__mean_final = 0.4

            else:
                Ewe_V__mean_final = Ewe_V__mean_final
        except Exception as e:
            LOGGER.error(f"Error getting global params: {e}")
            print(
                f"Error getting global params in calc_server.py, try perhaps the host details set here are wrong: {e}"
            )
        if Ewe_V__mean_final < lower_limit:
            limted_Ewe_V__mean_final = lower_limit
            LOGGER.info(
                f"Ewe_V__mean_final was below lower limit, setting to {lower_limit}"
            )
        elif Ewe_V__mean_final > upper_limit:
            limted_Ewe_V__mean_final = upper_limit
            LOGGER.info(
                f"Ewe_V__mean_final was above upper limit, setting to {upper_limit}"
            )
        else:
            limted_Ewe_V__mean_final = Ewe_V__mean_final
        await active.enqueue_data_dflt(
            datadict={"CP_Ewe_V__mean_final": limted_Ewe_V__mean_final}
        )
        active.action.action_params["CP_Ewe_V__mean_final"] = limted_Ewe_V__mean_final
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
