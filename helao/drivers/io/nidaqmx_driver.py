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
#from nidaqmx.constants import CJCSource
from nidaqmx.constants import ThermocoupleType
from nidaqmx.constants import CurrentShuntResistorLocation
from nidaqmx.constants import UnitsPreScaled
from nidaqmx.constants import TriggerType

from helao.helpers.premodels import Action
from helao.servers.base import Base
from helaocore.error import ErrorCodes
from helao.helpers.make_str_enum import make_str_enum
from helao.helpers.sample_api import UnifiedSampleDataAPI
from helaocore.models.sample import SampleInheritance, SampleStatus
from helaocore.models.file import FileConnParams, HloHeaderModel
from helao.helpers.active_params import ActiveParams
from helaocore.models.data import DataModel


class cNIMAX:
    def __init__(self, action_serv: Base):

        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.world_config = action_serv.world_cfg

        self.unified_db = UnifiedSampleDataAPI(self.base)
        asyncio.gather(self.unified_db.init_db())

        self.dev_pump = self.config_dict.get("dev_pump",{})
        self.dev_pumpitems = make_str_enum(
            "dev_pump", {key: key for key in self.dev_pump}
        )

        self.dev_gasvalve = self.config_dict.get("dev_gasvalve",{})
        self.dev_gasvalveitems = make_str_enum(
            "dev_gasvalve", {key: key for key in self.dev_gasvalve}
        )

        self.dev_liquidvalve = self.config_dict.get("dev_liquidvalve",{})
        self.dev_liquidvalveitems = make_str_enum(
            "dev_liquidvalve", {key: key for key in self.dev_liquidvalve}
        )
        self.dev_heat = self.config_dict.get("dev_heat",{})
        self.dev_heatitems = make_str_enum(
            "dev_heat", {key: key for key in self.dev_heat}
        )

        self.dev_led = self.config_dict.get("dev_led",{})
        self.dev_leditems = make_str_enum("dev_led", {key: key for key in self.dev_led})

        self.allow_no_sample = self.config_dict.get("allow_no_sample", False)

        self.base.print_message("init NI-MAX")

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
            tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            self.base.print_message(f"NImax error: {repr(e), tb,}", error=True)
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
    #        "cell8",   #removed from cell list due to use of NI lines
    #        "cell9",   #can add back in if rewiring added to box for heaters

        ]
        self.file_conn_keys = []
        self.FIFO_column_headings = [
            "t_s",
            "Icell_A",
            "Ecell_V",
            "Ttemp_type-S_C",
            "Ttemp_type-T_C",            
     ]

        # keeps track of the multi cell IV measurements in the background
        myloop = asyncio.get_event_loop()
        # add meas IOloop
        self.IOloop_run = False
        self.monitorloop_run = True
#        myloop.create_task(self.IOloop())  #if loop terminates immediately upon starting due to False, then
                                            #starting it here is useless? maybe have another loop inside it?
