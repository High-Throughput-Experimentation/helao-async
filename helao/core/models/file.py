"""Models describing HLO file headers, file connections, and file metadata."""

__all__ = ["HloFileGroup", "HloHeaderModel", "FileConnParams", "FileConn", "FileInfo"]

from copy import deepcopy
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator

from helao.core.helaodict import HelaoDict
from helao.core.version import get_hlo_version

from .run_use import RunUse


class HloFileGroup(str, Enum):
    """Buckets used to route a file to either HELAO or auxiliary storage.

    Members:
        aux_files: Files shipped alongside but not part of the HLO dataset.
        helao_files: Standard HELAO-managed data files.
    """

    aux_files = "aux_files"
    helao_files = "helao_files"


class HloHeaderModel(BaseModel, HelaoDict):
    """YAML header block written at the top of every HLO file.

    Attributes:
        hlo_version (Optional[str]): HELAO version stamped at construction.
        action_name (Optional[str]): Name of the action that owns the file.
        column_headings (list[str]): Column names for tabular payloads.
        optional (Optional[dict]): Instrument- or server-specific extra fields.
        epoch_ns (Optional[int]): Reference timestamp in nanoseconds since epoch.
    """

    hlo_version: Optional[str] = Field(default_factory=get_hlo_version)
    action_name: Optional[str] = None
    column_headings: list[str] = Field(default=[])
    # this can hold instrument/server specific optional header
    # entries
    optional: Optional[dict] = Field(default={})
    epoch_ns: Optional[int] = None


class FileConnParams(BaseModel, HelaoDict):
    """Parameters describing one file connection for an action.

    Attributes:
        file_conn_key (UUID): Required key identifying this connection
            (e.g. sample label or action UUID when only one file is produced).
        sample_global_labels (list[str]): Global labels of samples associated with the file.
        json_data_keys (list[str]): JSON data keys written to the file.
        file_type (str): File type tag (default ``"helao__file"``).
        file_group (Optional[HloFileGroup]): Which storage bucket to route the file to.
        file_name (Optional[str]): Output file name; `None` autogenerates one.
        hloheader (Optional[HloHeaderModel]): Header to prepend to the file.
    """

    # we require a file conn key
    # cannot be uuid 'object' as we might have more then one file
    # either use sample_label, or str(action_uuid) (if only one file etc
    file_conn_key: UUID

    # but samples are optional
    # only need the global label, but not the full sample basemodel
    sample_global_labels: list[str] = Field(default=[])
    json_data_keys: list[str] = Field(default=[])
    # type of file
    file_type: str = "helao__file"
    file_group: Optional[HloFileGroup] = HloFileGroup.helao_files
    # None will trigger autogeneration of a file name
    file_name: Optional[str] = None
    # the header of the hlo file as dict (will be written as yml)
    hloheader: Optional[HloHeaderModel] = Field(default_factory=HloHeaderModel)


class FileConn(BaseModel, HelaoDict):
    """Open file connection tracked by `Base` for streaming HLO output.

    Attributes:
        params (FileConnParams): Static parameters describing the connection.
        added_hlo_separator (bool): True once the HLO header/data separator has been written.
        file (Optional[object]): Underlying file handle (or `None` when closed).
    """

    params: FileConnParams
    added_hlo_separator: bool = False
    # holds the file reference
    file: Optional[object] = None

    class Config:
        """Pydantic config allowing the raw file handle in `file`."""

        arbitrary_types_allowed = True

    def reset_file_conn(self):
        """Clear the file handle and separator flag, leaving params intact."""
        self.added_hlo_separator = False
        self.file = None

    def deepcopy(self) -> "FileConn":
        """Return a copy with params/flags duplicated but `file` reset to None."""
        newfileconn = FileConn(
            params=deepcopy(self.params),
            added_hlo_separator=deepcopy(self.added_hlo_separator),
            file=None,
        )
        return newfileconn

    @validator("file")
    def validate_file(cls, v):
        """Pass-through validator for the `file` field."""
        return v


class FileInfo(BaseModel, HelaoDict):
    """Metadata record describing one file produced by an action.

    Attributes:
        file_type (Optional[str]): File type tag.
        file_name (Optional[str]): File name on disk.
        data_keys (list[str]): Data keys present in the file.
        sample (list[str]): Sample labels associated with the file.
        action_uuid (Optional[UUID]): UUID of the producing action.
        run_use (Optional[RunUse]): Intended use of the file's data.
        nosync (bool): True to exclude the file from data sync.
    """

    action_uuid: Optional[UUID] = None
    run_use: Optional[RunUse] = None
    sample: list[str] = Field(default=[])
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    data_keys: list[str] = Field(default=[])
    nosync: bool = False
