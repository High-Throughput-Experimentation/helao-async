"""``Pidd.close`` kills the servers of one launch group concurrently.

Groups still go in ``KILL_ORDER`` (operator, visualizer, action, orchestrator),
but inside a group each server's grace window used to be waited out one after
another. On hte-ecms-03 (2026-10-14) that was ~5-8 s per action server, about
35 s for the action group alone. Concurrent kills overlap those windows.

Real child processes, Linux path (SIGTERM -> GRACEFUL_WAIT): each child is
spawned with the argv a launched server has, so ``_pid_is_server`` accepts it,
and takes ``EXIT_DELAY`` seconds to exit on SIGTERM.

Run:  conda run -n helao python -m pytest helao/core/tests/test_launch_parallel_teardown.py
"""

import logging as _logging
import os
import select
import subprocess
import sys
import threading
import time

import pytest

import launch

launch.LAUNCH_LOGGER = _logging.getLogger("test_launch_parallel_teardown")

EXIT_DELAY = 1.0
CHILD = (
    "import signal, sys, time\n"
    "def bye(*_):\n"
    f"    time.sleep({EXIT_DELAY}); sys.exit(0)\n"
    "signal.signal(signal.SIGTERM, bye)\n"
    "print('ready', flush=True)\n"
    "while True: time.sleep(0.05)\n"
)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="exercises the SIGTERM path"
)


@pytest.fixture
def pidd(tmp_path):
    p = launch.Pidd(
        pidFile="pids_golden_.pck", pidPath=str(tmp_path), configPrefix="golden"
    )
    yield p
    for proc in p.procs.values():  # never leak a child, even on failure
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def _spawn(pidd, groups: dict[str, list[str]]):
    pidd.servers = {g: {k: {} for k in keys} for g, keys in groups.items()}
    for keys in groups.values():
        for k in keys:
            proc = subprocess.Popen(
                [sys.executable, "-c", CHILD, "fast_launcher.py", "golden", k],
                stdout=subprocess.PIPE,
            )
            pidd.procs[k] = proc  # registered first, so the fixture can reap it
            assert proc.stdout is not None
            ready, _, _ = select.select([proc.stdout], [], [], 15)
            assert ready, f"{k} never signalled ready"
            assert proc.stdout.readline().strip() == b"ready"
            pidd.store_pid(k, "127.0.0.1", 0, proc.pid)


def test_one_group_is_killed_concurrently(pidd, monkeypatch):
    keys = ["MFC", "CALIBRATIONMFC", "CALIBRATIONMFCSECOND", "SAMPLE"]
    _spawn(pidd, {"action": keys})
    assert {k for k, *_ in pidd.list_active()} == set(keys)
    # keep the pickle close() would delete, to read what the kills left in it
    monkeypatch.setattr(launch.os, "remove", lambda path: None)

    t0 = time.monotonic()
    pidd.close()
    elapsed = time.monotonic() - t0

    # serially this is >= 4 * EXIT_DELAY; concurrently about one EXIT_DELAY
    assert elapsed < 2.5 * EXIT_DELAY, f"close took {elapsed:.1f}s"
    assert all(p.poll() is not None for p in pidd.procs.values())
    # every concurrent kill's removal survived the others' rewrites
    pidd.load_global()
    assert pidd.d == {}


def test_one_failing_kill_does_not_abort_the_teardown(pidd, monkeypatch):
    """The other servers of the group, later groups and the sweep still run."""
    _spawn(pidd, {"action": ["A1", "A2"], "orchestrator": ["ORCH"]})
    real_kill = launch.Pidd.kill_server
    failed = []

    def flaky_kill(self, k):
        if k == "A1" and not failed:
            failed.append(k)
            raise EOFError("pickle read mid-write")
        return real_kill(self, k)

    monkeypatch.setattr(launch.Pidd, "kill_server", flaky_kill)
    pidd.close()

    assert failed == ["A1"]
    assert all(p.poll() is not None for p in pidd.procs.values())
    assert not os.path.exists(pidd.pidFilePath)


def test_groups_are_still_killed_in_order(pidd, monkeypatch):
    _spawn(pidd, {"operator": ["OP"], "action": ["A1", "A2"]})
    spans: dict[str, tuple[float, float]] = {}
    real_kill = launch.Pidd.kill_server

    def timed_kill(self, k):
        start = time.monotonic()
        try:
            return real_kill(self, k)
        finally:
            spans[k] = (start, time.monotonic())

    monkeypatch.setattr(launch.Pidd, "kill_server", timed_kill)
    pidd.close()

    assert spans["OP"][1] <= min(spans["A1"][0], spans["A2"][0])
    # and the action pair overlapped
    assert max(spans["A1"][0], spans["A2"][0]) < min(spans["A1"][1], spans["A2"][1])


def test_concurrent_forgets_lose_no_removal(pidd, monkeypatch):
    keys = [f"S{i}" for i in range(8)]
    for i, k in enumerate(keys):
        pidd.store_pid(k, "127.0.0.1", 0, 100000 + i)

    real_write = launch.Pidd.write_global

    def slow_write(self):
        time.sleep(0.01)  # widen the read-modify-write window
        real_write(self)

    monkeypatch.setattr(launch.Pidd, "write_global", slow_write)
    threads = [threading.Thread(target=pidd._forget, args=(k,)) for k in keys]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    pidd.load_global()
    assert pidd.d == {}
