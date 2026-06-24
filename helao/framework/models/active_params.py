"""Pydantic container describing the parameters of an in-flight action."""

__all__ = ["ActiveParams"]

from typing import List, Dict
from pydantic import BaseModel, ConfigDict, Field, field_validator
from uuid import UUID


from helao.framework.models.file import FileConnParams

from helao.framework.models.action import ActionModel
from helao.framework.models.helao_dict import HelaoDict


class ActiveParams(BaseModel, HelaoDict):
    """Bundle of state passed to :class:`Base.contain_action` when an action becomes active.

    Attributes:
        action: The :class:`ActionModel` instance currently being executed.
        file_conn_params_dict: Per-file connection parameters keyed by the
            file connection UUID; one entry per output file the action will
            produce.
        aux_listen_uuids: UUIDs of auxiliary actions whose status/data
            streams should be subscribed to alongside the primary action.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # the Action object for this action
    action: ActionModel
    # a dict keyed by file_conn_key of FileConnParams
    # for all files of active
    file_conn_params_dict: Dict[UUID, FileConnParams] = Field(default_factory=dict)
    aux_listen_uuids: List[UUID] = Field(default_factory=list)

    @field_validator("action")
    @classmethod
    def validate_action(cls, v):
        """Pydantic validator hook for the ``action`` field; returns the value unchanged."""
        return v
