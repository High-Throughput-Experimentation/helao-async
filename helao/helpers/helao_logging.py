"""Logging module, import at top of every script

Usage:

    from helao.helpers import helao_logging as logging
    if logging.LOGGER is None:
        logger = logging.make_logger(__file__)
    logger = logging.LOGGER

"""

import tempfile
import os
import subprocess
import logging
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


# class TitledQueueHandler(QueueHandler):
#     def getSubject(self, record):
#         if "~" in record.message:
#             title = record.message.split("~")[0].strip()
#         else:
#             title = record.message.split()[0].strip()
#         return f"{record.levelname} - {title}"


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
    formatter = logging.Formatter(format_string)
    # for stream output
    colored_format_string = "%(log_color)s%(asctime)s | %(levelname)-8s | %(name)s %(reset)s%(white)s:: %(funcName)s @ %(filename)s:%(lineno)d - %(reset)s%(light_blue)s%(message)s"
    colored_formatter = ColoredFormatter(
        colored_format_string,
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

    logger_instance.info(f"writing log events to {log_path}")
    logger_instance.propagate = False
    return logger_instance
