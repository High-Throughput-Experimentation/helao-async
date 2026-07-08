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

import os
import sys
import json
import pickle
import psutil
import time
import requests
import subprocess
import re
import threading
import zipfile
from glob import glob

import click
from termcolor import cprint
from pyfiglet import figlet_format
import colorama

from helao.core.version import get_hlo_version
from helao.helpers.helao_dirs import helao_dirs
from helao.helpers.config_loader import read_config
from helao.helpers.time_utils import get_ntp_time

from logging import Logger
from helao.helpers import helao_logging as logging

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
        self.codeKeys = ("fast", "bokeh")
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
        # print_message(LAUNCH_LOGGER, "launcher", helaoPids)
        running = [tup for tup in helaoPids if psutil.pid_exists(tup[3])]
        # active = []
        # for tup in running:
        #     pid = tup[3]
        #     port = tup[2]
        #     host = tup[1]
        #     proc = psutil.Process(pid)
        #     if proc.name() in self.PROC_NAMES:
        #         connections = [
        #             c for c in proc.connections("tcp4") if c.status == "LISTEN"
        #         ]
        #         if (host, port) in [(c.laddr.ip, c.laddr.port) for c in connections]:
        #             active.append(tup)
        return running

    def _reap_child(self, k):
        """Reap the OS child for server ``k`` so a terminated process does not
        linger as an unwaited zombie. No-op if this launcher never spawned it
        (e.g. servers appended by ``append.py`` or a fresh ``Pidd`` in cli.py)."""
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
            LAUNCH_LOGGER.info(
                f"All servers terminated. Removing '{self.pidFilePath}'"
            )
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
        LAUNCH_LOGGER.info("Server keys are not unique.")
        return False
    if "servers" not in confDict:
        LAUNCH_LOGGER.info("'servers' key not defined in config dictionary.")
        return False
    for server in confDict["servers"]:
        serverDict = confDict["servers"][server]
        hasKeys = [k in serverDict for k in PIDD.reqKeys]
        hasCode = [k for k in serverDict if k in PIDD.codeKeys]
        if not all(hasKeys):
            LAUNCH_LOGGER.info(
                f"{server} config is missing {[k for k,b in zip(PIDD.reqKeys, hasKeys) if b]}."
            )
            return False
        if not isinstance(serverDict["host"], str):
            LAUNCH_LOGGER.info(f"{server} server 'host' is not a string")
            return False
        if not isinstance(serverDict["port"], int):
            LAUNCH_LOGGER.info(f"{server} server 'port' is not an integer")
            return False
        if not isinstance(serverDict["group"], str):
            LAUNCH_LOGGER.info(f"{server} server 'group' is not a string")
            return False
        if hasCode:
            if len(hasCode) != 1:
                LAUNCH_LOGGER.info(
                    f"{server} cannot have more than one code key {PIDD.codeKeys}"
                )
                return False
            if not isinstance(serverDict[hasCode[0]], str):
                LAUNCH_LOGGER.info(f"{server} server '{hasCode[0]}' is not a string")
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
    serverAddrs = [f"{d['host']}:{d['port']}" for d in confDict["servers"].values()]
    if len(serverAddrs) != len(set(serverAddrs)):
        LAUNCH_LOGGER.info("Server host:port locations are not unique.")
        return False
    return True


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
        keypress = click.getchar()
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
    confPrefix = os.path.basename(confArg).replace(".py", "")
    # get the BaseModel which contains all the dirs for helao
    helaodirs = helao_dirs(confDict, "launcher")

    # API server launch priority (matches folders in root helao-dev/).
    # The "operator" group is launched the same way as visualizers (a bokeh
    # subprocess via bokeh_launcher.py, resolved from servers/operator/), but is
    # ordered immediately after the orchestrator group so a standalone operator
    # can connect to a live orchestrator as soon as it starts.
    LAUNCH_ORDER = ["action", "orchestrator", "operator", "visualizer"]

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
                        cmd = ["python", "fast_launcher.py", confArg, server]
                        if restore and group == "orchestrator":
                            cmd.append("--restore")
                            LAUNCH_LOGGER.info(
                                f"{server} launched with --restore; will import saved queues."
                            )
                        p = subprocess.Popen(cmd, cwd=helao_repo_root)
                        ppid = p.pid
                    elif codeKey == "bokeh":
                        if (
                            extraopt in ["nolive", "actionvis"]
                            and servPy == "live_visualizer"
                        ):
                            continue
                        cmd = ["python", "bokeh_launcher.py", confArg, server]
                        p = subprocess.Popen(cmd, cwd=helao_repo_root)
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


