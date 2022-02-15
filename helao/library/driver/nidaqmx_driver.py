
__all__ = ["cNIMAX"]

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

from helaocore.schema import Action
from helaocore.server import Base
from helaocore.error import error_codes
from helaocore.helper import make_str_enum
from helaocore.data.sample import UnifiedSampleDataAPI
from helaocore.model.sample import SampleInheritance, SampleStatus, NoneSample
from helaocore.model.file import FileConnParams, HloHeaderModel
from helaocore.model.active import ActiveParams
from helaocore.model.data import DataModel


class cNIMAX:

    def __init__(self, action_serv: Base):
        
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.world_config = action_serv.world_cfg

        self.unified_db = UnifiedSampleDataAPI(self.base)
        asyncio.gather(self.unified_db.init_db())

        self.dev_pump = self.config_dict.get("dev_pump",dict())
        self.dev_pumpitems = make_str_enum("dev_pump",{key:key for key in self.dev_pump})
        
        self.dev_gasvalve = self.config_dict.get("dev_gasvalve",dict())
        self.dev_gasvalveitems = make_str_enum("dev_gasvalve",{key:key for key in self.dev_gasvalve})
        
        self.dev_liquidvalve = self.config_dict.get("dev_liquidvalve",dict())
        self.dev_liquidvalveitems = make_str_enum("dev_liquidvalve",{key:key for key in self.dev_liquidvalve})

        self.base.print_message("init NI-MAX")

        self.action = None  # for passing action object from technique method to measure loop
        self.active = None  # for holding active action object, clear this at end of measurement
        self.samples_in = []

        # seems to work by just defining the scale and then only using its name
        try:
            self.Iscale = nidaqmx.scale.Scale.create_lin_scale(
                "NEGATE3", -1.0, 0.0, UnitsPreScaled.AMPS, "AMPS"
            )
        except Exception as e:
            self.base.print_message("NImax error", error = True)
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
        self.task_cellcurrent = None
        self.task_cellvoltage = None
        self.IO_do_meas = False  # signal flag for intent (start/stop)
        self.IO_measuring = False  # status flag of measurement
        self.activeCell = [False for _ in range(9)]
        

        self.FIFO_epoch = None
        # self.FIFO_header = ''
        self.FIFO_NImaxheader = dict()
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
            "cell8",
            "cell9",
        ]
        self.file_conn_keys = []
        self.FIFO_column_headings = [
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
        self.task_cellcurrent = nidaqmx.Task()
        for myname, mydev in self.config_dict["dev_cellcurrent"].items():
            self.task_cellcurrent.ai_channels.add_ai_current_chan(
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
        self.task_cellcurrent.ai_channels.all.ai_lowpass_enable = True
        self.task_cellcurrent.timing.cfg_samp_clk_timing(
            self.samplingrate,
            source="",
            active_edge=Edge.RISING,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=self.buffersize,
        )
        # TODO can increase the callbackbuffersize if needed
        # self.task_cellcurrent.register_every_n_samples_acquired_into_buffer_event(10,self.streamCURRENT_callback)
        self.task_cellcurrent.register_every_n_samples_acquired_into_buffer_event(
            self.buffersizeread, self.streamIV_callback
        )

        # Voltage reading is SLAVE
        # we cannot combine both tasks into one as they run on different DAQs
        # define the VOLT and CURRENT task as they need to stay in memory
        self.task_cellvoltage = nidaqmx.Task()
        for myname, mydev in self.config_dict["dev_cellvoltage"].items():
            self.task_cellvoltage.ai_channels.add_ai_voltage_chan(
                mydev,
                name_to_assign_to_channel="Cell_" + myname,
                terminal_config=TerminalConfiguration.DIFFERENTIAL,
                min_val=-10.0,
                max_val=+10.0,
                units=VoltageUnits.VOLTS,
            )

        # does this globally enable lowpass or only for channels in task?
        self.task_cellvoltage.ai_channels.all.ai_lowpass_enable = True
        # self.task_cellvoltage.ai_lowpass_enable = True
        self.task_cellvoltage.timing.cfg_samp_clk_timing(
            self.samplingrate,
            source="",
            active_edge=Edge.RISING,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=self.buffersize,
        )
        
        # each card need its own physical trigger input
        if (
            self.config_dict["dev_cellvoltage_trigger"] != ""
            and self.config_dict["dev_cellcurrent_trigger"] != ""
            and self.ttlwait != -1
        ):
            self.task_cellvoltage.triggers.start_trigger.trig_type = (
                TriggerType.DIGITAL_EDGE
            )
            self.task_cellvoltage.triggers.start_trigger.cfg_dig_edge_start_trig(
                trigger_source=self.config_dict["dev_cellvoltage_trigger"],
                trigger_edge=Edge.RISING,
            )

            self.task_cellcurrent.triggers.start_trigger.trig_type = (
                TriggerType.DIGITAL_EDGE
            )
            self.task_cellcurrent.triggers.start_trigger.cfg_dig_edge_start_trig(
                trigger_source=self.config_dict["dev_cellcurrent_trigger"],
                trigger_edge=Edge.RISING,
            )


    def streamIV_callback(
        self, task_handle, every_n_samples_event_type, number_of_samples, callback_data
    ):
        if self.IO_do_meas and not self.base.actionserver.estop:
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
                dataI = self.task_cellcurrent.read(
                    number_of_samples_per_channel=number_of_samples
                )
                dataV = self.task_cellvoltage.read(
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
                for i,FIFO_cell_key in enumerate(self.FIFO_cell_keys):
                    data_dict[self.file_conn_keys[i]] = {
                        f"{self.FIFO_column_headings[0]}":time,
                        f"{self.FIFO_column_headings[1]}":dataI[i],
                        f"{self.FIFO_column_headings[2]}":dataV[i],
                        }

                # push data to datalogger queue
                if self.active:
                    self.active.enqueue_data_nowait(datamodel = \
                           DataModel(
                                     data = data_dict,
                                     errors = []
                                    )
                    )

            except Exception:
                self.base.print_message("canceling NImax IV stream")

        elif self.base.actionserver.estop and self.IO_do_meas:
            _ = self.task_cellcurrent.read(
                number_of_samples_per_channel=number_of_samples
            )
            _ = self.task_cellvoltage.read(
                number_of_samples_per_channel=number_of_samples
            )
            self.IO_measuring = False
            self.task_cellcurrent.close()
            self.task_cellvoltage.close()

        else:
            # NImax has data but measurement was already turned off
            # just pull data from buffer and turn task off
            _ = self.task_cellcurrent.read(
                number_of_samples_per_channel=number_of_samples
            )
            _ = self.task_cellvoltage.read(
                number_of_samples_per_channel=number_of_samples
            )
            # task should be already off or should be closed soon
            self.base.print_message("meas was turned off but NImax IV task is still running ...")
            # self.task_cellcurrent.close()
            # self.task_cellvoltage.close()

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
                    if not self.base.actionserver.estop:
                        self.base.print_message("NImax IV task got measurement request")


                        # start slave first
                        self.task_cellvoltage.start()
                        # then start master to trigger slave
                        self.task_cellcurrent.start()


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
                        self.task_cellcurrent.close()
                        self.task_cellvoltage.close()
                        _ = await self.active.finish()
                        self.active = None
                        self.action = None
                        self.samples_in = []


                        if self.base.actionserver.estop:
                            self.base.print_message("NImax IV task is in estop.")
                            # await self.stat.set_estop()
                        else:
                            self.base.print_message("setting NImax IV task to idle")
                            # await self.stat.set_idle()
                        self.base.print_message("NImax IV task measurement is done")
                    else:
                        self.IO_do_meas = False
                        self.base.print_message("NImax IV task is in estop.")
                        # await self.stat.set_estop()
                elif self.IO_do_meas and self.IO_measuring:
                    self.base.print_message("got measurement request but NImax IV task is busy")
                elif not self.IO_do_meas and self.IO_measuring:
                    self.base.print_message("got stop request, measurement will stop next cycle")
                else:
                    self.base.print_message("got stop request but NImax IV task is idle")
        except asyncio.CancelledError:
            self.base.print_message("IOloop task was cancelled")


    async def set_digital_out(self, 
                          do_port = None, 
                          do_name: str = "", 
                          on:bool = False,
                          *args,**kwargs
                         ):
        self.base.print_message(f"do_port '{do_name}': {do_port} is {on}")
        on = bool(on)
        cmds = []
        err_code = error_codes.none
        if do_port is not None:
            with nidaqmx.Task() as task_do_port:
                # for pump in pumps:
                task_do_port.do_channels.add_do_chan(do_port,
                    line_grouping=LineGrouping.CHAN_FOR_ALL_LINES,
                )
                cmds.append(on)
                if cmds:
                    task_do_port.write(cmds)
                    err_code = error_codes.none
                else:
                    err_code = error_codes.not_available
        else:
            err_code = error_codes.not_available

        return {
                "error_code": err_code,
                "port": do_port,
                "name": do_name,
                "type": "digital_out",
                "value": on
               }

    async def get_digital_in(self, 
                          di_port = None, 
                          di_name: str = "", 
                          on:bool = False,
                          *args,**kwargs
                         ):
        self.base.print_message(f"di_port '{di_name}': {di_port}")
        on = None
        err_code = error_codes.none
        if di_port is not None:
            with nidaqmx.Task() as task_di_port:

                task_di_port.di_channels.add_di_chan(
                    di_port,
                    line_grouping=LineGrouping.CHAN_PER_LINE,
                )
                on = task_di_port.read(number_of_samples_per_channel=1)
        else:
            err_code = error_codes.not_available

        return {
                "error_code": err_code,
                "port": di_port,
                "name": di_name,
                "type": "digital_in",
                "value": on
               }


    async def run_cell_IV(self, A: Action):
        activeDict = dict()
        
        samplerate = A.action_params["SampleRate"]
        duration = A.action_params["Tval"]
        ttlwait = A.action_params["TTLwait"] # -1 disables, else select TTL channel
        
        err_code = error_codes.none
        if not self.IO_do_meas:
            self.IVtimeoffset = 0.0
            self.file_conn_keys = []
            self.samplingrate = samplerate
            self.duration = duration
            self.ttlwait = ttlwait
            self.buffersizeread = int(self.samplingrate)
            # save submitted action object
            self.action = A
            self.samples_in = await self.unified_db.get_sample(self.action.samples_in)
            self.FIFO_epoch = None
            # create active and write streaming file header
            
            self.FIFO_NImaxheader = dict()
            file_sample_label = dict()
            file_sample_list = []

            for sample in self.samples_in:
                sample.status = [SampleStatus.preserved]
                sample.inheritance = SampleInheritance.allow_both

            for i, FIFO_cell_key in enumerate(self.FIFO_cell_keys):
                if self.samples_in is not None:
                    if len(self.samples_in) == 9:
                        file_sample_list.append([self.samples_in[i]])
                        sample_label = [self.samples_in[i].get_global_label()]
                    else:
                        file_sample_list.append(self.samples_in)
                        sample_label = [sample.get_global_label() for sample in self.samples_in]
                else:
                    file_sample_list.append([])
                    sample_label = None
                file_sample_label[FIFO_cell_key]=sample_label


            # create the first action and then split it into child actions
            # for the other data streams
            self.file_conn_keys.append(self.base.dflt_file_conn_key())
            self.active =  await self.base.contain_action(
                ActiveParams(
                             action = self.action,
                             file_conn_params_dict = {self.base.dflt_file_conn_key():
                                 FileConnParams(
                                                file_conn_key = \
                                                    self.base.dflt_file_conn_key(),
                                                sample_global_labels=file_sample_label[self.FIFO_cell_keys[0]],
                                                json_data_keys = self.FIFO_column_headings,
                                                file_type="ni_helao__file",
                                                # only add optional keys to header
                                                # rest will be added later
                                                hloheader = HloHeaderModel(
                                                    optional = {"cell":self.FIFO_cell_keys[0]})
                                               )
                                     }

                )
            )
            # clear old samples_in first
            self.active.action.samples_in = []
            # now add updated samples to sample_in again
            await self.active.append_sample(samples = file_sample_list[0],
                                            IO="in"
                                           )

            # now add the rest
            for i in range(len(self.FIFO_cell_keys)-1):
                new_file_conn_keys = await self.active.split(new_fileconnparams = 
                    FileConnParams(
                                   file_conn_key = \
                                       self.base.dflt_file_conn_key(),
                                   sample_global_labels=\
                                       file_sample_label[self.FIFO_cell_keys[i+1]],
                                   json_data_keys = self.FIFO_column_headings,
                                   file_type="ni_helao__file",
                                   # only add optional keys to header
                                   # rest will be added later
                                   hloheader = HloHeaderModel(
                                       optional = {"cell":self.FIFO_cell_keys[i+1]})
                                  )
                )
                # add the new file_conn_key to the list
                if new_file_conn_keys:
                    self.file_conn_keys.append(new_file_conn_keys[0])

                # clear old samples_in first
                self.active.action.samples_in = []
                    
                # now add updated samples to sample_in again
                await self.active.append_sample(samples = file_sample_list[i+1],
                                                IO="in"
                                               )

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


    async def estop(self, switch:bool, *args, **kwargs):
        """same as estop, but also sets flag"""
        switch = bool(switch)
        self.base.actionserver.estop = switch
        if self.IO_measuring:
            if switch:
                await self.IO_signalq.put(False)
                if self.active:
                    await self.active.set_estop()
        return switch
