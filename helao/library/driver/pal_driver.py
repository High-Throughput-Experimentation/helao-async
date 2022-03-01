__all__ = [
           "Spacingmethod",
           "PALtools",
           "PALposition",
           "PAL",
           "GCsampletype"
          ]

from enum import Enum
import asyncio
import os
import paramiko
import time
import copy
from typing import List, Optional, Union, Tuple
from pydantic import BaseModel, Field
import aiofiles
import subprocess

from helaocore.schema import Action
from helaocore.server.base import Base
from helaocore.error import ErrorCodes
from helaocore.helper.helaodict import HelaoDict

from helaocore.data.sample import UnifiedSampleDataAPI
from helaocore.model.sample import (
                                    SampleUnion, 
                                    NoneSample, 
                                    LiquidSample,
                                    GasSample,
                                    SolidSample,
                                    AssemblySample,
                                    SampleStatus,
                                    SampleInheritance
                                    )
from helaocore.model.file import FileConnParams
from helaocore.model.active import ActiveParams
from helaocore.model.data import DataModel
from helao.library.driver.archive_driver import Archive, CustomTypes


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

class GCsampletype(str, Enum):
    liquid = "liquid"
    gas = "gas"
    none = "none"
    # solid = "solid"
    # assembly = "assembly"


class CAMS(Enum):

    transfer_tray_tray = _cam(name="transfer_tray_tray",
                   file_name = "", # filled in from config later
                   sample_out_type = _sampletype.liquid,
                   source = _positiontype.tray,
                   dest = _positiontype.tray,
                  )


    transfer_custom_tray = _cam(name="transfer_custom_tray",
                   file_name = "", # filled in from config later
                   sample_out_type = _sampletype.liquid,
                   source = _positiontype.custom,
                   dest = _positiontype.tray,
                  )


    transfer_tray_custom = _cam(name="transfer_tray_custom",
                   file_name = "", # filled in from config later
                   sample_out_type = _sampletype.liquid,
                   source = _positiontype.tray,
                   dest = _positiontype.custom,
                  )


    transfer_custom_custom = _cam(name="transfer_tray_custom",
                   file_name = "", # filled in from config later
                   sample_out_type = _sampletype.liquid,
                   source = _positiontype.custom,
                   dest = _positiontype.custom,
                  )


    injection_custom_GC_gas_wait = _cam(name="injection_custom_GC_gas_wait",
                   file_name = "", # filled in from config later
                   sample_out_type = _sampletype.gas,
                   source = _positiontype.custom,
                   dest = _positiontype.custom,
                  )


    injection_custom_GC_gas_start = _cam(name="injection_custom_GC_gas_start",
                   file_name = "", # filled in from config later
                   sample_out_type = _sampletype.gas,
                   source = _positiontype.custom,
                   dest = _positiontype.custom,
                  )


    injection_custom_GC_liquid_wait = _cam(name="injection_custom_GC_liquid_wait",
                   file_name = "", # filled in from config later
                   sample_out_type = _sampletype.liquid,
                   source = _positiontype.custom,
                   dest = _positiontype.custom,
                  )


    injection_custom_GC_liquid_start = _cam(name="injection_custom_GC_liquid_start",
                   file_name = "", # filled in from config later
                   sample_out_type = _sampletype.liquid,
                   source = _positiontype.custom,
                   dest = _positiontype.custom,
                  )


    injection_tray_GC_liquid_wait = _cam(name="injection_tray_GC_liquid_wait",
                   file_name = "", # filled in from config later
                   sample_out_type = _sampletype.liquid,
                   source = _positiontype.tray,
                   dest = _positiontype.custom,
                  )


    injection_tray_GC_liquid_start = _cam(name="injection_tray_GC_liquid_start",
                   file_name = "", # filled in from config later
                   sample_out_type = _sampletype.liquid,
                   source = _positiontype.tray,
                   dest = _positiontype.custom,
                  )

    injection_tray_GC_gas_wait = _cam(name="injection_tray_GC_gas_wait",
                   file_name = "", # filled in from config later
                   sample_out_type = _sampletype.gas,
                   source = _positiontype.tray,
                   dest = _positiontype.custom,
                  )


    injection_tray_GC_gas_start = _cam(name="injection_tray_GC_gas_start",
                   file_name = "", # filled in from config later
                   sample_out_type = _sampletype.gas,
                   source = _positiontype.tray,
                   dest = _positiontype.custom,
                  )


    injection_custom_HPLC = _cam(name="injection_custom_HPLC",
                   file_name = "", # filled in from config later
                   sample_out_type = _sampletype.liquid,
                   source = _positiontype.custom,
                   dest = _positiontype.custom,
                  )


    injection_tray_HPLC = _cam(name="injection_tray_HPLC",
                   file_name = "", # filled in from config later
                   sample_out_type = _sampletype.liquid,
                   source = _positiontype.tray,
                   dest = _positiontype.custom,
                  )


    deepclean = _cam(name="deepclean",
                     file_name = "", # filled in from config later
                    )

    none = _cam(name="",
                file_name = "",
               )
    
    # transfer_liquid = _cam(name="transfer_liquid",
    #                       file_name = "lcfc_transfer.cam", # from config later
    #                       sample_out_type = _sampletype.liquid,
    #                       source = _positiontype.custom,
    #                       dest = _positiontype.next_empty_vial,
    #                      )


    archive = _cam(name="archive",
                    file_name = "", # from config later
                    sample_out_type = _sampletype.liquid,
                    source = _positiontype.custom,
                    dest = _positiontype.next_empty_vial,
                  )


    # fillfixed = _cam(name="fillfixed",
    #                   file_name = "lcfc_fill_hardcodedvolume.cam", # from config later
    #                   sample_out_type = _sampletype.liquid,
    #                   source = _positiontype.custom,
    #                   dest = _positiontype.custom,
    #                 )
    
    # fill = _cam(name="fill",
    #             file_name = "lcfc_fill.cam", # from config later
    #             sample_out_type = _sampletype.liquid,
    #             source = _positiontype.custom,
    #             dest = _positiontype.custom,
    #          )

    # test = _cam(name="test",
    #             file_name = "relay_actuation_test2.cam", # from config later
    #            )

    # autodilute = _cam(name="autodilute",
    #               file_name = "lcfc_dilute.cam", # from config later
    #               sample_out_type = _sampletype.liquid,
    #               source = _positiontype.custom,
    #               dest = _positiontype.next_full_vial,
    #              )

    # dilute = _cam(name="dilute",
    #               file_name = "lcfc_dilute.cam", # from config later
    #               sample_out_type = _sampletype.liquid,
    #               source = _positiontype.custom,
    #               dest = _positiontype.tray,
    #              )


class Spacingmethod(str, Enum):
    linear = "linear" # 1, 2, 3, 4, 5, ...
    geometric = "gemoetric" # 1, 2, 4, 8, 16
    custom = "custom" # list of absolute times for each run
#    power = "power"
#    exponential = "exponential"

class PALtools(str, Enum):
    LS1 = "LS 1"
    LS2 = "LS 2"
    LS3 = "LS 3"
    LS4 = "LS 4"
    HS1 = "HS 1"
    HS2 = "HS 2"


class PALposition(BaseModel, HelaoDict):
    position: Optional[str]  # dest can be cust. or tray
    sample_initial: List[SampleUnion] = Field(default_factory=list)
    sample_final: List[SampleUnion] = Field(default_factory=list)
    # sample: List[SampleUnion] = Field(default_factory=list)  # holds dest/source position
                                                # will be also added to 
                                                # sample in/out 
                                                # depending on cam
    tray: Optional[int]
    slot: Optional[int]
    vial: Optional[int]
    error: Optional[ErrorCodes] = ErrorCodes.none


class PalAction(BaseModel, HelaoDict):
    sample_in: List[SampleUnion] = Field(default_factory=list)
    # this initially always holds 
    # references which need to be 
    # converted to 
    # to a real sample later
    sample_out: List[SampleUnion] = Field(default_factory=list) 

    # this holds the runtime list for excution of the PAL cam
    # a microcam could run 'repeat' times
    dest: Optional[PALposition]
    source: Optional[PALposition]

    
    dilute: List[bool] = Field(default_factory=list)
    dilute_type: List[Union[str, None]] = Field(default_factory=list)
    sample_in_delta_vol_ml: List[float] = Field(default_factory=list) # contains a list of
                                                       # delta volumes
                                                       # for sample_in
                                                       # for each repeat

    # I probably don't need them as lists but can keep it for now
    start_time: Optional[int]
    continue_time: Optional[int]
    done_time: Optional[int]


class PalMicroCam(BaseModel, HelaoDict):
    # scalar values which are the same for each repetition of the PAL method
    method: str = None # name of methods
    tool: str = None 
    volume_ul: int = 0  # uL
    # this holds a single resuested source and destination
    requested_dest: PALposition = PALposition()
    requested_source: PALposition = PALposition()


    wash1: bool = False
    wash2: bool = False
    wash3: bool = False
    wash4: bool = False


    path_methodfile: str = "" # all shoukld be in the same folder
    rshs_pal_logfile: str = "" # one PAL action logs into one logfile
    cam:_cam = _cam()
    repeat: int = 0

    # for each microcam repetition we save a list of results
    run: List[PalAction] = Field(default_factory=list)


class PalCam(BaseModel, HelaoDict):
    sample_in: List[SampleUnion] = Field(default_factory=list)
    sample_out: List[SampleUnion] = Field(default_factory=list)
    
    microcam: List[PalMicroCam]  = Field(default_factory=list)

    totalruns: int = 1
    sampleperiod: List[float] = Field(default_factory=list)
    spacingmethod: Spacingmethod = "linear"
    spacingfactor: float = 1.0
    timeoffset: float = 0.0 # sec
    cur_run: int = 0
    
    joblist: list = Field(default_factory=list)
    joblist_time: int = None
    aux_output_filepath: str = None


