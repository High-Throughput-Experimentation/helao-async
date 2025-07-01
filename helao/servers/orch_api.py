import json
import time
import asyncio
from copy import copy
from enum import Enum
from socket import gethostname
from typing import Union, Optional, List
from collections import namedtuple

from fastapi import Body, WebSocket, Request
from fastapi.routing import APIRoute
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from helao.drivers.helao_driver import HelaoDriver
from helao.helpers.server_api import HelaoFastAPI
from helao.helpers.gen_uuid import gen_uuid
from helao.helpers.eval import eval_val
from helao.servers.orch import Orch
from helao.core.models.server import ActionServerModel
from helao.core.models.machine import MachineModel
from helao.core.models.orchstatus import LoopStatus
from helao.core.models.action_start_condition import ActionStartCondition as ASC
from helao.helpers.premodels import Sequence, Experiment, Action
from helao.helpers.executor import Executor
from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from starlette.types import Message
from starlette.responses import JSONResponse, Response

from helao.helpers import helao_logging as logging

global LOGGER
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER


class OrchAPI(HelaoFastAPI):
    orch: Orch

    def __init__(
        self,
        server_key,
        server_title,
        description,
        version,
        driver_classes=None,
        poller_class=None,
    ):
        """
        Initialize the OrchAPI server.

            config (dict): Configuration dictionary for the server.
            server_key (str): Unique key identifying the server.
            server_title (str): Title of the server.
            description (str): Description of the server.
            version (str): Version of the server.
            driver_class (Optional[type], optional): Class for the driver. Defaults to None.
            poller_class (Optional[type], optional): Class for the poller. Defaults to None.
        """
        super().__init__(
            helao_srv=server_key,
            title=server_title,
            description=description,
            version=str(version),
        )
        self.drivers = tuple()
        self.driver = None
        self.poller = None
        
        async def set_body(request: Request, body: bytes):
            """
            Asynchronously sets the body of the given request.

            This function modifies the request object by setting its _receive method
            to a custom function that returns a message containing the provided body.

            Args:
                request (Request): The request object to modify.
                body (bytes): The body content to set in the request.

            Returns:
                None
            """

            async def receive() -> Message:
                return {"type": "http.request", "body": body}

            request._receive = receive

        async def get_body(request: Request) -> bytes:
            """
            Asynchronously retrieves the body of an HTTP request and sets it back to the request.

            Args:
                request (Request): The HTTP request object.

            Returns:
                bytes: The body of the HTTP request.
            """
            body = await request.body()
            await set_body(request, body)
            return body

        @self.middleware("http")
        async def app_entry(request: Request, call_next):
            """
            Middleware function to handle incoming requests and manage action endpoints.

            Args:
                request (Request): The incoming HTTP request.
                call_next (Callable): The next middleware or endpoint handler to call.

            Returns:
                Response: The HTTP response.

            Behavior:
                - Handles HEAD requests by returning an empty response.
                - Handles POST requests to action endpoints by checking if the endpoint is available.
                - If available, processes the request immediately.
                - If busy, queues the action and returns a response indicating the action is queued.
                - For non-action POST requests, passes the request to the next handler.

            Logging:
                - Logs debug information for received requests and their types.
                - Logs information about action endpoint availability and queuing.

            """
            endpoint = request.url.path.strip("/").split("/")[-1]
            if request.method == "HEAD":  # comes from endpoint checker, session.head()
                LOGGER.debug("got HEAD request in middleware")
                response = Response()
            elif (
                request.url.path.strip("/").startswith(f"{server_key}/")
                and request.method == "POST"
            ):
                LOGGER.debug("got action POST request in middleware")
                body_bytes = await request.body()
                body_dict = json.loads(body_bytes)
                action_dict = body_dict.get("action", {})
                start_cond = action_dict.get("start_condition", ASC.wait_for_all)
                action_dict["action_uuid"] = action_dict.get("action_uuid", gen_uuid())
                if not self.orch.server_params.get("allow_concurrent_actions", True):
                    active_endpoints = [
                        ep
                        for ep, em in self.orch.actionservermodel.endpoints.items()
                        if em.active_dict
                    ]
                    if len(active_endpoints) > 0:
                        LOGGER.info("action endpoint is busy, queuing")
                        action_dict["action_params"] = action_dict.get(
                            "action_params", {}
                        )
                        action_dict["action_params"]["queued_on_actserv"] = True
                        extra_params = {}
                        action = Action(**action_dict)
                        for d in (
                            request.query_params,
                            request.path_params,
                        ):
                            for k, v in d.items():
                                if k in [
                                    "action_version",
                                    "start_condition",
                                    "from_global_seq_params",
                                    "from_global_exp_params",
                                    "from_global_act_params",
                                    "to_global_params",
                                ]:
                                    extra_params[k] = eval_val(v)
                        action.action_name = request.url.path.strip("/").split("/")[-1]
                        action.action_server = MachineModel(
                            server_name=server_key, machine_name=gethostname().lower()
                        )
                        # send active status but don't create active object
                        await self.orch.status_q.put(action.get_act())
                        response = JSONResponse(action.as_dict())
                        LOGGER.info(
                            f"action request for {action.action_name} received, but server does not allow concurrency, queuing action {action.action_uuid}"
                        )
                        self.orch.local_action_queue.append(
                            (
                                action,
                                extra_params,
                            )
                        )
                    else:
                        LOGGER.debug("action endpoint is available")
                        response = await call_next(request)
                elif (
                    len(self.orch.actionservermodel.endpoints[endpoint].active_dict)
                    == 0
                    or start_cond == ASC.no_wait
                    or action_dict.get("action_params", {}).get(
                        "queued_on_actserv", False
                    )
                ):
                    LOGGER.debug("action endpoint is available")
                    response = await call_next(request)
                else:  # collision between two base requests for one resource, queue
                    LOGGER.info("action endpoint is busy, queuing")
                    action_dict["action_params"] = action_dict.get("action_params", {})
                    action_dict["action_params"]["queued_on_actserv"] = True
                    extra_params = {}
                    action = Action(**action_dict)
                    for d in (
                        request.query_params,
                        request.path_params,
                    ):
                        for k, v in d.items():
                            if k in [
                                "action_version",
                                "start_condition",
                                "from_global_seq_params",
                                "from_global_exp_params",
                                "from_global_act_params",
                                "to_global_params",
                            ]:
                                extra_params[k] = eval_val(v)
                    action.action_name = request.url.path.strip("/").split("/")[-1]
                    action.action_server = MachineModel(
                        server_name=server_key, machine_name=gethostname().lower()
                    )
                    # send active status but don't create active object
                    await self.orch.status_q.put(action.get_act())
                    response = JSONResponse(action.as_dict())
                    LOGGER.info(
                        f"simultaneous action requests for {action.action_name} received, queuing action {action.action_uuid}"
                    )
                    self.orch.endpoint_queues[endpoint].append(
                        (
                            action,
                            extra_params,
                        )
                    )
            else:
                # LOGGER.debug("got non-action POST request")
                response = await call_next(request)
            return response

        @self.exception_handler(StarletteHTTPException)
        async def custom_http_exception_handler(request, exc):
            """
            Handles custom HTTP exceptions for requests that match a specific server key.

            Args:
                request (Request): The incoming HTTP request.
                exc (HTTPException): The exception that was raised.

            Returns:
                Response: The HTTP response generated by the default exception handler.

            Behavior:
                - If the request URL path starts with the specified server key, logs the exception and triggers emergency stop (e-stop) procedures for active operations and executors.
                - Delegates the actual response generation to the default HTTP exception handler.
            """
            if request.url.path.strip("/").startswith(f"{server_key}/"):
                print(f"Could not process request: {repr(exc)}")
                for _, active in self.orch.actives.items():
                    active.set_estop()
                for executor_id in self.orch.executors:
                    self.orch.stop_executor(executor_id)
            return await http_exception_handler(request, exc)

        @self.on_event("startup")
        async def startup_event():
            """
            Asynchronous startup event for initializing the orchestrator and driver.

            This method performs the following actions:
            1. Initializes the orchestrator with the current FastAPI application instance.
            2. Calls the `myinit` method on the orchestrator.
            3. If a driver class is provided and it is a subclass of `HelaoDriver`,
               initializes the driver with the server parameters and, if a poller class
               is provided, initializes the poller with the driver and polling time.
            4. If the driver class is not a subclass of `HelaoDriver`, initializes the
               driver with the orchestrator.
            5. Initializes the endpoint queues in the orchestrator.

            Args:
                None

            Returns:
                None
            """
            self.orch = Orch(fastapp=self)

            self.orch.myinit()
            if driver_classes is not None:
                Drivers = namedtuple("Drivers", [d.__name__ for d in driver_classes])
                driver_dict = {}
                for i, driver_class in enumerate(driver_classes):
                    if issubclass(driver_class, HelaoDriver):
                        driver_inst = driver_class(config=self.server_params)
                        if i==0 and poller_class is not None:
                            self.poller = poller_class(
                                driver_inst, self.server_cfg.get("polling_time", 0.1)
                            )
                            self.poller._base_hook = self.base
                    else:
                        driver_inst = driver_class(self.base)
                    driver_dict[driver_class.__name__] = driver_inst
                self.drivers = Drivers(**driver_dict)
                self.driver = self.drivers[0]
            self.orch.endpoint_queues_init()

        @self.on_event("startup")
        async def add_default_head_endpoints() -> None:
            """
            Adds default HEAD endpoints for all existing POST routes in the server.

            This method iterates through the server's routes and checks if the route
            is an instance of APIRoute and supports the POST method. For each such route,
            it creates a copy of the route, changes its method to HEAD, and appends it
            to the server's routes. The new HEAD route is not included in the schema.

            Returns:
                None
            """
            for route in self.routes:
                if isinstance(route, APIRoute) and "POST" in route.methods:
                    new_route = copy(route)
                    new_route.methods = {"HEAD"}
                    new_route.include_in_schema = False
                    self.routes.append(new_route)

        # --- BASE endpoints ---
        @self.websocket("/ws_status")
        async def websocket_status(websocket: WebSocket):
            """
            Handle the WebSocket connection for status updates.

            Args:
                websocket (WebSocket): The WebSocket connection instance.

            Returns:
                None
            """
            await self.orch.ws_status(websocket)

        @self.websocket("/ws_data")
        async def websocket_data(websocket: WebSocket):
            """
            Handle incoming WebSocket data.

            Args:
                websocket (WebSocket): The WebSocket connection instance.

            Returns:
                None
            """
            await self.orch.ws_data(websocket)

        @self.websocket("/ws_live")
        async def websocket_live(websocket: WebSocket):
            """
            Handle live WebSocket connections.

            This asynchronous function manages the WebSocket connection by
            delegating the handling to the `ws_live` method of the `orch` object.

            Args:
                websocket (WebSocket): The WebSocket connection to be managed.
            """
            await self.orch.ws_live(websocket)

        @self.post("/get_status", tags=["private"])
        def get_status():
            """
            Retrieve the current status of the orchestrator and its driver.

            Returns:
                dict: A dictionary containing the status of the orchestrator and the driver.
                  The dictionary includes the following keys:
                  - All keys from the orchestrator's action server model.
                  - '_driver_status': The status of the driver, or "not_implemented" if the driver is not an instance of HelaoDriver.
            """
            status_dict = self.orch.actionservermodel.model_dump()
            driver_status = "not_implemented"
            if isinstance(self.driver, HelaoDriver):
                resp = self.driver.get_status()
                driver_status = resp.status
            status_dict["_driver_status"] = driver_status
            return status_dict

        @self.post("/attach_client", tags=["private"])
        async def attach_client(
            client_servkey: str, client_host: str, client_port: int
        ):
            """
            Asynchronously attaches a client to the orchestrator.

            Args:
                client_servkey (str): The service key of the client.
                client_host (str): The hostname or IP address of the client.
                client_port (int): The port number on which the client is running.

            Returns:
                The result of the attach_client method from the orchestrator.
            """
            return await self.orch.attach_client(
                client_servkey, client_host, client_port
            )

        @self.post("/stop_executor", tags=["private"])
        def stop_executor(executor_id: str = ""):
            """
            Stops the executor with the given executor_id.

            Args:
                executor_id (str): The ID of the executor to stop. If not specified, an error message is returned.

            Returns:
                dict: A dictionary containing the result of the stop operation. If executor_id is not specified,
                  returns a dictionary with an error message.
            """
            if executor_id == "":
                return {"error": "executor_id was not specified"}
            return self.orch.stop_executor(executor_id)

        @self.post("/endpoints", tags=["private"])
        def get_all_urls():
            """
            Return a list of all endpoints on this server.

            Returns:
                list: A list of endpoint URLs.
            """
            return self.orch.get_endpoint_urls()

        @self.post("/get_lbuf", tags=["private"])
        def get_lbuf():
            """
            Retrieve the live buffer from the orchestrator.

            Returns:
                The live buffer object from the orchestrator.
            """
            return self.orch.live_buffer

        @self.post("/list_executors", tags=["private"])
        def list_executors():
            """
            Retrieve a list of executor names.

            Returns:
                list: A list containing the keys of the executors dictionary from the orch attribute.
            """
            return list(self.orch.executors.keys())

        @self.post("/shutdown", tags=["private"])
        def post_shutdown():
            """
            Handles the shutdown event by calling the shutdown_event function.
            This function is typically used to perform any necessary cleanup
            operations before the application is terminated.
            """
            shutdown_event()

        # --- ORCH-specific endpoints ---
        @self.post("/global_status", tags=["private"])
        def global_status():
            """
            Retrieve the global status of the orchestrator.

            Returns:
                dict: A JSON representation of the global status model.
            """
            return self.orch.globalstatusmodel.as_json()

        @self.post("/export_queues", tags=["private"])
        def export_queues(timestamp_pck: bool = False):
            """
            Exports the current state of various queues and active elements in the orchestrator to a pickle file.

            The function collects the following data from the orchestrator:
            - Sequence queue
            - Experiment queue
            - Action queue
            - Active experiment
            - Last experiment
            - Active sequence
            - Last sequence
            - Active sequence-experiment counter
            - Last action UUID
            - Last dispatched action UUID
            - Last 50 action UUIDs

            The collected data is saved as a dictionary in a pickle file located in the "STATES" directory under the root path specified in the orchestrator's world configuration.

            Returns:
                str: The file path where the pickle file is saved.
            """
            return self.orch.export_queues(timestamp_pck)

        @self.post("/import_queues", tags=["private"])
        def import_queues(pck_path: Optional[str] = None):
            """
            Imports and restores the state of various queues from a saved pickle file.

            This function attempts to load a previously saved state of action, experiment,
            and sequence queues from a pickle file located at "STATES/queues.pck" within
            the directory specified by `self.orch.world_cfg["root"]`. If the file does not
            exist, or if any of the current queues are not empty, the function will print
            an appropriate message and will not restore the queues.

            Upon successful restoration, the function updates the following attributes of
            `self.orch`:
            - action_dq
            - experiment_dq
            - sequence_dq
            - active_experiment
            - last_experiment
            - active_sequence
            - last_sequence
            - active_seq_exp_counter
            - last_action_uuid
            - last_dispatched_action_uuid
            - last_50_action_uuids

            Returns:
                str: The path to the pickle file used for restoring the queues.
            """
            return self.orch.import_queues(pck_path)

        @self.post("/update_status", tags=["private"])
        async def update_status(
            actionservermodel: ActionServerModel = Body({}, embed=True),
            regular_task: str = "false",
        ):
            """
            Asynchronously updates the status of an action server.

            Args:
                actionservermodel (ActionServerModel, optional): The model containing the action server's status information. Defaults to an empty dictionary.

            Returns:
                bool: Returns False if the actionservermodel is None, otherwise returns the result of the orch's update_status method.
            """
            if actionservermodel is None:
                return False
            if regular_task == "false":
                LOGGER.debug(
                    f"orch '{self.orch.server.server_name}' got status from '{actionservermodel.action_server.server_name}': {actionservermodel.endpoints}"
                )
            return await self.orch.update_status(actionservermodel=actionservermodel)

        @self.post("/clear_actives", tags=["private"])
        async def clear_actives():
            """
            Asynchronously clears active actions from all action servers and updates their status.

            This function iterates through all action servers in the global status model,
            removes active actions from each server's endpoint models, and moves them to
            the non-active dictionary with a status of 'skipped'. It then updates the
            global status model and returns a list of cleared active action UUIDs.

            Returns:
                list: A list of UUIDs of the cleared active actions.
            """
            cleared_actives = []
            for actionservermodel in self.orch.globalstatusmodel.server_dict.values():
                for endpointkey, endpointmodel in actionservermodel.endpoints.items():
                    active_items = list(endpointmodel.active_dict.items())
                    for uuid, statusmodel in active_items:
                        endpointmodel.active_dict.pop(uuid)
                        cleared_actives.append(uuid)
                        self.orch.globalstatusmodel.active_dict.pop(uuid)
                        if HloStatus.skipped not in endpointmodel.nonactive_dict:
                            endpointmodel[HloStatus.skipped] = {}
                        endpointmodel.nonactive_dict[HloStatus.skipped].update(
                            {uuid: statusmodel}
                        )
                    actionservermodel.endpoints[endpointkey] = endpointmodel
                await self.orch.update_status(actionservermodel=actionservermodel)
            return cleared_actives

        @self.post("/update_nonblocking", tags=["private"])
        async def update_nonblocking(
            actionmodel: Action = Body({}, embed=True),
            server_host: str = "",
            server_port: int = 9000,
        ):
            """
            Asynchronously updates the non-blocking status of an action.

            Args:
                actionmodel (Action): The model representing the action to update.
                server_host (str): The host of the server. Defaults to an empty string.
                server_port (int): The port of the server. Defaults to 9000.

            Returns:
                dict: A dictionary containing the result of the update operation.
            """
            LOGGER.info(
                f"'{self.orch.server.server_name.upper()}' got nonblocking status from '{actionmodel.action_server.server_name}': exec_id: {actionmodel.exec_id} -- status: {actionmodel.action_status} on {server_host}:{server_port}"
            )
            result_dict = await self.orch.update_nonblocking(
                actionmodel, server_host, server_port
            )
            return result_dict

        @self.post("/update_global_params", tags=["private"])
        async def update_global_params(params: dict):
            """
            Updates the global parameters for the active experiment.

            Args:
                params (dict): A dictionary containing the parameters to update.

            Returns:
                bool: True if the parameters were successfully updated, False otherwise.
            """
            LOGGER.info(f"Updated global params with {params}.")
            # if self.orch.active_experiment is not None:
            #     self.orch.active_experiment.global_params.update(params)
            #     return True
            # else:
            #     self.orch.print_message(
            #         "No active experiment, could not update global params."
            #     )
            #     return False
            self.orch.global_params.update(params)
            return True

        @self.post("/start", tags=["private"])
        async def start():
            """
            Asynchronously starts the orchestrator.

            This method calls the `start` method of the orchestrator instance and
            waits for it to complete. Once the orchestrator has started, it returns
            an empty dictionary.

            Returns:
                dict: An empty dictionary.
            """
            await self.orch.start()
            return {}

        @self.post("/get_active_experiment", tags=["private"])
        def get_active_experiment():
            """
            Retrieve the active experiment's clean dictionary representation.

            Returns:
                dict: A dictionary containing the cleaned data of the active experiment.
            """
            if self.orch.active_experiment is None:
                return {}
            return self.orch.active_experiment.clean_dict()

        @self.post("/get_active_sequence", tags=["private"])
        def get_active_sequence():
            """
            Retrieve the active sequence from the orchestrator.

            Returns:
                dict: A dictionary representation of the active sequence.
            """
            if self.orch.active_sequence is None:
                return {}
            return self.orch.active_sequence.clean_dict()

        @self.post("/estop_orch", tags=["private"])
        async def estop_orch():
            """
            Asynchronously handles the emergency stop (E-STOP) for the orchestrator.

            This function checks the current loop state of the orchestrator and performs
            the appropriate action based on the state:
            - If the loop is currently running, it will trigger an emergency stop.
            - If the loop is already in an emergency stop state, it will log a message indicating this.
            - If the loop is not running, it will log a message indicating that the orchestrator is not running.

            Returns:
                dict: An empty dictionary.
            """
            if self.orch.globalstatusmodel.loop_state == LoopStatus.started:
                await self.orch.estop_loop()
            elif self.orch.globalstatusmodel.loop_state == LoopStatus.estopped:
                LOGGER.info("orchestrator E-STOP flag already raised")
            else:
                LOGGER.info("orchestrator is not running")
            return {}

        @self.post("/stop", tags=["private"])
        async def stop():
            """
            Asynchronously stops the orchestrator.

            This method calls the `stop` method on the orchestrator instance and
            returns an empty dictionary upon completion.

            Returns:
                dict: An empty dictionary.
            """
            await self.orch.stop()
            return {}

        @self.post("/clear_estop", tags=["private"])
        async def clear_estop():
            """
            Asynchronously clears the emergency stop (E-STOP) condition.

            If the orchestrator is not currently in an E-STOP state, a message is printed
            indicating that the orchestrator is not in E-STOP. Otherwise, it proceeds to
            clear the E-STOP condition by calling the `clear_estop` method of the orchestrator.

            Returns:
                None
            """
            if self.orch.globalstatusmodel.loop_state != LoopStatus.estopped:
                LOGGER.info("orchestrator is not currently in E-STOP")
            else:
                await self.orch.clear_estop()

        @self.post("/clear_error", tags=["private"])
        async def clear_error():
            """
            Asynchronously clears the error state of the orchestrator.

            If the orchestrator's loop state is not in an error state, it logs a message indicating that the orchestrator is not currently in an error state.
            Otherwise, it calls the `clear_error` method of the orchestrator to clear the error state.
            """
            if self.orch.globalstatusmodel.loop_state != LoopStatus.error:
                LOGGER.info("orchestrator is not currently in ERROR")
            else:
                await self.orch.clear_error()

        @self.post("/skip_experiment", tags=["private"])
        async def skip_experiment():
            """
            Asynchronously skips the current experiment.

            This method calls the `skip` method on the `orch` object to skip the
            current experiment and returns an empty dictionary.

            Returns:
                dict: An empty dictionary.
            """
            await self.orch.skip()
            return {}

        @self.post("/clear_actions", tags=["private"])
        async def clear_actions():
            """
            Asynchronously clears all actions in the orchestrator.

            This method calls the `clear_actions` method of the orchestrator instance
            and returns an empty dictionary upon completion.

            Returns:
                dict: An empty dictionary.
            """
            await self.orch.clear_actions()
            return {}

        @self.post("/clear_experiments", tags=["private"])
        async def clear_experiments():
            """
            Asynchronously clears all experiments in the orchestrator.

            This method calls the `clear_experiments` method on the orchestrator
            instance to remove all current experiments.

            Returns:
                dict: An empty dictionary indicating the operation was successful.
            """
            await self.orch.clear_experiments()
            return {}

        @self.post("/append_sequence", tags=["private"])
        async def append_sequence(sequence: Sequence = Body({}, embed=True)):
            """
            Asynchronously appends a sequence to the orchestrator.

            Args:
                sequence (Sequence, optional): The sequence to append. Defaults to an empty dictionary.

            Returns:
                dict: A dictionary containing the UUID of the appended sequence.
            """
            if not isinstance(sequence, Sequence):
                sequence = Sequence(**sequence)
            seq_uuid = await self.orch.add_sequence(sequence=sequence)
            return {"sequence_uuid": seq_uuid}

        @self.post("/append_experiment", tags=["private"])
        async def append_experiment(experiment: Experiment = Body({}, embed=True)):
            """
            Add an experiment object to the end of the experiment queue.

            Args:
                experiment (Experiment): The experiment object to be added to the queue.

            Returns:
                dict: A dictionary containing the UUID of the added experiment.
            """
            """Add a experiment object to the end of the experiment queue."""
            exp_uuid = await self.orch.add_experiment(
                seq=self.orch.seq_model, experimentmodel=experiment.get_exp()
            )
            return {"experiment_uuid": exp_uuid}

        @self.post("/prepend_experiment", tags=["private"])
        async def prepend_experiment(experiment: Experiment = Body({}, embed=True)):
            """
            Prepend an experiment to the sequence.

            Args:
                experiment (Experiment): The experiment to be prepended. It is expected to be passed in the request body.

            Returns:
                dict: A dictionary containing the UUID of the prepended experiment.
            """
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
            """
            Asynchronously inserts an experiment into the sequence at the specified index.

            Args:
                experiment (Experiment): The experiment to be inserted. Defaults to an empty Experiment.
                idx (int): The index at which to insert the experiment. Defaults to 0.

            Returns:
                dict: A dictionary containing the UUID of the inserted experiment.
            """
            exp_uuid = await self.orch.add_experiment(
                seq=self.orch.seq_model,
                experimentmodel=experiment.get_exp(),
                at_index=idx,
            )
            return {"experiment_uuid": exp_uuid}

        @self.post("/list_sequences", tags=["private"])
        def list_sequences():
            """
            Retrieve a list of sequences from the orchestrator.

            Returns:
                list: A list of sequences managed by the orchestrator.
            """
            return self.orch.list_sequences()

        @self.post("/list_experiments", tags=["private"])
        def list_experiments():
            """
            Retrieve a list of experiments.

            Returns:
                list: A list of experiments from the orchestrator.
            """
            return self.orch.list_experiments()

        @self.post("/list_all_experiments", tags=["private"])
        def list_all_experiments():
            """
            Retrieve a list of all experiments.

            Returns:
                list: A list containing all experiments.
            """
            return self.orch.list_all_experiments()

        @self.post("/drop_experiment_inds", tags=["private"])
        def drop_experiment_inds(inds: List[int]):
            """
            Drops experiments based on the provided indices.

            Args:
                inds (List[int]): A list of integer indices representing the experiments to be dropped.

            Returns:
                The result of the drop operation from the orchestrator.
            """
            return self.orch.drop_experiment_inds(inds)

        @self.post("/drop_experiment_range", tags=["private"])
        def drop_experiment_range(lower: int, upper: int):
            """
            Drops a range of experiments from the orchestrator.

            Parameters:
            lower (int): The lower bound of the range (inclusive).
            upper (int): The upper bound of the range (inclusive).

            Returns:
            bool: True if the experiments were successfully dropped, False otherwise.
            """
            inds = list(range(lower, upper + 1))
            return self.orch.drop_experiment_inds(inds)

        @self.post("/active_experiment", tags=["private"])
        def active_experiment():
            """
            Retrieve the currently active experiment.

            Returns:
                Experiment: The currently active experiment object.
            """
            return self.orch.get_experiment(last=False)

        @self.post("/last_experiment", tags=["private"])
        def last_experiment():
            """
            Retrieve the last experiment from the orchestrator.

            Returns:
                Experiment: The last experiment object managed by the orchestrator.
            """
            return self.orch.get_experiment(last=True)

        @self.post("/list_actions", tags=["private"])
        def list_actions():
            """
            Retrieve a list of actions from the orchestrator.

            Returns:
                list: A list of actions managed by the orchestrator.
            """
            return self.orch.list_actions()

        @self.post("/list_active_actions", tags=["private"])
        def list_active_actions():
            """
            List all active actions managed by the orchestrator.

            Returns:
                list: A list of active actions.
            """
            return self.orch.list_active_actions()

        @self.post("/list_nonblocking", tags=["private"])
        def list_non_blocking():
            """
            Retrieve the list of non-blocking operations.

            Returns:
                list: A list containing non-blocking operations.
            """
            return self.orch.nonblocking

        @self.post("/get_orch_state", tags=["private"])
        def get_orch_state() -> dict:
            """
            Retrieve the current state of the orchestrator.

            Returns:
                dict: A dictionary containing the following keys:
                - "orch_state": The current state of the orchestrator.
                - "loop_state": The current state of the loop.
                - "loop_intent": The current intent of the loop.
                - "active_sequence": A dictionary representation of the active sequence, if any.
                - "last_sequence": A dictionary representation of the last sequence, if any.
                - "active_experiment": A dictionary representation of the active experiment, if any.
                - "last_experiment": A dictionary representation of the last experiment, if any.
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

        @self.post("/latest_sequence_uuids", tags=["private"])
        def latest_sequence_uuids():
            """
            Retrieve a list of 50 most recent sequence_uuids.

            Returns:
                list: A list of most recent sequence_uuids from the orchestrator.
            """
            return self.orch.last_50_sequence_uuids

        @self.post("/latest_experiment_uuids", tags=["private"])
        def latest_experiment_uuids():
            """
            Retrieve a list of 50 most recent experiment_uuids.

            Returns:
                list: A list of most recent experiment_uuids from the orchestrator.
            """
            return self.orch.last_50_experiment_uuids

        @self.post("/latest_action_uuids", tags=["private"])
        def latest_action_uuids():
            """
            Retrieve a list of 50 most recent action_uuids.

            Returns:
                list: A list of most recent action_uuids from the orchestrator.
            """
            return self.orch.last_50_action_uuids

        @self.post(f"/{server_key}/wait", tags=["action"])
        async def wait(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            waittime: float = 10.0,
        ):
            """
            Asynchronous function to wait for a specified amount of time.

            Args:
                action (Action): The action to be performed, provided in the request body.
                action_version (int): The version of the action. Default is 1.
                waittime (float): The time to wait in seconds. Default is 10.0 seconds.

            Returns:
                dict: A dictionary containing the details of the active action.
            """
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
            """
            Stop a wait action.

            This asynchronous function cancels an ongoing "wait" action by stopping the
            associated executor tasks. It first sets up and contains the action, then
            iterates through the executors to find and stop the "wait" action tasks.
            Finally, it finishes the action and returns the result as a dictionary.

            Args:
                action (Action, optional): The action to be canceled. Defaults to an empty dictionary.
                action_version (int, optional): The version of the action. Defaults to 1.

            Returns:
                dict: The finished action details as a dictionary.
            """
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
            """
            Interrupts the current action and stops the orchestrator.

            Args:
                action (Action, optional): The action to be interrupted. Defaults to an empty Action.
                action_version (int, optional): The version of the action. Defaults to 1.
                reason (str, optional): The reason for the interruption. Defaults to "wait".

            Returns:
                dict: The finished action as a dictionary.
            """
            active = await self.orch.setup_and_contain_action()
            self.orch.current_stop_message = active.action.action_params["reason"]
            LOGGER.warning(active.action.action_params["reason"])
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
            """
            Emergency stop (estop) action handler.

            This asynchronous function handles the emergency stop action. It sets up
            and contains the action, checks if the driver has an estop function, and
            either calls it or sets the estop status directly. It also updates the
            action status and stops all executors.

            Args:
                action (Action): The action object containing parameters for the estop action.
                action_version (int): The version of the action. Default is 1.
                switch (bool): A flag indicating whether to switch the estop status. Default is True.

            Returns:
                dict: A dictionary representation of the finished action.
            """
            active = await self.orch.setup_and_contain_action(
                json_data_keys=["estop"], action_abbr="estop"
            )
            has_estop = getattr(self.driver, "estop", None)
            if has_estop is not None and callable(has_estop):
                LOGGER.info("driver has estop function")
                await active.enqueue_data_dflt(
                    datadict={
                        "estop": await self.driver.estop(**active.action.action_params)
                    }
                )
            else:
                LOGGER.info("driver has NO estop function")
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
            """
            Executes a conditional experiment based on specified parameters and conditions.

            Args:
                action (Action): The action object containing parameters for the experiment.
                action_version (int): The version of the action. Default is 1.
                check_parameter (Optional[str]): The parameter to check against the condition. Default is an empty string.
                check_condition (checkcond): The condition to check. Default is checkcond.equals.
                check_value (Union[float, int, bool]): The value to compare the parameter against. Default is True.
                conditional_experiment_name (str): The name of the conditional experiment. Default is an empty string.
                conditional_experiment_params (dict): The parameters for the conditional experiment. Default is an empty dictionary.

            Returns:
                dict: The finished action as a dictionary.
            """
            active = await self.orch.setup_and_contain_action()
            experiment_model = Experiment(
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
            action_version: int = 2,
            stop_parameter: Optional[str] = "",
            stop_condition: checkcond = checkcond.equals,
            stop_value: Union[str, float, int, bool] = True,
            reason: str = "conditional stop",
            clear_queues: bool = False,
        ):
            """
            Asynchronously stops an action based on a specified condition.

            Parameters:
                action (Action): The action to be conditionally stopped. Defaults to an empty dictionary.
                action_version (int): The version of the action. Defaults to 1.
                stop_parameter (Optional[str]): The parameter to check against the stop condition. Defaults to an empty string.
                stop_condition (checkcond): The condition to evaluate for stopping the action. Defaults to checkcond.equals.
                stop_value (Union[str, float, int, bool]): The value to compare against the stop parameter. Defaults to True.
                reason (str): The reason for stopping the action. Defaults to "conditional stop".

            Returns:
                dict: The dictionary representation of the finished action.

            Behavior:
                - Sets up and contains the action.
                - Evaluates the stop condition against the specified parameter and value.
                - If the condition is met, clears actions, experiments, and sequences, and updates the stop message.
                - Finishes the action and returns its dictionary representation.
            """
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
                if active.action.action_params["clear_queues"]:
                    await self.orch.clear_actions()
                    await self.orch.clear_experiments()
                    await self.orch.clear_sequences()
                await self.orch.stop()
                self.orch.current_stop_message = active.action.action_params["reason"]
                LOGGER.warning(active.action.action_params["reason"])
                await self.orch.update_operator(True)

            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.post(f"/{server_key}/conditional_skip", tags=["action"])
        async def conditional_skip(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            skip_parameter: Optional[str] = "",
            skip_condition: checkcond = checkcond.equals,
            skip_value: Union[str, float, int, bool] = True,
            skip_queued_actions: bool = True,
            skip_queued_experiments: bool = False,
            reason: str = "conditional skip",
        ):
            """
            Conditionally skips actions or experiments based on specified parameters.

            Args:
                action (Action): The action to be evaluated.
                action_version (int): The version of the action.
                skip_parameter (Optional[str]): The parameter to check for the skip condition.
                skip_condition (checkcond): The condition to evaluate for skipping.
                skip_value (Union[str, float, int, bool]): The value to compare against the parameter.
                skip_queued_actions (bool): Whether to skip queued actions if the condition is met.
                skip_queued_experiments (bool): Whether to skip queued experiments if the condition is met.
                reason (str): The reason for the conditional skip.

            Returns:
                dict: The finished action as a dictionary.
            """
            active = await self.orch.setup_and_contain_action()
            cond = active.action.action_params["skip_condition"]
            param = active.action.action_params.get(
                active.action.action_params["skip_parameter"], None
            )
            thresh = active.action.action_params["skip_value"]
            skip = False
            if cond == checkcond.equals:
                skip = param == thresh
            elif cond == checkcond.above:
                skip = param > thresh
            elif cond == checkcond.below:
                skip = param < thresh
            elif cond == checkcond.isnot:
                skip = param != thresh
            elif cond == checkcond.uncond:
                skip = True
            elif cond is None:
                skip = False

            if skip:
                if active.action.action_params["skip_queued_actions"]:
                    await self.orch.clear_actions()
                if active.action.action_params["skip_queued_experiments"]:
                    await self.orch.clear_experiments()
                await self.orch.update_operator(True)

            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.post(f"/{server_key}/add_global_param", tags=["action"])
        async def add_global_param(
            action: Action = Body({}, embed=True),
            param_name: str = "global_param_test",
            param_value: Union[str, float, int, bool] = True,
        ):
            """
            Adds a global experiment parameter to the orchestrator.

            Args:
                action (Action, optional): The action object containing parameters. Defaults to an empty Action object.
                param_name (str, optional): The name of the parameter to add. Defaults to "global_param_test".
                param_value (Union[str, float, int, bool], optional): The value of the parameter to add. Defaults to True.

            Returns:
                dict: The finished action as a dictionary.
            """
            active = await self.orch.setup_and_contain_action()
            pdict = {
                active.action.action_params["param_name"]: active.action.action_params[
                    "param_value"
                ]
            }
            active.action.action_params.update(pdict)
            # active.action.to_global_params = list(pdict.keys())
            self.orch.global_params.update(pdict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.post("/_raise_exception", tags=["private"])
        def _raise_exception():
            """
            Raises a test exception for error recovery debugging purposes.

            This function is used to simulate an exception in order to test
            the error handling and recovery mechanisms of the system.

            Raises:
                Exception: Always raises an exception with the message
                       "test exception for error recovery debugging".
            """
            raise Exception("test exception for error recovery debugging")

        @self.post("/_raise_async_exception", tags=["private"])
        async def _raise_async_exception():
            """
            Asynchronously raises an exception after a delay.

            This function schedules an asynchronous task that sleeps for 10 seconds
            and then raises an exception. It is useful for testing error recovery
            and debugging asynchronous code.

            Returns:
                bool: Always returns True.
            """

            async def sleep_then_error():
                print(f"Start time: {time.time()}")
                await asyncio.sleep(10)
                print(f"End time: {time.time()}")
                raise Exception("test async exception for error recovery debugging")

            loop = asyncio.get_running_loop()
            loop.create_task(sleep_then_error())
            return True

        @self.post("/clear_global_params_private", tags=["private"])
        def clear_global_params_private():
            """
            Clears the global parameters stored in the orchestrator.

            This function resets the `global_params` dictionary in the orchestrator to an empty dictionary.
            It returns a string indicating which parameters were removed or if the `global_params` was already empty.

            Returns:
                str: A message indicating the removed parameters or that `global_params` was empty.
            """
            current_params = list(self.orch.global_params.keys())
            self.orch.global_params = {}
            if current_params:
                return "\n".join(["removed:"] + current_params)
            else:
                return "global_params was empty"

        @self.post("/get_global_params", tags=["private"])
        def get_global_params():
            """
            Retrieve the global parameters from the orchestrator.

            Returns:
                dict: A dictionary containing the global parameters.
            """
            return self.orch.global_params

        @self.post(f"/{server_key}/clear_global_params", tags=["action"])
        async def clear_global_params(action: Action = Body({}, embed=True)):
            """
            Asynchronous endpoint to clear global parameters.

            This function clears the global parameters stored in the orchestrator.
            It sets up and contains an action, retrieves the current global parameters,
            and then clears them. If there were any global parameters, it logs the removed
            parameters; otherwise, it logs that the global parameters were already empty.
            Finally, it updates the action parameters with the cleared parameters and
            finishes the action.

            Args:
                action (Action, optional): The action object containing the parameters.
                    Defaults to an empty dictionary.

            Returns:
                dict: The finished action as a dictionary.
            """
            active = await self.orch.setup_and_contain_action()
            current_params = list(self.orch.global_params.keys())
            self.orch.global_params = {}
            if current_params:
                self.orch.print_message(
                    "\n".join(["removed:"] + current_params), info=True
                )
            else:
                LOGGER.info("global_params was empty")
            active.action.action_params.update({"cleared": current_params})
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.on_event("shutdown")
        def shutdown_event():
            """
            Shuts down the operator and the Bokeh application.

            This function performs the following steps:
            1. Logs a message indicating that the operator is stopping.
            2. Stops the Bokeh application.
            3. Logs a message indicating that the orchestrator has shut down.
            4. Waits for 0.75 seconds to ensure all processes have terminated properly.
            """
            if any(
                [
                    len(x) > 0
                    for x in (
                        self.orch.sequence_dq,
                        self.orch.experiment_dq,
                        self.orch.action_dq,
                    )
                ]
            ):
                export_path = self.orch.export_queues(timestamp_pck=True)
                LOGGER.info(
                    f"Orch queues are not empty, exported queues to {export_path}"
                )
            LOGGER.info("Stopping operator")
            self.orch.bokehapp.stop()
            LOGGER.info("orch shutdown")
            time.sleep(0.75)


class WaitExec(Executor):
    """
    WaitExec is an executor class that performs a wait action for a specified duration.

    Attributes:
        poll_rate (float): The rate at which the poll method is called.
        duration (float): The duration to wait, in seconds.
        print_every_secs (int): The interval at which status messages are printed, in seconds.
        start_time (float): The start time of the wait action.
        last_print_time (float): The last time a status message was printed.

    Methods:
        _exec(): Logs the wait action and returns a result dictionary.
        _poll(): Periodically checks the elapsed time and updates the status.
        _post_exec(): Logs the completion of the wait action and returns a result dictionary.
    """

    def __init__(self, *args, **kwargs):
        """
        Initializes the WaitExec class.

        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.
                - print_every_secs (int, optional): Interval in seconds for printing messages. Defaults to 5.

        Attributes:
            poll_rate (float): The rate at which the poll occurs, in seconds.
            duration (int): The duration to wait, retrieved from action parameters.
            print_every_secs (int): Interval in seconds for printing messages.
            start_time (float): The start time of the wait execution.
            last_print_time (float): The last time a message was printed.
        """
        super().__init__(*args, **kwargs)
        LOGGER.info("WaitExec initialized.")
        self.poll_rate = 0.01
        self.duration = self.active.action.action_params.get("waittime", -1)
        self.print_every_secs = kwargs.get("print_every_secs", 5)
        self.start_time = time.time()
        self.last_print_time = self.start_time

    async def _exec(self):
        """
        Asynchronously executes an action and logs the duration.

        Returns:
            dict: A dictionary containing an empty "data" field and an "error" field with the value `ErrorCodes.none`.
        """
        LOGGER.info(f" ... wait action: {self.duration}")
        return {"data": {}, "error": ErrorCodes.none}

    async def _poll(self):
        """
        Asynchronously polls the analog inputs from the live buffer and logs the elapsed time.

        This method checks the current time and calculates the elapsed time since the start.
        It logs the elapsed time at intervals specified by `self.print_every_secs`.
        The method then determines the status based on the elapsed time and the specified duration.
        Finally, it sleeps for a short duration to yield control back to the event loop.

        Returns:
            dict: A dictionary containing the error code and the status.
        """
        """Read analog inputs from live buffer."""
        check_time = time.time()
        elapsed_time = check_time - self.start_time
        if check_time - self.last_print_time > self.print_every_secs - 0.01:
            LOGGER.info(
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
        LOGGER.info(" ... wait action done")
        return {"error": ErrorCodes.none}


class checkcond(str, Enum):
    """
    checkcond is an enumeration that represents different types of conditions.

    Attributes:
        equals (str): Represents a condition where values are equal.
        below (str): Represents a condition where a value is below a certain threshold.
        above (str): Represents a condition where a value is above a certain threshold.
        isnot (str): Represents a condition where values are not equal.
        uncond (str): Represents an unconditional state.
    """

    equals = "equals"
    below = "below"
    above = "above"
    isnot = "isnot"
    uncond = "uncond"
