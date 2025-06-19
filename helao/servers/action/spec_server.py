# shell: uvicorn motion_server:app --reload
"""Spectrometer server

Spec server handles setup and configuration for spectrometer devices. Hardware triggers
are the preferred method for synchronizing spectral capture with illumination source.
"""

__all__ = ["makeApp"]

import asyncio
import time
from typing import Optional, List, Union
from fastapi import Body
from helao.helpers.premodels import Action
from helao.servers.base_api import BaseAPI
from helao.core.models.sample import (
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
)
from helao.core.models.file import HloHeaderModel
from helao.drivers.spec.spectral_products_driver import SM303
from helao.helpers.config_loader import CONFIG

from helao.drivers.io.enum import TriggerType

from helao.helpers import helao_logging as logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER


async def sm303_dyn_endpoints(app=None):
    server_key = app.base.server.server_name
    app.base.server_params["allow_concurrent_actions"] = False

    @app.post("/get_wl", tags=["private"])
    def get_wl():
        """Return spectrometer wavelength array; shape = (num_pixels)"""
        return app.driver.pxwl  # type: ignore

    @app.post(f"/{server_key}/acquire_spec", tags=["action"])
    async def acquire_spec(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        int_time_ms: int = 35,
        duration_sec: Optional[
            float
        ] = -1,  # measurements longer than HTTP timeout should use acquire_spec_extrig
    ):
        """Acquire one or more spectrum if duration is positive."""
        LOGGER.info("!!! Starting acquire_spec action.")
        spec_header = {"wl": app.driver.pxwl}  # type: ignore
        active = await app.base.setup_and_contain_action(
            action_abbr="OPT", hloheader=HloHeaderModel(optional=spec_header)
        )
        LOGGER.info("!!! acquire_spec action is active.")
        starttime = time.time()
        # acquire at least 1 spectrum
        specdict = app.driver.acquire_spec_adv(**active.action.action_params)  # type: ignore
        await active.enqueue_data_dflt(datadict=specdict)
        # duration loop
        while time.time() - starttime < active.action.action_params["duration_sec"]:
            specdict = app.driver.acquire_spec_adv(**active.action.action_params)
            await active.enqueue_data_dflt(datadict=specdict)
        # wait 1 second to capture dangling data messages
        await asyncio.sleep(1)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/acquire_spec_adv", tags=["action"])
    async def acquire_spec_adv(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        int_time_ms: int = 35,
        duration_sec: Optional[
            float
        ] = -1,  # measurements longer than HTTP timeout should use acquire_spec_extrig
        n_avg: int = 1,
        fft: int = 0,
        peak_lower_wl: Optional[float] = None,
        peak_upper_wl: Optional[float] = None,
    ):
        """Acquire N spectra and average."""
        spec_header = {"wl": app.driver.pxwl}
        active = await app.base.setup_and_contain_action(
            action_abbr="OPT", hloheader=HloHeaderModel(optional=spec_header)
        )
        starttime = time.time()
        # acquire at least 1 spectrum
        specdict = app.driver.acquire_spec_adv(**active.action.action_params)
        await active.enqueue_data_dflt(datadict=specdict)
        # duration loop
        while time.time() - starttime < active.action.action_params["duration_sec"]:
            specdict = app.driver.acquire_spec_adv(**active.action.action_params)
            await active.enqueue_data_dflt(datadict=specdict)

        active.action.action_params["peak_intensity"] = specdict.get(
            "peak_intensity", None
        )
        # wait 0.1 second to capture dangling data messages
        await asyncio.sleep(0.1)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/calibrate_intensity", tags=["action"])
    async def calibrate_intensity(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        int_time_ms: int = 35,
        n_avg: int = 3,
        peak_lower_wl: Optional[float] = 400,
        peak_upper_wl: Optional[float] = 750,
        target_peak_min: Optional[float] = 30000,
        target_peak_max: Optional[float] = 32000,
        max_iters: int = 5,
        max_integration_time: int = 150,
    ):
        """Calibrate integration time to achieve peak intensity window."""
        spec_header = {"wl": app.driver.pxwl}
        active = await app.base.setup_and_contain_action(
            action_abbr="OPT", hloheader=HloHeaderModel(optional=spec_header)
        )
        current_int_time = active.action.action_params["int_time_ms"]
        specdict = app.driver.acquire_spec_adv(**active.action.action_params)
        await active.enqueue_data_dflt(datadict=specdict)
        peak_int = specdict["peak_intensity"]
        LOGGER.info(f"Initial peak intensity: {peak_int}")
        target_avg = 0.5 * (
            active.action.action_params["target_peak_max"]
            + active.action.action_params["target_peak_min"]
        )
        adjust_count = 0
        max_reached = False
        while (
            (
                (peak_int < active.action.action_params["target_peak_min"])
                or (peak_int > active.action.action_params["target_peak_max"])
            )
            and adjust_count < active.action.action_params["max_iters"]
            and not max_reached
        ):
            if peak_int < active.action.action_params["target_peak_min"]:
                current_int_time = int(current_int_time * target_avg / peak_int)
            else:
                current_int_time = int(current_int_time * peak_int / target_avg)

            if current_int_time > active.action.action_params["max_integration_time"]:
                current_int_time = active.action.action_params["max_integration_time"]
                max_reached = True
            LOGGER.info(f"Adjusting integration time to: {current_int_time} ms")
            spec_params = active.action.action_params
            spec_params.update({"int_time_ms": current_int_time})
            specdict = app.driver.acquire_spec_adv(**spec_params)
            await active.enqueue_data_dflt(datadict=specdict)
            peak_int = specdict["peak_intensity"]
            LOGGER.info(f"Current peak intensity: {peak_int}")
            adjust_count += 1

        active.action.action_params["peak_intensity"] = peak_int
        active.action.action_params["calibrated_int_time_ms"] = current_int_time
        # wait 0.1 second to capture dangling data messages
        await asyncio.sleep(0.1)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/acquire_spec_extrig", tags=["action"])
    async def acquire_spec_extrig(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        edge_mode: TriggerType = TriggerType.risingedge,
        int_time: int = 35,
        n_avg: int = 1,
        fft: int = 0,
        duration: float = -1,
    ):
        """Acquire spectra based on external trigger."""
        A = app.base.setup_action()
        A.action_abbr = "OPT"
        LOGGER.info("Setting up external trigger.")
        active_dict = await app.driver.acquire_spec_extrig(A)
        LOGGER.info("External trigger task initiated.")
        return active_dict

    @app.post(f"/{server_key}/stop_extrig_after", tags=["action"])
    async def stop_extrig_after(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        delay: int = 0,
    ):
        """Acquire spectra based on external trigger."""
        active = await app.base.setup_and_contain_action()
        await app.driver.stop(delay=active.action.action_params["delay"])  # type: ignore
        finished_action = await active.finish()  # type: ignore
        return finished_action.as_dict()


def makeApp(server_key):
    config = CONFIG

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Spectrometer server",
        version=0.1,
        driver_class=SM303,
        dyn_endpoints=sm303_dyn_endpoints,
    )

    return app
