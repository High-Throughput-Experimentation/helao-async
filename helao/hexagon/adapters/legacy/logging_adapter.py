"""LoggingPort adapter (spec §9.1, F3): ONE module, FAIL LOUD.

Wraps legacy helao.helpers.helao_logging -- nothing is vendored. The two
legacy tempdir traps (make_logger(log_dir=None) -> mkdtemp(); OSError ->
mkdtemp()) are unreachable through this port: file_logger RAISES on a falsy
log root. Contractual path: <log_root>/<server_key>.log (flat file).
"""

from typing import Optional

from helao.helpers import helao_logging

__all__ = ["LegacyLoggingAdapter"]


class LegacyLoggingAdapter:
    def __init__(self, logger=None):
        self._logger = logger

    def _log(self):
        # call-time resolution so the launcher-installed singleton is seen
        return self._logger if self._logger is not None else helao_logging.LOGGER

    def file_logger(self, server_key: str, log_root: Optional[str]) -> object:
        if not log_root:
            raise ValueError(
                "Logging port refuses a file logger without a resolved log "
                "root (F3: the legacy mkdtemp() fallback is banned); pass "
                "<config root>/LOGS"
            )
        return helao_logging.make_logger(logger_name=server_key, log_dir=log_root)

    def info(self, msg: str) -> None:
        lg = self._log()
        if lg is not None:
            lg.info(msg)

    def warning(self, msg: str) -> None:
        lg = self._log()
        if lg is not None:
            lg.warning(msg)

    def error(self, msg: str, exc_info: bool = False) -> None:
        lg = self._log()
        if lg is not None:
            lg.error(msg, exc_info=exc_info)

    def alert(self, msg: str) -> None:
        lg = self._log()
        if lg is not None:
            # ALERT (level 60, email/webhook listeners, throttled) is added to
            # logging.Logger by helao_logging's module-level setattr; stdlib
            # type stubs don't know about it.
            lg.alert(msg)  # type: ignore[attr-defined]
