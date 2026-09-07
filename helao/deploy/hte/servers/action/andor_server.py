# shell: uvicorn motion_server:app --reload
"""Andor spectrograph/camera action server.

Wraps :class:`AndorDriver` and exposes acquisition, cooling, ND-filter
adjustment and lamp wavelength-calibration endpoints. Uses the
:class:`Executor` model so the hardware driver remains decoupled from the
action-server base class.
"""

__all__ = ["makeApp"]


import time

from helao.core.error import ErrorCodes
from helao.core.models.file import HloHeaderModel
from helao.core.models.hlostatus import HloStatus
from helao.hexagon.app.action_context import ActionContext, action_version
from helao.hexagon.app.action_host import ActionHost
from helao.helpers import config_loader
from helao.helpers import helao_logging as logging  # get LOGGER from the host instance
from helao.helpers.executor import Executor

from ...drivers.spec.andor import kr_lines
from ...drivers.spec.andor.calibrated import AndorCalibratedDriver
from ...drivers.spec.andor.driver import AndorDriver, DriverStatus
from ...drivers.spec.andor.spectrograph import AndorSpectrographDriver

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

    driver: AndorSpectrographDriver

    def __init__(self, *args, **kwargs):
        """Bind the driver handle this executor's ``_exec`` needs.

        Without this the endpoint cannot run at all. ``Executor`` defines no
        ``driver`` attribute and no ``__getattr__``, so the class annotation
        above binds nothing at runtime and ``_exec`` raised ``AttributeError``
        on every call -- ``/ANDOR/adjust_nd`` had never worked. ``AndorCooling``
        and ``AndorAcquire`` each bind it in their own ``__init__``; this class
        was the one that did not.
        """
        super().__init__(*args, **kwargs)
        try:
            self.driver = self.active.driver
        except Exception:
            LOGGER.error("AndorAdjustND init failed", exc_info=True)

    async def _exec(self) -> dict:
        """Call :meth:`AndorDriver.adjust_ND` and forward its data payload."""
        LOGGER.debug("Running driver.adjust_ND()")
        resp = self.driver.adjust_ND()
        error = (
            ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
        )
        return {"error": error, "data": resp.data}


class AndorCalibrateWavelength(Executor):
    """Executor that measures a calibration lamp and fits the wavelength axis.

    One-shot: ``_exec`` calls :meth:`AndorDriver.run_wl_calibration` and
    forwards its data payload, which reports whether the fit became the live
    axis on this station.
    """

    driver: AndorDriver

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            # Executor defines no `driver` and no __getattr__, so the class
            # annotation above binds nothing at runtime; _exec would raise
            # AttributeError without this. AndorCooling and AndorAcquire do
            # the same.
            self.driver = self.active.driver
            self.action_params = self.active.action.action_params
            self.anchors = self.action_params.get("anchors") or None
            self.lamp = self.action_params.get("lamp", kr_lines.LAMP_NAME)
            self.n_frames = self.action_params.get("n_frames", 1)
            self.exp_time = self.action_params.get("exp_time", 0.0098)
            self.degree = self.action_params.get("degree", 4)
            self.max_fit_rms_nm = self.action_params.get("max_fit_rms_nm", 0.5)
            # 0 disables the check; the driver takes None for that.
            self.saturation = self.action_params.get("saturation") or None
        except Exception:
            LOGGER.error("AndorCalibrateWavelength init failed", exc_info=True)

    async def _exec(self) -> dict:
        """Call :meth:`AndorDriver.run_wl_calibration` and forward its data."""
        LOGGER.debug("Running driver.run_wl_calibration()")
        resp = self.driver.run_wl_calibration(
            self.anchors,
            lamp=self.lamp,
            n_frames=self.n_frames,
            exp_time=self.exp_time,
            degree=self.degree,
            max_fit_rms_nm=self.max_fit_rms_nm,
            saturation=self.saturation,
            source_action_uuid=str(self.active.action.action_uuid),
        )
        error = (
            ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
        )
        # The failed branch of run_wl_calibration builds a DriverResponse with
        # no `data` at all, so every field here is absent on exactly the path
        # an operator most needs a result on. Reading one unguarded would
        # raise out of the executor and turn a reported failure into a crash.
        return {"error": error, "data": resp.data or {}}


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


