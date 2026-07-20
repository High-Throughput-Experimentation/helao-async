"""Snapshot + terminate a launched HELAO group (its pid-pickle servers PLUS the
launch.py monitor that owns the console window).

Two-phase so the PIDs are captured BEFORE a graceful ``/shutdown`` perturbs the
group and BEFORE launch.py's own ``Pidd.close()`` can remove the pickle
(launch.py:394 removes ``STATES/pids_<prefix>_.pck`` once all servers are down):

    kill_group.py <root> <prefix> --snapshot <file>   # read PIDs -> <file>, no kill
    kill_group.py --from-snapshot <file>              # terminate the snapshotted PIDs

Legacy one-shot (read pickle + kill now) still works:

    kill_group.py <root> <prefix>

Why also kill the launch.py monitor: the pickle records only the child servers,
so terminating those leaves the ``launch.py`` process (and its ``start "..."``
console window) alive. We find it by command line at snapshot time and kill it
by PID, which closes the window without the fragility of a post-hoc WMI/taskkill
command-line match.

Path-robustness: a station's launch may write the pickle under a root that
differs from the arg passed here (e.g. an extra ``\\TEST`` segment), which made
the exact ``<root>/STATES/...`` lookup miss. If the exact path is absent we glob
for ``pids_<prefix>_*.pck`` under the root and its parent.
"""

import argparse
import glob
import json
import os
import pickle
import sys
import time

import psutil


def _find_pickle(root: str, prefix: str):
    """Locate the group's pid pickle, tolerating a root/path mismatch."""
    exact = os.path.join(root, "STATES", f"pids_{prefix}_.pck")
    if os.path.exists(exact):
        return exact
    for base in (root, os.path.dirname(root.rstrip("/\\"))):
        if not base:
            continue
        hits = glob.glob(
            os.path.join(base, "**", f"pids_{prefix}_*.pck"), recursive=True
        )
        if hits:
            return sorted(hits)[0]
    return None


def _launcher_pid(prefix: str):
    """PID of the ``launch.py <prefix> --no-hot-reload`` monitor, or None."""
    needle = f"launch.py {prefix} --no-hot-reload"
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = " ".join(p.info.get("cmdline") or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if needle in cmdline:
            return p.info["pid"]
    return None


def _collect(root: str, prefix: str) -> dict:
    """Map of label -> pid for the group's servers plus its launch.py monitor."""
    pids: dict = {}
    pck = _find_pickle(root, prefix)
    if pck is None:
        print(f"no pid pickle for prefix '{prefix}' under {root}")
    else:
        try:
            pidd = pickle.load(open(pck, "rb"))
            for key, entry in pidd.items():
                pid = entry.get("pid") if isinstance(entry, dict) else None
                if pid:
                    pids[str(key)] = pid
        except Exception as exc:  # noqa: BLE001 -- best-effort teardown
            print(f"could not read {pck}: {exc}")
    launcher = _launcher_pid(prefix)
    if launcher:
        pids["__launcher__"] = launcher
    return pids


def _kill(pids: dict) -> None:
    """Terminate then SIGKILL the given pids (servers first is fine here)."""
    procs = []
    for label, pid in pids.items():
        if pid and psutil.pid_exists(pid):
            try:
                p = psutil.Process(pid)
            except psutil.NoSuchProcess:
                continue
            print(f"terminating {label} (pid {pid})")
            p.terminate()
            procs.append(p)
    _gone, alive = psutil.wait_procs(procs, timeout=10)
    for p in alive:
        print(f"SIGKILL {p.pid}")
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass
    time.sleep(1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="snapshot/kill a launched HELAO group")
    ap.add_argument("root", nargs="?")
    ap.add_argument("prefix", nargs="?", default="goldenhex")
    ap.add_argument(
        "--snapshot", help="write collected PIDs to this JSON file (no kill)"
    )
    ap.add_argument(
        "--from-snapshot", help="terminate the PIDs recorded in this JSON file"
    )
    a = ap.parse_args(argv)

    if a.from_snapshot:
        try:
            pids = json.load(open(a.from_snapshot))
        except (OSError, ValueError) as exc:
            print(f"no snapshot to kill ({a.from_snapshot}): {exc}")
            return 0
        _kill(pids)
        return 0

    if a.root is None:
        print(
            "usage: kill_group.py <root> <prefix> "
            "[--snapshot FILE | --from-snapshot FILE]"
        )
        return 2

    pids = _collect(a.root, a.prefix)
    if a.snapshot:
        with open(a.snapshot, "w") as f:
            json.dump(pids, f)
        print(f"snapshot {pids} -> {a.snapshot}")
        return 0

    if not pids:
        print(f"nothing to kill for prefix '{a.prefix}'")
        return 0
    _kill(pids)
    return 0


if __name__ == "__main__":
    sys.exit(main())
