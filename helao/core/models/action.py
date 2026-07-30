"""Pydantic models describing actions dispatched by the orchestrator."""

__all__ = ["ActionModel", "ShortActionModel"]

from datetime import datetime
from typing import Optional, Union
from uuid import UUID
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field

from .hlostatus import HloStatus
from .status_transitions import guarded_append, guarded_replace, guarded_reset
from .process_contrib import ProcessContrib
from .run_use import RunUse
from .sample import SampleUnion
from .file import FileInfo
from .machine import MachineModel
from helao.core.version import get_hlo_version
from helao.core.helaodict import HelaoDict
from helao.core.error import ErrorCodes
from .action_start_condition import ActionStartCondition


class ShortActionModel(BaseModel, HelaoDict):
    """Lightweight summary of a HELAO action.

    Used in places that need an action reference without carrying the full
    `ActionModel` payload (e.g. dispatched-action lists on experiments).

    Attributes:
        hlo_version (Optional[str]): HELAO version stamped at construction.
        action_uuid (Optional[UUID]): Unique identifier for the action.
        action_output_dir (Optional[Path]): Directory holding the action's output files.
        action_actual_order (Optional[int]): Position assigned when the action actually ran.
        orch_submit_order (Optional[int]): Position the orchestrator submitted the action in.
        action_server (MachineModel): Server that owns/executes the action.
        action_comment (Optional[str]): Free-form comment attached to the action.
        orch_key (Optional[str]): Identifier of the orchestrator that owns the action.
        orch_host (Optional[str]): Hostname of the owning orchestrator.
        orch_port (Optional[int]): Port of the owning orchestrator.
    """

    # validate_assignment coerces str->UUID (and other lax coercions) on
    # attribute assignment, not just at construction, so post-construction
    # assignments like ``act.campaign_uuid = "<uuid-str>"`` store a real UUID
    # instead of leaking a str to the pydantic serializer.
    model_config = ConfigDict(validate_assignment=True)

    hlo_version: Optional[str] = Field(default_factory=get_hlo_version)
    action_uuid: Optional[UUID] = None
    action_output_dir: Optional[Path] = None
    action_actual_order: Optional[int] = 0
    orch_submit_order: Optional[int] = 0
    action_server: MachineModel = MachineModel()
    action_comment: Optional[str] = None
    orch_key: Optional[str] = None
    orch_host: Optional[str] = None
    orch_port: Optional[int] = None


