"""Canonical logger factory shared by every HELAO server.

Adds a custom ``ALERT`` level above ``CRITICAL`` and provides ``make_logger``,
which configures a single per-server ``logging.Logger`` with a coloured
console handler, a daily ``TimedRotatingFileHandler`` that gzips rotated
files, and optional NTP-offset-aware timestamps. When credentials are
provided, ``ALERT``-level records are also fanned out to an SMTP handler
and/or a JSON HTTP POST webhook via queue listeners.

Usage::

    from helao.helpers import helao_logging as logging
    if logging.LOGGER is None:
        logger = logging.make_logger(__file__)
    logger = logging.LOGGER
"""

import copy
import tempfile
import os
import subprocess
import logging
import time
import requests
from socket import gethostname
from queue import Queue
from logging.handlers import (
    TimedRotatingFileHandler,
    SMTPHandler,
    QueueHandler,
    QueueListener,
)
from typing import Optional
from pathlib import Path

from colorlog import ColoredFormatter
from datetime import datetime, timezone, timedelta
from helao.helpers.time_utils import read_saved_offset

ALERT_LEVEL = 60
logging.addLevelName(ALERT_LEVEL, "ALERT")

# Default minimum number of seconds between two outgoing alert emails. Alert
# records that arrive while an email is still "cooling down" are suppressed
# (counted, then summarised in the next email's subject). ``0`` disables
# throttling entirely. Overridden per-deployment via the ``email_interval``
# key in the alert config referenced by ``alert_config_path``.
DEFAULT_EMAIL_INTERVAL = 600

# Default seconds over which identical consecutive file-log messages are
# collapsed into a single summary line. When a message is immediately repeated,
# further identical records are counted (not written) until a different message
# arrives or this interval elapses, at which point one summary line reporting
# the repeat count is written. ``0`` disables de-duplication and restores stock
# ``TimedRotatingFileHandler`` behaviour. Overridden per-logger via the
# ``dedup_interval`` argument to :func:`make_logger`.
DEFAULT_DEDUP_INTERVAL = 10.0


def alert(self, message, *args, **kws):
    """Log ``message`` at the custom ``ALERT`` level if enabled."""
    if self.isEnabledFor(ALERT_LEVEL):
        # Yes, logger takes its '*args' as 'args'.
        self._log(ALERT_LEVEL, message, args, **kws)


# logging.Logger.alert = alert
setattr(logging.Logger, "alert", alert)

LOGGER: logging.Logger = None
HOST = gethostname()


class GZipRotator:
    """Rotation callable that renames the rotated log file and gzips it."""

    def __call__(self, source, dest):
        """Move ``source`` to ``dest`` then spawn ``gzip`` to compress it."""
        os.rename(source, dest)
        subprocess.Popen(["gzip", dest])


