"""helao.py is a full-stack launcher for initializing API servers

Example:
  launch via 'python helao.py {config_prefix}'

  where config_prefix specifies the config/{config_prefix}.py
  contains parameters for a jointly-managed group of servers and
  server_key references the API server's unique subdictionary defined
  in config_prefix.py

See config/world.py for example.

Requirements:
  1. All API server instances must take a {config_prefix} argument
     when launched in order to reference the same configuration parameters.
     This allows server code to be reused for separate instances.

  2. All API server instances must include a {server_key} argument
     following the {config_prefix} argument. This the subdictionary
     referenced by server_key must be unique.

  3. Consequently, only class and function definitions are allowed in
     driver code, and driver configuration must be supplied during class
     initialization by an API server's @app.startup method.
"""

__all__ = []

import os
import sys
import pickle
import psutil
import time
import requests
import subprocess
from importlib import import_module

from munch import munchify
from termcolor import cprint
from pyfiglet import figlet_format
import colorama

helao_root = os.path.dirname(os.path.realpath(__file__))
confPrefix = sys.argv[1]
config = import_module(f"helao.config.{confPrefix}").config
conf = munchify(config)

import helaocore.helper
import helaocore.server

import helao.test.unit_test_sample_models
# from helao.test.unit_test_sample_models import sample_model_unit_test

colorama.init(strip=not sys.stdout.isatty()) # strip colors if stdout is redirected 

class Pidd:
    def __init__(self, pidFile, retries=3):
        self.PROC_NAMES = ["python.exe", "python"]
        self.pidFile = pidFile
        self.RETRIES = retries
        self.reqKeys = ("host", "port", "group")
        self.codeKeys = ("fast", "bokeh")
        self.d = {}
        try:
            self.load_global()
        except IOError:
            helaocore.helper.print_message({}, "launcher", f"'{pidFile}' does not exist, writing empty global dict.", info = True)
            self.write_global()
        except Exception:
            helaocore.helper.print_message({}, "launcher", f"Error loading '{pidFile}', writing empty global dict.", info = True)
            self.write_global()

    def load_global(self):
        with open(self.pidFile, "rb") as f:
            self.d = pickle.load(f)
            # helaocore.helper.print_message({}, "launcher", f"Succesfully loaded '{self.pidFile}'.")
        
    def write_global(self):
        with open(self.pidFile, "wb") as f:
            pickle.dump(self.d, f)

    def list_pids(self):
        self.load_global()
        return [(k, d["host"], d["port"], d["pid"]) for k, d in self.d.items()]

    def store_pid(self, k, host, port, pid):
        self.d[k] = {"host": host, "port": port, "pid": pid}
        self.write_global()

    def list_active(self):
        helaoPids = self.list_pids()
        # helaocore.helper.print_message({}, "launcher", helaoPids)
        running = [tup for tup in helaoPids if psutil.pid_exists(tup[3])]
        active = []
        for tup in running:
            pid = tup[3]
            port = tup[2]
            host = tup[1]
            proc = psutil.Process(pid)
            if proc.name() in self.PROC_NAMES:
                connections = [
                    c for c in proc.connections("tcp4") if c.status == "LISTEN"
                ]
                if (host, port) in [(c.laddr.ip, c.laddr.port) for c in connections]:
                    active.append(tup)
        return active

    def find_bokeh(self, host, port):
        pyPids = {
            p.pid: p.info["connections"]
            for p in psutil.process_iter(["name", "connections"])
            if p.info["name"].startswith("python")
        }
        # helaocore.helper.print_message({}, "launcher", pyPids)
        match = {pid: connections for pid, connections in pyPids.items() if connections}
        for pid, connections in match.items():
            if (host, port) in [(c.laddr.ip, c.laddr.port) for c in connections]:
                return pid
        raise Exception(f"Could not find running bokeh server at {host}:{port}")

    def kill_server(self, k):
        self.load_global()  # reload in case any servers were appended
        if k not in self.d:
            helaocore.helper.print_message({}, "launcher", f"Server '{k}' not found in pid dict.")
            return True
        else:
            active = self.list_active()
            if k not in [key for key, _, _, _ in active]:
                helaocore.helper.print_message({}, "launcher", f"Server '{k}' is not running, removing from global dict.")
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
                            helaocore.helper.print_message({}, "launcher", f"Successfully terminated server '{k}'.")
                            return True
                    if psutil.pid_exists(p.pid):
                        helaocore.helper.print_message({}, "launcher", 
                            f"Failed to terminate server '{k}' after {self.RETRIES} retries.", error = True
                        )
                        return False
                except Exception as e:
                    helaocore.helper.print_message({}, "launcher", f"Error terminating server '{k}'", error = True)
                    helaocore.helper.print_message({}, "launcher", e,error = True)
                    return False

    def close(self):
        active = self.list_active()
        helaocore.helper.print_message({}, "launcher", active)

        activeserver = [k for k, _, _, _ in active]
        KILL_ORDER = ["operator", "visualizer", "action", "orchestrator"]
        for group in KILL_ORDER:
            helaocore.helper.print_message({}, "launcher", f"Killing {group} group.")
            if group in pidd.A:
                G = pidd.A[group]
                for server in G:
                    helaocore.helper.print_message({}, "launcher", f"Killing {server}.")
                    if server in activeserver:
                        self.kill_server(server)

        # kill whats left
        active = self.list_active()
        for k, _, _, _ in self.list_active():
            self.kill_server(k)
        active = self.list_active()
        if active:
            helaocore.helper.print_message({}, "launcher", "Following actions failed to terminate:", error = True)
            for x in active:
                helaocore.helper.print_message({}, "launcher", x)
        else:
            helaocore.helper.print_message({}, "launcher", f"All actions terminated. Removing '{self.pidFile}'")
            os.remove(self.pidFile)


