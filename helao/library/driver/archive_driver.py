

__all__ = ["Archive"]

import asyncio
import os
from datetime import datetime
import copy
from typing import List
from socket import gethostname
import pickle
import re

from helaocore.server import Base
from helaocore.error import error_codes

import helaocore.model.sample as hcms
from helaocore.helper import print_message


class Custom:
    def __init__(self, custom_name, custom_type):
        self.sample = hcms.SampleList()
        self.custom_name = custom_name
        self.custom_type = custom_type
        self.blocked = False
        self.vol_mL = 0.0
        self.max_vol_mL = None
        self.dilution_factor = 1.0
        
        
    def assembly_allowed(self):
        if self.custom_type == "cell":
            return True
        elif self.custom_type == "reservoir":
            return True
        else:
            print_message({}, "model", f"invalid 'custom_type': {self.custom_type}", error = True)                
            return False

    def unload(self):
        ret_sample = self.sample
        self.blocked = False
        self.vol_mL = 0.0
        self.max_vol_mL = None
        self.dilution_factor = 1.0
        self.sample = hcms.SampleList()
        return ret_sample

    def as_dict(self):
        return vars(self)

    
class VT_template:
    def __init__(self, max_vol_mL: float = 0.0, VTtype: str = "", positions: int = 0):
        self.type: str = VTtype
        self.max_vol_mL: float = max_vol_mL
        self.vials: List[bool] = [False for i in range(positions)]
        self.blocked: List[bool] = [False for i in range(positions)]
        self.vol_mL: List[float] = [0.0 for i in range(positions)]
        self.sample: List[hcms.SampleList] = [hcms.SampleList() for i in range(positions)]
        self.dilution_factor: List[float] = [1.0 for i in range(positions)]


    def first_empty(self):
        # res = next((i for i, j in enumerate(self.vials) if not j), None)
        res = next((i for i, j in enumerate(self.vials) if not j and not self.blocked[i]), None)
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

    def update_sample(self, samples):
        for i, sample in enumerate(samples):
            try:
                self.sample[i] = sample
            except Exception:
                self.sample[i] = None


    def update_dilution_factor(self, samples):
        for i, df in enumerate(samples):
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


