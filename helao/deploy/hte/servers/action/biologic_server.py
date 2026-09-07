# shell: uvicorn motion_server:app --reload
"""Biologic potentiostat action server.

Wraps :class:`BiologicDriver` and exposes electrochemistry technique endpoints
(``run_CA``, ``run_CP``, ``run_CV``, ``run_OCV``, ``run_PEIS``, ``run_GEIS``,
``run_CAOCV``) plus status/stop routes. Uses the :class:`Executor` model so
the hardware driver stays decoupled from the action-server base class.
"""

__all__ = ["makeApp"]


import asyncio
import itertools
import os
import time
from collections import defaultdict, deque
from typing import Any, Optional, Union

import numpy as np
import pandas as pd
from fastapi import Body

from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.core.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    SolidSample,
)
from helao.hexagon.app.action_context import ActionContext, action_version
from helao.hexagon.app.action_host import ActionHost
from helao.helpers import config_loader
from helao.helpers import helao_logging as logging  # get LOGGER from the host instance
from helao.helpers.bubble_detection import bubble_detection
from helao.helpers.executor import Executor

from ...drivers.pstat.biologic.driver import BiologicDriver
from ...drivers.pstat.biologic.enum import EC_Bandwidth, EC_ERange, EC_IRange
from ...drivers.pstat.biologic.technique import BIOTECHS
from ...drivers.pstat.biologic_backend import BiologicBackend
from ...drivers.pstat.biologic_eclib2 import technique as ec2tech
from ...drivers.pstat.biologic_eclib2.driver import BiologicEclib2Driver
from ...drivers.pstat.biologic_eclib2.technique import (
    resolve as resolve_eclib2_technique,
)
from ...drivers.pstat.biologic_ole.driver import BiologicOleDriver
from ...drivers.pstat.biologic_ole.technique import resolve as resolve_ole_technique

global LOGGER
LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class BiologicExec(Executor):
    """Executor that runs a single Biologic technique on one channel.

    Loads the technique into the driver in ``_pre_exec``, starts the channel
    (optionally honouring Gamry-style TTL parameters) in ``_exec``, streams
    data via ``_poll`` while monitoring optional Ewe/I alert thresholds, and
    cleans up the channel in ``_post_exec`` while running bubble detection on
    OCV traces. ``_manual_stop`` aborts the measurement.
    """

    #: Backend-specific technique object -- a BiologicTechnique (eclib) or an
    #: OleTechnique (olecom); the two backends' registries resolve different
    #: types, so this cannot be pinned to one of them.
    technique: Any
    driver: BiologicDriver

    def __init__(self, *args, **kwargs):
        """Initialise the Biologic executor for a specific technique.

        Reads the action parameters (filtering out ``TTL*`` / ``alert*``
        helper keys into separate dicts), binds the driver and target channel,
        and stores the ``technique`` keyword argument.

        Args:
            *args: Positional arguments forwarded to :class:`Executor`.
            **kwargs: Keyword arguments forwarded to :class:`Executor`; must
                include ``technique`` (a backend-specific technique object).
        """
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
            self.driver = self.active.driver
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

    def _action_output_path(self) -> Optional[str]:
        """Absolute path of this action's output directory, or None.

        ``action_output_dir`` is stored *relative* to the run root, so it must
        be joined with ``helaodirs.save_root`` -- and a manual action's root
        is redirected from ACTIVE to DIAG, exactly as ``ActionSession`` does
        when it creates the directory. Returns None rather than guessing if
        the action is not saving, so the OLE backend simply keeps its vendor
        artifacts in scratch.
        """
        action = self.active.action
        if not action.save_act or not action.action_output_dir:
            return None
        try:
            save_root = str(self.active.base.helaodirs.save_root)
        except AttributeError:
            return None
        if action.manual_action:
            save_root = save_root.replace("ACTIVE", "DIAG")
        return os.path.join(save_root, str(action.action_output_dir))

    async def _pre_exec(self) -> dict:
        """Load the configured technique and action parameters into the driver."""
        try:
            resp = self.driver.setup(
                technique=self.technique,
                action_params=self.action_params,
                output_dir=self._action_output_path(),
            )
            error = ErrorCodes.none if resp.response == "success" else ErrorCodes.setup
            LOGGER.info("BiologicExec setup successful.")
        except Exception:
            error = ErrorCodes.critical_error
            LOGGER.error("BiologicExec pre-exec error", exc_info=True)
        return {"error": error}

    async def _exec(self) -> dict:
        """Start the configured channel (optionally waiting for a TTL trigger)."""
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
        """Pull the next data chunk from the channel and evaluate alerts.

        Extends the rolling ``data_buffer`` deques with the latest samples,
        emits :meth:`LOGGER.alert` when configured Ewe/I thresholds are
        crossed for ``alert_duration__s``, and translates the driver response
        into HLO ``active`` / ``finished`` / ``errored`` status.
        """
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

    async def _post_exec(self) -> dict:
        """Clean up the channel and post-process the buffered data.

        Stores the trailing mean of ``t_s``/``Ewe_V``/``I_A`` on the action
        params and, for OCV runs, evaluates :func:`bubble_detection` and sets
        ``has_bubble`` on the action params.
        """
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
        """Interrupt the running technique and disconnect the cell."""
        resp = self.driver.stop()
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.stop
        return {"error": error}


