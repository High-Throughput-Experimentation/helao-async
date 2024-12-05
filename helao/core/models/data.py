__all__ = ["DataModel", "DataPackageModel"]

from typing import List, Dict, Optional
from uuid import UUID
from pydantic import BaseModel, Field

from helao.core.models.hlostatus import HloStatus
from helao.core.helaodict import HelaoDict
from helao.core.error import ErrorCodes


class DataModel(BaseModel, HelaoDict):
    # data is contained in a dict and keyed by file_conn_key
    data: Dict[UUID, dict] = Field(default={})
    errors: List[ErrorCodes] = Field(default=[])
    status: Optional[HloStatus] = HloStatus.active


class DataPackageModel(BaseModel, HelaoDict):
    action_uuid: UUID
    action_name: str
    datamodel: DataModel
    errors: List[ErrorCodes] = Field(default=[])
    # status: Optional[HloStatus] = None
