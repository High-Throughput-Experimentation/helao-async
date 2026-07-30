# shell: uvicorn motion_server:app --reload
"""Andor spectrograph/camera action server.

Wraps :class:`AndorDriver` and exposes acquisition, cooling and ND-filter
adjustment endpoints. Uses the :class:`Executor` model so the hardware driver
remains decoupled from the action-server base class.
"""

__all__ = ["makeApp"]


import time

from helao.core.error import ErrorCodes
from helao.core.models.file import HloHeaderModel
from helao.core.models.hlostatus import HloStatus
from helao.core.servers.base_api import BaseAPI, action_version
from helao.helpers import helao_logging as logging  # get LOGGER from BaseAPI instance
from helao.helpers.executor import Executor

from ...drivers.spec.andor.driver import AndorDriver, DriverStatus

global LOGGER
LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class AndorCooling(Executor):
    """Executor that drives the Andor sensor to its cool or warm setpoint.

    Sets ``SensorCooling`` on the camera in ``_exec`` and polls the temperature
    in ``_poll`` until the sensor reports ``Stabilised`` (and is sufficiently
    cold when cooling). Has no fixed duration; ``_poll`` terminates the run.
    """

    driver: AndorDriver

    def __init__(self, *args, **kwargs):
        """Initialise the cooling executor from the active action parameters.

        Reads ``timeout`` and ``cooldown`` from ``action_params`` and links
        convenience handles to the driver and its camera object.
        """
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
        """Toggle ``SensorCooling`` on the camera to the requested state."""
        LOGGER.debug(f"setting cam.SensorCooling = {self.cooldown}")
        resp = self.driver.set_cooldown(self.cooldown)
        error = (
            ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
        )
        return {"error": error}

    async def _poll(self) -> dict:
        """Read the current sensor temperature and decide when to finish.

        Returns finished status once the camera reports ``Stabilised`` and the
        temperature is below 20C (when cooling) or as soon as it is stabilised
        when warming up; faults are surfaced as errored status.
        """
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
    """Executor that runs the driver's ND-filter auto-selection routine.

    One-shot executor: ``_exec`` invokes :meth:`AndorDriver.adjust_ND` and
    returns its result data.
    """

    driver: AndorDriver

    async def _exec(self) -> dict:
        """Call :meth:`AndorDriver.adjust_ND` and forward its data payload."""
        LOGGER.debug("Running driver.adjust_ND()")
        resp = self.driver.adjust_ND()
        error = (
            ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
        )
        return {"error": error, "data": resp.data}


class AndorAcquire(Executor):
    """Executor that acquires spectra from the Andor camera.

    Configures exposure/framerate in ``_pre_exec``, arms the trigger in
    ``_exec``, pulls frames in ``_poll`` until either the requested duration
    elapses or the driver reports completion, and tears down via
    ``_post_exec``. Supports external triggering.
    """

    driver: AndorDriver

    def __init__(self, *args, **kwargs):
        """Initialise acquisition executor from the active action parameters.

        Reads ``external_trigger``, ``duration``, ``timeout``,
        ``frames_per_poll``, ``buffer_count``, ``exp_time`` and ``framerate``
        from ``action_params`` and records the action output directory.
        """
        super().__init__(*args, **kwargs)
        try:
            self.poll_rate = 0.1  # pump events every 100 millisecond
            self.start_time = time.time()

            # link attrs for convenience
            self.action_params = self.active.action.action_params
            self.active.action.action_params["action_path"] = str(
                self.active.action.action_output_dir
            )

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
        """Configure exposure time and framerate on the camera."""
        resp = self.driver.setup(exp_time=self.exp_time, framerate=self.framerate)
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.setup
        return {"error": error}

    async def _exec(self) -> dict:
        """Arm the camera trigger (external or internal) to start acquisition."""
        try:
            LOGGER.debug("setting trigger")
            resp = self.driver.set_trigger(self.external_trigger)
            error = (
                ErrorCodes.none
                if resp.response == "success"
                else ErrorCodes.critical_error
            )
        except Exception:
            error = ErrorCodes.critical_error
            LOGGER.error("Error setting trigger", exc_info=True)
        return {"error": error}

    async def _poll(self) -> dict:
        """Pull a batch of frames from the camera and decide whether to finish.

        Finished status is returned when the driver reports ``ok`` or when the
        elapsed tick interval exceeds ``duration``.
        """
        resp = self.driver.get_data(
            frames=self.frames_per_poll,
            total_duration=self.duration,
            external=self.external_trigger,
            first_tick=self.first_tick,
        )
        if not resp.data:
            LOGGER.info("No data received.")
            return {"error": ErrorCodes.none, "status": HloStatus.active}
        if self.first_tick is None:
            self.first_tick = resp.data["tick_time"][0]
        latest_tick = resp.data["tick_time"][-1]
        error = (
            ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
        )
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

    async def _post_exec(self) -> dict:
        """Run :meth:`AndorDriver.cleanup` to release camera resources."""
        resp = self.driver.cleanup()

        error = (
            ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
        )
        return {"error": error, "data": {}}


