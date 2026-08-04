"""Make a launched server die with the launcher that spawned it (Linux).

``launch.py`` spawns every server as a plain ``subprocess.Popen``. If the
launcher is SIGKILLed or crashes, nothing signals those children: they are
reparented to init and keep running -- holding their ports and serving whatever
code they started with. One such group was observed alive ~12 hours after its
launcher died, and a later launch silently deferred to it, producing a
measurement from 12-hour-old code that looked completely healthy.

The kernel can close that hole. ``prctl(PR_SET_PDEATHSIG, sig)`` asks it to
deliver ``sig`` to *this* process when its parent goes away, which needs no
cooperation from the dying parent and therefore survives ``kill -9``.

Three things about this are easy to get wrong, so they are spelled out here:

**Arm from inside the child, never via ``preexec_fn``.** ``preexec_fn`` runs
post-fork in the parent's address space, and ``launch.py`` is multi-threaded (a
console-mux reader thread per child, plus the hotkey and hot-reload threads).
The CPython docs call ``preexec_fn`` unsafe in the presence of threads -- the
child between fork and exec may only call async-signal-safe functions, and any
lock a thread held at fork time is held forever in the child. Calling
:func:`arm_parent_death_signal` at the top of the child's own entry point
avoids fork-time code entirely. Do not "simplify" this back into
``preexec_fn``.

**PDEATHSIG is scoped to the parent *thread*, not the parent process.** Linux
delivers it when the thread that forked the child exits, even if the process
lives on. ``launch.py`` spawns servers from its main thread on a cold start but
from the hotkey thread (CTRL-r) and the hot-reload thread on a restart, so a
child can be notified while its launcher is perfectly healthy. The handler
installed here therefore re-checks that the parent is really gone and re-arms
instead of exiting when it is not.

**A deliberate detach must not kill the group.** CTRL-d disconnects the monitor
and leaves the group running on purpose ("Launch 'python launch.py <config>' to
reconnect"). Parent death alone cannot distinguish that from a crash, so
``launch.py`` writes a detach marker before it exits that way, and the handler
below stands down when it finds one. Without this, adding PDEATHSIG would have
silently deleted the CTRL-d feature and taken a running instrument group down
with the terminal.

Windows is a first-class deployment target and **nothing here changes its
behaviour**: every entry point no-ops off Linux. The Windows equivalent is a
Job Object with ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``, assigned by the parent
at spawn time; that is a different mechanism in a different process and is
explicitly out of scope for this module.
"""

__all__ = [
    "PARENT_PID_ENV",
    "DETACH_MARKER_ENV",
    "arm_parent_death_signal",
    "clear_detach_marker",
    "detach_marker_path",
    "expected_parent_pid",
    "monitor_detached",
    "parent_is_gone",
    "write_detach_marker",
]

import os
import signal
import sys

# launch.py publishes its own pid here so a child can tell "my parent is gone"
# from "my parent's pid was recycled" without racing getppid(). Absent when a
# server is started by hand, which is a supported way to run one.
PARENT_PID_ENV = "HELAO_LAUNCHER_PID"

# Path of the marker file launch.py writes when it exits *deliberately* leaving
# the group up (CTRL-d). Its presence means "parent death is expected, keep
# serving".
DETACH_MARKER_ENV = "HELAO_DETACH_MARKER"

# PR_SET_PDEATHSIG from linux/prctl.h.
_PR_SET_PDEATHSIG = 1


def _supported() -> bool:
    """Whether kernel parent-death signalling is available on this platform."""
    return sys.platform.startswith("linux")


def detach_marker_path(states_root: str, config_prefix: str, extraopt: str = "") -> str:
    """Return the detach-marker path for one launched group.

    Named after the same ``<prefix>_<extraopt>`` pair as the group's pid
    pickle, so two groups launched from one ``STATES`` directory cannot read
    each other's marker.

    Args:
        states_root: The group's ``STATES`` directory.
        config_prefix: Config prefix the group was launched with.
        extraopt: The launcher's ``extraopt`` value, if any.

    Returns:
        str: Absolute path of the marker file (which may not exist).
    """
    return os.path.join(states_root, f"detached_{config_prefix}_{extraopt}.marker")


