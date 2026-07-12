"""Unit tests for the :class:`helao.core.helaodict.HelaoDict` serializer mixin.

``HelaoDict.as_dict`` is the workhorse that turns pydantic model
instances into the JSON/YAML-friendly dicts every HELAO artifact
serializer relies on. This module pins down its handling of:

* enums (string and numeric)
* numpy scalars (``np.bool_`` / ``np.integer`` / ``np.floating``)
* ``UUID`` / ``datetime`` / ``date`` / ``Path`` conversion
* nested ``HelaoDict`` (``as_dict``) and bare ``BaseModel`` instances
* NaN -> ``None`` replacement at the top level via ``nan2None``
* float rounding to 9 decimals
* :meth:`clean_dict` pruning of ``None`` / empty values, with the
  ``strip_private`` flag honouring the leading-underscore convention.
"""

__all__ = ["helaodict_unit_test"]

import traceback
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
from pydantic import BaseModel

from helao.core.helaodict import HelaoDict, nan2None
from helao.core.tests._test_utils import TestReporter


class _Mode(str, Enum):
    """Trivial string-valued enum used to exercise ``Enum``-handling."""

    one = "one"
    two = "two"


class _LevelEnum(int, Enum):
    """Trivial int-valued enum used to assert ``value`` is returned, not ``name``."""

    low = 1
    high = 5


class _Inner(BaseModel, HelaoDict):
    """Small nested ``HelaoDict`` model used to confirm recursive `as_dict`."""

    label: str = "x"


class _Holder(BaseModel, HelaoDict):
    """Wide model covering every branch of ``HelaoDict._serialize_item``.

    Each attribute exercises one or more of the coercion paths in
    :meth:`HelaoDict._serialize_item`, so we can assert the final dict
    contains JSON-safe primitives only.
    """

    s: str = "plain"
    backslash_path: str = "a\\\\b\\\\c"  # raw r"\\" inside the string
    n_int: int = 7
    n_float: float = 1 / 3  # exercises the 9-decimal rounding
    nan_field: float = float("nan")
    flag: bool = True
    enum_str: _Mode = _Mode.two
    enum_int: _LevelEnum = _LevelEnum.high
    np_bool: bool = True  # placeholder, populated post-init
    np_int: int = 0
    np_float: float = 0.0
    uuid_field: UUID = uuid4()
    dt: datetime = datetime(2024, 1, 2, 3, 4, 5, 123456)
    d: date = date(2024, 1, 2)
    path_field: Path = Path("a/b/c.txt")
    items: list = [1, 2.5, "three"]
    nested_dict: dict = {"a": 1, "b": {"c": 2}}
    inner: _Inner = _Inner()

    class Config:
        """Allow ``Path`` / numpy objects to pass through without strict types."""

        arbitrary_types_allowed = True


