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


def read_config(confArg):
    """
    Loads a configuration file in either Python (.py) or YAML (.yml) format.

    Args:
        confArg (str): The path to the configuration file or a prefix for the configuration file.
        helao_repo_root (str): The root directory for the helao project.

    Returns:
        dict: The loaded configuration dictionary with an additional key 'loaded_config_path'
              indicating the absolute path of the loaded configuration file.

    Raises:
        FileNotFoundError: If the specified configuration file does not exist or if the prefix
                           does not correspond to an existing .py or .yml file.
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
    return config


def load_global_config(confArg: str, set_global: bool = False):
    helao_repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    )
    config_dict = read_config(confArg)
    if set_global:
        global CONFIG
        CONFIG = munchify(
            HelaoConfig(**config_dict).model_dump(exclude_unset=True, exclude_none=True)
        )
    return config_dict


class OrchServerParams(BaseModel):
    enable_op: Optional[bool] = True
    heartbeat_interval: Optional[float] = 10.0
    ignore_heartbeats: Optional[List[str]] = None
    verify_plates: Optional[bool] = True


class ServerConfig(BaseModel):
    host: str
    port: int
    group: str
    fast: Optional[str] = None
    bokeh: Optional[str] = None
    params: Optional[dict | OrchServerParams] = None
    verbose: Optional[bool] = False


class HelaoConfig(BaseModel):
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
