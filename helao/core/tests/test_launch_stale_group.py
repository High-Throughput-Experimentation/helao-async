"""Tests for launch.py's startup guard against a group that is still running.

Nothing used to check whether the PIDs in ``pids_<config>_<extraopt>.pck`` were
alive before launching. A second launch then failed to bind the held ports,
logged "already running" at INFO for every server, and silently deferred to the
old processes -- which kept serving the code they were started with. That
produced a measurement from 12-hour-old code with every log line reporting
success.

The guard has to distinguish three states, and the middle one is why
``psutil.pid_exists`` alone is not enough: falsely claiming an unrelated process
is a live HELAO server would be worse than the bug.

Run:  conda run -n helao python -m pytest helao/core/tests/test_launch_stale_group.py
"""

import logging as _logging

import psutil
import pytest

import launch

launch.LAUNCH_LOGGER = _logging.getLogger("test_launch_stale_group")


CONF = {
    "servers": {
        "ORCH": {"host": "127.0.0.1", "port": 8001, "group": "orchestrator"},
        "SIM": {"host": "127.0.0.1", "port": 8002, "group": "action"},
    }
}


class _FakeProc:
    """psutil.Process stand-in for one scenario."""

    def __init__(self, cmdline, status="running"):
        self._cmdline = cmdline
        self._status = status

    def status(self):
        return self._status

    def cmdline(self):
        return self._cmdline


@pytest.fixture
def pidd(tmp_path):
    """A Pidd over an empty pickle in a tmp STATES dir, scoped to 'golden'."""
    return launch.Pidd(
        pidFile="pids_golden_.pck", pidPath=str(tmp_path), configPrefix="golden"
    )


def _fake_world(monkeypatch, procs):
    """Present ``procs`` ({pid: _FakeProc}) as the live process table."""
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: pid in procs)

    def _process(pid):
        if pid not in procs:
            raise psutil.NoSuchProcess(pid)
        return procs[pid]

    monkeypatch.setattr(psutil, "Process", _process)


# -- identity predicate -----------------------------------------------------


def test_a_live_server_of_this_config_is_ours(monkeypatch, pidd):
    _fake_world(
        monkeypatch,
        {77: _FakeProc(["python", "-u", "fast_launcher.py", "golden", "SIM"])},
    )
    assert pidd._pid_is_server(77, "SIM") is True


def test_a_full_config_path_still_matches_the_prefix(monkeypatch, pidd):
    """launch.py forwards confArg verbatim, so the cmdline may hold a path."""
    _fake_world(
        monkeypatch,
        {
            77: _FakeProc(
                [
                    "python",
                    "-u",
                    "fast_launcher.py",
                    "/repo/helao/deploy/test/configs/golden.yml",
                    "SIM",
                ]
            )
        },
    )
    assert pidd._pid_is_server(77, "SIM") is True


def test_the_same_server_key_under_another_config_is_not_ours(monkeypatch, pidd):
    """A recycled PID could be a different station's server of the same name."""
    _fake_world(
        monkeypatch,
        {77: _FakeProc(["python", "-u", "fast_launcher.py", "adss3", "SIM"])},
    )
    assert pidd._pid_is_server(77, "SIM") is False


def test_an_unrelated_process_on_a_recycled_pid_is_not_ours(monkeypatch, pidd):
    _fake_world(monkeypatch, {77: _FakeProc(["/usr/bin/some_daemon", "--serve"])})
    assert pidd._pid_is_server(77, "SIM") is False


def test_a_live_reflex_server_is_recognised(monkeypatch, pidd):
    """Reflex servers are launched the same way. While reflex_launcher.py was
    missing from the check, list_active() omitted them, so close() never killed
    them and CTRL-x left the UI holding both of its ports."""
    _fake_world(
        monkeypatch,
        {78: _FakeProc(["python", "-u", "reflex_launcher.py", "golden", "UI"])},
    )
    assert pidd._pid_is_server(78, "UI") is True


def test_a_prefixless_pidd_keeps_the_looser_check(monkeypatch, tmp_path):
    p = launch.Pidd(pidFile="pids_x_.pck", pidPath=str(tmp_path))
    _fake_world(
        monkeypatch,
        {77: _FakeProc(["python", "-u", "fast_launcher.py", "whatever", "SIM"])},
    )
    assert p._pid_is_server(77, "SIM") is True


# -- resolve_existing_group -------------------------------------------------


def test_all_dead_pids_are_cleared_without_complaint(monkeypatch, pidd):
    """The ordinary case after any clean shutdown. Must not become noisy."""
    pidd.store_pid("SIM", "127.0.0.1", 8002, 77)
    pidd.store_pid("ORCH", "127.0.0.1", 8001, 78)
    _fake_world(monkeypatch, {})
    assert launch.resolve_existing_group(pidd, CONF) == []
    assert pidd.d == {}
    pidd.load_global()
    assert pidd.d == {}  # pruned on disk too, not just in memory


