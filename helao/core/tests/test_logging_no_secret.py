"""``make_logger`` must never write the alert config (SMTP password) to the log."""

import glob
import logging

from helao.helpers.helao_logging import make_logger

SENTINEL = "s3ntinel-p4ssw0rd"


def test_disabled_alert_log_line_omits_the_password(tmp_path):
    # Incomplete SMTP set -> the "not enabled" branch runs.
    logger = make_logger(
        logger_name="no_secret_test",
        log_dir=str(tmp_path),
        log_level=logging.INFO,
        email_config={"username": "u", "password": SENTINEL},
    )
    for h in logger.handlers:
        h.flush()
    text = "".join(
        open(p, encoding="utf-8").read()
        for p in glob.glob(f"{tmp_path}/**/*.log*", recursive=True)
    )
    assert "alerts not enabled" in text, "branch under test did not run"
    assert SENTINEL not in text
