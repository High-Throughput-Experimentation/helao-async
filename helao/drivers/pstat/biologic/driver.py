""" HelaoDriver wrapper around easy-biologic package for Biologic potentiostats

https://github.com/bicarlsen/easy-biologic

Notes:
- import easy_biologic as ebl
- import easy_biologic.base_programs as blp
- establish connection using `ebl.BiologicDevice('ip_address')`
- create technique using blp.OCV, blp.CP, etc. with set channels
- run technique using retrieve_data=False
- manually call _retrieve_data_segment to get single channel data

"""

import time
from typing import Optional

# save a default log file system temp
from helao.helpers import helao_logging as logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

import numpy as np
import pandas as pd
import easy_biologic as ebl

from helao.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
)

from .technique import BiologicTechnique


# ctypes struct to dict (won't work with arrays, nested structs)
def getdict(struct):
    return dict((field, getattr(struct, field)) for field, _ in struct._fields_)


class BiologicDriver(HelaoDriver):
    device_name: str
    connection_raised: bool

    def __init__(self, config: dict = {}):
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
        """Open connection to resource."""
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
        """Return current driver status."""
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
        """Set measurement conditions on potentiostat."""
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

    def list_techniques(self, channel: int = 0):
        if channel not in self.channels:
            raise ValueError(f"Channel {channel} does not exist.")
        if self.channels[channel] is None:
            raise ValueError(f"Channel {channel} has not been set up.")
        techlist = [
            (i, tp) for i, tp in enumerate(self.channels[channel].device.__techniques)
        ]
        return techlist

    def update_parameters(self, channel: int = 0, new_params: dict = {}):
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
        """Apply signal and begin data acquisition."""
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
        """Retrieve data from device buffer."""
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
            
            if 'modulus' in data.keys():
                try:
                    data["X_ohm"] = (-np.array(data['modulus']) * np.sin(np.array(data['phase']))).tolist()
                    data["R_ohm"] = (np.array(data['modulus']) * np.cos(np.array(data['phase']))).tolist()
                except Exception:
                    LOGGER.warning("Unexpected value in modulus or phase data, unable to calculate X_ohm and R_ohm.")
                    data["X_ohm"] = [np.nan] * len(data['modulus'])
                    data["R_ohm"] = [np.nan] * len(data['modulus'])

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
        """General stop method to abort all active methods e.g. motion, I/O, compute."""
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
        """Release state objects but don't close pstat."""
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
        """Release connection to resource."""
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
        """Reinitialize driver, force-close old connection if necessary."""
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
        """Pass-through shutdown events for BaseAPI."""
        state_dict = self.get_status().data
        running_channels = [ch for ch, state in state_dict.items() if state > 0]
        for ch in running_channels:
            self.stop(channel=ch)
            self.cleanup(channel=ch)
        self.disconnect()
