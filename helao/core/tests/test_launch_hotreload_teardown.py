"""The hot-reload watcher stands down when a group teardown starts.

On hte-ecms-03 (2026-10-14 11:57) a CTRL-x began its /shutdown sweep, and four
seconds in, the hot-reload watcher -- which never looked at the teardown --
saw a pulled commit, judged PSTAT idle and relaunched it, re-initializing the
Gamry; the teardown then had to kill the fresh process again. ``watch_until``
ends the watcher loop on the teardown event, and ``guarded_restart`` refuses a
restart before it starts and before it relaunches.

Run:  conda run -n helao python -m pytest helao/core/tests/test_launch_hotreload_teardown.py
"""

import ast
import logging as _logging
import pathlib
import threading
import time

import pytest

import launch


@pytest.fixture(autouse=True)
def _launch_logger(monkeypatch):
    monkeypatch.setattr(
        launch, "LAUNCH_LOGGER", _logging.getLogger("test_launch_hotreload_teardown")
    )


def test_watcher_never_polls_once_teardown_has_started():
    stop = threading.Event()
    stop.set()
    calls = []
    t0 = time.monotonic()
    launch.watch_until(stop, 60, lambda: calls.append(1))
    assert calls == [] and time.monotonic() - t0 < 1


def test_watcher_polls_until_stopped():
    stop = threading.Event()
    calls = []

    def poll():
        calls.append(1)
        if len(calls) == 3:
            stop.set()

    launch.watch_until(stop, 0.01, poll)
    assert len(calls) == 3


def test_teardown_from_another_thread_ends_a_long_wait_promptly():
    """The watcher must not sit out its poll interval (30 s by default)."""
    stop = threading.Event()
    calls = []
    watcher = threading.Thread(
        target=launch.watch_until, args=(stop, 60, lambda: calls.append(1))
    )
    watcher.start()
    time.sleep(0.1)
    t0 = time.monotonic()
    stop.set()
    watcher.join(timeout=5)
    assert not watcher.is_alive()
    assert time.monotonic() - t0 < 1 and calls == []


def _restart(teardown, set_during_stop=False):
    log = []

    def stop_old():
        log.append("stop")
        if set_during_stop:
            teardown.set()

    result = launch.guarded_restart(
        teardown, "PSTAT", stop_old, lambda: log.append("start")
    )
    return result, log


def test_restart_runs_normally_without_a_teardown():
    assert _restart(threading.Event()) == (True, ["stop", "start"])


def test_restart_is_refused_once_teardown_has_started():
    teardown = threading.Event()
    teardown.set()
    assert _restart(teardown) == (False, [])


def test_teardown_starting_mid_restart_prevents_the_relaunch():
    """The ecms-03 case: the old server is stopped, but no new one is spawned."""
    assert _restart(threading.Event(), set_during_stop=True) == (False, ["stop"])


def test_a_non_positive_interval_is_refused_not_spun():
    """Event.wait(<=0) returns at once; the watcher would hammer git forever."""
    for bad in (0, -5):
        with pytest.raises(ValueError):
            launch.watch_until(threading.Event(), bad, lambda: None)


# --- wiring ------------------------------------------------------------------
# thread_hotreload, restart_server, teardown_group and relaunch_all are closures
# inside main(), reachable only by running a whole group. These pin, in the
# parsed source, the connections that close the ecms-03 race; each assertion
# fails if its connection is dropped while the helper tests above stay green.

_MAIN = next(
    n
    for n in ast.parse(pathlib.Path(launch.__file__).read_text(encoding="utf-8")).body
    if isinstance(n, ast.FunctionDef) and n.name == "main"
)


def _fn(name: str) -> ast.FunctionDef:
    return next(
        n for n in ast.walk(_MAIN) if isinstance(n, ast.FunctionDef) and n.name == name
    )


def _calls(node: ast.AST, name: str) -> list:
    return [
        c
        for c in ast.walk(node)
        if isinstance(c, ast.Call)
        and (
            (isinstance(c.func, ast.Name) and c.func.id == name)
            or (isinstance(c.func, ast.Attribute) and c.func.attr == name)
        )
    ]


def _is_teardown_event(arg: ast.AST) -> bool:
    return isinstance(arg, ast.Name) and arg.id == "teardown_started"


def _teardown_checks(node: ast.AST) -> list:
    return [
        c
        for c in _calls(node, "is_set")
        if isinstance(c.func, ast.Attribute) and _is_teardown_event(c.func.value)
    ]


def test_the_watcher_waits_on_the_teardown_event():
    (call,) = _calls(_fn("thread_hotreload"), "watch_until")
    assert _is_teardown_event(call.args[0])


def test_the_watcher_rechecks_teardown_around_each_restart():
    assert len(_teardown_checks(_fn("poll_once"))) >= 2


def test_restart_server_goes_through_guarded_restart():
    (call,) = _calls(_fn("restart_server"), "guarded_restart")
    assert _is_teardown_event(call.args[0])
    returns = [r for r in ast.walk(_fn("restart_server")) if isinstance(r, ast.Return)]
    assert any(r.value is call for r in returns)


def test_teardown_holds_the_lock_across_sweep_and_kill():
    fn = _fn("teardown_group")
    (lock_block,) = [
        w
        for w in ast.walk(fn)
        if isinstance(w, ast.With)
        and any(
            isinstance(i.context_expr, ast.Name) and i.context_expr.id == "pidd_lock"
            for i in w.items
        )
    ]
    assert _calls(lock_block, "graceful_shutdown_all") and _calls(lock_block, "close")
    (set_call,) = [
        c
        for c in _calls(fn, "set")
        if isinstance(c.func, ast.Attribute) and _is_teardown_event(c.func.value)
    ]
    assert set_call.lineno < lock_block.lineno, "set the event before waiting"


def test_relaunch_all_checks_teardown_before_relaunching():
    fn = _fn("relaunch_all")
    (relaunch,) = _calls(fn, "launch_server_groups")
    assert any(c.lineno < relaunch.lineno for c in _teardown_checks(fn))