class ActionModel(ShortActionModel):
    """Full record of a HELAO action.

    Extends `ShortActionModel` with the parameters, samples, files, status,
    process linkage, and bookkeeping fields persisted for each action run.

    Attributes:
        orchestrator (MachineModel): Orchestrator that dispatched the action.
        access (str): Access tier identifier (e.g. ``"hte"``).
        dummy (bool): True if this is a dummy/test action.
        simulation (bool): True if the action ran against a simulated driver.
        run_type (Optional[str]): Instrument/run-type label from the world config.
        run_use (Optional[RunUse]): How the resulting data is to be used.
        experiment_uuid (Optional[UUID]): UUID of the parent experiment.
        experiment_timestamp (Optional[datetime]): Timestamp of the parent experiment.
        action_timestamp (Optional[datetime]): Timestamp when the action was created.
        action_status (list[HloStatus]): Accumulated status flags for the action.
        action_order (Optional[int]): Intended dispatch order.
        action_retry (Optional[int]): Retry counter.
        action_split (Optional[int]): Split index for parallelized/split actions.
        action_name (Optional[str]): Action endpoint name.
        action_sub_name (Optional[str]): Sub-name or variant.
        action_abbr (Optional[str]): Short label used in file names.
        action_params (dict): Parameters supplied to the action endpoint.
        action_output (dict): Data produced by the action (non-file output).
        action_etc (Optional[float]): Expected time-to-completion in seconds.
        action_codehash (Optional[str]): Git hash of the action's source file.
        action_codepath (Optional[str]): Source file path of the action.
        action_funcname (Optional[str]): Name of the Python function implementing it.
        action_finished_timestamp (Optional[datetime]): When the action completed.
        parent_action_uuid (Optional[UUID]): UUID of the parent action, if any.
        child_action_uuid (Optional[UUID]): UUID of the child action, if any.
        samples_in (list): Input samples (union of sample model types).
        samples_out (list): Output samples (union of sample model types).
        files (list[FileInfo]): Files produced by the action.
        manual_action (bool): True if performed manually rather than dispatched.
        nonblocking (bool): True if the orchestrator does not wait for completion.
        exec_id (Optional[str]): Execution identifier used by the runner.
        technique_name (Optional[Union[str, list]]): Technique(s) associated with the action.
        process_finish (bool): True marks the action as the terminator of a process group.
        process_contrib (list[ProcessContrib]): Fields this action contributes to its process.
        error_code (Optional[ErrorCodes]): Final error code.
        process_uuid (Optional[UUID]): UUID of the enclosing process.
        data_request_id (Optional[UUID]): Optional data-request linkage.
        sync_data (bool): True to ship the action's data via the syncer.
        campaign_name (Optional[str]): Campaign name label.
        campaign_uuid (Optional[UUID]): Campaign UUID.
        run_id (Optional[UUID]): Run identifier.
        start_condition (ActionStartCondition): Gate that must clear before dispatch.
        save_act (bool): True to persist the action YAML record.
        save_data (bool): True to persist data files.
        aux_file_paths (list[Path]): Auxiliary files to ship with the action.
        from_global_act_params (dict): Parameters injected from the global context.
        to_global_params (Union[list, dict]): Parameters to publish to the global context.
    """

    orchestrator: MachineModel = MachineModel()
    access: str = "hte"
    dummy: bool = False
    simulation: bool = False
    run_type: Optional[str] = None
    run_use: Optional[RunUse] = RunUse.data
    experiment_uuid: Optional[UUID] = None
    experiment_timestamp: Optional[datetime] = None
    action_timestamp: Optional[datetime] = None
    action_status: list[HloStatus] = Field(default=[])
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
    action_codepath: Optional[str] = None
    action_funcname: Optional[str] = None
    action_finished_timestamp: Optional[datetime] = None
    parent_action_uuid: Optional[UUID] = None
    child_action_uuid: Optional[UUID] = None
    samples_in: list[SampleUnion] = Field(default=[])
    samples_out: list[SampleUnion] = Field(default=[])
    files: list[FileInfo] = Field(default=[])
    manual_action: bool = False
    nonblocking: bool = False
    exec_id: Optional[str] = None
    technique_name: Optional[Union[str, list]] = None
    process_finish: bool = False
    process_contrib: list[ProcessContrib] = Field(default=[])
    error_code: Optional[ErrorCodes] = ErrorCodes.none
    process_uuid: Optional[UUID] = None
    data_request_id: Optional[UUID] = None
    # process_group_index: Optional[int] = 0 # unnecessary if we rely on process_finish as group terminator
    sync_data: bool = True
    campaign_name: Optional[str] = None
    campaign_uuid: Optional[UUID] = None
    run_id: Optional[UUID] = None
    # not in ActionModel:
    start_condition: ActionStartCondition = ActionStartCondition.wait_for_all
    save_act: bool = True  # default should be true
    save_data: bool = True  # default should be true
    aux_file_paths: list[Path] = Field(default=[])
    from_global_act_params: dict = {}
    to_global_params: Union[list, dict] = []

    @property
    def url(self) -> str:
        """Return the HTTP endpoint URL on the action server for this action."""
        return f"http://{self.action_server.hostname}:{self.action_server.port}/{self.action_server.server_name}/{self.action_name}"

    def append_action_status(self, s: HloStatus) -> None:
        """Guarded append onto ``action_status`` (see status_transitions.guarded_append)."""
        guarded_append(
            self.action_status, s, owner=f"action {self.action_uuid}/{self.action_name}"
        )

    def replace_action_status(self, old: HloStatus, new: HloStatus) -> None:
        """Guarded swap-or-append onto ``action_status`` (see status_transitions.guarded_replace)."""
        guarded_replace(
            self.action_status,
            old,
            new,
            owner=f"action {self.action_uuid}/{self.action_name}",
        )

    def reset_action_status(self, *statuses: HloStatus) -> None:
        """Guarded wholesale reset of ``action_status`` (see status_transitions.guarded_reset)."""
        guarded_reset(
            self.action_status,
            statuses,
            owner=f"action {self.action_uuid}/{self.action_name}",
        )
