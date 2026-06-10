"""Unit tests for ``helao.helpers.helao_logging``.

Builds a logger in a scratch directory, exercises the custom ``ALERT``
log level (added by the module at import time), the
``NtpOffsetFormatter`` time-shift behaviour, the ``GZipRotator`` rename
hook, and the ``print_message`` level-selection helper. The default
logger is configured with a coloured console handler plus a daily
rotating file handler; the latter is exercised by writing an INFO
record and asserting the log file is created.
"""

__all__ = ["logging_unit_test"]

import logging
import logging.handlers
import os
import sys
import tempfile
import traceback
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

from helao.helpers import helao_logging as helao_log
from helao.helpers.helao_logging import (
    ALERT_LEVEL,
    ColoredNtpOffsetFormatter,
    GZipRotator,
    NtpOffsetFormatter,
    make_logger,
    print_message,
)
from helao.core.tests._test_utils import TestReporter


class _CaptureHandler(logging.Handler):
    """In-memory handler used to capture the levels of emitted records."""

    def __init__(self):
        """Initialise the empty record buffer."""
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        """Append the record to ``self.records`` without any formatting."""
        self.records.append(record)


def logging_unit_test() -> bool:
    """Run all logging-helper assertions and report pass/fail."""
    reporter = TestReporter("logging")

    try:
        reporter.section("module-level constants and custom level")
        reporter.check(
            "ALERT level numerically above CRITICAL",
            lambda: ALERT_LEVEL > logging.CRITICAL,
        )
        reporter.check(
            "logging.getLevelName(ALERT_LEVEL) == 'ALERT'",
            lambda: logging.getLevelName(ALERT_LEVEL) == "ALERT",
        )
        reporter.check(
            "Logger.alert is monkey-patched onto the global logger class",
            lambda: callable(getattr(logging.Logger, "alert", None)),
        )

        reporter.section("make_logger configures a working logger")
        tmpdir = tempfile.mkdtemp(prefix="helao_test_log_")
        logger = make_logger(
            logger_name="unit_test_logger",
            log_dir=tmpdir,
            log_level=logging.INFO,
        )
        reporter.check(
            "make_logger returns a logging.Logger",
            lambda: isinstance(logger, logging.Logger),
        )
        reporter.check(
            "logger has at least one file handler",
            lambda: any(
                isinstance(h, TimedRotatingFileHandler) for h in logger.handlers
            ),
        )
        reporter.check(
            "logger has propagation disabled",
            lambda: logger.propagate is False,
        )

        # Drive an actual INFO event and confirm the log file is created.
        logger.info("hello world")
        log_path = os.path.join(tmpdir, "unit_test_logger.log")
        reporter.check(
            "INFO event writes to the configured log file",
            lambda: os.path.exists(log_path),
        )

        reporter.section("ALERT records survive a CaptureHandler attached at ALERT")
        capture = _CaptureHandler()
        capture.setLevel(ALERT_LEVEL)
        logger.addHandler(capture)
        try:
            logger.alert("escalate now")
        finally:
            logger.removeHandler(capture)

        reporter.check(
            "Logger.alert emitted exactly one record at ALERT level",
            lambda: len(capture.records) == 1
            and capture.records[0].levelno == ALERT_LEVEL,
        )

        reporter.section("NtpOffsetFormatter shifts timestamps")
        fmt = NtpOffsetFormatter("%(asctime)s | %(message)s", offset_seconds=3600)
        record = logging.LogRecord(
            name="t",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="m",
            args=(),
            exc_info=None,
        )
        unshifted = datetime.fromtimestamp(record.created)
        formatted = fmt.formatTime(record, "%Y-%m-%d %H:%M:%S")
        parsed = datetime.strptime(formatted, "%Y-%m-%d %H:%M:%S")
        delta = (parsed - unshifted.replace(microsecond=0)).total_seconds()
        # allow tz-related drift around DST changeover; require ~1 hour offset
        reporter.check(
            "NtpOffsetFormatter applies +3600 second offset within 60 seconds",
            lambda: abs(delta - 3600) <= 60,
        )

        cfmt = ColoredNtpOffsetFormatter(
            "%(message)s",
            offset_seconds=0,
            log_colors={
                "DEBUG": "cyan",
                "INFO": "white",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "red",
                "ALERT": "purple",
            },
        )
        reporter.check(
            "ColoredNtpOffsetFormatter formats a record without raising",
            lambda: isinstance(cfmt.format(record), str),
        )

        reporter.section("GZipRotator rename behaviour")
        src = os.path.join(tmpdir, "rotate_src.txt")
        dst = os.path.join(tmpdir, "rotate_dst.txt")
        with open(src, "w") as fh:
            fh.write("payload")
        try:
            GZipRotator()(src, dst)
        except FileNotFoundError:
            # gzip not on PATH on Windows is fine; rename still happens first.
            pass

        # source should be gone whether or not gzip succeeded
        reporter.check(
            "GZipRotator moved source file off the original path",
            lambda: not os.path.exists(src),
        )
        reporter.check(
            "GZipRotator left rotated file (or gzipped variant) at dst path",
            lambda: os.path.exists(dst) or os.path.exists(dst + ".gz"),
        )

        reporter.section("print_message routes by kwarg")
        capture2 = _CaptureHandler()
        capture2.setLevel(logging.DEBUG)
        logger.addHandler(capture2)
        try:
            print_message(logger, "srv", "hi", "there", info=True)
            print_message(logger, "srv", "uhoh", warning=True)
            print_message(logger, "srv", "boom", error=True)
        finally:
            logger.removeHandler(capture2)

        levels = [r.levelno for r in capture2.records]
        reporter.check(
            "print_message emits INFO/WARNING/ERROR in that order",
            lambda: levels == [logging.INFO, logging.WARNING, logging.ERROR],
        )
        reporter.check(
            "print_message concatenates positional args with spaces",
            lambda: capture2.records[0].getMessage() == "hi there",
        )

        reporter.section("TitledSMTPHandler throttles alert emails")
        sent_subjects = []

        def _capture_super_emit(self, record):
            sent_subjects.append(self.getSubject(record))

        def _alert_record(message):
            rec = logging.LogRecord(
                name="t",
                level=ALERT_LEVEL,
                pathname=__file__,
                lineno=1,
                msg=message,
                args=(),
                exc_info=None,
            )
            # mimic QueueHandler.prepare, which sets record.message
            rec.message = message
            return rec

        throttled = helao_log.TitledSMTPHandler(
            mailhost=("localhost", 25),
            fromaddr="a@b.c",
            toaddrs=["d@e.f"],
            subject="s",
            min_interval=3600,
        )
        original_emit = logging.handlers.SMTPHandler.emit
        logging.handlers.SMTPHandler.emit = _capture_super_emit
        try:
            throttled.emit(_alert_record("FIRST ~ one"))
            throttled.emit(_alert_record("SECOND ~ two"))
            throttled.emit(_alert_record("THIRD ~ three"))
        finally:
            logging.handlers.SMTPHandler.emit = original_emit

        reporter.check(
            "only the first alert is mailed within the interval",
            lambda: len(sent_subjects) == 1,
        )
        reporter.check(
            "throttled handler counts the suppressed alerts",
            lambda: throttled._suppressed_count == 2,
        )

        unthrottled = helao_log.TitledSMTPHandler(
            mailhost=("localhost", 25),
            fromaddr="a@b.c",
            toaddrs=["d@e.f"],
            subject="s",
            min_interval=0,
        )
        sent_subjects.clear()
        logging.handlers.SMTPHandler.emit = _capture_super_emit
        try:
            for idx in range(4):
                unthrottled.emit(_alert_record(f"MSG{idx} ~ body"))
        finally:
            logging.handlers.SMTPHandler.emit = original_emit

        reporter.check(
            "min_interval=0 disables throttling (all alerts mailed)",
            lambda: len(sent_subjects) == 4,
        )

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False
