"""Tests for the Windows orphan checker's parsers.

The point of these: ``launch_orphan_win.bat`` can only be *run* at a Windows
station, so its judgement lives in :mod:`helao.core.tests.win_orphan_check` and
is tested here instead. Fixtures are shaped like real ``wmic`` and ``netstat``
output, including the two details that break a naive parser -- a pid that is the
*last* number on a line already containing a port, and a port number that is a
prefix of another.
"""

from typing import Final

from helao.core.tests.win_orphan_check import (
    listening_ports,
    orphan_report,
    surviving_launchers,
)

# `wmic process get CommandLine,ProcessId` output. Command line first, pid last,
# which is why the pid is read as the trailing number and not the first one.
WMIC_WITH_ORPHANS: Final[
    str
] = """CommandLine                                                        ProcessId
python.exe -u fast_launcher.py golden SIM                           7412
python.exe -u bokeh_launcher.py golden OPERATOR                     7480
C:\\Windows\\explorer.exe                                            3120
python.exe launch.py golden                                        7008
"""

WMIC_CLEAN: Final[
    str
] = """CommandLine                                                        ProcessId
C:\\Windows\\explorer.exe                                            3120
python.exe -m pytest                                                9001
"""

# `netstat -ano`. 50010 is present on purpose: a ":5001" substring match would
# report port 5001 as still held when only 50010 is.
NETSTAT_HOLDING: Final[str] = """Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    127.0.0.1:5001         0.0.0.0:0              LISTENING       7480
  TCP    127.0.0.1:50010        0.0.0.0:0              LISTENING       6001
  TCP    127.0.0.1:9999         127.0.0.1:5002         ESTABLISHED     4242
"""

NETSTAT_CLEAR: Final[str] = """Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    127.0.0.1:50010        0.0.0.0:0              LISTENING       6001
"""


def test_surviving_launchers_reads_the_pid_as_the_trailing_number() -> None:
    """The pid is the last number on the line, not the first.

    ``wmic`` puts the command line first, and that command line contains digits
    of its own (a config name, a server key, a port in some invocations). Taking
    the first number would report a nonsense pid that ``taskkill`` then fails on
    with a confusing error.
    """
    found = surviving_launchers(WMIC_WITH_ORPHANS)
    assert [pid for pid, _ in found] == [7412, 7480]


def test_surviving_launchers_ignores_the_monitor_and_unrelated_processes() -> None:
    """Only the child launcher scripts count.

    ``launch.py`` itself is not in ``LAUNCHER_SCRIPTS``: the smoke test kills the
    monitor deliberately, so finding it would be reporting the thing under test
    as a failure.
    """
    lines = [cmd for _, cmd in surviving_launchers(WMIC_WITH_ORPHANS)]
    assert not any("launch.py golden" in line for line in lines)
    assert not any("explorer" in line for line in lines)


def test_surviving_launchers_is_empty_on_a_clean_teardown() -> None:
    assert surviving_launchers(WMIC_CLEAN) == []


def test_config_prefix_scopes_the_match() -> None:
    """A group for a different config must not fail this check.

    Stations do run more than one group, and the smoke test should only judge
    the one it launched.
    """
    assert surviving_launchers(WMIC_WITH_ORPHANS, config_prefix="golden")
    assert surviving_launchers(WMIC_WITH_ORPHANS, config_prefix="clad") == []


def test_listening_ports_does_not_match_a_longer_port() -> None:
    """``:5001`` must not match ``:50010``.

    The failure this prevents is the worse direction: a check that reports a
    port as held when it is free turns a passing smoke test into a mystery.
    """
    assert listening_ports(NETSTAT_HOLDING, [5001]) == [5001]
    assert listening_ports(NETSTAT_CLEAR, [5001]) == []


def test_listening_ports_ignores_a_port_seen_only_as_a_remote_address() -> None:
    """5002 appears as a foreign address on an ESTABLISHED row, not a listener."""
    assert listening_ports(NETSTAT_HOLDING, [5002]) == []


def test_listening_ports_preserves_the_requested_order_without_duplicates() -> None:
    held = listening_ports(NETSTAT_HOLDING + NETSTAT_HOLDING, [5003, 5001])
    assert held == [5001]


def test_orphan_report_is_empty_when_everything_shut_down() -> None:
    """Empty string is the success signal the CLI turns into exit 0."""
    assert orphan_report(WMIC_CLEAN, NETSTAT_CLEAR, [5001, 5002, 5003]) == ""


def test_orphan_report_names_every_survivor_and_points_at_the_cause() -> None:
    """A failure has to be actionable at a station, not just true.

    Whoever reads this is standing at an instrument PC, so the report names the
    surviving pids, the held ports, and the two log lines that explain why the
    job object did not contain them.
    """
    report = orphan_report(WMIC_WITH_ORPHANS, NETSTAT_HOLDING, [5001], "golden")
    assert "7412" in report and "7480" in report
    assert "port 5001 still LISTENING" in report
    assert "win_job" in report
    assert "AssignProcessToJobObject failed" in report
