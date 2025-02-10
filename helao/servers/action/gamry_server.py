# shell: uvicorn motion_server:app --reload
""" A FastAPI service definition for a potentiostat device server, e.g. Gamry.

The potentiostat service defines RESTful methods for sending commmands and retrieving 
data from a potentiostat driver class such as 'gamry_driver' using
FastAPI. The methods provided by this service are not device-specific. Appropriate code
must be written in the driver class to ensure that the service methods are generic, i.e.
calls to 'poti.*' are not device-specific. Currently inherits configuration from driver 
code, and hard-coded to use 'gamry' class (see "__main__").

IMPORTANT -- class methods which are "blocking" i.e. synchronous driver calls must be
preceded by:
  await stat.set_run()
and followed by :
  await stat.set_idle()
which will update this action server's status dictionary which is query-able via
../get_status, and also broadcast the status change via websocket ../ws_status

IMPORTANT -- this framework assumes a single data stream and structure produced by the
low level device driver, so ../ws_data will only broadcast the device class's  poti.q;
additional data streams may be added as separate websockets or reworked into present
../ws_data columar format with an additional tag column to differentiate streams

Manual Bugfixes:
    https://github.com/chrullrich/comtypes/commit/6d3934b37a5d614a6be050cbc8f09d59bceefcca

"""

__all__ = ["makeApp"]


import asyncio
from typing import Optional, List
from fastapi import Body, Query

from helao.servers.base_api import BaseAPI
from helao.core.models.sample import SampleModel
from helao.helpers.premodels import Action
from helao.drivers.pstat.gamry_driver import gamry
from helao.helpers.config_loader import config_loader


