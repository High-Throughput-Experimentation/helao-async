"""
This module provides functionality for managing and launching HELAO servers.
Classes:
    Pidd: Manages process IDs (PIDs) for HELAO servers, including loading, storing, and terminating processes.
Functions:
    validateConfig(PIDD, confDict, helao_repo_root): Validates the configuration dictionary for HELAO servers.
    wait_key(): Waits for a key press on the console and returns it.
    launcher(confArg, confDict, helao_repo_root, extraopt=""): Launches HELAO servers based on the provided configuration.
    main(): Main entry point for the HELAO launcher script.
Usage:
    This script is intended to be run as a standalone launcher for HELAO servers. It validates the configuration,
    launches the servers in a specified order, and provides options for restarting or terminating servers via
    keyboard input.
Example:
    To run the launcher, use the following command:
    python launch.py <config_file> [extra_option] [--restore] [--no-hot-reload]
    Where <config_file> is the path to the configuration file and [extra_option] is an optional argument for additional
    launch options. The optional --restore flag makes launched orchestrators
    import their previously exported queues (STATES/queues.pck) on startup. The
    hot-reload watcher (which watches the parent and nested deployment git repos
    and restarts idle servers whose loaded code changes on a pull) runs by
    default; pass --no-hot-reload (or set `hot_reload.enabled: false` in the
    config) to disable it. Flags may appear anywhere on the command line.
Note:
    This script requires the 'click', 'termcolor', 'pyfiglet', 'colorama', 'psutil', and 'requests' libraries.
"""

__all__ = []

import json

# ``logging`` below is helao's logging helper, NOT the stdlib module, so the
# stdlib gets an explicit alias for the handler/filter classes ConsoleMux needs.
import logging as pylogging
import os
import pickle
import re
import subprocess
import sys
import threading
import time
import zipfile
from collections import deque
from contextlib import contextmanager
from glob import glob
from logging import Logger

import click
import colorama
import psutil
import requests
from pyfiglet import figlet_format
from termcolor import cprint

from helao.core.servers.reflex.discovery import reserved_addresses
from helao.core.version import get_hlo_version
from helao.helpers import helao_logging as logging
from helao.helpers.config_loader import read_config
from helao.helpers.helao_dirs import helao_dirs
from helao.helpers.time_utils import get_ntp_time

# Upper bound (seconds) for a blocking POST /shutdown. The server's shutdown
# hook runs its driver shutdown (e.g. gamry disconnect + kill GamryCOM) before
# responding; this bounds the wait so a hung driver shutdown can't stall
# teardown. On timeout the server-side handler keeps running and kill_server
# reaps the process afterward.
SHUTDOWN_POST_TIMEOUT = 30

# API server launch priority (matches folders in root helao-dev/).
# The "operator" group is launched the same way as visualizers (a bokeh
# subprocess via bokeh_launcher.py, resolved from servers/operator/), but is
# ordered immediately after the orchestrator group so a standalone operator
# can connect to a live orchestrator as soon as it starts.
#
# Module-level so a cold start (:func:`launcher`) and the CTRL-r "R" full
# relaunch drive the same order from one definition.
LAUNCH_ORDER = ["action", "orchestrator", "operator", "visualizer"]

# Groups whose servers accept a graceful POST /shutdown before being signalled,
# in the order the request is sent. Orchestrators go first so they detach their
# subscribers (and export any non-empty queues) while the action servers they
# talk to are still up.
SHUTDOWN_POST_ORDER = ["orchestrator", "action"]

# ---------------------------------------------------------------------------
# Console multiplexer: child output pump + CTRL-r menu isolation
# ---------------------------------------------------------------------------
# Servers are spawned on pipes rather than inheriting the launcher's terminal,
# so the CTRL-r menu can be shown without being scrolled away -- roughly 96% of
# the terminal's lines come from the servers, not the launcher, so gating the
# launcher's own logging alone would not help.
#
# INVARIANT: reader threads drain their pipe UNCONDITIONALLY, whatever the menu
# is doing. A child writing to a full pipe blocks inside write(); for a helao
# server that means its asyncio loop stops serving HTTP, status websockets and
# driver polling *while the process stays alive and its PID stays valid*, so
# neither Pidd._pid_is_server nor server_is_idle would notice. Only the display
# is gated -- drained lines go to an in-memory buffer and are flushed on resume.

# Launcher-side buffer holding output produced while the display is suppressed.
CONSOLE_BUFFER_MAX_BYTES = 1024 * 1024

# Target capacity for each child pipe. 16x the Linux default, so a stalled
# reader has ~8000 lines of slack before the child could block at all.
CHILD_PIPE_SIZE = 1024 * 1024
F_SETPIPE_SZ = 1031
F_GETPIPE_SZ = 1032

# Pipe occupancy that force-ends menu isolation. Linux pipes are grown to
# CHILD_PIPE_SIZE so half is a wide margin; on Windows the size is fixed by
# CreatePipe at spawn time and is not tunable from Python, so the available
# margin is smaller and the trigger is correspondingly tighter.
PIPE_HIGH_WATER = 0.25 if os.name == "nt" else 0.5

# Launcher-buffer occupancy that force-ends isolation, before lines get dropped.
CONSOLE_BUFFER_HIGH_WATER = 0.75

# Seconds between watchdog pressure checks while isolation is active.
CONSOLE_WATCHDOG_INTERVAL = 0.25

# DEC private mode 1049: switch to/from the alternate screen buffer. Used only
# when stdout is a tty -- colorama does not translate this sequence (its regex
# accepts only digits and semicolons before the final letter, and "?1049h" has a
# "?"), so on a redirected stream it would leak through as literal garbage.
ALT_SCREEN_ON = "\x1b[?1049h"
ALT_SCREEN_OFF = "\x1b[?1049l"


def _mux_log(level, message, **kwargs):
    """Log from :class:`ConsoleMux`, tolerating an unconfigured LAUNCH_LOGGER.

    LAUNCH_LOGGER is only populated by :func:`main`, so a caller that drives
    :func:`launcher` directly may leave it ``None``; the mux must not be what
    raises in that case. Resolved at call time because ``main()`` rebinds the
    global.
    """
    if LAUNCH_LOGGER is None:
        return
    getattr(LAUNCH_LOGGER, level)(message, **kwargs)


