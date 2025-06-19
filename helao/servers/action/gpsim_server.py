""" GP simulation server

FastAPI server host for the GP modeling simulator.

Loads a subset of 3 mA/cm2 CP measurement data from https://doi.org/10.1039/C8MH01641K

"""

__all__ = ["makeApp"]

from typing import Union
from fastapi import Body

from helao.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from helao.helpers.config_loader import config_loader
from helao.drivers.data.gpsim_driver import GPSim, GPSimExec

from helao.helpers import helao_logging as logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

def makeApp(confPrefix, server_key, helao_root):
    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="GP simulator",
        version=1.0,
        driver_classes=[GPSim],
    )

    @app.post(f"/{server_key}/initialize_global", tags=["action"])
    async def initialize_global(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        num_random_points: int = 5,
        random_seed: int = 9999,
    ):
        active = await app.base.setup_and_contain_action()
        app.driver.clear_global()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/initialize_plate", tags=["action"])
    async def initialize_plate(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plate_id: int = 0,
        num_random_points: int = 5,
        reinitialize: bool = False,
    ):
        active = await app.base.setup_and_contain_action()
        pid = active.action.action_params["plate_id"]
        reinit = active.action.action_params["reinitialize"]
        npoints = active.action.action_params["num_random_points"]
        if not app.driver.initialized[pid] or reinit:
            app.base.print_message(
                f"initializing priors for plate {pid} with {npoints} random points"
            )
            await app.driver.init_priors_random(pid, npoints)
            app.driver.fit_model(pid)
        else:
            LOGGER.info(f"plate {pid} is already initialized")
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/get_progress", tags=["action"])
    async def get_progress(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plate_id: int = 0,
    ):
        active = await app.base.setup_and_contain_action()
        progress = app.driver.progress[active.action.action_params["plate_id"]]
        if not progress:
            app.driver.fit_model(active.action.action_params["plate_id"])
        progress = app.driver.progress[active.action.action_params["plate_id"]]
        active.action.action_params.update({f"_{k}": v for k, v in progress.items()})
        await active.enqueue_data_dflt(datadict=progress)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/acquire_point", tags=["action"])
    async def acquire_point(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plate_id: int = 0,
    ):
        active = await app.base.setup_and_contain_action()
        data = {}
        orch_string = f"{active.action.orch_key} {active.action.orch_host}:{active.action.orch_port}"
        while data.get("feature", []) == []:
            data = await app.driver.acquire_point(
                plate_id=active.action.action_params["plate_id"],
                init_point=[],
                orch_str=orch_string,
            )
        await active.enqueue_data_dflt(datadict=data)
        active.action.action_params["_feature"] = data["feature"]
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/update_model", tags=["action"])
    async def update_model(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plate_id: int = 0,
    ):
        """Record simulated data."""
        active = await app.base.setup_and_contain_action()
        active.action.action_params[
            "orch_str"
        ] = f"{active.action.orch_key} {active.action.orch_host}:{active.action.orch_port}"
        active.action.action_abbr = "GPSIM"
        executor = GPSimExec(
            active=active,
            oneoff=True,
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/check_condition", tags=["action"])
    async def check_condition(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plate_id: int = 0,
        stop_condition: str = "max_iters",
        thresh_value: Union[float, int] = 10,
        repeat_experiment_name: str = "OERSIM_sub_activelearn",
        repeat_experiment_params: dict = {},
        repeat_experiment_kwargs: dict = {},
        orch_key: str = "",
        orch_host: str = "",
        orch_port: int = 0,
    ):
        active = await app.base.setup_and_contain_action()
        return_dict = await app.driver.check_condition(active)
        await active.enqueue_data_dflt(datadict=return_dict)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post("/clear_plate", tags=["private"])
    def clear_plate(plate_id: int):
        return app.driver.clear_plate(plate_id)

    @app.post("/clear_global", tags=["private"])
    def clear_global():
        return app.driver.clear_global()

    return app
