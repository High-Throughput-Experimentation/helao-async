
__all__ = ["LiquidSample",
           "GasSample",
           "SolidSample",
           "AssemblySample",
           "SampleList"]

from pydantic import BaseModel
from pydantic import validator
from typing import Union, List, Optional
from socket import gethostname
from datetime import datetime


from helao.core.helper import print_message


def _sample_model_list_validator(model_list, values, **kwargs):
    """validates samples models in a list"""

    def dict_to_model(model_dict):
        sample_type = model_dict.get("sample_type", None)
        if sample_type is None:
            return None
        elif sample_type == "liquid":
            return LiquidSample(**model_dict)
        elif sample_type == "gas":
            return GasSample(**model_dict)
        elif sample_type == "solid":
            return SolidSample(**model_dict)
        elif sample_type == "assembly":
            return AssemblySample(**model_dict)
        else:
            print_message({}, "model", f"unsupported sample_type '{sample_type}'", error = True)
            raise ValueError("model", f"unsupported sample_type '{sample_type}'")

    
    if model_list is None or not isinstance(model_list, list):
        print_message({}, "model", f"validation error, type '{type(model_list)}' is not a valid sample model list", error = True)
        raise ValueError("must be valid sample model list")
    
    for i, model in enumerate(model_list):
        if isinstance(model, dict):
            model_list[i] = dict_to_model(model)
        elif isinstance(model, LiquidSample):
            continue
        elif isinstance(model, SolidSample):
            continue
        elif isinstance(model, GasSample):
            continue
        elif isinstance(model, AssemblySample):
            continue
        elif model is None:
            continue
        else:
            print_message({}, "model", f"validation error, type '{type(model)}' is not a valid sample model", error = True)
            raise ValueError("must be valid sample model")

    return model_list


class _BaseSample(BaseModel):
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


class LiquidSample(_BaseSample):
    """base class for liquid samples"""
    sample_type: Optional[str] = "liquid"
    volume_mL: Optional[float] = None
    pH: Optional[float]=None

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


class SolidSample(_BaseSample):
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
        

class GasSample(_BaseSample):
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


class AssemblySample(_BaseSample):
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
        return _sample_model_list_validator(value, values, **kwargs)


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


class SampleList(BaseModel):
    """ a combi basemodel which can contain all possible samples
    Its also a list and we should enforce samples as being a list"""
    samples: Optional[list] = [] # don't use union of models, that does not work here

    @validator("samples")
    def validate_samples(cls, value, values, **kwargs):
        return _sample_model_list_validator(value, values, **kwargs)
