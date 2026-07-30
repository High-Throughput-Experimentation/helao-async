"""Pydantic container describing the parameters of an in-flight action."""

__all__ = ["ActiveParams"]

from pydantic import BaseModel, Field, validator
from uuid import UUID


from helao.core.models.file import FileConnParams

from .premodels import Action
from helao.core.helaodict import HelaoDict


class ActiveParams(BaseModel, HelaoDict):
    """Bundle of state passed to :class:`Base.contain_action` when an action becomes active.

    Attributes:
        action: The :class:`Action` instance currently being executed.
        file_conn_params_dict: Per-file connection parameters keyed by the
            file connection UUID; one entry per output file the action will
            produce.
        aux_listen_uuids: UUIDs of auxiliary actions whose status/data
            streams should be subscribed to alongside the primary action.
    """

    # the Action object for this action
    action: Action
    # a dict keyed by file_conn_key of FileConnParams
    # for all files of active
    file_conn_params_dict: dict[UUID, FileConnParams] = Field(default={})
    aux_listen_uuids: list[UUID] = Field(default=[])

    class Config:
        arbitrary_types_allowed = True

    @validator("action")
    def validate_action(cls, v):
        """Pydantic validator hook for the ``action`` field; returns the value unchanged."""
        return v
