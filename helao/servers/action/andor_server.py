# shell: uvicorn motion_server:app --reload
""" A FastAPI service definition for a potentiostat device server, e.g. Gamry.

andor_server uses the Executor model with helao.drivers.spec.andor.driver which decouples
the hardware driver class from the action server base class.

"""

__all__ = ["makeApp"]


import time

from fastapi import Body

from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.core.models.file import HloHeaderModel

from helao.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from helao.helpers.config_loader import CONFIG
from helao.helpers.executor import Executor
from helao.helpers import helao_logging as logging  # get LOGGER from BaseAPI instance
from helao.drivers.spec.andor.driver import AndorDriver, DriverStatus

global LOGGER
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER


class AndorCooling(Executor):
    """Handle cooling and warmup of Andor camera."""

    driver: AndorDriver

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.poll_rate = 5  # pump events every 100 millisecond
            self.start_time = time.time()

            # link attrs for convenience
            self.action_params = self.active.action.action_params
            self.driver = self.active.driver
            self.cam = self.driver.cam

            # no external timer, event sink signals end of measurement
            self.duration = -1

            self.timeout = self.action_params.get("timeout", 600)
            self.cooldown = self.action_params.get("cooldown", True)

            LOGGER.info("AndorCooling initialized.")
        except Exception:
            LOGGER.error("AndorCooling was not initialized.", exc_info=True)

    async def _exec(self) -> dict:
        """Set SensorCooling flag and wait for stabilization."""
        LOGGER.debug(f"setting cam.SensorCooling = {self.cooldown}")
        resp = self.driver.set_cooldown(self.cooldown)
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
        return {"error": error}

    async def _poll(self) -> dict:
        """Return data and status from dtaq event sink."""
        resp = self.driver.check_temperature()

        if not resp.data:
            return {"error": ErrorCodes.critical_error, "status": HloStatus.errored}

        sensor_temp = resp.data["temp"]
        temp_status = resp.data["status"]
        LOGGER.info("Temperature: {:.5f}C".format(sensor_temp))
        LOGGER.info("Status: '{}'".format(temp_status))

        if temp_status == "Fault":
            return {"error": ErrorCodes.critical_error, "status": HloStatus.errored}

        status = HloStatus.active
        if temp_status == "Stabilised":
            if (sensor_temp < 20 and self.cooldown) or not self.cooldown:
                status = HloStatus.finished

        error = ErrorCodes.none
        return {
            "error": error,
            "status": status,
            "data": {"sensor_temp__C": sensor_temp},
        }


class AndorAdjustND(Executor):
    """Auto-select ND filter with maximum optimality."""

    driver: AndorDriver

    async def _exec(self) -> dict:
        """Run ND filter adjustment routine."""
        LOGGER.debug("Running driver.adjust_ND()")
        resp = self.driver.adjust_ND()
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
        return {"error": error, "data": resp.data}


