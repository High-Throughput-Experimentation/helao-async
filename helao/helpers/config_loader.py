"""Configuration loading for HELAO orchestration groups.

Locates a ``.yml`` or ``.py`` config from a path or a bare prefix, populates
a few path-related keys derived from the surrounding repo layout, and
optionally publishes the result as the module-level :data:`CONFIG` Munch.
"""

__all__ = ["read_config", "load_global_config", "CONFIG"]

import os
from glob import glob
from munch import munchify, Munch
from typing import List, Dict, Optional
from pathlib import Path
from importlib.util import spec_from_file_location
from importlib.util import module_from_spec
from importlib.machinery import SourceFileLoader

from .yml_tools import yml_load
from pydantic import BaseModel

# from helao.helpers import helao_logging as logging

# if logging.LOGGER is None:
#     LOGGER = logging.make_logger(__file__)
# else:
#     LOGGER = logging.LOGGER

CONFIG: Munch = None


def read_config(confArg, *args, **kwargs):
    """Load a HELAO orchestration-group config from a path or a prefix.

    Resolves ``confArg`` to a single ``.py`` or ``.yml`` config file. An
    explicit path ending in ``.py`` is executed as a module and its
    top-level ``config`` dict is returned; a ``.yml`` path is parsed with
    :func:`yml_load`. Otherwise the basename is treated as a prefix and
    matched against ``helao/deploy/*/configs/<prefix>.{py,yml}``. The
    returned dict is augmented with ``loaded_config_path``,
    ``helao_repo_root``, ``helao_credentials_path``, and (if the
    environment variable is set) ``alert_config_path``.

    Args:
        confArg: Absolute/relative path to a ``.py`` or ``.yml`` config, or a
            bare prefix used to glob the deploy tree.
        *args: Unused; accepted for signature compatibility.
        **kwargs: Unused; accepted for signature compatibility.

    Returns:
        The loaded config as a plain ``dict`` with the extra path keys.

    Raises:
        FileNotFoundError: The repo root could not be located, the explicit
            path does not exist, or the prefix did not resolve to a config.
        Exception: Multiple ``.py`` or ``.yml`` files match the same prefix.
    """
    helao_repo_root = os.path.abspath(__file__)
    while os.path.basename(helao_repo_root) != "helao":  # find helao module directory
        helao_repo_root = os.path.dirname(helao_repo_root)
        if helao_repo_root == "/":
            raise FileNotFoundError(
                "Could not find helao repo root while searching for config file."
            )
    helao_repo_root = os.path.dirname(helao_repo_root)  # go up one to repo root
    confPrefix = os.path.basename(confArg).replace(".py", "").replace(".yml", "")
    if confArg.endswith(".py") and os.path.exists(confArg):
        # LOGGER.info(f"Loading config from {confArg}")
        print(f"Loading config from {confArg}")
        conf_spec = spec_from_file_location("configs", confArg)
        conf_mod = module_from_spec(conf_spec)
        conf_spec.loader.exec_module(conf_mod)
        config = conf_mod.config
        full_path = os.path.abspath(confArg)
    elif confArg.endswith(".yml") and os.path.exists(confArg):
        # LOGGER.info(f"Loading config from {confArg}")
        print(f"Loading config from {confArg}")
        config = yml_load(Path(confArg))
        full_path = os.path.abspath(confArg)
    elif (confArg.endswith(".py") or confArg.endswith(".yml")) and not os.path.exists(
        confArg
    ):
        # LOGGER.error(f"Config not found at {os.path.abspath(confArg)}")
        print(f"Config not found at {os.path.abspath(confArg)}")
        raise FileNotFoundError(
            "Config argument ends with .py or .yml but expected path not found."
        )
    else:
        prefix_paths = glob(
            os.path.join(
                helao_repo_root, "helao", "deploy", "*", "configs", f"{confPrefix}.*"
            )
        )
        yml_paths = [x for x in prefix_paths if x.endswith(".yml")]
        py_paths = [x for x in prefix_paths if x.endswith(".py")]
        if len(yml_paths) == 1:
            full_path = yml_paths[0]
            config = yml_load(Path(full_path))
        elif len(yml_paths) > 1:
            raise Exception(
                "Multiple .yml files found with that prefix.\n" + "\n".join(yml_paths)
            )
        elif len(py_paths) == 1:
            full_path = py_paths[0]
            config = (
                SourceFileLoader(
                    "config",
                    full_path,
                )
                .load_module()
                .config
            )
        elif len(py_paths) > 1:
            raise Exception(
                "Multiple .py files found with that prefix.\n" + "\n".join(py_paths)
            )
        else:
            raise FileNotFoundError(
                "Config argument was a prefix but .py or .yml could not be found."
            )
    config["loaded_config_path"] = full_path
    config["helao_repo_root"] = helao_repo_root
    config["helao_credentials_path"] = os.environ.get("HELAO_CREDENTIALS", "")
    if "ALERT_CONFIG_PATH" in os.environ:
        config["alert_config_path"] = os.environ["ALERT_CONFIG_PATH"]
    return config


