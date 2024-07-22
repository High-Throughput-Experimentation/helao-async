""" HelaoDriver for LeanCAT Fuel Cell Test Station

TODO: 
  1. Always disconnect from the station when the driver is shut down
  2. Create_session should be an action so we can control OPC logging over the course of an experiment
  3. Need to query postgresql database for latest job id


"""

import json
import time
from typing import Optional

# save a default log file system temp
from helao.helpers import logging
from logging.handlers import TimedRotatingFileHandler

if logging.LOGGER is None:
    LOGGER = logging.make_logger(logger_name="leancat_driver_standalone")
else:
    LOGGER = logging.LOGGER

import pandas as pd
import leancat_helao.config

from helao.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
)



class LeancatDriver(HelaoDriver):
    device_name: str
    connection_raised: bool

    def __init__(self, config: dict = {}):
        super().__init__(config=config)
        file_handlers = [x for x in LOGGER.handlers if isinstance(x, TimedRotatingFileHandler)]
        log_path = file_handlers[0].baseFilename
        leancat_config_path = config.get("app_config_json_path", None)
        if leancat_config_path is None:
            raise ValueError("Please provide a path to the LeanCAT app.config.json file.")
        nodes_config_path = config.get("nodes_config_json_path", None)
        if nodes_config_path is None:
            raise ValueError("Please provide a path to the LeanCAT nodes.config.json file.")
        with open(leancat_helao.config.node_config_path, "r") as f:
            self.nodes = {d['alias']: d['nodeId'] for d in json.load(f)["nodes"]}
        
        leancat_helao.config.arg_logs_folder_path = log_path
        leancat_helao.config.arg_app_config_path = leancat_config_path
        leancat_helao.config.node_config_path = nodes_config_path

        self.station_name = config.get("station_name", "Caltech_PBT_n1")
        
        import leancat_helao.logger
        from leancat_helao.station import Station

        self.station = Station(self.station_name)
        self.station.connect()
        LOGGER.info(f"Connected to LeanCAT station {self.station_name}.")
        
    
    def shutdown(self) -> None:
        self.station.disconnect()
        LOGGER.info(f"Disconnected from LeanCAT station {self.station_name}.")