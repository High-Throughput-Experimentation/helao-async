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


def test_yml_finisher_retries_then_fails(tmp_path, monkeypatch):
    class _RetryResp(_FakeResp):
        pass

    class _RetrySession(_FakeSession):
        def post(self, url, params=None):
            return _RetryResp(500)

    monkeypatch.setattr(yml_tools.aiohttp, "ClientSession", _RetrySession)
    monkeypatch.setattr(yml_tools.asyncio, "sleep", _noop_sleep)

    yml_path = tmp_path / "fail.yml"
    yml_path.write_text("file_type: action\n")
    result = asyncio.run(
        yml_finisher(str(yml_path), db_config={"host": "h", "port": 1}, retry=2)
    )
    assert result is False


# ---- move_dir promotes a RUNS_ACTIVE directory tree ----


async def _noop_sleep(*a, **k):
    return None


class Action:
    """Minimal Action-like object for move_dir (class name drives obj_type)."""

    manual_action = False
    sync_data = True

    def __init__(self, active_dir):
        from datetime import datetime

        self._dir = active_dir
        self.action_timestamp = datetime(2024, 1, 2, 3, 4, 5)

    def get_action_dir(self):
        return self._dir


class _FakeBase:
    def __init__(self, save_root):
        self.helaodirs = type("HD", (), {"save_root": save_root})()
        self.world_cfg = {"servers": {}}


def test_move_dir_invalid_type_returns_empty_dict(monkeypatch):
    monkeypatch.setattr(yml_tools.asyncio, "sleep", _noop_sleep)

    class _Weird:
        manual_action = False

    out = asyncio.run(
        yml_tools.move_dir(
            _Weird(), base=_FakeBase("/tmp"), retry_delay=0
        )
    )
    assert out == {}


def test_move_dir_promotes_action_files(tmp_path, monkeypatch):
    # Build a RUNS_ACTIVE action dir with one file.
    save_root = tmp_path
    active = save_root / "RUNS_ACTIVE" / "seq" / "exp" / "act"
    active.mkdir(parents=True)
    (active / "240102.030405000000-act.yml").write_text("file_type: action\n")
    (active / "data.txt").write_text("payload")

    monkeypatch.setattr(yml_tools.asyncio, "sleep", _noop_sleep)

    finished = []

    async def _fake_finisher(yml_path, db_config=None, retry=3):
        finished.append(yml_path)
        return True

    monkeypatch.setattr(yml_tools, "yml_finisher", _fake_finisher)

    hobj = Action(str(active.relative_to(save_root)))
    asyncio.run(yml_tools.move_dir(hobj, base=_FakeBase(str(save_root)), retry_delay=0))

    finished_dir = save_root / "RUNS_FINISHED" / "seq" / "exp" / "act"
    assert (finished_dir / "data.txt").exists()
    assert not active.exists()
    assert len(finished) == 1


class Experiment:
    """Minimal Experiment-like object (uses glob non-recursive branch)."""

    manual_action = False
    sync_data = True

    def __init__(self, active_dir):
        from datetime import datetime

        self._dir = active_dir
        self.experiment_timestamp = datetime(2024, 1, 2, 3, 4, 5)

    def get_experiment_dir(self):
        return self._dir


def test_move_dir_experiment_non_recursive(tmp_path, monkeypatch):
    save_root = tmp_path
    active = save_root / "RUNS_ACTIVE" / "seq" / "exp"
    active.mkdir(parents=True)
    (active / "240102.030405000000-exp.yml").write_text("file_type: experiment\n")

    monkeypatch.setattr(yml_tools.asyncio, "sleep", _noop_sleep)

    async def _fake_finisher(yml_path, db_config=None, retry=3):
        return True

    monkeypatch.setattr(yml_tools, "yml_finisher", _fake_finisher)

    hobj = Experiment(str(active.relative_to(save_root)))
    asyncio.run(yml_tools.move_dir(hobj, base=_FakeBase(str(save_root)), retry_delay=0))
    assert (save_root / "RUNS_FINISHED" / "seq" / "exp").exists()
    assert not active.exists()


def _make_manual_action(active_dir):
    # Class name must be "Action" (obj_type derives from __class__.__name__).
    obj = Action(active_dir)
    obj.manual_action = True
    obj.sync_data = False  # .hlo data routed to RUNS_NOSYNC
    return obj


def test_move_dir_manual_action_nosync_and_cleanup(tmp_path, monkeypatch):
    save_root = tmp_path
    active = save_root / "RUNS_ACTIVE" / "seq" / "exp" / "act"
    active.mkdir(parents=True)
    (active / "240102.030405000000-act.yml").write_text("file_type: action\n")
    (active / "trace.hlo").write_text("hlo-data")

    monkeypatch.setattr(yml_tools.asyncio, "sleep", _noop_sleep)

    finisher_calls = []

    async def _fake_finisher(yml_path, db_config=None, retry=3):
        finisher_calls.append(yml_path)
        return True

    monkeypatch.setattr(yml_tools, "yml_finisher", _fake_finisher)

    hobj = _make_manual_action(str(active.relative_to(save_root)))
    asyncio.run(yml_tools.move_dir(hobj, base=_FakeBase(str(save_root)), retry_delay=0))

    # manual -> RUNS_DIAG destination; .hlo diverted to RUNS_NOSYNC
    assert (save_root / "RUNS_NOSYNC" / "seq" / "exp" / "act" / "trace.hlo").exists()
    # manual action removes the active seq/exp dirs entirely
    assert not (save_root / "RUNS_ACTIVE" / "seq").exists()
    # yml_finisher is NOT called for manual moves
    assert finisher_calls == []


def test_move_dir_copy_failure_exhausts_retries(tmp_path, monkeypatch):
    save_root = tmp_path
    active = save_root / "RUNS_ACTIVE" / "seq" / "exp" / "act"
    active.mkdir(parents=True)
    (active / "data.txt").write_text("payload")

    monkeypatch.setattr(yml_tools.asyncio, "sleep", _noop_sleep)

    async def _fail_copy(src, dst):
        raise OSError("disk full")

    # copies never land -> exists_list stays short -> retries exhaust (<=60)
    monkeypatch.setattr(yml_tools.aioshutil, "copy", _fail_copy)

    hobj = Action(str(active.relative_to(save_root)))
    asyncio.run(yml_tools.move_dir(hobj, base=_FakeBase(str(save_root)), retry_delay=0))
    # active dir still present because copy never succeeded
    assert active.exists()
