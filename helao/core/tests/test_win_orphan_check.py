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
    MIN_PROCESS_LINES,
    evidence_is_usable,
    listening_ports,
    orphan_report,
    surviving_launchers,
)

# `wmic process get CommandLine,ProcessId` / PowerShell CIM output. Command line
# first, pid last, which is why the pid is read as the trailing number.
#
# Padded with filler processes so both fixtures clear MIN_PROCESS_LINES: a real
# enumeration lists dozens, and a fixture short enough to be mistaken for a failed
# capture would exercise the usability guard instead of the parser.
_FILLER: Final[str] = "\n".join(
    f"C:\\Windows\\System32\\svchost.exe -k netsvcs  {900 + i}" for i in range(20)
)

WMIC_WITH_ORPHANS: Final[str] = (
    "CommandLine                                          ProcessId\n"
    "python.exe -u fast_launcher.py golden SIM             7412\n"
    "python.exe -u bokeh_launcher.py golden OPERATOR       7480\n"
    "C:\\Windows\\explorer.exe                              3120\n"
    "python.exe launch.py golden                           7008\n" + _FILLER + "\n"
)

WMIC_CLEAN: Final[str] = (
    "CommandLine                                          ProcessId\n"
    "C:\\Windows\\explorer.exe                              3120\n"
    "python.exe -m pytest                                  9001\n" + _FILLER + "\n"
)

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


def test_a_failed_capture_is_reported_as_unusable_not_clean() -> None:
    """A short listing must never read as a clean teardown.

    ``wmic`` is absent on current Windows builds and writes nothing or a bare
    header, and "found no launchers" in an empty file is indistinguishable from
    "no launchers survived". The checker refuses to judge instead, and says how
    many lines it actually got so the next reader is not left guessing.
    """
    for unusable in ("", "\n", "CommandLine  ProcessId\n", "ERROR: bad command\n"):
        report = orphan_report(unusable, NETSTAT_CLEAR, [5001])
        assert report, f"a failed capture must not pass: {unusable!r}"
        assert "CANNOT JUDGE" in report
        assert "wmic" in report
        assert "says nothing about containment" in report


def test_a_listing_with_no_python_at_all_is_still_usable() -> None:
    """Zero python processes is a legitimate SUCCESS state, not broken evidence.

    Pins the mistake this replaced. The guard used to require the listing to name
    ``python``, on the reasoning that the checker is itself run as ``python -m``
    moments later -- but the snapshot is taken *before* this process starts. So on
    a station where the job object killed every server and nothing else was
    running python, the listing correctly held none, and the guard turned a PASS
    into "CANNOT JUDGE". Both stations hit exactly that.
    """
    listing = "\n".join(
        f"C:\\Windows\\System32\\svchost.exe  {900 + i}" for i in range(30)
    )
    assert "python" not in listing
    assert evidence_is_usable(listing) is True
    assert orphan_report(listing, NETSTAT_CLEAR, [5001]) == "", "this is a clean pass"


def test_evidence_usability_keys_on_the_process_count() -> None:
    """Usable above the threshold, unusable below it."""

    def listing(n):
        return "\n".join(f"proc-{i}.exe  {900 + i}" for i in range(n))

    assert evidence_is_usable(listing(MIN_PROCESS_LINES)) is True
    assert evidence_is_usable(listing(MIN_PROCESS_LINES - 1)) is False
    # Blank lines must not pad a failed capture up over the threshold.
    assert evidence_is_usable("\n" * 100) is False


def test_usable_evidence_with_orphans_still_reports_them() -> None:
    """The new guard must not swallow a real finding."""
    report = orphan_report(WMIC_WITH_ORPHANS, NETSTAT_HOLDING, [5001], "golden")
    assert "CANNOT JUDGE" not in report
    assert "7412" in report