async def biologic_dyn_endpoints(app: ActionHost):
    """Register the Biologic technique endpoints once the driver is ready.

    Disables concurrent actions on this server, waits for
    ``app.driver.ready``, then attaches the ``run_CA``, ``run_CP``, ``run_CV``,
    ``run_OCV``, ``run_PEIS``, ``run_GEIS`` and ``run_CAOCV`` POST routes.

    Args:
        app: The :class:`ActionHost` instance being constructed by ``makeApp``.
    """
    server_key = app.server.server_name
    app.server_params["allow_concurrent_actions"] = False

    # P3a-2 constructor-connect fix: BiologicDriver.__init__ no longer opens the
    # instrument (disconnected construct); connect here at startup. connect()
    # sets app.driver.ready on success, satisfying the wait below.
    connect_resp = app.driver.connect()
    LOGGER.info(f"Biologic connect() returned status={connect_resp.status}")

    while not app.driver.ready:
        LOGGER.info("waiting for biologic init")
        await asyncio.sleep(1)

    @app.action()
    @action_version(2)
    async def run_CA(
        ctx: ActionContext,
        fast_samples_in: list[
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
        """Run chronoamperometry (current response to a stepped potential).

        Maps the I/E/Bandwidth range enums to their driver values and dispatches
        a :class:`BiologicExec` configured with the ``"CA"`` technique. Use a 4-bit
        bitmask for trigger arguments; valid I/E ranges depend on the
        Biologic model.
        """
        active = await ctx.begin()
        active.action.action_abbr = "CA"
        active.action.action_params["AcqInterval__A"] = 10.0
        executor = BiologicExec(
            active=active, oneoff=False, technique=app.resolve_technique("CA")
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.action()
    @action_version(2)
    async def run_CP(
        ctx: ActionContext,
        fast_samples_in: list[
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
        """Run chronopotentiometry (potential response to a controlled current).

        Maps I/E/Bandwidth range enums and dispatches a :class:`BiologicExec`
        configured with the ``"CP"`` technique. Use a 4-bit bitmask for trigger
        arguments; valid I/E ranges depend on the Biologic model.
        """
        active = await ctx.begin()
        active.action.action_abbr = "CP"
        active.action.action_params["AcqInterval__V"] = 10.0
        executor = BiologicExec(
            active=active, oneoff=False, technique=app.resolve_technique("CP")
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.action()
    @action_version(2)
    async def run_CV(
        ctx: ActionContext,
        fast_samples_in: list[
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
        """Run cyclic voltammetry between two apex potentials.

        Subtracts one from ``Cycles`` (the driver expects additional cycles),
        derives ``AcqInterval__V`` from the time interval and scan rate, maps
        I/E/Bandwidth range enums and dispatches a :class:`BiologicExec`
        configured with the ``"CV"`` technique.
        """
        active = await ctx.begin()
        active.action.action_params["Cycles"] -= 1  # i.e. additional cycles
        active.action.action_params["AcqInterval__V"] = (
            active.action.action_params["AcqInterval__s"]
            * active.action.action_params["ScanRate__V_s"]
        )
        active.action.action_abbr = "CV"
        executor = BiologicExec(
            active=active, oneoff=False, technique=app.resolve_technique("CV")
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.action()
    @action_version(2)
    async def run_OCV(
        ctx: ActionContext,
        fast_samples_in: list[
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
        """Measure open-circuit potential for ``Tval__s`` seconds.

        Dispatches a :class:`BiologicExec` configured with the ``"OCV"`` technique;
        the ``*_threshold`` parameters are forwarded to bubble detection during
        ``_post_exec``.
        """
        active = await ctx.begin()
        active.action.action_abbr = "OCV"
        active.action.action_params["AcqInterval__V"] = 10.0
        executor = BiologicExec(
            active=active, oneoff=False, technique=app.resolve_technique("OCV")
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.action()
    @action_version(3)
    async def run_PEIS(
        ctx: ActionContext,
        fast_samples_in: list[
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
        """Run potentiostatic electrochemical impedance spectroscopy (PEIS).

        Maps the I/E/Bandwidth range enums and dispatches a
        :class:`BiologicExec` configured with the ``"PEIS"`` technique.
        """
        active = await ctx.begin()
        active.action.action_abbr = "PEIS"
        executor = BiologicExec(
            active=active, oneoff=False, technique=app.resolve_technique("PEIS")
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.action()
    @action_version(3)
    async def run_GEIS(
        ctx: ActionContext,
        fast_samples_in: list[
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
        """Run galvanostatic electrochemical impedance spectroscopy (GEIS).

        Maps the I/E/Bandwidth range enums and dispatches a
        :class:`BiologicExec` configured with the ``"GEIS"`` technique.
        """
        active = await ctx.begin()
        active.action.action_abbr = "GEIS"
        executor = BiologicExec(
            active=active, oneoff=False, technique=app.resolve_technique("GEIS")
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.action()
    @action_version(2)
    async def run_CAOCV(
        ctx: ActionContext,
        fast_samples_in: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        CA_Vval__V_list: list[float] = Body([], embed=True),
        CA_Tval__s_list: list[float] = Body([], embed=True),
        CA_AcqInterval__s: float = 0.01,  # Time between data acq in seconds.
        CA_IRange: EC_IRange = EC_IRange.AUTO,
        CA_ERange: EC_ERange = EC_ERange.AUTO,
        CA_Bandwidth: EC_Bandwidth = EC_Bandwidth.BW4,
        OCV_Tval__s: float = 10.0,
        OCV_AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
        channel: int = 0,
        TTLwait: int = -1,
        TTLsend: int = -1,
        TTLduration: float = 1.0,
        alert_duration__s: float = -1,
        alert_above: bool = True,
        alert_sleep__s: float = -1,
        alertThreshI_A: float = 0,
    ):
        """Run a CA step followed by an OCV recovery, interleaved per pair.

        Iterates the ``CA_Vval__V_list`` / ``CA_Tval__s_list`` lists; maps the
        CA I/E/Bandwidth range enums and dispatches a :class:`BiologicExec`
        configured with the ``"CAOCV"`` technique.
        """
        active = await ctx.begin()
        active.action.action_abbr = "CAOCV"
        active.action.action_params["CA_AcqInterval__A"] = 10.0
        active.action.action_params["OCV_AcqInterval__V"] = 10.0
        executor = BiologicExec(
            active=active, oneoff=False, technique=app.resolve_technique("CAOCV")
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    # `run_plan` is eclib2-only, the way `run_protocol` is olecom-only: it is
    # not a technique but a whole *experiment* of them, which is a capability
    # EC-Lib 2.0 has and the other two backends do not. easy-biologic runs one
    # program per action, and the OLE backend's multi-technique unit is an
    # `.mps` file, which `run_protocol` covers. Registering it on those
    # backends would advertise a route that could only fail.
    if getattr(app, "pstat_backend", None) == "eclib2":

        @app.action()
        @action_version(1)
        async def run_plan(
            ctx: ActionContext,
            fast_samples_in: list[
                Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
            ] = Body([], embed=True),
            plan: list[dict] = Body([], embed=True),
            loops: list[dict] = Body([], embed=True),
            channel: int = 0,
        ):
            """Run several techniques on one channel as a single experiment.

            One ``BL_LoadExperiment`` for the whole plan, so the techniques run
            back to back with no gap for a round trip between them -- which is
            the point, and is not reachable by chaining ``run_*`` actions.

            Args:
                plan: Techniques in execution order, each
                    ``{"name": <technique>, "params": {...}}`` where ``params``
                    are keyed exactly as that technique's own ``run_*``
                    endpoint keys them. Ranges are per entry, so one plan may
                    run two techniques at different current ranges.
                loops: Repeats, each ``{"start": i, "end": j, "n": k}`` over
                    *plan* indices, inclusive. Spans must nest rather than
                    straddle. An entry may expand to more than one EClib2
                    technique (PEIS becomes CA+PEIS); the indices here are into
                    ``plan``, and the expansion is mapped for you.
                channel: Channel to run on.

            The emitted columns are the union of the entries' columns, so a
            plan mixing CA and PEIS emits both sets with NaN where a technique
            does not report one.
            """
            entries = [
                ec2tech.PlanEntry(
                    name=str(item.get("name", "")), params=dict(item.get("params", {}))
                )
                for item in plan
            ]
            spans = [
                ec2tech.PlanLoop(
                    start=int(item["start"]), end=int(item["end"]), n=int(item["n"])
                )
                for item in loops
            ]
            # Built here, not in the executor: an unbuildable plan must fail
            # the call rather than start an action that then aborts in
            # _pre_exec with the cell already claimed.
            technique = ec2tech.plan_technique(entries, spans)

            active = await ctx.begin()
            active.action.action_abbr = "PLAN"
            executor = BiologicExec(active=active, oneoff=False, technique=technique)
            active_action_dict = active.start_executor(executor)
            return active_action_dict


#: `pstat_backend` value -> driver class. An absent key yields the
#: easy-biologic driver, so every existing station config keeps working
#: unedited; a station opts into EC-Lab (`olecom`) or the EC-Lib 2.0 SDK
#: (`eclib2`) by adding the key. `eclib` and `eclib2` are not versions of one
#: backend: EC-Lib 2.0 is not backwards compatible with the EClib1 DLLs
#: easy-biologic bundles, so they are separate drivers over separate SDKs.
#:
#: Annotated `type[BiologicBackend]` rather than bare `type`, which is what
#: makes the protocol's conformance claim true: the drivers are structural
#: implementers that inherit nothing from it, so nothing checks their shapes
#: unless something assigns them to it in a typed position. This dict is that
#: position -- it is also the one the server actually reads, so a driver whose
#: `setup` lost `output_dir` fails the type check here rather than at the first
#: action. `isinstance` against the runtime_checkable protocol would not do:
#: it compares only method *names*.
BACKENDS: dict[str, type[BiologicBackend]] = {
    "eclib": BiologicDriver,
    "olecom": BiologicOleDriver,
    "eclib2": BiologicEclib2Driver,
}
DEFAULT_BACKEND = "eclib"

#: Technique-object resolver per backend. The two backends take different
#: technique objects -- a BiologicTechnique names an easy-biologic program
#: class, an OleTechnique names an .mps template -- so the endpoints pass a
#: technique *name* and the executor resolves it against the selected
#: backend's registry. A shared object would have to know both.
TECHNIQUE_REGISTRIES = {
    "eclib": lambda name: BIOTECHS[name],
    "olecom": resolve_ole_technique,
    "eclib2": resolve_eclib2_technique,
}


def _backend_name(server_key: str) -> str:
    """The backend this server's config selects.

    Reads the global CONFIG, which ``fast_launcher.py`` populates before it
    imports this module and calls ``makeApp``. Tolerates a missing CONFIG or
    server entry, because capture scripts and build tests call ``makeApp``
    outside the launcher.

    Raises:
        ValueError: On an unrecognized value. A typo must not fall through to
            the default -- a station meaning to drive EC-Lab would silently
            get the easy-biologic driver and fail at connect() with a vendor
            import error that names the wrong problem.
    """
    config = getattr(config_loader, "CONFIG", None) or {}
    params = (config.get("servers") or {}).get(server_key, {}).get("params", {}) or {}
    name = params.get("pstat_backend", DEFAULT_BACKEND)
    if name not in BACKENDS:
        raise ValueError(
            f"unknown pstat_backend {name!r} for server {server_key!r}; "
            f"expected one of {sorted(BACKENDS)}"
        )
    return name


def _driver_class(server_key: str) -> type:
    """The driver class this server's config selects."""
    return BACKENDS[_backend_name(server_key)]


def makeApp(server_key) -> ActionHost:
    """Build the Biologic potentiostat FastAPI app.

    Constructs a :class:`ActionHost` backed by the driver class the server's
    ``pstat_backend`` param selects (``eclib`` or ``olecom``, defaulting to
    ``eclib`` so an existing station config needs no edit), defers technique
    endpoint registration to :func:`biologic_dyn_endpoints`, and adds the
    ``get_meas_status``, ``stop`` and private ``stop_private`` routes.

    Args:
        server_key: Key identifying this server in the orchestration group.

    Returns:
        The configured :class:`ActionHost` application.
    """

    backend = _backend_name(server_key)
    app = ActionHost(
        server_key=server_key,
        server_title=server_key,
        description="Biologic instrument/action server",
        version=3.0,
        driver_classes=[BACKENDS[backend]],
        dyn_endpoints=biologic_dyn_endpoints,
    )
    #: Which backend this app was built for. `base_api` names the driver
    #: namedtuple field from the class name, so `app.drivers.<Name>` differs
    #: between backends -- use `app.driver`.
    app.pstat_backend = backend
    app.resolve_technique = TECHNIQUE_REGISTRIES[backend]

    @app.action()
    async def get_meas_status(ctx: ActionContext):
        """Report the dtaq sink status (e.g. ``idle``/``measuring``).

        Intended for use alongside an estimated ETA in an
        ``asyncio.sleep``-based polling loop.
        """
        active = await ctx.begin()
        await active.enqueue_data_dflt(datadict={"status": app.driver.dtaqsink.status})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.action()
    async def stop(
        ctx: ActionContext,
        channel: Optional[int] = None,
    ):
        """Stop the measurement on ``channel`` via :meth:`BiologicDriver.stop`."""
        active = await ctx.begin(action_abbr="stop")
        app.driver.stop(active.action.action_params["channel"])
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post("/stop_private", tags=["private"])
    def stop_private(channel: Optional[int] = None):
        """Internal counterpart to ``stop`` (no action record)."""
        app.driver.stop(channel)

    return app
