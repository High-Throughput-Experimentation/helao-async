"""Terminate a launched goldenhex group via its pid pickle (the same
STATES/pids_<prefix>_<extraopt>.pck contract launch.py maintains)."""

import pickle
import sys
import time

import psutil


def main(root: str, prefix: str = "goldenhex") -> int:
    pck = f"{root}/STATES/pids_{prefix}_.pck"
    try:
        pidd = pickle.load(open(pck, "rb"))
    except FileNotFoundError:
        print(f"no pid pickle at {pck}; nothing to kill")
        return 0
    procs = []
    for key, entry in pidd.items():
        pid = entry.get("pid") if isinstance(entry, dict) else None
        if pid and psutil.pid_exists(pid):
            p = psutil.Process(pid)
            print(f"terminating {key} (pid {pid})")
            p.terminate()
            procs.append(p)
    _gone, alive = psutil.wait_procs(procs, timeout=10)
    for p in alive:
        print(f"SIGKILL {p.pid}")
        p.kill()
    time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "goldenhex"))