class ConsoleMux:
    """Pumps child-server output to the terminal, suppressible for the menu.

    Attributes:
        stream: Destination for forwarded output (the launcher's real stdout).
        active: True once :meth:`activate` has opted this process in to piping
            children. Off by default -- see :meth:`activate`.
        enabled: True once at least one child has been registered, i.e. children
            are on pipes and their output flows through here.
    """

    def __init__(self, stream=None):
        """Initialise an idle, inactive mux with the display enabled.

        Args:
            stream: Output stream to forward to. Defaults to ``sys.stdout``.
        """
        self.stream = stream if stream is not None else sys.stdout
        self.active = False
        self.enabled = False
        self._display = threading.Event()
        self._display.set()
        self._lock = threading.Lock()
        self._buffer = deque()
        self._buffered_bytes = 0
        self._dropped_lines = 0
        self._pipes = {}  # server_key -> binary pipe object being drained
        self._suppress_reason = None

    # -- child registration -------------------------------------------------

    def activate(self):
        """Opt this process in to piping child output through the mux.

        Off by default, and only ``main()`` turns it on, because piping is only
        safe for a launcher that outlives its children. A process that spawns
        servers and then exits closes the pipe read end on the way out, and the
        server is killed on its next console write -- verified directly: the
        child is reaped without finishing its writes. Any future fire-and-forget
        caller of :func:`launcher` must therefore leave this off and let its
        children inherit the terminal, which is what an inactive mux gives them.
        """
        self.active = True

    def spawn_kwargs(self) -> dict:
        """``Popen`` kwargs routing a child's output into the mux.

        Empty while inactive, so the child inherits this process's stdout and
        stderr exactly as it did before the mux existed.
        """
        if not self.active:
            return {}
        return {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}

    def child_env(self):
        """Environment for a spawned child, or ``None`` to inherit unchanged.

        ``HELAO_FORCE_COLOR`` tells the child to emit ANSI even though its own
        stdout is a pipe, because this launcher forwards it to a real terminal.
        Only set when that terminal actually exists, so a redirected launcher
        still produces clean, escape-free output. ``PYTHONUNBUFFERED`` keeps the
        child line-buffered; a non-tty stdout would otherwise block-buffer and
        arrive in delayed multi-kilobyte chunks.
        """
        if not self.active:
            return None
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        try:
            if sys.stdout.isatty():
                env["HELAO_FORCE_COLOR"] = "1"
        except Exception:
            pass
        return env

    def register(self, server_key, proc):
        """Start draining ``proc``'s output under ``server_key``.

        Grows the pipe to :data:`CHILD_PIPE_SIZE` where supported, then starts a
        daemon reader thread. Registration failure is logged and ignored: losing
        the terminal copy of a server's log is survivable (the per-server
        rotating file handler is unaffected), whereas raising here would abort a
        launch.
        """
        if proc.stdout is None:
            return
        try:
            self._grow_pipe(proc.stdout)
            self._pipes[server_key] = proc.stdout
            self.enabled = True
            threading.Thread(
                target=self._reader,
                args=(server_key, proc.stdout),
                name=f"console_mux__{server_key}",
                daemon=True,
            ).start()
        except Exception:
            _mux_log(
                "error",
                f"Could not attach console mux to {server_key}; its output will "
                f"not reach the terminal (LOGS/{server_key}.log is unaffected).",
                exc_info=True,
            )

    def unregister(self, server_key):
        """Forget ``server_key``'s pipe. The reader thread exits on EOF."""
        self._pipes.pop(server_key, None)

    def _grow_pipe(self, pipe):
        """Enlarge ``pipe``'s kernel buffer, where the platform allows it."""
        if os.name == "nt":
            # CreatePipe fixes the size at creation and subprocess does not
            # expose it, so there is nothing to grow.
            return
        try:
            import fcntl

            fcntl.fcntl(pipe.fileno(), F_SETPIPE_SZ, CHILD_PIPE_SIZE)
        except Exception:
            # Non-fatal: an ungrown pipe is the 64 KiB default, which the
            # always-draining reader keeps near empty anyway.
            pass

    # -- draining -----------------------------------------------------------

    def _reader(self, server_key, pipe):
        """Drain ``pipe`` line by line until EOF. Never gates on the display."""
        try:
            for raw in iter(pipe.readline, b""):
                self._emit(raw.decode("utf8", "replace"))
        except Exception:
            pass
        finally:
            self.unregister(server_key)
            # Close our read end at EOF so repeated restarts do not leak fds.
            try:
                pipe.close()
            except Exception:
                pass

    def _emit(self, text):
        """Forward ``text`` now, or buffer it while the display is suppressed."""
        if self._display.is_set():
            try:
                self.stream.write(text)
                self.stream.flush()
            except Exception:
                pass
            return
        with self._lock:
            self._buffer.append(text)
            self._buffered_bytes += len(text)
            while self._buffered_bytes > CONSOLE_BUFFER_MAX_BYTES and self._buffer:
                self._buffered_bytes -= len(self._buffer.popleft())
                self._dropped_lines += 1

    # -- pressure -----------------------------------------------------------

    def pipe_pressure(self):
        """Return ``(server_key, occupied_fraction)`` for the fullest pipe.

        The fraction is how close that child is to blocking on a write. Returns
        ``(None, 0.0)`` when unmeasurable, which includes Windows -- there is no
        cheap equivalent of ``FIONREAD`` for an anonymous pipe, so the buffer
        pressure check below carries the load there.
        """
        if os.name == "nt":
            return None, 0.0
        worst_key, worst_frac = None, 0.0
        try:
            import fcntl
            import struct
            import termios
        except Exception:
            return None, 0.0
        for server_key, pipe in list(self._pipes.items()):
            try:
                fd = pipe.fileno()
                pending = struct.unpack(
                    "i", fcntl.ioctl(fd, termios.FIONREAD, b"\0" * 4)
                )[0]
                capacity = fcntl.fcntl(fd, F_GETPIPE_SZ)
                frac = pending / capacity if capacity else 0.0
            except Exception:
                continue
            if frac > worst_frac:
                worst_key, worst_frac = server_key, frac
        return worst_key, worst_frac

    def buffer_pressure(self) -> float:
        """Occupied fraction of the launcher-side buffer."""
        with self._lock:
            return self._buffered_bytes / CONSOLE_BUFFER_MAX_BYTES

    # -- isolation ----------------------------------------------------------

    def _flush(self):
        """Write out everything buffered, noting any dropped lines."""
        with self._lock:
            pending, dropped = list(self._buffer), self._dropped_lines
            self._buffer.clear()
            self._buffered_bytes = 0
            self._dropped_lines = 0
        try:
            if dropped:
                self.stream.write(
                    f"... {dropped} line(s) dropped: launcher console buffer "
                    f"({CONSOLE_BUFFER_MAX_BYTES // 1024} KiB) overflowed while "
                    f"the menu was open; see the per-server logs under LOGS/.\n"
                )
            for chunk in pending:
                self.stream.write(chunk)
            self.stream.flush()
        except Exception:
            pass

    def resume(self, reason=None):
        """End suppression: leave the alternate screen and flush the buffer.

        Idempotent and safe to call from the watchdog thread while the menu's
        blocking ``input()`` is still pending -- that intentionally restores the
        output flow around the live prompt rather than cancelling the prompt.

        Args:
            reason: When set, logged to explain an automatic resume so it does
                not look like a glitch.
        """
        with self._lock:
            if self._display.is_set():
                return
            alt = self._suppress_reason == "alt"
            self._suppress_reason = None
        if alt:
            try:
                self.stream.write(ALT_SCREEN_OFF)
                self.stream.flush()
            except Exception:
                pass
        self._display.set()
        self._flush()
        if reason:
            _mux_log("warning", f"Menu isolation ended early: {reason}")

    @contextmanager
    def isolated(self):
        """Suppress child output for the duration of the block.

        Enters the alternate screen buffer when stdout is a tty so the menu never
        touches the scrollback. A watchdog thread ends isolation early if any
        child pipe or the launcher buffer crosses its high-water mark, so a burst
        of logging can never push a child toward a blocking write.
        """
        if not self.enabled:
            # Children were never piped (nothing launched yet); isolating would
            # suppress nothing and the alternate screen would just hide the menu
            # from a scrollback the caller can still read.
            yield
            return
        is_tty = False
        try:
            is_tty = self.stream.isatty()
        except Exception:
            pass
        with self._lock:
            self._display.clear()
            self._suppress_reason = "alt" if is_tty else "plain"
        if is_tty:
            try:
                self.stream.write(ALT_SCREEN_ON)
                self.stream.flush()
            except Exception:
                pass
        stop = threading.Event()
        threading.Thread(
            target=self._watchdog,
            args=(stop,),
            name="console_mux__watchdog",
            daemon=True,
        ).start()
        try:
            yield
        finally:
            stop.set()
            self.resume()

    def _watchdog(self, stop):
        """End isolation if child pipes or the buffer approach saturation."""
        while not stop.wait(CONSOLE_WATCHDOG_INTERVAL):
            if self._display.is_set():
                return
            key, frac = self.pipe_pressure()
            if frac >= PIPE_HIGH_WATER:
                self.resume(
                    f"{key} pipe at {frac:.0%} of capacity (limit "
                    f"{PIPE_HIGH_WATER:.0%}); resuming output so it cannot block"
                )
                return
            buffered = self.buffer_pressure()
            if buffered >= CONSOLE_BUFFER_HIGH_WATER:
                self.resume(
                    f"launcher console buffer at {buffered:.0%} of "
                    f"{CONSOLE_BUFFER_MAX_BYTES // 1024} KiB (limit "
                    f"{CONSOLE_BUFFER_HIGH_WATER:.0%}); resuming output so no "
                    f"lines are dropped"
                )
                return

    # -- launcher's own logging --------------------------------------------

    def install_log_gate(self, logger):
        """Suppress ``logger``'s console handlers while isolation is active.

        The launcher's own records are only ~4% of the terminal's lines, but they
        include the per-keypress hotkey hint, which would otherwise print over
        the menu.
        """
        mux = self

        class _Gate(pylogging.Filter):
            def filter(self, record):
                return mux._display.is_set()

        for handler in logger.handlers:
            if isinstance(handler, pylogging.StreamHandler) and not isinstance(
                handler, pylogging.FileHandler
            ):
                handler.addFilter(_Gate())


# Single mux shared by launcher(), launch_server_groups() and restart_server(),
# so every spawned child is drained by the same pump.
CONSOLE = ConsoleMux()

LAUNCH_LOGGER: Logger = None


