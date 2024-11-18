__all__ = ["MeerstetterTEC", "TECMonExec", "TECWaitExec"]

import time
import asyncio
import logging
from mecom import MeCom, ResponseException, WrongChecksum
from mecom.exceptions import ResponseTimeout

from helao.helpers import logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER
from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.servers.base import Base
from helao.helpers.executor import Executor

# default queries from command table below
DEFAULT_QUERIES = [
    "enabled_status",
    "object_temperature",
    "target_object_temperature",
    "output_current",
    "temperature_is_stable",
]

# syntax
# { display_name: [parameter_id, unit], }
COMMAND_TABLE = {
    "device_status": [104, ""],
    "enabled_status": [2010, ""],
    "temperature_is_stable": [1200, ""],
    "object_temperature": [1000, "degC"],
    "target_object_temperature": [1010, "degC"],
    "output_current": [1020, "A"],
    "output_voltage": [1021, "V"],
    "sink_temperature": [1001, "degC"],
    "ramp_temperature": [1011, "degC"],
}


class MeerstetterTEC(object):
    """Controlling TEC devices via serial."""

    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.channel = self.config_dict["channel"]
        self.port = self.config_dict["port"]
        connection_retries = self.config_dict.get("retries", 15)

        self.queries = self.config_dict.get("queries", DEFAULT_QUERIES)
        self._session = None

        for i in range(connection_retries):
            try:
                self._connect()
                break
            except ResponseTimeout:
                LOGGER.info(f"connection timeout, retrying attempt {i+1}")
        self.action = None
        self.active = None
        self.start_margin = self.config_dict.get("start_margin", 0)
        self.start_time = 0
        self.last_rec_time = 0
        self.event_loop = asyncio.get_event_loop()
        self.recording_duration = 0
        self.recording_rate = 0.1  # seconds per acquisition
        self.allow_no_sample = self.config_dict.get("allow_no_sample", True)
        self.polling_task = self.event_loop.create_task(self.poll_sensor_loop())

    def _tearDown(self):
        self.session().stop()

    def _connect(self):
        # open session
        self._session = MeCom(serialport=self.port, timeout=1)
        # get device address
        self.address = self._session.identify()
        logging.info("connected to {}".format(self.address))

    def session(self):
        if self._session is None:
            self._connect()
        return self._session

    def get_data(self):
        data = {}
        for description in self.queries:
            cid, unit = COMMAND_TABLE[description]
            try:
                value = self.session().get_parameter(
                    parameter_id=cid,
                    address=self.address,
                    parameter_instance=self.channel,
                )
                data.update({description: (value, unit)})
            except (ResponseException, WrongChecksum) as ex:
                self.session().stop()
                self._session = None
        return data

    def set_temp(self, value):
        """
        Set object temperature of channel to desired value.
        :param value: float
        :param channel: int
        :return:
        """
        # assertion to explicitly enter floats
        assert type(value) is float
        logging.info(
            "set object temperature for channel {} to {} C".format(self.channel, value)
        )
        return self.session().set_parameter(
            parameter_id=3000,
            value=value,
            address=self.address,
            parameter_instance=self.channel,
        )

    def _set_enable(self, enable=True):
        """
        Enable or disable control loop
        :param enable: bool
        :param channel: int
        :return:
        """
        value, description = (1, "on") if enable else (0, "off")
        logging.info("set loop for channel {} to {}".format(self.channel, description))
        return self.session().set_parameter(
            value=value,
            parameter_name="Status",
            address=self.address,
            parameter_instance=self.channel,
        )

    def enable(self):
        return self._set_enable(True)

    def disable(self):
        return self._set_enable(False)

    async def poll_sensor_loop(self, frequency: int = 1):
        waittime = 1.0 / frequency
        LOGGER.info("Starting polling loop")
        while True:
            tec_vals = {k: v[0] for k, v in self.get_data().items()}
            if tec_vals:
                msg_dict = {"tec_vals": tec_vals}
                await self.base.put_lbuf(msg_dict)
            await asyncio.sleep(waittime)

    def shutdown(self):
        try:
            self.polling_task.cancel()
        except asyncio.CancelledError:
            LOGGER.info("closed TEC polling loop task")
        self.disable()


class TECMonExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        LOGGER.info("TECMonExec initialized.")
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)

    async def _poll(self):
        """Read TEC values from live buffer."""
        live_dict = {}
        tec_vals, epoch_s = self.active.base.get_lbuf("tec_vals")
        live_dict["epoch_s"] = epoch_s
        for k, v in tec_vals.items():
            live_dict[k] = v
        iter_time = time.time()
        elapsed_time = iter_time - self.start_time
        if (self.duration < 0) or (elapsed_time < self.duration):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.01)

        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": live_dict,
        }


STABLE_ID_MAP = {
    0: "Temperature regulation not active.",
    1: "Temperature is not stable.",
    2: "Temperature is stable.",
}


class TECWaitExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        LOGGER.info("TECWaitExec initialized.")
        self.start_time = time.time()
        self.duration = -1
        self.last_check = 0
        self.initial_sleep = 2

    async def _pre_exec(self):
        "Setup methods, return error state."
        LOGGER.info(f"TECWait Executor sleeping for {self.initial_sleep} seconds.")
        await asyncio.sleep(self.initial_sleep)
        self.setup_err = ErrorCodes.none
        return {"error": self.setup_err}

    async def _poll(self):
        """Read TEC values from live buffer."""
        live_dict = {}
        tec_vals, epoch_s = self.active.base.get_lbuf("tec_vals")
        live_dict["epoch_s"] = epoch_s
        for k, v in tec_vals.items():
            live_dict[k] = v
        stable_id = live_dict["temperature_is_stable"]
        if stable_id != 2:
            status = HloStatus.active
            if epoch_s - self.last_check > 5:
                stab_msg = STABLE_ID_MAP.get(stable_id, "temperature state is unknown")
                self.active.base.print_message(stab_msg)
                self.last_check = epoch_s
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.01)

        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": live_dict,
        }
