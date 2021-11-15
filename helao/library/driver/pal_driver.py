
__all__ = ["Spacingmethod",
           "PALtools",
           "PAL_position",
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

from helaocore.schema import Process
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
    sample_out_type: str = None # should not be assembly, only liquid, solid...
    ttl_start: bool = False
    ttl_continue: bool = False
    ttl_done: bool = False

    source:str = None
    dest:str = None


class _positiontype(str, Enum):
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
                          sample_out_type = _sampletype.liquid,
                          source = _positiontype.custom,
                          dest = _positiontype.next_empty_vial,
                         )


    archive = _cam(name="archive",
                   file_name = "lcfc_archive.cam", # from config later
                   sample_out_type = _sampletype.liquid,
                   source = _positiontype.custom,
                   dest = _positiontype.next_empty_vial,
                  )


    fillfixed = _cam(name="fillfixed",
                      file_name = "lcfc_fill_hardcodedvolume.cam", # from config later
                      sample_out_type = _sampletype.liquid,
                      source = _positiontype.custom,
                      dest = _positiontype.custom,
                    )
    
    fill = _cam(name="fill",
                file_name = "lcfc_fill.cam", # from config later
                sample_out_type = _sampletype.liquid,
                source = _positiontype.custom,
                dest = _positiontype.next_empty_vial,
             )

    test = _cam(name="test",
                file_name = "relay_actuation_test2.cam", # from config later
               )

    autodilute = _cam(name="autodilute",
                  file_name = "lcfc_dilute.cam", # from config later
                  sample_out_type = _sampletype.liquid,
                  source = _positiontype.custom,
                  dest = _positiontype.next_full_vial,
                 )

    dilute = _cam(name="dilute",
                  file_name = "lcfc_dilute.cam", # from config later
                  sample_out_type = _sampletype.liquid,
                  source = _positiontype.custom,
                  dest = _positiontype.tray,
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


class PAL_position(BaseModel):
    position: str = None  # dest can be cust. or tray
    sample: hcms.SampleList = hcms.SampleList() # holds dest/source position
                                                # will be also added to 
                                                # sample in/out 
                                                # depending on cam
    tray: int = None
    slot: int = None
    vial: int = None


class MicroPalParams(BaseModel):
    PAL_sample_in: List[hcms.SampleList] = []
    PAL_sample_out: List[hcms.SampleList] = [] # this initially always holds 
                                               # references which need to be 
                                               # converted to 
                                               # to a real sample later
    


    PAL_method: str = None # name of methods
    PAL_tool: str = None 
    PAL_volume_ul: int = 0  # uL

    # this holds a single resuested source and destination
    PAL_requested_dest: PAL_position = PAL_position()
    PAL_requested_source: PAL_position = PAL_position()

    # this holds the runtime list for excution of the PAL cam
    # a microcam could run 'repeat' times
    PAL_runtime_dest: List[PAL_position] = []
    PAL_runtime_source: List[PAL_position] = []



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
            "PAL_sample_in",
            "PAL_sample_out",
            "epoch_PAL",
            "epoch_start",
            "epoch_continue",
            "epoch_done",
            "PAL_tool",
            "PAL_source",
            "PAL_volume_ul",
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


    async def _init_PAL_IOloop(self, A: Process, PALparams: cPALparams):
        activeDict = dict()
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

                        
                    error = await self._sendcommand_update_archive_helper(micropal, i_repeat)


                    # write data
                    if self.active:
                        if self.active.process.save_data:
                            logdata = [
                                [sample.get_global_label() for sample in micropal.PAL_runtime_source[i_repeat].sample.samples],
                                [sample.get_global_label() for sample in micropal.PAL_runtime_dest[i_repeat].sample.samples],
                                str(PALparams.PAL_joblist_time),
                                str(micropal.PAL_start_time),
                                str(micropal.PAL_continue_time),
                                str(micropal.PAL_done_time),
                                micropal.PAL_tool,
                                micropal.PAL_runtime_source[i_repeat].position,
                                str(micropal.PAL_volume_ul),
                                str(micropal.PAL_runtime_source[i_repeat].tray),
                                str(micropal.PAL_runtime_source[i_repeat].slot),
                                str(micropal.PAL_runtime_source[i_repeat].vial),
                                micropal.PAL_runtime_dest[i_repeat].position,
                                str(micropal.PAL_runtime_dest[i_repeat].tray),
                                str(micropal.PAL_runtime_dest[i_repeat].slot),
                                str(micropal.PAL_runtime_dest[i_repeat].vial),
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
                                          sample_in: hcms.SampleList = hcms.SampleList(),
                                          sample_out_type: str = ""
                                         ):
        """ volume_ml and sample_position need to be updated after the 
        function call by the function calling this."""

        error = error_codes.none
        sample = hcms.SampleList()

        if len(sample_in.samples) == 0:
            self.base.print_message(" ... no sample_in to create sample_out", error = True)
            error = error_codes.not_available
        elif len(sample_in.samples) == 1:
            source_chemical =  sample_in.samples[0].chemical
            source_mass = sample_in.samples[0].mass
            source_supplier = sample_in.samples[0].supplier
            source_lotnumber = sample_in.samples[0].lot_number
            source = sample_in.samples[0].get_global_label()
            self.base.print_message(f" ... source_global_label: '{source}'")
            self.base.print_message(f" ... source_chemical: {source_chemical}")
            self.base.print_message(f" ... source_mass: {source_mass}")
            self.base.print_message(f" ... source_supplier: {source_supplier}")
            self.base.print_message(f" ... source_lotnumber: {source_lotnumber}")

            if sample_out_type == "liquid":
                # this is a sample reference, it needs to be added to the db later
                sample.samples.append(hcms.LiquidSample(
                        sequence_uuid=self.process.sequence_uuid,
                        process_uuid=self.process.process_uuid,
                        source=source,
                        #volume_ml=micropal.PAL_volume_ul / 1000.0,
                        process_timestamp=self.process.process_timestamp,
                        chemical=source_chemical,
                        mass=source_mass,
                        supplier=source_supplier,
                        lot_number=source_lotnumber,
                        status="created",
                        inheritance="receive_only"
                        ))
            elif sample_out_type == "gas":
                sample.samples.append(hcms.GasSample(
                        sequence_uuid=self.process.sequence_uuid,
                        process_uuid=self.process.process_uuid,
                        source=source,
                        #volume_ml=micropal.PAL_volume_ul / 1000.0,
                        process_timestamp=self.process.process_timestamp,
                        chemical=source_chemical,
                        mass=source_mass,
                        supplier=source_supplier,
                        lot_number=source_lotnumber,
                        status="created",
                        inheritance="receive_only"
                        ))
            elif sample_out_type == "assembly":
                sample.samples.append(hcms.AssemblySample(
                        parts = [sample for sample in sample_in.samples],
                        #sample_position = micropal.PAL_dest, # no vial slot can be an assembly, only custom positions
                        sequence_uuid=self.process.sequence_uuid,
                        process_uuid=self.process.process_uuid,
                        source=source,
                        # volume_ml=micropal.PAL_volume_ul / 1000.0,
                        process_timestamp=self.process.process_timestamp,
                        # chemical=source_chemical,
                        # mass=source_mass,
                        # supplier=source_supplier,
                        # lot_number=source_lotnumber,
                        status="created",
                        inheritance="receive_only"
                        ))
    
            else:
                self.base.print_message(f" ... PAL_sample_out type {sample_out_type} is not supported yet.", error = True)
                error = error_codes.not_available




        elif len(sample_in.samples) > 1:
            # we always create an assembly for more than one sample_in
            sample.samples.append(hcms.AssemblySample(
                parts = [sample for sample in sample_in.samples],
                #sample_position = "", # is updated later
                status="created",
                inheritance="receive_only",
                source = [sample.get_global_label() for sample in sample_in.samples],
                sequence_uuid=self.process.sequence_uuid,
                process_uuid=self.process.process_uuid,
                process_timestamp=self.process.process_timestamp,
                ))
        else:
            # this should never happen, else we found a bug
            self.base.print_message(" ... found a BUG in new_ref_sample", error = True)
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

        if after_tray is None or after_slot is None or after_vial is None:
            error = error_codes.not_available
            return error, tray_pos, slot_pos, vial_pos, sample
        

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

        """Checks if a sample is present in the source position.
        An error is returned if no sample is found.
        Else the sample in the source postion is added to sample in.
        'Inheritance' and 'status' are set later when the destination
        is determined."""
        
        sample_in = hcms.SampleList()
        source_sample = hcms.SampleList()
        source = None
        source_tray = None
        source_slot = None
        source_vial = None

        
        # check against desired source type
        if micropal.cam.source == _positiontype.tray:
            source = _positiontype.tray # should be the same as micropal.PAL_requested_source.position
            error, sample_in = await self.archive.tray_get_sample(
                    micropal.PAL_requested_source.tray,
                    micropal.PAL_requested_source.slot,
                    micropal.PAL_requested_source.vial
                    )

            if error != error_codes.none:
                self.base.print_message("Requested tray position does not exist.", error = True)
                return error_codes.critical

            if len(sample_in.samples) > 1:
                self.base.print_message("More then one sample in source position. This is not allowed.", error = True)
                return error_codes.critical


            if len(sample_in.samples) == 0:
                self.base.print_message(f"No sample in tray {micropal.PAL_requested_source.tray}, slot {micropal.PAL_requested_source.slot}, vial {micropal.PAL_requested_source.vial}", error = True)
                return error_codes.not_available
            
            source_tray = micropal.PAL_requested_source.tray
            source_slot = micropal.PAL_requested_source.slot
            source_vial = micropal.PAL_requested_source.vial
            


        elif micropal.cam.source == _positiontype.custom:
            source = micropal.PAL_requested_source.position # custom position name
            if source is None:
                self.base.print_message("Innvalid PAL source 'NONE' for 'custom' position method.", error = True)
                return error_codes.not_available

            error, sample_in = await self.archive.custom_get_sample(micropal.PAL_requested_source.position)
            if error != error_codes.none:
                self.base.print_message("Requested custom position does not exist.", error = True)
                return error_codes.critical
            if len(sample_in.samples) > 1:
                self.base.print_message("More then one sample in source position. This is not allowed.", error = True)
                return error_codes.critical
            if len(sample_in.samples) == 0:
                self.base.print_message(f"No sample in custom position '{source}'", error = True)
                return error_codes.not_available
                    

        elif micropal.cam.source == _positiontype.next_empty_vial:
            self.base.print_message("PAL source cannot be 'next_empty_vial'", error = True)
            return error_codes.not_available


        elif micropal.cam.source == _positiontype.next_full_vial:
            source = _positiontype.tray
            error, source_tray, source_slot, source_vial, sample_in = \
                await self._sendcommand_next_full_vial(
                                  after_tray = micropal.PAL_requested_source.tray,
                                  after_slot = micropal.PAL_requested_source.slot,
                                  after_vial = micropal.PAL_requested_source.vial,
                                                 )
            if error != error_codes.none:
                self.base.print_message("No next full vial", error = True)
                return error_codes.not_available
            if len(sample_in.samples) > 1:
                self.base.print_message("More then one sample in source position. This is not allowed.", error = True)
                return error_codes.critical

            # Set requested position to new position.
            # The new position will be the requested positin for the 
            # next full vial search as the new start position
            micropal.PAL_requested_source.tray = source_tray
            micropal.PAL_requested_source.slot = source_slot
            micropal.PAL_requested_source.vial = source_vial



        # done with checking source type
        # setting inheritance and status to None for all samples
        # in sample_in (will be updated when dest is decided)
        for sample in sample_in.samples:
            # they all should actually be give only
            # but might not be preserved dpending on target
            # sample.inheritance =  "give_only"
            # sample.status = "preserved"
            sample.inheritance = None
            sample.status = None

        # set source sample to sample_in
        # (source and sample_in can be different in certain scenarios):
        # sample_in holds all input samples but
        # source only holds the sample where PAL takes a something from
        # and puts it to destination, e.g. desitantion can also be added 
        # to sample_in if no new sample is created, e.g. just liquid transfer
        source_sample = sample_in


        micropal.PAL_runtime_source.append(
            PAL_position(
                position = source,
                sample = source_sample,
                tray = source_tray,
                slot = source_slot,
                vial = source_vial
            )
        )
        micropal.PAL_sample_in.append(sample_in)
        return error_codes.none


    async def _sendcommand_check_micropal_dest(
                                               self, 
                                               micropal: MicroPalParams
                                              ):

        """Checks if the destination position is empty or contains a sample.
        If it finds a sample, it either creates an assembly or 
        will dilute it (if liquid is added to liquid).
        If no sample is found it will create a reference sample of the
        correct type."""

        sample_out = hcms.SampleList()
        dest_sample = hcms.SampleList()
        dest = None
        dest_tray = None
        dest_slot = None
        dest_vial = None


        ######################################################################
        # check dest == tray
        ######################################################################
        if micropal.cam.dest == _positiontype.tray:
            dest = _positiontype.tray
            error, sample_in = await self.archive.tray_get_sample(
                    micropal.PAL_requested_dest.tray,
                    micropal.PAL_requested_dest.slot,
                    micropal.PAL_requested_dest.vial
                    )

            if error != error_codes.none:
                self.base.print_message("Requested tray position does not exist.", error = True)
                return error_codes.critical

            if len(sample_in.samples) > 1:
                self.base.print_message("More then one sample in destination position. This is not allowed.", error = True)
                return error_codes.critical
                

            # check if a sample is present in destination
            if len(sample_in.samples) == 0:
                # no sample in dest, create a new sample reference
                self.base.print_message(f"No sample in tray {micropal.PAL_requested_dest.tray}, slot {micropal.PAL_requested_dest.slot}, vial {micropal.PAL_requested_dest.vial}", info = True)
                if len(micropal.PAL_sample_in[-1].samples > 1):
                    self.base.print_message(f"Found a BUG: Assembly not allowed for PAL dest '{dest}' for 'tray' position method.", error = True)
                    return error_codes.bug      
                
                
                
                error, sample_out = await self._sendcommand_new_ref_sample(
                                          sample_in = micropal.PAL_sample_in[-1], # this should hold a sample already from "check source call"
                                          sample_out_type =  micropal.cam.sample_out_type
                                         )

                if error != error_codes.none:
                    return error

                sample_out.samples[0].volume_ml = micropal.PAL_volume_ul / 1000.0
                sample_out.samples[0].sample_position = dest
                sample_out.samples[0].inheritance = "receive_only"
                sample_out.samples[0].status = "created"
                dest_sample = sample_out

            else:
                # a sample is already present in the tray position
                # we add more sample to it, e.g. dilute it
                micropal.dilute = True # TODO, will calculate a dilution factor when updating position table
                dest_sample = sample_in
                for sample in sample_in.samples:
                    # we can only add liquid to vials (diluite them, no assembly here)
                    sample.inheritance = "receive_only"
                    sample.status = "preserved"
                    # add that sample to the current sample_in list
                    micropal.PAL_sample_in[-1].samples.append(sample)


            dest_tray = micropal.PAL_requested_dest.tray
            dest_slot = micropal.PAL_requested_dest.slot
            dest_vial = micropal.PAL_requested_dest.vial

        ######################################################################
        # check dest == custom
        ######################################################################
        elif micropal.cam.dest == _positiontype.custom:
            dest = micropal.PAL_requested_dest.position
            if dest is None:
                self.base.print_message("Innvalid PAL dest 'NONE' for 'custom' position method.", error = True)
                return error_codes.not_available

            error, sample_in = await self.archive.custom_get_sample(dest)
            if error != error_codes.none:
                self.base.print_message(f"Innvalid PAL dest '{dest}' for 'custom' position method.", error = True)
                return error
            if len(sample_in.samples) > 1:
                self.base.print_message("More then one sample on destination position. This is not allowed,", error = True)
                return error_codes.critical

            # check if a sample is already present in the custom position
            if len(sample_in.samples) == 0:
                # no sample in custom position, create a new sample reference
                self.base.print_message(f"No sample in custom position '{dest}', creating new sample reference.", info = True)
                
                # cannot create an assembly
                if len(micropal.PAL_sample_in[-1].samples > 1):
                    self.base.print_message("Found a BUG: Too many input samples. Cannot create an assembly here.", error = True)
                    return error_codes.bug

                # this should actually never create an assembly
                error, sample_out = await self._sendcommand_new_ref_sample(
                                          sample_in = micropal.PAL_sample_in[-1],
                                          sample_out_type =  micropal.cam.sample_out_type
                                         )

                if error != error_codes.none:
                    return error

                sample_out.samples[0].volume_ml = micropal.PAL_volume_ul / 1000.0
                sample_out.samples[0].sample_position = dest
                sample_out.samples[0].inheritance = "receive_only"
                sample_out.samples[0].status = "created"
                dest_sample = sample_out
                
            else:
                # sample is already present
                # either create an assembly or dilute it
                # first check what type is present


                if sample_in.samples[0].sample_type == "assembly":
                    # need to check if we already go the same type in
                    # the assembly and then would dilute too
                    # else we add a new sample to that assembly


                    # soure input should only hold a single sample
                    # but better check for sure
                    if len(micropal.PAL_sample_in[-1].samples > 1):
                        self.base.print_message("Found a BUG: Too many input samples. Cannot create an assembly here.", error = True)
                        return error_codes.bug



                    test = False
                    if micropal.PAL_sample_in[-1].samples[0].sample_type == "liquid":
                        test = await self._sendcommand_check_for_assemblytypes(
                            sample_type = "liquid",
                            assembly = sample_in.samples[0]
                            )
                    elif micropal.PAL_sample_in[-1].sample_type == "solid":
                        test = False # always add it as a new part
                        # test = await self._sendcommand_check_for_assemblytypes(
                        #     sample_type = "solid",
                        #     assembly = sample_in.samples[0]
                        #     )
                    elif micropal.PAL_sample_in[-1].sample_type == "gas":
                        test = await self._sendcommand_check_for_assemblytypes(
                            sample_type = "gas",
                            assembly = sample_in.samples[0]
                            )
                    else:
                        self.base.print_message("Found a BUG: unsupported sample type.", error = True)
                        return error_codes.bug
    
                    if test is True:
                        # we dilute the assembly sample
                        if micropal.PAL_sample_in[-1].samples[0].sample_type == "liquid":
                            micropal.dilute = True # will calculate a dilution factor
                                                   # when updating position table
                        dest_sample = sample_in
                        for sample in sample_in.samples:
                            # we can only add liquid to vials 
                            # (diluite them, no assembly here)
                            sample.inheritance = "receive_only"
                            sample.status = "preserved"
                            micropal.PAL_sample_in[-1].samples.append(sample)
                        
                    else:
                        # add a new part to assembly
                        self.base.print_message("Adding new part to assembly", info = True)
                        if len(micropal.PAL_sample_in[-1].samples > 1):
                            self.base.print_message(f"Found a BUG: Assembly not allowed for PAL dest '{dest}' for 'tray' position method.", error = True)
                            return error_codes.bug      
                        
                        
                        
                        # first create a new sample from the source sample 
                        # which is then incoporarted into the assembly
                        error, sample_out = await self._sendcommand_new_ref_sample(
                                                  sample_in = micropal.PAL_sample_in[-1], # this should hold a sample already from "check source call"
                                                  sample_out_type =  micropal.cam.sample_out_type
                                                 )
        
                        if error != error_codes.none:
                            return error

                        sample_out.samples[0].volume_ml = micropal.PAL_volume_ul / 1000.0
                        sample_out.samples[0].sample_position = dest
                        sample_out.samples[0].inheritance = "allow_both"
                        sample_out.samples[0].status = ["created", "incorporated"]

                        # add new sample to assembly
                        sample_in.samples[0].parts.append(sample_out.samples[0])

                        dest_sample = sample_in
                        for sample in sample_in.samples:
                            # we can only add liquid to vials 
                            # (diluite them, no assembly here)
                            sample.inheritance = "allow_both"
                            sample.status = "preserved"
                            micropal.PAL_sample_in[-1].samples.append(sample)






                elif sample_in.samples[0].sample_type == micropal.PAL_sample_in[-1].sample_type:
                    # we dilute it if its the same sample type
                    # (and not an assembly),
                    micropal.dilute = True # will calculate a dilution factor
                                           # when updating position table
                    dest_sample = sample_in
                    for sample in sample_in.samples:
                        # we can only add liquid to vials 
                        # (diluite them, no assembly here)
                        sample.inheritance = "receive_only"
                        sample.status = "preserved"
                        micropal.PAL_sample_in[-1].samples.append(sample)


                else:
                    # neither same type or an assembly present.
                    # we now create an assembly if allowed
                    if not self.archive.custom_assembly_allowed(dest):
                        # no assembly allowed
                        self.base.print_message(f"Assembly not allowed for PAL dest '{dest}' for 'custom' position method.", error = True)
                        return error_codes.critical
        
                    # cannot create an assembly from an assamebly
                    if len(micropal.PAL_sample_in[-1].samples > 1):
                        self.base.print_message("Found a BUG: Too many input samples. Cannot create an assembly here.", error = True)
                        return error_codes.bug
                        
                    # add the sample which was found in the position
                    # to the sample_in list for the prc/prg
                    for sample in sample_in.samples:
                        sample_out.samples[0].inheritance = "allow_both"
                        sample_out.samples[0].status = "incorporated"
                        micropal.PAL_sample_in[-1].samples.append(sample)
                        

                    dest_sample = sample_in
                    # first create a new sample from the source sample 
                    # which is then incoporarted into the assembly
                    error, sample_out = await self._sendcommand_new_ref_sample(
                                              sample_in = micropal.PAL_sample_in[-1],
                                              sample_out_type =  micropal.cam.sample_out_type
                                             )
        
                    if error != error_codes.none:
                        return error

                    sample_out.samples[0].volume_ml = micropal.PAL_volume_ul / 1000.0
                    sample_out.samples[0].sample_position = dest
                    sample_out.samples[0].inheritance = "allow_both"
                    sample_out.samples[0].status = ["created", "incorporated"]
        
        
                    # create now an assembly of both
                    # make a tmp sample_in from original sample_in of this 
                    # position
                    tmp_sample_in = hcms.SampleList(samples = [sample for sample in sample_in.samples])
                    # and also add the newly created sample ref to it
                    tmp_sample_in.samples.append(sample_out.samples[0])
                    error, sample_out2 = await self._sendcommand_new_ref_sample(
                          sample_in = tmp_sample_in,
                          sample_out_type =  "assembly"
                         )

                    
                    if error != error_codes.none:
                        return error
                    # sample_out2.samples[0].volume_ml = micropal.PAL_volume_ul / 1000.0
                    sample_out2.samples[0].sample_position = dest
                    sample_out2.samples[0].inheritance = "allow_both"
                    sample_out2.samples[0].status = "created"
                    # add second sample out to sample_out
                    sample_out.samples.append(sample_out2.samples[0])
                    # dest_sample.samples.append(sample_out2.samples[0])
                    
                    
        ######################################################################
        # check dest == next empty
        ######################################################################
        elif micropal.cam.dest == _positiontype.next_empty_vial:
            dest = _positiontype.tray
            newvialpos = await self.archive.tray_new_position(
                            req_vol = micropal.PAL_volume_ul/1000.0)

            if newvialpos["tray"] is None:
                self.base.print_message(" ... empty vial slot is not available", error= True)
                return error_codes.not_available

            dest = _positiontype.tray
            dest_tray = newvialpos["tray"]
            dest_slot = newvialpos["slot"]
            dest_vial = newvialpos["vial"]
            self.base.print_message(f" ... archiving liquid sample to tray {dest_tray}, slot {dest_slot}, vial {dest_vial}")

            error, sample_out = await self._sendcommand_new_ref_sample(
                                      sample_in = micropal.PAL_sample_in[-1], # this should hold a sample already from "check source call"
                                      sample_out_type =  micropal.cam.sample_out_type
                                     )

            if error != error_codes.none:
                return error

            sample_out.samples[0].volume_ml = micropal.PAL_volume_ul / 1000.0
            sample_out.samples[0].sample_position = dest
            sample_out.samples[0].inheritance = "receive_only"
            sample_out.samples[0].status = "created"
            dest_sample = sample_out



        ######################################################################
        # check dest == next full
        ######################################################################
        elif micropal.cam.dest == _positiontype.next_full_vial:
            dest = _positiontype.tray
            error, dest_tray, dest_slot, dest_vial, sample_in = \
                await self._sendcommand_next_full_vial(
                                  after_tray = micropal.PAL_requested_dest.tray,
                                  after_slot = micropal.PAL_requested_dest.slot,
                                  after_vial = micropal.PAL_requested_dest.vial,
                                                 )
            if error != error_codes.none:
                self.base.print_message("No next full vial", error = True)
                return error_codes.not_available
            if len(sample_in.samples) > 1:
                self.base.print_message("More then one sample in source position. This is not allowed.", error = True)
                return error_codes.critical

            # a sample is already present in the tray position
            # we add more sample to it, e.g. dilute it
            micropal.dilute = True # TODO, will calculate a dilution factor when updating position table

            dest_sample = sample_in
            for sample in sample_in.samples:
                sample.inheritance = "receive_only"
                sample.status ="preserved"
                micropal.PAL_sample_in[-1].samples.append(sample)

            # Set requested position to new position.
            # The new position will be the requested positin for the 
            # next full vial search as the new start position
            micropal.PAL_requested_dest.tray = dest_tray
            micropal.PAL_requested_dest.slot = dest_slot
            micropal.PAL_requested_dest.vial = dest_vial





        # done with destination checks

        # update the rest of sample_in
        for sample in micropal.PAL_sample_in[-1].samples:
            if sample.inheritance is not None:
                sample.inheritance = "give_only"
                sample.status = "preserved"




        micropal.PAL_runtime_dest.append(
            PAL_position(
                position = dest,
                sample = dest_sample,
                tray = dest_tray,
                slot = dest_slot,
                vial = dest_vial
            )
        )
        micropal.PAL_sample_out.append(sample_out)
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

                PAL_source = micropal.PAL_runtime_source[-1].position
                PAL_dest_tray = micropal.PAL_runtime_dest[-1].tray
                PAL_dest_slot = micropal.PAL_runtime_dest[-1].slot
                PAL_dest_vial = micropal.PAL_runtime_dest[-1].vial


                PALparams.joblist.append(_palcmd(method=f"{camfile}",
                                       params=f"{micropal.PAL_tool};{PAL_source};{micropal.PAL_volume_ul};{PAL_dest_tray};{PAL_dest_slot};{PAL_dest_vial};{wash1};{wash2};{wash3};{wash4};{micropal.PAL_rshs_pal_logfile}"))

 
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
                

                # cmd_to_execute = f"tmux new-window PAL  /loadmethod '{PALparams.PAL_path_methodfile}' '{PALparams.PAL_tool};{PALparams.PAL_source};{PALparams.PAL_volume_ul};{PALparams.PAL_dest_tray};{PALparams.PAL_dest_slot};{PALparams.PAL_dest_vial};{wash1};{wash2};{wash3};{wash4};{PALparams.PAL_rshs_pal_logfile}' /start /quit"
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


    async def _sendcommand_check_for_assemblytypes(self, sample_type, assembly: hcms.AssemblySample):
        for part in assembly.parts:
            if part.sample_type == sample_type:
                return True
        return False


    async def _sendcommand_update_archive_helper(self, micropal: MicroPalParams, num:int):
        error = error_codes.none

        # if  micropal.PAL_runtime_dest[num].tray is not None:
        if micropal.PAL_runtime_dest[num].position == "tray":
            retval = await self.archive.tray_update_position(
                                              tray = micropal.PAL_runtime_dest[num].tray,
                                              slot = micropal.PAL_runtime_dest[num].slot,
                                              vial = micropal.PAL_runtime_dest[num].vial,
                                              vol_ml = micropal.PAL_volume_ul/1000.0,
                                              sample = micropal.PAL_sample_out[num],
                                              dilute = micropal.dilute
                                              )
        else: # custom postion
            retval, sample = await self.archive.custom_update_position(
                                              custom = micropal.PAL_dest,
                                              vol_ml = micropal.PAL_volume_ul/1000.0,
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
                    # create active and check sample_in
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
    
    
    async def method_arbitrary(self, A: Process):
        PALparams = cPALparams(**A.process_params)
        PALparams.PAL_sample_in = A.samples_in
        return await self._init_PAL_IOloop(
            A = A,
            PALparams = PALparams
        )
    
    
    async def method_archive(self, A: Process):
        PALparams = cPALparams(
            PAL_sample_in = A.samples_in,
            PAL_totalruns = len(A.process_params.get("PAL_sampleperiod",[])),
            PAL_sampleperiod = A.process_params.get("PAL_sampleperiod",[]),
            PAL_spacingmethod = A.process_params.get("PAL_spacingmethod",Spacingmethod.linear),
            PAL_spacingfactor = A.process_params.get("PAL_spacingfactor",1.0),
            PAL_timeoffset = A.process_params.get("PAL_timeoffset",0.0),
            micropal = MicroPalParams(**{
                    "PAL_method":"archive",
                    "PAL_tool":A.process_params.get("PAL_tool",None),
                    "PAL_volume_ul":A.process_params.get("PAL_volume_ul",0),
                    "PAL_requested_source":PAL_position(**{
                        "position":A.process_params.get("PAL_source",None),
                        }),
                    "PAL_wash1":A.process_params.get("PAL_wash1",0),
                    "PAL_wash2":A.process_params.get("PAL_wash2",0),
                    "PAL_wash3":A.process_params.get("PAL_wash3",0),
                    "PAL_wash4":A.process_params.get("PAL_wash4",0),
                    })
        )
        return await self._init_PAL_IOloop(
            A = A,
            PALparams = PALparams,
        )


    async def method_fill(self, A: Process):
        PALparams = cPALparams(
            PAL_sample_in = A.samples_in,
            PAL_totalruns = 1,
            PAL_sampleperiod = [],
            PAL_spacingmethod = Spacingmethod.linear,
            PAL_spacingfactor = 1.0,
            PAL_timeoffset = 0.0,
            micropal = MicroPalParams(**{
                    "PAL_method":"fill",
                    "PAL_tool":A.process_params.get("PAL_tool",None),
                    "PAL_volume_ul":A.process_params.get("PAL_volume_ul",0),
                    "PAL_requested_source":PAL_position(**{
                        "position":A.process_params.get("PAL_source",None),
                        }),
                    "PAL_requested_dest":PAL_position(**{
                        "position":A.process_params.get("PAL_dest",None),
                        }),
                    "PAL_wash1":A.process_params.get("PAL_wash1",0),
                    "PAL_wash2":A.process_params.get("PAL_wash2",0),
                    "PAL_wash3":A.process_params.get("PAL_wash3",0),
                    "PAL_wash4":A.process_params.get("PAL_wash4",0),
                    })
        )
        return await self._init_PAL_IOloop(
            A = A,
            PALparams = PALparams,
        )


    async def method_fillfixed(self, A: Process):
        PALparams = cPALparams(
            PAL_sample_in = A.samples_in,
            PAL_totalruns = 1,
            PAL_sampleperiod = [],
            PAL_spacingmethod = Spacingmethod.linear,
            PAL_spacingfactor = 1.0,
            PAL_timeoffset = 0.0,
            micropal = MicroPalParams(**{
                    "PAL_method":"fillfixed",
                    "PAL_tool":A.process_params.get("PAL_tool",None),
                    "PAL_volume_ul":A.process_params.get("PAL_volume_ul",0),
                    "PAL_requested_source":PAL_position(**{
                        "position":A.process_params.get("PAL_source",None),
                        }),
                    "PAL_requested_dest":PAL_position(**{
                        "position":A.process_params.get("PAL_dest",None),
                        }),
                    "PAL_wash1":A.process_params.get("PAL_wash1",0),
                    "PAL_wash2":A.process_params.get("PAL_wash2",0),
                    "PAL_wash3":A.process_params.get("PAL_wash3",0),
                    "PAL_wash4":A.process_params.get("PAL_wash4",0),
                    })
        )
        return await self._init_PAL_IOloop(
            A = A,
            PALparams = PALparams,
        )


    async def method_deepclean(self, A: Process):
        PALparams = cPALparams(
            PAL_sample_in = A.samples_in,
            PAL_totalruns = 1,
            PAL_sampleperiod = [],
            PAL_spacingmethod = Spacingmethod.linear,
            PAL_spacingfactor = 1.0,
            PAL_timeoffset = 0.0,
            micropal = MicroPalParams(**{
                    "PAL_method":"deepclean",
                    "PAL_tool":A.process_params.get("PAL_tool",None),
                    "PAL_volume_ul":A.process_params.get("PAL_volume_ul",0),
                    "PAL_wash1":1,
                    "PAL_wash2":1,
                    "PAL_wash3":1,
                    "PAL_wash4":1,
                    })
        )
        return await self._init_PAL_IOloop(
            A = A,
            PALparams = PALparams,
        )


    async def method_dilute(self, A: Process):
        PALparams = cPALparams(
            PAL_sample_in = A.samples_in,
            PAL_totalruns = len(A.process_params.get("PAL_sampleperiod",[])),
            PAL_sampleperiod = A.process_params.get("PAL_sampleperiod",[]),
            PAL_spacingmethod = A.process_params.get("PAL_spacingmethod",Spacingmethod.linear),
            PAL_spacingfactor = A.process_params.get("PAL_spacingfactor",1.0),
            PAL_timeoffset = A.process_params.get("PAL_timeoffset",0.0),
            micropal = MicroPalParams(**{
                    "PAL_method":"dilute",
                    "PAL_tool":A.process_params.get("PAL_tool",None),
                    "PAL_volume_ul":A.process_params.get("PAL_volume_ul",0),
                    "PAL_requested_source":PAL_position(**{
                        "position":A.process_params.get("PAL_source",None),
                        }),
                    "PAL_requested_dest":PAL_position(**{
                        "position":_positiontype.tray,
                        "tray":A.process_params.get("PAL_dest_tray",0),
                        "slot":A.process_params.get("PAL_dest_slot",0),
                        "vial":A.process_params.get("PAL_dest_vial",0),
                        }),
                    "PAL_wash1":A.process_params.get("PAL_wash1",1),
                    "PAL_wash2":A.process_params.get("PAL_wash2",1),
                    "PAL_wash3":A.process_params.get("PAL_wash3",1),
                    "PAL_wash4":A.process_params.get("PAL_wash4",1),
                    })
        )
        return await self._init_PAL_IOloop(
            A = A,
            PALparams = PALparams,
        )


    async def method_autodilute(self, A: Process):
        PALparams = cPALparams(
            PAL_sample_in = A.samples_in,
            PAL_totalruns = len(A.process_params.get("PAL_sampleperiod",[])),
            PAL_sampleperiod = A.process_params.get("PAL_sampleperiod",[]),
            PAL_spacingmethod = A.process_params.get("PAL_spacingmethod",Spacingmethod.linear),
            PAL_spacingfactor = A.process_params.get("PAL_spacingfactor",1.0),
            PAL_timeoffset = A.process_params.get("PAL_timeoffset",0.0),
            micropal = MicroPalParams(**{
                    "PAL_method":"autodilute",
                    "PAL_tool":A.process_params.get("PAL_tool",None),
                    "PAL_volume_ul":A.process_params.get("PAL_volume_ul",0),
                    "PAL_requested_source":PAL_position(**{
                        "position":A.process_params.get("PAL_source",None),
                        }),
                    "PAL_wash1":A.process_params.get("PAL_wash1",1),
                    "PAL_wash2":A.process_params.get("PAL_wash2",1),
                    "PAL_wash3":A.process_params.get("PAL_wash3",1),
                    "PAL_wash4":A.process_params.get("PAL_wash4",1),
                    })
        )
        return await self._init_PAL_IOloop(
            A = A,
            PALparams = PALparams,
        )