class Pidd:
    """
    A class to manage process IDs (PIDs) for various servers.
    Attributes:
        PROC_NAMES (list): List of process names to check.
        pidFilePath (str): Path to the PID file.
        RETRIES (int): Number of retries for terminating a process.
        reqKeys (tuple): Required keys for the PID dictionary.
        codeKeys (tuple): Code keys for the PID dictionary.
        d (dict): Dictionary to store PID information.
    Methods:
        __init__(pidFile, pidPath, retries=3):
            Initializes the Pidd class with the given PID file, path, and retries.
        load_global():
            Loads the global PID dictionary from the PID file.
        write_global():
            Writes the global PID dictionary to the PID file.
        list_pids():
            Lists all stored PIDs with their host, port, and PID.
        store_pid(k, host, port, pid):
            Stores a PID with the given key, host, port, and PID.
        list_active():
            Lists all active PIDs that are currently running.
        kill_server(k):
            Terminates the server with the given key.
        close():
            Closes all active servers and removes the PID file.
    """

    def __init__(self, pidFile, pidPath, retries=3):
        """
        Initializes the class with the given parameters.

        Args:
            pidFile (str): The name of the PID file.
            pidPath (str): The path to the PID file.
            retries (int, optional): The number of retries. Defaults to 3.

        Attributes:
            PROC_NAMES (list): List of process names to check.
            pidFilePath (str): Full path to the PID file.
            RETRIES (int): Number of retries.
            reqKeys (tuple): Required keys for the configuration.
            codeKeys (tuple): Code keys for the configuration.
            d (dict): Dictionary to store configuration data.

        Raises:
            IOError: If the PID file does not exist.
            Exception: If there is an error loading the PID file.
        """
        self.PROC_NAMES = ["python.exe", "python"]
        self.pidFilePath = os.path.join(pidPath, pidFile)
        self.RETRIES = retries
        # Seconds to wait for a cooperative SIGTERM shutdown before escalating to
        # SIGKILL. Must exceed the servers' own graceful-shutdown floor: uvicorn's
        # timeout_graceful_shutdown (5s) plus Base.shutdown()'s detach_subscribers
        # sleep (1s). The old 3x0.5s=1.5s budget was shorter than that floor and
        # always timed out on Linux.
        self.GRACEFUL_WAIT = 7.0
        self.FORCE_WAIT = 3.0
        # server_key -> subprocess.Popen handle, populated by launcher(). Kept so
        # terminated children can be reaped; an unreaped child becomes a zombie
        # whose PID psutil.pid_exists() still reports as alive.
        self.procs = {}
        self.reqKeys = ("host", "port", "group")
        self.codeKeys = ("fast", "bokeh", "reflex")
        self.d = {}
        try:
            self.load_global()
        except IOError:
            LAUNCH_LOGGER.info(
                f"'{self.pidFilePath}' does not exist, writing empty global dict."
            )
            self.write_global()
        except Exception:
            LAUNCH_LOGGER.info(
                f"Error loading '{self.pidFilePath}', writing empty global dict."
            )
            self.write_global()

    def load_global(self):
        """
        Loads global data from a pickle file specified by `self.pidFilePath`.

        This method opens the file in binary read mode, loads the data using the
        pickle module, and assigns it to `self.d`.

        Raises:
            FileNotFoundError: If the file specified by `self.pidFilePath` does not exist.
            pickle.UnpicklingError: If there is an error unpickling the file.
        """
        with open(self.pidFilePath, "rb") as f:
            self.d = pickle.load(f)
            # print_message(LAUNCH_LOGGER, "launcher", f"Succesfully loaded '{self.pidFilePath}'.")

    def write_global(self):
        """
        Writes the global state to a file specified by `self.pidFilePath`.

        This method serializes the dictionary `self.d` using the `pickle` module
        and writes it to a file in binary mode.

        Raises:
            Exception: If there is an error during the file writing process.
        """
        with open(self.pidFilePath, "wb") as f:
            pickle.dump(self.d, f)

    def list_pids(self):
        """
        Lists the process IDs (PIDs) along with their corresponding host and port information.

        Returns:
            list of tuple: A list of tuples where each tuple contains the key, host, port, and PID.
        """
        self.load_global()
        return [(k, d["host"], d["port"], d["pid"]) for k, d in self.d.items()]

    def store_pid(self, k, host, port, pid):
        """
        Stores process information in the dictionary and writes it to a global storage.

        Args:
            k (str): The key to store the process information under.
            host (str): The hostname of the process.
            port (int): The port number the process is using.
            pid (int): The process ID.

        Returns:
            None
        """
        self.d[k] = {"host": host, "port": port, "pid": pid}
        self.write_global()

    def list_active(self):
        """
        List active processes.

        This method retrieves a list of active processes by checking if the process IDs (PIDs)
        from the list returned by `list_pids` are currently running. It filters out the processes
        that are not running and returns a list of tuples representing the active processes.

        Returns:
            list: A list of tuples representing the active processes. Each tuple contains
                  information about a process, such as its PID, port, and host.
        """
        helaoPids = self.list_pids()
        # Only count a PID as active if it is a LIVE process that is actually
        # the launched helao server for that key. A stale pids_*.pck can hold a
        # PID that the OS has since reused for an unrelated process;
        # psutil.pid_exists() alone would then report it "running" and the
        # launcher would refuse to (re)start a server that is in fact NOT
        # running. _pid_is_server verifies process identity via cmdline.
        return [tup for tup in helaoPids if self._pid_is_server(tup[3], tup[0])]

    def _pid_is_server(self, pid, server_key):
        """Return True only if ``pid`` is a live, non-zombie process that is the
        launched helao server for ``server_key``.

        Guards against a stale ``pids_*.pck`` whose recorded PID has since been
        reused by an unrelated process: ``psutil.pid_exists`` returns True for
        the reused PID, which would make the launcher skip a server that is not
        actually running. Servers are spawned as
        ``python {fast,bokeh}_launcher.py <config> <server_key>`` (see
        :func:`launcher`), so requiring both the launcher script and the exact
        ``server_key`` argv token in the process cmdline confirms identity
        cross-platform, without needing socket/port permissions.

        Args:
            pid (int): PID recorded in the pids pickle.
            server_key (str): Server key the PID is expected to belong to.

        Returns:
            bool: True if the PID is the live launched server, else False
            (dead, a zombie, another user's reused PID, or an unrelated
            process).
        """
        if not psutil.pid_exists(pid):
            return False
        try:
            proc = psutil.Process(pid)
            if proc.status() == psutil.STATUS_ZOMBIE:
                return False
            cmdline = proc.cmdline()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # gone, a zombie, or owned by another user (a reused PID) -> not ours
            return False
        launched_by = any(
            launcher in arg
            for arg in cmdline
            for launcher in ("fast_launcher.py", "bokeh_launcher.py")
        )
        # server_key is passed as its own argv element, so list membership is an
        # exact-token match (won't false-match a key that is a substring of a
        # longer server key or of a path).
        return launched_by and server_key in cmdline

    def _reap_child(self, k):
        """Reap the OS child for server ``k`` so a terminated process does not
        linger as an unwaited zombie. No-op if this launcher never spawned it,
        e.g. a ``Pidd`` that adopted pids from an existing pickle rather than
        launching them."""
        p = self.procs.get(k)
        if p is not None:
            try:
                p.wait(timeout=0)
            except Exception:
                pass

    def _wait_gone(self, proc, timeout, k):
        """Wait up to ``timeout`` seconds for ``proc`` to exit, reaping it so no
        zombie remains. Return True if the process is gone.

        ``psutil.Process.wait()`` reaps the process when it is a child of this
        process (which every launcher-spawned server is), preventing the zombie
        that would otherwise keep ``psutil.pid_exists()`` returning True forever.
        """
        try:
            proc.wait(timeout=timeout)
        except psutil.TimeoutExpired:
            return False
        except psutil.NoSuchProcess:
            pass
        # belt-and-suspenders: also reap via the Popen handle if we own it
        self._reap_child(k)
        if not psutil.pid_exists(proc.pid):
            return True
        # a lingering PID that is a zombie counts as gone (already dead)
        try:
            return proc.status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return True

    def kill_server(self, k):
        """
        Terminates a server process identified by the key `k`.

        This method attempts to terminate a server process by its PID. It first checks if the server
        exists in the global dictionary and if it is currently running. If the server is not running,
        it removes the server from the global dictionary. If the server is running, it sends SIGTERM
        and waits up to ``GRACEFUL_WAIT`` seconds for a cooperative shutdown, escalating to SIGKILL
        (waiting a further ``FORCE_WAIT`` seconds) if needed. Every terminating branch reaps the child
        so it does not linger as a zombie.

        Args:
            k (str): The key identifying the server to be terminated.

        Returns:
            bool: True if the server was successfully terminated or not found, False if the process
                survived even SIGKILL (in which case the pid entry is retained for recovery).
        """
        self.load_global()  # reload in case any servers were appended
        if k not in self.d:
            LAUNCH_LOGGER.info(f"Server '{k}' not found in pid dict.")
            return True

        active = self.list_active()
        if k not in [key for key, _, _, _ in active]:
            LAUNCH_LOGGER.info(
                f"Server '{k}' is not running, removing from global dict."
            )
            self._reap_child(k)  # in case the child exited but was never waited on
            del self.d[k]
            self.write_global()
            return True

        pid = self.d[k]["pid"]
        try:
            p = psutil.Process(pid)
        except psutil.NoSuchProcess:
            LAUNCH_LOGGER.info(f"Server '{k}' (pid {pid}) already gone.")
            self._reap_child(k)
            del self.d[k]
            self.write_global()
            return True

        # Send SIGTERM (an alias for kill() on Windows) and wait past the servers'
        # graceful-shutdown floor before escalating to SIGKILL. Every branch reaps
        # the child so it never lingers as a zombie.
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            self._reap_child(k)
            del self.d[k]
            self.write_global()
            return True
        except Exception:
            LAUNCH_LOGGER.error(f"Error signaling server '{k}'", exc_info=True)
            return False

        if self._wait_gone(p, self.GRACEFUL_WAIT, k):
            LAUNCH_LOGGER.info(f"Successfully terminated server '{k}' (graceful).")
            del self.d[k]
            self.write_global()
            return True

        LAUNCH_LOGGER.warning(
            f"Server '{k}' still alive after {self.GRACEFUL_WAIT}s SIGTERM; "
            f"escalating to SIGKILL."
        )
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass
        except Exception:
            LAUNCH_LOGGER.error(f"Error killing server '{k}'", exc_info=True)

        if self._wait_gone(p, self.FORCE_WAIT, k):
            LAUNCH_LOGGER.info(f"Successfully killed server '{k}' (SIGKILL).")
            del self.d[k]
            self.write_global()
            return True

        LAUNCH_LOGGER.error(f"Failed to terminate server '{k}' even after SIGKILL.")
        return False

    def close(self):
        """
        Terminates all active servers in a specific order and removes the PID file.
        This method performs the following steps:
        1. Lists all active servers.
        2. Prints the list of active servers.
        3. Iterates through a predefined kill order (`KILL_ORDER`) and terminates servers in each group.
        4. Waits for a short duration before killing each server.
        5. Kills any remaining active servers.
        6. Prints a message if any servers failed to terminate.
        7. Removes the PID file if all servers are successfully terminated.
        The method uses the following helper methods:
        - `list_active()`: Returns a list of active servers.
        - `print_message()`: Prints messages to the console.
        - `kill_server(server)`: Terminates the specified server.
        Raises:
            OSError: If there is an issue removing the PID file.
        """
        active = self.list_active()
        LAUNCH_LOGGER.info(f"active pidds: {active}")

        activeserver = [k for k, _, _, _ in active]
        KILL_ORDER = ["operator", "visualizer", "action", "orchestrator"]
        for group in KILL_ORDER:
            LAUNCH_LOGGER.info(f"Killing {group} group.")
            if group in self.servers.keys():
                G = self.servers[group]
                for server in G:
                    twait = 0.1
                    LAUNCH_LOGGER.info(
                        f"waiting {twait} seconds before killing server {server}"
                    )
                    time.sleep(twait)
                    LAUNCH_LOGGER.info(f"Killing {server}.")
                    if server in activeserver:
                        self.kill_server(server)

        # kill whats left
        for k, _, _, _ in self.list_active():
            self.kill_server(k)
        active = self.list_active()
        if active:
            LAUNCH_LOGGER.warning(
                f"Following servers failed to terminate: {active}. "
                f"Retaining '{self.pidFilePath}' for recovery."
            )
        else:
            LAUNCH_LOGGER.info(f"All servers terminated. Removing '{self.pidFilePath}'")
            if os.path.exists(self.pidFilePath):
                os.remove(self.pidFilePath)


