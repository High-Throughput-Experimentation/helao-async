"""Decide whether a Windows launch left orphaned servers behind.

The judgement half of ``helao/hexagon/tests/smoke/launch_orphan_win.bat``. It
lives here, in Python, for the reason every Windows-only check in this repo does:
a ``.bat`` cannot be run or tested on the Linux development machine, so anything
resembling a decision goes in a module that can be, leaving the batch file to do
nothing but collect evidence and shell out.

Reads ``tasklist`` and ``netstat`` output from files rather than running them, so
the parsers are exercised on Linux against captured fixtures
(``test_win_orphan_check.py``) and the batch file stays a thin driver.

Usage, from the batch file after it force-kills the launcher::

    python -m helao.core.tests.win_orphan_check tasklist.csv netstat.txt 5001 5002

Exits 0 when nothing survived, 1 when anything did -- so the ``.bat`` can gate
on ``errorlevel`` without parsing anything itself.
"""

import re
import sys

__all__ = [
    "LAUNCHER_SCRIPTS",
    "listening_ports",
    "orphan_report",
    "surviving_launchers",
]

#: The child launcher scripts a managed server runs under. Mirrors
#: ``launch.Pidd.LAUNCHER_SCRIPTS``; kept as its own copy because this module is
#: a diagnostic that must not import ``launch`` (importing it pulls in the whole
#: launcher, psutil and the config loader, on a station where the point is to run
#: a check *after* something went wrong).
LAUNCHER_SCRIPTS = ("fast_launcher.py", "bokeh_launcher.py", "reflex_launcher.py")


def surviving_launchers(tasklist_csv: str, config_prefix: str = "") -> list[tuple]:
    """Return ``[(pid, command_line), ...]`` for launcher processes still alive.

    Args:
        tasklist_csv: Contents of ``tasklist /FO CSV /V`` (or ``wmic``-style
            output with a command-line column). Matching is done on the whole
            line, because ``tasklist`` alone reports the image name as
            ``python.exe`` for every server -- the script name only appears when
            the command line is included, which is why the batch file captures it
            with ``wmic process get ProcessId,CommandLine``.
        config_prefix: When given, only processes whose command line also names
            this config count. Lets the check run on a machine where an
            *unrelated* group is legitimately running.

    Returns:
        list[tuple[int, str]]: Surviving launcher processes, pid first.
    """
    found: list[tuple] = []
    for line in tasklist_csv.splitlines():
        if not any(script in line for script in LAUNCHER_SCRIPTS):
            continue
        if config_prefix and config_prefix not in line:
            continue
        pids = re.findall(r"\b(\d{2,})\b", line)
        # The pid is the trailing column of `wmic process get CommandLine,ProcessId`
        # and a quoted field in tasklist CSV; either way it is the last number on
        # the line, and a port number earlier in the line must not be mistaken
        # for it.
        pid = int(pids[-1]) if pids else -1
        found.append((pid, line.strip()))
    return found


def listening_ports(netstat_txt: str, ports) -> list[int]:
    """Return which of ``ports`` are still in LISTENING state.

    Args:
        netstat_txt: Contents of ``netstat -ano``.
        ports: Ports the launched group should have released.

    Returns:
        list[int]: Still-listening ports, in the order given.
    """
    wanted = [int(p) for p in ports]
    held: list[int] = []
    for line in netstat_txt.splitlines():
        if "LISTENING" not in line.upper():
            continue
        # Match ":<port>" followed by whitespace so :5001 does not also match
        # :50010, and an ephemeral remote address is never read as a local port.
        for port in wanted:
            if port in held:
                continue
            if re.search(rf":{port}\s", line):
                held.append(port)
    return [p for p in wanted if p in held]


def orphan_report(tasklist_csv: str, netstat_txt: str, ports, config_prefix="") -> str:
    """Return a human-readable verdict, empty when the teardown was clean.

    Args:
        tasklist_csv: Process listing including command lines.
        netstat_txt: ``netstat -ano`` output.
        ports: Ports the group should have released.
        config_prefix: Restrict the process match to one config.

    Returns:
        str: Empty string on success; otherwise every finding, one per line.
    """
    procs = surviving_launchers(tasklist_csv, config_prefix)
    held = listening_ports(netstat_txt, ports)
    if not procs and not held:
        return ""
    lines = ["ORPHANS SURVIVED the launcher being force-killed:"]
    for pid, cmd in procs:
        lines.append(f"    pid {pid}  {cmd[:120]}")
    for port in held:
        lines.append(f"    port {port} still LISTENING")
    lines.append("")
    lines.append(
        "On Windows the job object (helao.helpers.win_job) is what should have "
        "terminated these. Check the launcher log for "
        "'AssignProcessToJobObject failed' or 'CreateJobObjectW failed'."
    )
    return "\n".join(lines)


def main(argv) -> int:
    """CLI entry point. See the module docstring for the argument order."""
    if len(argv) < 3:
        print(
            "usage: python -m helao.core.tests.win_orphan_check "
            "<tasklist.csv> <netstat.txt> <port> [port ...] [--prefix NAME]",
            file=sys.stderr,
        )
        return 2
    prefix = ""
    args = list(argv)
    if "--prefix" in args:
        i = args.index("--prefix")
        prefix = args[i + 1]
        del args[i : i + 2]
    tasklist_path, netstat_path, *ports = args
    with open(tasklist_path, errors="replace") as fh:
        tasklist_csv = fh.read()
    with open(netstat_path, errors="replace") as fh:
        netstat_txt = fh.read()
    report = orphan_report(tasklist_csv, netstat_txt, ports, prefix)
    if report:
        print(report)
        return 1
    print("clean: no launcher processes survive and every port was released.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
