"""Logging port (spec §4.3.8, §9.1): ONE module, FAIL LOUD.

Wraps the legacy helao.helpers.helao_logging in P1b — nothing is vendored
(F3 countermeasure). Real ``helao_logging.make_logger`` today falls back to
``tempfile.mkdtemp()`` whenever ``log_dir`` is ``None`` (see
``helao/helpers/helao_logging.py:412``) — that fallback is the F3 regression
this port exists to close. The port's file-logger factory MUST raise when
asked to create a file logger without a resolved log root; the mkdtemp()
fallback is unreachable through the port. Contractual path:
<root>/LOGS/<server_key>.log.
"""

from typing import Protocol, runtime_checkable

__all__ = ["LoggingPort"]


@runtime_checkable
class LoggingPort(Protocol):
    def file_logger(self, server_key: str, log_root: str) -> object:
        """Create/return the named singleton logger writing
        <log_root>/<server_key>.log. MUST raise ValueError when log_root is
        falsy — never fall back to a tempdir (F3)."""
        ...

    def info(self, msg: str) -> None: ...

    def warning(self, msg: str) -> None: ...

    def error(self, msg: str, exc_info: bool = False) -> None: ...

    def alert(self, msg: str) -> None:
        """ALERT level 60: email/webhook queue listeners (throttled)."""
        ...
