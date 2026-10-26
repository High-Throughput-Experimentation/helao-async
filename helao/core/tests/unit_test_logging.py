"""Unit tests for ``helao.helpers.helao_logging``.

Builds a logger in a scratch directory, exercises the custom ``ALERT``
log level (added by the module at import time), the
``NtpOffsetFormatter`` time-shift behaviour, and the ``print_message``
level-selection helper. The default logger is configured with a coloured
console handler plus a JSONL sink handler; the latter is exercised by
writing an INFO record and asserting ``<name>.jsonl`` is created.
"""

__all__ = ["logging_unit_test"]

import logging
import logging.handlers
import os
import tempfile
import traceback
from datetime import datetime
from email.message import EmailMessage

from helao.core.tests._test_utils import TestReporter
from helao.helpers import helao_logging as helao_log
from helao.helpers.log_jsonl import JsonlSinkHandler
from helao.helpers.helao_logging import (
    ALERT_LEVEL,
    EMPTY_SUBJECT_TITLE,
    MAX_SUBJECT_TITLE,
    ColoredNtpOffsetFormatter,
    NtpOffsetFormatter,
    make_logger,
    print_message,
    subject_title,
)


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
            "logger has a JSONL sink handler",
            lambda: any(isinstance(h, JsonlSinkHandler) for h in logger.handlers),
        )
        reporter.check(
            "logger has propagation disabled",
            lambda: logger.propagate is False,
        )

        # Drive an actual INFO event and confirm the log file is created.
        logger.info("hello world")
        log_path = os.path.join(tmpdir, "unit_test_logger.jsonl")
        reporter.check(
            "make_logger writes <name>.jsonl",
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

        reporter.section("alert subject lines are header-safe")
        # Email headers may not contain CR/LF; assigning one raises ValueError
        # from the email policy, which drops the alert and prints a "--- Logging
        # error ---" traceback. Multi-line messages (embedded tracebacks) hit
        # this routinely, and the "~" title branch used to pass them through.
        multiline_tilde = (
            "Sync failed for plate 10221\n"
            "Traceback (most recent call last):\n"
            "  File x ~ detail"
        )
        header_cases = {
            "single-line with ~": "Sync failed ~ detail here",
            "multi-line before ~": multiline_tilde,
            "CR before ~": "Sync failed\rmore ~ detail",
            "multi-line without ~": "Sync failed\nTraceback (most recent call last):",
            "empty message": "",
            "whitespace-only message": "   \n  ",
            "long title": "x" * (MAX_SUBJECT_TITLE * 2) + " ~ detail",
        }

        def _assignable(value: str) -> bool:
            """True when ``value`` survives assignment to a Subject header."""
            try:
                EmailMessage()["Subject"] = value
            except ValueError:
                return False
            return True

        for case_name, case_msg in header_cases.items():
            title = subject_title(case_msg)
            reporter.check(
                f"subject_title is single-line and non-empty: {case_name}",
                lambda t=title: bool(t) and "\n" not in t and "\r" not in t,
            )
            reporter.check(
                f"subject_title is header-assignable: {case_name}",
                lambda t=title: _assignable(f"ALERT - {t} on host"),
            )

        reporter.check(
            "subject_title keeps the pre-~ segment of a single-line message",
            lambda: subject_title("Sync failed ~ detail here") == "Sync failed",
        )
        reporter.check(
            "subject_title collapses interior whitespace to single spaces",
            lambda: subject_title(multiline_tilde)
            == "Sync failed for plate 10221 Traceback (most recent call last): File x",
        )
        reporter.check(
            "subject_title takes the first token when no ~ is present",
            lambda: subject_title("Sync failed\nTraceback:") == "Sync",
        )
        reporter.check(
            "subject_title substitutes a placeholder for an empty message",
            lambda: subject_title("   \n  ") == EMPTY_SUBJECT_TITLE,
        )
        reporter.check(
            "subject_title truncates an over-long title",
            lambda: len(subject_title("x" * (MAX_SUBJECT_TITLE * 2) + " ~ d"))
            == MAX_SUBJECT_TITLE + 3,
        )

        subject_handler = helao_log.TitledSMTPHandler(
            mailhost=("localhost", 25),
            fromaddr="a@b.c",
            toaddrs=["d@e.f"],
            subject="s",
        )
        multiline_record = logging.LogRecord(
            name="t",
            level=ALERT_LEVEL,
            pathname=__file__,
            lineno=1,
            msg=multiline_tilde,
            args=(),
            exc_info=None,
        )
        reporter.check(
            "_base_subject of a multi-line record is header-assignable",
            lambda: _assignable(subject_handler._base_subject(multiline_record)),
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