class Archive():
    def __init__(self, process_serv: Base):
        
        self.base = process_serv
        self.config_dict = process_serv.server_cfg["params"]
        self.world_config = process_serv.world_cfg


        
        self.position_config = self.config_dict.get("positions", None)
        self.local_data_dump = self.world_config["save_root"]
        self.archivepck = os.path.join(self.local_data_dump, f"{gethostname()}_archive.pck")
        self.config = {}

        # configure the tray
        self.trays = dict()
        self.custom_positions = dict()
        self.startup_trays = dict()
        self.startup_custom_positions = dict()

        # get some empty db dicts from default config
        self.startup_trays, self.startup_custom_positions = self.process_startup_config()
        # compare default config to backup

        try:
            self.load_config()
        except IOError:
            self.base.print_message(f"'{self.archivepck}' does not exist, writing empty global dict.", error = True)
            self.write_config()
        except Exception:
            # print_message({}, "launcher", f"Error loading '{pidFile}', writing empty global dict.", error = True)
            self.write_config()


        
        # check trays
        failed = False
        if len(self.trays) == len(self.startup_trays):
            for i, tray in self.trays.items():
                if i not in self.startup_trays:
                    failed = True
                    break
                else:
                    if len(tray) == len(self.startup_trays[i]):
                        for slot in tray.keys():
                            if slot not in self.startup_trays[i]:
                                self.base.print_message("slot not present", error = True)
                                failed = True
                                break
                            else:
                                if type(tray[slot]) != type(self.startup_trays[i][slot]):
                                    self.base.print_message("not the same slot type", error = True)
                                    failed = True
                                    break
                            
                    else:
                        self.base.print_message("tray has not the same length", error = True)
                        failed = True
                        break
        else:
            self.base.print_message("not the same length", error = True)
            failed = True




        if failed:
            self.base.print_message("trays did not match", error = True)
            self.trays = copy.deepcopy(self.startup_trays)
        else:
            self.base.print_message("trays matched", info = True)


        # check custom positions
        failed = False
        if len(self.custom_positions) != len(self.startup_custom_positions):
            for key, val in self.custom_positions.items():
                if key not in self.startup_custom_positions:
                    
                    failed = True
                    break
                else:
                    if type(val) != type(self.startup_custom_positions[key]):
                        failed = True
                        break
        else:
            failed = True


        if failed:
            self.base.print_message("customs did not match", error = True)
            self.custom_positions = copy.deepcopy(self.startup_custom_positions)
        else:
            self.base.print_message("customs matched", info = True)
        

        self.write_config()


        
    def process_startup_config(self):
        custom_positions = dict()
        trays_dict = dict()

        pattern = re.compile("([a-zA-Z]+)([0-9]+)")
        if self.position_config != None:
            for key, val in self.position_config.items():
                key = key.lower()
                test = pattern.match(key)
                if test is None:
                    if key == "custom":
                        for custom_name, custom_type in val.items():
                            custom_positions.update({custom_name:
                                            Custom(custom_name, custom_type)})

                        # for custom in val:
                        #     custom_positions.update({custom:hcms.SampleList()})
                else:
                    tmps, tmpi = test.groups()
                    tmpi = int(tmpi)
                    if tmps == "tray":
                        if val is not None:
                            for slot, slot_item in val.items():
                                slot_no = None
                                if slot == "slot1":
                                    slot_no = 1
                                elif slot == "slot2":
                                    slot_no = 2
                                elif slot == "slot3":
                                    slot_no = 3
                                else:
                                    self.base.print_message(f"unknown slot item '{slot}'", error = True)
                                    continue

                                if slot_no is not None:
                                    if tmpi not in trays_dict:
                                        trays_dict[tmpi] = dict()
                                        
                                        
                                    if slot_item is not None:
                                        self.base.print_message(f" ... got {slot_item}")
                                        if slot_item == "VT54":
                                            trays_dict[tmpi][slot_no] = VT54()
                                        elif slot_item == "VT15":
                                            trays_dict[tmpi][slot_no] = VT15()
                                        elif slot_item == "VT70":
                                            trays_dict[tmpi][slot_no] = VT70()


                                        else:
                                            self.base.print_message(f" ... slot type {slot_item} not supported", error = True)
                                            trays_dict[tmpi][slot_no] = None
                                    else:
                                        trays_dict[tmpi][slot_no] = None
        self.base.print_message(trays_dict)
        self.base.print_message(custom_positions)
        return trays_dict, custom_positions
        

    def load_config(self):
        filehandler = open(self.archivepck, "rb")
        data = pickle.load(filehandler)
        self.trays = data.get("trays", [])
        self.custom_positions = data.get("customs", {})
        filehandler.close()
        

        
    def write_config(self):
        data = {"customs":self.custom_positions, "trays":self.trays}
        filehandler = open(self.archivepck, "wb")
        pickle.dump(data, filehandler)
        filehandler.close()


    async def trays_to_dict(self):
        traydict = copy.deepcopy(self.trays)
        for tray_key, tray_item in traydict.items():
            self.base.print_message(tray_key, tray_item)
            if tray_item is not None:
                for slot_key, slot_item in tray_item.items():
                    self.base.print_message(slot_key, slot_item)
                    if slot_item is not None:
                        tray_item[slot_key] = slot_item.as_dict()
        return traydict


    async def reset_trays(self, *args, **kwargs):
        # resets PAL table
        ret = await self.trays_to_dict()
        self.trays = copy.deepcopy(self.startup_trays)
        return ret
    
    
    async def tray_export_json(self, tray, slot, *args,**kwargs):
        self.write_config()

        if tray in self.trays:
            if slot in self.trays[tray]:
                if self.trays[tray][slot] is not None:
                    return self.trays[tray][slot].as_dict()

    
    async def tray_export_csv(
                              self,
                              tray,
                              slot,
                              myactive
                             ):
        self.write_config() # save backup

        if tray in self.trays:
            if self.trays[tray] is not None:
                if slot in self.trays[tray]:
                    if self.trays[tray][slot] is not None:
                        tmp_output_str = ""
                        for i, vial in enumerate(self.trays[tray][slot].vials):
                            if tmp_output_str != "":
                                tmp_output_str += "\n"
                            tmp_output_str += ",".join(
                                [
                                    str(i + 1),
                                    str(
                                        self.trays[tray]
                                        .slots[slot]
                                        .sample[i].get_global_label()
                                    ),
                                    str(self.trays[tray].slots[slot].vol_mL[i]),
                                ]
                            )
                await myactive.write_file(
                    file_type = "pal_vialtable_file",
                    filename = f"VialTable__tray{tray}__slot{slot}__{datetime.now().strftime('%Y%m%d.%H%M%S%f')}.csv",
                    output_str = tmp_output_str,
                    header = ",".join(["vial_no", "global_sample_label", "vol_mL"]),
                    sample_str = None
                    )


    async def tray_export_icpms(self, 
                                tray: int, 
                                slot: int, 
                                myactive, 
                                survey_runs: int,
                                main_runs: int,
                                rack: int,
                                dilution_factor: float = None,
                               ):
        self.write_config() # save backup

        if tray in self.trays:
            if self.trays[tray] is not None:
                if slot in self.trays[tray]:
                    if self.trays[tray][slot] is not None:
                        tmp_output_str = ""
                        for i, vial in enumerate(self.trays[tray][slot].vials):
                            if tmp_output_str != "":
                                tmp_output_str += "\n"
                            if vial is True:
                                if dilution_factor is None:
                                    temp_dilution_factor = self.trays[tray][slot].dilution_factor[i]
                                tmp_output_str += ";".join(
                                    [
                                        str(
                                            self.trays[tray]
                                            .slots[slot]
                                            .sample[i].get_global_label()
                                        ),
                                        str(survey_runs),
                                        str(main_runs),
                                        str(rack),
                                        str(i + 1),
                                        str(temp_dilution_factor),
                                    ]
                                )

                await myactive.write_file(
                    file_type = "pal_icpms_file",
                    filename = f"VialTable__tray{tray}__slot{slot}__{datetime.now().strftime('%Y%m%d-%H%M%S%f')}_ICPMS.csv",
                    output_str = tmp_output_str,
                    header = ";".join(["global_sample_label", "Survey Runs", "Main Runs", "Rack", "Vial", "Dilution Factor"]),
                    sample_str = None
                    )
                
                
    async def tray_get_sample(self, tray: int, slot: int, vial: int):
        vial -= 1
        sample = hcms.SampleList()
        error = error_codes.not_available


        if tray in self.trays:
            if self.trays[tray] is not None:
                if slot in self.trays[tray]:
                    if self.trays[tray][slot] is not None:
                        error = error_codes.none
                        if self.trays[tray][slot].vials[vial] is not False:
                            sample = self.trays[tray][slot].sample[vial]
                            

        return error, sample


    async def tray_new_position(self, req_vol: float = 2.0, *args, **kwargs):
        """Returns an empty vial position for given max volume.\n
        For mixed vial sizes the req_vol helps to choose the proper vial for sample volume.\n
        It will select the first empty vial which has the smallest volume that still can hold req_vol"""
        
        await asyncio.sleep(0.001)
        lock = asyncio.Lock()
        async with lock:
            self.base.print_message(self.trays)
            new_tray = None
            new_slot = None
            new_vial = None
            new_vial_vol = float("inf")
            
            
            for tray_no in sorted(self.trays.keys()):
                if self.trays[tray_no] is not None:
                    for slot_no in sorted(self.trays[tray_no]):
                        if self.trays[tray_no][slot_no] is not None:
                            if (
                                self.trays[tray_no][slot_no].max_vol_mL >= req_vol
                                and new_vial_vol > self.trays[tray_no][slot_no].max_vol_mL
                            ):
                                position = self.trays[tray_no][slot_no].first_empty()
                                if position is not None:
                                    new_tray = tray_no
                                    new_slot = slot_no
                                    new_vial = position + 1
                                    new_vial_vol = self.trays[tray_no][slot_no].max_vol_mL
                                    self.trays[tray_no][slot_no].blocked[position] = True
    
            self.base.print_message(f" ... new vial nr. {new_vial} in slot {new_slot} in tray {new_tray}")
            return {"tray": new_tray, "slot": new_slot, "vial": new_vial}


    async def tray_get_next_full(self, 
                                 after_tray: int = -1, 
                                 after_slot: int = -1, 
                                 after_vial: int = -1
                                ):

        """Finds the next full vial after the current vial position
        defined in micropal."""
        new_tray = None
        new_slot = None
        new_vial = None
        after_vial -= 1;
        for tray_no in sorted(self.trays.keys()):
            if self.trays[tray_no] is not None:
                if tray_no < after_tray:
                    continue
                else:
                    for slot_no in sorted(self.trays[tray_no]):
                        if self.trays[tray_no][slot_no] is not None:
                            if tray_no <= after_tray \
                            and slot_no < after_slot:
                                continue
                            else:
                                for vial_no, vial in enumerate(self.trays[tray_no][slot_no].vials):
                                    if vial is not None:
                                        if tray_no <= after_tray \
                                        and slot_no <= after_slot \
                                        and vial_no <= after_vial:
                                            continue
                                        else:
                                            if vial[vial_no] == True:
                                                new_tray = tray_no
                                                new_slot = slot_no
                                                new_vial = vial_no + 1 # starts at 0 in []
                                                break

        
        return {"tray": new_tray,
                "slot": new_slot,
                "vial": new_vial}


    async def tray_update_position(
                                   self, 
                                   tray: int, 
                                   slot: int, 
                                   vial: int, 
                                   vol_mL: float, 
                                   sample: hcms.SampleList,
                                   dilute: bool = False,
                                   *args,**kwargs
                                  ):
        vial -= 1
        if tray in self.trays:
            if self.trays[tray] is not None:
                if slot in self.trays[tray]:
                    if self.trays[tray][slot] is not None:
                        if self.trays[tray][slot].vials[vial] is not True:
                            self.trays[tray][slot].vials[vial] = True
                            self.trays[tray][slot].vol_mL[vial] = vol_mL
                            self.trays[tray][slot].sample[vial] = sample
                            self.trays[tray][slot].dilution_factor[vial]  = 1.0
                            # backup file
                            self.write_config()
                            return True
                        else:
                            if dilute is True:
                                self.trays[tray][slot].vials[vial] = True
                                old_vol = self.trays[tray][slot].vol_mL[vial]
                                old_df = self.trays[tray][slot].dilution_factor[vial]
                                tot_vol = old_vol + vol_mL
                                new_df = tot_vol/(old_vol/old_df)
                                self.trays[tray][slot].vol_mL[vial] = tot_vol
                                self.trays[tray][slot].dilution_factor[vial] = new_df
                                
                                self.write_config()
                                return True

                        self.write_config()

        return False


    def custom_assembly_allowed(self, custom: str):
        if custom in self.custom_positions:
            return self.custom_positions[custom].assembly_allowed()
        else:
            return False


    async def custom_get_sample(self, custom: str):
        sample = hcms.SampleList()
        error = error_codes.none
        
        if custom in self.custom_positions:
            sample = self.custom_positions[custom].sample
        else:
            error = error_codes.not_available

        return error, sample


    async def custom_update_position(
                                     self,
                                     custom: str,
                                     vol_mL: float,
                                     sample: hcms.SampleList,
                                     dilute: bool = False,
                                     *args,**kwargs
                                    ):

        if custom in self.custom_positions:
            if len(sample.samples) > 1:
                return False, hcms.SampleList()
            if sample.samples[0].sample_type == "assembly" \
            and not self.custom_positions[custom].assembly_allowed():
                return False, hcms.SampleList()

            if dilute:
                old_vol = self.custom_positions[custom].vol_mL
                old_df = self.custom_positions[custom].dilution_factor
                tot_vol = old_vol + vol_mL
                new_df = tot_vol/(old_vol/old_df)
                self.custom_positions[custom].dilution_factor = new_df
                self.custom_positions[custom].vol_mL = tot_vol
                self.custom_positions[custom].sample = sample
            else:
                self.custom_positions[custom].sample = sample
                self.custom_positions[custom].vol_mL = 0.0
                self.custom_positions[custom].dilution_factor = 1.0
            
            self.write_config()

        return True, sample
    

    async def customs_to_dict(self):
        customdict = copy.deepcopy(self.custom_positions)
        for custom_key in customdict.keys():
            customdict[custom_key] = customdict[custom_key].as_dict()
        return customdict

    
    async def custom_unloadall(self, *args, **kwargs):
        samples = hcms.SampleList()
        for custom in self.custom_positions:
            _samples = custom.unload()
            for sample in _samples.samples:
                samples.samples.append(sample)
        # ret = await self.customs_to_dict()
        # self.custom_positions = copy.deepcopy(self.startup_custom_positions)
        return True, samples


    async def custom_unload(self, custom: str = "", *args, **kwargs):
        if custom in self.custom_positions:
            sample = self.custom_positions[custom].unload()
            return True, sample
        return False, hcms.hcms.SampleList()


    async def custom_load(
                          self,
                          custom: str,
                          vol_mL: float,
                          load_samples_in: hcms.SampleList,
                          *args, **kwargs
                         ):

        if type(load_samples_in) is dict:
            load_samples_in = hcms.SampleList(**load_samples_in)


        return await self.custom_update_position(
                                     custom = custom,
                                     vol_mL = vol_mL,
                                     sample = load_samples_in,
                                     dilute = False
                                    )