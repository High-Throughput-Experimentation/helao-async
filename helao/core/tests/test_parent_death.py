"""Tests for helao.helpers.parent_death.

Covers the three things the kernel parent-death mechanism has to get right:
arming works on Linux and no-ops elsewhere, a parent that died before the call
is detected anyway, and the notification is *not* obeyed when it was really the
spawning thread that exited or when the launcher detached on purpose.

Run:  conda run -n helao python -m pytest helao/core/tests/test_parent_death.py
"""

import os
import signal
import subprocess
import sys

import pytest

from helao.helpers import parent_death as pdeath

# -- platform gating --------------------------------------------------------


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="linux-only")
def test_arming_succeeds_on_linux():
    try:
        assert pdeath.arm_parent_death_signal(expected_ppid=os.getppid()) is True
    finally:
        signal.signal(signal.SIGUSR1, signal.SIG_DFL)
        pdeath._set_pdeathsig(0)


def test_arming_is_a_noop_off_linux(monkeypatch):
    """Windows must be untouched: no prctl, and no handler installed either."""
    monkeypatch.setattr(pdeath, "_supported", lambda: False)
    installed = []
    monkeypatch.setattr(pdeath.signal, "signal", lambda *a: installed.append(a) or None)
    assert pdeath.arm_parent_death_signal(expected_ppid=424242) is False
    assert installed == []


def test_set_pdeathsig_is_false_off_linux(monkeypatch):
    monkeypatch.setattr(pdeath, "_supported", lambda: False)
    assert pdeath._set_pdeathsig(signal.SIGUSR1) is False


# -- parent_is_gone ---------------------------------------------------------


def test_parent_is_gone_is_false_while_the_parent_lives():
    assert pdeath.parent_is_gone(4242, getppid=lambda: 4242) is False


def test_parent_is_gone_is_true_once_reparented_to_init():
    assert pdeath.parent_is_gone(4242, getppid=lambda: 1) is True


def test_parent_is_gone_is_true_for_a_subreaper_reparent():
    """systemd --user is a subreaper, so an orphan need not land on pid 1."""
    assert pdeath.parent_is_gone(4242, getppid=lambda: 900) is True


def test_parent_is_gone_is_false_without_a_real_parent_to_compare():
    # A hand-started server must never decide it has been orphaned.
    assert pdeath.parent_is_gone(None, getppid=lambda: 1) is False
    assert pdeath.parent_is_gone(1, getppid=lambda: 1) is False
    assert pdeath.parent_is_gone(0, getppid=lambda: 1) is False


# -- expected_parent_pid ----------------------------------------------------


def test_expected_parent_pid_prefers_the_published_launcher_pid():
    assert pdeath.expected_parent_pid({pdeath.PARENT_PID_ENV: "1234"}) == 1234


def test_expected_parent_pid_falls_back_on_a_garbage_value():
    assert pdeath.expected_parent_pid({pdeath.PARENT_PID_ENV: "nope"}) == os.getppid()


def test_expected_parent_pid_falls_back_when_unset():
    assert pdeath.expected_parent_pid({}) == os.getppid()


# -- detach marker ----------------------------------------------------------


def test_detach_marker_path_is_namespaced_by_prefix_and_extraopt(tmp_path):
    a = pdeath.detach_marker_path(str(tmp_path), "golden", "")
    b = pdeath.detach_marker_path(str(tmp_path), "golden", "liveonly")
    c = pdeath.detach_marker_path(str(tmp_path), "adss3", "")
    assert a != b != c and a != c


def test_write_then_clear_a_detach_marker(tmp_path):
    path = pdeath.detach_marker_path(str(tmp_path), "golden", "")
    assert pdeath.write_detach_marker(path) is True
    assert os.path.exists(path)
    pdeath.clear_detach_marker(path)
    assert not os.path.exists(path)


def test_clearing_an_absent_marker_is_silent(tmp_path):
    pdeath.clear_detach_marker(str(tmp_path / "nope.marker"))


