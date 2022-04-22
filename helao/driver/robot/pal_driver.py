__all__ = ["Spacingmethod", "PALtools", "PALposition", "PAL", "GCsampletype"]

import asyncio
import os
import paramiko
import time
from copy import deepcopy
from typing import List, Optional, Union, Tuple
from pydantic import BaseModel, Field
import aiofiles
import subprocess
import psutil

from helaocore.schema import Action
from helaocore.server.base import Base
from helaocore.error import ErrorCodes
from helaocore.helper.helaodict import HelaoDict

from helaocore.model.sample import (
    SampleUnion,
    NoneSample,
    AssemblySample,
    SampleStatus,
    SampleInheritance,
    SampleType,
)
from helaocore.model.file import FileConnParams
from helaocore.model.active import ActiveParams
from helaocore.model.data import DataModel
from helao.driver.data.archive_driver import Archive
from helao.driver.robot.enum import (
    PALtools,
    CAMS,
    Spacingmethod,
    _positiontype,
    _cam,
    GCsampletype,
)

import nidaqmx
from nidaqmx.constants import LineGrouping


class _palcmd(BaseModel):
    method: str = ""
    params: str = ""


class PALposition(BaseModel, HelaoDict):
    position: Optional[str]  # dest can be cust. or tray
    samples_initial: List[SampleUnion] = Field(default_factory=list)
    samples_final: List[SampleUnion] = Field(default_factory=list)
    # sample: List[SampleUnion] = Field(default_factory=list)  # holds dest/source position
    # will be also added to
    # sample in/out
    # depending on cam
    tray: Optional[int]
    slot: Optional[int]
    vial: Optional[int]
    error: Optional[ErrorCodes] = ErrorCodes.none


class PalAction(BaseModel, HelaoDict):
    samples_in: List[SampleUnion] = Field(default_factory=list)
    # this initially always holds
    # references which need to be
    # converted to
    # to a real sample later
    samples_out: List[SampleUnion] = Field(default_factory=list)

    # this holds the runtime list for excution of the PAL cam
    # a microcam could run 'repeat' times
    dest: Optional[PALposition]
    source: Optional[PALposition]

    dilute: List[bool] = Field(default_factory=list)
    dilute_type: List[Union[str, None]] = Field(default_factory=list)
    samples_in_delta_vol_ml: List[float] = Field(
        default_factory=list
    )  # contains a list of
    # delta volumes
    # for samples_in
    # for each repeat

    # I probably don't need them as lists but can keep it for now
    start_time: Optional[int]
    continue_time: Optional[int]
    done_time: Optional[int]


class PalMicroCam(BaseModel, HelaoDict):
    # scalar values which are the same for each repetition of the PAL method
    method: str = None  # name of methods
    tool: str = None
    volume_ul: int = 0  # uL
    # this holds a single resuested source and destination
    requested_dest: PALposition = PALposition()
    requested_source: PALposition = PALposition()

    wash1: bool = False
    wash2: bool = False
    wash3: bool = False
    wash4: bool = False

    path_methodfile: str = ""  # all shoukld be in the same folder
    rshs_pal_logfile: str = ""  # one PAL action logs into one logfile
    cam: _cam = _cam()
    repeat: int = 0

    # for each microcam repetition we save a list of results
    run: List[PalAction] = Field(default_factory=list)


class PalCam(BaseModel, HelaoDict):
    samples_in: List[SampleUnion] = Field(default_factory=list)
    samples_out: List[SampleUnion] = Field(default_factory=list)

    microcams: List[PalMicroCam] = Field(default_factory=list)

    totalruns: int = 1
    sampleperiod: List[float] = Field(default_factory=list)
    spacingmethod: Spacingmethod = "linear"
    spacingfactor: float = 1.0
    timeoffset: float = 0.0  # sec
    cur_run: int = 0

    joblist: list = Field(default_factory=list)
    joblist_time: int = None
    aux_output_filepath: str = None


