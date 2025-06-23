__all__ = ["SequenceTemplate", "SequenceModel"]

from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pathlib import Path

from pydantic import BaseModel, Field

from helao.core.models.hlostatus import HloStatus
from helao.core.models.experiment import ShortExperimentModel, ExperimentTemplate, ExperimentModel
from helao.core.models.machine import MachineModel

from helao.core.version import get_hlo_version
from helao.core.helaodict import HelaoDict


class SequenceTemplate(BaseModel, HelaoDict):
    sequence_name: Optional[str] = None
    sequence_params: Optional[dict] = {}
    sequence_label: Optional[str] = "noLabel"
    experiment_plan_list: List[ExperimentTemplate] = Field(default=[])  # populated by operator using sequence library funcs


class SequenceModel(SequenceTemplate):
    hlo_version: Optional[str] = Field(default_factory=get_hlo_version)
    access: Optional[str] = 'hte'
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
    experiment_list: List[ShortExperimentModel] = Field(default=[])  # list of completed experiments from experimentmodel_list (premodels.py)
    sync_data: bool = True
    campaign_name: Optional[str] = None
    manual_action: bool = False
    # not in SequenceModel:
    experimentmodel_list: List[ExperimentModel] = (
        []
    )  # running tally of completed experiments
    # allow sequences to inherit parameters from global dict
    from_global_params: dict = {}