def validateConfig(PIDD, confDict, helao_repo_root):
    """
    Validates the configuration dictionary for the servers.

    Args:
        PIDD (object): An object containing required keys (`reqKeys`) and code keys (`codeKeys`).
        confDict (dict): Configuration dictionary containing server details.
        helao_repo_root (str): Root directory path for the helao project.

    Returns:
        bool: True if the configuration is valid, False otherwise.

    The function performs the following checks:
    1. Ensures the 'servers' key is present in the configuration dictionary.
    2. Ensures all server keys are unique.
    3. Validates each server configuration:
        - Checks for the presence of required keys.
        - Ensures 'host' is a string.
        - Ensures 'port' is an integer.
        - Ensures 'group' is a string.
        - Validates code keys, ensuring only one is present and it is a string.
        - Checks if the server code file exists in the specified path.
    4. Ensures all server host:port combinations are unique.

    If any of these checks fail, an appropriate error message is printed and the function returns False.
    """
    if len(confDict["servers"]) != len(set(confDict["servers"])):
        _mux_log("info", "Server keys are not unique.")
        return False
    if "servers" not in confDict:
        _mux_log("info", "'servers' key not defined in config dictionary.")
        return False
    for server in confDict["servers"]:
        serverDict = confDict["servers"][server]
        hasKeys = [k in serverDict for k in PIDD.reqKeys]
        hasCode = [k for k in serverDict if k in PIDD.codeKeys]
        if not all(hasKeys):
            _mux_log(
                "info",
                f"{server} config is missing {[k for k,b in zip(PIDD.reqKeys, hasKeys) if b]}.",
            )
            return False
        if not isinstance(serverDict["host"], str):
            _mux_log("info", f"{server} server 'host' is not a string")
            return False
        if not isinstance(serverDict["port"], int):
            _mux_log("info", f"{server} server 'port' is not an integer")
            return False
        if not isinstance(serverDict["group"], str):
            _mux_log("info", f"{server} server 'group' is not a string")
            return False
        if hasCode:
            if len(hasCode) != 1:
                _mux_log(
                    "info",
                    f"{server} cannot have more than one code key {PIDD.codeKeys}",
                )
                return False
            if not isinstance(serverDict[hasCode[0]], str):
                _mux_log("info", f"{server} server '{hasCode[0]}' is not a string")
                return False
            # launchPath = os.path.join(
            #     "helao",
            #     "servers",
            #     serverDict["group"],
            #     serverDict[hasCode[0]] + ".py",
            # )
            # if not os.path.exists(os.path.join(helao_repo_root, launchPath)):
            #     LAUNCH_LOGGER.info(
            #         f"{server} server code helao/servers/{serverDict['group']}/{serverDict[hasCode[0]]+'.py'} does not exist."
            #     )
            #     return False
    serverAddrs = []
    for d in confDict["servers"].values():
        serverAddrs.extend(reserved_addresses(d))
    if len(serverAddrs) != len(set(serverAddrs)):
        _mux_log("info", "Server host:port locations are not unique.")
        return False
    # Single-owner sample-state guardrail: at most one server may declare
    # params.positions (the SAMPLE server after the archive hoist). Two owners
    # would race/clobber the shared archive-state JSON.
    positionsOwners = [
        server
        for server, d in confDict["servers"].items()
        if isinstance(d.get("params"), dict) and d["params"].get("positions")
    ]
    if len(positionsOwners) > 1:
        _mux_log(
            "info",
            f"More than one server declares 'params.positions': "
            f"{positionsOwners}. Exactly one sample-state owner is allowed.",
        )
        return False
    return True


def _posix_getchar():
    """Read one character in cbreak mode (POSIX).

    click.getchar()/tty.setraw put the terminal in *raw* mode for the blocking
    read, which disables output post-processing (OPOST/ONLCR). Because the
    key-reader thread blocks in this read almost continuously, log lines
    emitted by other threads during that window get a bare '\\n' with no
    carriage return, so every line stair-steps further right across the
    terminal. cbreak leaves OPOST/ONLCR enabled (it only turns off canonical
    mode and echo), so '\\n' -> '\\r\\n' translation still happens and log
    lines stay left-aligned. Control keys (CTRL-r/x/d) arrive as single bytes
    either way.
    """
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = os.read(fd, 1)
        if not ch:
            raise EOFError
        return ch.decode(errors="replace")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def wait_key():
    """
    Waits for a key press and returns the character of the key pressed.

    Handles different exceptions to return specific characters:
    - If a KeyboardInterrupt occurs, returns '\x03'.
    - If an EOFError occurs, returns '\x1a' for Windows ('nt') or '\x04' for other OS.

    Returns:
        str: The character of the key pressed or a specific character based on the exception.
    """
    try:
        if os.name == "nt":
            keypress = click.getchar()
        else:
            keypress = _posix_getchar()
    except KeyboardInterrupt:
        keypress = "\x03"
    except EOFError:
        if os.name == "nt":
            keypress = "\x1a"
        else:
            keypress = "\x04"
    return keypress


def launcher(confArg, confDict, helao_repo_root, extraopt="", restore=False):
    """
    Launches the Helao servers based on the provided configuration.
    Args:
        confArg (str): Path to the configuration file.
        confDict (dict): Dictionary containing the configuration details.
        helao_repo_root (str): Root directory of the Helao project.
        extraopt (str, optional): Additional options for launching. Defaults to "".
        restore (bool, optional): When True, pass ``--restore`` to launched
            orchestrators so they import their saved queues on startup. Defaults
            to False.
    Raises:
        Exception: If the configuration is invalid.
        Exception: If a server cannot be started due to port conflicts.
    Returns:
        Pidd: An instance of the Pidd class containing the process IDs of the launched servers.
    """
    # Strip ANY config extension (.py/.yml/.yaml), not just .py, so launching by
    # a full path to a .yml config (read_config accepts either a bare prefix or a
    # full path) yields a clean prefix -- the pid pickle is named
    # pids_<confPrefix>_<extraopt>.pck and kill_group globs it, so a stray ".yml"
    # here would change the pickle name. splitext drops only the final extension.
    confPrefix = os.path.splitext(os.path.basename(confArg))[0]
    # get the BaseModel which contains all the dirs for helao
    helaodirs = helao_dirs(confDict, "launcher")

    pidd = Pidd(
        pidFile=f"pids_{confPrefix}_{extraopt}.pck", pidPath=helaodirs.states_root
    )
    if not validateConfig(
        PIDD=pidd, confDict=confDict, helao_repo_root=helao_repo_root
    ):
        LAUNCH_LOGGER.error(f"Configuration for '{confPrefix}' is invalid.")
        raise Exception(f"Configuration for '{confPrefix}' is invalid.")
    else:
        LAUNCH_LOGGER.info(f"Configuration for '{confPrefix}' is valid.")

    launch_server_groups(
        pidd=pidd,
        confArg=confArg,
        confDict=confDict,
        helao_repo_root=helao_repo_root,
        extraopt=extraopt,
        restore=restore,
    )
    return pidd