class PAL:
    def __init__(self, action_serv: Base):

        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.world_config = action_serv.world_cfg

        self.archive = Archive(self.base)

        self.sshuser = self.config_dict.get("user", "")
        self.sshkey = self.config_dict.get("key", "")
        self.sshhost = self.config_dict.get("host", None)
        self.cam_file_path = self.config_dict.get("cam_file_path", "")
        self.timeout = self.config_dict.get("timeout", 30 * 60)
        self.PAL_pid = None

        self.triggers = False
        self.IO_trigger_task = None
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
            self.base.print_message(
                f"PAL continue trigger port: {self.triggerport_continue}"
            )
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
        self.IO_measuring = False  # status flag of measurement
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
            "samples_in",
            "samples_out",
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

        self.palauxheader = [
            "Date",
            "Method",
            "Tool",
            "Source",
            "DestinationTray",
            "DestinationSlot",
            "DestinationVial",
            "Volume",
        ]
        self.IOloop_run = False
        self.IO_signalq = asyncio.Queue(1)
        self.IO_trigger_startq = asyncio.Queue()
        self.IO_trigger_continueq = asyncio.Queue()
        self.IO_trigger_doneq = asyncio.Queue()

    def check_tool(self, req_tool=None):
        names = [e.name for e in PALtools]
        vals = [e.value for e in PALtools]
        idx = None
        if req_tool in vals:
            idx = vals.index(req_tool)
        elif req_tool in names:
            idx = names.index(req_tool)
        if idx is None:
            self.base.print_message(f"unknown PAL tool: {req_tool}", error=True)
            return None
        else:
            return PALtools(vals[idx]).value

    def set_IO_signalq_nowait(self, val: bool) -> None:
        if self.IO_signalq.full():
            _ = self.IO_signalq.get_nowait()
        self.IO_signalq.put_nowait(val)

    async def set_IO_signalq(self, val: bool) -> None:
        if self.IO_signalq.full():
            _ = await self.IO_signalq.get()
        await self.IO_signalq.put(val)

    async def _clear_trigger_qs(self):
        while not self.IO_trigger_startq.empty():
            timecode = await self.IO_trigger_startq.get()
            self.base.print_message(f"startq was not empty: '{timecode}'", error=True)
        while not self.IO_trigger_continueq.empty():
            timecode = await self.IO_trigger_continueq.get()
            self.base.print_message(
                f"continyeq was not empty: '{timecode}'", error=True
            )
        while not self.IO_trigger_doneq.empty():
            timecode = await self.IO_trigger_doneq.get()
            self.base.print_message(f"doneq was not empty: '{timecode}'", error=True)

    async def _poll_trigger_task(self):
        prev_start = False
        prev_continue = False
        prev_done = False
        if not self.triggers:
            return
        try:
            with nidaqmx.Task() as task:
                self.base.print_message(
                    f"using trigger port "
                    f"'{self.triggerport_start}' "
                    "for 'start' trigger",
                    info=True,
                )
                task.di_channels.add_di_chan(
                    self.triggerport_start, line_grouping=LineGrouping.CHAN_PER_LINE
                )
                self.base.print_message(
                    f"using trigger port "
                    f"'{self.triggerport_continue}' "
                    f"for 'continue' trigger",
                    info=True,
                )
                task.di_channels.add_di_chan(
                    self.triggerport_continue, line_grouping=LineGrouping.CHAN_PER_LINE
                )
                self.base.print_message(
                    f"using trigger port "
                    f"'{self.triggerport_done}' "
                    "for 'done' trigger",
                    info=True,
                )
                task.di_channels.add_di_chan(
                    self.triggerport_done, line_grouping=LineGrouping.CHAN_PER_LINE
                )
                while self.IO_measuring:
                    data = task.read(number_of_samples_per_channel=1)
                    new_start = data[0][0]
                    new_continue = data[1][0]
                    new_done = data[2][0]
                    if (new_start ^ prev_start) and new_start:
                        self.IO_trigger_startq.put_nowait(
                            self.active.set_realtime_nowait()
                        )
                        prev_start = deepcopy(new_start)
                        self.base.print_message(
                            "IOq: got PAL 'start' trigger poll", info=True
                        )
                    if (new_start ^ prev_start) and not new_start:
                        prev_start = deepcopy(new_start)

                    if (new_continue ^ prev_continue) and new_continue:
                        self.IO_trigger_continueq.put_nowait(
                            self.active.set_realtime_nowait()
                        )
                        prev_continue = deepcopy(new_continue)
                        self.base.print_message(
                            "IOq: got PAL 'continue' trigger poll", info=True
                        )

                    if (new_continue ^ prev_continue) and not new_continue:
                        prev_continue = deepcopy(new_continue)

                    if (new_done ^ prev_done) and new_done:
                        self.IO_trigger_doneq.put_nowait(
                            self.active.set_realtime_nowait()
                        )
                        prev_done = deepcopy(new_done)
                        self.base.print_message(
                            "IOq: got PAL 'done' trigger poll", info=True
                        )

                    if (new_done ^ prev_done) and not new_done:
                        prev_done = deepcopy(new_done)

                    await asyncio.sleep(0.1)

        except Exception as e:
            self.base.print_message(
                f"_poll_trigger_task excited with error: {e}", error=True
            )

    async def _sendcommand_main(self, palcam: PalCam) -> ErrorCodes:
        """PAL takes liquid from sample_in and puts it in sample_out"""
        error = ErrorCodes.none

        # check if we have free vial slots
        # and update the microcams with correct positions and samples_out
        error = await self._sendcommand_prechecks(palcam)
        if error is not ErrorCodes.none:
            self.base.print_message(
                f"Got error after pre-checks: '{error}'", error=True
            )
            return error

        # assemble complete PAL command from microcams to submit a full joblist
        error = await self._sendcommand_submitjoblist_helper(palcam)
        if error is not ErrorCodes.none:
            self.base.print_message(
                f"Got error after sendcommand_ssh_helper: '{error}'", error=True
            )
            return error

        if error is not ErrorCodes.none:
            return error

        # wait for each microcam cam
        self.base.print_message("Waiting now for all microcams")
        for microcam in palcam.microcams:

            if not self.IO_signalq.empty():
                self.IO_measuring = await self.IO_signalq.get()
            if not self.IO_measuring:
                break

            self.base.print_message(f"waiting now '{microcam.method}'")
            # wait for each repeat of the same microcam
            for palaction in microcam.run:
                if not self.IO_signalq.empty():
                    self.IO_measuring = await self.IO_signalq.get()
                if not self.IO_measuring:
                    break

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
                self.IO_palcam.samples_in = []
                self.IO_palcam.samples_out = []
                self.base.print_message("waiting now for palaction")
                # waiting now for all three PAL triggers
                # continue is used as the sampling timestamp
                # populates the three trigger timings in palaction

                error = await self._sendcommand_triggerwait(palaction)

                if error is not ErrorCodes.none:
                    # there is not much we can do here
                    # as we have not control of pal directly
                    self.active.action.error_code = error
                    self.base.print_message(
                        f"Got error after triggerwait: '{error}'", error=True
                    )

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
                # (4) add all to the action samples_in/out
                #     samples_in: initial state
                #     sample_out: always new samples (final state)
                # (5) then update samples_in parameters to reflect
                #     the final states (samples_in_initial --> samples_in_final)
                #     and update all sample_out info (for assemblies again)
                # (6) save this back to the db (only samples_in)
                # (7) update all positions in the archive
                #     with new final samples
                # (8) write all output files
                # (9) add samples_in/out to active.action

                # -- (1) -- get most recent information for all samples_in
                # palaction.samples_in should always be non ref samples
                palaction.samples_in = await self.archive.unified_db.get_samples(
                    samples=palaction.samples_in
                )
                # update the action_uuid
                for sample in palaction.samples_in:
                    sample.action_uuid = [self.active.action.action_uuid]
                # as palaction.samples_in contains both source and dest samples
                # we had them saved separately (this is for the hlo file)

                # palaction.source should also always contain non ref samples
                palaction.source.samples_initial = (
                    await self.archive.unified_db.get_samples(
                        samples=palaction.source.samples_initial
                    )
                )
                # update the action_uuid
                for sample in palaction.source.samples_initial:
                    sample.action_uuid = [self.active.action.action_uuid]

                # dest can also contain ref samples, and these are not yet in the db
                for dest_i, dest_sample in enumerate(palaction.dest.samples_initial):
                    if dest_sample.global_label is not None:
                        dest_tmp = await self.archive.unified_db.get_samples(
                            samples=[dest_sample]
                        )
                        if dest_tmp:
                            palaction.dest.samples_initial[dest_i] = deepcopy(
                                dest_tmp[0]
                            )
                        else:
                            self.base.print_message(
                                "Sample does not exist in db", error=True
                            )
                            return ErrorCodes.critical
                    else:
                        self.base.print_message(
                            "palaction.dest.samples_initial "
                            "should not contain ref samples",
                            error=True,
                        )
                        return ErrorCodes.bug
                # update the action_uuid
                for sample in palaction.dest.samples_initial:
                    sample.action_uuid = [self.active.action.action_uuid]

                # -- (2) -- update sample_out
                # only samples in sample_out should be new ones (ref samples)
                # convert these to real samples by adding them to the db
                # update sample creation time
                for sample_out in palaction.samples_out:
                    self.base.print_message(
                        f" converting ref sample {sample_out} to real sample", info=True
                    )
                    sample_out.sample_creation_timecode = palaction.continue_time

                    # if the sample was destroyed during this run set its
                    # volume to zero
                    # destroyed: destination was waste or injector
                    # for newly created samples
                    if SampleStatus.destroyed in sample_out.status:
                        sample_out.destroy_sample()

                    # if sample_out is an assembly we need to update its parts
                    if sample_out.sample_type == SampleType.assembly:
                        # could also check if it has parts attribute?
                        # reset source
                        sample_out.source = []
                        for part_i, part in enumerate(sample_out.parts):
                            if part.global_label is not None:
                                tmp_part = await self.archive.unified_db.get_samples(
                                    samples=[part]
                                )
                                for sample in tmp_part:
                                    sample.action_uuid = [
                                        self.active.action.action_uuid
                                    ]
                                sample_out.parts[part_i] = deepcopy(tmp_part[0])
                            else:
                                # the assembly contains a ref sample which
                                # first need to be updated and converted
                                part.sample_creation_timecode = palaction.continue_time
                                part.action_uuid = [self.active.action.action_uuid]
                                tmp_part = await self.archive.unified_db.new_samples(
                                    samples=[part]
                                )
                                sample_out.parts[part_i] = deepcopy(tmp_part[0])
                            # now add the real samples back to the source list
                            sample_out.source.append(part.get_global_label())
                        # update the action_uuid
                        for sample in sample_out.parts:
                            sample.action_uuid = [self.active.action.action_uuid]

                # update the action_uuid
                for sample in palaction.samples_out:
                    sample.action_uuid = [self.active.action.action_uuid]

                # -- (3) -- convert samples_out references to real sample
                #           by adding them to the to db
                palaction.samples_out = await self.archive.unified_db.new_samples(
                    samples=palaction.samples_out
                )

                # -- (4) -- add palaction samples to action object
                # add palaction samples_in out to main palcam
                # these should be initial samples
                # properties are updated later and saved back to db
                # need a deep copy, else the next modifications would also
                # modify these samples
                for sample_in in palaction.samples_in:
                    self.IO_palcam.samples_in.append(deepcopy(sample_in))
                # add palaction sample_out to main palcam
                for sample in palaction.samples_out:
                    self.IO_palcam.samples_out.append(deepcopy(sample))

                # -- (5) -- convert pal action samples_in
                # from initial to final
                # update the sample volumes
                # (needed only for input samples, samples_out are always
                # new samples)
                await self._sendcommand_update_sample_volume(palaction)

                # -- (6) --
                # update all samples also in the local sample sqlite db
                await self.archive.unified_db.update_samples(palaction.samples_in)

                for sample_out in palaction.samples_out:
                    # if sample_out is an assembly we need to update its parts
                    if sample_out.sample_type == SampleType.assembly:
                        sample_out.parts = await self.archive.unified_db.get_samples(
                            samples=sample_out.parts
                        )
                    # update the action_uuid
                    sample_out.action_uuid = [self.active.action.action_uuid]
                    # save it back to the db
                    await self.archive.unified_db.update_samples([sample_out])

                # -- (7) -- update the sample position db
                error = await self._sendcommand_update_archive_helper(palaction)

                # -- (8) -- write data (hlo file)
                if self.active:
                    if self.active.action.save_data:
                        logdata = [
                            [
                                sample.get_global_label()
                                for sample in palaction.source.samples_initial
                            ],
                            [
                                sample.get_global_label()
                                for sample in palaction.dest.samples_initial
                            ],
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

                        tmpdata = {
                            k: [v] for k, v in zip(self.FIFO_column_headings, logdata)
                        }
                        # self.active.action.file_conn_keys holds the current
                        # active file conn keys
                        # cannot use the one which we used for contain action
                        # as action.split will generate a new one
                        # but will always update the one in
                        # self.active.action.file_conn_keys[0]
                        # to the current one
                        await self.active.enqueue_data(
                            datamodel=DataModel(
                                data={self.active.action.file_conn_keys[0]: tmpdata},
                                errors=[],
                            )
                        )
                        self.base.print_message(f"PAL data: {tmpdata}")

                # (9) add samples_in/out to active.action
                # add sample in and out to exp

                await self.active.append_sample(
                    samples=self.IO_palcam.samples_in, IO="in"
                )

                await self.active.append_sample(
                    samples=self.IO_palcam.samples_out, IO="out"
                )

        # wait another 20sec for program to close
        # after final done
        tmp_time = 20
        self.base.print_message(f"waiting {tmp_time}sec for PAL to close", info=True)
        await asyncio.sleep(tmp_time)
        self.base.print_message(
            f"done waiting {tmp_time}sec for PAL to close", info=True
        )
        if self.PAL_pid is not None:
            self.base.print_message("waiting for PAL pid to finish", info=True)
            self.PAL_pid.communicate()
            self.PAL_pid = None

        return error

    async def _sendcommand_next_full_vial(
        self,
        after_tray: int,
        after_slot: int,
        after_vial: int,
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
            after_tray=after_tray, after_slot=after_slot, after_vial=after_vial
        )

        if newvialpos["tray"] is not None:
            tray_pos = newvialpos["tray"]
            slot_pos = newvialpos["slot"]
            vial_pos = newvialpos["vial"]

            self.base.print_message(
                f"diluting liquid sample in tray {tray_pos}, slot {slot_pos}, vial {vial_pos}"
            )

            # need to get the sample which is currently in this vial
            # and also add it to global samples_in
            error, sample = await self.archive.tray_query_sample(
                tray=tray_pos, slot=slot_pos, vial=vial_pos
            )
            if error != ErrorCodes.none:
                if sample != NoneSample():
                    sample.inheritance = SampleInheritance.allow_both
                    sample.status = [SampleStatus.preserved]
                else:
                    error = ErrorCodes.not_available
                    self.base.print_message(
                        "error converting old liquid_sample to basemodel.", error=True
                    )

        else:
            self.base.print_message("no full vial slots", error=True)
            error = ErrorCodes.not_available

        return error, tray_pos, slot_pos, vial_pos, sample

    async def _sendcommand_check_source_tray(
        self, microcam: PalMicroCam
    ) -> PALposition:
        """checks for a valid sample in tray source position"""
        source = (
            _positiontype.tray
        )  # should be the same as microcam.requested_source.position
        error, sample_in = await self.archive.tray_query_sample(
            microcam.requested_source.tray,
            microcam.requested_source.slot,
            microcam.requested_source.vial,
        )

        if error != ErrorCodes.none:
            self.base.print_message(
                "PAL_source: Requested tray position does not exist.", error=True
            )
            error = ErrorCodes.critical

        elif sample_in == NoneSample():
            self.base.print_message(
                f"PAL_source: No sample in tray "
                f"{microcam.requested_source.tray}, "
                f"slot {microcam.requested_source.slot}, "
                f"vial {microcam.requested_source.vial}",
                error=True,
            )
            error = ErrorCodes.not_available

        return PALposition(
            position=source,
            samples_initial=[sample_in],
            tray=microcam.requested_source.tray,
            slot=microcam.requested_source.slot,
            vial=microcam.requested_source.vial,
            error=error,
        )

    async def _sendcommand_check_source_custom(
        self, microcam: PalMicroCam
    ) -> PALposition:
        """checks for a valid sample in custom source position"""
        source = microcam.requested_source.position  # custom position name

        if source is None:
            self.base.print_message(
                "PAL_source: Invalid PAL source "
                "'NONE' for 'custom' position method.",
                error=True,
            )
            return PALposition(error=ErrorCodes.not_available)

        error, sample_in = await self.archive.custom_query_sample(
            microcam.requested_source.position
        )

        if error != ErrorCodes.none:
            self.base.print_message(
                "PAL_source: Requested custom position does not exist.", error=True
            )
            error = ErrorCodes.critical
        elif sample_in == NoneSample():
            self.base.print_message(
                f"PAL_source: No sample in custom position '{source}'", error=True
            )
            error = ErrorCodes.not_available

        return PALposition(position=source, samples_initial=[sample_in], error=error)

    async def _sendcommand_check_source_next_empty(
        self, microcam: PalMicroCam
    ) -> PALposition:
        """source can never be empty, throw an error"""
        self.base.print_message(
            "PAL_source: PAL source cannot be 'next_empty_vial'", error=True
        )
        return PALposition(error=ErrorCodes.not_available)

    async def _sendcommand_check_source_next_full(
        self, microcam: PalMicroCam
    ) -> PALposition:
        """find the next full vial in a tray AFTER the requested
        source position"""

        source = _positiontype.tray
        (
            error,
            source_tray,
            source_slot,
            source_vial,
            sample_in,
        ) = await self._sendcommand_next_full_vial(
            after_tray=microcam.requested_source.tray,
            after_slot=microcam.requested_source.slot,
            after_vial=microcam.requested_source.vial,
        )
        if error != ErrorCodes.none:
            self.base.print_message("PAL_source: No next full vial", error=True)
            return PALposition(error=ErrorCodes.not_available)

        elif sample_in == NoneSample():
            self.base.print_message(
                "PAL_source: More then one sample in source position. This is not allowed.",
                error=True,
            )
            return PALposition(error=ErrorCodes.critical)

        return PALposition(
            position=source,
            samples_initial=[sample_in],
            tray=source_tray,
            slot=source_slot,
            vial=source_vial,
            error=error,
        )

    async def _sendcommand_check_source(self, microcam: PalMicroCam) -> ErrorCodes:

        """Checks if a sample is present in the source position.
        An error is returned if no sample is found.
        Else the sample in the source postion is added to sample in.
        'Inheritance' and 'status' are set later when the destination
        is determined."""

        palposition = PALposition()

        # check against desired source type
        if microcam.cam.source == _positiontype.tray:
            palposition = await self._sendcommand_check_source_tray(microcam=microcam)
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.source == _positiontype.custom:
            palposition = await self._sendcommand_check_source_custom(microcam=microcam)
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.source == _positiontype.next_empty_vial:
            palposition = await self._sendcommand_check_source_next_empty(
                microcam=microcam
            )
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.source == _positiontype.next_full_vial:
            palposition = await self._sendcommand_check_source_next_empty(
                microcam=microcam
            )
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
        if (
            palposition.samples_initial
            and len(palposition.samples_initial) == 1
            and palposition.samples_initial[0] != NoneSample()
        ):

            self.base.print_message(
                f"PAL_source: Got sample "
                f"'{palposition.samples_initial[0].global_label}' "
                f"in position '{palposition.position}'",
                info=True,
            )
            # done with checking source type
            # setting inheritance and status to None for all samples
            # in sample_in (will be updated when dest is decided)
            # they all should actually be give only
            # but might not be preserved depending on target
            # sample_in.inheritance =  SampleInheritance.give_only
            # sample_in.status = [SampleStatus.preserved]
            palposition.samples_initial[0].inheritance = None
            palposition.samples_initial[0].status = []
            palposition.samples_initial[0].sample_position = palposition.position

        else:
            # this should never happen
            # else we have a bug in the source checks
            if palposition.position is not None:
                self.base.print_message(
                    f"BUG check PAL_source: "
                    f"Got sample no sample in position "
                    f"'{palposition.position}'",
                    error=True,
                )

        microcam.run.append(
            PalAction(
                samples_in=deepcopy(palposition.samples_initial),
                source=deepcopy(palposition),
                dilute=[False],  # initial source is not diluted
                dilute_type=[microcam.cam.sample_out_type],
                samples_in_delta_vol_ml=[-1.0 * microcam.volume_ul / 1000.0],
            )
        )

        return ErrorCodes.none

    async def _sendcommand_check_dest_tray(
        self, microcam: PalMicroCam
    ) -> Tuple[PALposition, List[SampleUnion]]:
        """checks for a valid sample in tray destination position"""
        samples_out_list: List[SampleUnion] = []
        dest_samples_initial: List[SampleUnion] = []
        dest_samples_final: List[SampleUnion] = []

        dest = _positiontype.tray
        error, sample_in = await self.archive.tray_query_sample(
            microcam.requested_dest.tray,
            microcam.requested_dest.slot,
            microcam.requested_dest.vial,
        )

        if error != ErrorCodes.none:
            self.base.print_message(
                "PAL_dest: Requested tray position does not exist.", error=True
            )
            return PALposition(error=ErrorCodes.critical), samples_out_list

        # check if a sample is present in destination
        if sample_in == NoneSample():
            # no sample in dest, create a new sample reference
            self.base.print_message(
                f"PAL_dest: No sample in tray "
                f"{microcam.requested_dest.tray}, "
                f"slot {microcam.requested_dest.slot}, "
                f"vial {microcam.requested_dest.vial}",
                info=True,
            )
            if len(microcam.run[-1].samples_in) > 1:
                self.base.print_message(
                    f"PAL_dest: Found a BUG: "
                    f"Assembly not allowed for PAL dest "
                    f"'{dest}' for 'tray' "
                    f"position method.",
                    error=True,
                )
                return PALposition(error=ErrorCodes.bug), samples_out_list

            error, samples_out_list = await self.archive.new_ref_samples(
                samples_in=microcam.run[
                    -1
                ].samples_in,  # this should hold a sample already from "check source call"
                sample_out_type=microcam.cam.sample_out_type,
                sample_position=dest,
                action=self.active.action,
            )

            if error != ErrorCodes.none:
                return PALposition(error=error), samples_out_list

            # this will be a single sample anyway
            samples_out_list[0].volume_ml = microcam.volume_ul / 1000.0
            samples_out_list[0].sample_position = dest
            samples_out_list[0].inheritance = SampleInheritance.receive_only
            samples_out_list[0].status = [SampleStatus.created]
            dest_samples_initial = []  # no sample here in the beginning
            dest_samples_final = deepcopy(samples_out_list)

        else:
            # a sample is already present in the tray position
            # we add more sample to it, e.g. dilute it
            self.base.print_message(
                f"PAL_dest: Got sample "
                f"'{sample_in.global_label}' "
                f"in position '{dest}'",
                info=True,
            )
            # we can only add liquid to vials (diluite them, no assembly here)
            sample_in.inheritance = SampleInheritance.receive_only
            sample_in.status = [SampleStatus.preserved]

            dest_samples_initial = [deepcopy(sample_in)]
            dest_samples_final = [deepcopy(sample_in)]

            # add that sample to the current sample_in list
            microcam.run[-1].samples_in.append(deepcopy(sample_in))
            microcam.run[-1].samples_in_delta_vol_ml.append(microcam.volume_ul / 1000.0)
            microcam.run[-1].dilute.append(True)
            microcam.run[-1].dilute_type.append(sample_in.sample_type)

        return (
            PALposition(
                position=dest,
                samples_initial=dest_samples_initial,
                samples_final=dest_samples_final,
                tray=microcam.requested_dest.tray,
                slot=microcam.requested_dest.slot,
                vial=microcam.requested_dest.vial,
                error=error,
            ),
            samples_out_list,
        )

    async def _sendcommand_check_dest_custom(
        self, microcam: PalMicroCam
    ) -> Tuple[PALposition, List[SampleUnion]]:
        """checks for a valid sample in custom destination position"""
        samples_out_list: List[SampleUnion] = []
        dest_samples_initial: List[SampleUnion] = []
        dest_samples_final: List[SampleUnion] = []

        dest = microcam.requested_dest.position
        if dest is None:
            self.base.print_message(
                "PAL_dest: Invalid PAL dest 'NONE' for 'custom' position method.",
                error=True,
            )
            return PALposition(error=ErrorCodes.critical), samples_out_list

        if not self.archive.custom_dest_allowed(dest):
            self.base.print_message(
                f"PAL_dest: custom position '{dest}' cannot be dest.", error=True
            )
            return PALposition(error=ErrorCodes.critical), samples_out_list

        error, sample_in = await self.archive.custom_query_sample(dest)
        if error != ErrorCodes.none:
            self.base.print_message(
                f"PAL_dest: Invalid PAL dest '{dest}' for 'custom' position method.",
                error=True,
            )
            return PALposition(error=error), samples_out_list

        # check if a sample is already present in the custom position
        if sample_in == NoneSample():
            # no sample in custom position, create a new sample reference
            self.base.print_message(
                f"PAL_dest: No sample in custom position "
                "'{dest}', creating new "
                "sample reference.",
                info=True,
            )

            # cannot create an assembly
            if len(microcam.run[-1].samples_in) > 1:
                self.base.print_message(
                    "PAL_dest: Found a BUG: "
                    "Too many input samples. "
                    "Cannot create an assembly here.",
                    error=True,
                )
                return PALposition(error=ErrorCodes.bug), samples_out_list

            # this should actually never create an assembly
            error, samples_out_list = await self.archive.new_ref_samples(
                samples_in=microcam.run[-1].samples_in,
                sample_out_type=microcam.cam.sample_out_type,
                sample_position=dest,
                action=self.active.action,
            )

            if error != ErrorCodes.none:
                return PALposition(error=error), samples_out_list

            samples_out_list[0].volume_ml = microcam.volume_ul / 1000.0
            samples_out_list[0].sample_position = dest
            samples_out_list[0].inheritance = SampleInheritance.receive_only
            samples_out_list[0].status = [SampleStatus.created]
            dest_samples_initial = []  # no sample here in the beginning
            dest_samples_final = deepcopy(samples_out_list)

        else:
            # sample is already present
            # either create an assembly or dilute it
            # first check what type is present
            self.base.print_message(
                f"PAL_dest: Got sample '{sample_in.global_label}' in position '{dest}'",
                info=True,
            )

            if sample_in.sample_type == SampleType.assembly:
                # need to check if we already go the same type in
                # the assembly and then would dilute too
                # else we add a new sample to that assembly

                # source input should only hold a single sample
                # but better check for sure
                if len(microcam.run[-1].samples_in) > 1:
                    self.base.print_message(
                        "PAL_dest: Found a BUG: "
                        "Too many input samples. "
                        "Cannot create an assembly here.",
                        error=True,
                    )
                    return PALposition(error=ErrorCodes.bug), samples_out_list

                test = False
                if microcam.run[-1].samples_in[-1].sample_type == SampleType.liquid:
                    test = await self._sendcommand_check_for_assemblytypes(
                        sample_type=SampleType.liquid, assembly=sample_in
                    )
                elif microcam.run[-1].samples_in[-1].sample_type == SampleType.solid:
                    test = False  # always add it as a new part
                elif microcam.run[-1].samples_in[-1].sample_type == SampleType.gas:
                    test = await self._sendcommand_check_for_assemblytypes(
                        sample_type=SampleType.gas, assembly=sample_in
                    )
                else:
                    self.base.print_message(
                        "PAL_dest: Found a BUG: unsupported sample type.", error=True
                    )
                    return PALposition(error=ErrorCodes.bug), samples_out_list

                if test is True:
                    # we dilute the assembly sample
                    dest_samples_initial = deepcopy(samples_out_list)
                    dest_samples_final = deepcopy(samples_out_list)

                    # we can only add liquid to vials
                    # (diluite them, no assembly here)
                    sample_in.inheritance = SampleInheritance.receive_only
                    sample_in.status = [SampleStatus.preserved]

                    # first add the dilute type
                    microcam.run[-1].dilute_type.append(
                        microcam.run[-1].samples_in[-1].sample_type
                    )
                    microcam.run[-1].samples_in_delta_vol_ml.append(
                        microcam.volume_ul / 1000.0
                    )
                    microcam.run[-1].dilute.append(True)
                    # then add the new sample_in
                    microcam.run[-1].samples_in.append(deepcopy(sample_in))
                else:
                    # add a new part to assembly
                    self.base.print_message(
                        "PAL_dest: Adding new part to assembly", info=True
                    )
                    if len(microcam.run[-1].samples_in) > 1:
                        # sample_in should only hold one sample at that point
                        self.base.print_message(
                            f"PAL_dest: Found a BUG: Assembly not allowed for PAL dest '{dest}' for 'tray' position method.",
                            error=True,
                        )
                        return PALposition(error=ErrorCodes.bug), samples_out_list

                    # first create a new sample from the source sample
                    # which is then incoporarted into the assembly
                    error, samples_out_list = await self.archive.new_ref_samples(
                        samples_in=microcam.run[
                            -1
                        ].samples_in,  # this should hold a sample already from "check source call"
                        sample_out_type=microcam.cam.sample_out_type,
                        sample_position=dest,
                        action=self.active.action,
                    )

                    if error != ErrorCodes.none:
                        return PALposition(error=error), samples_out_list

                    samples_out_list[0].volume_ml = microcam.volume_ul / 1000.0
                    samples_out_list[0].sample_position = dest
                    samples_out_list[0].inheritance = SampleInheritance.allow_both
                    samples_out_list[0].status = [
                        SampleStatus.created,
                        SampleStatus.incorporated,
                    ]

                    # add new sample to assembly
                    sample_in.parts.append(samples_out_list[0])
                    # we can only add liquid to vials
                    # (diluite them, no assembly here)
                    sample_in.inheritance = SampleInheritance.allow_both
                    sample_in.status = [SampleStatus.preserved]

                    dest_samples_initial = [deepcopy(sample_in)]
                    dest_samples_final = [deepcopy(sample_in)]
                    microcam.run[-1].samples_in.append(deepcopy(sample_in))

            elif sample_in.sample_type == microcam.run[-1].samples_in[-1].sample_type:
                # we dilute it if its the same sample type
                # (and not an assembly),
                # we can only add liquid to vials
                # (diluite them, no assembly here)
                sample_in.inheritance = SampleInheritance.receive_only
                sample_in.status = [SampleStatus.preserved]

                dest_samples_initial = [deepcopy(sample_in)]
                dest_samples_final = [deepcopy(sample_in)]

                microcam.run[-1].dilute_type.append(sample_in.sample_type)
                microcam.run[-1].samples_in.append(deepcopy(sample_in))
                microcam.run[-1].samples_in_delta_vol_ml.append(
                    microcam.volume_ul / 1000.0
                )
                microcam.run[-1].dilute.append(True)

            else:
                # neither same sample type nor an assembly present.
                # we now create an assembly if allowed
                if not self.archive.custom_assembly_allowed(dest):
                    # no assembly allowed
                    self.base.print_message(
                        f"PAL_dest: Assembly not allowed "
                        f"for PAL dest '{dest}' for "
                        f"'custom' position method.",
                        error=True,
                    )
                    return PALposition(error=ErrorCodes.not_allowed), samples_out_list

                # cannot create an assembly from an assembly
                if len(microcam.run[-1].samples_in) > 1:
                    self.base.print_message(
                        "PAL_dest: Found a BUG: "
                        "Too many input samples. "
                        "Cannot create an assembly here.",
                        error=True,
                    )
                    return PALposition(error=ErrorCodes.bug), samples_out_list

                # dest_sample = sample_in
                # first create a new sample from the source sample
                # which is then incoporarted into the assembly
                error, samples_out_list = await self.archive.new_ref_samples(
                    samples_in=microcam.run[-1].samples_in,
                    sample_out_type=microcam.cam.sample_out_type,
                    sample_position=dest,
                    action=self.active.action,
                )

                if error != ErrorCodes.none:
                    return PALposition(error=error), samples_out_list

                samples_out_list[0].volume_ml = microcam.volume_ul / 1000.0
                samples_out_list[0].sample_position = dest
                samples_out_list[0].inheritance = SampleInheritance.allow_both
                samples_out_list[0].status = [
                    SampleStatus.created,
                    SampleStatus.incorporated,
                ]

                # only now add the sample which was found in the position
                # to the sample_in list for the exp/prg
                sample_in.inheritance = SampleInheritance.allow_both
                sample_in.status = [SampleStatus.incorporated]

                microcam.run[-1].samples_in.append(deepcopy(sample_in))
                # we only add the sample to assembly so delta_vol is 0
                microcam.run[-1].samples_in_delta_vol_ml.append(0.0)
                microcam.run[-1].dilute.append(False)
                microcam.run[-1].dilute_type.append(None)

                # create now an assembly of both
                tmp_samples_in = [sample_in]
                # and also add the newly created sample ref to it
                tmp_samples_in.append(samples_out_list[0])
                self.base.print_message(
                    f"PAL_dest: Creating assembly from "
                    f"'{[sample.global_label for sample in tmp_samples_in]}'"
                    f" in position '{dest}'",
                    info=True,
                )
                error, samples_out2_list = await self.archive.new_ref_samples(
                    samples_in=tmp_samples_in,
                    sample_out_type=SampleType.assembly,
                    sample_position=dest,
                    action=self.active.action,
                )

                if error != ErrorCodes.none:
                    return PALposition(error=error), samples_out_list

                samples_out2_list[0].sample_position = dest
                samples_out2_list[0].inheritance = SampleInheritance.allow_both
                samples_out2_list[0].status = [SampleStatus.created]
                # add second sample out to samples_out
                samples_out_list.append(samples_out2_list[0])

                # intial is the sample initial in the position
                dest_samples_initial = [deepcopy(sample_in)]
                # this will be the new assembly
                dest_samples_final = deepcopy(samples_out2_list)

        return (
            PALposition(
                position=dest,
                samples_initial=dest_samples_initial,
                samples_final=dest_samples_final,
                tray=microcam.requested_dest.tray,
                slot=microcam.requested_dest.slot,
                vial=microcam.requested_dest.vial,
                error=error,
            ),
            samples_out_list,
        )

    async def _sendcommand_check_dest_next_empty(
        self, microcam: PalMicroCam
    ) -> Tuple[PALposition, List[SampleUnion]]:
        """find the next empty vial in a tray"""
        samples_out_list: List[SampleUnion] = []
        dest_samples_initial: List[SampleUnion] = []
        dest_samples_final: List[SampleUnion] = []

        dest_tray = None
        dest_slot = None
        dest_vial = None

        dest = _positiontype.tray
        newvialpos = await self.archive.tray_new_position(
            req_vol=microcam.volume_ul / 1000.0
        )

        if newvialpos["tray"] is None:
            self.base.print_message(
                "PAL_dest: empty vial slot is not available", error=True
            )
            return PALposition(error=ErrorCodes.not_available), samples_out_list

        # dest = _positiontype.tray
        dest_tray = newvialpos["tray"]
        dest_slot = newvialpos["slot"]
        dest_vial = newvialpos["vial"]
        self.base.print_message(
            f"PAL_dest: archiving liquid sample to tray {dest_tray}, slot {dest_slot}, vial {dest_vial}"
        )

        error, samples_out_list = await self.archive.new_ref_samples(
            samples_in=microcam.run[
                -1
            ].samples_in,  # this should hold a sample already from "check source call"
            sample_out_type=microcam.cam.sample_out_type,
            sample_position=dest,
            action=self.active.action,
        )

        self.base.print_message(
            f"new reference sample for empty vial: {samples_out_list}"
        )

        if error != ErrorCodes.none:
            return PALposition(error=error), samples_out_list

        samples_out_list[0].volume_ml = microcam.volume_ul / 1000.0
        samples_out_list[0].sample_position = dest
        samples_out_list[0].inheritance = SampleInheritance.receive_only
        samples_out_list[0].status = [SampleStatus.created]
        dest_samples_initial = []  # no sample here in the beginning
        dest_samples_final = deepcopy(samples_out_list)

        return (
            PALposition(
                position=dest,
                samples_initial=dest_samples_initial,
                samples_final=dest_samples_final,
                tray=dest_tray,
                slot=dest_slot,
                vial=dest_vial,
                error=error,
            ),
            samples_out_list,
        )

    async def _sendcommand_check_dest_next_full(
        self, microcam: PalMicroCam
    ) -> Tuple[PALposition, List[SampleUnion]]:
        """find the next full vial in a tray AFTER the requested
        destination position"""
        samples_out_list: List[SampleUnion] = []
        dest_samples_initial: List[SampleUnion] = []
        dest_samples_final: List[SampleUnion] = []

        dest = None
        dest_tray = None
        dest_slot = None
        dest_vial = None

        dest = _positiontype.tray
        (
            error,
            dest_tray,
            dest_slot,
            dest_vial,
            sample_in,
        ) = await self._sendcommand_next_full_vial(
            after_tray=microcam.requested_dest.tray,
            after_slot=microcam.requested_dest.slot,
            after_vial=microcam.requested_dest.vial,
        )
        if error != ErrorCodes.none:
            self.base.print_message("PAL_dest: No next full vial", error=True)
            return PALposition(error=ErrorCodes.not_available), samples_out_list
        if sample_in == NoneSample():
            self.base.print_message(
                "PAL_dest: More then one sample in source position. This is not allowed.",
                error=True,
            )
            return PALposition(error=ErrorCodes.critical), samples_out_list

        # a sample is already present in the tray position
        # we add more sample to it, e.g. dilute it
        self.base.print_message(
            f"PAL_dest: Got sample '{sample_in.global_label}' in position '{dest}'",
            info=True,
        )
        sample_in.inheritance = SampleInheritance.receive_only
        sample_in.status = [SampleStatus.preserved]

        microcam.run[-1].samples_in.append(sample_in)
        microcam.run[-1].samples_in_delta_vol_ml.append(microcam.volume_ul / 1000.0)
        microcam.run[-1].dilute.append(True)
        microcam.run[-1].dilute_type.append(sample_in.sample_type)

        dest_samples_initial = [deepcopy(sample_in)]
        dest_samples_final = [deepcopy(sample_in)]

        return (
            PALposition(
                position=dest,
                samples_initial=dest_samples_initial,
                samples_final=dest_samples_final,
                tray=dest_tray,
                slot=dest_slot,
                vial=dest_vial,
                error=error,
            ),
            samples_out_list,
        )

    async def _sendcommand_check_dest(self, microcam: PalMicroCam) -> ErrorCodes:

        """Checks if the destination position is empty or contains a sample.
        If it finds a sample, it either creates an assembly or
        will dilute it (if liquid is added to liquid).
        If no sample is found it will create a reference sample of the
        correct type."""

        samples_out_list: List[SampleUnion] = []
        palposition = PALposition()

        if microcam.cam.dest == _positiontype.tray:
            palposition, samples_out_list = await self._sendcommand_check_dest_tray(
                microcam=microcam
            )
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.dest == _positiontype.custom:
            palposition, samples_out_list = await self._sendcommand_check_dest_custom(
                microcam=microcam
            )
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.dest == _positiontype.next_empty_vial:
            (
                palposition,
                samples_out_list,
            ) = await self._sendcommand_check_dest_next_empty(microcam=microcam)
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.dest == _positiontype.next_full_vial:
            (
                palposition,
                samples_out_list,
            ) = await self._sendcommand_check_dest_next_full(microcam=microcam)
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
        if self.archive.custom_is_destroyed(custom=palposition.position):
            for sample in samples_out_list:
                sample.status.append(SampleStatus.destroyed)
            for sample in palposition.samples_final:
                sample.status.append(SampleStatus.destroyed)

        # add validated destination to run
        microcam.run[-1].dest = deepcopy(palposition)

        # update the rest of sample_in for the run
        for sample in microcam.run[-1].samples_in:
            if sample.inheritance is None:
                sample.inheritance = SampleInheritance.give_only
                sample.status = [SampleStatus.preserved]

        # add the samples_out to the run
        for sample in samples_out_list:
            microcam.run[-1].samples_out.append(sample)

        # a quick message if samples will be diluted or not
        for i, sample in enumerate(microcam.run[-1].samples_in):
            if microcam.run[-1].dilute[i]:
                self.base.print_message(
                    f"PAL: Diluting sample_in '{sample.global_label}'.", info=True
                )
            else:
                self.base.print_message(
                    f"PAL: Not diluting sample_in '{sample.global_label}'.", info=True
                )

        return ErrorCodes.none

    async def _sendcommand_prechecks(self, palcam: PalCam) -> ErrorCodes:
        error = ErrorCodes.none
        palcam.joblist = []

        # Set the aux log file for the exteral pal program
        # It needs to exists before the joblist is submitted
        # else nothing will be recorded
        # if PAL is on an exernal machine, this will be empty
        # but we need the correct outputpath to create it on the
        # other machine
        palcam.aux_output_filepath = self.active.write_file_nowait(
            file_type="pal_auxlog_file",
            filename="AUX__PAL__log.txt",
            output_str="",
            header="\t".join(self.palauxheader),
            sample_str=None,
        )

        # loop over the list of microcams (joblist)
        for microcam in palcam.microcams:
            # get the correct cam definition which contains all params
            # for the correct submission of the job to the PAL
            if microcam.method in [e.name for e in self.cams]:
                if self.cams[microcam.method].value.file_name is not None:
                    microcam.cam = self.cams[microcam.method].value
                else:
                    self.base.print_message(
                        f"cam method '{microcam.method}' is not available", error=True
                    )
                    return ErrorCodes.not_available
            else:
                self.base.print_message(
                    f"cam method '{microcam.method}' is not available", error=True
                )
                return ErrorCodes.not_available

            # set runs to empty list
            # shouldn't actually need it but better be sure its an empty list
            # at this point
            microcam.run = []

            for repeat in range(microcam.repeat + 1):

                # check source position
                error = await self._sendcommand_check_source(microcam)
                if error != ErrorCodes.none:
                    return error
                # check target position
                error = await self._sendcommand_check_dest(microcam)
                if error != ErrorCodes.none:
                    return error

                # add cam to cammand list
                camfile = os.path.join(microcam.cam.file_path, microcam.cam.file_name)
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

                palcam.joblist.append(
                    _palcmd(
                        method=f"{camfile}",
                        params=f"{microcam.tool};{microcam.volume_ul};{source};{source_tray};{source_slot};{source_vial};{dest};{dest_tray};{dest_slot};{dest_vial};{wash1};{wash2};{wash3};{wash4};{microcam.rshs_pal_logfile}",
                    )
                )

        return error

    async def _sendcommand_triggerwait(self, palaction: PalAction) -> ErrorCodes:
        error = ErrorCodes.none
        # only wait if triggers are configured
        if not self.triggers:
            self.base.print_message("No triggers configured", error=True)
            return error

        self.base.print_message("waiting for PAL start trigger", info=True)
        try:
            val = await asyncio.wait_for(self.IO_trigger_startq.get(), self.timeout)
        except Exception as e:
            self.base.print_message(
                f"PAL start trigger timeout with error: {e}", error=True
            )
            # also need to set IO_continue and IO_error
            # so active can return
            # else it will return after real first continue trigger
            self.IO_error = ErrorCodes.done_timeout
            self.IO_continue = True
            return ErrorCodes.done_timeout

        palaction.start_time = val
        self.base.print_message(
            "got PAL start trigger, waiting for PAL continue trigger", info=True
        )

        try:
            val = await asyncio.wait_for(self.IO_trigger_continueq.get(), self.timeout)
        except Exception as e:
            self.base.print_message(
                f"PAL continue trigger timeout with error: {e}", error=True
            )
            return ErrorCodes.done_timeout

        self.IO_continue = True
        palaction.continue_time = val
        self.base.print_message(
            "got PAL continue trigger, waiting for PAL done trigger", info=True
        )

        try:
            val = await asyncio.wait_for(self.IO_trigger_doneq.get(), self.timeout)
        except Exception as e:
            self.base.print_message(
                f"PAL done trigger timeout with error: {e}", error=True
            )
            return ErrorCodes.done_timeout

        palaction.done_time = val
        self.base.print_message("got PAL done trigger", info=True)

        return error

    async def _sendcommand_write_local_rshs_aux_header(self, auxheader, output_file):
        async with aiofiles.open(output_file, mode="w+") as f:
            await f.write(auxheader)

    async def _sendcommand_submitjoblist_helper(self, palcam: PalCam) -> ErrorCodes:

        error = ErrorCodes.none
        # kill PAL if program is open
        error = await self.kill_PAL()
        if error is not ErrorCodes.none:
            self.base.print_message("Could not close PAL", error=True)
            return error

        await self._clear_trigger_qs()
        self.IO_trigger_task = asyncio.create_task(self._poll_trigger_task())
        if self.sshhost == "localhost":

            FIFO_rshs_dir, rshs_logfile = os.path.split(palcam.aux_output_filepath)
            self.base.print_message(f"RSHS saving to: {FIFO_rshs_dir}")

            if not os.path.exists(FIFO_rshs_dir):
                os.makedirs(FIFO_rshs_dir, exist_ok=True, cwd=FIFO_rshs_dir)

            await self._sendcommand_write_local_rshs_aux_header(
                auxheader="\t".join(self.palauxheader) + "\r\n",
                output_file=palcam.aux_output_filepath,
            )
            tmpjob = " ".join(
                [f'/loadmethod "{job.method}" "{job.params}"' for job in palcam.joblist]
            )
            cmd_to_execute = f"PAL {tmpjob} /start /quit"
            self.base.print_message(f"PAL command: '{cmd_to_execute}'", info=True)
            try:
                # result = os.system(cmd_to_execute)
                palcam.joblist_time = self.active.set_realtime_nowait()
                self.PAL_pid = subprocess.Popen(cmd_to_execute, shell=True)
                self.base.print_message(f"PAL command send: {self.PAL_pid}")
            except Exception as e:
                self.base.print_message(
                    "CMD error. Could not send commands.", error=True
                )
                self.base.print_message(e, error=True)
                error = ErrorCodes.cmd_error
        elif self.sshhost is not None:
            ssh_connected = False
            while not ssh_connected:
                try:
                    # open SSH to PAL
                    k = paramiko.RSAKey.from_private_key_file(self.sshkey)
                    mysshclient = paramiko.SSHClient()
                    mysshclient.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    mysshclient.connect(
                        hostname=self.sshhost, username=self.sshuser, pkey=k
                    )
                    ssh_connected = True
                except Exception as e:
                    ssh_connected = False
                    self.base.print_message(
                        f"SSH connection error. Retrying in 1 seconds.\n{e}",
                        error=True,
                    )
                    await asyncio.sleep(1)

            try:

                FIFO_rshs_dir, rshs_logfile = os.path.split(palcam.aux_output_filepath)
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

                auxheader = "\t".join(self.palauxheader) + "\r\n"
                sshcmd = f"echo -e '{auxheader}' > {rshs_logfilefull}"
                (
                    mysshclient_stdin,
                    mysshclient_stdout,
                    mysshclient_stderr,
                ) = mysshclient.exec_command(sshcmd)
                self.base.print_message(f"final RSHS logfile: {rshs_logfilefull}")

                tmpjob = " ".join(
                    [
                        f"/loadmethod '{job.method}' '{job.params}'"
                        for job in palcam.joblist
                    ]
                )
                cmd_to_execute = f"tmux new-window PAL {tmpjob} /start /quit"

                self.base.print_message(f"PAL command: '{cmd_to_execute}'", info=True)

            except Exception as e:
                self.base.print_message(
                    f"SSH connection error 1. Could not send commands.\n{e}", error=True
                )
                self.base.print_message(e, error=True)

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

            except Exception as e:
                self.base.print_message(
                    f"SSH connection error 2. Could not send commands.\n{e}", error=True
                )
                error = ErrorCodes.ssh_error

        return error

    async def _sendcommand_check_for_assemblytypes(
        self, sample_type: str, assembly: AssemblySample
    ) -> bool:
        for part in assembly.parts:
            if part.sample_type == sample_type:
                return True
        return False

    async def _sendcommand_update_archive_helper(
        self, palaction: PalAction
    ) -> ErrorCodes:

        # update source and dest final samples
        palaction.source.samples_final = await self.archive.unified_db.get_samples(
            samples=palaction.source.samples_initial
        )
        # update the action_uuid
        for sample in palaction.source.samples_final:
            sample.action_uuid = [self.active.action.action_uuid]

        if palaction.dest.samples_final:
            # should always only contain one sample
            if palaction.dest.samples_final[0].global_label is None:
                # dest_final contains a ref sample
                # the correct new sample should be always found
                # in the last position of palaction.samples_out
                # which should already be uptodate
                palaction.dest.samples_final = [palaction.samples_out[-1]]
                pass
            else:
                palaction.dest.samples_final = (
                    await self.archive.unified_db.get_samples(
                        samples=palaction.dest.samples_final
                    )
                )

        # update the action_uuid
        for sample in palaction.dest.samples_final:
            sample.action_uuid = [self.active.action.action_uuid]

        error = ErrorCodes.none
        retval = False
        if palaction.source.samples_final:
            if palaction.source.position == "tray":
                retval = await self.archive.tray_update_position(
                    tray=palaction.source.tray,
                    slot=palaction.source.slot,
                    vial=palaction.source.vial,
                    sample=palaction.source.samples_final[0],
                )
            else:  # custom postion
                retval, sample = await self.archive.custom_update_position(
                    custom=palaction.source.position,
                    sample=palaction.source.samples_final[0],
                )
        else:
            self.base.print_message("No sample in PAL source.", info=True)

        if palaction.dest.samples_final:
            if palaction.dest.position == "tray":
                retval = await self.archive.tray_update_position(
                    tray=palaction.dest.tray,
                    slot=palaction.dest.slot,
                    vial=palaction.dest.vial,
                    sample=palaction.dest.samples_final[0],
                )
            else:  # custom postion
                retval, sample = await self.archive.custom_update_position(
                    custom=palaction.dest.position,
                    sample=palaction.dest.samples_final[0],
                )
        else:
            self.base.print_message("No sample in PAL dest.", info=True)

        if not retval:
            error = ErrorCodes.not_available

        return error

    async def _sendcommand_update_sample_volume(self, palaction: PalAction) -> None:
        """updates sample volume only for input (sample_in)
        samples, output (sample_out) are always new samples"""
        if len(palaction.samples_in_delta_vol_ml) != len(palaction.samples_in):
            self.base.print_message("len(samples_in) != len(delta_vol)", error=True)
            return
        if len(palaction.dilute) != len(palaction.samples_in):
            self.base.print_message("len(samples_in) != len(dilute)", error=True)
            return
        if len(palaction.dilute_type) != len(palaction.samples_in):
            self.base.print_message("len(samples_in) != len(sample_type)", error=True)
            return

        for i, sample in enumerate(palaction.samples_in):
            if sample.sample_type == SampleType.assembly:
                # if sample.sample_type == SampleType.assembly:
                for part in sample.parts:
                    if part.sample_type == palaction.dilute_type[i]:
                        part.update_vol(
                            palaction.samples_in_delta_vol_ml[i], palaction.dilute[i]
                        )
            else:
                sample.update_vol(
                    palaction.samples_in_delta_vol_ml[i], palaction.dilute[i]
                )

    async def _init_PAL_IOloop(self, A: Action, palcam: PalCam) -> dict:
        """initializes the main PAL IO loop after an action was submitted"""
        activeDict = {}
        if (
            self.sshhost is not None
            and not self.IO_do_meas
            and not self.IO_measuring
            and not self.base.actionserver.estop
        ):
            self.base.print_message("init PAL IO loop", info=True)
            self.IO_error = ErrorCodes.none
            # do a check of the PAL tool
            for microcam in palcam.microcams:
                microcam.tool = self.check_tool(req_tool=microcam.tool)
                if microcam.tool is None:
                    self.IO_error = ErrorCodes.not_available
                    break

            A.error_code = self.IO_error
            self.IO_palcam = palcam
            self.action = A

            self.active = await self.base.contain_action(
                ActiveParams(
                    action=self.action,
                    file_conn_params_dict={
                        self.base.dflt_file_conn_key(): FileConnParams(
                            file_conn_key=self.base.dflt_file_conn_key(),
                            # sample_global_labels=[],
                            file_type="pal_helao__file",
                        )
                    },
                )
            )

            if self.IO_error is ErrorCodes.none:
                self.IO_continue = False
                await self.set_IO_signalq(True)
                # wait for first continue trigger
                self.base.print_message("waiting for first continue", info=True)
                while not self.IO_continue:
                    await asyncio.sleep(1)
                self.base.print_message("got first continue", info=True)
                A.error_code = self.IO_error
            else:
                self.base.print_message("Error during PAL IOloop init", error=True)

            activeDict = self.active.action.as_dict()

        elif self.base.actionserver.estop:
            self.base.print_message("PAL is in estop.", error=True)
            A.error_code = ErrorCodes.estop
            activeDict = A.as_dict()

        elif self.sshhost is None:
            self.base.print_message("No PAL host specified.", error=True)
            A.error_code = ErrorCodes.not_available
            activeDict = A.as_dict()

        else:
            self.base.print_message("PAL method already in progress.", error=True)
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
            self.IO_do_meas = await self.IO_signalq.get()
            if self.IO_do_meas:
                self.IO_measuring = True
                # create active and check sample_in
                await self._PAL_IOloop_meas_start_helper()

                # gets some internal timing references
                start_time = time.time()  # this is only internal
                # time when the io loop was
                # started
                last_run_time = start_time  # the time of the last PAL run
                prev_timepoint = 0.0
                diff_time = 0.0

                # for multipe runs we don't wait for first trigger
                if self.IO_palcam.totalruns > 1:
                    self.IO_continue = True

                # loop over the requested runs of one complete
                # microcam list run
                for run in range(self.IO_palcam.totalruns):
                    self.base.print_message(
                        f"PAL run {run+1} of {self.IO_palcam.totalruns}"
                    )
                    # need to make a deepcopy as we modify this object during the run
                    # but each run should start from the same initial
                    # params again
                    run_palcam = deepcopy(self.IO_palcam)
                    run_palcam.cur_run = run

                    # # if sampleperiod list is empty
                    # # set it to default
                    # if not self.IO_palcam.sampleperiod:
                    #     self.IO_palcam.sampleperiod = [0.0]

                    # get the scheduled time for next PAL command
                    # self.IO_palcam.timeoffset corrects for offset
                    # between send ssh and continue (or any other offset)

                    if len(self.IO_palcam.sampleperiod) < (run + 1):
                        self.base.print_message(
                            "len(sampleperiod) < (run), using 0.0", info=True
                        )
                        sampleperiod = 0.0
                    else:
                        sampleperiod = self.IO_palcam.sampleperiod[run]

                    if self.IO_palcam.spacingmethod == Spacingmethod.linear:
                        self.base.print_message("PAL linear scheduling")
                        cur_time = time.time()
                        self.base.print_message(
                            f"time since last PAL run {(cur_time-last_run_time)}",
                            info=True,
                        )
                        self.base.print_message(
                            f"requested time between "
                            f"PAL runs "
                            f"{sampleperiod-self.IO_palcam.timeoffset}",
                            info=True,
                        )
                        diff_time = (
                            sampleperiod
                            - (cur_time - last_run_time)
                            - self.IO_palcam.timeoffset
                        )
                    elif self.IO_palcam.spacingmethod == Spacingmethod.geometric:
                        self.base.print_message("PAL geometric scheduling")
                        timepoint = (self.IO_palcam.spacingfactor**run) * sampleperiod
                        self.base.print_message(
                            f"time since last PAL run {(cur_time-last_run_time)}",
                            info=True,
                        )
                        self.base.print_message(
                            f"requested time between "
                            f"PAL runs {timepoint-prev_timepoint-self.IO_palcam.timeoffset}",
                            info=True,
                        )
                        diff_time = (
                            timepoint
                            - prev_timepoint
                            - (cur_time - last_run_time)
                            - self.IO_palcam.timeoffset
                        )
                        prev_timepoint = timepoint  # todo: consider time lag
                    elif self.IO_palcam.spacingmethod == Spacingmethod.custom:
                        self.base.print_message("PAL custom scheduling")
                        cur_time = time.time()
                        self.base.print_message(
                            f"time since PAL start {(cur_time-start_time)}",
                            info=True,
                        )
                        self.base.print_message(
                            f"time for next PAL run "
                            f"since start "
                            f"{sampleperiod-self.IO_palcam.timeoffset}",
                            info=True,
                        )
                        diff_time = (
                            sampleperiod
                            - (cur_time - start_time)
                            - self.IO_palcam.timeoffset
                        )

                    # only wait for positive time
                    self.base.print_message(
                        f"PAL waits {diff_time} for sending next command", info=True
                    )
                    if diff_time > 0:
                        for ii in range(round(diff_time)):
                            await asyncio.sleep(1)
                            if not self.IO_signalq.empty():
                                self.IO_measuring = await self.IO_signalq.get()
                                if not self.IO_measuring:
                                    break

                    if not self.IO_measuring:
                        break

                    # finally submit a single PAL run
                    last_run_time = time.time()
                    self.base.print_message("PAL sendcommand def start", info=True)
                    self.IO_error = await self._sendcommand_main(run_palcam)
                    self.base.print_message("PAL sendcommand def end", info=True)

                    if self.IO_trigger_task is not None:
                        self.IO_trigger_task.cancel()
                        self.IO_trigger_task = None

                # update samples_in/out in exp
                # and other cleanup
                await self._PAL_IOloop_meas_end_helper()

    async def _PAL_IOloop_meas_start_helper(self) -> None:
        """sets active object and
        checks samples_in"""
        self.IO_action_run_counter = 0

        self.base.print_message(
            f"Active action uuid is {self.active.action.action_uuid}"
        )
        if self.active:
            self.active.finish_hlo_header(
                file_conn_keys=self.active.action.file_conn_keys,
                realtime=await self.active.set_realtime(),
            )

        self.base.print_message(f"PAL_samples_in: {self.IO_palcam.samples_in}")
        # update sample list with correct information from db if possible
        self.base.print_message(
            "getting current sample information for all sample_in from db"
        )
        self.IO_palcam.samples_in = await self.archive.unified_db.get_samples(
            samples=self.IO_palcam.samples_in
        )

    async def _PAL_IOloop_meas_end_helper(self) -> None:
        """resets all IO variables
        and updates exp samples in and out"""

        if self.PAL_pid is not None:
            self.base.print_message("waiting for PAL pid to finish")
            self.PAL_pid.communicate()
            self.PAL_pid = None

        if self.IO_trigger_task is not None:
            self.IO_trigger_task.cancel()
            self.IO_trigger_task = None

        self.IO_continue = True
        # done sending all PAL commands
        self.IO_do_meas = False
        self.IO_action_run_counter = 0

        # need to check here again in case estop was triggered during
        # measurement
        # need to set the current meas to idle first
        if self.active:
            _ = await self.active.finish()
        self.active = None
        self.action = None

        if self.base.actionserver.estop:
            self.base.print_message("PAL is in estop.")
        else:
            self.base.print_message("setting PAL to idle")

        self.IO_measuring = False
        self.base.print_message("PAL is done")

    async def method_arbitrary(self, A: Action) -> dict:
        palcam = PalCam(**A.action_params)
        palcam.samples_in = A.samples_in
        return await self._init_PAL_IOloop(A=A, palcam=palcam)

    async def method_transfer_tray_tray(self, A: Action) -> dict:
        palcam = PalCam(
            samples_in=A.samples_in,
            totalruns=len(A.action_params.get("sampleperiod", [])),
            sampleperiod=A.action_params.get("sampleperiod", []),
            spacingmethod=A.action_params.get("spacingmethod", Spacingmethod.linear),
            spacingfactor=A.action_params.get("spacingfactor", 1.0),
            timeoffset=A.action_params.get("timeoffset", 0.0),
            microcams=[
                PalMicroCam(
                    **{
                        "method": "transfer_tray_tray",
                        "tool": A.action_params.get("tool", None),
                        "volume_ul": A.action_params.get("volume_ul", 0),
                        "requested_source": PALposition(
                            **{
                                "position": _positiontype.tray,
                                "tray": A.action_params.get("source_tray", 0),
                                "slot": A.action_params.get("source_slot", 0),
                                "vial": A.action_params.get("source_vial", 0),
                            }
                        ),
                        "requested_dest": PALposition(
                            **{
                                "position": _positiontype.tray,
                                "tray": A.action_params.get("dest_tray", 0),
                                "slot": A.action_params.get("dest_slot", 0),
                                "vial": A.action_params.get("dest_vial", 0),
                            }
                        ),
                        "wash1": A.action_params.get("wash1", 0),
                        "wash2": A.action_params.get("wash2", 0),
                        "wash3": A.action_params.get("wash3", 0),
                        "wash4": A.action_params.get("wash4", 0),
                    }
                )
            ],
        )
        return await self._init_PAL_IOloop(
            A=A,
            palcam=palcam,
        )

    async def method_transfer_custom_tray(self, A: Action) -> dict:
        palcam = PalCam(
            samples_in=A.samples_in,
            totalruns=len(A.action_params.get("sampleperiod", [])),
            sampleperiod=A.action_params.get("sampleperiod", []),
            spacingmethod=A.action_params.get("spacingmethod", Spacingmethod.linear),
            spacingfactor=A.action_params.get("spacingfactor", 1.0),
            timeoffset=A.action_params.get("timeoffset", 0.0),
            microcams=[
                PalMicroCam(
                    **{
                        "method": "transfer_tray_tray",
                        "tool": A.action_params.get("tool", None),
                        "volume_ul": A.action_params.get("volume_ul", 0),
                        "requested_source": PALposition(
                            **{
                                "position": A.action_params.get("source", None),
                            }
                        ),
                        "requested_dest": PALposition(
                            **{
                                "position": _positiontype.tray,
                                "tray": A.action_params.get("dest_tray", 0),
                                "slot": A.action_params.get("dest_slot", 0),
                                "vial": A.action_params.get("dest_vial", 0),
                            }
                        ),
                        "wash1": A.action_params.get("wash1", 0),
                        "wash2": A.action_params.get("wash2", 0),
                        "wash3": A.action_params.get("wash3", 0),
                        "wash4": A.action_params.get("wash4", 0),
                    }
                )
            ],
        )
        return await self._init_PAL_IOloop(
            A=A,
            palcam=palcam,
        )

    async def method_transfer_tray_custom(self, A: Action) -> dict:
        palcam = PalCam(
            samples_in=A.samples_in,
            totalruns=len(A.action_params.get("sampleperiod", [])),
            sampleperiod=A.action_params.get("sampleperiod", []),
            spacingmethod=A.action_params.get("spacingmethod", Spacingmethod.linear),
            spacingfactor=A.action_params.get("spacingfactor", 1.0),
            timeoffset=A.action_params.get("timeoffset", 0.0),
            microcams=[
                PalMicroCam(
                    **{
                        "method": "transfer_tray_tray",
                        "tool": A.action_params.get("tool", None),
                        "volume_ul": A.action_params.get("volume_ul", 0),
                        "requested_source": PALposition(
                            **{
                                "position": _positiontype.tray,
                                "tray": A.action_params.get("source_tray", 0),
                                "slot": A.action_params.get("source_slot", 0),
                                "vial": A.action_params.get("source_vial", 0),
                            }
                        ),
                        "requested_dest": PALposition(
                            **{
                                "position": A.action_params.get("dest", None),
                            }
                        ),
                        "wash1": A.action_params.get("wash1", 0),
                        "wash2": A.action_params.get("wash2", 0),
                        "wash3": A.action_params.get("wash3", 0),
                        "wash4": A.action_params.get("wash4", 0),
                    }
                )
            ],
        )
        return await self._init_PAL_IOloop(
            A=A,
            palcam=palcam,
        )

    async def method_transfer_custom_custom(self, A: Action) -> dict:
        palcam = PalCam(
            samples_in=A.samples_in,
            totalruns=len(A.action_params.get("sampleperiod", [])),
            sampleperiod=A.action_params.get("sampleperiod", []),
            spacingmethod=A.action_params.get("spacingmethod", Spacingmethod.linear),
            spacingfactor=A.action_params.get("spacingfactor", 1.0),
            timeoffset=A.action_params.get("timeoffset", 0.0),
            microcams=[
                PalMicroCam(
                    **{
                        "method": "transfer_tray_tray",
                        "tool": A.action_params.get("tool", None),
                        "volume_ul": A.action_params.get("volume_ul", 0),
                        "requested_source": PALposition(
                            **{
                                "position": A.action_params.get("source", None),
                            }
                        ),
                        "requested_dest": PALposition(
                            **{
                                "position": A.action_params.get("dest", None),
                            }
                        ),
                        "wash1": A.action_params.get("wash1", 0),
                        "wash2": A.action_params.get("wash2", 0),
                        "wash3": A.action_params.get("wash3", 0),
                        "wash4": A.action_params.get("wash4", 0),
                    }
                )
            ],
        )
        return await self._init_PAL_IOloop(
            A=A,
            palcam=palcam,
        )

    async def method_archive(self, A: Action) -> dict:
        palcam = PalCam(
            samples_in=A.samples_in,
            totalruns=len(A.action_params.get("sampleperiod", [])),
            sampleperiod=A.action_params.get("sampleperiod", []),
            spacingmethod=A.action_params.get("spacingmethod", Spacingmethod.linear),
            spacingfactor=A.action_params.get("spacingfactor", 1.0),
            timeoffset=A.action_params.get("timeoffset", 0.0),
            microcams=[
                PalMicroCam(
                    **{
                        "method": "archive",
                        "tool": A.action_params.get("tool", None),
                        "volume_ul": A.action_params.get("volume_ul", 0),
                        "requested_source": PALposition(
                            **{
                                "position": A.action_params.get("source", None),
                            }
                        ),
                        "wash1": A.action_params.get("wash1", 0),
                        "wash2": A.action_params.get("wash2", 0),
                        "wash3": A.action_params.get("wash3", 0),
                        "wash4": A.action_params.get("wash4", 0),
                    }
                )
            ],
        )
        return await self._init_PAL_IOloop(
            A=A,
            palcam=palcam,
        )

    # async def method_fill(self, A: Action) -> dict:
    #     palcam = PalCam(
    #         samples_in = A.samples_in,
    #         totalruns = 1,
    #         sampleperiod = [],
    #         spacingmethod = Spacingmethod.linear,
    #         spacingfactor = 1.0,
    #         timeoffset = 0.0,
    #         microcams = [PalMicroCam(**{
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
    #         samples_in = A.samples_in,
    #         totalruns = 1,
    #         sampleperiod = [],
    #         spacingmethod = Spacingmethod.linear,
    #         spacingfactor = 1.0,
    #         timeoffset = 0.0,
    #         microcams = [PalMicroCam(**{
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
            samples_in=A.samples_in,
            totalruns=1,
            sampleperiod=[],
            spacingmethod=Spacingmethod.linear,
            spacingfactor=1.0,
            timeoffset=0.0,
            microcams=[
                PalMicroCam(
                    **{
                        "method": "deepclean",
                        "tool": A.action_params.get("tool", None),
                        "volume_ul": A.action_params.get("volume_ul", 0),
                        "wash1": A.action_params.get("wash1", 1),
                        "wash2": A.action_params.get("wash2", 1),
                        "wash3": A.action_params.get("wash3", 1),
                        "wash4": A.action_params.get("wash4", 1),
                    }
                )
            ],
        )
        return await self._init_PAL_IOloop(
            A=A,
            palcam=palcam,
        )

    # async def method_dilute(self, A: Action) -> dict:
    #     palcam = PalCam(
    #         samples_in = A.samples_in,
    #         totalruns = len(A.action_params.get("sampleperiod",[])),
    #         sampleperiod = A.action_params.get("sampleperiod",[]),
    #         spacingmethod = A.action_params.get("spacingmethod",Spacingmethod.linear),
    #         spacingfactor = A.action_params.get("spacingfactor",1.0),
    #         timeoffset = A.action_params.get("timeoffset",0.0),
    #         microcams = [PalMicroCam(**{
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
    #         samples_in = A.samples_in,
    #         totalruns = len(A.action_params.get("sampleperiod",[])),
    #         sampleperiod = A.action_params.get("sampleperiod",[]),
    #         spacingmethod = A.action_params.get("spacingmethod",Spacingmethod.linear),
    #         spacingfactor = A.action_params.get("spacingfactor",1.0),
    #         timeoffset = A.action_params.get("timeoffset",0.0),
    #         microcams = [PalMicroCam(**{
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
        start = A.action_params.get("startGC", None)

        if start == True:
            start = "start"
        elif start == False:
            start = "wait"

        sampletype = A.action_params.get("sampletype", GCsampletype.none)

        method = f"injection_tray_GC_{str(sampletype)}_{start}"

        palcam = PalCam(
            samples_in=A.samples_in,
            totalruns=1,
            sampleperiod=[],
            spacingmethod=Spacingmethod.linear,
            spacingfactor=1.0,
            timeoffset=0.0,
            microcams=[
                PalMicroCam(
                    **{
                        "method": method,
                        "tool": A.action_params.get("tool", None),
                        "volume_ul": A.action_params.get("volume_ul", 0),
                        "requested_source": PALposition(
                            **{
                                "position": _positiontype.tray,
                                "tray": A.action_params.get("source_tray", 0),
                                "slot": A.action_params.get("source_slot", 0),
                                "vial": A.action_params.get("source_vial", 0),
                            }
                        ),
                        "requested_dest": PALposition(
                            **{
                                "position": A.action_params.get("dest", None),
                            }
                        ),
                        "wash1": A.action_params.get("wash1", 0),
                        "wash2": A.action_params.get("wash2", 0),
                        "wash3": A.action_params.get("wash3", 0),
                        "wash4": A.action_params.get("wash4", 0),
                    }
                )
            ],
        )
        return await self._init_PAL_IOloop(
            A=A,
            palcam=palcam,
        )

    async def method_injection_custom_GC(self, A: Action) -> dict:
        start = A.action_params.get("startGC", None)

        if start == True:
            start = "start"
        elif start == False:
            start = "wait"

        sampletype = A.action_params.get("sampletype", GCsampletype.none)

        method = f"injection_custom_GC_{str(sampletype.name)}_{start}"

        palcam = PalCam(
            samples_in=A.samples_in,
            totalruns=1,
            sampleperiod=[],
            spacingmethod=Spacingmethod.linear,
            spacingfactor=1.0,
            timeoffset=0.0,
            microcams=[
                PalMicroCam(
                    **{
                        "method": method,
                        "tool": A.action_params.get("tool", None),
                        "volume_ul": A.action_params.get("volume_ul", 0),
                        "requested_source": PALposition(
                            **{
                                "position": A.action_params.get("source", None),
                            }
                        ),
                        "requested_dest": PALposition(
                            **{
                                "position": A.action_params.get("dest", None),
                            }
                        ),
                        "wash1": A.action_params.get("wash1", 0),
                        "wash2": A.action_params.get("wash2", 0),
                        "wash3": A.action_params.get("wash3", 0),
                        "wash4": A.action_params.get("wash4", 0),
                    }
                )
            ],
        )
        return await self._init_PAL_IOloop(
            A=A,
            palcam=palcam,
        )

    async def method_injection_tray_HPLC(self, A: Action) -> dict:
        palcam = PalCam(
            samples_in=A.samples_in,
            totalruns=1,
            sampleperiod=[],
            spacingmethod=Spacingmethod.linear,
            spacingfactor=1.0,
            timeoffset=0.0,
            microcams=[
                PalMicroCam(
                    **{
                        "method": "injection_tray_HPLC",
                        "tool": A.action_params.get("tool", None),
                        "volume_ul": A.action_params.get("volume_ul", 0),
                        "requested_source": PALposition(
                            **{
                                "position": _positiontype.tray,
                                "tray": A.action_params.get("source_tray", 0),
                                "slot": A.action_params.get("source_slot", 0),
                                "vial": A.action_params.get("source_vial", 0),
                            }
                        ),
                        "requested_dest": PALposition(
                            **{
                                "position": A.action_params.get("dest", None),
                            }
                        ),
                        "wash1": A.action_params.get("wash1", 0),
                        "wash2": A.action_params.get("wash2", 0),
                        "wash3": A.action_params.get("wash3", 0),
                        "wash4": A.action_params.get("wash4", 0),
                    }
                )
            ],
        )
        return await self._init_PAL_IOloop(
            A=A,
            palcam=palcam,
        )

    async def method_injection_custom_HPLC(self, A: Action) -> dict:
        palcam = PalCam(
            samples_in=A.samples_in,
            totalruns=1,
            sampleperiod=[],
            spacingmethod=Spacingmethod.linear,
            spacingfactor=1.0,
            timeoffset=0.0,
            microcams=[
                PalMicroCam(
                    **{
                        "method": "injection_custom_HPLC",
                        "tool": A.action_params.get("tool", None),
                        "volume_ul": A.action_params.get("volume_ul", 0),
                        "requested_source": PALposition(
                            **{
                                "position": A.action_params.get("source", None),
                            }
                        ),
                        "requested_dest": PALposition(
                            **{
                                "position": A.action_params.get("dest", None),
                            }
                        ),
                        "wash1": A.action_params.get("wash1", 0),
                        "wash2": A.action_params.get("wash2", 0),
                        "wash3": A.action_params.get("wash3", 0),
                        "wash4": A.action_params.get("wash4", 0),
                    }
                )
            ],
        )
        return await self._init_PAL_IOloop(
            A=A,
            palcam=palcam,
        )

    async def method_ANEC_GC(self, A: Action) -> dict:
        palcam = PalCam(
            samples_in=A.samples_in,
            totalruns=1,
            sampleperiod=[],
            spacingmethod=Spacingmethod.linear,
            spacingfactor=1.0,
            timeoffset=0.0,
            microcams=[
                PalMicroCam(
                    **{
                        "method": "injection_custom_GC_gas_wait",
                        "tool": A.action_params.get("toolGC", None),
                        "volume_ul": A.action_params.get("volume_ul_GC", 0),
                        "requested_source": PALposition(
                            **{
                                "position": A.action_params.get("source", None),
                            }
                        ),
                        "requested_dest": PALposition(
                            **{
                                "position": "Injector 2",
                            }
                        ),
                        "wash1": 0,
                        "wash2": 0,
                        "wash3": 0,
                        "wash4": 0,
                    }
                ),
                PalMicroCam(
                    **{
                        "method": "injection_custom_GC_gas_start",
                        "tool": A.action_params.get("toolGC", None),
                        "volume_ul": A.action_params.get("volume_ul_GC", 0),
                        "requested_source": PALposition(
                            **{
                                "position": A.action_params.get("source", None),
                            }
                        ),
                        "requested_dest": PALposition(
                            **{
                                "position": "Injector 1",
                            }
                        ),
                        "wash1": 0,
                        "wash2": 0,
                        "wash3": 0,
                        "wash4": 0,
                    }
                ),
            ],
        )
        return await self._init_PAL_IOloop(
            A=A,
            palcam=palcam,
        )

    async def method_ANEC_aliquot(self, A: Action) -> dict:
        palcam = PalCam(
            samples_in=A.samples_in,
            totalruns=1,
            sampleperiod=[],
            spacingmethod=Spacingmethod.linear,
            spacingfactor=1.0,
            timeoffset=0.0,
            microcams=[
                PalMicroCam(
                    **{
                        "method": "injection_custom_GC_gas_wait",
                        "tool": A.action_params.get("toolGC", None),
                        "volume_ul": A.action_params.get("volume_ul_GC", 0),
                        "requested_source": PALposition(
                            **{
                                "position": A.action_params.get("source", None),
                            }
                        ),
                        "requested_dest": PALposition(
                            **{
                                "position": "Injector 2",
                            }
                        ),
                        "wash1": 0,
                        "wash2": 0,
                        "wash3": 0,
                        "wash4": 0,
                    }
                ),
                PalMicroCam(
                    **{
                        "method": "injection_custom_GC_gas_start",
                        "tool": A.action_params.get("toolGC", None),
                        "volume_ul": A.action_params.get("volume_ul_GC", 0),
                        "requested_source": PALposition(
                            **{
                                "position": A.action_params.get("source", None),
                            }
                        ),
                        "requested_dest": PALposition(
                            **{
                                "position": "Injector 1",
                            }
                        ),
                        "wash1": 0,
                        "wash2": 0,
                        "wash3": 0,
                        "wash4": 0,
                    }
                ),
                PalMicroCam(
                    **{
                        "method": "archive",
                        "tool": A.action_params.get("toolarchive", None),
                        "volume_ul": A.action_params.get("volume_ul_archive", 0),
                        "requested_source": PALposition(
                            **{
                                "position": A.action_params.get("source", None),
                            }
                        ),
                        "wash1": A.action_params.get("wash1", 0),
                        "wash2": A.action_params.get("wash2", 0),
                        "wash3": A.action_params.get("wash3", 0),
                        "wash4": A.action_params.get("wash4", 0),
                    }
                ),
            ],
        )
        return await self._init_PAL_IOloop(
            A=A,
            palcam=palcam,
        )

    def shutdown(self):
        self.base.print_message("shutting down pal")
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
        # stop IOloop
        self.IOloop_run = False

    async def stop(self):
        """stops measurement, writes all data and returns from meas loop"""
        # turn off cell and run before stopping meas loop
        if self.IO_do_meas:
            await self.set_IO_signalq(False)

    async def estop(self, switch: bool, *args, **kwargs):
        """same as estop, but also sets flag"""
        switch = bool(switch)
        self.base.actionserver.estop = switch
        if self.IO_do_meas:
            if switch:
                await self.set_IO_signalq(False)
                if self.active:
                    await self.active.set_estop()
        return switch

    async def kill_PAL(self) -> ErrorCodes:
        """kills PAL program if its still open"""
        error_code = ErrorCodes.none
        self.base.print_message("killing PAL", info=True)

        if self.sshhost == "localhost":

            # kill PAL if program is open
            error_code = await self.kill_PAL_local()
        elif self.sshhost is not None:
            error_code = await self.kill_PAL_cygwin()

        if error_code is not ErrorCodes.none:
            self.base.print_message("Could not close PAL", error=True)

        return error_code

    async def kill_PAL_cygwin(self) -> bool:
        ssh_connected = False
        while not ssh_connected:
            try:
                # open SSH to PAL
                k = paramiko.RSAKey.from_private_key_file(self.sshkey)
                mysshclient = paramiko.SSHClient()
                mysshclient.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                mysshclient.connect(
                    hostname=self.sshhost, username=self.sshuser, pkey=k
                )
                ssh_connected = True
            except Exception as e:
                ssh_connected = False
                self.base.print_message(
                    f"SSH connection error. Retrying in 1 seconds.\n{e}", error=True
                )
                await asyncio.sleep(1)

        try:
            sshcmd = "tmux new-window taskkill /F /FI 'WINDOWTITLE eq PAL*'"
            (
                mysshclient_stdin,
                mysshclient_stdout,
                mysshclient_stderr,
            ) = mysshclient.exec_command(sshcmd)
            mysshclient.close()

        except Exception as e:
            self.base.print_message(
                f"SSH connection error 1. Could not send commands.\n{e}", error=True
            )
            self.base.print_message(e, error=True)

            return ErrorCodes.ssh_error

        return ErrorCodes.none

    async def kill_PAL_local(self) -> bool:
        pyPids = {
            p.pid: p
            for p in psutil.process_iter(["name", "connections"])
            if p.info["name"].startswith("PAL")
        }

        for pid in pyPids:
            self.base.print_message(f"killing PAL on PID: {pid}", info=True)
            p = psutil.Process(pid)
            for _ in range(3):
                # os.kill(p.pid, signal.SIGTERM)
                p.terminate()
                time.sleep(0.5)
                if not psutil.pid_exists(p.pid):
                    self.base.print_message("Successfully terminated PAL.", info=True)
                    return True
            if psutil.pid_exists(p.pid):
                self.base.print_message(
                    "Failed to terminate server PAL after 3 retries.", error=True
                )
                return ErrorCodes.critical

        # if none is found return True
        return ErrorCodes.none