def write_detach_marker(path: str) -> bool:
    """Record that the launcher is exiting but the group should stay up.

    Must be called *before* the launcher exits: the children only read the
    marker once they are notified of its death, so writing it first is what
    makes the handshake race-free.

    Args:
        path: Marker path from :func:`detach_marker_path`.

    Returns:
        bool: True if the marker is now on disk.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(f"detached by pid {os.getpid()}\n")
        return True
    except Exception:
        return False


def clear_detach_marker(path: str) -> None:
    """Remove a detach marker, ignoring one that is not there.

    Called by the launcher at startup. A marker left by an earlier CTRL-d would
    otherwise keep protecting a *future* group from the very orphan case this
    module exists to fix.

    Args:
        path: Marker path from :func:`detach_marker_path`.
    """
    try:
        os.remove(path)
    except OSError:
        pass


def monitor_detached(env=None) -> bool:
    """Whether the launcher announced a deliberate detach before exiting.

    Args:
        env: Environment mapping. Defaults to ``os.environ``.

    Returns:
        bool: True only when a marker path was published *and* that file
        exists. False when unset, so a server started by hand is never treated
        as detached.
    """
    env = os.environ if env is None else env
    marker = env.get(DETACH_MARKER_ENV)
    if not marker:
        return False
    return os.path.exists(marker)


def expected_parent_pid(env=None) -> int:
    """Return the pid this process should regard as its launcher.

    Args:
        env: Environment mapping. Defaults to ``os.environ``.

    Returns:
        int: The launcher's pid from :data:`PARENT_PID_ENV` when it is set and
        numeric, else the current parent pid.
    """
    env = os.environ if env is None else env
    raw = env.get(PARENT_PID_ENV)
    if raw:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    return os.getppid()


def parent_is_gone(expected_ppid: int, getppid=os.getppid) -> bool:
    """Whether this process has outlived the launcher it was spawned by.

    Args:
        expected_ppid: Pid the launcher is expected to have.
        getppid: Injected for tests.

    Returns:
        bool: True when the current parent is no longer ``expected_ppid``,
        which includes reparenting to init (pid 1) and to a systemd user
        subreaper. False when ``expected_ppid`` is not a real pid to compare
        against, so a hand-started server never decides it is orphaned.
    """
    if expected_ppid is None or expected_ppid <= 1:
        return False
    return getppid() != expected_ppid


def arm_parent_death_signal(
    expected_ppid=None,
    logger=None,
    on_orphaned=None,
    env=None,
) -> bool:
    """Ask the kernel to notify this process when its launcher dies.

    Call once, at the very top of a launcher's entry point, before any server
    is constructed. Off Linux this is a no-op returning False -- see the module
    docstring for why Windows is deliberately unhandled.

    On Linux it installs a handler for :data:`signal.SIGUSR1` and then arms
    ``PR_SET_PDEATHSIG`` with that signal. SIGUSR1 rather than SIGTERM keeps
    the two paths distinguishable: SIGTERM stays exactly what it was, the
    launcher's cooperative teardown signal, so ``Pidd.kill_server``'s
    graceful-then-SIGKILL contract is untouched. When the handler decides the
    parent really is gone it re-raises SIGTERM on itself, so the process takes
    the *same* graceful shutdown path (uvicorn's handler, the FastAPI shutdown
    event, driver disconnect) that a normal teardown would have given it.

    Finally it closes the fork/prctl race: if the launcher died before this
    call landed, the kernel has nothing left to signal, so the orphan state is
    checked directly and the process exits at once.

    Args:
        expected_ppid: Pid to treat as the launcher. Defaults to
            :func:`expected_parent_pid`.
        logger: Optional logger for the warning paths.
        on_orphaned: Called instead of ``sys.exit(0)`` when the parent is found
            already dead. Injected for tests.
        env: Environment mapping. Defaults to ``os.environ``.

    Returns:
        bool: True if the kernel notification was armed.
    """
    if not _supported():
        return False

    if expected_ppid is None:
        expected_ppid = expected_parent_pid(env)

    def _log(level, message):
        # Resolved at call time, not at arm time. This is armed at the very top
        # of a launcher's entry point, before its logger exists, but the handler
        # runs much later -- by which point helao_logging.LOGGER is the server's
        # own file+console logger and is where an operator will look.
        sink = logger
        if sink is None:
            try:
                from helao.helpers import helao_logging

                sink = helao_logging.LOGGER
            except Exception:
                sink = None
        if sink is None:
            print(f"[parent_death] {message}", file=sys.stderr, flush=True)
            return
        getattr(sink, level)(message)

    def _handler(signum, frame):
        # PDEATHSIG follows the parent *thread*, so this can fire while the
        # launcher is alive and well (it spawns restarts from its hotkey and
        # hot-reload threads). Re-arm and carry on in that case.
        if not parent_is_gone(expected_ppid):
            rearmed = (
                "re-armed" if _set_pdeathsig(signal.SIGUSR1) else "could not re-arm"
            )
            _log(
                "info",
                f"Got a parent-death signal while the launcher (pid "
                f"{expected_ppid}) is still alive -- the spawning thread exited, "
                f"not the process. Staying up ({rearmed}).",
            )
            return
        if monitor_detached(env):
            _log(
                "info",
                f"Launcher (pid {expected_ppid}) exited after a deliberate "
                "detach (CTRL-d); staying up. Reconnect with "
                "'python launch.py <config> --reconnect'.",
            )
            return
        _log(
            "warning",
            f"Launcher (pid {expected_ppid}) is gone and did not detach; "
            "shutting down so this server does not orphan and hold its port.",
        )
        # Hand off to the ordinary graceful path rather than exiting here: the
        # SIGTERM handler uvicorn installed runs the FastAPI shutdown event,
        # which is what disconnects drivers.
        signal.raise_signal(signal.SIGTERM)

    try:
        signal.signal(signal.SIGUSR1, _handler)
    except (OSError, ValueError):
        # ValueError: not the main thread. Either way there is no handler, and
        # arming would make the default SIGUSR1 action (terminate) the
        # behaviour -- acceptable for orphan prevention but it would bypass the
        # detach check, so do not arm at all.
        _log("warning", "Could not install the parent-death handler; not arming.")
        return False

    armed = _set_pdeathsig(signal.SIGUSR1)
    if not armed:
        _log(
            "warning",
            "prctl(PR_SET_PDEATHSIG) failed; this server will not notice if its "
            "launcher is killed and may be left holding its port.",
        )

    # The race the kernel cannot cover: the parent may already have died before
    # the call above, in which case no signal is ever coming.
    if parent_is_gone(expected_ppid) and not monitor_detached(env):
        _log(
            "warning",
            f"Launcher (pid {expected_ppid}) was already gone at startup; "
            "exiting instead of orphaning.",
        )
        (on_orphaned or _default_orphan_exit)()

    return armed


def _default_orphan_exit():
    """Leave immediately, before any server binds a port."""
    sys.exit(0)


def _set_pdeathsig(sig) -> bool:
    """Arm ``PR_SET_PDEATHSIG`` with ``sig``.

    Args:
        sig: Signal the kernel should deliver on parent death.

    Returns:
        bool: True on success. False off Linux, when libc cannot be loaded, or
        when prctl reports an error -- never raises, because failing to arm is
        a lost safety net, not a reason to refuse to start a server.
    """
    if not _supported():
        return False
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        return libc.prctl(_PR_SET_PDEATHSIG, int(sig), 0, 0, 0) == 0
    except Exception:
        return False
