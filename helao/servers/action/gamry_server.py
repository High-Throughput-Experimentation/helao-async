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

from helao.servers.base import makeActionServ
from helaocore.models.sample import LiquidSample, SampleUnion
from helao.helpers.premodels import Action
from helao.drivers.pstat.gamry_driver import gamry
from helao.helpers.config_loader import config_loader


async def gamry_dyn_endpoints(app=None):
    servKey = app.base.server.server_name
    enable_pstat = False

    while not app.driver.ready:
        app.base.print_message("waiting for gamry init", info=True)
        await asyncio.sleep(1)

    if app.driver.pstat is not None:
        enable_pstat = True

    if enable_pstat:

        @app.post(f"/{servKey}/run_LSV")
        async def run_LSV(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            fast_samples_in: Optional[List[SampleUnion]] = Body([], embed=True),
            Vinit__V: Optional[float] = 0.0,  # Initial value in volts or amps.
            Vfinal__V: Optional[float] = 1.0,  # Final value in volts or amps.
            ScanRate__V_s: Optional[
                float
            ] = 1.0,  # Scan rate in volts/second or amps/second.
#            SampleRate: Optional[
            AcqInterval__s: Optional[
                float
            ] = 0.01,  # Time between data acquisition samples in seconds.
            TTLwait: Optional[int] = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            TTLsend: Optional[int] = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            IErange: Optional[app.driver.gamry_range_enum] = "auto",
        ):
            """Linear Sweep Voltammetry (unlike CV no backward scan is done)
            use 4bit bitmask for triggers
            IErange depends on gamry model used (test actual limit before using)"""
            A = await app.base.setup_action()
            A.action_abbr = "LSV"
            # A.save_data = True
            active_dict = await app.driver.technique_LSV(A)
            return active_dict

        @app.post(f"/{servKey}/run_CA")
        async def run_CA(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            fast_samples_in: Optional[List[SampleUnion]] = Body([], embed=True),
            Vval__V: Optional[float] = 0.0,
            Tval__s: Optional[float] = 10.0,
#            SampleRate: Optional[
            AcqInterval__s: Optional[
                float
            ] = 0.01,  # Time between data acquisition samples in seconds.
            TTLwait: Optional[int] = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            TTLsend: Optional[int] = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            IErange: Optional[app.driver.gamry_range_enum] = "auto",
        ):
            """Chronoamperometry (current response on amplied potential)
            use 4bit bitmask for triggers
            IErange depends on gamry model used
            (test actual limit before using)"""
            A = await app.base.setup_action()
            A.action_abbr = "CA"
            # A.save_data = True
            active_dict = await app.driver.technique_CA(A)
            return active_dict

        @app.post(f"/{servKey}/run_CP")
        async def run_CP(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            fast_samples_in: Optional[List[SampleUnion]] = Body([], embed=True),
            Ival__A: Optional[float] = 0.0,
            Tval__s: Optional[float] = 10.0,
#            SampleRate: Optional[
            AcqInterval__s: Optional[
                float
            ] = 1.0,  # Time between data acquisition samples in seconds.
            TTLwait: Optional[int] = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            TTLsend: Optional[int] = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            IErange: Optional[app.driver.gamry_range_enum] = "auto",
        ):
            """Chronopotentiometry (Potential response on controlled current)
            use 4bit bitmask for triggers
            IErange depends on gamry model used (test actual limit before using)"""
            A = await app.base.setup_action()
            A.action_abbr = "CP"
            # A.save_data = True
            active_dict = await app.driver.technique_CP(A)
            return active_dict

        @app.post(f"/{servKey}/run_CV")
        async def run_CV(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            fast_samples_in: Optional[List[SampleUnion]] = Body([], embed=True),
            Vinit__V: Optional[float] = 0.0,  # Initial value in volts or amps.
            Vapex1__V: Optional[float] = 1.0,  # Apex 1 value in volts or amps.
            Vapex2__V: Optional[float] = -1.0,  # Apex 2 value in volts or amps.
            Vfinal__V: Optional[float] = 0.0,  # Final value in volts or amps.
            ScanRate__V_s: Optional[
                float
            ] = 1.0,  # scan rate in volts/second or amps/second.
            AcqInterval__s: Optional[float] = 0.01,  # Time between data acquisition steps.
            Cycles: Optional[int] = 1,
            TTLwait: Optional[int] = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            TTLsend: Optional[int] = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            IErange: Optional[app.driver.gamry_range_enum] = "auto",
        ):
            """Cyclic Voltammetry (most widely used technique
            for acquireing information about electrochemical reactions)
            use 4bit bitmask for triggers
            IErange depends on gamry model used (test actual limit before using)"""
            A = await app.base.setup_action()
            A.action_abbr = "CV"
            # A.save_data = True
            active_dict = await app.driver.technique_CV(A)
            return active_dict

        @app.post(f"/{servKey}/run_EIS")
        async def run_EIS(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            fast_samples_in: Optional[List[SampleUnion]] = Body([], embed=True),
            Vval__V: Optional[float] = 0.0,
            Tval__s: Optional[float] = 10.0,
            Freq: Optional[float] = 1000.0,
            RMS: Optional[float] = 0.02,
            Precision: Optional[
                float
            ] = 0.001,  # The precision is used in a Correlation Coefficient (residual power) based test to determine whether or not to measure another cycle.
            AcqInterval__s: Optional[float] = 0.01,
            TTLwait: Optional[int] = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            TTLsend: Optional[int] = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            IErange: Optional[app.driver.gamry_range_enum] = "auto",
        ):
            """Electrochemical Impendance Spectroscopy
            NOT TESTED
            use 4bit bitmask for triggers
            IErange depends on gamry model used (test actual limit before using)"""
            A = await app.base.setup_action()
            A.action_abbr = "EIS"
            # A.save_data = True
            active_dict = await app.driver.technique_EIS(A)
            return active_dict

        @app.post(f"/{servKey}/run_OCV")
        async def run_OCV(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            fast_samples_in: Optional[List[SampleUnion]] = Body([], embed=True),
            Tval__s: Optional[float] = 10.0,
            AcqInterval__s: Optional[float] = 0.01,
            TTLwait: Optional[int] = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            TTLsend: Optional[int] = Query(
                -1, ge=-1, le=3
            ),  # -1 disables, else select TTL 0-3
            # IErange: Optional[app.driver.gamry_range_enum] = "auto",
            IErange: Optional[app.driver.gamry_range_enum] = "auto",
        ):
            """mesasures open circuit potential
            use 4bit bitmask for triggers
            IErange depends on gamry model used (test actual limit before using)"""
            A = await app.base.setup_action()
            A.action_abbr = "OCV"
            # A.save_data = True
            active_dict = await app.driver.technique_OCV(A)
            return active_dict


def makeApp(confPrefix, servKey, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = makeActionServ(
        config=config,
        server_key=servKey,
        server_title=servKey,
        description="Gamry instrument/action server",
        version=2.0,
        driver_class=gamry,
        dyn_endpoints=gamry_dyn_endpoints,
    )

    @app.post(f"/{servKey}/get_meas_status")
    async def get_meas_status(action: Optional[Action] = Body({}, embed=True)):
        """Will return 'idle' or 'measuring'.
        Should be used in conjuction with eta to async.sleep loop poll"""
        active = await app.base.setup_and_contain_action()
        await active.enqueue_data_dflt(datadict={"status": await app.driver.status()})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/stop")
    async def stop(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Stops measurement in a controlled way."""
        active = await app.base.setup_and_contain_action(action_abbr="stop")
        await active.enqueue_data_dflt(datadict={"stop": await app.driver.stop()})
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
