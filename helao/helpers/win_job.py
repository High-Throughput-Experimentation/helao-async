"""Make a launched server group die with its launcher (Windows).

The Windows counterpart to :mod:`helao.helpers.parent_death`, and a different
mechanism for the same failure: kill or crash ``launch.py`` and every server it
spawned keeps running, holding its port. On Windows the cost is higher than a
held port -- the Windows-only drivers are Galil (``gclib``) and Gamry
(``comtypes``), and an orphaned Gamry server still owns ``GamryCOM`` and the
potentiostat, so the next launch cannot acquire the instrument at all.

``PR_SET_PDEATHSIG`` has no Windows equivalent. A **Job Object** with
``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` is the real analogue: when the last
handle to the job closes, the kernel terminates every process still in it. The
launcher assigns *itself* to the job, and that is the whole trick --
:func:`assign_launcher` needs no cooperation from the children, because a
process created by a job member joins that member's job automatically. It also
covers the case a per-child scheme cannot: the launcher dying between spawning a
child and telling it anything.

Four things about this are easy to get wrong, so they are spelled out:

**The handle must be held for the launcher's whole lifetime.** Closing it is
precisely what triggers the kill, so a handle that goes out of scope and is
garbage-collected would terminate the entire running server group on the spot.
:func:`assign_launcher` returns the handle for the caller to keep alive, and
``launch.py`` stores it on a module global for that reason alone.

**A deliberate detach has to clear the limit first.** CTRL-d leaves the group
running on purpose, but the launcher exiting closes its handle, which under
``KILL_ON_JOB_CLOSE`` kills everyone. A process cannot be removed from a job, so
the flag itself is cleared instead -- see :func:`release_for_detach`. Without
that call, adding this module would silently delete the CTRL-d feature on
Windows exactly as it would have on Linux.

**Assignment can legitimately fail.** If the launcher is already inside a job
that forbids breakaway (some service managers, CI agents, and container
supervisors do this), ``AssignProcessToJobObject`` fails with access-denied.
That is not a reason to refuse to launch an instrument: everything here logs and
returns, leaving the previous behaviour intact.

**No ``pywin32``.** ``helao_dev_win-64.yml`` ships ``comtypes`` and ``pyserial``
and not ``pywin32``, so this uses raw :mod:`ctypes` against ``kernel32`` rather
than ``win32job``. That keeps it a pure-stdlib addition needing no station
environment rebuild.

Nothing here runs off Windows: every entry point checks the platform and returns
a no-op result, so the Linux path is provably unchanged.
"""

__all__ = [
    "CREATE_NEW_PROCESS_GROUP",
    "NEW_PROCESS_GROUP_ENV",
    "assign_launcher",
    "ctrl_break",
    "release_for_detach",
    "spawn_creationflags",
    "supported",
]

import ctypes
import os
import sys

# From winnt.h / jobapi2.h. Spelled out rather than imported because there is no
# stdlib module that exposes them.
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

#: ``subprocess`` exposes this, but only on Windows, so it is re-published here
#: as a plain int that is safe to reference on any platform.
CREATE_NEW_PROCESS_GROUP = 0x00000200

#: Set to "0" to spawn children in the launcher's own console process group,
#: giving up the CTRL_BREAK graceful step. An escape hatch for a station where
#: the new-process-group change turns out to interact badly with a vendor SDK --
#: the job object keeps working either way, so orphan protection is not lost.
NEW_PROCESS_GROUP_ENV = "HELAO_WIN_NEW_PROCESS_GROUP"


def supported() -> bool:
    """Whether Job Object containment is available on this platform."""
    return os.name == "nt" and sys.platform == "win32"


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _kernel32():
    """Return ``kernel32`` with errno tracking, or None off Windows."""
    if not supported():
        return None
    return ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]


