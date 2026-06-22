"""Pydantic models for the in-flight data payloads produced by actions."""

__all__ = ["DataModel", "DataPackageModel"]

from typing import List, Dict, Optional
from uuid import UUID
from pydantic import BaseModel, Field

from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.helao_dict import HelaoDict
from helao.framework.models.errors import ErrorCodes


class DataModel(BaseModel, HelaoDict):
    """A batch of action data keyed by file-connection UUID.

    Attributes:
        data (Dict[UUID, dict]): Per-file payloads keyed by `file_conn_key`.
        errors (List[ErrorCodes]): Errors raised while producing this batch.
        status (Optional[HloStatus]): Current status of the data stream.
    """

    # data is contained in a dict and keyed by file_conn_key
    data: Dict[UUID, dict] = Field(default_factory=dict)
    errors: List[ErrorCodes] = Field(default_factory=list)
    status: Optional[HloStatus] = HloStatus.active


class DataPackageModel(BaseModel, HelaoDict):
    """An action-tagged envelope wrapping a `DataModel` for transport.

    Attributes:
        action_uuid (UUID): UUID of the action that produced the data.
        action_name (str): Name of the source action endpoint.
        datamodel (DataModel): The wrapped per-file data batch.
        errors (List[ErrorCodes]): Envelope-level errors.
    """

    action_uuid: UUID
    action_name: str
    datamodel: DataModel
    errors: List[ErrorCodes] = Field(default_factory=list)
