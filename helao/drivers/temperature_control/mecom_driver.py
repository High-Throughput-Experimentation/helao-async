__all__ = ["MeerstetterTEC", "TECExec"]

import time
import asyncio
import logging
from mecom import MeCom, ResponseException, WrongChecksum
from serial import SerialException

from helaocore.error import ErrorCodes
from helaocore.models.hlostatus import HloStatus
from helao.servers.base import Base, Executor

# default queries from command table below
DEFAULT_QUERIES = [
    "loop status",
    "object temperature",
    "target object temperature",
    "output current",
    "output voltage",
]

# syntax
# { display_name: [parameter_id, unit], }
COMMAND_TABLE = {
    "loop status": [1200, ""],
    "object temperature": [1000, "degC"],
    "target object temperature": [1010, "degC"],
    "output current": [1020, "A"],
    "output voltage": [1021, "V"],
    "sink temperature": [1001, "degC"],
    "ramp temperature": [1011, "degC"],
}


class MeerstetterTEC(object):
    """Controlling TEC devices via serial."""

    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.channel = self.config_dict["channel"]
        self.port = self.config_dict["port"]

        self.queries = self.config_dict["queries"]
        self._session = None
        self._connect()
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
        self._session = MeCom(serialport=self.port)
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

    async def poll_sensor_loop(self, frequency: int = 2):
        waittime = 1.0 / frequency
        self.base.print_message("Starting polling loop")
        while True:
            try:
                o2_level = self.inst.read_register(1, functioncode=4) * 10
            except minimalmodbus.NoResponseError as err:
                self.base.print_message(
                    f"NoResponseError: Driver polling rate is too fast. {err}"
                )
                continue
            except serial.SerialException as err:
                self.base.print_message(
                    f"Device {self.config_dict['device']} is in use. {err}"
                )
                continue
            if o2_level:
                msg_dict = {"o2_ppm": int(o2_level)}
                await self.base.put_lbuf(msg_dict)
            await asyncio.sleep(waittime)

    def shutdown(self):
        try:
            self.polling_task.cancel()
        except asyncio.CancelledError:
            self.base.print_message("closed sensor polling loop task")
        try:
            self.recording_task.cancel()
        except asyncio.CancelledError:
            self.base.print_message("closed sensor recording loop task")
        self.inst.serial.close()


class O2MonExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.active.base.print_message("O2MonExec initialized.")
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)

    async def _poll(self):
        """Read O2 ppm from live buffer."""
        live_dict = {}
        o2_ppm, epoch_s = self.active.base.get_lbuf("o2_ppm")
        live_dict["co2_ppm"] = o2_ppm
        live_dict["epoch_s"] = epoch_s
        iter_time = time.time()
        elapsed_time = iter_time - self.start_time
        if (self.duration < 0) or (elapsed_time < self.duration):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.001)

        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": live_dict,
        }


class O2MonExec(Executor):
    """O2 recording action written as an executor."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.active.base.print_message("O2MonExec initialized.")
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)

    async def _poll(self):
        """Read O2 ppm from live buffer."""
        live_dict = {}
        o2_ppm, epoch_s = self.active.base.get_lbuf("o2_ppm")
        live_dict["co2_ppm"] = o2_ppm
        live_dict["epoch_s"] = epoch_s
        iter_time = time.time()
        elapsed_time = iter_time - self.start_time
        if (self.duration < 0) or (elapsed_time < self.duration):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.001)

        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": live_dict,
        }