def _set_limit_flags(handle, flags, logger=None) -> bool:
    """Write ``flags`` as the job's extended ``LimitFlags``.

    Args:
        handle: Job handle from :func:`assign_launcher`.
        flags: The complete ``LimitFlags`` value to set, not a delta.
        logger: Optional logger for the failure path.

    Returns:
        bool: True when the kernel accepted the new limits.
    """
    k32 = _kernel32()
    if k32 is None or not handle:
        return False
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = flags
    ok = k32.SetInformationJobObject(
        ctypes.c_void_p(handle),
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok and logger is not None:
        logger.warning(
            f"SetInformationJobObject failed (error "
            f"{ctypes.get_last_error()}); job limits unchanged."  # type: ignore[attr-defined]
        )
    return bool(ok)


def assign_launcher(logger=None):
    """Put this process in a kill-on-close job so its children cannot outlive it.

    Call once from ``launch.py`` before any server is spawned. Children created
    afterwards join the job automatically, which is why nothing has to be done
    per child.

    Args:
        logger: Optional logger for the diagnostic paths.

    Returns:
        The job handle, which the caller **must keep referenced for the life of
        the process** -- closing it is what terminates the group. ``None`` off
        Windows, or when the job could not be created or joined, in which case
        the group simply behaves as it did before.
    """
    k32 = _kernel32()
    if k32 is None:
        return None

    k32.CreateJobObjectW.restype = ctypes.c_void_p
    handle = k32.CreateJobObjectW(None, None)
    if not handle:
        if logger is not None:
            logger.warning(
                f"CreateJobObjectW failed (error {ctypes.get_last_error()}); "  # type: ignore[attr-defined]
                f"servers will not be terminated automatically if this launcher "
                f"is killed."
            )
        return None

    if not _set_limit_flags(handle, _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, logger):
        k32.CloseHandle(ctypes.c_void_p(handle))
        return None

    k32.GetCurrentProcess.restype = ctypes.c_void_p
    if not k32.AssignProcessToJobObject(
        ctypes.c_void_p(handle), ctypes.c_void_p(k32.GetCurrentProcess())
    ):
        # Access-denied here usually means an outer job forbids breakaway -- a
        # service manager or CI agent already containing us. Never a reason to
        # refuse to launch.
        if logger is not None:
            logger.warning(
                f"AssignProcessToJobObject failed (error "
                f"{ctypes.get_last_error()}); this launcher is probably already "  # type: ignore[attr-defined]
                f"inside a job that forbids breakaway. Servers will not be "
                f"terminated automatically if it is killed."
            )
        k32.CloseHandle(ctypes.c_void_p(handle))
        return None

    if logger is not None:
        logger.info(
            "Servers will be terminated with this launcher (Windows job object)."
        )
    return handle


def release_for_detach(handle, logger=None) -> bool:
    """Clear kill-on-close so the group survives a deliberate CTRL-d detach.

    A process cannot be removed from a job, so the limit is dropped instead:
    afterwards the handle closing is an ordinary handle close and the members
    keep running. Must be called *before* the launcher exits.

    Args:
        handle: Job handle from :func:`assign_launcher`. ``None`` is a no-op,
            which is the Linux path and the already-failed-to-assign path.
        logger: Optional logger.

    Returns:
        bool: True when the group will now survive this process exiting. True
        for a ``None`` handle as well -- there is no job holding the group, so
        detaching is already safe.
    """
    if not handle:
        return True
    released = _set_limit_flags(handle, 0, logger)
    if logger is not None:
        if released:
            logger.info("Cleared the job's kill-on-close limit for the detach.")
        else:
            logger.error(
                "Could not clear the job's kill-on-close limit; the servers "
                "WILL be terminated when this launcher exits."
            )
    return released


def spawn_creationflags(env=None) -> int:
    """Return the ``creationflags`` a launched server should be spawned with.

    ``CREATE_NEW_PROCESS_GROUP`` is what makes a targeted ``CTRL_BREAK_EVENT``
    possible: without it every child shares the launcher's console group, and
    ``GenerateConsoleCtrlEvent`` can then only address group 0 -- which would
    signal the launcher along with them.

    The trade is deliberate and worth stating: a child in its own group no
    longer receives console Ctrl+C. That is acceptable because ``launch.py``
    catches ``KeyboardInterrupt`` itself and runs the full teardown, so Ctrl+C
    still stops the group -- it just travels through the launcher rather than
    straight to every child.

    Args:
        env: Environment mapping. Defaults to ``os.environ``.

    Returns:
        int: Flags to pass to ``subprocess.Popen``; ``0`` off Windows or when
        :data:`NEW_PROCESS_GROUP_ENV` is set to ``"0"``.
    """
    if not supported():
        return 0
    env = os.environ if env is None else env
    if env.get(NEW_PROCESS_GROUP_ENV, "1") == "0":
        return 0
    return CREATE_NEW_PROCESS_GROUP


def ctrl_break(pid: int, logger=None) -> bool:
    """Ask one server to shut down the way Ctrl+Break would.

    Windows has no deliverable SIGTERM: ``psutil.Process.terminate()`` is
    ``TerminateProcess``, which stops a process dead without running a single
    shutdown handler. ``CTRL_BREAK_EVENT`` is the nearest thing to a cooperative
    stop, and uvicorn does handle it, so this gives the Windows path a real
    graceful window instead of one that only reads like one.

    Only meaningful for a child spawned with :func:`spawn_creationflags`, since
    the event is addressed to a process *group* id.

    Args:
        pid: The server's process id, which is also its group id.
        logger: Optional logger.

    Returns:
        bool: True if the event was posted. False off Windows or on failure --
        callers must treat this as "no graceful step happened" and fall through
        to their force-kill, never as a reason to leave a server running.
    """
    k32 = _kernel32()
    if k32 is None:
        return False
    _CTRL_BREAK_EVENT = 1
    if not k32.GenerateConsoleCtrlEvent(_CTRL_BREAK_EVENT, pid):
        if logger is not None:
            logger.info(
                f"CTRL_BREAK to pid {pid} failed (error "
                f"{ctypes.get_last_error()}); escalating instead."  # type: ignore[attr-defined]
            )
        return False
    return True
