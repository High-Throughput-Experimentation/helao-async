"""Targeted coverage tests for support/ modules.

Closes the per-module >=90% coverage bar for the support layer by exercising
branches not hit by the focused functional tests: version git-hash helpers,
time_utils NTP read/write, and helao_logging webhook/email/formatter paths.
No real network: subprocess and requests/SMTP are monkeypatched.
"""
import logging
import os
import subprocess

import pytest

from helao.framework.support import version, time_utils
from helao.framework.support import helao_logging as helao_log


# ---------------- version.py ----------------


def test_get_branch_commithash_returns_tuple():
    branch, commit = version.get_branch_commithash()
    assert isinstance(branch, str)
    assert isinstance(commit, str)


def test_get_branch_commithash_failure(monkeypatch):
    def _boom(*a, **k):
        raise subprocess.CalledProcessError(1, "git")

    monkeypatch.setattr(version.subprocess, "check_output", _boom)
    assert version.get_branch_commithash() == ("", "")


def test_get_filehash_success(monkeypatch):
    monkeypatch.setattr(
        version.subprocess, "check_output", lambda *a, **k: b"abc1234\n"
    )
    assert version.get_filehash(__file__) == "abc1234"


def test_get_filehash_empty_response(monkeypatch):
    monkeypatch.setattr(version.subprocess, "check_output", lambda *a, **k: b"\n")
    assert version.get_filehash(__file__) == ""


def test_get_filehash_failure(monkeypatch):
    def _boom(*a, **k):
        raise OSError("no git")

    monkeypatch.setattr(version.subprocess, "check_output", _boom)
    assert version.get_filehash(__file__) == ""


def test_get_hlo_version_uses_commithash(monkeypatch):
    monkeypatch.setattr(version, "get_branch_commithash", lambda: ("main", "deadbee"))
    assert version.get_hlo_version() == "deadbee"


def test_get_hlo_version_fallback(monkeypatch):
    def _boom():
        raise RuntimeError("nope")

    monkeypatch.setattr(version, "get_branch_commithash", _boom)
    out = version.get_hlo_version()
    assert "_" in out


def test_get_caller_filehash(monkeypatch):
    monkeypatch.setattr(version, "get_filehash", lambda f: "cafef00")
    h, fname = version.get_caller_filehash()
    assert h == "cafef00"
    assert fname.endswith(".py")