class AndorAcquire(Executor):
    """Acquire data with external start trigger."""

    driver: AndorDriver

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.poll_rate = 0.1  # pump events every 100 millisecond
            self.start_time = time.time()

            # link attrs for convenience
            self.action_params = self.active.action.action_params
            self.active.action.action_params['action_path']=str(self.active.action.action_output_dir)

            self.driver = self.active.driver

            self.external_trigger = self.action_params["external_trigger"]
            self.duration = self.action_params["duration"]
            self.timeout = self.action_params["timeout"]
            self.frames_per_poll = self.action_params["frames_per_poll"]
            self.buffer_count = self.action_params["buffer_count"]
            self.exp_time = self.action_params["exp_time"]
            self.framerate = self.action_params["framerate"]

            self.first_tick = None

            LOGGER.info("AndorAcquire initialized.")
        except Exception:
            LOGGER.error("AndorAcquire was not initialized.", exc_info=True)

    async def _pre_exec(self) -> dict:
        """Setup potentiostat device for given technique."""
        resp = self.driver.setup(exp_time=self.exp_time, framerate=self.framerate)
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.setup
        return {"error": error}

    async def _exec(self) -> dict:
        """Set trigger to wait for measurement start."""
        try:
            LOGGER.debug("setting trigger")
            resp = self.driver.set_trigger(self.external_trigger)
            error = (
                ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
            )
        except Exception:
            error = ErrorCodes.critical_error
            LOGGER.error("Error setting trigger", exc_info=True)
        return {"error": error}

    async def _poll(self) -> dict:
        """Return data and status from dtaq event sink."""
        resp = self.driver.get_data(
            frames=self.frames_per_poll, total_duration=self.duration, external=self.external_trigger, first_tick=self.first_tick
        )
        if not resp.data:
            LOGGER.info("No data received.")
            return {"error": ErrorCodes.none, "status": HloStatus.active}
        if self.first_tick is None:
            self.first_tick = resp.data["tick_time"][0]
        latest_tick = resp.data["tick_time"][-1]
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
        if resp.status == DriverStatus.ok:
            status = HloStatus.finished
        else:
            status = (
                HloStatus.active
                if resp.status == DriverStatus.busy
                and latest_tick - self.first_tick < self.duration
                else HloStatus.finished
            )
        return {"error": error, "status": status, "data": resp.data}

    async def _post_exec(self):
        resp = self.driver.cleanup()

        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
        return {"error": error, "data": {}}


async def andor_dyn_endpoints(app=None):
    server_key = app.base.server.server_name
    app.base.server_params["allow_concurrent_actions"] = False

    @app.post(f"/{server_key}/acquire", tags=["action"])
    async def acquire(
        action: Action = Body({}, embed=True),
        action_version: int = 2,
        external_trigger: bool = True,
        duration: float = 10.0,
        frames_per_poll: int = 100,
        buffer_count: int = 10,
        exp_time: float = 0.0098,
        framerate: float = 98,
        timeout: float = 5000,
    ):
        data_keys = ["elapsed_time_s"] + [
            f"ch_{i:04}" for i in range(app.driver.wl_arr.shape[0])
        ]
        active = await app.base.setup_and_contain_action(
            json_data_keys=data_keys,
            file_type="andor_helao__file",
            # to reduce polling data size, we get the wl_arr directly from the driver
            hloheader=HloHeaderModel(
                action_name=action.action_name,
                column_headings=data_keys,
                optional={"wl": list(app.driver.wl_arr)},
            ),
        )

        # decide on abbreviated action name
        active.action.action_abbr = "ANDORSPEC"
        executor = AndorAcquire(active=active, oneoff=False)
        active_action_dict = active.start_executor(executor)

        return active_action_dict

    @app.post(f"/{server_key}/cancel_acquire", tags=["action"])
    async def cancel_acquire(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Stop sleep action."""
        active = await app.base.setup_and_contain_action()
        for exec_id, executor in app.base.executors.items():
            if exec_id.split()[0] == "acquire":
                executor.stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/cooling", tags=["action"])
    async def cooling(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        cooldown: bool = True,
        timeout: int = 600,
    ):
        active = await app.base.setup_and_contain_action()
        executor = AndorCooling(
            active=active, oneoff=False, cooldown=cooldown, timeout=timeout
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/adjust_nd", tags=["action"])
    async def adjust_nd(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        active = await app.base.setup_and_contain_action()
        executor = AndorAdjustND(active=active, oneoff=True)
        active_action_dict = active.start_executor(executor)
        return active_action_dict


def makeApp(server_key):

    config = CONFIG

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Andor camera/action server",
        version=0.1,
        driver_classes=[AndorDriver],
        dyn_endpoints=andor_dyn_endpoints,
    )

    @app.post("/stop_private", tags=["private"])
    def stop_private():
        """Calls driver stop method."""
        app.driver.stop()

    return app
