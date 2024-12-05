__all__ = [
    "ProcessModel",
    "ShortProcessModel",
]

from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field

from helao.core.models.sample import SampleUnion
from helao.core.models.action import ShortActionModel
from helao.core.models.file import FileInfo
from helao.core.models.machine import MachineModel
from helao.core.version import get_hlo_version
from helao.core.helaodict import HelaoDict
from helao.core.models.run_use import RunUse


class ShortProcessModel(BaseModel, HelaoDict):
    hlo_version: Optional[str] = Field(default_factory=get_hlo_version)
    process_uuid: Optional[UUID] = None


class ProcessModel(ShortProcessModel):
    sequence_uuid: Optional[UUID] = None
    experiment_uuid: Optional[UUID] = None
    orchestrator: MachineModel = MachineModel()
    access: Optional[str] = "hte"
    dummy: bool = False
    simulation: bool = False
    technique_name: Optional[str] = None
    run_type: Optional[str] = None
    run_use: Optional[RunUse] = "data"
    process_timestamp: Optional[datetime] = None
    process_params: Optional[dict] = {}
    process_group_index: Optional[int] = None
    data_request_id: Optional[UUID] = None
    action_list: List[ShortActionModel] = Field(default=[])
    samples_in: List[SampleUnion] = Field(default=[])
    samples_out: List[SampleUnion] = Field(default=[])
    files: List[FileInfo] = Field(default=[])
    # TODO: created assembly global label, created solid...
