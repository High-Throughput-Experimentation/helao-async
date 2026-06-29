"""Tests for the ported support dependencies: ErrorCodes, HelaoDict, version."""
import json
import math
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
from pydantic import BaseModel, ConfigDict

from helao.framework.models.errors import ErrorCodes
from helao.framework.models.helao_dict import HelaoDict, nan2None
from helao.framework.support.version import get_hlo_version


# --------------------------------------------------------------------------- #
# ErrorCodes
# --------------------------------------------------------------------------- #
def test_errorcodes_has_none_success_member():
    assert ErrorCodes.none.value == "none"


def test_errorcodes_known_members_exist():
    for name in ("critical", "timeout", "estop", "stop", "not_allowed"):
        assert hasattr(ErrorCodes, name)


def test_errorcodes_round_trips_by_value():
    assert ErrorCodes("timeout") is ErrorCodes.timeout
    assert ErrorCodes(ErrorCodes.none.value) is ErrorCodes.none


def test_errorcodes_is_str_enum():
    assert issubclass(ErrorCodes, str)


# --------------------------------------------------------------------------- #
# HelaoDict
# --------------------------------------------------------------------------- #
class _Mode(str, Enum):
    one = "one"
    two = "two"


class _LevelEnum(int, Enum):
    low = 1
    high = 5


class _Inner(BaseModel, HelaoDict):
    label: str = "x"


class _Holder(BaseModel, HelaoDict):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    s: str = "plain"
    backslash_path: str = "a\\\\b\\\\c"
    n_int: int = 7
    n_float: float = 1 / 3
    nan_field: float = float("nan")
    flag: bool = True
    enum_str: _Mode = _Mode.two
    enum_int: _LevelEnum = _LevelEnum.high
    np_bool: bool = True
    np_int: int = 0
    np_float: float = 0.0
    uuid_field: UUID = uuid4()
    dt: datetime = datetime(2024, 1, 2, 3, 4, 5, 123456)
    d: date = date(2024, 1, 2)
    path_field: Path = Path("a/b/c.txt")
    items: list = [1, 2.5, "three"]
    nested_dict: dict = {"a": 1, "b": {"c": 2}}
    inner: _Inner = _Inner()


def test_nan2none_deep_replacement():
    nested = {
        "ok": 1.0,
        "bad": float("nan"),
        "list": [1.0, float("nan"), 3.0],
        "deep": {"x": float("nan"), "y": "stay"},
    }
    replaced = nan2None(nested)
    assert replaced["ok"] == 1.0
    assert replaced["deep"]["y"] == "stay"
    assert replaced["bad"] is None
    assert replaced["list"] == [1.0, None, 3.0]
    assert replaced["deep"]["x"] is None


def _holder_dict():
    h = _Holder()
    h.np_bool = bool(np.bool_(True))
    h.np_int = int(np.int64(42))
    h.np_float = float(np.float64(3.141592653589793))
    return h, h.as_dict()


def test_as_dict_coerces_primitives():
    h, d = _holder_dict()
    assert d["s"] == "plain" and isinstance(d["s"], str)
    assert d["backslash_path"] == "a/b/c"
    assert d["n_int"] == 7 and isinstance(d["n_int"], int)
    assert d["n_float"] == round(1 / 3, 9)
    assert d["nan_field"] is None
    assert d["flag"] is True and isinstance(d["flag"], bool)


def test_as_dict_coerces_enums():
    _, d = _holder_dict()
    assert d["enum_str"] == "two"  # str enum -> .name
    assert d["enum_int"] == 5  # int enum -> .value


def test_as_dict_coerces_numpy_scalars():
    _, d = _holder_dict()
    assert d["np_bool"] is True
    assert d["np_int"] == 42 and isinstance(d["np_int"], int)
    assert d["np_float"] == round(3.141592653589793, 9)


def test_as_dict_coerces_identity_types():
    h, d = _holder_dict()
    assert d["uuid_field"] == str(h.uuid_field)
    assert d["dt"] == "2024-01-02 03:04:05.123456"
    assert d["d"] == "2024-01-02"
    assert d["path_field"] == "a/b/c.txt"


