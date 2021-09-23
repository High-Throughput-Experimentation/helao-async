""" models.py
Standard classes for HelaoFastAPI server response objects.

"""
from typing import Optional, List, Union
from collections import defaultdict
from enum import Enum
from pydantic import BaseModel, ValidationError, validator
from socket import gethostname
from helao.core.helper import print_message

class return_dec(BaseModel):
    """Return class for queried Decision objects."""
    index: int
    uid: Union[str, None]
    label: str
    actualizer: str
    pars: dict
    access: str


class return_declist(BaseModel):
    """Return class for queried Decision list."""
    decisions: List[return_dec]


class return_act(BaseModel):
    """Return class for queried Action objects."""
    index: int
    uid: Union[str, None]
    server: str
    action: str
    pars: dict
    preempt: int


class return_actlist(BaseModel):
    """Return class for queried Action list."""
    actions: List[return_act]


class return_finishedact(BaseModel):
    """Standard return class for actions that finish with response."""
    technique_name: str
    access: str
    orch_name: str
    decision_timestamp: str
    decision_uuid: str
    decision_label: str
    actualizer: str
    actualizer_pars: dict
    result_dict: dict
    action_server: str
    action_queue_time: str
    action_real_time: Optional[str]
    action_name: str
    action_params: dict
    action_uuid: str
    action_enum: str
    action_abbr: str
    actionnum: str
    start_condition: Union[int, dict]
    save_rcp: bool
    save_data: bool
    samples_in: Optional[dict]
    samples_out: Optional[dict]
    output_dir: Optional[str]
    file_dict: Optional[dict]
    column_names: Optional[list]
    header: Optional[str]
    data: Optional[list]


class return_runningact(BaseModel):
    """Standard return class for actions that finish after response."""
    technique_name: str
    access: str
    orch_name: str
    decision_timestamp: str
    decision_uuid: str
    decision_label: str
    actualizer: str
    actualizer_pars: dict
    result_dict: dict
    action_server: str
    action_queue_time: str
    action_real_time: Optional[str]
    action_name: str
    action_params: dict
    action_uuid: str
    action_enum: str
    action_abbr: str
    actionnum: str
    start_condition: Union[int, dict]
    save_rcp: bool
    save_data: bool
    samples_in: Optional[dict]
    samples_out: Optional[dict]
    output_dir: Optional[str]


class base_sample(BaseModel):
    global_label: Optional[str] = None
    sample_type: Optional[str] = None
    sample_no: Optional[int] = None
    sample_creation_timecode: Optional[str] = None
    sample_position: Optional[str] = None
    machine_name: Optional[str] = None
    # sample_hash: Optional[str] = None
    last_update: Optional[str] = None
    inheritance: Optional[str] = None
    DUID: Optional[str] = None
    AUID: Optional[str] = None
    action_time: Optional[str] = None
    servkey: Optional[str] = None
    plate_id: Optional[int] = None
    chemical: Optional[List[str]] = []
    mass: Optional[List[str]] = []
    supplier: Optional[List[str]] = []
    lot_number: Optional[List[str]] = []
    source: Union[List[str],str] = None

    def get_global_label(self):
        if self.global_label is None:
            label = None
            if self.sample_type == "liquid":
                machine_name = self.machine_name if self.machine_name is not None else gethostname()
                label = f"{machine_name}__liquid__{self.sample_no}"
            elif self.sample_type == "gas":
                machine_name = self.machine_name if self.machine_name is not None else gethostname()
                label = f"{machine_name}__gas__{self.sample_no}"
            elif self.sample_type == "solid":
                machine_name = self.machine_name if self.machine_name is not None else "legacy"
                label = f"{machine_name}__solid__{self.plate_id}_{self.sample_no}"
            elif self.sample_type == "sample_assembly":
                machine_name = self.machine_name if self.machine_name is not None else gethostname()
                label = f"{machine_name}__sample_assembly__{self.sample_position}__{self.sample_creation_timecode}"
            return label
        else:
            return self.global_label

        
    def create_initial_rcp_dict(self):
        return {
            "global_label":self.get_global_label(),
            "sample_type":self.sample_type,
            "sample_no": self.sample_no,
            "machine_name":self.machine_name if self.machine_name is not None else gethostname(),
            }


class liquid_sample(base_sample):
    """base class for liquid samples"""
    sample_type: Optional[str] = "liquid"
    volume_mL: Optional[float] = None
    ph: Optional[float]=None

    def rcp_dict(self):
        rcp_dict = self.create_initial_rcp_dict()
        return rcp_dict

    @validator('sample_type')
    def validate_sample_type(cls, v):
        if v != "liquid":
            print_message({}, "model", f"validation liquid in solid_sample, got type {v}", error = True)
            # return "liquid"
            raise ValueError('must be liquid')
        return "liquid"