def test_a_live_but_unrelated_pid_is_ignored(monkeypatch, pidd):
    pidd.store_pid("SIM", "127.0.0.1", 8002, 77)
    _fake_world(monkeypatch, {77: _FakeProc(["/usr/bin/some_daemon"])})
    assert launch.resolve_existing_group(pidd, CONF) == []
    assert pidd.d == {}


def test_a_live_group_aborts_the_launch(monkeypatch, pidd):
    pidd.store_pid("SIM", "127.0.0.1", 8002, 77)
    _fake_world(
        monkeypatch,
        {77: _FakeProc(["python", "-u", "fast_launcher.py", "golden", "SIM"])},
    )
    with pytest.raises(launch.StaleGroupError) as excinfo:
        launch.resolve_existing_group(pidd, CONF)
    report = excinfo.value.report()
    assert "SIM" in report and "77" in report and "8002" in report
    assert "--reconnect" in report and "--force-relaunch" in report


def test_reconnect_attaches_to_the_live_group_instead(monkeypatch, pidd):
    pidd.store_pid("SIM", "127.0.0.1", 8002, 77)
    _fake_world(
        monkeypatch,
        {77: _FakeProc(["python", "-u", "fast_launcher.py", "golden", "SIM"])},
    )
    members = launch.resolve_existing_group(pidd, CONF, reconnect=True)
    assert [m[0] for m in members] == ["SIM"]
    assert "SIM" in pidd.d  # left in place for launch_server_groups to skip


def test_force_relaunch_tears_the_live_group_down_first(monkeypatch, pidd):
    pidd.store_pid("SIM", "127.0.0.1", 8002, 77)
    _fake_world(
        monkeypatch,
        {77: _FakeProc(["python", "-u", "fast_launcher.py", "golden", "SIM"])},
    )
    called = []
    monkeypatch.setattr(
        launch, "shutdown_live_members", lambda p, c: called.append((p, c)) or True
    )
    members = launch.resolve_existing_group(pidd, CONF, force_relaunch=True)
    assert [m[0] for m in members] == ["SIM"]
    assert len(called) == 1


def test_force_relaunch_aborts_if_the_group_survives_teardown(monkeypatch, pidd):
    """A survivor still holds its port, so launching would silently skip it."""
    pidd.store_pid("SIM", "127.0.0.1", 8002, 77)
    _fake_world(
        monkeypatch,
        {77: _FakeProc(["python", "-u", "fast_launcher.py", "golden", "SIM"])},
    )
    monkeypatch.setattr(launch, "shutdown_live_members", lambda p, c: False)
    with pytest.raises(launch.StaleGroupError):
        launch.resolve_existing_group(pidd, CONF, force_relaunch=True)


# -- liveness of an adopted (non-child) process ------------------------------


class _UnreapableProc:
    """A process this launcher did not spawn, so wait() can only time out.

    Mirrors the real adopted case: the server has exited but lingers as a zombie
    owned by its true parent, and ``psutil.Process.wait()`` on a non-child
    cannot reap it and so reports a timeout indefinitely.
    """

    def __init__(self, pid=77, status=psutil.STATUS_ZOMBIE):
        self.pid = pid
        self._status = status

    def wait(self, timeout=None):
        raise psutil.TimeoutExpired(timeout or 0)

    def status(self):
        return self._status


def test_an_adopted_zombie_counts_as_gone(monkeypatch, pidd):
    """Otherwise a server that exited cleanly is signalled again and then
    reported as 'Failed to terminate even after SIGKILL' -- a spurious ERROR
    (and, on a station, an alert email) for every server in the group."""
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: True)
    assert pidd._wait_gone(_UnreapableProc(), 0.01, "SIM") is True


def test_an_adopted_live_process_is_not_gone(monkeypatch, pidd):
    """The escalation path must still fire for something genuinely running."""
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: True)
    proc = _UnreapableProc(status=psutil.STATUS_RUNNING)
    assert pidd._wait_gone(proc, 0.01, "SIM") is False


def test_a_vanished_pid_is_gone(monkeypatch, pidd):
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: False)
    assert pidd._wait_gone(_UnreapableProc(), 0.01, "SIM") is True


def test_already_dead_is_conservative_when_it_cannot_tell(monkeypatch, pidd):
    class _Denied(_UnreapableProc):
        def status(self):
            raise psutil.AccessDenied(self.pid)

    monkeypatch.setattr(psutil, "pid_exists", lambda pid: True)
    assert pidd._already_dead(_Denied()) is False


def test_group_map_buckets_servers_by_group():
    mapped = launch.group_map(CONF)
    assert mapped["orchestrator"] == {"ORCH": CONF["servers"]["ORCH"]}
    assert mapped["action"] == {"SIM": CONF["servers"]["SIM"]}
    assert mapped["visualizer"] == {}
    assert set(mapped) == set(launch.LAUNCH_ORDER)
