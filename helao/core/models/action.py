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
from helao.core.models.action_start_condition import ActionStartCondition


class ShortActionModel(BaseModel, HelaoDict):
    """
    Minimal model for representing an action in the HELAO system.

    Attributes:
        hlo_version (Optional[str]): HELAO version string.
        action_uuid (Optional[UUID]): Unique identifier for the action.
        action_output_dir (Optional[Path]): Directory where action output is stored.
        action_actual_order (Optional[int]): Actual order of the action in execution.
        orch_submit_order (Optional[int]): Order in which the orchestrator submitted the action.
        action_server (MachineModel): Server on which the action is executed.
        orch_key (Optional[str]): Orchestrator key for tracking.
        orch_host (Optional[str]): Hostname of the orchestrator.
        orch_port (Optional[int]): Port of the orchestrator.
    """
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
    """
    Comprehensive model for representing a full action in the HELAO system.

    Attributes:
        orchestrator (MachineModel): Orchestrator server information.
        access (str): Access type (e.g., 'hte').
        dummy (bool): If True, action is a dummy/test action.
        simulation (bool): If True, action is a simulation.
        run_type (Optional[str]): Type of run (e.g., experiment, calibration).
        run_use (Optional[RunUse]): Purpose of the run (e.g., data, calibration).
        experiment_uuid (Optional[UUID]): UUID of the associated experiment.
        experiment_timestamp (Optional[datetime]): Timestamp of the experiment.
        action_timestamp (Optional[datetime]): Timestamp when the action was created.
        action_status (List[HloStatus]): List of status updates for the action.
        action_order (Optional[int]): Intended order of the action.
        action_retry (Optional[int]): Number of retries for the action.
        action_split (Optional[int]): Split index for parallelized actions.
        action_name (Optional[str]): Name of the action.
        action_sub_name (Optional[str]): Sub-name or variant of the action.
        action_abbr (Optional[str]): Abbreviation for the action.
        action_params (dict): Parameters for the action.
        action_output (dict): Output data from the action.
        action_etc (Optional[float]): Expected time to completion (seconds).
        action_codehash (Optional[str]): Code hash for reproducibility.
        parent_action_uuid (Optional[UUID]): UUID of the parent action.
        child_action_uuid (Optional[UUID]): UUID of the child action.
        samples_in (List[Sample]): Input samples for the action.
        samples_out (List[Sample]): Output samples from the action.
        files (List[FileInfo]): Files generated or used by the action.
        manual_action (bool): If True, action is performed manually.
        nonblocking (bool): If True, action does not block execution.
        exec_id (Optional[str]): Execution identifier.
        technique_name (Optional[Union[str, list]]): Name(s) of the technique used.
        process_finish (bool): If True, marks the end of a process group.
        process_contrib (List[ProcessContrib]): Contributions to the process.
        error_code (Optional[ErrorCodes]): Error code if the action failed.
        process_uuid (Optional[UUID]): UUID of the process this action belongs to.
        data_request_id (Optional[UUID]): UUID for a data request.
        sync_data (bool): If True, synchronize data after action.
        campaign_name (Optional[str]): Name of the campaign.
        start_condition (ActionStartCondition): Condition to start the action.
        save_act (bool): If True, save the action record.
        save_data (bool): If True, save the action's data.
        aux_file_paths (List[Path]): Additional file paths related to the action.
        from_global_act_params (dict): Parameters received from global context.
        to_global_params (Union[list, dict]): Parameters to pass to global context.
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
    # not in ActionModel:
    start_condition: ActionStartCondition = ActionStartCondition.wait_for_all
    save_act: bool = True  # default should be true
    save_data: bool = True  # default should be true
    aux_file_paths: List[Path] = Field(default=[])
    from_global_act_params: dict = {}
    to_global_params: Union[list, dict] = []

    @property
    def url(self):
        return f"http://{self.action_server.hostname}:{self.action_server.port}/{self.action_server.server_name}/{self.action_name}"