class TitledSMTPHandler(SMTPHandler):
    """SMTP handler that derives a structured subject line from the record.

    Adds rate limiting so that at most one email is sent per
    ``min_interval`` seconds. Records that arrive during the cooldown window
    are dropped rather than mailed, but are counted so the next email that
    does go out can report how many alerts were suppressed in the meantime.
    The subject lines of dropped records are also buffered (up to
    ``MAX_SUPPRESSED_SUBJECTS`` lines) and appended to the body of the next
    email. Once the buffer is full further records are still counted but their
    subject lines are no longer retained.
    """

    #: Maximum number of suppressed subject lines buffered for the next email.
    MAX_SUPPRESSED_SUBJECTS = 100

    def __init__(self, *args, min_interval: float = 0, **kwargs):
        """Build the handler.

        Args:
            *args: Positional arguments forwarded to ``SMTPHandler``.
            min_interval: Minimum seconds between outgoing emails. ``0`` (the
                default) disables throttling and restores stock behaviour.
            **kwargs: Keyword arguments forwarded to ``SMTPHandler``.
        """
        super().__init__(*args, **kwargs)
        self.min_interval = min_interval
        self._last_emit_monotonic = None
        self._suppressed_count = 0
        self._suppressed_subjects = []

    def _base_subject(self, record) -> str:
        """Return ``"<LEVEL> - <title> on <HOST>"`` for ``record``."""
        message = record.getMessage()
        if "~" in message:
            title = message.split("~")[0].strip()
        else:
            title = message.split()[0].strip()
        return f"{record.levelname} - {title} on {HOST}"

    def getSubject(self, record) -> str:
        """Return ``"<LEVEL> - <title> on <HOST>"`` for ``record``.

        When alerts were suppressed by throttling since the last email, a
        ``"(+N suppressed)"`` note is appended to the subject.
        """
        subject = self._base_subject(record)
        if self._suppressed_count:
            subject += f" (+{self._suppressed_count} suppressed)"
        return subject

    def format(self, record) -> str:
        """Format ``record`` and append any buffered suppressed subject lines."""
        body = super().format(record)
        if self._suppressed_subjects:
            note_lines = [
                "",
                "",
                f"--- {self._suppressed_count} alert(s) suppressed during cooldown ---",
            ]
            note_lines.extend(self._suppressed_subjects)
            if self._suppressed_count > len(self._suppressed_subjects):
                dropped = self._suppressed_count - len(self._suppressed_subjects)
                note_lines.append(
                    f"... (+{dropped} more not shown; buffer limit "
                    f"{self.MAX_SUPPRESSED_SUBJECTS} reached)"
                )
            body = body + "\n".join(note_lines)
        return body

    def emit(self, record):
        """Send ``record`` by email unless still within the cooldown window."""
        if self.min_interval and self.min_interval > 0:
            now = time.monotonic()
            if (
                self._last_emit_monotonic is not None
                and now - self._last_emit_monotonic < self.min_interval
            ):
                self._suppressed_count += 1
                if len(self._suppressed_subjects) < self.MAX_SUPPRESSED_SUBJECTS:
                    self._suppressed_subjects.append(self._base_subject(record))
                return
            self._last_emit_monotonic = now
        super().emit(record)
        self._suppressed_count = 0
        self._suppressed_subjects = []


class DedupTimedRotatingFileHandler(TimedRotatingFileHandler):
    """Rotating file handler that collapses repeated consecutive messages.

    When the same log message — compared by raw content via
    ``record.getMessage()``, ignoring formatting — is emitted twice in a row,
    a de-duplication cooldown starts: subsequent identical messages are counted
    rather than written. The buffered repeat count is flushed as a single
    summary line when either a different message arrives or the cooldown
    interval elapses, whichever comes first. Because handlers only act on
    ``emit``, an elapsed cooldown is detected lazily on the next record; a run
    of duplicates that simply stops is summarised when the next record (of any
    kind) arrives. ``dedup_interval`` of ``0`` disables the behaviour and
    restores stock ``TimedRotatingFileHandler`` semantics.
    """

    def __init__(self, *args, dedup_interval: float = 0, **kwargs):
        """Build the handler.

        Args:
            *args: Positional arguments forwarded to
                ``TimedRotatingFileHandler``.
            dedup_interval: Seconds a run of identical consecutive messages is
                collapsed before a summary line is written. ``0`` (the default)
                disables de-duplication.
            **kwargs: Keyword arguments forwarded to
                ``TimedRotatingFileHandler``.
        """
        super().__init__(*args, **kwargs)
        self.dedup_interval = dedup_interval
        self._dedup_last_message = None
        self._dedup_record = None
        self._dedup_count = 0
        self._dedup_started = None

    def _flush_dedup(self):
        """Write a summary line for any buffered repeats and reset the window."""
        if self._dedup_count > 0 and self._dedup_record is not None:
            times = self._dedup_count
            summary = copy.copy(self._dedup_record)
            summary.msg = (
                f"{self._dedup_record.getMessage()} "
                f"[previous message repeated {times} "
                f"time{'s' if times != 1 else ''}]"
            )
            summary.args = None
            super().emit(summary)
        self._dedup_count = 0
        self._dedup_started = None

    def emit(self, record):
        """Write ``record`` unless it is a suppressed consecutive duplicate."""
        if not (self.dedup_interval and self.dedup_interval > 0):
            super().emit(record)
            return

        message = record.getMessage()
        now = time.monotonic()

        if message != self._dedup_last_message:
            # New, non-duplicate message: flush any pending repeats, then write.
            self._flush_dedup()
            super().emit(record)
            self._dedup_last_message = message
            self._dedup_record = record
            return

        if self._dedup_started is None:
            # First immediate repeat: open the cooldown window and suppress.
            self._dedup_started = now
            self._dedup_count = 1
            return

        # Continued repeat within an open window.
        self._dedup_count += 1
        if now - self._dedup_started >= self.dedup_interval:
            # Cooldown satisfied: summarise the run so far and reopen a window
            # so sustained spam yields one summary line per interval.
            self._flush_dedup()
            self._dedup_started = now


