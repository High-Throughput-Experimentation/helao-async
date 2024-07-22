import os
import json
import logging
from datetime import datetime


log_level_acquired = True

with open(arg_app_config_path, "r") as f:
    app_config = json.loads(f.read())
    log_level_str = app_config["app"]["logLevel"]["python"]

match log_level_str:
    case "info":
        log_level = logging.INFO
    case "debug":
        log_level = logging.DEBUG
    case _:
        log_level = logging.INFO
        # Set default level INFO
        log_level_acquired = False


def setup_logger(log_name, log_folder, level) -> logging.Logger:
    date = datetime.now()
    date_formatted = date.strftime("%Y_%m_%dT%H_%M_%S_%f%z")
    log_path = os.path.join(log_folder, f"{log_name}_{date_formatted}.log")

    l = logging.getLogger(log_name)

    filet_formatter = logging.Formatter("%(asctime)s : [%(levelname)s] %(message)s")
    file_handler = logging.FileHandler(log_path, mode="w")
    file_handler.setFormatter(filet_formatter)

    stream_formatter = logging.Formatter("%(asctime)s : %(name)s >> [%(levelname)s] %(message)s")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(stream_formatter)

    l.setLevel(level)
    l.addHandler(file_handler)
    l.addHandler(stream_handler)

    return logging.getLogger(log_name)


log_folder = os.path.join(os.getcwd(), arg_logs_folder_path)

main_log = setup_logger("main", log_folder, log_level)
main_log_path = main_log.handlers[0].baseFilename
main_log.info("Main log started")
if not log_level_acquired:
    main_log.info(f'Log level "{log_level_str}" not recognized, setting default level INFO')
main_log.info(f"Log level: {main_log.level}")

script_log = setup_logger("script", log_folder, log_level)
script_log_path = script_log.handlers[0].baseFilename
script_log.info("Script log started")
script_log.info(f"Log level: {main_log.level}")
