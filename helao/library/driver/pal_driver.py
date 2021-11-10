
__all__ = ["Spacingmethod",
           "PALtools",
           "cPAL"]

from enum import Enum
import asyncio
import os
import paramiko
import time
from datetime import datetime
from time import strftime
import json
import aiofiles
import copy
import pyaml
from typing import Optional, List, Union
# from socket import gethostname
from pydantic import BaseModel
from pydantic import validator
# from typing import List
# import pickle
# import re

from helaocore.schema import cProcess
from helaocore.server import Base
from helaocore.error import error_codes
from helao.library.driver.HTEdata_legacy import LocalDataHandler
# from helaocore.data import LiquidSampleAPI, OldLiquidSampleAPI

import helaocore.data as hcd
import helaocore.model.sample as hcms
from helao.library.driver.archive_driver import Archive

import nidaqmx
from nidaqmx.constants import LineGrouping


class _cam(BaseModel):
    name: str = None
    file_name: str = None
    file_path: str = None
    sample_type: str = None
    ttl_start: bool = False
    ttl_continue: bool = False
    ttl_done: bool = False

    source:str = None
    dest:str = None


class _sourcedest(str, Enum):
    tray = "tray"
    custom = "custom"
    next_empty_vial = "next_empty_vial"
    next_full_vial = "next_full_vial"



class _palcmd(BaseModel):
    method: str = ""
    params: str = ""

class _sampletype(str, Enum):
    liquid = "liquid"
    gas = "gas"
    solid = "solid"
    assembly = "assembly"


class CAMS(Enum):
    archive_liquid = _cam(name="archive_liquid",
                          file_name = "lcfc_archive.cam", # from config later
                          sample_type = _sampletype.liquid,
                          source = _sourcedest.custom,
                          dest = _sourcedest.next_empty_vial,
                         )


    archive = _cam(name="archive",
                   file_name = "lcfc_archive.cam", # from config later
                   sample_type = _sampletype.liquid,
                   source = _sourcedest.custom,
                   dest = _sourcedest.next_empty_vial,
                  )


    fillfixed = _cam(name="fillfixed",
                      file_name = "lcfc_fill_hardcodedvolume.cam", # from config later
                      sample_type = _sampletype.liquid,
                      source = _sourcedest.custom,
                      dest = _sourcedest.custom,
                    )
    
    fill = _cam(name="fill",
                file_name = "lcfc_fill.cam", # from config later
                sample_type = _sampletype.liquid,
                source = _sourcedest.custom,
                dest = _sourcedest.next_empty_vial,
             )

    test = _cam(name="test",
                file_name = "relay_actuation_test2.cam", # from config later
               )

    autodilute = _cam(name="autodilute",
                  file_name = "lcfc_dilute.cam", # from config later
                  sample_type = _sampletype.liquid,
                  source = _sourcedest.custom,
                  dest = _sourcedest.next_full_vial,
                 )

    dilute = _cam(name="dilute",
                  file_name = "lcfc_dilute.cam", # from config later
                  sample_type = _sampletype.liquid,
                  source = _sourcedest.custom,
                  dest = _sourcedest.tray,
                 )

    deepclean = _cam(name="deepclean",
                     file_name = "lcfc_deep_clean.cam", # from config later
                    )

    none = _cam(name="",
                file_name = "",
               )


class Spacingmethod(str, Enum):
    linear = "linear" # 1, 2, 3, 4, 5, ...
    geometric = "gemoetric" # 1, 2, 4, 8, 16
    custom = "custom"
#    power = "power"
#    exponential = "exponential"

class PALtools(str, Enum):
    LS1 = "LS1"
    LS2 = "LS2"
    LS3 = "LS3"



class MicroPalParams(BaseModel):
    PAL_sample_in: List[hcms.SampleList] = []
    # this initially always holds references which need to be converted to 
    # to a real sample later
    PAL_sample_out: List[hcms.SampleList] = []
    


    PAL_method: str = None # names of methods
    PAL_tool: str = None 
    PAL_volume_uL: int = 0  # uL

    PAL_dest: str = None  # dest can be cust. or tray
    PAL_dest_sample: List[hcms.SampleList] = []
    PAL_dest_tray: Union[List[int], int] = []
    PAL_dest_slot: Union[List[int], int] = []
    PAL_dest_vial: Union[List[int], int] = []
    PAL_source: str = None  # source can be cust. or tray
    PAL_source_sample: List[hcms.SampleList] = []
    PAL_source_tray: Union[List[int], int] = []
    PAL_source_slot: Union[List[int], int] = []
    PAL_source_vial: Union[List[int], int] = []
    PAL_wash1: bool = False
    PAL_wash2: bool = False
    PAL_wash3: bool = False
    PAL_wash4: bool = False

    # I probably don't need them as lists but can keep it for now
    PAL_start_time: int = None
    PAL_continue_time: int = None
    PAL_done_time: int = None

    PAL_path_methodfile: str = "" # all shoukld be in the same folder
    PAL_rshs_pal_logfile: str = "" # one PAL action logs into one logfile
    cam:_cam = _cam()
    repeat:int = 0
    dilute:bool = False


    @validator("PAL_dest_tray",
               "PAL_dest_slot",
               "PAL_dest_vial",
               "PAL_source_tray",
               "PAL_source_slot",
               "PAL_source_vial")
    def _check_if_list(cls, v):
        if type(v) is not list:
            v = [v]
        return v
    

class cPALparams(BaseModel):
    PAL_sample_in: hcms.SampleList = hcms.SampleList()
    PAL_sample_out: hcms.SampleList = hcms.SampleList()
    # PAL_sample_out_ref: hcms.SampleList = hcms.SampleList()
    
    micropal: Union[List[MicroPalParams],MicroPalParams]  = [MicroPalParams]

    PAL_totalruns: int = 1
    PAL_sampleperiod: List[float] = [0.0]
    PAL_spacingmethod: Spacingmethod = "linear"
    PAL_spacingfactor: float = 1.0
    PAL_timeoffset: float = 0.0 # sec
    PAL_cur_run: int = 0
    
    joblist: list = []
    PAL_joblist_time: int = None
    aux_output_filepath: str = None


    @validator("micropal")
    def _check_if_list(cls, v):
        if type(v) is not list:
            v = [v]
        return v


