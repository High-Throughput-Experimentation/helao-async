"""``BiologicEclib2Driver`` -- a BioLogic driver over the EC-Lib 2.0 SDK.

Satisfies ``biologic_backend.BiologicBackend`` structurally, alongside the
eclib (easy-biologic) and olecom (EC-Lab OLE) backends, and is selected by
``pstat_backend: eclib2``. Two differences from the eclib backend are forced by
the SDK, and neither changes the protocol surface:

- ``get_data`` returns whole columns per poll rather than easy-biologic's
  segment objects, and carries no ``_``-prefixed live-value columns: the eclib
  driver copied a ``segment.values`` struct onto every row, which EClib2 has no
  equivalent of -- ``BL_GetLiveValues`` is a separate, non-popping call.
- ``start_channel`` accepts ``ttl_params`` and **refuses** an active TTL
  request rather than ignoring it. EClib2 has no TTL capability at all; see the
  note on :meth:`BiologicEclib2Driver.start_channel`.

Config keys (on the action server's ``params``):

``address``
    Instrument IP. Ethernet only -- EClib2 does not support USB.
``num_channels``
    Channels to expose, zero-based.
``sdk_path``
    Unpacked ``biologic_ec_sdk`` root. Required unless simulating.
``simulate``
    Use :mod:`sim` instead of the vendor SDK.
``timeout_s``
    ``BL_Connect`` communication timeout, seconds.
"""

import asyncio
import time
from typing import Any, Optional

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import data as ec2data
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import technique as ec2tech
from helao.deploy.hte.drivers.pstat.biologic_eclib2.sdk_client import (
    Eclib2Error,
    open_client,
)
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

DEFAULT_TIMEOUT_S = 120

#: Reported by ``get_status`` for a channel the config declares but the
#: instrument does not have a board in. Not a ``ChannelState`` member -- the SDK
#: has no such state, because it never gets asked about an absent channel.
NOT_PLUGGED = "not_plugged"

#: How many ``BL_DownloadRawData`` rounds one :meth:`get_data` call will make.
#: The instrument erases downloaded data to make room, so draining greedily is
#: right -- but unbounded draining would let a fast channel hold the call, and
#: the single SDK worker thread, forever.
MAX_DRAINS_PER_CALL = 64


