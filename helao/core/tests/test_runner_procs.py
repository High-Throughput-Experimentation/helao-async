"""/runners backend: catalog, probes, processes, overlap."""

import asyncio
import os
import signal
import sys
import textwrap

import pytest

from helao.core.error import ErrorCodes
from helao.ui.reflex import runner_procs as rp

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def test_deployment_of():
    cfg = {"loaded_config_path": "/x/helao/deploy/test/configs/goldenreflex.yml"}
    assert rp.deployment_of(cfg) == "test"
    assert rp.deployment_of({}) is None


def _pkg(tmp_path):
    runners = tmp_path / "helao" / "deploy" / "zz" / "runners"
    runners.mkdir(parents=True)
    # helao and helao.deploy must merge with the real packages on PYTHONPATH,
    # not shadow them, or the launcher cannot import helao.core.
    ext = "__path__ = __import__('pkgutil').extend_path(__path__, __name__)\n"
    for d in (tmp_path / "helao", tmp_path / "helao" / "deploy"):
        (d / "__init__.py").write_text(ext, encoding="utf-8")
    for d in (tmp_path / "helao" / "deploy" / "zz", runners):
        (d / "__init__.py").write_text("", encoding="utf-8")
    return runners


GOOD = "from helao.core.runners.micro_orch import MicroOrch\nasync def run(orch: MicroOrch, n: int = 1):\n    pass\n"


@pytest.mark.asyncio
async def test_catalog_lists_broken_module_with_error(tmp_path, monkeypatch):
    runners = _pkg(tmp_path)
    (runners / "good_runner.py").write_text(GOOD, encoding="utf-8")
    (runners / "bad_runner.py").write_text(
        "raise RuntimeError('top level')\n", encoding="utf-8"
    )
    monkeypatch.setenv("PYTHONPATH", f"{tmp_path}{os.pathsep}{REPO}")
    monkeypatch.chdir(tmp_path)  # `python -m` puts cwd first on sys.path
    mods = rp.runner_modules("zz", str(tmp_path))
    assert mods == [
        "helao.deploy.zz.runners.bad_runner",
        "helao.deploy.zz.runners.good_runner",
    ]
    entries = {e["module"]: e for e in await rp.describe_all(mods)}
    assert "error" in entries["helao.deploy.zz.runners.bad_runner"]
    assert entries["helao.deploy.zz.runners.good_runner"]["args"] == ["n"]