class solid_sample(base_sample):
    """base class for solid samples"""
    sample_type: Optional[str] = "solid"
    machine_name: Optional[str] = "legacy"
    
    def rcp_dict(self):
        rcp_dict = self.create_initial_rcp_dict()
        rcp_dict.update({"plate_id":self.plate_id})
        return rcp_dict

    @validator('sample_type')
    def validate_sample_type(cls, v):
        if v != "solid":
            print_message({}, "model", f"validation error in solid_sample, got type {v}", error = True)
            # return "solid"
            raise ValueError('must be solid')
        return "solid"
        

class gas_sample(base_sample):
    """base class for gas samples"""
    sample_type: Optional[str] = "gas"
    volume_mL: Optional[float] = None

    def rcp_dict(self):
        rcp_dict = self.create_initial_rcp_dict()
        return rcp_dict

    @validator('sample_type')
    def validate_sample_type(cls, v):
        if v != "gas":
            print_message({}, "model", f"validation error in gas_sample, got type {v}", error = True)
            # return "gas"
            raise ValueError('must be gas')
        return "gas"


def sample_model_list_validator(model_list, values, **kwargs):
    """validates samples models in a list"""

   
    def dict_to_model(model_dict):
        sample_type = model_dict.get("sample_type", None)
        if sample_type is None:
            return None
        else:
            model = None
            if sample_type == "liquid":
                model = liquid_sample(**model_dict)
            elif sample_type == "gas":
                model = gas_sample(**model_dict)
            elif sample_type == "solid":
                model = solid_sample(**model_dict)
            elif sample_type == "sample_assembly":
                model = sample_assembly(**model_dict)
            return model
    
    if model_list is None or not isinstance(model_list, list):
        print_message({}, "model", f"validation error, type {type(model_list)} is not a valid sample model list", error = True)
        raise ValueError("must be valid sample model list")
        return []
    
    for i, model in enumerate(model_list):
        if isinstance(model, dict):
            model_list[i] = dict_to_model(model)
        else:
            if not isinstance(model, liquid_sample):
                if not isinstance(model, solid_sample):
                    if not isinstance(model, gas_sample):
                        if not isinstance(model, sample_assembly):
                            if model is not None:
                                print_message({}, "model", f"validation error, type {type(model)} is not a valid sample model", error = True)
                                raise ValueError("must be valid sample model")

    return model_list


class sample_assembly(base_sample):
    sample_type: Optional[str] = "sample_assembly"
    parts: Optional[list] = []
    sample_position: Optional[str] = "cell1_we" # overwrite base variable with usual default assembly position

    # class Config:
    #     arbitrary_types_allowed = True # this just checks if param is of that type

    @validator('parts')
    def validate_parts(cls, value, values, **kwargs):
        return sample_model_list_validator(value, values, **kwargs)


    @validator('sample_type')
    def validate_sample_type(cls, v):
        if v != "sample_assembly":
            print_message({}, "model", f"validation error in sample_assembly, got type {v}", error = True)
            # return "gas"
            raise ValueError('must be sample_assembly')
        return "sample_assembly"            


    def rcp_dict(self):
        # self.check_assembly_parts()
        return {
            "global_label":self.get_global_label(),
            "sample_type":self.sample_type,
            # "sample_no": self.sample_no,
            "machine_name":self.machine_name,
            "assembly_parts":self.get_assembly_parts_rcp_dict()
            }


    def get_assembly_parts_rcp_dict(self):
        part_dict_list = []
        for part in self.parts:
            if part is not None:
                # return full dict
                # part_dict_list.append(part.rcp_dict())
                # return only the label (prefered)
                part_dict_list.append(part.get_global_label())
            else:
                # part_dict_list.append(None)
                pass
        return part_dict_list


class sample_list(BaseModel):
    """ a combi basemodel which can contain all possible samples
    Its also a list and we should enforce samples as being a list"""
    samples: Optional[list] = [] # don't use union of models, that does not work here

    @validator('samples')
    def validate_samples(cls, value, values, **kwargs):
        return sample_model_list_validator(value, values, **kwargs)


class rcp_header(BaseModel):
    hlo_version: str = "2021.09.20"
    technique_name: str
    server_name: str
    orchestrator: str
    machine_name: str
    access: str
    output_dir: str
    decision_uuid: str
    decision_timestamp: str
    action_uuid: str
    action_queue_time: str
    action_enum: Optional[float] = 0.0
    action_name: str
    action_abbr: Optional[str] = None
    action_params: Union[dict, None] = None
    samples_in: Optional[Union[dict, None]] = None#Optional[List[samples_inout]]
    samples_out: Optional[Union[dict, None]] = None#Optional[List[samples_inout]]
    files: Optional[Union[dict, None]] = None#Optional[List[hlo_file]]
    
