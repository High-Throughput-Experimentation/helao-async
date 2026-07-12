# shell: uvicorn motion_server:app --reload
"""FastAPI action server for Gamry potentiostats.

Uses an Executor-based architecture: :class:`GamryExec` runs dtaq-driven
techniques (LSV, CA, CP, CV, OCV, RCA), and :class:`GamryEisExec` runs
potentiostatic/galvanostatic EIS sweeps via :class:`ReadZ`. The hardware
driver class is :class:`GamryDriver`; the server dynamically attaches one
endpoint per supported technique once the driver is initialised.
"""


__all__ = ["makeApp"]


import asyncio
import json
import time
import itertools
from typing import Optional, List, Union
from collections import defaultdict, deque

import numpy as np
import pandas as pd
from fastapi import Body, Query

from helao.core.error import ErrorCodes
from helao.core.models.sample import (
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
)
from helao.core.models.hlostatus import HloStatus
from helao.core.models.file import HloFileGroup

from helao.core.servers.base_api import BaseAPI, action_version
from helao.helpers.executor import Executor
from helao.helpers import helao_logging as logging  # get LOGGER from BaseAPI instance
from helao.helpers.yml_tools import yml_dumps
from helao.helpers.bubble_detection import bubble_detection
from ...drivers.pstat.gamry.driver import GamryDriver, DriverStatus, ControlMode
from ...drivers.pstat.gamry.technique import (
    GamryTechnique,
    TECH_LSV,
    TECH_CA,
    TECH_CP,
    TECH_CV,
    TECH_OCV,
    TECH_RCA,
)
from ...drivers.pstat.gamry.readz import ReadZ, measure_ocv

