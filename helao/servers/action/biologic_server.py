# shell: uvicorn motion_server:app --reload
""" A FastAPI service definition for a potentiostat device server, e.g. Biologic.

biologic_server uses the Executor model with helao.drivers.pstat.biologic.driver which decouples
the hardware driver class from the action server base class.

"""


__all__ = ["makeApp"]


import asyncio
import time
from typing import Optional, List
from collections import defaultdict, deque

import numpy as np
import pandas as pd
from fastapi import Body, Query

from helaocore.error import ErrorCodes
from helaocore.models.sample import SampleUnion
from helaocore.models.hlostatus import HloStatus

from helao.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from helao.helpers.config_loader import config_loader
from helao.helpers.executor import Executor
from helao.helpers import logging  # get LOGGER from BaseAPI instance
from helao.helpers.bubble_detection import bubble_detection
from helao.drivers.pstat.biologic.driver import BiologicDriver
from helao.drivers.pstat.biologic.technique import (
    EC_IRange,
    BiologicTechnique,
    TECH_OCV,
    TECH_CA,
    TECH_CP,
    TECH_CV,
)

import easy_biologic.lib.ec_lib as ecl

global LOGGER
if logging.LOGGER is None:
    LOGGER = logging.make_logger(logger_name="biologic_server_standalone")
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
                if not (k.startswith("ttl_") or k == "ttl")
            }
            self.ttl_params = {
                k: v
                for k, v in self.active.action.action_params.items()
                if (k.startswith("ttl_") or k == "ttl")
            }
            self.driver = self.active.base.fastapp.driver
            self.channel = self.action_params["channel"]

            # no external timer, event sink signals end of measurement
            self.duration = -1
            self.technique = kwargs["technique"]

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
        except Exception:
            error = ErrorCodes.critical
            LOGGER.error("BiologicExec pre-exec error", exc_info=True)
        return {"error": error}

    async def _exec(self) -> dict:
        """Begin measurement or wait for TTL trigger if specified."""
        LOGGER.debug("starting measurement")
        resp = self.driver.start_channel(self.channel, self.ttl_params)
        self.start_time = resp.data.get("start_time", time.time())
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.critical
        return {"error": error}

    async def _poll(self) -> dict:
        """Return data and status from dtaq event sink."""
        resp = await self.driver.get_data(self.channel)
        # populate executor buffer for output calculation
        data_length = 0
        for k, v in resp.data.items():
            self.data_buffer[k].extend(v)
            data_length = len(v)
        if data_length:
            self.data_buffer["channel"].extend(data_length * [self.channel])
            resp.data.update({"channel": data_length * [self.channel]})
        else:
            resp.data.update({"channel": []})
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.critical
        status = HloStatus.active if resp.message != "done" else HloStatus.finished
        return {"error": error, "status": status, "data": resp.data}

    async def _post_exec(self):
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

        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.critical
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
        fast_samples_in: List[SampleUnion] = Body([], embed=True),
        Vval__V: float = 0.0,
        Tval__s: float = 10.0,
        AcqInterval__s: float = 0.01,  # Time between data acq in seconds.
        IRange: EC_IRange = EC_IRange.AUTO,
        channel: int = 0,
        ttl: str = 'none',
        ttl_logic: int = 1,
        ttl_duration: float = 1.0,
    ):
        """Chronoamperometry (current response on amplied potential)
        use 4bit bitmask for triggers
        IErange depends on biologic model used
        (test actual limit before using)"""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "CA"
        active.action.action_params["IRange"] = getattr(
            ecl.IRange, active.action.action_params["IRange"].value
        )
        executor = BiologicExec(active=active, oneoff=False, technique=TECH_CA)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_CP", tags=["action"])
    async def run_CP(
        action: Action = Body({}, embed=True),
        action_version: int = 2,
        fast_samples_in: List[SampleUnion] = Body([], embed=True),
        Ival__A: float = 0.0,
        Tval__s: float = 10.0,
        AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
        channel: int = 0,
        ttl: str = 'none',
        ttl_logic: int = 1,
        ttl_duration: float = 1.0,
    ):
        """Chronopotentiometry (Potential response on controlled current)
        use 4bit bitmask for triggers
        IErange depends on biologic model used (test actual limit before using)"""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "CP"
        executor = BiologicExec(active=active, oneoff=False, technique=TECH_CP)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_CV", tags=["action"])
    async def run_CV(
        action: Action = Body({}, embed=True),
        action_version: int = 2,
        fast_samples_in: List[SampleUnion] = Body([], embed=True),
        Vinit__V: float = 0.0,  # Initial value in volts or amps.
        Vapex1__V: float = 1.0,  # Apex 1 value in volts or amps.
        Vapex2__V: float = -1.0,  # Apex 2 value in volts or amps.
        Vfinal__V: float = 0.0,  # Final value in volts or amps.
        ScanRate__V_s: float = 1.0,  # Scan rate in volts/sec or amps/sec.
        AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
        Cycles: int = 1,
        channel: int = 0,
        ttl: str = 'none',
        ttl_logic: int = 1,
        ttl_duration: float = 1.0,
    ):
        """Cyclic Voltammetry (most widely used technique
        for acquireing information about electrochemical reactions)
        use 4bit bitmask for triggers
        IErange depends on biologic model used (test actual limit before using)"""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "CV"
        executor = BiologicExec(active=active, oneoff=False, technique=TECH_CV)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/run_OCV", tags=["action"])
    async def run_OCV(
        action: Action = Body({}, embed=True),
        action_version: int = 2,
        fast_samples_in: List[SampleUnion] = Body([], embed=True),
        Tval__s: float = 10.0,
        AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
        channel: int = 0,
        RSD_threshold: float = 1,
        simple_threshold: float = 0.3,
        signal_change_threshold: float = 0.01,
        amplitude_threshold: float = 0.05,
        ttl: str = 'none',
        ttl_logic: int = 1,
        ttl_duration: float = 1.0,
    ):
        """mesasures open circuit potential
        use 4bit bitmask for triggers
        IErange depends on biologic model used (test actual limit before using)"""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "OCV"
        executor = BiologicExec(active=active, oneoff=False, technique=TECH_OCV)
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
        app.driver.stop()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post("/stop_private", tags=["private"])
    def stop_private():
        """Stops measurement."""
        app.driver.stop()

    return app