def load_global_config(confArg: str, set_global: bool = False) -> dict:
    """Read a config and optionally publish it as the module-level :data:`CONFIG`.

    Args:
        confArg: Path or prefix passed through to :func:`read_config`.
        set_global: When true, validate the loaded dict against
            :class:`HelaoConfig` and store the resulting Munch on
            ``CONFIG``.

    Returns:
        The raw config dict from :func:`read_config`.
    """
    config_dict = read_config(confArg)
    if set_global:
        global CONFIG
        CONFIG = munchify(
            HelaoConfig(**config_dict).model_dump(exclude_unset=True, exclude_none=True)
        )
    return config_dict


class OrchServerParams(BaseModel):
    """Per-orchestrator ``params:`` block from a config YAML.

    Attributes:
        enable_op: Whether the orchestrator should host its Bokeh operator UI.
        heartbeat_interval: Seconds between status pings sent to action servers.
        ignore_heartbeats: Server keys whose missed heartbeats should not
            trigger error handling.
        verify_plates: Whether plate barcode verification is required.
    """

    enable_op: Optional[bool] = True
    heartbeat_interval: Optional[float] = 10.0
    ignore_heartbeats: Optional[List[str]] = None
    verify_plates: Optional[bool] = True


class ServerConfig(BaseModel):
    """One entry of the ``servers:`` mapping in a HELAO config.

    Attributes:
        host: Hostname or IP the server binds to.
        port: TCP port the server binds to.
        group: One of ``action``, ``orchestrator``, ``visualizer`` or
            ``operator``; selects the launcher and import path.
        fast: Module name under ``servers/<group>/`` for FastAPI servers.
        bokeh: Module name under ``servers/<group>/`` for Bokeh servers.
        params: Free-form parameter dict (or :class:`OrchServerParams` for
            orchestrators) passed through to the server's ``makeApp``.
        verbose: Enables debug-level logging on the server.
    """

    host: str
    port: int
    group: str
    fast: Optional[str] = None
    bokeh: Optional[str] = None
    params: Optional[dict | OrchServerParams] = None
    verbose: Optional[bool] = False


class HelaoConfig(BaseModel):
    """Top-level schema for a HELAO orchestration-group config file.

    Attributes:
        run_type: Free-form run-type label written into action/experiment metadata.
        root: Output root directory (e.g. logs, state, run trees) on disk.
        dummy: Marks the group as a dummy/non-production deployment.
        simulation: Marks the group as a simulated deployment; selects
            simulated drivers in many action servers.
        experiment_libraries: Module names under
            ``helao/deploy/<deployment>/experiments`` to import for the orchestrator.
        experiment_params: Default parameters merged into experiments at runtime.
        sequence_libraries: Module names under
            ``helao/deploy/<deployment>/sequences`` to import for the orchestrator.
        sequence_params: Default parameters merged into sequences at runtime.
        servers: Mapping of server key to :class:`ServerConfig`.
        alert_config_path: Path to the email-alert configuration, if any.
        builtin_ref_motorxy: Built-in reference XY motor coordinates.
    """

    run_type: str
    root: str
    dummy: Optional[bool] = True
    simulation: Optional[bool] = True
    experiment_libraries: Optional[List[str]] = None
    experiment_params: Optional[dict] = None
    sequence_libraries: Optional[List[str]] = None
    sequence_params: Optional[dict] = None
    servers: Optional[Dict[str, ServerConfig]] = None
    alert_config_path: Optional[str] = None
    builtin_ref_motorxy: Optional[List[float]] = None
