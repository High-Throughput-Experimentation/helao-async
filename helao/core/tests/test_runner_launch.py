"""Runner launcher: describe, coercion, signals (spec: Launcher)."""

import json
import os
import queue
import signal
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from helao.core.runners import launch

PY = sys.executable
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _env(tmp_path):
    return {**os.environ, "PYTHONPATH": f"{tmp_path}{os.pathsep}{REPO}"}


def _write(tmp_path, name, body):
    (tmp_path / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")


GOOD = '''
"""Demo runner.

Longer text."""
from helao.core.runners.micro_orch import MicroOrch
REQUIRES = {"SIM": ["acquire_data"]}

async def run(orch: MicroOrch, n: int = 2, label: str = "x"):
    return None
'''


posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="sends SIGTERM to a subprocess"
)


def test_describe_good_module(tmp_path):
    _write(tmp_path, "demo_runner", GOOD)
    out = subprocess.run(
        [PY, "-m", "helao.core.runners.launch", "--describe", "demo_runner"],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        timeout=60,
    )
    assert out.returncode == 0, out.stderr
    d = json.loads(out.stdout)
    assert d["args"] == ["n", "label"] and d["defaults"] == [2, "x"]
    assert d["argtypes"] == ["int", "str"]
    assert d["requires"] == {"SIM": ["acquire_data"]}
    assert d["doc"].startswith("Demo runner.")


@pytest.mark.parametrize(
    "body", ["def nope(:\n", "x = 1\n", "def run(orch):\n    pass\n"]
)
def test_describe_bad_module_errors(tmp_path, body):
    _write(tmp_path, "bad_runner", body)
    out = subprocess.run(
        [PY, "-m", "helao.core.runners.launch", "--describe", "bad_runner"],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        timeout=60,
    )
    assert out.returncode == 1
    assert "error" in json.loads(out.stdout)


def test_default_key():
    assert (
        launch.default_key("helao.deploy.test.runners.simulatews_runner")
        == "SIMULATEWS"
    )
    assert launch.default_key("pkg.my_thing") == "MY_THING"


def test_coerce_types_and_unknown():
    import inspect

    async def run(
        orch, n: int = 1, f: float = 1.0, b: bool = False, s: str = "", raw=None
    ): ...

    sig = inspect.signature(run)
    assert launch.coerce(
        {"n": "3", "f": "2.5", "b": "true", "s": 5, "raw": [1]}, sig
    ) == {"n": 3, "f": 2.5, "b": True, "s": "5", "raw": [1]}
    with pytest.raises(ValueError, match="nope"):
        launch.coerce({"nope": 1}, sig)
    with pytest.raises(ValueError, match="n"):
        launch.coerce({"n": "abc"}, sig)


SLOW = """
import asyncio
from helao.core.runners.micro_orch import MicroOrch, RunnerStopped
async def run(orch: MicroOrch):
    print("started", flush=True)
    while True:
        await asyncio.sleep(0.05)
        if orch.stop_requested:
            print("saw-stop", flush=True)
            raise RunnerStopped("stop")
"""

BOOM = """
from helao.core.runners.micro_orch import MicroOrch
async def run(orch: MicroOrch):
    raise RuntimeError("boom")
"""


def _cfg(tmp_path):
    p = tmp_path / "cfg.yml"
    p.write_text(f"root: {tmp_path}\nservers: {{}}\n", encoding="utf-8")
    return str(p)


