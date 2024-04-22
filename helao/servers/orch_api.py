import json
import time
import os
import pickle
import asyncio
from copy import copy
from enum import Enum
from socket import gethostname
from typing import Union, Optional

from fastapi import Body, WebSocket, Request
from fastapi.routing import APIRoute
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from helao.drivers.helao_driver import HelaoDriver
from helao.helpers.server_api import HelaoFastAPI
from helao.helpers.gen_uuid import gen_uuid
from helao.helpers.eval import eval_val
from helao.servers.orch import Orch
from helaocore.models.server import ActionServerModel
from helaocore.models.action import ActionModel
from helaocore.models.machine import MachineModel
from helaocore.models.orchstatus import LoopStatus
from helaocore.models.action_start_condition import ActionStartCondition as ASC
from helao.helpers.premodels import Sequence, Experiment, Action
from helao.helpers.executor import Executor
from helaocore.error import ErrorCodes
from helaocore.models.experiment import ExperimentModel
from helaocore.models.hlostatus import HloStatus
from starlette.types import Message
from starlette.responses import JSONResponse, Response

from helao.helpers import logging

global LOGGER


class OrchAPI(HelaoFastAPI):
    def __init__(
        self,
        config,
        server_key,
        server_title,
        description,
        version,
        driver_class=None,
        poller_class=None,
    ):
        super().__init__(
            helao_cfg=config,
            helao_srv=server_key,
            title=server_title,
            description=description,
            version=str(version),
        )
        self.driver = None
        LOGGER = logging.LOGGER

        async def set_body(request: Request, body: bytes):
            async def receive() -> Message:
                return {"type": "http.request", "body": body}

            request._receive = receive

        async def get_body(request: Request) -> bytes:
            body = await request.body()
            await set_body(request, body)
            return body

        @self.middleware("http")
        async def app_entry(request: Request, call_next):
            endpoint = request.url.path.strip("/").split("/")[-1]
            if request.method == "HEAD":  # comes from endpoint checker, session.head()
                LOGGER.debug("got HEAD request in middleware")
                response = Response()
            elif request.url.path.strip("/").startswith(f"{server_key}/") and request.method == "POST":
                LOGGER.debug("got action POST request in middleware")
                body_bytes = await request.body()
                body_dict = json.loads(body_bytes)
                action_dict = body_dict.get("action", {})
                start_cond = action_dict.get("start_condition", ASC.wait_for_all)
                action_dict["action_uuid"] = action_dict.get("action_uuid", gen_uuid())
                if (
                    len(self.orch.actionservermodel.endpoints[endpoint].active_dict)
                    == 0
                    or start_cond == ASC.no_wait
                ):
                    LOGGER.debug("action endpoint is available")
                    response = await call_next(request)
                else:  # collision between two base requests for one resource, queue
                    LOGGER.info("action endpoint is busy, queuing")
                    action_dict["action_params"] = action_dict.get("action_params", {})
                    action_dict["action_params"]["delayed_on_actserv"] = True
                    extra_params = {}
                    for d in (
                        request.query_params,
                        request.path_params,
                    ):
                        for k, v in d.items():
                            extra_params[k] = eval_val(v)
                    action = Action(**action_dict)
                    action.action_name = request.url.path.strip("/").split("/")[-1]
                    action.action_server = MachineModel(
                        server_name=server_key, machine_name=gethostname().lower()
                    )
                    # send active status but don't create active object
                    await self.orch.status_q.put(action.get_actmodel())
                    response = JSONResponse(action.as_dict())
                    self.orch.print_message(
                        f"simultaneous action requests for {action.action_name} received, queuing action {action.action_uuid}"
                    )
                    self.orch.endpoint_queues[endpoint].put(
                        (
                            action,
                            extra_params,
                        )
                    )
            else:
                LOGGER.debug("got non-action POST request")
                response = await call_next(request)
            return response

        @self.exception_handler(StarletteHTTPException)
        async def custom_http_exception_handler(request, exc):
            if request.url.path.strip("/").startswith(f"{server_key}/"):
                print(f"Could not process request: {repr(exc)}")
                for _, active in self.orch.actives.items():
                    active.set_estop()
                for executor_id in self.orch.executors:
                    self.orch.stop_executor(executor_id)
            return await http_exception_handler(request, exc)

        @self.on_event("startup")
        async def startup_event():
            """Run startup actions.

            When FastAPI server starts, create a global OrchHandler object,
            initiate the monitor_states coroutine which runs forever,
            and append dummy experiments to the
            experiment queue for testing.
            """
            self.orch = Orch(fastapp=self)
            
            self.orch.myinit()
            if driver_class is not None:
                if issubclass(driver_class, HelaoDriver):
                    self.driver = driver_class(config=self.server_params)
                    if poller_class is not None:
                        self.poller = poller_class(
                            self.driver, self.server_cfg.get("polling_time", 0.05)
                        )
                else:
                    self.driver = driver_class(self.orch)
            self.orch.endpoint_queues_init()

        @self.on_event("startup")
        async def add_default_head_endpoints() -> None:
            for route in self.routes:
                if isinstance(route, APIRoute) and "POST" in route.methods:
                    new_route = copy(route)
                    new_route.methods = {"HEAD"}
                    new_route.include_in_schema = False
                    self.routes.append(new_route)

        # --- BASE endpoints ---
        @self.websocket("/ws_status")
        async def websocket_status(websocket: WebSocket):
            """Subscribe to orchestrator status messages.

            Args:
            websocket: a fastapi.WebSocket object
            """
            await self.orch.ws_status(websocket)

        @self.websocket("/ws_data")
        async def websocket_data(websocket: WebSocket):
            """Subscribe to action server status dicts.

            Args:
            websocket: a fastapi.WebSocket object
            """
            await self.orch.ws_data(websocket)

        @self.websocket("/ws_live")
        async def websocket_live(websocket: WebSocket):
            """Broadcast live buffer dicts.

            Args:
            websocket: a fastapi.WebSocket object
            """
            await self.orch.ws_live(websocket)

        @self.post("/get_status", tags=["private"])
        def get_status():
            status_dict = self.orch.actionservermodel.model_dump()
            driver_status = "not_implemented"
            if isinstance(self.driver, HelaoDriver):
                resp = self.driver.get_status()
                driver_status = resp.status
            status_dict['_driver_status'] = driver_status
            return status_dict

        @self.post("/attach_client", tags=["private"])
        async def attach_client(
            client_servkey: str, client_host: str, client_port: int
        ):
            return await self.orch.attach_client(
                client_servkey, client_host, client_port
            )

        @self.post("/stop_executor", tags=["private"])
        def stop_executor(executor_id: str = ""):
            if executor_id == "":
                return {"error": "executor_id was not specified"}
            return self.orch.stop_executor(executor_id)

        @self.post("/endpoints", tags=["private"])
        def get_all_urls():
            """Return a list of all endpoints on this server."""
            return self.orch.get_endpoint_urls()

        @self.post("/get_lbuf", tags=["private"])
        def get_lbuf():
            return self.orch.live_buffer

        @self.post("/list_executors", tags=["private"])
        def list_executors():
            return list(self.orch.executors.keys())

        @self.post("/shutdown", tags=["private"])
        def post_shutdown():
            shutdown_event()

        @self.on_event("shutdown")
        def shutdown_event():
            """Run shutdown actions."""
            self.orch.print_message("Stopping operator", info=True)
            self.orch.bokehapp.stop()
            self.orch.print_message("orch shutdown", info=True)
            time.sleep(0.75)

        # --- ORCH-specific endpoints ---
        @self.post("/global_status", tags=["private"])
        def global_status():
            return self.orch.globalstatusmodel.as_json()

        @self.post("/export_queues", tags=["private"])
        def export_queues():
            save_dir = self.orch.world_cfg["root"]
            queue_dict = {
                "seq": list(self.orch.sequence_dq),
                "exp": list(self.orch.experiment_dq),
                "act": list(self.orch.action_dq),
                "active_exp": self.orch.active_experiment,
                "last_exp": self.orch.last_experiment,
                "active_seq": self.orch.active_sequence,
                "last_seq": self.orch.last_sequence,
                "active_counter": self.orch.active_seq_exp_counter,
                "last_act": self.orch.last_action_uuid,
                "last_dispatched_act": self.orch.last_dispatched_action_uuid,
                "last_50_act_uuids": self.orch.last_50_action_uuids,
            }
            save_path = os.path.join(save_dir, "STATES", "queues.pck")
            pickle.dump(queue_dict, open(save_path, "wb"))
            return save_path

        @self.post("/import_queues", tags=["private"])
        def import_queues():
            save_dir = self.orch.world_cfg["root"]
            save_path = os.path.join(save_dir, "STATES", "queues.pck")
            if os.path.exists(save_path):
                queue_dict = pickle.load(open(save_path, "rb"))
            else:
                self.orch.print_message(
                    "Exported queues.pck does not exist. Cannot restore."
                )
            if self.orch.sequence_dq or self.orch.experiment_dq or self.orch.action_dq:
                self.orch.print_message(
                    "Existing queues are not empty. Cannot restore."
                )
            else:
                self.orch.print_message("Restoring queues from saved pck.")
                for x in queue_dict["act"]:
                    self.orch.action_dq.append(x)
                for x in queue_dict["exp"]:
                    self.orch.experiment_dq.append(x)
                for x in queue_dict["seq"]:
                    self.orch.sequence_dq.append(x)
                self.orch.active_experiment = queue_dict["active_exp"]
                self.orch.last_experiment = queue_dict["last_exp"]
                self.orch.active_sequence = queue_dict["active_seq"]
                self.orch.last_sequence = queue_dict["last_seq"]
                self.orch.active_seq_exp_counter = queue_dict["active_counter"]
                self.orch.last_action_uuid = queue_dict["last_act"]
                self.orch.last_dispatched_action_uuid = queue_dict[
                    "last_dispatched_act"
                ]
                self.orch.last_50_action_uuids = queue_dict["last_50_act_uuids"]
            return save_path

        @self.post("/update_status", tags=["private"])
        async def update_status(
            actionservermodel: ActionServerModel = Body({}, embed=True)
        ):
            if actionservermodel is None:
                return False
            self.orch.print_message(
                f"orch '{self.orch.server.server_name}' "
                f"got status from "
                f"'{actionservermodel.action_server.server_name}': "
                f"{actionservermodel.endpoints}"
            )
            return await self.orch.update_status(actionservermodel=actionservermodel)

        @self.post("/clear_actives", tags=["private"])
        async def clear_actives():
            cleared_actives = []
            for actionservermodel in list(self.orch.globalstatusmodel.server_dict.values()):
                updatemodel = copy(actionservermodel)
                for endpointmodel in actionservermodel.endpoints.values():
                    active_items = list(endpointmodel.active_dict.items())
                    for uuid, statusmodel in active_items:
                        endpointmodel.active_dict.pop(uuid)
                        cleared_actives.append(uuid)
                        self.orch.globalstatusmodel.active_dict.pop(uuid)
                        if HloStatus.skipped not in endpointmodel.nonactive_dict:
                            endpointmodel[HloStatus.skipped] = {}
                        endpointmodel.nonactive_dict[HloStatus.skipped].update({uuid: statusmodel})
                await self.orch.update_status(actionservermodel=updatemodel)
            return cleared_actives 

        @self.post("/update_nonblocking", tags=["private"])
        async def update_nonblocking(
            actionmodel: ActionModel = Body({}, embed=True),
            server_host: str = "",
            server_port: int = 9000,
        ):
            self.orch.print_message(
                f"'{self.orch.server.server_name.upper()}' "
                f"got nonblocking status from "
                f"'{actionmodel.action_server.server_name}': "
                f"exec_id: {actionmodel.exec_id} -- status: {actionmodel.action_status} "
                f"on {server_host}:{server_port}"
            )
            result_dict = await self.orch.update_nonblocking(
                actionmodel, server_host, server_port
            )
            return result_dict

        @self.post("/update_globalexp_params", tags=["private"])
        async def update_globalexp_params(params: dict):
            """Updates globalexp_params for active experiment"""
            # if self.orch.active_experiment is not None:
            #     self.orch.active_experiment.globalexp_params.update(params)
            #     self.orch.print_message(f"Updated globalexp params with {params}.")
            #     return True
            # else:
            #     self.orch.print_message(
            #         "No active experiment, could not update globalexp params."
            #     )
            #     return False
            self.orch.global_params.update(params)
            return True

        @self.post("/start", tags=["private"])
        async def start():
            """Begin dispatching experiment and action queues."""
            await self.orch.start()
            return {}

        @self.post("/get_active_experiment", tags=["private"])
        def get_active_experiment():
            """Return active experiment."""
            return self.orch.active_experiment.clean_dict()

        @self.post("/get_active_sequence", tags=["private"])
        def get_active_sequence():
            """Return active sequence."""
            return self.orch.active_sequence.clean_dict()

        @self.post("/estop_orch", tags=["private"])
        async def estop_orch():
            """Emergency stop experiment and action queues, interrupt running actions."""
            if self.orch.globalstatusmodel.loop_state == LoopStatus.started:
                await self.orch.estop_loop()
            elif self.orch.globalstatusmodel.loop_state == LoopStatus.estopped:
                self.orch.print_message("orchestrator E-STOP flag already raised")
            else:
                self.orch.print_message("orchestrator is not running")
            return {}

        @self.post("/stop", tags=["private"])
        async def stop():
            """Stop dispatching experiment and action queues after current actions finish."""
            await self.orch.stop()
            return {}

        @self.post("/clear_estop", tags=["private"])
        async def clear_estop():
            """Remove emergency stop condition."""
            if self.orch.globalstatusmodel.loop_state != LoopStatus.estopped:
                self.orch.print_message("orchestrator is not currently in E-STOP")
            else:
                await self.orch.clear_estop()

        @self.post("/clear_error", tags=["private"])
        async def clear_error():
            """Remove error condition."""
            if self.orch.globalstatusmodel.loop_state != LoopStatus.error:
                self.orch.print_message("orchestrator is not currently in ERROR")
            else:
                await self.orch.clear_error()

        @self.post("/skip_experiment", tags=["private"])
        async def skip_experiment():
            """Clear the present action queue while running."""
            await self.orch.skip()
            return {}

        @self.post("/clear_actions", tags=["private"])
        async def clear_actions():
            """Clear the present action queue while stopped."""
            await self.orch.clear_actions()
            return {}

        @self.post("/clear_experiments", tags=["private"])
        async def clear_experiments():
            """Clear the present experiment queue while stopped."""
            await self.orch.clear_experiments()
            return {}

        @self.post("/append_sequence", tags=["private"])
        async def append_sequence(
            sequence: Sequence = Body({}, embed=True),
        ):
            if not isinstance(sequence, Sequence):
                sequence = Sequence(**sequence)
            seq_uuid = await self.orch.add_sequence(sequence=sequence)
            return {"sequence_uuid": seq_uuid}

        @self.post("/append_experiment", tags=["private"])
        async def append_experiment(experiment: Experiment = Body({}, embed=True)):
            """Add a experiment object to the end of the experiment queue."""
            exp_uuid = await self.orch.add_experiment(
                seq=self.orch.seq_model, experimentmodel=experiment.get_exp()
            )
            return {"experiment_uuid": exp_uuid}

        @self.post("/prepend_experiment", tags=["private"])
        async def prepend_experiment(experiment: Experiment = Body({}, embed=True)):
            """Add a experiment object to the start of the experiment queue."""
            exp_uuid = await self.orch.add_experiment(
                seq=self.orch.seq_model,
                experimentmodel=experiment.get_exp(),
                prepend=True,
            )
            return {"experiment_uuid": exp_uuid}

        @self.post("/insert_experiment", tags=["private"])
        async def insert_experiment(
            experiment: Experiment = Body({}, embed=True),
            idx: int = 0,
        ):
            """Insert a experiment object at experiment queue index."""
            exp_uuid = await self.orch.add_experiment(
                seq=self.orch.seq_model,
                experimentmodel=experiment.get_exp(),
                at_index=idx,
            )
            return {"experiment_uuid": exp_uuid}

        @self.post("/list_sequences", tags=["private"])
        def list_sequences():
            """Return the current list of sequences."""
            return self.orch.list_sequences()

        @self.post("/list_experiments", tags=["private"])
        def list_experiments():
            """Return the current list of experiments."""
            return self.orch.list_experiments()

        @self.post("/active_experiment", tags=["private"])
        def active_experiment():
            """Return the active experiment."""
            return self.orch.get_experiment(last=False)

        @self.post("/last_experiment", tags=["private"])
        def last_experiment():
            """Return the last experiment."""
            return self.orch.get_experiment(last=True)

        @self.post("/list_actions", tags=["private"])
        def list_actions():
            """Return the current list of actions."""
            return self.orch.list_actions()

        @self.post("/list_active_actions", tags=["private"])
        def list_active_actions():
            """Return the current list of actions."""
            return self.orch.list_active_actions()

        @self.post("/list_nonblocking", tags=["private"])
        def list_non_blocking():
            return self.orch.nonblocking

        @self.post("/get_orch_state", tags=["private"])
        def get_orch_state() -> dict:
            """Get orchestrator and loop status.

            Orch states: ["error", "idle", "busy", "estop"]
            Loop states: ["started", "stopped", "estopped"]
            Loop intents: ["stop", "skip", "estop", "none"]
            """

            resp = {
                "orch_state": self.orch.globalstatusmodel.orch_state,
                "loop_state": self.orch.globalstatusmodel.loop_state,
                "loop_intent": self.orch.globalstatusmodel.loop_intent,
            }

            active_seq = self.orch.get_sequence()
            last_seq = self.orch.get_sequence(last=True)
            active_exp = self.orch.get_experiment()
            last_exp = self.orch.get_experiment(last=True)

            resp["active_sequence"] = active_seq.clean_dict() if active_seq else {}
            resp["last_sequence"] = last_seq.clean_dict() if last_seq else {}
            resp["active_experiment"] = active_exp.clean_dict() if active_exp else {}
            resp["last_experiment"] = last_exp.clean_dict() if last_exp else {}

            return resp

        @self.post(f"/{server_key}/wait", tags=["action"])
        async def wait(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            waittime: float = 10.0,
        ):
            """Sleep action"""
            active = await self.orch.setup_and_contain_action()
            active.action.action_abbr = "wait"
            executor = WaitExec(
                active=active,
                oneoff=False,
            )
            active_action_dict = active.start_executor(executor)
            return active_action_dict

        @self.post(f"/{server_key}/cancel_wait", tags=["action"])
        async def cancel_wait(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
        ):
            """Stop sleep action."""
            active = await self.orch.setup_and_contain_action()
            for exec_id, executor in self.orch.executors.items():
                if exec_id.split()[0] == "wait":
                    executor.stop_action_task()
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.post(f"/{server_key}/interrupt", tags=["action"])
        async def interrupt(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            reason: str = "wait",
        ):
            """Stop dispatch loop for planned manual intervention."""
            active = await self.orch.setup_and_contain_action()
            self.orch.current_stop_message = active.action.action_params["reason"]
            await self.orch.stop()
            await self.orch.update_operator(True)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.post(f"/{server_key}/estop", tags=["action"])
        async def estop(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            switch: bool = True,
        ):
            active = await self.orch.setup_and_contain_action(
                json_data_keys=["estop"], action_abbr="estop"
            )
            has_estop = getattr(self.driver, "estop", None)
            if has_estop is not None and callable(has_estop):
                self.orch.print_message("driver has estop function", info=True)
                await active.enqueue_data_dflt(
                    datadict={
                        "estop": await self.driver.estop(**active.action.action_params)
                    }
                )
            else:
                self.orch.print_message("driver has NO estop function", info=True)
                self.orch.actionservermodel.estop = switch
            if switch:
                active.action.action_status.append(HloStatus.estopped)
            for k in self.orch.executors:
                self.orch.stop_executor(k)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.post(f"/{server_key}/conditional_exp", tags=["action"])
        async def conditional_exp(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            check_parameter: Optional[str] = "",
            check_condition: checkcond = checkcond.equals,
            check_value: Union[float, int, bool] = True,
            conditional_experiment_name: str = "",
            conditional_experiment_params: dict = {},
        ):
            """Enqueue next experiment if condition is met."""
            active = await self.orch.setup_and_contain_action()
            experiment_model = ExperimentModel(
                experiment_name=active.action.action_params[
                    "conditional_experiment_name"
                ],
                experiment_params=active.action.action_params[
                    "conditional_experiment_params"
                ],
            )
            cond = active.action.action_params["check_condition"]
            param = active.action.action_params.get(
                active.action.action_params["check_parameter"], None
            )
            thresh = active.action.action_params["check_value"]
            check = False
            if cond == checkcond.equals:
                check = param == thresh
            elif cond == checkcond.above:
                check = param > thresh
            elif cond == checkcond.below:
                check = param < thresh
            elif cond == checkcond.isnot:
                check = param != thresh
            elif cond == checkcond.uncond:
                check = True
            elif cond is None:
                check = False

            if check:
                await self.orch.add_experiment(
                    seq=self.orch.seq_model,
                    experimentmodel=experiment_model,
                    prepend=True,
                )
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.post(f"/{server_key}/conditional_stop", tags=["action"])
        async def conditional_stop(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            stop_parameter: Optional[str] = "",
            stop_condition: checkcond = checkcond.equals,
            stop_value: Union[str, float, int, bool] = True,
            reason: str = "conditional stop",
        ):
            """Stop and clear all orch queues if condition is met."""
            active = await self.orch.setup_and_contain_action()
            cond = active.action.action_params["stop_condition"]
            param = active.action.action_params.get(
                active.action.action_params["stop_parameter"], None
            )
            thresh = active.action.action_params["stop_value"]
            stop = False
            if cond == checkcond.equals:
                stop = param == thresh
            elif cond == checkcond.above:
                stop = param > thresh
            elif cond == checkcond.below:
                stop = param < thresh
            elif cond == checkcond.isnot:
                stop = param != thresh
            elif cond == checkcond.uncond:
                stop = True
            elif cond is None:
                stop = False

            if stop:
                await self.orch.clear_actions()
                await self.orch.clear_experiments()
                await self.orch.clear_sequences()
                self.orch.current_stop_message = active.action.action_params["reason"]
                await self.orch.update_operator(True)

            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.post(f"/{server_key}/add_globalexp_param", tags=["action"])
        async def add_globalexp_param(
            action: Action = Body({}, embed=True),
            param_name: str = "globalexp_param_test",
            param_value: Union[str, float, int, bool] = True,
        ):
            active = await self.orch.setup_and_contain_action()
            pdict = {
                active.action.action_params["param_name"]: active.action.action_params[
                    "param_value"
                ]
            }
            active.action.action_params.update(pdict)
            active.action.to_globalexp_params = list(pdict.keys())
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.post("/_raise_exception", tags=["private"])
        def _raise_exception():
            raise Exception("test exception for error recovery debugging")

        @self.post("/_raise_async_exception", tags=["private"])
        async def _raise_async_exception():
            async def sleep_then_error():
                print(f'Start time: {time.time()}')
                await asyncio.sleep(10)
                print(f'End time: {time.time()}')
                raise Exception("test async exception for error recovery debugging")
            loop = asyncio.get_running_loop()
            loop.create_task(sleep_then_error())
            return True

        @self.post("/clear_global_params", tags=["private"])
        def clear_global_params():
            current_params = list(self.orch.global_params.keys())
            self.orch.global_params = {}
            if current_params:
                return "\n".join(["removed:"] + current_params)
            else:
                return "global_params was empty"

        @self.post("/get_global_params", tags=["private"])
        def get_global_params():
            return self.orch.global_params

class WaitExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.active.base.print_message("WaitExec initialized.")
        self.poll_rate = 0.01
        self.duration = self.active.action.action_params.get("waittime", -1)
        self.print_every_secs = kwargs.get("print_every_secs", 5)
        self.start_time = time.time()
        self.last_print_time = self.start_time

    async def _exec(self):
        self.active.base.print_message(f" ... wait action: {self.duration}")
        return {"data": {}, "error": ErrorCodes.none}

    async def _poll(self):
        """Read analog inputs from live buffer."""
        check_time = time.time()
        elapsed_time = check_time - self.start_time
        if check_time - self.last_print_time > self.print_every_secs - 0.01:
            self.active.base.print_message(
                f" ... orch waited {elapsed_time:.1f} sec / {self.duration:.1f} sec"
            )
            self.last_print_time = check_time
        if (self.duration < 0) or (elapsed_time < self.duration):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.001)
        return {"error": ErrorCodes.none, "status": status}

    async def _post_exec(self):
        self.active.base.print_message(" ... wait action done")
        return {"error": ErrorCodes.none}


class checkcond(str, Enum):
    equals = "equals"
    below = "below"
    above = "above"
    isnot = "isnot"
    uncond = "uncond"
