""" models.py
Standard classes for HelaoFastAPI server response objects.

"""
from typing import Optional, List, Union
from collections import defaultdict
from enum import Enum
from pydantic import BaseModel


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


class liquid_sample_no(BaseModel):
    """Return class for liquid sample_no objects."""
    sample_id: int = None
    DUID: Optional[str] = None
    AUID: Optional[str] = None
    source: Union[List[str],str] = None
    volume_mL: Optional[float] = None
    inheritance: Optional[str] = None
    machine: Optional[str] = None
    sample_hash: Optional[str] = None
    action_time: Optional[str] = None
    chemical: Optional[List[str]] = []
    mass: Optional[List[str]] = []
    supplier: Optional[List[str]] = []
    lot_number: Optional[List[str]] = []
    servkey: Optional[str] = None
    plate_id: Union[int, None] = None
    plate_sample_no: Union[int, None] = None
    last_update: Optional[str] = None
    global_hash_md5: Optional[str] = None
    ph: Optional[float]=None

class solid_sample_no(BaseModel):
    plate_id: int = None
    sample_no: int = None

    
class gas_sample_no(BaseModel):
    """Return class for liquid sample_no objects."""
    sample_id: int = None
    DUID: Optional[str] = None
    AUID: Optional[str] = None
    source: Union[List[str],str] = None
    volume_mL: Optional[float] = None
    inheritance: Optional[str] = None
    machine: Optional[str] = None
    sample_hash: Optional[str] = None
    action_time: Optional[str] = None
    chemical: Optional[List[str]] = []
    mass: Optional[List[str]] = []
    supplier: Optional[List[str]] = []
    lot_number: Optional[List[str]] = []
    servkey: Optional[str] = None
    plate_id: Union[int, None] = None
    plate_sample_no: Union[int, None] = None
    last_update: Optional[str] = None
    global_hash_md5: Optional[str] = None
    # ph: Optional[float]=None


class samples_inout(BaseModel):
    sample_type: str
    in_out: Optional[str] = "in"
    label: Optional[Union[str, None]]
    solid: Optional[Union[solid_sample_no, None]]
    liquid: Optional[Union[liquid_sample_no, None]]
    gas: Optional[Union[gas_sample_no, None]]
    status: Optional[Union[Union[List[str], str], None]]
    inheritance: Optional[Union[str, None]]
    machine: Optional[Union[str, None]]


class sample_assembly(BaseModel):
    pass


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
    