global LOGGER
LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class GamryExec(Executor):
    """Executor that runs a single Gamry dtaq-based technique.

    Splits action parameters into signal, dtaq, TTL trigger, and alert
    groups; configures the driver in ``_pre_exec``; starts the measurement
    in ``_exec``; polls the dtaq event sink in ``_poll`` while checking
    optional Ewe/I alert thresholds; computes mean Ewe/I/t outputs in
    ``_post_exec`` (and a bubble-detection flag for OCV runs); and forwards
    user stops to the driver in ``_manual_stop``.

    Attributes:
        technique: The :class:`GamryTechnique` definition to execute.
        driver: The bound :class:`GamryDriver` instance.
        data_buffer: Rolling deques of the last 1000 points per channel
            used for output statistics and alert windowing.
        signal_params: Subset of action params relevant to the signal.
        dtaq_params: Subset of action params relevant to the dtaq.
        ttl_params: TTLwait/TTLsend trigger bits.
        alert_params: Thresholds and timing for runtime alerts.
    """

    technique: GamryTechnique
    driver: GamryDriver

    def __init__(self, *args, **kwargs):
        """Cache the technique, driver, and parameter groupings.

        Args:
            *args: Forwarded to :class:`Executor`.
            **kwargs: Must include ``technique`` (:class:`GamryTechnique`).
        """
        super().__init__(*args, **kwargs)
        try:
            self.poll_rate = 0.01  # pump events every 10 millisecond
            self.concurrent = False
            self.start_time = time.time()
            self.data_buffer = defaultdict(lambda: deque(maxlen=1000))

            # link attrs for convenience
            self.action_params = self.active.action.action_params
            self.driver = self.active.driver

            # no external timer, event sink signals end of measurement
            self.duration = -1
            self.technique = kwargs["technique"]

            # split action params into dtaq and signal dicts
            self.dtaq_params = {
                k: v
                for k, v in self.action_params.items()
                if k
                in self.technique.dtaq.int_param_keys
                + self.technique.dtaq.bool_param_keys
            }
            self.signal_params = {
                k: v
                for k, v in self.action_params.items()
                if k
                in self.technique.signal.param_keys + self.technique.signal.init_keys
            }
            self.ierange = self.action_params.get("IErange", "auto")
            self.ttl_params = {
                k: self.action_params.get(k, -1) for k in ("TTLwait", "TTLsend")
            }
            self.alert_params = {
                k: self.action_params.get(k, None)
                for k in (
                    "alertThreshEwe_V",
                    "alertThreshI_A",
                    "alert_above",
                    "alert_duration__s",
                    "alert_sleep__s",
                )
            }
            self.last_alert_time = 0

            LOGGER.info("GamryExec initialized.")
        except Exception:
            LOGGER.error("GamryExec was not initialized.", exc_info=True)

    async def _pre_exec(self) -> dict:
        """Wait for the cell to be free and configure the technique.

        Polls ``get_gamry_state`` until the cell is idle (up to 30 s) and
        then calls ``driver.setup`` with the technique, signal, dtaq, and
        IE-range parameters.

        Returns:
            Dict with ``error`` set to :attr:`ErrorCodes.none` on success or
            :attr:`ErrorCodes.setup` on timeout or driver failure.
        """
        max_wait = 30
        init_time = time.time()
        while self.driver.get_gamry_state()["Cell"] != "0":
            if time.time() - init_time > max_wait:
                LOGGER.error("Gamry cell is busy. Timeout reached.")
                return {"error": ErrorCodes.setup}
            LOGGER.warning("Gamry cell is busy. Waiting 1 second.")
            await asyncio.sleep(1)
        resp = self.driver.setup(
            self.technique,
            self.signal_params,
            self.dtaq_params,
            self.action_params,
            self.ierange,
        )
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.setup
        return {"error": error}

    async def _exec(self) -> dict:
        """Wait for a TTL trigger (if configured) and start the measurement.

        Returns:
            Dict with ``error`` set to :attr:`ErrorCodes.none` on a successful
            ``measure`` call or :attr:`ErrorCodes.critical_error` otherwise.
        """
        if self.ttl_params["TTLwait"] > -1:
            bits = self.driver.pstat.DigitalIn()
            LOGGER.info(f"Gamry DIbits: {bits}, waiting for trigger.")
            while not bits:
                await asyncio.sleep(0.001)
                bits = self.driver.pstat.DigitalIn()
        LOGGER.debug("starting measurement")
        resp = self.driver.measure(self.ttl_params)
        self.start_time = resp.data.get("start_time", time.time())
        error = (
            ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
        )
        return {"error": error}

    async def _poll(self) -> dict:
        """Drain the dtaq event sink and apply runtime alert checks.

        Appends each polled data slice to ``self.data_buffer`` and, when
        ``alert_params`` defines a threshold, walks the rolling time buffer
        backwards to find a window of at least ``alert_duration__s`` of
        consecutive points above/below the configured Ewe/I threshold.
        Triggered alerts are emitted via ``LOGGER.alert``.

        Returns:
            Dict with ``error``, an :class:`HloStatus` (``finished`` once the
            dtaq reports ``done``), and the latest ``data`` slice.
        """
        try:
            resp = self.driver.get_data(self.poll_rate)
            # populate executor buffer for output calculation
            for k, v in resp.data.items():
                self.data_buffer[k].extend(v)
            # check for alert thresholds at this point in data_buffer
            poll_iter_time = time.time()
            if self.alert_params["alert_sleep__s"] is not None:
                single_alert = (
                    self.alert_params["alert_sleep__s"] <= 0
                    and self.last_alert_time == 0
                )
                ongoing_alert = self.alert_params["alert_sleep__s"] > 0 and (
                    poll_iter_time - self.last_alert_time
                    > self.alert_params["alert_sleep__s"]
                )
                if single_alert or ongoing_alert:
                    LOGGER.debug(
                        f"single_alert: {single_alert}, ongoing_alert: {ongoing_alert}"
                    )
                    min_duration = self.alert_params["alert_duration__s"]
                    if (
                        min_duration > 0
                        and self.data_buffer.get("t_s", [-1])[-1] > min_duration
                    ):
                        LOGGER.debug(
                            f"elapsed time is above min_duration: {min_duration}"
                        )
                        time_buffer = self.data_buffer["t_s"]
                        idx = 1
                        latest_t = time_buffer[-1]
                        slice_duration = latest_t - time_buffer[-idx]
                        while (len(time_buffer) > idx) and (
                            slice_duration < min_duration
                        ):
                            idx += 1
                            slice_duration = latest_t - time_buffer[-idx]
                        LOGGER.debug(f"slice index is: {-idx}")
                        if slice_duration >= min_duration:
                            LOGGER.debug(
                                f"slice_duration {slice_duration:.3f} is above min_duration"
                            )
                            for thresh_key in ("Ewe_V", "I_A"):
                                thresh_val = self.alert_params.get(
                                    f"alertThresh{thresh_key}", None
                                )
                                if thresh_val is not None:
                                    data_dq = self.data_buffer[thresh_key]
                                    slice_vals = list(
                                        itertools.islice(
                                            data_dq, len(data_dq) - idx, len(data_dq)
                                        )
                                    )
                                    if (
                                        all([x > thresh_val for x in slice_vals])
                                        and self.alert_params["alert_above"]
                                    ):
                                        LOGGER.alert(
                                            f"{thresh_key} went above {thresh_val} for {min_duration} seconds."
                                        )
                                        self.last_alert_time = poll_iter_time
                                    elif (
                                        all([x < thresh_val for x in slice_vals])
                                        and not self.alert_params["alert_above"]
                                    ):
                                        LOGGER.alert(
                                            f"{thresh_key} went below {thresh_val} for {min_duration} seconds."
                                        )
                                        self.last_alert_time = poll_iter_time
            error = (
                ErrorCodes.none
                if resp.response == "success"
                else ErrorCodes.critical_error
            )
            status = HloStatus.active if resp.message != "done" else HloStatus.finished
            return {"error": error, "status": status, "data": resp.data}
        except Exception:
            LOGGER.error("GamryExec poll error", exc_info=True)
            print(data_dq)
            return {"error": ErrorCodes.critical_error, "status": HloStatus.errored}

    async def _post_exec(self) -> dict:
        """Compute summary statistics and run OCV bubble detection.

        Calls ``driver.cleanup``, stores the mean of the final five samples
        of ``t_s``, ``Ewe_V``, and ``I_A`` back into ``action_params`` under
        ``<key>__mean_final``, and, for ``run_OCV`` actions, calls
        :func:`bubble_detection` and stores the boolean result under
        ``has_bubble``.

        Returns:
            Dict with ``error`` (success or critical) and an empty ``data``.
        """
        resp = self.driver.cleanup(self.ttl_params)

        # parse calculate outputs from data buffer:
        for k in ["t_s", "Ewe_V", "I_A"]:
            if k in self.data_buffer:
                meanv = np.nanmean(np.array(self.data_buffer[k])[-5:])
                self.active.action.action_params[f"{k}__mean_final"] = meanv

        if self.active.action.action_name == "run_OCV":
            data_df = pd.DataFrame(self.data_buffer)
            rsd_thresh = self.action_params.get("RSD_threshold", 1)
            simple_thresh = self.action_params.get("simple_threshold", 1)
            signal_change_thresh = self.action_params.get("signal_change_threshold", 1)
            amplitude_thresh = self.action_params.get("amplitude_threshold", 1)
            has_bubble = bubble_detection(
                data_df,
                rsd_thresh,
                simple_thresh,
                signal_change_thresh,
                amplitude_thresh,
            )
            self.active.action.action_params["has_bubble"] = has_bubble

        error = (
            ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
        )
        return {"error": error, "data": {}}

    async def _manual_stop(self) -> dict:
        """Stop the active technique and disconnect the cell on demand.

        Returns:
            Dict with ``error`` set to :attr:`ErrorCodes.none` on success or
            :attr:`ErrorCodes.stop` if the driver stop call fails.
        """
        resp = await self.driver.stop()
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.stop
        return {"error": error}