def launch_server_groups(
    pidd, confArg, confDict, helao_repo_root, extraopt="", restore=False
):
    """Launch every configured server group into ``pidd``, in ``LAUNCH_ORDER``.

    Skips servers already running (matched by key/host/port) and servers whose
    host:port is occupied by something else, so it is safe to call against a
    partially-populated group. Shared by the cold start (:func:`launcher`) and
    by the CTRL-r "R" full relaunch, so both bring servers up in exactly the
    same order by exactly the same code path.

    ``pidd.servers`` and ``pidd.orchServs`` are (re)derived from ``confDict``
    here rather than by the caller, so a relaunch after a config edit picks up
    the current server set.

    Args:
        pidd (Pidd): Process registry to populate. Mutated in place, so existing
            closures over it stay valid across a relaunch.
        confArg (str): Config path/prefix forwarded to each server launcher.
        confDict (dict): Loaded configuration.
        helao_repo_root (str): Repo root used as the subprocess cwd.
        extraopt (str, optional): ``liveonly``/``gpvis``/``nolive``/``actionvis``
            visualizer filter. Defaults to "".
        restore (bool, optional): When True, pass ``--restore`` to launched
            orchestrators so they import their saved queues. Defaults to False.

    Returns:
        Pidd: The same ``pidd`` that was passed in, now populated.
    """
    # get running pids
    active = pidd.list_active()
    activeKHP = [(k, h, p) for k, h, p, _ in active]
    activeHP = [(h, p) for k, h, p, _ in active]
    allGroup = {
        k: {sk: sv for sk, sv in confDict["servers"].items() if sv["group"] == k}
        for k in LAUNCH_ORDER
    }
    pidd.servers = allGroup
    pidd.orchServs = []
    for group in LAUNCH_ORDER:
        LAUNCH_LOGGER.info(f"Launching {group} group.")
        if group in pidd.servers.keys():
            G = pidd.servers[group]
            for server in G.keys():
                S = G[server]
                codeKey = [k for k in S if k in pidd.codeKeys]
                if codeKey:
                    codeKey = codeKey[0]
                    servPy = S[codeKey]
                else:
                    servPy = None
                servHost = S["host"]
                servPort = S["port"]
                servKHP = (server, servHost, servPort)
                servHP = (servHost, servPort)
                if extraopt in ["liveonly", "gpvis"] and servPy != "live_visualizer":
                    continue
                # if 'py' key is None, assume remotely started or monitored by a separate action
                if servPy is None:
                    LAUNCH_LOGGER.info(
                        f"{server} does not specify one of ({pidd.codeKeys}) so action server will not be managed by this launcher.",
                    )
                elif servKHP in activeKHP:
                    LAUNCH_LOGGER.info(
                        f"{server} already running with pid [{active[activeKHP.index(servKHP)][3]}]",
                    )
                elif servHP in activeHP:
                    LAUNCH_LOGGER.warning(
                        f"Cannot start {server}, {servHost}:{servPort} is already in use."
                    )
                else:
                    LAUNCH_LOGGER.info(
                        f"Launching {server} at {servHost}:{servPort} using helao/servers/{group}/{servPy}.py",
                    )
                    if codeKey == "fast":
                        if group == "orchestrator":
                            pidd.orchServs.append(server)
                        cmd = ["python", "-u", "fast_launcher.py", confArg, server]
                        if restore and group == "orchestrator":
                            cmd.append("--restore")
                            LAUNCH_LOGGER.info(
                                f"{server} launched with --restore; will import saved queues."
                            )
                        p = subprocess.Popen(
                            cmd,
                            cwd=helao_repo_root,
                            env=CONSOLE.child_env(),
                            **CONSOLE.spawn_kwargs(),
                        )
                        CONSOLE.register(server, p)
                        ppid = p.pid
                    elif codeKey == "bokeh":
                        if (
                            extraopt in ["nolive", "actionvis"]
                            and servPy == "live_visualizer"
                        ):
                            continue
                        cmd = ["python", "-u", "bokeh_launcher.py", confArg, server]
                        p = subprocess.Popen(
                            cmd,
                            cwd=helao_repo_root,
                            env=CONSOLE.child_env(),
                            **CONSOLE.spawn_kwargs(),
                        )
                        CONSOLE.register(server, p)
                        ppid = p.pid
                    else:
                        LAUNCH_LOGGER.warning(
                            f"No launch method available for code type '{codeKey}', cannot launch {group}/{servPy}.py",
                        )
                        continue
                    pidd.store_pid(server, servHost, servPort, ppid)
                    pidd.procs[server] = p
                    time.sleep(0.5)
        if group != LAUNCH_ORDER[-1]:
            time.sleep(3)
    return pidd


# ---------------------------------------------------------------------------
# Hot-reload support (Phase 2): map pulled git changes to the idle servers that
# must restart. See .omc/specs/deep-dive-hotreload-phase2.md. All helpers are
# pure/read-only; the orchestration lives in main()'s thread_hotreload so it can
# reuse restart_server and pidd.
# ---------------------------------------------------------------------------


def discover_git_repos(helao_repo_root):
    """Return git working-tree roots to watch: the parent helao-async repo plus
    each nested ``helao/deploy/*`` deployment that is its own git repo."""
    repos = []
    if os.path.isdir(os.path.join(helao_repo_root, ".git")):
        repos.append(helao_repo_root)
    for deploy_dir in sorted(
        glob(os.path.join(helao_repo_root, "helao", "deploy", "*"))
    ):
        if os.path.isdir(os.path.join(deploy_dir, ".git")):
            repos.append(deploy_dir)
    return repos


