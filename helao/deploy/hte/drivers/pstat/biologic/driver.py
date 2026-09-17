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


def _kernel_loaded(ch: vendor.ChannelInfo) -> bool:
    """A channel with no firmware kernel loaded reports ``FirmwareCode == 0``.

    Same check as the vendor example's ``is_kernel_loaded`` property; kept
    here (not called from the example, which this repo does not vendor).
    """
    return ch.FirmwareCode != 0


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

            ch = client.channel_info(0)
            if self.force_load_firmware or not _kernel_loaded(ch):
                kernel, fpga = vendor.firmware_assets(self.board_type)
                client.load_firmware(0, kernel, fpga, force=self.force_load_firmware)

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
            data = {}
            for ch in channels:
                info = self._client.channel_info(ch)
                data[ch] = info.State
                for message in self._client.drain_messages(ch):
                    LOGGER.warning(f"channel {ch} firmware message: {message}")
            status = (
                DriverStatus.busy
                if any(state != vendor.PROG_STATE.STOP for state in data.values())
                else DriverStatus.ok
            )
            return DriverResponse(
                response=DriverResponseType.success, status=status, data=data
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
        for i, step in enumerate(plan.steps):
            ecc = vendor.ecc_file(step.ecc_stem, board_type)
            params = self._client.define_params(step.params)
            self._client.load_technique(
                channel,
                os.path.join(self.sdk_path, ecc),
                params,
                first=(i == 0),
                last=(i == len(plan.steps) - 1),
            )

    def setup(
        self,
        technique: Any,
        action_params: dict = {},
        output_dir: Optional[str] = None,
    ) -> DriverResponse:
        """Claim a channel and load its technique, without a trigger.

        Loading here -- rather than deferring everything to `start_channel`
        -- is what lets a bad technique build or a vendor rejection surface
        at setup time, before an action believes the channel is ready. The
        trigger is not known yet (it arrives with `start_channel`'s
        `ttl_params`), so `start_channel` rebuilds and reloads the plan from
        scratch once it does -- redundant against real firmware, but
        harmless, since `first=True` always replaces whatever is loaded.

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
            # Deliberate first load, without a trigger: the trigger is not
            # known until start_channel's ttl_params arrive, so this is a
            # validation load only. start_channel reloads with the real
            # ttl_params and BL_LoadTechnique(first=True) fully replaces
            # this list -- do not delete either load, the first is what
            # surfaces a bad technique/param here rather than at start.
            self._load_plan(channel, plan, board_type)
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
            if status.status == DriverStatus.busy:
                raise ValueError(f"channel {channel} is busy")
            if status.status == DriverStatus.error:
                raise ValueError(f"channel {channel} encountered an error")

            plan = bt.plan_for(self._technique, self._params, ttl_params)
            # Deliberate second load, this time with the real ttl_params:
            # setup()'s earlier load had none to build from. This supersedes
            # setup()'s load outright (BL_LoadTechnique(first=True) replaces
            # the whole list) -- do not delete this thinking setup()'s load
            # already covers it, or a requested trigger never gets loaded.
            self._load_plan(channel, plan, board_type)

            loaded = self._client.technique_ids(channel, len(plan.steps))
            if loaded != plan.tech_ids:
                raise RuntimeError(
                    f"loaded technique list {loaded} does not match the "
                    f"requested plan {plan.tech_ids}"
                )

            for message in self._client.drain_messages(channel):
                LOGGER.warning(f"channel {channel} technique message: {message}")

            self._tracker = data.RunTracker()
            self._logged_skipped = 0
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
