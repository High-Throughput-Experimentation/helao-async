# shell: uvicorn motion_server:app --reload
"""FastAPI action server for the SM303 spectrometer.

Provides endpoints for single and averaged spectrum acquisition, intensity
calibration that adjusts integration time toward a target peak window, and
externally-triggered captures. Hardware triggers are the preferred method
for synchronising spectral capture with an illumination source.
"""

__all__ = ["makeApp"]

import asyncio
import time
from typing import Optional, List, Union
from fastapi import Body
from helao.helpers.premodels import Action
from helao.core.servers.base_api import BaseAPI
from helao.core.models.sample import (
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
)
from helao.core.models.file import HloHeaderModel
from ...drivers.spec.spectral_products_driver import SM303

from ...drivers.io.enum import TriggerType

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


async def sm303_dyn_endpoints(app: BaseAPI):
    """Register SM303 spectrometer endpoints.

    Disables concurrent actions on this server and attaches private and
    action endpoints for wavelength retrieval, single/averaged acquisition,
    intensity calibration, and external trigger control.

    Args:
        app: The :class:`BaseAPI` instance being configured.
    """
    server_key = app.base.server.server_name
    app.base.server_params["allow_concurrent_actions"] = False

    @app.post("/get_wl", tags=["private"])
    def get_wl():
        """Return the spectrometer wavelength array with shape ``(num_pixels,)``."""
        return app.driver.pxwl  # type: ignore

    @app.post(f"/{server_key}/acquire_spec", tags=["action"])
    async def acquire_spec(
        action: Action = Body({}, embed=True),
        action_version: int = 2,
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
    async def acquire_spec_adv(
        action: Action = Body({}, embed=True),
        action_version: int = 2,
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
        action: Action = Body({}, embed=True),
        action_version: int = 1,
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
        action: Action = Body({}, embed=True),
        action_version: int = 1,
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

        The driver waits on the configured trigger edge and captures spectra
        as triggers arrive; results are streamed through the driver's
        internal active-action management.

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
            The active action dictionary returned by the driver.
        """
        A = app.base.setup_action()
        A.action_abbr = "OPT"
        LOGGER.info("Setting up external trigger.")
        active_dict = await app.driver.acquire_spec_extrig(A)
        LOGGER.info("External trigger task initiated.")
        return active_dict

    @app.post(f"/{server_key}/stop_extrig_after", tags=["action"])
    async def stop_extrig_after(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        delay: int = 0,
    ):
        """Schedule a delayed stop of any running external-trigger capture.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            delay: Seconds to wait before stopping the acquisition.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action()
        await app.driver.stop(delay=active.action.action_params["delay"])  # type: ignore
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
