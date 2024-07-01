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
from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(logger_name="biologic_driver_standalone")
else:
    LOGGER = logging.LOGGER

import pandas as pd
import easy_biologic as ebl

from helao.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
)

from .technique import BiologicTechnique


class BiologicDriver(HelaoDriver):
    device_name: str
    connection_raised: bool

    def __init__(self, config: dict = {}):
        super().__init__(config=config)
        #
        self.address = config.get(key="address", default="192.168.200.240")
        self.num_channels = config.get(key="num_channels", default=12)
        self.device_name = "unknown"
        self.connection_raised = False
        self.pstat = ebl.BiologicDevice(self.address)
        self.channels = {i: None for i in range(self.num_channels)}
        self.connect()

    def connect(self) -> DriverResponse:
        """Open connection to resource."""
        try:
            if self.connection_raised:
                raise ConnectionError(
                    "Connection already raised. In use by another script."
                )
            self.connection_raised = True
            self.pstat.connect()
            self.ready = True
            LOGGER.debug(f"connected to {self.device_name} on device_id {self.address}")
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
            if channel is None:
                infos = [self.pstat.channel_info(i) for i in range(self.num_channels)]
                states = [x.State for x in infos]
                status = (
                    DriverStatus.busy
                    if any([x > 0 for x in states])
                    else DriverStatus.ok
                )
            elif channel not in self.channels:
                raise ValueError(f"Channel {channel} does not exist.")
            else:
                info = self.pstat.channel_info(channel)
                status = DriverStatus.busy if info.State > 0 else DriverStatus.ok
            response = DriverResponse(
                response=DriverResponseType.success,
                status=status,
                data={i: s for i, s in enumerate(states)},
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
        try:
            channel = action_params.get("channel", -1)
            if channel not in self.channels:
                raise ValueError(f"Channel {channel} does not exist.")
            if self.channels[channel] is not None:
                raise ValueError(f"Channel {channel} is in use.")
            parmap = technique.parameter_map
            mapped_params = {
                parmap[k]: v for k, v in action_params.items() if k in parmap
            }
            self.channels[channel] = technique.easy_class(
                device=self.pstat, params=mapped_params, channels=[channel]
            )
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
            self.cleanup()
        return response

    def start_channel(self, channel: int = 0) -> DriverResponse:
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
            self.channels[channel].run(retrieve_data=False)

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
            self.cleanup()
        return response

    def get_data(self, channel: int = 0) -> DriverResponse:
        """Retrieve data from device buffer."""
        try:
            if channel not in self.channels:
                raise ValueError(f"Channel {channel} does not exist.")
            if self.channels[channel] is None:
                raise ValueError(f"Channel {channel} has not been set up.")
            program = self.channels[channel]
            segment = program._retrieve_data_segment(channel)
            if segment.values.State > 0:
                status = DriverStatus.busy
                program_state = "measuring"
            else:
                status = DriverStatus.ok
                program_state = "done"
            segment_data = segment.data

            # empty buffer if program_state is done
            if program_state == "done":
                latest_segment = program._retrieve_data_segment(channel)
                while len(latest_segment.data) > 0:
                    segment_data += latest_segment.data
                    program._retrieve_data_segment(channel)

            parsed = [
                program._fields(*program._field_values(datum, segment))
                for datum in segment_data
            ]
            data = pd.DataFrame(parsed).to_dict(orient="list")
            data = {program.field_remap[k]: v for k, v in data.items()}

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
            if channel is None:
                for ch in running_channels:
                    self.pstat.stop_channel(ch)
            elif channel in running_channels:
                self.pstat.stop_channel(channel)
            elif channel not in self.channels:
                raise ValueError(f"Channel {channel} does not exist.")
            else:
                raise ValueError(f"Channel {channel} is not running.")
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
            self.pstat = None
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