def validateConfig(PIDD, confDict):
    if len(confDict["servers"]) != len(set(confDict["servers"])):
        helaocore.helper.print_message({}, "launcher", "Server keys are not unique.")
        return False
    if "servers" not in confDict:
        helaocore.helper.print_message({}, "launcher", "'servers' key not defined in config dictionary.")
        return False
    for server in confDict["servers"]:
        serverDict = confDict["servers"][server]
        hasKeys = [k in serverDict for k in PIDD.reqKeys]
        hasCode = [k for k in serverDict if k in PIDD.codeKeys]
        if not all(hasKeys):
            helaocore.helper.print_message({}, "launcher", 
                f"{server} config is missing {[k for k,b in zip(PIDD.reqKeys, hasKeys) if b]}."
            )
            return False
        if not isinstance(serverDict["host"], str):
            helaocore.helper.print_message({}, "launcher", f"{server} server 'host' is not a string", error = True)
            return False
        if not isinstance(serverDict["port"], int):
            helaocore.helper.print_message({}, "launcher", f"{server} server 'port' is not an integer", error = True)
            return False
        if not isinstance(serverDict["group"], str):
            helaocore.helper.print_message({}, "launcher", f"{server} server 'group' is not a string", error = True)
            return False
        if hasCode:
            if len(hasCode) != 1:
                helaocore.helper.print_message({}, "launcher", f"{server} cannot have more than one code key {PIDD.codeKeys}", error = True)
                return False
            if not isinstance(serverDict[hasCode[0]], str):
                helaocore.helper.print_message({}, "launcher", f"{server} server '{hasCode[0]}' is not a string", error = True)
                return False
            launchPath = os.path.join(
                "helao",
                "library",
                "server",
                serverDict["group"],
                serverDict[hasCode[0]] + ".py",
            )
            if not os.path.exists(os.path.join(os.getcwd(), launchPath)):
                helaocore.helper.print_message({}, "launcher", 
                    f"{server} server code helao/library/server/{serverDict['group']}/{serverDict[hasCode[0]]+'.py'} does not exist.", 
                    error = True
                )
                return False
    serverAddrs = [f"{d['host']}:{d['port']}" for d in confDict["servers"].values()]
    if len(serverAddrs) != len(set(serverAddrs)):
        helaocore.helper.print_message({}, "launcher", "Server host:port locations are not unique.")
        return False
    return True


def wait_key():
    """ Wait for a key press on the console and return it. """
    result = None
    if os.name == "nt":
        import msvcrt

        result = msvcrt.getch()
    else:
        import termios

        fd = sys.stdin.fileno()

        oldterm = termios.tcgetattr(fd)
        newattr = termios.tcgetattr(fd)
        newattr[3] = newattr[3] & ~termios.ICANON & ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSANOW, newattr)

        try:
            result = sys.stdin.read(1)
        except IOError:
            pass
        finally:
            termios.tcsetattr(fd, termios.TCSAFLUSH, oldterm)

    return result


