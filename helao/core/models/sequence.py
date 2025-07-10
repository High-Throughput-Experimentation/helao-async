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
    """
    Template model for defining a sequence in the HELAO system.

    Attributes:
        sequence_name (Optional[str]): Name of the sequence.
        sequence_params (dict): Parameters for the sequence.
        sequence_label (Optional[str]): Label for the sequence.
        planned_experiments (List[ExperimentTemplate]): List of planned experiments in the sequence.
        from_global_seq_params (dict): Parameters received from global sequence context.
    """
    sequence_name: Optional[str] = None
    sequence_params: dict = {}
    sequence_label: Optional[str] = "noLabel"
    planned_experiments: List[ExperimentTemplate] = Field(
        default=[]
    )  # populated by operator using sequence library funcs
    campaign_name: Optional[str] = None
    campaign_uuid: Optional[UUID] = None
    campaign_sequence_parameter_variable: Optional[List[str]] = None
    from_global_seq_params: dict = {} 

class SequenceModel(SequenceTemplate):
    """
    Comprehensive model for representing a full sequence in the HELAO system.

    Attributes:
        hlo_version (Optional[str]): HELAO version string.
        access (Optional[str]): Access type (e.g., 'hte').
        dummy (bool): If True, sequence is a dummy/test sequence.
        simulation (bool): If True, sequence is a simulation.
        sequence_uuid (Optional[UUID]): Unique identifier for the sequence.
        sequence_timestamp (Optional[datetime]): Timestamp when the sequence was created.
        sequence_status (List[HloStatus]): List of status updates for the sequence.
        sequence_output_dir (Optional[Path]): Directory where sequence output is stored.
        sequence_codehash (Optional[str]): Code hash for reproducibility.
        sequence_comment (Optional[str]): Comment or description for the sequence.
        data_request_id (Optional[UUID]): UUID for a data request associated with the sequence.
        orchestrator (MachineModel): Orchestrator server information.
        dispatched_experiments_abbr (List[ShortExperimentModel]): List of dispatched experiment summaries.
        sync_data (bool): If True, synchronize data after sequence.
        campaign_name (Optional[str]): Name of the campaign.
        manual_action (bool): If True, sequence contains manual actions.
    """
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
    manual_action: bool = False
