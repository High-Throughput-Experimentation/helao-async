""" models.py
Standard classes for HelaoFastAPI server response objects.

"""
from typing import Optional, List, Union
from collections import defaultdict
from enum import Enum
from pydantic import BaseModel, ValidationError, validator
from socket import gethostname
from datetime import datetime

from helao.core.helper import print_message

class return_process_group(BaseModel):
    """Return class for queried cProcess_group objects."""
    index: int
    uid: Union[str, None]
    label: str
    sequence: str
    pars: dict
    access: str


class return_process_group_list(BaseModel):
    """Return class for queried cProcess_group list."""
    process_groups: List[return_process_group]


class return_process(BaseModel):
    """Return class for queried process objects."""
    index: int
    uid: Union[str, None]
    server: str
    process: str
    pars: dict
    preempt: int


class return_process_list(BaseModel):
    """Return class for queried process list."""
    processes: List[return_process]


class return_finished_process(BaseModel):
    """Standard return class for processes that finish with response."""
    technique_name: str
    access: str
    orch_name: str
    process_group_timestamp: str
    process_group_uuid: str
    process_group_label: str
    sequence: str
    sequence_pars: dict
    result_dict: dict
    process_server: str
    process_queue_time: str
    process_real_time: Optional[str]
    process_name: str
    process_params: dict
    process_uuid: str
    process_enum: str
    process_abbr: str
    process_num: str
    start_condition: Union[int, dict]
    save_prc: bool
    save_data: bool
    samples_in: Optional[dict]
    samples_out: Optional[dict]
    output_dir: Optional[str]
    file_dict: Optional[dict]
    column_names: Optional[list]
    header: Optional[str]
    data: Optional[list]


class return_running_process(BaseModel):
    """Standard return class for processes that finish after response."""
    technique_name: str
    access: str
    orch_name: str
    process_group_timestamp: str
    process_group_uuid: str
    process_group_label: str
    sequence: str
    sequence_pars: dict
    result_dict: dict
    process_server: str
    process_queue_time: str
    process_real_time: Optional[str]
    process_name: str
    process_params: dict
    process_uuid: str
    process_enum: str
    process_abbr: str
    process_num: str
    start_condition: Union[int, dict]
    save_prc: bool
    save_data: bool
    samples_in: Optional[dict]
    samples_out: Optional[dict]
    output_dir: Optional[str]


class base_sample(BaseModel):
    global_label: Optional[str] = None
    sample_type: Optional[str] = None
    sample_no: Optional[int] = None
    sample_creation_timecode: Optional[int] = None # epoch in ns
    sample_position: Optional[str] = None
    machine_name: Optional[str] = None
    sample_hash: Optional[str] = None
    last_update: Optional[int] = None # epoch in ns
    inheritance: Optional[str] = None # only for internal use
    status: Union[List[str],str] = None # only for internal use
    process_group_uuid: Optional[str] = None
    process_uuid: Optional[str] = None
    process_queue_time: Optional[str] = None # "%Y%m%d.%H%M%S%f"
    server_name: Optional[str] = None
    chemical: Optional[List[str]] = []
    mass: Optional[List[str]] = []
    supplier: Optional[List[str]] = []
    lot_number: Optional[List[str]] = []
    source: Union[List[str],str] = None
    comment: Optional[str] = None

    @validator("process_queue_time")
    def validate_process_queue_time(cls, v):
        if v is not None:
            try:
                atime = datetime.strptime(v, "%Y%m%d.%H%M%S%f")
            except ValueError:
                print_message({}, "model", f"invalid 'process_queue_time': {v}", error = True)
                raise ValueError("invalid 'process_queue_time'")
            return atime.strftime("%Y%m%d.%H%M%S%f")
        else:
            return None
        
    def create_initial_prc_dict(self):
        return {
            "global_label":self.get_global_label(),
            "sample_type":self.sample_type,
            "sample_no":self.sample_no,
            "machine_name":self.machine_name if self.machine_name is not None else gethostname(),
            "sample_creation_timecode":self.sample_creation_timecode
            }


class liquid_sample(base_sample):
    """base class for liquid samples"""
    sample_type: Optional[str] = "liquid"
    volume_mL: Optional[float] = None
    ph: Optional[float]=None

    def prc_dict(self):
        prc_dict = self.create_initial_prc_dict()
        return prc_dict

    def get_global_label(self):
        if self.global_label is None:
            label = None
            machine_name = self.machine_name if self.machine_name is not None else gethostname()
            label = f"{machine_name}__liquid__{self.sample_no}"
            return label
        else:
            return self.global_label


    @validator("sample_type")
    def validate_sample_type(cls, v):
        if v != "liquid":
            print_message({}, "model", f"validation liquid in solid_sample, got type '{v}'", error = True)
            # return "liquid"
            raise ValueError("must be liquid")
        return "liquid"


