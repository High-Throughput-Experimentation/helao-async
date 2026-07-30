"""Mixin providing HELAO-aware dict and serialization helpers for pydantic models."""

__all__ = ["HelaoDict"]

import math
import types
from copy import deepcopy
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
from pydantic import BaseModel


# https://stackoverflow.com/a/71389334
def nan2None(obj):
    """Recursively replace NaN float values in a nested dict/list structure with `None`."""
    if isinstance(obj, dict):
        return {k: nan2None(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [nan2None(v) for v in obj]
    elif isinstance(obj, float) and math.isnan(obj):
        return None
    return obj


class HelaoDict:
    """Serialization helpers for HELAO models.

    Provides `as_dict` and `clean_dict` methods that walk a pydantic model's
    attributes and coerce non-JSON-friendly values (numpy scalars, `UUID`,
    `datetime`, `Path`, enums, NaN floats, nested models) into plain Python
    types suitable for YAML/JSON output.
    """

    def _serialize_dict(self, dict_in: dict) -> dict:
        """Serialize each entry of a dict via `_serialize_item`, skipping functions and dunder strings."""
        clean = {}
        for k, v in dict_in.items():
            if not isinstance(v, types.FunctionType) and not (
                isinstance(v, str) and k.startswith("__")
            ):
                # keys can also be UUID, datetime etc
                clean.update({self._serialize_item(val=k): self._serialize_item(val=v)})
        return clean

    def _serialize_item(self, val: Any):
        """Coerce a single value into a JSON/YAML-friendly representation.

        Handles enums, numpy scalars, paths, datetimes, UUIDs, lists/tuples/sets,
        dicts, nested `HelaoDict`/`BaseModel` instances, and rounds floats.

        Raises:
            ValueError: If `val` is of an unsupported type.
        """
        if isinstance(val, Enum):
            # need to be first to catch also str enums
            if isinstance(val, str):
                return val.name
            else:
                return val.value
        elif isinstance(val, type(None)):
            return val
        elif isinstance(val, np.bool_):
            return bool(val)
        elif isinstance(val, bool):
            return val
        elif isinstance(val, np.integer):
            return int(val)
        elif isinstance(val, int):
            return val
        elif isinstance(val, np.floating):
            return round(float(val), 9)
        elif isinstance(val, float):
            return round(val, 9)
        elif isinstance(val, str):
            if r"\\" in val:
                return val.replace(r"\\", "/")
            else:
                return val
        elif isinstance(val, (Path)):
            return str(val.as_posix())
        elif isinstance(val, datetime):
            strtime = val.strftime("%Y-%m-%d %H:%M:%S.%f")
            return strtime
        elif isinstance(val, (UUID, date)):
            return str(val)
        elif isinstance(val, list):
            return [self._serialize_item(val=item) for item in val]
        elif isinstance(val, tuple):
            return [self._serialize_item(val=item) for item in val]
        elif isinstance(val, set):
            return {self._serialize_item(val=item) for item in val}
        elif isinstance(val, dict):
            return self._serialize_dict(dict_in=val)
        elif hasattr(val, "as_dict"):
            return val.as_dict()
        elif isinstance(val, BaseModel):
            return self._serialize_dict(dict_in=val.model_dump())
        else:
            tmp_str = f"Helao as_dict cannot serialize {val} of type {type(val)}"
            raise ValueError(tmp_str)

    def as_dict(self) -> dict:
        """Return a fully-serialized dict of the instance's attributes with NaNs replaced by `None`."""
        d = deepcopy(vars(self))
        attr_only = self._serialize_dict(dict_in=d)
        clean_nans = {k: nan2None(v) for k, v in attr_only.items()}
        return clean_nans

    def clean_dict(self, strip_private: bool = False) -> dict:
        """Return `as_dict()` pruned of empty values, optionally dropping ``_``-prefixed keys."""
        return self._cleanupdict(self.as_dict(), strip_private)

    def _cleanupdict(self, d: dict, strip_private: bool = False) -> dict:
        """Recursively drop `None`, empty strings/lists, and empty nested dicts from `d`."""
        clean = {}
        for k, v in d.items():
            if str(k).startswith("_") and strip_private:
                continue
            if isinstance(v, types.GeneratorType):
                print(f"!!! error on attribute {k}, value is a generator")
            elif isinstance(v, dict):
                nested = self._cleanupdict(v)
                if len(nested.keys()) > 0:
                    clean[k] = nested
            elif v is not None:
                if isinstance(v, Enum):
                    clean[k] = v.name
                elif isinstance(v, UUID):
                    clean[k] = str(v)
                elif isinstance(v, list):
                    if len(v) != 0:
                        clean[k] = self._cleanuplist(v)
                elif isinstance(v, str):
                    if len(v) != 0:
                        clean[k] = v
                elif math.isnan(v):
                    clean[k] = None
                else:
                    clean[k] = v
        return clean

    def _cleanuplist(self, input_list) -> list:
        """Recursively clean a list by passing dicts through `_cleanupdict` and stringifying UUIDs."""
        clean_list = []
        for list_item in input_list:
            if isinstance(list_item, dict):
                clean_list.append(self._cleanupdict(list_item))
            elif isinstance(list_item, UUID):
                clean_list.append(str(list_item))
            else:
                clean_list.append(list_item)
        return clean_list
