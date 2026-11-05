"""Startup steps shared by fast_launcher, bokeh_launcher and reflex_launcher.

Only the bootstrap lives here (colorama, config load, logger, deployment
auto-detect). The spawn path, parent-death arming and pid handling stay in the
launchers; see ``helao/helpers/CLAUDE.md``.
"""

__all__ = [
    "init_colorama",
    "launcher_bootstrap",
    "load_alert_config",
    "resolve_app_deployment",
]

import os
import sys
from pathlib import Path

import colorama

from helao.helpers import config_loader
from helao.helpers import helao_logging as logging
from helao.helpers import server_modules
from helao.helpers.yml_tools import yml_load


def init_colorama() -> None:
    # launch.py sets HELAO_FORCE_COLOR when it pumps our output through its own
    # tty stdout: emit raw ANSI so the launcher's colorama translates it (which
    # on Windows must happen against a real console handle, not our pipe),
    # instead of stripping just because our own stdout is a pipe.
    if os.environ.get("HELAO_FORCE_COLOR") == "1":
        colorama.init(strip=False, convert=False)
    else:
        colorama.init(strip=not sys.stdout.isatty())


def load_alert_config(config: dict) -> dict:
    """The email/webhook alert settings named by ``alert_config_path``, else ``{}``."""
    path = config.get("alert_config_path")
    return yml_load(path) if path else {}


def launcher_bootstrap(conf_arg: str, server_key: str):
    """Load the global config and logger. Returns (CONFIG, server_config, LOGGER)."""
    if config_loader.CONFIG is None:
        config_dict, _validated = config_loader.read_validated_config(conf_arg)
        config_loader.install_global_config(config_dict)
    CONFIG = config_loader.CONFIG
    assert CONFIG is not None  # install_global_config just set it
    server_config = CONFIG["servers"][server_key]
    log_root = os.path.join(CONFIG["root"], "LOGS") if "root" in CONFIG else None
    logging.set_server_key(server_key)
    if logging.LOGGER is None:
        logging.LOGGER = logging.make_logger(
            logger_name=server_key,
            log_dir=log_root,
            email_config=load_alert_config(CONFIG),
            log_level=server_config.get("log_level", CONFIG.get("log_level", 20)),
        )
    LOGGER = logging.LOGGER
    LOGGER.info(f"Loaded config from: {CONFIG['loaded_config_path']}")
    return CONFIG, server_config, LOGGER


def resolve_app_deployment(server_config, module, config_path, logger) -> str:
    """Deployment holding the ``fast:``/``bokeh:`` module for this server.

    An explicit ``deployment:`` key wins unchecked. Otherwise the search root is
    the config's great-grandparent (``helao/deploy`` for an in-tree config) and
    the config's own deployment is preferred; a module in several other
    deployments warns and takes the first in sorted order. Unchanged semantics
    from the ``servers/<group>/`` glob, now over every ``servers/*`` folder.
    """
    if "deployment" in server_config:
        return server_config["deployment"]
    cfg = Path(config_path).resolve()
    own, root = cfg.parents[1].name, cfg.parents[2]
    deployment, found = server_modules.locate(module, "app", own=own, deploy_root=root)
    if deployment is not None:
        if deployment != own:
            logger.info(f"Auto-detected deployment: {deployment}")
        return deployment
    if not found:
        raise FileNotFoundError(f"Could not find deployment for {module}")
    logger.warning(
        f"{module} exists in {found}, none of them this config's own; falling "
        f"back to '{found[0]}'. Set an explicit 'deployment:' key on the server."
    )
    return found[0]


def app_module_path(deployment: str, module: str) -> str:
    """Dotted import path of ``module`` (app stack) inside ``deployment``."""
    path = server_modules.module_file(deployment, module, "app")
    if path is None:
        raise FileNotFoundError(
            f"deployment {deployment!r} has no module {module!r} under servers/"
        )
    return server_modules.import_path(path)
