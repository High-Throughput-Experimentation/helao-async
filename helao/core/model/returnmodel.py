
__all__ = ["ReturnProcessGroup",
           "ReturnProcessGroupList",
           "ReturnProcess",
           "ReturnProcessList",
           "ReturnFinishedProcess",
           "ReturnRunningProcess"]


from pydantic import BaseModel
from typing import Union, List, Optional


class ReturnProcessGroup(BaseModel):
    """Return class for queried cProcess_group objects."""
    index: int
    uid: Union[str, None]
    label: str
    sequence: str
    pars: dict
    access: str


class ReturnProcessGroupList(BaseModel):
    """Return class for queried cProcess_group list."""
    process_groups: List[ReturnProcessGroup]


class ReturnProcess(BaseModel):
    """Return class for queried process objects."""
    index: int
    uid: Union[str, None]
    server: str
    process: str
    pars: dict
    preempt: int


class ReturnProcessList(BaseModel):
    """Return class for queried process list."""
    processes: List[ReturnProcess]


class ReturnFinishedProcess(BaseModel):
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


class ReturnRunningProcess(BaseModel):
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
    
    
