"""Gaussian-process simulation server.

Hosts :class:`GPSim`, which maintains per-plate GP surrogates over a subset
of CP data from https://doi.org/10.1039/C8MH01641K . Exposes actions to
(re)initialize a plate's priors, pick the next EI composition, refit the
surrogate (driven by :class:`GPSimExec`), report progress, and evaluate the
active-learning stop condition.
"""

__all__ = ["makeApp"]

from typing import Union

from helao.core.servers.base_api import BaseAPI
from helao.helpers import helao_logging as logging

from ...drivers.data.gpsim_driver import GPSim, GPSimExec

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def makeApp(server_key):
    """Build the GP-simulator FastAPI app.

    Wires :class:`GPSim` into a :class:`BaseAPI` and exposes actions
    ``initialize_global``, ``initialize_plate``, ``get_progress``,
    ``acquire_point``, ``update_model`` (uses :class:`GPSimExec`), and
    ``check_condition``, plus private endpoints for clearing per-plate or
    global state.

    Args:
        server_key: Server name in the launched config.

    Returns:
        Configured :class:`HelaoFastAPI` app.
    """
    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="GP simulator",
        version=1.0,
        driver_classes=[GPSim],
    )

    @app.post(f"/{server_key}/initialize_global", tags=["action"])
    async def initialize_global(
        num_random_points: int = 5,
        random_seed: int = 9999,
    ):
        """Reset all per-plate state and global acquisition history."""
        active = await app.base.setup_and_contain_action()
        app.driver.clear_global()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/initialize_plate", tags=["action"])
    async def initialize_plate(
        plate_id: int = 0,
        num_random_points: int = 5,
        reinitialize: bool = False,
    ):
        """Seed random priors for a plate and fit its surrogate."""
        active = await app.base.setup_and_contain_action()
        pid = active.action.action_params["plate_id"]
        reinit = active.action.action_params["reinitialize"]
        npoints = active.action.action_params["num_random_points"]
        if not app.driver.initialized[pid] or reinit:
            LOGGER.info(
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
        plate_id: int = 0,
    ):
        """Return the latest progress record for a plate, refitting if empty."""
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
        plate_id: int = 0,
    ):
        """Pick the next EI composition for a plate and stamp it on the action."""
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
        plate_id: int = 0,
    ):
        """Refit the surrogate model for a plate via :class:`GPSimExec`."""
        active = await app.base.setup_and_contain_action()
        active.action.action_params["orch_str"] = (
            f"{active.action.orch_key} {active.action.orch_host}:{active.action.orch_port}"
        )
        active.action.action_abbr = "GPSIM"
        executor = GPSimExec(
            active=active,
            oneoff=True,
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/check_condition", tags=["action"])
    async def check_condition(
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
        """Evaluate the active-learning stop condition and requeue if unmet."""
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