#        myloop.create_task(self.monitorloop())



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
#        self.task_6289cellcurrent = nidaqmx.Task()
        self.task_6289cellcurrent.ai_channels.add_ai_thrmcpl_chan(
#            physical_channel= 'type-S',
            physical_channel= 'PXI-6289/ai0',
            name_to_assign_to_channel="Temp_typeS",
            min_val=0,
            max_val=150,
            units=TemperatureUnits.DEG_C,
            thermocouple_type=ThermocoupleType.S,
#            cjc_source=CJCSource.BUILT_IN,
        )

        self.task_6284cellvoltage.ai_channels.add_ai_thrmcpl_chan(
 #           physical_channel= 'type-T',
            physical_channel= 'PXI-6284/ai0',
            name_to_assign_to_channel="Temp_typeT",
            min_val=0,
            max_val=150,
            units=TemperatureUnits.DEG_C,
            thermocouple_type=ThermocoupleType.T,
#            cjc_source=CJCSource.BUILT_IN,
        )


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

    def create_Ttask(self):
        """configures and starts a NImax task for nonexperiment temp measurements"""
        self.task_tempinst_S = nidaqmx.Task()
        self.task_tempinst_S.ai_channels.add_ai_thrmcpl_chan(
#           physical_channel= 'type-S',
            physical_channel= 'PXI-6289/ai2', 
            name_to_assign_to_channel="Temp_typeS",
            min_val=0,
            max_val=150,
            units=TemperatureUnits.DEG_C,
            thermocouple_type=ThermocoupleType.S,
            # cjc_source=CJCSource.CONSTANT_USER_VALUE,
            # cjc_val = 27,
            # cjc_source=CJCSource.SCANNABLE_CHANNEL,
            # cjc_channel= 'CJCtemp',
        )

        self.task_tempinst_S.ai_channels.all.ai_lowpass_enable = True
        self.task_tempinst_S.timing.cfg_samp_clk_timing(   #timing/triggering need
                                                         
            rate= 1,
#           self.Tsamplingrate,
            source="",
            active_edge=Edge.RISING,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=self.buffersize,
        )
        self.task_tempinst_T = nidaqmx.Task()
        self.task_tempinst_T.ai_channels.add_ai_thrmcpl_chan(
           # physical_channel= 'type-T',
            physical_channel= 'PXI-6284/ai2',   #temporary  cjc source ai channel instead of 2
            name_to_assign_to_channel="Temp_typeT",
            min_val=0,
            max_val=150,
            units=TemperatureUnits.DEG_C,
            thermocouple_type=ThermocoupleType.T,
            # cjc_source=CJCSource.CONSTANT_USER_VALUE,
            # cjc_val = 27,
            # cjc_source=CJCSource.SCANNABLE_CHANNEL,
            # cjc_channel = 'CJCtemp',
        )

        self.task_tempinst_T.ai_channels.all.ai_lowpass_enable = True
        self.task_tempinst_T.timing.cfg_samp_clk_timing(   #timing need?

            rate= 1,
#           self.Tsamplingrate,
            source="",
            active_edge=Edge.RISING,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=self.buffersize,
        )
        # self.task_tempCJC = nidaqmx.Task()
        # self.task_tempCJC.ai_channels.add_ai_temp_built_in_sensor_chan(
        #     physical_channel= 'PXI-6284/ai0',
        #     name_to_assign_to_channel="CJCtemp",
        #     units=TemperatureUnits.DEG_C,
        # )
#         self.task_tempCJC.ai_channels.all.ai_lowpass_enable = True
#         self.task_tempCJC.timing.cfg_samp_clk_timing(   #timing need?
#             rate= 1,
# #           self.Tsamplingrate,
#             source="",
#             active_edge=Edge.RISING,
#             sample_mode=AcquisitionType.CONTINUOUS,
#             samps_per_chan=self.buffersize,
#         )

        self.task_tempinst_S.start()
        self.task_tempinst_T.start()
#         self.task_tempCJC.start()
    def create_monitortask(self):
        """configures and starts a NImax task for nonexperiment temp measurements"""
        self.task_monitors = nidaqmx.Task()
        for myname, mydev in self.config_dict["dev_monitor"].items():
            #can add if filter for different types of monitors (other than Temp)
            print(myname)
            print('typek')
            TCtype=ThermocoupleType.K,
            if myname == "type-S":
                print('types')
                TCtype=ThermocoupleType.S,
            if myname == "type-T":
                print('typet')
                TCtype=ThermocoupleType.T,
#            else:
            self.task_monitors.ai_channels.add_ai_thrmcpl_chan(
                mydev,
                name_to_assign_to_channel="TC_" + myname,
                min_val=0,
                max_val=150,
                units=TemperatureUnits.DEG_C,
                thermocouple_type=TCtype,
                cjc_source=CJCSource.CONSTANT_USER_VALUE,
                cjc_val = 27,
                # cjc_source=CJCSource.SCANNABLE_CHANNEL,
                # cjc_channel= 'CJCtemp',
            )
        self.task_monitors.ai_channels.all.ai_lowpass_enable = True
        self.task_monitors.timing.cfg_samp_clk_timing(
            sampling_rate=1,
            source="",
            active_edge=Edge.RISING,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=self.buffersize,
        )