def launcher(confPrefix, confDict):

    # API server launch priority (matches folders in root helao-dev/)
    LAUNCH_ORDER = ["action", "orchestrator", "visualizer", "operator"]

    pidd = Pidd(f"pids_{confPrefix}.pck")
    if not validateConfig(pidd, confDict):
        helaocore.helper.print_message({}, "launcher", f"Configuration for '{confPrefix}' is invalid.", error = True)
        raise Exception(f"Configuration for '{confPrefix}' is invalid.")
    else:
        helaocore.helper.print_message({}, "launcher", f"Configuration for '{confPrefix}' is valid.")
    # get running pids
    active = pidd.list_active()
    activeKHP = [(k, h, p) for k, h, p, _ in active]
    activeHP = [(h, p) for k, h, p, _ in active]
    allGroup = {
        k: {sk: sv for sk, sv in confDict["servers"].items() if sv["group"] == k}
        for k in LAUNCH_ORDER
    }
    pidd.A = munchify(allGroup)
    pidd.orchServs = []
    for group in LAUNCH_ORDER:
        helaocore.helper.print_message({}, "launcher", f"Launching {group} group.")
        if group in pidd.A:
            G = pidd.A[group]
            for server in G:
                S = G[server]
                codeKey = [k for k in S if k in pidd.codeKeys]
                if codeKey:
                    codeKey = codeKey[0]
                    servPy = S[codeKey]
                else:
                    servPy = None
                servHost = S.host
                servPort = S.port
                servKHP = (server, servHost, servPort)
                servHP = (servHost, servPort)
                # if 'py' key is None, assume remotely started or monitored by a separate action
                if servPy is None:
                    helaocore.helper.print_message({}, "launcher", 
                        f"{server} does not specify one of ({pidd.codeKeys}) so action not be managed.",
                        info = True
                    )
                elif servKHP in activeKHP:
                    helaocore.helper.print_message({}, "launcher", 
                        f"{server} already running with pid [{active[activeKHP.index(servKHP)][3]}]",
                        info = True
                    )
                elif servHP in activeHP:
                    raise (
                        f"Cannot start {server}, {servHost}:{servPort} is already in use."
                    )
                else:
                    helaocore.helper.print_message({}, "launcher", 
                        f"Launching {server} at {servHost}:{servPort} using helao/library/server/{group}/{servPy}.py"
                    )
                    if codeKey == "fast":
                        if group == "orchestrators":
                            pidd.orchServs.append(server)
                        cmd = ["python", "fast_launcher.py", confPrefix, server]
                        p = subprocess.Popen(cmd, cwd=helao_root)
                        ppid = p.pid
                    elif codeKey == "bokeh":
                        cmd = ["python", "bokeh_launcher.py", confPrefix, server]
                        p = subprocess.Popen(cmd, cwd=helao_root)
                        try:
                            time.sleep(3)
                            ppid = pidd.find_bokeh(servHost, servPort)
                        except:
                            helaocore.helper.print_message({}, "launcher", 
                                f"Could not find running bokeh server at {servHost}:{servPort}",
                                error = True
                            )
                            helaocore.helper.print_message({}, "launcher", 
                                "Unable to manage bokeh action. See bokeh output for correct PID.",
                                error = True
                            )
                            ppid = p.pid
                    else:
                        helaocore.helper.print_message({}, "launcher", 
                            f"No launch method available for code type '{codeKey}', cannot launch {group}/{servPy}.py"
                        )
                        continue
                    pidd.store_pid(server, servHost, servPort, ppid)
        if group != LAUNCH_ORDER[-1]:
            time.sleep(3)
    return pidd


# def main():
if __name__ == "__main__":
    if not helao.test.unit_test_sample_models.sample_model_unit_test():
        quit()
    # print("\x1b[2J") # clear screen
    cprint(figlet_format(f"HELAO\nV2.1\n{helaocore.server.hlo_version}", font="starwars"),"yellow", "on_red", attrs=["bold"])
    pidd = launcher(confPrefix, config)
    result = None
    while result not in [b"\x18", b"\x04"]:
        helaocore.helper.print_message({}, "launcher", "CTRL-x to terminate action group. CTRL-d to disconnect.")
        result = wait_key()
    if result == b"\x18":
        for server in pidd.orchServs:
            try:
                helaocore.helper.print_message({}, "launcher", f"Unsubscribing {server} websockets.")
                S = pidd.A["orchestrators"][server]
                requests.post(f"http://{S.host}:{S.port}/shutdown")
            except Exception as e:
                helaocore.helper.print_message({}, "launcher", " ... got error: ", e, error = True)
        # in case a /shutdown is added to other FastAPI servers (not the shutdown without '/')
        # KILL_ORDER = ["visualizer", "action", "server"] # orch are killed above
        # no /shutdown in visualizers
        KILL_ORDER = ["action", "server"]  # orch are killed above
        for group in KILL_ORDER:
            helaocore.helper.print_message({}, "launcher", f"Shutting down {group} group.")
            if group in pidd.A:
                G = pidd.A[group]
                for server in G:
                    try:
                        helaocore.helper.print_message({}, "launcher", f"Shutting down {server}.")
                        S = G[server]
                        # will produce a 404 if not found
                        requests.post(f"http://{S.host}:{S.port}/shutdown")
                    except Exception as e:
                        helaocore.helper.print_message({}, "launcher", " ... got error: ", e, error = True)

        pidd.close()
    else:
        helaocore.helper.print_message({}, "launcher", 
            f"Disconnecting action monitor. Launch 'python helao.py {confPrefix}' to reconnect."
        )

# main()