class HTTPPostHandler(logging.Handler):
    """Logging handler that POSTs each record as JSON to a webhook URL."""

    def __init__(self, url, headers=None, **kwargs):
        """Store the webhook URL, headers and extra payload fields.

        Args:
            url: Destination URL for the HTTP POST.
            headers: Request headers (defaults to ``application/json``).
            **kwargs: Extra key/value pairs merged into every payload.
        """
        super().__init__()
        self.url = url
        self.headers = (
            headers if headers is not None else {"Content-type": "application/json"}
        )
        self.payload = kwargs

    def emit(self, record):
        """Format ``record`` and POST it to the webhook with the stored payload."""
        try:
            # Format the log record into a desired structure (e.g., a JSON dictionary)
            log_entry = self.format(record)
            payload = {k: v for k, v in self.payload.items()}
            payload["text"] = log_entry
            # print("Sending log record to webhook with payload:", payload)

            # Send the custom payload using requests
            requests.post(self.url, json=payload, headers=self.headers, timeout=30)
        except Exception:
            self.handleError(record)


class NtpOffsetFormatter(logging.Formatter):
    """Formatter that shifts timestamps by a fixed NTP-derived offset.

    Attributes:
        offset: Timedelta added to each record's creation time.
        tz: Timezone used for formatting (UTC or local).
    """

    def __init__(self, *args, offset_seconds=0, use_utc: bool = False, **kwargs):
        """Build the formatter.

        Args:
            *args: Positional arguments forwarded to ``logging.Formatter``.
            offset_seconds: Seconds to add to each log record timestamp.
            use_utc: If ``True``, format times in UTC instead of local time.
            **kwargs: Keyword arguments forwarded to ``logging.Formatter``.
        """
        super().__init__(*args, **kwargs)
        self.offset = timedelta(seconds=offset_seconds)
        if use_utc:
            self.tz = timezone.utc
        else:
            now = datetime.now()
            local_now = now.astimezone()
            local_tz = local_now.tzinfo
            self.tz = local_tz

    def formatTime(self, record, datefmt=None) -> str:
        """Return the record's creation time shifted by the configured offset."""
        # Convert the record's timestamp (seconds since epoch) to a UTC datetime
        ct = datetime.fromtimestamp(record.created, tz=self.tz)
        # Apply the desired offset
        dt = ct + self.offset

        if datefmt:
            return dt.strftime(datefmt)
        else:
            # If no datefmt is specified, use a default ISO8601-like format with offset
            t = dt.strftime(self.default_time_format)
            return self.default_msec_format % (t, record.msecs)


class ColoredNtpOffsetFormatter(ColoredFormatter):
    """Colour-aware variant of ``NtpOffsetFormatter`` for stream handlers."""

    def __init__(self, *args, offset_seconds=0, use_utc: bool = False, **kwargs):
        """Build the formatter.

        Args:
            *args: Positional arguments forwarded to ``ColoredFormatter``.
            offset_seconds: Seconds to add to each log record timestamp.
            use_utc: If ``True``, format times in UTC instead of local time.
            **kwargs: Keyword arguments forwarded to ``ColoredFormatter``.
        """
        super().__init__(*args, **kwargs)
        self.offset = timedelta(seconds=offset_seconds)
        if use_utc:
            self.tz = timezone.utc
        else:
            now = datetime.now()
            local_now = now.astimezone()
            local_tz = local_now.tzinfo
            self.tz = local_tz

    def formatTime(self, record, datefmt=None) -> str:
        """Return the record's creation time shifted by the configured offset."""
        # Convert the record's timestamp (seconds since epoch) to a UTC datetime
        ct = datetime.fromtimestamp(record.created, tz=self.tz)
        # Apply the desired offset
        dt = ct + self.offset

        if datefmt:
            return dt.strftime(datefmt)
        else:
            # If no datefmt is specified, use a default ISO8601-like format with offset
            t = dt.strftime(self.default_time_format)
            return self.default_msec_format % (t, record.msecs)