async def gamry_dyn_endpoints(app=None):
    server_key = app.base.server.server_name
    enable_pstat = False

    while not app.driver.ready:
        LOGGER.info("waiting for gamry init")
        await asyncio.sleep(1)

    if app.driver.pstat is not None:
        enable_pstat = True

    if enable_pstat:

        @app.post(f"/{server_key}/run_LSV", tags=["action"])
        async def run_LSV(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            fast_samples_in: List[SampleModel] = Body([], embed=True),
            Vinit__V: float = 0.0,  # Initial value in volts or amps.
            Vfinal__V: float = 1.0,  # Final value in volts or amps.
            ScanRate__V_s: float = 1.0,  # Scan rate in volts/sec or amps/sec.
            AcqInterval__s: float = 0.01,  # Time between data acq in seconds.
            TTLwait: int = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            TTLsend: int = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            IErange: app.driver.gamry_range_enum = "auto",
            stop_imin: Optional[float] = None,
            stop_imax: Optional[float] = None,
            stop_dimin: Optional[float] = None,
            stop_dimax: Optional[float] = None,
            stop_adimin: Optional[float] = None,
            stop_adimax: Optional[float] = None,
            stopdelay_imin: Optional[int] = None,
            stopdelay_imax: Optional[int] = None,
            stopdelay_dimin: Optional[int] = None,
            stopdelay_dimax: Optional[int] = None,
            stopdelay_adimin: Optional[int] = None,
            stopdelay_adimax: Optional[int] = None,
        ):
            """Linear Sweep Voltammetry (unlike CV no backward scan is done)
            use 4bit bitmask for triggers
            IErange depends on gamry model used (test actual limit before using)"""
            A =  app.base.setup_action()
            A.action_abbr = "LSV"
            # A.save_data = True
            active_dict = await app.driver.technique_LSV(A)
            return active_dict

        @app.post(f"/{server_key}/run_CA", tags=["action"])
        async def run_CA(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            fast_samples_in: List[SampleModel] = Body([], embed=True),
            Vval__V: float = 0.0,
            Tval__s: float = 10.0,
            AcqInterval__s: float = 0.01,  # Time between data acq in seconds.
            TTLwait: int = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            TTLsend: int = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            IErange: app.driver.gamry_range_enum = "auto",
            stop_imin: Optional[float] = None,
            stop_imax: Optional[float] = None,
            stopdelay_imin: Optional[int] = None,
            stopdelay_imax: Optional[int] = None,
        ):
            """Chronoamperometry (current response on amplied potential)
            use 4bit bitmask for triggers
            IErange depends on gamry model used
            (test actual limit before using)"""
            A =  app.base.setup_action()
            A.action_abbr = "CA"
            # A.save_data = True
            active_dict = await app.driver.technique_CA(A)
            return active_dict

        @app.post(f"/{server_key}/run_CP", tags=["action"])
        async def run_CP(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            fast_samples_in: List[SampleModel] = Body([], embed=True),
            Ival__A: float = 0.0,
            Tval__s: float = 10.0,
            AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
            TTLwait: int = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            TTLsend: int = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            IErange: app.driver.gamry_range_enum = "auto",
            stop_vmin: Optional[float] = None,
            stop_vmax: Optional[float] = None,
            stopdelay_vmin: Optional[int] = None,
            stopdelay_vmax: Optional[int] = None,
        ):
            """Chronopotentiometry (Potential response on controlled current)
            use 4bit bitmask for triggers
            IErange depends on gamry model used (test actual limit before using)"""
            A =  app.base.setup_action()
            A.action_abbr = "CP"
            # A.save_data = True
            active_dict = await app.driver.technique_CP(A)
            return active_dict

        @app.post(f"/{server_key}/run_CV", tags=["action"])
        async def run_CV(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            fast_samples_in: List[SampleModel] = Body([], embed=True),
            Vinit__V: float = 0.0,  # Initial value in volts or amps.
            Vapex1__V: float = 1.0,  # Apex 1 value in volts or amps.
            Vapex2__V: float = -1.0,  # Apex 2 value in volts or amps.
            Vfinal__V: float = 0.0,  # Final value in volts or amps.
            ScanRate__V_s: float = 1.0,  # Scan rate in volts/sec or amps/sec.
            AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
            Cycles: int = 1,
            TTLwait: int = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            TTLsend: int = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            IErange: app.driver.gamry_range_enum = "auto",
            stop_imin: Optional[float] = None,
            stop_imax: Optional[float] = None,
            stopdelay_imin: Optional[int] = None,
            stopdelay_imax: Optional[int] = None,
        ):
            """Cyclic Voltammetry (most widely used technique
            for acquireing information about electrochemical reactions)
            use 4bit bitmask for triggers
            IErange depends on gamry model used (test actual limit before using)"""
            A =  app.base.setup_action()
            A.action_abbr = "CV"
            # A.save_data = True
            active_dict = await app.driver.technique_CV(A)
            return active_dict

        @app.post(f"/{server_key}/run_EIS", tags=["action"])
        async def run_EIS(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            fast_samples_in: List[SampleModel] = Body([], embed=True),
            Vval__V: float = 0.0,
            Tval__s: float = 10.0,
            Freq: float = 1000.0,
            RMS: float = 0.02,
            Precision: Optional[
                float
            ] = 0.001,  # The precision is used in a Correlation Coefficient (residual power) based test to determine whether or not to measure another cycle.
            AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
            TTLwait: int = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            TTLsend: int = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            IErange: app.driver.gamry_range_enum = "auto",
        ):
            """Electrochemical Impendance Spectroscopy
            NOT TESTED
            use 4bit bitmask for triggers
            IErange depends on gamry model used (test actual limit before using)"""
            A =  app.base.setup_action()
            A.action_abbr = "EIS"
            # A.save_data = True
            active_dict = await app.driver.technique_EIS(A)
            return active_dict

        @app.post(f"/{server_key}/run_OCV", tags=["action"])
        async def run_OCV(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            fast_samples_in: List[SampleModel] = Body([], embed=True),
            Tval__s: float = 10.0,
            AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
            TTLwait: int = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            TTLsend: int = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            IErange: app.driver.gamry_range_enum = "auto",
            stop_advmin: Optional[float] = None,
            stop_advmax: Optional[float] = None,
        ):
            """mesasures open circuit potential
            use 4bit bitmask for triggers
            IErange depends on gamry model used (test actual limit before using)"""
            A =  app.base.setup_action()
            A.action_abbr = "OCV"
            # A.save_data = True
            active_dict = await app.driver.technique_OCV(A)
            return active_dict


        @app.post(f"/{server_key}/run_RCA", tags=["action"])
        async def run_RCA(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            fast_samples_in: List[SampleModel] = Body([], embed=True),
            Vinit__V: float = 0.0,
            Tinit__s: float = 0.5,
            Vstep__V: float = 0.5,
            Tstep__s: float = 0.5,
            Cycles: int = 5,
            AcqInterval__s: float = 0.01,  # acquisition rate

            TTLwait: int = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            TTLsend: int = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            IErange: app.driver.gamry_range_enum = "auto",
        ):
            """Measure pulsed voltammetry"""
            A =  app.base.setup_action()
            A.action_abbr = "RCA"
            # A.save_data = True
            active_dict = await app.driver.technique_RCA(A)
            return active_dict

def makeApp(confPrefix, server_key, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Gamry instrument/action server",
        version=2.0,
        driver_class=gamry,
        dyn_endpoints=gamry_dyn_endpoints,
    )

    @app.post(f"/{server_key}/get_meas_status", tags=["action"])
    async def get_meas_status(action: Action = Body({}, embed=True)):
        """Will return 'idle' or 'measuring'.
        Should be used in conjuction with eta to async.sleep loop poll"""
        active = await app.base.setup_and_contain_action()
        await active.enqueue_data_dflt(datadict={"status": await app.driver.status()})
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
        await app.driver.stop()

    return app