@pytest.fixture
def spawn(tmp_path):
    procs = []

    def _spawn(module):
        p = subprocess.Popen(
            [PY, "-m", "helao.core.runners.launch", _cfg(tmp_path), module]
            + ["--host", "127.0.0.1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=_env(tmp_path),
        )
        q = queue.Queue()

        def pump():
            for line in p.stdout:
                q.put(line)
            q.put(None)

        threading.Thread(target=pump, daemon=True).start()
        p.lines = q
        procs.append(p)
        return p

    try:
        yield _spawn
    finally:
        for p in procs:
            p.kill()
            p.wait()


def _wait_line(p, text, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            line = p.lines.get(timeout=max(0.01, end - time.time()))
        except queue.Empty:
            return False
        if line is None:
            return False
        if text in line:
            return True
    return False


@posix_only
def test_sigterm_is_clean_stop(tmp_path, spawn):
    _write(tmp_path, "slow_runner", SLOW)
    p = spawn("slow_runner")
    assert _wait_line(p, "started")
    p.send_signal(signal.SIGTERM)
    assert _wait_line(p, "saw-stop")
    assert p.wait(timeout=30) == 0


@posix_only
def test_second_sigterm_forces_130(tmp_path, spawn):
    _write(
        tmp_path, "stuck_runner", SLOW.replace("if orch.stop_requested:", "if False:")
    )
    p = spawn("stuck_runner")
    assert _wait_line(p, "started")
    p.send_signal(signal.SIGTERM)
    time.sleep(0.5)
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=30) == 130


def test_exception_exits_1_and_is_logged(tmp_path, spawn):
    _write(tmp_path, "boom_runner", BOOM)
    p = spawn("boom_runner")
    assert _wait_line(p, "runner BOOM failed")
    assert _wait_line(p, "RuntimeError: boom")
    assert p.wait(timeout=60) == 1


def test_key_clash_exits_2(tmp_path):
    _write(tmp_path, "slow_runner", SLOW)
    cfg = tmp_path / "cfg.yml"
    cfg.write_text(
        f"root: {tmp_path}\nservers:\n  SLOW:\n    host: 127.0.0.1\n    port: 1\n",
        encoding="utf-8",
    )
    out = subprocess.run(
        [PY, "-m", "helao.core.runners.launch", str(cfg), "slow_runner"],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        timeout=60,
    )
    assert out.returncode == 2


def _launch(tmp_path, *args):
    return subprocess.run(
        [PY, "-m", "helao.core.runners.launch", *args],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        timeout=60,
    )


def test_non_dict_params_exits_2(tmp_path):
    _write(tmp_path, "slow_runner", SLOW)
    out = _launch(tmp_path, _cfg(tmp_path), "slow_runner", "--params", "[1]")
    assert out.returncode == 2
    assert "--params must be a JSON object" in out.stderr


def test_missing_config_exits_2(tmp_path):
    _write(tmp_path, "slow_runner", SLOW)
    assert _launch(tmp_path, str(tmp_path / "nope.yml"), "slow_runner").returncode == 2


FUTURE = """
from __future__ import annotations
from helao.core.runners.micro_orch import MicroOrch
async def run(orch: MicroOrch, n: int = 2, flag: bool = True, s: str = "x"):
    return None
"""


def test_future_annotations_describe_and_coerce(tmp_path):
    _write(tmp_path, "fut_runner", FUTURE)
    out = _launch(tmp_path, "--describe", "fut_runner")
    assert json.loads(out.stdout)["argtypes"] == ["int", "bool", "str"]
    sys.path.insert(0, str(tmp_path))
    try:
        import importlib
        import inspect

        mod = importlib.import_module("fut_runner")
        got = launch.coerce({"n": "3", "flag": "false"}, inspect.signature(mod.run))
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("fut_runner", None)
    assert got == {"n": 3, "flag": False}


def test_describe_import_time_print_does_not_corrupt_json(tmp_path):
    _write(tmp_path, "noisy_runner", 'print("hello")\n' + GOOD)
    out = _launch(tmp_path, "--describe", "noisy_runner")
    assert out.returncode == 0
    assert json.loads(out.stdout)["args"] == ["n", "label"]


def test_signal_fallback_when_loop_handlers_unsupported(monkeypatch):
    import asyncio

    handlers = {}
    monkeypatch.setattr(signal, "signal", lambda sig, h: handlers.update({sig: h}))
    loop = asyncio.new_event_loop()
    scheduled = []
    ran = []
    try:

        def boom(*a):
            raise NotImplementedError

        monkeypatch.setattr(loop, "add_signal_handler", boom)
        monkeypatch.setattr(
            loop, "call_soon_threadsafe", lambda cb, *a: scheduled.append(cb)
        )
        launch._install_signal_handlers(loop, lambda: ran.append(1))
        assert signal.SIGINT in handlers and signal.SIGTERM in handlers
        handlers[signal.SIGTERM](signal.SIGTERM, None)
    finally:
        loop.close()
    # the handler must hand on_signal to the loop, not run it inline
    assert ran == [] and len(scheduled) == 1
    scheduled[0]()
    assert ran == [1]


BADIMPORT = "x = undefined_name\n"
NEEDARG = """
from helao.core.runners.micro_orch import MicroOrch
async def run(orch: MicroOrch, n: int):
    return None
"""


def test_import_failure_exits_1_with_traceback(tmp_path):
    _write(tmp_path, "badimp_runner", BADIMPORT)
    out = _launch(tmp_path, _cfg(tmp_path), "badimp_runner")
    assert out.returncode == 1
    assert "failed to import" in out.stdout + out.stderr
    assert "NameError" in out.stdout + out.stderr


def test_missing_required_arg_exits_2(tmp_path):
    _write(tmp_path, "need_runner", NEEDARG)
    out = _launch(tmp_path, _cfg(tmp_path), "need_runner")
    assert out.returncode == 2


RACE = """
import asyncio, os, signal, sys
from helao.core.runners import launch as L

class Fake:
    def __init__(self, **kw):
        pass
    def request_stop(self):
        pass
    async def __aenter__(self):
        os.kill(os.getpid(), signal.SIGTERM)
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(0.1)
        return self
    async def __aexit__(self, *a):
        return False

L.MicroOrch = Fake
L.free_port = lambda: 1

async def run(orch):
    await asyncio.sleep(3)

async def main():
    return await asyncio.wait_for(L._run(run, {}, "K", {}, "127.0.0.1"), 10)

sys.exit(asyncio.run(main()))
"""


@posix_only
def test_two_signals_before_task_exists_force_130(tmp_path):
    script = tmp_path / "race.py"
    script.write_text(RACE, encoding="utf-8")
    out = subprocess.run(
        [PY, str(script)],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        timeout=60,
    )
    assert out.returncode == 130, out.stdout + out.stderr


TASKGROUP_STOP = """
import asyncio
from helao.core.runners.micro_orch import MicroOrch, RunnerStopped
async def run(orch: MicroOrch):
    async def worker():
        raise RunnerStopped("stop")
    async with asyncio.TaskGroup() as tg:
        tg.create_task(worker())
"""


def test_stop_inside_taskgroup_exits_0(tmp_path, spawn):
    _write(tmp_path, "tg_runner", TASKGROUP_STOP)
    p = spawn("tg_runner")
    assert p.wait(timeout=60) == 0