@pytest.mark.asyncio
async def test_refresh_sees_add_edit_delete(tmp_path, monkeypatch):
    runners = _pkg(tmp_path)
    (runners / "a_runner.py").write_text(GOOD, encoding="utf-8")
    (runners / "b_runner.py").write_text(GOOD, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", f"{tmp_path}{os.pathsep}{REPO}")
    monkeypatch.chdir(tmp_path)  # `python -m` puts cwd first on sys.path
    cfg = {"loaded_config_path": f"{tmp_path}/helao/deploy/zz/configs/c.yml"}
    await rp.refresh_catalog(cfg, str(tmp_path))
    (runners / "a_runner.py").write_text(
        GOOD.replace("n: int = 1", "n: int = 7"), encoding="utf-8"
    )
    (runners / "b_runner.py").unlink()
    (runners / "c_runner.py").write_text(GOOD, encoding="utf-8")
    entries = {
        e["module"].rsplit(".", 1)[-1]: e
        for e in await rp.refresh_catalog(cfg, str(tmp_path))
    }
    assert set(entries) == {"a_runner", "c_runner"}
    assert {m.rsplit(".", 1)[-1] for m in rp.CATALOG} == {"a_runner", "c_runner"}
    assert entries["a_runner"]["defaults"] == [7]


@pytest.mark.asyncio
async def test_probe_unreachable_server_fails_rows(monkeypatch):
    async def fake(server, host, port, path, **kw):
        assert kw.get("timeout") == 5 and kw.get("retries") == 1
        return None, "http"

    monkeypatch.setattr(rp, "async_private_dispatcher", fake)
    eps, st = await rp.probe(["SIM"], {"servers": {"SIM": {"host": "h", "port": 1}}})
    assert eps == {"SIM": None} and st == {"SIM": None}


SLOW = (
    "import asyncio, signal\n"
    "from helao.core.runners.micro_orch import MicroOrch\n"
    "async def run(orch: MicroOrch):\n"
    "    open('ready', 'w').close()\n"  # handlers are installed by now
    "    await asyncio.sleep(3600)\n"
)


def _slow_world(tmp_path, monkeypatch):
    runners = _pkg(tmp_path)
    (runners / "slow_runner.py").write_text(SLOW, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", f"{tmp_path}{os.pathsep}{REPO}")
    monkeypatch.chdir(tmp_path)  # `python -m` puts cwd first on sys.path
    cfg = tmp_path / "cfg.yml"
    cfg.write_text(f"root: {tmp_path}\nservers: {{}}\n", encoding="utf-8")
    rp.PROCS.clear()
    return {"root": str(tmp_path), "servers": {}, "loaded_config_path": str(cfg)}


SLOW_MOD = "helao.deploy.zz.runners.slow_runner"


async def _reap(*procs):
    for p in procs:
        if p.proc.returncode is None:
            p.proc.kill()
        await p.proc.wait()
    rp.PROCS.clear()


@pytest.mark.asyncio
async def test_launch_refuses_duplicate_key_and_stop_kill(tmp_path, monkeypatch):
    world = _slow_world(tmp_path, monkeypatch)
    p = await rp.launch(world, SLOW_MOD, "SLOW", {})
    try:
        assert p.state == "running" and os.path.exists(p.log_path)
        for _ in range(300):  # a signal before the launcher's handlers just kills it
            if os.path.exists(tmp_path / "ready"):
                break
            await asyncio.sleep(0.1)
        assert os.path.exists(tmp_path / "ready")
        with pytest.raises(ValueError, match="SLOW"):
            await rp.launch(world, SLOW_MOD, "SLOW", {})
        rp.stop("SLOW")
        assert rp.PROCS["SLOW"].state == "stopping"
        await asyncio.sleep(1.5)
        # the fake ignores the stop, so only a delivered signal explains the log line
        assert p.proc.returncode is None
        with open(p.log_path, encoding="utf-8") as f:
            assert "stop requested" in f.read()
        rp.force_kill("SLOW")
        await asyncio.wait_for(p.proc.wait(), 30)
        await asyncio.sleep(0.1)
        assert rp.PROCS["SLOW"].state == "killed"
        if os.name != "nt":
            assert rp.PROCS["SLOW"].rc == -signal.SIGKILL
    finally:
        await _reap(p)


@pytest.mark.asyncio
async def test_concurrent_launch_same_key_spawns_one(tmp_path, monkeypatch):
    world = _slow_world(tmp_path, monkeypatch)
    res = await asyncio.gather(
        rp.launch(world, SLOW_MOD, "RACE", {}),
        rp.launch(world, SLOW_MOD, "RACE", {}),
        return_exceptions=True,
    )
    ok = [r for r in res if isinstance(r, rp.RunnerProc)]
    try:
        assert len(ok) == 1
        assert sum(isinstance(r, ValueError) for r in res) == 1
        assert list(rp.PROCS) == ["RACE"] and not rp._LAUNCHING
    finally:
        await _reap(*ok)


@pytest.mark.asyncio
async def test_launch_refuses_key_live_in_runner_registry(tmp_path, monkeypatch):
    world = _slow_world(tmp_path, monkeypatch)

    class Live:
        def lost(self, now):
            return False

    class Reg:
        def get(self, key):
            return Live() if key == "PUSHED" else None

    monkeypatch.setattr(rp.group, "REGISTRY", Reg())
    with pytest.raises(ValueError, match="PUSHED"):
        await rp.launch(world, SLOW_MOD, "PUSHED", {})
    assert not rp.PROCS


@pytest.mark.asyncio
async def test_probe_keeps_only_routes_of_the_probed_server(monkeypatch):
    async def fake(server, host, port, path, **kw):
        if path == "endpoints":
            return [
                {"path": "/SIM/acquire_data"},
                {"path": "/get_status"},
                {"path": "/OTHER/x"},
            ], ErrorCodes.none
        return {"s": 1}, ErrorCodes.none

    monkeypatch.setattr(rp, "async_private_dispatcher", fake)
    eps, st = await rp.probe(["SIM"], {"servers": {"SIM": {"host": "h", "port": 1}}})
    assert eps == {"SIM": ["acquire_data"]} and st == {"SIM": {"s": 1}}


def test_overlap(monkeypatch):
    frames = {
        "ORCH": {
            "servers": [
                {"key": "SIM", "status": "busy"},
                {"key": "PSTAT", "status": "idle"},
            ]
        },
        "R1": {"servers": [{"key": "SIM", "status": "busy"}]},
        "OLD": {"servers": [{"key": "SIM", "status": "busy"}]},
    }
    monkeypatch.setattr(rp.group, "feed_keys", lambda: list(frames))
    monkeypatch.setattr(rp.group, "feed_for", lambda k: k)
    monkeypatch.setattr(rp.group, "latest_frame", lambda feed: frames[feed])
    monkeypatch.setattr(rp.group, "stream_lost", lambda feed, now: feed == "OLD")
    assert rp.overlap() == {"SIM": ["ORCH", "R1"]}


def test_platform_ops_windows_and_posix():
    import signal
    import subprocess

    kw, sig = rp._platform_ops("posix")
    assert kw == {} and sig == signal.SIGTERM
    if os.name == "nt":
        kw, sig = rp._platform_ops("nt")
        assert kw == {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        assert sig == signal.CTRL_BREAK_EVENT


def test_platform_ops_nt_branch(monkeypatch):
    import signal
    import subprocess

    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)
    monkeypatch.setattr(signal, "CTRL_BREAK_EVENT", 1, raising=False)
    assert rp._platform_ops("nt") == ({"creationflags": 512}, 1)
    monkeypatch.setattr(os, "name", "nt")
    assert rp._platform_ops()[0] == {"creationflags": 512}
