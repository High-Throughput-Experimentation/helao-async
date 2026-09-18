"""HelaoDriver for Biologic potentiostats, calling the EClib1 DLL directly.

Replaces the former easy-biologic-backed driver: connection, firmware, and
status now go through `eclib_client.EclibClient`, which serializes every
vendor call onto one worker thread and turns a vendor error code into
`EclibError`. This module owns the connection half of the driver --
``__init__``, ``connect``, ``get_status``, ``disconnect``, ``reset``, and
``shutdown``. The measurement half (``setup``, ``start_channel``,
``get_data``, ``stop``, ``cleanup``) is added alongside it, not stubbed here.

Unlike the easy-biologic driver, which opened a program per channel, this
driver claims a single channel at a time (``self.channel``) -- see the
measurement half for why.
"""

import asyncio
import os
import time
from typing import Any, Optional

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)
from helao.deploy.hte.drivers.pstat.biologic import data, vendor
from helao.deploy.hte.drivers.pstat.biologic import technique as bt
from helao.deploy.hte.drivers.pstat.biologic.eclib_client import EclibClient, EclibError


def _segment_name(info, technique: Any) -> str:
    """Map one decoded segment's `TechniqueID` back to a `data.COLUMNS` key.

    A plan's steps can be a mix of techniques (a trigger, CAOCV's CA+OCV),
    so each segment is named from what the firmware actually reports rather
    than assuming the whole action is one technique. Falls back to the
    claimed technique's own name for an id this build does not recognize, or
    one (LOOP/TI/TO/TOS) that carries no data columns of its own.
    """
    try:
        name = vendor.TECH_ID(info.TechniqueID).name
    except ValueError:
        return technique.technique_name
    return name if name in data.COLUMNS else technique.technique_name


#: The vendor's `FIRMWARE` enum member for a fully loaded kernel
#: (`kbio_types.py`: NONE=0, INTERPR=1, UNKNOWN=4, KERNEL=5, INVALID=8,
#: ECAL=10, ECAL4=11). `!= 0` was wrong -- it treated every other non-kernel
#: code as "kernel loaded", including ECAL, which a calibration leaves behind
#: and which then never gets a kernel reloaded.
KERNEL_FIRMWARE_CODE = 5

#: How long `_ensure_stopped` waits for a channel to reach `PROG_STATE.STOP`
#: after `BL_StopChannel`, and how often it looks. The station's firmware log
#: puts a halt at 1-2 ms ("halt experiment..." to "end protocol"), so this is
#: three orders of magnitude of headroom rather than a tuned value. It is a
#: ceiling, not a wait: a channel that is already stopped costs one
#: `BL_GetChannelInfos`. Expiring is a warning and the load proceeds -- the
#: firmware, not this timer, is what gets to refuse the load.
STOP_BEFORE_LOAD_TIMEOUT_S = 2.0
STOP_BEFORE_LOAD_POLL_S = 0.02


def _firmware_path(sdk_path: str, name: str) -> str:
    """Join a firmware asset name with `sdk_path`, the same reason
    `_load_plan` joins a `.ecc` name -- unless `name` is empty, which is a
    sentinel (DIGICORE's FPGA slot: `vendor.firmware_assets` returns `""`
    meaning "no FPGA file"), not a bare filename. `os.path.join(sdk_path,
    "")` yields `f"{sdk_path}/"`, which is not empty and would tell the DLL
    to look for a file that does not exist.
    """
    return os.path.join(sdk_path, name) if name else name


def _kernel_loaded(ch: vendor.ChannelInfo) -> bool:
    """A channel has a kernel loaded only at ``FirmwareCode == KERNEL_FIRMWARE_CODE``.

    Same check as the vendor example's ``is_kernel_loaded`` property (`code ==
    FIRMWARE.KERNEL`); kept here (not called from the example, which this
    repo does not vendor).
    """
    return ch.FirmwareCode == KERNEL_FIRMWARE_CODE


