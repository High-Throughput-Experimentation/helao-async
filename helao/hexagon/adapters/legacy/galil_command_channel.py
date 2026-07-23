"""gclib-backed GalilCommandChannel (P3a galil-3 native deepening).

The at-station adapter: wraps the Windows-only ``gclib`` runtime behind the
:class:`~helao.hexagon.ports.galil_command_channel.GalilCommandChannel` port.
``import gclib`` is lazy (inside ``open``), so this module and the native motion
driver import and construct on Linux without gclib; only ``open()`` (and the
subsequent I/O) require the vendor runtime + a reachable controller.
"""

from typing import Any, Optional

from helao.hexagon.ports.galil_command_channel import GalilChannelError

__all__ = ["GclibCommandChannel"]


class GclibCommandChannel:
    """`GalilCommandChannel` backed by ``gclib.py()`` (opened at-station)."""

    def __init__(self) -> None:
        # No gclib import / no connection here (disconnected construct).
        self._g: Optional[Any] = None
        self._command: Optional[Any] = None

    def open(self, connection_string: str) -> None:
        import gclib  # lazy: Windows/at-station only

        try:
            g = gclib.py()
            g.GOpen(connection_string)
            self._g = g
            self._command = g.GCommand
        except gclib.GclibError as exc:
            raise GalilChannelError(str(exc)) from exc

    def command(self, cmd: str) -> str:
        if self._command is None:
            raise GalilChannelError("channel not open")
        import gclib

        try:
            return self._command(cmd)
        except gclib.GclibError as exc:
            raise GalilChannelError(f"command {cmd!r} failed: {exc}") from exc

    def info(self) -> str:
        if self._g is None:
            raise GalilChannelError("channel not open")
        return self._g.GInfo()

    def version(self) -> str:
        if self._g is None:
            raise GalilChannelError("channel not open")
        return self._g.GVersion()

    def close(self) -> None:
        if self._g is None:
            return
        import gclib

        try:
            self._g.GClose()
        except gclib.GclibError:
            pass
        finally:
            self._g = None
            self._command = None
