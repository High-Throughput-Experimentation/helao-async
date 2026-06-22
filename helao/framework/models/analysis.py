"""Pydantic models describing analyses, their inputs, and their outputs."""

__all__ = [
    "AnalysisModel",
    "ShortAnalysisModel",
    "AnalysisDataModel",
    "AnalysisOutputModel",
]

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field

from helao.framework.models.run_use import RunUse
from helao.framework.models.file import FileInfo
from helao.framework.support.version import get_hlo_version
from helao.framework.models.helao_dict import HelaoDict
from helao.framework.models.s3locator import S3Locator


class ShortAnalysisModel(BaseModel, HelaoDict):
    """Minimal identifying record for an analysis.

    Attributes:
        hlo_version (Optional[str]): HELAO version stamped at construction.
        analysis_uuid (Optional[UUID]): Unique identifier for the analysis.
        analysis_timestamp (Optional[datetime]): When the analysis was created;
            populated with the current time if omitted.
    """

    hlo_version: Optional[str] = Field(default_factory=get_hlo_version)
    analysis_uuid: Optional[UUID] = None
    analysis_timestamp: Optional[datetime] = None

    def __init__(self, *args, **kwargs):
        """Construct the model and default `analysis_timestamp` to now if unset."""
        super().__init__(*args, **kwargs)
        if self.analysis_timestamp is None:
            self.analysis_timestamp = datetime.now()


class AnalysisDataModel(FileInfo):
    """Reference to an action's raw-data payload used as analysis input.

    Extends :class:`~helao.framework.models.file.FileInfo`, inheriting
    ``action_uuid``, ``run_use``, ``sample``, ``file_name``, ``file_type``,
    ``data_keys``, and ``nosync``; ``action_uuid`` is required and ``run_use``
    defaults to :attr:`RunUse.data` for analysis inputs.

    Attributes:
        action_uuid (UUID): UUID of the source action (required here).
        run_use (RunUse): How the source data is being used.
        raw_data_path (str): Storage path to the raw data file.
        global_sample_label (Optional[str]): Global label of the sample, if known.
        composition (Optional[dict]): Optional composition metadata for the sample.
    """

    action_uuid: UUID
    run_use: RunUse = RunUse.data
    raw_data_path: str
    global_sample_label: Optional[str] = None
    composition: Optional[dict] = None


class AnalysisOutputModel(BaseModel, HelaoDict):
    """One output artifact produced by an analysis.

    Attributes:
        analysis_output_path (S3Locator): S3 location of the output artifact.
        content_type (str): MIME or content type of the artifact.
        content_encoding (Optional[str]): Optional content encoding.
        output_type (str): Type tag classifying the output.
        output_keys (Optional[List[str]]): Keys produced by the analysis, if applicable.
        output_name (Optional[str]): Display name for the output.
        output (Optional[Dict[str, ...]]): Inline scalar/structured output values.
    """

    analysis_output_path: S3Locator
    content_type: str
    content_encoding: Optional[str] = None
    output_type: str
    output_keys: Optional[List[str]] = None
    output_name: Optional[str] = None
    output: Optional[Dict[str, Union[float, str, bool, int, list, dict, None]]] = None


class AnalysisModel(ShortAnalysisModel):
    """Full record of an analysis run with its inputs and outputs.

    Attributes:
        access (str): Access tier identifier (e.g. ``"hte"``).
        dummy (bool): True if this is a dummy/test analysis.
        simulation (bool): True if produced from simulated data.
        analysis_name (str): Name of the analysis routine.
        analysis_params (dict): Parameters supplied to the analysis.
        analysis_codehash (Optional[str]): Git hash of the analysis source.
        analysis_codepath (Optional[str]): Source path for the analysis.
        analysis_classname (Optional[str]): Implementing class name.
        analysis_action_uuid (Optional[UUID]): UUID of an action that triggered the analysis.
        global_sample_label (Optional[str]): Global sample label, if relevant.
        process_uuid (Optional[UUID]): Associated process UUID.
        process_params (Optional[dict]): Associated process parameters.
        inputs (List[AnalysisDataModel]): Input data references.
        outputs (List[AnalysisOutputModel]): Output artifacts.
        data_request_id (Optional[UUID]): Optional data-request linkage.
        campaign_name (Optional[str]): Campaign label.
        campaign_uuid (Optional[UUID]): Campaign UUID.
        sequence_uuid (Optional[UUID]): Sequence UUID under which the analysis ran.
    """

    access: str = "hte"
    dummy: bool = False
    simulation: bool = False
    analysis_name: str
    analysis_params: dict
    analysis_codehash: Optional[str] = None
    analysis_codepath: Optional[str] = None
    analysis_classname: Optional[str] = None
    analysis_action_uuid: Optional[UUID] = None
    global_sample_label: Optional[str] = None
    process_uuid: Optional[UUID] = None
    process_params: Optional[dict] = None
    inputs: List[AnalysisDataModel]
    outputs: List[AnalysisOutputModel]
    data_request_id: Optional[UUID] = None
    campaign_name: Optional[str] = None
    campaign_uuid: Optional[UUID] = None
    sequence_uuid: Optional[UUID] = None
    # TODO: include run_type, process_timestamp, technique_name


class AnalysisInput(ABC):
    """Abstract base for objects that supply input data to an analysis.

    Attributes:
        process_params (dict): Process parameters associated with the input.
    """

    process_params: dict

    @abstractmethod
    def get_datamodels(self, *args, **kwargs) -> List[AnalysisDataModel]:
        """Return the `AnalysisDataModel` instances representing this input."""
        return NotImplemented


class AnalysisOutput(BaseModel):
    """Base model for typed analysis output payloads.

    Subclass to add fields specific to a given analysis type.

    Attributes:
        output_type (str): Tag identifying the concrete output flavor.
    """

    output_type: str
