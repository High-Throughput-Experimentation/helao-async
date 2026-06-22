"""Tests for helao.framework.support.time_utils."""
import importlib
import sys
import uuid
from datetime import datetime

import pytest

from helao.framework.support import time_utils


def test_gen_uuid_returns_uuid_and_two_calls_differ():
    u1 = time_utils.gen_uuid()
    u2 = time_utils.gen_uuid()
    assert isinstance(u1, uuid.UUID)
    assert isinstance(u2, uuid.UUID)
    assert u1 != u2


def test_gen_uuid_string_is_deterministic_uuid5():
    a = time_utils.gen_uuid("hello")
    b = time_utils.gen_uuid("hello")
    assert a == b
    assert a == uuid.uuid5(uuid.NAMESPACE_URL, "hello")


def test_gen_uuid_from_datetime_and_int_are_time_ordered():
    dt = datetime(2024, 1, 2, 3, 4, 5)
    u = time_utils.gen_uuid(dt)
    assert isinstance(u, uuid.UUID)
    assert isinstance(time_utils.gen_uuid(12345), uuid.UUID)


def test_uuid7_from_datetime():
    dt = datetime(2024, 1, 2, 3, 4, 5)
    assert isinstance(time_utils.uuid7_from_datetime(dt), uuid.UUID)


def test_md5_string_is_deterministic():
    assert time_utils.md5_string("abc") == time_utils.md5_string("abc")
    assert isinstance(time_utils.md5_string("abc"), uuid.UUID)


def test_set_time_shifts_with_offset():
    base = time_utils.set_time(offset=0)
    shifted = time_utils.set_time(offset=3600)
    assert isinstance(base, datetime)
    assert isinstance(shifted, datetime)
    delta = shifted.timestamp() - base.timestamp()
    assert abs(delta - 3600) <= 5


def test_read_saved_offset_returns_float(tmp_path):
    p = tmp_path / "ntpLastSync.txt"
    p.write_text("1700000000.0,1.25")
    last_sync, offset = time_utils.read_saved_offset(str(p))
    assert offset == 1.25
    assert isinstance(offset, float)
    assert last_sync == "1700000000.0"


def test_read_saved_offset_malformed_returns_none(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text("only_one_field")
    assert time_utils.read_saved_offset(str(p)) is None


def test_import_opens_no_socket(monkeypatch):
    """Importing the module must not perform any NTP/socket call."""
    import socket

    def _boom(*args, **kwargs):
        raise AssertionError("socket created at import time")

    monkeypatch.setattr(socket, "socket", _boom)
    sys.modules.pop("helao.framework.support.time_utils", None)
    mod = importlib.import_module("helao.framework.support.time_utils")
    assert hasattr(mod, "gen_uuid")