async def andor_dyn_endpoints(app: ActionHost):
    """Register Andor action endpoints on ``app`` after the driver is ready.

    Disables concurrent actions on this server and attaches the ``acquire``,
    ``cancel_acquire``, ``cooling``, ``adjust_nd`` and ``calibrate_wl`` POST
    routes. All are registered unconditionally: the frozen route checklist is
    an AST extraction of source, so a decorator wrapped in a config test would
    keep the source surface uniform while the live OpenAPI silently differed
    per station -- a divergence no gate can observe. ``adjust_nd`` refuses at
    runtime instead, on a station with no software-controlled ND wheel.

    Args:
        app: The :class:`ActionHost` instance being constructed by ``makeApp``.
    """
    server_key = app.server.server_name
    app.server_params["allow_concurrent_actions"] = False

    # ActionHost constructs the driver as driver_class(config=server_params)
    # (action_host.py's startup handler), which passes it neither the
    # server's real key nor anything that knows where the station's STATES
    # directory is -- app.driver does not exist until that handler runs, so
    # this cannot be wired any earlier than here. Without it, the wavelength
    # calibration is written to a cwd-relative path and every andor server on
    # a host shares one filename. Must run before connect(): the calibrated
    # variant's connect() reads calibration_file() to load the lamp fit.
    app.driver.server_key = server_key
    app.driver._base_hook = app

    # P3a-2 constructor-connect fix: AndorDriver.__init__ no longer opens the
    # camera (disconnected construct); open it here at startup before any
    # acquire request reads app.driver.wl_arr.
    connect_resp = app.driver.connect()
    LOGGER.info(f"Andor connect() returned status={connect_resp.status}")

    @app.action()
    @action_version(2)
    async def acquire(
        ctx: ActionContext,
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

        Runs whether or not the station has been wavelength-calibrated. When
        it has not, the driver puts the bare channel index in ``wl_arr`` and
        ``wl`` carries ``0..n-1`` instead of nanometres.

        Every action records ``calibrated`` in its params, and that parameter
        is what makes the substitution safe: an uncalibrated run is
        indistinguishable from a real one in the recorded numbers alone, so
        the flag is the only thing that tells them apart afterwards. It is
        written on BOTH paths -- an absent key would be ambiguous, and older
        records predate it.

        Refuses only when the driver has no axis at all, which means
        ``connect()`` never succeeded and there is no camera to read.
        """
        if app.driver.wl_arr is None:
            LOGGER.error(
                "acquire refused: the driver has no wavelength axis at all, "
                "so connect() did not succeed on /%s. This is a camera or "
                "vendor-SDK fault, not a missing calibration -- an "
                "uncalibrated station still acquires, against the channel "
                "index. Check the server's startup log.",
                server_key,
            )
            active = await ctx.begin()
            active.action.error_code = ErrorCodes.critical_error
            finished_action = await active.finish()
            return finished_action.as_dict()

        data_keys = ["elapsed_time_s"] + [
            f"ch_{i:04}" for i in range(app.driver.wl_arr.shape[0])
        ]
        active = await ctx.begin(
            json_data_keys=data_keys,
            file_type="andor_helao__file",
            # to reduce polling data size, we get the wl_arr directly from the driver
            hloheader=HloHeaderModel(
                column_headings=data_keys,
                optional={"wl": list(app.driver.wl_arr)},
            ),
        )

        # Recorded on both paths: `False` says `wl` is the channel index, not
        # nanometres. Written after ctx.begin so it lands in the action params
        # the record keeps, the same way AndorAcquire writes `action_path`.
        active.action.action_params["calibrated"] = bool(
            getattr(app.driver, "wl_calibrated", False)
        )
        if not active.action.action_params["calibrated"]:
            LOGGER.warning(
                "acquiring on /%s without a wavelength calibration: `wl` is "
                "the channel index and this action records calibrated=False",
                server_key,
            )

        # decide on abbreviated action name
        active.action.action_abbr = "ANDORSPEC"
        executor = AndorAcquire(active=active, oneoff=False)
        active_action_dict = active.start_executor(executor)

        return active_action_dict

    @app.action()
    async def cancel_acquire(ctx: ActionContext):
        """Stop any running ``acquire`` executor on this server."""
        active = await ctx.begin()
        for exec_id, executor in app.executors.items():
            if exec_id.split()[0] == "acquire":
                executor.stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.action()
    async def cooling(
        ctx: ActionContext,
        cooldown: bool = True,
        timeout: int = 600,
    ):
        """Cool or warm the Andor sensor using :class:`AndorCooling`."""
        active = await ctx.begin()
        executor = AndorCooling(
            active=active, oneoff=False, cooldown=cooldown, timeout=timeout
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.action()
    async def adjust_nd(ctx: ActionContext):
        """Run the ND-filter auto-selection routine via :class:`AndorAdjustND`."""
        if not isinstance(app.driver, AndorSpectrographDriver):
            LOGGER.error(
                "adjust_nd refused: this station has no software-controlled ND "
                "filter wheel (wl_source=calibration). Set the filter by hand."
            )
            active = await ctx.begin()
            active.action.error_code = ErrorCodes.critical_error
            finished_action = await active.finish()
            return finished_action.as_dict()
        active = await ctx.begin()
        executor = AndorAdjustND(active=active, oneoff=True)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.action()
    async def calibrate_wl(
        ctx: ActionContext,
        anchors: list = [],
        lamp: str = kr_lines.LAMP_NAME,
        n_frames: int = 1,
        exp_time: float = 0.0098,
        degree: int = 4,
        max_fit_rms_nm: float = 0.5,
        saturation: float = 0.0,
    ):
        """Measure a calibration lamp and fit this detector's wavelength axis.

        The standard arc-lamp procedure: detect the emission lines, centroid
        each by a Gaussian fit, identify them against the bundled NIST
        krypton catalogue, fit a Chebyshev polynomial, and sigma-clip the
        mis-identifications out.

        Works on both driver variants. On a spectrograph station the fit is
        recorded for comparison against ``GetCalibration`` and the live axis
        is unchanged; the response's ``applied`` field says which happened.

        ``anchors`` is REQUIRED: ``[[pixel, wavelength_nm], ...]``, at least
        ``degree + 4`` of them, spread across the detector. Read them off the
        raw lamp spectrum -- pick lines you can point at unambiguously, not
        ones crowded by a neighbour. Both halves are approximate and are
        snapped, the pixel to the nearest detected line and the wavelength to
        the nearest catalogue entry, so reading them off a plot is enough.

        Why so many: the anchors seed the solution that identifies every other
        line, and a degree-N fit through exactly N+1 points reproduces their
        centroid error rather than averaging it. Measured on a representative
        430-900 nm solution over 2560 columns, five anchors left the axis
        8.9 nm out and eight brought it to 0.002 nm.

        ``saturation`` excludes lines that reached it -- a flat top has no
        well-defined centre. ``0`` disables the check.

        Nothing is written unless the fit clears both quality gates: a
        residual no worse than ``max_fit_rms_nm``, and a strictly monotonic
        axis. A refused calibration leaves the previous one in place, and any
        calibration that IS written moves the outgoing one to a ``.prev``
        sibling first.
        """
        active = await ctx.begin()
        executor = AndorCalibrateWavelength(active=active, oneoff=True)
        active_action_dict = active.start_executor(executor)
        return active_action_dict


#: `wl_source` value -> driver class. An absent key yields the spectrograph
#: driver so every existing station config keeps working unedited; a station
#: opts into the lamp-calibrated path by adding the key.
WL_SOURCES: dict[str, type] = {
    "spectrograph": AndorSpectrographDriver,
    "calibration": AndorCalibratedDriver,
}
DEFAULT_WL_SOURCE = "spectrograph"


def _driver_class(server_key: str) -> type:
    """The driver class this server's config selects.

    Reads the global CONFIG, which ``fast_launcher.py`` populates before it
    imports this module and calls ``makeApp``. Tolerates a missing CONFIG or
    server entry, because capture scripts and build tests call ``makeApp``
    outside the launcher.

    Raises:
        ValueError: On an unrecognized ``wl_source``. A typo must not fall
            through to the default -- a station meaning to run the calibrated
            path would silently get the spectrograph one and fail at
            ``connect()`` with a vendor import error instead.
    """
    config = getattr(config_loader, "CONFIG", None) or {}
    params = (config.get("servers") or {}).get(server_key, {}).get("params", {}) or {}
    name = params.get("wl_source", DEFAULT_WL_SOURCE)
    if name not in WL_SOURCES:
        raise ValueError(
            f"unknown wl_source {name!r} for server {server_key!r}; "
            f"expected one of {sorted(WL_SOURCES)}"
        )
    return WL_SOURCES[name]


def makeApp(server_key) -> ActionHost:
    """Build the Andor camera FastAPI app.

    Constructs a :class:`ActionHost` backed by :class:`AndorDriver` and uses
    :func:`andor_dyn_endpoints` to register the action endpoints once the
    driver finishes initialising.

    The driver class is selected by the server's ``wl_source`` param
    (``spectrograph`` or ``calibration``), defaulting to ``spectrograph`` so an
    existing station config needs no edit. Note that ``base_api`` names the
    driver namedtuple field from the class name, so ``app.drivers.<Name>``
    differs between the two -- use ``app.driver``.

    Args:
        server_key: Key identifying this server in the orchestration group.

    Returns:
        The configured :class:`ActionHost` application.
    """

    app = ActionHost(
        server_key=server_key,
        server_title=server_key,
        description="Andor camera/action server",
        version=0.1,
        driver_classes=[_driver_class(server_key)],
        dyn_endpoints=andor_dyn_endpoints,
    )
    app.driver: AndorDriver  # type hint for convenience

    @app.post("/stop_private", tags=["private"])
    def stop_private():
        """Invoke :meth:`AndorDriver.stop` to halt the camera."""
        app.driver.stop()

    @app.post("/set_wl_from_pairs", tags=["private"])
    def set_wl_from_pairs(pairs: list, degree: int = 2):
        """Fit and install a wavelength axis from ``(channel, wavelength_nm)``.

        The direct route, for when the line identities are already known: no
        lamp exposure, no peak detection, no catalogue matching. Second order
        by default.

        Private rather than an action, and deliberately: it drives no
        hardware, produces no data, and takes no measurement, so an action
        record of it would carry nothing worth keeping. What it does change is
        persisted -- the fit is written to the same file the lamp calibration
        writes, with the outgoing one kept as ``.prev``, and on a
        lamp-calibrated station it becomes the live axis immediately.

        It cannot check the pairs. With no independent evidence a mislabelled
        pair is fitted exactly as faithfully as a correct one, which is why
        ``/ANDOR/calibrate_wl`` exists beside it -- there the catalogue
        disagrees with a bad identification and sigma-clipping removes it.

        Args:
            pairs: ``[[channel, wavelength_nm], ...]``, at least ``degree + 1``
                of them, each channel distinct.
            degree: Polynomial order. Three pairs at degree 2 interpolate, so
                the reported residual is 0 and means nothing; pass more if you
                want the number to carry information.

        Returns:
            The driver's response dict, including the fitted coefficients, the
            residual, the resulting wavelength span, and whether the axis was
            applied live on this station.
        """
        resp = app.driver.set_wl_from_pairs(
            [tuple(pair) for pair in pairs], degree=degree
        )
        return {
            "response": resp.response,
            "message": resp.message,
            "data": resp.data,
        }

    return app
