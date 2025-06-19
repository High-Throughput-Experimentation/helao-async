__all__ = ["ActionModel", "ShortActionModel"]

from datetime import datetime
from typing import List, Optional, Union
from uuid import UUID
from pathlib import Path
from pydantic import BaseModel, Field

from helao.core.models.hlostatus import HloStatus
from helao.core.models.process_contrib import ProcessContrib
from helao.core.models.run_use import RunUse
from helao.core.models.sample import (
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
)
from helao.core.models.file import FileInfo
from helao.core.models.machine import MachineModel
from helao.core.version import get_hlo_version
from helao.core.helaodict import HelaoDict
from helao.core.error import ErrorCodes


class ShortActionModel(BaseModel, HelaoDict):
    hlo_version: Optional[str] = Field(default_factory=get_hlo_version)
    action_uuid: Optional[UUID] = None
    action_output_dir: Optional[Path] = None
    action_actual_order: Optional[int] = 0
    orch_submit_order: Optional[int] = 0
    action_server: MachineModel = MachineModel()
    orch_key: Optional[str] = None
    orch_host: Optional[str] = None
    orch_port: Optional[int] = None


class ActionModel(ShortActionModel):
    orchestrator: MachineModel = MachineModel()
    access: str = "hte"
    dummy: bool = False
    simulation: bool = False
    run_type: Optional[str] = None
    run_use: Optional[RunUse] = RunUse.data
    experiment_uuid: Optional[UUID] = None
    experiment_timestamp: Optional[datetime] = None
    action_timestamp: Optional[datetime] = None
    action_status: List[HloStatus] = Field(default=[])
    action_order: Optional[int] = 0
    action_retry: Optional[int] = 0
    action_split: Optional[int] = 0
    action_name: Optional[str] = None
    action_sub_name: Optional[str] = None
    action_abbr: Optional[str] = None
    action_params: dict = Field(default={})
    action_output: dict = Field(default={})
    action_etc: Optional[float] = None  # expected time to completion
    action_codehash: Optional[str] = None
    parent_action_uuid: Optional[UUID] = None
    child_action_uuid: Optional[UUID] = None
    samples_in: List[
        Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
    ] = Field(default=[])
    samples_out: List[
        Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
    ] = Field(default=[])
    files: List[FileInfo] = Field(default=[])
    manual_action: bool = False
    nonblocking: bool = False
    exec_id: Optional[str] = None
    technique_name: Optional[Union[str, list]] = None
    process_finish: bool = False
    process_contrib: List[ProcessContrib] = Field(default=[])
    error_code: Optional[ErrorCodes] = ErrorCodes.none
    process_uuid: Optional[UUID] = None
    data_request_id: Optional[UUID] = None
    # process_group_index: Optional[int] = 0 # unnecessary if we rely on process_finish as group terminator
    sync_data: bool = True
    campaign_name: Optional[str] = None

    @property
    def url(self):
        return f"http://{self.action_server.hostname}:{self.action_server.port}/{self.action_server.server_name}/{self.action_name}"
