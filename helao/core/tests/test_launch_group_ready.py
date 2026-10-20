"""The next launch group waits for this group's servers to answer.

A fixed 3 s pause used to separate the groups. The orchestrator then gives each
action server ~30 s of ``attach_client`` retries; on a slow station an action
server could finish booting after that and leave the orchestrator unable to
run experiments. ``wait_group_ready`` polls each FastAPI server just launched
in the group on ``/get_status`` instead (bounded, never fatal).
"""

import logging
import types

import pytest

import launch


@pytest.fixture(autouse=True)
def _logger(monkeypatch):
    # LAUNCH_LOGGER is created by launch.main(); importing launch leaves it None
    monkeypatch.setattr(launch, "LAUNCH_LOGGER", logging.getLogger("test_launch"))


class _Proc:
    def __init__(self, exited=False):
        self._exited = exited

    def poll(self):
        return 0 if self._exited else None


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _patch_ready(monkeypatch, answers, clock=None, step=2.0):
    """``answers``: per host, the poll number at which it starts answering."""
    calls = []

    def ready(host, port, timeout=30.0, interval=0.5):
        calls.append(host)
        if clock is not None:
            clock.t += step
        return calls.count(host) >= answers.get(host, 10**9)

    monkeypatch.setattr(launch, "wait_for_server_ready", ready)
    return calls


def test_waits_for_every_launched_fastapi_server(monkeypatch):
    calls = _patch_ready(monkeypatch, {"a": 3, "b": 1})
    sleeps = []
    launched = [("A", "a", 1, _Proc()), ("B", "b", 2, _Proc())]
    launch.wait_group_ready("action", launched, [], sleep=sleeps.append)
    assert calls == ["a", "a", "a", "b"]
    assert sleeps == []  # no fixed pause once there is something to poll


def test_an_exited_server_is_not_waited_on(monkeypatch):
    calls = _patch_ready(monkeypatch, {})
    launch.wait_group_ready("action", [("A", "a", 1, _Proc(exited=True))], [])
    assert calls == ["a"]


def test_a_server_that_never_answers_is_given_up_on(monkeypatch):
    clock = _Clock()
    calls = _patch_ready(monkeypatch, {}, clock=clock)
    launch.wait_group_ready("action", [("A", "a", 1, _Proc())], [], now=clock)
    assert clock.t > launch.GROUP_READY_TIMEOUT_S
    assert len(calls) <= launch.GROUP_READY_TIMEOUT_S / 2 + 2


def test_a_group_of_only_bokeh_or_reflex_servers_keeps_the_pause():
    sleeps = []
    launch.wait_group_ready("visualizer", [], ["VIS"], sleep=sleeps.append)
    assert sleeps == [3]


def test_a_group_that_launched_nothing_does_not_wait():
    sleeps = []
    launch.wait_group_ready("operator", [], [], sleep=sleeps.append)
    assert sleeps == []


def test_launch_server_groups_gates_each_group_before_the_next(monkeypatch, tmp_path):
    """The orchestrator is spawned only after the action group was waited on."""
    events = []

    class _Popen:
        def __init__(self, cmd, **kw):
            events.append(("spawn", cmd[-1] if cmd[-1] != "--restore" else cmd[-2]))
            self.pid = 1000 + len(events)

        def poll(self):
            return None

    monkeypatch.setattr(launch.subprocess, "Popen", _Popen)
    monkeypatch.setattr(launch.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        launch,
        "wait_group_ready",
        lambda group, fast, other, **kw: events.append(
            ("wait", group, [s[0] for s in fast])
        ),
    )
    monkeypatch.setattr(launch.CONSOLE, "register", lambda *a: None)
    monkeypatch.setattr(launch.CONSOLE, "child_env", lambda: {})
    monkeypatch.setattr(launch.CONSOLE, "spawn_kwargs", lambda: {})

    stored = {}
    pidd = types.SimpleNamespace(
        codeKeys=["fast", "bokeh", "reflex"],
        procs={},
        list_active=lambda: [],
        store_pid=lambda k, h, p, pid: stored.__setitem__(k, pid),
    )
    conf = {
        "servers": {
            "SIM": {"group": "action", "fast": "ws_simulator", "host": "h", "port": 1},
            "PSTAT": {
                "group": "action",
                "fast": "gamry_server2",
                "host": "h",
                "port": 2,
            },
            "ORCH": {
                "group": "orchestrator",
                "fast": "async_orch2",
                "host": "h",
                "port": 3,
            },
            "VIS": {
                "group": "visualizer",
                "bokeh": "action_visualizer",
                "host": "h",
                "port": 4,
            },
        }
    }
    launch.launch_server_groups(pidd, "cfg", conf, str(tmp_path))
    assert events.index(("wait", "action", ["SIM", "PSTAT"])) < events.index(
        ("spawn", "ORCH")
    )
    assert ("wait", "orchestrator", ["ORCH"]) in events
    # the last group is never waited on
    assert not any(e[0] == "wait" and e[1] == "visualizer" for e in events)
