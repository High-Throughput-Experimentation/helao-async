"""Tests for the Windows job-object containment in :mod:`helao.helpers.win_job`.

Two halves, and the split matters because this runs on Linux:

* the **platform guarantee** -- every entry point must be an inert no-op off
  Windows, since that is what makes it safe to call unconditionally from
  ``launch.py``. Directly testable here.
* the **call sequence** -- exercised against a fake ``kernel32``, because the
  real one does not exist on this machine. That checks the parts a Windows box
  would only reveal by behaving badly: that the kill-on-close flag is actually
  set, that a failed assignment closes the handle it opened instead of leaking
  it, and above all that a detach *clears* the flag rather than leaving the job
  to kill the group CTRL-d is meant to preserve.

The fake proves the arguments and the ordering, not that Windows honours them.
The Job Object behaviour itself is station-unverified.
"""

import ctypes
from typing import Final

import pytest

from helao.helpers import win_job

# From winnt.h; duplicated rather than imported from win_job so a typo there is a
# test failure instead of a tautology.
KILL_ON_JOB_CLOSE: Final[int] = 0x00002000
EXTENDED_LIMIT_INFORMATION: Final[int] = 9


class _Fn:
    """A callable that accepts a ``restype`` assignment.

    ``win_job`` sets ``.restype`` on the function pointers it calls, as ctypes
    requires for anything returning a handle -- without it a 64-bit HANDLE is
    truncated to a C int. A bound method cannot carry that attribute, so the
    fake's functions have to be objects rather than methods; getting this wrong
    is what a plain ``Mock`` would paper over.
    """

    def __init__(self, fn):
        self._fn = fn
        self.restype = None

    def __call__(self, *args):
        return self._fn(*args)


class FakeKernel32:
    """Minimal stand-in recording the calls ``win_job`` makes."""

    def __init__(self, *, create=1234, assign_ok=True, set_ok=True, ctrl_ok=True):
        self._create = create
        self._assign_ok = assign_ok
        self._set_ok = set_ok
        self._ctrl_ok = ctrl_ok
        self.limit_flags: list[int] = []
        self.assigned: list[int] = []
        self.closed: list[int] = []
        self.ctrl_events: list[tuple[int, int]] = []
        self.CreateJobObjectW = _Fn(lambda name, attrs: self._create)
        self.GetCurrentProcess = _Fn(lambda: 999)

    def SetInformationJobObject(self, handle, klass, info, size):
        assert klass == EXTENDED_LIMIT_INFORMATION
        if self._set_ok:
            self.limit_flags.append(info._obj.BasicLimitInformation.LimitFlags)
        return 1 if self._set_ok else 0

    def AssignProcessToJobObject(self, job, proc):
        if self._assign_ok:
            self.assigned.append(job.value)
        return 1 if self._assign_ok else 0

    def CloseHandle(self, handle):
        self.closed.append(handle.value)
        return 1

    def GenerateConsoleCtrlEvent(self, event, pid):
        if self._ctrl_ok:
            self.ctrl_events.append((event, pid))
        return 1 if self._ctrl_ok else 0

    def __getattr__(self, name):
        raise AssertionError(f"unexpected kernel32 call: {name}")


@pytest.fixture
def fake(monkeypatch):
    """Install a fake kernel32 and pretend this is Windows."""

    def _install(**kwargs):
        k32 = FakeKernel32(**kwargs)
        # CreateJobObjectW.restype is assigned by the module; allow it.
        monkeypatch.setattr(win_job, "_kernel32", lambda: k32)
        monkeypatch.setattr(win_job, "supported", lambda: True)
        return k32

    return _install


# --- the platform guarantee -------------------------------------------------


def test_every_entry_point_is_a_no_op_off_windows() -> None:
    """Nothing here may do anything on Linux.

    ``launch.py`` calls these unconditionally, so "inert off Windows" is the
    property that keeps the Linux path unchanged. Asserted as one test over
    every entry point rather than one each, because the risk is a *new* function
    that forgets the guard.
    """
    assert win_job.supported() is False
    assert win_job.assign_launcher() is None
    assert win_job.spawn_creationflags() == 0
    assert win_job.ctrl_break(1) is False
    # True, not False: with no job holding the group, detaching is already safe.
    assert win_job.release_for_detach(None) is True


def test_release_for_detach_accepts_a_missing_handle() -> None:
    """A None handle must report success, not failure.

    That is the Linux path and also the path where assignment failed, and in
    both the group genuinely does survive the launcher. Reporting False would
    make ``launch.py`` log an alarming error on every CTRL-d on Linux.
    """
    assert win_job.release_for_detach(None) is True


# --- the call sequence, against a fake kernel32 -----------------------------


