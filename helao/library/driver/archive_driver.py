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
import helaocore.data as hcd
from helaocore.helper import print_message


class Custom:
    def __init__(self, custom_name, custom_type):
        self.sample = hcms.SampleList()
        self.custom_name = custom_name
        self.custom_type = custom_type
        self.blocked = False
        self.max_vol_ml = None
        
        
    def assembly_allowed(self):
        if self.custom_type == "cell":
            return True
        elif self.custom_type == "reservoir":
            return False
        else:
            print_message({}, "archive", f"invalid 'custom_type': {self.custom_type}", error = True)                
            return False


    def dilution_allowed(self):
        if self.custom_type == "cell":
            return True
        elif self.custom_type == "reservoir":
            return False
        else:
            print_message({}, "archive", f"invalid 'custom_type': {self.custom_type}", error = True)                
            return False


    def dest_allowed(self):
        if self.custom_type == "cell":
            return True
        elif self.custom_type == "reservoir":
            return False
        else:
            print_message({}, "archive", f"invalid 'custom_type': {self.custom_type}", error = True)                
            return False


    def unload(self):
        ret_sample = copy.deepcopy(self.sample)
        self.blocked = False
        self.max_vol_ml = None
        self.sample = hcms.SampleList()
        return ret_sample

    
    def load(self, sample_in:  hcms.SampleList):
        if self.sample.samples:
            print_message({}, "archive", "sample already loaded. Unload first to load new one.", error = True) 
            return False, hcms.SampleList()

        if len(sample_in.samples) > 1:
            print_message({}, "archive", "Can only load one sample", error = True) 
            return False, hcms.SampleList()
        
        self.sample = copy.deepcopy(sample_in)
        self.blocked = False
        print_message({}, "archive", f"loaded sample {sample_in.samples[0].global_label}", info = True) 
        return True, copy.deepcopy(sample_in)


    def as_dict(self):
        ret_dict = copy.deepcopy(vars(self)) # it needs a deepcopy
                                             # else the next line will
                                             # overwrite self.sample too
        ret_dict["sample"] = self.sample.dict()
        return ret_dict

    
class VT_template:
    def __init__(self, max_vol_ml: float = 0.0, VTtype: str = "", positions: int = 0):
        self.init_max_vol_ml = max_vol_ml
        self.init_VTtype = VTtype
        self.init_positions = positions
        self.reset_tray()

    def reset_tray(self):
        self.type = self.init_VTtype
        self.max_vol_ml: float = self.init_max_vol_ml
        self.vials: List[bool] = [False for i in range(self.init_positions)]
        self.blocked: List[bool] = [False for i in range(self.init_positions)]
        self.sample: List[hcms.SampleList] = [hcms.SampleList() for i in range(self.init_positions)]


    def first_empty(self):
        res = next((i for i, j in enumerate(self.vials) if not j and not self.blocked[i]), None)
        return res
    

    def first_full(self):
        res = next((i for i, j in enumerate(self.vials) if j), None)
        return res


    def update_vials(self, vial_dict):
        for i, vial in enumerate(vial_dict):
            try:
                self.vials[i] = bool(vial)
            except Exception:
                self.vials[i] = False

    def update_sample(self, samples):
        for i, sample in enumerate(samples):
            try:
                self.sample[i] = copy.deepcopy(sample)
            except Exception:
                self.sample[i] = None


    def as_dict(self):
        ret_dict = copy.deepcopy(vars(self)) # it needs a deepcopy
                                             # else the next line will
                                             # overwrite self.sample too
        ret_dict["sample"] = [sample.dict() for sample in self.sample]
        return ret_dict

    def unload(self):
        ret_sample = hcms.SampleList()
        for samplelist in self.sample:
            for sample in samplelist.samples:
                ret_sample.samples.append(copy.deepcopy(sample))
        
        self.reset_tray()
        return ret_sample

        

class VT15(VT_template):
    def __init__(self, max_vol_ml: float = 10.0):
        super().__init__(max_vol_ml = max_vol_ml, VTtype = "VT15", positions = 15)


class VT54(VT_template):
    def __init__(self, max_vol_ml: float = 2.0):
        super().__init__(max_vol_ml = max_vol_ml, VTtype = "VT54", positions = 54)


