__all__ = ["ActiveParams"]

from typing import List, Dict
from pydantic import BaseModel, Field, validator
from uuid import UUID


from helaocore.models.file import FileConnParams

from helao.helpers.premodels import Action
from helaocore.helaodict import HelaoDict


class ActiveParams(BaseModel, HelaoDict):
    """
    ActiveParams is a model that represents the parameters for an active action.

    Attributes:
        action (Action): The Action object for this action.
        file_conn_params_dict (Dict[UUID, FileConnParams]): A dictionary keyed by file_conn_key of FileConnParams for all files of active.
        aux_listen_uuids (List[UUID]): A list of UUIDs for auxiliary listeners.

    Config:
        arbitrary_types_allowed (bool): Allows arbitrary types for model attributes.

    Methods:
        validate_action(cls, v): Validator method for the action attribute.
    """
    # the Action object for this action
    action: Action
    # a dict keyed by file_conn_key of FileConnParams
    # for all files of active
    file_conn_params_dict: Dict[UUID, FileConnParams] = Field(default={})
    aux_listen_uuids: List[UUID] = Field(default=[])

    class Config:
        arbitrary_types_allowed = True

    @validator("action")
    def validate_action(cls, v):
        """
        Validates the given action.

        Args:
            v: The action to be validated.

        Returns:
            The validated action.
        """
        return v
