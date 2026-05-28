"""HelaoDriver wrapper around the easy-biologic package for Biologic potentiostats.

Wraps a multi-channel Biologic instrument behind the HelaoDriver contract,
delegating channel configuration and data retrieval to the easy-biologic
``BiologicDevice`` and ``BiologicProgram`` classes. The driver tracks per-channel
program objects, parameter dictionaries, and the active technique so that
setup, start, get_data, stop, and cleanup can be issued independently for each
channel of the device.

See https://github.com/bicarlsen/easy-biologic for the underlying library.
"""

import time
from typing import Optional

# save a default log file system temp
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
import numpy as np
import pandas as pd
import easy_biologic as ebl

from helao.core.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
)

from .technique import BiologicTechnique


# ctypes struct to dict (won't work with arrays, nested structs)
def getdict(struct) -> dict:
    """Convert a flat ``ctypes.Structure`` instance into a plain dict.

    Only handles top-level scalar fields; arrays and nested structs are not
    unpacked.

    Args:
        struct: A ``ctypes.Structure`` instance whose ``_fields_`` describes
            scalar fields.

    Returns:
        Mapping of field name to attribute value.
    """
    return dict((field, getattr(struct, field)) for field, _ in struct._fields_)


class BiologicDriver(HelaoDriver):
    """HelaoDriver implementation for a multi-channel Biologic potentiostat.

    Holds one easy-biologic ``BiologicProgram`` per channel and exposes
    setup/start/get_data/stop/cleanup methods scoped to a channel index. A
    single TCP connection to the instrument is established at construction
    time and reused for the lifetime of the driver.

    Attributes:
        device_name: Human-readable identifier for the connected instrument.
        connection_raised: Whether a connection attempt has been made; used to
            guard against double-open by another process.
    """

    device_name: str
    connection_raised: bool

    def __init__(self, config: dict = {}):
        """Initialize the driver and open the connection to the instrument.

        Args:
            config: Driver configuration. Recognized keys are ``address``
                (instrument IP, default ``"192.168.200.240"``) and
                ``num_channels`` (default ``12``).
        """
        super().__init__(config=config)
        #
        self.ready = False
        self.address = config.get("address", "192.168.200.240")
        self.num_channels = config.get("num_channels", 12)
        self.device_name = "unknown"
        self.pstat = None
        self.connection_raised = False
        self.channels = {i: None for i in range(self.num_channels)}
        self.channel_params = {i: {} for i in range(self.num_channels)}
        self.channel_technique = {i: None for i in range(self.num_channels)}
        self.connect()
        self.stopping = False
        self.connection_ctx = None

    def connect(self) -> DriverResponse:
        """Open the TCP connection to the Biologic instrument.

        Returns:
            ``DriverResponse`` with ``status=ok`` on success, ``status=busy``
            if another script holds the connection, otherwise ``status=error``.
        """
        try:
            if self.connection_raised:
                raise ConnectionError(
                    "Connection already raised. In use by another script."
                )
            self.connection_raised = True
            self.pstat = ebl.BiologicDevice(str(self.address))
            self.connection_ctx = self.pstat.connect()
            self.ready = True
            LOGGER.info(f"connected to {self.device_name} on device_id {self.address}")
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as exc:
            if "In use by another script" in exc.__str__():
                response = DriverResponse(
                    response=DriverResponseType.failed, status=DriverStatus.busy
                )
            else:
                LOGGER.error("get_status connection", exc_info=True)
                response = DriverResponse(
                    response=DriverResponseType.failed, status=DriverStatus.error
                )
        return response

    def get_status(self, channel: Optional[int] = None) -> DriverResponse:
        """Return the driver status, optionally for a single channel.

        Args:
            channel: Channel index to query. When ``None``, queries every
                channel and reports ``busy`` if any channel has a non-zero
                state.

        Returns:
            ``DriverResponse`` whose ``data`` maps channel index to the raw
            Biologic ``State`` value, and whose ``status`` reflects whether
            any queried channel is busy.
        """
        try:
            if not self.ready:
                # raise ConnectionError("Device not connected.")
                status = DriverStatus.uninitialized
                data = {}
            if channel is None:
                infos = [self.pstat.channel_info(i) for i in range(self.num_channels)]
                states = [x.State for x in infos]
                status = (
                    DriverStatus.busy
                    if any([x > 0 for x in states])
                    else DriverStatus.ok
                )
                
                data = {i: x for i, x in enumerate(states)}
            elif channel not in self.channels:
                status = DriverStatus.uninitialized
                data = {}
                # raise ValueError(f"Channel {channel} does not exist.")
            else:
                info = self.pstat.channel_info(channel)
                status = DriverStatus.busy if info.State > 0 else DriverStatus.ok
                data = {channel: info.State}
            response = DriverResponse(
                response=DriverResponseType.success,
                status=status,
                data=data,
            )
        except Exception:
            LOGGER.error("get_status failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def setup(
        self,
        technique: BiologicTechnique,
        action_params: dict = {},  # for mapping action keys to signal keys
    ) -> DriverResponse:
        """Configure a channel for an upcoming measurement.

        Translates action-server parameter keys into easy-biologic parameter
        names using ``technique.parameter_map``, wraps scalar values for the
        list-valued parameters (``voltages``, ``currents``, ``durations``),
        and instantiates ``technique.easy_class`` for the target channel.

        Args:
            technique: Technique definition specifying the easy-biologic
                program class and key remaps.
            action_params: Parameter dictionary supplied by the action server.
                Must include ``channel`` and the technique-specific keys
                listed in ``technique.parameter_map``.

        Returns:
            ``DriverResponse`` reporting setup success or failure.
        """
        channel = action_params.get("channel", -1)
        try:
            if channel not in self.channels:
                raise ValueError(f"Channel {channel} does not exist.")
            if self.channels[channel] is not None:
                raise ValueError(f"Channel {channel} is in use.")
            parmap = technique.parameter_map
            mapped_params = {
                parmap[k]: v for k, v in action_params.items() if k in parmap
            }
            listed = ["voltages", "currents", "durations"]
            listed_params = {
                k: [v] if k in listed else v for k, v in mapped_params.items()
            }
            self.channels[channel] = technique.easy_class(
                device=self.pstat, params=listed_params, channels=[channel]
            )
            self.channel_params[channel] = listed_params
            self.channel_technique[channel] = technique
            self.channels[channel].field_remap = technique.field_map
            response = DriverResponse(
                response=DriverResponseType.success,
                message="setup complete",
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("setup failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
            self.cleanup(channel)
        return response

    def list_techniques(self, channel: int = 0) -> list:
        """Return the list of techniques currently loaded on a channel.

        Args:
            channel: Channel index to inspect.

        Returns:
            List of ``(index, technique_payload)`` tuples as reported by the
            underlying easy-biologic device.

        Raises:
            ValueError: If the channel does not exist or has not been set up.
        """
        if channel not in self.channels:
            raise ValueError(f"Channel {channel} does not exist.")
        if self.channels[channel] is None:
            raise ValueError(f"Channel {channel} has not been set up.")
        techlist = [
            (i, tp) for i, tp in enumerate(self.channels[channel].device.__techniques)
        ]
        return techlist

    def update_parameters(self, channel: int = 0, new_params: dict = {}):
        """Merge ``new_params`` into the currently loaded technique on a channel.

        Translates action-server keys via the active technique's
        ``parameter_map``, wraps list-valued parameters, and pushes the
        combined parameter set down to the device.

        Args:
            channel: Channel index to update.
            new_params: Action-server parameter overrides.

        Raises:
            ValueError: If the channel does not exist or has not been set up.
        """
        if channel not in self.channels:
            raise ValueError(f"Channel {channel} does not exist.")
        if self.channels[channel] is None:
            raise ValueError(f"Channel {channel} has not been set up.")
        technique = self.channel_technique[channel]
        parmap = technique.parameter_map
        mapped_params = {parmap[k]: v for k, v in new_params.items() if k in parmap}
        listed = ["voltages", "currents", "durations"]
        listed_params = {k: [v] if k in listed else v for k, v in mapped_params.items()}
        techind, existing_tp = self.list_techniques(channel)[-1]
        existing_tech, existing_params = existing_tp
        updated_params = {**existing_params, **listed_params}
        self.channels[channel].device.update_params(
            ch=channel,
            technique=existing_tech,
            parameters=updated_params,
            index=techind,
            types=self.channels[channel]._parameter_types,
        )

    def start_channel(self, channel: int = 0, ttl_params: dict = {}) -> DriverResponse:
        """Start the previously configured technique on a channel.

        Args:
            channel: Channel index to start.
            ttl_params: TTL configuration forwarded to the easy-biologic
                program's ``run`` call.

        Returns:
            ``DriverResponse`` with ``status=busy`` and the wall-clock
            ``start_time`` in ``data`` on success.
        """
        try:
            if channel not in self.channels:
                raise ValueError(f"Channel {channel} does not exist.")
            if self.channels[channel] is None:
                raise ValueError(f"Channel {channel} has not been set up.")
            channel_state = self.get_status(channel=channel).status
            if channel_state == DriverStatus.busy:
                raise ValueError(f"Channel {channel} is busy.")
            if channel_state == DriverStatus.error:
                raise ValueError(f"Channel {channel} encountered error.")

            start_time = time.time()
            self.channels[channel].run(retrieve_data=False, ttl_params=ttl_params)

            response = DriverResponse(
                response=DriverResponseType.success,
                message="measurement started",
                data={"start_time": start_time},
                status=DriverStatus.busy,
            )
        except Exception:
            LOGGER.error("start_channel failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
            self.cleanup(channel)
        return response

    async def get_data(self, channel: int = 0) -> DriverResponse:
        """Retrieve buffered data from a running or just-finished channel.

        Pulls one data segment from the channel, drains any remaining
        segments once the channel reports ``done``, applies the technique's
        ``field_remap`` to rename data columns, and for impedance techniques
        derives ``X_ohm`` and ``R_ohm`` from ``modulus`` and ``phase``.

        Args:
            channel: Channel index to read.

        Returns:
            ``DriverResponse`` with column-oriented data in ``data`` and a
            ``measuring``/``done`` marker in ``message``.
        """
        try:
            if channel not in self.channels:
                raise ValueError(f"Channel {channel} does not exist.")
            if self.channels[channel] is None:
                raise ValueError(f"Channel {channel} has not been set up.")
            program = self.channels[channel]
            segment = await program._retrieve_data_segment(channel)
            if segment.values.State > 0:
                status = DriverStatus.busy
                program_state = "measuring"
            else:
                status = DriverStatus.ok
                program_state = "done"
            segment_data = segment.data
            segment_values = getdict(segment.values)
            values_list = []
            if segment_data:
                for _ in range(len(segment_data)):
                    values_list.append(segment_values)

            # empty buffer if program_state is done
            if program_state == "done":
                print("!!! retrieving last segment")
                latest_segment = await program._retrieve_data_segment(channel)
                while len(latest_segment.data) > 0:
                    segment_data += latest_segment.data
                    segment_values = getdict(latest_segment.values)
                    for _ in range(len(latest_segment.data)):
                        values_list.append(segment_values)
                    latest_segment = await program._retrieve_data_segment(channel)

            parsed = [
                program._fields(*program._field_values(datum, segment))
                for datum in segment_data
            ]

            data = pd.DataFrame(parsed).to_dict(orient="list")
            data = {program.field_remap[k]: v for k, v in data.items()}
            values = pd.DataFrame(values_list).to_dict(orient="list")
            values = {f"_{k}": v for k, v in values.items()}

            data.update(values)

            if "modulus" in data.keys():
                try:
                    data["X_ohm"] = (
                        -np.array(data["modulus"]) * np.sin(np.array(data["phase"]))
                    ).tolist()
                    data["R_ohm"] = (
                        np.array(data["modulus"]) * np.cos(np.array(data["phase"]))
                    ).tolist()
                except Exception:
                    LOGGER.warning(
                        "Unexpected value in modulus or phase data, unable to calculate X_ohm and R_ohm."
                    )
                    data["X_ohm"] = [np.nan] * len(data["modulus"])
                    data["R_ohm"] = [np.nan] * len(data["modulus"])

            response = DriverResponse(
                response=DriverResponseType.success,
                message=program_state,
                data=data,
                status=status,
            )
        except Exception:
            LOGGER.error("get_data failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
        return response

    def stop(self, channel: Optional[int] = None) -> DriverResponse:
        """Abort the active technique on one or all channels.

        Args:
            channel: Channel index to stop. When ``None``, every channel with
                an active program is stopped.

        Returns:
            ``DriverResponse`` reporting whether the stop call succeeded.
        """
        try:
            running_channels = [k for k, c in self.channels.items() if c is not None]
            if not self.stopping:
                self.stopping = True
                if channel is None and running_channels:
                    for ch in running_channels:
                        self.pstat.stop_channel(ch)
                elif channel in running_channels:
                    self.pstat.stop_channel(channel)
                elif channel not in self.channels:
                    LOGGER.warning(f"Channel {channel} does not exist.")
                else:
                    LOGGER.info(f"Channel {channel} is not running.")
                self.stopping = False
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("stop failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def cleanup(self, channel: int) -> DriverResponse:
        """Clear per-channel program, parameters, and technique state.

        Does not disconnect the instrument.

        Args:
            channel: Channel index to clean up.

        Returns:
            ``DriverResponse`` reporting cleanup status. Fails with
            ``status=error`` if the channel is currently busy.
        """
        try:
            if channel not in self.channels:
                raise ValueError(f"Channel {channel} does not exist.")
            channel_state = self.get_status(channel=channel).status
            if channel_state == DriverStatus.busy:
                raise ValueError(f"Channel {channel} is busy.")
            self.channels[channel] = None
            self.channel_params[channel] = {}
            self.channel_technique[channel] = None
            response = DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("cleanup failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
        finally:
            pass
        return response

    def disconnect(self) -> DriverResponse:
        """Close the TCP connection to the instrument and clear ready state."""
        try:
            self.pstat.disconnect()
            LOGGER.info(
                f"disconnected from {self.device_name} on device_id {self.address}"
            )
            self.pstat = None
            self.connection_ctx = None
            self.ready = False
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("disconnect failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        finally:
            self.connection_raised = False
        return response

    def reset(self) -> DriverResponse:
        """Disconnect then reconnect the driver to recover from a bad state."""
        try:
            self.disconnect()
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("reset error", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        finally:
            self.connect()
        return response

    def shutdown(self) -> None:
        """Stop any running channels, clean them up, and disconnect.

        Invoked by ``BaseAPI`` when the action server is shutting down.
        """
        state_dict = self.get_status().data
        running_channels = [ch for ch, state in state_dict.items() if state > 0]
        for ch in running_channels:
            self.stop(channel=ch)
            self.cleanup(channel=ch)
        self.disconnect()
