""" A device class for the SprintIR-6S CO2 sensor.

"""

__all__ = []

import time
import asyncio

import serial

from helaocore.error import ErrorCodes
from helao.servers.base import Base
from helaocore.models.data import DataModel
from helaocore.models.file import FileConnParams, HloHeaderModel
from helaocore.models.sample import SampleInheritance, SampleStatus
from helaocore.models.hlostatus import HloStatus
from helao.helpers.premodels import Action
from helao.helpers.active_params import ActiveParams
from helao.helpers.sample_api import UnifiedSampleDataAPI
from helao.servers.base import Base

from functools import partial
from bokeh.server.server import Server

""" Notes:

Setup polling task to populate base.live_buffer dictionary, record CO2 action will read
from dictionary.

TODO: send CO2 reading to bokeh visualizer w/o writing data

"""


class SprintIR:
    def __init__(self, action_serv: Base):

        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.unified_db = UnifiedSampleDataAPI(self.base)

        self.bokehapp = None

        # read pump addr and strings from config dict
        self.com = serial.Serial(
            port=self.config_dict["port"],
            baudrate=9600,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1,
            xonxoff=False,
            rtscts=False,
        )

        # set POLL and flush present buffer until empty
        self.com.write(b"K 2\r\n")
        self.com.flush()
        buf = self.com.read_all()
        while not buf == b"":
            buf = self.com.read_all()

        fw_map = {
            "digital_filter_value": "a",
            "zero-point_air": "G",
            "zero-point_n2": "U",
            "scaling_factor": ".",
            "pc_compensation": "s"
        }
        ifw_map = {v: k for k,v in fw_map.items()}
        self.fw = {}
        for k, v in fw_map.items():
            resp, aux = self.send(v)
            if resp:
                fw_val = resp[0].split()[-1].replace(v, "").strip()
                if fw_val not in ['?', '']:
                    self.fw[k] = int(fw_val)
            for aresp in aux:
                cmd = aresp[0]
                if cmd in ifw_map.keys():
                    fw_val = aresp.split()[-1].replace(cmd, "").strip()
                    self.fw[cmd] = int(fw_val)
            time.sleep(0.1)
        
        self.base.print_message(self.fw)

        self.action = None
        self.active = None
        self.start_margin = self.config_dict.get("start_margin", 0)
        self.start_time = 0
        self.last_rec_time = 0
        self.last_check_time = time.time()
        self.IO_signalq = asyncio.Queue(1)
        self.IO_do_meas = False  # signal flag for intent (start/stop)
        self.IO_measuring = False  # status flag of measurement
        self.event_loop = asyncio.get_event_loop()
        self.recording_task = self.event_loop.create_task(self.IOloop())
        self.recording_duration = 0
        self.recording_rate = 0.2  # seconds per acquisition
        self.polling_task = self.event_loop.create_task(self.poll_sensor_loop())

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
                        self.base.print_message("CO2-sense got measurement request")
                        try:
                            await asyncio.wait_for(
                                self.continuous_record(),
                                self.recording_duration + self.start_margin,
                            )
                        except asyncio.exceptions.TimeoutError:
                            pass
                        if self.base.actionservermodel.estop:
                            self.IO_do_meas = False
                            self.base.print_message(
                                "CO2-sense is in estop after measurement.", error=True
                            )
                        else:
                            self.base.print_message("setting CO2-sense to idle")
                            # await self.stat.set_idle()
                        self.base.print_message("CO2 measurement is done")
                    else:
                        self.active.action.action_status.append(HloStatus.estopped)
                        self.IO_do_meas = False
                        self.base.print_message("CO2-sense is in estop.", error=True)

                # endpoint can return even we got errors
                self.IO_continue = True

                if self.active:
                    self.base.print_message("CO2-sense finishes active action")
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
            self.base.print_message("IOloop task was cancelled")

    def send(self, command_str: str):
        if not command_str.endswith("\r\n"):
            command_str = command_str + "\r\n"
        self.com.write(command_str.encode('utf8'))
        self.com.flush()
        lines = self.com.readlines()
        cmd_resp = []
        aux_resp = []
        for line in lines:
            strip = line.decode('utf8').strip()
            if strip.startswith(command_str[0]):
                cmd_resp.append(strip)
            elif strip:
                aux_resp.append(strip)
        if aux_resp:
            self.base.print_message(
                f"Received auxiliary responses: {aux_resp}", warning=True
            )
        return cmd_resp, aux_resp

    async def poll_sensor_loop(self, frequency: int = 20):
        waittime = 1.0 / frequency
        while True:
            co2_level, _ = self.send("Z")[0]
            if co2_level:
                await self.base.put_lbuf({"co2_sensor": co2_level.split()[-1]})
            await asyncio.sleep(waittime)

    async def continuous_record(self):
        """Async polling task.

        'start_margin' is the number of seconds to extend the trigger acquisition window
        to account for the time delay between SPEC and PSTAT actions
        """
        # first_print = True
        await asyncio.sleep(0.001)

        if self.sio is None:
            self.IO_measuring = False
            return {"co2-measure": "not initialized"}

        else:
            # active object is set so we can set the continue flag
            self.IO_continue = True

        while self.IO_do_meas:
            valid_time = (self.last_rec_time - self.start_time) < (
                self.recording_duration + self.start_margin
            )
            valid_rate = time.time() - self.last_check_time >= self.recording_rate
            if valid_time and valid_rate:
                co2_reading, co2_ts = self.base.get_lbuf("co2_sensor")
                datadict = {
                    "epoch_s": co2_ts,
                    "co2_ppm": co2_reading * self.fw['scaling_factor'],
                }
                await self.active.enqueue_data(
                    datamodel=DataModel(
                        data={self.active.action.file_conn_keys[0]: datadict},
                        errors=[],
                        status=HloStatus.active,
                    )
                )
                self.last_rec_time = time.time()
            self.last_check_time = time.time()
            await asyncio.sleep(0.001)

        self.base.print_message("polling loop duration complete, finishing")
        self.recording_duration = 0
        if self.IO_measuring:
            self.IO_do_meas = False
            self.IO_measuring = False
            self.base.print("signaling IOloop to stop")
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
            self.base.print_message(
                "Server got no valid sample, cannot start measurement!", error=True
            )
            A.samples_in = []
            A.error_code = ErrorCodes.no_sample
            activeDict = A.as_dict()
        else:
            self.samples_in = samples_in
            self.action = A
            # self.base.print_message("Writing initial spec_helao__file", info=True)
            file_header = self.fw
            dflt_conn_key = self.base.dflt_file_conn_key()
            file_conn_params = FileConnParams(
                file_conn_key=dflt_conn_key,
                sample_global_labels=[
                    sample.get_global_label() for sample in samples_in
                ],
                file_type="co2-sense_helao__file",
                hloheader=HloHeaderModel(optional=file_header)
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

            self.start_time = time.time()
            self.last_rec_time = time.time()
            self.base.print_message(f"start_time: {self.start_time}")
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
        self.com.close()
