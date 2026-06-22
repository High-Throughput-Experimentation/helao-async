"""Pydantic models describing a process (a grouped collection of actions)."""

__all__ = [
    "ProcessModel",
    "ShortProcessModel",
]

from datetime import datetime
from typing import List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field

from helao.framework.models.sample import (
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
    SampleModel,
)
from helao.framework.models.action import ShortActionModel
from helao.framework.models.file import FileInfo
from helao.framework.models.machine import MachineModel
from helao.framework.support.version import get_hlo_version
from helao.framework.models.helao_dict import HelaoDict
from helao.framework.models.run_use import RunUse


class ShortProcessModel(BaseModel, HelaoDict):
    """Minimal identifying record for a process.

    Attributes:
        hlo_version (Optional[str]): HELAO version stamped at construction.
        process_uuid (Optional[UUID]): Unique identifier for the process.
    """

    hlo_version: Optional[str] = Field(default_factory=get_hlo_version)
    process_uuid: Optional[UUID] = None


class ProcessModel(ShortProcessModel):
    """Full record of a process: a grouping of actions sharing a context.

    Aggregates the actions, samples, and files of a process group identified
    by `process_finish` on its terminating action.

    Attributes:
        sequence_uuid (Optional[UUID]): UUID of the enclosing sequence.
        experiment_uuid (Optional[UUID]): UUID of the enclosing experiment.
        orchestrator (MachineModel): Orchestrator that owned the process.
        access (str): Access tier identifier (e.g. ``"hte"``).
        dummy (bool): True if this is a dummy/test process.
        simulation (bool): True if the process was a simulation.
        technique_name (Optional[str]): Name of the technique applied.
        run_type (Optional[str]): Instrument/run-type label.
        run_use (Optional[RunUse]): How the produced data is used.
        process_timestamp (Optional[datetime]): Process start timestamp.
        process_params (Optional[dict]): Parameters captured for the process.
        process_group_index (Optional[int]): Index of this process within its group.
        data_request_id (Optional[UUID]): Optional data-request linkage.
        dispatched_actions_abbr (List[ShortActionModel]): Short records for contributing actions.
        samples_in (List): Input samples (union of sample types).
        samples_out (List): Output samples (union of sample types).
        files (List[FileInfo]): Files associated with the process.
        campaign_name (Optional[str]): Campaign label.
        campaign_uuid (Optional[UUID]): Campaign UUID.
        run_id (Optional[UUID]): Run identifier.
    """

    sequence_uuid: Optional[UUID] = None
    experiment_uuid: Optional[UUID] = None
    orchestrator: MachineModel = Field(default_factory=MachineModel)
    access: str = "hte"
    dummy: bool = False
    simulation: bool = False
    technique_name: Optional[str] = None
    run_type: Optional[str] = None
    run_use: Optional[RunUse] = RunUse.data
    process_timestamp: Optional[datetime] = None
    process_params: Optional[dict] = Field(default_factory=dict)
    process_group_index: Optional[int] = None
    data_request_id: Optional[UUID] = None
    dispatched_actions_abbr: List[ShortActionModel] = Field(default_factory=list)
    samples_in: List[
        Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample, SampleModel]
    ] = Field(default_factory=list)
    samples_out: List[
        Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample, SampleModel]
    ] = Field(default_factory=list)
    files: List[FileInfo] = Field(default_factory=list)
    campaign_name: Optional[str] = None
    campaign_uuid: Optional[UUID] = None
    run_id: Optional[UUID] = None
