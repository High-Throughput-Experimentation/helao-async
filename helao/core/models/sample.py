from __future__ import annotations
from socket import gethostname
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, validator, root_validator, Field
from pydantic.tools import parse_obj_as

import datetime
from typing import List, Optional, Union, Literal
from typing import ForwardRef

from helao.core.version import get_hlo_version
from helao.core.helaodict import HelaoDict


""" sample.py
Liquid, Gas, Assembly, and Solid sample type models.

"""
__all__ = [
    "NoneSample",
    "SampleModel",
    "LiquidSample",
    "GasSample",
    "SolidSample",
    "AssemblySample",
    "SampleList",
    "SampleUnion",
    "object_to_sample",
    "SampleInheritance",
    "SampleStatus",
]

SampleUnion = ForwardRef("SampleUnion")
SamplePartUnion = ForwardRef("SamplePartUnion")


class SampleType(str, Enum):
    liquid = "liquid"
    gas = "gas"
    solid = "solid"
    assembly = "assembly"


class SampleInheritance(str, Enum):
    none = "none"
    give_only = "give_only"
    receive_only = "receive_only"
    allow_both = "allow_both"
    block_both = "block_both"


class SampleStatus(str, Enum):
    none = "none"
    # pretty self-explanatory; the sample was created during the action.
    created = "created"
    # also self-explanatory
    destroyed = "destroyed"
    # merged with another liquid/gas/solid
    merged = "merged"
    # the sample exists before and after the action. e.g. an echem experiment
    preserved = "preserved"
    # the sample was combined with others in the action. E.g. the creation of an electrode assembly from electrodes and electrolytes
    incorporated = "incorporated"
    # the opposite of incorporated. E.g. an electrode assembly is taken apart, and the original electrodes are recovered, and further experiments may be done on those electrodes
    recovered = "recovered"
    loaded = "loaded"
    unloaded = "unloaded"


class SampleModel(BaseModel, HelaoDict):
    """Bare bones sample with only the key identifying information of a sample in the database."""

    _hashinclude_ = {"global_label", "sample_type"}

    hlo_version: Optional[str] = Field(default_factory=get_hlo_version)
    global_label: Optional[str] = None  # is None for a ref sample
    sample_type: Optional[str] = None

    # time related fields
    sample_creation_timecode: Optional[int] = None  # epoch in ns
    last_update: Optional[int] = None  # epoch in ns
    # action_timestamp: Optional[str]  # "%Y%m%d.%H%M%S%f"

    # labels
    sample_no: Optional[int|str] = None
    machine_name: Optional[str] = None
    sample_hash: Optional[str] = None
    server_name: Optional[str] = None

    # action related
    action_uuid: List[UUID] = Field(default=[])
    sample_creation_action_uuid: Optional[UUID] = None
    sample_creation_experiment_uuid: Optional[UUID] = None

    # metadata
    sample_position: Optional[str] = None
    inheritance: Optional[SampleInheritance] = None  # only for internal use
    status: List[SampleStatus] = Field(default=[])  # only for internal use
    chemical: List[str] = Field(default=[])
    partial_molarity: List[str] = Field(default=[])
    supplier: List[str] = Field(default=[])
    lot_number: List[str] = Field(default=[])
    source: List[str] = Field(default=[])
    prep_date: Optional[datetime.date] = None
    comment: Optional[str] = None

    def create_initial_exp_dict(self):
        if not isinstance(self.status, list):
            self.status = [self.status]

        return {
            "global_label": self.get_global_label(),
            "sample_type": self.sample_type,
            "sample_no": self.sample_no,
            "machine_name": (
                self.machine_name.lower()
                if self.machine_name is not None
                else gethostname().lower()
            ),
            "sample_creation_timecode": self.sample_creation_timecode,
            "last_update": self.last_update,
            "sample_position": self.sample_position,
            "inheritance": self.inheritance,
            "status": self.status,
        }

    def exp_dict(self):
        exp_dict = self.create_initial_exp_dict()
        return exp_dict

    def get_global_label(self):
        pass

    def zero_volume(self):
        if hasattr(self, "volume_ml"):
            self.volume_ml = 0
            if SampleStatus.destroyed not in self.status:
                self.status.append(SampleStatus.destroyed)
            if SampleStatus.preserved in self.status:
                self.status.remove(SampleStatus.preserved)

    def destroy_sample(self):
        self.zero_volume()
        if SampleStatus.preserved in self.status:
            self.status.remove(SampleStatus.preserved)
        if SampleStatus.destroyed not in self.status:
            self.status.append(SampleStatus.destroyed)

    def get_vol_ml(self) -> float:
        if hasattr(self, "volume_ml"):
            return self.volume_ml
        else:
            return 0.0

    def get_dilution_factor(self) -> float:
        if hasattr(self, "dilution_factor"):
            return self.dilution_factor
        else:
            return 1.0


