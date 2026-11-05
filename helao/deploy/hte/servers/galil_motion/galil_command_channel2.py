"""gclib 2.x (``gclib.Controller``) implementation of the Galil command-channel port.

Same port as :mod:`galil_command_channel` (wrapper 1.0), so the motion and I/O
drivers run unchanged on either wrapper. Selected by ``gclib_api: "2"``.
``import gclib`` is lazy (inside ``open``); the module imports without gclib.
Windows or Linux, Python >= 3.12.
"""

from typing import Any, Optional

from helao.deploy.hte.servers.galil_motion.galil_command_channel_port import (
    GalilChannelError,
)

__all__ = ["Gclib2CommandChannel"]


class Gclib2CommandChannel:
    """`GalilCommandChannel` backed by ``gclib.Controller`` (wrapper 2.x)."""

    def __init__(self) -> None:
        self._c: Optional[Any] = None
        self._gclib: Optional[Any] = None

    def open(self, connection_string: str) -> None:
        import gclib  # lazy: vendor package, at-station only

        if not hasattr(gclib, "Controller"):
            raise GalilChannelError(
                "gclib_api '2' needs the 2.x wrapper (gclib.Controller); the "
                "installed gclib is wrapper 1.0 (gclib.py) - set gclib_api: '1' "
                "or install wrapper 2.x"
            )
        parts = connection_string.split()
        if not parts:
            raise GalilChannelError("empty connection string")
        try:
            # 1.0's "--direct" bypassed gcaps; 2.x does that process-wide.
            if "--direct" in parts[1:]:
                gclib.force_gcaps(False)
            self._c = gclib.Controller(parts[0])
            self._gclib = gclib
        except gclib.Error as exc:
            raise GalilChannelError(str(exc)) from exc

    def _open_controller(self) -> Any:
        if self._c is None:
            raise GalilChannelError("channel not open")
        return self._c

    def command(self, cmd: str) -> str:
        c = self._open_controller()
        try:
            return c.command(cmd)
        except self._gclib.Error as exc:
            raise GalilChannelError(f"command {cmd!r} failed: {exc}") from exc

    def download_program(self, program: str) -> None:
        c = self._open_controller()
        try:
            # 1.0 callers append a NUL terminator; set_program takes plain text.
            c.set_program(program.removesuffix("\x00"))
        except self._gclib.Error as exc:
            raise GalilChannelError(f"program download failed: {exc}") from exc

    def info(self) -> str:
        c = self._open_controller()
        # the 1.0 GInfo() shape: "<address>, <revision>, <serial>"
        return f"{c.address()}, {c.revision_information()}, {c.serial_number()}"

    def version(self) -> str:
        self._open_controller()
        return self._gclib.version()

    def close(self) -> None:
        if self._c is None:
            return
        try:
            self._c.close()
        except self._gclib.Error:
            pass
        finally:
            self._c = None
