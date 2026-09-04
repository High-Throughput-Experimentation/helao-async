"""FastAPI action server for an Ocean Insight (OceanDirect) spectrometer.

Provides single-shot and averaged acquisition, an integration-time
intensity calibration, on-device dark/nonlinearity correction, two
long-running capture paths, and the optional device controls (TEC, shutter,
lamp, light source, strobes) that the device reports as available.

The two long-running paths are not interchangeable, and which one a station
can use is a property of its hardware:

* ``acquire_spec_buffered`` drains the device's hardware buffer and is the
  only way to capture gaplessly at the detector's own frame rate. It needs
  ``DATA_BUFFER``/``BACK_TO_BACK``, which plenty of devices lack -- an
  OCEANSR4 among them.
* ``acquire_spec_extrig`` needs no buffer. It performs one blocking read per
  external trigger (or free-running with ``trigger_mode=0``), which is how
  ``spec_server.py``'s SM303 path works. Software polling costs a USB round
  trip per spectrum and loses frames arriving between reads, so it replaces
  the buffered path's *duration*, not its rate.

Two design points are worth reading before editing:

* **Every acquired spectrum is emitted in long format.** One ``.hlo`` line
  carries one spectrum as parallel arrays (``epoch_s``, ``spec_idx``, ``wl``,
  ``i``, plus ``dev_ts_ns`` where the device supplies one); both HLO readers
  concatenate list-valued columns across lines, so a reader reconstructs one
  row per pixel. See ``OceanDirectSpec.build_rows``. ``json_data_keys`` is
  passed explicitly to ``ctx.begin`` so the column order is pinned rather than
  inferred from whichever data message happens to arrive first.
* **``dev_ts_ns`` is written only when it exists.** ``get_spectrum()`` carries
  no metadata, so the single-shot actions declare ``SINGLE_SHOT_KEYS`` and omit
  the column entirely rather than writing one ``null`` per pixel. Only the
  buffered path, via ``get_spectrum_with_metadata``, can fill it.
* **Optional features are gated at the driver, not here.** An endpoint for a
  feature the device lacks returns an error code on a finished action rather
  than raising, which is why each handler inspects the ``DriverResponse``
  instead of assuming success.
"""

__all__ = ["makeApp"]

import asyncio
import time
from typing import Optional, Union

from fastapi import Body

from helao.core.error import ErrorCodes
from helao.core.models.file import HloHeaderModel
from helao.core.models.hlostatus import HloStatus
from helao.hexagon.app.action_context import ActionContext, action_version
from helao.hexagon.app.action_host import ActionHost
from helao.core.drivers.helao_driver import DriverResponse, DriverResponseType
from helao.core.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    SampleInheritance,
    SampleStatus,
    SolidSample,
)
from helao.helpers import helao_logging as logging
from helao.helpers.executor import Executor
from helao.helpers.sample_api import UnifiedSampleDataAPI

from ...drivers.spec.oceandirect_driver import OceanDirectSpec
from ...drivers.spec.oceandirect_enum import (
    LONG_FORMAT_KEYS,
    MAX_METADATA_BUFFER_SIZE,
    ODTrigMode,
    SINGLE_SHOT_KEYS,
)

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class OceanDirectBufferExec(Executor):
    """Drains the device's hardware buffer during a back-to-back burst.

    ``_pre_exec`` arms the buffer, each ``_poll`` drains up to
    ``MAX_METADATA_BUFFER_SIZE`` spectra and emits them in long format, and
    ``_post_exec``/``_manual_stop`` abort the run and disable buffering. The
    executor finishes when the requested spectrum count is reached, when
    ``duration`` elapses, or when the buffer runs dry after having produced
    something.
    """

    def __init__(self, *args, **kwargs):
        """Bind the server's driver and zero the per-run counters."""
        super().__init__(*args, **kwargs)
        self.driver: OceanDirectSpec = self.active.driver
        self.emitted = 0
        self.dry_polls = 0
        self.armed = False

    async def _pre_exec(self) -> dict:
        """Arm the hardware buffer from ``action_params``."""
        # Read from action_params (subscript), never the endpoint fn-args.
        p = self.active.action.action_params
        self.driver.reset_spec_idx()
        self.emitted = 0
        self.dry_polls = 0
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: self.driver.start_buffered(
                n_scans=p["n_scans"], capacity=p["buffer_capacity"]
            ),
        )
        if resp.response != DriverResponseType.success:
            LOGGER.error(f"could not arm buffered capture: {resp.message}")
            return {"error": ErrorCodes.critical_error}
        self.armed = True
        LOGGER.info(f"buffered capture armed: {resp.data}")
        return {"error": ErrorCodes.none}

    async def _poll(self) -> dict:
        """Drain one batch of buffered spectra and emit them in long format."""
        p = self.active.action.action_params
        if not self.armed:
            return {"error": ErrorCodes.critical_error, "status": HloStatus.finished}

        duration = p["duration"]
        if duration is not None and duration > 0:
            if time.time() - self.start_time >= duration:
                LOGGER.info("buffered capture duration reached, finishing")
                return {
                    "error": ErrorCodes.none,
                    "status": HloStatus.finished,
                    "data": {},
                }

        loop = asyncio.get_event_loop()
        try:
            spectra, timestamps = await loop.run_in_executor(
                None, lambda: self.driver.drain_buffered(MAX_METADATA_BUFFER_SIZE)
            )
        except Exception as exc:
            LOGGER.error(f"buffered drain failed: {exc!r}")
            return {"error": ErrorCodes.critical_error, "status": HloStatus.finished}

        n_spectra = p["n_spectra"]
        if not spectra:
            self.dry_polls += 1
            # Only treat a dry buffer as the end of the run once something has
            # actually been produced; an early poll can legitimately arrive
            # before the device has filled its first scan.
            if self.emitted and self.dry_polls >= p["dry_polls_to_finish"]:
                LOGGER.info(
                    f"buffer dry for {self.dry_polls} polls after {self.emitted} "
                    "spectra, finishing"
                )
                return {
                    "error": ErrorCodes.none,
                    "status": HloStatus.finished,
                    "data": {},
                }
            return {"error": ErrorCodes.none, "status": HloStatus.active, "data": {}}

        self.dry_polls = 0
        if n_spectra is not None and n_spectra > 0:
            remaining = n_spectra - self.emitted
            if remaining <= 0:
                return {
                    "error": ErrorCodes.none,
                    "status": HloStatus.finished,
                    "data": {},
                }
            if len(spectra) > remaining:
                # Never emit more than was asked for, even though the device
                # handed over a full batch.
                spectra = spectra[:remaining]
                timestamps = timestamps[:remaining]

        epochs = [time.time()] * len(spectra)
        rows = self.driver.build_rows(
            spectra=spectra, epochs=epochs, dev_timestamps=timestamps
        )
        self.emitted += len(spectra)

        status = HloStatus.active
        if n_spectra is not None and n_spectra > 0 and self.emitted >= n_spectra:
            LOGGER.info(f"buffered capture reached {self.emitted} spectra, finishing")
            status = HloStatus.finished
        return {"error": ErrorCodes.none, "status": status, "data": rows}

    async def _post_exec(self) -> dict:
        """Stop the buffered run and disable buffering."""
        loop = asyncio.get_event_loop()
        if self.armed:
            await loop.run_in_executor(None, self.driver.stop_buffered)
            self.armed = False
        self.active.action.action_params["spectra_emitted"] = self.emitted
        return {"error": ErrorCodes.none, "data": {}}

    async def _manual_stop(self) -> dict:
        """Abort the buffered run on estop or manual stop."""
        loop = asyncio.get_event_loop()
        if self.armed:
            await loop.run_in_executor(None, self.driver.stop_buffered)
            self.armed = False
        return {"error": ErrorCodes.none}


