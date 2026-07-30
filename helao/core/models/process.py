"""Pydantic models describing a process (a grouped collection of actions)."""

__all__ = [
    "ProcessModel",
    "ShortProcessModel",
]

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field

from .sample import SampleUnion
from .action import ShortActionModel
from .file import FileInfo
from .machine import MachineModel
from helao.core.version import get_hlo_version
from helao.core.helaodict import HelaoDict
from .run_use import RunUse


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
        dispatched_actions_abbr (list[ShortActionModel]): Short records for contributing actions.
        samples_in (list): Input samples (union of sample types).
        samples_out (list): Output samples (union of sample types).
        files (list[FileInfo]): Files associated with the process.
        campaign_name (Optional[str]): Campaign label.
        campaign_uuid (Optional[UUID]): Campaign UUID.
        run_id (Optional[UUID]): Run identifier.
    """

    sequence_uuid: Optional[UUID] = None
    experiment_uuid: Optional[UUID] = None
    orchestrator: MachineModel = MachineModel()
    access: str = "hte"
    dummy: bool = False
    simulation: bool = False
    technique_name: Optional[str] = None
    run_type: Optional[str] = None
    run_use: Optional[RunUse] = RunUse.data
    process_timestamp: Optional[datetime] = None
    process_params: Optional[dict] = {}
    process_group_index: Optional[int] = None
    data_request_id: Optional[UUID] = None
    dispatched_actions_abbr: list[ShortActionModel] = Field(default=[])
    samples_in: list[SampleUnion] = Field(default=[])
    samples_out: list[SampleUnion] = Field(default=[])
    files: list[FileInfo] = Field(default=[])
    campaign_name: Optional[str] = None
    campaign_uuid: Optional[UUID] = None
    run_id: Optional[UUID] = None
