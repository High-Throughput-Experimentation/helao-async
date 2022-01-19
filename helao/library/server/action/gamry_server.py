# shell: uvicorn motion_server:app --reload
""" A FastAPI service definition for a potentiostat device server, e.g. Gamry.

The potentiostat service defines RESTful methods for sending commmands and retrieving 
data from a potentiostat driver class such as 'gamry_driver' or 'gamry_simulate' using
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
from importlib import import_module
from fastapi import Request
from socket import gethostname
from uuid import UUID

from helaocore.server import make_action_serv, setup_action
from helao.library.driver.gamry_driver import gamry, Gamry_IErange
import helaocore.model.sample as hcms
from helaocore.server.base import ActiveParams, FileConnParams


def makeApp(confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config
 
    app = make_action_serv(
        config,
        servKey,
        servKey,
        "Gamry instrument/action server",
        version=2.0,
        driver_class=gamry,
    )
    

    @app.post(f"/{servKey}/get_meas_status")
    async def get_meas_status(request: Request):
        """Will return 'idle' or 'measuring'. 
        Should be used in conjuction with eta to async.sleep loop poll"""
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["status"]
        )
        await active.enqueue_data_dflt(datadict = \
                                       {"status": await app.driver.status()})
        finished_action = await active.finish()
        return finished_action.as_dict()


    @app.post(f"/{servKey}/run_LSV")
    async def run_LSV(
                      request: Request,
                      fast_samples_in: Optional[List[hcms.SampleUnion]] = \
           [hcms.LiquidSample(**{"sample_no":1,"machine_name":gethostname()})],
                      Vinit: Optional[float] = 0.0,  # Initial value in volts or amps.
                      Vfinal: Optional[float] = 1.0,  # Final value in volts or amps.
                      ScanRate: Optional[float] = 1.0,  # Scan rate in volts/second or amps/second.
                      SampleRate: Optional[
                                           float
                                          ] = 0.01,  # Time between data acquisition samples in seconds.
                      TTLwait: Optional[int] = -1,  # -1 disables, else select TTL 0-3
                      TTLsend: Optional[int] = -1,  # -1 disables, else select TTL 0-3
                      IErange: Optional[Gamry_IErange] = "auto",
                      scratch: Optional[List[None]] = [None], # temp fix so swagger still works
                     ):
        """Linear Sweep Voltammetry (unlike CV no backward scan is done)
        use 4bit bitmask for triggers
        IErange depends on gamry model used (test actual limit before using)"""
        A = await setup_action(request)
        A.action_abbr = "LSV"
        # A.save_data = True
        active_dict = await app.driver.technique_LSV(A)
        return active_dict


    @app.post(f"/{servKey}/run_CA")
    async def run_CA(
                     request: Request,
                      fast_samples_in: Optional[List[hcms.SampleUnion]] = \
           [hcms.LiquidSample(**{"sample_no":1,"machine_name":gethostname()})],
                     Vval: Optional[float] = 0.0,
                     Tval: Optional[float] = 10.0,
                     SampleRate: Optional[
                                          float
                     ] = 0.01,  # Time between data acquisition samples in seconds.
                     TTLwait: Optional[int] = -1,  # -1 disables, else select TTL 0-3
                     TTLsend: Optional[int] = -1,  # -1 disables, else select TTL 0-3
                     IErange: Optional[Gamry_IErange] = "auto",
                     scratch: Optional[List[None]] = [None], # temp fix so swagger still works
                    ):
        """Chronoamperometry (current response on amplied potential)
        use 4bit bitmask for triggers
        IErange depends on gamry model used 
        (test actual limit before using)"""
        A = await setup_action(request)
        A.action_abbr = "CA"
        # A.save_data = True
        active_dict = await app.driver.technique_CA(A)
        return active_dict


    @app.post(f"/{servKey}/run_CP")
    async def run_CP(
                     request: Request,
                      fast_samples_in: Optional[List[hcms.SampleUnion]] = \
           [hcms.LiquidSample(**{"sample_no":1,"machine_name":gethostname()})],
                     Ival: Optional[float] = 0.0,
                     Tval: Optional[float] = 10.0,
                     SampleRate: Optional[
                                          float
                                         ] = 1.0,  # Time between data acquisition samples in seconds.
                     TTLwait: Optional[int] = -1,  # -1 disables, else select TTL 0-3
                     TTLsend: Optional[int] = -1,  # -1 disables, else select TTL 0-3
                     IErange: Optional[Gamry_IErange] = "auto",
                     scratch: Optional[List[None]] = [None], # temp fix so swagger still works
                    ):
        """Chronopotentiometry (Potential response on controlled current)
        use 4bit bitmask for triggers
        IErange depends on gamry model used (test actual limit before using)"""
        A = await setup_action(request)
        A.action_abbr = "CP"
        # A.save_data = True
        active_dict = await app.driver.technique_CP(A)
        return active_dict


    @app.post(f"/{servKey}/run_CV")
    async def run_CV(
                     request: Request,
                      fast_samples_in: Optional[List[hcms.SampleUnion]] = \
           [hcms.LiquidSample(**{"sample_no":1,"machine_name":gethostname()})],
                     Vinit: Optional[float] = 0.0,  # Initial value in volts or amps.
                     Vapex1: Optional[float] = 1.0,  # Apex 1 value in volts or amps.
                     Vapex2: Optional[float] = -1.0,  # Apex 2 value in volts or amps.
                     Vfinal: Optional[float] = 0.0,  # Final value in volts or amps.
                     ScanRate: Optional[
                                        float
                     ] = 1.0,  # Apex scan rate in volts/second or amps/second.
                     SampleRate: Optional[float] = 0.01,  # Time between data acquisition steps.
                     Cycles: Optional[int] = 1,
                     TTLwait: Optional[int] = -1,  # -1 disables, else select TTL 0-3
                     TTLsend: Optional[int] = -1,  # -1 disables, else select TTL 0-3
                     IErange: Optional[Gamry_IErange] = "auto",
                     scratch: Optional[List[None]] = [None], # temp fix so swagger still works
                    ):
        """Cyclic Voltammetry (most widely used technique 
        for acquireing information about electrochemical reactions)
        use 4bit bitmask for triggers
        IErange depends on gamry model used (test actual limit before using)"""
        A = await setup_action(request)
        A.action_abbr = "CV"
        # A.save_data = True
        active_dict = await app.driver.technique_CV(A)
        return active_dict

    @app.post(f"/{servKey}/run_EIS")
    async def run_EIS(
                      request: Request,
                      fast_samples_in: Optional[List[hcms.SampleUnion]] = \
           [hcms.LiquidSample(**{"sample_no":1,"machine_name":gethostname()})],
                      Vval: Optional[float] = 0.0,
                      Tval: Optional[float] = 10.0,
                      Freq: Optional[float] = 1000.0,
                      RMS: Optional[float] = 0.02,
                      Precision: Optional[
                                          float
                                         ] = 0.001,  # The precision is used in a Correlation Coefficient (residual power) based test to determine whether or not to measure another cycle.
                      SampleRate: Optional[float] = 0.01,
                      TTLwait: Optional[int] = -1,  # -1 disables, else select TTL 0-3
                      TTLsend: Optional[int] = -1,  # -1 disables, else select TTL 0-3
                      IErange: Optional[Gamry_IErange] = "auto",
                      scratch: Optional[List[None]] = [None], # temp fix so swagger still works
                     ):
        """Electrochemical Impendance Spectroscopy
        NOT TESTED
        use 4bit bitmask for triggers
        IErange depends on gamry model used (test actual limit before using)"""
        A = await setup_action(request)
        A.action_abbr = "EIS"
        # A.save_data = True
        active_dict = await app.driver.technique_EIS(A)
        return active_dict

    @app.post(f"/{servKey}/run_OCV")
    async def run_OCV(
                      request: Request,
                      fast_samples_in: Optional[List[hcms.SampleUnion]] = \
           [hcms.LiquidSample(**{"sample_no":1,"machine_name":gethostname()})],
                      Tval: Optional[float] = 10.0,
                      SampleRate: Optional[float] = 0.01,
                      TTLwait: Optional[int] = -1,  # -1 disables, else select TTL 0-3
                      TTLsend: Optional[int] = -1,  # -1 disables, else select TTL 0-3
                      IErange: Optional[Gamry_IErange] = "auto",
                      scratch: Optional[List[None]] = [None], # temp fix so swagger still works
                     ):
        """mesasures open circuit potential
        use 4bit bitmask for triggers
        IErange depends on gamry model used (test actual limit before using)"""
        A = await setup_action(request)
        A.action_abbr = "OCV"
        # A.save_data = True
        active_dict = await app.driver.technique_OCV(A)
        return active_dict


    @app.post(f"/{servKey}/stop")
    async def stop(request: Request):
        """Stops measurement in a controlled way."""
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["status"],
                                          action_abbr = "stop"
        )
        await active.enqueue_data_dflt(datadict = \
                                       {"stop": await app.driver.stop()})
        finished_action = await active.finish()
        return finished_action.as_dict()


    @app.post(f"/{servKey}/estop")
    async def estop(
                    request: Request,
                    switch: Optional[bool] = True,
                   ):
        """Same as stop, but also sets estop flag."""
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["status"],
                                          action_abbr = "estop"
        )
        await active.enqueue_data_dflt(datadict = \
                                       {"stop": await app.driver.estop(active)})
        finished_action = await active.finish()
        return finished_action.as_dict()


    @app.post("/shutdown")
    def post_shutdown():
        # asyncio.gather(app.driver.close_connection())
        app.driver.kill_GamryCom()

    #    shutdown_event()


    @app.on_event("shutdown")
    def shutdown_event():
        # this gets called when the server is shut down or reloaded to ensure a clean
        # disconnect ... just restart or terminate the server
        asyncio.gather(app.driver.close_connection())
        app.driver.kill_GamryCom()
        return {"shutdown"}

    return app
