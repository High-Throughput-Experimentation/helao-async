# shell: uvicorn motion_server:app --reload
""" A FastAPI service definition for a potentiostat device server, e.g. Gamry.

gamry_server2 uses the Executor model with helao.drivers.pstat.gamry.driver which decouples
the hardware driver class from the action server base class.

"""

__all__ = ["makeApp"]


import asyncio
import time
from typing import Optional, List
from fastapi import Body, Query

from helaocore.error import ErrorCodes
from helaocore.models.sample import SampleUnion
from helaocore.models.hlostatus import HloStatus

from helao.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from helao.helpers.config_loader import config_loader
from helao.helpers.executor import Executor
from helao.helpers import logging  # get logger from BaseAPI instance
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

global logger
if logging.LOGGER is None:
    logger = logging.make_logger(logger_name="gamry_server_standalone")
else:
    logger = logging.LOGGER


class GamryExec(Executor):
    technique: GamryTechnique
    driver: GamryDriver

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.poll_rate = 0.01  # pump events every 10 millisecond
            self.start_time = time.time()

            # link attrs for convenience
            self.action_params = self.active.action.action_params
            self.driver = self.active.base.fastapp.driver

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
                k: self.action_params.get(k, -1)
                for k in ("TTLwait", "TTLsend")
            }
            logger.info("GamryExec initialized.")
        except Exception:
            logger.error("GamryExec was not initialized.", exc_info=True)

    async def _pre_exec(self) -> dict:
        """Setup potentiostat device for given technique."""
        resp = self.driver.setup(
            self.technique, self.signal_params, self.dtaq_params, self.ierange
        )
        error = ErrorCodes.none if resp.reponse == "success" else ErrorCodes.setup
        return {"error": error}

    async def _exec(self) -> dict:
        """Begin measurement or wait for TTL trigger if specified."""
        if self.ttl_params["TTLwait"] > -1:
            bits = self.driver.pstat.DigitalIn()
            logger.info(f"Gamry DIbits: {bits}, waiting for trigger.")
            while not bits:
                await asyncio.sleep(0.001)
                bits = self.driver.pstat.DigitalIn()
        resp = self.driver.measure(self.ttl_params)
        error = ErrorCodes.none if resp.reponse == "success" else ErrorCodes.critical
        return {"error": error}

    async def _poll(self) -> dict:
        """Return data and status from dtaq event sink."""
        resp = self.driver.get_data(self.poll_rate)
        error = ErrorCodes.none if resp.reponse == "success" else ErrorCodes.critical
        status = HloStatus.active if resp.status=="busy" else HloStatus.finished
        return {"error": error, "status": status, "data": resp.data}

    async def _post_exec(self):
        resp = self.driver.cleanup()
        error = ErrorCodes.none if resp.reponse == "success" else ErrorCodes.critical
        return {"error": error, "data": {}}

    async def _manual_stop(self) -> dict:
        """Interrupt measurement and disconnect cell."""
        resp = self.driver.stop()
        error = ErrorCodes.none if resp.reponse == "success" else ErrorCodes.stop
        return {"error": error}


