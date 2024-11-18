"""Logging module, import at top of every script

Usage:

    from helao.helpers import logging
    if logging.LOGGER is None:
        logger = logging.make_logger()
    logger = logging.LOGGER

"""

# import picologging as logging
# from picologging.handlers import TimedRotatingFileHandler
import logging

ALERT_LEVEL = 60
logging.addLevelName(ALERT_LEVEL, "ALERT")


def alert(self, message, *args, **kws):
    if self.isEnabledFor(ALERT_LEVEL):
        # Yes, logger takes its '*args' as 'args'.
        self._log(ALERT_LEVEL, message, args, **kws)


logging.Logger.alert = alert


from logging.handlers import TimedRotatingFileHandler, SMTPHandler
from colorlog import ColoredFormatter
import tempfile
import os

from typing import Optional
from pathlib import Path

LOGGER = None


def make_logger(
    logger_name: Optional[str] = None,
    log_dir: Optional[str] = None,
    log_level: int = 20,  # 10 (DEBUG), 20 (INFO), 30 (WARNING), 40 (ERROR), 50 (CRITICAL)
    email_config: dict = {},
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
    log_dir = tempfile.gettempdir() if log_dir is None else log_dir
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
            "ALERT": "purple",
        },
        secondary_log_colors={},
        style="%",
    )

    logger_instance = logging.getLogger(logger_name)
    logger_instance.setLevel(log_level)

    # create handlers
    console = logging.StreamHandler()
    console.setFormatter(colored_formatter)
    timed_rotation = TimedRotatingFileHandler(
        filename=log_path, when="D", interval=1, backupCount=14
    )
    timed_rotation.setFormatter(formatter)

    # set log level and attach default handlers
    handlers = [console, timed_rotation]
    for handler in handlers:
        handler.setLevel(log_level)
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
    if all(email_conditions):
        email_handler = SMTPHandler(
            mailhost=(mailhost, mailport),
            fromaddr=fromaddr,
            toaddrs=recipients,
            subject=subject,
            credentials=(username, password),
            secure=(),
        )
        email_handler.setLevel(ALERT_LEVEL)
        email_handler.setFormatter(formatter)
        logger_instance.addHandler(email_handler)
        logger_instance.info(f"Email alerts enabled at log level: {ALERT_LEVEL}")
    else:
        logger_instance.info(f"Email alerts not enabled using config: {email_config}")

    logger_instance.info(f"writing log events to {log_path}")
    return logger_instance
