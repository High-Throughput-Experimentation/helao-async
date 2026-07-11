# shell: uvicorn motion_server:app --reload
"""FastAPI action server for the SM303 spectrometer.

Provides endpoints for single and averaged spectrum acquisition, intensity
calibration that adjusts integration time toward a target peak window, and
externally-triggered captures. Hardware triggers are the preferred method
for synchronising spectral capture with an illumination source.

The externally-triggered acquisition lifecycle (``acquire_spec_extrig``) is
owned here rather than by the driver: the endpoint validates samples and
opens the ``Active`` action, and :class:`SM303Exec` drives the
trigger/collect loop that the driver's legacy ``IOloop`` used to run.
"""

__all__ = ["makeApp"]

import asyncio
import time
from typing import Optional, List, Union
from fastapi import Body
from helao.helpers.premodels import Action
from helao.helpers.executor import Executor
from helao.helpers.active_params import ActiveParams
from helao.helpers.sample_api import UnifiedSampleDataAPI
from helao.core.servers.base_api import BaseAPI, action_version
from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.core.models.sample import (
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
    SampleInheritance,
    SampleStatus,
)
from helao.core.models.file import FileConnParams, HloHeaderModel
from ...drivers.spec.spectral_products_driver import SM303

from ...drivers.io.enum import TriggerType
from ...drivers.spec.enum import SpecTrigType

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class SM303Exec(Executor):
    """Executor that drives an externally-triggered SM303 acquisition.

    Owns the ``Active`` action created by the ``acquire_spec_extrig``
    endpoint (K7b: the endpoint validates samples and calls
    ``contain_action``). ``_pre_exec`` arms the driver's per-run state from
    ``action_params``; ``_poll`` is the ported body of the driver's legacy
    ``continuous_read`` loop (one iteration per call, cadence set by
    ``poll_rate``); ``_post_exec``/``_manual_stop`` close out the device
    channel/trigger the same way the legacy ``IOloop`` did after
    ``continuous_read`` returned.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the executor and bind the server's driver instance."""
        super().__init__(*args, **kwargs)
        LOGGER.info("SM303Exec initialized.")
        self.driver: SM303 = self.active.driver

    async def _pre_exec(self) -> dict:
        """Arm the driver's per-run acquisition state from ``action_params``."""
        # K7 CRITICAL: read from action_params (subscript), never endpoint fn-args
        p = self.active.action.action_params
        self.driver.n_avg = p["n_avg"]
        self.driver.fft = p["fft"]
        self.driver.trigger_duration = p["duration"]
        self.driver.start_time = time.time()
        self.driver.spec_time = time.time()
        LOGGER.info(f"start_time: {self.driver.start_time}")
        LOGGER.info(f"spec_time: {self.driver.spec_time}")
        return {"error": ErrorCodes.none}

    async def _poll(self) -> dict:
        """Read one spectrum (ported ``continuous_read`` loop body).

        Uses ``run_in_executor`` for the blocking ctypes read, same as the
        legacy loop, since the DLL call releases the GIL and would otherwise
        break the ordering of this coroutine relative to others.
        """
        driver = self.driver
        if driver.spec is None:
            return {"error": ErrorCodes.none, "status": HloStatus.finished, "data": {}}

        if (driver.spec_time - driver.start_time) >= (
            driver.trigger_duration + driver.start_margin
        ):
            LOGGER.info("polling loop duration complete, finishing")
            return {"error": ErrorCodes.none, "status": HloStatus.finished, "data": {}}

        loop = asyncio.get_event_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(None, driver.read_data),
                timeout=driver.trigger_duration + driver.start_margin,
            )
        except asyncio.exceptions.TimeoutError:
            driver.data = []

        data = {}
        if driver.data:
            datadict = {"epoch_s": driver.spec_time}
            datadict.update({f"ch_{i:04}": x for i, x in enumerate(driver.data)})
            data = datadict
            driver.data = []

        driver.spec_time = time.time()
        return {"error": ErrorCodes.none, "status": HloStatus.active, "data": data}

    async def _post_exec(self) -> dict:
        """Close the device channel and disable the trigger (ported ``IOloop`` tail)."""
        self.driver.trigger_duration = 0
        if self.driver.spec is not None:
            self.driver.unset_external_trigger()
            self.driver.spec.spCloseGivenChannel(self.driver.dev_num)
        return {"error": ErrorCodes.none, "data": {}}

    async def _manual_stop(self) -> dict:
        """Disable the trigger on abort (estop/manual stop)."""
        if self.driver.spec is not None:
            self.driver.unset_external_trigger()
        return {"error": ErrorCodes.none}