class BiologicDriver(HelaoDriver):
    """HelaoDriver implementation for a multi-channel Biologic potentiostat,
    driven directly through the EClib1 DLL.

    Attributes:
        ready: Whether ``connect()`` has succeeded and not since been undone.
        address: Instrument IP address.
        num_channels: Number of channels the instrument exposes.
        sdk_path: Filesystem path to the EC-Lab Development Package's ``lib``
            directory (or, under simulation, an unused placeholder).
        simulate: Whether to load the in-process fake DLL instead of the
            real one.
        force_load_firmware: Reflash the channel's firmware kernel on every
            connect, even when one is already loaded. Off by default -- see
            module docstring for why the vendor example's ``force=True`` is
            not the default here.
        device_name: Human-readable identifier for the connected instrument.
        channel: The single channel currently claimed for a measurement, or
            ``None`` when free.
        board_type: The connected channel's ``vendor.BOARD_TYPE`` value, or
            ``None`` before a successful connect.
    """

    device_name: str

    def __init__(self, config: dict = {}):
        """Store configuration only. No device I/O here -- the action server
        calls ``connect()`` at startup (P3a-2 constructor-connect fix).

        Args:
            config: Driver configuration. Recognized keys: ``address``
                (default ``"192.168.200.240"``), ``num_channels`` (default
                ``12``), ``sdk_path`` (default ``vendor.DEFAULT_SDK_PATH``),
                ``simulate`` (default ``False``), ``force_load_firmware``
                (default ``False``), ``timeout`` (default ``5``).
        """
        super().__init__(config=config)
        self.address = config.get("address", "192.168.200.240")
        self.num_channels = config.get("num_channels", 12)
        self.sdk_path = config.get("sdk_path", vendor.DEFAULT_SDK_PATH)
        self.simulate = config.get("simulate", False)
        self.force_load_firmware = config.get("force_load_firmware", False)
        self.timeout = config.get("timeout", 5)

        self.ready = False
        self.channel: Optional[int] = None
        self.board_type: Optional[int] = None
        self.device_name = "unknown"
        self._client: Optional[EclibClient] = None
        self._tracker: Optional[data.RunTracker] = None
        self._technique: Any = None
        self._params: dict = {}
        #: Total `RunTracker.skipped` last logged, so a WARNING fires only
        #: when the dropped-point count has grown since the last one.
        self._logged_skipped: int = 0

    def connect(self) -> DriverResponse:
        """Open the connection to the instrument and load its firmware if
        needed.

        A second call on an already-live connection is a successful no-op,
        checked via ``EclibClient.test_connection`` rather than a flag set
        before the attempt -- a flag set early is what stranded the old
        driver after a throwing connect.

        Returns:
            ``DriverResponse`` with ``status=ok`` on success, ``status=busy``
            if EC-Lab already holds the instrument, otherwise
            ``status=error``. A failed attempt tears down any half-built
            client so the driver stays retryable.
        """
        if self.ready and self._client is not None and self._client.test_connection():
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )

        client = None
        try:
            client = EclibClient(sdk_path=self.sdk_path, simulate=self.simulate)
            info = client.connect(self.address, self.timeout)
            self.device_name = f"{info.DeviceCode}/fw{info.FirmwareVersion}"
            self.board_type = client.board_type(0)
            LOGGER.info(
                f"connected to {self.device_name} at {self.address} "
                f"(board_type={vendor.BOARD_TYPE(self.board_type).name}, "
                f"family={vendor.board_family(self.board_type).value})"
            )

            try:
                needs_kernel = not _kernel_loaded(client.channel_info(0))
            except EclibError as exc:
                if exc.name != "ERR_FIRM_FIRMWARENOTLOADED":
                    raise
                # BL_GetChannelInfos needs the kernel it is being asked
                # about, so a channel that has lost its firmware answers
                # -308 instead of reporting a FirmwareCode of 0. Treated as
                # a failure, that made a channel whose firmware crashed
                # unrecoverable from here: connect aborted on the very probe
                # it uses to decide whether to reload, and no later call
                # could get further. Observed at a station on 2026-09-18,
                # where a BL_LoadTechnique that returned -200 took the
                # channel's kernel with it.
                LOGGER.warning(
                    f"channel 0 reports no firmware ({exc}); loading the kernel"
                )
                needs_kernel = True
            if self.force_load_firmware or needs_kernel:
                kernel, fpga = vendor.firmware_assets(self.board_type)
                client.load_firmware(
                    0,
                    _firmware_path(self.sdk_path, kernel),
                    _firmware_path(self.sdk_path, fpga),
                    force=self.force_load_firmware,
                )

            for message in client.drain_messages(0):
                LOGGER.warning(f"channel 0 firmware message: {message}")

            self._client = client
            self.ready = True
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except EclibError as exc:
            LOGGER.error(f"connect failed: {exc}", exc_info=True)
            status = (
                DriverStatus.busy
                if exc.name == "ERR_GEN_ECLAB_LOADED"
                else DriverStatus.error
            )
            if client is not None:
                client.close()
            return DriverResponse(response=DriverResponseType.failed, status=status)
        except Exception:
            LOGGER.error("connect failed", exc_info=True)
            if client is not None:
                client.close()
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )

    def get_status(self, channel: Optional[int] = None) -> DriverResponse:
        """Return the driver status, optionally for a single channel.

        Args:
            channel: Channel index to query. When ``None``, queries every
                channel and reports ``busy`` if any is not ``STOP``.

        Returns:
            ``DriverResponse`` whose ``data`` maps channel index to the raw
            ``State`` int. An out-of-range channel (or a driver that has
            never connected) reports ``uninitialized`` with ``data={}``.
        """
        if not self.ready or self._client is None:
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.uninitialized,
                data={},
            )
        if channel is None:
            channels = list(range(self.num_channels))
        elif 0 <= channel < self.num_channels:
            channels = [channel]
        else:
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.uninitialized,
                data={},
            )

        try:
            states = {}
            for ch in channels:
                info = self._client.channel_info(ch)
                states[ch] = info.State
                for message in self._client.drain_messages(ch):
                    LOGGER.warning(f"channel {ch} firmware message: {message}")
            status = (
                DriverStatus.busy
                if any(state != vendor.PROG_STATE.STOP for state in states.values())
                else DriverStatus.ok
            )
            return DriverResponse(
                response=DriverResponseType.success, status=status, data=states
            )
        except EclibError:
            LOGGER.error("get_status failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )

    def disconnect(self) -> DriverResponse:
        """Close the connection to the instrument and clear connected state."""
        try:
            if self._client is not None:
                self._client.close()
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("disconnect failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        finally:
            self._client = None
            self.ready = False
            self.channel = None
            self.board_type = None

    def reset(self) -> DriverResponse:
        """Disconnect then reconnect, reporting the reconnect's own result.

        The previous implementation built a success response before
        reconnecting in a ``finally``, so a failed reconnect still reported
        success. This returns whatever ``connect()`` actually reports.
        """
        self.disconnect()
        return self.connect()

    def shutdown(self) -> None:
        """Release a claimed channel, if any, then disconnect.

        Safe to call on a driver that never connected. Stopping/cleaning up
        a claimed channel is the measurement half's responsibility
        (``stop``/``cleanup``); this only drives them when there is
        something to release.
        """
        if self.channel is not None:
            try:
                self.stop(self.channel)
            except Exception:
                LOGGER.error("shutdown: stop failed", exc_info=True)
            try:
                self.cleanup(self.channel)
            except Exception:
                LOGGER.error("shutdown: cleanup failed", exc_info=True)
        self.disconnect()

    # -- measurement (setup / start / get_data / stop / cleanup) -----------

    def _load_plan(self, channel: int, plan, board_type: int) -> None:
        """Load every step of a plan onto `channel`, in order.

        `first`/`last` are derived from a step's position: EClib1 has no
        unload, so `BL_LoadTechnique(first=True)` is what clears whatever a
        previous load left behind, and `last=True` closes the list. The
        `.ecc` name is joined with `sdk_path` -- easy-biologic gets away with
        a bare name only because its vendored `.ecc` set is co-located with
        `EClib64.dll`; that is not guaranteed for a station's own
        `sdk_path` layout, and an absolute path fails with a path a human
        can go and look at rather than depending on undocumented
        DLL-relative resolution.
        """
        assert self._client is not None
        self._ensure_stopped(channel)
        total = len(plan.steps)
        for i, step in enumerate(plan.steps):
            ecc = vendor.ecc_file(step.ecc_stem, board_type)
            first, last = i == 0, i == total - 1
            params = self._client.define_params(step.params)
            try:
                self._client.load_technique(
                    channel,
                    os.path.join(self.sdk_path, ecc),
                    params,
                    first=first,
                    last=last,
                )
            except EclibError as exc:
                raise EclibError(
                    exc.code,
                    f"loading step {i + 1}/{total} {step.ecc_stem} "
                    f"(ecc {ecc}, tech_id {step.tech_id}, "
                    f"{len(step.params)} params, first={first}, last={last})",
                ) from exc
            # Drained per step, not once at the end: the firmware answers a
            # load asynchronously and `BL_LoadTechnique` can return 0 on a
            # load the firmware went on to refuse ("cannot load experiment
            # after make..."). Drained in a lump by the next `get_status`,
            # those lines cannot be attributed to the call that caused them,
            # which is how a two-step plan's failure read as a one-step
            # plan's error code.
            for message in self._client.drain_messages(channel):
                LOGGER.warning(
                    f"channel {channel} load message "
                    f"(step {i + 1}/{total} {step.ecc_stem}): {message}"
                )

    def _ensure_stopped(self, channel: int) -> None:
        """Stop `channel` and wait for it, before loading a technique list.

        A list spanning more than one `BL_LoadTechnique` call leaves the
        experiment un-made between calls, and the firmware will not begin one
        on a channel that is still running. The station log for a TTL run
        shows exactly that: the trigger's load (`first=True, last=False`)
        drew `cannot load experiment after make...` while still returning 0,
        and the technique's load then failed with `make experiment failed`
        and `ERR_TECH_LOADTECHNIQUEFAILED` (-403), leaving the channel
        holding the 8 bytes of the trigger alone. A single `first=True,
        last=True` load is "made" by its own call and survives a running
        channel, which is why plain `run_OCV` works and every linked plan --
        a trigger, `CAOCV`, `run_plan` -- did not.

        Stopping is safe here and nowhere near as blunt as it looks: every
        caller of this is about to replace the channel's whole technique
        list, and the load itself halts the channel anyway (`halt
        experiment...`/`end protocol`). The only thing added is *waiting* for
        that halt to land before the next call needs it.
        """
        assert self._client is not None
        deadline = time.time() + STOP_BEFORE_LOAD_TIMEOUT_S
        requested = False
        while True:
            state = self._client.channel_info(channel).State
            if state == vendor.PROG_STATE.STOP:
                return
            if not requested:
                LOGGER.info(
                    f"channel {channel} is in state {state}; stopping it "
                    "before loading"
                )
                self._client.stop_channel(channel)
                requested = True
                continue  # a halt lands in 1-2 ms; re-probe before sleeping
            if time.time() >= deadline:
                LOGGER.warning(
                    f"channel {channel} still reports state {state} "
                    f"{STOP_BEFORE_LOAD_TIMEOUT_S}s after BL_StopChannel; "
                    "loading anyway"
                )
                return
            time.sleep(STOP_BEFORE_LOAD_POLL_S)

    def setup(
        self,
        technique: Any,
        action_params: dict = {},
        output_dir: Optional[str] = None,
    ) -> DriverResponse:
        """Claim a channel and build its plan, without loading anything.

        **Nothing is sent to the instrument here.** Until 2026-09-18 this
        also loaded the plan, as a validation load, on the reasoning that
        `start_channel`'s reload with the real `ttl_params` would replace it
        and the first load was therefore harmless. It was not. A load takes
        the firmware ~170 ms to "make" (its own messages timestamp it), and
        the channel reads `PROG_STATE.RUN` for that whole time; the reload
        landed inside that window. A single-call load survives it -- the
        firmware halts the in-flight make and remakes -- so `run_OCV` worked.
        A two-call load (any linked plan: a trigger, `CAOCV`, `run_plan`)
        did not: the first call drew `cannot load experiment after make...`
        and the second failed, with -403 or, once a `BL_StopChannel` was put
        in front of it, `ERR_COMM_COMMFAILED` and a channel that had lost
        its kernel. `easy_biologic` never hit this because it loads exactly
        once per run, immediately before starting.

        What is validated here is everything that does not need the
        instrument: the technique builds its parameter entries (a missing or
        out-of-range action param raises `TechniqueError`) and every step's
        `.ecc` resolves for this board. A vendor rejection of the parameter
        values themselves now surfaces from `start_channel` instead, which
        fails the same action one step later.

        Args:
            technique: A `BiologicTechnique` (or `PlanTechnique`) from
                `BIOTECHS`.
            action_params: Endpoint parameters, including `channel`.
            output_dir: Accepted for signature parity with the OLE backend,
                which ships vendor artifacts there. EClib1 writes no files of
                its own, so this is unused.

        Returns:
            `DriverResponse` with `status=busy` naming the current holder if
            another channel is already claimed, `status=error` for an
            out-of-range channel or a build/load failure, else `status=ok`.
        """
        channel = action_params.get("channel", -1)
        if channel not in range(self.num_channels):
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
                message=f"channel {channel} does not exist (0..{self.num_channels - 1})",
            )
        if self.channel is not None:
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.busy,
                message=f"channel {self.channel} is already claimed",
            )
        self.channel = channel
        try:
            board_type = self.board_type
            if not self.ready or self._client is None or board_type is None:
                raise ConnectionError("device not connected")
            defaults = getattr(technique, "defaults", {}) or {}
            params = {**defaults, **action_params}
            plan = bt.plan_for(technique, params, None)
            # Built and thrown away: building is the validation (see the
            # docstring), and the plan `start_channel` loads is a different
            # one -- it is rebuilt there with the `ttl_params` that only
            # arrive with the start. Resolving each `.ecc` is part of the
            # check: an unsupported board raises `VendorError` here rather
            # than mid-load.
            for step in plan.steps:
                vendor.ecc_file(step.ecc_stem, board_type)
            self._technique = technique
            self._params = params
            return DriverResponse(
                response=DriverResponseType.success,
                message="setup complete",
                status=DriverStatus.ok,
            )
        except Exception as exc:
            LOGGER.error("setup failed", exc_info=True)
            self.channel = None
            self._technique = None
            self._params = {}
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
                message=str(exc),
            )

    def start_channel(
        self, channel: int = 0, ttl_params: Optional[dict] = None
    ) -> DriverResponse:
        """Rebuild the plan with `ttl_params` honoured, load it, verify the
        loaded technique list, and start the channel running.

        Reloading here (rather than reusing `setup`'s load) is what makes a
        requested trigger both possible and verifiable: EClib1 offers no way
        to insert a technique into an already-loaded list, so the only way
        to get a trigger to load at index 0 is to load the whole plan again
        with it in place -- and then read the list back rather than trust
        it, which is the check easy-biologic never made.
        """
        try:
            if self.channel is None or channel != self.channel:
                raise ValueError(f"channel {channel} has not been set up")
            board_type = self.board_type
            if self._client is None or not self.ready or board_type is None:
                raise ConnectionError("device not connected")
            if self._technique is None:
                raise ValueError(f"channel {channel} has not been set up")

            status = self.get_status(channel)
            if status.status == DriverStatus.error:
                raise ValueError(f"channel {channel} encountered an error")
            if status.status == DriverStatus.busy:
                # Warned, never refused. `setup` has already called
                # BL_LoadTechnique(first=True) on this channel, which
                # replaces the whole loaded list and halts whatever was
                # running -- the "halt experiment"/"end protocol" firmware
                # messages this drains are that happening. A gate placed
                # *after* the destructive step protects nothing, and it cost
                # the first station run of this driver: `run_OCV` failed with
                # "channel 0 is busy" on a state the driver's own load had
                # just produced, one poll earlier. `BL_StartChannel` is the
                # authority on whether a channel can start, and it answers
                # with an error code `_checked` raises by name; easy-biologic
                # asked no such question for years of production runs.
                state = (status.data or {}).get(channel)
                try:
                    label = vendor.PROG_STATE(state).name
                except ValueError:
                    label = "unknown"
                LOGGER.warning(
                    f"channel {channel} reports state {state} ({label}), "
                    "not STOP; starting anyway"
                )

            plan = bt.plan_for(self._technique, self._params, ttl_params)
            # The only load of the run. `setup` deliberately sends nothing
            # (see its docstring): a second load arriving while the firmware
            # is still making the first is what broke every linked plan at a
            # station.
            self._load_plan(channel, plan, board_type)

            loaded = self._client.technique_ids(channel, len(plan.steps))
            if loaded != plan.tech_ids:
                raise RuntimeError(
                    f"loaded technique list {loaded} does not match the "
                    f"requested plan {plan.tech_ids}"
                )

            for message in self._client.drain_messages(channel):
                LOGGER.warning(f"channel {channel} technique message: {message}")

            # Only Trigger In parks the channel waiting on an external event
            # -- deliberately indefinite, unlike a firmware start failure
            # (sub-second) -- so only it lifts MAX_STARTING_POLLS. Trigger
            # Out (TECH_TO) pulses for its own finite Trigger_Duration and
            # returns; it waits on nothing, so the firmware-start-failure
            # detector must stay armed for it.
            waiting_on_trigger = (ttl_params or {}).get("ttl", "none") == "in"
            self._tracker = data.RunTracker(
                max_starting_polls=(
                    None if waiting_on_trigger else data.MAX_STARTING_POLLS
                )
            )
            self._logged_skipped = 0
            self._last_tech_index: Optional[int] = None
            start_time = time.time()
            self._client.start_channel(channel)
            return DriverResponse(
                response=DriverResponseType.success,
                message="measurement started",
                data={"start_time": start_time},
                status=DriverStatus.busy,
            )
        except Exception as exc:
            LOGGER.error("start_channel failed", exc_info=True)
            # Restores the old driver's cleanup-on-failed-start: without
            # this, self.channel/_technique/_tracker stay set from setup()
            # (plus the tracker pre-created above), so a subsequent get_data
            # believes a never-started channel is running and reports
            # "measuring" with no error -- a silent, empty success instead of
            # a failed action.
            self.channel = None
            self._technique = None
            self._params = {}
            self._tracker = None
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
                message=str(exc),
            )

    async def get_data(self, channel: int = 0) -> DriverResponse:
        """Pull the next data chunk from the claimed, running channel.

        Every vendor call runs on the client's single worker thread; the
        `run_in_executor` here is what keeps a slow `BL_GetData` from
        blocking this process's event loop -- and the HTTP/WS traffic
        sharing it -- at the 10 ms rate `BiologicExec` polls this.

        Returns:
            `DriverResponse` whose `data` is column-oriented and never
            ragged: every column in the claimed technique's `column_plan` is
            present on every call, NaN-filled where a segment did not carry
            it, alongside the `_`-prefixed `CurrentValues` fields (one value
            per row). `message` is `"measuring"` while running -- folding in
            the tracker's `"starting"` state -- or `"done"` once the
            technique has finished and its tail has been drained.
        """
        try:
            if self.channel is None or channel != self.channel:
                raise ValueError(f"channel {channel} has not been set up")
            client = self._client
            tracker = self._tracker
            technique = self._technique
            board_type = self.board_type
            if (
                client is None
                or tracker is None
                or technique is None
                or board_type is None
            ):
                raise ValueError(f"channel {channel} has not been started")

            loop = asyncio.get_running_loop()
            plan_columns = technique.column_plan
            combined: dict[str, list] = {col: [] for col in plan_columns}

            async def poll_once():
                values, info, records = await loop.run_in_executor(
                    None, client.get_data, channel
                )
                state = tracker.observe(values, info)
                decoded = data.decode(
                    _segment_name(info, technique),
                    info,
                    values,
                    records,
                    client.to_single,
                    client.to_seconds,
                    board_type,
                )
                index = int(getattr(info, "TechniqueIndex", 0) or 0)
                if index != self._last_tech_index:
                    # One line per technique boundary in a linked plan. This
                    # is the transition a single STOP sample used to be read
                    # as the end of the run.
                    LOGGER.info(
                        f"channel {channel}: technique index "
                        f"{self._last_tech_index} -> {index} (id "
                        f"{int(info.TechniqueID)}, process "
                        f"{int(info.ProcessIndex)}, state {int(values.State)})"
                    )
                    self._last_tech_index = index
                row_n = len(next(iter(decoded.values()), []))
                for col in plan_columns:
                    combined[col].extend(decoded.get(col, [float("nan")] * row_n))
                for field in vendor.CurrentValues._fields_:
                    name = field[0]
                    combined.setdefault(f"_{name}", []).extend(
                        [getattr(values, name)] * row_n
                    )
                return state, info

            state, info = await poll_once()
            if state == "error":
                # RunTracker gave up: the channel accepted BL_StartChannel
                # but never reached RUN (or STOP-with-rows) within its
                # bound -- report a fault rather than polling "measuring"
                # forever.
                raise RuntimeError(
                    f"channel {channel} never reached RUN within "
                    f"{tracker.max_starting_polls} polls"
                )
            if state == "done":
                while tracker.should_drain(info):
                    state, info = await poll_once()

            if tracker.skipped > self._logged_skipped:
                LOGGER.warning(
                    f"channel {channel}: {tracker.skipped} dropped points "
                    "(IRQskipped)"
                )
                self._logged_skipped = tracker.skipped

            done = state == "done"
            if done:
                LOGGER.info(
                    f"channel {channel}: done at technique index "
                    f"{int(getattr(info, 'TechniqueIndex', 0) or 0)} (id "
                    f"{int(info.TechniqueID)}), after "
                    f"{tracker.stop_polls_to_finish} polls reporting STOP"
                )
            return DriverResponse(
                response=DriverResponseType.success,
                message="done" if done else "measuring",
                data=combined,
                status=DriverStatus.ok if done else DriverStatus.busy,
            )
        except Exception as exc:
            LOGGER.error("get_data failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
                message=str(exc),
            )

    def stop(self, channel: Optional[int] = None) -> DriverResponse:
        """Stop the claimed channel, if any.

        `channel` is accepted for protocol parity with the other backends,
        but this driver holds one claim at a time -- there is no "all
        channels" sweep -- so the claimed channel is what actually gets
        stopped regardless of the value passed. A no-op success when
        nothing is claimed is what makes this safe to call from `stop_private`
        and `shutdown` unconditionally.
        """
        target = self.channel
        if target is None:
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.ok,
                message="nothing claimed",
            )
        try:
            if self._client is None:
                raise ConnectionError("device not connected")
            self._client.stop_channel(target)
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as exc:
            LOGGER.error("stop failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
                message=str(exc),
            )

    def cleanup(self, channel: int) -> DriverResponse:
        """Release the claim on `channel`, refusing while it is still running.

        EClib1 has no unload call, so a technique stays resident until the
        next `BL_LoadTechnique(first=True)` replaces it -- this clears the
        driver's own claim/technique/params/tracker, not the instrument's
        state.
        """
        try:
            if self.channel is None or channel != self.channel:
                raise ValueError(f"channel {channel} is not claimed")
            if self._client is not None:
                info = self._client.channel_info(channel)
                if info.State == vendor.PROG_STATE.RUN:
                    raise ValueError(f"channel {channel} is running; stop it first")
            self.channel = None
            self._technique = None
            self._params = {}
            self._tracker = None
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as exc:
            LOGGER.error("cleanup failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
                message=str(exc),
            )
