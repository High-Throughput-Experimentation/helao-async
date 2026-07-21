"""Standalone regression test: launch.py verifies stale PIDs before skipping.

Locks the fix for ``Pidd.list_active`` trusting ``psutil.pid_exists`` alone.
A stale ``pids_<config>_.pck`` can hold a PID the OS has since reused for an
unrelated process; ``pid_exists`` returns True for the reused PID, so the
launcher would report the server "already running" and refuse to (re)start it.
``_pid_is_server`` must confirm the PID is the actual launched helao server
(launcher script + exact server-key token in the process cmdline).

Run:  conda run -n helao python helao/core/tests/test_launch_pid_verify.py
"""

import logging as _logging
import sys
import tempfile

import psutil

import launch

# launch.LAUNCH_LOGGER is only initialized inside main(); give Pidd a real
# logger so its construction (which logs on a missing pickle) works here.
launch.LAUNCH_LOGGER = _logging.getLogger("test_launch_pid_verify")


class _FakeProc:
    """Minimal psutil.Process stand-in for one scenario."""

    def __init__(self, status, cmdline=None, cmdline_exc=None):
        self._status = status
        self._cmdline = cmdline or []
        self._cmdline_exc = cmdline_exc

    def status(self):
        return self._status

    def cmdline(self):
        if self._cmdline_exc is not None:
            raise self._cmdline_exc
        return self._cmdline


def _pidd():
    """Build a Pidd against an empty tmp pickle (no real servers)."""
    d = tempfile.mkdtemp()
    return launch.Pidd(pidFile="pids_test_.pck", pidPath=d)


def main() -> int:
    failures = []

    def check(cond, msg):
        print(("PASS: " if cond else "FAIL: ") + msg)
        if not cond:
            failures.append(msg)

    pidd = _pidd()
    orig_pid_exists = psutil.pid_exists
    orig_process = psutil.Process

    def run_case(*, exists, proc, key="CLEANSYRINGE", pid=4242):
        """Patch psutil for one case and return _pid_is_server(pid, key)."""
        psutil.pid_exists = lambda *_: exists
        psutil.Process = lambda *_: proc
        try:
            return pidd._pid_is_server(pid, key)
        finally:
            psutil.pid_exists = orig_pid_exists
            psutil.Process = orig_process

    # 1. Dead PID (pickle stale, process gone) -> not running -> will launch.
    check(
        run_case(exists=False, proc=None) is False,
        "dead PID (pid_exists False) is not active",
    )

    # 2. Live PID reused by an UNRELATED process (the reported bug) -> not ours.
    check(
        run_case(
            exists=True,
            proc=_FakeProc("running", cmdline=["/usr/bin/some_other_daemon", "--x"]),
        )
        is False,
        "reused PID with unrelated cmdline is NOT treated as the server",
    )

    # 3. Live PID that IS the launched fast server -> active.
    check(
        run_case(
            exists=True,
            proc=_FakeProc(
                "running",
                cmdline=["python", "fast_launcher.py", "adss3", "CLEANSYRINGE"],
            ),
        )
        is True,
        "live launched fast server (launcher + key in cmdline) is active",
    )

    # 3b. Live bokeh server likewise.
    check(
        run_case(
            exists=True,
            proc=_FakeProc(
                "running",
                cmdline=["python", "bokeh_launcher.py", "adss3", "CLEANSYRINGE"],
            ),
        )
        is True,
        "live launched bokeh server is active",
    )

    # 4. Right launcher but DIFFERENT server key (substring guard) -> not this one.
    check(
        run_case(
            exists=True,
            proc=_FakeProc(
                "running",
                cmdline=["python", "fast_launcher.py", "adss3", "WORKSYRINGE"],
            ),
        )
        is False,
        "another server's launcher process is not this server_key",
    )

    # 5. Zombie (unreaped, pid_exists still True) -> gone.
    check(
        run_case(
            exists=True,
            proc=_FakeProc(
                psutil.STATUS_ZOMBIE,
                cmdline=["python", "fast_launcher.py", "adss3", "CLEANSYRINGE"],
            ),
        )
        is False,
        "zombie process is not active",
    )

    # 6. cmdline() raises AccessDenied (another user's reused PID) -> not ours.
    check(
        run_case(
            exists=True,
            proc=_FakeProc("running", cmdline_exc=psutil.AccessDenied(4242)),
        )
        is False,
        "AccessDenied on cmdline (foreign PID) is not active",
    )

    print("=" * 44)
    if failures:
        print(f"RESULT: FAIL ({len(failures)} check(s) failed)")
        return 1
    print("RESULT: PASS (all checks passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
