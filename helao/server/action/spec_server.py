# shell: uvicorn motion_server:app --reload
""" Spectrometer server

Spec server handles setup and configuration for spectrometer devices. Hardware triggers
are the preferred method for synchronizing spectral capture with illumination source.
"""

__all__ = ["makeApp"]

from typing import Optional
from fastapi import Body
from helaocore.schema import Action
from helaocore.server.base import makeActionServ
from helao.driver.spec.spectral_products import SM303
from helaocore.helper.config_loader import config_loader


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

    @app.post(f"/{servKey}/measure")
    async def measure_spec(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        int_time: Optional[int] = 35,
    ):
        """Measure single spectrum."""
        active = await app.base.setup_and_contain_action(action_abbr="OPT")
        pars = {k:v for k,v in active.action.action_params.items() if k!='action_version'}
        spectrum = app.driver.measure_spec(**pars)
        _ = await active.finish()
        return spectrum

    @app.post(f"/{servKey}/measure_adv")
    async def measure_spec_adv(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        int_time: Optional[int] = 35,
        n_avg: Optional[int] = 1,
        fft: Optional[int] = 0,
    ):
        """Measure single spectrum."""
        active = await app.base.setup_and_contain_action(action_abbr="OPT")
        pars = {k:v for k,v in active.action.action_params.items() if k!='action_version'}
        spectrum = app.driver.measure_spec_adv(**pars)
        _ = await active.finish()
        return spectrum

    return app