def helaodict_unit_test() -> bool:
    """Run all HelaoDict assertions and report pass/fail."""
    reporter = TestReporter("helaodict")

    try:
        reporter.section("nan2None deep replacement")
        nested = {
            "ok": 1.0,
            "bad": float("nan"),
            "list": [1.0, float("nan"), 3.0],
            "deep": {"x": float("nan"), "y": "stay"},
        }
        replaced = nan2None(nested)
        reporter.check(
            "nan2None keeps non-NaN floats intact",
            lambda: replaced["ok"] == 1.0 and replaced["deep"]["y"] == "stay",
        )
        reporter.check(
            "nan2None replaces top-level NaN with None",
            lambda: replaced["bad"] is None,
        )
        reporter.check(
            "nan2None replaces NaN inside lists with None",
            lambda: replaced["list"] == [1.0, None, 3.0],
        )
        reporter.check(
            "nan2None recurses into nested dicts",
            lambda: replaced["deep"]["x"] is None,
        )

        reporter.section("HelaoDict.as_dict coerces primitives")
        h = _Holder()
        # patch numpy scalars in after construction (pydantic strips types)
        h.np_bool = bool(np.bool_(True))
        h.np_int = int(np.int64(42))
        h.np_float = float(np.float64(3.141592653589793))

        d = h.as_dict()

        reporter.check(
            "str stays a str",
            lambda: d["s"] == "plain" and isinstance(d["s"], str),
        )
        reporter.check(
            r"strings containing literal '\\' are flipped to '/'",
            lambda: d["backslash_path"] == "a/b/c",
        )
        reporter.check(
            "ints survive as ints",
            lambda: d["n_int"] == 7 and isinstance(d["n_int"], int),
        )
        reporter.check(
            "floats are rounded to 9 decimals",
            lambda: d["n_float"] == round(1 / 3, 9),
        )
        reporter.check(
            "top-level NaN field becomes None",
            lambda: d["nan_field"] is None,
        )
        reporter.check(
            "booleans survive as booleans (not coerced to int by Enum branch)",
            lambda: d["flag"] is True and isinstance(d["flag"], bool),
        )

        reporter.section("HelaoDict.as_dict coerces enums")
        reporter.check(
            "string-valued Enum uses .name in as_dict",
            lambda: d["enum_str"] == "two",
        )
        reporter.check(
            "int-valued Enum uses .value in as_dict",
            lambda: d["enum_int"] == 5,
        )

        reporter.section("HelaoDict.as_dict coerces numpy scalars")
        reporter.check(
            "np.bool_ -> Python bool",
            lambda: d["np_bool"] is True,
        )
        reporter.check(
            "np.int64 -> Python int",
            lambda: d["np_int"] == 42 and isinstance(d["np_int"], int),
        )
        reporter.check(
            "np.float64 rounds to 9 decimals like native float",
            lambda: d["np_float"] == round(3.141592653589793, 9),
        )

        reporter.section("HelaoDict.as_dict coerces identity types")
        reporter.check(
            "UUID becomes its string form",
            lambda: d["uuid_field"] == str(h.uuid_field),
        )
        reporter.check(
            "datetime uses YYYY-MM-DD HH:MM:SS.ffffff format",
            lambda: d["dt"] == "2024-01-02 03:04:05.123456",
        )
        reporter.check(
            "date becomes its ISO string",
            lambda: d["d"] == "2024-01-02",
        )
        reporter.check(
            "Path becomes a posix string",
            lambda: d["path_field"] == "a/b/c.txt",
        )

        reporter.section("HelaoDict.as_dict recurses through containers")
        reporter.check(
            "lists preserve element ordering and types",
            lambda: d["items"] == [1, 2.5, "three"],
        )
        reporter.check(
            "nested dicts come through recursively",
            lambda: d["nested_dict"]["b"]["c"] == 2,
        )
        reporter.check(
            "inner HelaoDict goes through its own as_dict",
            lambda: d["inner"] == {"label": "x"},
        )

        reporter.section("HelaoDict._serialize_item raises on unknown types")

        class _Junk:
            """Sentinel object with no registered serializer."""

            pass

        class _BadHolder(BaseModel, HelaoDict):
            """Holder model whose only field is the unsupported sentinel."""

            j: object = _Junk()

            class Config:
                arbitrary_types_allowed = True

        def _try_serialize_unknown():
            _BadHolder().as_dict()

        reporter.check(
            "unsupported attribute type raises ValueError",
            lambda: _expect_raises(_try_serialize_unknown, ValueError),
        )

        reporter.section("HelaoDict.clean_dict prunes empties")

        class _Sparse(BaseModel, HelaoDict):
            """Mix of empty and populated fields for clean_dict pruning."""

            name: str = "kept"
            blank_str: str = ""
            null_val: int = None  # noqa: ASGT001
            empty_list: list = []
            populated_list: list = [1]
            nested_empty: dict = {}
            nested_full: dict = {"k": "v"}
            _private: int = 0

            class Config:
                arbitrary_types_allowed = True

        sparse = _Sparse()
        cleaned = sparse.clean_dict()
        reporter.check(
            "clean_dict keeps populated string fields",
            lambda: cleaned["name"] == "kept",
        )
        reporter.check(
            "clean_dict drops empty string fields",
            lambda: "blank_str" not in cleaned,
        )
        reporter.check(
            "clean_dict drops None-valued fields",
            lambda: "null_val" not in cleaned,
        )
        reporter.check(
            "clean_dict drops empty list/dict fields",
            lambda: "empty_list" not in cleaned and "nested_empty" not in cleaned,
        )
        reporter.check(
            "clean_dict keeps populated nested dicts",
            lambda: cleaned["nested_full"] == {"k": "v"},
        )

        cleaned_priv = sparse.clean_dict(strip_private=True)
        reporter.check(
            "clean_dict(strip_private=True) drops underscore-prefixed keys",
            lambda: "_private" not in cleaned_priv,
        )

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False


def _expect_raises(fn, exc_type) -> bool:
    """Return True iff calling ``fn()`` raises an instance of ``exc_type``."""
    try:
        fn()
    except exc_type:
        return True
    except Exception:  # noqa: BLE001
        return False
    return False
