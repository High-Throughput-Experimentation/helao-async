import asyncio
import json
import os
import sys
from collections import defaultdict, deque
from copy import copy
from math import floor
from pathlib import Path
from socket import gethostname
from time import ctime, strftime, strptime, time, time_ns
from typing import Optional, Union

import aiofiles
import aiohttp
import colorama
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
from helao.core.model import (
    prc_file,
    prg_file,
    return_process,
    return_process_group,
    return_process_group_list,
    return_process_list,
)
from helao.core.schema import cProcess, cProcess_group

from .api import HelaoFastAPI
from .base import Base
from .dispatcher import async_private_dispatcher, async_process_dispatcher
from .import_sequences import import_sequences
from .process_start_condition import process_start_condition
from .version import hlo_version

# ANSI color codes converted to the Windows versions
colorama.init(strip=not sys.stdout.isatty())  # strip colors if stdout is redirected
# colorama.init()


class Orch(Base):
    """Base class for async orchestrator with trigger support and pushed status update.

    Websockets are not used for critical communications. Orch will attach to all process
    servers listed in a config and maintain a dict of {serverName: status}, which is
    updated by POST requests from process servers. Orch will simultaneously dispatch as
    many process_dq as possible in process queue until it encounters any of the following
    conditions:
      (1) last executed process is final process in queue
      (2) last executed process is blocking
      (3) next process to execute is preempted
      (4) next process is on a busy process server
    which triggers a temporary async task to monitor the process server status dict until
    all conditions are cleared.

    POST requests from process servers are added to a multisubscriber queue and consumed
    by a self-subscriber task to update the process server status dict and log changes.
    """

    def __init__(self, fastapp: HelaoFastAPI):
        super().__init__(fastapp)
        self.process_lib = import_sequences(
            world_config_dict=self.world_cfg,
            library_path=None,
            server_name=self.server_name,
        )
        # instantiate process_group/experiment queue, process queue
        self.process_group_dq = deque([])
        self.process_dq = deque([])
        self.dispatched_processes = {}
        self.active_process_group = None
        self.last_process_group = None
        self.prg_file = None

        # compilation of process server status dicts
        self.global_state_dict = defaultdict(lambda: defaultdict(list))
        self.global_state_dict["_internal"]["async_process_dispatcher"] = []
        self.global_q = MultisubscriberQueue()  # passes global_state_dict dicts
        self.dispatch_q = self.global_q.queue()

        # global state of all instruments as string [idle|busy] independent of dispatch loop
        self.global_state_str = None

        # uuid lists for estop and error tracking used by update_global_state_task
        self.error_uuids = []
        self.estop_uuids = []
        self.running_uuids = []

        self.init_success = False  # need to subscribe to all fastapi servers in config
        # present dispatch loop state [started|stopped]
        self.loop_state = "stopped"

        # separate from global state, signals dispatch loop control [skip|stop|None]
        self.loop_intent = None

        # pointer to dispatch_loop_task
        self.loop_task = None
        self.status_subscriber = asyncio.create_task(self.subscribe_all())
        self.status_subscriber = asyncio.create_task(self.update_global_state_task())

    async def check_dispatch_queue(self):
        val = await self.dispatch_q.get()
        while not self.dispatch_q.empty():
            val = await self.dispatch_q.get()
        return val

    async def check_wait_for_all_processes(self):
        running_states, _ = await self.check_global_state()
        global_free = len(running_states) == 0
        self.print_message(f" ... check len(running_states): {len(running_states)}")
        return global_free

    async def subscribe_all(self, retry_limit: int = 5):
        """Subscribe to all fastapi servers in config."""
        fails = []
        for serv_key, serv_dict in self.world_cfg["servers"].items():
            if "fast" in serv_dict.keys():
                self.print_message(f" ... trying to subscribe to {serv_key} status")

                success = False
                for _ in range(retry_limit):
                    response = await async_private_dispatcher(
                        world_config_dict=self.world_cfg,
                        server=serv_key,
                        private_process="attach_client",
                        params_dict={"client_servkey": self.server_name},
                        json_dict={},
                    )
                    if response == True:
                        success = True
                        break

                serv_addr = serv_dict["host"]
                serv_port = serv_dict["port"]
                if success:
                    self.print_message(
                        f"Subscribed to {serv_key} at {serv_addr}:{serv_port}"
                    )
                else:
                    fails.append(serv_key)
                    self.print_message(
                        f" ... Failed to subscribe to {serv_key} at {serv_addr}:{serv_port}. Check connection."
                    )

        if len(fails) == 0:
            self.init_success = True
        else:
            self.print_message(
                " ... Orchestrator cannot process process_group_dq unless all FastAPI servers in config file are accessible."
            )

    async def update_status(self, process_serv: str, status_dict: dict):
        """Dict update method for process server to push status messages.

        Async task for updating orch status dict {process_serv_key: {act_name: [act_uuid]}}
        """
        last_dict = self.global_state_dict[process_serv]
        for act_name, acts in status_dict.items():
            if set(acts) != set(last_dict[act_name]):
                started = set(acts).difference(last_dict[act_name])
                removed = set(last_dict[act_name]).difference(acts)
                ongoing = set(acts).intersection(last_dict[act_name])
                if removed:
                    self.print_message(
                        f" ... '{process_serv}:{act_name}' finished {','.join(removed)}"
                    )
                if started:
                    self.print_message(
                        f" ... '{process_serv}:{act_name}' started {','.join(started)}"
                    )
                if ongoing:
                    self.print_message(
                        f" ... '{process_serv}:{act_name}' ongoing {','.join(ongoing)}"
                    )
        self.global_state_dict[process_serv].update(status_dict)
        await self.global_q.put(self.global_state_dict)
        return True

    async def update_global_state(self, status_dict: dict):
        _running_uuids = []
        for process_serv, act_named in status_dict.items():
            for act_name, uuids in act_named.items():
                for myuuid in uuids:
                    uuid_tup = (process_serv, act_name, myuuid)
                    if myuuid.endswith("__estop"):
                        self.estop_uuids.append(uuid_tup)
                    elif myuuid.endswith("__error"):
                        self.error_uuids.append(uuid_tup)
                    else:
                        _running_uuids.append(uuid_tup)
        self.running_uuids = _running_uuids

    async def update_global_state_task(self):
        """Self-subscribe to global_q and update status dict."""
        async for status_dict in self.global_q.subscribe():
            await self.update_global_state(status_dict)
            running_states, _ = await self.check_global_state()
            if self.estop_uuids and self.loop_state == "started":
                await self.estop_loop()
            elif self.error_uuids and self.loop_state == "started":
                self.global_state_str = "error"
            elif len(running_states) == 0:
                self.global_state_str = "idle"
            else:
                self.global_state_str = "busy"
                self.print_message(f" ... running_states: {running_states}")

    async def check_global_state(self):
        """Return global state of process servers."""
        running_states = []
        idle_states = []
        # self.print_message(" ... checking global state:")
        # self.print_message(self.global_state_dict.items())
        for process_serv, act_dict in self.global_state_dict.items():
            self.print_message(f" ... checking {process_serv} state")
            for act_name, act_uuids in act_dict.items():
                if len(act_uuids) == 0:
                    idle_states.append(f"{process_serv}:{act_name}")
                else:
                    running_states.append(f"{process_serv}:{act_name}:{len(act_uuids)}")
            await asyncio.sleep(
                0.001
            )  # allows status changes to affect between process_dq, also enforce unique timestamp
        return running_states, idle_states

    async def dispatch_loop_task(self):
        """Parse process_group and process queues, and dispatch process_dq while tracking run state flags."""
        self.print_message(" ... running operator orch")
        self.print_message(f" ... orch status: {self.global_state_str}")
        # clause for resuming paused process list
        self.print_message(f" ... orch descisions: {self.process_group_dq}")
        try:
            self.loop_state = "started"
            while self.loop_state == "started" and (
                self.process_dq or self.process_group_dq
            ):
                self.print_message(
                    f" ... current content of process_dq: {self.process_dq}"
                )
                self.print_message(
                    f" ... current content of process_group_dq: {self.process_group_dq}"
                )
                await asyncio.sleep(
                    0.001
                )  # allows status changes to affect between process_dq, also enforce unique timestamp
                if not self.process_dq:
                    self.print_message(" ... getting process_dq from new process_group")
                    # generate uids when populating, generate timestamp when acquring
                    self.last_process_group = copy(self.active_process_group)
                    self.active_process_group = self.process_group_dq.popleft()
                    self.active_process_group.technique_name = self.technique_name
                    self.active_process_group.machine_name = self.hostname
                    self.active_process_group.set_dtime(offset=self.ntp_offset)
                    self.active_process_group.gen_uuid_process_group(self.hostname)
                    sequence = self.active_process_group.sequence
                    # additional sequence params should be stored in process_group.sequence_pars
                    unpacked_acts = self.process_lib[sequence](
                        self.active_process_group
                    )
                    for i, act in enumerate(unpacked_acts):
                        act.process_enum = float(i)  # f"{i}"
                        # act.gen_uuid()
                    # TODO:update sequence code
                    self.process_dq = deque(unpacked_acts)
                    self.dispatched_processes = {}
                    self.print_message(f" ... got: {self.process_dq}")
                    self.print_message(
                        f" ... optional params: {self.active_process_group.sequence_pars}"
                    )

                    self.prg_file = prg_file(
                        hlo_version=f"{hlo_version}",
                        orchestrator=self.active_process_group.orch_name,
                        access="hte",
                        process_group_uuid=self.active_process_group.process_group_uuid,
                        process_group_timestamp=self.active_process_group.process_group_timestamp,
                        process_group_label=self.active_process_group.process_group_label,
                        technique_name=self.active_process_group.technique_name,
                        sequence_name=self.active_process_group.sequence,
                        sequence_params=self.active_process_group.sequence_pars,
                        sequence_model=None,
                    )
                    await self.write_active_process_group_prg()

                else:
                    if self.loop_intent == "stop":
                        self.print_message(" ... stopping orchestrator")
                        # monitor status of running process_dq, then end loop
                        # async for _ in self.global_q.subscribe():
                        while True:
                            _ = await self.check_dispatch_queue()
                            if self.global_state_str == "idle":
                                self.loop_state = "stopped"
                                await self.intend_none()
                                break
                    elif self.loop_intent == "skip":
                        # clear process queue, forcing next process_group
                        self.process_dq.clear()
                        await self.intend_none()
                        self.print_message(" ... skipping to next process_group")
                    else:
                        # all process blocking is handled like preempt, check cProcess requirements
                        A = self.process_dq.popleft()
                        # append previous results to current process
                        A.result_dict = self.active_process_group.result_dict

                        # see async_process_dispatcher for unpacking
                        if isinstance(A.start_condition, int):
                            if A.start_condition == process_start_condition.no_wait:
                                self.print_message(
                                    " ... orch is dispatching an unconditional process"
                                )
                            else:
                                if (
                                    A.start_condition
                                    == process_start_condition.wait_for_endpoint
                                ):
                                    self.print_message(
                                        " ... orch is waiting for endpoint to become available"
                                    )
                                    # async for _ in self.global_q.subscribe():
                                    while True:
                                        _ = await self.check_dispatch_queue()
                                        endpoint_free = (
                                            len(
                                                self.global_state_dict[
                                                    A.process_server
                                                ][A.process_name]
                                            )
                                            == 0
                                        )
                                        if endpoint_free:
                                            break
                                elif (
                                    A.start_condition
                                    == process_start_condition.wait_for_server
                                ):
                                    self.print_message(
                                        " ... orch is waiting for server to become available"
                                    )
                                    # async for _ in self.global_q.subscribe():
                                    while True:
                                        _ = await self.check_dispatch_queue()
                                        server_free = all(
                                            [
                                                len(uuid_list) == 0
                                                for _, uuid_list in self.global_state_dict[
                                                    A.process_server
                                                ].items()
                                            ]
                                        )
                                        if server_free:
                                            break
                                else:  # start_condition is 3 or unsupported value
                                    self.print_message(
                                        " ... orch is waiting for all process_dq to finish"
                                    )
                                    if not await self.check_wait_for_all_processes():
                                        while True:
                                            _ = await self.check_dispatch_queue()
                                            if (
                                                await self.check_wait_for_all_processes()
                                            ):
                                                break
                                    else:
                                        self.print_message(" ... global_free is true")
                        elif isinstance(A.start_condition, dict):
                            self.print_message(
                                " ... waiting for multiple conditions on external servers"
                            )
                            condition_dict = A.start_condition
                            # async for _ in self.global_q.subscribe():
                            while True:
                                _ = await self.check_dispatch_queue()
                                conditions_free = all(
                                    [
                                        len(self.global_state_dict[k][v] == 0)
                                        for k, vlist in condition_dict.items()
                                        if vlist and isinstance(vlist, list)
                                        for v in vlist
                                    ]
                                    + [
                                        len(uuid_list) == 0
                                        for k, v in condition_dict.items()
                                        if v == [] or v is None
                                        for _, uuid_list in self.global_state_dict[
                                            k
                                        ].items()
                                    ]
                                )
                                if conditions_free:
                                    break
                        else:
                            self.print_message(
                                " ... invalid start condition, waiting for all process_dq to finish"
                            )
                            # async for _ in self.global_q.subscribe():
                            while True:
                                _ = await self.check_dispatch_queue()
                                if await self.check_wait_for_all_processes():
                                    break

                        self.print_message(" ... copying global vars to process")

                        # copy requested global param to process params
                        for k, v in A.from_global_params.items():
                            self.print_message(f"{k}:{v}")
                            if k in self.active_process_group.global_params.keys():
                                A.process_params.update(
                                    {v: self.active_process_group.global_params[k]}
                                )

                        self.print_message(" ... dispatching process", A.as_dict())
                        self.print_message(
                            f" ... dispatching process {A.process_name} on server {A.process_server}"
                        )
                        # keep running list of dispatched processes
                        self.dispatched_processes[A.process_enum] = copy(A)
                        result = await async_process_dispatcher(self.world_cfg, A)
                        self.active_process_group.result_dict[A.process_enum] = result

                        self.print_message(
                            " ... copying global vars back to process_group"
                        )
                        # self.print_message(result)
                        if "to_global_params" in result:
                            for k in result["to_global_params"]:
                                if k in result["process_params"].keys():
                                    if (
                                        result["process_params"][k] is None
                                        and k
                                        in self.active_process_group.global_params.keys()
                                    ):
                                        self.active_process_group.global_params.pop(k)
                                    else:
                                        self.active_process_group.global_params.update(
                                            {k: result["process_params"][k]}
                                        )
                        self.print_message(
                            " ... done copying global vars back to process_group"
                        )

            self.print_message(" ... process_group queue is empty")
            self.print_message(" ... stopping operator orch")
            self.loop_state = "stopped"
            await self.intend_none()
            return True
        # except asyncio.CancelledError:
        #     self.print_message(" ... serious orch exception occurred",error = True)
        #     return False
        except Exception as e:
            self.print_message(" ... serious orch exception occurred", error=True)
            self.print_message(f"ERROR: {e}", error=True)
            return False

    async def start_loop(self):
        if self.loop_state == "stopped":
            self.loop_task = asyncio.create_task(self.dispatch_loop_task())
        elif self.loop_state == "E-STOP":
            self.print_message(
                " ... E-STOP flag was raised, clear E-STOP before starting."
            )
        else:
            self.print_message(" ... loop already started.")
        return self.loop_state

    async def estop_loop(self):
        self.loop_state = "E-STOP"
        self.loop_task.cancel()
        await self.force_stop_running_process_q()
        await self.intend_none()

    async def force_stop_running_process_q(self):
        running_uuids = []
        estop_uuids = []
        for process_serv, act_named in self.global_state_dict.items():
            for act_name, uuids in act_named.items():
                for myuuid in uuids:
                    uuid_tup = (process_serv, act_name, myuuid)
                    if myuuid.endswith("__estop"):
                        estop_uuids.append(uuid_tup)
                    else:
                        running_uuids.append(uuid_tup)
        running_servers = list(set([serv for serv, _, _ in running_uuids]))
        for serv in running_servers:
            serv_conf = self.world_cfg["servers"][serv]
            async with aiohttp.ClientSession() as session:
                self.print_message(f" ... Sending force-stop request to {serv}")
                async with session.post(
                    f"http://{serv_conf['host']}:{serv_conf['port']}/force_stop"
                ) as resp:
                    response = await resp.text()
                    self.print_message(response)

    async def intend_skip(self):
        await asyncio.sleep(0.001)
        self.loop_intent = "skip"

    async def intend_stop(self):
        await asyncio.sleep(0.001)
        self.loop_intent = "stop"

    async def intend_none(self):
        await asyncio.sleep(0.001)
        self.loop_intent = None

    async def clear_estate(self, clear_estop=True, clear_error=True):
        if not clear_estop and not clear_error:
            self.print_message(
                " ... both clear_estop and clear_error parameters are False, nothing to clear"
            )
        cleared_status = copy(self.global_state_dict)
        if clear_estop:
            for serv, process, myuuid in self.estop_uuids:
                self.print_message(f" ... clearing E-STOP {process} on {serv}")
                cleared_status[serv][process] = cleared_status[serv][process].remove(
                    myuuid
                )
        if clear_error:
            for serv, process, myuuid in self.error_uuids:
                self.print_message(f" ... clearing error {process} on {serv}")
                cleared_status[serv][process] = cleared_status[serv][process].remove(
                    myuuid
                )
        await self.global_q.put(cleared_status)
        self.print_message(" ... resetting dispatch loop state")
        self.loop_state = "stopped"
        self.print_message(
            f" ... {len(self.running_uuids)} running process_dq did not fully stop after E-STOP/error was raised"
        )

    async def add_process_group(
        self,
        orch_name: str = None,
        process_group_label: str = None,
        sequence: str = None,
        sequence_pars: dict = {},
        result_dict: dict = {},
        access: str = "hte",
        prepend: Optional[bool] = False,
        at_index: Optional[int] = None,
    ):

        D = cProcess_group(
            {
                "orch_name": orch_name,
                "process_group_label": process_group_label,
                "sequence": sequence,
                "sequence_pars": sequence_pars,
                "result_dict": result_dict,
                "access": access,
            }
        )

        # reminder: process_group_dict values take precedence over keyword args but we grab
        # active or last process_group label if process_group_label is not specified
        if D.orch_name is None:
            D.orch_name = self.server_name
        if process_group_label is None:
            if self.active_process_group is not None:
                active_label = self.active_process_group.process_group_label
                self.print_message(
                    f" ... process_group_label not specified, inheriting {active_label} from active process_group"
                )
                D.process_group_label = active_label
            elif self.last_process_group is not None:
                last_label = self.last_process_group.process_group_label
                self.print_message(
                    f" ... process_group_label not specified, inheriting {last_label} from previous process_group"
                )
                D.process_group_label = last_label
            else:
                self.print_message(
                    " ... process_group_label not specified, no past process_group_dq to inherit so using default 'nolabel"
                )
        await asyncio.sleep(0.001)
        if at_index:
            self.process_group_dq.insert(i=at_index, x=D)
        elif prepend:
            self.process_group_dq.appendleft(D)
            self.print_message(
                f" ... process_group {D.process_group_uuid} prepended to queue"
            )
        else:
            self.process_group_dq.append(D)
            self.print_message(
                f" ... process_group {D.process_group_uuid} appended to queue"
            )

    def list_process_groups(self):
        """Return the current queue of process_group_dq."""

        process_group_list = [
            return_process_group(
                index=i,
                uid=process_group.process_group_uuid,
                label=process_group.process_group_label,
                sequence=process_group.sequence,
                pars=process_group.sequence_pars,
                access=process_group.access,
            )
            for i, process_group in enumerate(self.process_group_dq)
        ]
        retval = return_process_group_list(process_groups=process_group_list)
        return retval

    def get_process_group(self, last=False):
        """Return the active or last process_group."""
        if last:
            process_group = self.last_process_group
        else:
            process_group = self.active_process_group
        if process_group is not None:
            process_group_list = [
                return_process_group(
                    index=-1,
                    uid=process_group.process_group_uuid,
                    label=process_group.process_group_label,
                    sequence=process_group.sequence,
                    pars=process_group.sequence_pars,
                    access=process_group.access,
                )
            ]
        else:
            process_group_list = [
                return_process_group(
                    index=-1,
                    uid=None,
                    label=None,
                    sequence=None,
                    pars=None,
                    access=None,
                )
            ]
        retval = return_process_group_list(process_groups=process_group_list)
        return retval

    def list_active_processes(self):
        """Return the current queue running processes."""
        process_list = []
        index = 0
        for process_serv, process_dict in self.global_state_dict.items():
            for process_name, process_uuids in process_dict.items():
                for process_uuid in process_uuids:
                    process_list.append(
                        return_process(
                            index=index,
                            uid=process_uuid,
                            server=process_serv,
                            process=process_name,
                            pars=dict(),
                            preempt=-1,
                        )
                    )
                    index = index + 1
        retval = return_process_list(processes=process_list)
        return retval

    def list_processes(self):
        """Return the current queue of process_dq."""
        process_list = [
            return_process(
                index=i,
                uid=process.process_uuid,
                server=process.process_server,
                process=process.process_name,
                pars=process.process_params,
                preempt=process.start_condition,
            )
            for i, process in enumerate(self.process_dq)
        ]
        retval = return_process_list(processes=process_list)
        return retval

    def supplement_error_process(self, check_uuid: str, sup_process: cProcess):
        """Insert process at front of process queue with subversion of errored process, inherit parameters if desired."""
        if self.error_uuids == []:
            self.print_message("There are no error statuses to replace")
        else:
            matching_error = [tup for tup in self.error_uuids if tup[2] == check_uuid]
            if matching_error:
                _, _, error_uuid = matching_error[0]
                EA = [
                    A
                    for _, A in self.dispatched_processes.items()
                    if A.process_uuid == error_uuid
                ][0]
                # up to 99 supplements
                new_enum = round(EA.process_enum + 0.01, 2)
                new_process = sup_process
                new_process.process_enum = new_enum
                self.process_dq.appendleft(new_process)
            else:
                self.print_message(
                    f"uuid {check_uuid} not found in list of error statuses:"
                )
                self.print_message(", ".join(self.error_uuids))

    def remove_process_group(
        self, by_index: Optional[int] = None, by_uuid: Optional[str] = None
    ):
        """Remove process_group in list by enumeration index or uuid."""
        if by_index:
            i = by_index
        elif by_uuid:
            i = [
                i
                for i, D in enumerate(list(self.process_group_dq))
                if D.process_group_uuid == by_uuid
            ][0]
        else:
            self.print_message(
                "No arguments given for locating existing process_group to remove."
            )
            return None
        del self.process_group_dq[i]

    def replace_process(
        self,
        sup_process: cProcess,
        by_index: Optional[int] = None,
        by_uuid: Optional[str] = None,
        by_enum: Optional[Union[int, float]] = None,
    ):
        """Substitute a queued process."""
        if by_index:
            i = by_index
        elif by_uuid:
            i = [
                i
                for i, A in enumerate(list(self.process_dq))
                if A.process_uuid == by_uuid
            ][0]
        elif by_enum:
            i = [
                i
                for i, A in enumerate(list(self.process_dq))
                if A.process_enum == by_enum
            ][0]
        else:
            self.print_message(
                "No arguments given for locating existing process to replace."
            )
            return None
        current_enum = self.process_dq[i].process_enum
        new_process = sup_process
        new_process.process_enum = current_enum
        self.process_dq.insert(i, new_process)
        del self.process_dq[i + 1]

    def append_process(self, sup_process: cProcess):
        """Add process to end of current process queue."""
        if len(self.process_dq) == 0:
            last_enum = floor(max(list(self.dispatched_processes.keys())))
        else:
            last_enum = floor(self.process_dq[-1].process_enum)
        new_enum = int(last_enum + 1)
        new_process = sup_process
        new_process.process_enum = new_enum
        self.process_dq.append(new_process)

    async def write_active_process_group_prg(self):
        if self.prg_file is not None:
            await self.write_to_prg(
                cleanupdict(self.prg_file.dict()), self.active_process_group
            )
        self.prg_file = None

    async def shutdown(self):
        await self.detach_subscribers()
        self.status_logger.cancel()
        self.ntp_syncer.cancel()
        self.status_subscriber.cancel()