class cPAL:
    # def __init__(self, config_dict, stat, C, servkey):
    def __init__(self, process_serv: Base):
        
        self.base = process_serv
        self.config_dict = process_serv.server_cfg["params"]
        self.world_config = process_serv.world_cfg

        self.sample_no_db_path = self.world_config["local_db_path"]
        self.unified_db = hcd.UnifiedSampleDataAPI(self.base, self.sample_no_db_path)
        asyncio.gather(self.unified_db.init_db())

        self.archive = Archive(self.base)

        self.sshuser = self.config_dict["user"]
        self.sshkey = self.config_dict["key"]
        self.sshhost = self.config_dict["host"]
        self.cam_file_path = self.config_dict["cam_file_path"]
        self.log_file = self.config_dict["log_file"]
        self.timeout = self.config_dict.get("timeout", 30 * 60)

        self.triggers = False
        self.triggerport_start = None
        self.triggerport_continue = None
        self.triggerport_done = None
        self.trigger_start = False
        self.trigger_continue = False
        self.trigger_done = False

        self.trigger_start_epoch = False
        self.trigger_continue_epoch = False
        self.trigger_done_epoch = False

        # will hold NImax task objects
        self.task_start = None
        self.task_continue = None
        self.task_done = None

        self.buffersize = 2  # finite samples or size of buffer depending on mode
        self.samplingrate = 10  # samples per second


        self.dev_trigger = self.config_dict.get("dev_trigger", None)
        self.triggerport_start = None
        self.triggerport_continue = None
        self.triggerport_done = None
        
        
           
        if self.dev_trigger == "NImax":
            self.triggerport_start = self.config_dict["trigger"].get("start", None)
            self.triggerport_continue = self.config_dict["trigger"].get(
                "continue", None
            )
            self.triggerport_done = self.config_dict["trigger"].get("done", None)
            self.base.print_message(f" ... PAL start trigger port: {self.triggerport_start}")
            self.base.print_message(f" ... PAL continue trigger port: {self.triggerport_continue}")
            self.base.print_message(f" ... PAL done trigger port: {self.triggerport_done}")
            self.triggers = True


        self.process = (
            None  # for passing process object from technique method to measure loop
        )

        self.active = (
            None  # for holding active process object, clear this at end of measurement
        )


        # for global IOloop
        self.IO_do_meas = False
        self.IO_estop = False
        # holds the parameters for the PAL
        self.IO_PALparams = cPALparams()
        # check for that to return FASTapi post
        self.IO_continue = False
        self.IO_error = error_codes.none
        # self.IO_datafile = LocalDataHandler()
        # self.liquid_sample_prc = LocalDataHandler()

        # self.runparams = process_runparams

        myloop = asyncio.get_event_loop()
        # add meas IOloop
        myloop.create_task(self._PAL_IOloop())


        self.FIFO_column_headings = [
            "PAL_sample_out",
            "PAL_sample_in",
            "epoch_PAL",
            "epoch_start",
            "epoch_continue",
            "epoch_done",
            "PAL_tool",
            "PAL_source",
            "PAL_volume_uL",
            "PAL_source_tray",
            "PAL_source_slot",
            "PAL_source_vial",
            "PAL_dest",
            "PAL_dest_tray",
            "PAL_dest_slot",
            "PAL_dest_vial",
            "PAL_logfile",
            "PAL_method",
        ]


        self.cams = CAMS
        # update cam params with config settings
        self.cam_config = self.config_dict.get("cams", None)
        self.cam_file_path = self.config_dict.get("cam_file_path", None)
        if self.cam_config is not None:
            for cam in [e.name for e in self.cams]:
                self.cams[cam].value.file_path = self.cam_file_path
                self.cams[cam].value.file_name = self.cam_config.get(cam, None)
        else:
            self.cams = None

        self.palauxheader = ["Date", "Method", "Tool", "Source", "DestinationTray", "DestinationSlot", "DestinationVial", "Volume"]



    async def convert_olddb_to_sqllite(self):
        pass
        # await self.sqlite_liquid_sample_API.old_jsondb_to_sqlitedb()
                

    async def _poll_start(self):
        starttime = time.time()
        self.trigger_start = False
        with nidaqmx.Task() as task:
            task.di_channels.add_di_chan(
                self.triggerport_start, line_grouping=LineGrouping.CHAN_PER_LINE
            )
            while self.trigger_start == False:
                data = task.read(number_of_samples_per_channel=1)
                if any(data) == True:
                    self.base.print_message(" ... got PAL start trigger poll")
                    self.trigger_start_epoch = self.active.set_realtime_nowait()
                    self.trigger_start = True
                    return True
                if (time.time() - starttime) > self.timeout:
                    return False
                await asyncio.sleep(1)
        return True


    async def _poll_continue(self):
        starttime = time.time()
        self.trigger_continue = False
        with nidaqmx.Task() as task:
            task.di_channels.add_di_chan(
                self.triggerport_continue, line_grouping=LineGrouping.CHAN_PER_LINE
            )
            while self.trigger_continue == False:
                data = task.read(number_of_samples_per_channel=1)
                if any(data) == True:
                    self.base.print_message(" ... got PAL continue trigger poll")
                    self.trigger_continue_epoch = self.active.set_realtime_nowait()
                    self.trigger_continue = True
                    return True
                if (time.time() - starttime) > self.timeout:
                    return False
                await asyncio.sleep(1)
        return True


    async def _poll_done(self):
        starttime = time.time()
        self.trigger_done = False
        with nidaqmx.Task() as task:
            task.di_channels.add_di_chan(
                self.triggerport_done, line_grouping=LineGrouping.CHAN_PER_LINE
            )
            while self.trigger_done == False:
                data = task.read(number_of_samples_per_channel=1)
                if any(data) == True:
                    self.base.print_message(" ... got PAL done trigger poll")
                    self.trigger_done_epoch = self.active.set_realtime_nowait()
                    self.trigger_done = True
                    return True
                if (time.time() - starttime) > self.timeout:
                    return False
                await asyncio.sleep(1)
        return True


    async def init_PAL_IOloop(self, A: cProcess):
        activeDict = dict()
        
        # if "PAL_method" in A.process_params:
        #     if type(A.process_params["PAL_method"]) is not list:
        #         A.process_params["PAL_method"] = [A.process_params["PAL_method"]]
        PALparams = cPALparams(**A.process_params)
        PALparams.PAL_sample_in = A.samples_in
        # A.process_abbr = PALparams.PAL_method.name
        print("---------------------")
        print(PALparams)
        print("---------------------")


        if not self.IO_do_meas:
            self.IO_error = error_codes.none
            self.IO_PALparams = PALparams
            self.process = A
            self.IO_continue = False
            self.IO_do_meas = True
            # wait for first continue trigger
            error = error_codes.none
            while not self.IO_continue:
                await asyncio.sleep(1)
            error = self.IO_error
            if self.active:
                activeDict = self.active.process.as_dict()
            else:
                activeDict = A.as_dict()
        else:
            self.base.print_message(" ... PAL method already in progress.", error = True)
            activeDict = A.as_dict()
            error = error_codes.in_progress
        # else:
        #     self.base.print_message(" ... PAL method not defined", error = True)
        #     activeDict = A.as_dict()
        #     error = error_codes.not_available

        activeDict["data"] = {"error_code": error}
        activeDict["error_code"] = error
        return activeDict


    async def _sendcommand_main(self, PALparams: cPALparams):
        """PAL takes liquid from sample_in and puts it in sample_out"""
        error =  error_codes.none

        # check if we have free vial slots
        # and update the micropals with correct positions and samples_out
        error = await self._sendcommand_prechecks(PALparams)
        if error is not error_codes.none:
            self.base.print_message(f" ... Got error after pre-checks: '{error}'", error = True)
            return error
            
            
        # assemble complete PAL command from micropals to submit a full joblist
        error = await self._sendcommand_submitjoblist_helper(PALparams)
        if error is not error_codes.none:
            self.base.print_message(f" ... Got error after sendcommand_ssh_helper: '{error}'", error = True)
            return error





        if error is error_codes.none:
            # wait for each micropal cam
            for i_micropal, micropal in enumerate(PALparams.micropal):
                # wait for each repeat of the same micropal
                for i_repeat in range(micropal.repeat+1):
    
                    # waiting now for all three PAL triggers
                    # continue is used as the sampling timestamp
                    error = await self._sendcommand_triggerwait(micropal)
    
                    if error is not error_codes.none:
                        self.base.print_message(f" ... Got error after triggerwait: '{error}'", error = True)


                    for sample_out in micropal.PAL_sample_out[i_repeat].samples:
                        # update sample creation time
                        sample_out.sample_creation_timecode = micropal.PAL_continue_time
                        # add sample to db
                        tmp = await self.new_sample(hcms.SampleList(samples=[sample_out]))
                        sample_out = tmp.samples[0]
                        # add sample out to main PALparams
                        self.IO_PALparams.PAL_sample_out.samples.append(sample_out)

                    # add sample in to main PALparams
                    for sample_in in micropal.PAL_sample_in[i_repeat].samples:
                        self.IO_PALparams.PAL_sample_in.samples.append(sample_in)

                        
                    error = await self._sendcommand_update_archive_helper(i_micropal, i_repeat)
   
                    PAL_source_tray = micropal.PAL_source_tray[i_repeat] if len(micropal.PAL_source_tray) >=i_repeat else None
                    PAL_source_slot = micropal.PAL_source_slot[i_repeat] if len(micropal.PAL_source_slot) >=i_repeat else None
                    PAL_source_vial = micropal.PAL_source_vial[i_repeat] if len(micropal.PAL_source_vial) >=i_repeat else None

                    PAL_dest_tray = micropal.PAL_dest_tray[i_repeat] if len(micropal.PAL_dest_tray) >=i_repeat else None
                    PAL_dest_slot = micropal.PAL_dest_slot[i_repeat] if len(micropal.PAL_dest_slot) >=i_repeat else None
                    PAL_dest_vial = micropal.PAL_dest_vial[i_repeat] if len(micropal.PAL_dest_vial) >=i_repeat else None



                    # write data
                    if self.active:
                        if self.active.process.save_data:
                            logdata = [
                                # [sample.get_global_label() for sample in i_micropal.PAL_sample_out[i_repeat].samples], # thats the ref sample cmverted to a real one
                                # [source for source in [sample.source for sample in i_micropal.PAL_sample_out[i_repeat].samples]],
                                [sample.get_global_label() for sample in i_micropal.PAL_dest_sample[i_repeat].samples],
                                [sample.get_global_label() for sample in i_micropal.PAL_source_sample[i_repeat].samples],
                                # [sample.get_global_label() for sample in PALparams.PAL_sample_in.samples], # thats the input to the ref sample
                                str(PALparams.PAL_joblist_time),
                                str(micropal.PAL_start_time),
                                str(micropal.PAL_continue_time),
                                str(micropal.PAL_done_time),
                                micropal.PAL_tool,
                                micropal.PAL_source,
                                str(micropal.PAL_volume_uL),
                                str(PAL_source_tray),
                                str(PAL_source_slot),
                                str(PAL_source_vial),
                                micropal.PAL_dest,
                                str(PAL_dest_tray),
                                str(PAL_dest_slot),
                                str(PAL_dest_vial),
                                micropal.PAL_rshs_pal_logfile,
                                micropal.PAL_path_methodfile,
                            ]
                            await self.active.enqueue_data(
                                {
                                    k: [v]
                                    for k, v in zip(
                                        self.FIFO_column_headings, logdata
                                    )
                                }
                            )
                            tmpdata = {k: [v] for k, v in zip(self.FIFO_column_headings, logdata)}
                            self.base.print_message(f" ... PAL data: {tmpdata}")


                # wait another 20sec for program to close



        # after final done
        await asyncio.sleep(20)
 
        return error


    async def _sendcommand_new_ref_sample(
                                          self, 
                                          samples_in: hcms.SampleList = hcms.SampleList(),
                                          sample_type: str = ""
                                         ):
        """ volume_ml and sample_position need to be updated after the 
        function call by the function calling this."""

        error = error_codes.none
        sample = hcms.SampleList()

        if len(samples_in.samples) == 0:
            self.base.print_message(" ... no sample_in to create sample_out", error = True)
            error = error_codes.not_available
        elif len(samples_in.samples) == 1:
            source_chemical =  samples_in.samples[0].chemical
            source_mass = samples_in.samples[0].mass
            source_supplier = samples_in.samples[0].supplier
            source_lotnumber = samples_in.samples[0].lot_number
            source = samples_in.samples[0].get_global_label()
            self.base.print_message(f" ... source_global_label: '{source}'")
            self.base.print_message(f" ... source_chemical: {source_chemical}")
            self.base.print_message(f" ... source_mass: {source_mass}")
            self.base.print_message(f" ... source_supplier: {source_supplier}")
            self.base.print_message(f" ... source_lotnumber: {source_lotnumber}")

            if sample_type == "liquid":
                # this is a sample reference, it needs to be added to the db later
                sample.samples.append(hcms.LiquidSample(
                        process_group_uuid=self.process.process_group_uuid,
                        process_uuid=self.process.process_uuid,
                        source=source,
                        #volume_ml=micropal.PAL_volume_uL / 1000.0,
                        process_queue_time=self.process.process_queue_time,
                        chemical=source_chemical,
                        mass=source_mass,
                        supplier=source_supplier,
                        lot_number=source_lotnumber,
                        status="created",
                        inheritance="allow_both"
                        ))
            elif sample_type == "gas":
                sample.samples.append(hcms.GasSample(
                        process_group_uuid=self.process.process_group_uuid,
                        process_uuid=self.process.process_uuid,
                        source=source,
                        #volume_ml=micropal.PAL_volume_uL / 1000.0,
                        process_queue_time=self.process.process_queue_time,
                        chemical=source_chemical,
                        mass=source_mass,
                        supplier=source_supplier,
                        lot_number=source_lotnumber,
                        status="created",
                        inheritance="allow_both"
                        ))
            elif sample_type == "assembly":
                sample.samples.append(hcms.AssemblySample(
                        parts = [sample for sample in samples_in.samples],
                        #sample_position = micropal.PAL_dest, # no vial slot can be an assembly, only custom positions
                        process_group_uuid=self.process.process_group_uuid,
                        process_uuid=self.process.process_uuid,
                        source=source,
                        # volume_ml=micropal.PAL_volume_uL / 1000.0,
                        process_queue_time=self.process.process_queue_time,
                        # chemical=source_chemical,
                        # mass=source_mass,
                        # supplier=source_supplier,
                        # lot_number=source_lotnumber,
                        status="created",
                        inheritance="allow_both"
                        ))
    
            else:
                self.base.print_message(f" ... PAL_sample_out type {sample_type} is not supported yet.", error = True)
                error = error_codes.not_available




        elif len(samples_in.samples) > 1:
            # we always create an assembly for more than one sample_in
            sample.samples.append(hcms.AssemblySample(
                parts = [sample for sample in samples_in.samples],
                #sample_position = "", # is updated later
                status="created",
                inheritance="allow_both",
                source = [sample.get_global_label() for sample in samples_in.samples],
                process_group_uuid=self.process.process_group_uuid,
                process_uuid=self.process.process_uuid,
                process_queue_time=self.process.process_queue_time,
                ))
        else:
            # this should never happen, else we found a bug
            self.base.print_message(" ... found a bug in new_ref_sample", error = True)
            error = error_codes.bug

        return error, sample


    async def _sendcommand_next_full_vial(
                                          self,
                                          after_tray:int,
                                          after_slot:int,
                                          after_vial:int,
                                         ):

        error = error_codes.none
        tray_pos = None
        slot_pos = None
        vial_pos = None
        sample = hcms.SampleList()
        
        

        # if tray is None, find the global first full vial, 
        # else find the next full after that one
        # this will add the sample to global sample_in
        newvialpos = await self.archive.tray_get_next_full(
            after_tray = after_tray,
            after_slot = after_slot,
            after_vial = after_vial)

        if newvialpos["tray"] is not None:
            tray_pos = newvialpos["tray"]
            slot_pos = newvialpos["slot"]
            vial_pos = newvialpos["vial"]

            self.base.print_message(f" ... diluting liquid sample in tray {tray_pos}, slot {slot_pos}, vial {vial_pos}")

            # need to get the sample which is currently in this vial
            # and also add it to global samples_in
            error, sample = await self.archive.tray_get_sample(
                                                         tray = tray_pos,
                                                         slot = slot_pos,
                                                         vial = vial_pos
                                                        )
            if error != error_codes.none:
                if len(sample.samples) == 1:
                    sample.samples[0].inheritance = "allow_both"
                    sample.samples[0].status = "preserved"
                    # self.IO_PALparams.PAL_sample_in.samples.append(tmp_sample_in.samples[0])
                elif len(sample.samples) > 1:
                    error = error_codes.critical
                    self.base.print_message(" ... more then one liquid sample in the same vial", error= True)
                else:
                    error = error_codes.not_available
                    self.base.print_message(" ... error converting old liquid_sample to basemodel.", error= True)

        else:
            self.base.print_message(" ... no full vial slots", error = True)
            error = error_codes.not_available        
        
        return error, tray_pos, slot_pos, vial_pos, sample


    async def _sendcommand_check_micropal_source(
                                                 self, 
                                                 micropal: MicroPalParams
                                                ):

        sample_in = hcms.SampleList()
        source_sample = hcms.SampleList()
        source = micropal.PAL_source
        source_tray = None
        source_slot = None
        source_vial = None

        if micropal.cam.source == _sourcedest.tray:
            source = _sourcedest.tray
            error, sample_in = await self.archive.tray_get_sample(
                    micropal.PAL_source_tray[-1],
                    micropal.PAL_source_slot[-1],
                    micropal.PAL_source_vial[-1]
                    )
            if len(sample_in.samples) == 0 or error != error_codes.none:
                self.base.print_message(f"No sample in tray {micropal.PAL_source_tray[-1]}, slot {micropal.PAL_source_slot[-1]}, vial {micropal.PAL_source_vial[-1]}", error = True)
                return error_codes.not_available
            else:
                source_sample = sample_in
                for sample in sample_in.samples:
                    sample.inheritance = None # is updated when dest is decided
                    sample.status = None # is updated when dest is decided

        elif micropal.cam.source == _sourcedest.custom:
            if source is None:
                self.base.print_message("Innvalid PAL source 'NONE' for 'custom' position method.", error = True)
                return error_codes.not_available
            else:
                error, sample_in = await self.archive.custom_get_sample(micropal.PAL_source)
                if len(sample_in.samples) == 0 or error != error_codes.none:
                    self.base.print_message(f"No sample in custom position {micropal.PAL_source}", error = True)
                    return error_codes.not_available
                else:
                    source_sample = sample_in
                    for sample in sample_in.samples:
                        sample.inheritance = None # is updated when dest is decided
                        sample.status = None # is updated when dest is decided
                    

        elif micropal.cam.source == _sourcedest.next_empty_vial:
            self.base.print_message("PAL source cannot be 'next_empty_vial'", error = True)
            return error_codes.not_available

        elif micropal.cam.source == _sourcedest.next_full_vial:
            error, source_tray, source_slot, source_vial, samples_in = \
                await self._sendcommand_next_full_vial(
                                  after_tray = micropal.PAL_dest_tray[-1],
                                  after_slot = micropal.PAL_dest_slot[-1],
                                  after_vial = micropal.PAL_dest_vial[-1],
                                                 )
            if error != error_codes.none:
                self.base.print_message("No next full vial", error = True)
                return error_codes.not_available
            else:
                source = _sourcedest.tray
                # micropal.dilute = True # will calculate a dilution factor when updating position table
                source_sample = sample_in
                for sample in sample_in.samples:
                    sample.inheritance = None # is updated when dest is decided
                    sample.status = None # is updated when dest is decided


        micropal.PAL_source = source
        micropal.PAL_source_tray.append(source_tray)
        micropal.PAL_source_slot.append(source_slot)
        micropal.PAL_source_vial.append(source_vial)
        micropal.PAL_sample_in.append(sample_in)
        micropal.PAL_source_sample.append(source_sample)
        return error_codes.none


    async def _sendcommand_check_micropal_dest(
                                               self, 
                                               micropal: MicroPalParams
                                              ):

        sample_out = hcms.SampleList()
        dest_sample = hcms.SampleList()
        dest = micropal.PAL_dest
        dest_tray = None
        dest_slot = None
        dest_vial = None


        if micropal.cam.dest == _sourcedest.tray:
            dest = _sourcedest.tray
            error, sample_in = await self.archive.tray_get_sample(
                    micropal.PAL_dest_tray[-1],
                    micropal.PAL_dest_slot[-1],
                    micropal.PAL_dest_vial[-1]
                    )
            if len(sample_in.samples) == 0 or error != error_codes.none:
                self.base.print_message(f"No sample in tray {micropal.PAL_dest_tray[-1]}, slot {micropal.PAL_dest_slot[-1]}, vial {micropal.PAL_dest_vial[-1]}", info = True)
                # return error_codes.not_available
                error, sample_out = self._sendcommand_new_ref_sample(
                                          samples_in = micropal.PAL_sample_in[-1],
                                          sample_type =  micropal.cam.sample_type
                                         )

                if error != error_codes.none:
                    return error
                else:
                    sample_out.samples[0].volume_ml = micropal.PAL_volume_uL / 1000.0
                    sample_out.samples[0].sample_position = micropal.PAL_dest
                    # micropal.PAL_sample_out.samples.append(sample_out.samples[0])

            else:
                # a sample is already present in the tray position
                # we add more sample to it, e.g. dilute it
                micropal.dilute = True # TODO, will calculate a dilution factor when updating position table
                dest_sample = sample_in
                for sample in sample_in.samples:
                    # we can only add liquid to vials (diluite them, no assembly here)
                    sample.inheritance = "receive_only"
                    sample.status = "preserved"
                    micropal.PAL_sample_in[-1].samples.append(sample)

            # update the rest of samples_in
            for sample in micropal.PAL_sample_in[-1].samples:
                if sample.inheritance is not None:
                    sample.inheritance = "give_only"
                    sample.status = "preserved"


        elif micropal.cam.dest == _sourcedest.custom:
            if dest is None:
                self.base.print_message("Innvalid PAL dest 'NONE' for 'custom' position method.", error = True)
                return error_codes.not_available

            else:
                error, sample_in = await self.archive.custom_get_sample(micropal.PAL_dest)
                if error != error_codes.none:
                    self.base.print_message(f"Innvalid PAL dest '{micropal.PAL_dest}' for 'custom' position method.", error = True)
                    return error
                else:
                    if len(sample_in.samples) == 0:
                        self.base.print_message(f"No sample in custom position {micropal.PAL_dest}", infor = True)
                        # return error_codes.not_available
                        if len(micropal.PAL_sample_in[-1].samples > 1) \
                        and not self.archive.custom_assembly_allowed(micropal.PAL_dest):
                            self.base.print_message(f"Assembly not allowed for PAL dest '{micropal.PAL_dest}' for 'custom' position method.", error = True)
                            return error_codes.critical
                        else:
                            error, sample_out = self._sendcommand_new_ref_sample(
                                                      samples_in = micropal.PAL_sample_in[-1],
                                                      sample_type =  micropal.cam.sample_type
                                                     )
        
                            if error != error_codes.none:
                                return error
                            else:
                                sample_out.samples[0].volume_ml = micropal.PAL_volume_uL / 1000.0
                                sample_out.samples[0].sample_position = micropal.PAL_dest

                        for sample in micropal.PAL_sample_in[-1].samples:
                            if sample.inheritance is not None:
                                sample.inheritance =  "give_only"
                                sample.status = "preserved"


    
                    else:
                        # if we add somthing to custom position via PAL it will be an assembly
                        dest_sample = sample_in
                        for sample in sample_in.samples:
                            sample.inheritance =  "allow_both"
                            sample.status = "incorporated"
                            micropal.PAL_sample_in[-1].samples.append(sample)
                        # TODO: create an assembly of sample_in

                        for sample in micropal.PAL_sample_in[-1].samples:
                            if sample.inheritance is not None:
                                sample.inheritance =  "allow_both"
                                sample.status = "incorporated"
                    

        elif micropal.cam.dest == _sourcedest.next_empty_vial:
            dest = _sourcedest.tray
            newvialpos = await self.archive.tray_new_position(
                            req_vol = micropal.PAL_volume_uL/1000.0)

            if newvialpos["tray"] is not None:
                micropal.PAL_dest = "tray" # the sample is put into a tray (instead custom position)
                micropal.PAL_dest_tray.append(newvialpos["tray"])
                micropal.PAL_dest_slot.append(newvialpos["slot"])
                micropal.PAL_dest_vial.append(newvialpos["vial"])
                self.base.print_message(f" ... archiving liquid sample to tray {micropal.PAL_dest_tray}, slot {micropal.PAL_dest_slot}, vial {micropal.PAL_dest_vial}")
            else:
                self.base.print_message(" ... empty vial slot is not available", error= True)
                return error_codes.not_available

        elif micropal.cam.dest == _sourcedest.next_full_vial:
            dest = _sourcedest.tray
            error, dest_tray, dest_slot, dest_vial, samples_in = \
                await self._sendcommand_next_full_vial(
                                  after_tray = micropal.PAL_dest_tray[-1],
                                  after_slot = micropal.PAL_dest_slot[-1],
                                  after_vial = micropal.PAL_dest_vial[-1],
                                                 )
            if error != error_codes.none:
                self.base.print_message("No next full vial", error = True)
                return error_codes.not_available
            else:
                # a sample is already present in the tray position
                # we add more sample to it, e.g. dilute it
                micropal.dilute = True # TODO, will calculate a dilution factor when updating position table

                for sample in sample_in.samples:
                    sample.inheritance = "receive_only"
                    sample.status ="preserved"
                    micropal.PAL_sample_in[-1].samples.append(sample)
                # update the rest of samples_in
                for sample in micropal.PAL_sample_in[-1].samples:
                    if sample.inheritance is not None:
                        sample.inheritance = "give_only"
                        sample.status = "preserved"

        micropal.PAL_dest = dest
        micropal.PAL_dest_tray.append(dest_tray)
        micropal.PAL_dest_slot.append(dest_slot)
        micropal.PAL_dest_vial.append(dest_vial)
        micropal.PAL_sample_out.append(sample_out)
        micropal.PAL_dest_sample.append(dest_sample)
        return error_codes.none


    async def _sendcommand_prechecks(self, PALparams: cPALparams):
        error =  error_codes.none
        PALparams.joblist = []


        # Set the aux log file for the exteral pal program
        # It needs to exists before the joblist is submitted
        # else nothing will be recorded
        # if PAL is on an exernal machine, this will be empty
        # but we need the correct outputpath to create it on the 
        # other machine
        PALparams.aux_output_filepath = self.active.write_file_nowait(
            file_type = "pal_auxlog_file",
            filename =  "AUX__PAL__log.txt",
            output_str = "",
            header = "\t".join(self.palauxheader),
            sample_str = None
            )


        # loop over the list of micropals (joblist)
        for micropal in PALparams.micropal:
            # get the correct cam definition which contains all params 
            # for the correct submission of the job to the PAL
            if micropal.PAL_method in [e.name for e in self.cams]:
                if self.cams[micropal.PAL_method].value.file_name is not None:
                    micropal.cam = self.cams[micropal.PAL_method].value
                else:
                    self.base.print_message(f"cam method '{micropal.PAL_method}' is not available", error = True)
                    return error_codes.not_available
            else: 
                self.base.print_message(f"cam method '{micropal.PAL_method}' is not available", error = True)
                return error_codes.not_available


            for repeat in range(micropal.repeat+1):

                # check source position
                error = await self._sendcommand_check_micropal_source(micropal)
                if error != error_codes.none:
                    return error
                # check target position
                error = await self._sendcommand_check_micropal_dest(micropal)
                if error != error_codes.none:
                    return error

                    
                # add cam to cammand list
                camfile = os.path.join(micropal.cam.file_path,micropal.cam.file_name)
                self.base.print_message(f"adding cam '{camfile}'", error= True)
                wash1 = "False"
                wash2 = "False"
                wash3 = "False"
                wash4 = "False"
                if micropal.PAL_wash1 is True:
                    wash1 = "True"
                if micropal.PAL_wash2 is True:
                    wash2 = "True"
                if micropal.PAL_wash3 is True:
                    wash3 = "True"
                if micropal.PAL_wash4 is True:
                    wash4 = "True"
                micropal.PAL_rshs_pal_logfile = PALparams.aux_output_filepath
                micropal.PAL_path_methodfile = camfile

                PAL_dest_tray = micropal.PAL_dest_tray[-1] if len(micropal.PAL_dest_tray) !=0 else None
                PAL_dest_slot = micropal.PAL_dest_slot[-1] if len(micropal.PAL_dest_slot) !=0 else None
                PAL_dest_vial = micropal.PAL_dest_vial[-1] if len(micropal.PAL_dest_vial) !=0 else None


                PALparams.joblist.append(_palcmd(method=f"{camfile}",
                                       params=f"{micropal.PAL_tool};{micropal.PAL_source};{micropal.PAL_volume_uL};{PAL_dest_tray};{PAL_dest_slot};{PAL_dest_vial};{wash1};{wash2};{wash3};{wash4};{micropal.PAL_rshs_pal_logfile}"))

 
        return error


    async def _sendcommand_triggerwait(self, micropal: MicroPalParams):
        error =  error_codes.none
        # only wait if triggers are configured
        if self.triggers:
            self.base.print_message(" ... waiting for PAL start trigger")
            # val = await self.wait_for_trigger_start()
            val = await self._poll_start()
            if not val:
                self.base.print_message(" ... PAL start trigger timeout", error = True)
                error = error_codes.start_timeout
                self.IO_error = error
                self.IO_continue = True
            else:
                self.base.print_message(" ... got PAL start trigger")
                self.base.print_message(" ... waiting for PAL continue trigger")
                micropal.PAL_start_time = self.trigger_start_epoch
                # val = await self.wait_for_trigger_continue()
                val = await self._poll_continue()
                if not val:
                    self.base.print_message(" ... PAL continue trigger timeout", error = True)
                    error = error_codes.continue_timeout
                    self.IO_error = error
                    self.IO_continue = True
                else:
                    self.IO_continue = (
                        True  # signal to return FASTAPI, but not yet status
                    )
                    self.base.print_message(" ... got PAL continue trigger")
                    self.base.print_message(" ... waiting for PAL done trigger")
                    micropal.PAL_continue_time = self.trigger_continue_epoch
                    # val = await self.wait_for_trigger_done()
                    val = await self._poll_done()
                    if not val:
                        self.base.print_message(" ... PAL done trigger timeout", error = True)
                        error = error_codes.done_timeout
                        # self.IO_error = error
                        # self.IO_continue = True
                    else:
                        # self.IO_continue = True
                        # self.IO_continue = True
                        self.base.print_message(" ... got PAL done trigger")
                        micropal.PAL_done_time = self.trigger_done_epoch
        else:
            self.base.print_message(" ... No triggers configured", error = True)
        return error


    async def _sendcommand_submitjoblist_helper(self, PALparams: cPALparams):

        error = error_codes.none

        if self.sshhost == "localhost":
            error = error_codes.not_available
            #TODO: tdb
        else:
            ssh_connected = False
            while not ssh_connected:
                try:
                    # open SSH to PAL
                    k = paramiko.RSAKey.from_private_key_file(self.sshkey)
                    mysshclient = paramiko.SSHClient()
                    mysshclient.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    mysshclient.connect(hostname=self.sshhost, username=self.sshuser, pkey=k)
                    ssh_connected = True
                except Exception:
                    ssh_connected = False
                    self.base.print_message(" ... SSH connection error. Retrying in 1 seconds.")
                    await asyncio.sleep(1)
    
    
            try:


                FIFO_rshs_dir,rshs_logfile = os.path.split(PALparams.aux_output_filepath)
                FIFO_rshs_dir = FIFO_rshs_dir.replace("C:\\", "")
                FIFO_rshs_dir = FIFO_rshs_dir.replace("\\", "/")

                self.base.print_message(f" ... RSHS saving to: /cygdrive/c/{FIFO_rshs_dir}")

                # creating remote folder and logfile on RSHS
                rshs_path = "/cygdrive/c"
                for path in FIFO_rshs_dir.split("/"):
            
                    rshs_path += "/" + path
                    if path != "":
                        sshcmd = f"mkdir {rshs_path}"
                        (
                            mysshclient_stdin,
                            mysshclient_stdout,
                            mysshclient_stderr,
                        ) = mysshclient.exec_command(sshcmd)
                if not rshs_path.endswith("/"):
                    rshs_path += "/"
                self.base.print_message(f" ... final RSHS path: {rshs_path}")
            
                rshs_logfilefull = rshs_path + rshs_logfile
                sshcmd = f"touch {rshs_logfilefull}"
                (
                    mysshclient_stdin,
                    mysshclient_stdout,
                    mysshclient_stderr,
                ) = mysshclient.exec_command(sshcmd)
            
                auxheader = "\t".join(self.palauxheader)+"\r\n"
                sshcmd = f"echo -e '{auxheader}' > {rshs_logfilefull}"
                (
                    mysshclient_stdin,
                    mysshclient_stdout,
                    mysshclient_stderr,
                ) = mysshclient.exec_command(sshcmd)
                self.base.print_message(f" ... final RSHS logfile: {rshs_logfilefull}")

                tmpjob = " ".join([f"/loadmethod '{job.method}' '{job.params}'" for job in PALparams.joblist])
                cmd_to_execute = f"tmux new-window PAL {tmpjob} /start /quit"
                

                # cmd_to_execute = f"tmux new-window PAL  /loadmethod '{PALparams.PAL_path_methodfile}' '{PALparams.PAL_tool};{PALparams.PAL_source};{PALparams.PAL_volume_uL};{PALparams.PAL_dest_tray};{PALparams.PAL_dest_slot};{PALparams.PAL_dest_vial};{wash1};{wash2};{wash3};{wash4};{PALparams.PAL_rshs_pal_logfile}' /start /quit"
                self.base.print_message(f" ... PAL command: {cmd_to_execute}")
            
    
    
            except Exception as e:
                self.base.print_message(
                    " ... SSH connection error 1. Could not send commands.",
                    error = True
                )
                self.base.print_message(
                    e,
                    error = True
                )
                
                error = error_codes.ssh_error
    
    
            try:
                if error is error_codes.none:
                    PALparams.PAL_joblist_time = self.active.set_realtime_nowait()
                    (
                        mysshclient_stdin,
                        mysshclient_stdout,
                        mysshclient_stderr,
                    ) = mysshclient.exec_command(cmd_to_execute)
                    mysshclient.close()
     
            except Exception:
                self.base.print_message(
                    " ... SSH connection error 2. Could not send commands.",
                    error = True
                )
                error = error_codes.ssh_error
    
        return error


    async def _sendcommand_update_archive_helper(self, micropal: MicroPalParams, num:int):
        error = error_codes.none

        if  micropal.PAL_dest_tray is not None:
            if micropal.PAL_dest == "tray":
                retval = await self.archive.tray_update_position(
                                                  tray = micropal.PAL_dest_tray[num],
                                                  slot = micropal.PAL_dest_slot[num],
                                                  vial = micropal.PAL_dest_vial[num],
                                                  vol_mL = micropal.PAL_volume_uL/1000.0,
                                                  sample = micropal.PAL_sample_out[num],
                                                  dilute = micropal.dilute
                                                  )
            else: # cutom postion
                retval = await self.archive.custom_update_position(
                                                  custom = micropal.PAL_dest,
                                                  vol_mL = micropal.PAL_volume_uL/1000.0,
                                                  sample = micropal.PAL_sample_out[num],
                                                  dilute = micropal.dilute
                                                  )

            if retval == False:
                error = error_codes.not_available

        return error


    async def _PAL_IOloop(self):
        """This is the main dispatch loop for the PAL.
        Its start when self.IO_do_meas is set to True
        and works on the current content of self.IO_PALparams."""

        while True:
            await asyncio.sleep(1)
            if self.IO_do_meas:
                if not self.IO_estop:
                    # create active and check samples_in
                    await self._PAL_IOloop_meas_start_helper()

                    # gets some internal timing references
                    start_time = time.time()# this is only interal 
                    last_time = start_time
                    prev_timepoint = 0.0
                    diff_time = 0.0
                    
                    # for multipe runs we don't wait for first trigger
                    if self.IO_PALparams.PAL_totalruns > 1:
                        self.IO_continue = True

                    # loop over the requested runs for a single action
                    for run in range(self.IO_PALparams.PAL_totalruns):
                        self.base.print_message(f" ... PAL run {run+1} of {self.IO_PALparams.PAL_totalruns}")
                        # need to make a deepcopy as we modify this object during the run
                        # but each run should start from the same initial
                        # params again
                        run_PALparams =  copy.deepcopy(self.IO_PALparams)
                        run_PALparams.PAL_cur_run = run


                        # get the scheduled time for next PAL command
                        # self.IO_PALparams.timeoffset corrects for offset 
                        # between send ssh and continue (or any other offset)
                        if self.IO_PALparams.PAL_spacingmethod == Spacingmethod.linear:
                            self.base.print_message(" ... PAL linear scheduling")
                            cur_time = time.time()
                            diff_time = self.IO_PALparams.PAL_sampleperiod[0]-(cur_time-last_time)-self.IO_PALparams.PAL_timeoffset
                        elif self.IO_PALparams.PAL_spacingmethod == Spacingmethod.geometric:
                            self.base.print_message(" ... PAL geometric scheduling")
                            timepoint = (self.IO_PALparams.PAL_spacingfactor ** run) * self.IO_PALparams.PAL_sampleperiod[0]
                            diff_time = timepoint-prev_timepoint-(cur_time-last_time)-self.IO_PALparams.PAL_timeoffset
                            prev_timepoint = timepoint # todo: consider time lag
                        elif self.IO_PALparams.PAL_spacingmethod == Spacingmethod.custom:
                            self.base.print_message(" ... PAL custom scheduling")
                            cur_time = time.time()
                            self.base.print_message((cur_time-last_time))
                            self.base.print_message(self.IO_PALparams.PAL_sampleperiod[run])
                            diff_time = self.IO_PALparams.PAL_sampleperiod[run]-(cur_time-start_time)-self.IO_PALparams.PAL_timeoffset


                        # only wait for positive time
                        self.base.print_message(f" ... PAL waits {diff_time} for sending next command")
                        if (diff_time > 0):
                            await asyncio.sleep(diff_time)


                        # finally submit a single PAL run
                        last_time = time.time()
                        self.base.print_message(" ... PAL sendcommmand def start")
                        self.IO_error = await self._sendcommand_main(run_PALparams)
                        self.base.print_message(" ... PAL sendcommmand def end")


                    # update samples_in/out in prc
                    # and other cleanup
                    await self._PAL_IOloop_meas_end_helper()

                else:
                    self.IO_do_meas = False
                    self.base.print_message(" ... PAL is in estop.")
                    # await self.stat.set_estop()


    async def _PAL_IOloop_meas_start_helper(self):
        """sets active object and
        checks samples_in"""

        self.active = await self.base.contain_process(
            self.process,
            file_type="pal_helao__file",
            file_data_keys=self.FIFO_column_headings,
            header=None,
        )
        self.base.print_message(f" ... Active process uuid is {self.active.process.process_uuid}")
        if self.active:
            self.active.finish_hlo_header(realtime=await self.active.set_realtime())

        self.base.print_message(f" ... PAL_sample_in: {self.IO_PALparams.PAL_sample_in.samples}")

            
        # update sample list with correct information from db if possible
        for sample in self.IO_PALparams.PAL_sample_in.samples:
            if sample is not None:
                if sample.sample_no < 0:
                    self.base.print_message(f" ... PAL need to get n-{self.IO_PALparams.PAL_sample_in.samples[0].sample_no+1} last sample from list")
                    self.IO_PALparams.PAL_sample_in = await self.get_sample(hcms.SampleList(samples=[sample]))
                    self.base.print_message(f" ... correct PAL_sample_in is now: {self.IO_PALparams.PAL_sample_in.samples[0]}")
                else:
                    # update information of sample from db
                    # TODO also for other sample types
                    self.IO_PALparams.PAL_sample_in = await self.get_sample(hcms.SampleList(samples=[self.IO_PALparams.PAL_sample_in.samples[0]]))
                        
            
            if sample.inheritance is None:
                sample.inheritance = "give_only"
            if sample.status is None:
                sample.status = "preserved"


    async def _PAL_IOloop_meas_end_helper(self):
        """resets all IO variables
            and updates prc samples in and out"""


        self.IO_continue = True
        # done sending all PAL commands
        self.IO_do_meas = False

        # add sample in and out to prc
            
        await self.active.append_sample(samples = [sample for sample in self.IO_PALparams.PAL_sample_in.samples],
                                        IO="in"
                                      )

        await self.active.append_sample(samples = [sample for sample in self.IO_PALparams.PAL_sample_out.samples],
                                        IO="out"
                                       )


        # need to check here again in case estop was triggered during
        # measurement
        # need to set the current meas to idle first
        _ = await self.active.finish()
        self.active = None
        self.process = None

        if self.IO_estop:
            self.base.print_message(" ... PAL is in estop.")
            # await self.stat.set_estop()
        else:
            self.base.print_message(" ... setting PAL to idle")
        #                        await self.stat.set_idle()
        self.base.print_message(" ... PAL is done")


    async def get_sample(self, samples: hcms.SampleList = hcms.SampleList()):
        return await self.unified_db.get_sample(samples)


    async def new_sample(self, samples: hcms.SampleList = hcms.SampleList()):
        return await self.unified_db.new_sample(samples)
