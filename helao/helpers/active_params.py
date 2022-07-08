__all__ = ["ActiveParams"]

from typing import List, Dict
from pydantic import BaseModel, Field, validator
from uuid import UUID


from helaocore.models.file import FileConnParams

from helao.helpers.premodels import Action
from helaocore.helaodict import HelaoDict


class ActiveParams(BaseModel, HelaoDict):
    # the Action object for this action
    action: Action
    # a dict keyed by file_conn_key of FileConnParams
    # for all files of active
    file_conn_params_dict: Dict[UUID, FileConnParams] = Field(default_factory=dict)
    aux_listen_uuids: List[UUID] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True

    @validator("action")
    def validate_action(cls, v):
        return v