def server_is_idle(group, server_entry):
    """Return True if a server is safe to restart (no active work).

    - action: ``/get_status`` shows no endpoint with active actions.
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
            return not any(ep.get("active_dict") for ep in endpoints.values())
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
        - CTRL-d: Disconnect
        """
        LAUNCH_LOGGER.info(
            "CTRL-x to terminate orchestration group. CTRL-r for restart options. CTRL-d to disconnect."
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
        requests.post(f"http://{S['host']}:{S['port']}/shutdown")
        return S

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
                cmd = ["python", f"{codeKey}_launcher.py", confArg, servername]
                if restore and groupname == "orchestrator":
                    cmd.append("--restore")
                p = subprocess.Popen(
                    cmd,
                    cwd=helao_repo_root,
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                )
                pidd.store_pid(servername, S["host"], S["port"], p.pid)
                pidd.procs[servername] = p
                if groupname == "action":
                    for orchserv in pidd.orchServs:
                        OS = pidd.servers["orchestrator"][orchserv]
                        LAUNCH_LOGGER.info(f"Reregistering {servername} on {orchserv}.")
                        # /attach_client takes client_servkey, client_host,
                        # client_port as query params (base_api.py); a form body
                        # of only client_servkey yields a 422.
                        requests.post(
                            f"http://{OS['host']}:{OS['port']}/attach_client",
                            params={
                                "client_servkey": servername,
                                "client_host": S["host"],
                                "client_port": S["port"],
                            },
                        )
                return True
            except Exception:
                LAUNCH_LOGGER.error(
                    f" ... got error restarting {groupname}/{servername}: ",
                    exc_info=True,
                )
                return False

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
            LAUNCH_LOGGER.warning("Hot-reload: no git repos found to watch; watcher exiting.")
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
                        LAUNCH_LOGGER.info(f"Hot-reload: restarting idle {group}/{name}.")
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
                    print("Currently running server type/name:")
                    for i, (gk, sk) in enumerate(slist):
                        print(f"{i}: {gk}/{sk}")
                    if len(slist) > 1:
                        optionstr = f"{min(opts)}-{max(opts)}"
                    else:
                        optionstr = "0"
                    sind = input(
                        f"Enter server num to restart or blank to cancel [{optionstr}]: "
                    )
                    if sind in [str(o) for o in opts]:
                        sg, sn = slist[int(sind)]
                        LAUNCH_LOGGER.info(f"Got option {sind}. Restarting {sg}/{sn}.")
                        restart_server(sg, sn)
                        break
                    elif sind == "":
                        LAUNCH_LOGGER.info("Cancelling restart.")
                        break
                    else:
                        LAUNCH_LOGGER.warning(f"'{sind}' is not a valid option.")
                result = None
            hotkey_msg()
            result = wait_key()
        if result == "\x18":
            LAUNCH_LOGGER.info("Detected CTRL-x, terminating orchestration group.")
            for server in pidd.orchServs:
                try:
                    stop_server("orchestrator", server)
                except Exception:
                    LAUNCH_LOGGER.error(" ... got error: ", exc_info=True)
            # in case a /shutdown is added to other FastAPI servers (not the shutdown without '/')
            # KILL_ORDER = ["visualizer", "action", "server"] # orch are killed above
            # no /shutdown in visualizers
            KILL_ORDER = ["action"]  # orch are killed above
            for group in KILL_ORDER:
                LAUNCH_LOGGER.info(f"Shutting down {group} group.")
                if group in pidd.servers.keys():
                    G = pidd.servers[group]
                    for server in G.keys():
                        try:
                            LAUNCH_LOGGER.info(f"Shutting down {server}.")
                            S = G[server]
                            # will produce a 404 if not found
                            requests.post(f"http://{S['host']}:{S['port']}/shutdown")
                        except Exception:
                            LAUNCH_LOGGER.error(" ... got error: ", exc_info=True)
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
    if hot_reload_on:
        poll_seconds = int(hot_reload_cfg.get("poll_seconds", 30))
        LAUNCH_LOGGER.info(
            f"Hot-reload ENABLED ({reason}, poll {poll_seconds}s). Idle servers "
            f"whose loaded code changes on git pull will be restarted."
        )
        hr = threading.Thread(
            target=thread_hotreload, args=(poll_seconds,), daemon=True
        )
        hr.start()
    else:
        LAUNCH_LOGGER.info(
            f"Hot-reload disabled ({reason}). Re-enable by omitting --no-hot-reload "
            f"and setting hot_reload.enabled: true (or omitting it)."
        )


if __name__ == "__main__":
    main()
