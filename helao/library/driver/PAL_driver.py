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

from pydantic import BaseModel
from typing import List

from helao.core.schema import Action
from helao.core.server import Base
from helao.core.error import error_codes
from helao.library.driver.HTEdata_legacy import LocalDataHandler
from helao.core.data import liquid_sample_no_API



import nidaqmx
from nidaqmx.constants import LineGrouping


class PALmethods(str, Enum):
    archive = 'lcfc_archive.cam'
    fillfixed = 'lcfc_fill_hardcodedvolume.cam'
    fill = 'lcfc_fill.cam'
    test = 'relay_actuation_test2.cam'
    dilute = 'lcfc_dilute.cam'
    deepclean = 'lcfc_deep_clean.cam'
    none = ""


class Spacingmethod(str, Enum):
    linear = 'linear' # 1, 2, 3, 4, 5, ...
    geometric = 'gemoetric' # 1, 2, 4, 8, 16
    custom = 'custom'
#    power = 'power'
#    exponential = 'exponential'

class PALtools(str, Enum):
    LS1 = "LS1"
    LS2 = "LS2"
    LS3 = "LS3"


class VT_template:
    def __init__(self, max_vol_mL: float = 0.0, VTtype: str = '', positions: int = 0):
        self.type: str = VTtype
        self.max_vol_mL: float = max_vol_mL
        self.vials: List[bool] = [False for i in range(positions)]
        self.vol_mL: List[float] = [0.0 for i in range(positions)]
        self.liquid_sample_no: List[int] = [None for i in range(positions)]
        self.dilution_factor: List[float] = [1.0 for i in range(positions)]


    def first_empty(self):
        res = next((i for i, j in enumerate(self.vials) if not j), None)
        # print ("The values till first True value : " + str(res))
        return res
    

    def first_full(self):
        res = next((i for i, j in enumerate(self.vials) if j), None)
        # print ("The values till first False value : " + str(res))
        return res


    def update_vials(self, vial_dict):
        for i, vial in enumerate(vial_dict):
            try:
                self.vials[i] = bool(vial)
            except Exception:
                self.vials[i] = False

    def update_vol(self, vol_dict):
        for i, vol in enumerate(vol_dict):
            try:
                self.vol_mL[i] = float(vol)
            except Exception:
                self.vol_mL[i] = 0.0

    def update_liquid_sample_no(self, sample_dict):
        for i, sample in enumerate(sample_dict):
            try:
                self.liquid_sample_no[i] = int(sample)
            except Exception:
                self.liquid_sample_no[i] = None


    def update_dilution_factor(self, sample_dict):
        for i, df in enumerate(sample_dict):
            try:
                self.dilution_factor[i] = float(df)
            except Exception:
                self.dilution_factor[i] = 1.0


    def as_dict(self):
        return vars(self)


class VT15(VT_template):
    def __init__(self, max_vol_mL: float = 10.0):
        super().__init__(max_vol_mL = max_vol_mL, VTtype = "VT15", positions = 15)


class VT54(VT_template):
    def __init__(self, max_vol_mL: float = 2.0):
        super().__init__(max_vol_mL = max_vol_mL, VTtype = "VT54", positions = 54)


class VT70(VT_template):
    def __init__(self, max_vol_mL: float = 1.0):
        super().__init__(max_vol_mL = max_vol_mL, VTtype = "VT70", positions = 70)


class PALtray:
    def __init__(self, slot1=None, slot2=None, slot3=None):
        self.slots = [slot1, slot2, slot3]

    def as_dict(self):
        return vars(self)


class cPALparams(BaseModel):
    liquid_sample_no_in: int = None
    liquid_sample_no_out: int = None
    PAL_method: PALmethods = PALmethods.none
    PAL_tool: str = ""
    PAL_volume_uL: int = 0  # uL
    PAL_dest: str = "" # dest can be cust. or tray
    PAL_dest_tray: int = None
    PAL_dest_slot: int = None
    PAL_dest_vial: int = None
    PAL_source: str = ""  # source can be cust. or tray
    PAL_source_tray: int = None
    PAL_source_slot: int = None
    PAL_source_vial: int = None
    PAL_wash1: bool = False
    PAL_wash2: bool = False
    PAL_wash3: bool = False
    PAL_wash4: bool = False
    PAL_totalvials: int = 1
    PAL_sampleperiod: List[float] = [0.0]
    PAL_spacingmethod: Spacingmethod = "linear"
    PAL_spacingfactor: float = 1.0
    # PAL_mixing: str = ""
    PAL_timeoffset: float = 0.0 # sec
    PAL_cur_sample: int = 0

    PAL_plate_id: int = None
    PAL_plate_sample_no: int = None
    PAL_start_time: int = None
    PAL_continue_time: int = None
    PAL_done_time: int = None
    PAL_ssh_time: int = None