#        self.task_monitors.start()
    async def monitorloop(self):
        monitors=self.create_monitortask()
        self.task_monitors.start()
        while self.monitorloop_run:
            mvalues = self.task_monitors.read()
            print(mvalues)
 #           for i, myname in enumerate(self.config_dict["dev_monitor"].items()):
            for i, myname in enumerate(self.config_dict["dev_monitor"]):
                datastore = {myname : mvalues[i]}
            print(datastore)    
            await self.base.put_lbuf(datastore)
            time.sleep(1)    

    def streamIV_callback(
        self, task_handle, every_n_samples_event_type, number_of_samples, callback_data
    ):
        if self.IO_do_meas and not self.base.actionserver.estop:
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
                for i, myname in enumerate(self.config_dict["dev_monitor"].items()):
                    mdata[i], _ = self.base.get_lbuf(myname)    

                # this is also what NImax seems to do
                time = [
                    self.IVtimeoffset + i / self.samplingrate
                    for i in range(len(dataI[0]))
                ]
                # update timeoffset
                self.IVtimeoffset += number_of_samples / self.samplingrate

                data_dict = {}
                #T and S temp data out first is 8 when 7 cells (due to wiring) would be 10 if 9
                for i, FIFO_cell_key in enumerate(self.FIFO_cell_keys):
                    data_dict[self.file_conn_keys[i]] = {
                        f"{self.FIFO_column_headings[0]}": time,
                        f"{self.FIFO_column_headings[1]}": dataI[i],
                        f"{self.FIFO_column_headings[2]}": dataV[i],
                        f"{self.FIFO_column_headings[3]}": mdata[0],
                        f"{self.FIFO_column_headings[4]}": mdata[1],
                    }

                # push data to datalogger queue
                if self.active:
                    self.active.enqueue_data_nowait(
                        datamodel=DataModel(data=data_dict, errors=[])
                    )

            except Exception as e:
                tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                self.base.print_message(f"canceling NImax IV stream: {repr(e), tb,}", error=True)

        elif self.base.actionserver.estop and self.IO_do_meas:
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
            self.base.print_message(
                "meas was turned off but NImax IV task is still running ..."
            )
            #self.task_6289cellcurrent.close()
            #self.task_6284cellvoltage.close()

        return 0

    async def IOloop(self):
        """only monitors the status and keeps track of time for the
        multi cell iv task. This one will also handle estop, stop,
        finishes the active object etc."""
        self.IOloop_run = True    #could have another loop before that set of ifs?
        try:
            while self.IOloop_run:
                self.IO_do_meas = await self.IO_signalq.get()
                if self.IO_do_meas and not self.IO_measuring:
                    # are we in estop?
                    if not self.base.actionserver.estop:
                        self.base.print_message("NImax IV task got measurement request")

                        # start slave first
                        self.task_6284cellvoltage.start()
                        # then start master to trigger slave
                        self.task_6289cellcurrent.start()

                        # wait for first callback interrupt
                        while not self.IO_measuring:
                            await asyncio.sleep(0.1)
                        self.base.print_message("got IO_measuring", info=True)

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

                        self.base.print_message(
                            f"NImax IV finished with IO_do_meas {self.IO_do_meas}",
                            info=True,
                        )

                        # await self.IO_signalq.put(False)
                        self.IO_do_meas = False
                        self.IO_measuring = False
                        self.task_6289cellcurrent.close()
                        self.task_6284cellvoltage.close()
                        _ = await self.active.finish()
                        self.active = None
                        self.action = None
                        self.samples_in = []

                        if self.base.actionserver.estop:
                            self.base.print_message("NImax IV task is in estop.")
                        else:
                            self.base.print_message("setting NImax IV task to idle")
                        self.base.print_message("NImax IV task measurement is done")
                    else:
                        self.IO_do_meas = False
                        self.base.print_message("NImax IV task is in estop.")

                elif self.IO_do_meas and self.IO_measuring:
                    self.base.print_message(
                        "got measurement request but NImax IV task is busy"
                    )
                elif not self.IO_do_meas and self.IO_measuring:
                    self.base.print_message(
                        "got stop request, measurement will stop next cycle"
                    )
                else:
                    self.base.print_message(
                        "got stop request but NImax IV task is idle"
                    )

            self.base.print_message(f"IOloop got IOloop_run {self.IOloop_run}")

        except asyncio.CancelledError:
            self.base.print_message("IOloop task was cancelled")

    async def Heatloop(self, duration_h, reservoir1_min, reservoir1_max, reservoir2_min, reservoir2_max,):
        activeDict = {}

        # samplerate = A.action_params["SampleRate"]
        # duration = A.action_params["duration"] * 60 * 60  #time in hours
        # reservoir1_min = A.action_params["r1min"]
        # reservoir1_max = A.action_params["r1max"]
        # reservoir2_min = A.action_params["r2min"]
        # reservoir2_max = A.action_params["r2max"]

        """attempt maintain temperatures for the
        temp task. """
        duration = duration_h * 3600
        heatloopstarttime = time.time()       
        loopduration = time.time() - heatloopstarttime

        self.Heatloop_run = True
        mdata = {}
                                
        while (time.time() - heatloopstarttime < duration) and self.Heatloop_run:
            readtempdict = {}
            for i, myname in enumerate(self.config_dict["dev_monitor"].items()):
                print("myname" + myname)
                mdata[i], _ = self.base.get_lbuf(myname)
                print(mdata[i]) 
                readtempdict[myname] = mdata[i]
            temp_typeS = float(readtempdict["type-S"])
            temp_typeT = float(readtempdict["type-T"])
            for myheat, myport in self.dev_heat.items():
                if myheat == "heater1":
                    if temp_typeS < reservoir1_min:
                        await self.set_digital_out(do_port=myport, do_name=myheat, on=True)
                    if temp_typeS > reservoir1_max:
                        await self.set_digital_out(do_port=myport, do_name=myheat, on=False)
                if myheat == "heater2":
                    if temp_typeT < reservoir2_min:
                        await self.set_digital_out(do_port=myport, do_name=myheat, on=True)
                    if temp_typeT > reservoir2_max:
                        await self.set_digital_out(do_port=myport, do_name=myheat, on=False)
            time.sleep(1)
        return self.Heatloop_run

    async def set_digital_out(
        self, do_port=None, do_name: str = "", on: bool = False, *args, **kwargs
    ):
        self.base.print_message(f"do_port '{do_name}': {do_port} is {on}")
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
        self.base.print_message(f"di_port '{di_name}': {di_port}")
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
                self.base.print_message(
                    "NI got no valid sample, cannot start measurement!", error=True
                )
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
                        if len(self.samples_in) == 7:   #number of cells
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
        #activeDict = {}
        rtemp = {}
        mdata = {}