def test_monitor_detached_is_false_when_unset_or_missing(tmp_path):
    assert pdeath.monitor_detached({}) is False
    assert (
        pdeath.monitor_detached({pdeath.DETACH_MARKER_ENV: str(tmp_path / "no")})
        is False
    )


def test_monitor_detached_is_true_once_the_marker_exists(tmp_path):
    path = str(tmp_path / "detached.marker")
    pdeath.write_detach_marker(path)
    assert pdeath.monitor_detached({pdeath.DETACH_MARKER_ENV: path}) is True


# -- the fork/prctl race ----------------------------------------------------


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="linux-only")
def test_a_parent_that_already_died_makes_the_child_exit_at_once():
    """prctl cannot help once the parent is gone, so arm() checks directly."""
    fired = []
    try:
        pdeath.arm_parent_death_signal(
            expected_ppid=424242,  # certainly not our parent
            on_orphaned=lambda: fired.append(1),
            env={},
        )
    finally:
        signal.signal(signal.SIGUSR1, signal.SIG_DFL)
        pdeath._set_pdeathsig(0)
    assert fired == [1]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="linux-only")
def test_a_detached_launcher_does_not_make_the_child_exit(tmp_path):
    marker = str(tmp_path / "detached.marker")
    pdeath.write_detach_marker(marker)
    fired = []
    try:
        pdeath.arm_parent_death_signal(
            expected_ppid=424242,
            on_orphaned=lambda: fired.append(1),
            env={pdeath.DETACH_MARKER_ENV: marker},
        )
    finally:
        signal.signal(signal.SIGUSR1, signal.SIG_DFL)
        pdeath._set_pdeathsig(0)
    assert fired == []


# -- the installed handler --------------------------------------------------


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="linux-only")
def test_a_notification_while_the_launcher_lives_is_ignored():
    """PDEATHSIG follows the parent *thread*: launch.py spawns restarts from its
    hotkey and hot-reload threads, so a child can be signalled while its
    launcher is healthy. Obeying that would kill a server mid-run."""
    try:
        pdeath.arm_parent_death_signal(expected_ppid=os.getppid(), env={})
        signal.raise_signal(signal.SIGUSR1)  # would terminate if unhandled
    finally:
        signal.signal(signal.SIGUSR1, signal.SIG_DFL)
        pdeath._set_pdeathsig(0)
    assert True  # still running


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="linux-only")
def test_a_notification_after_a_deliberate_detach_is_ignored(tmp_path):
    marker = str(tmp_path / "detached.marker")
    pdeath.write_detach_marker(marker)
    try:
        pdeath.arm_parent_death_signal(
            expected_ppid=424242,
            on_orphaned=lambda: None,
            env={pdeath.DETACH_MARKER_ENV: marker},
        )
        signal.raise_signal(signal.SIGUSR1)
    finally:
        signal.signal(signal.SIGUSR1, signal.SIG_DFL)
        pdeath._set_pdeathsig(0)
    assert True  # still running


# The remaining case terminates the process by design, so it needs its own.
_ORPHAN_SCRIPT = """
import signal, sys
sys.path.insert(0, {repo!r})
from helao.helpers import parent_death

signal.signal(signal.SIGTERM, lambda *a: (print("SIGTERM", flush=True), sys.exit(7)))
parent_death.arm_parent_death_signal(
    expected_ppid=424242, on_orphaned=lambda: None, env={{}}
)
signal.raise_signal(signal.SIGUSR1)
print("NOT REACHED", flush=True)
"""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="linux-only")
def test_a_real_orphan_notification_escalates_to_sigterm(tmp_path):
    """The handler must hand off to SIGTERM, not exit on the spot: SIGTERM is
    what runs uvicorn's graceful shutdown and therefore the driver disconnect."""
    repo = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    script = tmp_path / "orphan.py"
    script.write_text(_ORPHAN_SCRIPT.format(repo=repo))
    out = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=60
    )
    assert "SIGTERM" in out.stdout, out
    assert "NOT REACHED" not in out.stdout, out
    assert out.returncode == 7, out