class NoneSample(SampleModel):
    sample_type: Literal[None] = None
    global_label: Literal[None] = None
    inheritance: Optional[SampleInheritance] = None  # only for internal use
    status: List[SampleStatus] = Field(default=[])  # only for internal use

    def get_global_label(self):
        return None

    def get_vol_ml(self):
        return None

    def exp_dict(self):
        return {
            "global_label": self.get_global_label(),
            "sample_type": self.sample_type,
        }


class LiquidSample(SampleModel):
    """base class for liquid samples"""

    sample_type: Literal[SampleType.liquid] = SampleType.liquid
    volume_ml: Optional[float] = 0.0
    ph: Optional[float] = None
    dilution_factor: Optional[float] = 1.0
    electrolyte: Optional[str] = None

    def exp_dict(self):
        exp_dict = self.create_initial_exp_dict()
        exp_dict.update({"volume_ml": self.volume_ml})
        exp_dict.update({"ph": self.ph})
        exp_dict.update({"dilution_factor": self.dilution_factor})
        return exp_dict

    def get_global_label(self):
        if self.global_label is None:
            label = None
            machine_name = (
                self.machine_name.lower()
                if self.machine_name is not None
                else gethostname().lower()
            )
            label = f"{machine_name}__liquid__{self.sample_no}"
            return label
        else:
            return self.global_label


class SolidSample(SampleModel):
    """base class for solid samples"""

    sample_type: Literal[SampleType.solid] = SampleType.solid
    machine_name: Optional[str] = "legacy"
    plate_id: Optional[int|str] = None

    def exp_dict(self):
        exp_dict = self.create_initial_exp_dict()
        exp_dict.update({"plate_id": self.plate_id})
        return exp_dict

    def get_global_label(self):
        if self.global_label is None:
            label = None
            machine_name = (
                self.machine_name.lower() if self.machine_name is not None else "legacy"
            )
            label = f"{machine_name}__solid__{self.plate_id}_{self.sample_no}"
            return label
        else:
            return self.global_label

    @root_validator(pre=False, skip_on_failure=True)
    def validate_global_label(cls, values):
        machine_name = values.get("machine_name")
        plate_id = values.get("plate_id")
        sample_no = values.get("sample_no")
        values["global_label"] = f"{machine_name}__solid__{plate_id}_{sample_no}"
        return values


class GasSample(SampleModel):
    """base class for gas samples"""

    sample_type: Literal[SampleType.gas] = SampleType.gas
    volume_ml: Optional[float] = 0.0
    dilution_factor: Optional[float] = 1.0

    def exp_dict(self):
        exp_dict = self.create_initial_exp_dict()
        exp_dict.update({"volume_ml": self.volume_ml})
        exp_dict.update({"dilution_factor": self.dilution_factor})
        return exp_dict

    def get_global_label(self):
        if self.global_label is None:
            label = None
            machine_name = (
                self.machine_name.lower()
                if self.machine_name is not None
                else gethostname().lower()
            )
            label = f"{machine_name}__gas__{self.sample_no}"
            return label
        else:
            return self.global_label


class AssemblySample(SampleModel):
    sample_type: Literal[SampleType.assembly] = SampleType.assembly
    # parts: List[SampleUnion] = Field(default=[])
    parts: List[SamplePartUnion] = Field(default=[])
    sample_position: Optional[str] = "cell1_we"  # usual default assembly position

    def get_global_label(self):
        if self.global_label is None:
            label = None
            machine_name = (
                self.machine_name.lower()
                if self.machine_name is not None
                else gethostname().lower()
            )
            label = f"{machine_name}__assembly__{self.sample_position}__{self.sample_creation_timecode}"
            return label
        else:
            return self.global_label

    @validator("parts", pre=True)
    def validate_parts(cls, value):
        if value is None:
            return []
        return value

    def exp_dict(self):
        exp_dict = self.create_initial_exp_dict()
        exp_dict.update({"assembly_parts": self.get_assembly_parts_exp_dict()})
        return exp_dict

    def get_assembly_parts_exp_dict(self):
        part_dict_list = []
        for part in self.parts:
            if part is not None:
                # return full dict
                # part_dict_list.append(part.exp_dict())
                # return only the label (preferred)
                part_dict_list.append(part.get_global_label())
            else:
                pass
        return part_dict_list


# TODO: this needs to be removed in the near future
# and all calls to SampleList replaced by SampleUnion
class SampleList(BaseModel, HelaoDict):
    """a combi basemodel which can contain all possible samples
    Its also a list and we should enforce samples as being a list"""

    samples: Optional[List[SampleModel]] = Field(default=[])


SampleUnion = Union[
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
]


SamplePartUnion = Union[
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
]


def object_to_sample(data):
    if isinstance(data, BaseModel):
        data = data.model_dump()
    try:
        sample = parse_obj_as(SampleUnion, data)
    except Exception as e:
        print(f"Error: {e}")
        print(f"Data: {data}")
        raise e
    return sample


AssemblySample.model_rebuild()
SampleList.model_rebuild()
