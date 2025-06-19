__all__ = ["read_config", "load_global_config", "CONFIG"]

import os
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

CONFIG = None


def read_config(confArg, helao_repo_root):
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
        yml_path = os.path.join(
            helao_repo_root, "helao", "configs", f"{confPrefix}.yml"
        )
        py_path = yml_path.replace(".yml", ".py")
        if os.path.exists(yml_path):
            full_path = yml_path
            config = yml_load(Path(yml_path))
        elif os.path.exists(py_path):
            full_path = py_path
            config = (
                SourceFileLoader(
                    "config",
                    full_path,
                )
                .load_module()
                .config
            )
        else:
            raise FileNotFoundError(
                "Config argument was a prefix but .py or .yml could not be found."
            )
        # print_message(
        #     LOGGER,
        #     "launcher",
        #     f"Loading config from {full_path}",
        #     info=True,
        # )
        print(f"Loading config from {full_path}")
    config["loaded_config_path"] = full_path
    return config


def load_global_config(confArg: str, set_global: bool = False):
    helao_repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    )
    config_dict = read_config(confArg, helao_repo_root)
    if set_global:
        global CONFIG
        CONFIG = config_dict
    return config_dict


class OrchServerParams(BaseModel):
    enable_op: bool = False
    heartbeat_interval: float = 10.0
    ignore_heartbeats: List[str] = []
    verify_plates: bool = True


class ServerConfig(BaseModel):
    host: str
    port: int
    group: str
    fast: Optional[str] = None
    bokeh: Optional[str] = None
    params: Optional[dict | OrchServerParams] = {}
    verbose: Optional[bool] = False


class HelaoConfig(BaseModel):
    run_type: str
    root: str
    dummy: Optional[bool] = True
    simulation: Optional[bool] = True
    experiment_libraries: Optional[List[str]] = []
    experiment_params: Optional[dict] = {}
    sequence_libraries: Optional[List[str]] = []
    sequence_params: Optional[dict] = {}
    servers: Optional[dict] = {}
    alert_config_path: Optional[str] = None
    builtin_ref_motorxy: Optional[List[float]] = None
