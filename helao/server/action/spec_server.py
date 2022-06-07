# shell: uvicorn motion_server:app --reload
""" Spectrometer server

Spec server handles setup and configuration for spectrometer devices. Hardware triggers
are the preferred method for synchronizing spectral capture with illumination source.
"""

__all__ = ["makeApp"]

from typing import Optional, List
from fastapi import Body
from helaocore.schema import Action
from helaocore.server.base import makeActionServ
from helaocore.model.sample import SampleUnion
from helaocore.model.file import HloHeaderModel
from helao.driver.spec.spectral_products import SM303
from helaocore.helper.config_loader import config_loader

from helao.driver.io.enum import TriggerType

def makeApp(confPrefix, servKey, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = makeActionServ(
        config=config,
        server_key=servKey,
        server_title=servKey,
        description="Spectrometer server",
        version=0.1,
        driver_class=SM303,
    )

    @app.post(f"/{servKey}/acquire_spec")
    async def acquire_spec(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        fast_samples_in: Optional[List[SampleUnion]] = Body([], embed=True),
        int_time: Optional[int] = 35,
    ):
        """Acquire single spectrum."""
        app.base.print_message("!!! Starting acquire_spec action.")
        spec_header = {"wl": app.driver.pxwl}
        active = await app.base.setup_and_contain_action(action_abbr="OPT", hloheader=HloHeaderModel(optional=spec_header))
        app.base.print_message("!!! acquire_spec action is active.")
        specdict = app.driver.acquire_spec_adv(**active.action.action_params)
        await active.enqueue_data_dflt(datadict=specdict)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{servKey}/acquire_spec_adv")
    async def acquire_spec_adv(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        fast_samples_in: Optional[List[SampleUnion]] = Body([], embed=True),
        int_time: Optional[int] = 35,
        n_avg: Optional[int] = 1,
        fft: Optional[int] = 0,
    ):
        """Acquire N spectra and average."""
        spec_header = {"wl": app.driver.pxwl}
        active = await app.base.setup_and_contain_action(action_abbr="OPT", hloheader=HloHeaderModel(optional=spec_header))
        specdict = app.driver.acquire_spec_adv(**active.action.action_params)
        await active.enqueue_data_dflt(datadict=specdict)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{servKey}/acquire_spec_extrig")
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
        active_dict = await app.driver.acquire_spec_extrig(A)
        return active_dict

    @app.post(f"/stop_extrig")
    async def stop_extrig(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Acquire spectra based on external trigger."""
        active = await app.base.setup_and_contain_action()
        _ = await app.driver.stop_continuous_read()
        finished_act = await active.finish()
        return finished_act.as_dict()

    return app
