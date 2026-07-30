"""Pydantic models describing sequences (the top-level orchestrator run unit)."""

__all__ = ["ShortSequenceModel", "SequenceModel"]

from datetime import datetime
from typing import Optional
from uuid import UUID
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .hlostatus import HloStatus
from .status_transitions import guarded_append, guarded_replace, guarded_reset
from .experiment import (
    ShortExperimentModel,
)
from .file import FileInfo
from .machine import MachineModel

from helao.core.version import get_hlo_version
from helao.core.helaodict import HelaoDict


class ShortSequenceModel(BaseModel, HelaoDict):
    """Lightweight definition of a sequence as authored by the operator.

    Attributes:
        sequence_name (Optional[str]): Name of the sequence.
        sequence_params (dict): Parameters supplied to the sequence.
        sequence_label (Optional[str]): Label for the sequence; default ``"noLabel"``.
        sequence_comment (Optional[str]): Free-form comment.
        planned_experiments (list[ShortExperimentModel]): Experiments planned by the sequence.
        run_type (Optional[str]): Run-type/instrument label.
        campaign_name (Optional[str]): Campaign label.
        campaign_uuid (Optional[UUID]): Campaign UUID.
        run_id (Optional[UUID]): Run identifier.
        run_sequence_parameter_variable (Optional[list[str]]): Variables the run wires through.
        from_global_seq_params (dict): Params injected from the global sequence context.
    """

    # validate_assignment coerces str->UUID on attribute assignment (not just at
    # construction) so ``seq.campaign_uuid = "<uuid-str>"`` stores a real UUID.
    model_config = ConfigDict(validate_assignment=True)

    sequence_name: Optional[str] = None
    sequence_params: dict = {}
    sequence_label: Optional[str] = "noLabel"
    sequence_comment: Optional[str] = None
    planned_experiments: list[ShortExperimentModel] = Field(
        default=[]
    )  # populated by operator using sequence library funcs
    run_type: Optional[str] = None

    @field_validator("planned_experiments", mode="before")
    @classmethod
    def _coerce_planned_experiments(cls, v):
        if isinstance(v, list):
            return [
                item.model_dump() if isinstance(item, BaseModel) else item for item in v
            ]
        return v

    campaign_name: Optional[str] = None
    campaign_uuid: Optional[UUID] = None
    run_id: Optional[UUID] = None
    run_sequence_parameter_variable: Optional[list[str]] = None
    from_global_seq_params: dict = {}


class SequenceModel(ShortSequenceModel):
    """Full record of a sequence executed by the orchestrator.

    Extends `ShortSequenceModel` with identity, status, code provenance,
    dispatched experiment history, and global parameter snapshots.

    Attributes:
        hlo_version (Optional[str]): HELAO version stamped at construction.
        access (Optional[str]): Access tier identifier (e.g. ``"hte"``).
        dummy (bool): True if this is a dummy/test sequence.
        simulation (bool): True if the sequence ran against simulated drivers.
        sequence_uuid (Optional[UUID]): Unique identifier for the sequence.
        sequence_timestamp (Optional[datetime]): Creation timestamp.
        sequence_status (list[HloStatus]): Accumulated status flags.
        sequence_output_dir (Optional[Path]): Output directory.
        sequence_codehash (Optional[str]): Git hash of the sequence source.
        sequence_codepath (Optional[str]): Source file path.
        sequence_funcname (Optional[str]): Implementing function name.
        sequence_finished_timestamp (Optional[datetime]): When the sequence finished.
        files (list[FileInfo]): Files produced.
        aux_files (list[str]): Auxiliary file paths.
        data_request_id (Optional[UUID]): Optional data-request linkage.
        orchestrator (MachineModel): Owning orchestrator.
        dispatched_experiments_abbr (list[ShortExperimentModel]): Short records of dispatched experiments.
        sync_data (bool): True to ship sequence data via the syncer.
        manual_action (bool): True if the sequence contains manual actions.
        initial_global_params (dict): Snapshot of global params at start.
        finished_global_params (dict): Snapshot of global params at end.
    """

    hlo_version: Optional[str] = Field(default_factory=get_hlo_version)
    access: Optional[str] = "hte"
    dummy: bool = False
    simulation: bool = False
    sequence_uuid: Optional[UUID] = None
    sequence_timestamp: Optional[datetime] = None
    sequence_status: list[HloStatus] = Field(default=[])
    sequence_output_dir: Optional[Path] = None
    sequence_codehash: Optional[str] = None
    sequence_codepath: Optional[str] = None
    sequence_funcname: Optional[str] = None
    sequence_finished_timestamp: Optional[datetime] = None
    files: list[FileInfo] = Field(default=[])
    aux_files: list[str] = Field(default=[])
    data_request_id: Optional[UUID] = None
    orchestrator: MachineModel = MachineModel()
    dispatched_experiments_abbr: list[ShortExperimentModel] = Field(
        default=[]
    )  # list of completed experiments (abbreviated) from dispatched_experiments (premodels.py)

    @field_validator("dispatched_experiments_abbr", mode="before")
    @classmethod
    def _coerce_dispatched_experiments(cls, v):
        if isinstance(v, list):
            return [
                item.model_dump() if isinstance(item, BaseModel) else item for item in v
            ]
        return v

    sync_data: bool = True
    manual_action: bool = False
    initial_global_params: dict = Field(default={})
    finished_global_params: dict = Field(default={})

    def append_sequence_status(self, s: HloStatus) -> None:
        """Guarded append onto ``sequence_status`` (see status_transitions.guarded_append)."""
        guarded_append(
            self.sequence_status,
            s,
            owner=f"sequence {self.sequence_uuid}/{self.sequence_name}",
        )

    def replace_sequence_status(self, old: HloStatus, new: HloStatus) -> None:
        """Guarded swap-or-append onto ``sequence_status`` (see status_transitions.guarded_replace)."""
        guarded_replace(
            self.sequence_status,
            old,
            new,
            owner=f"sequence {self.sequence_uuid}/{self.sequence_name}",
        )

    def reset_sequence_status(self, *statuses: HloStatus) -> None:
        """Guarded wholesale reset of ``sequence_status`` (see status_transitions.guarded_reset)."""
        guarded_reset(
            self.sequence_status,
            statuses,
            owner=f"sequence {self.sequence_uuid}/{self.sequence_name}",
        )
