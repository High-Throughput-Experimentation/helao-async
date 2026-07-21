"""Unit tests for `helao.hexagon.adapters.legacy.pal_transport.
LegacyPalTransport` (P3a-PAL slice 4).

Covers construct-disconnected (no SSH/NI-DAQ opened at construction) and
the LOCAL (subprocess/aiofiles) path, which is genuinely Linux-runnable
without any PAL hardware. The SSH/Cygwin path is station-gated (real
paramiko connection to a real host) and is not exercised here -- see the
module docstring's boundary note and the plan's slice-4 verification
recipe (`pal_canary.bat` proves the SSH path at the station).

`pytest-asyncio` is not installed in this env (see test_pal_reconciliation.
py's docstring), so async bodies run via `asyncio.run(...)` from plain
`def test_*` wrappers.
"""

import asyncio
import sys

from helao.core.error import ErrorCodes
from helao.hexagon.adapters.legacy.pal_transport import LegacyPalTransport
from helao.hexagon.ports.pal_transport import PalTransportPort


def test_is_pal_transport_port():
    assert isinstance(LegacyPalTransport(host=None), PalTransportPort)


def test_construct_disconnected_no_host():
    # construction never opens SSH/subprocess -- just stores values
    transport = LegacyPalTransport(host=None, user="u", key="k")
    assert transport.host is None


def test_construct_disconnected_does_not_import_paramiko():
    # paramiko is only ever imported inside _ssh_connect; constructing (and
    # exercising the local/None-host paths) must never trigger it.
    was_loaded = "paramiko" in sys.modules
    LegacyPalTransport(host="localhost")
    if not was_loaded:
        assert "paramiko" not in sys.modules


def test_host_property_reflects_construction():
    assert LegacyPalTransport(host="localhost").host == "localhost"
    assert LegacyPalTransport(host="palhost.example").host == "palhost.example"
    assert LegacyPalTransport(host=None).host is None


def test_kill_with_no_host_is_noop():
    async def _run():
        transport = LegacyPalTransport(host=None)
        error = await transport.kill()
        assert error is ErrorCodes.none

    asyncio.run(_run())


def test_reap_local_process_noop_when_none():
    async def _run():
        transport = LegacyPalTransport(host="localhost")
        await transport.reap_local_process()  # must not raise

    asyncio.run(_run())


def test_ensure_aux_logfile_local_writes_header(tmp_path):
    async def _run():
        transport = LegacyPalTransport(host="localhost")
        # pre-create the parent dir -- matches how this is always exercised
        # at the station (see test_ensure_aux_logfile_local_missing_dir_
        # hits_preexisting_bug below for the case where it doesn't exist).
        sub = tmp_path / "sub"
        sub.mkdir()
        aux_path = str(sub / "AUX__PAL__log.txt")
        header = "Date\tMethod\tTool\r\n"

        error = await transport.ensure_aux_logfile(aux_path, header)

        assert error is ErrorCodes.none
        with open(aux_path, "r", newline="") as f:
            assert f.read() == header

    asyncio.run(_run())


def test_ensure_aux_logfile_local_missing_dir_hits_preexisting_bug(tmp_path):
    """Locks in a genuine pre-existing bug discovered while writing this
    slice's tests (not fixed here, per the port-lift's preserve-verbatim
    mandate -- see the adapter's inline NOTE): `os.makedirs(..., cwd=...)`
    is not a valid call (`makedirs` has no `cwd` kwarg), so this path
    raises `TypeError` whenever the aux-log parent directory doesn't
    already exist. Apparently never hit at the station because that
    directory is always pre-created there."""

    async def _run():
        transport = LegacyPalTransport(host="localhost")
        aux_path = str(tmp_path / "not_yet_created" / "AUX__PAL__log.txt")

        try:
            await transport.ensure_aux_logfile(aux_path, "header\r\n")
            raised = False
        except TypeError:
            raised = True

        assert raised, (
            "expected the pre-existing os.makedirs(cwd=...) bug to raise "
            "TypeError -- if this now passes, the bug was fixed upstream "
            "and this test (and the adapter's NOTE) should be updated"
        )

    asyncio.run(_run())


def test_submit_joblist_local_dispatches_and_reap_waits():
    async def _run():
        transport = LegacyPalTransport(host="localhost")
        joblist = [("true.cam", "LS1;100;src;dst")]

        error = await transport.submit_joblist(joblist)

        assert error is ErrorCodes.none
        assert transport._pal_pid is not None

        await transport.reap_local_process()
        assert transport._pal_pid is None

    asyncio.run(_run())


def test_submit_joblist_no_host_is_noop():
    async def _run():
        transport = LegacyPalTransport(host=None)
        error = await transport.submit_joblist([("m.cam", "p")])
        assert error is ErrorCodes.none
        assert transport._pal_pid is None

    asyncio.run(_run())


def test_ensure_aux_logfile_no_host_is_noop(tmp_path):
    async def _run():
        transport = LegacyPalTransport(host=None)
        error = await transport.ensure_aux_logfile(
            str(tmp_path / "AUX__PAL__log.txt"), "header\r\n"
        )
        assert error is ErrorCodes.none
        assert not (tmp_path / "AUX__PAL__log.txt").exists()

    asyncio.run(_run())
