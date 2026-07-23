"""Galil command-channel port (P3a galil-3 native deepening).

The single seam between the native Galil motion logic and the Windows-only
``gclib`` runtime. Every gclib interaction in the legacy driver reduces to a
connection lifecycle plus a string command channel (``g.GCommand``); promoting
that to a port lets the motion logic (command generation, coordinate transform,
TP/PA/SC parsing) run and be unit-tested on Linux against a fake channel, with
only the real TCP I/O deferred to an at-station gclib adapter.
"""

from typing import Protocol, runtime_checkable

__all__ = ["GalilCommandChannel", "GalilChannelError"]


class GalilChannelError(Exception):
    """Transport-level failure talking to the Galil controller.

    Native adapters catch this instead of the vendor ``gclib.GclibError`` so
    the motion logic never imports gclib.
    """


@runtime_checkable
class GalilCommandChannel(Protocol):
    """String command channel to a Galil controller (the ``gclib`` seam)."""

    def open(self, connection_string: str) -> None:
        """Open the connection (legacy ``g.GOpen('<ip> --direct -s ALL')``)."""
        ...

    def command(self, cmd: str) -> str:
        """Send one command and return its raw string response (``g.GCommand``)."""
        ...

    def info(self) -> str:
        """Controller info string (legacy ``g.GInfo()``)."""
        ...

    def version(self) -> str:
        """gclib version string (legacy ``g.GVersion()``)."""
        ...

    def close(self) -> None:
        """Close the connection (legacy ``g.GClose()``); idempotent."""
        ...