async def gamry_dyn_endpoints(app=None):
    server_key = app.base.server.server_name
    enable_pstat = False

    while not app.driver.ready:
        logger.info("waiting for gamry init")
        await asyncio.sleep(1)

    if app.driver.pstat is not None:
        enable_pstat = True

    if enable_pstat:

        @app.post(f"/{server_key}/run_LSV", tags=["action"])
        async def run_LSV(
            action: Action = Body({}, embed=True),
            action_version: int = 2,
            fast_samples_in: List[SampleUnion] = Body([], embed=True),
            Vinit__V: float = 0.0,  # Initial value in volts or amps.
            Vfinal__V: float = 1.0,  # Final value in volts or amps.
            ScanRate__V_s: float = 1.0,  # Scan rate in volts/sec or amps/sec.
            AcqInterval__s: float = 0.01,  # Time between data acq in seconds.
            TTLwait: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
            TTLsend: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
            IErange: app.driver.model.ierange = "auto",
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
        ):
            """Linear Sweep Voltammetry (unlike CV no backward scan is done)
            use 4bit bitmask for triggers
            IErange depends on gamry model used (test actual limit before using)"""
            active = await app.base.setup_and_contain_action()
            active.action_abbr = "LSV"
            executor = GamryExec(active=active, oneoff=False, technique=TECH_LSV)
            active_action_dict = active.start_executor(executor)
            return active_action_dict

        @app.post(f"/{server_key}/run_CA", tags=["action"])
        async def run_CA(
            action: Action = Body({}, embed=True),
            action_version: int = 2,
            fast_samples_in: List[SampleUnion] = Body([], embed=True),
            Vval__V: float = 0.0,
            Tval__s: float = 10.0,
            AcqInterval__s: float = 0.01,  # Time between data acq in seconds.
            TTLwait: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
            TTLsend: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
            IErange: app.driver.model.ierange = "auto",
            SetStopXMin: Optional[float] = None,
            SetStopXMax: Optional[float] = None,
            SetStopAtDelayXMin: Optional[int] = None,
            SetStopAtDelayXMax: Optional[int] = None,
        ):
            """Chronoamperometry (current response on amplied potential)
            use 4bit bitmask for triggers
            IErange depends on gamry model used
            (test actual limit before using)"""
            active = await app.base.setup_and_contain_action()
            active.action_abbr = "CA"
            executor = GamryExec(active=active, oneoff=False, technique=TECH_CA)
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
            TTLwait: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
            TTLsend: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
            IErange: app.driver.model.ierange = "auto",
            SetStopXMin: Optional[float] = None,
            SetStopXMax: Optional[float] = None,
            SetStopAtDelayXMin: Optional[int] = None,
            SetStopAtDelayXMax: Optional[int] = None,
        ):
            """Chronopotentiometry (Potential response on controlled current)
            use 4bit bitmask for triggers
            IErange depends on gamry model used (test actual limit before using)"""
            active = await app.base.setup_and_contain_action()
            active.action_abbr = "CP"
            executor = GamryExec(active=active, oneoff=False, technique=TECH_CP)
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
            TTLwait: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
            TTLsend: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
            IErange: app.driver.model.ierange = "auto",
            SetStopIMin: Optional[float] = None,
            SetStopIMax: Optional[float] = None,
            SetStopAtDelayIMin: Optional[int] = None,
            SetStopAtDelayIMax: Optional[int] = None,
        ):
            """Cyclic Voltammetry (most widely used technique
            for acquireing information about electrochemical reactions)
            use 4bit bitmask for triggers
            IErange depends on gamry model used (test actual limit before using)"""
            active = await app.base.setup_and_contain_action()
            active.action_abbr = "CV"
            executor = GamryExec(active=active, oneoff=False, technique=TECH_CV)
            active_action_dict = active.start_executor(executor)
            return active_action_dict

        @app.post(f"/{server_key}/run_OCV", tags=["action"])
        async def run_OCV(
            action: Action = Body({}, embed=True),
            action_version: int = 2,
            fast_samples_in: List[SampleUnion] = Body([], embed=True),
            Tval__s: float = 10.0,
            AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
            TTLwait: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
            TTLsend: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
            IErange: app.driver.model.ierange = "auto",
            SetStopADVMin: Optional[float] = None,
            SetStopADVMax: Optional[float] = None,
        ):
            """mesasures open circuit potential
            use 4bit bitmask for triggers
            IErange depends on gamry model used (test actual limit before using)"""
            active = await app.base.setup_and_contain_action()
            active.action_abbr = "OCV"
            executor = GamryExec(active=active, oneoff=False, technique=TECH_OCV)
            active_action_dict = active.start_executor(executor)
            return active_action_dict

        @app.post(f"/{server_key}/run_RCA", tags=["action"])
        async def run_RCA(
            action: Action = Body({}, embed=True),
            action_version: int = 2,
            fast_samples_in: List[SampleUnion] = Body([], embed=True),
            Vinit__V: float = 0.0,
            Tinit__s: float = 0.5,
            Vstep__V: float = 0.5,
            Tstep__s: float = 0.5,
            Cycles: int = 5,
            AcqInterval__s: float = 0.01,  # acquisition rate
            TTLwait: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
            TTLsend: int = Query(-1, ge=-1, le=3),  # -1 disables, else select TTL 0-3
            IErange: app.driver.model.ierange = "auto",
        ):
            """Measure pulsed voltammetry"""
            active = await app.base.setup_and_contain_action()
            active.action_abbr = "RCA"
            executor = GamryExec(active=active, oneoff=False, technique=TECH_RCA)
            active_action_dict = active.start_executor(executor)
            return active_action_dict

        # @app.post(f"/{server_key}/run_EIS", tags=["action"])
        # async def run_EIS(
        #     action: Action = Body({}, embed=True),
        #     action_version: int = 1,
        #     fast_samples_in: List[SampleUnion] = Body([], embed=True),
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
        #     IErange: app.driver.model.ierange = "auto",
        # ):
        #     """Electrochemical Impendance Spectroscopy
        #     NOT TESTED
        #     use 4bit bitmask for triggers
        #     IErange depends on gamry model used (test actual limit before using)"""
        #     active = await app.base.setup_and_contain_action()
        #     active.action_abbr = "EIS"
        #     executor = GamryExec(active=active, oneoff=False, technique=TECH_EIS)
        #     active_action_dict = active.start_executor(executor)
        #     return active_action_dict


def makeApp(confPrefix, server_key, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Gamry instrument/action server",
        version=3.0,
        driver_class=GamryDriver,
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
        app.driver.stop()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post("/stop_private", tags=["private"])
    def stop_private():
        """Stops measurement."""
        app.driver.stop()

    return app
