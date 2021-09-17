from enum import Enum
import time
from typing import List
import asyncio
import pyaml

import nidaqmx
from nidaqmx.constants import LineGrouping
from nidaqmx.constants import Edge
from nidaqmx.constants import AcquisitionType
from nidaqmx.constants import TerminalConfiguration
from nidaqmx.constants import VoltageUnits
from nidaqmx.constants import CurrentShuntResistorLocation
from nidaqmx.constants import UnitsPreScaled
from nidaqmx.constants import TriggerType

from helao.core.schema import Action
from helao.core.server import Base
from helao.core.error import error_codes


class pumpitems(str, Enum):
    PeriPump = "PeriPump"
    # MultiPeriPump = 'MultiPeriPump'
    Direction = "Direction"


class cNIMAX:

    def __init__(self, actServ: Base):
        
        self.base = actServ
        self.config_dict = actServ.server_cfg["params"]
        self.world_config = actServ.world_cfg


        self.base.print_message(" ... init NI-MAX")

        self.action = None  # for passing action object from technique method to measure loop
        self.active = None  # for holding active action object, clear this at end of measurement
        self.samples_in = []

        # seems to work by just defining the scale and then only using its name
        try:
            self.Iscale = nidaqmx.scale.Scale.create_lin_scale(
                "NEGATE3", -1.0, 0.0, UnitsPreScaled.AMPS, "AMPS"
            )
        except Exception as e:
            self.base.print_message(" ... NImax error", error = True)
            raise e
        self.time_stamp = time.time()

        # this defines the time axis, need to calculate our own
        self.samplingrate = 10  # samples per second
        # used to keep track of time during data readout
        self.IVtimeoffset = 0.0
        self.buffersize = 1000  # finite samples or size of buffer depending on mode
        self.duration = 10 #sec
        self.ttlwait = -1
        self.buffersizeread = int(self.samplingrate)
        self.IOloopstarttime = 0


        self.IO_signalq = asyncio.Queue(1)
        self.task_CellCurrent = None
        self.task_CellVoltage = None
        self.IO_do_meas = False  # signal flag for intent (start/stop)
        self.IO_measuring = False  # status flag of measurement
        self.IO_estop = False
        self.activeCell = [False for _ in range(9)]
        

        self.FIFO_epoch = None
        # self.FIFO_header = ''
        self.FIFO_NImaxheader = dict()
        self.FIFO_name = ""
        self.FIFO_dir = ""
        self.FIFO_sample_keys = [
            "cell1",
            "cell2",
            "cell3",
            "cell4",
            "cell5",
            "cell6",
            "cell7",
            "cell8",
            "cell9",
        ]
        self.FIFO_column_headings = dict()
        for FIFO_sample_key in self.FIFO_sample_keys:
            self.FIFO_column_headings[FIFO_sample_key] = [
                "t_s",
                "Icell_A",
                "Ecell_V",
                ]
        

        # keeps track of the multi cell IV measurements in the background        
        myloop = asyncio.get_event_loop()
        # add meas IOloop
        myloop.create_task(self.IOloop())


    def create_IVtask(self):
        """configures a NImax task for multi cell IV measurements"""
        # Voltage reading is MASTER
        self.task_CellCurrent = nidaqmx.Task()
        for myname, mydev in self.config_dict["dev_CellCurrent"].items():
            self.task_CellCurrent.ai_channels.add_ai_current_chan(
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
        self.task_CellCurrent.ai_channels.all.ai_lowpass_enable = True
        self.task_CellCurrent.timing.cfg_samp_clk_timing(
            self.samplingrate,
            source="",
            active_edge=Edge.RISING,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=self.buffersize,
        )
        # TODO can increase the callbackbuffersize if needed
        # self.task_CellCurrent.register_every_n_samples_acquired_into_buffer_event(10,self.streamCURRENT_callback)
        self.task_CellCurrent.register_every_n_samples_acquired_into_buffer_event(
            self.buffersizeread, self.streamIV_callback
        )

        # Voltage reading is SLAVE
        # we cannot combine both tasks into one as they run on different DAQs
        # define the VOLT and CURRENT task as they need to stay in memory
        self.task_CellVoltage = nidaqmx.Task()
        for myname, mydev in self.config_dict["dev_CellVoltage"].items():
            self.task_CellVoltage.ai_channels.add_ai_voltage_chan(
                mydev,
                name_to_assign_to_channel="Cell_" + myname,
                terminal_config=TerminalConfiguration.DIFFERENTIAL,
                min_val=-10.0,
                max_val=+10.0,
                units=VoltageUnits.VOLTS,
            )

        # does this globally enable lowpass or only for channels in task?
        self.task_CellVoltage.ai_channels.all.ai_lowpass_enable = True
        # self.task_CellVoltage.ai_lowpass_enable = True
        self.task_CellVoltage.timing.cfg_samp_clk_timing(
            self.samplingrate,
            source="",
            active_edge=Edge.RISING,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=self.buffersize,
        )
        
        # each card need its own physical trigger input
        if (
            self.config_dict["dev_CellVoltage_trigger"] != ""
            and self.config_dict["dev_CellCurrent_trigger"] != ""
            and self.ttlwait != -1
        ):
            self.task_CellVoltage.triggers.start_trigger.trig_type = (
                TriggerType.DIGITAL_EDGE
            )
            self.task_CellVoltage.triggers.start_trigger.cfg_dig_edge_start_trig(
                trigger_source=self.config_dict["dev_CellVoltage_trigger"],
                trigger_edge=Edge.RISING,
            )

            self.task_CellCurrent.triggers.start_trigger.trig_type = (
                TriggerType.DIGITAL_EDGE
            )
            self.task_CellCurrent.triggers.start_trigger.cfg_dig_edge_start_trig(
                trigger_source=self.config_dict["dev_CellCurrent_trigger"],
                trigger_edge=Edge.RISING,
            )


    def streamIV_callback(
        self, task_handle, every_n_samples_event_type, number_of_samples, callback_data
    ):
        if self.IO_do_meas and not self.IO_estop:
            try:
                self.IO_measuring = True

                if self.FIFO_epoch is None:
                    self.FIFO_epoch = self.active.set_realtime_nowait()
                    # need to correct for the first datapoints 
                    self.FIFO_epoch -= number_of_samples / self.samplingrate
                    if self.active:
                        if self.active.action.save_data:
                            self.active.finish_hlo_header(realtime=self.FIFO_epoch)

                
                # start seq: V then current, so read current first then Volt
                # put callback only on current (Volt should the always have enough points)
                # readout is requested-1 when callback is on requested
                dataI = self.task_CellCurrent.read(
                    number_of_samples_per_channel=number_of_samples
                )
                dataV = self.task_CellVoltage.read(
                    number_of_samples_per_channel=number_of_samples
                )
                # this is also what NImax seems to do
                time = [
                    self.IVtimeoffset + i / self.samplingrate
                    for i in range(len(dataI[0]))
                ]
                # update timeoffset
                self.IVtimeoffset += number_of_samples / self.samplingrate


                data_dict = dict()
                for i,FIFO_sample_key in enumerate(self.FIFO_sample_keys):
                    data_dict[FIFO_sample_key] = {
                        f"{self.FIFO_column_headings[FIFO_sample_key][0]}":time,
                        f"{self.FIFO_column_headings[FIFO_sample_key][1]}":dataI[i],
                        f"{self.FIFO_column_headings[FIFO_sample_key][2]}":dataV[i],
                        }

                # push data to datalogger queue
                if self.active:
                    if self.active.action.save_data:
                        self.active.enqueue_data_nowait(
                            data_dict,
                            file_sample_keys = self.FIFO_sample_keys
                        )

            except Exception:
                self.base.print_message(" ... canceling NImax IV stream")

        elif self.IO_estop and self.IO_do_meas:
            _ = self.task_CellCurrent.read(
                number_of_samples_per_channel=number_of_samples
            )
            _ = self.task_CellVoltage.read(
                number_of_samples_per_channel=number_of_samples
            )
            self.IO_measuring = False
            self.task_CellCurrent.close()
            self.task_CellVoltage.close()

        else:
            # NImax has data but measurement was already turned off
            # just pull data from buffer and turn task off
            _ = self.task_CellCurrent.read(
                number_of_samples_per_channel=number_of_samples
            )
            _ = self.task_CellVoltage.read(
                number_of_samples_per_channel=number_of_samples
            )
            # task should be already off or should be closed soon
            self.base.print_message(" ... meas was turned off but NImax IV task is still running ...")
            # self.task_CellCurrent.close()
            # self.task_CellVoltage.close()

        return 0


    async def IOloop(self):
        """only monitors the status and keeps track of time for the 
        multi cell iv task. This one will also handle estop, stop,
        finishes the active object etc."""
        try:
            while True:
                self.IO_do_meas = await self.IO_signalq.get()
                if self.IO_do_meas and not self.IO_measuring:
                    # are we in estop?
                    if not self.IO_estop:
                        self.base.print_message(" ... NImax IV task got measurement request")


                        # start slave first
                        self.task_CellVoltage.start()
                        # then start master to trigger slave
                        self.task_CellCurrent.start()


                        # wait for first callback interrupt 
                        while not self.IO_measuring:
                            await asyncio.sleep(0.5)

                        # get timecode and correct for offset from first interrupt
                        self.IOloopstarttime = time.time()#-self.buffersizeread/self.samplingrate 

                        while (time.time() - self.IOloopstarttime < self.duration) and self.IO_do_meas:
                            if not self.IO_signalq.empty():
                                self.IO_do_meas = await self.IO_signalq.get()
                            await asyncio.sleep(1.0)


                        # await self.IO_signalq.put(False)
                        self.IO_do_meas = False
                        self.IO_measuring = False
                        self.task_CellCurrent.close()
                        self.task_CellVoltage.close()
                        _ = await self.active.finish()
                        self.active = None
                        self.action = None
                        self.samples_in = []


                        if self.IO_estop:
                            self.base.print_message(" ... NImax IV task is in estop.")
                            # await self.stat.set_estop()
                        else:
                            self.base.print_message(" ... setting NImax IV task to idle")
                            # await self.stat.set_idle()
                        self.base.print_message(" ... NImax IV task measurement is done")
                    else:
                        self.IO_do_meas = False
                        self.base.print_message(" ... NImax IV task is in estop.")
                        # await self.stat.set_estop()
                elif self.IO_do_meas and self.IO_measuring:
                    self.base.print_message(" ... got measurement request but NImax IV task is busy")
                elif not self.IO_do_meas and self.IO_measuring:
                    self.base.print_message(" ... got stop request, measurement will stop next cycle")
                else:
                    self.base.print_message(" ... got stop request but NImax IV task is idle")
        except asyncio.CancelledError:
            self.base.print_message("IOloop task was cancelled")


    async def run_task_getFSW(self, FSW:str):
        with nidaqmx.Task() as task_FSW:
            if FSW in self.config_dict["dev_FSW"].keys():
                task_FSW.di_channels.add_di_chan(
                    self.config_dict["dev_FSW"][FSW],
                    line_grouping=LineGrouping.CHAN_PER_LINE,
                )
                data = task_FSW.read(number_of_samples_per_channel=1)
                return {"name": [FSW], "status": data}


    async def run_task_FSWBCD(self, BCDs:str, on:bool,*args,**kwargs):
        on = bool(on)
        cmds = []
        with nidaqmx.Task() as task_FSWBCD:
            for BCD in BCDs:
                if BCD in self.config_dict["dev_FSWBCDCmd"].keys():
                    task_FSWBCD.do_channels.add_do_chan(
                        self.config_dict["dev_FSWBCDCmd"][BCD],
                        line_grouping=LineGrouping.CHAN_FOR_ALL_LINES,
                    )
                    cmds.append(on)
            if cmds:
                task_FSWBCD.write(cmds)
                return {"err_code": error_codes.none}
            else:
                return {"err_code": error_codes.not_available}


    async def run_task_Pump(self, pump:pumpitems, on:bool,*args,**kwargs):
        self.base.print_message(" ... NIMAX pump:", pump, on)
        on = bool(on)
        cmds = []
        with nidaqmx.Task() as task_Pumps:
            # for pump in pumps:
            if pump in self.config_dict["dev_Pumps"].keys():
                task_Pumps.do_channels.add_do_chan(
                    self.config_dict["dev_Pumps"][pump],
                    line_grouping=LineGrouping.CHAN_FOR_ALL_LINES,
                )
                cmds.append(on)
            if cmds:
                task_Pumps.write(cmds)
                return {"err_code": error_codes.none}
            else:
                return {"err_code": error_codes.not_available}


    async def run_task_GasFlowValves(self, valves:List[int], on:bool,*args,**kwargs):
        on = bool(on)
        cmds = []
        with nidaqmx.Task() as task_GasFlowValves:
            for valve in valves:
                if valve in self.config_dict["dev_GasFlowValves"].keys():
                    task_GasFlowValves.do_channels.add_do_chan(
                        self.config_dict["dev_GasFlowValves"][valve],
                        line_grouping=LineGrouping.CHAN_FOR_ALL_LINES,
                    )
                    cmds.append(on)
            if cmds:
                task_GasFlowValves.write(cmds)
                return {"err_code": error_codes.none}
            else:
                return {"err_code": error_codes.not_available}


    async def run_task_Master_Cell_Select(self, cells:List[int], on: bool,*args,**kwargs):
        on = bool(on)
        if len(cells) > 1:
            self.base.print_message(
                " ... Multiple cell selected. Only one can be Master cell. Using first one!"
            )
            self.base.print_message(cells)
            cells = [cells[0]]
            self.base.print_message(cells)
        cmds = []
        with nidaqmx.Task() as task_MasterCell:
            for cell in cells:
                if cell in self.config_dict["dev_MasterCellSelect"].keys():
                    task_MasterCell.do_channels.add_do_chan(
                        self.config_dict["dev_MasterCellSelect"][cell],
                        line_grouping=LineGrouping.CHAN_FOR_ALL_LINES,
                    )
                    cmds.append(on)
            if cmds:
                task_MasterCell.write(cmds)
                return {"err_code": error_codes.none}
            else:
                return {"err_code": error_codes.not_available}


    async def run_task_Active_Cells_Selection(self, cells:List[int], on:bool,*args,**kwargs):
        on = bool(on)
        cmds = []
        with nidaqmx.Task() as task_ActiveCell:
            for cell in cells:
                if cell in self.config_dict["dev_ActiveCellsSelection"].keys():
                    task_ActiveCell.do_channels.add_do_chan(
                        self.config_dict["dev_ActiveCellsSelection"][cell],
                        line_grouping=LineGrouping.CHAN_FOR_ALL_LINES,
                    )
                    cmds.append(on)

                self.activeCell[int(cell) - 1] = on


            if cmds:
                task_ActiveCell.write(cmds)
                return {"err_code": error_codes.none}
            else:
                return {"err_code": error_codes.not_available}


    async def run_cell_IV(self, A: Action):
        activeDict = dict()
        
        samplerate = A.action_params["SampleRate"]
        duration = A.action_params["Tval"]
        ttlwait = A.action_params["TTLwait"] # -1 disables, else select TTL channel
        
        err_code = error_codes.none
        if not self.IO_do_meas:
            self.samplingrate = samplerate
            self.duration = duration
            self.ttlwait = ttlwait
            self.buffersizeread = int(self.samplingrate)
            # save submitted action object
            self.action = A
            self.samples_in = A.get_sample_in()
            self.FIFO_epoch = None
            # create active and write streaming file header
            
            self.FIFO_NImaxheader = dict()
            file_sample_label = dict()
                
            for i, FIFO_sample_key in enumerate(self.FIFO_sample_keys):
                self.FIFO_NImaxheader[FIFO_sample_key] = {
                    # "version":0.2,
                    "technique_name":"multi_cell_IV",
                    "column_headings":self.FIFO_column_headings[FIFO_sample_key]
                    }
                if len(self.samples_in) == 9:
                    sample_label = self.base.create_file_sample_label(self.samples_in[i])
                else:
                    sample_label = self.base.create_file_sample_label(self.samples_in)
                file_sample_label[FIFO_sample_key]=sample_label
                
            self.active = await self.base.contain_action(
                self.action,
                file_type="ni_helao__file",
                file_group="helao_files",
                file_data_keys=self.FIFO_column_headings,
                file_sample_keys = self.FIFO_sample_keys,
                file_sample_label=file_sample_label,
                header=self.FIFO_NImaxheader,
            )
            await self.active.append_sample(self.samples_in)

            self.base.print_message(f"!!! Active action uuid is {self.active.action.action_uuid}")

            # create the cell IV task
            self.create_IVtask()
            
            await self.IO_signalq.put(True)

            err_code = error_codes.none

            if self.active:
                activeDict = self.active.action.as_dict()
            else:
                activeDict = A.as_dict()

        else:
            activeDict = A.as_dict()
            err_code = error_codes.in_progress

        activeDict["data"] = {"err_code": err_code}
        return activeDict


    async def stop(self):
        """stops measurement, writes all data and returns from meas loop"""
        # turn off cell and run before stopping meas loop
        if self.IO_measuring:
            await self.IO_signalq.put(False)


    async def estop(self, switch:bool,*args,**kwargs):
        """same as estop, but also sets flag"""
        switch = bool(switch)
        self.IO_estop = switch
        if self.IO_measuring:
            if switch:
                await self.IO_signalq.put(False)
                await self.base.set_estop(
                    self.active.active.action_name, self.active.active.action_uuid
                )
