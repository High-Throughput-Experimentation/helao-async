
"""
This module provides functionality for managing and launching HELAO servers.
Classes:
    Pidd: Manages process IDs (PIDs) for HELAO servers, including loading, storing, and terminating processes.
Functions:
    validateConfig(PIDD, confDict, helao_root): Validates the configuration dictionary for HELAO servers.
    wait_key(): Waits for a key press on the console and returns it.
    launcher(confArg, confDict, helao_root, extraopt=""): Launches HELAO servers based on the provided configuration.
    main(): Main entry point for the HELAO launcher script.
Usage:
    This script is intended to be run as a standalone launcher for HELAO servers. It validates the configuration,
    launches the servers in a specified order, and provides options for restarting or terminating servers via
    keyboard input.
Example:
    To run the launcher, use the following command:
    python helao.py <config_file> [extra_option]
    Where <config_file> is the path to the configuration file and [extra_option] is an optional argument for additional
    launch options.
Note:
    This script requires the 'click', 'termcolor', 'pyfiglet', 'colorama', 'psutil', and 'requests' libraries.
"""
__all__ = []

import os
import sys
import pickle
import psutil
import time
import requests
import subprocess
import traceback
import re
import threading
import zipfile
from glob import glob

import click
from termcolor import cprint
from pyfiglet import figlet_format
import colorama

from helaocore.version import get_hlo_version
from helao.helpers.print_message import print_message
from helao.helpers.helao_dirs import helao_dirs
from helao.helpers.config_loader import config_loader

import helao.tests.unit_test_sample_models

from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(logger_name="launcher")
else:
    LOGGER = logging.LOGGER
