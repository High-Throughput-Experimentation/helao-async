""" GP simulation server

FastAPI server host for the GP modeling simulator.

Loads a subset of 3 mA/cm2 CP measurement data from https://doi.org/10.1039/C8MH01641K

"""

__all__ = ["makeApp"]

from typing import List
from fastapi import Body

from helao.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from helao.helpers.config_loader import config_loader
from helao.drivers.data.oergpsim_driver import OerGPSim, OerGPExec


def makeApp(confPrefix, server_key, helao_root):
    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="GP simulator",
        version=1.0,
        driver_class=OerGPSim,
    )

    @app.post(f"/{server_key}/update_model", tags=["action"])
    async def update_model(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        comp_vec: List[float] = [],
        plate_id: int = 0,
    ):
        """Record simulated data."""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "SIMGP"
        executor = OerGPExec(
            active=active,
            oneoff=True,
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post("/clear_plate", tags=["private"])
    def clear_plate(plate_id: int):
        return app.driver.clear_plate(plate_id)

    @app.post("/clear_global", tags=["private"])
    def clear_global():
        return app.driver.clear_global()

    @app.post("/progress", tags=["private"])
    def progress(plate_id: int):
        return app.driver.progress[plate_id]

    return app
