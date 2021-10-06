import asyncio
import json
import os
from copy import copy
from pathlib import Path
from socket import gethostname
from time import ctime, strftime, strptime, time, time_ns
from typing import Optional

import aiofiles
import ntplib
import numpy as np
import pyaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.openapi.utils import get_flat_params
from helao.core.helper import (
    MultisubscriberQueue,
    async_copy,
    cleanupdict,
    print_message,
)
from helao.core.model import prc_file, prg_file
from helao.core.schema import cProcess
from .server import HelaoFastAPI, async_private_dispatcher, hlo_version


class Base(object):
    """Base class for all HELAO servers.

    Base is a general class which implements message passing, status update, data
    writing, and data streaming via async tasks. Every instrument and process server
    should import this class for efficient integration into an orchestrated environment.

    A Base initialized within a FastAPI startup event will launch three async tasks
    to the server's event loop for handling:
    (1) broadcasting status updates via websocket and http POST requests to an attached
        orchestrator's status updater if available,
    (2) data streaming via websocket,
    (3) data writing to local disk.

    Websocket connections are broadcast from a multisubscriber queue in order to handle
    consumption from multiple clients awaiting a single queue. Self-subscriber tasks are
    also created as initial subscribers to log all events and prevent queue overflow.

    The data writing method will update a class attribute with the currently open file.
    For a given root directory, files and folders will be written as follows:
    {%y.%j}/  # process_group_date year.weeknum
        {%Y%m%d}/  # process_group_date
            {%H%M%S}__{process_group_label}/  # process_group_time
                {%Y%m%d.%H%M%S}__{process_server_name}__{process_name}__{process_uuid}/
                    {filename}.{ext}
                    {%Y%m%d.%H%M%S%f}.prc  # process_datetime
                    (aux_files)
    """

    def __init__(
        self,
        fastapp: HelaoFastAPI,
        calibration: dict = {},
    ):
        self.server_name = fastapp.helao_srv
        self.server_cfg = fastapp.helao_cfg["servers"][self.server_name]
        self.world_cfg = fastapp.helao_cfg
        self.hostname = gethostname()
        self.save_root = None
        self.technique_name = None
        self.aloop = asyncio.get_running_loop()

        if "technique_name" in self.world_cfg.keys():
            self.print_message(
                f" ... Found technique_name in config: {self.world_cfg['technique_name']}",
                info=True,
            )
            self.technique_name = self.world_cfg["technique_name"]
        else:
            raise ValueError(
                "Missing 'technique_name' in config, cannot create server object.",
                error=True,
            )

        self.calibration = calibration
        if "save_root" in self.world_cfg.keys():
            self.save_root = self.world_cfg["save_root"]
            self.print_message(
                f" ... Found root save directory in config: {self.world_cfg['save_root']}",
                info=True,
            )
            if not os.path.isdir(self.save_root):
                self.print_message(
                    " ... Warning: root save directory does not exist. Creatig it.",
                    warning=True,
                )
                os.makedirs(self.save_root)
        else:
            raise ValueError(
                " ... Warning: root save directory was not defined. Logs, PRCs, PRGs, and data will not be written.",
                error=True,
            )
        self.actives = {}
        self.status = {}
        self.endpoints = []
        self.status_q = MultisubscriberQueue()
        self.data_q = MultisubscriberQueue()
        self.status_clients = set()
        self.ntp_server = "time.nist.gov"
        self.ntp_response = None
        self.ntp_offset = None  # add to system time for correction
        self.ntp_last_sync = None
        if os.path.exists("ntpLastSync.txt"):
            time_inst = open("ntpLastSync.txt", "r")
            tmps = time_inst.readlines()
            time_inst.close()
            if len(tmps) > 0:
                self.ntp_last_sync, self.ntp_offset = tmps[0].strip().split(",")
                self.ntp_offset = float(self.ntp_offset)
        elif self.ntp_last_sync is None:
            asyncio.gather(self.get_ntp_time())
        self.init_endpoint_status(fastapp)
        self.fast_urls = self.get_endpoint_urls(fastapp)
        self.status_logger = self.aloop.create_task(self.log_status_task())
        self.ntp_syncer = self.aloop.create_task(self.sync_ntp_task())

    def print_message(self, *args, **kwargs):
        print_message(self.server_cfg, self.server_name, *args, **kwargs)

        # style = self.server_cfg.get("msg_color","")
        # for arg in args:
        #     # print(f"{Style.BRIGHT}{Fore.GREEN}{arg}{Style.RESET_ALL}")
        #     print(f"[{strftime('%H:%M:%S')}_{self.server_name}]: {style}{arg}{Style.RESET_ALL}")

    def init_endpoint_status(self, app: FastAPI):
        "Populate status dict with FastAPI server endpoints for monitoring."
        for route in app.routes:
            if route.path.startswith(f"/{self.server_name}"):
                self.status[route.name] = []
                self.endpoints.append(route.name)
        self.print_message(
            f" ... Found {len(self.status)} endpoints for status monitoring on {self.server_name}."
        )

    def get_endpoint_urls(self, app: HelaoFastAPI):
        """Return a list of all endpoints on this server."""
        url_list = []
        for route in app.routes:
            routeD = {"path": route.path, "name": route.name}
            if "dependant" in dir(route):
                flatParams = get_flat_params(route.dependant)
                paramD = {
                    par.name: {
                        "outer_type": str(par.outer_type_).split("'")[1],
                        "type": str(par.type_).split("'")[1],
                        "required": par.required,
                        "shape": par.shape,
                        "default": par.default,
                    }
                    for par in flatParams
                }
                routeD["params"] = paramD
            else:
                routeD["params"] = []
            url_list.append(routeD)
        return url_list

    async def contain_process(
        self,
        process: cProcess,
        file_type: str = "helao__file",
        file_data_keys: Optional[str] = None,  # this is also keyd by file_sample_keys
        file_sample_label: Optional[
            str
        ] = None,  # this is also keyd by file_sample_keys
        file_sample_keys: Optional[
            list
        ] = None,  # I need one key per datafile, but each datafile can still be based on multiple samples
        header: Optional[str] = None,  # this is also keyd by file_sample_keys
    ):
        self.actives[process.process_uuid] = Base.Active(
            self,
            process=process,
            file_type=file_type,
            file_data_keys=file_data_keys,
            file_sample_label=file_sample_label,
            file_sample_keys=file_sample_keys,
            header=header,
        )
        await self.actives[process.process_uuid].myinit()
        return self.actives[process.process_uuid]

    async def get_active_info(self, process_uuid: str):
        if process_uuid in self.actives.keys():
            process_dict = await self.actives[process_uuid].active.as_dict()
            return process_dict
        else:
            self.print_message(
                f" ... Specified process uuid {process_uuid} was not found.", error=True
            )
            return None

    async def get_ntp_time(self):
        "Check system clock against NIST clock for trigger operations."
        c = ntplib.NTPClient()
        response = c.request(self.ntp_server, version=3)
        self.ntp_response = response
        self.ntp_last_sync = response.orig_time
        self.ntp_offset = response.offset
        self.print_message(f" ... ntp_offset: {self.ntp_offset}")

        time_inst = await aiofiles.open("ntpLastSync.txt", "w")
        await time_inst.write(f"{self.ntp_last_sync},{self.ntp_offset}")
        await time_inst.close()
        self.print_message(
            f" ... retrieved time at {ctime(self.ntp_response.tx_timestamp)} from {self.ntp_server}"
        )

    async def attach_client(self, client_servkey: str, retry_limit=5):
        "Add client for pushing status updates via HTTP POST."
        success = False

        if client_servkey in self.world_cfg["servers"]:

            if client_servkey in self.status_clients:
                self.print_message(
                    f" ... Client {client_servkey} is already subscribed to {self.server_name} status updates."
                )
            else:
                self.status_clients.add(client_servkey)

                current_status = self.status
                for _ in range(retry_limit):
                    response = await async_private_dispatcher(
                        world_config_dict=self.world_cfg,
                        server=client_servkey,
                        private_process="update_status",
                        params_dict={
                            "server": self.server_name,
                            "status": json.dumps(current_status),
                        },
                        json_dict={},
                    )
                    if response == True:
                        self.print_message(
                            f" ... Added {client_servkey} to {self.server_name} status subscriber list."
                        )
                        success = True
                        break
                    else:
                        self.print_message(
                            f" ... Failed to add {client_servkey} to {self.server_name} status subscriber list.",
                            error=True,
                        )

            if success:
                self.print_message(
                    f" ... Updated {self.server_name} status to {current_status} on {client_servkey}."
                )
            else:
                self.print_message(
                    f" ... Failed to push status message to {client_servkey} after {retry_limit} attempts.",
                    error=True,
                )

        return success

    def detach_client(self, client_servkey: str):
        "Remove client from receiving status updates via HTTP POST"
        if client_servkey in self.status_clients:
            self.status_clients.remove(client_servkey)
            self.print_message(
                f"Client {client_servkey} will no longer receive status updates."
            )
        else:
            self.print_message(f" ... Client {client_servkey} is not subscribed.")

    async def ws_status(self, websocket: WebSocket):
        "Subscribe to status queue and send message to websocket client."
        self.print_message(" ... got new status subscriber")
        await websocket.accept()
        try:
            async for status_msg in self.status_q.subscribe():
                await websocket.send_text(json.dumps(status_msg))
        except WebSocketDisconnect:
            self.print_message(
                f" ... Status websocket client {websocket.client[0]}:{websocket.client[1]} disconnected.",
                error=True,
            )

    async def ws_data(self, websocket: WebSocket):
        "Subscribe to data queue and send messages to websocket client."
        self.print_message(" ... got new data subscriber")
        await websocket.accept()
        try:
            async for data_msg in self.data_q.subscribe():
                await websocket.send_text(json.dumps(data_msg))
        except WebSocketDisconnect:
            self.print_message(
                f" ... Data websocket client {websocket.client[0]}:{websocket.client[1]} disconnected.",
                error=True,
            )

    async def log_status_task(self, retry_limit: int = 5):
        "Self-subscribe to status queue, log status changes, POST to clients."
        self.print_message(f" ... {self.server_name} status log task created.")

        try:
            async for status_msg in self.status_q.subscribe():
                self.status.update(status_msg)
                for client_servkey in self.status_clients:
                    success = False

                    for _ in range(retry_limit):

                        response = await async_private_dispatcher(
                            world_config_dict=self.world_cfg,
                            server=client_servkey,
                            private_process="update_status",
                            params_dict={
                                "server": self.server_name,
                                "status": json.dumps(status_msg),
                            },
                            json_dict={},
                        )
                        if response == True:
                            self.print_message(
                                f" ... send status msg to {client_servkey}."
                            )
                            success = True
                            break
                        else:
                            self.print_message(
                                f" ... Failed to send status msg {client_servkey}."
                            )

                    if success:
                        self.print_message(
                            f" ... Updated {self.server_name} status to {status_msg} on {client_servkey}."
                        )
                    else:
                        self.print_message(
                            f" ... Failed to push status message to {client_servkey} after {retry_limit} attempts."
                        )

                # TODO:write to log if save_root exists
        except asyncio.CancelledError:
            self.print_message(" ... status logger task was cancelled", error=True)

    async def detach_subscribers(self):
        await self.status_q.put(StopAsyncIteration)
        await self.data_q.put(StopAsyncIteration)
        await asyncio.sleep(5)

    async def set_realtime(
        self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
    ):
        return self.set_realtime_nowait(epoch_ns=epoch_ns, offset=offset)

    def set_realtime_nowait(
        self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
    ):
        if offset is None:
            if self.ntp_offset is not None:
                offset_ns = int(np.floor(self.ntp_offset * 1e9))
            else:
                offset_ns = 0.0
        else:
            offset_ns = int(np.floor(offset * 1e9))
        if epoch_ns is None:
            real_time = time_ns() + offset_ns
        else:
            real_time = epoch_ns + offset_ns
        return real_time

    async def sync_ntp_task(self, resync_time: int = 600):
        "Regularly sync with NTP server."
        try:
            while True:
                time_inst = await aiofiles.open("ntpLastSync.txt", "r")
                ntp_last_sync = await time_inst.readline()
                await time_inst.close()
                self.ntp_last_sync = float(ntp_last_sync.strip())
                if time() - self.ntp_last_sync > resync_time:
                    await self.get_ntp_time()
                else:
                    wait_time = time() - self.ntp_last_sync
                    await asyncio.sleep(wait_time)
        except asyncio.CancelledError:
            self.print_message(" ... ntp sync task was cancelled", error=True)

    async def shutdown(self):
        await self.detach_subscribers()
        self.status_logger.cancel()
        self.ntp_syncer.cancel()

    async def write_to_prg(self, prg_dict: dict, process_group):
        process_group_timestamp = process_group.process_group_timestamp
        process_group_dir = self.get_process_group_dir(process_group)
        output_path = os.path.join(
            self.save_root, process_group_dir, f"{process_group_timestamp}.prg"
        )
        self.print_message(f" ... writing to prg: {output_path}")
        output_str = pyaml.dump(prg_dict, sort_dicts=False)
        file_instance = await aiofiles.open(output_path, mode="a+")

        if not output_str.endswith("\n"):
            output_str += "\n"

        await file_instance.write(output_str)
        await file_instance.close()

    def get_process_group_dir(self, process_group):
        """accepts process or process_group object"""
        process_group_date = process_group.process_group_timestamp.split(".")[0]
        process_group_time = process_group.process_group_timestamp.split(".")[-1]
        year_week = strftime("%y.%U", strptime(process_group_date, "%Y%m%d"))
        return os.path.join(
            year_week,
            process_group_date,
            f"{process_group_time}_{process_group.process_group_label}",
        )

    class Active(object):
        """Active process holder which wraps data queing and prc writing."""

        def __init__(
            self,
            base,  # outer instance
            process: cProcess,
            file_type: str = "helao__file",
            file_data_keys: Optional[str] = None,
            file_sample_label: Optional[str] = None,
            file_sample_keys: Optional[list] = None,
            header: Optional[str] = None,
        ):
            self.base = base
            self.process = process
            self.process.file_type = file_type
            self.process.file_group = "helao_files"
            self.process.file_data_keys = file_data_keys
            self.process.file_sample_label = file_sample_label
            self.process.header = header
            self.prc_file = None
            self.manual_prg_file = None
            self.manual = False
            self.process_group_dir = None

            if file_sample_keys is None:
                self.process.file_sample_keys = ["None"]
                self.process.file_sample_label = {
                    "None": self.process.file_sample_label
                }
                self.process.file_data_keys = {"None": self.process.file_data_keys}
                self.process.header = {"None": self.process.header}
            else:
                self.process.file_sample_keys = file_sample_keys
                if type(self.process.file_sample_keys) is not list:
                    self.process.file_sample_keys = [self.process.file_sample_keys]
                if self.process.file_sample_label is None:
                    self.process.file_sample_label = {
                        f"{file_sample_key}": None
                        for file_sample_key in self.process.file_sample_keys
                    }
                if self.process.file_data_keys is None:
                    self.process.file_data_keys = {
                        f"{file_sample_key}": None
                        for file_sample_key in self.process.file_sample_keys
                    }
                if self.process.header is None:
                    self.process.header = {
                        f"{file_sample_key}": None
                        for file_sample_key in self.process.file_sample_keys
                    }

            self.process.set_atime(offset=self.base.ntp_offset)
            self.process.gen_uuid_process(self.base.hostname)
            # signals the data logger that it got data and hlo header was written or not
            # active.finish_hlo_header should be called within the driver before
            # any data is pushed to avoid a forced header end write
            self.finished_hlo_header = dict()
            self.file_conn = dict()
            # if cProcess is not created from process_group+sequence, cProcess is independent
            if self.process.process_group_timestamp is None:
                self.manual = True
                self.base.print_message(" ... Manual Process.", info=True)
                self.process.set_dtime(offset=self.base.ntp_offset)
                self.process.gen_uuid_process_group(self.base.hostname)

            if not self.base.save_root:
                self.base.print_message(
                    " ... Root save directory not specified, cannot save process results."
                )
                self.process.save_data = False
                self.process.save_prc = False
                self.process.output_dir = None
            else:
                if self.process.save_data is None:
                    self.process.save_data = False
                if self.process.save_prc is None:
                    self.process.save_prc = False
                # cannot save data without prc
                if self.process.save_data is True:
                    self.process.save_prc = True

                self.process_group_dir = self.base.get_process_group_dir(self.process)
                self.process.output_dir = os.path.join(
                    self.process_group_dir,
                    f"{self.process.process_queue_time}__{self.process.process_server}__{self.process.process_name}__{self.process.process_uuid}",
                )

            self.data_logger = self.base.aloop.create_task(self.log_data_task())

        def update_prc_file(self):
            # need to remove swagger workaround value if present
            if "scratch" in self.process.process_params:
                del self.process.process_params["scratch"]

            if self.process.process_enum is None:
                self.process.process_enum = 0.0

            self.prc_file = prc_file(
                hlo_version=f"{hlo_version}",
                technique_name=self.process.technique_name,
                server_name=self.base.server_name,
                orchestrator=self.process.orch_name,
                machine_name=self.process.machine_name,
                access=self.process.access,
                output_dir=Path(self.process.output_dir).as_posix(),
                process_group_uuid=self.process.process_group_uuid,
                process_group_timestamp=self.process.process_group_timestamp,
                process_uuid=self.process.process_uuid,
                process_queue_time=self.process.process_queue_time,
                process_enum=self.process.process_enum,
                process_name=self.process.process_name,
                process_abbr=self.process.process_abbr,
                process_params=self.process.process_params,
            )

        async def myinit(self):
            if self.process.save_prc:
                os.makedirs(
                    os.path.join(self.base.save_root, self.process.output_dir),
                    exist_ok=True,
                )
                self.process.process_num = (
                    f"{self.process.process_abbr}-{self.process.process_enum}"
                )
                self.update_prc_file()

                if self.manual:
                    # create and write prg file for manual process
                    self.manual_prg_file = prg_file(
                        hlo_version=f"{hlo_version}",
                        orchestrator=self.process.orch_name,
                        access=self.process.access,
                        process_group_uuid=self.process.process_group_uuid,
                        process_group_timestamp=self.process.process_group_timestamp,
                        process_group_label=self.process.process_group_label,
                        technique_name=self.process.technique_name,
                        sequence_name="MANUAL",
                        sequence_params=None,
                        sequence_model=None,
                    )
                    await self.base.write_to_prg(
                        cleanupdict(self.manual_prg_file.dict()), self.process
                )

                if self.process.save_data:
                    for i, file_sample_key in enumerate(self.process.file_sample_keys):
                        filename, header, file_info = self.init_datafile(
                            header=self.process.header.get(file_sample_key, None),
                            file_type=self.process.file_type,
                            file_data_keys=self.process.file_data_keys.get(
                                file_sample_key, None
                            ),
                            file_sample_label=self.process.file_sample_label.get(
                                file_sample_key, None
                            ),
                            filename=None,  # always autogen a filename
                            file_group=self.process.file_group,
                            process_enum=self.process.process_enum,
                            process_abbr=self.process.process_abbr,
                            filenum=i,
                        )

                        self.process.file_dict.update({filename: file_info})
                        await self.set_output_file(
                            filename=filename,
                            header=header,
                            file_sample_key=file_sample_key,
                        )

            await self.add_status()

        def init_datafile(
            self,
            header,
            file_type,
            file_data_keys,
            file_sample_label,
            filename,
            file_group,
            process_enum,
            process_abbr,
            filenum: Optional[int] = 0,
        ):

            if header:
                if isinstance(header, dict):
                    header_dict = copy(header)
                    header = pyaml.dump(header, sort_dicts=False)
                    # header_lines = len(header_dict.keys())
                else:
                    if isinstance(header, list):
                        # header_lines = len(header)
                        header = "\n".join(header)
                    # else:
                    #     header_lines = len(header.split("\n"))

            file_info = {"type": file_type}
            if file_data_keys is not None:
                file_info.update({"keys": file_data_keys})
            if file_sample_label is not None:
                if len(file_sample_label) != 0:
                    file_info.update({"sample": file_sample_label})

            if filename is None:  # generate filename
                file_ext = "csv"
                if file_group == "helao_files":
                    file_ext = "hlo"

                    header_dict = {
                        "hlo_version": hlo_version,
                        "process_name": self.process.process_abbr,
                        "column_headings": file_data_keys,
                    }

                    if header is None:
                        header = pyaml.dump(header_dict, sort_dicts=False)
                    else:
                        header = pyaml.dump(header_dict, sort_dicts=False) + header
                else:  # aux_files
                    pass

                if process_enum is not None:
                    filename = (
                        f"{process_abbr}-{process_enum:.1f}__{filenum}.{file_ext}"
                    )
                else:
                    filename = f"{process_abbr}-0.0__{filenum}.{file_ext}"

            if header:
                if not header.endswith("\n"):
                    header += "\n"

            return filename, header, file_info

        def finish_hlo_header(self, realtime: Optional[int] = None):
            # needs to be a sync function
            if realtime == None:
                realtime = self.set_realtime_nowait()

            data_dict1 = dict()
            data_dict2 = dict()
            file_keys = []
            for file_key in self.file_conn.keys():
                data_dict1[file_key] = pyaml.dump({"epoch_ns": realtime})
                data_dict2[file_key] = "%%"
                file_keys.append(file_key)
                # before we push the header end onto the dataq, need to set the flag
                self.finished_hlo_header[file_key] = True

            self.enqueue_data_nowait(data_dict1, file_sample_keys=file_keys)
            self.enqueue_data_nowait(data_dict2, file_sample_keys=file_keys)

        async def add_status(self):
            self.base.status[self.process.process_name].append(
                self.process.process_uuid
            )
            self.base.print_message(
                f" ... Added {self.process.process_uuid} to {self.process.process_name} status list."
            )
            await self.base.status_q.put(
                {self.process.process_name: self.base.status[self.process.process_name]}
            )

        async def clear_status(self):
            if self.process.process_uuid in self.base.status[self.process.process_name]:
                self.base.status[self.process.process_name].remove(
                    self.process.process_uuid
                )
                self.base.print_message(
                    f" ... Removed {self.process.process_uuid} from {self.process.process_name} status list.",
                    info=True,
                )
            else:
                self.base.print_message(
                    f" ... {self.process.process_uuid} did not excist in {self.process.process_name} status list.",
                    error=True,
                )
            await self.base.status_q.put(
                {self.process.process_name: self.base.status[self.process.process_name]}
            )

        async def set_estop(self):
            self.base.status[self.process.process_name].remove(
                self.process.process_uuid
            )
            self.base.status[self.process.process_name].append(
                f"{self.process.process_uuid}__estop"
            )
            self.base.print_message(
                f" ... E-STOP {self.process.process_uuid} on {self.process.process_name} status.",
                error=True,
            )
            await self.base.status_q.put(
                {self.process.process_name: self.base.status[self.process.process_name]}
            )

        async def set_error(self, err_msg: Optional[str] = None):
            self.base.status[self.process.process_name].remove(
                self.process.process_uuid
            )
            self.base.status[self.process.process_name].append(
                f"{self.process.process_uuid}__error"
            )
            self.base.print_message(
                f" ... ERROR {self.process.process_uuid} on {self.process.process_name} status.",
                error=True,
            )
            if err_msg:
                self.process.error_code = err_msg
            else:
                self.process.error_code = "-1 unspecified error"
            await self.base.status_q.put(
                {self.process.process_name: self.base.status[self.process.process_name]}
            )

        async def set_realtime(
            self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
        ):
            # return self.set_realtime_nowait(epoch_ns=epoch_ns, offset=offset)
            return self.base.set_realtime_nowait(epoch_ns=epoch_ns, offset=offset)

        def set_realtime_nowait(
            self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
        ):
            return self.base.set_realtime_nowait(epoch_ns=epoch_ns, offset=offset)
            # if offset is None:
            #     if self.base.ntp_offset is not None:
            #         offset_ns = int(np.floor(self.base.ntp_offset * 1e9))
            #     else:
            #         offset_ns = 0.0
            # else:
            #     offset_ns = int(np.floor(offset * 1e9))
            # if epoch_ns is None:
            #     process_real_time = time_ns() + offset_ns
            # else:
            #     process_real_time = epoch_ns + offset_ns
            # return process_real_time

        async def set_output_file(
            self, filename: str, file_sample_key: str, header: Optional[str] = None
        ):
            "Set active save_path, write header if supplied."
            output_path = os.path.join(
                self.base.save_root, self.process.output_dir, filename
            )
            self.base.print_message(f" ... writing data to: {output_path}")
            # create output file and set connection
            self.file_conn[file_sample_key] = await aiofiles.open(
                output_path, mode="a+"
            )
            self.finished_hlo_header[file_sample_key] = False
            if header:
                if not header.endswith("\n"):
                    header += "\n"
                await self.file_conn[file_sample_key].write(header)

        async def write_live_data(self, output_str: str, file_conn_key):
            """Appends lines to file_conn."""
            if file_conn_key in self.file_conn:
                if self.file_conn[file_conn_key]:
                    if not output_str.endswith("\n"):
                        output_str += "\n"
                    await self.file_conn[file_conn_key].write(output_str)

        async def enqueue_data(
            self, data, errors: list = [], file_sample_keys: Optional[list] = None
        ):
            await self.base.data_q.put(
                self.assemble_data_msg(
                    data=data, errors=errors, file_sample_keys=file_sample_keys
                )
            )

        def enqueue_data_nowait(
            self, data, errors: list = [], file_sample_keys: Optional[list] = None
        ):
            self.base.data_q.put_nowait(
                self.assemble_data_msg(
                    data=data, errors=errors, file_sample_keys=file_sample_keys
                )
            )

        def assemble_data_msg(
            self, data, errors: list = [], file_sample_keys: list = None
        ):
            data_dict = dict()
            if file_sample_keys is None:
                data_dict["None"] = data
            else:
                if type(file_sample_keys) is not list:
                    file_sample_keys = [file_sample_keys]
                for file_sample_key in file_sample_keys:
                    data_dict[file_sample_key] = data.get(file_sample_key, dict())

            data_msg = {
                self.process.process_uuid: {
                    "data": data_dict,
                    "process_name": self.process.process_name,
                    "errors": errors,
                }
            }
            return data_msg

        async def log_data_task(self):
            """Self-subscribe to data queue, write to present file path."""
            self.base.print_message(" ... starting data logger")
            # data_msg should be a dict {uuid: list of values or a list of list of values}
            try:
                async for data_msg in self.base.data_q.subscribe():
                    if (
                        self.process.process_uuid in data_msg.keys()
                    ):  # only write data for this process
                        data_dict = data_msg[self.process.process_uuid]
                        data_val = data_dict["data"]
                        self.process.data.append(data_val)
                        for sample, sample_data in data_val.items():
                            if sample in self.file_conn:
                                if self.file_conn[sample]:
                                    # check if end of hlo header was writen
                                    # else force it here
                                    # e.g. just write the separator
                                    if not self.finished_hlo_header[sample]:
                                        self.base.print_message(
                                            f" ... {self.process.process_abbr} data file {sample} is missing hlo separator. Writing it.",
                                            error=True,
                                        )
                                        self.finished_hlo_header[sample] = True
                                        await self.write_live_data(
                                            output_str=pyaml.dump({"epoch_ns": None})
                                            + "%%\n",
                                            file_conn_key=sample,
                                        )

                                    if type(sample_data) is dict:
                                        await self.write_live_data(
                                            output_str=json.dumps(sample_data),
                                            file_conn_key=sample,
                                        )
                                    else:
                                        await self.write_live_data(
                                            output_str=sample_data, file_conn_key=sample
                                        )
                            else:
                                self.base.print_message(
                                    " ... {sample} doesn not exist in file_conn.",
                                    error=True,
                                )

            except asyncio.CancelledError:
                self.base.print_message(
                    " ... data logger task was cancelled", error=True
                )

        async def write_file(
            self,
            output_str: str,
            file_type: str,
            filename: Optional[str] = None,
            file_group: Optional[str] = "aux_files",
            header: Optional[str] = None,
            sample_str: Optional[str] = None,
            file_sample_label: Optional[str] = None,
            file_data_keys: Optional[str] = None,
        ):
            "Write complete file, not used with queue streaming."
            if self.process.save_data:
                filename, header, file_info = self.init_datafile(
                    header=header,
                    file_type=file_type,
                    file_data_keys=file_data_keys,
                    file_sample_label=file_sample_label,
                    filename=filename,
                    file_group=file_group,
                    process_enum=self.process.process_enum,
                    process_abbr=self.process.process_abbr,
                )
                output_path = os.path.join(
                    self.base.save_root, self.process.output_dir, filename
                )
                self.base.print_message(
                    f" ... writing non stream data to: {output_path}"
                )

                file_instance = await aiofiles.open(output_path, mode="w")
                await file_instance.write(header + output_str)
                await file_instance.close()
                self.process.file_dict.update({filename: file_info})

        def write_file_nowait(
            self,
            output_str: str,
            file_type: str,
            filename: Optional[str] = None,
            file_group: Optional[str] = "aux_files",
            header: Optional[str] = None,
            sample_str: Optional[str] = None,
            file_sample_label: Optional[str] = None,
            file_data_keys: Optional[str] = None,
        ):
            "Write complete file, not used with queue streaming."
            if self.process.save_data:
                filename, header, file_info = self.init_datafile(
                    header=header,
                    file_type=file_type,
                    file_data_keys=file_data_keys,
                    file_sample_label=file_sample_label,
                    filename=filename,
                    file_group=file_group,
                    process_enum=self.process.process_enum,
                    process_abbr=self.process.process_abbr,
                )
                output_path = os.path.join(
                    self.base.save_root, self.process.output_dir, filename
                )
                self.base.print_message(
                    f" ... writing non stream data to: {output_path}"
                )

                file_instance = open(output_path, mode="w")
                file_instance.write(header + output_str)
                file_instance.close()
                self.process.file_dict.update({filename: file_info})

        async def write_to_prc(self, prc_dict: dict):
            "Create new prc if it doesn't exist, otherwise append prc_dict to file."
            output_path = os.path.join(
                self.base.save_root,
                self.process.output_dir,
                f"{self.process.process_queue_time}.prc",
            )
            self.base.print_message(f" ... writing to prc: {output_path}")
            # self.base.print_message(" ... writing:",prc_dict)
            output_str = pyaml.dump(prc_dict, sort_dicts=False)
            file_instance = await aiofiles.open(output_path, mode="a+")

            if not output_str.endswith("\n"):
                output_str += "\n"

            await file_instance.write(output_str)
            await file_instance.close()

        async def append_sample(
            self, samples, IO: str, status: bool = None, inheritance: bool = None
        ):
            "Add sample to samples_out and samples_in dict"

            # - inheritance
            # give_only:
            # receive_only:
            # allow_both:
            # block_both:

            # - status:
            # created: pretty self-explanatory; the sample was created during the process.
            # destroyed: also self-explanatory
            # preserved: the sample exists before and after the process. e.g. an echem experiment
            # incorporated: the sample was combined with others in the process. E.g. the creation of an electrode assembly from electrodes and electrolytes
            # recovered: the opposite of incorporated. E.g. an electrode assembly is taken apart, and the original electrodes are recovered, and further experiments may be done on those electrodes

            if samples is None:
                return

            if type(samples) is not list:
                samples = [samples]

            for sample in samples:
                if inheritance is None:
                    inheritance = "allow_both"
                if status is None:
                    status = "preserved"

                append_dict = sample.prc_dict()
                if append_dict is not None:
                    if inheritance is not None:
                        append_dict.update({"inheritance": inheritance})
                    if status is not None:
                        if type(status) is not list:
                            status = [status]
                        append_dict.update({"status": status})

                    # check if list for safety reasons
                    if type(self.process.prc_samples_in) is not list:
                        self.process.prc_samples_in = []
                    if type(self.process.prc_samples_out) is not list:
                        self.process.prc_samples_out = []

                    if IO == "in":
                        self.process.prc_samples_in.append(append_dict)
                    elif IO == "out":
                        self.process.prc_samples_out.append(append_dict)

        async def finish(self):
            "Close file_conn, finish prc, copy aux, set endpoint status, and move active dict to past."
            await asyncio.sleep(1)
            self.base.print_message(" ... finishing data logging.")
            for filekey in self.file_conn.keys():
                if self.file_conn[filekey]:
                    await self.file_conn[filekey].close()
            self.file_conn = dict()
            # (1) update sample_in and sample_out
            if self.process.prc_samples_in:
                self.prc_file.samples_in = self.process.prc_samples_in
            if self.process.prc_samples_out:
                self.prc_file.samples_out = self.process.prc_samples_out
            # (2) update file dict in prc header
            if self.process.file_dict:
                self.prc_file.files = self.process.file_dict

            # write full prc header to file
            await self.write_to_prc(cleanupdict(self.prc_file.dict()))

            await self.clear_status()
            self.data_logger.cancel()
            _ = self.base.actives.pop(self.process.process_uuid, None)
            return self.process

        async def track_file(self, file_type: str, file_path: str, sample_no: str):
            "Add auxiliary files to file dictionary."
            if os.path.dirname(file_path) != os.path.join(
                self.base.save_root, self.process.output_dir
            ):
                self.process.file_paths.append(file_path)
            file_info = f"{file_type};{sample_no}"
            filename = os.path.basename(file_path)
            self.process.file_dict.update({filename: file_info})
            self.base.print_message(
                f" ... {filename} added to files_technique__{self.process.process_num} / aux_files list."
            )

        async def relocate_files(self):
            "Copy auxiliary files from folder path to prc directory."
            for x in self.process.file_paths:
                new_path = os.path.join(
                    self.base.save_root, self.process.output_dir, os.path.basename(x)
                )
                await async_copy(x, new_path)
