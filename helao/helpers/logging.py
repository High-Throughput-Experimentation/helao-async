"""Logging module, import at top of every script

Usage:

    from helao.helpers import logging
    if logging.LOGGER is None:
        logger = logging.make_logger()
    logger = logging.LOGGER

"""

import logging
from logging.handlers import TimedRotatingFileHandler
import tempfile
import os

from typing import Optional
from pathlib import Path


LOGGER = None


def make_logger(
    logger_name: Optional[str] = None,
    log_dir: Optional[str] = None,
    log_level: int = 20,
):
    """Creates a logger (use once per process)."""
    log_dir = tempfile.gettempdir() if log_dir is None else log_dir
    log_path = Path(os.path.join(log_dir, f"{logger_name}.log"))
    format_string = "%(asctime)s :: %(funcName)s @ %(filename)s:%(lineno)d - %(levelname)-8s %(message)s"
    formatter = logging.Formatter(format_string)

    logger = logging.getLogger(logger_name)
    logger.setLevel(log_level)

    # create handlers
    console = logging.StreamHandler()
    timed_rotation = TimedRotatingFileHandler(
        filename=log_path, when="D", interval=1, backupCount=14
    )

    # set log level, formatter, and attach handlers
    handlers = [console, timed_rotation]
    for handler in handlers:
        handler.setLevel(log_level)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.info(f"writing log events to {log_path}")
    return logger
