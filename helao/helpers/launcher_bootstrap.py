"""Startup steps shared by fast_launcher, bokeh_launcher and reflex_launcher.

Only the bootstrap lives here (colorama, config load, logger, deployment
auto-detect). The spawn path, parent-death arming and pid handling stay in the
launchers; see ``helao/helpers/CLAUDE.md``.
"""

__all__ = ["init_colorama", "launcher_bootstrap", "resolve_app_deployment"]

import os
import sys
from glob import glob

import colorama

from helao.helpers import config_loader
from helao.helpers import helao_logging as logging
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


def launcher_bootstrap(conf_arg: str, server_key: str):
    """Load the global config and logger. Returns (CONFIG, server_config, LOGGER)."""
    if config_loader.CONFIG is None:
        config_dict, _validated = config_loader.read_validated_config(conf_arg)
        config_loader.install_global_config(config_dict)
    CONFIG = config_loader.CONFIG
    assert CONFIG is not None  # install_global_config just set it
    server_config = CONFIG["servers"][server_key]
    log_root = os.path.join(CONFIG["root"], "LOGS") if "root" in CONFIG else None
    if CONFIG.get("alert_config_path", False):
        email_config = yml_load(CONFIG["alert_config_path"])
    else:
        email_config = {}
    if logging.LOGGER is None:
        logging.LOGGER = logging.make_logger(
            logger_name=server_key,
            log_dir=log_root,
            email_config=email_config,
            log_level=server_config.get("log_level", CONFIG.get("log_level", 20)),
        )
    LOGGER = logging.LOGGER
    LOGGER.info(f"Loaded config from: {CONFIG['loaded_config_path']}")
    return CONFIG, server_config, LOGGER


def resolve_app_deployment(server_config, module, config_path, logger) -> str:
    """Deployment holding ``servers/<group>/<module>.py`` for this server.

    An explicit ``deployment:`` key wins; otherwise glob the deployments, prefer
    the one matching the config's own path, and fall back (with a warning) to
    the first match.
    """
    detected_deployment = os.path.basename(
        os.path.dirname(os.path.dirname(config_path))
    )
    deployment = server_config.get("deployment", detected_deployment)
    if "deployment" not in server_config:
        possible_deployments = sorted(
            glob(
                os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(config_path))),
                    "*",
                    "servers",
                    server_config["group"],
                    f"{module}.py",
                )
            )
        )
        if len(possible_deployments) == 1:
            deployment = os.path.basename(
                os.path.dirname(
                    os.path.dirname(os.path.dirname(possible_deployments[0]))
                )
            )
            logger.info(f"Auto-detected deployment: {deployment}")
        elif len(possible_deployments) > 1:
            # Prefer the deployment matching the config's own path. If none
            # match (e.g. a derived/private config that reuses another
            # deployment's generic app), fall back to the first match and warn
            # rather than crashing on an empty filter.
            config_dep_dir = os.path.dirname(os.path.dirname(config_path))
            filter_possible = [
                x for x in possible_deployments if x.startswith(config_dep_dir)
            ]
            chosen = filter_possible[0] if filter_possible else possible_deployments[0]
            deployment = os.path.basename(
                os.path.dirname(os.path.dirname(os.path.dirname(chosen)))
            )
            if filter_possible:
                logger.info(
                    f"Auto-detected deployment from multiple options: {deployment}"
                )
            else:
                logger.warning(
                    f"No deployment under the config path matched "
                    f"{module} in {server_config['group']}; "
                    f"falling back to '{deployment}'. Set an explicit "
                    f"'deployment:' key on this server to disambiguate."
                )
        else:
            raise FileNotFoundError(
                f"Could not find deployment for {module} in {server_config['group']}"
            )
    return deployment