def git_head(repo):
    """Return the current HEAD commit sha for ``repo`` (or None on failure)."""
    try:
        out = subprocess.run(
            ["git", "-C", repo, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def git_changed_files(repo, old_sha, new_sha):
    """Return absolute paths changed between ``old_sha`` and ``new_sha`` in ``repo``."""
    try:
        out = subprocess.run(
            ["git", "-C", repo, "diff", "--name-only", f"{old_sha}..{new_sha}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if out.returncode != 0:
            return []
        return [
            os.path.abspath(os.path.join(repo, rel.strip()))
            for rel in out.stdout.splitlines()
            if rel.strip()
        ]
    except Exception:
        return []


def server_loaded_files(server_entry, server_key, root):
    """Return the set of repo files a server has loaded.

    FastAPI servers (``fast``) are queried live at ``/loaded_modules``; bokeh
    servers (``bokeh``) have no HTTP route, so their startup snapshot at
    ``<root>/STATES/loaded_modules_<key>.json`` is read instead. Returns an empty
    set on any failure (treated as "no known mapping", so nothing is restarted
    on a bad read rather than restarting blindly)."""
    if "fast" in server_entry:
        try:
            resp = requests.post(
                f"http://{server_entry['host']}:{server_entry['port']}/loaded_modules",
                timeout=10,
            )
            if resp.status_code == 200:
                return set(resp.json().keys())
        except Exception:
            return set()
        return set()
    # bokeh server (visualizer/operator)
    if root is None:
        return set()
    snap = os.path.join(root, "STATES", f"loaded_modules_{server_key}.json")
    try:
        with open(snap) as f:
            return set(json.load(f).keys())
    except Exception:
        return set()


def wait_for_server_ready(host, port, timeout=30.0, interval=0.5):
    """Poll a just-restarted server until it accepts requests, or timeout.

    A freshly ``Popen``'d server needs a few seconds to boot uvicorn and bind
    its port. POSTing to it immediately (e.g. ``/attach_client`` when
    re-subscribing an orchestrator) raises ``ConnectionError`` because nothing
    is listening yet -- this is what broke hot-reload / CTRL-r re-subscription
    on Linux. Probe a cheap endpoint (``/get_status``) until it answers so the
    caller doesn't fire requests at a not-yet-listening socket.

    Returns True if the server responded before the timeout, else False.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.post(f"http://{host}:{port}/get_status", timeout=5)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def server_is_idle(group, server_entry):
    """Return True if a server is safe to restart (no active work).

    - action: ``/get_status`` shows no endpoint with active actions, AND the
      optional ``/hotreload_busy`` hook reports no pending background work
      (data syncer / analysis / batch-conversion queues, which are not action
      ``active_dict`` entries and would be lost on restart -- action servers get
      no --restore). A 404 on ``/hotreload_busy`` means an older server without
      the hook, so only the ``active_dict`` check gates it.
    - orchestrator: ``/global_status`` shows loop_state 'stopped' and no active
      actions. Pending (not-yet-dispatched) queue items are preserved across the
      restart via the --restore path, so they do not block idleness.
    - visualizer/operator: always idle (stateless bokeh subscribers).

    Any query failure returns False (fail safe: do not restart what we cannot
    confirm is idle)."""
    if group in ("visualizer", "operator"):
        return True
    host, port = server_entry["host"], server_entry["port"]
    try:
        if group == "orchestrator":
            resp = requests.post(f"http://{host}:{port}/global_status", timeout=10)
            if resp.status_code != 200:
                return False
            gs = resp.json()
            return gs.get("loop_state") == "stopped" and not gs.get("active_dict")
        if group == "action":
            resp = requests.post(f"http://{host}:{port}/get_status", timeout=10)
            if resp.status_code != 200:
                return False
            endpoints = resp.json().get("endpoints", {})
            if any(ep.get("active_dict") for ep in endpoints.values()):
                return False
            # No active HELAO action, but the server may still be draining a
            # background processing queue (data syncer, analysis, batch
            # conversions) that a restart would drop. Defer while busy. The
            # /hotreload_busy hook is optional: a 404 (older server without the
            # hook) means there is no background queue to protect.
            bresp = requests.post(f"http://{host}:{port}/hotreload_busy", timeout=10)
            if bresp.status_code == 404:
                return True
            if bresp.status_code != 200:
                return False
            return not bresp.json().get("busy", False)
    except Exception:
        return False
    # unknown group: be conservative
    return False


def main():
    """
    Main function to initialize and launch the HELAO application.
    This function performs the following tasks:
    1. Initializes colorama for colored terminal output.
    2. Checks if the script is running in the 'helao' conda environment.
    3. Validates the PYTHONPATH environment variable and retrieves paths for HELAO repositories.
    4. Loads the configuration file based on the provided argument.
    5. Runs the full unit-test suite when ``run_unit_tests: true`` is set in the loaded config.
    6. Clears the terminal screen and prints the HELAO banner.
    7. Displays the current branch and status of each local HELAO repository.
    8. Compresses old log files.
    9. Launches the HELAO application using the provided configuration.
    10. Sets up hotkey listeners for terminating or restarting servers.
    The function also defines helper functions for printing messages, stopping servers,
    and handling hotkey inputs for server management.
    Raises:
        SystemExit: If unit tests fail (when enabled in config) or if PYTHONPATH is not defined.
    """
    colorama.init(strip=not sys.stdout.isatty())  # strip colors if stdout is redirected
    if os.environ.get("CONDA_DEFAULT_ENV") != "helao":
        print(
            "launch.py launcher was not called from a 'helao' conda environment.",
        )
    python_path = os.environ.get("PYTHONPATH")
    if python_path is None:
        print("PYTHONPATH environment var not defined.")
        quit()
    else:
        python_paths = (
            python_path.split(";")
            if sys.platform == "win32"
            else python_path.split(":")
        )
        python_paths = [os.path.abspath(x) for x in python_paths]
        python_paths = [
            x for x in python_paths if os.path.basename(x).startswith("helao-async")
        ]
        print(python_paths)
        branches = {
            os.path.basename(x): subprocess.getoutput(
                f'git --git-dir={os.path.join(x, ".git")} branch --show-current'
            ).split("\n")[-1]
            for x in python_paths
        }
        print(branches)
    helao_repo_root = os.path.dirname(os.path.realpath(__file__))
    # Separate flags (e.g. --restore) from positional args so confArg and the
    # optional extraopt are not shifted by a flag's position on the command line.
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    cli_flags = [a for a in sys.argv[1:] if a.startswith("--")]
    restore = "--restore" in cli_flags
    confArg = positional[0]
    config = read_config(confArg)

    # Run the full unit-test suite only when the config opts in.
    if config.get("run_unit_tests") is True:
        from run_unit_tests import main as run_all_unit_tests

        if run_all_unit_tests() != 0:
            quit()

    # save ntp time offset
    helaodirs = helao_dirs(config, "launcher")
    get_ntp_time("time.nist.gov", os.path.join(helaodirs.log_root, "ntpLastSync.txt"))

    if len(positional) > 1:
        extraopt = positional[1]
    else:
        extraopt = ""

    print("\x1b[2J")  # clear screen
    print("\n\n")
    cprint(
        figlet_format(
            f"HELAO\n{get_hlo_version()[:7]}",
            font="nancyj-fancy",
        ),
        "magenta" if config["dummy"] else "green",
        attrs=["bold"],
    )
    for x in python_paths:
        repo = os.path.basename(x)
        cprint(
            f"\n\nlocal repo '{repo}' on branch: '{branches[repo]}'",
            "yellow" if config["dummy"] else "cyan",
            attrs=["bold"],
        )
        git_stat = subprocess.getoutput(
            f'git --git-dir={os.path.join(x, ".git")} show --stat'
        )
        git_stat = "\n".join(
            [
                s
                for s in git_stat.split("\n")
                if not s.strip().startswith(
                    "The system cannot find the path specified."
                )
            ]
        )
        cprint(git_stat, "yellow" if config["dummy"] else "cyan")
    cprint(
        f"\n\nusing config: {config['loaded_config_path']}\n", "white", attrs=["bold"]
    )
    modestring = "dummy" if config["dummy"] else "production"
    cprint(f"launching HELAO ({modestring} mode) in 5 seconds...\n\n", "white")
    time.sleep(5)

    global LAUNCH_LOGGER
    LAUNCH_LOGGER = logging.make_logger(
        __file__, log_dir=helaodirs.log_root, log_level=config.get("log_level", 20)
    )
    # Gate the launcher's own console output on menu isolation too. Its records
    # are a small share of the terminal, but the per-keypress hotkey hint would
    # otherwise print straight over the menu.
    CONSOLE.install_log_gate(LAUNCH_LOGGER)
    # This process owns the CTRL-r menu and outlives its servers, so it is safe
    # to pipe their output through the mux. Opt in explicitly; fire-and-forget
    # callers of launcher() must not (see ConsoleMux.activate).
    CONSOLE.activate()
    # compress old logs:
    log_root = os.path.join(config["root"], "LOGS")
    for server_name in ["_MASTER_", "bokeh_launcher", "fast_launcher"]:
        old_log_txts = glob(os.path.join(log_root, server_name, "*.txt"))
        nots_counter = 0
        for old_log in old_log_txts:
            LAUNCH_LOGGER.info(f"Compressing: {old_log}")
            try:
                timestamp_found = False
                timestamp = ""
                with open(old_log, "r") as f:
                    for line in f:
                        if line.replace("error_[", "[").strip().startswith("["):
                            timestamp_found = True
                            timestamp = re.findall("[0-9]{2}:[0-9]{2}:[0-9]{2}", line)[
                                0
                            ].replace(":", "")
                            zipname = old_log.replace(".txt", f"{timestamp}.zip")
                            arcname = os.path.basename(old_log).replace(
                                ".txt", f"{timestamp}.txt"
                            )
                            break
                if not timestamp_found:
                    while os.path.exists(
                        old_log.replace(".txt", f"__{nots_counter}.zip")
                    ):
                        nots_counter += 1
                    zipname = old_log.replace(".txt", f"__{nots_counter}.zip")
                    arcname = os.path.basename(old_log).replace(
                        ".txt", f"__{nots_counter}.txt"
                    )
                with zipfile.ZipFile(
                    zipname, "w", compression=zipfile.ZIP_DEFLATED
                ) as zf:
                    zf.write(old_log, arcname)
                os.remove(old_log)
            except Exception:
                LAUNCH_LOGGER.error(f"Error compressing log: {old_log}", exc_info=True)

    pidd = launcher(
        confArg=confArg,
        confDict=config,
        helao_repo_root=helao_repo_root,
        extraopt=extraopt,
        restore=restore,
    )

    def hotkey_msg():
        """
        Prints a message with hotkey instructions for terminating orchestration group,
        restarting options, and disconnecting.

        The message includes the following hotkey instructions:
        - CTRL-x: Terminate orchestration group
        - CTRL-r: Restart options
        - CTRL-t: Toggle hot-reload watcher on/off
        - CTRL-d: Disconnect
        """
        LAUNCH_LOGGER.info(
            "CTRL-x to terminate orchestration group. CTRL-r for restart options. "
            "CTRL-t to toggle hot-reload. CTRL-d to disconnect."
        )

    def stop_server(groupname, servername):
        """
        Stops the specified server by unsubscribing its websockets and sending a shutdown request.

        Args:
            groupname (str): The name of the group to which the server belongs.
            servername (str): The name of the server to be stopped.

        Returns:
            dict: The server details including host and port.
        """
        LAUNCH_LOGGER.info(f"Unsubscribing {servername} websockets.")
        S = pidd.servers[groupname][servername]
        # /shutdown blocks until the server's shutdown_event (incl. the driver's
        # shutdown hook, e.g. gamry disconnect + kill GamryCOM) completes. Bound
        # the wait so a hung driver shutdown can't stall teardown forever; the
        # server-side handler keeps running and kill_server reaps afterward.
        requests.post(
            f"http://{S['host']}:{S['port']}/shutdown", timeout=SHUTDOWN_POST_TIMEOUT
        )
        return S

    def graceful_shutdown_all():
        """POST /shutdown to every managed server, in ``SHUTDOWN_POST_ORDER``.

        Gives each server its cooperative shutdown hook (drivers disconnect,
        orchestrators detach subscribers and export any non-empty queues to
        ``STATES/queues.pck``) before anything is signalled. Errors are logged
        per server and never abort the sweep -- a server that is already dead,
        wedged, or lacks a ``/shutdown`` route must not block the rest.

        Shared by CTRL-x teardown and the CTRL-r "R" full relaunch so both get
        the same ordering and the same queue-export guarantee.

        Orchestrators are addressed via ``pidd.orchServs`` (only those this
        launcher actually started) rather than the whole configured group, so an
        externally-managed orchestrator is never shut down from here. Visualizer
        and operator bokeh apps expose no ``/shutdown`` route and are left to be
        signalled by ``pidd.close()``.
        """
        for group in SHUTDOWN_POST_ORDER:
            if group not in pidd.servers:
                continue
            LAUNCH_LOGGER.info(f"Shutting down {group} group.")
            if group == "orchestrator":
                servers = list(pidd.orchServs)
            else:
                servers = list(pidd.servers[group])
            for server in servers:
                try:
                    LAUNCH_LOGGER.info(f"Shutting down {server}.")
                    stop_server(group, server)
                except Exception:
                    LAUNCH_LOGGER.error(
                        f" ... got error shutting down {group}/{server}: ",
                        exc_info=True,
                    )

    # Serializes all pidd mutation across the keypress thread (CTRL-r/CTRL-x) and
    # the hot-reload daemon so their read-modify-write on pidd.d / the pickle /
    # pidd.procs can't interleave and drop, resurrect, or double-restart a server.
    pidd_lock = threading.Lock()

    def restart_server(groupname, servername, restore=False):
        """Gracefully stop, kill, and relaunch a single server, re-registering
        action servers with every orchestrator afterward.

        Shared by the CTRL-r hotkey and the hot-reload watcher so both drive
        exactly one restart code path. Reuses ``pidd.kill_server`` (graceful ->
        SIGKILL + reap) and records the new ``Popen`` handle in ``pidd.procs``
        for later reaping. Holds ``pidd_lock`` for the whole sequence so it
        cannot race the keypress thread's pidd mutations.

        Args:
            groupname (str): Server group (action/orchestrator/visualizer/operator).
            servername (str): Server key to restart.
            restore (bool): When True and the server is an orchestrator, pass
                ``--restore`` so it imports its saved queues on startup.

        Returns:
            bool: True if the relaunch sequence completed without error.
        """
        with pidd_lock:
            try:
                codeKey = [
                    k
                    for k in pidd.servers[groupname][servername].keys()
                    if k in pidd.codeKeys
                ][0]
                S = stop_server(groupname, servername)
                LAUNCH_LOGGER.info(f"{servername} successful shutdown() event.")
                pidd.kill_server(servername)
                LAUNCH_LOGGER.info(f"Successfully closed {servername} process.")
                cmd = ["python", "-u", f"{codeKey}_launcher.py", confArg, servername]
                if restore and groupname == "orchestrator":
                    cmd.append("--restore")
                CONSOLE.unregister(servername)
                p = subprocess.Popen(
                    cmd,
                    cwd=helao_repo_root,
                    env=CONSOLE.child_env(),
                    **CONSOLE.spawn_kwargs(),
                )
                CONSOLE.register(servername, p)
                pidd.store_pid(servername, S["host"], S["port"], p.pid)
                pidd.procs[servername] = p
                if groupname == "action":
                    # The restarted server was just Popen'd; wait for it to
                    # bind its port before re-subscribing, otherwise the
                    # /attach_client POST below hits a dead socket
                    # (ConnectionError) and re-subscription silently fails.
                    if not wait_for_server_ready(S["host"], S["port"]):
                        LAUNCH_LOGGER.warning(
                            f"Restarted {servername} not responding after wait; "
                            f"attempting re-subscription anyway."
                        )
                    for orchserv in pidd.orchServs:
                        OS = pidd.servers["orchestrator"][orchserv]
                        LAUNCH_LOGGER.info(
                            f"Re-subscribing {orchserv} to restarted {servername}."
                        )
                        # A restarted action server comes up with an empty
                        # subscriber list, so the orchestrator must re-subscribe
                        # to it. Mirror Orch.subscribe_all: call the ACTION
                        # server's /attach_client with the orchestrator as the
                        # client, so the action server pushes its status to the
                        # orch's /update_status. (Calling the ORCH's
                        # /attach_client with the action server as the client is
                        # backwards -- it makes the orch POST to
                        # <action>/update_status, which 404s and spams the log.)
                        requests.post(
                            f"http://{S['host']}:{S['port']}/attach_client",
                            params={
                                "client_servkey": orchserv,
                                "client_host": OS["host"],
                                "client_port": OS["port"],
                            },
                            timeout=10,
                        )
                return True
            except Exception:
                LAUNCH_LOGGER.error(
                    f" ... got error restarting {groupname}/{servername}: ",
                    exc_info=True,
                )
                return False

    def relaunch_all():
        """Shut down every server, then relaunch the whole group cold-start style.

        The CTRL-r "R" option. Sequence:

        1. POST /shutdown to every server via :func:`graceful_shutdown_all`, so
           drivers disconnect cleanly and orchestrators export any non-empty
           queues to ``STATES/queues.pck``.
        2. ``pidd.close()`` to signal/reap whatever is left, in ``KILL_ORDER``.
        3. Recreate the pid pickle, which ``close()`` deletes after a clean
           teardown. Mirrors what ``Pidd.__init__`` does for an absent file;
           without it every subsequent ``list_active()`` raises
           ``FileNotFoundError``.
        4. Verify nothing survived. A survivor still holds its host:port, so
           relaunching would log "already in use" and silently leave that server
           down; abort instead and leave the group torn down for the operator to
           inspect.
        5. ``launch_server_groups`` to bring everything back up in
           ``LAUNCH_ORDER`` -- the same function the cold start uses.

        Orchestrators are relaunched with whatever ``restore`` setting this
        session was launched with, NOT unconditionally: a cold start only imports
        queues when the operator opted in via ``--restore`` or
        ``restore_queues_on_startup``, and "relaunch like a cold start" has to
        mean that too. Forcing it on turned out to break production -- it opts the
        orchestrator into importing ``STATES/queues.pck`` even when the config
        never asked for it, and a pickle left by an older release raises
        ``AttributeError`` inside the FastAPI startup event, so the orchestrator
        exits instead of coming up. Step 1 still exports the queues either way,
        so nothing is lost; they can be imported deliberately.

        Holds ``pidd_lock`` throughout so the hot-reload watcher cannot restart a
        server into the middle of the teardown.

        Returns:
            bool: True if every server was torn down and the relaunch ran.
        """
        with pidd_lock:
            LAUNCH_LOGGER.info("Full relaunch: shutting down all servers.")
            try:
                graceful_shutdown_all()
                pidd.close()
                # close() removes the pid pickle once everything is down; recreate
                # it from the (now empty) in-memory dict so the reads below and the
                # relaunch's store_pid calls have a file to work with.
                pidd.write_global()
            except Exception:
                LAUNCH_LOGGER.error(
                    " ... got error during full-relaunch shutdown: ", exc_info=True
                )
                return False

            survivors = pidd.list_active()
            if survivors:
                LAUNCH_LOGGER.error(
                    f"Full relaunch aborted: {[k for k, _, _, _ in survivors]} "
                    f"survived shutdown and still hold their ports. Nothing was "
                    f"relaunched; resolve those processes then use CTRL-r again."
                )
                return False

            LAUNCH_LOGGER.info(
                f"All servers down. Relaunching in cold-start order: "
                f"{'/'.join(LAUNCH_ORDER)}."
            )
            try:
                launch_server_groups(
                    pidd=pidd,
                    confArg=confArg,
                    confDict=config,
                    helao_repo_root=helao_repo_root,
                    extraopt=extraopt,
                    restore=restore,
                )
            except Exception:
                LAUNCH_LOGGER.error(
                    " ... got error during full relaunch: ", exc_info=True
                )
                return False
            LAUNCH_LOGGER.info("Full relaunch complete.")
            return True

    # Runtime on/off switch for the hot-reload watcher, flipped by the CTRL-t
    # hotkey (see thread_waitforkey). The watcher thread always runs but only
    # detects commits / restarts servers while this is set; when cleared it
    # idles without advancing the tracked HEADs, so commits that land while
    # paused are applied on resume.
    hotreload_enabled = threading.Event()

    def thread_hotreload(poll_seconds):
        """Poll watched git repos; hot-reload idle servers whose loaded code changed.

        On each poll: detect new commits (git pull) in the parent repo and any
        nested deployment repos, diff the changed files, and intersect them with
        each running server's loaded-module set (live /loaded_modules for fast
        servers, startup snapshot for bokeh). Affected servers are queued and
        restarted once idle (busy ones are deferred to a later poll, never
        forced). Reuses restart_server (Phase-1 kill+reap+re-register).
        """
        repos = discover_git_repos(helao_repo_root)
        if not repos:
            LAUNCH_LOGGER.warning(
                "Hot-reload: no git repos found to watch; watcher exiting."
            )
            return
        root = config.get("root", None)
        # Seed only repos whose HEAD is currently readable; a repo that fails to
        # read here stays unseeded and is picked up (as a seed, not a diff) on a
        # later poll, so its first observed commit is never silently dropped.
        heads = {}
        for r in repos:
            h = git_head(r)
            if h is not None:
                heads[r] = h
        LAUNCH_LOGGER.info(
            f"Hot-reload watching {len(repos)} repo(s) every {poll_seconds}s: {repos}"
        )
        pending = set()  # (group, name) affected but not yet restarted
        while True:
            time.sleep(poll_seconds)
            if not hotreload_enabled.is_set():
                # Paused via CTRL-t: do not poll git or advance HEADs, so any
                # commits during the pause are picked up once re-enabled.
                continue
            changed = set()
            for r in repos:
                cur = git_head(r)
                if cur is None:
                    continue
                if r not in heads:
                    # first successful read for this repo: seed, don't diff
                    heads[r] = cur
                    continue
                if cur == heads[r]:
                    continue
                LAUNCH_LOGGER.info(
                    f"Hot-reload: new commit in {r}: {heads[r]} -> {cur}"
                )
                changed.update(git_changed_files(r, heads[r], cur))
                heads[r] = cur
            if changed:
                active_names = [k for k, *_ in pidd.list_active()]
                mapped_any = False
                for group, gd in pidd.servers.items():
                    for name, entry in gd.items():
                        if name not in active_names:
                            continue
                        hits = changed & server_loaded_files(entry, name, root)
                        if hits:
                            mapped_any = True
                            LAUNCH_LOGGER.info(
                                f"Hot-reload: {group}/{name} affected by "
                                f"{len(hits)} changed file(s): {sorted(hits)}"
                            )
                            pending.add((group, name))
                if not mapped_any:
                    LAUNCH_LOGGER.info(
                        f"Hot-reload: {len(changed)} changed file(s) map to no "
                        f"running server; nothing to reload."
                    )
                if len(pending) > 3:
                    LAUNCH_LOGGER.warning(
                        f"Hot-reload: {len(pending)} servers queued for restart "
                        f"(likely a core/helpers change); restarts are gated on "
                        f"idle and applied one at a time."
                    )
            if pending:
                still_pending = set()
                for group, name in pending:
                    entry = pidd.servers.get(group, {}).get(name)
                    if entry is None:
                        continue  # server no longer known; drop
                    if server_is_idle(group, entry):
                        LAUNCH_LOGGER.info(
                            f"Hot-reload: restarting idle {group}/{name}."
                        )
                        if not restart_server(
                            group, name, restore=(group == "orchestrator")
                        ):
                            # relaunch failed (server may now be down); keep it
                            # queued so a later poll retries rather than leaving
                            # it dead silently.
                            LAUNCH_LOGGER.error(
                                f"Hot-reload: restart of {group}/{name} failed; "
                                f"will retry next poll."
                            )
                            still_pending.add((group, name))
                    else:
                        LAUNCH_LOGGER.info(
                            f"Hot-reload: {group}/{name} busy; deferring restart."
                        )
                        still_pending.add((group, name))
                pending = still_pending

    def thread_waitforkey():
        """
        Monitors for specific keypress events and performs corresponding actions.

        This function waits for specific keypresses and performs actions based on the key pressed:
        - CTRL-r: Prompts the user to restart a running server.
        - CTRL-x: Terminates the orchestration group and shuts down servers in a specified order.
        - Other keys: Disconnects the action monitor.

        The function continuously waits for keypresses and handles them accordingly until a termination key is pressed.

        Keypress Actions:
        - CTRL-r: Lists currently running servers and prompts the user to select a server to restart.
            - Restarts the selected server and re-registers it with orchestrators if necessary.
            - Entering capital "R" instead shuts every server down and relaunches
              the whole group in cold-start order (see ``relaunch_all``).
        - CTRL-x: Terminates the orchestration group and shuts down servers in the specified order.
        - Other keys: Disconnects the action monitor and provides instructions to reconnect.

        Exceptions:
        - Handles and logs exceptions that occur during server restart and shutdown processes.

        Note:
        - The function uses `print_message` to log messages and `wait_key` to capture keypresses.
        - The function interacts with the `pidd` object to manage server processes and orchestrators.
        """
        result = None
        while result not in ["\x18", "\x04"]:
            if result == "\x12":
                LAUNCH_LOGGER.info("Detected CTRL-r, checking restart options.")
                slist = [
                    (gk, sk) for gk, gd in pidd.servers.items() for sk in gd.keys()
                ]
                opts = range(len(slist))
                while True:
                    # Only the prompt is isolated. The restart itself runs with
                    # output visible -- that is exactly when you want to watch
                    # the servers come back up.
                    with CONSOLE.isolated():
                        print("Currently running server type/name:")
                        for i, (gk, sk) in enumerate(slist):
                            print(f"{i}: {gk}/{sk}")
                        print("R: shut down ALL servers and relaunch the whole group")
                        if len(slist) > 1:
                            optionstr = f"{min(opts)}-{max(opts)}"
                        else:
                            optionstr = "0"
                        sind = input(
                            f"Enter server num to restart, R to relaunch all, "
                            f"or blank to cancel [{optionstr}/R]: "
                        )
                    if sind in [str(o) for o in opts]:
                        sg, sn = slist[int(sind)]
                        LAUNCH_LOGGER.info(f"Got option {sind}. Restarting {sg}/{sn}.")
                        restart_server(sg, sn)
                        break
                    # Capital-R only: a lowercase 'r' is far more likely to be a
                    # stray keypress than a deliberate request to bounce every
                    # server on a running instrument.
                    elif sind == "R":
                        LAUNCH_LOGGER.info(
                            "Got option R. Shutting down all servers and relaunching."
                        )
                        relaunch_all()
                        break
                    elif sind == "":
                        LAUNCH_LOGGER.info("Cancelling restart.")
                        break
                    else:
                        LAUNCH_LOGGER.warning(f"'{sind}' is not a valid option.")
                result = None
            if result == "\x14":
                if hotreload_enabled.is_set():
                    hotreload_enabled.clear()
                    LAUNCH_LOGGER.info(
                        "Detected CTRL-t: hot-reload watcher PAUSED "
                        "(no servers will be restarted on git pull)."
                    )
                else:
                    hotreload_enabled.set()
                    LAUNCH_LOGGER.info(
                        "Detected CTRL-t: hot-reload watcher RESUMED "
                        "(idle servers restart on pulled code changes)."
                    )
                result = None
            hotkey_msg()
            result = wait_key()
        if result == "\x18":
            LAUNCH_LOGGER.info("Detected CTRL-x, terminating orchestration group.")
            # Orchestrators first (they detach subscribers and export non-empty
            # queues), then action servers. Visualizer/operator bokeh apps have
            # no /shutdown route, so pidd.close() signals those.
            graceful_shutdown_all()
            # hold pidd_lock so a concurrent hot-reload restart can't interleave
            # its pidd mutation with the teardown's kill loop.
            with pidd_lock:
                pidd.close()
        else:
            LAUNCH_LOGGER.info(
                f"Disconnecting action monitor. Launch 'python launch.py {confArg}' to reconnect."
            )

    x = threading.Thread(target=thread_waitforkey)
    x.start()

    # Phase-2 hot-reload: ON by default. Disable via the `--no-hot-reload` CLI
    # flag or `hot_reload.enabled: false` in the config. Precedence:
    # --no-hot-reload (force off) > --hot-reload (force on) > config
    # hot_reload.enabled (default True). Runs as a daemon thread so it dies with
    # the process.
    hot_reload_cfg = config.get("hot_reload", {}) or {}
    if "--no-hot-reload" in cli_flags:
        hot_reload_on = False
        reason = "--no-hot-reload flag"
    elif "--hot-reload" in cli_flags:
        hot_reload_on = True
        reason = "--hot-reload flag"
    else:
        hot_reload_on = bool(hot_reload_cfg.get("enabled", True))
        reason = f"config hot_reload.enabled={hot_reload_cfg.get('enabled', True)}"
    # The watcher thread always runs; whether it actually polls is governed by
    # the hotreload_enabled Event, which the CTRL-t hotkey toggles at runtime.
    # The resolved on/off state above only sets the initial position.
    poll_seconds = int(hot_reload_cfg.get("poll_seconds", 30))
    if hot_reload_on:
        hotreload_enabled.set()
        LAUNCH_LOGGER.info(
            f"Hot-reload ENABLED ({reason}, poll {poll_seconds}s). Idle servers "
            f"whose loaded code changes on git pull will be restarted. "
            f"Toggle at runtime with CTRL-t."
        )
    else:
        hotreload_enabled.clear()
        LAUNCH_LOGGER.info(
            f"Hot-reload disabled ({reason}). Toggle on at runtime with CTRL-t, "
            f"or set hot_reload.enabled: true / omit --no-hot-reload at launch."
        )
    hr = threading.Thread(target=thread_hotreload, args=(poll_seconds,), daemon=True)
    hr.start()


if __name__ == "__main__":
    main()