class solid_sample(base_sample):
    """base class for solid samples"""
    sample_type: Optional[str] = "solid"
    machine_name: Optional[str] = "legacy"
    plate_id: Optional[int] = None
    
    def prc_dict(self):
        prc_dict = self.create_initial_prc_dict()
        prc_dict.update({"plate_id":self.plate_id})
        return prc_dict

    def get_global_label(self):
        if self.global_label is None:
            label = None
            machine_name = self.machine_name if self.machine_name is not None else "legacy"
            label = f"{machine_name}__solid__{self.plate_id}_{self.sample_no}"
            return label
        else:
            return self.global_label

    @validator("sample_type")
    def validate_sample_type(cls, v):
        if v != "solid":
            print_message({}, "model", f"validation error in solid_sample, got type '{v}'", error = True)
            # return "solid"
            raise ValueError("must be solid")
        return "solid"
        

class gas_sample(base_sample):
    """base class for gas samples"""
    sample_type: Optional[str] = "gas"
    volume_mL: Optional[float] = None

    def prc_dict(self):
        prc_dict = self.create_initial_prc_dict()
        return prc_dict

    def get_global_label(self):
        if self.global_label is None:
            label = None
            machine_name = self.machine_name if self.machine_name is not None else gethostname()
            label = f"{machine_name}__gas__{self.sample_no}"
            return label
        else:
            return self.global_label

    @validator("sample_type")
    def validate_sample_type(cls, v):
        if v != "gas":
            print_message({}, "model", f"validation error in gas_sample, got type '{v}'", error = True)
            # return "gas"
            raise ValueError("must be gas")
        return "gas"


def sample_model_list_validator(model_list, values, **kwargs):
    """validates samples models in a list"""

    def dict_to_model(model_dict):
        sample_type = model_dict.get("sample_type", None)
        if sample_type is None:
            return None
        elif sample_type == "liquid":
            return liquid_sample(**model_dict)
        elif sample_type == "gas":
            return gas_sample(**model_dict)
        elif sample_type == "solid":
            return solid_sample(**model_dict)
        elif sample_type == "assembly":
            return assembly_sample(**model_dict)
        else:
            print_message({}, "model", f"unsupported sample_type '{sample_type}'", error = True)
            return None

    
    if model_list is None or not isinstance(model_list, list):
        print_message({}, "model", f"validation error, type '{type(model_list)}' is not a valid sample model list", error = True)
        raise ValueError("must be valid sample model list")
        return []
    
    for i, model in enumerate(model_list):
        if isinstance(model, dict):
            model_list[i] = dict_to_model(model)
        elif isinstance(model, liquid_sample):
            continue
        elif isinstance(model, solid_sample):
            continue
        elif isinstance(model, gas_sample):
            continue
        elif isinstance(model, assembly_sample):
            continue
        elif model is None:
            continue
        else:
            print_message({}, "model", f"validation error, type '{type(model)}' is not a valid sample model", error = True)
            raise ValueError("must be valid sample model")

    return model_list


class assembly_sample(base_sample):
    sample_type: Optional[str] = "assembly"
    parts: Optional[list] = []
    sample_position: Optional[str] = "cell1_we" # usual default assembly position

    def get_global_label(self):
        if self.global_label is None:
            label = None
            machine_name = self.machine_name if self.machine_name is not None else gethostname()
            label = f"{machine_name}__assembly__{self.sample_position}__{self.sample_creation_timecode}"
            return label
        else:
            return self.global_label

    @validator("parts")
    def validate_parts(cls, value, values, **kwargs):
        return sample_model_list_validator(value, values, **kwargs)


    @validator("sample_type")
    def validate_sample_type(cls, v):
        if v != "assembly":
            print_message({}, "model", f"validation error in assembly, got type '{v}'", error = True)
            # return "assembly"
            raise ValueError("must be assembly")
        return "assembly"            


    def prc_dict(self):
        return {
            "global_label":self.get_global_label(),
            "sample_type":self.sample_type,
            "machine_name":self.machine_name,
            "sample_position":self.sample_position,
            "sample_creation_timecode":self.sample_creation_timecode,
            "assembly_parts":self.get_assembly_parts_prc_dict()
            }


    def get_assembly_parts_prc_dict(self):
        part_dict_list = []
        for part in self.parts:
            if part is not None:
                # return full dict
                # part_dict_list.append(part.prc_dict())
                # return only the label (preferred)
                part_dict_list.append(part.get_global_label())
            else:
                # part_dict_list.append(None)
                pass
        return part_dict_list


class sample_list(BaseModel):
    """ a combi basemodel which can contain all possible samples
    Its also a list and we should enforce samples as being a list"""
    samples: Optional[list] = [] # don't use union of models, that does not work here

    @validator("samples")
    def validate_samples(cls, value, values, **kwargs):
        return sample_model_list_validator(value, values, **kwargs)


class prc_header(BaseModel):
    hlo_version: str = "2021.09.20"
    technique_name: str
    server_name: str
    orchestrator: str
    machine_name: str
    access: str
    output_dir: str
    process_group_uuid: str
    process_group_timestamp: str
    process_uuid: str
    process_queue_time: str
    process_enum: Optional[float] = 0.0
    process_name: str
    process_abbr: Optional[str] = None
    process_params: Union[dict, None] = None
    samples_in: Optional[Union[dict, None]] = None
    samples_out: Optional[Union[dict, None]] = None
    files: Optional[Union[dict, None]] = None
    