#        for i, myname in enumerate(self.config_dict["dev_monitor"].items()):
        for i, myname in enumerate(self.config_dict["dev_monitor"]):
            print(myname)
            mdata[i], _ = self.base.get_lbuf(myname) 
            print(mdata[i]) 
            rtemp[myname] = mdata[i]

#        rtemp["type-S"] = self.task_tempinst_S.read()
 #       print(rtemp)
#        rtemp["type-T"] = self.task_tempinst_T.read()        
#        print(rtemp)
        return rtemp

    def stop_Ttask(self):
        """stops instantaneous temp measurement"""
        self.Heatloop_run = False
#        self.task_tempinst_S.close()
#        self.task_tempinst_T.close()
        

    async def stop(self):
        """stops measurement, writes all data and returns from meas loop"""
        # turn off cell and run before stopping meas loop
        if self.IO_measuring:
            await self.set_IO_signalq(False)

    async def estop(self, switch: bool, *args, **kwargs):
        """same as estop, but also sets flag"""
        switch = bool(switch)
        self.base.actionserver.estop = switch

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
                    await self.active.set_estop()

        return switch

    def shutdown(self):
        self.base.print_message("shutting down nidaqmx")
        self.set_IO_signalq_nowait(False)
        retries = 0
        while self.active is not None and retries < 10:
            self.base.print_message(
                f"Got shutdown, but Active is not yet done!, retry {retries}",
                info=True,
            )
            # set it again
            self.set_IO_signalq_nowait(False)
            time.sleep(1)
            retries += 1
        # stop IOloop and monitorloop
        self.monitorloop_run = False
        self.IOloop_run = False

    def tasklist(self):
        system = nidaqmx.system.System.local()
        task_names = system.tasks.task_names
        print(task_names)
        return task_names