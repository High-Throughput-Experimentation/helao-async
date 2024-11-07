__all__ = ["HelaoDict"]

from datetime import datetime, date
from uuid import UUID
import types
import numpy as np
from pydantic import BaseModel
from typing import Any
from enum import Enum
from pathlib import Path
from copy import deepcopy
import math


# https://stackoverflow.com/a/71389334
def nan2None(obj):
    if isinstance(obj, dict):
        return {k: nan2None(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [nan2None(v) for v in obj]
    elif isinstance(obj, float) and math.isnan(obj):
        return None
    return obj


class HelaoDict:
    """implements dict and serialization methods for helao"""

    def _serialize_dict(self, dict_in: dict):
        clean = {}
        for k, v in dict_in.items():
            if not isinstance(v, types.FunctionType) and not (
                isinstance(v, str) and k.startswith("__")
            ):
                # keys can also be UUID, datetime etc
                clean.update({self._serialize_item(val=k): self._serialize_item(val=v)})
        return clean

    def _serialize_item(self, val: Any):
        if isinstance(val, Enum):
            # need to be first to catch also str enums
            if isinstance(val, str):
                return val.name
            else:
                return val.value
        elif isinstance(val, np.integer):
            return int(val)
        elif isinstance(val, np.floating):
            return float(val)
        elif isinstance(val, np.bool_):
            return bool(val)
        elif isinstance(val, (int, float, bool, type(None))):
            return val
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
            return (self._serialize_item(val=item) for item in val)
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

    def as_dict(self):
        d = deepcopy(vars(self))
        attr_only = self._serialize_dict(dict_in=d)
        clean_nans = nan2None(attr_only)
        return clean_nans

    def clean_dict(self, strip_private: bool = False):
        return self._cleanupdict(self.as_dict(), strip_private)

    def _cleanupdict(self, d: dict, strip_private: bool = False):
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

    def _cleanuplist(self, input_list):
        clean_list = []
        for list_item in input_list:
            if isinstance(list_item, dict):
                clean_list.append(self._cleanupdict(list_item))
            elif isinstance(list_item, UUID):
                clean_list.append(str(list_item))
            else:
                clean_list.append(list_item)
        return clean_list
