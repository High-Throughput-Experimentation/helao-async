""" CP simulation server

FastAPI server host for the OER screening simulator.

Loads a subset of 3 mA/cm2 CP measurement data from https://doi.org/10.1039/C8MH01641K

"""

__all__ = ["makeApp"]

from typing import List
from fastapi import Body

from helao.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from helao.drivers.pstat.cpsim_driver import CPSim, CPSimExec


def makeApp(server_key):

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="OER CP simulator",
        version=1.0,
        driver_classes=[CPSim],
    )

    @app.post(f"/{server_key}/measure_cp", tags=["action"])
    async def measure_cp(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        comp_vec: List[int] = [],
        acquisition_rate: float = 0.2,
    ):
        """Record simulated data."""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "CPSIM"
        executor = CPSimExec(
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

    @app.post(f"/{server_key}/get_loaded_plate", tags=["action"])
    async def get_loaded_plate(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        active = await app.base.setup_and_contain_action()
        plate_id = app.driver.loaded_plate
        data_dict = {
            "loaded_plate_id": plate_id,
            "orch_key": app.base.orch_key,
            "orch_host": app.base.orch_host,
            "orch_port": app.base.orch_port,
        }
        active.action.action_params.update({f"_{k}": v for k, v in data_dict.items()})
        await active.enqueue_data_dflt(datadict=data_dict)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/change_plate", tags=["action"])
    async def change_plate(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plate_id: int = 0,
    ):
        active = await app.base.setup_and_contain_action()
        app.driver.change_plate(active.action.action_params["plate_id"])
        loaded_plate_id = app.driver.loaded_plate
        active.action.action_params["_loaded_plate_id"] = loaded_plate_id
        await active.enqueue_data_dflt(datadict={"loaded_plate_id": loaded_plate_id})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post("/list_plates", tags=["private"])
    def list_plates():
        return app.driver.list_plates()

    @app.post("/list_addressable", tags=["private"])
    def list_addressable(limit: int = 10, by_el: bool = False):
        return app.driver.list_addressable(limit, by_el)

    return app