class OceanDirectExtrigExec(Executor):
    """Externally-triggered (or free-running) acquisition without a buffer.

    The OceanDirect counterpart of ``spec_server.py``'s ``SM303Exec``, and the
    answer for a device with no ``DATA_BUFFER`` -- an OCEANSR4, for instance,
    where :class:`OceanDirectBufferExec` cannot arm at all. Instead of draining
    hardware, each ``_poll`` performs one blocking ``get_spectrum()``: in an
    external trigger mode that call returns when a trigger fires, so the poll
    loop *is* the trigger loop, exactly as the SM303's ``read_data`` loop is.

    Three properties of the vendor API shape this, and the first is a genuine
    limitation rather than a detail:

    * **The SDK has no acquisition timeout.** Its only ``timeout`` parameter is
      on ``open_device2``; nothing bounds a read waiting on a trigger, and
      ``abort_spectrum_acquisition`` is documented buffer-only ("applicable to
      OBP2 enabled devices"), so it cannot cancel one here. The read is
      therefore bounded with ``asyncio.wait_for``, which frees *this coroutine*
      on a timeout but leaves the worker thread blocked in the vendor call
      until a trigger arrives or the device is closed. That is the same trade
      ``SM303Exec`` makes. It is why ``_post_exec`` disarms the trigger:
      returning the device to free-running is what lets a pending read
      complete and the thread retire.
    * **The read must not hold the driver lock** (``serialize=False``). A wait
      of minutes would otherwise serialize the whole driver behind it,
      including ``disconnect()``, and server shutdown would hang until someone
      fired a trigger.
    * **No device timestamp is available on this path.** ``get_spectrum()``
      carries no metadata, so rows come back with ``SINGLE_SHOT_KEYS`` and no
      ``dev_ts_ns`` column.

    A timed-out poll is not an error and not the end of the run -- it is the
    normal "still waiting for a trigger" state, and the loop keeps waiting
    until ``duration`` expires or ``n_spectra`` is reached.
    """

    def __init__(self, *args, **kwargs):
        """Bind the server's driver and zero the per-run counters."""
        super().__init__(*args, **kwargs)
        self.driver: OceanDirectSpec = self.active.driver
        self.emitted = 0
        self.waits = 0
        self.armed = False

    async def _pre_exec(self) -> dict:
        """Arm the requested trigger mode from ``action_params``."""
        # Read from action_params (subscript), never the endpoint fn-args.
        p = self.active.action.action_params
        self.driver.reset_spec_idx()
        self.emitted = 0
        self.waits = 0
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None, lambda: self.driver.arm_trigger(p["trigger_mode"])
        )
        if resp.response != DriverResponseType.success:
            LOGGER.error(f"could not arm trigger mode: {resp.message}")
            return {"error": ErrorCodes.critical_error}
        self.armed = True
        LOGGER.info(f"trigger armed: {resp.data}")
        return {"error": ErrorCodes.none}

    async def _poll(self) -> dict:
        """Wait for one triggered spectrum and emit it."""
        p = self.active.action.action_params
        if not self.armed:
            return {"error": ErrorCodes.critical_error, "status": HloStatus.finished}

        duration = p["duration"]
        if duration is not None and duration > 0:
            if time.time() - self.start_time >= duration:
                LOGGER.info(
                    f"triggered acquisition duration reached after "
                    f"{self.emitted} spectra, finishing"
                )
                return {
                    "error": ErrorCodes.none,
                    "status": HloStatus.finished,
                    "data": {},
                }

        loop = asyncio.get_event_loop()
        try:
            spectrum, epoch_s = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.driver.acquire_spectrum(serialize=False),
                ),
                timeout=p["read_timeout_s"],
            )
        except asyncio.TimeoutError:
            # No trigger within the window. Expected, not an error: stay active
            # so the run continues waiting until duration or count says stop.
            self.waits += 1
            return {"error": ErrorCodes.none, "status": HloStatus.active, "data": {}}
        except Exception as exc:
            LOGGER.error(f"triggered read failed: {exc!r}")
            return {"error": ErrorCodes.critical_error, "status": HloStatus.finished}

        rows = self.driver.build_rows(spectra=[spectrum], epochs=[epoch_s])
        self.emitted += 1

        n_spectra = p["n_spectra"]
        status = HloStatus.active
        if n_spectra is not None and n_spectra > 0 and self.emitted >= n_spectra:
            LOGGER.info(f"triggered acquisition reached {self.emitted} spectra")
            status = HloStatus.finished
        return {"error": ErrorCodes.none, "status": status, "data": rows}

    async def _post_exec(self) -> dict:
        """Disarm the trigger, returning the device to free-running."""
        await self._disarm()
        p = self.active.action.action_params
        p["spectra_emitted"] = self.emitted
        p["trigger_waits"] = self.waits
        return {"error": ErrorCodes.none, "data": {}}

    async def _manual_stop(self) -> dict:
        """Disarm on estop or manual stop."""
        await self._disarm()
        return {"error": ErrorCodes.none}

    async def _disarm(self) -> None:
        """Return the device to free-running, once."""
        if not self.armed:
            return
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, self.driver.disarm_trigger)
        if resp.response != DriverResponseType.success:
            LOGGER.error(
                f"could not disarm trigger; the device may still be waiting "
                f"on one: {resp.message}"
            )
        self.armed = False


