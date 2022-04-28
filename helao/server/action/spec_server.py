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
        spectrum = app.driver.measure_spec(active.action.action_params["int_time"])
        finished_action = await active.finish()
        return spectrum

    @app.post("/shutdown")
    def post_shutdown():
        pass

    @app.on_event("shutdown")
    def shutdown_event():
        # this code doesn't run
        pass

    return app