class VT70(VT_template):
    def __init__(self, max_vol_ml: float = 1.0):
        super().__init__(max_vol_ml = max_vol_ml, VTtype = "VT70", positions = 70)


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

        self.sample_no_db_path = self.world_config["local_db_path"]
        self.unified_db = hcd.UnifiedSampleDataAPI(self.base, self.sample_no_db_path)
        asyncio.gather(self.unified_db.init_db())

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
                        for slot in tray:
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
        if len(self.custom_positions) == len(self.startup_custom_positions):
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


        # update all samples in tray and custom positions
        self.write_config()
        asyncio.gather(self.update_samples_from_db())

        
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
        with open(self.archivepck, "rb") as f:
            data = pickle.load(f)
            self.trays = data.get("trays", [])
            self.custom_positions = data.get("customs", {})


    def write_config(self):
        data = {"customs":self.custom_positions, "trays":self.trays}
        with open(self.archivepck, "wb") as f:
            pickle.dump(data, f)

    async def update_samples_from_db(self):
        self.base.print_message("Updating all samples in position table.", info = True)
        # need to wait for the db to finish initializing
        while not self.unified_db.ready:
            self.base.print_message("db not ready", info = True)
            await asyncio.sleep(0.1)

        # first update all custom position samples
        for custom in self.custom_positions:
            self.custom_positions[custom].sample = \
                await self.update_samples_from_db_helper(self.custom_positions[custom].sample)

        # second update all tray samples
        for tray_key, tray_item in self.trays.items():
            if tray_item is not None:
                for slot_key, slot_item in tray_item.items():
                    if slot_item is not None:
                        for i, sample_list in enumerate(slot_item.sample):
                            slot_item.sample[i] = \
                                await self.update_samples_from_db_helper(sample_list)

        # update all samples in tray and custom positions
        self.write_config()


    async def update_samples_from_db_helper(
                                            self, 
                                            samples: hcms.SampleList = None
                                           ):
        """pulls the newest sample data from the db,
        only of global_label is not none, else sample is a ref sample"""
        if samples is None:
            samples = hcms.SampleList()

        if isinstance(samples, dict):
            samples = hcms.SampleList(**samples)
        ret_sample = hcms.SampleList()
        for sample in samples.samples:
            if sample is None:
                continue
            if sample.global_label is not None:
                new_samples = await self.unified_db.get_sample(hcms.SampleList(samples=[sample]))
                for new_sample in new_samples.samples:
                    ret_sample.samples.append(new_sample)
            else:
                self.base.print_message(f"Bug found: reference sample was saved in pck file: {sample}", error = True)
                ret_sample.samples.append(sample)

        return ret_sample


    async def tray_unload(
                          self,
                          tray: int = None, 
                          slot: int = None,
                          *args, **kwargs
                         ):
        samples = hcms.SampleList()
        unloaded = False
        tray_dict = dict()

        if tray in self.trays:
            if self.trays[tray] is not None:
                if slot in self.trays[tray]:
                    if self.trays[tray][slot] is not None:
                        unloaded = True
                        tray_dict[tray] = dict()
                        tray_dict[tray].update({slot:self.trays[tray][slot].as_dict()})
                        samples = self.trays[tray][slot].unload()
        self.write_config() # save current state of table
        sample_in, sample_out = await self.unpack_samples(samples = samples)
        return unloaded, sample_in, sample_out, tray_dict


    async def tray_unloadall(self, *args, **kwargs):
        tray_dict = dict()#copy.deepcopy(self.trays)
        samples = hcms.SampleList()
        for tray_key, tray_item in self.trays.items():
            if tray_item is not None:
                for slot_key, slot_item in tray_item.items():
                    if slot_item is not None:
                        # first get content as dict
                        tray_dict[tray_key] = dict()
                        tray_dict[tray_key].update({slot_key:slot_item.as_dict()})
                        # then unload (which resets the slot)
                        _samples = slot_item.unload()
                        for sample in _samples.samples:
                            samples.samples.append(sample)
                    
        self.write_config() # save current state of table
        sample_in, sample_out = await self.unpack_samples(samples = samples)
        return True, sample_in, sample_out, tray_dict

    
    
    async def tray_export_json(
                               self, 
                               tray: int = None,
                               slot: int = None,
                               *args,**kwargs
                              ):
        self.write_config()

        if tray in self.trays:
            if self.trays[tray] is not None:
                if slot in self.trays[tray]:
                    if self.trays[tray][slot] is not None:
                        return self.trays[tray][slot].as_dict()

    
    async def tray_export_csv(
                              self,
                              tray: int = None,
                              slot: int = None,
                              myactive = None
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

                            label = "None"
                            vol = 0.0
                            if len(self.trays[tray][slot].sample[i].samples) == 1:
                                label = self.trays[tray][slot].sample[i].samples[0].get_global_label()
                                vol = self.trays[tray][slot].sample[i].samples[0].get_vol_ml()

                            tmp_output_str += ",".join(
                                [
                                    str(i + 1),
                                    str(label),
                                    str(vol),
                                ]
                            )


                await myactive.write_file(
                    file_type = "pal_vialtable_file",
                    filename = f"VialTable__tray{tray}__slot{slot}__{datetime.now().strftime('%Y%m%d.%H%M%S%f')}.csv",
                    output_str = tmp_output_str,
                    header = ",".join(["vial_no", "global_sample_label", "vol_ml"]),
                    sample_str = None
                    )


    async def tray_export_icpms(self, 
                                tray: int = None, 
                                slot: int = None, 
                                myactive = None, 
                                survey_runs: int = None,
                                main_runs: int = None,
                                rack: int = None,
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
                            if vial is True \
                            and len(self.trays[tray][slot].sample[i].samples) == 1:

                                if dilution_factor is None:
                                    temp_dilution_factor = \
                                    self.trays[tray][slot].sample[i].samples[0].get_dilution_factor()
                                tmp_output_str += ";".join(
                                    [
                                        str(
                                            self.trays[tray][slot]
                                            .sample[i].samples[0].get_global_label()
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
                
                
    async def tray_query_sample(
                                self, 
                                tray: int = None, 
                                slot: int = None, 
                                vial: int = None
                               ):
        vial -= 1
        sample = hcms.SampleList()
        error = error_codes.not_available


        if tray in self.trays:
            if self.trays[tray] is not None:
                if slot in self.trays[tray]:
                    if self.trays[tray][slot] is not None:
                        error = error_codes.none
                        if self.trays[tray][slot].vials[vial] is not False:
                            sample = copy.deepcopy(self.trays[tray][slot].sample[vial])
                            

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
            
            
            for tray_no in sorted(self.trays):
                if self.trays[tray_no] is not None:
                    for slot_no in sorted(self.trays[tray_no]):
                        if self.trays[tray_no][slot_no] is not None:
                            if (
                                self.trays[tray_no][slot_no].max_vol_ml >= req_vol
                                and new_vial_vol > self.trays[tray_no][slot_no].max_vol_ml
                            ):
                                position = self.trays[tray_no][slot_no].first_empty()
                                if position is not None:
                                    new_tray = tray_no
                                    new_slot = slot_no
                                    new_vial = position + 1
                                    new_vial_vol = self.trays[tray_no][slot_no].max_vol_ml
                                    self.trays[tray_no][slot_no].blocked[position] = True
    
            self.base.print_message(f" ... new vial nr. {new_vial} in slot {new_slot} in tray {new_tray}")
            return {"tray": new_tray, "slot": new_slot, "vial": new_vial}


    async def tray_get_next_full(self, 
                                 after_tray: int = None, 
                                 after_slot: int = None, 
                                 after_vial: int = None
                                ):

        """Finds the next full vial after the current vial position
        defined in micropal."""
        if after_tray is None:
            after_tray = -1
        if after_slot is None:
            after_slot = -1
        if after_vial is None:
            after_vial = -1
            
        new_tray = None
        new_slot = None
        new_vial = None
        after_vial -= 1;
        for tray_no in sorted(self.trays):
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
                                   tray: int = None, 
                                   slot: int = None, 
                                   vial: int = None, 
                                   sample: hcms.SampleList = None,
                                   dilute: bool = False,
                                   *args,**kwargs
                                  ):
        if sample is None:
            sample = hcms.SampleList()

        if isinstance(sample, dict):
            sample = hcms.SampleList(**sample)
        
        if not sample.samples:
            return False

        if len(sample.samples) > 1:
            print_message({}, "archive", "tray_update_position: sample_list contains more than one sample. Only using first one.", error = True)
            sample = hcms.SampleList(samples = [sample.samples[0]])

        vial -= 1
        if tray in self.trays:
            if self.trays[tray] is not None:
                if slot in self.trays[tray]:
                    if self.trays[tray][slot] is not None:
                        self.trays[tray][slot].vials[vial] = True
                        self.trays[tray][slot].sample[vial] = sample
                        # backup file
                        self.write_config()
                        return True

        return False


    def custom_assembly_allowed(self, custom: str = None):
        if custom in self.custom_positions:
            return self.custom_positions[custom].assembly_allowed()
        else:
            return False


    def custom_dest_allowed(self, custom: str = None):
        if custom in self.custom_positions:
            return self.custom_positions[custom].dest_allowed()
        else:
            return False


    def custom_dilution_allowed(self, custom: str = None):
        if custom in self.custom_positions:
            return self.custom_positions[custom].dilution_allowed()
        else:
            return False


    async def custom_query_sample(self,custom: str = None, *args, **kwargs):
        sample = hcms.SampleList()
        error = error_codes.none
        
        if custom in self.custom_positions:
            sample = copy.deepcopy(self.custom_positions[custom].sample)
        else:
            error = error_codes.not_available

        return error, sample


    async def custom_update_position(
                                     self,
                                     custom: str = None,
                                     sample: hcms.SampleList = None,
                                     dilute: bool = False,
                                     *args,**kwargs
                                    ):
        if sample is None:
            sample = hcms.SampleList()

        if len(sample.samples) > 1:
            print_message({}, "archive", "custom_update_position: sample_list contains more than one sample. Only using first one.", error = True)
            sample = hcms.SampleList(samples = [sample.samples[0]])


        if custom in self.custom_positions:
            if len(sample.samples) > 1:
                return False, hcms.SampleList()
            if sample.samples[0].sample_type == "assembly" \
            and not self.custom_positions[custom].assembly_allowed():
                return False, hcms.SampleList()

            self.custom_positions[custom].sample = copy.deepcopy(sample)
            self.write_config()

        return True, sample
    

    async def customs_to_dict(self):
        customdict = copy.deepcopy(self.custom_positions)
        for custom_key in customdict:
            customdict[custom_key] = customdict[custom_key].as_dict()
        return customdict

    
    async def custom_unloadall(self, *args, **kwargs):
        samples = hcms.SampleList()
        customs_dict = await self.customs_to_dict()
        for custom in self.custom_positions:
            _samples = self.custom_positions[custom].unload()
            for sample in _samples.samples:
                samples.samples.append(sample)
        
        self.write_config() # save current state of table
        sample_in, sample_out = await self.unpack_samples(samples = samples)
        return True, sample_in, sample_out, customs_dict


    async def custom_unload(self, custom: str = None, *args, **kwargs):
        sample = hcms.SampleList()
        unloaded = False
        customs_dict = dict()
        if custom in self.custom_positions:
            customs_dict = self.custom_positions[custom].as_dict()
            sample = self.custom_positions[custom].unload()
            unloaded = True
        
        self.write_config() # save current state of table
        sample_in, sample_out = await self.unpack_samples(samples = sample)
        return unloaded, sample_in, sample_out, customs_dict


    async def custom_load(
                          self,
                          custom: str = None,
                          load_samples_in: hcms.SampleList = None,
                          *args, **kwargs
                         ):

        if load_samples_in is None:
            load_samples_in = hcms.SampleList()

        sample = hcms.SampleList()
        loaded = False
        customs_dict = dict()

        if isinstance(load_samples_in, dict):
            load_samples_in = hcms.SampleList(**load_samples_in)

        if not load_samples_in.samples:
            return False, hcms.SampleList(), dict()
            
        # check if sample actually exists
        load_samples_in = await self.unified_db.get_sample(load_samples_in)
        if load_samples_in.samples[0] is None:
            print_message({}, "archive", "Sample does not exist in DB.", error = True)
            return False, hcms.SampleList(), dict()


        if len(load_samples_in.samples) > 1:
            self.base.print_message("custom_load: sample is empty", error = True)
            loaded = False
        else:
            if custom in self.custom_positions:
                loaded, sample = \
                self.custom_positions[custom].load(load_samples_in)
                customs_dict = self.custom_positions[custom].as_dict()

        self.write_config() # save current state of table
        return loaded, sample, customs_dict


    async def unpack_samples(self, samples: hcms.SampleList = None):
        if samples is None:
            samples = hcms.SampleList()

        ret_samples_in = hcms.SampleList()
        ret_samples_out = hcms.SampleList()
        for sample in samples.samples:
            if isinstance(sample, hcms.AssemblySample):
                sample.inheritance = "allow_both"
                sample.status = "destroyed"
                ret_samples_in.samples.append(sample)
                for part in sample.parts:
                    part.inheritance = "allow_both"
                    part.status = "recovered"
                    ret_samples_out.samples.append(part)
            else:
                sample.inheritance = "allow_both"
                sample.status = "preserved"
                ret_samples_in.samples.append(sample)
        return ret_samples_in, ret_samples_out
