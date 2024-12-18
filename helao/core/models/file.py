__all__ = ["HloFileGroup", "HloHeaderModel", "FileConnParams", "FileConn", "FileInfo"]

from enum import Enum
from typing import List, Optional, Dict
from pydantic import BaseModel, Field, validator
from uuid import UUID
from copy import deepcopy

from helao.core.version import get_hlo_version
from helao.core.models.run_use import RunUse
from helao.core.helaodict import HelaoDict


class HloFileGroup(str, Enum):
    aux_files = "aux_files"
    helao_files = "helao_files"


class HloHeaderModel(BaseModel, HelaoDict):
    hlo_version: Optional[str] = Field(default_factory=get_hlo_version)
    action_name: Optional[str] = None
    column_headings: List[str] = Field(default=[])
    # this can hold instrument/server specific optional header
    # entries
    optional: Optional[Dict] = Field(default={})
    epoch_ns: Optional[float] = None


class FileConnParams(BaseModel, HelaoDict):
    # we require a file conn key
    # cannot be uuid 'object' as we might have more then one file
    # either use sample_label, or str(action_uuid) (if only one file etc
    file_conn_key: UUID

    # but samples are optional
    # only need the global label, but not the full sample basemodel
    sample_global_labels: List[str] = Field(default=[])
    json_data_keys: List[str] = Field(default=[])
    # type of file
    file_type: str = "helao__file"
    file_group: Optional[HloFileGroup] = HloFileGroup.helao_files
    # None will trigger autogeneration of a file name
    file_name: Optional[str] = None
    # the header of the hlo file as dict (will be written as yml)
    hloheader: Optional[HloHeaderModel] = HloHeaderModel()


class FileConn(BaseModel, HelaoDict):
    """This is an internal BaseModel for Base which will hold all
    file connections.
    """

    params: FileConnParams
    added_hlo_separator: bool = False
    # holds the file reference
    file: Optional[object] = None

    class Config:
        arbitrary_types_allowed = True

    def reset_file_conn(self):
        self.added_hlo_separator = False
        self.file = None

    def deepcopy(self):
        newfileconn = FileConn(
            params=deepcopy(self.params), added_hlo_separator=deepcopy(self.added_hlo_separator), file=None
        )
        return newfileconn

    @validator("file")
    def validate_file(cls, v):
        return v


class FileInfo(BaseModel, HelaoDict):
    file_type: Optional[str] = None
    file_name: Optional[str] = None
    data_keys: List[str] = Field(default=[])
    sample: List[str] = Field(default=[])
    action_uuid: Optional[UUID] = None
    run_use: Optional[RunUse] = None
    nosync: bool = False