class cPAL:
    # def __init__(self, config_dict, stat, C, servkey):
    def __init__(self, actServ: Base):
        
        self.base = actServ
        self.config_dict = actServ.server_cfg["params"]
        self.world_config = actServ.world_cfg

        
        # configure the tray
        self.trays = [
            PALtray(slot1=None, slot2=None, slot3=None),
            PALtray(slot1=VT54(max_vol_mL=2.0), slot2=VT54(max_vol_mL=2.0), slot3=None),
        ]

        self.PAL_file = "PAL_holder_DB.json"
        # load backup of vial table, if file does not exist it will use the default one from above
        asyncio.gather(self.trayDB_load_backup())

        self.local_data_dump = self.world_config["save_root"]
        self.liquid_sample_no_DB_path = self.world_config["liquid_sample_no_DB"]

        self.liquid_sample_no_DB = liquid_sample_no_API(self.base, self.liquid_sample_no_DB_path)

        self.sshuser = self.config_dict["user"]
        self.sshkey = self.config_dict["key"]
        self.sshhost = self.config_dict["host"]
        self.method_path = self.config_dict["method_path"]
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

        if "dev_NImax" in self.config_dict:
            self.triggerport_start = self.config_dict["dev_NImax"].get("start", None)
            self.triggerport_continue = self.config_dict["dev_NImax"].get(
                "continue", None
            )
            self.triggerport_done = self.config_dict["dev_NImax"].get("done", None)
            self.base.print_message(f" ... PAL start trigger port: {self.triggerport_start}")
            self.base.print_message(f" ... PAL continue trigger port: {self.triggerport_continue}")
            self.base.print_message(f" ... PAL done trigger port: {self.triggerport_done}")
            self.triggers = True


        self.action = (
            None  # for passing action object from technique method to measure loop
        )

        self.active = (
            None  # for holding active action object, clear this at end of measurement
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
        # self.liquid_sample_rcp = LocalDataHandler()
        self.IO_remotedatafile = ""

        # self.runparams = action_runparams

        myloop = asyncio.get_event_loop()
        # add meas IOloop
        myloop.create_task(self.IOloop())


        self.FIFO_PALheader = (
            ""  # measuement specific, will be reset each measurement
        )
        self.FIFO_name = ""
        self.FIFO_dir = ""
        self.FIFO_rshs_dir = ""
        self.FIFO_column_headings = []



    async def trayDB_reset(self, A):
        myactive = await self.base.contain_action(A)
        # backup to json
        await self.trayDB_backup(reset=True)
        # full backup to csv
        for tray in range(len(self.trays)):
            for slot in range(3):  # each tray has 3 slots
                await self.trayDB_export_csv(tray + 1, slot + 1, myactive)
        # reset PAL table
        # todo change that to a config config
        self.trays = [
            PALtray(slot1=None, slot2=None, slot3=None),
            PALtray(slot1=VT54(max_vol_mL=2.0), slot2=VT54(max_vol_mL=2.0), slot3=None),
        ]
        # save new one so it can be loaded of Program startup
        await self.trayDB_backup(reset=False)
        await myactive.enqueue_data({"reset": "done"})
        return await myactive.finish()


    async def trayDB_load_backup(self):
        file_path = os.path.join(self.local_data_dump, self.PAL_file)
        self.base.print_message(f" ... loading PAL table from: {file_path}")
        if not os.path.exists(file_path):
            return False

        self.fjsonread = await aiofiles.open(file_path, "r")
        trays_dict = dict()
        await self.fjsonread.seek(0)
        async for line in self.fjsonread:
            newline = json.loads(line)
            tray_no = newline.get("tray_no", None)
            slot_no = newline.get("slot_no", None)
            content = newline.get("content", None)
            if tray_no is not None:
                if slot_no is not None:
                    if tray_no not in trays_dict:
                        trays_dict[tray_no] = dict()
                    trays_dict[tray_no][slot_no] = content
                else:
                    trays_dict[tray_no] = None
        await self.fjsonread.close()

        # load back into self.trays
        # this does not care about the sequence
        # (double entries will be overwritten by the last one in the dict)
        # reset old tray DB
        self.trays = []
        for traynum, trayitem in trays_dict.items():
            # self.base.print_message(" ... tray num", traynum)
            # check if long enough
            for i in range(traynum):
                if len(self.trays) < i + 1:
                    # not long enough, add None
                    self.trays.append(None)

            if trayitem is not None:
                slots = []
                for slotnum, slotitem in trayitem.items():
                    # if slots is not long enough, extend it
                    for i in range(slotnum):
                        if len(slots) < i + 1:
                            slots.append(None)

                    # self.base.print_message(" ... slot num", slotnum)
                    if slotitem is not None:
                        if slotitem["type"] == "VT54":
                            self.base.print_message(" ... got VT54")
                            slots[slotnum - 1] = VT54(max_vol_mL=slotitem["max_vol_mL"])
                            slots[slotnum - 1].update_vials(slotitem["vials"])
                            slots[slotnum - 1].update_vol(slotitem["vol_mL"])
                            slots[slotnum - 1].update_liquid_sample_no(
                                slotitem["liquid_sample_no"]
                            )
                            slots[slotnum - 1].update_dilution_factor(
                                slotitem["dilution_factor"]
                            )
                        else:
                            self.base.print_message(f' ... slot type {slotitem["type"]} not supported')
                            slots[slotnum - 1] = None
                    else:
                        self.base.print_message(" ... got empty slot")
                        slots[slotnum - 1] = None

                self.trays[traynum - 1] = PALtray(
                    slot1=slots[0], slot2=slots[1], slot3=slots[2]
                )
            else:
                self.trays[traynum - 1] = None
        return True



    async def trayDB_backup(self, reset: bool = False):
        datafile = LocalDataHandler()
        datafile.filepath = self.local_data_dump
        if reset:
            datafile.filename = (
                f'PALresetBackup__{datetime.now().strftime("%Y%m%d.%H%M%S%f")}'
                + self.PAL_file
            )
        else:
            datafile.filename = self.PAL_file

        self.base.print_message(f" ... updating table: {datafile.filepath}:{datafile.filename}")
        await datafile.open_file_async(mode="w+")

        for mytray_no, mytray in enumerate(self.trays):
            if mytray is not None:
                for slot_no, slot in enumerate(mytray.slots):
                    if slot is not None:
                        tray_dict = dict(
                            tray_no=mytray_no + 1,
                            slot_no=slot_no + 1,
                            content=slot.as_dict(),
                        )
                        await datafile.write_data_async(json.dumps(tray_dict))
                    else:
                        tray_dict = dict(
                            tray_no=mytray_no + 1, slot_no=slot_no + 1, content=None
                        )
                        await datafile.write_data_async(json.dumps(tray_dict))
            else:
                tray_dict = dict(tray_no=mytray_no + 1, slot_no=None, content=None)
                await datafile.write_data_async(json.dumps(tray_dict))

        await datafile.close_file_async()


    async def trayDB_update(
        self, 
        tray: int, 
        slot: int, 
        vial: int, 
        vol_mL: float, 
        liquid_sample_no: int,
        dilute: bool = False,
        *args,**kwargs
    ):
        tray -= 1
        slot -= 1
        vial -= 1
        if self.trays[tray] is not None:
            if self.trays[tray].slots[slot] is not None:
                if self.trays[tray].slots[slot].vials[vial] is not True:
                    self.trays[tray].slots[slot].vials[vial] = True
                    self.trays[tray].slots[slot].vol_mL[vial] = vol_mL
                    self.trays[tray].slots[slot].liquid_sample_no[vial] = liquid_sample_no
                    # backup file
                    await self.trayDB_backup()
                    return True
                else:
                    if dilute is True:
                        self.trays[tray].slots[slot].vials[vial] = True
                        old_vol = self.trays[tray].slots[slot].vol_mL[vial]
                        old_df = self.trays[tray].slots[slot].dilution_factor[vial]
                        tot_vol = old_vol + vol_mL
                        new_df = tot_vol/(old_vol/old_df)
                        self.trays[tray].slots[slot].vol_mL[vial] = tot_vol
                        self.trays[tray].slots[slot].dilution_factor[vial] = new_df
                        
                        await self.trayDB_backup()
                        return True
                    else:
                        return False            
            else:
                return False
        else:
            return False
        pass


    async def trayDB_export_csv(self, tray, slot, myactive):
        # save full table as backup too
        await self.trayDB_backup()

        if self.trays[tray - 1] is not None:
            if self.trays[tray - 1].slots[slot - 1] is not None:
                tmp_output_str = ""#",".join(["vial_no", "liquid_sample_no", "vol_mL"])
                
                for i, _ in enumerate(self.trays[tray - 1].slots[slot - 1].vials):
                    if tmp_output_str != "":
                        tmp_output_str += "\n"
                    tmp_output_str += ",".join(
                        [
                            str(i + 1),
                            str(
                                self.trays[tray - 1]
                                .slots[slot - 1]
                                .liquid_sample_no[i]
                            ),
                            str(self.trays[tray - 1].slots[slot - 1].vol_mL[i]),
                        ]
                    )
                # # await datafile.write_data_async('\t'.join(logdata))
                # # await datafile.close_file_async()
                await myactive.write_file(
                    file_type = 'pal_vialtable_file',
                    filename = f'VialTable__tray{tray}__slot{slot}__{datetime.now().strftime("%Y%m%d.%H%M%S%f")}.csv',
                    output_str = tmp_output_str,
                    header = ",".join(["vial_no", "liquid_sample_no", "vol_mL"]),
                    sample_str = None
                    )


    async def trayDB_export_icpms(self, 
                                  tray: int, 
                                  slot: int, 
                                  myactive, 
                                  survey_runs: int,
                                  main_runs: int,
                                  rack: int,
                                  dilution_factor: float = None,
):
        # save full table as backup too
        await self.trayDB_backup()

        if self.trays[tray - 1] is not None:
            if self.trays[tray - 1].slots[slot - 1] is not None:
                tmp_output_str = ""#",".join(["vial_no", "liquid_sample_no", "vol_mL"])
                
                for i, vial in enumerate(self.trays[tray - 1].slots[slot - 1].vials):
                    if tmp_output_str != "":
                        tmp_output_str += "\n"


                    if vial is True:
                        if dilution_factor is None:
                            temp_dilution_factor = self.trays[tray - 1].slots[slot - 1].dilution_factor[i]
                        tmp_output_str += ";".join(
                            [
                                str(
                                    self.trays[tray - 1]
                                    .slots[slot - 1]
                                    .liquid_sample_no[i]
                                ),
                                str(survey_runs),
                                str(main_runs),
                                str(rack),
                                str(i + 1),
                                str(temp_dilution_factor),
                            ]
                        )
                # # await datafile.write_data_async('\t'.join(logdata))
                # # await datafile.close_file_async()
                await myactive.write_file(
                    file_type = 'pal_vialtable_file',
                    filename = f'VialTable__tray{tray}__slot{slot}__{datetime.now().strftime("%Y%m%d-%H%M%S%f")}_ICPMS.csv',
                    output_str = tmp_output_str,
                    header = ";".join(["liquid_sample_no", "Survey Runs", "Main Runs", "Rack", "Vial", "Dilution Factor"]),
                    sample_str = None
                    )


    async def trayDB_get_db(self, A):
        """Returns vial tray sample table"""
        tray =  A.action_params["tray"]
        slot =  A.action_params["slot"]
        csv = A.action_params.get("csv", False)
        icpms = A.action_params.get("icpms", False)

        myactive = await self.base.contain_action(A)
        table = {}

        if self.trays[tray - 1] is not None:
            if self.trays[tray - 1].slots[slot - 1] is not None:
                if csv:
                    await self.trayDB_export_csv(tray, slot, myactive)
                if icpms:
                    await self.trayDB_export_icpms(
                                                 tray = tray,
                                                 slot = slot,
                                                 myactive = myactive,
                                                 survey_runs = A.action_params.get("survey_runs", 1),
                                                 main_runs = A.action_params.get("main_runs", 3),
                                                 rack = A.action_params.get("rack", 2),
                                                 dilution_factor = A.action_params.get("dilution_factor", None),
                                                )
                table = self.trays[tray - 1].slots[slot - 1].as_dict()
        await myactive.enqueue_data({"vial_table": table})

        return await myactive.finish()
                

    async def trayDB_get_first_full(self, vialtable = None):
        new_tray = None
        new_slot = None
        new_vial = None
        
        if vialtable == None:
            vialtable = self.trays

        for tray_no, tray in enumerate(vialtable):
            # self.base.print_message(' ... tray', tray_no,tray)
            if tray is not None:
                for slot_no, slot in enumerate(tray.slots):
                    if slot is not None:
                        # self.base.print_message(' .... slot ', slot_no,slot)
                        # self.base.print_message(' .... ',slot.type)
                        position = slot.first_full()
                        if position is not None:
                            new_tray = tray_no + 1
                            new_slot = slot_no + 1
                            new_vial = position + 1
                            break
        
        return {'tray': new_tray,
                'slot': new_slot,
                'vial': new_vial}


    async def trayDB_new(self, req_vol: float = 2.0,*args,**kwargs):
        """Returns an empty vial position for given max volume.\n
        For mixed vial sizes the req_vol helps to choose the proper vial for sample volume.\n
        It will select the first empty vial which has the smallest volume that still can hold req_vol"""
        self.base.print_message(self.trays)
        new_tray = None
        new_slot = None
        new_vial = None
        new_vial_vol = float("inf")

        for tray_no, tray in enumerate(self.trays):
            # self.base.print_message(" ... tray", tray_no, tray)
            if tray is not None:
                for slot_no, slot in enumerate(tray.slots):
                    if slot is not None:
                        if (
                            slot.max_vol_mL >= req_vol
                            and new_vial_vol > slot.max_vol_mL
                        ):
                            position = slot.first_empty()
                            if position is not None:
                                new_tray = tray_no + 1
                                new_slot = slot_no + 1
                                new_vial = position + 1
                                new_vial_vol = slot.max_vol_mL

        self.base.print_message(f" ... new vial nr. {new_vial} in slot {new_slot} in tray {new_tray}")
        return {"tray": new_tray, "slot": new_slot, "vial": new_vial}


    async def trayDB_get_vial_liquid_sample_no(self, tray: int, slot: int, vial: int):
        tray -= 1
        slot -= 1
        vial -= 1
        liquid_sample_no = None
        vol_mL = None
        if self.trays[tray] is not None:
            if self.trays[tray].slots[slot] is not None:
                if self.trays[tray].slots[slot].vials[vial] is not False:
                    vol_mL = self.trays[tray].slots[slot].vials[vial]
                    liquid_sample_no = self.trays[tray].slots[slot].liquid_sample_no[vial]

        return {'liquid_sample_no':liquid_sample_no,
                'vol_mL':vol_mL}


    async def poll_start(self):
        starttime = time.time()
        self.trigger_start = False
        with nidaqmx.Task() as task:
            task.di_channels.add_di_chan(
                self.triggerport_start, line_grouping=LineGrouping.CHAN_PER_LINE
            )
            while self.trigger_start == False:
                data = task.read(number_of_samples_per_channel=1)
                # self.base.print_message("...................... start port status:", data)
                if any(data) == True:
                    self.base.print_message(" ... got PAL start trigger poll")
                    self.trigger_start_epoch = time.time_ns()
                    self.trigger_start = True
                    return True
                if (time.time() - starttime) > self.timeout:
                    return False
                await asyncio.sleep(1)
        return True


    async def poll_continue(self):
        starttime = time.time()
        self.trigger_continue = False
        with nidaqmx.Task() as task:
            task.di_channels.add_di_chan(
                self.triggerport_continue, line_grouping=LineGrouping.CHAN_PER_LINE
            )
            while self.trigger_continue == False:
                data = task.read(number_of_samples_per_channel=1)
                # self.base.print_message("...................... continue port status:", data)
                if any(data) == True:
                    self.base.print_message(" ... got PAL continue trigger poll")
                    self.trigger_continue_epoch = time.time_ns()
                    self.trigger_continue = True
                    return True
                if (time.time() - starttime) > self.timeout:
                    return False
                await asyncio.sleep(1)
        return True


    async def poll_done(self):
        starttime = time.time()
        self.trigger_done = False
        with nidaqmx.Task() as task:
            task.di_channels.add_di_chan(
                self.triggerport_done, line_grouping=LineGrouping.CHAN_PER_LINE
            )
            while self.trigger_done == False:
                data = task.read(number_of_samples_per_channel=1)
                # self.base.print_message("...................... done port status:", data)
                if any(data) == True:
                    self.base.print_message(" ... got PAL done trigger poll")
                    self.trigger_done_epoch = time.time_ns()
                    self.trigger_done = True
                    return True
                if (time.time() - starttime) > self.timeout:
                    return False
                await asyncio.sleep(1)
        return True


    async def init_PAL_IOloop(self, A: Action):
        activeDict = dict()
        if not self.IO_do_meas:
            self.IO_PALparams = cPALparams(**A.action_params)
            self.action = A
            self.IO_remotedatafile = ""
            self.FIFO_name = (
                f'PAL__{strftime("%Y%m%d_%H%M%S%z.txt")}'  # need to be txt at end
            )
            self.FIFO_dir = self.local_data_dump
            remotedatafile = os.path.join(
                self.FIFO_dir, "AUX__" + self.FIFO_name
            )
            self.base.print_message(" ... PAL saving to: {self.FIFO_dir}")
            self.FIFO_rshs_dir = self.FIFO_dir
            #            self.FIFO_rshs_dir = self.FIFO_rshs_dir.replace('C:\\','/cygdrive/c/')
            self.FIFO_rshs_dir = self.FIFO_rshs_dir.replace("C:\\", "")
            self.FIFO_rshs_dir = self.FIFO_rshs_dir.replace("\\", "/")
            self.base.print_message(f" ... RSHS saving to: /cygdrive/c/{self.FIFO_rshs_dir}")
            self.IO_continue = False
            self.IO_do_meas = True
            # wait for first continue trigger
            error = error_codes.none
            while not self.IO_continue:
                await asyncio.sleep(1)
            error = self.IO_error
            if self.active:
                activeDict = self.active.action.as_dict()
            else:
                activeDict = A.as_dict()
        else:
            activeDict = A.as_dict()
            error = error_codes.in_progress
            remotedatafile = ""


        activeDict["data"] = {"err_code": error, 
                              "remotedatafile": remotedatafile,
                          }
        return activeDict


    async def sendcommand_main(self, PALparams: cPALparams):
        """PAL takes liquid from sample_in and puts it in sample_out"""
        # default for return dict
        cmd_to_execute = ""
        # start_time = None
        # continue_time = None
        # done_time = None
        # ssh_time = None
        error =  error_codes.none
        # plate_id = None
        # sample_no = None


        # (1) check if we have free vial slots
        error = await self.sendcommand_prechecks(PALparams)
        if error is not error_codes.none:
            self.base.print_message(f" ... Got error after pre-checks: {error}", error = True)

        # (2) Rest
        if error is error_codes.none:
            # these will be constant and dont change for multi PAL sampling
            # only PALparams will be modified accordingly
            # self.base.print_message(" ... PAL got actionparams:", self.action_params)
            DUID = self.action.decision_uuid#self.action_params["DUID"]
            AUID = self.action.action_uuid#self.action_params["DUID"]
            actiontime = self.action.action_queue_time#self.action_params["actiontime"]

            if PALparams.liquid_sample_no_in < 0:
                 error = error_codes.not_available
                 self.base.print_message(f" ... liquid_sample_no < 0 ('{PALparams.liquid_sample_no_in}')", error = True)

            if error is error_codes.none:
                if PALparams.PAL_method != PALmethods.dilute and PALparams.PAL_method != PALmethods.deepclean: 
                    self.base.print_message(f" ... liquid_sample_no_in is: {PALparams.liquid_sample_no_in}")
                    if PALparams.liquid_sample_no_in == -1:
                        self.base.print_message(" ... PAL need to get last sample from list")
                        PALparams.liquid_sample_no_in = await self.liquid_sample_no_get_last()
                        self.base.print_message(" ... updated liquid_sample_no_in is", PALparams.liquid_sample_no_in)
        
                    liquid_sample_no_in_dict = await self.liquid_sample_no_get(PALparams.liquid_sample_no_in)
        
                    source_chemical = liquid_sample_no_in_dict.get("chemical", [""])
                    source_mass = liquid_sample_no_in_dict.get("mass", [""])
                    source_supplier = liquid_sample_no_in_dict.get("supplier", [""])
                    source_lotnumber = liquid_sample_no_in_dict.get("lot_number", [""])
                    self.base.print_message(f" ... source_electrolyte: {liquid_sample_no_in_dict['id']}")
                    self.base.print_message(f" ... source_chemical: {source_chemical}")
                    self.base.print_message(f" ... source_mass: {source_mass}")
                    self.base.print_message(f" ... source_supplier: {source_supplier}")
                    self.base.print_message(f" ... source_lotnumber: {source_lotnumber}")
                    liquid_sample_no_out_dict = await self.liquid_sample_no_create_new(
                        DUID,
                        AUID,
                        source=PALparams.liquid_sample_no_in,
                        volume_mL=PALparams.PAL_volume_uL / 1000.0,
                        action_time=actiontime,
                        chemical=source_chemical,
                        mass=source_mass,
                        supplier=source_supplier,
                        lot_number=source_lotnumber,
                        servkey=self.base.server_name,
                        plate_id = PALparams.PAL_plate_id, 
                        sample_no = PALparams.PAL_plate_sample_no
                    )
                
                    # TODO: check if ID was really created (later)
                    PALparams.liquid_sample_no_out = liquid_sample_no_out_dict["id"]

                    if PALparams.PAL_method == PALmethods.fill or PALparams.PAL_method == PALmethods.fillfixed:
                        if self.active:
                            self.active.action.action_params.update({"_eche_sample_no":PALparams.liquid_sample_no_out})



                    # update sample in and out
                    await self.sendcommand_update_action_sampleinout(PALparams)


                retvals = await self.sendcommand_ssh_helper(PALparams)
                error = retvals["error"]
                # ssh_time = retvals["ssh_time"]
                path_methodfile = retvals["path_methodfile"]
                rshs_pal_logfile = retvals["rshs_pal_logfile"]
    
                if error is not error_codes.none:
                    self.base.print_message(f" ... Got error after sendcommand_ssh_helper: {error}", error = True)
    
    
                if error is error_codes.none:
                    # waiting now for all three PAL triggers
                    # continue is use as the sampling timestamp
                    error = await self.sendcommand_triggerwait(PALparams)

                    if error is not error_codes.none:
                        self.base.print_message(f" ... Got error after triggerwait: {error}", error = True)
    
                    # write data
                    if self.active:
                        if self.active.action.save_data:
                            logdata = [
                                str(PALparams.liquid_sample_no_out),
                                str(PALparams.liquid_sample_no_in),
                                str(PALparams.PAL_ssh_time),
                                str(PALparams.PAL_start_time),
                                str(PALparams.PAL_continue_time),
                                str(PALparams.PAL_done_time),
                                PALparams.PAL_tool,
                                PALparams.PAL_source,
                                str(PALparams.PAL_volume_uL),
                                str(PALparams.PAL_source_tray),
                                str(PALparams.PAL_source_slot),
                                str(PALparams.PAL_source_vial),
                                PALparams.PAL_dest,
                                str(PALparams.PAL_dest_tray),
                                str(PALparams.PAL_dest_slot),
                                str(PALparams.PAL_dest_vial),
                                rshs_pal_logfile,
                                path_methodfile,
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


            # wait another 30sec for program to close
            await asyncio.sleep(20)

        # these will be arrays for multiple samples
        return {
            "cmd": cmd_to_execute,
            "PALtime": PALparams.PAL_ssh_time,
            "start": PALparams.PAL_start_time,
            "continue": PALparams.PAL_continue_time,
            "done": PALparams.PAL_done_time,
            "liquid_sample_no": PALparams.liquid_sample_no_out,
            "error": error,
        }



    async def sendcommand_prechecks(self, PALparams: cPALparams):
        error =  error_codes.none

        if PALparams.PAL_method == PALmethods.archive:
            newvialpos = await self.trayDB_new(
                            req_vol = PALparams.PAL_volume_uL/1000.0
                            )
            if newvialpos['tray'] is not None:
                # PALparams.PAL_source = "lcfc_res"
                PALparams.PAL_dest = "tray"
                PALparams.PAL_dest_tray = newvialpos['tray']
                PALparams.PAL_dest_slot = newvialpos['slot']
                PALparams.PAL_dest_vial = newvialpos['vial']
                self.base.print_message(f' ... archiving liquid sample to tray {PALparams.PAL_dest_tray}, slot {PALparams.PAL_dest_slot}, vial {PALparams.PAL_dest_vial}')
            else:
                self.base.print_message(' ... Tray is not available', error= True)
                error = error_codes.not_available
        elif PALparams.PAL_method == PALmethods.dilute:
            PALparams.PAL_dest = "tray"
            oldvial = await self.trayDB_get_vial_liquid_sample_no(
                            PALparams.PAL_dest_tray,
                            PALparams.PAL_dest_slot,
                            PALparams.PAL_dest_vial
                            )
            if oldvial['liquid_sample_no'] is not None:
                PALparams.liquid_sample_no_out = oldvial['liquid_sample_no']
            else:
                error = error_codes.not_available
                self.base.print_message(' ... old liquid_sample_no is None.', error= True)
        elif PALparams.PAL_method == PALmethods.deepclean:
            PALparams.PAL_dest = "waste"
            PALparams.PAL_source = "wash"
            PALparams.liquid_sample_no_in = 0
            PALparams.liquid_sample_no_out = 0
        elif PALparams.PAL_method == PALmethods.fill or PALparams.PAL_method == PALmethods.fillfixed:
            PALparams.PAL_dest = "lcfc_res"
            # PALparams.PAL_source = ""
            PALparams.PAL_plate_id =  self.action.plate_id
            PALparams.PAL_plate_sample_no =  None #TODO self.action.samples_in
        else:
            PALparams.PAL_dest = ""
            PALparams.PAL_source = ""
            PALparams.liquid_sample_no_in = 0
            PALparams.liquid_sample_no_out = 0
            PALparams.PAL_dest_tray = None
            PALparams.PAL_dest_slot = None
            PALparams.PAL_dest_vial = None
            self.base.print_message(f' ... unknown PAL method: {PALparams.PAL_method}', error= True)

            error = error_codes.not_available
        
        return error


    async def sendcommand_triggerwait(self, PALparams: cPALparams):
        error =  error_codes.none
        # only wait if triggers are configured
        if self.triggers:
            self.base.print_message(" ... waiting for PAL start trigger")
            # val = await self.wait_for_trigger_start()
            val = await self.poll_start()
            if not val:
                self.base.print_message(" ... PAL start trigger timeout", error = True)
                error = error_codes.start_timeout
                self.IO_error = error
                self.IO_continue = True
            else:
                self.base.print_message(" ... got PAL start trigger")
                self.base.print_message(" ... waiting for PAL continue trigger")
                PALparams.PAL_start_time = self.trigger_start_epoch
                # val = await self.wait_for_trigger_continue()
                val = await self.poll_continue()
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
                    PALparams.PAL_continue_time = self.trigger_continue_epoch
                    # val = await self.wait_for_trigger_done()
                    val = await self.poll_done()
                    if not val:
                        self.base.print_message(" ... PAL done trigger timeout", error = True)
                        error = error_codes.done_timeout
                        # self.IO_error = error
                        # self.IO_continue = True
                    else:
                        # self.IO_continue = True
                        # self.IO_continue = True
                        self.base.print_message(" ... got PAL done trigger")
                        PALparams.PAL_done_time = self.trigger_done_epoch
        return error


    async def sendcommand_update_action_sampleinout(self, PALparams: cPALparams):
        """Updates action sample_in and sample_out"""
        # TODO: use self.active.append_sample() instead later
        
        # get a copy of action in and out samples
        if "liquid_samples" in self.action.samples_in:
            temp_liquid_in = self.action.samples_in["liquid_samples"]
        else:
            temp_liquid_in = []
        if "liquid_samples" in self.action.samples_out:
            temp_liquid_out = self.action.samples_out["liquid_samples"]
        else:
            temp_liquid_out = []
        if "plate_samples" in self.action.samples_in:
            temp_plate_in = self.action.samples_in["plate_samples"]
        else:
            temp_plate_in = []


        
        if PALparams.PAL_method == PALmethods.archive:
            # we take liquid from this
            temp_liquid_in.append(PALparams.liquid_sample_no_in)
            # and add it to a new sample ID
            temp_liquid_out.append(PALparams.liquid_sample_no_out)

        elif PALparams.PAL_method == PALmethods.dilute:
            # the sample that gets diluted
            temp_liquid_in.append(PALparams.liquid_sample_no_out)
            # the sample that gets added
            temp_liquid_in.append(PALparams.liquid_sample_no_in)
            # out the diluted sample
            temp_liquid_out.append(PALparams.liquid_sample_no_out)

        elif PALparams.PAL_method == PALmethods.deepclean:
            # nothing in in and out
            pass

        elif PALparams.PAL_method == PALmethods.fill or PALparams.PAL_method == PALmethods.fillfixed:
            # the reservoir from which a sample gets taken
            temp_liquid_in.append(PALparams.liquid_sample_no_in)
            # the new sample in the echem cell (in contact with the solid sample)
            temp_liquid_out.append(PALparams.liquid_sample_no_out)
            # the solid sample
            temp_plate_in.append(PALparams.PAL_plate_sample_no)


        # update action sample in and out (only temp in/out is not empty)
        # set removes duplicates
        if temp_liquid_in:
            self.action.samples_in.update({"liquid_samples": sorted(set(temp_liquid_in))})
        if temp_liquid_out:
            self.action.samples_out.update({"liquid_samples": sorted(set(temp_liquid_out))})
        if temp_plate_in:
            self.action.samples_in.update({"plate_samples": sorted(set(temp_plate_in))})


    async def sendcommand_ssh_helper(self, PALparams: cPALparams):
        ssh_connected = False
        error = error_codes.none
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
                self.base.print_message(' ... SSH connection error. Retrying in 1 seconds.')
                await asyncio.sleep(1)


        try:
            # creating remote folder and logfile on RSHS
            rshs_path = "/cygdrive/c"
            for path in self.FIFO_rshs_dir.split("/"):
        
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
        
            rshs_logfile = "AUX__" + self.FIFO_name
            rshs_logfilefull = rshs_path + rshs_logfile
            sshcmd = f"touch {rshs_logfilefull}"
            (
                mysshclient_stdin,
                mysshclient_stdout,
                mysshclient_stderr,
            ) = mysshclient.exec_command(sshcmd)
        
            auxheader = "Date\tMethod\tTool\tSource\tDestinationTray\tDestinationSlot\tDestinationVial\tVolume\r\n"
            sshcmd = f'echo -e "{auxheader}" > {rshs_logfilefull}'
            (
                mysshclient_stdin,
                mysshclient_stdout,
                mysshclient_stderr,
            ) = mysshclient.exec_command(sshcmd)
            self.base.print_message(f" ... final RSHS logfile: {rshs_logfilefull}")

            # rshs_pal_logfile = self.log_file
            rshs_pal_logfile = os.path.join(
                self.FIFO_dir, "AUX__" + self.FIFO_name
            )  # need to be txt at end
            self.IO_remotedatafile = rshs_pal_logfile
            
            
            wash1 = 'False'
            wash2 = 'False'
            wash3 = 'False'
            wash4 = 'False'
            if PALparams.PAL_wash1 is True:
                wash1 = 'True'
            if PALparams.PAL_wash2 is True:
                wash2 = 'True'
            if PALparams.PAL_wash3 is True:
                wash3 = 'True'
            if PALparams.PAL_wash4 is True:
                wash4 = 'True'
            
            path_methodfile = os.path.join(self.method_path, PALparams.PAL_method.value)
            cmd_to_execute = f'tmux new-window PAL  /loadmethod "{path_methodfile}" "{PALparams.PAL_tool};{PALparams.PAL_source};{PALparams.PAL_volume_uL};{PALparams.PAL_dest_tray};{PALparams.PAL_dest_slot};{PALparams.PAL_dest_vial};{wash1};{wash2};{wash3};{wash4};{rshs_pal_logfile}" /start /quit'
            self.base.print_message(f" ... PAL command: {cmd_to_execute}")
        
            # update now the vial warehouse before PAL command gets executed
            # only needs to be updated if
            if  PALparams.PAL_dest_tray is not None:
                if PALparams.PAL_method == PALmethods.dilute:
                    retval = await self.trayDB_update(
                                                      tray = PALparams.PAL_dest_tray,
                                                      slot = PALparams.PAL_dest_slot,
                                                      vial = PALparams.PAL_dest_vial,
                                                      vol_mL = PALparams.PAL_volume_uL/1000.0,
                                                      liquid_sample_no = PALparams.liquid_sample_no_out,
                                                      dilute = True
                                                      )
                elif PALparams.PAL_method == PALmethods.deepclean:
                    retval = True
                else:
                    retval = await self.trayDB_update(
                                                      tray = PALparams.PAL_dest_tray,
                                                      slot = PALparams.PAL_dest_slot,
                                                      vial = PALparams.PAL_dest_vial,
                                                      vol_mL = PALparams.PAL_volume_uL/1000.0,
                                                      liquid_sample_no = PALparams.liquid_sample_no_out
                                                      )
                if retval == False:
                    error = error_codes.not_available


        except Exception:
            self.base.print_message('##############################################################')
            self.base.print_message(' ... SSH connection error 1. Could not send commands.')
            self.base.print_message('##############################################################')
            error = error_codes.ssh_error


        try:
            if error is error_codes.none:
                PALparams.PAL_ssh_time = time.time_ns()
                (
                    mysshclient_stdin,
                    mysshclient_stdout,
                    mysshclient_stderr,
                ) = mysshclient.exec_command(cmd_to_execute)
                mysshclient.close()
 
        except Exception:
            self.base.print_message('##############################################################')
            self.base.print_message(' ... SSH connection error 2. Could not send commands.')
            self.base.print_message('##############################################################')
            error = error_codes.ssh_error
    
        return {
            "error": error,
            "path_methodfile": path_methodfile,
            "rshs_pal_logfile": rshs_pal_logfile
            }


    async def IOloop(self):
        while True:
            await asyncio.sleep(1)
            if self.IO_do_meas:
                # are we in estop?
                if not self.IO_estop:

                    # write file header here
                    # PAL takes liquid from sample_in and puts it in sample_out
                    self.FIFO_column_headings = [
                        "liquid_sample_no_out",
                        "liquid_sample_no_in",
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


                    tmps_headings = "\t".join(self.FIFO_column_headings)
                    self.FIFO_PALheader = "\n".join(
                        [
                            f"%techniquename={self.IO_PALparams.PAL_method}",
                            "%epoch_ns=FIXME",
                            "%version=0.2",
                            f"%column_headings={tmps_headings}",
                        ]
                    )

                    self.active = await self.base.contain_action(
                        self.action,
                        file_type="pal_file",
                        file_group="pal_files",
                        header=self.FIFO_PALheader,
                    )
                    self.base.print_message(f" ... Active action uuid is {self.active.action.action_uuid}")
                    realtime = await self.active.set_realtime()
                    self.FIFO_PALheader.replace("%epoch_ns=FIXME", f"%epoch_ns={realtime}")




                    # for sequence, the sample in is always the same
                    self.base.print_message(f" ... liquid_sample_no_in: {self.IO_PALparams.liquid_sample_no_in}")
                    # need to check for None
                    
                    if self.IO_PALparams.liquid_sample_no_in is None:
                        self.base.print_message(' ... error, invalid liquid_sample_no_in.')
                        # await self.IOloop_meas_end_helper()
                    else:
                        
                        if self.IO_PALparams.liquid_sample_no_in < 0:
                            self.base.print_message(f' ... PAL need to get n-{self.IO_PALparams.liquid_sample_no_in+1} last sample from list')
                            sampledict = await self.liquid_sample_no_get_last(self.IO_PALparams.liquid_sample_no_in)
                            self.IO_PALparams.liquid_sample_no_in = sampledict["id"]
                            self.base.print_message(' ... correct liquid_sample_no_in is now:', self.IO_PALparams.liquid_sample_no_in)
                        # need to check for none again if no sample_no_was obtained
                        if self.IO_PALparams.liquid_sample_no_in is None:
                            self.base.print_message(' ... error, invalid liquid_sample_no_in.')
                        else:
        
        
                            start_time = time.time()
                            last_time = start_time
                            prev_timepoint = 0.0
                            diff_time = 0.0
                            backuptrays = copy.deepcopy(self.trays)
                            
                            # for multipe vials we don't wait for first trigger
                            if self.IO_PALparams.PAL_totalvials > 1:
                                self.IO_continue = True
                            
                            for vial in range(self.IO_PALparams.PAL_totalvials):
                                self.base.print_message(f' ... vial {vial+1} of {self.IO_PALparams.PAL_totalvials}')
                                run_PALparams = self.IO_PALparams
                                run_PALparams.PAL_cur_sample = vial
        
        
                                if self.IO_PALparams.PAL_method == PALmethods.dilute:
                                    newvialpos = await self.trayDB_get_first_full(vialtable = backuptrays)
                                    if newvialpos['tray'] is not None:
                                        # mark this spot as False now so 
                                        # it won't be found again next time
                                        backuptrays[newvialpos['tray']-1].slots[newvialpos['slot']-1].vials[newvialpos['vial']-1] = False
                                        run_PALparams.PAL_dest_tray = newvialpos['tray']
                                        run_PALparams.PAL_dest_slot = newvialpos['slot']
                                        run_PALparams.PAL_dest_vial = newvialpos['vial']
                                        self.base.print_message(f' ... diluting liquid sample in tray {run_PALparams.PAL_dest_tray}, slot {run_PALparams.PAL_dest_slot}, vial {run_PALparams.PAL_dest_vial}')
                                    else:
                                        self.base.print_message(' ... no full vial slots')
                                        break
        
        
        
        
                                # get the scheduled time for next PAL command
                                # self.IO_PALparams.timeoffset corrects for offset 
                                # between send ssh and continue (or any other offset)
                                if self.IO_PALparams.PAL_spacingmethod == Spacingmethod.linear:
                                    self.base.print_message(' ... PAL linear scheduling')
                                    cur_time = time.time()
                                    diff_time = self.IO_PALparams.PAL_sampleperiod[0]-(cur_time-last_time)-self.IO_PALparams.PAL_timeoffset
                                elif self.IO_PALparams.PAL_spacingmethod == Spacingmethod.geometric:
                                    self.base.print_message(' ... PAL geometric scheduling')
                                    timepoint = (self.IO_PALparams.PAL_spacingfactor ** vial) * self.IO_PALparams.PAL_sampleperiod[0]
                                    diff_time = timepoint-prev_timepoint-(cur_time-last_time)-self.IO_PALparams.PAL_timeoffset
                                    prev_timepoint = timepoint # todo: consider time lag
                                elif self.IO_PALparams.PAL_spacingmethod == Spacingmethod.custom:
                                    self.base.print_message(' ... PAL custom scheduling')
                                    cur_time = time.time()
                                    self.base.print_message((cur_time-last_time))
                                    self.base.print_message(self.IO_PALparams.PAL_sampleperiod[vial])
                                    diff_time = self.IO_PALparams.PAL_sampleperiod[vial]-(cur_time-start_time)-self.IO_PALparams.PAL_timeoffset
        
        
                                self.base.print_message(f' ... PAL waits {diff_time} for sending next command')
                                # only wait for positive time
                                if (diff_time > 0):
                                    await asyncio.sleep(diff_time)
        
        
        
                                last_time = time.time()
                                self.base.print_message(' ... PAL sendcommmand def start')
                                retvals = await self.sendcommand_main(run_PALparams)
                                self.base.print_message(' ... PAL sendcommmand def end')



                    await self.IOloop_meas_end_helper()

                else:
                    self.IO_do_meas = False
                    self.base.print_message(" ... PAL is in estop.")
                    # await self.stat.set_estop()


    async def IOloop_meas_end_helper(self):
        self.IO_continue = True
        # done sending all PAL commands
        self.IO_do_meas = False

        # need to check here again in case estop was triggered during
        # measurement
        # need to set the current meas to idle first
        _ = await self.active.finish()
        self.active = None
        self.action = None

        if self.IO_estop:
            self.base.print_message(" ... PAL is in estop.")
            # await self.stat.set_estop()
        else:
            self.base.print_message(" ... setting PAL to idle")
        #                        await self.stat.set_idle()
        self.base.print_message(" ... PAL is done")



    async def IOloop_meas_start_helper(self):
        pass


    async def liquid_sample_no_get_last(self, last_no: int = -1):
        lastno = await self.liquid_sample_no_DB.count_liquid_sample_no()
        datadict = await self.liquid_sample_no_DB.get_liquid_sample_no(lastno+last_no+1)
        return datadict


    async def liquid_sample_no_get(self, liquid_sample_no: int,*args,**kwargs):
        datadict = await self.liquid_sample_no_DB.get_liquid_sample_no(liquid_sample_no)
        return datadict

    async def liquid_sample_no_create_new(
        self,
        DUID: str = "",
        AUID: str = "",
        source: str = None,
        volume_mL: float = None,
        action_time: str = strftime("%Y%m%d.%H%M%S"),
        chemical: List[str] = [],
        mass: List[str] = [],
        supplier: List[str] = [],
        lot_number: List[str] = [],
        servkey: str = None,
        plate_id: int = None,
        sample_no: int = None,
        *args,**kwargs
    ):
        entry = dict(
            DUID=DUID,
            AUID=AUID,
            source=source,
            volume_mL=volume_mL,
            action_time=action_time,
            chemical=chemical,
            mass=mass,
            supplier=supplier,
            lot_number=lot_number,
            servkey=self.base.server_name,
            plate_id = plate_id,
            sample_no = sample_no
        )
        datadict = await self.liquid_sample_no_DB.new_liquid_sample_no(entry)
        return datadict
