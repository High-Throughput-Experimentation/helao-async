"""Archive class handles local sample DB and legacy DB lookup

    TODO:
    1. consolidate tray_export_json, tray_export_csv, tray_export_icpms, and make 
    tray_unloadall call the export function
    2. write tray_import function to consume exported json or csv and ingest into local
    sqlite database, import needs to check for existing global_sample_labels

"""

__all__ = [
    "Archive",
]

import asyncio
import os
from datetime import datetime
from copy import deepcopy
from typing import List, Tuple, Union
import traceback

from socket import gethostname
import re
from enum import Enum
import json


from helao.servers.base import Base, Active
from helaocore.error import ErrorCodes

from helaocore.models.sample import (
    SampleType,
    SampleUnion,
    LiquidSample,
    GasSample,
    SolidSample,
    AssemblySample,
    NoneSample,
    SampleStatus,
    SampleInheritance,
    object_to_sample,
)
from helao.helpers.sample_positions import (
    Custom,
    VT54,
    VT70,
    VT15,
    Positions,
)


from helao.helpers.print_message import print_message
from helao.helpers.unpack_samples import unpack_samples_helper

from helao.helpers.sample_api import UnifiedSampleDataAPI
from helao.helpers.premodels import Action
from helao.helpers.update_sample_vol import update_vol

from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(logger_name="archive_driver_standalone")
else:
    LOGGER = logging.LOGGER

class ScanDirection(str, Enum):
    raster_rows = "raster_rows"
    raster_columns = "raster_columns"
    left_to_right = "left_to_right"
    top_to_bottom = "top_to_bottom"


class ScanOperator(str, Enum):
    so_gt = "gt"
    so_gte = "gte"
    so_lt = "lt"
    so_lte = "lte"
    so_not = "not"  # cannot have not, thats why I added so_ to each


