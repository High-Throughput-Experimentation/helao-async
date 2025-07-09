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
    """
    Minimal model for representing an experiment in the HELAO system.

    Attributes:
        experiment_uuid (Optional[UUID]): Unique identifier for the experiment.
        experiment_name (Optional[str]): Name of the experiment.
        experiment_output_dir (Optional[Path]): Directory where experiment output is stored.
        orch_key (Optional[str]): Orchestrator key for tracking.
        orch_host (Optional[str]): Hostname of the orchestrator.
        orch_port (Optional[int]): Port of the orchestrator.
        data_request_id (Optional[UUID]): UUID for a data request associated with the experiment.
    """
    experiment_uuid: Optional[UUID] = None
    experiment_name: Optional[str] = None
    experiment_output_dir: Optional[Path] = None
    orch_key: Optional[str] = None
    orch_host: Optional[str] = None
    orch_port: Optional[int] = None
    data_request_id: Optional[UUID] = None


class ExperimentTemplate(BaseModel, HelaoDict):
    """
    Template model for defining an experiment in the HELAO system.

    Attributes:
        experiment_name (Optional[str]): Name of the experiment.
        experiment_params (dict): Parameters for the experiment.
        data_request_id (Optional[UUID]): UUID for a data request associated with the experiment.
        from_global_exp_params (dict): Parameters received from global experiment context.
    """
    experiment_name: Optional[str] = None
    experiment_params: dict = {}
    data_request_id: Optional[UUID] = None
    from_global_exp_params: dict = {}


class ExperimentModel(ExperimentTemplate):
    """
    Comprehensive model for representing a full experiment in the HELAO system.

    Attributes:
        hlo_version (Optional[str]): HELAO version string.
        orchestrator (MachineModel): Orchestrator server information.
        access (Optional[str]): Access type (e.g., 'hte').
        dummy (bool): If True, experiment is a dummy/test experiment.
        simulation (bool): If True, experiment is a simulation.
        run_type (Optional[str]): Type of run (e.g., experiment, calibration).
        sequence_uuid (Optional[UUID]): UUID of the associated sequence.
        experiment_uuid (Optional[UUID]): Unique identifier for the experiment.
        experiment_timestamp (Optional[datetime]): Timestamp when the experiment was created.
        experiment_status (List[HloStatus]): List of status updates for the experiment.
        experiment_output_dir (Optional[Path]): Directory where experiment output is stored.
        experiment_codehash (Optional[str]): Code hash for reproducibility.
        experiment_label (Optional[str]): Label for the experiment.
        planned_actions (list): List of planned actions for the experiment.
        dispatched_actions_abbr (List[ShortActionModel]): List of dispatched action summaries.
        samples_in (List[Sample]): Input samples for the experiment.
        samples_out (List[Sample]): Output samples from the experiment.
        files (List[FileInfo]): Files generated or used by the experiment.
        process_list (List[UUID]): List of process UUIDs associated with the experiment.
        process_order_groups (Dict[int, List[int]]): Mapping of process group indices to action orders.
        data_request_id (Optional[UUID]): UUID for a data request associated with the experiment.
        orch_key (Optional[str]): Orchestrator key for tracking.
        orch_host (Optional[str]): Hostname of the orchestrator.
        orch_port (Optional[int]): Port of the orchestrator.
        sync_data (bool): If True, synchronize data after experiment.
        campaign_name (Optional[str]): Name of the campaign.
    """
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
