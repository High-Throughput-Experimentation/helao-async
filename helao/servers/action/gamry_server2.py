# shell: uvicorn motion_server:app --reload
""" A FastAPI service definition for a potentiostat device server, e.g. Gamry.

gamry_server2 uses the Executor model with helao.drivers.pstat.gamry.driver which decouples
the hardware driver class from the action server base class.

"""


__all__ = ["makeApp"]


import asyncio
import time
import itertools
from typing import Optional, List, Union
from collections import defaultdict, deque

import numpy as np
import pandas as pd
from fastapi import Body, Query

from helao.core.error import ErrorCodes
from helao.core.models.sample import AssemblySample, LiquidSample, GasSample,SolidSample, NoneSample
from helao.core.models.hlostatus import HloStatus

from helao.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from helao.helpers.executor import Executor
from helao.helpers import helao_logging as logging  # get LOGGER from BaseAPI instance
from helao.helpers.bubble_detection import bubble_detection
from helao.drivers.pstat.gamry.driver import GamryDriver
from helao.drivers.pstat.gamry.technique import (
    GamryTechnique,
    TECH_LSV,
    TECH_CA,
    TECH_CP,
    TECH_CV,
    TECH_OCV,
    TECH_RCA,
)

global LOGGER
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER


class GamryExec(Executor):
    technique: GamryTechnique
    driver: GamryDriver

    def __init__(self, *args, **kwargs):
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
        """Setup potentiostat device for given technique."""
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
        """Begin measurement or wait for TTL trigger if specified."""
        if self.ttl_params["TTLwait"] > -1:
            bits = self.driver.pstat.DigitalIn()
            LOGGER.info(f"Gamry DIbits: {bits}, waiting for trigger.")
            while not bits:
                await asyncio.sleep(0.001)
                bits = self.driver.pstat.DigitalIn()
        LOGGER.debug("starting measurement")
        resp = self.driver.measure(self.ttl_params)
        self.start_time = resp.data.get("start_time", time.time())
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
        return {"error": error}

    async def _poll(self) -> dict:
        """Return data and status from dtaq event sink."""
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
                ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
            )
            status = HloStatus.active if resp.message != "done" else HloStatus.finished
            return {"error": error, "status": status, "data": resp.data}
        except Exception:
            LOGGER.error("GamryExec poll error", exc_info=True)
            print(data_dq)
            return {"error": ErrorCodes.critical_error, "status": HloStatus.errored}

    async def _post_exec(self):
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

        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
        return {"error": error, "data": {}}

    async def _manual_stop(self) -> dict:
        """Interrupt measurement and disconnect cell."""
        resp = await self.driver.stop()
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.stop
        return {"error": error}


