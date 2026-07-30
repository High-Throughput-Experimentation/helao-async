"""Manual smoke check for the logger's ALERT delivery path (email / webhook).

NOT a pytest module, despite the filename and location. It is a hand-run
utility, and it is now **import-safe**: everything lives behind ``main()`` and
the ``__main__`` guard.

That guard is the point of this file's shape. Previously the config load, logger
construction, and ``LOGGER.alert(...)`` all ran at MODULE level, so merely
importing this module delivered a real alert. pytest imports a module in order
to collect it, so any tool sweeping ``test_*.py`` -- which this filename invites
-- would send mail as a side effect of collecting tests. It escaped notice only
because the module also read ``sys.argv[1]`` as a config path, so under pytest
it crashed on the test file's own path before reaching the send. A valid YAML in
``argv[1]`` would have delivered.

Delivery now additionally requires an explicit ``--send``. Without it this does
a dry run: it validates the config and reports where an alert WOULD go, which is
the part worth checking most of the time anyway.

    python -m helao.core.tests.test_alert <email_config.yml>           # dry run
    python -m helao.core.tests.test_alert <email_config.yml> --send    # delivers

``helao.helpers.helao_logging.make_logger`` attaches the ALERT-level handler
only when the config carries a full SMTP set (``mailhost``, ``fromaddr``,
``recipients``, ...) or a ``webhook`` plus ``payload``; the dry run reports which
of those two channels would actually be live.
"""

import argparse
import sys
import tempfile
from pathlib import Path

#: Config keys make_logger reads for the SMTP channel (helao_logging.py:524+).
SMTP_KEYS = (
    "mailhost",
    "mailport",
    "fromaddr",
    "username",
    "password",
    "recipients",
    "subject",
    "email_interval",
)
#: Keys for the HTTP channel, which ALERT records also fan out to.
WEBHOOK_KEYS = ("webhook", "payload")
#: Never echoed back, even on a dry run.
SECRET_KEYS = {"password", "username"}

DEFAULT_MESSAGE = "TEST ~ this is a test alert"


def describe(email_config: dict) -> list[str]:
    """Lines describing which ALERT channels this config would enable.

    Credentials are redacted: this prints to a terminal, often into a scrollback
    that outlives the session. (``make_logger`` itself is less careful -- when
    alerts are NOT enabled it logs the whole config dict, password included.)
    """
    lines = []
    smtp = {k: email_config.get(k) for k in SMTP_KEYS}
    smtp_live = all(smtp.get(k) for k in ("mailhost", "fromaddr", "recipients"))
    lines.append(f"SMTP channel:    {'ENABLED' if smtp_live else 'not enabled'}")
    for key in SMTP_KEYS:
        value = smtp.get(key)
        if value is None:
            continue
        lines.append(f"    {key}: {'<redacted>' if key in SECRET_KEYS else value}")

    hook_live = all(email_config.get(k) for k in WEBHOOK_KEYS)
    lines.append(f"webhook channel: {'ENABLED' if hook_live else 'not enabled'}")
    for key in WEBHOOK_KEYS:
        if email_config.get(key) is not None:
            lines.append(f"    {key}: {email_config[key]}")

    if not (smtp_live or hook_live):
        lines.append(
            "    -> nothing would be delivered: make_logger attaches the ALERT "
            "handler only for a complete SMTP set, or webhook+payload"
        )
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helao.core.tests.test_alert",
        description="Dry-run (default) or deliver a single test ALERT record.",
    )
    parser.add_argument("email_config", type=Path, help="path to an email-config YAML")
    parser.add_argument(
        "--send",
        action="store_true",
        help="actually deliver the alert; omit for a dry run that sends nothing",
    )
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument(
        "--log-dir",
        default=None,
        help="logger output dir (default: a temp dir, so sending one alert does "
        "not write into a production LOGS tree)",
    )
    args = parser.parse_args(argv)

    if not args.email_config.is_file():
        parser.error(f"no such email config: {args.email_config}")

    # Imported inside main(), not at module scope, so importing this module does
    # not drag in the logging stack either.
    from helao.helpers import helao_logging as logging
    from helao.helpers.yml_tools import yml_load

    email_config = yml_load(str(args.email_config)) or {}
    if not isinstance(email_config, dict):
        parser.error(
            f"{args.email_config} did not parse to a mapping "
            f"(got {type(email_config).__name__})"
        )

    print(f"config: {args.email_config}")
    for line in describe(email_config):
        print(line)

    if not args.send:
        print("\nDRY RUN -- nothing sent. Re-run with --send to deliver.")
        return 0

    log_dir = args.log_dir or tempfile.mkdtemp(prefix="helao-alert-smoke-")
    logger = logging.make_logger(
        logger_name=None,
        log_dir=log_dir,
        email_config=email_config,
        log_level=20,
    )
    print(f"\nsending: {args.message!r}")
    # `alert` is installed onto Logger by helao_logging (custom level 60)
    logger.alert(args.message)  # type: ignore[attr-defined]
    print("submitted to the ALERT handler (delivery is queued and asynchronous)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
