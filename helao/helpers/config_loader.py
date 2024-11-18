__all__ = ["config_loader"]

import os
from pathlib import Path
from importlib.util import spec_from_file_location
from importlib.util import module_from_spec
from importlib.machinery import SourceFileLoader

from .print_message import print_message
from .yml_tools import yml_load

# from helao.helpers import logging

# if logging.LOGGER is None:
#     LOGGER = logging.make_logger(logger_name="config_loader_standalone")
# else:
#     LOGGER = logging.LOGGER

CONFIG = None 


def config_loader(confArg, helao_root):
    """
    Loads a configuration file in either Python (.py) or YAML (.yml) format.

    Args:
        confArg (str): The path to the configuration file or a prefix for the configuration file.
        helao_root (str): The root directory for the helao project.

    Returns:
        dict: The loaded configuration dictionary with an additional key 'loaded_config_path' 
              indicating the absolute path of the loaded configuration file.

    Raises:
        FileNotFoundError: If the specified configuration file does not exist or if the prefix 
                           does not correspond to an existing .py or .yml file.
    """
    confPrefix = os.path.basename(confArg).replace(".py", "").replace(".yml", "")
    if confArg.endswith(".py") and os.path.exists(confArg):
        # print_message(LOGGER, "launcher", f"Loading config from {confArg}", info=True)
        print(f"Loading config from {confArg}")
        conf_spec = spec_from_file_location("configs", confArg)
        conf_mod = module_from_spec(conf_spec)
        conf_spec.loader.exec_module(conf_mod)
        config = conf_mod.config
        full_path = os.path.abspath(confArg)
    elif confArg.endswith(".yml") and os.path.exists(confArg):
        # print_message(LOGGER, "launcher", f"Loading config from {confArg}", info=True)
        print(f"Loading config from {confArg}")
        config = yml_load(Path(confArg))
        full_path = os.path.abspath(confArg)
    elif (confArg.endswith(".py") or confArg.endswith(".yml")) and not os.path.exists(confArg):
        # print_message(LOGGER, "launcher", f"Config not found at {os.path.abspath(confArg)}", error=True)
        print(f"Config not found at {os.path.abspath(confArg)}")
        raise FileNotFoundError("Config argument ends with .py or .yml but expected path not found.")
    else:
        yml_path = os.path.join(helao_root, "helao", "configs", f"{confPrefix}.yml")
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
            raise FileNotFoundError("Config argument was a prefix but .py or .yml could not be found.")
        # print_message(
        #     LOGGER,
        #     "launcher",
        #     f"Loading config from {full_path}",
        #     info=True,
        # )
        print(f"Loading config from {full_path}")
    config["loaded_config_path"] = full_path
    return config