async def sm303_dyn_endpoints(app: BaseAPI):
    """Register SM303 spectrometer endpoints.

    Disables concurrent actions on this server, opens the vendor DLL
    connection (``connect()``, moved out of ``__init__`` per the
    HelaoDriver ABC's no-device-I/O-at-construction rule), constructs the
    shared ``UnifiedSampleDataAPI`` instance used for sample validation, and
    attaches private and action endpoints for wavelength retrieval,
    single/averaged acquisition, intensity calibration, and external trigger
    control.

    Args:
        app: The :class:`BaseAPI` instance being configured.
    """
    server_key = app.base.server.server_name
    app.base.server_params["allow_concurrent_actions"] = False

    app.driver: SM303
    connect_resp = app.driver.connect()
    LOGGER.info(f"SM303 connect() returned status={connect_resp.status}")

    app.unified_db = UnifiedSampleDataAPI(app.base)
    await app.unified_db.init_db()

    @app.post("/get_wl", tags=["private"])
    def get_wl():
        """Return the spectrometer wavelength array with shape ``(num_pixels,)``."""
        return app.driver.pxwl  # type: ignore

    @app.post(f"/{server_key}/acquire_spec", tags=["action"])
    @action_version(2)
    async def acquire_spec(
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        int_time_ms: int = 35,
        duration_sec: Optional[
            float
        ] = -1,  # measurements longer than HTTP timeout should use acquire_spec_extrig
    ):
        """Acquire one spectrum, optionally looping until ``duration_sec`` elapses.

        Each spectrum is enqueued to the default data sink with the wavelength
        array attached to the HLO header.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            fast_samples_in: Sample references associated with this action.
            int_time_ms: Integration time per spectrum in milliseconds.
            duration_sec: Total acquisition window in seconds; non-positive
                acquires a single spectrum. Long acquisitions should use
                ``acquire_spec_extrig`` to avoid HTTP timeouts.

        Returns:
            The finished action dictionary.
        """
        LOGGER.info("!!! Starting acquire_spec action.")
        spec_header = {"wl": app.driver.pxwl}  # type: ignore
        active = await app.base.setup_and_contain_action(
            action_abbr="OPT", hloheader=HloHeaderModel(optional=spec_header)
        )
        LOGGER.info("!!! acquire_spec action is active.")
        starttime = time.time()
        # acquire at least 1 spectrum
        specdict = app.driver.acquire_spec_adv(**active.action.action_params)  # type: ignore
        await active.enqueue_data_dflt(datadict=specdict)
        # duration loop
        if active.action.action_params["duration_sec"] > 0:
            while time.time() - starttime < active.action.action_params["duration_sec"]:
                specdict = app.driver.acquire_spec_adv(**active.action.action_params)
                await active.enqueue_data_dflt(datadict=specdict)
        # wait 1 second to capture dangling data messages
        await asyncio.sleep(1)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/acquire_spec_adv", tags=["action"])
    @action_version(2)
    async def acquire_spec_adv(
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        int_time_ms: int = 35,
        duration_sec: Optional[
            float
        ] = -1,  # measurements longer than HTTP timeout should use acquire_spec_extrig
        n_avg: int = 1,
        fft: int = 0,
        peak_lower_wl: Optional[float] = None,
        peak_upper_wl: Optional[float] = None,
    ):
        """Acquire averaged spectra with optional FFT smoothing.

        Delegates to ``driver.acquire_spec_adv``, optionally repeating until
        ``duration_sec`` elapses. The peak intensity in the optional
        ``[peak_lower_wl, peak_upper_wl]`` window is recorded back into
        ``action_params``.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            fast_samples_in: Sample references associated with this action.
            int_time_ms: Integration time per spectrum in milliseconds.
            duration_sec: Total acquisition window in seconds.
            n_avg: Number of acquisitions to average per output spectrum.
            fft: FFT smoothing parameter forwarded to the driver.
            peak_lower_wl: Lower wavelength bound for peak detection.
            peak_upper_wl: Upper wavelength bound for peak detection.

        Returns:
            The finished action dictionary.
        """
        spec_header = {"wl": app.driver.pxwl}
        active = await app.base.setup_and_contain_action(
            action_abbr="OPT", hloheader=HloHeaderModel(optional=spec_header)
        )
        starttime = time.time()
        # acquire at least 1 spectrum
        specdict = app.driver.acquire_spec_adv(**active.action.action_params)
        await active.enqueue_data_dflt(datadict=specdict)
        # duration loop
        if active.action.action_params["duration_sec"] > 0:
            while time.time() - starttime < active.action.action_params["duration_sec"]:
                specdict = app.driver.acquire_spec_adv(**active.action.action_params)
                await active.enqueue_data_dflt(datadict=specdict)

        active.action.action_params["peak_intensity"] = specdict.get(
            "peak_intensity", None
        )
        # wait 0.1 second to capture dangling data messages
        await asyncio.sleep(0.1)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/calibrate_intensity", tags=["action"])
    async def calibrate_intensity(
        int_time_ms: int = 35,
        n_avg: int = 3,
        peak_lower_wl: Optional[float] = 400,
        peak_upper_wl: Optional[float] = 750,
        target_peak_min: Optional[float] = 30000,
        target_peak_max: Optional[float] = 32000,
        max_iters: int = 5,
        max_integration_time: int = 150,
    ):
        """Iteratively adjust integration time until the peak falls in range.

        Scales the integration time toward the centre of
        ``[target_peak_min, target_peak_max]`` and re-acquires until the peak
        intensity is in range, ``max_iters`` is reached, or the integration
        time saturates at ``max_integration_time``. The final integration
        time and peak intensity are written back to ``action_params``.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            int_time_ms: Initial integration time in milliseconds.
            n_avg: Number of acquisitions averaged per iteration.
            peak_lower_wl: Lower wavelength bound for peak detection.
            peak_upper_wl: Upper wavelength bound for peak detection.
            target_peak_min: Lower bound of the desired peak intensity window.
            target_peak_max: Upper bound of the desired peak intensity window.
            max_iters: Maximum number of adjustment iterations.
            max_integration_time: Hard ceiling on integration time in ms.

        Returns:
            The finished action dictionary.
        """
        spec_header = {"wl": app.driver.pxwl}
        active = await app.base.setup_and_contain_action(
            action_abbr="OPT", hloheader=HloHeaderModel(optional=spec_header)
        )
        current_int_time = active.action.action_params["int_time_ms"]
        specdict = app.driver.acquire_spec_adv(**active.action.action_params)
        await active.enqueue_data_dflt(datadict=specdict)
        peak_int = specdict["peak_intensity"]
        LOGGER.info(f"Initial peak intensity: {peak_int}")
        target_avg = 0.5 * (
            active.action.action_params["target_peak_max"]
            + active.action.action_params["target_peak_min"]
        )
        adjust_count = 0
        max_reached = False
        while (
            (
                (peak_int < active.action.action_params["target_peak_min"])
                or (peak_int > active.action.action_params["target_peak_max"])
            )
            and adjust_count < active.action.action_params["max_iters"]
            and not max_reached
        ):
            if peak_int < active.action.action_params["target_peak_min"]:
                current_int_time = int(current_int_time * target_avg / peak_int)
            else:
                current_int_time = int(current_int_time * peak_int / target_avg)

            if current_int_time > active.action.action_params["max_integration_time"]:
                current_int_time = active.action.action_params["max_integration_time"]
                max_reached = True
            LOGGER.info(f"Adjusting integration time to: {current_int_time} ms")
            spec_params = active.action.action_params
            spec_params.update({"int_time_ms": current_int_time})
            specdict = app.driver.acquire_spec_adv(**spec_params)
            await active.enqueue_data_dflt(datadict=specdict)
            peak_int = specdict["peak_intensity"]
            LOGGER.info(f"Current peak intensity: {peak_int}")
            adjust_count += 1

        active.action.action_params["peak_intensity"] = peak_int
        active.action.action_params["calibrated_int_time_ms"] = current_int_time
        # wait 0.1 second to capture dangling data messages
        await asyncio.sleep(0.1)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/acquire_spec_extrig", tags=["action"])
    async def acquire_spec_extrig(
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        edge_mode: TriggerType = TriggerType.risingedge,
        int_time: int = 35,
        n_avg: int = 1,
        fft: int = 0,
        duration: float = -1,
    ):
        """Arm the spectrometer for externally triggered acquisitions.

        Validates samples and configures the trigger/edge/integration-time
        device state (K7b: moved here from the driver's former
        ``acquire_spec_extrig``/``contain_action`` call), then starts
        :class:`SM303Exec`, which waits on the configured trigger edge and
        captures spectra as triggers arrive.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            fast_samples_in: Sample references associated with this action.
            edge_mode: Trigger edge type used to gate acquisition.
            int_time: Integration time per spectrum in milliseconds.
            n_avg: Number of acquisitions averaged per output spectrum.
            fft: FFT smoothing parameter forwarded to the driver.
            duration: Total run duration in seconds; negative runs until
                stopped.

        Returns:
            The active action dictionary, or a finished-with-error action
            dict if trigger configuration or sample validation failed
            (matching the pre-migration behavior: neither case creates an
            ``Active`` action).
        """
        A = app.base.setup_action()
        A.action_abbr = "OPT"
        # K7 CRITICAL: read from action_params (subscript), never endpoint fn-args
        p = A.action_params

        LOGGER.info("Setting up external trigger.")
        trigset = app.driver.set_trigger_mode(SpecTrigType.external)
        edgeset = app.driver.set_extedge_mode(p["edge_mode"])
        inttset = app.driver.set_integration_time(p["int_time"])
        # TODO: can perform more checks like gamry technique wrapper...
        if not (trigset and edgeset and inttset):
            LOGGER.error(
                f"Could not set trigger_mode ('SpecTrigType.external'), edge_mode "
                f"({p['edge_mode']}), int_time ({p['int_time']}), or trigger_duration "
                f"({p['duration']})."
            )
            A.error_code = ErrorCodes.critical_error
            return A.as_dict()

        A.error_code = ErrorCodes.none
        # validate samples_in
        samples_in = await app.unified_db.get_samples(A.samples_in)
        if not samples_in and not app.driver.allow_no_sample:
            LOGGER.error(
                "Spec server got no valid sample, cannot start measurement!",
            )
            A.samples_in = []
            A.error_code = ErrorCodes.no_sample
            return A.as_dict()

        spec_header = {"wl": app.driver.pxwl}
        dflt_conn_key = app.base.dflt_file_conn_key()
        active = await app.base.contain_action(
            ActiveParams(
                action=A,
                file_conn_params_dict={
                    dflt_conn_key: FileConnParams(
                        file_conn_key=dflt_conn_key,
                        sample_global_labels=[
                            sample.get_global_label() for sample in samples_in
                        ],
                        file_type="spec_helao__file",
                        hloheader=HloHeaderModel(optional=spec_header),
                    )
                },
            )
        )
        for sample in samples_in:
            sample.reset_sample_status(SampleStatus.preserved)
            sample.inheritance = SampleInheritance.allow_both

        active.action.samples_in = []
        # now add updated samples to sample_in again
        await active.append_sample(samples=samples_in, IO="in")

        active.finish_hlo_header(
            realtime=active.get_realtime_nowait(),
            file_conn_keys=active.action.file_conn_keys,
        )

        LOGGER.info("External trigger task initiated.")
        executor = SM303Exec(active=active, oneoff=False, poll_rate=0.01)
        return active.start_executor(executor)

    @app.post(f"/{server_key}/stop_extrig_after", tags=["action"])
    async def stop_extrig_after(
        delay: int = 0,
    ):
        """Schedule a delayed stop of any running external-trigger capture.

        Waits ``delay`` seconds (mirroring the legacy driver-side
        ``stop(delay)``), disables the trigger via
        ``driver.stop_acquisition``, then signals any in-progress
        ``acquire_spec_extrig`` executor to stop via the action-server
        framework (the legacy ``IO_signalq``-driven stop is superseded by
        ``Active.stop_action_task``, since ``SM303Exec`` -- not a
        driver-owned ``IOloop`` -- now drives the collect loop).

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            delay: Seconds to wait before stopping the acquisition.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action()
        stop_resp = await app.driver.stop_acquisition(
            delay=active.action.action_params["delay"]
        )
        for exec_id, exec_active in list(app.base.executors.items()):
            if exec_id.split()[0] == "acquire_spec_extrig":
                exec_active.stop_action_task()
        await active.enqueue_data_dflt(datadict={"stop": stop_resp})
        finished_action = await active.finish()  # type: ignore
        return finished_action.as_dict()


def makeApp(server_key) -> BaseAPI:
    """Build the BaseAPI app for the SM303 spectrometer.

    Args:
        server_key: Unique key identifying this server in the orchestration
            group.

    Returns:
        The configured BaseAPI instance with spectrometer endpoints attached
        via :func:`sm303_dyn_endpoints`.
    """

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Spectrometer server",
        version=0.1,
        driver_classes=[SM303],
        dyn_endpoints=sm303_dyn_endpoints,
    )

    return app
