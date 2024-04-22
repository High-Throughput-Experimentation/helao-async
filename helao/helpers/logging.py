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
from logging.handlers import TimedRotatingFileHandler
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
):
    """Creates a logger (use once per process)."""
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
        },
        secondary_log_colors={},
        style='%'
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

    # set log level and attach handlers
    handlers = [console, timed_rotation]
    for handler in handlers:
        handler.setLevel(log_level)
        logger_instance.addHandler(handler)

    logger_instance.info(f"writing log events to {log_path}")
    return logger_instance
