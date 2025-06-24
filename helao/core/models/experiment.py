__all__ = ["ExperimentTemplate", "ExperimentModel", "ShortExperimentModel"]

from datetime import datetime
from typing import List, Optional, Dict, Union
from uuid import UUID
from pathlib import Path

from pydantic import BaseModel, Field

from helao.core.models.hlostatus import HloStatus
from helao.core.models.sample import (
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
)
from helao.core.models.action import ShortActionModel
from helao.core.models.file import FileInfo
from helao.core.models.machine import MachineModel

from helao.core.version import get_hlo_version
from helao.core.helaodict import HelaoDict


class ShortExperimentModel(BaseModel, HelaoDict):
    experiment_uuid: Optional[UUID] = None
    experiment_name: Optional[str] = None
    experiment_output_dir: Optional[Path] = None
    orch_key: Optional[str] = None
    orch_host: Optional[str] = None
    orch_port: Optional[int] = None
    data_request_id: Optional[UUID] = None


class ExperimentTemplate(BaseModel, HelaoDict):
    experiment_name: Optional[str] = None
    experiment_params: dict = {}
    data_request_id: Optional[UUID] = None
    from_global_params: dict = {}


class ExperimentModel(ExperimentTemplate):
    hlo_version: Optional[str] = Field(default_factory=get_hlo_version)
    orchestrator: MachineModel = MachineModel()
    access: Optional[str] = "hte"
    dummy: bool = False
    simulation: bool = False
    # name of "instrument": eche, anec, adss etc. defined in world config
    run_type: Optional[str] = None
    sequence_uuid: Optional[UUID] = None
    experiment_uuid: Optional[UUID] = None
    experiment_timestamp: Optional[datetime] = None
    experiment_status: List[HloStatus] = Field(default=[])
    experiment_output_dir: Optional[Path] = None
    experiment_codehash: Optional[str] = None
    experiment_label: Optional[str] = None
    planned_actions: list = []
    dispatched_actions_abbr: List[ShortActionModel] = Field(default=[])
    samples_in: List[
        Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
    ] = Field(default=[])
    samples_out: List[
        Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
    ] = Field(default=[])
    files: List[FileInfo] = Field(default=[])
    process_list: List[UUID] = Field(default=[])  # populated by DB yml_finisher
    process_order_groups: Dict[int, List[int]] = Field(default={})
    data_request_id: Optional[UUID] = None
    orch_key: Optional[str] = None
    orch_host: Optional[str] = None
    orch_port: Optional[int] = None
    sync_data: bool = True
    campaign_name: Optional[str] = None
