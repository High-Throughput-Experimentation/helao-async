""" CP simulation server

FastAPI server host for the OER screening simulator.

Loads a subset of 3 mA/cm2 CP measurement data from https://doi.org/10.1039/C8MH01641K

"""

__all__ = ["makeApp"]

from typing import List
from fastapi import Body

from helao.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from helao.helpers.config_loader import config_loader
from helao.drivers.pstat.oersim_driver import OerSim, OerSimExec


def makeApp(confPrefix, server_key, helao_root):
    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="OER CP simulator",
        version=1.0,
        driver_class=OerSim,
    )

    @app.post(f"/{server_key}/measure_cp", tags=["action"])
    async def measure_cp(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        comp_vec: List[float] = [],
        acquisition_rate: float = 0.2,
    ):
        """Record simulated data."""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "EcheCPSim"
        executor = OerSimExec(
            active=active,
            oneoff=False,
            poll_rate=active.action.action_params["acquisition_rate"],
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/cancel_measure_cp", tags=["action"])
    async def cancel_measure_cp(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Stop running measure_cp."""
        active = await app.base.setup_and_contain_action()
        for exec_id, executor in app.base.executors.items():
            if exec_id.split()[0] == "measure_cp":
                executor.stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post("/list_plates", tags=["private"])
    def list_plates():
        return app.driver.list_plates()

    @app.post("/list_addressable", tags=["private"])
    def list_addressable(limit: int = 10, by_el: bool = False):
        return app.driver.list_addressable()

    @app.post("/change_plate", tags=["private"])
    def change_plate(plate_id: int):
        return app.driver.change_plate(plate_id)

    return app