class PAL:
    def __init__(self, action_serv: Base):
        
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.world_config = action_serv.world_cfg

        self.unified_db = UnifiedSampleDataAPI(self.base)
        asyncio.gather(self.unified_db.init_db())

        self.archive = Archive(self.base)

        self.sshuser = self.config_dict.get("user","")
        self.sshkey = self.config_dict.get("key","")
        self.sshhost = self.config_dict.get("host","")
        self.cam_file_path = self.config_dict.get("cam_file_path","")
        self.timeout = self.config_dict.get("timeout", 30 * 60)
        self.PAL_pid = None

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
            self.base.print_message(f"PAL start trigger port: {self.triggerport_start}")
            self.base.print_message(f"PAL continue trigger port: {self.triggerport_continue}")
            self.base.print_message(f"PAL done trigger port: {self.triggerport_done}")
            self.triggers = True


        self.action = (
            None  # for passing action object from technique method to measure loop
        )

        self.active = (
            None  # for holding active action object, clear this at end of measurement
        )


        # for global IOloop
        self.IO_do_meas = False
        # holds the parameters for the PAL
        self.IO_palcam = PalCam()
        # check for that to final FASTapi post
        self.IO_continue = False
        self.IO_error = ErrorCodes.none
        
        # counts the total submission
        # for split actions
        self.IO_action_run_counter: int = 0

        myloop = asyncio.get_event_loop()
        # add meas IOloop
        myloop.create_task(self._PAL_IOloop())


        self.FIFO_column_headings = [
            "sample_in",
            "sample_out",
            "epoch_PAL",
            "epoch_start",
            "epoch_continue",
            "epoch_done",
            "tool",
            "source",
            "volume_ul",
            "source_tray",
            "source_slot",
            "source_vial",
            "dest",
            "dest_tray",
            "dest_slot",
            "dest_vial",
            "logfile",
            "method",
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
        self.IOloop_run = False

    async def _poll_start(self) -> bool:
        starttime = time.time()
        self.trigger_start = False
        with nidaqmx.Task() as task:
            self.base.print_message(f"using trigger port '{self.triggerport_start}' for 'start' trigger", info = True)
            task.di_channels.add_di_chan(
                self.triggerport_start, line_grouping=LineGrouping.CHAN_PER_LINE
            )
            while self.trigger_start == False:
                data = task.read(number_of_samples_per_channel=1)
                if any(data) == True:
                    self.base.print_message("got PAL 'start' trigger poll", info = True)
                    self.trigger_start_epoch = self.active.set_realtime_nowait()
                    self.trigger_start = True
                    return True
                if (time.time() - starttime) > self.timeout:
                    return False
                await asyncio.sleep(1)
        return True


    async def _poll_continue(self) -> bool:
        starttime = time.time()
        self.trigger_continue = False
        with nidaqmx.Task() as task:
            self.base.print_message(f"using trigger port '{self.triggerport_start}' for 'continue' trigger", info = True)
            task.di_channels.add_di_chan(
                self.triggerport_continue, line_grouping=LineGrouping.CHAN_PER_LINE
            )
            while self.trigger_continue == False:
                data = task.read(number_of_samples_per_channel=1)
                if any(data) == True:
                    self.base.print_message("got PAL 'continue' trigger poll", info = True)
                    self.trigger_continue_epoch = self.active.set_realtime_nowait()
                    self.trigger_continue = True
                    return True
                if (time.time() - starttime) > self.timeout:
                    return False
                await asyncio.sleep(1)
        return True


    async def _poll_done(self) -> bool:
        starttime = time.time()
        self.trigger_done = False
        with nidaqmx.Task() as task:
            self.base.print_message(f"using trigger port '{self.triggerport_start}' for 'done' trigger", info = True)
            task.di_channels.add_di_chan(
                self.triggerport_done, line_grouping=LineGrouping.CHAN_PER_LINE
            )
            while self.trigger_done == False:
                data = task.read(number_of_samples_per_channel=1)
                if any(data) == True:
                    self.base.print_message("got PAL 'done' trigger poll", info = True)
                    self.trigger_done_epoch = self.active.set_realtime_nowait()
                    self.trigger_done = True
                    return True
                if (time.time() - starttime) > self.timeout:
                    return False
                await asyncio.sleep(1)
        return True


    async def _sendcommand_main(self, palcam: PalCam) -> ErrorCodes:
        """PAL takes liquid from sample_in and puts it in sample_out"""
        error =  ErrorCodes.none

        # check if we have free vial slots
        # and update the microcams with correct positions and samples_out
        error = await self._sendcommand_prechecks(palcam)
        if error is not ErrorCodes.none:
            self.base.print_message(f"Got error after pre-checks: '{error}'", error = True)
            return error


        # assemble complete PAL command from microcams to submit a full joblist
        error = await self._sendcommand_submitjoblist_helper(palcam)
        if error is not ErrorCodes.none:
            self.base.print_message(f"Got error after sendcommand_ssh_helper: '{error}'", error = True)
            return error

        if error is not ErrorCodes.none:
            return error

        # wait for each microcam cam
        self.base.print_message("Waiting now for all microcams")
        for microcam in palcam.microcam:
            self.base.print_message(f"waiting now '{microcam.method}'")
            # wait for each repeat of the same microcam
            for palaction in microcam.run:
                self.base.print_message("waiting now for palaction")
                # waiting now for all three PAL triggers
                # continue is used as the sampling timestamp
                # populates the three trigger timings in palaction
                error = await self._sendcommand_triggerwait(palaction)

                if error is not ErrorCodes.none:
                    # there is not much we can do here
                    # as we have not control of pal directly
                    self.base.print_message(f"Got error after triggerwait: '{error}'", error = True)


                # after each pal trigger:
                # as a pal action can contain many actions which modify
                # samples in a complex manner
                # (0) split action if its not the first one
                # (1) we need to update all input samples from the db to get 
                #     most up-to-date information
                # (2) then update the new samples (sample_out) 
                #     with up-to-date information
                #     - creation timecode
                #     - refresh parts for assemblies
                # (3) convert samples_out references to real sample
                #     and add them to the db
                # (4) add all to the action sample_in/out 
                #     sample_in: initial state
                #     sample_out: always new samples (final state)
                # (5) then update sample_in parameters to reflect
                #     the final states (sample_in_initial --> sample_in_final)
                #     and update all sample_out info (for assemblies again)
                # (6) save this back to the db (only sample_in)
                # (7) update all positions in the archive 
                #     with new final samples
                # (8) write all output files
                # (9) add samples_in/out to active.action



                # (0) split action
                # this also writes the action meta file for the parent action
                # if split, last action is finished when pal endpoint is done
                # and will update exp and seq

                if self.IO_action_run_counter > 0:
                    _ = await self.active.split()
                self.IO_action_run_counter += 1
                self.active.action.samples_in = []
                self.active.action.samples_out = []
                self.active.action.action_sub_name = microcam.method
                self.IO_palcam.sample_in = []
                self.IO_palcam.sample_out = []


                # -- (1) -- get most recent information for all sample_in
                # palaction.sample_in should always be non ref samples
                palaction.sample_in = \
                    await self.db_get_sample(palaction.sample_in)
                # as palaction.sample_in contains both source and dest samples
                # we had them saved separately (this is for the hlo file)

                # palaction.source should also always contain non ref samples
                palaction.source.sample_initial = \
                    await self.db_get_sample(palaction.source.sample_initial)

                # dest can also contain ref samples, and these are not yet in the db
                for dest_i, dest_sample in enumerate(palaction.dest.sample_initial):
                    if dest_sample.global_label is not None:
                        dest_tmp = \
                            await self.db_get_sample([dest_sample])
                        if dest_tmp:
                            palaction.dest.sample_initial[dest_i] = \
                                copy.deepcopy(dest_tmp[0])
                        else:
                            self.base.print_message("Sample does not exist in db", error = True)
                            return ErrorCodes.critical
                    else:
                            self.base.print_message("palaction.dest.sample_initial should not contain ref samples", error = True)
                            return ErrorCodes.bug

                # -- (2) -- update sample_out
                # only samples in sample_out should be new ones (ref samples)
                # convert these to real samples by adding them to the db
                # update sample creation time
                for sample_out in palaction.sample_out:
                    self.base.print_message(f" converting ref sample {sample_out} to real sample", info = True)
                    sample_out.sample_creation_timecode = palaction.continue_time
                    
                    # if the sample was destroyed during this run set its
                    # volume to zero
                    # destroyed: destination was waste or injector
                    # for newly created samples
                    if SampleStatus.destroyed in sample_out.status:
                        sample_out.zero_volume()


                    # if sample_out is an assembly we need to update its parts
                    if isinstance(sample_out, AssemblySample):
                        # could also check if it has parts attribute?
                        # reset source
                        sample_out.source = []
                        for part_i, part in enumerate(sample_out.parts):
                            if part.global_label is not None:
                                tmp_part = await self.db_get_sample([part])
                                sample_out.parts[part_i] = \
                                    copy.deepcopy(tmp_part[0])
                            else:
                                # the assembly contains a ref sample which 
                                # first need to be updated and converted
                                part.sample_creation_timecode = palaction.continue_time
                                tmp_part = await self.db_new_sample([part])
                                sample_out.parts[part_i] = \
                                    copy.deepcopy(tmp_part[0])
                            # now add the real samples back to the source list
                            sample_out.source.append(part.get_global_label())
                        

                # -- (3) -- convert samples_out references to real sample
                #           by adding them to the to db
                palaction.sample_out = await self.db_new_sample(palaction.sample_out)

                # -- (4) -- add palaction samples to action object
                # add palaction sample_in out to main palcam
                # these should be initial samples
                # properties are updated later and saved back to db
                # need a deep copy, else the next modifications would also
                # modify these samples
                for sample_in in palaction.sample_in:
                    self.IO_palcam.sample_in.append(copy.deepcopy(sample_in))
                # add palaction sample_out to main palcam
                for sample in palaction.sample_out:
                    self.IO_palcam.sample_out.append(copy.deepcopy(sample))

                # -- (5) -- convert pal action sample_in
                # from initial to final
                # update the sample volumes
                # (needed only for input samples, samples_out are always
                # new samples)
                await self._sendcommand_update_sample_volume(palaction)

                # -- (6) --
                # update all samples also in the local sample sqlite db
                await self.unified_db.update_sample(palaction.sample_in)

                for sample_out in palaction.sample_out:
                    # if sample_out is an assembly we need to update its parts
                    if isinstance(sample_out, AssemblySample):
                        sample_out.parts = \
                            await self.db_get_sample(sample_out.parts)
                    # save it back to the db
                    await self.unified_db.update_sample([sample_out])



                # -- (7) -- update the sample position db
                error = await self._sendcommand_update_archive_helper(palaction)


                # -- (8) -- write data (hlo file)
                if self.active:
                    if self.active.action.save_data:
                        logdata = [
                            [sample.get_global_label() for sample in palaction.source.sample_initial],
                            [sample.get_global_label() for sample in palaction.dest.sample_initial],
                            str(palcam.joblist_time),
                            str(palaction.start_time),
                            str(palaction.continue_time),
                            str(palaction.done_time),
                            microcam.tool,
                            palaction.source.position,
                            str(microcam.volume_ul),
                            str(palaction.source.tray),
                            str(palaction.source.slot),
                            str(palaction.source.vial),
                            palaction.dest.position,
                            str(palaction.dest.tray),
                            str(palaction.dest.slot),
                            str(palaction.dest.vial),
                            microcam.rshs_pal_logfile,
                            microcam.path_methodfile,
                        ]

                        tmpdata = {k: [v] for k, v in zip(self.FIFO_column_headings, logdata)}
                        # self.active.action.file_conn_keys holds the current
                        # active file conn keys
                        # cannot use the one which we used for contain action
                        # as action.split will generate a new one
                        # but will always update the one in
                        # self.active.action.file_conn_keys[0]
                        # to the current one
                        await self.active.enqueue_data(datamodel = \
                               DataModel(
                                         data = {self.active.action.file_conn_keys[0]:\
                                                    tmpdata
                                                 },
                                         errors = []
                                   
                                        )
                        )
                        self.base.print_message(f"PAL data: {tmpdata}")


                # (9) add samples_in/out to active.action
                # add sample in and out to prc
                    
                await self.active.append_sample(samples = self.IO_palcam.sample_in,
                                                IO="in"
                                              )
        
                await self.active.append_sample(samples = self.IO_palcam.sample_out,
                                                IO="out"
                                                )


        # wait another 20sec for program to close
        # after final done
        tmp_time = 20
        self.base.print_message(f"waiting {tmp_time}sec for PAL to close", info = True)
        await asyncio.sleep(tmp_time)
        self.base.print_message(f"done waiting {tmp_time}sec for PAL to close", info = True)
        print(self.PAL_pid)
        if self.PAL_pid is not None:
            self.base.print_message("waiting for PAL pid to finish", info = True)
            self.PAL_pid.communicate()
            self.PAL_pid = None

        return error


    async def _sendcommand_add_listA_to_listB(self, listA, listB) -> list:
        for item in listA:
            listB.append(copy.deepcopy(item))
        return listB


    async def _sendcommand_new_ref_samples(
                                          self, 
                                          samples_in: List[SampleUnion],
                                          samples_out_type: str = "",
                                          samples_position: str = ""
                                         ) -> Tuple[bool, List[SampleUnion]]:

        """ volume_ml and sample_position need to be updated after the 
        function call by the function calling this."""

        error = ErrorCodes.none
        samples: List[SampleUnion] = []

        if not samples_in:
            self.base.print_message("no sample_in to create sample_out", error = True)
            error = ErrorCodes.not_available
        elif len(samples_in) == 1:
            source_chemical = []
            source_mass = []
            source_supplier = []
            source_lotnumber = []
            for sample in samples_in:
                source_chemical = \
                    await self._sendcommand_add_listA_to_listB(
                                                               sample.chemical, 
                                                               source_chemical
                                                              )
                source_mass = \
                    await self._sendcommand_add_listA_to_listB(
                                                               sample.mass, 
                                                               source_mass
                                                              )
                source_supplier = \
                    await self._sendcommand_add_listA_to_listB(
                                                               sample.supplier, 
                                                               source_supplier
                                                              )
                source_lotnumber = \
                    await self._sendcommand_add_listA_to_listB(
                                                               sample.lot_number,
                                                               source_lotnumber
                                                              )

            source = [sample.get_global_label() for sample in samples_in]
            self.base.print_message(f"source_global_label: '{source}'")
            self.base.print_message(f"source_chemical: {source_chemical}")
            self.base.print_message(f"source_mass: {source_mass}")
            self.base.print_message(f"source_supplier: {source_supplier}")
            self.base.print_message(f"source_lotnumber: {source_lotnumber}")

            if samples_out_type == _sampletype.liquid:
                # this is a sample reference, it needs to be added
                # to the db later
                samples.append(LiquidSample(
                        action_uuid=[self.active.action.action_uuid],
                        sample_creation_action_uuid = self.active.action.action_uuid,
                        sample_creation_experiment_uuid = self.active.action.experiment_uuid,
                        source=source,
                        action_timestamp=self.active.action.action_timestamp,
                        chemical=source_chemical,
                        mass=source_mass,
                        supplier=source_supplier,
                        lot_number=source_lotnumber,
                        status=[SampleStatus.created],
                        inheritance=SampleInheritance.receive_only
                        ))
            elif samples_out_type == _sampletype.gas:
                samples.append(GasSample(
                        action_uuid=[self.active.action.action_uuid],
                        sample_creation_action_uuid = self.active.action.action_uuid,
                        sample_creation_experiment_uuid = self.active.action.experiment_uuid,
                        source=source,
                        action_timestamp=self.active.action.action_timestamp,
                        chemical=source_chemical,
                        mass=source_mass,
                        supplier=source_supplier,
                        lot_number=source_lotnumber,
                        status=[SampleStatus.created],
                        inheritance=SampleInheritance.receive_only
                        ))
            elif samples_out_type == _sampletype.assembly:
                samples.append(AssemblySample(
                        parts = samples_in,
                        sample_position = samples_position,
                        action_uuid=[self.active.action.action_uuid],
                        sample_creation_action_uuid = self.active.action.action_uuid,
                        sample_creation_experiment_uuid = self.active.action.experiment_uuid,
                        source=source,
                        action_timestamp=self.active.action.action_timestamp,
                        status=[SampleStatus.created],
                        inheritance=SampleInheritance.receive_only
                        ))
    
            else:
                self.base.print_message(f"sample_out type {samples_out_type} is not supported yet.", error = True)
                error = ErrorCodes.not_available


        elif len(samples_in) > 1:
            # we always create an assembly for more than one sample_in
            samples.append(AssemblySample(
                parts = [sample for sample in samples_in],
                #sample_position = "", # is updated later
                status=[SampleStatus.created],
                inheritance=SampleInheritance.receive_only,
                source = [sample.get_global_label() for sample in samples_in],
                experiment_uuid=self.active.action.experiment_uuid,
                action_uuid=[self.active.action.action_uuid],
                action_timestamp=self.active.action.action_timestamp,
                ))
        else:
            # this should never happen, else we found a bug
            self.base.print_message("found a BUG in new_ref_sample", error = True)
            error = ErrorCodes.bug

        return error, samples


    async def _sendcommand_next_full_vial(
                                          self,
                                          after_tray:int,
                                          after_slot:int,
                                          after_vial:int,
                                         ) -> Tuple[ErrorCodes, int, int, int, SampleUnion]:
        error = ErrorCodes.none
        tray_pos = None
        slot_pos = None
        vial_pos = None
        sample = NoneSample()

        if after_tray is None or after_slot is None or after_vial is None:
            error = ErrorCodes.not_available
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

            self.base.print_message(f"diluting liquid sample in tray {tray_pos}, slot {slot_pos}, vial {vial_pos}")

            # need to get the sample which is currently in this vial
            # and also add it to global samples_in
            error, sample = await self.archive.tray_query_sample(
                                                         tray = tray_pos,
                                                         slot = slot_pos,
                                                         vial = vial_pos
                                                        )
            if error != ErrorCodes.none:
                if sample != NoneSample():
                    sample.inheritance = SampleInheritance.allow_both
                    sample.status = [SampleStatus.preserved]
                else:
                    error = ErrorCodes.not_available
                    self.base.print_message("error converting old liquid_sample to basemodel.", error= True)

        else:
            self.base.print_message("no full vial slots", error = True)
            error = ErrorCodes.not_available        
        
        return error, tray_pos, slot_pos, vial_pos, sample


    async def _sendcommand_check_source_tray(
                                             self, 
                                             microcam: PalMicroCam
                                            ) -> PALposition:
        """checks for a valid sample in tray source position"""
        source = _positiontype.tray # should be the same as microcam.requested_source.position
        error, sample_in = await self.archive.tray_query_sample(
                microcam.requested_source.tray,
                microcam.requested_source.slot,
                microcam.requested_source.vial
                )

        if error != ErrorCodes.none:
            self.base.print_message("PAL_source: Requested tray position "
                                    "does not exist.", error = True)
            error = ErrorCodes.critical

        elif sample_in == NoneSample():
            self.base.print_message(f"PAL_source: No sample in tray "
                                    f"{microcam.requested_source.tray}, "
                                    f"slot {microcam.requested_source.slot}, "
                                    f"vial {microcam.requested_source.vial}",
                                    error = True)
            error = ErrorCodes.not_available
        


        return PALposition(
            position = source,
            sample_initial = [sample_in],
            tray = microcam.requested_source.tray,
            slot = microcam.requested_source.slot,
            vial = microcam.requested_source.vial,
            error = error
        )


    async def _sendcommand_check_source_custom(
                                               self, 
                                               microcam: PalMicroCam
                                              ) -> PALposition:
        """checks for a valid sample in custom source position"""
        source = microcam.requested_source.position # custom position name

        if source is None:
            self.base.print_message("PAL_source: Invalid PAL source 'NONE' for 'custom' position method.", error = True)
            return PALposition(error = ErrorCodes.not_available)

        error, sample_in = await self.archive.custom_query_sample(microcam.requested_source.position)

        if error != ErrorCodes.none:
            self.base.print_message("PAL_source: Requested custom position does not exist.", error = True)
            error = ErrorCodes.critical
        elif sample_in == NoneSample():
            self.base.print_message(f"PAL_source: No sample in custom position '{source}'", error = True)
            error = ErrorCodes.not_available
        
        return PALposition(
            position = source,
            sample_initial = [sample_in],
            error = error
        )


    async def _sendcommand_check_source_next_empty(
                                                   self, 
                                                   microcam: PalMicroCam
                                                  ) -> PALposition:
        """source can never be empty, throw an error"""
        self.base.print_message("PAL_source: PAL source cannot be "
                                "'next_empty_vial'", error = True)
        return PALposition(error = ErrorCodes.not_available)


    async def _sendcommand_check_source_next_full(
                                                  self, 
                                                  microcam: PalMicroCam
                                                 ) -> PALposition:
        """find the next full vial in a tray AFTER the requested 
           source position"""

        source = _positiontype.tray
        error, source_tray, source_slot, source_vial, sample_in = \
            await self._sendcommand_next_full_vial(
                              after_tray = microcam.requested_source.tray,
                              after_slot = microcam.requested_source.slot,
                              after_vial = microcam.requested_source.vial,
                                             )
        if error != ErrorCodes.none:
            self.base.print_message("PAL_source: No next full vial", error = True)
            return PALposition(error = ErrorCodes.not_available)

        elif sample_in == NoneSample():
            self.base.print_message("PAL_source: More then one sample in source position. This is not allowed.", error = True)
            return PALposition(error = ErrorCodes.critical)

        return PALposition(
            position = source,
            sample_initial = [sample_in],
            tray = source_tray,
            slot = source_slot,
            vial = source_vial,
            error = error
        )


    async def _sendcommand_check_source(
                                                 self, 
                                                 microcam: PalMicroCam
                                                ) -> ErrorCodes:

        """Checks if a sample is present in the source position.
        An error is returned if no sample is found.
        Else the sample in the source postion is added to sample in.
        'Inheritance' and 'status' are set later when the destination
        is determined."""
        
        palposition = PALposition()
        
        # check against desired source type
        if microcam.cam.source == _positiontype.tray:
            palposition = \
                 await self._sendcommand_check_source_tray(microcam = microcam)
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.source == _positiontype.custom:
            palposition = \
                 await self._sendcommand_check_source_custom(microcam = microcam)
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.source == _positiontype.next_empty_vial:
            palposition = \
                 await self._sendcommand_check_source_next_empty(microcam = microcam)
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.source == _positiontype.next_full_vial:
            palposition = \
                 await self._sendcommand_check_source_next_empty(microcam = microcam)
            if palposition.error != ErrorCodes.none:
                return palposition.error


        # # Set requested position to new position.
        # # The new position will be the requested positin for the 
        # # e.g. next full vial search as the new start position
        microcam.requested_source.tray = palposition.tray
        microcam.requested_source.slot = palposition.slot
        microcam.requested_source.vial = palposition.vial


        # if sample_in != NoneSample():
        # should never be the case as this will already throw an error before
        # but better check agin
        if palposition.sample_initial \
        and len(palposition.sample_initial) == 1 \
        and palposition.sample_initial[0] != NoneSample():

            self.base.print_message(f"PAL_source: Got sample "
                                    f"'{palposition.sample_initial[0].global_label}' "
                                    f"in position '{palposition.position}'",
                                    info = True)
            # done with checking source type
            # setting inheritance and status to None for all samples
            # in sample_in (will be updated when dest is decided)
            # they all should actually be give only
            # but might not be preserved depending on target
            # sample_in.inheritance =  SampleInheritance.give_only
            # sample_in.status = [SampleStatus.preserved]
            palposition.sample_initial[0].inheritance = None
            palposition.sample_initial[0].status = []
            palposition.sample_initial[0].sample_position = palposition.position

        else:
            # this should never happen
            # else we have a bug in the source checks
            self.base.print_message(f"BUG PAL_source: "
                                    f"Got sample no sample in position "
                                    f"'{palposition.position}'", info = True)
 


        microcam.run.append(
            PalAction(
                sample_in = copy.deepcopy(palposition.sample_initial),
                source = copy.deepcopy(palposition),
                dilute = [False], # initial source is not diluted
                dilute_type = [microcam.cam.sample_out_type],
                sample_in_delta_vol_ml = [-1.0*microcam.volume_ul / 1000.0],
            )                
        )

        
        return ErrorCodes.none


    async def _sendcommand_check_dest_tray(
                                             self, 
                                             microcam: PalMicroCam
                                            ) -> Tuple[PALposition, List[SampleUnion]]:
        """checks for a valid sample in tray destination position"""
        sample_out_list: List[SampleUnion] = []
        dest_sample_initial: List[SampleUnion] = []
        dest_sample_final: List[SampleUnion] = []


        dest = _positiontype.tray
        error, sample_in = await self.archive.tray_query_sample(  
                microcam.requested_dest.tray,
                microcam.requested_dest.slot,
                microcam.requested_dest.vial
                )

        if error != ErrorCodes.none:
            self.base.print_message("PAL_dest: Requested tray position "
                                    "does not exist.", error = True)
            return PALposition(error = ErrorCodes.critical), sample_out_list

        # check if a sample is present in destination
        if sample_in == NoneSample():
            # no sample in dest, create a new sample reference
            self.base.print_message(f"PAL_dest: No sample in tray "
                                    f"{microcam.requested_dest.tray}, "
                                    f"slot {microcam.requested_dest.slot}, "
                                    f"vial {microcam.requested_dest.vial}", info = True)
            if len(microcam.run[-1].sample_in) > 1:
                self.base.print_message(f"PAL_dest: Found a BUG: "
                                        f"Assembly not allowed for PAL dest "
                                        f"'{dest}' for 'tray' "
                                        f"position method.", error = True)
                return PALposition(error = ErrorCodes.bug), sample_out_list
            
            
            
            error, sample_out_list = await self._sendcommand_new_ref_samples(
                                      samples_in = microcam.run[-1].sample_in, # this should hold a sample already from "check source call"
                                      samples_out_type =  microcam.cam.sample_out_type,
                                      samples_position = dest
                                     )

            if error != ErrorCodes.none:
                return PALposition(error = error), sample_out_list

            # this will be a single sample anyway
            sample_out_list[0].volume_ml = microcam.volume_ul / 1000.0
            sample_out_list[0].sample_position = dest
            sample_out_list[0].inheritance = SampleInheritance.receive_only
            sample_out_list[0].status = [SampleStatus.created]
            dest_sample_initial = [] # no sample here in the beginning
            dest_sample_final = copy.deepcopy(sample_out_list)

        else:
            # a sample is already present in the tray position
            # we add more sample to it, e.g. dilute it
            self.base.print_message(f"PAL_dest: Got sample "
                                    f"'{sample_in.global_label}' "
                                    f"in position '{dest}'", info = True)
            # we can only add liquid to vials (diluite them, no assembly here)
            sample_in.inheritance = SampleInheritance.receive_only
            sample_in.status = [SampleStatus.preserved]

            dest_sample_initial = [copy.deepcopy(sample_in)]
            dest_sample_final = [copy.deepcopy(sample_in)]


            # add that sample to the current sample_in list
            microcam.run[-1].sample_in.append(copy.deepcopy(sample_in))
            microcam.run[-1].sample_in_delta_vol_ml.append(microcam.volume_ul / 1000.0)
            microcam.run[-1].dilute.append(True)
            microcam.run[-1].dilute_type.append(sample_in.sample_type)


        return PALposition(
            position = dest,
            sample_initial = dest_sample_initial,
            sample_final = dest_sample_final,
            tray = microcam.requested_dest.tray,
            slot = microcam.requested_dest.slot,
            vial = microcam.requested_dest.vial,
            error = error
        ), sample_out_list


    async def _sendcommand_check_dest_custom(
                                             self, 
                                             microcam: PalMicroCam
                                            ) -> Tuple[PALposition, List[SampleUnion]]:
        """checks for a valid sample in custom destination position"""
        sample_out_list: List[SampleUnion] = []
        dest_sample_initial: List[SampleUnion] = []
        dest_sample_final: List[SampleUnion] = []


        dest = microcam.requested_dest.position
        if dest is None:
            self.base.print_message("PAL_dest: Invalid PAL dest 'NONE' for 'custom' position method.", error = True)
            return PALposition(error = ErrorCodes.critical), sample_out_list

        if not self.archive.custom_dest_allowed(dest):
            self.base.print_message(f"PAL_dest: custom position '{dest}' cannot be dest.", error = True)
            return PALposition(error = ErrorCodes.critical), sample_out_list


        error, sample_in = await self.archive.custom_query_sample(dest)
        if error != ErrorCodes.none:
            self.base.print_message(f"PAL_dest: Invalid PAL dest '{dest}' for 'custom' position method.", error = True)
            return PALposition(error = error), sample_out_list

        # check if a sample is already present in the custom position
        if sample_in == NoneSample():
            # no sample in custom position, create a new sample reference
            self.base.print_message(f"PAL_dest: No sample in custom position '{dest}', creating new sample reference.", info = True)
            
            # cannot create an assembly
            if len(microcam.run[-1].sample_in) > 1:
                self.base.print_message("PAL_dest: Found a BUG: Too many input samples. Cannot create an assembly here.", error = True)
                return PALposition(error = ErrorCodes.bug), sample_out_list

            # this should actually never create an assembly
            error, sample_out_list = await self._sendcommand_new_ref_samples(
                                      samples_in = microcam.run[-1].sample_in,
                                      samples_out_type =  microcam.cam.sample_out_type,
                                      samples_position = dest
                                     )

            if error != ErrorCodes.none:
                return PALposition(error = error), sample_out_list


            sample_out_list[0].volume_ml = microcam.volume_ul / 1000.0
            sample_out_list[0].sample_position = dest
            sample_out_list[0].inheritance = SampleInheritance.receive_only
            sample_out_list[0].status = [SampleStatus.created]
            dest_sample_initial = [] # no sample here in the beginning
            dest_sample_final = copy.deepcopy(sample_out_list)
            
        else:
            # sample is already present
            # either create an assembly or dilute it
            # first check what type is present
            self.base.print_message(f"PAL_dest: Got sample '{sample_in.global_label}' in position '{dest}'", info = True)


            if isinstance(sample_in, AssemblySample):
                # need to check if we already go the same type in
                # the assembly and then would dilute too
                # else we add a new sample to that assembly


                # source input should only hold a single sample
                # but better check for sure
                if len(microcam.run[-1].sample_in) > 1:
                    self.base.print_message("PAL_dest: Found a BUG: Too many input samples. Cannot create an assembly here.", error = True)
                    return PALposition(error = ErrorCodes.bug), sample_out_list



                test = False
                if isinstance(microcam.run[-1].sample_in[-1], LiquidSample):
                    test = await self._sendcommand_check_for_assemblytypes(
                        sample_type = _sampletype.liquid,
                        assembly = sample_in
                        )
                elif isinstance(microcam.run[-1].sample_in[-1], SolidSample):
                    test = False # always add it as a new part
                elif isinstance(microcam.run[-1].sample_in[-1], GasSample):
                    test = await self._sendcommand_check_for_assemblytypes(
                        sample_type = _sampletype.gas,
                        assembly = sample_in
                        )
                else:
                    self.base.print_message("PAL_dest: Found a BUG: unsupported sample type.", error = True)
                    return PALposition(error = ErrorCodes.bug), sample_out_list

                if test is True:
                    # we dilute the assembly sample
                    dest_sample_initial = copy.deepcopy(sample_out_list)
                    dest_sample_final = copy.deepcopy(sample_out_list)

                    # we can only add liquid to vials 
                    # (diluite them, no assembly here)
                    sample_in.inheritance = SampleInheritance.receive_only
                    sample_in.status = [SampleStatus.preserved]
                    
                    # first add the dilute type
                    microcam.run[-1].dilute_type.append(
                        microcam.run[-1].sample_in[-1].sample_type)
                    microcam.run[-1].sample_in_delta_vol_ml.append(microcam.volume_ul / 1000.0)
                    microcam.run[-1].dilute.append(True)
                    # then add the new sample_in
                    microcam.run[-1].sample_in.append(copy.deepcopy(sample_in))
                else:
                    # add a new part to assembly
                    self.base.print_message("PAL_dest: Adding new part to assembly", info = True)
                    if len(microcam.run[-1].sample_in) > 1:
                        # sample_in should only hold one sample at that point
                        self.base.print_message(f"PAL_dest: Found a BUG: Assembly not allowed for PAL dest '{dest}' for 'tray' position method.", error = True)
                        return PALposition(error = ErrorCodes.bug), sample_out_list
                    
                    
                    # first create a new sample from the source sample 
                    # which is then incoporarted into the assembly
                    error, sample_out_list = await self._sendcommand_new_ref_samples(
                                              samples_in = microcam.run[-1].sample_in, # this should hold a sample already from "check source call"
                                              samples_out_type =  microcam.cam.sample_out_type,
                                              samples_position = dest
                                             )
    
                    if error != ErrorCodes.none:
                        return PALposition(error = error), sample_out_list

                    sample_out_list[0].volume_ml = microcam.volume_ul / 1000.0
                    sample_out_list[0].sample_position = dest
                    sample_out_list[0].inheritance = SampleInheritance.allow_both
                    sample_out_list[0].status = [SampleStatus.created, SampleStatus.incorporated]

                    # add new sample to assembly
                    sample_in.parts.append(sample_out_list[0])
                    # we can only add liquid to vials 
                    # (diluite them, no assembly here)
                    sample_in.inheritance = SampleInheritance.allow_both
                    sample_in.status = [SampleStatus.preserved]


                    dest_sample_initial = [copy.deepcopy(sample_in)]
                    dest_sample_final = [copy.deepcopy(sample_in)]
                    microcam.run[-1].sample_in.append(copy.deepcopy(sample_in))



            elif sample_in.sample_type == microcam.run[-1].sample_in[-1].sample_type:
                # we dilute it if its the same sample type
                # (and not an assembly),
                # we can only add liquid to vials 
                # (diluite them, no assembly here)
                sample_in.inheritance = SampleInheritance.receive_only
                sample_in.status = [SampleStatus.preserved]

                dest_sample_initial = [copy.deepcopy(sample_in)]
                dest_sample_final = [copy.deepcopy(sample_in)]

                microcam.run[-1].dilute_type.append(sample_in.sample_type)
                microcam.run[-1].sample_in.append(copy.deepcopy(sample_in))
                microcam.run[-1].sample_in_delta_vol_ml.append(microcam.volume_ul / 1000.0)
                microcam.run[-1].dilute.append(True)


            else:
                # neither same sample type nor an assembly present.
                # we now create an assembly if allowed
                if not self.archive.custom_assembly_allowed(dest):
                    # no assembly allowed
                    self.base.print_message(f"PAL_dest: Assembly not allowed for PAL dest '{dest}' for 'custom' position method.", error = True)
                    return PALposition(error = ErrorCodes.critical), sample_out_list
    
                # cannot create an assembly from an assembly
                if len(microcam.run[-1].sample_in) > 1:
                    self.base.print_message("PAL_dest: Found a BUG: Too many input samples. Cannot create an assembly here.", error = True)
                    return PALposition(error = ErrorCodes.bug), sample_out_list


                # dest_sample = sample_in
                # first create a new sample from the source sample 
                # which is then incoporarted into the assembly
                error, sample_out_list = await self._sendcommand_new_ref_samples(
                                          samples_in = microcam.run[-1].sample_in,
                                          samples_out_type =  microcam.cam.sample_out_type,
                                          samples_position = dest
                                         )
    
                if error != ErrorCodes.none:
                    return PALposition(error = error), sample_out_list

                sample_out_list[0].volume_ml = microcam.volume_ul / 1000.0
                sample_out_list[0].sample_position = dest
                sample_out_list[0].inheritance = SampleInheritance.allow_both
                sample_out_list[0].status = [SampleStatus.created, SampleStatus.incorporated]


                # only now add the sample which was found in the position
                # to the sample_in list for the prc/prg
                sample_in.inheritance = SampleInheritance.allow_both
                sample_in.status = [SampleStatus.incorporated]

                microcam.run[-1].sample_in.append(copy.deepcopy(sample_in))
                # we only add the sample to assembly so delta_vol is 0
                microcam.run[-1].sample_in_delta_vol_ml.append(0.0)
                microcam.run[-1].dilute.append(False)
                microcam.run[-1].dilute_type.append(None)
    
    
                # create now an assembly of both
                tmp_sample_in = [sample_in]
                # and also add the newly created sample ref to it
                tmp_sample_in.append(sample_out_list[0])
                self.base.print_message(f"PAL_dest: Creating assembly from '{[sample.global_label for sample in tmp_sample_in]}' in position '{dest}'", info = True)
                error, sample_out2_list = await self._sendcommand_new_ref_samples(
                      samples_in = tmp_sample_in,
                      samples_out_type =  _sampletype.assembly,
                      samples_position = dest
                     )



                if error != ErrorCodes.none:
                    return PALposition(error = error), sample_out_list

                sample_out2_list[0].sample_position = dest
                sample_out2_list[0].inheritance = SampleInheritance.allow_both
                sample_out2_list[0].status = [SampleStatus.created]
                # add second sample out to sample_out
                sample_out_list.append(sample_out2_list[0])
                
                
                # intial is the sample initial in the position
                dest_sample_initial = [copy.deepcopy(sample_in)]
                # this will be the new assembly
                dest_sample_final = copy.deepcopy(sample_out2_list)



        return PALposition(
            position = dest,
            sample_initial = dest_sample_initial,
            sample_final = dest_sample_final,
            tray = microcam.requested_dest.tray,
            slot = microcam.requested_dest.slot,
            vial = microcam.requested_dest.vial,
            error = error
        ), sample_out_list


    async def _sendcommand_check_dest_next_empty(
                                                 self, 
                                                 microcam: PalMicroCam
                                                ) -> Tuple[PALposition, List[SampleUnion]]:
        """find the next empty vial in a tray"""
        sample_out_list: List[SampleUnion] = []
        dest_sample_initial: List[SampleUnion] = []
        dest_sample_final: List[SampleUnion] = []


        dest_tray = None
        dest_slot = None
        dest_vial = None


        dest = _positiontype.tray
        newvialpos = await self.archive.tray_new_position(
                        req_vol = microcam.volume_ul/1000.0)

        if newvialpos["tray"] is None:
            self.base.print_message("PAL_dest: empty vial slot is not available", error= True)
            return PALposition(error = ErrorCodes.not_available), sample_out_list

        # dest = _positiontype.tray
        dest_tray = newvialpos["tray"]
        dest_slot = newvialpos["slot"]
        dest_vial = newvialpos["vial"]
        self.base.print_message(f"PAL_dest: archiving liquid sample to tray {dest_tray}, slot {dest_slot}, vial {dest_vial}")

        error, sample_out_list = await self._sendcommand_new_ref_samples(
                                  samples_in = microcam.run[-1].sample_in, # this should hold a sample already from "check source call"
                                  samples_out_type =  microcam.cam.sample_out_type,
                                  samples_position = dest
                                 )

        self.base.print_message(f"new reference sample for empty vial: {sample_out_list}")

        if error != ErrorCodes.none:
            return PALposition(error = error), sample_out_list

        sample_out_list[0].volume_ml = microcam.volume_ul / 1000.0
        sample_out_list[0].sample_position = dest
        sample_out_list[0].inheritance = SampleInheritance.receive_only
        sample_out_list[0].status = [SampleStatus.created]
        dest_sample_initial = [] # no sample here in the beginning
        dest_sample_final =  copy.deepcopy(sample_out_list)


        return PALposition(
            position = dest,
            sample_initial = dest_sample_initial,
            sample_final = dest_sample_final,
            tray = dest_tray,
            slot = dest_slot,
            vial = dest_vial,
            error = error
        ), sample_out_list


    async def _sendcommand_check_dest_next_full(
                                                self, 
                                                microcam: PalMicroCam
                                               ) -> Tuple[PALposition, List[SampleUnion]]:
        """find the next full vial in a tray AFTER the requested 
           destination position"""
        sample_out_list: List[SampleUnion] = []
        dest_sample_initial: List[SampleUnion] = []
        dest_sample_final: List[SampleUnion] = []


        dest = None
        dest_tray = None
        dest_slot = None
        dest_vial = None


        dest = _positiontype.tray
        error, dest_tray, dest_slot, dest_vial, sample_in = \
            await self._sendcommand_next_full_vial(
                              after_tray = microcam.requested_dest.tray,
                              after_slot = microcam.requested_dest.slot,
                              after_vial = microcam.requested_dest.vial,
                                             )
        if error != ErrorCodes.none:
            self.base.print_message("PAL_dest: No next full vial", error = True)
            return PALposition(error = ErrorCodes.not_available), sample_out_list
        if sample_in == NoneSample():
            self.base.print_message("PAL_dest: More then one sample in source position. This is not allowed.", error = True)
            return PALposition(error = ErrorCodes.critical), sample_out_list

        # a sample is already present in the tray position
        # we add more sample to it, e.g. dilute it
        self.base.print_message(f"PAL_dest: Got sample '{sample_in.global_label}' in position '{dest}'", info = True)
        sample_in.inheritance = SampleInheritance.receive_only
        sample_in.status = [SampleStatus.preserved]

        microcam.run[-1].sample_in.append(sample_in)
        microcam.run[-1].sample_in_delta_vol_ml.append(microcam.volume_ul / 1000.0)
        microcam.run[-1].dilute.append(True)
        microcam.run[-1].dilute_type.append(sample_in.sample_type)

        dest_sample_initial = [copy.deepcopy(sample_in)]
        dest_sample_final = [copy.deepcopy(sample_in)]


        return PALposition(
            position = dest,
            sample_initial = dest_sample_initial,
            sample_final = dest_sample_final,
            tray = dest_tray,
            slot = dest_slot,
            vial = dest_vial,
            error = error
        ), sample_out_list


    async def _sendcommand_check_dest(
                                      self, 
                                      microcam: PalMicroCam
                                     ) -> ErrorCodes:

        """Checks if the destination position is empty or contains a sample.
        If it finds a sample, it either creates an assembly or 
        will dilute it (if liquid is added to liquid).
        If no sample is found it will create a reference sample of the
        correct type."""

        sample_out_list: List[SampleUnion] = []
        palposition = PALposition()

        if microcam.cam.dest == _positiontype.tray:
            palposition, sample_out_list = \
                  await self._sendcommand_check_dest_tray(microcam = microcam)
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.dest == _positiontype.custom:
            palposition, sample_out_list = \
                 await self._sendcommand_check_dest_custom(microcam = microcam)
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.dest == _positiontype.next_empty_vial:
            palposition, sample_out_list = \
                 await self._sendcommand_check_dest_next_empty(microcam = microcam)
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.dest == _positiontype.next_full_vial:
            palposition, sample_out_list = \
                  await self._sendcommand_check_dest_next_full(microcam = microcam)
            if palposition.error != ErrorCodes.none:
                return palposition.error


        # done with destination checks


        # Set requested position to new position.
        # The new position will be the requested position for the 
        # next full vial search as the new start position
        microcam.requested_dest.tray = palposition.tray
        microcam.requested_dest.slot = palposition.slot
        microcam.requested_dest.vial = palposition.vial

        # check if final samples would be destroyed directly after they
        # were created
        if self.archive.custom_is_destroyed(custom = palposition.position):
            for sample in sample_out_list:
                sample.status.append(SampleStatus.destroyed)
            for sample in palposition.sample_final:
                sample.status.append(SampleStatus.destroyed)

        # add validated destination to run
        microcam.run[-1].dest = copy.deepcopy(palposition)

        # update the rest of sample_in for the run
        for sample in microcam.run[-1].sample_in:
            if sample.inheritance is None:
                sample.inheritance = SampleInheritance.give_only
                sample.status = [SampleStatus.preserved]


        # add the samples_out to the run
        for sample in sample_out_list:
            microcam.run[-1].sample_out.append(sample)


        # a quick message if samples will be diluted or not
        for i, sample in enumerate(microcam.run[-1].sample_in):
            if microcam.run[-1].dilute[i]:
                self.base.print_message(f"PAL: Diluting sample_in '{sample.global_label}'.", info = True)
            else:
                self.base.print_message(f"PAL: Not diluting sample_in '{sample.global_label}'.", info = True)

        return ErrorCodes.none


    async def _sendcommand_prechecks(
                                     self, 
                                     palcam: PalCam
                                    ) -> ErrorCodes:
        error =  ErrorCodes.none
        palcam.joblist = []


        # Set the aux log file for the exteral pal program
        # It needs to exists before the joblist is submitted
        # else nothing will be recorded
        # if PAL is on an exernal machine, this will be empty
        # but we need the correct outputpath to create it on the 
        # other machine
        palcam.aux_output_filepath = self.active.write_file_nowait(
            file_type = "pal_auxlog_file",
            filename =  "AUX__PAL__log.txt",
            output_str = "",
            header = "\t".join(self.palauxheader),
            sample_str = None
            )


        # loop over the list of microcams (joblist)
        for microcam in palcam.microcam:
            # get the correct cam definition which contains all params 
            # for the correct submission of the job to the PAL
            if microcam.method in [e.name for e in self.cams]:
                if self.cams[microcam.method].value.file_name is not None:
                    microcam.cam = self.cams[microcam.method].value
                else:
                    self.base.print_message(f"cam method '{microcam.method}' is not available", error = True)
                    return ErrorCodes.not_available
            else: 
                self.base.print_message(f"cam method '{microcam.method}' is not available", error = True)
                return ErrorCodes.not_available



            # set runs to empty list
            # shouldn't actually need it but better be sure its an empty list
            # at this point
            microcam.run = []

            for repeat in range(microcam.repeat+1):

                # check source position
                error = await self._sendcommand_check_source(microcam)
                if error != ErrorCodes.none:
                    return error
                # check target position
                error = await self._sendcommand_check_dest(microcam)
                if error != ErrorCodes.none:
                    return error

                    
                # add cam to cammand list
                camfile = os.path.join(microcam.cam.file_path,microcam.cam.file_name)
                self.base.print_message(f"adding cam '{camfile}'")
                wash1 = "False"
                wash2 = "False"
                wash3 = "False"
                wash4 = "False"
                if microcam.wash1 is True:
                    wash1 = "True"
                if microcam.wash2 is True:
                    wash2 = "True"
                if microcam.wash3 is True:
                    wash3 = "True"
                if microcam.wash4 is True:
                    wash4 = "True"
                microcam.rshs_pal_logfile = palcam.aux_output_filepath
                microcam.path_methodfile = camfile
                
                # A --> B
                # A
                source = microcam.run[-1].source.position
                source_tray = microcam.run[-1].source.tray
                source_slot = microcam.run[-1].source.slot
                source_vial = microcam.run[-1].source.vial
                # B
                dest = microcam.run[-1].dest.position
                dest_tray = microcam.run[-1].dest.tray
                dest_slot = microcam.run[-1].dest.slot
                dest_vial = microcam.run[-1].dest.vial

                palcam.joblist.append(_palcmd(method=f"{camfile}",
                                       params=f"{microcam.tool};{microcam.volume_ul};{source};{source_tray};{source_slot};{source_vial};{dest};{dest_tray};{dest_slot};{dest_vial};{wash1};{wash2};{wash3};{wash4};{microcam.rshs_pal_logfile}"))
    
        return error


    async def _sendcommand_triggerwait(
                                       self, 
                                       palaction: PalAction
                                      ) -> ErrorCodes:
        error =  ErrorCodes.none
        # only wait if triggers are configured
        if self.triggers:
            self.base.print_message("waiting for PAL start trigger", info = True)
            val = await self._poll_start()
            if not val:
                self.base.print_message("PAL start trigger timeout", error = True)
                error = ErrorCodes.start_timeout
                self.IO_error = error
                self.IO_continue = True
            else:
                self.base.print_message("got PAL start trigger", info = True)
                self.base.print_message("waiting for PAL continue trigger", info = True)
                palaction.start_time = self.trigger_start_epoch
                val = await self._poll_continue()
                if not val:
                    self.base.print_message("PAL continue trigger timeout", error = True)
                    error = ErrorCodes.continue_timeout
                    self.IO_error = error
                    self.IO_continue = True
                else:
                    self.IO_continue = (
                        True  # signal to return FASTAPI, but not yet status
                    )
                    self.base.print_message("got PAL continue trigger", info = True)
                    self.base.print_message("waiting for PAL done trigger", info = True)
                    palaction.continue_time = self.trigger_continue_epoch
                    val = await self._poll_done()
                    if not val:
                        self.base.print_message("PAL done trigger timeout", error = True)
                        error = ErrorCodes.done_timeout
                    else:
                        self.base.print_message("got PAL done trigger", info = True)
                        palaction.done_time = self.trigger_done_epoch
        else:
            self.base.print_message("No triggers configured", error = True)
        return error


    async def _sendcommand_write_local_rshs_aux_header(
                                           self,
                                           auxheader,
                                           output_file
                                          ):
        async with aiofiles.open(output_file, mode="w+") as f:
            await f.write(auxheader)


    async def _sendcommand_submitjoblist_helper(
                                                self, 
                                                palcam: PalCam
                                               ) -> ErrorCodes:

        error = ErrorCodes.none

        if self.sshhost == "localhost":
            
            FIFO_rshs_dir,rshs_logfile = os.path.split(palcam.aux_output_filepath)
            self.base.print_message(f"RSHS saving to: {FIFO_rshs_dir}")

            if not os.path.exists(FIFO_rshs_dir):
                os.makedirs(FIFO_rshs_dir, exist_ok=True, cwd=FIFO_rshs_dir)
            
            await self._sendcommand_write_local_rshs_aux_header(
                            auxheader = "\t".join(self.palauxheader)+"\r\n",
                            output_file = palcam.aux_output_filepath
            )
            tmpjob = ' '.join([f'/loadmethod "{job.method}" "{job.params}"' for job in palcam.joblist])
            cmd_to_execute = f'PAL {tmpjob} /start /quit'
            self.base.print_message(f"PAL command: '{cmd_to_execute}'",
                                    info=True)
            try:
                # result = os.system(cmd_to_execute)
                palcam.joblist_time = self.active.set_realtime_nowait()
                self.PAL_pid = subprocess.Popen(cmd_to_execute, shell = True)
                self.base.print_message(f"PAL command send: {self.PAL_pid}")
            except Exception as e:
                self.base.print_message(
                    "CMD error. Could not send commands.",
                    error = True
                )
                self.base.print_message(
                    e,
                    error = True
                )
                error = ErrorCodes.cmd_error
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
                    self.base.print_message("SSH connection error. Retrying in 1 seconds.")
                    await asyncio.sleep(1)
    
    
            try:


                FIFO_rshs_dir,rshs_logfile = os.path.split(palcam.aux_output_filepath)
                FIFO_rshs_dir = FIFO_rshs_dir.replace("C:\\", "")
                FIFO_rshs_dir = FIFO_rshs_dir.replace("\\", "/")

                self.base.print_message(f"RSHS saving to: /cygdrive/c/{FIFO_rshs_dir}")

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
                self.base.print_message(f"final RSHS path: {rshs_path}")
            
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
                self.base.print_message(f"final RSHS logfile: {rshs_logfilefull}")

                tmpjob = " ".join([f"/loadmethod '{job.method}' '{job.params}'" for job in palcam.joblist])
                cmd_to_execute = f"tmux new-window PAL {tmpjob} /start /quit"
                

                self.base.print_message(f"PAL command: '{cmd_to_execute}'",
                                        info=True)
            
    
    
            except Exception as e:
                self.base.print_message(
                    "SSH connection error 1. Could not send commands.",
                    error = True
                )
                self.base.print_message(
                    e,
                    error = True
                )
                
                error = ErrorCodes.ssh_error
    
    
            try:
                if error is ErrorCodes.none:
                    palcam.joblist_time = self.active.set_realtime_nowait()
                    (
                        mysshclient_stdin,
                        mysshclient_stdout,
                        mysshclient_stderr,
                    ) = mysshclient.exec_command(cmd_to_execute)
                    mysshclient.close()
     
            except Exception:
                self.base.print_message(
                    "SSH connection error 2. Could not send commands.",
                    error = True
                )
                error = ErrorCodes.ssh_error
    
        return error


    async def _sendcommand_check_for_assemblytypes(
                                                  self, 
                                                  sample_type: str, 
                                                  assembly: AssemblySample
                                                  ) -> bool:
        for part in assembly.parts:
            if part.sample_type == sample_type:
                return True
        return False


    async def _sendcommand_update_archive_helper(
                                                 self, 
                                                 palaction: PalAction
                                                ) -> ErrorCodes:

        # update source and dest final samples
        palaction.source.sample_final = \
             await self.db_get_sample(palaction.source.sample_initial)
        if palaction.dest.sample_final:
            # should always only contain one sample
            if palaction.dest.sample_final[0].global_label is None:
                # dest_final contains a ref sample
                # the correct new sample should be always found 
                # in the last position of palaction.sample_out
                # which should already be uptodate
                palaction.dest.sample_final = [palaction.sample_out[-1]]
                pass
            else:
                palaction.dest.sample_final = \
                      await self.db_get_sample(palaction.dest.sample_final)



        error = ErrorCodes.none
        retval = False
        if palaction.source.sample_final:
            if palaction.source.position == "tray":
                retval = await self.archive.tray_update_position(
                                                  tray = palaction.source.tray,
                                                  slot = palaction.source.slot,
                                                  vial = palaction.source.vial,
                                                  sample = palaction.source.sample_final[0],
                                                  )
            else: # custom postion
                retval, sample = await self.archive.custom_update_position(
                                                  custom = palaction.source.position,
                                                  sample = palaction.source.sample_final[0],
                                                  )
        else:
            self.base.print_message("No sample in PAL source.", info = True)

        if palaction.dest.sample_final:
            if palaction.dest.position == "tray":
                retval = await self.archive.tray_update_position(
                                                  tray = palaction.dest.tray,
                                                  slot =palaction.dest.slot,
                                                  vial = palaction.dest.vial,
                                                  sample = palaction.dest.sample_final[0],
                                                  )
            else: # custom postion
                retval, sample = await self.archive.custom_update_position(
                                                  custom = palaction.dest.position,
                                                  sample = palaction.dest.sample_final[0],
                                                  )
        else:
            self.base.print_message("No sample in PAL dest.", info = True)
            


        if retval == False:
            error = ErrorCodes.not_available

        return error


    async def _sendcommand_update_sample_volume(
                                                self, 
                                                palaction: PalAction
                                               ) -> None:
        """updates sample volume only for input (sample_in)
        samples, output (sample_out) are always new samples"""
        if len(palaction.sample_in_delta_vol_ml) != len(palaction.sample_in):
            self.base.print_message("len(samples_in) != len(delta_vol)", error = True)
            return
        if len(palaction.dilute) != len(palaction.sample_in):
            self.base.print_message("len(samples_in) != len(dilute)", error = True)
            return
        if len(palaction.dilute_type) != len(palaction.sample_in):
            self.base.print_message("len(samples_in) != len(sample_type)", error = True)
            return

        for i, sample in enumerate(palaction.sample_in):
            if isinstance(sample, AssemblySample):
            # if sample.sample_type == _sampletype.assembly:
                for part in sample.parts:
                    if part.sample_type == palaction.dilute_type[i]:
                        part.update_vol(palaction.sample_in_delta_vol_ml[i], palaction.dilute[i])
            else:
                sample.update_vol(palaction.sample_in_delta_vol_ml[i], palaction.dilute[i])


    async def _init_PAL_IOloop(self, A: Action, palcam: PalCam) -> dict:
        """initializes the main PAL IO loop after an action was submitted"""
        activeDict = dict()
        if not self.IO_do_meas:
            self.IO_error = ErrorCodes.none
            self.IO_palcam = palcam
            self.action = A
            self.IO_continue = False
            self.IO_do_meas = True
            # wait for first continue trigger
            A.error_code = ErrorCodes.none
            while not self.IO_continue:
                await asyncio.sleep(1)
            A.error_code = self.IO_error
            if self.active:
                activeDict = self.active.action.as_dict()
            else:
                activeDict = A.as_dict()
        else:
            self.base.print_message("PAL method already in progress.", error = True)
            A.error_code = ErrorCodes.in_progress
            activeDict = A.as_dict()

        return activeDict


    async def _PAL_IOloop(self) -> None:
        """This is the main dispatch loop for the PAL.
        Its start when self.IO_do_meas is set to True
        and works on the current content of self.IO_palcam."""
        self.IOloop_run = True
        while self.IOloop_run:
            await asyncio.sleep(1)
            if self.IO_do_meas:
                if not self.base.actionserver.estop:
                    # create active and check sample_in
                    await self._PAL_IOloop_meas_start_helper()

                    # gets some internal timing references
                    start_time = time.time() # this is only internal 
                                             # time when the io loop was
                                             # started
                    last_run_time = start_time # the time of the last PAL run
                    prev_timepoint = 0.0
                    diff_time = 0.0
                    
                    # for multipe runs we don't wait for first trigger
                    if self.IO_palcam.totalruns > 1:
                        self.IO_continue = True

                    # loop over the requested runs of one complete 
                    # microcam list run
                    for run in range(self.IO_palcam.totalruns):
                        self.base.print_message(f"PAL run {run+1} of {self.IO_palcam.totalruns}")
                        # need to make a deepcopy as we modify this object during the run
                        # but each run should start from the same initial
                        # params again
                        run_palcam =  copy.deepcopy(self.IO_palcam)
                        run_palcam.cur_run = run

                        # # if sampleperiod list is empty 
                        # # set it to default
                        # if not self.IO_palcam.sampleperiod:
                        #     self.IO_palcam.sampleperiod = [0.0]


                        # get the scheduled time for next PAL command
                        # self.IO_palcam.timeoffset corrects for offset 
                        # between send ssh and continue (or any other offset)
                        
                        if len(self.IO_palcam.sampleperiod) < (run+1):
                            self.base.print_message("len(self.IO_palcam.sampleperiod) < (run), using 0.0", info = True)
                            sampleperiod = 0.0
                        else:
                            sampleperiod = self.IO_palcam.sampleperiod[run]
                        
                        if self.IO_palcam.spacingmethod == Spacingmethod.linear:
                            self.base.print_message("PAL linear scheduling")
                            cur_time = time.time()
                            self.base.print_message(f"time since last PAL run {(cur_time-last_run_time)}", info = True)
                            self.base.print_message(f"requested time between PAL runs {sampleperiod-self.IO_palcam.timeoffset}", info = True)
                            diff_time = sampleperiod-(cur_time-last_run_time)-self.IO_palcam.timeoffset
                        elif self.IO_palcam.spacingmethod == Spacingmethod.geometric:
                            self.base.print_message("PAL geometric scheduling")
                            timepoint = (self.IO_palcam.spacingfactor ** run) * sampleperiod
                            self.base.print_message(f"time since last PAL run {(cur_time-last_run_time)}", info = True)
                            self.base.print_message(f"requested time between PAL runs {timepoint-prev_timepoint-self.IO_palcam.timeoffset}", info = True)
                            diff_time = timepoint-prev_timepoint-(cur_time-last_run_time)-self.IO_palcam.timeoffset
                            prev_timepoint = timepoint # todo: consider time lag
                        elif self.IO_palcam.spacingmethod == Spacingmethod.custom:
                            self.base.print_message("PAL custom scheduling")
                            cur_time = time.time()
                            self.base.print_message(f"time since PAL start {(cur_time-start_time)}", info = True)
                            self.base.print_message(f"time for next PAL run since start {sampleperiod-self.IO_palcam.timeoffset}", info = True)
                            diff_time = sampleperiod-(cur_time-start_time)-self.IO_palcam.timeoffset


                        # only wait for positive time
                        self.base.print_message(f"PAL waits {diff_time} for sending next command", info = True)
                        if (diff_time > 0):
                            await asyncio.sleep(diff_time)


                        # finally submit a single PAL run
                        last_run_time = time.time()
                        self.base.print_message("PAL sendcommand def start", info = True)
                        self.IO_error = await self._sendcommand_main(run_palcam)
                        self.base.print_message("PAL sendcommand def end", info = True)


                    # update samples_in/out in prc
                    # and other cleanup
                    await self._PAL_IOloop_meas_end_helper()

                else:
                    self.IO_do_meas = False
                    self.base.print_message("PAL is in estop.")


    async def _PAL_IOloop_meas_start_helper(self) -> None:
        """sets active object and
        checks samples_in"""
        self.IO_action_run_counter = 0
        self.active = await self.base.contain_action(
        ActiveParams(
            action = self.action,
            file_conn_params_dict = {self.base.dflt_file_conn_key():
                FileConnParams(
                               file_conn_key = \
                                   self.base.dflt_file_conn_key(),
                               # sample_global_labels=[],
                               file_type="pal_helao__file",
                              )
                             }
        ))


        self.base.print_message(f"Active action uuid is {self.active.action.action_uuid}")
        if self.active:
            self.active.finish_hlo_header(file_conn_keys=self.active.action.file_conn_keys,
                                          realtime=await self.active.set_realtime())

        self.base.print_message(f"PAL_sample_in: {self.IO_palcam.sample_in}")
        # update sample list with correct information from db if possible
        self.base.print_message("getting current sample information for all sample_in from db")
        self.IO_palcam.sample_in = await self.db_get_sample(samples = self.IO_palcam.sample_in)


    async def _PAL_IOloop_meas_end_helper(self) -> None:
        """resets all IO variables
            and updates prc samples in and out"""

        if self.PAL_pid is not None:            
            self.base.print_message("waiting for PAL pid to finish")
            self.PAL_pid.communicate()
            self.PAL_pid = None

        self.IO_continue = True
        # done sending all PAL commands
        self.IO_do_meas = False
        self.IO_action_run_counter = 0


        # need to check here again in case estop was triggered during
        # measurement
        # need to set the current meas to idle first
        _ = await self.active.finish()
        self.active = None
        self.action = None

        if self.base.actionserver.estop:
            self.base.print_message("PAL is in estop.")
        else:
            self.base.print_message("setting PAL to idle")

        self.base.print_message("PAL is done")


    async def db_get_sample(
                            self, 
                            samples: List[SampleUnion]
                           ) -> List[SampleUnion]:
        return await self.unified_db.get_sample(samples=samples)


    async def db_new_sample(
                            self, 
                            samples: List[SampleUnion]
                           ) -> List[SampleUnion]:
        return await self.unified_db.new_sample(samples=samples)
    
    
    async def method_arbitrary(self, A: Action) -> dict:
        palcam = PalCam(**A.action_params)
        palcam.sample_in = A.samples_in
        return await self._init_PAL_IOloop(
            A = A,
            palcam = palcam
        )


    async def method_transfer_tray_tray(self, A: Action) -> dict:
        palcam = PalCam(
            sample_in = A.samples_in,
            totalruns = len(A.action_params.get("sampleperiod",[])),
            sampleperiod = A.action_params.get("sampleperiod",[]),
            spacingmethod = A.action_params.get("spacingmethod",Spacingmethod.linear),
            spacingfactor = A.action_params.get("spacingfactor",1.0),
            timeoffset = A.action_params.get("timeoffset",0.0),
            microcam = [PalMicroCam(**{
                    "method":"transfer_tray_tray",
                    "tool":A.action_params.get("tool",None),
                    "volume_ul":A.action_params.get("volume_ul",0),
                    "requested_source":PALposition(**{
                        "position":_positiontype.tray,
                        "tray":A.action_params.get("source_tray",0),
                        "slot":A.action_params.get("source_slot",0),
                        "vial":A.action_params.get("source_vial",0),
                        }),
                    "requested_dest":PALposition(**{
                        "position":_positiontype.tray,
                        "tray":A.action_params.get("dest_tray",0),
                        "slot":A.action_params.get("dest_slot",0),
                        "vial":A.action_params.get("dest_vial",0),
                        }),
                    "wash1":A.action_params.get("wash1",0),
                    "wash2":A.action_params.get("wash2",0),
                    "wash3":A.action_params.get("wash3",0),
                    "wash4":A.action_params.get("wash4",0),
                    })]
        )
        return await self._init_PAL_IOloop(
            A = A,
            palcam = palcam,
        )


    async def method_transfer_custom_tray(self, A: Action) -> dict:
        palcam = PalCam(
            sample_in = A.samples_in,
            totalruns = len(A.action_params.get("sampleperiod",[])),
            sampleperiod = A.action_params.get("sampleperiod",[]),
            spacingmethod = A.action_params.get("spacingmethod",Spacingmethod.linear),
            spacingfactor = A.action_params.get("spacingfactor",1.0),
            timeoffset = A.action_params.get("timeoffset",0.0),
            microcam = [PalMicroCam(**{
                    "method":"transfer_tray_tray",
                    "tool":A.action_params.get("tool",None),
                    "volume_ul":A.action_params.get("volume_ul",0),
                    "requested_source":PALposition(**{
                        "position":A.action_params.get("source",None),
                        }),
                    "requested_dest":PALposition(**{
                        "position":_positiontype.tray,
                        "tray":A.action_params.get("dest_tray",0),
                        "slot":A.action_params.get("dest_slot",0),
                        "vial":A.action_params.get("dest_vial",0),
                        }),
                    "wash1":A.action_params.get("wash1",0),
                    "wash2":A.action_params.get("wash2",0),
                    "wash3":A.action_params.get("wash3",0),
                    "wash4":A.action_params.get("wash4",0),
                    })]
        )
        return await self._init_PAL_IOloop(
            A = A,
            palcam = palcam,
        )


    async def method_transfer_tray_custom(self, A: Action) -> dict:
        palcam = PalCam(
            sample_in = A.samples_in,
            totalruns = len(A.action_params.get("sampleperiod",[])),
            sampleperiod = A.action_params.get("sampleperiod",[]),
            spacingmethod = A.action_params.get("spacingmethod",Spacingmethod.linear),
            spacingfactor = A.action_params.get("spacingfactor",1.0),
            timeoffset = A.action_params.get("timeoffset",0.0),
            microcam = [PalMicroCam(**{
                    "method":"transfer_tray_tray",
                    "tool":A.action_params.get("tool",None),
                    "volume_ul":A.action_params.get("volume_ul",0),
                    "requested_source":PALposition(**{
                        "position":_positiontype.tray,
                        "tray":A.action_params.get("source_tray",0),
                        "slot":A.action_params.get("source_slot",0),
                        "vial":A.action_params.get("source_vial",0),
                        }),
                    "requested_dest":PALposition(**{
                        "position":A.action_params.get("dest",None),
                        }),
                    "wash1":A.action_params.get("wash1",0),
                    "wash2":A.action_params.get("wash2",0),
                    "wash3":A.action_params.get("wash3",0),
                    "wash4":A.action_params.get("wash4",0),
                    })]
        )
        return await self._init_PAL_IOloop(
            A = A,
            palcam = palcam,
        )


    async def method_transfer_custom_custom(self, A: Action) -> dict:
        palcam = PalCam(
            sample_in = A.samples_in,
            totalruns = len(A.action_params.get("sampleperiod",[])),
            sampleperiod = A.action_params.get("sampleperiod",[]),
            spacingmethod = A.action_params.get("spacingmethod",Spacingmethod.linear),
            spacingfactor = A.action_params.get("spacingfactor",1.0),
            timeoffset = A.action_params.get("timeoffset",0.0),
            microcam = [PalMicroCam(**{
                    "method":"transfer_tray_tray",
                    "tool":A.action_params.get("tool",None),
                    "volume_ul":A.action_params.get("volume_ul",0),
                      "requested_source":PALposition(**{
                        "position":A.action_params.get("source",None),
                        }),
                    "requested_dest":PALposition(**{
                        "position":A.action_params.get("dest",None),
                        }),
                    "wash1":A.action_params.get("wash1",0),
                    "wash2":A.action_params.get("wash2",0),
                    "wash3":A.action_params.get("wash3",0),
                    "wash4":A.action_params.get("wash4",0),
                    })]
        )
        return await self._init_PAL_IOloop(
            A = A,
            palcam = palcam,
        )

    async def method_archive(self, A: Action) -> dict:
        palcam = PalCam(
            sample_in = A.samples_in,
            totalruns = len(A.action_params.get("sampleperiod",[])),
            sampleperiod = A.action_params.get("sampleperiod",[]),
            spacingmethod = A.action_params.get("spacingmethod",Spacingmethod.linear),
            spacingfactor = A.action_params.get("spacingfactor",1.0),
            timeoffset = A.action_params.get("timeoffset",0.0),
            microcam = [PalMicroCam(**{
                    "method":"archive",
                    "tool":A.action_params.get("tool",None),
                    "volume_ul":A.action_params.get("volume_ul",0),
                    "requested_source":PALposition(**{
                        "position":A.action_params.get("source",None),
                        }),
                    "wash1":A.action_params.get("wash1",0),
                    "wash2":A.action_params.get("wash2",0),
                    "wash3":A.action_params.get("wash3",0),
                    "wash4":A.action_params.get("wash4",0),
                    })]
        )
        return await self._init_PAL_IOloop(
            A = A,
            palcam = palcam,
        )
    
    

    # async def method_fill(self, A: Action) -> dict:
    #     palcam = PalCam(
    #         sample_in = A.samples_in,
    #         totalruns = 1,
    #         sampleperiod = [],
    #         spacingmethod = Spacingmethod.linear,
    #         spacingfactor = 1.0,
    #         timeoffset = 0.0,
    #         microcam = [PalMicroCam(**{
    #                 "method":"fill",
    #                 "tool":A.action_params.get("tool",None),
    #                 "volume_ul":A.action_params.get("volume_ul",0),
    #                 "requested_source":PALposition(**{
    #                     "position":A.action_params.get("source",None),
    #                     }),
    #                 "requested_dest":PALposition(**{
    #                     "position":A.action_params.get("dest",None),
    #                     }),
    #                 "wash1":A.action_params.get("wash1",0),
    #                 "wash2":A.action_params.get("wash2",0),
    #                 "wash3":A.action_params.get("wash3",0),
    #                 "wash4":A.action_params.get("wash4",0),
    #                 })]
    #     )
    #     return await self._init_PAL_IOloop(
    #         A = A,
    #         palcam = palcam,
    #     )


    # async def method_fillfixed(self, A: Action) -> dict:
    #     palcam = PalCam(
    #         sample_in = A.samples_in,
    #         totalruns = 1,
    #         sampleperiod = [],
    #         spacingmethod = Spacingmethod.linear,
    #         spacingfactor = 1.0,
    #         timeoffset = 0.0,
    #         microcam = [PalMicroCam(**{
    #                 "method":"fillfixed",
    #                 "tool":A.action_params.get("tool",None),
    #                 "volume_ul":A.action_params.get("volume_ul",0),
    #                 "requested_source":PALposition(**{
    #                     "position":A.action_params.get("source",None),
    #                     }),
    #                 "requested_dest":PALposition(**{
    #                     "position":A.action_params.get("dest",None),
    #                     }),
    #                 "wash1":A.action_params.get("wash1",0),
    #                 "wash2":A.action_params.get("wash2",0),
    #                 "wash3":A.action_params.get("wash3",0),
    #                 "wash4":A.action_params.get("wash4",0),
    #                 })]
    #     )
    #     return await self._init_PAL_IOloop(
    #         A = A,
    #         palcam = palcam,
    #     )


    async def method_deepclean(self, A: Action) -> dict:
        palcam = PalCam(
            sample_in = A.samples_in,
            totalruns = 1,
            sampleperiod = [],
            spacingmethod = Spacingmethod.linear,
            spacingfactor = 1.0,
            timeoffset = 0.0,
            microcam = [
                PalMicroCam(**{
                    "method":"deepclean",
                    "tool":A.action_params.get("tool",None),
                    "volume_ul":A.action_params.get("volume_ul",0),
                    "wash1":A.action_params.get("wash1",1),
                    "wash2":A.action_params.get("wash2",1),
                    "wash3":A.action_params.get("wash3",1),
                    "wash4":A.action_params.get("wash4",1),
                    })
            ]
        )
        return await self._init_PAL_IOloop(
            A = A,
            palcam = palcam,
        )


    # async def method_dilute(self, A: Action) -> dict:
    #     palcam = PalCam(
    #         sample_in = A.samples_in,
    #         totalruns = len(A.action_params.get("sampleperiod",[])),
    #         sampleperiod = A.action_params.get("sampleperiod",[]),
    #         spacingmethod = A.action_params.get("spacingmethod",Spacingmethod.linear),
    #         spacingfactor = A.action_params.get("spacingfactor",1.0),
    #         timeoffset = A.action_params.get("timeoffset",0.0),
    #         microcam = [PalMicroCam(**{
    #                 "method":"dilute",
    #                 "tool":A.action_params.get("tool",None),
    #                 "volume_ul":A.action_params.get("volume_ul",0),
    #                 "requested_source":PALposition(**{
    #                     "position":A.action_params.get("source",None),
    #                     }),
    #                 "requested_dest":PALposition(**{
    #                     "position":_positiontype.tray,
    #                     "tray":A.action_params.get("dest_tray",0),
    #                     "slot":A.action_params.get("dest_slot",0),
    #                     "vial":A.action_params.get("dest_vial",0),
    #                     }),
    #                 "wash1":A.action_params.get("wash1",1),
    #                 "wash2":A.action_params.get("wash2",1),
    #                 "wash3":A.action_params.get("wash3",1),
    #                 "wash4":A.action_params.get("wash4",1),
    #                 })]
    #     )
    #     return await self._init_PAL_IOloop(
    #         A = A,
    #         palcam = palcam,
    #     )


    # async def method_autodilute(self, A: Action) -> dict:
    #     palcam = PalCam(
    #         sample_in = A.samples_in,
    #         totalruns = len(A.action_params.get("sampleperiod",[])),
    #         sampleperiod = A.action_params.get("sampleperiod",[]),
    #         spacingmethod = A.action_params.get("spacingmethod",Spacingmethod.linear),
    #         spacingfactor = A.action_params.get("spacingfactor",1.0),
    #         timeoffset = A.action_params.get("timeoffset",0.0),
    #         microcam = [PalMicroCam(**{
    #                 "method":"autodilute",
    #                 "tool":A.action_params.get("tool",None),
    #                 "volume_ul":A.action_params.get("volume_ul",0),
    #                 "requested_source":PALposition(**{
    #                     "position":A.action_params.get("source",None),
    #                     }),
    #                 "wash1":A.action_params.get("wash1",1),
    #                 "wash2":A.action_params.get("wash2",1),
    #                 "wash3":A.action_params.get("wash3",1),
    #                 "wash4":A.action_params.get("wash4",1),
    #                 })]
    #     )
    #     return await self._init_PAL_IOloop(
    #         A = A,
    #         palcam = palcam,
    #     )


    async def method_injection_tray_GC(self, A: Action) -> dict:
        start = A.action_params.get("startGC",None)

        if start == True:
            start = "start"
        elif start == False:
            start = "wait"

        sampletype = A.action_params.get("sampletype",GCsampletype.none)

        method = f"injection_tray_GC_{str(sampletype.name)}_{start}"

        palcam = PalCam(
            sample_in = A.samples_in,
            totalruns = 1,
            sampleperiod = [],
            spacingmethod = Spacingmethod.linear,
            spacingfactor = 1.0,
            timeoffset = 0.0,
            microcam = [PalMicroCam(**{
                    "method":method,
                    "tool":A.action_params.get("tool",None),
                    "volume_ul":A.action_params.get("volume_ul",0),
                    "requested_source":PALposition(**{
                        "position":_positiontype.tray,
                        "tray":A.action_params.get("source_tray",0),
                        "slot":A.action_params.get("source_slot",0),
                        "vial":A.action_params.get("source_vial",0),
                        }),
                    "requested_dest":PALposition(**{
                        "position":A.action_params.get("dest",None),
                        }),
                    "wash1":A.action_params.get("wash1",0),
                    "wash2":A.action_params.get("wash2",0),
                    "wash3":A.action_params.get("wash3",0),
                    "wash4":A.action_params.get("wash4",0),
                    })]
        )
        return await self._init_PAL_IOloop(
            A = A,
            palcam = palcam,
        )


    async def method_injection_custom_GC(self, A: Action) -> dict:
        start = A.action_params.get("startGC",None)

        if start == True:
            start = "start"
        elif start == False:
            start = "wait"

        sampletype = A.action_params.get("sampletype",GCsampletype.none)

        method = f"injection_custom_GC_{str(sampletype.name)}_{start}"


        palcam = PalCam(
            sample_in = A.samples_in,
            totalruns = 1,
            sampleperiod = [],
            spacingmethod = Spacingmethod.linear,
            spacingfactor = 1.0,
            timeoffset = 0.0,
            microcam = [PalMicroCam(**{
                    "method":method,
                    "tool":A.action_params.get("tool",None),
                    "volume_ul":A.action_params.get("volume_ul",0),
                    "requested_source":PALposition(**{
                        "position":A.action_params.get("source",None),
                        }),
                    "requested_dest":PALposition(**{
                        "position":A.action_params.get("dest",None),
                        }),
                    "wash1":A.action_params.get("wash1",0),
                    "wash2":A.action_params.get("wash2",0),
                    "wash3":A.action_params.get("wash3",0),
                    "wash4":A.action_params.get("wash4",0),
                    })]
        )
        return await self._init_PAL_IOloop(
            A = A,
            palcam = palcam,
        )


    async def method_injection_tray_HPLC(self, A: Action) -> dict:
        palcam = PalCam(
            sample_in = A.samples_in,
            totalruns = 1,
            sampleperiod = [],
            spacingmethod = Spacingmethod.linear,
            spacingfactor = 1.0,
            timeoffset = 0.0,
            microcam = [PalMicroCam(**{
                    "method":"injection_tray_HPLC",
                    "tool":A.action_params.get("tool",None),
                    "volume_ul":A.action_params.get("volume_ul",0),
                    "requested_source":PALposition(**{
                        "position":_positiontype.tray,
                        "tray":A.action_params.get("source_tray",0),
                        "slot":A.action_params.get("source_slot",0),
                        "vial":A.action_params.get("source_vial",0),
                        }),
                    "requested_dest":PALposition(**{
                        "position":A.action_params.get("dest",None),
                        }),
                    "wash1":A.action_params.get("wash1",0),
                    "wash2":A.action_params.get("wash2",0),
                    "wash3":A.action_params.get("wash3",0),
                    "wash4":A.action_params.get("wash4",0),
                    })]
        )
        return await self._init_PAL_IOloop(
            A = A,
            palcam = palcam,
        )
    
    
    async def method_injection_custom_HPLC(self, A: Action) -> dict:
        palcam = PalCam(
            sample_in = A.samples_in,
            totalruns = 1,
            sampleperiod = [],
            spacingmethod = Spacingmethod.linear,
            spacingfactor = 1.0,
            timeoffset = 0.0,
            microcam = [PalMicroCam(**{
                    "method":"injection_custom_HPLC",
                    "tool":A.action_params.get("tool",None),
                    "volume_ul":A.action_params.get("volume_ul",0),
                    "requested_source":PALposition(**{
                        "position":A.action_params.get("source",None),
                        }),
                    "requested_dest":PALposition(**{
                        "position":A.action_params.get("dest",None),
                        }),
                    "wash1":A.action_params.get("wash1",0),
                    "wash2":A.action_params.get("wash2",0),
                    "wash3":A.action_params.get("wash3",0),
                    "wash4":A.action_params.get("wash4",0),
                    })]
        )
        return await self._init_PAL_IOloop(
            A = A,
            palcam = palcam,
        )


    async def method_ANEC_GC(self, A: Action) -> dict:
        palcam = PalCam(
            sample_in = A.samples_in,
            totalruns = 1,
            sampleperiod = [],
            spacingmethod = Spacingmethod.linear,
            spacingfactor = 1.0,
            timeoffset = 0.0,
            microcam = [
                PalMicroCam(**{
                    "method":"injection_custom_GC_gas_wait",
                    "tool":A.action_params.get("toolGC",None),
                    "volume_ul":A.action_params.get("volume_ul_GC",0),
                    "requested_source":PALposition(**{
                        "position":A.action_params.get("source",None),
                        }),
                    "requested_dest":PALposition(**{
                        "position":"Injector 2",
                        }),
                    "wash1":0,
                    "wash2":0,
                    "wash3":0,
                    "wash4":0,
                }),
                PalMicroCam(**{
                    "method":"injection_custom_GC_gas_start",
                    "tool":A.action_params.get("toolGC",None),
                    "volume_ul":A.action_params.get("volume_ul_GC",0),
                    "requested_source":PALposition(**{
                        "position":A.action_params.get("source",None),
                        }),
                    "requested_dest":PALposition(**{
                        "position":"Injector 1",
                        }),
                    "wash1":0,
                    "wash2":0,
                    "wash3":0,
                    "wash4":0,
                })
            ]
        )
        return await self._init_PAL_IOloop(
            A = A,
            palcam = palcam,
        )


    async def method_ANEC_aliquot(self, A: Action) -> dict:
        palcam = PalCam(
            sample_in = A.samples_in,
            totalruns = 1,
            sampleperiod = [],
            spacingmethod = Spacingmethod.linear,
            spacingfactor = 1.0,
            timeoffset = 0.0,
            microcam = [
                PalMicroCam(**{
                    "method":"injection_custom_GC_gas_wait",
                    "tool":A.action_params.get("toolGC",None),
                    "volume_ul":A.action_params.get("volume_ul_GC",0),
                    "requested_source":PALposition(**{
                        "position":A.action_params.get("source",None),
                        }),
                    "requested_dest":PALposition(**{
                        "position":"Injector 2",
                        }),
                    "wash1":0,
                    "wash2":0,
                    "wash3":0,
                    "wash4":0,
                }),
                PalMicroCam(**{
                    "method":"injection_custom_GC_gas_start",
                    "tool":A.action_params.get("toolGC",None),
                    "volume_ul":A.action_params.get("volume_ul_GC",0),
                    "requested_source":PALposition(**{
                        "position":A.action_params.get("source",None),
                        }),
                    "requested_dest":PALposition(**{
                        "position":"Injector 1",
                        }),
                    "wash1":0,
                    "wash2":0,
                    "wash3":0,
                    "wash4":0,
                }),
                PalMicroCam(**{
                        "method":"archive",
                        "tool":A.action_params.get("toolarchive",None),
                        "volume_ul":A.action_params.get("volume_ul_archive",0),
                        "requested_source":PALposition(**{
                            "position":A.action_params.get("source",None),
                            }),
                        "wash1":A.action_params.get("wash1",0),
                        "wash2":A.action_params.get("wash2",0),
                        "wash3":A.action_params.get("wash3",0),
                        "wash4":A.action_params.get("wash4",0),
                })
            ]
        )
        return await self._init_PAL_IOloop(
            A = A,
            palcam = palcam,
        )