class GamryEisExec(Executor):
    """Executor that runs a PEIS or GEIS frequency sweep.

    Builds a logarithmically spaced frequency list from
    ``Finit__Hz``/``Ffinal__Hz``/``FrequenciesPerDecade``, performs an
    optional pre-measurement OCV to update the DC offset, and steps the
    :class:`ReadZ` instance through each frequency. Retries on the same
    frequency are bounded by ``MaxRetries``.

    Attributes:
        driver: The bound :class:`GamryDriver` instance.
        readz: The :class:`ReadZ` instance attached to the driver.
        control_mode: Pstat or Gstat mode chosen by the action abbreviation.
        offset: Initial DC offset (optionally OCV-corrected).
        freq_list: Computed list of measurement frequencies (Hz).
        z_expected: Expected impedance used to pick IE range.
        freq_idx: Current index into ``freq_list``.
        retry_count: Retries accumulated at the current frequency.
        max_repeats: Per-frequency retry limit (``MaxRetries`` param).
    """

    driver: GamryDriver
    readz: ReadZ

    def __init__(self, *args, **kwargs):
        """Build the frequency list and cache offsets and control mode.

        Args:
            *args: Forwarded to :class:`Executor`.
            **kwargs: Forwarded to :class:`Executor`.
        """
        super().__init__(*args, **kwargs)
        try:
            self.action_params = self.active.action.action_params
            self.poll_rate = 0.01  # pump events every 10 millisecond
            self.concurrent = False
            self.data_buffer = defaultdict(lambda: deque(maxlen=1000))

            self.ttl_params = {
                k: self.action_params.get(k, -1) for k in ("TTLwait", "TTLsend")
            }
            # link attrs for convenience
            self.max_repeats = self.action_params["MaxRetries"]
            self.driver = self.active.driver

            if self.active.action.action_abbr == "PEIS":
                self.control_mode = ControlMode.PstatMode
                self.offset = self.action_params.get("Voffset__V", 0.0)

            else:
                self.control_mode = ControlMode.GstatMode
                self.offset = self.action_params.get("Ioffset__A", 0.0)

            decades = np.abs(
                np.log10(
                    self.action_params["Finit__Hz"] / self.action_params["Ffinal__Hz"]
                )
            )
            self.freq_list = np.logspace(
                np.log10(self.action_params["Finit__Hz"]),
                np.log10(self.action_params["Ffinal__Hz"]),
                num=int(decades) * self.action_params["FrequenciesPerDecade"] + 1,
            ).tolist()
            self.z_expected = self.action_params["Zinit_expected_Ohm"]
            self.freq_idx = 0
            self.retry_count = 0

            # no external timer, event sink signals end of measurement
            self.duration = -1

            LOGGER.info("GamryEisExec initialized.")
        except Exception:
            LOGGER.error("GamryEisExec was not initialized.", exc_info=True)

    async def _pre_exec(self) -> dict:
        """Wait for the cell to be free, optionally measure OCV, set up EIS.

        Polls until the cell is idle (up to 30 s). If ``versus_OCV`` is set,
        runs :func:`measure_ocv` for ``OCV_duration__s`` seconds, writes the
        OCV trace as a HELAO file, and adds the mean of the final five
        samples to ``self.offset``. Then calls ``driver.setup_eis`` and
        ``readz.init_pstat`` to arm the sweep.

        Returns:
            Dict with ``error`` set to :attr:`ErrorCodes.none` on success or
            :attr:`ErrorCodes.setup` on failure.
        """
        max_wait = 30
        init_time = time.time()
        while self.driver.get_gamry_state()["Cell"] != "0":
            if time.time() - init_time > max_wait:
                LOGGER.error("Gamry cell is busy. Timeout reached.")
                return {"error": ErrorCodes.setup}
            LOGGER.warning("Gamry cell is busy. Waiting 1 second.")
            await asyncio.sleep(1)
        try:
            if self.action_params.get("versus_OCV", False):
                ocv_duration = self.action_params.get("OCV_duration__s", 2.0)
                ocv_acq_period = self.action_params.get(
                    "OCV_acquisition_period__s", 0.1
                )
                LOGGER.info(f"measuring OCV for {ocv_duration:.1f} seconds")
                ts, vs = await measure_ocv(
                    self.driver.pstat,
                    self.driver.GamryCOM,
                    ocv_duration,
                    ocv_acq_period,
                )
                self.mean_ocv = np.mean(vs[-5:])
                self.offset += self.mean_ocv
                ocv_data = {"t_s": ts, "Ewe_V": vs}
                await self.active.write_file(
                    output_str=json.dumps(ocv_data),
                    file_type="pstat_helao__file",
                    filename="init_ocv.hlo",
                    file_group=HloFileGroup.helao_files,
                    header=yml_dumps({"mean_ocv": float(self.mean_ocv)}),
                    json_data_keys=list(ocv_data.keys()),
                )
                LOGGER.info(f"OCV result: {self.mean_ocv:.3f} V")

            # create ReadZ instance and attach to driver (self.driver.readz)
            resp = self.driver.setup_eis(
                control_mode=self.control_mode,
                fast=self.action_params["ReadFast"],
                frequency=self.freq_list[self.freq_idx],
                dc_amplitude=self.offset,
                ac_amplitude=self.action_params[
                    (
                        "Vamp__V"
                        if self.control_mode == ControlMode.PstatMode
                        else "Iamp__A"
                    )
                ],
                z_expected=self.z_expected,
                set_ierange_ac=self.action_params["IErange_fromAC"],
            )
            if resp.status == DriverStatus.error:
                raise Exception("GamryEisExec driver setup_eis failed.")
            self.readz = self.driver.readz

            resp = self.readz.init_pstat()
            error = ErrorCodes.none if resp.response == "success" else ErrorCodes.setup
        except Exception:
            LOGGER.error("GamryEisExec _pre_exec error", exc_info=True)
            error = ErrorCodes.setup
        return {"error": error}

    async def _exec(self) -> dict:
        """Wait for a TTL trigger if configured and start the first frequency.

        Returns:
            Dict with ``error`` set to :attr:`ErrorCodes.none` on success or
            :attr:`ErrorCodes.critical_error` on exception.
        """
        try:
            if self.ttl_params["TTLwait"] > -1:
                bits = self.driver.pstat.DigitalIn()
                LOGGER.info(f"Gamry DIbits: {bits}, waiting for trigger.")
                while not bits:
                    await asyncio.sleep(0.001)
                    bits = self.driver.pstat.DigitalIn()
            LOGGER.debug("starting measurement")
            self.readz.measure_frequency(self.freq_list[self.freq_idx])
            self.start_time = time.time()
            error = ErrorCodes.none
        except Exception:
            LOGGER.error("GamryEisExec _exec error", exc_info=True)
            error = ErrorCodes.critical_error
        return {"error": error}

    async def _poll(self) -> dict:
        """Advance the EIS sweep based on the dtaq event message.

        Reads the latest :class:`ReadZ` response and acts on its ``message``:
        ``retry`` increments the retry count, ``done`` advances ``freq_idx``,
        and any other non-measuring message resets the dtaq sink and starts
        the next frequency (optionally rescaling the IE range from the
        previous Zmod when ``IErange_fromAC`` is true on GEIS). The sweep
        terminates when the retry limit is exceeded or all frequencies are
        consumed.

        Returns:
            Dict containing ``error``, an :class:`HloStatus`, and ``data``
            with an injected ``t_s`` relative to ``start_time``.
        """
        try:
            resp = self.readz.get_data(self.poll_rate)
            error = (
                ErrorCodes.none
                if resp.response == "success"
                else ErrorCodes.critical_error
            )
            status = HloStatus.active
            if resp.message in ["error", "idle"]:
                status = HloStatus.finished
            else:
                if resp.message == "retry":
                    self.retry_count += 1
                elif resp.message == "done":
                    self.retry_count = 0
                    self.freq_idx += 1

                if self.retry_count > self.max_repeats or self.freq_idx == len(
                    self.freq_list
                ):
                    status = HloStatus.finished
                elif resp.message == "measuring":
                    pass
                else:
                    self.readz.dtaqsink.reset()
                    LOGGER.info(
                        f"Proceeding to frequency {self.freq_list[self.freq_idx]:.2e} Hz ({self.freq_idx+1}/{len(self.freq_list)}), attempt {self.retry_count}/{self.max_repeats}."
                    )
                    if (
                        self.action_params["IErange_fromAC"]
                        and self.active.action.action_abbr == "GEIS"
                    ):
                        self.z_expected = resp.data.get("Zmod", self.z_expected)
                        self.readz.set_ierange(
                            self.freq_list[self.freq_idx], self.z_expected
                        )
                    self.readz.measure_frequency(self.freq_list[self.freq_idx])

            if resp.data:
                resp.data["t_s"] = time.time() - self.start_time
            return {"error": error, "status": status, "data": resp.data}
        except Exception:
            LOGGER.error("GamryExec poll error", exc_info=True)
            return {"error": ErrorCodes.critical_error, "status": HloStatus.errored}

    async def _post_exec(self) -> dict:
        """Tear down the EIS state on the driver.

        Calls ``driver.cleanup`` and ``driver.close_eis`` and clears both
        the executor's and the driver's ``readz`` reference.

        Returns:
            Dict with ``error`` (success or critical) and an empty ``data``.
        """
        resp = self.driver.cleanup(self.ttl_params)
        self.driver.close_eis()
        self.driver.readz = None
        self.readz = None

        error = (
            ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
        )
        return {"error": error, "data": {}}

    async def _manual_stop(self) -> dict:
        """Stop the active EIS sweep on demand.

        Returns:
            Dict with ``error`` set to :attr:`ErrorCodes.none` on success or
            :attr:`ErrorCodes.stop` if the stop call fails.
        """
        resp = await self.readz.stop()
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.stop
        return {"error": error}