def _resp_error(resp: DriverResponse) -> ErrorCodes:
    """Map a ``DriverResponse`` onto the action's error code."""
    if resp.response == DriverResponseType.success:
        return ErrorCodes.none
    if resp.response == DriverResponseType.not_implemented:
        return ErrorCodes.not_available
    return ErrorCodes.critical_error


async def oceandirect_dyn_endpoints(app: ActionHost):
    """Register OceanDirect spectrometer endpoints.

    Disables concurrent actions (the vendor requires discovery and open to be
    serialized, and a single spectrometer cannot serve two acquisitions),
    opens the device via ``connect()`` -- moved out of ``__init__`` per the
    ``HelaoDriver`` no-device-I/O-at-construction rule -- and attaches the
    private, acquisition, correction, buffered-capture and device-control
    endpoints.

    Args:
        app: The :class:`ActionHost` instance being configured.
    """
    app.server_params["allow_concurrent_actions"] = False

    app.driver: OceanDirectSpec
    connect_resp = app.driver.connect()
    LOGGER.info(
        f"OceanDirectSpec connect() returned status={connect_resp.status} "
        f"({connect_resp.message})"
    )

    app.unified_db = UnifiedSampleDataAPI(app.base)
    await app.unified_db.init_db()

    def _header() -> HloHeaderModel:
        """HLO header carrying the wavelength axis and device identity."""
        return HloHeaderModel(
            optional={
                "wl": app.driver.pxwl,  # type: ignore[attr-defined]
                "model": app.driver.model,  # type: ignore[attr-defined]
                "serial_number": app.driver.serial,  # type: ignore[attr-defined]
                "n_pixels": app.driver.n_pixels,  # type: ignore[attr-defined]
            }
        )

    async def _begin_spec_action(ctx: ActionContext, **kwargs):
        """Open a session for the single-shot long-format data contract.

        ``SINGLE_SHOT_KEYS``, not ``LONG_FORMAT_KEYS``: ``get_spectrum()``
        carries no metadata, so ``dev_ts_ns`` can never be filled on this path
        and declaring it wrote an all-null column one value wide per pixel.
        The buffered action declares the full five keys itself.
        """
        return await ctx.begin(
            action_abbr="OPT",
            json_data_keys=SINGLE_SHOT_KEYS,
            hloheader=_header(),
            **kwargs,
        )

    async def _acquire_and_enqueue(
        active,
        dark_corrected: bool = False,
        peak_lower_wl: Optional[float] = None,
        peak_upper_wl: Optional[float] = None,
    ) -> dict:
        """Acquire one spectrum, emit it in long format, return its summary.

        The blocking vendor read runs in a thread executor: the SDK call
        releases the GIL and would otherwise stall this coroutine relative to
        the data-logging task.
        """
        loop = asyncio.get_event_loop()
        spectrum, epoch_s = await loop.run_in_executor(
            None, lambda: app.driver.acquire_spectrum(dark_corrected=dark_corrected)
        )
        rows = app.driver.build_rows(spectra=[spectrum], epochs=[epoch_s])
        if rows:
            await active.enqueue_data_dflt(datadict=rows)
        return {
            "epoch_s": epoch_s,
            "peak_intensity": app.driver.peak_intensity(
                spectrum, peak_lower_wl, peak_upper_wl
            ),
            "saturated": app.driver.is_saturated(),
            "n_pixels": len(spectrum),
        }

    # ------------------------------------------------------------------
    # Private endpoints
    # ------------------------------------------------------------------
    @app.post("/get_device_info", tags=["private"])
    def get_device_info():
        """Return identity, geometry, integration-time bounds and capabilities.

        This is the capability probe the endpoint surface is designed around:
        which ``Advanced`` features exist varies per model, so the
        ``features`` matrix is the authoritative answer to what this server
        can actually do against the attached device.
        """
        return app.driver.device_info()  # type: ignore[attr-defined]

    @app.post("/get_wl", tags=["private"])
    def get_wl():
        """Return the wavelength array with shape ``(n_pixels,)``."""
        return app.driver.pxwl  # type: ignore[attr-defined]

    @app.post("/get_tec_status", tags=["private"])
    def get_tec_status():
        """Return TEC enable state, setpoint, temperature and stability."""
        resp = app.driver.get_tec_status()  # type: ignore[attr-defined]
        return {"response": resp.response, "message": resp.message, "data": resp.data}

    @app.post("/get_buffered_count", tags=["private"])
    def get_buffered_count():
        """Return how many spectra currently sit in the device buffer."""
        return {"buffered_spectra": app.driver.buffered_count()}  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Core acquisition
    # ------------------------------------------------------------------
    @app.action()
    @action_version(1)
    async def acquire_spec(
        ctx: ActionContext,
        fast_samples_in: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        int_time_us: int = 100_000,
        duration_sec: Optional[float] = -1,
    ):
        """Acquire one spectrum, optionally looping until ``duration_sec`` elapses.

        Args:
            ctx: Per-request action context supplied by the host.
            fast_samples_in: Sample references associated with this action.
            int_time_us: Integration time in **microseconds**, clamped to the
                device's range and snapped to its increment.
            duration_sec: Total acquisition window in seconds; non-positive
                acquires a single spectrum. Long acquisitions should use
                ``acquire_spec_buffered`` to avoid HTTP timeouts.

        Returns:
            The finished action dictionary.
        """
        active = await _begin_spec_action(ctx)
        p = active.action.action_params
        app.driver.reset_spec_idx()  # type: ignore[attr-defined]

        int_resp = app.driver.set_integration_time_us(p["int_time_us"])  # type: ignore[attr-defined]
        p["applied_int_time_us"] = int_resp.data.get("int_time_us")
        if int_resp.response != DriverResponseType.success:
            active.action.error_code = _resp_error(int_resp)
            finished = await active.finish()
            return finished.as_dict()

        starttime = time.time()
        summary = await _acquire_and_enqueue(active)
        if p["duration_sec"] and p["duration_sec"] > 0:
            while time.time() - starttime < p["duration_sec"]:
                summary = await _acquire_and_enqueue(active)
        p["spectra_emitted"] = app.driver.spec_idx  # type: ignore[attr-defined]
        p["saturated"] = summary["saturated"]
        # Let dangling data messages land before the file closes.
        await asyncio.sleep(0.1)
        finished = await active.finish()
        return finished.as_dict()

    @app.action()
    @action_version(1)
    async def acquire_spec_adv(
        ctx: ActionContext,
        fast_samples_in: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        int_time_us: int = 100_000,
        duration_sec: Optional[float] = -1,
        scans_to_average: int = 1,
        boxcar_width: int = 0,
        peak_lower_wl: Optional[float] = None,
        peak_upper_wl: Optional[float] = None,
    ):
        """Acquire with on-device averaging and boxcar smoothing.

        Averaging and smoothing are device-side settings in OceanDirect, not
        arguments to the read call as they were on the SM303.

        Args:
            ctx: Per-request action context supplied by the host.
            fast_samples_in: Sample references associated with this action.
            int_time_us: Integration time in microseconds.
            duration_sec: Total acquisition window in seconds.
            scans_to_average: Spectra the device averages per returned spectrum.
            boxcar_width: On-device boxcar half-width.
            peak_lower_wl: Lower wavelength bound for peak detection, nm.
            peak_upper_wl: Upper wavelength bound for peak detection, nm.

        Returns:
            The finished action dictionary.
        """
        active = await _begin_spec_action(ctx)
        p = active.action.action_params
        app.driver.reset_spec_idx()  # type: ignore[attr-defined]

        int_resp = app.driver.set_integration_time_us(p["int_time_us"])  # type: ignore[attr-defined]
        p["applied_int_time_us"] = int_resp.data.get("int_time_us")
        proc_resp = app.driver.set_processing(  # type: ignore[attr-defined]
            scans_to_average=p["scans_to_average"], boxcar_width=p["boxcar_width"]
        )
        p["applied_processing"] = proc_resp.data
        if int_resp.response != DriverResponseType.success:
            # Integration time is load-bearing: acquiring at an unknown one
            # would produce data that cannot be compared to anything.
            active.action.error_code = _resp_error(int_resp)
            finished = await active.finish()
            return finished.as_dict()
        if proc_resp.response != DriverResponseType.success:
            # Averaging/boxcar are refinements; record the failure and
            # acquire anyway rather than losing the measurement.
            LOGGER.warning(f"on-device processing not applied: {proc_resp.message}")
            active.action.error_code = _resp_error(proc_resp)

        starttime = time.time()
        summary = await _acquire_and_enqueue(
            active,
            peak_lower_wl=p["peak_lower_wl"],
            peak_upper_wl=p["peak_upper_wl"],
        )
        if p["duration_sec"] and p["duration_sec"] > 0:
            while time.time() - starttime < p["duration_sec"]:
                summary = await _acquire_and_enqueue(
                    active,
                    peak_lower_wl=p["peak_lower_wl"],
                    peak_upper_wl=p["peak_upper_wl"],
                )
        p["peak_intensity"] = summary["peak_intensity"]
        p["saturated"] = summary["saturated"]
        p["spectra_emitted"] = app.driver.spec_idx  # type: ignore[attr-defined]
        await asyncio.sleep(0.1)
        finished = await active.finish()
        return finished.as_dict()

    @app.action()
    @action_version(1)
    async def calibrate_intensity(
        ctx: ActionContext,
        int_time_us: int = 100_000,
        scans_to_average: int = 3,
        peak_lower_wl: Optional[float] = 400,
        peak_upper_wl: Optional[float] = 750,
        target_peak_min: float = 30000,
        target_peak_max: float = 32000,
        max_iters: int = 5,
        max_int_time_us: int = 1_000_000,
    ):
        """Adjust integration time until the peak lands in the target window.

        Scales the integration time toward the centre of the target window and
        re-acquires until the peak is in range, ``max_iters`` is spent, or the
        integration time saturates at the lower of ``max_int_time_us`` and the
        device's own maximum. Every iteration's spectrum is recorded.

        Args:
            ctx: Per-request action context supplied by the host.
            int_time_us: Starting integration time in microseconds.
            scans_to_average: Spectra averaged per iteration.
            peak_lower_wl: Lower wavelength bound for peak detection, nm.
            peak_upper_wl: Upper wavelength bound for peak detection, nm.
            target_peak_min: Lower bound of the desired peak window.
            target_peak_max: Upper bound of the desired peak window.
            max_iters: Maximum adjustment iterations.
            max_int_time_us: Caller-imposed ceiling on integration time.

        Returns:
            The finished action dictionary, with ``calibrated_int_time_us``
            and ``peak_intensity`` written back into ``action_params``.
        """
        active = await _begin_spec_action(ctx)
        p = active.action.action_params
        app.driver.reset_spec_idx()  # type: ignore[attr-defined]

        app.driver.set_processing(scans_to_average=p["scans_to_average"])  # type: ignore[attr-defined]
        # The device maximum wins over the caller's ceiling; asking for more
        # than the hardware allows would otherwise loop forever at the cap.
        device_max = app.driver.int_time_max_us  # type: ignore[attr-defined]
        ceiling = int(
            min(p["max_int_time_us"], device_max)
            if device_max is not None
            else p["max_int_time_us"]
        )
        current_us = int(p["int_time_us"])
        target_avg = 0.5 * (p["target_peak_max"] + p["target_peak_min"])

        int_resp = app.driver.set_integration_time_us(current_us)  # type: ignore[attr-defined]
        current_us = int_resp.data.get("int_time_us", current_us)
        summary = await _acquire_and_enqueue(
            active,
            peak_lower_wl=p["peak_lower_wl"],
            peak_upper_wl=p["peak_upper_wl"],
        )
        peak = summary["peak_intensity"]
        LOGGER.info(f"initial peak intensity: {peak}")

        iters = 0
        max_reached = False
        while (
            peak is not None
            and (peak < p["target_peak_min"] or peak > p["target_peak_max"])
            and iters < p["max_iters"]
            and not max_reached
        ):
            if peak <= 0:
                LOGGER.warning("peak intensity is non-positive; cannot scale")
                break
            scaled = int(current_us * target_avg / peak)
            if scaled >= ceiling:
                scaled = ceiling
                max_reached = True
            LOGGER.info(f"adjusting integration time to {scaled} us")
            int_resp = app.driver.set_integration_time_us(scaled)  # type: ignore[attr-defined]
            applied = int_resp.data.get("int_time_us")
            if applied == current_us:
                # The clamp/snap did not move: another iteration would repeat
                # the same measurement forever.
                LOGGER.info(
                    f"integration time pinned at {current_us} us; stopping calibration"
                )
                break
            current_us = applied
            summary = await _acquire_and_enqueue(
                active,
                peak_lower_wl=p["peak_lower_wl"],
                peak_upper_wl=p["peak_upper_wl"],
            )
            peak = summary["peak_intensity"]
            LOGGER.info(f"current peak intensity: {peak}")
            iters += 1

        p["peak_intensity"] = peak
        p["calibrated_int_time_us"] = current_us
        p["calibration_iters"] = iters
        p["max_int_time_reached"] = max_reached
        p["in_target_window"] = bool(
            peak is not None and p["target_peak_min"] <= peak <= p["target_peak_max"]
        )
        p["spectra_emitted"] = app.driver.spec_idx  # type: ignore[attr-defined]
        await asyncio.sleep(0.1)
        finished = await active.finish()
        return finished.as_dict()

    # ------------------------------------------------------------------
    # Dark and nonlinearity correction
    # ------------------------------------------------------------------
    @app.action()
    @action_version(1)
    async def store_dark_spectrum(
        ctx: ActionContext,
        int_time_us: Optional[int] = None,
    ):
        """Acquire a dark spectrum and store it on the device.

        The caller is responsible for blocking the light path; this only
        records what the detector sees. The summary statistics are written
        into ``action_params`` so a dark taken with the shutter open is
        recognisable after the fact.

        Args:
            ctx: Per-request action context supplied by the host.
            int_time_us: Integration time to use, in microseconds; ``None``
                keeps the current setting. It must match the integration time
                of the spectra the dark will later be subtracted from.

        Returns:
            The finished action dictionary.
        """
        active = await ctx.begin(action_abbr="OPT")
        p = active.action.action_params
        if p["int_time_us"] is not None:
            int_resp = app.driver.set_integration_time_us(p["int_time_us"])  # type: ignore[attr-defined]
            p["applied_int_time_us"] = int_resp.data.get("int_time_us")
        resp = app.driver.store_dark_spectrum()  # type: ignore[attr-defined]
        p.update(resp.data)
        active.action.error_code = _resp_error(resp)
        await active.enqueue_data_dflt(
            datadict={"store_dark_spectrum": resp.data, "message": resp.message}
        )
        finished = await active.finish()
        return finished.as_dict()

    @app.action()
    @action_version(1)
    async def set_corrections(
        ctx: ActionContext,
        electric_dark: Optional[bool] = None,
        nonlinearity: Optional[bool] = None,
        saturation_check: Optional[bool] = None,
    ):
        """Toggle the device's on-board correction stages.

        Each toggle is applied independently and gated on its own feature, so
        a device supporting only one of them still gets that one set; the
        action reports an error only if a requested toggle was unavailable.

        Args:
            ctx: Per-request action context supplied by the host.
            electric_dark: Electric-dark correction; ``None`` leaves it alone.
            nonlinearity: Nonlinearity correction; ``None`` leaves it alone.
            saturation_check: Saturation checking; ``None`` leaves it alone.

        Returns:
            The finished action dictionary.
        """
        active = await ctx.begin(action_abbr="OPT")
        p = active.action.action_params
        resp = app.driver.set_corrections(  # type: ignore[attr-defined]
            electric_dark=p["electric_dark"],
            nonlinearity=p["nonlinearity"],
            saturation_check=p["saturation_check"],
        )
        p["applied_corrections"] = resp.data
        active.action.error_code = _resp_error(resp)
        await active.enqueue_data_dflt(
            datadict={"corrections": resp.data, "message": resp.message}
        )
        finished = await active.finish()
        return finished.as_dict()

    @app.action()
    @action_version(1)
    async def acquire_spec_corrected(
        ctx: ActionContext,
        fast_samples_in: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        int_time_us: int = 100_000,
        duration_sec: Optional[float] = -1,
        peak_lower_wl: Optional[float] = None,
        peak_upper_wl: Optional[float] = None,
    ):
        """Acquire spectra dark-corrected against the device's stored dark.

        Requires a prior ``store_dark_spectrum`` at the same integration time;
        without one the device raises and the action finishes with an error
        code rather than emitting uncorrected data that looks corrected.

        Args:
            ctx: Per-request action context supplied by the host.
            fast_samples_in: Sample references associated with this action.
            int_time_us: Integration time in microseconds.
            duration_sec: Total acquisition window in seconds.
            peak_lower_wl: Lower wavelength bound for peak detection, nm.
            peak_upper_wl: Upper wavelength bound for peak detection, nm.

        Returns:
            The finished action dictionary.
        """
        active = await _begin_spec_action(ctx)
        p = active.action.action_params
        app.driver.reset_spec_idx()  # type: ignore[attr-defined]
        int_resp = app.driver.set_integration_time_us(p["int_time_us"])  # type: ignore[attr-defined]
        p["applied_int_time_us"] = int_resp.data.get("int_time_us")

        starttime = time.time()
        try:
            summary = await _acquire_and_enqueue(
                active,
                dark_corrected=True,
                peak_lower_wl=p["peak_lower_wl"],
                peak_upper_wl=p["peak_upper_wl"],
            )
            if p["duration_sec"] and p["duration_sec"] > 0:
                while time.time() - starttime < p["duration_sec"]:
                    summary = await _acquire_and_enqueue(
                        active,
                        dark_corrected=True,
                        peak_lower_wl=p["peak_lower_wl"],
                        peak_upper_wl=p["peak_upper_wl"],
                    )
        except Exception as exc:
            LOGGER.error(f"dark-corrected acquisition failed: {exc!r}")
            active.action.error_code = ErrorCodes.critical_error
            p["error_detail"] = repr(exc)
            finished = await active.finish()
            return finished.as_dict()

        p["peak_intensity"] = summary["peak_intensity"]
        p["saturated"] = summary["saturated"]
        p["spectra_emitted"] = app.driver.spec_idx  # type: ignore[attr-defined]
        await asyncio.sleep(0.1)
        finished = await active.finish()
        return finished.as_dict()

    # ------------------------------------------------------------------
    # Buffered burst capture
    # ------------------------------------------------------------------
    @app.action()
    @action_version(1)
    async def acquire_spec_buffered(
        ctx: ActionContext,
        fast_samples_in: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        int_time_us: int = 100_000,
        n_scans: int = 100,
        n_spectra: Optional[int] = None,
        buffer_capacity: Optional[int] = None,
        duration: float = -1,
        dry_polls_to_finish: int = 5,
        poll_rate: float = 0.05,
    ):
        """Run a hardware-buffered back-to-back burst and drain it.

        The device acquires into its own buffer at full rate while
        :class:`OceanDirectBufferExec` drains batches of at most 15 spectra
        (the vendor's ceiling on ``get_spectrum_with_metadata``), each
        carrying a device timestamp. Samples are validated before the session
        opens, matching the reference server: a no-sample rejection must
        produce an error code and no artifacts.

        Args:
            ctx: Per-request action context supplied by the host.
            fast_samples_in: Sample references associated with this action.
            int_time_us: Integration time in microseconds.
            n_scans: Back-to-back scans the device should acquire.
            n_spectra: Stop after this many spectra; ``None`` drains until the
                buffer runs dry or ``duration`` elapses.
            buffer_capacity: Device buffer capacity; ``None`` keeps the
                current setting.
            duration: Total run duration in seconds; negative runs until the
                buffer is dry or ``n_spectra`` is reached.
            dry_polls_to_finish: Consecutive empty drains that end the run
                once at least one spectrum has been emitted.
            poll_rate: Seconds between drains.

        Returns:
            The active action dictionary, or a finished-with-error action dict
            when setup or sample validation failed.
        """
        # The setup and no-sample branches must answer with an error code and
        # no artifacts, so the Action is needed before any session exists.
        A = ctx.action
        A.action_abbr = "OPT"
        p = A.action_params

        int_resp = app.driver.set_integration_time_us(p["int_time_us"])  # type: ignore[attr-defined]
        if int_resp.response != DriverResponseType.success:
            LOGGER.error(f"could not set integration time: {int_resp.message}")
            A.error_code = ErrorCodes.critical_error
            return A.as_dict()
        A.error_code = ErrorCodes.none

        samples_in = await app.unified_db.get_samples(A.samples_in)
        if not samples_in and not app.driver.allow_no_sample:  # type: ignore[attr-defined]
            LOGGER.error(
                "OceanDirect server got no valid sample, cannot start measurement!"
            )
            A.samples_in = []
            A.error_code = ErrorCodes.no_sample
            return A.as_dict()

        active = await ctx.begin(
            action_abbr="OPT",
            json_data_keys=LONG_FORMAT_KEYS,
            file_type="spec_helao__file",
            hloheader=_header(),
            sample_global_labels=[s.get_global_label() for s in samples_in],
        )
        for sample in samples_in:
            sample.reset_sample_status(SampleStatus.preserved)
            sample.inheritance = SampleInheritance.allow_both
        active.action.samples_in = []
        await active.append_sample(samples=samples_in, IO="in")
        active.finish_hlo_header(
            realtime=active.get_realtime_nowait(),
            file_conn_keys=active.action.file_conn_keys,
        )

        LOGGER.info("buffered capture task initiated.")
        executor = OceanDirectBufferExec(
            active=active,
            oneoff=False,
            poll_rate=active.action.action_params["poll_rate"],
        )
        return active.start_executor(executor)

    @app.action()
    @action_version(1)
    async def stop_buffered_after(
        ctx: ActionContext,
        delay: int = 0,
    ):
        """Stop any running buffered capture after ``delay`` seconds.

        Disables buffering on the device, then signals in-progress
        ``acquire_spec_buffered`` executors to stop via the action-server
        framework.

        Args:
            ctx: Per-request action context supplied by the host.
            delay: Seconds to wait before stopping.

        Returns:
            The finished action dictionary.
        """
        active = await ctx.begin(action_abbr="OPT")
        await asyncio.sleep(active.action.action_params["delay"])
        resp = app.driver.stop_buffered()  # type: ignore[attr-defined]
        stopped = []
        for exec_id, exec_active in list(app.executors.items()):
            if exec_id.split()[0] == "acquire_spec_buffered":
                exec_active.stop_action_task()
                stopped.append(exec_id)
        active.action.action_params["stopped_executors"] = stopped
        await active.enqueue_data_dflt(
            datadict={"stop": resp.response, "message": resp.message}
        )
        finished = await active.finish()
        return finished.as_dict()

    # ------------------------------------------------------------------
    # Externally-triggered capture (no hardware buffer required)
    # ------------------------------------------------------------------
    @app.action()
    @action_version(1)
    async def acquire_spec_extrig(
        ctx: ActionContext,
        fast_samples_in: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        int_time_us: int = 100_000,
        trigger_mode: int = int(ODTrigMode.ext_hardware_edge),
        n_spectra: Optional[int] = None,
        duration: float = -1,
        read_timeout_s: float = 5.0,
        poll_rate: float = 0.01,
    ):
        """Capture one spectrum per external trigger, for as long as asked.

        The counterpart of ``spec_server.py``'s ``acquire_spec_extrig``, and
        the path to use on a device with no ``DATA_BUFFER`` -- an OCEANSR4, for
        instance, where ``acquire_spec_buffered`` cannot arm. The device is put
        into ``trigger_mode`` and :class:`OceanDirectExtrigExec` then performs
        one blocking read per trigger, so this returns immediately with an
        active action rather than holding the HTTP request open.

        With ``trigger_mode=0`` (free-running) the same loop gives a long
        continuous acquisition without an HTTP timeout, which is the other
        thing the buffered path was for. Note what it cannot give: software
        polling reads one spectrum per USB round trip, so frames arriving
        between reads are lost. Gapless capture at the detector's own frame
        rate needs the hardware buffer, and no amount of polling substitutes
        for it.

        Args:
            ctx: Per-request action context supplied by the host.
            fast_samples_in: Sample references associated with this action.
            int_time_us: Integration time in microseconds.
            trigger_mode: Trigger mode integer. **Defined by the device
                manual, not the SDK** -- see ``ODTrigMode`` for the family's
                usual values, and check the applied value in the log, since
                the driver reads it back and warns on a mismatch.
            n_spectra: Finish after this many spectra; ``None`` runs until
                ``duration`` expires or the action is stopped.
            duration: Total run duration in seconds; negative runs until
                ``n_spectra`` is reached or the action is stopped.
            read_timeout_s: How long one poll waits for a trigger before
                giving up on *that* poll. A timeout is the normal
                "still waiting" state, not an error, and does not end the run.
            poll_rate: Seconds between polls.

        Returns:
            The active action dictionary, or a finished-with-error action dict
            when setup or sample validation failed.
        """
        # The setup and no-sample branches must answer with an error code and
        # no artifacts, so the Action is needed before any session exists.
        A = ctx.action
        A.action_abbr = "OPT"
        p = A.action_params

        int_resp = app.driver.set_integration_time_us(p["int_time_us"])  # type: ignore[attr-defined]
        if int_resp.response != DriverResponseType.success:
            LOGGER.error(f"could not set integration time: {int_resp.message}")
            A.error_code = ErrorCodes.critical_error
            return A.as_dict()
        A.error_code = ErrorCodes.none

        samples_in = await app.unified_db.get_samples(A.samples_in)
        if not samples_in and not app.driver.allow_no_sample:  # type: ignore[attr-defined]
            LOGGER.error(
                "OceanDirect server got no valid sample, cannot start measurement!"
            )
            A.samples_in = []
            A.error_code = ErrorCodes.no_sample
            return A.as_dict()

        active = await ctx.begin(
            action_abbr="OPT",
            # No device timestamp on this path: get_spectrum() has no metadata.
            json_data_keys=SINGLE_SHOT_KEYS,
            file_type="spec_helao__file",
            hloheader=_header(),
            sample_global_labels=[s.get_global_label() for s in samples_in],
        )
        for sample in samples_in:
            sample.reset_sample_status(SampleStatus.preserved)
            sample.inheritance = SampleInheritance.allow_both
        active.action.samples_in = []
        await active.append_sample(samples=samples_in, IO="in")
        active.finish_hlo_header(
            realtime=active.get_realtime_nowait(),
            file_conn_keys=active.action.file_conn_keys,
        )

        LOGGER.info("externally-triggered acquisition initiated.")
        executor = OceanDirectExtrigExec(
            active=active,
            oneoff=False,
            poll_rate=active.action.action_params["poll_rate"],
        )
        return active.start_executor(executor)

    @app.action()
    @action_version(1)
    async def stop_extrig_after(
        ctx: ActionContext,
        delay: int = 0,
    ):
        """Stop any running triggered acquisition after ``delay`` seconds.

        Disarms the trigger on the device, then signals in-progress
        ``acquire_spec_extrig`` executors to stop. Disarming first is
        deliberate: it is what allows a read already blocked on a trigger that
        never came to complete, so the executor can retire rather than sit
        waiting.

        Args:
            ctx: Per-request action context supplied by the host.
            delay: Seconds to wait before stopping.

        Returns:
            The finished action dictionary.
        """
        active = await ctx.begin(action_abbr="OPT")
        await asyncio.sleep(active.action.action_params["delay"])
        resp = app.driver.disarm_trigger()  # type: ignore[attr-defined]
        stopped = []
        for exec_id, exec_active in list(app.executors.items()):
            if exec_id.split()[0] == "acquire_spec_extrig":
                exec_active.stop_action_task()
                stopped.append(exec_id)
        active.action.action_params["stopped_executors"] = stopped
        await active.enqueue_data_dflt(
            datadict={"disarm": resp.response, "message": resp.message}
        )
        finished = await active.finish()
        return finished.as_dict()

    # ------------------------------------------------------------------
    # Device control
    # ------------------------------------------------------------------
    async def _control_action(active, resp: DriverResponse, key: str):
        """Record a device-control response and finish the action."""
        active.action.action_params[f"applied_{key}"] = resp.data
        active.action.error_code = _resp_error(resp)
        await active.enqueue_data_dflt(
            datadict={key: resp.data, "message": resp.message}
        )
        finished = await active.finish()
        return finished.as_dict()

    @app.action()
    @action_version(1)
    async def set_trigger_mode(
        ctx: ActionContext,
        mode: int = int(ODTrigMode.normal),
    ):
        """Set the device trigger source.

        Trigger-mode integers come from the device manual, not the SDK, so the
        applied value is read back and a mismatch is logged.

        Args:
            ctx: Per-request action context supplied by the host.
            mode: Trigger mode integer (see ``ODTrigMode``).

        Returns:
            The finished action dictionary.
        """
        active = await ctx.begin(action_abbr="OPT")
        resp = app.driver.set_trigger_mode(active.action.action_params["mode"])  # type: ignore[attr-defined]
        return await _control_action(active, resp, "trigger_mode")

    @app.action()
    @action_version(1)
    async def set_tec(
        ctx: ActionContext,
        enable: Optional[bool] = None,
        setpoint_degrees_c: Optional[float] = None,
    ):
        """Enable/disable the thermoelectric cooler and set its setpoint.

        Args:
            ctx: Per-request action context supplied by the host.
            enable: TEC enable state; ``None`` leaves it unchanged.
            setpoint_degrees_c: Target temperature in Celsius; ``None`` leaves
                it unchanged.

        Returns:
            The finished action dictionary.
        """
        active = await ctx.begin(action_abbr="OPT")
        p = active.action.action_params
        resp = app.driver.set_tec(  # type: ignore[attr-defined]
            enable=p["enable"], setpoint_degrees_c=p["setpoint_degrees_c"]
        )
        return await _control_action(active, resp, "tec")

    @app.action()
    @action_version(1)
    async def set_shutter(
        ctx: ActionContext,
        open_shutter: bool = False,
    ):
        """Open or close the device shutter.

        Args:
            ctx: Per-request action context supplied by the host.
            open_shutter: ``True`` to open, ``False`` to close.

        Returns:
            The finished action dictionary.
        """
        active = await ctx.begin(action_abbr="OPT")
        resp = app.driver.set_shutter_open(  # type: ignore[attr-defined]
            active.action.action_params["open_shutter"]
        )
        return await _control_action(active, resp, "shutter")

    @app.action()
    @action_version(1)
    async def set_lamp(
        ctx: ActionContext,
        enable: bool = False,
    ):
        """Enable or disable the device lamp output.

        Args:
            ctx: Per-request action context supplied by the host.
            enable: Lamp enable state.

        Returns:
            The finished action dictionary.
        """
        active = await ctx.begin(action_abbr="OPT")
        resp = app.driver.set_lamp_enable(active.action.action_params["enable"])  # type: ignore[attr-defined]
        return await _control_action(active, resp, "lamp")

    @app.action()
    @action_version(1)
    async def set_light_source(
        ctx: ActionContext,
        index: int = 0,
        enable: bool = False,
    ):
        """Enable or disable one of the device's light sources.

        Args:
            ctx: Per-request action context supplied by the host.
            index: Light-source index.
            enable: Desired enable state.

        Returns:
            The finished action dictionary.
        """
        active = await ctx.begin(action_abbr="OPT")
        p = active.action.action_params
        resp = app.driver.set_light_source_enable(p["index"], p["enable"])  # type: ignore[attr-defined]
        return await _control_action(active, resp, "light_source")

    @app.action()
    @action_version(1)
    async def set_single_strobe(
        ctx: ActionContext,
        enable: Optional[bool] = None,
        delay_us: Optional[int] = None,
        width_us: Optional[int] = None,
    ):
        """Configure the single strobe, clamped to the device's own limits.

        Args:
            ctx: Per-request action context supplied by the host.
            enable: Strobe enable state; ``None`` leaves it unchanged.
            delay_us: Strobe delay in microseconds; ``None`` leaves it alone.
            width_us: Strobe width in microseconds; ``None`` leaves it alone.

        Returns:
            The finished action dictionary.
        """
        active = await ctx.begin(action_abbr="OPT")
        p = active.action.action_params
        resp = app.driver.set_single_strobe(  # type: ignore[attr-defined]
            enable=p["enable"], delay_us=p["delay_us"], width_us=p["width_us"]
        )
        return await _control_action(active, resp, "single_strobe")

    @app.action()
    @action_version(1)
    async def set_continuous_strobe(
        ctx: ActionContext,
        enable: Optional[bool] = None,
        period_us: Optional[int] = None,
        width_us: Optional[int] = None,
    ):
        """Configure the continuous strobe, clamped to the device's limits.

        Args:
            ctx: Per-request action context supplied by the host.
            enable: Strobe enable state; ``None`` leaves it unchanged.
            period_us: Strobe period in microseconds; ``None`` leaves it alone.
            width_us: Strobe width in microseconds; ``None`` leaves it alone.

        Returns:
            The finished action dictionary.
        """
        active = await ctx.begin(action_abbr="OPT")
        p = active.action.action_params
        resp = app.driver.set_continuous_strobe(  # type: ignore[attr-defined]
            enable=p["enable"], period_us=p["period_us"], width_us=p["width_us"]
        )
        return await _control_action(active, resp, "continuous_strobe")


def makeApp(server_key) -> ActionHost:
    """Build the ActionHost app for the OceanDirect spectrometer.

    Args:
        server_key: Unique key identifying this server in the orchestration
            group.

    Returns:
        The configured ActionHost with endpoints attached via
        :func:`oceandirect_dyn_endpoints`.
    """
    app = ActionHost(
        server_key=server_key,
        server_title=server_key,
        description="OceanDirect spectrometer server",
        version=0.1,
        driver_classes=[OceanDirectSpec],
        dyn_endpoints=oceandirect_dyn_endpoints,
    )

    return app
