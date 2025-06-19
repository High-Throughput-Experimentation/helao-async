__all__ = ["cNIMAX"]

import time
import asyncio
import traceback

import nidaqmx
from nidaqmx.constants import LineGrouping
from nidaqmx.constants import Edge
from nidaqmx.constants import AcquisitionType
from nidaqmx.constants import TerminalConfiguration
from nidaqmx.constants import VoltageUnits
from nidaqmx.constants import TemperatureUnits
from nidaqmx.constants import ThermocoupleType
from nidaqmx.constants import CurrentShuntResistorLocation
from nidaqmx.constants import UnitsPreScaled
from nidaqmx.constants import TriggerType

from helao.helpers.premodels import Action
from helao.servers.base import Base
from helao.helpers.executor import Executor
from helao.core.error import ErrorCodes
from helao.helpers.make_str_enum import make_str_enum
from helao.helpers.sample_api import UnifiedSampleDataAPI
from helao.core.models.sample import SampleInheritance, SampleStatus
from helao.core.models.file import FileConnParams, HloHeaderModel
from helao.helpers.active_params import ActiveParams
from helao.core.models.data import DataModel
from helao.core.models.hlostatus import HloStatus

from helao.helpers import helao_logging as logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

class cNIMAX:
    def __init__(self, action_serv: Base):

        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg

        self.unified_db = UnifiedSampleDataAPI(self.base)
        asyncio.gather(self.unified_db.init_db())

        self.dev_pump = self.config_dict.get("dev_pump", {})
        self.dev_pumpitems = make_str_enum(
            "dev_pump", {key: key for key in self.dev_pump}
        )

        self.dev_gasvalve = self.config_dict.get("dev_gasvalve", {})
        self.dev_gasvalveitems = make_str_enum(
            "dev_gasvalve", {key: key for key in self.dev_gasvalve}
        )

        self.dev_liquidvalve = self.config_dict.get("dev_liquidvalve", {})
        self.dev_liquidvalveitems = make_str_enum(
            "dev_liquidvalve", {key: key for key in self.dev_liquidvalve}
        )
        self.dev_heat = self.config_dict.get("dev_heat", {})
        self.dev_heatitems = make_str_enum(
            "dev_heat", {key: key for key in self.dev_heat}
        )

        self.dev_led = self.config_dict.get("dev_led", {})
        self.dev_leditems = make_str_enum("dev_led", {key: key for key in self.dev_led})

        self.allow_no_sample = self.config_dict.get("allow_no_sample", False)

        LOGGER.info("init NI-MAX")

        self.action = (
            None  # for passing action object from technique method to measure loop
        )
        self.active = (
            None  # for holding active action object, clear this at end of measurement
        )
        self.samples_in = []

        # seems to work by just defining the scale and then only using its name
        try:
            self.Iscale = nidaqmx.scale.Scale.create_lin_scale(
                "NEGATE3", -1.0, 0.0, UnitsPreScaled.AMPS, "AMPS"
            )
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(f"NImax error: ", exc_info=True)
            raise e
        self.time_stamp = time.time()

        # this defines the time axis, need to calculate our own
        self.samplingrate = 10  # samples per second
        # used to keep track of time during data readout
        self.IVtimeoffset = 0.0
        self.buffersize = 1000  # finite samples or size of buffer depending on mode
        self.duration = 10  # sec
        self.ttlwait = -1
        self.buffersizeread = int(self.samplingrate)
        self.IOloopstarttime = 0

        self.IO_signalq = asyncio.Queue(1)
        self.task_6289cellcurrent = None
        self.task_6284cellvoltage = None
        self.task_monitors = None
        self.IO_do_meas = False  # signal flag for intent (start/stop)
        self.IO_measuring = False  # status flag of measurement
        self.activeCell = [False for _ in range(9)]

        self.FIFO_epoch = None
        # self.FIFO_header = ''
        self.FIFO_NImaxheader = {}
        self.FIFO_name = ""
        self.FIFO_dir = ""
        self.FIFO_cell_keys = [
            "cell1",
            "cell2",
            "cell3",
            "cell4",
            "cell5",
            "cell6",
            "cell7",
            "cell8",  # removed from cell list due to use of NI lines   ---- restored 8/14/2022
            "cell9",  # can add back in if rewiring added to box for heaters
        ]
        self.file_conn_keys = []
        self.FIFO_column_headings = [
            "t_s",
            "Icell_A",
            "Ecell_V",
            "Ttemp_Ktc_in_cell_C",
            "Ttemp_Ttc_in_reservoir_C",
            "Ttemp_Ktc_out_cell_C",
            "Ttemp_Ktc_out_reservoir_C",
        ]

        # keeps track of the multi cell IV measurements in the background
        myloop = asyncio.get_event_loop()
        # add meas IOloop
        self.IOloop_run = False
        self.monitorloop_run = True
        #        myloop.create_task(self.IOloop())  #if loop terminates immediately upon starting due to False, then
        # starting it here is useless? maybe have another loop inside it?
        myloop.create_task(self.monitorloop())

    def set_IO_signalq_nowait(self, val: bool) -> None:
        if self.IO_signalq.full():
            _ = self.IO_signalq.get_nowait()
        self.IO_signalq.put_nowait(val)

    async def set_IO_signalq(self, val: bool) -> None:
        if self.IO_signalq.full():
            _ = await self.IO_signalq.get()
        await self.IO_signalq.put(val)

    def create_IVtask(self):
        """configures a NImax task for multi cell IV measurements"""
        # Voltage reading is MASTER
        self.task_6289cellcurrent = nidaqmx.Task()
        for myname, mydev in self.config_dict["dev_cellcurrent"].items():
            self.task_6289cellcurrent.ai_channels.add_ai_current_chan(
                mydev,
                name_to_assign_to_channel="Cell_" + myname,
                terminal_config=TerminalConfiguration.DIFFERENTIAL,
                min_val=-0.02,
                max_val=+0.02,
                units=VoltageUnits.FROM_CUSTOM_SCALE,
                shunt_resistor_loc=CurrentShuntResistorLocation.EXTERNAL,
                ext_shunt_resistor_val=5.0,
                custom_scale_name="NEGATE3",  # TODO: this can be a per channel calibration
            )
        self.task_6289cellcurrent.ai_channels.all.ai_lowpass_enable = True
        self.task_6289cellcurrent.timing.cfg_samp_clk_timing(
            self.samplingrate,
            source="",
            active_edge=Edge.RISING,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=self.buffersize,
        )
        # TODO can increase the callbackbuffersize if needed
        # self.task_6289cellcurrent.register_every_n_samples_acquired_into_buffer_event(10,self.streamCURRENT_callback)
        self.task_6289cellcurrent.register_every_n_samples_acquired_into_buffer_event(
            self.buffersizeread, self.streamIV_callback
        )

        # Voltage reading is SLAVE
        # we cannot combine both tasks into one as they run on different DAQs
        # define the VOLT and CURRENT task as they need to stay in memory
        self.task_6284cellvoltage = nidaqmx.Task()
        for myname, mydev in self.config_dict["dev_cellvoltage"].items():
            self.task_6284cellvoltage.ai_channels.add_ai_voltage_chan(
                mydev,
                name_to_assign_to_channel="Cell_" + myname,
                terminal_config=TerminalConfiguration.DIFFERENTIAL,
                min_val=-10.0,
                max_val=+10.0,
                units=VoltageUnits.VOLTS,
            )

        # does this globally enable lowpass or only for channels in task?
        self.task_6284cellvoltage.ai_channels.all.ai_lowpass_enable = True
        # self.task_6284cellvoltage.ai_lowpass_enable = True
        self.task_6284cellvoltage.timing.cfg_samp_clk_timing(
            self.samplingrate,
            source="",
            active_edge=Edge.RISING,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=self.buffersize,
        )
        # #        self.task_6289cellcurrent = nidaqmx.Task()
        #         self.task_6289cellcurrent.ai_channels.add_ai_thrmcpl_chan(
        # #            physical_channel= 'Ktc_in_cell',
        #             physical_channel= 'PXI-6289/ai0',
        #             name_to_assign_to_channel="cell_temp",
        #             min_val=0,
        #             max_val=150,
        #             units=TemperatureUnits.DEG_C,
        #             thermocouple_type=ThermocoupleType.S,
        # #            cjc_source=CJCSource.BUILT_IN,
        #         )

        #         self.task_6284cellvoltage.ai_channels.add_ai_thrmcpl_chan(
        #  #           physical_channel= 'Ttc_in_reservoir',
        #             physical_channel= 'PXI-6284/ai0',
        #             name_to_assign_to_channel="reservoir_temp",
        #             min_val=0,
        #             max_val=150,
        #             units=TemperatureUnits.DEG_C,
        #             thermocouple_type=ThermocoupleType.T,
        # #            cjc_source=CJCSource.BUILT_IN,
        #         )

        # each card need its own physical trigger input
        if (
            self.config_dict["dev_cellvoltage_trigger"] != ""
            and self.config_dict["dev_cellcurrent_trigger"] != ""
            and self.ttlwait != -1
        ):
            self.task_6284cellvoltage.triggers.start_trigger.trig_type = (
                TriggerType.DIGITAL_EDGE
            )
            self.task_6284cellvoltage.triggers.start_trigger.cfg_dig_edge_start_trig(
                trigger_source=self.config_dict["dev_cellvoltage_trigger"],
                trigger_edge=Edge.RISING,
            )

            self.task_6289cellcurrent.triggers.start_trigger.trig_type = (
                TriggerType.DIGITAL_EDGE
            )
            self.task_6289cellcurrent.triggers.start_trigger.cfg_dig_edge_start_trig(
                trigger_source=self.config_dict["dev_cellcurrent_trigger"],
                trigger_edge=Edge.RISING,
            )

    #     def create_Ttask(self):
    #         """configures and starts a NImax task for nonexperiment temp measurements"""
    #         self.task_tempinst_S = nidaqmx.Task()
    #         self.task_tempinst_S.ai_channels.add_ai_thrmcpl_chan(
    # #           physical_channel= 'Ktc_in_cell',
    #             physical_channel= 'PXI-6289/ai2',
    #             name_to_assign_to_channel="cell_temp",
    #             min_val=0,
    #             max_val=150,
    #             units=TemperatureUnits.DEG_C,
    #             thermocouple_type=ThermocoupleType.S,
    #             # cjc_source=CJCSource.CONSTANT_USER_VALUE,
    #             # cjc_val = 27,
    #             # cjc_source=CJCSource.SCANNABLE_CHANNEL,
    #             # cjc_channel= 'CJCtemp',
    #         )

    #         self.task_tempinst_S.ai_channels.all.ai_lowpass_enable = True
    #         self.task_tempinst_S.timing.cfg_samp_clk_timing(   #timing/triggering need

    #             rate= 1,
    # #           self.Tsamplingrate,
    #             source="",
    #             active_edge=Edge.RISING,
    #             sample_mode=AcquisitionType.CONTINUOUS,
    #             samps_per_chan=self.buffersize,
    #         )
    #         self.task_tempinst_T = nidaqmx.Task()
    #         self.task_tempinst_T.ai_channels.add_ai_thrmcpl_chan(
    #            # physical_channel= 'Ttc_in_reservoir',
    #             physical_channel= 'PXI-6284/ai2',   #temporary  cjc source ai channel instead of 2
    #             name_to_assign_to_channel="reservoir_temp",
    #             min_val=0,
    #             max_val=150,
    #             units=TemperatureUnits.DEG_C,
    #             thermocouple_type=ThermocoupleType.T,
    #             # cjc_source=CJCSource.CONSTANT_USER_VALUE,
    #             # cjc_val = 27,
    #             # cjc_source=CJCSource.SCANNABLE_CHANNEL,
    #             # cjc_channel = 'CJCtemp',
    #         )

    #         self.task_tempinst_T.ai_channels.all.ai_lowpass_enable = True
    #         self.task_tempinst_T.timing.cfg_samp_clk_timing(   #timing need?

    #             rate= 1,
    # #           self.Tsamplingrate,
    #             source="",
    #             active_edge=Edge.RISING,
    #             sample_mode=AcquisitionType.CONTINUOUS,
    #             samps_per_chan=self.buffersize,
    #         )
    #         # self.task_tempCJC = nidaqmx.Task()
    #         # self.task_tempCJC.ai_channels.add_ai_temp_built_in_sensor_chan(
    #         #     physical_channel= 'PXI-6284/ai0',
    #         #     name_to_assign_to_channel="CJCtemp",
    #         #     units=TemperatureUnits.DEG_C,
    #         # )
    # #         self.task_tempCJC.ai_channels.all.ai_lowpass_enable = True
    # #         self.task_tempCJC.timing.cfg_samp_clk_timing(   #timing need?
    # #             rate= 1,
    # # #           self.Tsamplingrate,
    # #             source="",
    # #             active_edge=Edge.RISING,
    # #             sample_mode=AcquisitionType.CONTINUOUS,
    # #             samps_per_chan=self.buffersize,
    # #         )

    #         self.task_tempinst_S.start()
    #         self.task_tempinst_T.start()
    # #         self.task_tempCJC.start()

    def create_monitortask(self):
        """configures and starts a NImax task for nonexperiment temp measurements"""
        self.task_monitors = nidaqmx.Task()
        self.task_monitor_keys = list(self.config_dict.get("dev_monitor", {}).keys())
        if self.task_monitor_keys:
            for myname in self.task_monitor_keys:
                mydev = self.config_dict["dev_monitor"][myname]
                # can add if filter for different types of monitors (other than Temp)
                if "Ttc_" in myname:
                    TCtype = ThermocoupleType.T
                else:
                    TCtype = ThermocoupleType.K
                self.task_monitors.ai_channels.add_ai_thrmcpl_chan(
                    mydev,
                    name_to_assign_to_channel=myname,
                    min_val=0,
                    max_val=150,
                    units=TemperatureUnits.DEG_C,
                    thermocouple_type=TCtype,
                    # cjc_source=CJCSource.CONSTANT_USER_VALUE,
                    # cjc_val = 27,
                    # cjc_source=CJCSource.SCANNABLE_CHANNEL,
                    # cjc_channel= 'CJCtemp',
                )
            self.task_monitors.ai_channels.all.ai_lowpass_enable = True
            self.task_monitors.timing.cfg_samp_clk_timing(
                rate=1,
                source="",
                active_edge=Edge.RISING,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=self.buffersize,
            )

        #        self.task_monitors.start()

    async def monitorloop(self):
        self.create_monitortask()
        if self.task_monitor_keys:
            self.task_monitors.start()
            while self.monitorloop_run:
                mvalues = self.task_monitors.read()
                if not isinstance(mvalues, list):
                    mvalues = [mvalues]
                datastore = {
                    myname: mvalue
                    for myname, mvalue in zip(self.task_monitor_keys, mvalues)
                }
                await self.base.put_lbuf(datastore)
                await asyncio.sleep(0.5)
                # self.monitorloop_run = False   #so it only runs once
            self.task_monitors.close()

    def streamIV_callback(
        self, task_handle, every_n_samples_event_type, number_of_samples, callback_data
    ):
        if self.IO_do_meas and not self.base.actionservermodel.estop:
            try:
                self.IO_measuring = True

                if self.FIFO_epoch is None:
                    self.FIFO_epoch = self.active.get_realtime_nowait()
                    # need to correct for the first datapoints
                    self.FIFO_epoch -= number_of_samples / self.samplingrate
                    if self.active:
                        if self.active.action.save_data:
                            self.active.finish_hlo_header(realtime=self.FIFO_epoch)

                # start seq: V then current, so read current first then Volt
                # put callback only on current (Volt should the always have enough points)
                # readout is requested-1 when callback is on requested
                dataI = self.task_6289cellcurrent.read(
                    number_of_samples_per_channel=number_of_samples
                )
                dataV = self.task_6284cellvoltage.read(
                    number_of_samples_per_channel=number_of_samples
                )
                mdata = {}
                for myname in self.task_monitor_keys:
                    mdata[myname], _ = self.base.get_lbuf(myname)

                # this is also what NImax seems to do
                time = [
                    self.IVtimeoffset + i / self.samplingrate
                    for i in range(len(dataI[0]))
                ]
                # update timeoffset
                self.IVtimeoffset += number_of_samples / self.samplingrate

                data_dict = {}
                for i, _ in enumerate(self.FIFO_cell_keys):
                    cell_data_dict = {
                        f"{self.FIFO_column_headings[0]}": time,
                        f"{self.FIFO_column_headings[1]}": dataI[i],
                        f"{self.FIFO_column_headings[2]}": dataV[i],
                    }
                    for k in self.task_monitor_keys:
                        cell_data_dict[k] = mdata[k]
                    data_dict[self.file_conn_keys[i]] = cell_data_dict

                # push data to datalogger queue
                if self.active:
                    self.active.enqueue_data_nowait(
                        datamodel=DataModel(data=data_dict, errors=[])
                    )

            except Exception as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                LOGGER.error(f"canceling NImax IV stream: {repr(e), tb,}")

        elif self.base.actionservermodel.estop and self.IO_do_meas:
            _ = self.task_6289cellcurrent.read(
                number_of_samples_per_channel=number_of_samples
            )
            _ = self.task_6284cellvoltage.read(
                number_of_samples_per_channel=number_of_samples
            )
            self.IO_measuring = False
            self.task_6289cellcurrent.close()
            self.task_6284cellvoltage.close()

        else:
            # NImax has data but measurement was already turned off
            # just pull data from buffer and turn task off
            _ = self.task_6289cellcurrent.read(
                number_of_samples_per_channel=number_of_samples
            )
            _ = self.task_6284cellvoltage.read(
                number_of_samples_per_channel=number_of_samples
            )
            # task should be already off or should be closed soon
            LOGGER.info("meas was turned off but NImax IV task is still running ...")
            # self.task_6289cellcurrent.close()
            # self.task_6284cellvoltage.close()

        return 0

    async def IOloop(self):
        """only monitors the status and keeps track of time for the
        multi cell iv task. This one will also handle estop, stop,
        finishes the active object etc."""
        self.IOloop_run = True  # could have another loop before that set of ifs?
        try:
            while self.IOloop_run:
                self.IO_do_meas = await self.IO_signalq.get()
                if self.IO_do_meas and not self.IO_measuring:
                    # are we in estop?
                    if not self.base.actionservermodel.estop:
                        LOGGER.info("NImax IV task got measurement request")

                        # start slave first
                        self.task_6284cellvoltage.start()
                        # then start master to trigger slave
                        self.task_6289cellcurrent.start()

                        # wait for first callback interrupt
                        while not self.IO_measuring:
                            await asyncio.sleep(0.1)
                        LOGGER.info("got IO_measuring")

                        # get timecode and correct for offset from first interrupt
                        self.IOloopstarttime = (
                            time.time()
                        )  # -self.buffersizeread/self.samplingrate

                        while (
                            time.time() - self.IOloopstarttime < self.duration
                        ) and self.IO_do_meas:
                            if not self.IO_signalq.empty():
                                self.IO_do_meas = await self.IO_signalq.get()
                            await asyncio.sleep(0.1)

                        LOGGER.info(f"NImax IV finished with IO_do_meas {self.IO_do_meas}")

                        # await self.IO_signalq.put(False)
                        self.IO_do_meas = False
                        self.IO_measuring = False
                        self.task_6289cellcurrent.close()
                        self.task_6284cellvoltage.close()
                        _ = await self.active.finish()
                        self.active = None
                        self.action = None
                        self.samples_in = []

                        if self.base.actionservermodel.estop:
                            LOGGER.info("NImax IV task is in estop.")
                        else:
                            LOGGER.info("setting NImax IV task to idle")
                        LOGGER.info("NImax IV task measurement is done")
                    else:
                        self.IO_do_meas = False
                        LOGGER.info("NImax IV task is in estop.")

                elif self.IO_do_meas and self.IO_measuring:
                    LOGGER.info("got measurement request but NImax IV task is busy")
                elif not self.IO_do_meas and self.IO_measuring:
                    LOGGER.info("got stop request, measurement will stop next cycle")
                else:
                    LOGGER.info("got stop request but NImax IV task is idle")

            LOGGER.info(f"IOloop got IOloop_run {self.IOloop_run}")

        except asyncio.CancelledError:
            LOGGER.info("IOloop task was cancelled")

    async def Heatloop(
        self,
        duration_h,
        celltemp_min,
        celltemp_max,
        reservoir2_min,
        reservoir2_max,
    ):
        # samplerate = A.action_params["SampleRate"]
        # duration = A.action_params["duration"] * 60 * 60  #time in hours
        # celltemp_min = A.action_params["r1min"]
        # celltemp_max = A.action_params["r1max"]
        # reservoir2_min = A.action_params["r2min"]
        # reservoir2_max = A.action_params["r2max"]

        """attempt maintain temperatures for the mdatatemp task."""
        duration = duration_h * 3600
        heatloopstarttime = time.time()

        self.Heatloop_run = True
        mdata = {}

        while (time.time() - heatloopstarttime < duration) and self.Heatloop_run:
            readtempdict = {}
            for i, myname in enumerate(self.config_dict["dev_monitor"]):
                mdata[i], _ = self.base.get_lbuf(myname)
                readtempdict[myname] = mdata[i]
            cell_temp = float(readtempdict["Ttemp_Ktc_in_cell_C"])
            reservoir_temp = float(readtempdict["Ttemp_Ttc_in_reservoir_C"])
            for myheat, myport in self.dev_heat.items():
                if myheat == "cellheater":
                    if cell_temp < celltemp_min:
                        await self.set_digital_out(
                            do_port=myport, do_name=myheat, on=True
                        )
                    if cell_temp > celltemp_max:
                        await self.set_digital_out(
                            do_port=myport, do_name=myheat, on=False
                        )
                if myheat == "res_heater":
                    if reservoir_temp < reservoir2_min:
                        await self.set_digital_out(
                            do_port=myport, do_name=myheat, on=True
                        )
                    if reservoir_temp > reservoir2_max:
                        await self.set_digital_out(
                            do_port=myport, do_name=myheat, on=False
                        )
            await asyncio.sleep(1)
        await self.set_digital_out(do_port=myport, do_name=myheat, on=False)
        await self.set_digital_out(do_port=myport, do_name=myheat, on=False)
        return (
            self.Heatloop_run
        )  # indicates whether heatloop terminated via time duration or stop

    async def set_digital_out(
        self, do_port=None, do_name: str = "", on: bool = False, *args, **kwargs
    ):
        LOGGER.info(f"do_port '{do_name}': {do_port} is {on}")
        on = bool(on)
        cmds = []
        err_code = ErrorCodes.none
        if do_port is not None:
            with nidaqmx.Task() as task_do_port:
                # for pump in pumps:
                task_do_port.do_channels.add_do_chan(
                    do_port,
                    line_grouping=LineGrouping.CHAN_PER_LINE,
                )
                cmds.append(on)
                if cmds:
                    task_do_port.write(cmds)
                    err_code = ErrorCodes.none
                else:
                    err_code = ErrorCodes.not_available
        else:
            err_code = ErrorCodes.not_available

        return {
            "error_code": err_code,
            "port": do_port,
            "name": do_name,
            "type": "digital_out",
            "value": on,
        }

    async def get_digital_in(
        self, di_port=None, di_name: str = "", on: bool = False, *args, **kwargs
    ):
        LOGGER.info(f"di_port '{di_name}': {di_port}")
        on = None
        err_code = ErrorCodes.none
        if di_port is not None:
            with nidaqmx.Task() as task_di_port:

                task_di_port.di_channels.add_di_chan(
                    di_port,
                    line_grouping=LineGrouping.CHAN_PER_LINE,
                )
                on = task_di_port.read(number_of_samples_per_channel=1)
        else:
            err_code = ErrorCodes.not_available

        return {
            "error_code": err_code,
            "port": di_port,
            "name": di_name,
            "type": "digital_in",
            "value": on,
        }

    async def run_cell_IV(self, A: Action):
        activeDict = {}

        samplerate = A.action_params["SampleRate"]
        duration = A.action_params["Tval"]
        ttlwait = A.action_params["TTLwait"]  # -1 disables, else select TTL channel

        A.error_code = ErrorCodes.none
        if not self.IO_do_meas:
            # first validate the provided samples
            samples_in = await self.unified_db.get_samples(A.samples_in)
            if not samples_in and not self.allow_no_sample:
                LOGGER.error("NI got no valid sample, cannot start measurement!")
                A.error_code = ErrorCodes.no_sample
                activeDict = A.as_dict()
            else:

                self.IVtimeoffset = 0.0
                self.file_conn_keys = []
                self.samplingrate = samplerate
                self.duration = duration
                self.ttlwait = ttlwait
                self.buffersizeread = int(self.samplingrate)
                # save submitted action object
                self.action = A
                self.samples_in = samples_in
                self.FIFO_epoch = None
                # create active and write streaming file header

                self.FIFO_NImaxheader = {}
                file_sample_label = {}
                file_sample_list = []

                for sample in self.samples_in:
                    sample.status = [SampleStatus.preserved]
                    sample.inheritance = SampleInheritance.allow_both

                for i, FIFO_cell_key in enumerate(self.FIFO_cell_keys):
                    if self.samples_in is not None:
                        if (
                            len(self.samples_in) == 9
                        ):  # number of cells   ----restored to 9
                            file_sample_list.append([self.samples_in[i]])
                            sample_label = [self.samples_in[i].get_global_label()]
                        else:
                            file_sample_list.append(self.samples_in)
                            sample_label = [
                                sample.get_global_label() for sample in self.samples_in
                            ]
                    else:
                        file_sample_list.append([])
                        sample_label = None
                    file_sample_label[FIFO_cell_key] = sample_label

                # create the first action and then split it into child actions
                # for the other data streams
                self.file_conn_keys.append(self.base.dflt_file_conn_key())
                self.active = await self.base.contain_action(
                    ActiveParams(
                        action=self.action,
                        file_conn_params_dict={
                            self.base.dflt_file_conn_key(): FileConnParams(
                                file_conn_key=self.base.dflt_file_conn_key(),
                                sample_global_labels=file_sample_label[
                                    self.FIFO_cell_keys[0]
                                ],
                                file_type="ni_helao__file",
                                # only add optional keys to header
                                # rest will be added later
                                hloheader=HloHeaderModel(
                                    optional={"cell": self.FIFO_cell_keys[0]}
                                ),
                            )
                        },
                    )
                )
                # clear old samples_in first
                self.active.action.samples_in = []
                # now add updated samples to sample_in again
                await self.active.append_sample(samples=file_sample_list[0], IO="in")

                # now add the rest
                for i in range(len(self.FIFO_cell_keys) - 1):
                    new_file_conn_keys = await self.active.split(
                        new_fileconnparams=FileConnParams(
                            file_conn_key=self.base.dflt_file_conn_key(),
                            sample_global_labels=file_sample_label[
                                self.FIFO_cell_keys[i + 1]
                            ],
                            file_type="ni_helao__file",
                            # only add optional keys to header
                            # rest will be added later
                            hloheader=HloHeaderModel(
                                optional={"cell": self.FIFO_cell_keys[i + 1]}
                            ),
                        )
                    )
                    # add the new file_conn_key to the list
                    if new_file_conn_keys:
                        self.file_conn_keys.append(new_file_conn_keys[0])

                    # clear old samples_in first
                    self.active.action.samples_in = []

                    # now add updated samples to sample_in again
                    await self.active.append_sample(
                        samples=file_sample_list[i + 1], IO="in"
                    )

                # create the cell IV task
                self.create_IVtask()
                await self.set_IO_signalq(True)

                self.active.action.error_code = ErrorCodes.none

                if self.active:
                    activeDict = self.active.action.as_dict()
                else:
                    activeDict = A.as_dict()

        else:
            A.error_code = ErrorCodes.in_progress
            activeDict = A.as_dict()

        return activeDict

    async def read_T(self):
        mdata = {}
        for myname in self.task_monitor_keys:
            mdata[myname], _ = self.base.get_lbuf(myname)
        print(mdata)
        return mdata

    def stop_monitor(self):
        """stops instantaneous temp measurement"""
        self.monitorloop_run = False

    def stop_heatloop(self):
        """stops instantaneous temp measurement"""
        self.Heatloop_run = False

    async def stop(self):
        """stops measurement, writes all data and returns from meas loop"""
        # turn off cell and run before stopping meas loop
        if self.IO_measuring:
            await self.set_IO_signalq(False)

    async def estop(self, switch: bool, *args, **kwargs):
        """same as estop, but also sets flag"""
        switch = bool(switch)
        self.base.actionservermodel.estop = switch

        for do_name, do_port in self.dev_led.items():
            await self.set_digital_out(do_port=do_port, do_name=do_name, on=False)

        for do_name, do_port in self.dev_pump.items():
            await self.set_digital_out(do_port=do_port, do_name=do_name, on=False)

        for do_name, do_port in self.dev_gasvalve.items():
            await self.set_digital_out(do_port=do_port, do_name=do_name, on=False)

        for do_name, do_port in self.dev_liquidvalve.items():
            await self.set_digital_out(do_port=do_port, do_name=do_name, on=False)

        for do_name, do_port in self.dev_heat.items():
            await self.set_digital_out(do_port=do_port, do_name=do_name, on=False)

        if self.IO_measuring:
            if switch:
                await self.set_IO_signalq(False)
                if self.active:
                    self.active.set_estop()

        return switch

    def shutdown(self):
        LOGGER.info("shutting down nidaqmx")
        self.set_IO_signalq_nowait(False)
        retries = 0
        while self.active is not None and retries < 10:
            LOGGER.info(f"Got shutdown, but Active is not yet done!, retry {retries}")
            # set it again
            self.set_IO_signalq_nowait(False)
            time.sleep(1)
            retries += 1
        # stop IOloop and monitorloop
        self.Heatloop_run = False
        self.monitorloop_run = False
        self.IOloop_run = False


class DevMonExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        LOGGER.info("DevMonExec initialized.")
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)

    async def _poll(self):
        """Read analog inputs from live buffer."""
        data_dict = {}
        times = []
        for monitor_name in self.active.driver.task_monitor_keys:
            val, epoch_s = self.active.base.get_lbuf(monitor_name)
            data_dict[monitor_name] = val
            times.append(epoch_s)
        data_dict["epoch_s"] = max(times)
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
            "data": data_dict,
        }