async def gamry_dyn_endpoints(app: BaseAPI):
    """Register all Gamry technique endpoints once the driver is ready.

    Blocks until ``app.driver.ready`` is true, disables concurrent actions,
    captures the driver model's IE-range enum to use as the ``IErange``
    parameter type, and attaches one endpoint per technique
    (LSV, CA, CP, CV, OCV, RCA, PEIS, GEIS).

    Args:
        app: The :class:`BaseAPI` instance being configured.
    """
    server_key = app.base.server.server_name
    app.base.server_params["allow_concurrent_actions"] = False

    while not app.driver.ready:
        LOGGER.info("waiting for gamry init")
        await asyncio.sleep(1)

    model_ierange = app.driver.model.ierange

    @app.post(f"/{server_key}/run_LSV", tags=["action"])
    @action_version(3)
    async def run_LSV(
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        Vinit__V: float = 0.0,  # Initial value in volts or amps.
        Vfinal__V: float = 1.0,  # Final value in volts or amps.
        ScanRate__V_s: float = 1.0,  # Scan rate in volts/sec or amps/sec.
        AcqInterval__s: float = 0.01,  # Time between data acq in seconds.
        TTLwait: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
        TTLsend: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
        IErange: model_ierange = "auto",
        SetStopIMin: Optional[float] = None,
        SetStopIMax: Optional[float] = None,
        SetStopDIMin: Optional[float] = None,
        SetStopDIMax: Optional[float] = None,
        SetStopADIMin: Optional[float] = None,
        SetStopADIMax: Optional[float] = None,
        SetStopAtDelayIMin: Optional[int] = None,
        SetStopAtDelayIMax: Optional[int] = None,
        SetStopAtDelayDIMin: Optional[int] = None,
        SetStopAtDelayDIMax: Optional[int] = None,
        SetStopAtDelayADIMin: Optional[int] = None,
        SetStopAtDelayADIMax: Optional[int] = None,
        alert_duration__s: float = -1,
        alert_above: bool = True,
        alert_sleep__s: float = -1,
        alertThreshI_A: float = 0,
        comment: str = "",
    ):
        """Start a Linear Sweep Voltammetry run via :class:`GamryExec`.

        A forward-only voltage sweep is performed (no return scan).
        ``TTLwait``/``TTLsend`` use the lower 4 bits as a trigger bitmask;
        ``IErange`` accepts values supported by the connected potentiostat
        model.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            fast_samples_in: Sample references associated with this action.
            Vinit__V: Initial potential in volts.
            Vfinal__V: Final potential in volts.
            ScanRate__V_s: Scan rate in V/s.
            AcqInterval__s: Sample interval in seconds.
            TTLwait: TTL channel to wait on (``-1`` disables).
            TTLsend: TTL channel to assert on start (``-1`` disables).
            IErange: Current range setting; ``"auto"`` for autoranging.
            SetStopIMin: Lower current threshold for early stop.
            SetStopIMax: Upper current threshold for early stop.
            SetStopDIMin: Lower dI/dt threshold for early stop.
            SetStopDIMax: Upper dI/dt threshold for early stop.
            SetStopADIMin: Lower |dI/dt| threshold for early stop.
            SetStopADIMax: Upper |dI/dt| threshold for early stop.
            SetStopAtDelayIMin: Consecutive-point delay for ``SetStopIMin``.
            SetStopAtDelayIMax: Consecutive-point delay for ``SetStopIMax``.
            SetStopAtDelayDIMin: Consecutive-point delay for ``SetStopDIMin``.
            SetStopAtDelayDIMax: Consecutive-point delay for ``SetStopDIMax``.
            SetStopAtDelayADIMin: Consecutive-point delay for ``SetStopADIMin``.
            SetStopAtDelayADIMax: Consecutive-point delay for ``SetStopADIMax``.
            alert_duration__s: Minimum duration for runtime alerts (seconds).
            alert_above: Whether to alert on above- or below-threshold.
            alert_sleep__s: Suppression window between alerts.
            alertThreshI_A: Current alert threshold in amperes.
            comment: Free-form comment recorded with the action.

        Returns:
            The active action dictionary from ``start_executor``.
        """
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "LSV"
        executor = GamryExec(active=active, oneoff=False, technique=TECH_LSV)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_CA", tags=["action"])
    @action_version(3)
    async def run_CA(
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        Vval__V: float = 0.0,
        Tval__s: float = 10.0,
        AcqInterval__s: float = 0.01,  # Time between data acq in seconds.
        TTLwait: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
        TTLsend: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
        IErange: model_ierange = "auto",
        SetStopXMin: Optional[
            float
        ] = None,  # lower current threshold to trigger early stopping
        SetStopXMax: Optional[
            float
        ] = None,  # upper current threshold to trigger early stopping
        SetStopAtDelayXMin: Optional[
            int
        ] = None,  # number of consecutive points below SetStopXMin to trigger early stopping
        SetStopAtDelayXMax: Optional[
            int
        ] = None,  # number of consecutive points above SetStopXMax to trigger early stopping
        alert_duration__s: float = -1,
        alert_above: bool = True,
        alert_sleep__s: float = -1,
        alertThreshI_A: float = 0,
        comment: str = "",
    ):
        """Start a Chronoamperometry run via :class:`GamryExec`.

        Holds ``Vval__V`` for ``Tval__s`` while sampling current at
        ``AcqInterval__s``. ``TTLwait``/``TTLsend`` use the lower 4 bits as
        a trigger bitmask.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            fast_samples_in: Sample references associated with this action.
            Vval__V: Hold potential in volts.
            Tval__s: Hold duration in seconds.
            AcqInterval__s: Sample interval in seconds.
            TTLwait: TTL channel to wait on (``-1`` disables).
            TTLsend: TTL channel to assert on start (``-1`` disables).
            IErange: Current range setting; ``"auto"`` for autoranging.
            SetStopXMin: Lower current threshold for early stop.
            SetStopXMax: Upper current threshold for early stop.
            SetStopAtDelayXMin: Consecutive-point delay for ``SetStopXMin``.
            SetStopAtDelayXMax: Consecutive-point delay for ``SetStopXMax``.
            alert_duration__s: Minimum duration for runtime alerts (seconds).
            alert_above: Whether to alert on above- or below-threshold.
            alert_sleep__s: Suppression window between alerts.
            alertThreshI_A: Current alert threshold in amperes.
            comment: Free-form comment recorded with the action.

        Returns:
            The active action dictionary from ``start_executor``.
        """
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "CA"
        executor = GamryExec(active=active, oneoff=False, technique=TECH_CA)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_CP", tags=["action"])
    @action_version(3)
    async def run_CP(
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        Ival__A: float = 0.0,
        Tval__s: float = 10.0,
        AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
        TTLwait: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
        TTLsend: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
        IErange: model_ierange = "auto",
        SetStopXMin: Optional[
            float
        ] = None,  # lower potential threshold to trigger early stopping
        SetStopXMax: Optional[
            float
        ] = None,  # upper potential threshold to trigger early stopping
        SetStopAtDelayXMin: Optional[
            int
        ] = None,  # number of consecutive points below SetStopXMin to trigger early stopping
        SetStopAtDelayXMax: Optional[
            int
        ] = None,  # number of consecutive points above SetStopXMax to trigger early stopping
        alert_duration__s: float = -1,
        alert_above: bool = True,
        alert_sleep__s: float = -1,
        alertThreshEwe_V: float = 0,
        comment: str = "",
    ):
        """Start a Chronopotentiometry run via :class:`GamryExec`.

        Holds ``Ival__A`` for ``Tval__s`` while sampling potential at
        ``AcqInterval__s``. ``TTLwait``/``TTLsend`` use the lower 4 bits as
        a trigger bitmask.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            fast_samples_in: Sample references associated with this action.
            Ival__A: Hold current in amperes.
            Tval__s: Hold duration in seconds.
            AcqInterval__s: Sample interval in seconds.
            TTLwait: TTL channel to wait on (``-1`` disables).
            TTLsend: TTL channel to assert on start (``-1`` disables).
            IErange: Current range setting; ``"auto"`` for autoranging.
            SetStopXMin: Lower potential threshold for early stop.
            SetStopXMax: Upper potential threshold for early stop.
            SetStopAtDelayXMin: Consecutive-point delay for ``SetStopXMin``.
            SetStopAtDelayXMax: Consecutive-point delay for ``SetStopXMax``.
            alert_duration__s: Minimum duration for runtime alerts (seconds).
            alert_above: Whether to alert on above- or below-threshold.
            alert_sleep__s: Suppression window between alerts.
            alertThreshEwe_V: Potential alert threshold in volts.
            comment: Free-form comment recorded with the action.

        Returns:
            The active action dictionary from ``start_executor``.
        """
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "CP"
        executor = GamryExec(active=active, oneoff=False, technique=TECH_CP)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_CV", tags=["action"])
    @action_version(3)
    async def run_CV(
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        Vinit__V: float = 0.0,  # Initial value in volts or amps.
        Vapex1__V: float = 1.0,  # Apex 1 value in volts or amps.
        Vapex2__V: float = -1.0,  # Apex 2 value in volts or amps.
        Vfinal__V: float = 0.0,  # Final value in volts or amps.
        ScanRate__V_s: float = 1.0,  # Scan rate in volts/sec or amps/sec.
        AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
        Cycles: int = 1,
        TTLwait: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
        TTLsend: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
        IErange: model_ierange = "auto",
        SetStopIMin: Optional[
            float
        ] = None,  # lower current threshold to trigger early stopping
        SetStopIMax: Optional[
            float
        ] = None,  # upper current threshold to trigger early stopping
        SetStopAtDelayIMin: Optional[
            int
        ] = None,  # number of consecutive points below SetStopIMin to trigger early stopping
        SetStopAtDelayIMax: Optional[
            int
        ] = None,  # number of consecutive points above SetStopIMax to trigger early stopping
        alert_duration__s: float = -1,
        alert_above: bool = True,
        alert_sleep__s: float = -1,
        alertThreshI_A: float = 0,
        comment: str = "",
    ):
        """Start a Cyclic Voltammetry run via :class:`GamryExec`.

        Sweeps from ``Vinit__V`` to ``Vapex1__V`` to ``Vapex2__V`` to
        ``Vfinal__V`` at ``ScanRate__V_s`` for ``Cycles`` cycles, sampling
        every ``AcqInterval__s``. ``TTLwait``/``TTLsend`` use the lower
        4 bits as a trigger bitmask.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            fast_samples_in: Sample references associated with this action.
            Vinit__V: Initial potential in volts.
            Vapex1__V: First apex potential in volts.
            Vapex2__V: Second apex potential in volts.
            Vfinal__V: Final potential in volts.
            ScanRate__V_s: Scan rate in V/s.
            AcqInterval__s: Sample interval in seconds.
            Cycles: Number of CV cycles to run.
            TTLwait: TTL channel to wait on (``-1`` disables).
            TTLsend: TTL channel to assert on start (``-1`` disables).
            IErange: Current range setting; ``"auto"`` for autoranging.
            SetStopIMin: Lower current threshold for early stop.
            SetStopIMax: Upper current threshold for early stop.
            SetStopAtDelayIMin: Consecutive-point delay for ``SetStopIMin``.
            SetStopAtDelayIMax: Consecutive-point delay for ``SetStopIMax``.
            alert_duration__s: Minimum duration for runtime alerts (seconds).
            alert_above: Whether to alert on above- or below-threshold.
            alert_sleep__s: Suppression window between alerts.
            alertThreshI_A: Current alert threshold in amperes.
            comment: Free-form comment recorded with the action.

        Returns:
            The active action dictionary from ``start_executor``.
        """
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "CV"
        executor = GamryExec(active=active, oneoff=False, technique=TECH_CV)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_OCV", tags=["action"])
    @action_version(3)
    async def run_OCV(
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        Tval__s: float = 10.0,
        AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
        RSD_threshold: float = 1,
        simple_threshold: float = 0.3,
        signal_change_threshold: float = 0.01,
        amplitude_threshold: float = 0.05,
        TTLwait: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
        TTLsend: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
        IErange: model_ierange = "auto",
        SetStopADVMin: Optional[float] = None,
        SetStopADVMax: Optional[float] = None,
        alert_duration__s: float = -1,
        alert_above: bool = True,
        alert_sleep__s: float = -1,
        alertThreshEwe_V: float = 0,
        comment: str = "",
    ):
        """Measure open-circuit potential via :class:`GamryExec`.

        The post-exec hook runs :func:`bubble_detection` over the recorded
        Ewe trace using the four ``*_threshold`` parameters and stores the
        boolean result under ``action_params['has_bubble']``.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            fast_samples_in: Sample references associated with this action.
            Tval__s: Total measurement duration in seconds.
            AcqInterval__s: Sample interval in seconds.
            RSD_threshold: RSD threshold forwarded to :func:`bubble_detection`.
            simple_threshold: Simple-difference threshold for bubble detection.
            signal_change_threshold: Signal-change threshold for bubble detection.
            amplitude_threshold: Amplitude threshold for bubble detection.
            TTLwait: TTL channel to wait on (``-1`` disables).
            TTLsend: TTL channel to assert on start (``-1`` disables).
            IErange: Current range setting; ``"auto"`` for autoranging.
            SetStopADVMin: Lower |dV/dt| early-stop threshold.
            SetStopADVMax: Upper |dV/dt| early-stop threshold.
            alert_duration__s: Minimum duration for runtime alerts (seconds).
            alert_above: Whether to alert on above- or below-threshold.
            alert_sleep__s: Suppression window between alerts.
            alertThreshEwe_V: Potential alert threshold in volts.
            comment: Free-form comment recorded with the action.

        Returns:
            The active action dictionary from ``start_executor``.
        """
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "OCV"
        executor = GamryExec(active=active, oneoff=False, technique=TECH_OCV)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_RCA", tags=["action"])
    @action_version(3)
    async def run_RCA(
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        Vinit__V: float = 0.0,
        Tinit__s: float = 0.5,
        Vstep__V: float = 0.5,
        Tstep__s: float = 0.5,
        Cycles: int = 5,
        AcqInterval__s: float = 0.01,  # acquisition rate
        TTLwait: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
        TTLsend: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
        IErange: model_ierange = "auto",
        alert_duration__s: float = -1,
        alert_above: bool = True,
        alert_sleep__s: float = -1,
        alertThreshI_A: float = 0,
        comment: str = "",
    ):
        """Run a pulsed-voltammetry cycle via :class:`GamryExec`.

        Builds a per-cycle ``SignalArray__V`` that holds ``Vinit__V`` for
        ``Tinit__s`` then steps to ``Vstep__V`` for ``Tstep__s``, sampled
        at ``AcqInterval__s``, repeated for ``Cycles`` cycles.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            fast_samples_in: Sample references associated with this action.
            Vinit__V: Resting potential within a cycle.
            Tinit__s: Resting phase duration in seconds.
            Vstep__V: Stepped potential within a cycle.
            Tstep__s: Stepped phase duration in seconds.
            Cycles: Number of pulse cycles to run.
            AcqInterval__s: Sample interval in seconds.
            TTLwait: TTL channel to wait on (``-1`` disables).
            TTLsend: TTL channel to assert on start (``-1`` disables).
            IErange: Current range setting; ``"auto"`` for autoranging.
            alert_duration__s: Minimum duration for runtime alerts (seconds).
            alert_above: Whether to alert on above- or below-threshold.
            alert_sleep__s: Suppression window between alerts.
            alertThreshI_A: Current alert threshold in amperes.
            comment: Free-form comment recorded with the action.

        Returns:
            The active action dictionary from ``start_executor``.
        """
        active = await app.base.setup_and_contain_action()

        # custom signal array can't be done with mapping, generate array here
        Vinit = active.action.action_params["Vinit__V"]
        Tinit = active.action.action_params["Tinit__s"]
        Vstep = active.action.action_params["Vstep__V"]
        Tstep = active.action.action_params["Tstep__s"]
        AcqInt = active.action.action_params["AcqInterval__s"]

        cycle_time = Tinit + Tstep
        points_per_cycle = round(cycle_time / AcqInt)
        active.action.action_params["AcqPointsPerCycle"] = points_per_cycle
        active.action.action_params["SignalArray__V"] = [
            Vinit if i * AcqInt <= Tinit else Vstep for i in range(points_per_cycle)
        ]

        active.action.action_abbr = "RCA"
        executor = GamryExec(active=active, oneoff=False, technique=TECH_RCA)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_PEIS", tags=["action"])
    async def run_PEIS(
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        versus_OCV: bool = True,  # adds mean OCV value to offset vs ref if True
        OCV_duration__s: float = 2.0,  # run OCV to set voltage offset
        OCV_acquisition_period__s: float = 0.1,
        Voffset__V: float = 0.00,  # Initial value in volts or amps.
        Vamp__V: float = 0.01,  # Amplitude value in volts
        Finit__Hz: float = 1e6,  # Initial frequency in Hz.
        Ffinal__Hz: float = 10,  # Final frequency in Hz.
        FrequenciesPerDecade: int = 10,
        Zinit_expected_Ohm: float = 100.0,
        ReadFast: bool = False,  # True for fast EIS, False for normal
        MaxRetries: int = 10,
        IErange_fromAC: bool = False,
        TTLwait: int = -1,
        TTLsend: int = -1,
    ):
        """Start a Potentiostatic EIS sweep via :class:`GamryEisExec`.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            fast_samples_in: Sample references associated with this action.
            versus_OCV: If true, add a pre-measured mean OCV to ``Voffset__V``.
            OCV_duration__s: OCV measurement duration when ``versus_OCV`` is true.
            OCV_acquisition_period__s: OCV sampling period in seconds.
            Voffset__V: DC potential offset in volts.
            Vamp__V: AC voltage amplitude in volts.
            Finit__Hz: Starting frequency in Hz.
            Ffinal__Hz: Ending frequency in Hz.
            FrequenciesPerDecade: Spectral resolution in points per decade.
            Zinit_expected_Ohm: Expected impedance for IE-range selection.
            ReadFast: If true, request the driver's fast EIS mode.
            MaxRetries: Per-frequency retry limit before advancing.
            IErange_fromAC: If true, derive IE range from AC response.
            TTLwait: TTL channel to wait on (``-1`` disables).
            TTLsend: TTL channel to assert on start (``-1`` disables).

        Returns:
            The active action dictionary from ``start_executor``.
        """
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "PEIS"
        executor = GamryEisExec(active=active, oneoff=False)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_GEIS", tags=["action"])
    async def run_GEIS(
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        Ioffset__A: float = 0.01,  # Initial value in volts or amps.
        Iamp__A: float = 0.1,  # Final value in volts or amps.
        Finit__Hz: float = 1e6,  # Initial frequency in Hz.
        Ffinal__Hz: float = 10,  # Final frequency in Hz.
        FrequenciesPerDecade: int = 10,
        Zinit_expected_Ohm: float = 100.0,
        ReadFast: bool = False,  # True for fast EIS, False for normal
        MaxRetries: int = 10,
        IErange_fromAC: bool = False,
        TTLwait: int = -1,
        TTLsend: int = -1,
    ):
        """Start a Galvanostatic EIS sweep via :class:`GamryEisExec`.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            fast_samples_in: Sample references associated with this action.
            Ioffset__A: DC current offset in amperes.
            Iamp__A: AC current amplitude in amperes.
            Finit__Hz: Starting frequency in Hz.
            Ffinal__Hz: Ending frequency in Hz.
            FrequenciesPerDecade: Spectral resolution in points per decade.
            Zinit_expected_Ohm: Expected impedance for IE-range selection.
            ReadFast: If true, request the driver's fast EIS mode.
            MaxRetries: Per-frequency retry limit before advancing.
            IErange_fromAC: If true, derive IE range from AC response.
            TTLwait: TTL channel to wait on (``-1`` disables).
            TTLsend: TTL channel to assert on start (``-1`` disables).

        Returns:
            The active action dictionary from ``start_executor``.
        """
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "GEIS"
        executor = GamryEisExec(active=active, oneoff=False)
        active_action_dict = active.start_executor(executor)
        return active_action_dict


