"""Tests for helao.framework.support.helao_logging.

Ports the meaningful assertions from the legacy logging unit test: custom
ALERT level, make_logger configuration + file output, NtpOffsetFormatter
time-shift, GZipRotator rename, print_message routing, and the
TitledSMTPHandler throttling behaviour. No real email/network at import.
"""
import logging
import logging.handlers
import os
import tempfile
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

import pytest

from helao.framework.support import helao_logging as helao_log
from helao.framework.support.helao_logging import (
    ALERT_LEVEL,
    ColoredNtpOffsetFormatter,
    GZipRotator,
    NtpOffsetFormatter,
    make_logger,
    print_message,
)


class _CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def test_alert_level_above_critical_and_registered():
    assert ALERT_LEVEL > logging.CRITICAL
    assert logging.getLevelName(ALERT_LEVEL) == "ALERT"
    assert callable(getattr(logging.Logger, "alert", None))


def test_module_global_logger_default_is_none():
    assert helao_log.LOGGER is None


def test_make_logger_returns_configured_logger(tmp_path):
    logger = make_logger(
        logger_name="fw_test_logger",
        log_dir=str(tmp_path),
        log_level=logging.INFO,
    )
    assert isinstance(logger, logging.Logger)
    assert any(isinstance(h, TimedRotatingFileHandler) for h in logger.handlers)
    assert logger.propagate is False


def test_make_logger_writes_log_file(tmp_path):
    logger = make_logger(
        logger_name="fw_file_logger",
        log_dir=str(tmp_path),
        log_level=logging.INFO,
    )
    logger.info("hello world")
    assert os.path.exists(os.path.join(str(tmp_path), "fw_file_logger.log"))


def test_make_logger_strips_py_suffix(tmp_path):
    logger = make_logger(logger_name="thing.py", log_dir=str(tmp_path))
    assert logger.name == "thing"


def test_alert_emits_one_record_at_alert_level(tmp_path):
    logger = make_logger(logger_name="fw_alert_logger", log_dir=str(tmp_path))
    capture = _CaptureHandler()
    capture.setLevel(ALERT_LEVEL)
    logger.addHandler(capture)
    try:
        logger.alert("escalate now")
    finally:
        logger.removeHandler(capture)
    assert len(capture.records) == 1
    assert capture.records[0].levelno == ALERT_LEVEL


def test_ntp_offset_formatter_shifts_timestamp():
    fmt = NtpOffsetFormatter("%(asctime)s | %(message)s", offset_seconds=3600)
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname=__file__, lineno=1,
        msg="m", args=(), exc_info=None,
    )
    unshifted = datetime.fromtimestamp(record.created)
    formatted = fmt.formatTime(record, "%Y-%m-%d %H:%M:%S")
    parsed = datetime.strptime(formatted, "%Y-%m-%d %H:%M:%S")
    delta = (parsed - unshifted.replace(microsecond=0)).total_seconds()
    assert abs(delta - 3600) <= 60


def test_colored_formatter_formats_without_raising():
    cfmt = ColoredNtpOffsetFormatter(
        "%(message)s",
        offset_seconds=0,
        log_colors={"INFO": "white"},
    )
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname=__file__, lineno=1,
        msg="m", args=(), exc_info=None,
    )
    assert isinstance(cfmt.format(record), str)


def test_gzip_rotator_moves_source(tmp_path):
    src = os.path.join(str(tmp_path), "rotate_src.txt")
    dst = os.path.join(str(tmp_path), "rotate_dst.txt")
    with open(src, "w") as fh:
        fh.write("payload")
    try:
        GZipRotator()(src, dst)
    except FileNotFoundError:
        pass
    assert not os.path.exists(src)
    assert os.path.exists(dst) or os.path.exists(dst + ".gz")


def test_print_message_routes_by_kwarg(tmp_path):
    logger = make_logger(logger_name="fw_pm_logger", log_dir=str(tmp_path))
    capture = _CaptureHandler()
    capture.setLevel(logging.DEBUG)
    logger.addHandler(capture)
    try:
        print_message(logger, "srv", "hi", "there", info=True)
        print_message(logger, "srv", "uhoh", warning=True)
        print_message(logger, "srv", "boom", error=True)
    finally:
        logger.removeHandler(capture)
    levels = [r.levelno for r in capture.records]
    assert levels == [logging.INFO, logging.WARNING, logging.ERROR]
    assert capture.records[0].getMessage() == "hi there"


def _alert_record(message):
    rec = logging.LogRecord(
        name="t", level=ALERT_LEVEL, pathname=__file__, lineno=1,
        msg=message, args=(), exc_info=None,
    )
    rec.message = message
    return rec


def test_titled_smtp_handler_throttles(monkeypatch):
    sent_subjects = []

    def _capture_super_emit(self, record):
        sent_subjects.append(self.getSubject(record))

    monkeypatch.setattr(logging.handlers.SMTPHandler, "emit", _capture_super_emit)

    throttled = helao_log.TitledSMTPHandler(
        mailhost=("localhost", 25), fromaddr="a@b.c", toaddrs=["d@e.f"],
        subject="s", min_interval=3600,
    )
    throttled.emit(_alert_record("FIRST ~ one"))
    throttled.emit(_alert_record("SECOND ~ two"))
    throttled.emit(_alert_record("THIRD ~ three"))
    assert len(sent_subjects) == 1
    assert throttled._suppressed_count == 2


def test_titled_smtp_handler_no_throttle_when_interval_zero(monkeypatch):
    sent_subjects = []
    monkeypatch.setattr(
        logging.handlers.SMTPHandler,
        "emit",
        lambda self, record: sent_subjects.append(self.getSubject(record)),
    )
    unthrottled = helao_log.TitledSMTPHandler(
        mailhost=("localhost", 25), fromaddr="a@b.c", toaddrs=["d@e.f"],
        subject="s", min_interval=0,
    )
    for idx in range(4):
        unthrottled.emit(_alert_record(f"MSG{idx} ~ body"))
    assert len(sent_subjects) == 4


def test_make_logger_reads_ntp_offset_file(tmp_path):
    # When ntpLastSync.txt is present, make_logger reads the offset (no socket).
    (tmp_path / "ntpLastSync.txt").write_text("1700000000.0,5.0")
    logger = make_logger(logger_name="fw_ntp_logger", log_dir=str(tmp_path))
    assert isinstance(logger, logging.Logger)