class Archive:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg

        self.unified_db = UnifiedSampleDataAPI(self.base)
        asyncio.gather(self.unified_db.init_db())

        self.position_config = self.config_dict.get("positions", None)
        self.archivejson = None
        if self.base.helaodirs.states_root is not None:
            self.archivejson = os.path.join(
                self.base.helaodirs.states_root,
                f"{gethostname().lower()}_{self.base.server.server_name}_archive.json",
            )
        self.config = {}

        # configure the tray
        self.positions = Positions()

        # get some empty db dicts from default config

        self.startup_positions = self.action_startup_config()
        self.base.print_message(
            f"Config trays_dict has {len(self.startup_positions.trays_dict)} keys"
        )
        # compare default config to backup

        try:
            self.positions = self.load_config()
            self.base.print_message(
                f"Archive json has {len(self.positions.trays_dict)} keys"
            )
        except IOError:
            self.base.print_message(
                f"'{self.archivejson}' does not exist, writing empty global dict.",
                error=True,
            )
            self.write_config()
        # except Exception:
        # print_message(LOGGER, "launcher", f"Error loading '{pidFile}', writing empty global dict.", error = True)
        # self.write_config()

        # check trays
        failed = False
        if len(self.positions.trays_dict) == len(self.startup_positions.trays_dict):
            for i, tray in self.positions.trays_dict.items():
                if i not in self.startup_positions.trays_dict:
                    self.base.print_message(
                        f"tray key {i} from archive.json does not match config"
                    )
                    failed = True
                    break
                else:
                    if len(tray) == len(self.startup_positions.trays_dict[i]):
                        for slot in tray:
                            if slot not in self.startup_positions.trays_dict[i]:
                                self.base.print_message("slot not present", error=True)
                                failed = True
                                break
                            else:
                                if not isinstance(
                                    tray[slot],
                                    type(self.startup_positions.trays_dict[i][slot]),
                                ):
                                    self.base.print_message(
                                        "not the same slot type", error=True
                                    )
                                    failed = True
                                    break

                    else:
                        self.base.print_message(
                            "tray has not the same length", error=True
                        )
                        failed = True
                        break
        else:
            self.base.print_message("not the same length", error=True)
            failed = True

        if failed:
            self.base.print_message("trays did not match", error=True)
            self.positions.trays_dict = deepcopy(self.startup_positions.trays_dict)
        else:
            self.base.print_message("trays matched", info=True)

        # check custom positions
        failed = False
        if len(self.positions.customs_dict) == len(self.startup_positions.customs_dict):
            for key, val in self.positions.customs_dict.items():
                if key not in self.startup_positions.customs_dict:
                    failed = True
                    break
                else:
                    if not isinstance(
                        val, type(self.startup_positions.customs_dict[key])
                    ):
                        failed = True
                        break
        else:
            failed = True

        if failed:
            self.base.print_message("customs did not match", error=True)
            self.positions.customs_dict = deepcopy(self.startup_positions.customs_dict)
        else:
            self.base.print_message("customs matched", info=True)
            # update all samples in tray and custom positions
            self.write_config()
            asyncio.gather(self.update_samples_from_db())

    def action_startup_config(self):
        positions = Positions()
        # custom_positions = {}
        # trays_dict = {}

        pattern = re.compile("([a-zA-Z]+)([0-9]+)")
        if self.position_config is not None:
            self.base.print_message("Loading positions defined in config.", info=True)
            for key, val in self.position_config.items():
                key = key.lower()
                test = pattern.match(key)
                if test is None:
                    if key == "custom":
                        self.base.print_message(
                            "Custom position defined in config.", info=True
                        )
                        for custom_name, custom_type in val.items():
                            positions.customs_dict.update(
                                {
                                    custom_name: Custom(
                                        custom_name=custom_name, custom_type=custom_type
                                    )
                                }
                            )

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
                                    self.base.print_message(
                                        f"unknown slot item '{slot}'", error=True
                                    )
                                    continue

                                if slot_no is not None:
                                    if tmpi not in positions.trays_dict:
                                        positions.trays_dict[tmpi] = {}

                                    if slot_item is not None:
                                        self.base.print_message(f"got {slot_item}")
                                        if slot_item == "VT54":
                                            positions.trays_dict[tmpi][slot_no] = VT54()
                                        elif slot_item == "VT15":
                                            positions.trays_dict[tmpi][slot_no] = VT15()
                                        elif slot_item == "VT70":
                                            positions.trays_dict[tmpi][slot_no] = VT70()

                                        else:
                                            self.base.print_message(
                                                f"slot type {slot_item} not supported",
                                                error=True,
                                            )
                                            positions.trays_dict[tmpi][slot_no] = None
                                    else:
                                        positions.trays_dict[tmpi][slot_no] = None
        self.base.print_message(f"trays: {positions.trays_dict}")
        self.base.print_message(f"customs: {positions.customs_dict}")
        return positions  # trays_dict, custom_positions

    def load_config(self):
        if self.archivejson is not None:
            with open(self.archivejson, "r") as f:
                try:
                    data = json.load(f)
                    return Positions(**data)
                except Exception as e:
                    tb = "".join(
                        traceback.format_exception(type(e), e, e.__traceback__)
                    )
                    self.base.print_message(
                        f"error loading {self.archivejson}: {repr(e), tb,}", error=True
                    )
                    return Positions()
        #         data = pickle.load(f)
        #         self.positions.trays_dict = data.get("trays", [])
        #         self.positions.customs_dict = data.get("customs", {})
        # else:
        # self.positions.trays_dict = []
        # self.positions.customs_dict = {}

    def write_config(self):
        if self.archivejson is not None:
            with open(self.archivejson, "w") as f:
                json.dump(self.positions.as_dict(), f)
        # if self.archivejson is not None:
        #     data = {"customs":self.positions.customs_dict, "trays":self.positions.trays_dict}
        #     with open(self.archivejson, "wb") as f:
        #         pickle.dump(data, f)

    async def update_samples_from_db(self):
        self.base.print_message("Updating all samples in position table.", info=True)
        # need to wait for the db to finish initializing
        while not self.unified_db.ready:
            self.base.print_message("db not ready", info=True)
            await asyncio.sleep(0.1)

        # first update all custom position samples
        for custom in self.positions.customs_dict:
            if self.positions.customs_dict[custom].sample is None:
                # can happen sometimes during a crash
                # we want to convert None back to NoneSample()
                self.positions.customs_dict[custom].sample = NoneSample()
                continue

            if self.positions.customs_dict[custom].sample.sample_type is not None:
                self.positions.customs_dict[
                    custom
                ].sample = await self.update_samples_from_db_helper(
                    sample=self.positions.customs_dict[custom].sample
                )

        # second update all tray samples
        for tray_key, tray_item in self.positions.trays_dict.items():
            if tray_item is not None:
                for slot_key, slot_item in tray_item.items():
                    if slot_item is not None:
                        for i, sample in enumerate(slot_item.samples):
                            slot_item.samples[
                                i
                            ] = await self.update_samples_from_db_helper(sample=sample)

        # update all samples in tray and custom positions
        self.write_config()

    async def update_samples_from_db_helper(self, sample: SampleUnion):
        """pulls the newest sample data from the db,
        only of global_label is not none, else sample is a ref sample"""
        if sample.sample_type is not None:
            if sample.global_label is not None:
                _sample = await self.unified_db.get_samples([sample])
                if _sample:
                    sample = _sample[0]
            else:
                self.base.print_message(
                    f"Bug found: reference sample was saved in archive.json file: {sample}",
                    error=True,
                )

        return sample

    async def tray_load(
        self,
        tray: int = None,
        slot: int = None,
        vial: int = None,
        load_sample_in: Union[SampleUnion, dict] = None,
        *args,
        **kwargs,
    ) -> Tuple[ErrorCodes, SampleUnion]:
        vial -= 1
        sample = NoneSample()
        error = ErrorCodes.not_available

        if load_sample_in is None:
            return False, NoneSample(), {}

        print("!!!load_sample_in:", load_sample_in)
        # check if sample actually exists
        load_samples_in = await self.unified_db.get_samples(
            samples=[load_sample_in]
        )

        if not load_samples_in:
            print_message(LOGGER, "archive", "Sample does not exist in DB.", warning=True)
            return error, sample

        position_found = False
        if tray in self.positions.trays_dict:
            if self.positions.trays_dict[tray] is not None:
                if slot in self.positions.trays_dict[tray]:
                    if self.positions.trays_dict[tray][slot] is not None:
                        if (
                            self.positions.trays_dict[tray][slot].vials[vial]
                            is not True
                        ):
                            error = ErrorCodes.none
                            sample = self.positions.trays_dict[tray][slot].load(
                                vial=vial + 1, sample=load_samples_in[0]
                            )
                            position_found = True
        if not position_found:
            print_message(LOGGER, "archive", f"could not find tray {tray}, slot {slot}, vial {vial} in defined positions or set position is already occupied.")   
        
        # update with information from db
        sample = await self._update_samples(sample)
        return error, sample

    async def tray_unload(
        self, tray: int = None, slot: int = None, *args, **kwargs
    ) -> Tuple[bool, List[SampleUnion], List[SampleUnion], dict]:
        samples = []
        unloaded = False
        tray_dict = {}

        if tray in self.positions.trays_dict:
            if self.positions.trays_dict[tray] is not None:
                if slot in self.positions.trays_dict[tray]:
                    if self.positions.trays_dict[tray][slot] is not None:
                        unloaded = True
                        tray_dict[tray] = {}
                        tray_dict[tray].update(
                            {slot: self.positions.trays_dict[tray][slot].as_dict()}
                        )
                        samples = self.positions.trays_dict[tray][slot].unload()
        self.write_config()  # save current state of table

        # update samples with most recent info from db
        for sample in samples:
            sample = await self.update_samples_from_db_helper(sample=sample)
        # unpack samples, this also sets the status
        samples_in, samples_out = await self._unload_unpack_samples_helper(samples)
        samples_in = self.append_sample_status(
            samples=samples_in, newstatus=SampleStatus.unloaded
        )
        samples_out = self.append_sample_status(
            samples=samples_out, newstatus=SampleStatus.unloaded
        )
        # now write all samples back to the db
        # update all sample in the db
        await self.unified_db.update_samples(samples=samples_in)
        await self.unified_db.update_samples(samples=samples_out)
        return unloaded, samples_in, samples_out, tray_dict

    async def tray_unloadall(
        self, *args, **kwargs
    ) -> Tuple[bool, List[SampleUnion], List[SampleUnion], dict]:
        tray_dict = {}
        samples = []
        for tray_key, tray_item in self.positions.trays_dict.items():
            if tray_item is not None:
                for slot_key, slot_item in tray_item.items():
                    if slot_item is not None:
                        # first get content as dict
                        if tray_key not in tray_dict:
                            tray_dict[tray_key] = {}
                        tray_dict[tray_key].update(
                            {
                                slot_key: self.positions.trays_dict[tray_key][
                                    slot_key
                                ].as_dict()
                            }
                        )
                        # then unload (which resets the slot)
                        _samples = self.positions.trays_dict[tray_key][
                            slot_key
                        ].unload()
                        for sample in _samples:
                            samples.append(sample)

        self.write_config()  # save current state of table

        # update samples with most recent info from db
        for sample in samples:
            sample = await self.update_samples_from_db_helper(sample=sample)
        # unpack samples, this also sets the status
        samples_in, samples_out = await self._unload_unpack_samples_helper(samples)
        samples_in = self.append_sample_status(
            samples=samples_in, newstatus=SampleStatus.unloaded
        )
        samples_out = self.append_sample_status(
            samples=samples_out, newstatus=SampleStatus.unloaded
        )
        # now write all samples back to the db
        # update all sample in the db
        await self.unified_db.update_samples(samples=samples_in)
        await self.unified_db.update_samples(samples=samples_out)
        return True, samples_in, samples_out, tray_dict

    async def tray_export_json(
        self, tray: int = None, slot: int = None, *args, **kwargs
    ):
        self.write_config()

        if tray in self.positions.trays_dict:
            if self.positions.trays_dict[tray] is not None:
                if slot in self.positions.trays_dict[tray]:
                    if self.positions.trays_dict[tray][slot] is not None:
                        return self.positions.trays_dict[tray][slot].as_dict()

    async def tray_export_csv(self, tray: int = None, slot: int = None, myactive=None):
        self.write_config()  # save backup

        if tray in self.positions.trays_dict:
            if self.positions.trays_dict[tray] is not None:
                if slot in self.positions.trays_dict[tray]:
                    if self.positions.trays_dict[tray][slot] is not None:
                        tmp_output_str = ""
                        for i, vial in enumerate(
                            self.positions.trays_dict[tray][slot].vials
                        ):
                            if tmp_output_str != "":
                                tmp_output_str += "\n"

                            label = (
                                self.positions.trays_dict[tray][slot]
                                .samples[i]
                                .get_global_label()
                            )
                            vol = (
                                self.positions.trays_dict[tray][slot]
                                .samples[i]
                                .get_vol_ml()
                            )

                            tmp_output_str += ",".join(
                                [
                                    str(i + 1),
                                    str(label),
                                    str(vol),
                                ]
                            )

                await myactive.write_file(
                    file_type="pal_vialtable_file",
                    filename=f"VialTable__tray{tray}__slot{slot}__{datetime.now().strftime('%Y%m%d.%H%M%S%f')}.csv",
                    output_str=tmp_output_str,
                    header=",".join(["vial_no", "global_sample_label", "vol_ml"]),
                    sample_str=None,
                )

    async def tray_export_icpms(
        self,
        tray: int = None,
        slot: int = None,
        myactive: Active = None,
        survey_runs: int = None,
        main_runs: int = None,
        rack: int = None,
        dilution_factor: float = None,
    ):
        self.write_config()  # save backup

        trayobj = self.positions.trays_dict.get(tray, {})
        tmp_output_str = ""
        samplelist = []

        if slot in trayobj.keys():
            slotobj = trayobj[slot]
            vials = slotobj.vials

            sampletups = [
                (i, slotobj.samples[i])
                for i, v in enumerate(vials)
                if v and slotobj.samples[i] != NoneSample()
            ]
            tmp_output_str = "\n".join(
                [
                    ";".join(
                        [
                            f"{x}"
                            for x in [
                                v.get_global_label(),
                                survey_runs,
                                main_runs,
                                rack,
                                i + 1,
                                dilution_factor
                                if dilution_factor is not None
                                else v.get_dilution_factor(),
                            ]
                        ]
                    )
                    for i, v in sampletups
                ]
            )

            samplelist = [v for _, v in sampletups]
            self.base.print_message(
                f"Found {len(samplelist)} vials on tray {tray}, slot {slot}. Exporting csv."
            )

            headerline = ";".join(
                [
                    "liquid_sample_no",
                    "Survey Runs",
                    "Main Runs",
                    "Rack",
                    "Vial",
                    "Dilution Factor",
                ]
            )
            csv_filename = f"VialTable__tray{tray}__slot{slot}__{datetime.now().strftime('%Y%m%d-%H%M%S%f')}_ICPMS.csv"
            csv_dir = os.path.join(
                self.base.helaodirs.save_root.__str__(),
                myactive.action.get_action_dir(),
            )
            csv_path = os.path.join(csv_dir, csv_filename)
            with open(csv_path, "w") as f:
                f.write("\n".join([headerline, tmp_output_str]))

            await myactive.track_file(
                file_type="pal_icpms_file", file_path=csv_path, samples=samplelist
            )
        else:
            self.base.print_message(
                f"Slot {slot} not found in positions dict. Cannot export."
            )

    async def tray_query_sample(
        self, tray: int = None, slot: int = None, vial: int = None
    ) -> Tuple[ErrorCodes, SampleUnion]:
        vial -= 1
        sample = NoneSample()
        error = ErrorCodes.not_available

        if tray in self.positions.trays_dict:
            if self.positions.trays_dict[tray] is not None:
                if slot in self.positions.trays_dict[tray]:
                    if self.positions.trays_dict[tray][slot] is not None:
                        error = ErrorCodes.none
                        if (
                            self.positions.trays_dict[tray][slot].vials[vial]
                            is not False
                        ):
                            sample = deepcopy(
                                self.positions.trays_dict[tray][slot].samples[vial]
                            )

        sample = await self._update_samples(sample)
        return error, sample

    async def tray_new_position(self, req_vol: float = 2.0, *args, **kwargs):
        """Returns an empty vial position for given max volume.
        For mixed vial sizes the req_vol helps to choose the proper vial for sample volume.
        It will select the first empty vial which has the smallest volume that still can hold req_vol
        """

        await asyncio.sleep(0.01)
        lock = asyncio.Lock()
        async with lock:
            self.base.print_message(self.positions.trays_dict)
            new_tray = None
            new_slot = None
            new_vial = None
            new_vial_vol = float("inf")

            for tray_no in sorted(self.positions.trays_dict):
                if self.positions.trays_dict[tray_no] is not None:
                    for slot_no in sorted(self.positions.trays_dict[tray_no]):
                        if self.positions.trays_dict[tray_no][slot_no] is not None:
                            if (
                                self.positions.trays_dict[tray_no][slot_no].max_vol_ml
                                >= req_vol
                                and new_vial_vol
                                > self.positions.trays_dict[tray_no][slot_no].max_vol_ml
                            ):
                                position = self.positions.trays_dict[tray_no][
                                    slot_no
                                ].first_empty()
                                if position is not None:
                                    new_tray = tray_no
                                    new_slot = slot_no
                                    new_vial = position + 1
                                    new_vial_vol = self.positions.trays_dict[tray_no][
                                        slot_no
                                    ].max_vol_ml
                                    self.positions.trays_dict[tray_no][slot_no].blocked[
                                        position
                                    ] = True

            self.base.print_message(
                f"new vial nr. {new_vial} in slot {new_slot} in tray {new_tray}"
            )
            return {"tray": new_tray, "slot": new_slot, "vial": new_vial}

    async def tray_get_next_full(
        self, after_tray: int = None, after_slot: int = None, after_vial: int = None
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
        after_vial -= 1
        for tray_no in sorted(self.positions.trays_dict):
            if self.positions.trays_dict[tray_no] is not None:
                if tray_no < after_tray:
                    continue
                else:
                    for slot_no in sorted(self.positions.trays_dict[tray_no]):
                        if self.positions.trays_dict[tray_no][slot_no] is not None:
                            if tray_no <= after_tray and slot_no < after_slot:
                                continue
                            else:
                                for vial_no, vial in enumerate(
                                    self.positions.trays_dict[tray_no][slot_no].vials
                                ):
                                    if vial is not None:
                                        if (
                                            tray_no <= after_tray
                                            and slot_no <= after_slot
                                            and vial_no <= after_vial
                                        ):
                                            continue
                                        else:
                                            if vial[vial_no]:
                                                new_tray = tray_no
                                                new_slot = slot_no
                                                new_vial = (
                                                    vial_no + 1
                                                )  # starts at 0 in []
                                                break

        return {"tray": new_tray, "slot": new_slot, "vial": new_vial}

    async def tray_update_position(
        self,
        tray: int = None,
        slot: int = None,
        vial: int = None,
        sample: SampleUnion = None,
        dilute: bool = False,
        *args,
        **kwargs,
    ):
        if sample is None:
            return False

        vial -= 1
        if tray in self.positions.trays_dict:
            if self.positions.trays_dict[tray] is not None:
                if slot in self.positions.trays_dict[tray]:
                    if self.positions.trays_dict[tray][slot] is not None:
                        self.positions.trays_dict[tray][slot].vials[vial] = True
                        self.positions.trays_dict[tray][slot].samples[vial] = deepcopy(
                            sample
                        )
                        # backup file
                        self.write_config()
                        return True

        return False

    def custom_is_destroyed(self, custom: str = None) -> bool:
        """checks if the custom position is a waste, injector
        and similar position which fully comsumes and destroyes a
        sample if selected as a destination"""

        if custom in self.positions.customs_dict:
            return self.positions.customs_dict[custom].is_destroyed()
        else:
            return False

    def custom_assembly_allowed(self, custom: str = None):
        if custom in self.positions.customs_dict:
            return self.positions.customs_dict[custom].assembly_allowed()
        else:
            return False

    def custom_dest_allowed(self, custom: str = None):
        if custom in self.positions.customs_dict:
            return self.positions.customs_dict[custom].dest_allowed()
        else:
            return False

    def custom_dilution_allowed(self, custom: str = None):
        if custom in self.positions.customs_dict:
            return self.positions.customs_dict[custom].dilution_allowed()
        else:
            return False

    async def custom_query_sample(
        self, custom: str = None, *args, **kwargs
    ) -> Tuple[ErrorCodes, SampleUnion]:
        sample = NoneSample()
        error = ErrorCodes.none

        if custom in self.positions.customs_dict:
            sample = deepcopy(self.positions.customs_dict[custom].sample)
        else:
            error = ErrorCodes.not_available

        sample = await self._update_samples(sample)
        return error, sample

    async def custom_replace_sample(
        self, custom: str = None, sample: SampleUnion = None
    ) -> Tuple[bool, SampleUnion]:
        if sample is None:
            return False, NoneSample()
        sample = object_to_sample(sample)

        if custom in self.positions.customs_dict:
            if (
                sample.sample_type == SampleType.assembly
                and not self.positions.customs_dict[custom].assembly_allowed()
            ):
                return False, NoneSample()

            if SampleStatus.destroyed in sample.status:
                # cannot replace with a destroyed sample
                return False, NoneSample()
            else:
                self.positions.customs_dict[custom].sample = deepcopy(sample)

            self.write_config()

        return True, sample

    async def custom_update_position(
        self,
        custom: str = None,
        sample: SampleUnion = None,
        dilute: bool = False,
        *args,
        **kwargs,
    ) -> Tuple[bool, SampleUnion]:
        if sample is None:
            return False, NoneSample()

        sample = object_to_sample(sample)

        if custom in self.positions.customs_dict:
            if (
                sample.sample_type == SampleType.assembly
                and not self.positions.customs_dict[custom].assembly_allowed()
            ):
                return False, NoneSample()

            # check if updated sample has destroyed status
            # and empty position of necessary
            if SampleStatus.destroyed in sample.status:
                _ = self.positions.customs_dict[custom].unload()
            else:
                self.positions.customs_dict[custom].sample = deepcopy(sample)

            self.write_config()

        return True, sample

    def assign_new_sample_status(
        self,
        samples: List[SampleUnion],
        newstatus: List[str],
    ):
        if not isinstance(newstatus, list):
            newstatus = [newstatus]
        for sample in samples:
            sample.status = newstatus
        return samples

    def append_sample_status(
        self,
        samples: List[SampleUnion],
        newstatus,
    ) -> List[SampleUnion]:
        for sample in samples:
            sample.status.append(newstatus)
        return samples

    async def custom_unloadall(
        self,
        destroy_liquid: bool = False,
        destroy_gas: bool = False,
        destroy_solid: bool = False,
        keep_liquid: bool = False,
        keep_solid: bool = False,
        keep_gas: bool = False,
        action: Action = None,
        *args,
        **kwargs,
    ) -> Tuple[bool, List[SampleUnion], List[SampleUnion], dict]:
        samples_in = []
        samples_out = []

        customs_dict = {}
        for custom in self.positions.customs_dict:
            (
                unloaded,
                tmp_samples_in,
                tmp_samples_out,
                tmp_customs_dict,
            ) = await self.custom_unload(
                custom=custom,
                destroy_liquid=destroy_liquid,
                destroy_gas=destroy_gas,
                destroy_solid=destroy_solid,
                keep_liquid=keep_liquid,
                keep_solid=keep_solid,
                keep_gas=keep_gas,
                action=action,
            )

            for sample in tmp_samples_in:
                samples_in.append(sample)
            for sample in tmp_samples_out:
                samples_out.append(sample)
            customs_dict.update(tmp_customs_dict)

        # save current state of table
        self.write_config()

        return True, samples_in, samples_out, customs_dict

    async def custom_unload(
        self,
        custom: str = None,
        destroy_liquid: bool = False,
        destroy_gas: bool = False,
        destroy_solid: bool = False,
        keep_liquid: bool = False,
        keep_solid: bool = False,
        keep_gas: bool = False,
        action: Action = None,
        *args,
        **kwargs,
    ) -> Tuple[bool, List[SampleUnion], List[SampleUnion], dict]:
        samples = []
        unloaded = False
        customs_dict = {}
        if custom in self.positions.customs_dict:
            customs_dict.update({custom: self.positions.customs_dict[custom].as_dict()})
            samples.append(self.positions.customs_dict[custom].unload())
            unloaded = True

        # save current state of table
        self.write_config()
        # unpack samples and check which to keep
        liquids, solids, gases = unpack_samples_helper(samples=samples)
        keep_samples = []
        if keep_liquid:
            destroy_liquid = False
            for liquid in liquids:
                keep_samples.append(liquid)
        if keep_solid:
            destroy_solid = False
            for solid in solids:
                keep_samples.append(solid)
        if keep_gas:
            destroy_gas = False
            for gas in gases:
                keep_samples.append(gas)

        samples_in, samples_out = await self._unload_custom_helper(
            samples=samples,
            destroy_liquid=destroy_liquid,
            destroy_gas=destroy_gas,
            destroy_solid=destroy_solid,
        )

        # we keep at least one sample
        if keep_samples:
            self.base.print_message(
                f"trying to keep samples: "
                f"{[s.get_global_label() for s in keep_samples]}",
                info=True,
            )
            tmp_sample = None
            tmp_loaded = False
            if len(keep_samples) == 1:
                tmp_loaded, tmp_sample, tmp_customs_dict = await self.custom_load(
                    custom=custom, load_sample_in=keep_samples[0]
                )
            else:
                # we need to combine it as an assembly
                error, ref_samples = await self.new_ref_samples(
                    samples_in=keep_samples,
                    sample_out_type=SampleType.assembly,
                    sample_position=custom,
                    action=action,
                )
                if error != ErrorCodes.none:
                    self.base.print_message(
                        "no action provided to generate "
                        "assembly in order to keep samples",
                        error=True,
                    )
                else:
                    new_samples = await self.create_samples(
                        reference_samples_in=ref_samples,
                        action=action,
                    )
                    if new_samples:
                        (
                            tmp_loaded,
                            tmp_sample,
                            tmp_customs_dict,
                        ) = await self.custom_load(
                            custom=custom, load_sample_in=new_samples[0]
                        )
                        if tmp_loaded:
                            tmp_sample.status.append(SampleStatus.created)
                    else:
                        self.base.print_message(
                            "could not convert reference"
                            "to real sample during "
                            "custom_unload",
                            error=True,
                        )
            # if a new sample has been loaded, add it to samples_out
            if tmp_loaded and tmp_sample is not None:
                samples_out.append(tmp_sample)

        return unloaded, samples_in, samples_out, customs_dict

    async def _unload_custom_helper(
        self,
        samples: List[SampleUnion] = None,
        destroy_liquid: bool = False,
        destroy_gas: bool = False,
        destroy_solid: bool = False,
    ) -> Tuple[List[SampleUnion], List[SampleUnion]]:
        # update samlpes with most recent info from db
        for sample in samples:
            sample = await self.update_samples_from_db_helper(sample=sample)

        # unpack all assemblies
        # this also sets new status
        samples_in, samples_out = await self._unload_unpack_samples_helper(samples)

        # add unloaded status
        samples_in = self.append_sample_status(
            samples=samples_in, newstatus=SampleStatus.unloaded
        )
        samples_out = self.append_sample_status(
            samples=samples_out, newstatus=SampleStatus.unloaded
        )

        # now write all samples back to the db
        # update all sample in the db
        # (need to write it back as selective_destroy needs it)
        await self.unified_db.update_samples(samples=samples_in)
        await self.unified_db.update_samples(samples=samples_out)

        # now destroy samples if selected
        samples_in = await self.selective_destroy_samples(
            samples=samples_in,
            destroy_liquid=destroy_liquid,
            destroy_gas=destroy_gas,
            destroy_solid=destroy_solid,
        )
        samples_out = await self.selective_destroy_samples(
            samples=samples_out,
            destroy_liquid=destroy_liquid,
            destroy_gas=destroy_gas,
            destroy_solid=destroy_solid,
        )

        return samples_in, samples_out

    async def custom_load(
        self, custom: str = None, load_sample_in: SampleUnion = None, *args, **kwargs
    ):
        sample = NoneSample()
        loaded = False
        customs_dict = {}

        if load_sample_in is None:
            return False, NoneSample(), {}

        # check if sample actually exists
        load_samples_in = await self.unified_db.get_samples(
            samples=[object_to_sample(load_sample_in)]
        )

        if not load_samples_in:
            print_message(LOGGER, "archive", "Sample does not exist in DB.", warning=True)
            return False, NoneSample(), {}

        if custom in self.positions.customs_dict:
            loaded, sample = self.positions.customs_dict[custom].load(
                load_samples_in[0]
            )
            customs_dict = self.positions.customs_dict[custom].as_dict()

        self.write_config()  # save current state of table
        sample.status = [SampleStatus.loaded]
        return loaded, sample, customs_dict

    async def _unload_unpack_samples_helper(
        self, samples: List[SampleUnion] = []
    ) -> Tuple[List[SampleUnion], List[SampleUnion]]:
        ret_samples_in = []
        ret_samples_out = []
        for sample in samples:
            if sample.sample_type == SampleType.assembly:
                sample.inheritance = SampleInheritance.allow_both
                sample.status = [SampleStatus.destroyed]
                ret_samples_in.append(sample)
                for part in sample.parts:
                    if part.sample_type == SampleType.assembly:
                        # recursive unpacking
                        self.base.print_message(
                            "assembly contains an assembly", info=True
                        )
                        (
                            tmp_samples_in,
                            tmp_samples_out,
                        ) = await self._unload_unpack_samples_helper(samples=[part])
                        # all are samples out as they
                        # are not the initial sample in
                        # for sample in tmp_samples_in:
                        #     sample.inheritance = SampleInheritance.allow_both
                        #     sample.status = [SampleStatus.recovered]
                        #     ret_samples_out.append(sample)
                        for sample in tmp_samples_out:
                            sample.inheritance = SampleInheritance.allow_both
                            sample.status = [SampleStatus.recovered]
                            ret_samples_out.append(sample)

                    else:
                        part.inheritance = SampleInheritance.allow_both
                        part.status = [SampleStatus.recovered]
                        ret_samples_out.append(part)
            else:
                sample.inheritance = SampleInheritance.allow_both
                sample.status = [SampleStatus.preserved]
                ret_samples_in.append(sample)

        return ret_samples_in, ret_samples_out

    async def _update_samples(self, sample: SampleUnion) -> SampleUnion:
        tmp_samples = await self.unified_db.get_samples(samples=[sample])
        if tmp_samples:
            return tmp_samples[0]
        else:
            return NoneSample()

    async def _add_listA_to_listB(self, listA, listB) -> list:
        for item in listA:
            listB.append(deepcopy(item))
        return listB

    async def new_ref_samples(
        self,
        samples_in: List[SampleUnion],
        sample_out_type: str = "",
        sample_position: str = "",
        action: Action = None,
        # combine multiple liquids into a new
        # liquid sample
        combine_liquids: bool = False,
    ) -> Tuple[bool, List[SampleUnion]]:
        """volume_ml and sample_position need to be updated after the
        function call by the function calling this."""

        error = ErrorCodes.none
        samples: List[SampleUnion] = []

        if action is None:
            self.base.print_message("no action defined", error=True)
            error = ErrorCodes.critical
            return error, samples

        if not samples_in:
            self.base.print_message("no samples_in to create samples_out", error=True)
            error = ErrorCodes.not_available
            return error, []

        source_chemical = []
        source_partial_molarity = []
        source_supplier = []
        source_lotnumber = []
        for sample in samples_in:
            source_chemical = await self._add_listA_to_listB(
                sample.chemical, source_chemical
            )
            source_partial_molarity = await self._add_listA_to_listB(
                sample.partial_molarity, source_partial_molarity
            )
            source_supplier = await self._add_listA_to_listB(
                sample.supplier, source_supplier
            )
            source_lotnumber = await self._add_listA_to_listB(
                sample.lot_number, source_lotnumber
            )

        source = [sample.get_global_label() for sample in samples_in]
        self.base.print_message(f"source_global_label: '{source}'")
        self.base.print_message(f"source_chemical: {source_chemical}")
        self.base.print_message(f"source_partial_molarity: {source_partial_molarity}")
        self.base.print_message(f"source_supplier: {source_supplier}")
        self.base.print_message(f"source_lotnumber: {source_lotnumber}")

        sample_dict = {
            "action_uuid": [action.action_uuid],
            "sample_creation_action_uuid": action.action_uuid,
            "sample_creation_experiment_uuid": action.experiment_uuid,
            "source": source,
            #     # action_timestamp=action.action_timestamp,
            "chemical": source_chemical,
            "partial_molarity": source_partial_molarity,
            "supplier": source_supplier,
            "lot_number": source_lotnumber,
            "status": [SampleStatus.created],
            "inheritance": SampleInheritance.receive_only,
            "sample_position": sample_position,
        }

        if len(samples_in) == 1:
            if sample_out_type == SampleType.liquid:
                # this is a sample reference, it needs to be added
                # to the db later
                samples.append(LiquidSample(**sample_dict))

            elif sample_out_type == SampleType.gas:
                samples.append(GasSample(**sample_dict))

            elif sample_out_type == SampleType.assembly:
                sample_dict.update({"parts": samples_in})
                samples.append(AssemblySample(**sample_dict))

            else:
                self.base.print_message(
                    f"samples_out type {sample_out_type} is not supported yet.",
                    error=True,
                )
                error = ErrorCodes.not_available

        elif len(samples_in) > 1:
            # we always create an assembly for more than one samples_in
            if (
                all(sample.sample_type == SampleType.liquid for sample in samples_in)
                and combine_liquids
            ):
                self.base.print_message(
                    f"combining liquids '{source}' into new liquid reference",
                    info=True,
                )
                sample_dict.update({"parts": samples_in})
                samples.append(LiquidSample(**sample_dict))

            else:
                sample_dict.update({"parts": samples_in})
                samples.append(AssemblySample(**sample_dict))

        else:
            # this should never happen, else we found a bug
            self.base.print_message("found a BUG in new_ref_samples", error=True)
            error = ErrorCodes.bug

        return error, samples

    async def custom_add_liquid(
        self,
        custom: str = None,
        source_liquid_in: LiquidSample = None,
        volume_ml: float = 0.0,
        combine_liquids: bool = False,
        dilute_liquids: bool = True,
        action: Action = None,
    ) -> Tuple[bool, List[SampleUnion], List[SampleUnion]]:
        """adds new liquid from a 'reservoir' to a custom position"""

        error = ErrorCodes.none
        samples_in = []
        samples_in_initial = []
        samples_out = []

        # (1) check if source_liquid_in is not None
        # and its a valid sample (add it to samples_in list)
        if source_liquid_in is None:
            error = ErrorCodes.no_sample
            return error, [], []
        else:
            # check if source_liquid_in is valid
            # converts source_liquid_in to a list
            source_liquid_in = object_to_sample(source_liquid_in)
            samples_in = await self.unified_db.get_samples(samples=[source_liquid_in])

            if not samples_in:
                self.base.print_message(
                    f"source_liquid_in '{source_liquid_in}' is not in db",
                    error=True,
                )
                error = ErrorCodes.no_sample
                return error, [], []

        if samples_in[0].sample_type != SampleType.liquid:
            self.base.print_message("Not a liquid Sample", error=True)
            return ErrorCodes.not_allowed, [], []

        if samples_in[0].volume_ml < volume_ml:
            self.base.print_message("Not enough volume available", error=True)
            return ErrorCodes.not_available, [], []

        samples_in[0].inheritance = SampleInheritance.give_only
        samples_in[0].status = [SampleStatus.preserved]
        # save a deepcopy of initial state as we will return only initial
        # samples_in and final samples_out
        samples_in_initial.append(deepcopy(samples_in[0]))

        # (2) verify if custom is a valid position
        # and get sample from custom position
        if custom in self.positions.customs_dict:
            custom_sample = deepcopy(self.positions.customs_dict[custom].sample)
            self.base.print_message(f"custom sample in valid position: {custom_sample}")
        else:
            error = ErrorCodes.not_available
            return error, [], []

        # (3) check if sample in custom position is valid
        if custom_sample != NoneSample():
            custom_samples_in = await self.unified_db.get_samples(
                samples=[custom_sample]
            )
            if not custom_samples_in:
                self.base.print_message("invalid sample in custom position", error=True)
                error = ErrorCodes.critical
                return error, [], []
            else:
                custom_sample = custom_samples_in[0]

        self.base.print_message(
            f"sample in custom position '{custom}' is {custom_sample.exp_dict()}"
        )

        # (4) create a new ref sample first for the amount we
        # take from samples_in
        # always sets reference status and inheritance to:
        # status=[SampleStatus.created]
        # inheritance=SampleInheritance.receive_only
        error, ref_samples_out = await self.new_ref_samples(
            # sample check converted source_liquid_in
            # to a list already
            samples_in=samples_in,
            sample_out_type=SampleType.liquid,
            sample_position=custom,
            action=action,
        )

        if error != ErrorCodes.none:
            return error, [], []

        # set the volume to the requested value
        ref_samples_out[0].sample_position = custom
        ref_samples_out[0].volume_ml = volume_ml

        # update volume of samples_in
        # also sets status to destroyed if vol <= 0
        # never dilute reservoir
        update_vol(samples_in[0], delta_vol_ml=-volume_ml, dilute=False)

        # (5) now decide what the new sample should be
        # (5-1) custom is empty --> new sample is ref_samples_out[0]
        # (5-2) we combine liquid from custom with ref_samples_out[0]
        #       and create a new liquid (combine_liquids is True)
        # (5-3) we create an assembly with custom_sample and ref_samples_out[0]

        # (5-1)
        if custom_sample == NoneSample():
            # cannot always convert reference sample to real sample
            # as at last 5-3 not always can do that
            samples_out = await self.unified_db.new_samples(samples=ref_samples_out)
            if not samples_out:
                error = ErrorCodes.no_sample
                return error, [], []

            # replace sample in custom position
            replaced, sample = await self.custom_replace_sample(
                custom=custom, sample=samples_out[0]
            )

            if not replaced:
                self.base.print_message(
                    "could not replace sample with assembly when adding liquid",
                    error=True,
                )
                error = ErrorCodes.critical

        # (5-2)
        # we only can combine samples if dilution for the position is allowed
        # too, e.g. not allowed if custom is a reservoir type position
        elif (
            (custom_sample.sample_type == SampleType.liquid)
            and combine_liquids
            and self.custom_dilution_allowed(custom=custom)
        ):
            # convert the ref samples that gets added to a real sample
            samples_out = await self.unified_db.new_samples(samples=ref_samples_out)
            if not samples_out:
                error = ErrorCodes.no_sample
                return error, [], []

            # set sample status
            custom_sample.inheritance = SampleInheritance.allow_both
            custom_sample.status = [SampleStatus.merged]
            samples_out[0].inheritance = SampleInheritance.allow_both
            samples_out[0].status.append(SampleStatus.merged)

            # add the custom sample to the samples_in
            samples_in.append(custom_sample)
            samples_in_initial.append(deepcopy(custom_sample))

            # create a new ref sample which combines both liquid samples
            error, ref_samples_out2 = await self.new_ref_samples(
                # input for assembly is the custom sample
                # and the new sample from source_liquid_in
                samples_in=[custom_sample, samples_out[0]],
                sample_out_type=SampleType.assembly,
                sample_position=custom,
                action=action,
                combine_liquids=combine_liquids,
            )

            ref_samples_out2[0].sample_position = custom
            ref_samples_out2[0].volume_ml = custom_sample.volume_ml
            ref_samples_out2[0].dilution_factor = custom_sample.dilution_factor
            update_vol(
                ref_samples_out2[0],
                delta_vol_ml=samples_out[0].volume_ml,
                dilute=dilute_liquids,
            )

            # a reference assembly was successfully created
            # convert it now to a real sample
            samples_out2 = await self.unified_db.new_samples(samples=ref_samples_out2)

            if not samples_out2:
                # reference could not be converted to a real sample
                self.base.print_message(
                    "could not convert reference assembly to real assembly",
                    error=True,
                )
                return ErrorCodes.critical, [], []

            # add new reference to samples out list
            samples_out.append(samples_out2[0])
            # and update the custom position with the new sample

            replaced, sample = await self.custom_replace_sample(
                custom=custom, sample=samples_out2[0]
            )
            if not replaced:
                self.base.print_message(
                    "could not replace sample with assembly when adding liquid",
                    error=True,
                )
                return ErrorCodes.critical, [], []

        # (5-2b) liquid + assembly case
        elif (
            (custom_sample.sample_type == SampleType.assembly)
            and combine_liquids
            and self.custom_assembly_allowed(custom=custom)
        ):
            # convert the ref samples that gets added to a real sample
            # this next line populates local sqlite dbs with new liquid sample, should
            # be the liquid created from new liquid_in + existing assembly liquid
            samples_out = await self.unified_db.new_samples(samples=ref_samples_out)
            if not samples_out:
                error = ErrorCodes.no_sample
                return error, [], []

            # seprate assembly into solid and liquid parts
            loaded_liquid = [
                p for p in custom_sample.parts if p.sample_type == SampleType.liquid
            ]
            loaded_solid = [
                p for p in custom_sample.parts if p.sample_type == SampleType.solid
            ]
            loaded_gas = [
                p for p in custom_sample.parts if p.sample_type == SampleType.gas
            ]

            new_assembly_parts = []

            self.base.print_message("recovering parts from assembly")
            if loaded_liquid:
                # create a new liquid mixture
                error, new_liquid_mixture = await self.new_ref_samples(
                    samples_in=[loaded_liquid[0], samples_out[0]],
                    sample_out_type=SampleType.assembly,
                    sample_position=custom,
                    action=action,
                    combine_liquids=combine_liquids,
                )
                new_liquid_mixture[0].status.append(SampleStatus.merged)
                # calculate volumes, dilutions
                new_liquid_mixture[0].sample_position = custom
                new_liquid_mixture[0].volume_ml = loaded_liquid[0].volume_ml
                new_liquid_mixture[0].dilution_factor = loaded_liquid[0].dilution_factor
                update_vol(
                    new_liquid_mixture[0],
                    delta_vol_ml=samples_out[0].volume_ml,
                    dilute=dilute_liquids,
                )
                liquid_samples_out = await self.unified_db.new_samples(
                    samples=new_liquid_mixture
                )
                new_assembly_parts.append(liquid_samples_out[0])
                # set inheritance and status for sample transfered out of source_liquid_in
                samples_out[0].inheritance = SampleInheritance.allow_both
                samples_out[0].status.append(SampleStatus.merged)
                self.base.print_message("liquid recovered")
            if loaded_solid:
                new_assembly_parts.append(loaded_solid[0])
                self.base.print_message("solid recovered")
            if loaded_gas:
                new_assembly_parts.append(loaded_gas[0])
                self.base.print_message("gas recovered")

            # old assembly, mark as incorporated
            custom_sample.status = [SampleStatus.recovered]
            self.base.print_message("old assembly status set to recovered")

            # add the old assembly to the samples_in which already contains source_liquid_in
            samples_in.append(custom_sample)
            samples_in_initial.append(deepcopy(custom_sample))

            self.base.print_message("creating new assembly reference")
            # create a new ref sample for new assembly
            error, ref_samples_out2 = await self.new_ref_samples(
                # input for assembly is the custom sample
                # and the new sample from source_liquid_in
                samples_in=new_assembly_parts,
                sample_out_type=SampleType.assembly,
                sample_position=custom,
                action=action,
            )
            self.base.print_message("new assembly was successfully created")
            ref_samples_out2[0].sample_position = custom

            # a reference assembly was successfully created
            # convert it now to a real sample
            self.base.print_message("adding new assembly to sqlite db")
            samples_out2 = await self.unified_db.new_samples(samples=ref_samples_out2)

            if not samples_out2:
                # reference could not be converted to a real sample
                self.base.print_message(
                    "could not convert reference assembly to real assembly",
                    error=True,
                )
                return ErrorCodes.critical, [], []

            # add new reference to samples out list which already contains new liquid mixture
            samples_out.append(samples_out2[0])
            # and update the custom position with the new sample

            replaced, sample = await self.custom_replace_sample(
                custom=custom, sample=samples_out2[0]
            )
            if not replaced:
                self.base.print_message(
                    "could not replace sample with assembly when adding liquid",
                    error=True,
                )
                return ErrorCodes.critical, [], []

        # (5-3)
        # custom holds a sample and we need to create an assembly
        elif self.custom_assembly_allowed(custom=custom):
            # convert the ref samples that gets added to a real sample
            samples_out = await self.unified_db.new_samples(samples=ref_samples_out)
            if not samples_out:
                error = ErrorCodes.no_sample
                return error, [], []

            # set sample status
            custom_sample.inheritance = SampleInheritance.allow_both
            custom_sample.status = [SampleStatus.incorporated]
            samples_out[0].status.append(SampleStatus.incorporated)

            # add the custom sample to the samples_in
            samples_in.append(custom_sample)
            samples_in_initial.append(deepcopy(custom_sample))

            # create a new ref sample first
            error, ref_samples_out2 = await self.new_ref_samples(
                # input for assembly is the custom sample
                # and the new sample from source_liquid_in
                samples_in=[custom_sample, samples_out[0]],
                sample_out_type=SampleType.assembly,
                sample_position=custom,
                action=action,
            )

            if error != ErrorCodes.none:
                # something went wrong when creating the reference assembly
                return error, [], []

            # a reference assembly was successfully created
            # convert it now to a real sample
            samples_out2 = await self.unified_db.new_samples(samples=ref_samples_out2)
            if not samples_out2:
                # reference could not be converted to a real sample
                self.base.print_message(
                    "could not convert reference assembly to real assembly",
                    error=True,
                )
                return ErrorCodes.critical, [], []

            # add new reference to samples out list
            samples_out.append(samples_out2[0])

            # and update the custom position with the new sample
            replaced, sample = await self.custom_replace_sample(
                custom=custom, sample=samples_out2[0]
            )
            if not replaced:
                self.base.print_message(
                    "could not replace sample with assembly when adding liquid",
                    error=True,
                )
                return ErrorCodes.critical, [], []

        else:
            # nothing else possible
            self.base.print_message(
                f"Cannot add sample to position {custom}", error=True
            )
            return ErrorCodes.not_allowed, [], []

        # update all samples_out in the db
        await self.unified_db.update_samples(samples=samples_out)

        # update all samples_in in the db
        await self.unified_db.update_samples(samples=samples_in)

        return error, samples_in_initial, samples_out

    async def custom_add_gas(
        self,
        custom: str = None,
        source_gas_in: GasSample = None,
        volume_ml: float = 0.0,
        action: Action = None,
    ) -> Tuple[bool, List[SampleUnion], List[SampleUnion]]:
        """adds new gas from a 'reservoir' to a custom position"""

        error = ErrorCodes.none
        samples_in = []
        samples_in_initial = []
        samples_out = []

        # (1) check if source_gas_in is not None
        # and its a valid sample (add it to samples_in list)
        if source_gas_in is None:
            error = ErrorCodes.no_sample
            return error, [], []
        else:
            # check if source_gas_in is valid
            # converts source_gas_in to a list
            source_gas_in = object_to_sample(source_gas_in)
            samples_in = await self.unified_db.get_samples(samples=[source_gas_in])

            if not samples_in:
                self.base.print_message(
                    f"source_gas_in '{source_gas_in}' is not in db",
                    error=True,
                )
                error = ErrorCodes.no_sample
                return error, [], []

        if samples_in[0].sample_type != SampleType.gas:
            self.base.print_message("Not a gas Sample", error=True)
            return ErrorCodes.not_allowed, [], []

        if samples_in[0].volume_ml < volume_ml:
            self.base.print_message("Not enough volume available", error=True)
            return ErrorCodes.not_available, [], []

        samples_in[0].inheritance = SampleInheritance.give_only
        samples_in[0].status = [SampleStatus.preserved]
        # save a deepcopy of initial state as we will return only initial
        # samples_in and final samples_out
        samples_in_initial.append(deepcopy(samples_in[0]))

        # (2) verify if custom is a valid position
        # and get sample from custom position
        if custom in self.positions.customs_dict:
            custom_sample = deepcopy(self.positions.customs_dict[custom].sample)
            self.base.print_message(f"custom sample in valid position: {custom_sample}")
        else:
            error = ErrorCodes.not_available
            return error, [], []

        # (3) check if sample in custom position is valid
        if custom_sample != NoneSample():
            custom_samples_in = await self.unified_db.get_samples(
                samples=[custom_sample]
            )
            if not custom_samples_in:
                self.base.print_message("invalid sample in custom position", error=True)
                error = ErrorCodes.critical
                return error, [], []
            else:
                custom_sample = custom_samples_in[0]

        self.base.print_message(
            f"sample in custom position '{custom}' is {custom_sample.exp_dict()}"
        )

        # (4) create a new ref sample first for the amount we
        # take from samples_in
        # always sets reference status and inheritance to:
        # status=[SampleStatus.created]
        # inheritance=SampleInheritance.receive_only
        error, ref_samples_out = await self.new_ref_samples(
            # sample check converted source_gas_in
            # to a list already
            samples_in=samples_in,
            sample_out_type=SampleType.gas,
            sample_position=custom,
            action=action,
        )

        if error != ErrorCodes.none:
            return error, [], []

        # set the volume to the requested value
        ref_samples_out[0].sample_position = custom
        ref_samples_out[0].volume_ml = volume_ml

        # update volume of samples_in
        # also sets status to destroyed if vol <= 0
        # never dilute reservoir
        update_vol(samples_in[0], delta_vol_ml=-volume_ml, dilute=False)

        # (5) now decide what the new sample should be
        # (5-1) custom is empty --> new sample is ref_samples_out[0]
        # (5-2) we combine liquid from custom with ref_samples_out[0]
        #       and create a new liquid (combine_liquids is True)
        # (5-3) we create an assembly with custom_sample and ref_samples_out[0]

        # (5-1)
        if custom_sample == NoneSample():
            # cannot always convert reference sample to real sample
            # as at last 5-3 not always can do that
            samples_out = await self.unified_db.new_samples(samples=ref_samples_out)
            if not samples_out:
                error = ErrorCodes.no_sample
                return error, [], []

            # replace sample in custom position
            replaced, sample = await self.custom_replace_sample(
                custom=custom, sample=samples_out[0]
            )

            if not replaced:
                self.base.print_message(
                    "could not replace sample with assembly when adding gas",
                    error=True,
                )
                error = ErrorCodes.critical

        # (5-3)
        # custom holds a sample and we need to create an assembly
        elif self.custom_assembly_allowed(custom=custom):
            # convert the ref samples that gets added to a real sample
            samples_out = await self.unified_db.new_samples(samples=ref_samples_out)
            if not samples_out:
                error = ErrorCodes.no_sample
                return error, [], []

            # set sample status
            custom_sample.inheritance = SampleInheritance.allow_both
            custom_sample.status = [SampleStatus.incorporated]
            samples_out[0].status.append(SampleStatus.incorporated)

            # add the custom sample to the samples_in
            samples_in.append(custom_sample)
            samples_in_initial.append(deepcopy(custom_sample))

            # create a new ref sample first
            error, ref_samples_out2 = await self.new_ref_samples(
                # input for assembly is the custom sample
                # and the new sample from source_gas_in
                samples_in=[custom_sample, samples_out[0]],
                sample_out_type=SampleType.assembly,
                sample_position=custom,
                action=action,
            )

            if error != ErrorCodes.none:
                # something went wrong when creating the reference assembly
                return error, [], []

            # a reference assembly was successfully created
            # convert it now to a real sample
            samples_out2 = await self.unified_db.new_samples(samples=ref_samples_out2)
            if not samples_out2:
                # reference could not be converted to a real sample
                self.base.print_message(
                    "could not convert reference assembly to real assembly",
                    error=True,
                )
                return ErrorCodes.critical, [], []

            # add new reference to samples out list
            samples_out.append(samples_out2[0])

            # and update the custom position with the new sample
            replaced, sample = await self.custom_replace_sample(
                custom=custom, sample=samples_out2[0]
            )
            if not replaced:
                self.base.print_message(
                    "could not replace sample with assembly when adding gas",
                    error=True,
                )
                return ErrorCodes.critical, [], []

        else:
            # nothing else possible
            self.base.print_message(
                f"Cannot add sample to position {custom}", error=True
            )
            return ErrorCodes.not_allowed, [], []

        # update all samples_out in the db
        await self.unified_db.update_samples(samples=samples_out)

        # update all samples_in in the db
        await self.unified_db.update_samples(samples=samples_in)

        return error, samples_in_initial, samples_out

    async def destroy_sample(self, sample: SampleUnion = None) -> bool:
        """will mark a sample as destroyed in the sample db
        and update its parameters accordingly"""
        # first update it from the db (get the most recent info)
        sample = await self.update_samples_from_db_helper(sample=sample)
        # now destroy the sample
        sample.destroy_sample()
        # update all sample in the db
        await self.unified_db.update_samples(samples=[sample])

        return sample

    async def selective_destroy_samples(
        self,
        samples,
        destroy_liquid: bool = False,
        destroy_gas: bool = False,
        destroy_solid: bool = False,
    ) -> List[SampleUnion]:
        ret_samples = []
        for sample in samples:
            # first update it from the db (get the most recent info)
            sample = await self.update_samples_from_db_helper(sample=sample)
            self.base.print_message(f"destroy: got sample {sample.get_global_label()}")
            if sample.sample_type == SampleType.liquid:
                if destroy_liquid:
                    sample.destroy_sample()
                ret_samples.append(sample)
            elif sample.sample_type == SampleType.solid:
                if destroy_solid:
                    # this would mark the sample as destroyed
                    # but currently we have no db to track
                    # the status solids
                    sample.destroy_sample()
                ret_samples.append(sample)
            elif sample.sample_type == SampleType.gas:
                if destroy_gas:
                    sample.destroy_sample()
                ret_samples.append(sample)
            elif sample.sample_type == SampleType.assembly:
                # unpacking will mark assemblies as destroyed
                # and then this function can destroy its parts
                self.base.print_message(
                    "Cannot destroy assembly, unpack it first.",
                    info=True,
                )
                ret_samples.append(sample)
            elif sample.sample_type is None:
                self.base.print_message(
                    "got None sample",
                    info=True,
                )
            else:
                self.base.print_message(
                    f"validation error, type '{type(sample)}' "
                    "is not a valid sample model",
                    error=True,
                )

        # now write all samples back to the db
        # update all sample in the db
        await self.unified_db.update_samples(samples=ret_samples)

        return ret_samples

    async def create_samples(
        self, reference_samples_in: List[SampleUnion], action: Action = None
    ) -> List[SampleUnion]:
        """creates new samples in the db from provided refernces samples"""
        samples_out = []

        if action is None:
            self.base.print_message("no action defined", error=True)
            return samples_out

        for sample in reference_samples_in:
            sample.action_uuid = [action.action_uuid]
            sample.sample_creation_action_uuid = action.action_uuid
            sample.sample_creation_experiment_uuid = action.experiment_uuid
            sample.status = [SampleStatus.created]
            sample.inheritance = SampleInheritance.receive_only
            # need to update the parts of an assembly first
            if sample.sample_type == SampleType.assembly:
                sample.parts = await self.unified_db.get_samples(samples=sample.parts)
                for part in sample.parts:
                    part.status = [SampleStatus.incorporated]
                    part.inheritance = SampleInheritance.allow_both
                    part.action_uuid = [action.action_uuid]
                # now write all samples back to the db
                # update all sample in the db
                await self.unified_db.update_samples(samples=sample.parts)
                # create a sourcelist from all parts
                source = [s.get_global_label() for s in sample.parts]
                # add the source list to the sample source
                for s in source:
                    sample.source.append(s)

        samples_out = await self.unified_db.new_samples(samples=reference_samples_in)

        return samples_out

    async def generate_plate_sample_no_list(
        self,
        active=None,
        plate_id: int = None,
        sample_code: int = None,
        skip_n_samples: int = None,
        direction: ScanDirection = None,
        sample_nos: List[int] = [],
        sample_nos_operator: ScanOperator = None,
        platemap_xys: List[Tuple[int, int]] = [],
        platemap_xys_operator: ScanOperator = None,
    ):
        """generate the sample list based on filters:
        - which direction to move
        (raster rows, raster columns, left-to-right, top-to-bottom)
        - platemap composition (A>0 and/or B=0)
        - platemap sample codes (code=0, code!=1)
        - skip every N samples
        - sample number equals, gt, gte, lt, lte, not
        - platemap x,y equals, gt, gte, lt, lte, not
        """
        if (
            active is None
            or plate_id is None
            or sample_code is None
            or skip_n_samples is None
        ):
            return False

        # put all sample numbers in here
        sample_nos_list = []  # need to be a list of str

        # (1) check if plate_id is valid
        solid = SolidSample(plate_id=plate_id)
        pmmap = await self.unified_db.get_platemap(samples=[solid])
        if not pmmap:
            return False
        pmmap = pmmap[0]
        lasti = -1
        for i, col in enumerate(pmmap):
            if (i - lasti) - 1 == skip_n_samples:
                if col["code"] == sample_code:
                    sample_nos_list.append(f"{col['sample_no']}")
                    lasti = i

        # write the sample no list to a file
        await active.write_file(
            file_type="plate_sample_no_list_file",
            filename=f"{plate_id}.txt",
            output_str="\n".join(sample_nos_list),
            header=None,
            sample_str=None,
        )

        return True