def test_get_caller_filehash_failure(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError

    monkeypatch.setattr(version.inspect, "stack", _boom)
    assert version.get_caller_filehash() == ("", "")


def test_get_object_filehash(monkeypatch):
    monkeypatch.setattr(version, "get_filehash", lambda f: "beadfed")
    h, fname = version.get_object_filehash(test_get_object_filehash)
    assert h == "beadfed"


def test_get_object_filehash_failure():
    # builtins have no source file -> getabsfile raises
    assert version.get_object_filehash(len) == ("", "")


# ---------------- time_utils.py ----------------


def test_gen_uuid_variants():
    from datetime import datetime
    import uuid as uuidmod

    assert isinstance(time_utils.gen_uuid(), uuidmod.UUID)
    assert isinstance(time_utils.gen_uuid(123), uuidmod.UUID)
    assert isinstance(time_utils.gen_uuid(datetime.now()), uuidmod.UUID)
    det = time_utils.gen_uuid("seed")
    assert det == time_utils.gen_uuid("seed")


def test_md5_string():
    import uuid as uuidmod

    assert isinstance(time_utils.md5_string("hi"), uuidmod.UUID)


def test_set_time_offset_shifts():
    base = time_utils.set_time(0)
    shifted = time_utils.set_time(3600)
    assert (shifted - base).total_seconds() >= 3500


class _FakeNtpResponse:
    orig_time = 1700000000.0
    offset = 1.25
    tx_timestamp = 1700000001.0


def test_get_ntp_time_success(tmp_path, monkeypatch):
    out = tmp_path / "ntp.txt"

    class _Client:
        def request(self, server, version=3):
            return _FakeNtpResponse()

    monkeypatch.setattr(time_utils.ntplib, "NTPClient", _Client)
    time_utils.get_ntp_time("pool.example", str(out))
    last, off = out.read_text().split(",")
    assert float(off) == 1.25


def test_get_ntp_time_timeout_fallback(tmp_path, monkeypatch):
    out = tmp_path / "ntp.txt"

    class _Client:
        def request(self, server, version=3):
            raise time_utils.ntplib.NTPException("timeout")

    monkeypatch.setattr(time_utils.ntplib, "NTPClient", _Client)
    time_utils.get_ntp_time("pool.example", str(out))
    _, off = out.read_text().split(",")
    assert float(off) == 0.0


def test_read_saved_offset(tmp_path):
    p = tmp_path / "ntpLastSync.txt"
    p.write_text("1700000000.0,2.5")
    last, off = time_utils.read_saved_offset(str(p))
    assert off == 2.5


def test_read_saved_offset_malformed_returns_none(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text("only_one_field")
    assert time_utils.read_saved_offset(str(p)) is None


# ---------------- helao_logging.py ----------------


def test_http_post_handler_emits(monkeypatch):
    sent = {}

    def _post(url, json=None, headers=None, timeout=None):
        sent["url"] = url
        sent["json"] = json

    monkeypatch.setattr(helao_log.requests, "post", _post)
    handler = helao_log.HTTPPostHandler(url="http://hook.example", channel="x")
    record = logging.LogRecord(
        name="t", level=helao_log.ALERT_LEVEL, pathname=__file__, lineno=1,
        msg="boom", args=(), exc_info=None,
    )
    handler.emit(record)
    assert sent["url"] == "http://hook.example"
    assert sent["json"]["channel"] == "x"
    assert "boom" in sent["json"]["text"]


def test_http_post_handler_handles_error(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(helao_log.requests, "post", _boom)
    handled = {}
    handler = helao_log.HTTPPostHandler(url="http://hook.example")
    monkeypatch.setattr(handler, "handleError", lambda rec: handled.setdefault("hit", True))
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname=__file__, lineno=1,
        msg="m", args=(), exc_info=None,
    )
    handler.emit(record)
    assert handled.get("hit") is True


def test_make_logger_enables_email_alerts(tmp_path, monkeypatch):
    # No real SMTP connection: TitledSMTPHandler is constructed only.
    logger = helao_log.make_logger(
        logger_name="fw_email_logger",
        log_dir=str(tmp_path),
        email_config={
            "mailhost": "localhost",
            "mailport": 25,
            "fromaddr": "a@b.c",
            "username": "u",
            "password": "p",
            "recipients": ["d@e.f"],
            "email_interval": 0,
        },
    )
    assert any(
        h.__class__.__name__ == "QueueHandler" for h in logger.handlers
    )


def test_make_logger_enables_webhook_alerts(tmp_path):
    logger = helao_log.make_logger(
        logger_name="fw_webhook_logger",
        log_dir=str(tmp_path),
        email_config={"webhook": "http://hook.example", "payload": {"channel": "x"}},
    )
    assert any(h.__class__.__name__ == "QueueHandler" for h in logger.handlers)


def test_make_logger_debug_console(tmp_path):
    logger = helao_log.make_logger(
        logger_name="fw_dbg_logger",
        log_dir=str(tmp_path),
        show_debug_console=True,
    )
    stream_handlers = [
        h for h in logger.handlers if h.__class__ is logging.StreamHandler
    ]
    assert any(h.level == 10 for h in stream_handlers)


def test_make_logger_oserror_redirect(tmp_path, monkeypatch):
    # First TimedRotatingFileHandler construction raises OSError -> redirect path.
    real_ctor = helao_log.TimedRotatingFileHandler
    calls = {"n": 0}

    def _ctor(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("read-only fs")
        return real_ctor(*args, **kwargs)

    monkeypatch.setattr(helao_log, "TimedRotatingFileHandler", _ctor)
    logger = helao_log.make_logger(logger_name="fw_oserr_logger", log_dir=str(tmp_path))
    assert isinstance(logger, logging.Logger)
    assert calls["n"] >= 2


def test_ntp_formatter_use_utc_and_default_datefmt():
    fmt = helao_log.NtpOffsetFormatter(
        "%(asctime)s | %(message)s", offset_seconds=0, use_utc=True
    )
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname=__file__, lineno=1,
        msg="m", args=(), exc_info=None,
    )
    # no datefmt -> exercises default_msec_format branch
    assert isinstance(fmt.formatTime(record), str)


def test_colored_formatter_use_utc_default_datefmt():
    cfmt = helao_log.ColoredNtpOffsetFormatter(
        "%(message)s", offset_seconds=0, use_utc=True, log_colors={"INFO": "white"}
    )
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname=__file__, lineno=1,
        msg="m", args=(), exc_info=None,
    )
    assert isinstance(cfmt.formatTime(record), str)


def test_print_message_default_and_warn_alias(tmp_path):
    logger = helao_log.make_logger(logger_name="fw_pm2_logger", log_dir=str(tmp_path))

    class _Cap(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.records = []

        def emit(self, record):
            self.records.append(record)

    cap = _Cap()
    logger.addHandler(cap)
    try:
        helao_log.print_message(logger, "srv", "plain")  # default -> info
        helao_log.print_message(logger, "srv", "warned", warn=True)
    finally:
        logger.removeHandler(cap)
    assert cap.records[0].levelno == logging.INFO
    assert cap.records[1].levelno == logging.WARNING