def test_assign_launcher_sets_kill_on_job_close(fake) -> None:
    """The job must be created with kill-on-close and joined by this process."""
    k32 = fake()
    handle = win_job.assign_launcher()
    assert handle == 1234
    assert k32.limit_flags == [KILL_ON_JOB_CLOSE]
    assert k32.assigned == [1234]
    assert k32.closed == [], "a successfully assigned job must not be closed"


def test_assign_launcher_closes_the_handle_when_assignment_fails(fake) -> None:
    """A refused assignment must not leak the job handle.

    ``AssignProcessToJobObject`` fails with access-denied when an outer job
    forbids breakaway -- a service manager or CI agent. Returning None without
    closing would leak a kernel handle for the life of the launcher.
    """
    k32 = fake(assign_ok=False)
    assert win_job.assign_launcher() is None
    assert k32.closed == [1234]


def test_assign_launcher_gives_up_when_the_job_cannot_be_created(fake) -> None:
    """A failed CreateJobObjectW yields None and touches nothing else."""
    k32 = fake(create=0)
    assert win_job.assign_launcher() is None
    assert k32.assigned == []
    assert k32.closed == []


def test_assign_launcher_closes_the_handle_when_the_limit_is_refused(fake) -> None:
    """A job that would not take the limit is useless and must be closed.

    Keeping it would be worse than not having it: the handle would be held for
    the process lifetime while providing no containment at all.
    """
    k32 = fake(set_ok=False)
    assert win_job.assign_launcher() is None
    assert k32.closed == [1234]


def test_detach_clears_the_kill_on_close_limit(fake) -> None:
    """CTRL-d must drop the flag, or the job kills the group it should preserve.

    The single most important assertion in this file. A process cannot be
    removed from a job, so clearing ``LimitFlags`` is the only way a detached
    group survives the launcher exiting -- and if this regresses, CTRL-d on
    Windows silently becomes CTRL-x.
    """
    k32 = fake()
    win_job.assign_launcher()
    assert k32.limit_flags == [KILL_ON_JOB_CLOSE]
    assert win_job.release_for_detach(1234) is True
    assert k32.limit_flags == [KILL_ON_JOB_CLOSE, 0], "the flag must be cleared"


def test_detach_reports_failure_when_the_limit_cannot_be_cleared(fake) -> None:
    """A refused clear must return False so the caller can say so loudly."""
    k32 = fake(set_ok=False)
    assert win_job.release_for_detach(1234) is False


def test_ctrl_break_targets_the_process_group(fake) -> None:
    """CTRL_BREAK_EVENT is 1 and is addressed to the pid as a group id."""
    k32 = fake()
    assert win_job.ctrl_break(4321) is True
    assert k32.ctrl_events == [(1, 4321)]


def test_ctrl_break_reports_failure_rather_than_raising(fake) -> None:
    """A failed event must be False, so the caller escalates instead of hanging.

    Returning True on failure would make ``kill_server`` wait the full
    ``GRACEFUL_WAIT`` for a shutdown nobody was asked to perform.
    """
    fake(ctrl_ok=False)
    assert win_job.ctrl_break(4321) is False


def test_new_process_group_can_be_disabled_by_env(fake, monkeypatch) -> None:
    """The escape hatch must actually switch the flag off.

    A station that hits a vendor-SDK interaction needs to drop the
    new-process-group change without losing the job object with it.
    """
    fake()
    assert win_job.spawn_creationflags(env={}) == win_job.CREATE_NEW_PROCESS_GROUP
    assert win_job.spawn_creationflags(env={win_job.NEW_PROCESS_GROUP_ENV: "0"}) == 0
    assert (
        win_job.spawn_creationflags(env={win_job.NEW_PROCESS_GROUP_ENV: "1"})
        == win_job.CREATE_NEW_PROCESS_GROUP
    )


def test_create_new_process_group_matches_the_documented_value() -> None:
    """0x200 is CREATE_NEW_PROCESS_GROUP.

    Re-published as a plain int so it can be referenced off Windows, which means
    nothing cross-checks it against ``subprocess`` at runtime on this platform.
    """
    assert win_job.CREATE_NEW_PROCESS_GROUP == 0x00000200


def test_structure_layout_is_the_documented_extended_limit_information() -> None:
    """The struct must match ``JOBOBJECT_EXTENDED_LIMIT_INFORMATION``.

    A short or misordered struct is the failure mode with no symptom on Linux
    and a silently ignored limit on Windows: ``SetInformationJobObject``
    validates the size, so a wrong one is rejected and containment never
    engages. Checked by offset rather than by total size, since padding differs
    between 32- and 64-bit.
    """
    ext = win_job._JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    basic = win_job._JOBOBJECT_BASIC_LIMIT_INFORMATION
    assert ext.BasicLimitInformation.offset == 0
    assert basic.LimitFlags.offset == 16, "LimitFlags follows two 64-bit times"
    assert ext.ProcessMemoryLimit.offset == (
        ctypes.sizeof(basic) + ctypes.sizeof(win_job._IO_COUNTERS)
    )
