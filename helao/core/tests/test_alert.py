"""Manual smoke test for the logger's email alert path.

Loads an email-config YAML whose path is supplied as ``sys.argv[1]``,
builds a logger configured with that config, and emits a single
``alert``-level message so the alert delivery channel can be verified.
"""

import sys

from helao.helpers import helao_logging as logging
from helao.helpers.yml_tools import yml_load

email_config = yml_load(sys.argv[1])

LOGGER = logging.make_logger(
    logger_name=None,
    log_dir="c:/INST_hlo/LOGS",
    email_config=email_config,
    log_level=20,
)

LOGGER.alert("TEST ~ this is a test alert")
