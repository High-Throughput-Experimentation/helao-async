__all__ = ["AnalysisModel", "ShortAnalysisModel", "AnalysisDataModel", "AnalysisOutputModel"]

from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional, Union, Dict
from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime

from helao.core.models.run_use import RunUse
from helao.core.version import get_hlo_version
from helao.core.helaodict import HelaoDict
from helao.core.models.s3locator import S3Locator


class ShortAnalysisModel(BaseModel, HelaoDict):
    hlo_version: Optional[str] = Field(default_factory=get_hlo_version)
    analysis_uuid: Optional[UUID] = None
    analysis_timestamp: Optional[datetime] = None
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.analysis_timestamp is None:
            self.analysis_timestamp = datetime.now()


class AnalysisDataModel(BaseModel, HelaoDict):
    action_uuid: UUID
    run_use: RunUse = "data"
    raw_data_path: str
    global_sample_label: Optional[str] = None
    composition: Optional[dict] = None
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    data_keys: List[str] = Field(default=[])


class AnalysisOutputModel(BaseModel, HelaoDict):
    analysis_output_path: S3Locator
    content_type: str
    content_encoding: Optional[str] = None
    output_keys: Optional[List[str]] = None
    output_name: Optional[str] = None
    output: Optional[Dict[str, Union[float, str, bool, int, None]]] = None


class AnalysisModel(ShortAnalysisModel):
    access: Optional[str] = "hte"
    dummy: bool = False
    simulation: bool = False
    analysis_name: str
    analysis_params: dict
    analysis_codehash: Optional[str] = None
    global_sample_label: Optional[str] = None
    process_uuid: Optional[UUID] = None
    process_params: Optional[dict] = None
    inputs: List[AnalysisDataModel]
    outputs: List[AnalysisOutputModel]
    data_request_id: Optional[UUID] = None
    # TODO: include run_type, process_timestamp, technique_name


class AnalysisInput(ABC):
    process_params: dict
    
    @abstractmethod
    def get_datamodels(self, *args, **kwargs) -> List[AnalysisDataModel]:
        return NotImplemented