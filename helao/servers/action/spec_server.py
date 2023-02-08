# shell: uvicorn motion_server:app --reload
""" Spectrometer server

Spec server handles setup and configuration for spectrometer devices. Hardware triggers
are the preferred method for synchronizing spectral capture with illumination source.
"""

__all__ = ["makeApp"]

import asyncio
import time
from typing import Optional, List
from fastapi import Body
from helao.helpers.premodels import Action
from helao.servers.base import HelaoBase
from helaocore.models.sample import SampleUnion
from helaocore.models.file import HloHeaderModel
from helao.drivers.spec.spectral_products_driver import SM303
from helao.helpers.config_loader import config_loader

from helao.drivers.io.enum import TriggerType


def makeApp(confPrefix, server_key, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = HelaoBase(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Spectrometer server",
        version=0.1,
        driver_class=SM303,
    )

    @app.post(f"/{server_key}/acquire_spec", tags=["action"])
    async def acquire_spec(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        fast_samples_in: Optional[List[SampleUnion]] = Body([], embed=True),
        int_time_ms: Optional[int] = 35,
        duration_sec: Optional[
            float
        ] = -1,  # measurements longer than HTTP timeout should use acquire_spec_extrig
    ):
        """Acquire one or more spectrum if duration is positive."""
        # app.base.print_message("!!! Starting acquire_spec action.")
        spec_header = {"wl": app.driver.pxwl}
        active = await app.base.setup_and_contain_action(
            action_abbr="OPT", hloheader=HloHeaderModel(optional=spec_header)
        )
        # app.base.print_message("!!! acquire_spec action is active.")
        starttime = time.time()
        # acquire at least 1 spectrum
        specdict = app.driver.acquire_spec_adv(**active.action.action_params)
        await active.enqueue_data_dflt(datadict=specdict)
        # duration loop
        while time.time() - starttime < duration_sec:
            specdict = app.driver.acquire_spec_adv(**active.action.action_params)
            await active.enqueue_data_dflt(datadict=specdict)
        # wait 1 second to capture dangling data messages
        await asyncio.sleep(1)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/acquire_spec_adv", tags=["action"])
    async def acquire_spec_adv(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        fast_samples_in: Optional[List[SampleUnion]] = Body([], embed=True),
        int_time_ms: Optional[int] = 35,
        duration_sec: Optional[
            float
        ] = -1,  # measurements longer than HTTP timeout should use acquire_spec_extrig
        n_avg: Optional[int] = 1,
        fft: Optional[int] = 0,
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
        while time.time() - starttime < duration_sec:
            specdict = app.driver.acquire_spec_adv(**active.action.action_params)
            await active.enqueue_data_dflt(datadict=specdict)
        # wait 1 second to capture dangling data messages
        await asyncio.sleep(1)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/acquire_spec_extrig", tags=["action"])
    async def acquire_spec_extrig(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        fast_samples_in: Optional[List[SampleUnion]] = Body([], embed=True),
        edge_mode: Optional[TriggerType] = TriggerType.risingedge,
        int_time: Optional[int] = 35,
        n_avg: Optional[int] = 1,
        fft: Optional[int] = 0,
        duration: Optional[float] = -1,
    ):
        """Acquire spectra based on external trigger."""
        A = await app.base.setup_action()
        A.action_abbr = "OPT"
        # app.base.print_message("Setting up external trigger.", info=True)
        active_dict = await app.driver.acquire_spec_extrig(A)
        # app.base.print_message("External trigger task initiated.", info=True)
        return active_dict

    @app.post(f"/{server_key}/stop_extrig_after", tags=["action"])
    async def stop_extrig(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        delay: int = 0,
    ):
        """Acquire spectra based on external trigger."""
        active = await app.base.setup_and_contain_action()
        await app.driver.stop(delay=active.action.action_params["delay"])
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