async def andor_dyn_endpoints(app: BaseAPI):
    """Register Andor action endpoints on ``app`` after the driver is ready.

    Disables concurrent actions on this server and attaches the ``acquire``,
    ``cancel_acquire``, ``cooling`` and ``adjust_nd`` POST routes.

    Args:
        app: The :class:`BaseAPI` instance being constructed by ``makeApp``.
    """
    server_key = app.base.server.server_name
    app.base.server_params["allow_concurrent_actions"] = False

    # P3a-2 constructor-connect fix: AndorDriver.__init__ no longer opens the
    # camera (disconnected construct); open it here at startup before any
    # acquire request reads app.driver.wl_arr.
    connect_resp = app.driver.connect()
    LOGGER.info(f"Andor connect() returned status={connect_resp.status}")

    @app.post(f"/{server_key}/acquire", tags=["action"])
    @action_version(2)
    async def acquire(
        external_trigger: bool = True,
        duration: float = 10.0,
        frames_per_poll: int = 100,
        buffer_count: int = 10,
        exp_time: float = 0.0098,
        framerate: float = 98,
        timeout: float = 5000,
    ):
        """Start a spectrum acquisition via :class:`AndorAcquire`.

        Channel columns ``ch_0000..ch_NNNN`` carry per-pixel intensities and the
        ``wl`` array from the driver is embedded in the file header.
        """
        data_keys = ["elapsed_time_s"] + [
            f"ch_{i:04}" for i in range(app.driver.wl_arr.shape[0])
        ]
        active = await app.base.setup_and_contain_action(
            json_data_keys=data_keys,
            file_type="andor_helao__file",
            # to reduce polling data size, we get the wl_arr directly from the driver
            hloheader=HloHeaderModel(
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
    async def cancel_acquire():
        """Stop any running ``acquire`` executor on this server."""
        active = await app.base.setup_and_contain_action()
        for exec_id, executor in app.base.executors.items():
            if exec_id.split()[0] == "acquire":
                executor.stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/cooling", tags=["action"])
    async def cooling(
        cooldown: bool = True,
        timeout: int = 600,
    ):
        """Cool or warm the Andor sensor using :class:`AndorCooling`."""
        active = await app.base.setup_and_contain_action()
        executor = AndorCooling(
            active=active, oneoff=False, cooldown=cooldown, timeout=timeout
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/adjust_nd", tags=["action"])
    async def adjust_nd():
        """Run the ND-filter auto-selection routine via :class:`AndorAdjustND`."""
        active = await app.base.setup_and_contain_action()
        executor = AndorAdjustND(active=active, oneoff=True)
        active_action_dict = active.start_executor(executor)
        return active_action_dict


def makeApp(server_key) -> BaseAPI:
    """Build the Andor camera FastAPI app.

    Constructs a :class:`BaseAPI` backed by :class:`AndorDriver` and uses
    :func:`andor_dyn_endpoints` to register the action endpoints once the
    driver finishes initialising.

    Args:
        server_key: Key identifying this server in the orchestration group.

    Returns:
        The configured :class:`BaseAPI` application.
    """

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Andor camera/action server",
        version=0.1,
        driver_classes=[AndorDriver],
        dyn_endpoints=andor_dyn_endpoints,
    )
    app.driver: AndorDriver  # type hint for convenience

    @app.post("/stop_private", tags=["private"])
    def stop_private():
        """Invoke :meth:`AndorDriver.stop` to halt the camera."""
        app.driver.stop()

    return app
