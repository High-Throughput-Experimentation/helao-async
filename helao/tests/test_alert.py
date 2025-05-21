import sys

from helao.helpers import helao_logging as logging
from helao.helpers.yml_tools import yml_load

email_config = yml_load(sys.argv[1])

LOGGER = logging.make_logger(
    logger_name=None,
    log_dir="c:/INST_hlo/LOGS",
    email_config=email_config,
    log_level=20
)

LOGGER.alert("TEST ~ this is a test alert")