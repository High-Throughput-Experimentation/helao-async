"""Logging module, import at top of every script

Usage:

    from helao.helpers import helao_logging as logging
    if logging.LOGGER is None:
        logger = logging.make_logger(__file__)
    logger = logging.LOGGER

"""

import tempfile
import os
import sys
import subprocess
import logging
import requests
import json
from urllib.parse import quote
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
from helao.helpers.get_ntp_time import read_saved_offset

ALERT_LEVEL = 60
logging.addLevelName(ALERT_LEVEL, "ALERT")


def alert(self, message, *args, **kws):
    if self.isEnabledFor(ALERT_LEVEL):
        # Yes, logger takes its '*args' as 'args'.
        self._log(ALERT_LEVEL, message, args, **kws)


# logging.Logger.alert = alert
setattr(logging.Logger, "alert", alert)

LOGGER: logging.Logger = None


class GZipRotator:
    def __call__(self, source, dest):
        os.rename(source, dest)
        subprocess.Popen(["gzip", dest])


class TitledSMTPHandler(SMTPHandler):
    def getSubject(self, record):
        if "~" in record.message:
            title = record.message.split("~")[0].strip()
        else:
            title = record.message.split()[0].strip()
        return f"{record.levelname} - {title}"


class HTTPPostHandler(logging.Handler):
    def __init__(self, url, headers=None, **kwargs):
        super().__init__()
        self.url = url
        self.headers = (
            headers if headers is not None else {"Content-type": "application/json"}
        )
        self.payload = kwargs
        print(f"Initialized HTTPPostHandler with URL: {self.url} and payload: {self.payload}")

    def emit(self, record):
        """
        Emit a record.
        """
        try:
            # Format the log record into a desired structure (e.g., a JSON dictionary)
            log_entry = self.format(record)
            payload = {k: v for k, v in self.payload.items()}
            payload["text"] = log_entry
            print("Sending log record to webhook with payload:", payload)

            # Send the custom payload using requests
            resp = requests.post(self.url, data=payload, headers=self.headers, timeout=30)
            print(resp.request.body)
            print(resp.request.url)
            print(resp.request.path_url)
        except requests.exceptions.RequestException as e:
            # Handle exceptions, e.g. network issues
            print(f"Failed to send log record to {self.url}: {e}", file=sys.stderr)
        except Exception:
            self.handleError(record)


class NtpOffsetFormatter(logging.Formatter):
    def __init__(self, *args, offset_seconds=0, use_utc: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.offset = timedelta(seconds=offset_seconds)
        if use_utc:
            self.tz = timezone.utc
        else:
            now = datetime.now()
            local_now = now.astimezone()
            local_tz = local_now.tzinfo
            self.tz = local_tz

    def formatTime(self, record, datefmt=None):
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
    def __init__(self, *args, offset_seconds=0, use_utc: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.offset = timedelta(seconds=offset_seconds)
        if use_utc:
            self.tz = timezone.utc
        else:
            now = datetime.now()
            local_now = now.astimezone()
            local_tz = local_now.tzinfo
            self.tz = local_tz

    def formatTime(self, record, datefmt=None):
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
):
    """
    Creates and configures a logger instance with both console and file handlers.

    Args:
        logger_name (Optional[str]): The name of the logger. If None, the root logger is used.
        log_dir (Optional[str]): The directory where the log file will be stored. If None, the system's temporary directory is used.
        log_level (int): The logging level. Default is 20 (INFO). Other levels are 10 (DEBUG), 30 (WARNING), 40 (ERROR), 50 (CRITICAL).

    Returns:
        logging.Logger: Configured logger instance.
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
        timed_rotation = TimedRotatingFileHandler(
            filename=log_path, when="D", interval=1, backupCount=90
        )
        timed_rotation.rotator = GZipRotator()
    except OSError:
        temp_log_path = Path(os.path.join(temp_dir, f"{logger_name}.log"))
        print(f"Can't write to {log_path}. Redirecting to: {temp_log_path}")
        timed_rotation = TimedRotatingFileHandler(
            filename=temp_log_path, when="D", interval=1, backupCount=90
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
        )
        email_handler.setLevel(ALERT_LEVEL)
        email_handler.setFormatter(formatter)
        # logger_instance.addHandler(email_handler)
        queue_listener = QueueListener(email_queue, email_handler)
        queue_listener.start()
        logger_instance.info(f"Email alerts enabled at log level: {ALERT_LEVEL}")
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