async def gamry_dyn_endpoints(app: BaseAPI):
    server_key = app.base.server.server_name
    app.base.server_params["allow_concurrent_actions"] = False

    while not app.driver.ready:
        LOGGER.info("waiting for gamry init")
        await asyncio.sleep(1)

    model_ierange = app.driver.model.ierange

    @app.post(f"/{server_key}/run_LSV", tags=["action"])
    async def run_LSV(
        action: Action = Body({}, embed=True),
        action_version: int = 3,
        fast_samples_in: List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]] = Body([], embed=True),
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
        """Linear Sweep Voltammetry (unlike CV no backward scan is done)
        use 4bit bitmask for triggers
        IErange depends on gamry model used (test actual limit before using)"""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "LSV"
        executor = GamryExec(active=active, oneoff=False, technique=TECH_LSV)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_CA", tags=["action"])
    async def run_CA(
        action: Action = Body({}, embed=True),
        action_version: int = 3,
        fast_samples_in: List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]] = Body([], embed=True),
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
        """Chronoamperometry (current response on amplied potential)
        use 4bit bitmask for triggers
        IErange depends on gamry model used
        (test actual limit before using)"""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "CA"
        executor = GamryExec(active=active, oneoff=False, technique=TECH_CA)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_CP", tags=["action"])
    async def run_CP(
        action: Action = Body({}, embed=True),
        action_version: int = 3,
        fast_samples_in: List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]] = Body([], embed=True),
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
        """Chronopotentiometry (Potential response on controlled current)
        use 4bit bitmask for triggers
        IErange depends on gamry model used (test actual limit before using)"""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "CP"
        executor = GamryExec(active=active, oneoff=False, technique=TECH_CP)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_CV", tags=["action"])
    async def run_CV(
        action: Action = Body({}, embed=True),
        action_version: int = 3,
        fast_samples_in: List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]] = Body([], embed=True),
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
        """Cyclic Voltammetry (most widely used technique
        for acquireing information about electrochemical reactions)
        use 4bit bitmask for triggers
        IErange depends on gamry model used (test actual limit before using)"""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "CV"
        executor = GamryExec(active=active, oneoff=False, technique=TECH_CV)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_OCV", tags=["action"])
    async def run_OCV(
        action: Action = Body({}, embed=True),
        action_version: int = 3,
        fast_samples_in: List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]] = Body([], embed=True),
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
        """mesasures open circuit potential
        use 4bit bitmask for triggers
        IErange depends on gamry model used (test actual limit before using)"""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "OCV"
        executor = GamryExec(active=active, oneoff=False, technique=TECH_OCV)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_RCA", tags=["action"])
    async def run_RCA(
        action: Action = Body({}, embed=True),
        action_version: int = 3,
        fast_samples_in: List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]] = Body([], embed=True),
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
        """Measure pulsed voltammetry"""
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

    # @app.post(f"/{server_key}/run_EIS", tags=["action"])
    # async def run_EIS(
    #     action: Action = Body({}, embed=True),
    #     action_version: int = 1,
    #     fast_samples_in: List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]] = Body([], embed=True),
    #     Vval__V: float = 0.0,
    #     Tval__s: float = 10.0,
    #     Freq: float = 1000.0,
    #     RMS: float = 0.02,
    #     Precision: Optional[
    #         float
    #     ] = 0.001,  # The precision is used in a Correlation Coefficient (residual power) based test to determine whether or not to measure another cycle.
    #     AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
    #     TTLwait: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
    #     TTLsend: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
    #     IErange: model_ierange = "auto",
    # ):
    #     """Electrochemical Impendance Spectroscopy
    #     NOT TESTED
    #     use 4bit bitmask for triggers
    #     IErange depends on gamry model used (test actual limit before using)"""
    #     active = await app.base.setup_and_contain_action()
    #     active.action.action_abbr = "EIS"
    #     executor = GamryExec(active=active, oneoff=False, technique=TECH_EIS)
    #     active_action_dict = active.start_executor(executor)
    #     return active_action_dict


def makeApp(server_key):

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Gamry instrument/action server",
        version=3.0,
        driver_classes=[GamryDriver],
        dyn_endpoints=gamry_dyn_endpoints,
    )

    @app.post(f"/{server_key}/get_meas_status", tags=["action"])
    async def get_meas_status(action: Action = Body({}, embed=True)):
        """Will return 'idle' or 'measuring'.
        Should be used in conjuction with eta to async.sleep loop poll"""
        active = await app.base.setup_and_contain_action()
        await active.enqueue_data_dflt(datadict={"status": app.driver.dtaqsink.status})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/stop", tags=["action"])
    async def stop(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Stops measurement in a controlled way."""
        active = await app.base.setup_and_contain_action(action_abbr="stop")
        await app.driver.stop()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post("/stop_private", tags=["private"])
    async def stop_private():
        """Stops measurement."""
        response = await app.driver.stop()
        return response

    @app.post("/gamry_state", tags=["private"])
    def gamry_state():
        """Return pstat.State()."""
        state = app.driver.pstat.State()
        state = dict([x.split("\t") for x in state.split("\r\n") if x])
        return state

    return app