class BiologicEclib2Driver(HelaoDriver):
    """BioLogic potentiostat driver over EC-Lib 2.0.

    Attributes:
        address: Instrument IP address.
        num_channels: Number of channels this driver exposes.
        device_name: Human-readable identifier, filled in on connect.
        ready: Whether a connection has been established.
    """

    def __init__(self, config: dict = {}):
        """Set up driver state. Performs no device I/O.

        The action server calls :meth:`connect` at startup; doing it here would
        make a construction failure indistinguishable from a config error, and
        the EClib1 backend was changed for the same reason.
        """
        super().__init__(config=config)
        self.address = config.get("address", "")
        self.num_channels = int(config.get("num_channels", 1))
        self.sdk_path = config.get("sdk_path")
        self.simulate = bool(config.get("simulate", False))
        self.timeout_s = int(config.get("timeout_s", DEFAULT_TIMEOUT_S))

        self.device_name = "unknown"
        self.ready = False
        self.stopping = False
        self._client = None
        # Per-channel: the technique name and params last set up, and the
        # accumulated column table for the action in flight.
        self.channel_technique: dict[int, Optional[str]] = {
            i: None for i in range(self.num_channels)
        }
        self.channel_params: dict[int, dict] = {i: {} for i in range(self.num_channels)}
        self._done: dict[int, bool] = {i: False for i in range(self.num_channels)}
        # Filled in by connect() from the instrument's own DeviceInfo.
        self.plugged_channels: list[int] = []
        self.usable_channels: list[int] = []
        self.missing_channels: list[int] = []

    # -- lifecycle ---------------------------------------------------------

    def connect(self) -> DriverResponse:
        """Open the connection and load firmware on every exposed channel.

        Firmware loading is part of connecting because an EClib2 channel with
        no firmware accepts an experiment and then fails at acquisition, which
        reads as a bad technique rather than an unprepared channel.
        """
        try:
            if self._client is None:
                self._client = open_client(
                    simulate=self.simulate, sdk_path=self.sdk_path
                )
            info = self._client.connect(self.address, self.timeout_s)

            # `channels_plugged` is the instrument's own account of which
            # channel boards exist. A configured channel that is not plugged
            # must neither fail the whole connection -- one empty slot would
            # take the server down -- nor be passed over in silence, since a
            # station would then see actions fail later with no reason given.
            plugged = [
                index
                for index, present in enumerate(getattr(info, "channels_plugged", []))
                if present
            ]
            self.plugged_channels = plugged
            configured = list(range(self.num_channels))
            self.usable_channels = [c for c in configured if c in plugged]
            self.missing_channels = [c for c in configured if c not in plugged]
            if self.missing_channels:
                LOGGER.warning(
                    "eclib2 %s: configured channels %s are not plugged "
                    "(instrument reports %s); they will report not_plugged",
                    self.address,
                    self.missing_channels,
                    plugged,
                )
            if not self.usable_channels:
                raise ConnectionError(
                    f"none of the configured channels {configured} are plugged; "
                    f"instrument reports {plugged}"
                )

            for channel in self.usable_channels:
                self._client.load_firmware(channel)

            self.device_name = (
                f"device_code={getattr(info, 'device_code', '?')} "
                f"serial={getattr(info, 'serial_number', '?')}"
            )
            self.ready = True
            LOGGER.info("eclib2 connected to %s at %s", self.device_name, self.address)
            return DriverResponse(
                response=DriverResponseType.success,
                message=self.device_name,
                data={
                    "address": self.address,
                    "channels": self.num_channels,
                    "usable_channels": list(self.usable_channels),
                    "missing_channels": list(self.missing_channels),
                },
                status=DriverStatus.ok,
            )
        except Exception as exc:
            LOGGER.error("eclib2 connect failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    def get_status(self, channel: Optional[int] = None) -> DriverResponse:
        """Report per-channel running state.

        Args:
            channel: Channel to query, or None for every channel.

        Returns:
            ``DriverResponse`` whose ``data`` maps channel index to the
            ``ChannelState`` member *name*, and whose ``status`` is ``busy`` if
            any queried channel is running.
        """
        try:
            if not self.ready or self._client is None:
                return DriverResponse(
                    response=DriverResponseType.success,
                    status=DriverStatus.uninitialized,
                    data={},
                )
            channels = range(self.num_channels) if channel is None else [channel]
            if channel is not None and channel not in self.channel_technique:
                return DriverResponse(
                    response=DriverResponseType.success,
                    message=f"channel {channel} does not exist",
                    status=DriverStatus.uninitialized,
                    data={},
                )
            data = {}
            busy = False
            for index in channels:
                if index not in self.usable_channels:
                    # Configured but not plugged. Reported rather than raised,
                    # so one empty slot does not make the whole status call
                    # fail and hide the channels that do work.
                    data[index] = NOT_PLUGGED
                    continue
                values = self._client.live_values(index)
                state = getattr(values.channel_state, "name", "unknown")
                data[index] = state
                busy = busy or state == "EC_SDK_CHANNEL_STATE_RUNNING"
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.busy if busy else DriverStatus.ok,
                data=data,
            )
        except Exception as exc:
            LOGGER.error("eclib2 get_status failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    def disconnect(self) -> DriverResponse:
        """Close the instrument connection and clear ready state."""
        try:
            if self._client is not None:
                self._client.disconnect()
            self.ready = False
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as exc:
            LOGGER.error("eclib2 disconnect failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )
        finally:
            self.ready = False

    def reset(self) -> DriverResponse:
        """Disconnect and reconnect, to recover from a bad state."""
        self.disconnect()
        return self.connect()

    def shutdown(self) -> None:
        """Stop every running channel, clean up, disconnect, stop the worker.

        Called by ``BaseAPI`` at server exit. Returns None, matching the
        ``BiologicBackend`` protocol and both sibling backends. Stopping the
        worker thread is the last step and is not recoverable, which is why
        this is separate from :meth:`disconnect`.
        """
        try:
            states = self.get_status().data
            for channel, state in states.items():
                if state == "EC_SDK_CHANNEL_STATE_RUNNING":
                    self.stop(channel=channel)
                    self.cleanup(channel=channel)
        except Exception:
            LOGGER.error("eclib2 shutdown could not quiesce channels", exc_info=True)
        finally:
            self.disconnect()
            if self._client is not None:
                self._client.close()
                self._client = None

    # -- setup and run -----------------------------------------------------

    def setup(
        self,
        technique: ec2tech.Eclib2Technique,
        action_params: dict = {},
        output_dir: Optional[str] = None,
    ) -> DriverResponse:
        """Build and load the experiment for a technique on a channel.

        Signature matches the ``BiologicBackend`` protocol: the channel comes
        from ``action_params["channel"]``, as it does for both sibling
        backends, because ``BiologicExec`` reads it from there too.

        Args:
            technique: Registry entry from :func:`~.technique.resolve`.
            action_params: Action parameters, keyed as the eclib backend keys
                them, including ``channel``.
            output_dir: Accepted for protocol compatibility and unused. The OLE
                backend needs it because EC-Lab writes files into the record
                directory; EClib2 returns its data over the wire, so this
                backend writes nothing of its own.

        Returns:
            ``DriverResponse`` whose ``data`` reports the techniques the plan
            expanded to and the columns the action will emit.
        """
        channel = action_params.get("channel", -1)
        try:
            self._require_usable_channel(channel)
            if not self.ready or self._client is None:
                raise ConnectionError("device not connected")
            if self._client.is_running(channel):
                raise ValueError(f"channel {channel} is busy")

            plan = technique.plan(action_params)
            self._client.apply_plan(channel, plan)
            self.channel_technique[channel] = technique.technique_name
            self.channel_params[channel] = dict(action_params)
            self._done[channel] = False
            return DriverResponse(
                response=DriverResponseType.success,
                message=f"{technique.technique_name} loaded on channel {channel}",
                data={
                    "technique": technique.technique_name,
                    "techniques": [t.identifier for t in plan.techniques],
                    "columns": list(plan.columns),
                },
                status=DriverStatus.ok,
            )
        except Exception as exc:
            LOGGER.error("eclib2 setup failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    def start_channel(
        self, channel: int = 0, ttl_params: Optional[dict] = None
    ) -> DriverResponse:
        """Start the loaded experiment on a channel.

        **A TTL request is refused, not ignored.** EClib2 exposes no TTL or
        digital-output capability whatsoever -- no such call in its 53-function
        API, and no mention in its headers or documentation. The eclib backend
        passes TTL to easy-biologic and the OLE backend writes trigger
        techniques into the ``.mps``; this backend can do neither. Accepting
        the parameter and quietly dropping it would leave a station believing
        it was triggering an instrument that never fires, so an *active*
        request fails the action. The executor's default (``ttl="none"``) is
        what every non-triggered action sends, and passes through.
        """
        requested = (ttl_params or {}).get("ttl", "none")
        if requested not in ("none", None):
            message = (
                f"eclib2 cannot honour ttl={requested!r}: the EC-Lib 2.0 SDK has "
                "no TTL or digital-output capability. Use the eclib or olecom "
                "backend for hardware triggering."
            )
            LOGGER.error(message)
            return DriverResponse(
                response=DriverResponseType.not_implemented,
                message=message,
                status=DriverStatus.error,
            )
        try:
            self._require_usable_channel(channel)
            if not self.ready or self._client is None:
                raise ConnectionError("device not connected")
            if self.channel_technique[channel] is None:
                raise ValueError(f"channel {channel} has not been set up")
            if self._client.is_running(channel):
                raise ValueError(f"channel {channel} is busy")

            start_time = time.time()
            self._client.start(channel)
            self._done[channel] = False
            return DriverResponse(
                response=DriverResponseType.success,
                message="measurement started",
                data={"start_time": start_time},
                status=DriverStatus.busy,
            )
        except Exception as exc:
            LOGGER.error("eclib2 start_channel failed", exc_info=True)
            self.cleanup(channel)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    async def get_data(self, channel: int = 0) -> DriverResponse:
        """Drain what the instrument has produced since the last call.

        Every available buffer is drained in one call, not just one, because
        the instrument erases downloaded data to make room and warns that this
        must be called "sufficiently often for the memory of the instrument not
        to get full".

        Returns:
            ``DriverResponse`` with column-oriented data and a
            ``measuring``/``done`` marker in ``message``. An empty table while
            still measuring is the normal "nothing yet" state, not a failure.
        """
        try:
            self._require_usable_channel(channel)
            if not self.ready or self._client is None:
                raise ConnectionError("device not connected")
            plan = self._client.plan_for(channel)
            if plan is None:
                raise ValueError(f"channel {channel} has not been set up")

            table: dict[str, list] = {c: [] for c in plan.columns}
            running = True
            truncated = False
            for _ in range(MAX_DRAINS_PER_CALL):
                result = await asyncio.to_thread(self._client.poll, channel)
                running = result.running
                if result.rows:
                    for column, values in result.table.items():
                        table[column].extend(values)
                # An empty buffer means nothing more is waiting right now,
                # whether or not the channel is still running.
                if result.rows == 0:
                    break
            else:
                # Bounded rather than "drain until empty": a channel producing
                # rows faster than we read would otherwise hold this call, and
                # the SDK worker thread, indefinitely. The remainder is not
                # lost -- BL_DownloadRawData is a FIFO, so the next call
                # continues where this one stopped.
                truncated = True
                LOGGER.warning(
                    "eclib2 channel %s still had data after %s downloads; "
                    "returning early and continuing on the next call",
                    channel,
                    MAX_DRAINS_PER_CALL,
                )

            done = not running and not truncated
            self._done[channel] = done
            return DriverResponse(
                response=DriverResponseType.success,
                message="done" if done else "measuring",
                data=table,
                status=DriverStatus.ok if done else DriverStatus.busy,
            )
        except Exception as exc:
            LOGGER.error("eclib2 get_data failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    def stop(self, channel: Optional[int] = None) -> DriverResponse:
        """Abort the active technique on one or all channels."""
        try:
            if not self.ready or self._client is None:
                return DriverResponse(
                    response=DriverResponseType.success,
                    status=DriverStatus.uninitialized,
                )
            if self.stopping:
                return DriverResponse(
                    response=DriverResponseType.success,
                    message="already stopping",
                    status=DriverStatus.ok,
                )
            self.stopping = True
            try:
                channels = (
                    [
                        index
                        for index, name in self.channel_technique.items()
                        if name is not None
                    ]
                    if channel is None
                    else [channel]
                )
                for index in channels:
                    if index not in self.channel_technique:
                        LOGGER.warning("eclib2 channel %s does not exist", index)
                        continue
                    self._client.stop(index)
            finally:
                self.stopping = False
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as exc:
            LOGGER.error("eclib2 stop failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    def cleanup(self, channel: int = 0) -> DriverResponse:
        """Clear per-channel plan and parameters, without disconnecting."""
        try:
            self._require_channel(channel)
            # A channel with no board cannot be running and has nothing loaded,
            # so it is cleared locally rather than probed -- otherwise
            # per-channel state set before connecting could never be cleared.
            if (
                self._client is not None
                and self.ready
                and channel in self.usable_channels
            ):
                if self._client.is_running(channel):
                    raise ValueError(f"channel {channel} is busy")
                self._client.clear(channel)
            self.channel_technique[channel] = None
            self.channel_params[channel] = {}
            self._done[channel] = False
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as exc:
            LOGGER.error("eclib2 cleanup failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    # -- introspection and modify-on-the-fly -------------------------------

    def list_techniques(self, channel: int = 0) -> list:
        """The techniques currently loaded on a channel, in execution order."""
        if self._client is None:
            return []
        plan = self._client.plan_for(channel)
        if plan is None:
            return []
        return [(i, t.identifier) for i, t in enumerate(plan.techniques)]

    def update_parameters(
        self, channel: int = 0, new_params: dict = {}
    ) -> DriverResponse:
        """Rebuild and reload the experiment with changed parameters.

        EClib2 does have true modify-on-the-fly (``BL_Update*Parameter`` plus
        ``BL_UpdateExperiment``), and most technique parameters are flagged MOF
        in the docs. It is deliberately not used here: MOF updates one named
        parameter on one technique handle, while a HELAO ``update_parameters``
        call hands over a whole parameter dict whose plan may differ in step
        count -- which changes how many array entries every step parameter
        needs, something no per-parameter update expresses. Rebuilding is
        correct for any input; wiring MOF is a later, narrower change.

        Refuses while the channel is running, since reloading an experiment
        under a live acquisition would silently discard it.
        """
        try:
            self._require_channel(channel)
            if not self.ready or self._client is None:
                raise ConnectionError("device not connected")
            technique_name = self.channel_technique[channel]
            if technique_name is None:
                raise ValueError(f"channel {channel} has not been set up")
            if self._client.is_running(channel):
                raise ValueError(
                    f"channel {channel} is running; stop it before changing parameters"
                )
            merged = {
                **self.channel_params[channel],
                **new_params,
                # setup() reads the channel from the params, so a caller that
                # passed only changed values must not lose it.
                "channel": channel,
            }
            return self.setup(
                technique=ec2tech.resolve(technique_name), action_params=merged
            )
        except Exception as exc:
            LOGGER.error("eclib2 update_parameters failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    def emitted_columns(self, technique_name: str) -> tuple[str, ...]:
        """Columns a technique emits, without needing a device.

        Lets the column contract be checked against the eclib backend
        statically.
        """
        return ec2tech.COLUMNS_BY_TECHNIQUE[technique_name]

    # -- helpers -----------------------------------------------------------

    def _require_channel(self, channel: int) -> None:
        if channel not in self.channel_technique:
            raise ValueError(f"channel {channel} does not exist")

    def _require_usable_channel(self, channel: int) -> None:
        """As :meth:`_require_channel`, and the instrument must have the board.

        Separate because "not in the config" and "configured but no board
        fitted" need different fixes, and a single message for both sends a
        station looking in the wrong place.
        """
        self._require_channel(channel)
        if self.ready and channel not in self.usable_channels:
            raise ValueError(
                f"channel {channel} is not plugged; instrument reports "
                f"{self.plugged_channels}"
            )

    def __repr__(self) -> str:
        mode = "simulated" if self.simulate else "eclib2"
        return (
            f"<BiologicEclib2Driver {mode} address={self.address!r} "
            f"channels={self.num_channels} ready={self.ready}>"
        )
