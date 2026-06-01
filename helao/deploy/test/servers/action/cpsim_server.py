"""Chronopotentiometry simulation server.

Hosts :class:`CPSim`, which replays a subset of 3 mA/cm^2 CP measurements
from https://doi.org/10.1039/C8MH01641K . The server exposes actions for
running a simulated CP (``measure_cp``/``cancel_measure_cp``), switching
plates (``change_plate``), and reporting the loaded plate together with
the requesting orchestrator's coordinates (``get_loaded_plate``).
"""

__all__ = ["makeApp"]

from typing import List
from fastapi import Body

from helao.core.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from ...drivers.pstat.cpsim_driver import CPSim, CPSimExec


def makeApp(server_key):
    """Build the CP-simulator FastAPI app.

    Wires :class:`CPSim` into a :class:`BaseAPI` and registers actions:
    ``measure_cp`` and ``cancel_measure_cp`` (driven by :class:`CPSimExec`),
    ``get_loaded_plate``, and ``change_plate``, plus private listing
    endpoints.

    Args:
        server_key: Server name in the launched config.

    Returns:
        Configured :class:`HelaoFastAPI` app.
    """
    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="OER CP simulator",
        version=1.0,
        driver_classes=[CPSim],
    )

    @app.post(f"/{server_key}/measure_cp", tags=["action"])
    async def measure_cp(
        comp_vec: List[int] = [],
        acquisition_rate: float = 0.2,
    ):
        """Start a :class:`CPSimExec` that streams the stored CP for ``comp_vec``."""
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
    ):
        """Stop any running ``measure_cp`` executor."""
        active = await app.base.setup_and_contain_action()
        for exec_id, executor in app.base.executors.items():
            if exec_id.split()[0] == "measure_cp":
                executor.stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/get_loaded_plate", tags=["action"])
    async def get_loaded_plate(
    ):
        """Return the loaded plate id plus the requesting orchestrator's coords."""
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
        plate_id: int = 0,
    ):
        """Switch the simulator to a different plate."""
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