def makeApp(server_key) -> BaseAPI:
    """Build the BaseAPI app for the Gamry potentiostat.

    Args:
        server_key: Unique key identifying this server in the orchestration
            group.

    Returns:
        The configured BaseAPI instance with technique endpoints attached
        via :func:`gamry_dyn_endpoints` plus action-level ``get_meas_status``
        and ``stop`` endpoints and private state/measurement helpers.
    """

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Gamry instrument/action server",
        version=4.0,
        driver_classes=[GamryDriver],
        # poller_class=GamryPoller,
        dyn_endpoints=gamry_dyn_endpoints,
    )

    @app.post(f"/{server_key}/get_meas_status", tags=["action"])
    async def get_meas_status():
        """Report the dtaq sink's current state.

        Use together with the eta-driven sleep loop to poll for completion.

        Args:
            action: Action wrapper supplied by the orchestrator.

        Returns:
            The finished action dictionary containing ``status`` (typically
            ``'idle'`` or ``'measuring'``).
        """
        active = await app.base.setup_and_contain_action()
        await active.enqueue_data_dflt(datadict={"status": app.driver.dtaqsink.status})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/stop", tags=["action"])
    async def stop(
    ):
        """Stop every active executor on the server in a controlled way.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action(action_abbr="stop")
        for exec_key in app.base.executors.keys():
            app.base.stop_executor(exec_key)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post("/stop_private", tags=["private"])
    async def stop_private() -> list:
        """Stop every active executor and return the list of stopped keys."""
        stopped_keys = []
        for exec_key in app.base.executors.keys():
            app.base.stop_executor(exec_key)
            stopped_keys.append(exec_key)
        return stopped_keys

    @app.post("/gamry_state", tags=["private"])
    def gamry_state():
        """Return the dictionary form of ``pstat.State()``."""
        state = app.driver.get_gamry_state()
        return state

    @app.post("/gamry_is_open", tags=["private"])
    def gamry_is_open():
        """Return the result of ``pstat.TestIsOpen()``."""
        state = app.driver.pstat.TestIsOpen()
        return state

    @app.post("/measure_v", tags=["private"])
    def measure_v():
        """Return a single voltage reading via ``pstat.MeasureV()``."""
        state = app.driver.pstat.MeasureV()
        return state

    @app.post("/measure_i", tags=["private"])
    def measure_i():
        """Return a single current reading via ``pstat.MeasureI()``."""
        state = app.driver.pstat.MeasureI()
        return state

    @app.post("/measure_a", tags=["private"])
    def measure_a():
        """Return a single auxiliary reading via ``pstat.MeasureA()``."""
        state = app.driver.pstat.MeasureA()
        return state

    return app
