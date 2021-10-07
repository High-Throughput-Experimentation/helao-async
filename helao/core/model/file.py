
__all__ = ["PrcFile",
           "PrgFile"]

from typing import Optional, Union
from pydantic import BaseModel

import helao.core.server.version as version

class PrcFile(BaseModel):
    hlo_version: str = version.hlo_version
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

    
class PrgFile(BaseModel):
    hlo_version: str = version.hlo_version
    orchestrator: str
    access: str
    process_group_uuid: str
    process_group_timestamp: str
    process_group_label: str
    technique_name: str
    sequence_name: str
    sequence_params: Union[dict, None] = None
    sequence_model: Union[dict, None] = None