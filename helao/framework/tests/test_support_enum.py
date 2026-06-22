"""Tests for helao.framework.support.make_str_enum."""
from enum import StrEnum

from pydantic import BaseModel

from helao.framework.support.make_str_enum import make_str_enum


def test_make_str_enum_members_equal_their_string_values():
    Colors = make_str_enum("Colors", {"RED": "red", "GREEN": "green", "BLUE": "blue"})
    assert issubclass(Colors, StrEnum)
    assert Colors.RED == "red"
    assert Colors.RED.value == "red"
    assert Colors("green") is Colors.GREEN


def test_make_str_enum_serializes_in_pydantic_model():
    Colors = make_str_enum("Colors", {"RED": "red", "GREEN": "green"})

    class M(BaseModel):
        c: Colors = Colors.RED

    m = M(c="green")
    assert m.c == "green"
    dumped = m.model_dump()
    assert dumped["c"] == "green"
    assert m.model_dump_json() == '{"c":"green"}'


def test_single_member_enum_emits_enum_array_in_json_schema():
    Single = make_str_enum("Single", {"ONLY": "only"})

    class M(BaseModel):
        s: Single = Single.ONLY

    schema = M.model_json_schema()
    # Resolve the referenced enum schema and confirm it uses an enum array.
    defs = schema.get("$defs", {})
    single_schema = defs.get("Single", {})
    assert single_schema.get("enum") == ["only"]
    assert "const" not in single_schema


def test_multi_member_enum_keeps_default_schema():
    Multi = make_str_enum("Multi", {"A": "a", "B": "b"})

    class M(BaseModel):
        m: Multi = Multi.A

    schema = M.model_json_schema()
    single_schema = schema.get("$defs", {}).get("Multi", {})
    assert sorted(single_schema.get("enum", [])) == ["a", "b"]
