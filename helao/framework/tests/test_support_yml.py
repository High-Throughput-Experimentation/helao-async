"""Tests for helao.framework.support.yml_tools.

Round-trips dict <-> YAML via yml_dumps/yml_load (string, path, Path), and
exercises the remote-fetch path (yml_finisher) with a monkeypatched aiohttp
ClientSession so no real network is touched.
"""
import asyncio
from pathlib import Path

import pytest

from helao.framework.support import yml_tools
from helao.framework.support.yml_tools import yml_dumps, yml_load, yml_finisher


def test_yml_dumps_round_trips_dict():
    obj = {"a": 1, "b": ["x", "y"], "c": {"nested": True}}
    text = yml_dumps(obj)
    assert isinstance(text, str)
    loaded = yml_load(text)
    assert loaded["a"] == 1
    assert list(loaded["b"]) == ["x", "y"]
    assert loaded["c"]["nested"] is True


def test_yml_dumps_renders_none_as_null():
    text = yml_dumps({"k": None})
    assert "null" in text


def test_yml_load_from_path_and_str_path(tmp_path):
    p = tmp_path / "cfg.yml"
    p.write_text("run_type: simulation\nroot: /tmp\n")
    via_path = yml_load(p)
    via_str = yml_load(str(p))
    assert via_path["run_type"] == "simulation"
    assert via_str["root"] == "/tmp"


def test_yml_load_from_raw_string():
    loaded = yml_load("foo: 42\nbar: baz\n")
    assert loaded["foo"] == 42
    assert loaded["bar"] == "baz"


# ---- remote fetch (yml_finisher) with monkeypatched aiohttp ----


class _FakeResp:
    def __init__(self, status):
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeSession:
    posted = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def post(self, url, params=None):
        _FakeSession.posted.append((url, params))
        return _FakeResp(200)


def test_yml_finisher_returns_false_without_host_port():
    result = asyncio.run(yml_finisher("/tmp/x.yml", db_config={}))
    assert result is False


def test_yml_finisher_returns_false_when_file_missing(tmp_path):
    result = asyncio.run(
        yml_finisher(
            str(tmp_path / "nope.yml"),
            db_config={"host": "h", "port": 1},
        )
    )
    assert result is False


def test_yml_finisher_posts_to_db_server(tmp_path, monkeypatch):
    _FakeSession.posted = []
    monkeypatch.setattr(yml_tools.aiohttp, "ClientSession", _FakeSession)

    yml_path = tmp_path / "done.yml"
    yml_path.write_text("file_type: action\n")

    result = asyncio.run(
        yml_finisher(str(yml_path), db_config={"host": "dbhost", "port": 9999})
    )
    assert result is True
    assert len(_FakeSession.posted) == 1
    url, params = _FakeSession.posted[0]
    assert url == "http://dbhost:9999/finish_yml"
    assert params == {"yml_path": str(yml_path)}