# from helao.tests.unit_test_sample_models import sample_model_unit_test


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
        find_bokeh(host, port):
            Finds the PID of a running Bokeh server at the given host and port.
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
        self.reqKeys = ("host", "port", "group")
        self.codeKeys = ("fast", "bokeh")
        self.d = {}
        try:
            self.load_global()
        except IOError:
            print_message(
                {},
                "launcher",
                f"'{self.pidFilePath}' does not exist, writing empty global dict.",
                info=True,
            )
            self.write_global()
        except Exception:
            print_message(
                {},
                "launcher",
                f"Error loading '{self.pidFilePath}', writing empty global dict.",
                info=True,
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
            # print_message(LOGGER, "launcher", f"Succesfully loaded '{self.pidFilePath}'.")

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
        # print_message(LOGGER, "launcher", helaoPids)
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

    def find_bokeh(self, host, port):
        """
        Find the process ID of a running Bokeh server.

        This method searches through all running Python processes and checks their
        network connections to find a process that is listening on the specified
        host and port.

        Args:
            host (str): The hostname or IP address where the Bokeh server is running.
            port (int): The port number on which the Bokeh server is listening.

        Returns:
            int: The process ID (PID) of the Bokeh server.

        Raises:
            Exception: If no running Bokeh server is found at the specified host and port.
        """
        pyPids = {
            p.pid: p.info["connections"]
            for p in psutil.process_iter(["name", "connections"])
            if p.info["name"].startswith("python")
        }
        # print_message(LOGGER, "launcher", pyPids)
        match = {pid: connections for pid, connections in pyPids.items() if connections}
        for pid, connections in match.items():
            if (host, port) in [(c.laddr.ip, c.laddr.port) for c in connections]:
                return pid
        raise Exception(f"Could not find running bokeh server at {host}:{port}")

    def kill_server(self, k):
        """
        Terminates a server process identified by the key `k`.

        This method attempts to terminate a server process by its PID. It first checks if the server
        exists in the global dictionary and if it is currently running. If the server is not running,
        it removes the server from the global dictionary. If the server is running, it tries to 
        terminate the process up to a specified number of retries.

        Args:
            k (str): The key identifying the server to be terminated.

        Returns:
            bool: True if the server was successfully terminated or not found, False if the termination failed.

        Raises:
            Exception: If an error occurs during the termination process, it logs the traceback and returns False.
        """
        self.load_global()  # reload in case any servers were appended
        if k not in self.d:
            print_message(LOGGER, "launcher", f"Server '{k}' not found in pid dict.")
            return True
        else:
            active = self.list_active()
            if k not in [key for key, _, _, _ in active]:
                print_message(
                    {},
                    "launcher",
                    f"Server '{k}' is not running, removing from global dict.",
                )
                del self.d[k]
                return True
            else:
                try:
                    p = psutil.Process(self.d[k]["pid"])
                    for _ in range(self.RETRIES):
                        # os.kill(p.pid, signal.SIGTERM)
                        p.terminate()
                        time.sleep(0.5)
                        if not psutil.pid_exists(p.pid):
                            print_message(
                                {}, "launcher", f"Successfully terminated server '{k}'."
                            )
                            return True
                    if psutil.pid_exists(p.pid):
                        print_message(
                            {},
                            "launcher",
                            f"Failed to terminate server '{k}' after {self.RETRIES} retries.",
                            error=True,
                        )
                        return False
                except Exception as e:
                    tb = "".join(
                        traceback.format_exception(type(e), e, e.__traceback__)
                    )
                    print_message(
                        {}, "launcher", f"Error terminating server '{k}'", error=True
                    )
                    print_message(LOGGER, "launcher", repr(e), tb, error=True)
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
        print_message(LOGGER, "launcher", f"active pidds: {active}")

        activeserver = [k for k, _, _, _ in active]
        KILL_ORDER = ["operator", "visualizer", "action", "orchestrator"]
        for group in KILL_ORDER:
            print_message(LOGGER, "launcher", f"Killing {group} group.")
            if group in self.servers.keys():
                G = self.servers[group]
                for server in G:
                    twait = 0.1
                    print_message(
                        {},
                        "launcher",
                        f"waiting {twait} seconds before killing server {server}",
                    )
                    time.sleep(twait)
                    print_message(LOGGER, "launcher", f"Killing {server}.")
                    if server in activeserver:
                        self.kill_server(server)

        # kill whats left
        active = self.list_active()
        for k, _, _, _ in self.list_active():
            self.kill_server(k)
        active = self.list_active()
        if active:
            print_message(
                {}, "launcher", "Following actions failed to terminate:", error=True
            )
            for x in active:
                print_message(LOGGER, "launcher", x)
        else:
            print_message(
                {}, "launcher", f"All actions terminated. Removing '{self.pidFilePath}'"
            )
        os.remove(self.pidFilePath)


def validateConfig(PIDD, confDict, helao_root):
    """
    Validates the configuration dictionary for the servers.

    Args:
        PIDD (object): An object containing required keys (`reqKeys`) and code keys (`codeKeys`).
        confDict (dict): Configuration dictionary containing server details.
        helao_root (str): Root directory path for the helao project.

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
        print_message(LOGGER, "launcher", "Server keys are not unique.")
        return False
    if "servers" not in confDict:
        print_message(LOGGER, "launcher", "'servers' key not defined in config dictionary.")
        return False
    for server in confDict["servers"]:
        serverDict = confDict["servers"][server]
        hasKeys = [k in serverDict for k in PIDD.reqKeys]
        hasCode = [k for k in serverDict if k in PIDD.codeKeys]
        if not all(hasKeys):
            print_message(
                {},
                "launcher",
                f"{server} config is missing {[k for k,b in zip(PIDD.reqKeys, hasKeys) if b]}.",
            )
            return False
        if not isinstance(serverDict["host"], str):
            print_message(
                {}, "launcher", f"{server} server 'host' is not a string", error=True
            )
            return False
        if not isinstance(serverDict["port"], int):
            print_message(
                {}, "launcher", f"{server} server 'port' is not an integer", error=True
            )
            return False
        if not isinstance(serverDict["group"], str):
            print_message(
                {}, "launcher", f"{server} server 'group' is not a string", error=True
            )
            return False
        if hasCode:
            if len(hasCode) != 1:
                print_message(
                    {},
                    "launcher",
                    f"{server} cannot have more than one code key {PIDD.codeKeys}",
                    error=True,
                )
                return False
            if not isinstance(serverDict[hasCode[0]], str):
                print_message(
                    {},
                    "launcher",
                    f"{server} server '{hasCode[0]}' is not a string",
                    error=True,
                )
                return False
            launchPath = os.path.join(
                "helao",
                "servers",
                serverDict["group"],
                serverDict[hasCode[0]] + ".py",
            )
            if not os.path.exists(os.path.join(helao_root, launchPath)):
                print_message(
                    {},
                    "launcher",
                    f"{server} server code helao/servers/{serverDict['group']}/{serverDict[hasCode[0]]+'.py'} does not exist.",
                    error=True,
                )
                return False
    serverAddrs = [f"{d['host']}:{d['port']}" for d in confDict["servers"].values()]
    if len(serverAddrs) != len(set(serverAddrs)):
        print_message(LOGGER, "launcher", "Server host:port locations are not unique.")
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


def launcher(confArg, confDict, helao_root, extraopt=""):
    """
    Launches the Helao servers based on the provided configuration.
    Args:
        confArg (str): Path to the configuration file.
        confDict (dict): Dictionary containing the configuration details.
        helao_root (str): Root directory of the Helao project.
        extraopt (str, optional): Additional options for launching. Defaults to "".
    Raises:
        Exception: If the configuration is invalid.
        Exception: If a server cannot be started due to port conflicts.
    Returns:
        Pidd: An instance of the Pidd class containing the process IDs of the launched servers.
    """
    confPrefix = os.path.basename(confArg).replace(".py", "")
    # get the BaseModel which contains all the dirs for helao
    helaodirs = helao_dirs(confDict, "launcher")

    # API server launch priority (matches folders in root helao-dev/)
    LAUNCH_ORDER = ["action", "orchestrator", "visualizer", "operator"]

    pidd = Pidd(
        pidFile=f"pids_{confPrefix}_{extraopt}.pck", pidPath=helaodirs.states_root
    )
    if not validateConfig(PIDD=pidd, confDict=confDict, helao_root=helao_root):
        print_message(
            {}, "launcher", f"Configuration for '{confPrefix}' is invalid.", error=True
        )
        raise Exception(f"Configuration for '{confPrefix}' is invalid.")
    else:
        print_message(LOGGER, "launcher", f"Configuration for '{confPrefix}' is valid.")
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
        print_message(LOGGER, "launcher", f"Launching {group} group.")
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
                    print_message(
                        {},
                        "launcher",
                        f"{server} does not specify one of ({pidd.codeKeys}) so action server will not be managed by this launcher.",
                        info=True,
                    )
                elif servKHP in activeKHP:
                    print_message(
                        {},
                        "launcher",
                        f"{server} already running with pid [{active[activeKHP.index(servKHP)][3]}]",
                        info=True,
                    )
                elif servHP in activeHP:
                    raise (
                        f"Cannot start {server}, {servHost}:{servPort} is already in use."
                    )
                else:
                    print_message(
                        {},
                        "launcher",
                        f"Launching {server} at {servHost}:{servPort} using helao/servers/{group}/{servPy}.py",
                    )
                    if codeKey == "fast":
                        if group == "orchestrator":
                            pidd.orchServs.append(server)
                        cmd = ["python", "fast_launcher.py", confArg, server]
                        p = subprocess.Popen(cmd, cwd=helao_root)
                        ppid = p.pid
                    elif codeKey == "bokeh":
                        if extraopt in ["nolive", "actionvis"] and servPy == "live_visualizer":
                            continue
                        cmd = ["python", "bokeh_launcher.py", confArg, server]
                        p = subprocess.Popen(cmd, cwd=helao_root)
                        try:
                            time.sleep(5)
                            ppid = pidd.find_bokeh(servHost, servPort)
                        except:
                            print_message(
                                {},
                                "launcher",
                                f"Could not find running bokeh server at {servHost}:{servPort}",
                                warning=True,
                            )
                            print_message(
                                {},
                                "launcher",
                                "Unable to manage bokeh action. See bokeh output for correct PID.",
                                warning=True,
                            )
                            ppid = p.pid
                    else:
                        print_message(
                            {},
                            "launcher",
                            f"No launch method available for code type '{codeKey}', cannot launch {group}/{servPy}.py",
                        )
                        continue
                    pidd.store_pid(server, servHost, servPort, ppid)
                    time.sleep(0.5)
        if group != LAUNCH_ORDER[-1]:
            time.sleep(3)
    return pidd


def main():
    """
    Main function to initialize and launch the HELAO application.
    This function performs the following tasks:
    1. Runs unit tests for sample models.
    2. Initializes colorama for colored terminal output.
    3. Checks if the script is running in the 'helao' conda environment.
    4. Validates the PYTHONPATH environment variable and retrieves paths for HELAO repositories.
    5. Loads the configuration file based on the provided argument.
    6. Clears the terminal screen and prints the HELAO banner.
    7. Displays the current branch and status of each local HELAO repository.
    8. Compresses old log files.
    9. Launches the HELAO application using the provided configuration.
    10. Sets up hotkey listeners for terminating or restarting servers.
    The function also defines helper functions for printing messages, stopping servers,
    and handling hotkey inputs for server management.
    Raises:
        SystemExit: If unit tests fail or if PYTHONPATH is not defined.
    """
    if not helao.tests.unit_test_sample_models.sample_model_unit_test():
        quit()
    colorama.init(strip=not sys.stdout.isatty())  # strip colors if stdout is redirected
    if os.environ.get("CONDA_DEFAULT_ENV") != "helao":
        print_message(
            {},
            "launcher",
            "",
            "helao.py launcher was not called from a 'helao' conda environment.",
            warning=True,
        )
    python_path = os.environ.get("PYTHONPATH")
    if python_path is None:
        print_message(LOGGER, "launcher", "", "PYTHONPATH environment var not defined.")
        quit()
    else:
        python_paths = (
            python_path.split(";")
            if sys.platform == "win32"
            else python_path.split(":")
        )
        python_paths = [os.path.abspath(x) for x in python_paths]
        python_paths = [
            x for x in python_paths if os.path.basename(x).startswith("helao-")
        ]
        print(python_paths)
        branches = {
            os.path.basename(x): subprocess.getoutput(
                f'git --git-dir={os.path.join(x, ".git")} branch --show-current'
            ).split("\n")[-1]
            for x in python_paths
        }
        print(branches)
    helao_root = os.path.dirname(os.path.realpath(__file__))
    confArg = sys.argv[1]
    config = config_loader(confArg, helao_root)
    if len(sys.argv) > 2:
        extraopt = sys.argv[2]
    else:
        extraopt = ""

    print("\x1b[2J")  # clear screen
    print("\n\n")
    cprint(
        figlet_format(
            f"HELAO\n{'dummy' if config['dummy'] else get_hlo_version().strip('Vv')}",
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

    # compress old logs:
    log_root = os.path.join(config["root"], "LOGS")
    for server_name in ["_MASTER_", "bokeh_launcher", "fast_launcher"]:
        old_log_txts = glob(os.path.join(log_root, server_name, "*.txt"))
        nots_counter = 0
        for old_log in old_log_txts:
            print_message(LOGGER, "launcher", f"Compressing: {old_log}")
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
            except:
                print_message(LOGGER, "launcher", f"Error compressing log: {old_log}")

    pidd = launcher(
        confArg=confArg, confDict=config, helao_root=helao_root, extraopt=extraopt
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
        print_message(
            {},
            "launcher",
            "CTRL-x to terminate orchestration group. CTRL-r for restart options. CTRL-d to disconnect.",
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
        print_message(LOGGER, "launcher", f"Unsubscribing {servername} websockets.")
        S = pidd.servers[groupname][servername]
        requests.post(f"http://{S['host']}:{S['port']}/shutdown")
        return S

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
                print_message(
                    {}, "launcher", f"Detected CTRL-r, checking restart options."
                )
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
                        print_message(
                            {}, "launcher", f"Got option {sind}. Restarting {sg}/{sn}."
                        )
                        try:
                            codeKey = [
                                k
                                for k in pidd.servers[sg][sn].keys()
                                if k in pidd.codeKeys
                            ][0]
                            S = stop_server(sg, sn)
                            print_message(
                                {}, "launcher", f"{sn} successful shutdown() event."
                            )
                            pidd.kill_server(sn)
                            print_message(
                                {}, "launcher", f"Successfully closed {sn} process."
                            )
                            cmd = ["python", f"{codeKey}_launcher.py", confArg, sn]
                            p = subprocess.Popen(cmd, cwd=helao_root)
                            ppid = p.pid
                            pidd.store_pid(sn, S["host"], S["port"], ppid)
                            if sg == "action":
                                for orchserv in pidd.orchServs:
                                    OS = pidd.servers["orchestrator"][orchserv]
                                    print_message(
                                        {},
                                        "launcher",
                                        f"Reregistering {sn} on {orchserv}.",
                                    )
                                    requests.post(
                                        f"http://{OS['host']}:{OS['port']}/attach_client",
                                        data={"client_servkey": sn},
                                    )
                        except Exception as e:
                            tb = "".join(
                                traceback.format_exception(type(e), e, e.__traceback__)
                            )
                            print_message(
                                {},
                                "launcher",
                                " ... got error: ",
                                repr(e),
                                tb,
                                error=True,
                            )
                        break
                    elif sind == "":
                        print_message(LOGGER, "launcher", f"Cancelling restart.")
                        break
                    else:
                        print_message(
                            {}, "launcher", f"'{sind}' is not a valid option."
                        )
                result = None
            hotkey_msg()
            result = wait_key()
        if result == "\x18":
            print_message(
                {}, "launcher", f"Detected CTRL-x, terminating orchestration group."
            )
            for server in pidd.orchServs:
                try:
                    stop_server("orchestrator", server)
                except Exception as e:
                    tb = "".join(
                        traceback.format_exception(type(e), e, e.__traceback__)
                    )
                    print_message(
                        {}, "launcher", " ... got error: ", repr(e), tb, error=True
                    )
            # in case a /shutdown is added to other FastAPI servers (not the shutdown without '/')
            # KILL_ORDER = ["visualizer", "action", "server"] # orch are killed above
            # no /shutdown in visualizers
            KILL_ORDER = ["action"]  # orch are killed above
            for group in KILL_ORDER:
                print_message(LOGGER, "launcher", f"Shutting down {group} group.")
                if group in pidd.servers.keys():
                    G = pidd.servers[group]
                    for server in G.keys():
                        try:
                            print_message(LOGGER, "launcher", f"Shutting down {server}.")
                            S = G[server]
                            # will produce a 404 if not found
                            requests.post(f"http://{S['host']}:{S['port']}/shutdown")
                        except Exception as e:
                            tb = "".join(
                                traceback.format_exception(type(e), e, e.__traceback__)
                            )
                            print_message(
                                {},
                                "launcher",
                                f" ... got error: {repr(e), tb,}",
                                error=True,
                            )
            pidd.close()
        else:
            print_message(
                {},
                "launcher",
                f"Disconnecting action monitor. Launch 'python helao.py {confArg}' to reconnect.",
            )

    x = threading.Thread(target=thread_waitforkey)
    x.start()

if __name__ == "__main__":
    main()