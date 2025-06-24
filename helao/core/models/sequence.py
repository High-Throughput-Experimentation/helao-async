__all__ = ["SequenceTemplate", "SequenceModel"]

from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pathlib import Path

from pydantic import BaseModel, Field

from helao.core.models.hlostatus import HloStatus
from helao.core.models.experiment import (
    ShortExperimentModel,
    ExperimentTemplate,
)
from helao.core.models.machine import MachineModel

from helao.core.version import get_hlo_version
from helao.core.helaodict import HelaoDict


class SequenceTemplate(BaseModel, HelaoDict):
    sequence_name: Optional[str] = None
    sequence_params: dict = {}
    sequence_label: Optional[str] = "noLabel"
    planned_experiments: List[ExperimentTemplate] = Field(
        default=[]
    )  # populated by operator using sequence library funcs
    from_global_params: dict = {}


class SequenceModel(SequenceTemplate):
    hlo_version: Optional[str] = Field(default_factory=get_hlo_version)
    access: Optional[str] = "hte"
    dummy: bool = False
    simulation: bool = False
    sequence_uuid: Optional[UUID] = None
    sequence_timestamp: Optional[datetime] = None
    sequence_status: List[HloStatus] = Field(default=[])
    sequence_output_dir: Optional[Path] = None
    sequence_codehash: Optional[str] = None
    sequence_comment: Optional[str] = None
    data_request_id: Optional[UUID] = None
    orchestrator: MachineModel = MachineModel()
    dispatched_experiments_abbr: List[ShortExperimentModel] = Field(
        default=[]
    )  # list of completed experiments (abbreviated) from dispatched_experiments (premodels.py)
    sync_data: bool = True
    campaign_name: Optional[str] = None
    manual_action: bool = False
