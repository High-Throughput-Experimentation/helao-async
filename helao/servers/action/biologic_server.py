# shell: uvicorn motion_server:app --reload
"""A FastAPI service definition for a potentiostat device server, e.g. Biologic.

biologic_server uses the Executor model with helao.drivers.pstat.biologic.driver which decouples
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
from fastapi import Body

from helao.core.error import ErrorCodes
from helao.core.models.sample import (
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
)
from helao.core.models.hlostatus import HloStatus

from helao.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from helao.helpers.config_loader import config_loader
from helao.helpers.executor import Executor
from helao.helpers import helao_logging as logging  # get LOGGER from BaseAPI instance
from helao.helpers.bubble_detection import bubble_detection
from helao.drivers.pstat.biologic.driver import BiologicDriver
from helao.drivers.pstat.biologic.enum import (
    EC_IRange,
    EC_ERange,
    EC_Bandwidth,
    EC_IRange_map,
    EC_ERange_map,
    EC_Bandwidth_map,
)
from helao.drivers.pstat.biologic.technique import (
    BiologicTechnique,
    TECH_OCV,
    TECH_CA,
    TECH_CP,
    TECH_CV,
    TECH_GEIS,
    TECH_PEIS,
)


global LOGGER
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER


class BiologicExec(Executor):
    technique: BiologicTechnique
    driver: BiologicDriver

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.poll_rate = 0.01  # pump events every 10 millisecond
            self.concurrent = False
            self.start_time = time.time()
            self.data_buffer = defaultdict(lambda: deque(maxlen=1000))

            # link attrs for convenience
            self.action_params = {
                k: v
                for k, v in self.active.action.action_params.items()
                if not (k.startswith("TTL")) and not (k.startswith("alert"))
            }
            self.driver = self.active.base.fastapp.driver
            self.channel = self.action_params["channel"]

            # no external timer, event sink signals end of measurement
            self.duration = -1
            self.technique = kwargs["technique"]

            # parse gamry-style TTL params
            gttl_params = {
                k: v
                for k, v in self.active.action.action_params.items()
                if k.startswith("TTL")
            }
            self.ttl_params = {}
            self.ttl_params["ttl"] = "none"
            self.ttl_params["ttl_logic"] = 1
            self.ttl_params["ttl_duration"] = gttl_params.get("TTLduration", 1.0)
            if gttl_params.get("TTLsend", -1) >= 0:
                self.ttl_params["ttl"] = "out"
            elif gttl_params.get("TTLwait", -1) >= 0:
                self.ttl_params["ttl"] = "in"

            self.alert_params = {
                k: self.active.action.action_params.get(k, None)
                for k in (
                    "alertThreshEwe_V",
                    "alertThreshI_A",
                    "alert_above",
                    "alert_duration__s",
                    "alert_sleep__s",
                )
            }
            self.last_alert_time = 0

            LOGGER.info("BiologicExec initialized.")
        except Exception:
            LOGGER.error("BiologicExec was not initialized.", exc_info=True)

    async def _pre_exec(self) -> dict:
        """Setup potentiostat device for given technique."""
        try:
            resp = self.driver.setup(
                technique=self.technique,
                action_params=self.action_params,
            )
            error = ErrorCodes.none if resp.response == "success" else ErrorCodes.setup
            LOGGER.info("BiologicExec setup successful.")
        except Exception:
            error = ErrorCodes.critical_error
            LOGGER.error("BiologicExec pre-exec error", exc_info=True)
        return {"error": error}

    async def _exec(self) -> dict:
        """Begin measurement or wait for TTL trigger if specified."""
        LOGGER.debug("starting measurement")
        try:
            resp = self.driver.start_channel(self.channel, self.ttl_params)
            self.start_time = resp.data.get("start_time", time.time())
            error = (
                ErrorCodes.none
                if resp.response == "success"
                else ErrorCodes.critical_error
            )
            LOGGER.info("BiologicExec measurement started.")
            return {"error": error}
        except Exception:
            LOGGER.error("BiologicExec exec error", exc_info=True)
            return {"error": ErrorCodes.critical_error}

    async def _poll(self) -> dict:
        """Return data and status from dtaq event sink."""
        try:
            resp = await self.driver.get_data(self.channel)
            # populate executor buffer for output calculation
            data_length = 0
            for k, v in resp.data.items():
                self.data_buffer[k].extend(v)
                data_length = len(v)
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
            if data_length:
                self.data_buffer["channel"].extend(data_length * [self.channel])
                resp.data.update({"channel": data_length * [self.channel]})
            error = (
                ErrorCodes.none
                if resp.response == "success"
                else ErrorCodes.critical_error
            )
            status = HloStatus.active

            if resp.message == "done":
                status = HloStatus.finished
            if resp.response == "failed":
                status = HloStatus.errored

            return {"error": error, "status": status, "data": resp.data}
        except Exception:
            LOGGER.error("BiologicExec poll error", exc_info=True)
            return {"error": ErrorCodes.critical_error, "status": HloStatus.errored}

    async def _post_exec(self):
        LOGGER.info("BiologicExec running post_exec.")
        resp = self.driver.cleanup(self.channel)

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
        """Interrupt measurement and disconnect cell."""
        resp = self.driver.stop()
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.stop
        return {"error": error}


async def biologic_dyn_endpoints(app=None):
    server_key = app.base.server.server_name

    while not app.driver.ready:
        LOGGER.info("waiting for biologic init")
        await asyncio.sleep(1)

    @app.post(f"/{server_key}/run_CA", tags=["action"])
    async def run_CA(
        action: Action = Body({}, embed=True),
        action_version: int = 2,
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        Vval__V: float = 0.0,
        Tval__s: float = 10.0,
        AcqInterval__s: float = 0.01,  # Time between data acq in seconds.
        IRange: EC_IRange = EC_IRange.AUTO,
        ERange: EC_ERange = EC_ERange.AUTO,
        Bandwidth: EC_Bandwidth = EC_Bandwidth.BW4,
        channel: int = 0,
        TTLwait: int = -1,
        TTLsend: int = -1,
        TTLduration: float = 1.0,
        alert_duration__s: float = -1,
        alert_above: bool = True,
        alert_sleep__s: float = -1,
        alertThreshI_A: float = 0,
    ):
        """Chronoamperometry (current response on amplied potential)
        use 4bit bitmask for triggers
        IErange depends on biologic model used
        (test actual limit before using)"""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "CA"
        active.action.action_params["AcqInterval__A"] = 10.0
        active.action.action_params["IRange"] = EC_IRange_map[
            active.action.action_params["IRange"]
        ]
        active.action.action_params["ERange"] = EC_ERange_map[
            active.action.action_params["ERange"]
        ]
        active.action.action_params["Bandwidth"] = EC_Bandwidth_map[
            active.action.action_params["Bandwidth"]
        ]
        executor = BiologicExec(active=active, oneoff=False, technique=TECH_CA)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_CP", tags=["action"])
    async def run_CP(
        action: Action = Body({}, embed=True),
        action_version: int = 2,
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        Ival__A: float = 0.0,
        Tval__s: float = 10.0,
        AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
        IRange: EC_IRange = EC_IRange.AUTO,
        ERange: EC_ERange = EC_ERange.AUTO,
        Bandwidth: EC_Bandwidth = EC_Bandwidth.BW4,
        channel: int = 0,
        TTLwait: int = -1,
        TTLsend: int = -1,
        TTLduration: float = 1.0,
        alert_duration__s: float = -1,
        alert_above: bool = True,
        alert_sleep__s: float = -1,
        alertThreshEwe_V: float = 0,
    ):
        """Chronopotentiometry (Potential response on controlled current)
        use 4bit bitmask for triggers
        IErange depends on biologic model used (test actual limit before using)"""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "CP"
        active.action.action_params["AcqInterval__V"] = 10.0
        active.action.action_params["IRange"] = EC_IRange_map[
            active.action.action_params["IRange"]
        ]
        active.action.action_params["ERange"] = EC_ERange_map[
            active.action.action_params["ERange"]
        ]
        active.action.action_params["Bandwidth"] = EC_Bandwidth_map[
            active.action.action_params["Bandwidth"]
        ]
        executor = BiologicExec(active=active, oneoff=False, technique=TECH_CP)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_CV", tags=["action"])
    async def run_CV(
        action: Action = Body({}, embed=True),
        action_version: int = 2,
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
        IRange: EC_IRange = EC_IRange.AUTO,
        ERange: EC_ERange = EC_ERange.AUTO,
        Bandwidth: EC_Bandwidth = EC_Bandwidth.BW4,
        channel: int = 0,
        TTLwait: int = -1,
        TTLsend: int = -1,
        TTLduration: float = 1.0,
        alert_duration__s: float = -1,
        alert_above: bool = True,
        alert_sleep__s: float = -1,
        alertThreshI_A: float = 0,
    ):
        """Cyclic Voltammetry (most widely used technique
        for acquireing information about electrochemical reactions)
        use 4bit bitmask for triggers
        IErange depends on biologic model used (test actual limit before using)"""
        active = await app.base.setup_and_contain_action()
        active.action.action_params["Cycles"] -= 1  # i.e. additional cycles
        active.action.action_params["AcqInterval__V"] = (
            active.action.action_params["AcqInterval__s"]
            * active.action.action_params["ScanRate__V_s"]
        )
        active.action.action_abbr = "CV"
        active.action.action_params["IRange"] = EC_IRange_map[
            active.action.action_params["IRange"]
        ]
        active.action.action_params["ERange"] = EC_ERange_map[
            active.action.action_params["ERange"]
        ]
        active.action.action_params["Bandwidth"] = EC_Bandwidth_map[
            active.action.action_params["Bandwidth"]
        ]
        executor = BiologicExec(active=active, oneoff=False, technique=TECH_CV)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_OCV", tags=["action"])
    async def run_OCV(
        action: Action = Body({}, embed=True),
        action_version: int = 2,
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        Tval__s: float = 10.0,
        AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
        channel: int = 0,
        TTLwait: int = -1,
        TTLsend: int = -1,
        TTLduration: float = 1.0,
        RSD_threshold: float = 1,
        simple_threshold: float = 0.3,
        signal_change_threshold: float = 0.01,
        amplitude_threshold: float = 0.05,
    ):
        """mesasures open circuit potential
        use 4bit bitmask for triggers
        IErange depends on biologic model used (test actual limit before using)"""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "OCV"
        active.action.action_params["AcqInterval__V"] = 10.0
        executor = BiologicExec(active=active, oneoff=False, technique=TECH_OCV)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_PEIS", tags=["action"])
    async def run_PEIS(
        action: Action = Body({}, embed=True),
        action_version: int = 3,
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        Vinit__V: float = 0.00,  # Initial value in volts or amps.
        Vamp__V: float = 0.01,  # Amplitude value in volts
        Finit__Hz: float = 1000,  # Initial frequency in Hz.
        Ffinal__Hz: float = 1000000,  # Final frequency in Hz.
        FrequencyNumber: int = 60,
        Duration__s: float = 0,  # Duration in seconds.
        AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
        SweepMode: str = "log",
        Repeats: int = 10,
        DelayFraction: float = 0.1,
        # vs_initial: bool = False,  # True if vs initial, False if vs previous.
        IRange: EC_IRange = EC_IRange.AUTO,
        ERange: EC_ERange = EC_ERange.AUTO,
        Bandwidth: EC_Bandwidth = EC_Bandwidth.BW4,
        channel: int = 0,
        TTLwait: int = -1,
        TTLsend: int = -1,
        TTLduration: float = 1.0,
    ):
        """run Potentiostatic EIS"""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "PEIS"
        active.action.action_params["IRange"] = EC_IRange_map[
            active.action.action_params["IRange"]
        ]
        active.action.action_params["ERange"] = EC_ERange_map[
            active.action.action_params["ERange"]
        ]
        active.action.action_params["Bandwidth"] = EC_Bandwidth_map[
            active.action.action_params["Bandwidth"]
        ]
        executor = BiologicExec(active=active, oneoff=False, technique=TECH_PEIS)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_GEIS", tags=["action"])
    async def run_GEIS(
        action: Action = Body({}, embed=True),
        action_version: int = 3,
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        Iinit__A: float = 0.01,  # Initial value in volts or amps.
        Iamp__A: float = 0.1,  # Final value in volts or amps.
        Finit__Hz: float = 1,  # Initial frequency in Hz.
        Ffinal__Hz: float = 10000,  # Final frequency in Hz.
        FrequencyNumber: int = 60,
        Duration__s: float = 0,  # Duration in seconds.
        AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
        SweepMode: str = "log",
        Repeats: int = 10,
        DelayFraction: float = 0.1,
        # vs_initial: bool = False,  # True if vs initial, False if vs previous.
        IRange: EC_IRange = EC_IRange.AUTO,
        ERange: EC_ERange = EC_ERange.AUTO,
        Bandwidth: EC_Bandwidth = EC_Bandwidth.BW4,
        channel: int = 0,
        TTLwait: int = -1,
        TTLsend: int = -1,
        TTLduration: float = 1.0,
    ):
        """run Galvanostataic EIS"""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "GEIS"
        active.action.action_params["IRange"] = EC_IRange_map[
            active.action.action_params["IRange"]
        ]
        active.action.action_params["ERange"] = EC_ERange_map[
            active.action.action_params["ERange"]
        ]
        active.action.action_params["Bandwidth"] = EC_Bandwidth_map[
            active.action.action_params["Bandwidth"]
        ]
        executor = BiologicExec(active=active, oneoff=False, technique=TECH_GEIS)
        active_action_dict = active.start_executor(executor)
        return active_action_dict


def makeApp(confPrefix, server_key, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Biologic instrument/action server",
        version=3.0,
        driver_class=BiologicDriver,
        dyn_endpoints=biologic_dyn_endpoints,
    )
    # prevent concurrent actions on different endpoints
    app.base.server_params["allow_concurrent_actions"] = False

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
        channel: Optional[int] = None,
    ):
        """Stops measurement in a controlled way."""
        active = await app.base.setup_and_contain_action(action_abbr="stop")
        app.driver.stop(active.action.action_params["channel"])
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post("/stop_private", tags=["private"])
    def stop_private(channel: Optional[int] = None):
        """Stops measurement."""
        app.driver.stop(channel)

    return app
