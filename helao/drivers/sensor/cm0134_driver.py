__all__ = []

import time
import asyncio
import serial
import minimalmodbus

from helaocore.error import ErrorCodes
from helaocore.models.data import DataModel
from helaocore.models.file import FileConnParams, HloHeaderModel
from helaocore.models.sample import SampleInheritance, SampleStatus
from helaocore.models.hlostatus import HloStatus
from helao.servers.base import Base, Executor
from helao.helpers.premodels import Action
from helao.helpers.active_params import ActiveParams
from helao.helpers.sample_api import UnifiedSampleDataAPI


class CM0134:
    """Device driver class for the CM0134 oxygen sensor using RS-485 communication."""

    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.unified_db = UnifiedSampleDataAPI(self.base)

        self.bokehapp = None

        self.inst = minimalmodbus.Instrument(
            self.config_dict.get("device", "COM7"), self.config_dict.get("address", 254)
        )
        self.inst.serial.baudrate = self.config_dict.get("baudrate", 9600)

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
                        self.base.print_message("O2-sense got measurement request")
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
                                "O2-sense is in estop after measurement.", error=True
                            )
                        else:
                            self.base.print_message("setting O2-sense to idle")
                            # await self.stat.set_idle()
                        self.base.print_message("O2 measurement is done")
                    else:
                        self.active.action.action_status.append(HloStatus.estopped)
                        self.IO_do_meas = False
                        self.base.print_message("O2-sense is in estop.", error=True)

                # endpoint can return even we got errors
                self.IO_continue = True

                if self.active:
                    self.base.print_message("O2-sense finishes active action")
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

    async def poll_sensor_loop(self, frequency: int = 2):
        waittime = 1.0 / frequency
        self.base.print_message("Starting polling loop")
        while True:
            try:
                o2_level = self.inst.read_register(1, functioncode=4) * 10
            except minimalmodbus.NoResponseError as err:
                self.base.print_message(f"NoResponseError: Driver polling rate is too fast. {err}")
                continue
            except serial.SerialException as err:
                self.base.print_message(f"Device {self.config_dict['device']} is in use. {err}")
                continue
            if o2_level:
                msg_dict = {"o2_ppm": int(o2_level)}
                await self.base.put_lbuf(msg_dict)
            await asyncio.sleep(waittime)

    async def continuous_record(self):
        """Async polling task.

        'start_margin' is the number of seconds to extend the trigger acquisition window
        to account for the time delay between SPEC and PSTAT actions

        The 'while self.IO_do_meas' loop is exited by IOloop
        """
        # first_print = True
        # await asyncio.sleep(0.001)

        if self.inst is None:
            self.IO_measuring = False
            return {"o2-measure": "not initialized"}

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
                co2_ppm, co2_ts = self.base.get_lbuf("co2_ppm")
                datadict = {
                    "epoch_s": co2_ts,
                    "o2_ppm": co2_ppm,
                }
                self.active.enqueue_data_nowait(
                    datamodel=DataModel(
                        data={self.active.action.file_conn_keys[0]: datadict},
                        errors=[],
                        status=HloStatus.active,
                    )
                )
                self.last_rec_time = now
            await asyncio.sleep(0.001)

        self.base.print_message("polling loop duration complete, finishing")
        if self.IO_measuring:
            self.IO_do_meas = False
            self.IO_measuring = False
            self.base.print_message("signaling IOloop to stop")
            self.set_IO_signalq_nowait(False)
        else:
            pass

        return {"o2-measure": "done"}

    async def acquire_o2(self, A: Action):
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
            file_header = self.fw
            dflt_conn_key = self.base.dflt_file_conn_key()
            file_conn_params = FileConnParams(
                file_conn_key=dflt_conn_key,
                sample_global_labels=[
                    sample.get_global_label() for sample in samples_in
                ],
                file_type="o2-sense_helao__file",
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
            await self.active.append_sample(samples=self.samples_in, IO="in")

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
