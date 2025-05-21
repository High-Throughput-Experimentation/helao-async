""" A device class for the SprintIR-6S CO2 sensor.

"""

__all__ = []

import re
import time
import asyncio

import serial

from helao.helpers import helao_logging as logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

from helao.core.error import ErrorCodes
from helao.servers.base import Base
from helao.helpers.executor import Executor
from helao.core.models.data import DataModel
from helao.core.models.file import FileConnParams, HloHeaderModel
from helao.core.models.sample import SampleInheritance, SampleStatus
from helao.core.models.hlostatus import HloStatus
from helao.helpers.premodels import Action
from helao.helpers.active_params import ActiveParams
from helao.helpers.sample_api import UnifiedSampleDataAPI


""" Notes:

Setup polling task to populate base.live_buffer dictionary, record CO2 action will read
from dictionary.

TODO: send CO2 reading to bokeh visualizer w/o writing data

"""


class SprintIR:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.unified_db = UnifiedSampleDataAPI(self.base)

        self.bokehapp = None

        # read pump addr and strings from config dict
        self.com = serial.Serial(
            port=self.config_dict["port"],
            baudrate=9600,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.5,
            xonxoff=False,
            rtscts=False,
        )

        # set POLL and flush present buffer until empty
        LOGGER.info("Setting sensor to polling mode.")
        self.com.write(b"K 2\r\n")
        # self.send("K 2")
        self.send("! 0")
        self.send("Y")
        self.send("! 0")
        self.send("Y")
        self.send("! 0")
        self.send("Y")

        # self.com.write(b"K 2\r\n")
        # self.com.flush()
        # buf = self.com.read_all()
        # while not buf == b"":
        #     buf = self.com.read_all()

        fw_map = [
            ("scaling_factor", "."),
            ("init_co2_filtered", "Z"),
            # ("zero-point_air", "G"),
            # ("undocumented_t", "t"),
            # ("undocumented_y", "y"),
            # ("pressure", "B"),
            # ("humidity", "H"),
            # ("zero-point_n2", "U"),
            # ("pc_compensation", "s"),
            # ("digital_filter_value", "a"),
        ]
        ifw_map = {v: k for k, v in fw_map}
        self.fw = {}
        LOGGER.info("Reading scaling factor and initial co2 ppm.")
        for k, v in fw_map:
            LOGGER.info(f"checking {k}")
            resp, aux = self.send(v)
            if resp:
                fw_val = resp[0].split()[-1].replace(v, "").strip()
                if fw_val not in ["?", ""]:
                    self.fw[k] = int(fw_val)
            for aresp in aux:
                cmd = aresp[0]
                if cmd in ifw_map.keys():
                    fw_val = aresp.split()[-1].replace(cmd, "").strip()
                    self.fw[ifw_map[cmd]] = int(fw_val)
            time.sleep(0.1)

        # set streaming mode before starting async task
        LOGGER.info("Setting sensor to polling mode.")
        self.com.write(b"K 2\r\n")

        self.action = None
        self.active = None
        self.start_margin = self.config_dict.get("start_margin", 0)
        self.start_time = 0
        self.last_rec_time = 0
        self.IO_signalq = asyncio.Queue(1)
        self.IO_do_meas = False  # signal flag for intent (start/stop)
        self.IO_measuring = False  # status flag of measurement
        self.event_loop = asyncio.get_event_loop()
        self.recording_duration = 0
        self.recording_rate = 0.1  # seconds per acquisition

        self.unified_db = UnifiedSampleDataAPI(self.base)
        asyncio.gather(self.unified_db.init_db())
        self.allow_no_sample = self.config_dict.get("allow_no_sample", True)

        # for saving data localy
        self.FIFO_epoch = None
        self.FIFO_header = {}  # measuement specific, will be reset each measurement
        self.FIFO_column_headings = []
        self.FIFO_name = ""

        # signals return to endpoint after active was created
        self.IO_continue = False
        self.IOloop_run = False

        self.polling_task = self.event_loop.create_task(self.poll_sensor_loop())
        self.recording_task = self.event_loop.create_task(self.IOloop())

    def set_IO_signalq_nowait(self, val: bool) -> None:
        if self.IO_signalq.full():
            _ = self.IO_signalq.get_nowait()
        self.IO_signalq.put_nowait(val)

    async def set_IO_signalq(self, val: bool) -> None:
        if self.IO_signalq.full():
            _ = await self.IO_signalq.get()
        await self.IO_signalq.put(val)

    async def IOloop(self):
        """This is trigger-acquire-read loop which always runs."""
        self.IOloop_run = True
        try:
            while self.IOloop_run:
                self.IO_do_meas = await self.IO_signalq.get()
                if self.IO_do_meas:
                    # are we in estop?
                    if not self.base.actionservermodel.estop:
                        LOGGER.info("CO2-sense got measurement request")
                        try:
                            await asyncio.wait_for(
                                self.continuous_record(),
                                self.recording_duration + self.start_margin,
                            )
                        except asyncio.exceptions.TimeoutError:
                            pass
                        if self.base.actionservermodel.estop:
                            self.IO_do_meas = False
                            LOGGER.error("CO2-sense is in estop after measurement.")
                        else:
                            LOGGER.info("setting CO2-sense to idle")
                            # await self.stat.set_idle()
                        LOGGER.info("CO2 measurement is done")
                    else:
                        self.active.action.action_status.append(HloStatus.estopped)
                        self.IO_do_meas = False
                        LOGGER.error("CO2-sense is in estop.")

                # endpoint can return even we got errors
                self.IO_continue = True

                if self.active:
                    LOGGER.info("CO2-sense finishes active action")
                    active_not_finished = True
                    while active_not_finished:
                        try:
                            await asyncio.wait_for(self.active.finish(), 1)
                            active_not_finished = False
                        except asyncio.exceptions.TimeoutError:
                            pass
                    self.active = None
                    self.action = None
                    self.samples_in = []

        except asyncio.CancelledError:
            # endpoint can return even we got errors
            self.IO_continue = True
            LOGGER.info("IOloop task was cancelled")

    def send(self, command_str: str):
        if not command_str.endswith("\r\n"):
            command_str = command_str + "\r\n"
        self.com.write(command_str.encode("utf8"))
        self.com.flush()
        lines = []
        buf = self.com.read_until(b"\r\n")
        lines += buf.decode("utf8").split("\n")
        while buf != b"":
            buf = self.com.read_until(b"\r\n")
            lines += buf.decode("utf8").split("\n")
        cmd_resp = []
        aux_resp = []
        for line in lines:
            strip = line.strip()
            if strip.startswith(command_str[0]):
                cmd_resp.append(strip)
            elif strip:
                aux_resp.append(strip)
        if aux_resp:
            LOGGER.info(f"Received auxiliary responses: {aux_resp}")
        # while not cmd_resp:
        #     repeats = self.send(command_str)
        #     cmd_resp += repeats[0]
        #     aux_resp += repeats[1]
        #     time.sleep(0.1)
        return cmd_resp, aux_resp

    def read_stream(self):
        self.com.flush()
        lines, _ = self.send("Z")
        for line in lines[::-1]:
            stripped = line.strip()
            filts = re.findall("Z\s[0-9]+", stripped)
            filt = filts[-1].split()[-1] if filts else False
            if filt:
                return filt
        return False

    async def poll_sensor_loop(self, frequency: int = 4, reset_after: int = 5):
        waittime = 1.0 / frequency
        LOGGER.info("Starting polling loop")
        blanks = 0
        while True:
            if blanks == reset_after:
                LOGGER.warning(f"Did not receive a co2 message from sensor after {reset_after} checks, resetting polling mode.")
                self.com.write(b"K 2\r\n")
                blanks = 0
            try:
                co2_level = self.read_stream()
            except Exception as err:
                LOGGER.info(f"Could not parse streaming value, got {err}")
                continue
            if co2_level:
                msg_dict = {
                    "co2_ppm": int(co2_level) * self.fw["scaling_factor"],
                    # "co2_ppm_unflt": int(co2_level_unfilt) * self.fw["scaling_factor"],
                }
                if msg_dict["co2_ppm"] >= 0 and msg_dict["co2_ppm"] < 1e6:
                    await self.base.put_lbuf(msg_dict)
                else:
                    LOGGER.info(f"Got unreasonable co2_ppm value {msg_dict['co2_ppm']}")
                blanks = 0
            else:
                blanks += 1
            await asyncio.sleep(waittime)

    async def continuous_record(self):
        """Async polling task.

        'start_margin' is the number of seconds to extend the trigger acquisition window
        to account for the time delay between SPEC and PSTAT actions

        The 'while self.IO_do_meas' loop is exited by IOloop
        """
        # first_print = True
        # await asyncio.sleep(0.01)

        if self.com is None:
            self.IO_measuring = False
            return {"co2-measure": "not initialized"}

        else:
            # active object is set so we can set the continue flag
            self.IO_continue = True

        self.start_time = time.time()
        while self.IO_do_meas:
            now = time.time()
            valid_time = (now - self.start_time) < (
                self.recording_duration + self.start_margin
            )
            valid_rate = (now - self.last_rec_time) >= self.recording_rate
            if valid_time and valid_rate:
                # if 1:
                co2_ppm, co2_ts = self.base.get_lbuf("co2_ppm")
                co2_ppm_unflt, co2_ts = self.base.get_lbuf("co2_ppm_unflt")
                datadict = {
                    "epoch_s": co2_ts,
                    "co2_ppm": co2_ppm,
                    "co2_ppm_unflt": co2_ppm_unflt,
                }
                # await self.active.enqueue_data(
                self.active.enqueue_data_nowait(
                    datamodel=DataModel(
                        data={self.active.action.file_conn_keys[0]: datadict},
                        errors=[],
                        status=HloStatus.active,
                    )
                )
                self.last_rec_time = now
            await asyncio.sleep(0.01)
            # await asyncio.sleep(self.recording_rate)

        LOGGER.info("polling loop duration complete, finishing")
        if self.IO_measuring:
            self.IO_do_meas = False
            self.IO_measuring = False
            LOGGER.info("signaling IOloop to stop")
            self.set_IO_signalq_nowait(False)
        else:
            pass

        return {"co2-measure": "done"}

    async def acquire_co2(self, A: Action):
        """Perform async acquisition of co2 level for set duration.

        Return active dict.
        """

        params = A.action_params
        self.recording_duration = params["duration"]
        self.recording_rate = params["acquisition_rate"]
        A.error_code = ErrorCodes.none
        # validate samples_in
        samples_in = await self.unified_db.get_samples(A.samples_in)
        if not samples_in and not self.allow_no_sample:
            LOGGER.error("Server got no valid sample, cannot start measurement!")
            A.samples_in = []
            A.error_code = ErrorCodes.no_sample
            activeDict = A.as_dict()
        else:
            self.samples_in = samples_in
            self.action = A
            # LOGGER.info("Writing initial spec_helao__file")
            file_header = self.fw
            dflt_conn_key = self.base.dflt_file_conn_key()
            file_conn_params = FileConnParams(
                file_conn_key=dflt_conn_key,
                sample_global_labels=[
                    sample.get_global_label() for sample in samples_in
                ],
                file_type="co2-sense_helao__file",
                hloheader=HloHeaderModel(optional=file_header),
            )
            active_params = ActiveParams(
                action=self.action,
                file_conn_params_dict={dflt_conn_key: file_conn_params},
            )
            self.active = await self.base.contain_action(active_params)
            for sample in samples_in:
                sample.status = [SampleStatus.preserved]
                sample.inheritance = SampleInheritance.allow_both

            self.active.action.samples_in = []
            # now add updated samples to sample_in again
            await self.active.append_sample(
                samples=[sample_in for sample_in in self.samples_in], IO="in"
            )

            LOGGER.info(f"start_time: {self.start_time}")
            self.active.finish_hlo_header(
                realtime=self.base.get_realtime_nowait(),
                file_conn_keys=self.active.action.file_conn_keys,
            )
            # signal the IOloop to start the measrurement
            await self.set_IO_signalq(True)

            # need to wait now for the activation of the meas routine
            # and that the active object is activated and sets action status
            while not self.IO_continue:
                await asyncio.sleep(1)

            # reset continue flag
            self.IO_continue = False

            activeDict = self.active.action.as_dict()

        return activeDict

    def shutdown(self):
        try:
            self.polling_task.cancel()
        except asyncio.CancelledError:
            LOGGER.info("closed sensor polling loop task")
        try:
            self.recording_task.cancel()
        except asyncio.CancelledError:
            LOGGER.info("closed sensor recording loop task")
        self.com.close()


class CO2MonExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        LOGGER.info("CO2MonExec initialized.")
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)
        self.total = 0
        self.num_acqs = 0

    async def _poll(self):
        """Read CO2 ppm from live buffer."""
        live_dict = {}
        co2_ppm, epoch_s = self.active.base.get_lbuf("co2_ppm")
        # LOGGER.info(f"got from live buffer: {co2_ppm}")
        self.total += co2_ppm
        self.num_acqs += 1
        live_dict["co2_ppm"] = co2_ppm
        live_dict["epoch_s"] = epoch_s
        iter_time = time.time()
        elapsed_time = iter_time - self.start_time
        if (self.duration < 0) or (elapsed_time < self.duration):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.01)
        # LOGGER.info(f"sending status: {status}")
        # LOGGER.info(f"sending data: {live_dict}")
        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": live_dict,
        }

    async def _post_exec(self):
        "Cleanup methods, return error state."
        self.cleanup_err = ErrorCodes.none
        if self.num_acqs > 0:
            self.active.action.action_params["mean_co2_ppm"] = self.total / self.num_acqs
        return {"data": {}, "error": self.cleanup_err}