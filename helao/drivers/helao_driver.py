"""Generic driver class for inheriting common methods and attributes.

The following methods are used by various drivers which require access to action server
base object. 

    print_message
    helaodirs.save_root
    helao_dirs.process_root
    orch_key
    orch_host
    orch_port
    put_lbuf
    aiolock
    fastapp.helao_cfg
    actionservermodel.estop
    dflt_file_conn_key
    server_cfg
    server_params
    server.server_name
    contain_action
    get_realtime_nowait
    
    

"""

from enum import StrEnum
from pathlib import Path
from typing import List, Dict
from datetime import datetime

import os
import tempfile
import logging
import faulthandler
import asyncio


class DriverStatus(StrEnum):
    uninitialized = "uninitialized"
    ok = "ok"
    error = "error"

class DriverResponseType(StrEnum):
    success = "success"
    failed = "failed"

class DriverMessage:
    timestamp: datetime
    
    def __init__(self):
        self.timestamp = datetime.now()

    @property
    def timestamp_str(self):
        return self.timestamp.strftime('%F %T,%f')[:-3]

class DriverData(DriverMessage):
    data: dict
    def __init__(self):
        super().__init__()

class DriverResponse(DriverMessage):
    response: DriverResponseType
    message: str
    data: DriverData
    status: DriverStatus
    
    def __init__(self):
        super().__init__()

class HelaoDriver:
    timestamp: datetime
    name: str
    config: dict
    status: DriverStatus
    errors: list
    warnings: list
    infos: list
    data_buffer: dict
    live_buffer: dict
    log_path: Path

    def __init__(self, driver_name: str, config: dict = {}):
        self.timestamp = datetime.now()
        self.name = driver_name
        self.config = config
        self.status = DriverStatus.uninitialized
        self.errors = []
        self.warnings = []
        self.infos = []
        self.data_buffer = {}
        self.live_buffer = {}

        log_dir = self.config.get("log_dir", tempfile.gettempdir())
        log_level = self.config.get("log_level", 20)
        self.log_path = Path(os.path.join(log_dir, f"{self.name}_driver.log"))
        format_string = "%(asctime)s :: %(levelname)-8s %(message)s"
        logging.basicConfig(
            filename=self.log_path, format=format_string, level=log_level
        )
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(format_string))
        logging.getLogger('').addHandler(console)
        logging.info(f"writing log events to {self.log_path}")

    @property
    def timestamp_str(self):
        return self.timestamp.strftime('%F %T,%f')[:-3]

    def connect(self):
        """Open connection to resource."""
        pass

    def reset(self):
        """Reinitialize driver, force-close old connection if necessary."""
        pass

    def close(self):
        """Release connection to resource."""
        pass