def make_logger(
    logger_name: Optional[str] = None,
    log_dir: Optional[str] = None,
    log_level: int = 20,  # 10 (DEBUG), 20 (INFO), 30 (WARNING), 40 (ERROR), 50 (CRITICAL)
    email_config: dict = {},
    show_debug_console: bool = False,
    dedup_interval: float = DEFAULT_DEDUP_INTERVAL,
) -> logging.Logger:
    """Build and configure the canonical per-server HELAO logger.

    Attaches a daily-rotating gzip file handler and a coloured console
    handler. When ``email_config`` provides full SMTP credentials or a
    webhook plus payload, an ``ALERT``-level queue-backed handler is added
    that forwards records to email and/or HTTP respectively. Timestamps are
    offset using the cached NTP offset from ``ntpLastSync.txt`` in
    ``log_dir`` when present.

    Args:
        logger_name: Logger name; if it ends with ``.py`` the basename
            without extension is used.
        log_dir: Directory for log files; defaults to a fresh temp dir.
        log_level: Threshold for the file and (non-debug) console handlers.
        email_config: Configuration dict that may contain SMTP credentials
            (``mailhost``, ``mailport``, ``fromaddr``, ``username``,
            ``password``, ``recipients``, ``subject``) and/or a ``webhook``
            URL with associated ``payload``. An optional ``email_interval``
            key (seconds) throttles outgoing alert emails to at most one per
            interval, defaulting to :data:`DEFAULT_EMAIL_INTERVAL`.
        show_debug_console: If ``True``, the console handler is set to
            ``DEBUG`` level.
        dedup_interval: Seconds over which identical consecutive messages
            written to the rotating file are collapsed into a single summary
            line, defaulting to :data:`DEFAULT_DEDUP_INTERVAL`. ``0`` disables
            de-duplication.

    Returns:
        The configured ``logging.Logger`` instance.
    """
    if logger_name is not None and logger_name.endswith(".py"):
        logger_name = os.path.basename(logger_name).replace(".py", "")
    temp_dir = tempfile.mkdtemp()
    log_dir = temp_dir if log_dir is None else log_dir
    log_path = Path(os.path.join(log_dir, f"{logger_name}.log"))
    format_string = "%(asctime)s | %(levelname)-8s | %(name)s :: %(funcName)s @ %(filename)s:%(lineno)d - %(message)s"
    ntp_path = os.path.join(log_dir, "ntpLastSync.txt")
    if os.path.exists(ntp_path):
        _, offset_seconds = read_saved_offset(ntp_path)
    else:
        offset_seconds = 0
    formatter = NtpOffsetFormatter(format_string, offset_seconds=offset_seconds)
    # for stream output
    colored_format_string = "%(log_color)s%(asctime)s | %(levelname)-8s | %(name)s %(reset)s%(white)s:: %(funcName)s @ %(filename)s:%(lineno)d - %(reset)s%(light_blue)s%(message)s"
    colored_formatter = ColoredNtpOffsetFormatter(
        colored_format_string,
        offset_seconds=offset_seconds,
        log_colors={
            "DEBUG": "cyan",
            "INFO": "light_green",
            "WARNING": "yellow",
            "ERROR": "light_red",
            "CRITICAL": "red,bg_white",
            "ALERT": "light_purple",
        },
        secondary_log_colors={},
        style="%",
    )

    logger_instance = logging.getLogger(logger_name)
    logger_instance.setLevel(min(10, log_level))

    # create handlers
    console = logging.StreamHandler()
    console.setFormatter(colored_formatter)
    try:
        timed_rotation = DedupTimedRotatingFileHandler(
            filename=log_path,
            when="D",
            interval=1,
            backupCount=90,
            dedup_interval=dedup_interval,
        )
        timed_rotation.rotator = GZipRotator()
    except OSError:
        temp_log_path = Path(os.path.join(temp_dir, f"{logger_name}.log"))
        print(f"Can't write to {log_path}. Redirecting to: {temp_log_path}")
        timed_rotation = DedupTimedRotatingFileHandler(
            filename=temp_log_path,
            when="D",
            interval=1,
            backupCount=90,
            dedup_interval=dedup_interval,
        )
    timed_rotation.setFormatter(formatter)

    # set log level and attach default handlers
    handlers = [timed_rotation]
    for handler in handlers:
        handler.setLevel(log_level)
        logger_instance.addHandler(handler)

    debug_handlers = [console]
    for handler in debug_handlers:
        handler.setLevel(10 if show_debug_console else 20)
        logger_instance.addHandler(handler)

    mailhost = email_config.get("mailhost", None)
    mailport = email_config.get("mailport", None)
    fromaddr = email_config.get("fromaddr", None)
    username = email_config.get("username", None)
    password = email_config.get("password", None)
    recipients = email_config.get("recipients", None)
    subject = email_config.get("subject", "Error in Helao")
    email_interval = email_config.get("email_interval", DEFAULT_EMAIL_INTERVAL)
    email_conditions = [
        x is not None
        for x in [mailhost, mailport, fromaddr, username, password, recipients]
    ]
    # print(email_conditions)
    if all(email_conditions):
        email_queue = Queue(-1)
        queue_handler = QueueHandler(email_queue)
        queue_handler.setLevel(ALERT_LEVEL)
        # queue_handler.setFormatter(formatter)
        logger_instance.addHandler(queue_handler)
        email_handler = TitledSMTPHandler(
            mailhost=(mailhost, mailport),
            fromaddr=fromaddr,
            toaddrs=recipients,
            subject=subject,
            credentials=(username, password),
            secure=(),
            min_interval=email_interval,
        )
        email_handler.setLevel(ALERT_LEVEL)
        email_handler.setFormatter(formatter)
        # logger_instance.addHandler(email_handler)
        queue_listener = QueueListener(email_queue, email_handler)
        queue_listener.start()
        logger_instance.info(
            f"Email alerts enabled at log level: {ALERT_LEVEL} "
            f"(throttled to 1 email per {email_interval}s)"
        )
    else:
        logger_instance.info(f"Email alerts not enabled using config: {email_config}")

    webhook = email_config.get("webhook", None)
    payload = email_config.get("payload", None)
    webhook_conditions = [x is not None for x in [webhook, payload]]
    if all(webhook_conditions):
        webhook_queue = Queue(-1)
        webhook_queue_handler = QueueHandler(webhook_queue)
        webhook_queue_handler.setLevel(ALERT_LEVEL)
        logger_instance.addHandler(webhook_queue_handler)
        webhook_handler = HTTPPostHandler(url=webhook, **payload)
        webhook_handler.setLevel(ALERT_LEVEL)
        webhook_handler.setFormatter(formatter)
        # logger_instance.addHandler(webhook_handler)
        webhook_queue_listener = QueueListener(webhook_queue, webhook_handler)
        webhook_queue_listener.start()
        logger_instance.info(f"Webhook alerts enabled at log level: {ALERT_LEVEL}")
    else:
        logger_instance.info(f"Webhook alerts not enabled using config: {email_config}")

    logger_instance.info(f"writing log events to {log_path}")
    logger_instance.propagate = False
    return logger_instance


def print_message(logger, server_name, *args, **kwargs):
    """Forward a message to ``logger`` at a level chosen by recognised kwargs.

    The level is picked from ``kwargs``: ``error`` selects ``logger.error``,
    ``warning`` or ``warn`` selects ``logger.warning``, ``info`` or no
    recognised key selects ``logger.info``. Positional ``args`` are
    stringified and joined with spaces.

    Args:
        logger: Target logger.
        server_name: Originating server name (currently unused, retained for
            call-site compatibility).
        *args: Message fragments concatenated with spaces.
        **kwargs: Level-selecting flags as described above.
    """
    if "error" in kwargs:
        logger_method = logger.error
    elif "warning" in kwargs or "warn" in kwargs:
        logger_method = logger.warning
    elif "info" in kwargs:
        logger_method = logger.info
    else:
        logger_method = logger.info

    logger_method(" ".join([str(x) for x in args]))