def test_as_dict_recurses_through_containers():
    _, d = _holder_dict()
    assert d["items"] == [1, 2.5, "three"]
    assert d["nested_dict"]["b"]["c"] == 2
    assert d["inner"] == {"label": "x"}


def test_serialize_item_raises_on_unknown_type():
    class _Junk:
        pass

    class _BadHolder(BaseModel, HelaoDict):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        j: object = _Junk()

    import pytest

    with pytest.raises(ValueError):
        _BadHolder().as_dict()


def test_clean_dict_prunes_empties():
    class _Sparse(BaseModel, HelaoDict):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        name: str = "kept"
        blank_str: str = ""
        null_val: int = None
        empty_list: list = []
        populated_list: list = [1]
        nested_empty: dict = {}
        nested_full: dict = {"k": "v"}

    sparse = _Sparse()
    cleaned = sparse.clean_dict()
    assert cleaned["name"] == "kept"
    assert "blank_str" not in cleaned
    assert "null_val" not in cleaned
    assert "empty_list" not in cleaned and "nested_empty" not in cleaned
    assert cleaned["nested_full"] == {"k": "v"}


def test_serialize_item_tuple_set_and_numpy_branches():
    class _C(BaseModel, HelaoDict):
        pass

    c = _C()
    # tuple -> list, set -> set, numpy scalars
    assert c._serialize_item(val=(1, 2)) == [1, 2]
    assert c._serialize_item(val={1, 2}) == {1, 2}
    assert c._serialize_item(val=np.int64(9)) == 9
    assert c._serialize_item(val=np.float64(0.5)) == 0.5


def test_serialize_item_tuple_is_json_serializable_list():
    # Regression (upstream 7013aaa6): a tuple attribute must serialize to a
    # plain list, not a generator. A generator embedded in the dict is not
    # json-serializable and corrupts .hlo output.
    class _TupleHolder(BaseModel, HelaoDict):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        pair: tuple = (1, "two")

    d = _TupleHolder().as_dict()
    assert isinstance(d["pair"], list)
    assert d["pair"] == [1, "two"]
    # The whole as_dict() must be json-serializable.
    assert json.loads(json.dumps(d))["pair"] == [1, "two"]


def test_serialize_item_basemodel_without_as_dict():
    class _Plain(BaseModel):
        x: int = 3

    class _C(BaseModel, HelaoDict):
        pass

    assert _C()._serialize_item(val=_Plain()) == {"x": 3}


def test_clean_dict_uuid_list_and_strip_private():
    u = uuid4()

    class _M(BaseModel, HelaoDict):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        uid: UUID = u
        ids: list = [u]
        kept_float: float = 1.5
        nan_float: float = float("nan")
        _priv: int = 1

    m = _M()
    cleaned = m.clean_dict()
    assert cleaned["uid"] == str(u)
    assert cleaned["ids"] == [str(u)]
    assert cleaned["kept_float"] == 1.5
    # as_dict() runs nan2None first, so the NaN field is None and clean_dict drops it
    assert "nan_float" not in cleaned
    cleaned_priv = m.clean_dict(strip_private=True)
    assert "_priv" not in cleaned_priv


def test_cleanupdict_nan_branch_direct():
    # The math.isnan branch is only reachable when _cleanupdict gets a raw NaN
    class _C(BaseModel, HelaoDict):
        pass

    out = _C()._cleanupdict({"bad": float("nan"), "good": 2})
    assert out["bad"] is None
    assert out["good"] == 2


def test_cleanupdict_warns_on_generator(capsys):
    class _C(BaseModel, HelaoDict):
        pass

    out = _C()._cleanupdict({"g": (x for x in range(2))})
    assert "g" not in out
    assert "generator" in capsys.readouterr().out


def test_cleanuplist_handles_nested_dict():
    class _C(BaseModel, HelaoDict):
        pass

    out = _C()._cleanuplist([{"a": 1, "b": None}, "plain"])
    assert out == [{"a": 1}, "plain"]


# --------------------------------------------------------------------------- #
# version
# --------------------------------------------------------------------------- #
def test_get_hlo_version_returns_str():
    v = get_hlo_version()
    assert isinstance(v, str)
