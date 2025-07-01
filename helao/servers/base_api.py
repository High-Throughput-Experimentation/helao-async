import os
import json
import time
import asyncio
import faulthandler
from copy import copy
from socket import gethostname
from collections import namedtuple

from helao.drivers.helao_driver import HelaoDriver, DriverPoller, DriverStatus
from helao.helpers.gen_uuid import gen_uuid
from helao.helpers.eval import eval_val
from helao.servers.base import Base
from helao.helpers.server_api import HelaoFastAPI
from helao.helpers.premodels import Action
from helao.core.models.machine import MachineModel
from fastapi import Body, WebSocket, WebSocketDisconnect, Request
from fastapi.routing import APIRoute
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from helao.core.models.hlostatus import HloStatus
from helao.core.models.action_start_condition import ActionStartCondition as ASC
from starlette.responses import JSONResponse, Response
from websockets.exceptions import ConnectionClosedOK
from helao.helpers import helao_logging as logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER


class BaseAPI(HelaoFastAPI):
    """
    BaseAPI class extends HelaoFastAPI to provide additional functionality for handling
    middleware, exception handling, startup and shutdown events, WebSocket connections,
    and various endpoints for configuration, status, and control.

    Attributes:
        base (Base): An instance of the Base class.
        driver (Optional[HelaoDriver]): An optional driver instance.
        poller (Optional[DriverPoller]): An optional poller instance.

    Methods:
        __init__(config, server_key, server_title, description, version, driver_classes=None, dyn_endpoints=None, poller_class=None):
            Initializes the BaseAPI instance with the given configuration and parameters.

        app_entry(request: Request, call_next):
            Middleware function to handle incoming HTTP requests and manage action queuing.

        custom_http_exception_handler(request, exc):
            Custom exception handler for HTTP exceptions.

        startup_event():
            Event handler for application startup.

        add_default_head_endpoints():
            Adds default HEAD endpoints for all POST routes.

        websocket_status(websocket: WebSocket):
            WebSocket endpoint to broadcast status messages.

        websocket_data(websocket: WebSocket):
            WebSocket endpoint to broadcast status dictionaries.

        websocket_live(websocket: WebSocket):
            WebSocket endpoint to broadcast live buffer dictionaries.

        get_config():
            Endpoint to retrieve the server configuration.

        get_status():
            Endpoint to retrieve the server status.

        attach_client(client_servkey: str, client_host: str, client_port: int):
            Endpoint to attach a client to the server.

        stop_executor(executor_id: str):
            Endpoint to stop a specific executor.

        get_all_urls():
            Endpoint to retrieve all URLs on the server.

        get_lbuf():
            Endpoint to retrieve the live buffer.

        list_executors():
            Endpoint to list all executors.

        _raise_exception():
            Endpoint to raise a test exception for debugging.

        _raise_async_exception():
            Endpoint to raise a test asynchronous exception for debugging.

        resend_active(action_uuid: str):
            Endpoint to resend the last active action.

        post_shutdown():
            Endpoint to initiate server shutdown.

        shutdown_event():
            Event handler for application shutdown.

        estop(action: Action, switch: bool):
            Endpoint to handle emergency stop (estop) actions.
    """

    base: Base
    root_dir: str
    fault_dir: str
    drivers: tuple

    def __init__(
        self,
        server_key,
        server_title,
        description,
        version,
        driver_classes=None,
        dyn_endpoints=None,
        poller_class=None,
    ):
        """
        Initialize the BaseAPI server.

            config (dict): Configuration dictionary for the server.
            server_key (str): Unique key identifying the server.
            server_title (str): Title of the server.
            description (str): Description of the server.
            version (str): Version of the server.
            driver_class (type, optional): Class of the driver to be used. Defaults to None.
            dyn_endpoints (list, optional): List of dynamic endpoints. Defaults to None.
            poller_class (type, optional): Class of the poller to be used. Defaults to None.

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

        @self.middleware("http")
        async def app_entry(request: Request, call_next):
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
                if not self.base.server_params.get("allow_concurrent_actions", True):
                    active_endpoints = [
                        ep
                        for ep, em in self.base.actionservermodel.endpoints.items()
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
                        await self.base.status_q.put(action.get_act())
                        response = JSONResponse(action.as_dict())
                        LOGGER.info(
                            f"action request for {action.action_name} received, but server does not allow concurrency, queuing action {action.action_uuid}"
                        )
                        self.base.local_action_queue.append(
                            (
                                action,
                                extra_params,
                            )
                        )
                    else:
                        LOGGER.debug("action endpoint is available")
                        response = await call_next(request)
                elif (
                    len(self.base.actionservermodel.endpoints[endpoint].active_dict)
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
                    await self.base.status_q.put(action.get_act())
                    response = JSONResponse(action.as_dict())
                    LOGGER.info(
                        f"simultaneous action requests for {action.action_name} received, queuing action {action.action_uuid}"
                    )
                    self.base.endpoint_queues[endpoint].append(
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
                - If the request URL path starts with the specified server key, logs the exception and triggers emergency stop (estop) procedures for active processes and executors.
                - Delegates the actual response generation to the default HTTP exception handler.
            """
            if request.url.path.strip("/").startswith(f"{server_key}/"):
                print(f"Could not process request: {repr(exc)}")
                for _, active in self.base.actives.items():
                    active.set_estop()
                for executor_id in self.base.executors:
                    self.base.stop_executor(executor_id)
            return await http_exception_handler(request, exc)

        @self.on_event("startup")
        def startup_event():
            """
            Initializes the server during startup.

            This method performs the following actions:
            - Creates an instance of the Base class with the current FastAPI app and dynamic endpoints.
            - Retrieves the root directory from the world configuration and sets up the fault directory and fault file if the root directory is specified.
            - Initializes the base instance.
            - If a driver class is provided and it is a subclass of HelaoDriver, it initializes the driver with the server parameters.
            - If a poller class is provided, it initializes the poller with the driver and polling time from the server configuration.
            - If the driver class is not a subclass of HelaoDriver, it initializes the driver with the base instance.
            - Initializes dynamic endpoints for the base instance.
            """
            self.base = Base(app=self, dyn_endpoints=dyn_endpoints)

            self.root_dir = self.base.world_cfg.get("root", None)
            if self.root_dir is not None:
                self.fault_dir = os.path.join(self.root_dir, "FAULTS")
                os.makedirs(self.fault_dir, exist_ok=True)
                fault_path = os.path.join(self.fault_dir, f"{server_key}_faults.txt")
                self.fault_file = open(fault_path, "a")
                faulthandler.enable(self.fault_file)

            self.base.myinit()
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
            self.base.dyn_endpoints_init()

        @self.on_event("startup")
        async def add_default_head_endpoints() -> None:
            """
            Adds default HEAD endpoints for all existing POST routes in the server.

            This method iterates through the server's routes and checks if a route
            is an instance of `APIRoute` and supports the POST method. For each such
            route, it creates a new route that supports only the HEAD method and
            appends it to the server's routes. The new HEAD route is not included
            in the schema.

            Returns:
                None
            """
            for route in self.routes:
                if isinstance(route, APIRoute) and "POST" in route.methods:
                    new_route = copy(route)
                    new_route.methods = {"HEAD"}
                    new_route.include_in_schema = False
                    self.routes.append(new_route)

        @self.websocket("/ws_status")
        async def websocket_status(websocket: WebSocket):
            """
            Handles the WebSocket connection for status updates.

            This asynchronous method manages the WebSocket connection for status updates.
            It connects the WebSocket to the status publisher, broadcasts status updates,
            and handles disconnections.

            Args:
                websocket (WebSocket): The WebSocket connection to be managed.

            Raises:
                WebSocketDisconnect: If the WebSocket connection is disconnected.
                ConnectionClosedOK: If the WebSocket connection is closed normally.
            """
            await self.base.status_publisher.connect(websocket)
            try:
                await self.base.status_publisher.broadcast(websocket)
            except WebSocketDisconnect:
                self.base.status_publisher.disconnect(websocket)
            except ConnectionClosedOK:
                self.base.status_publisher.disconnect(websocket)

        @self.websocket("/ws_data")
        async def websocket_data(websocket: WebSocket):
            """
            Handles websocket data connection and broadcasting.

            This asynchronous function manages the connection of a websocket to the
            data publisher, handles broadcasting of data, and ensures proper
            disconnection in case of websocket disconnection or closure.

            Args:
                websocket (WebSocket): The websocket connection to be managed.

            Raises:
                WebSocketDisconnect: If the websocket gets disconnected.
                ConnectionClosedOK: If the websocket connection is closed properly.
            """
            await self.base.data_publisher.connect(websocket)
            try:
                await self.base.data_publisher.broadcast(websocket)
            except WebSocketDisconnect:
                self.base.data_publisher.disconnect(websocket)
            except ConnectionClosedOK:
                self.base.data_publisher.disconnect(websocket)

        @self.websocket("/ws_live")
        async def websocket_live(websocket: WebSocket):
            """
            Handle live websocket connections.

            This asynchronous function manages the lifecycle of a websocket connection.
            It connects the websocket to the live publisher, broadcasts messages, and
            handles disconnections.

            Args:
                websocket (WebSocket): The websocket connection to manage.

            Raises:
                WebSocketDisconnect: If the websocket is disconnected unexpectedly.
                ConnectionClosedOK: If the websocket connection is closed normally.
            """
            await self.base.live_publisher.connect(websocket)
            try:
                await self.base.live_publisher.broadcast(websocket)
            except WebSocketDisconnect:
                self.base.live_publisher.disconnect(websocket)
            except ConnectionClosedOK:
                self.base.live_publisher.disconnect(websocket)

        @self.post("/get_config", tags=["private"])
        def get_config():
            """
            Retrieve the world configuration.

            Returns:
                dict: The world configuration dictionary.
            """
            return self.base.world_cfg

        @self.post("/get_status", tags=["private"])
        def get_status():
            """
            Retrieve the current status of the action server and its driver.

            Returns:
                dict: A dictionary containing the status of the action server and the driver.
                  The dictionary includes the following keys:
                  - All keys from the action server model dump.
                  - '_driver_status': The status of the driver, which can be "not_implemented",
                    DriverStatus.ok, or the status returned by the driver's get_status method.
            """
            status_dict = self.base.actionservermodel.model_dump()
            driver_status = "not_implemented"
            # first check if poller is available
            if isinstance(self.poller, DriverPoller):
                resp = self.poller.live_dict
                driver_status = DriverStatus.ok
            # if no poller, but HelaoDriver, use get_status method
            elif isinstance(self.driver, HelaoDriver):
                resp = self.driver.get_status()
                driver_status = resp.status
            status_dict["_driver_status"] = driver_status
            return status_dict

        @self.post("/attach_client", tags=["private"])
        async def attach_client(
            client_servkey: str, client_host: str, client_port: int
        ):
            """
            Asynchronously attaches a client to the base server.

            Args:
                client_servkey (str): The service key of the client.
                client_host (str): The hostname of the client.
                client_port (int): The port number of the client.

            Returns:
                The result of the base server's attach_client method.
            """
            return await self.base.attach_client(
                client_servkey, client_host, client_port
            )

        @self.post("/stop_executor", tags=["private"])
        def stop_executor(executor_id: str):
            """
            Stops the executor with the given executor ID.

            Args:
                executor_id (str): The ID of the executor to stop.

            Returns:
                The result of the stop operation from the base.
            """
            return self.base.stop_executor(executor_id)

        @self.post("/endpoints", tags=["private"])
        def get_all_urls():
            """
            Retrieve all URLs.

            Returns:
                list: A list of URLs from the `fast_urls` attribute of the `base` object.
            """
            return self.base.fast_urls

        @self.post("/get_lbuf", tags=["private"])
        def get_lbuf():
            """
            Retrieve the live buffer from the base.

            Returns:
                The live buffer object from the base.
            """
            return self.base.live_buffer

        @self.post("/list_executors", tags=["private"])
        def list_executors():
            """
            List the keys of the executors in the base.

            Returns:
                list: A list of keys from the executors dictionary.
            """
            return list(self.base.executors.keys())

        @self.post("/_raise_exception", tags=["private"])
        def _raise_exception():
            """
            Raises a test exception for error recovery debugging purposes.

            This function is used to simulate an exception to test the error
            handling and recovery mechanisms in the application.

            Raises:
                Exception: Always raises an exception with the message
                "test exception for error recovery debugging".
            """
            raise Exception("test exception for error recovery debugging")

        @self.post("/_raise_async_exception", tags=["private"])
        async def _raise_async_exception():
            """
            Asynchronously raises an exception after a delay.

            This function creates an asynchronous task that sleeps for 10 seconds
            and then raises an exception. It is intended for testing error recovery
            and debugging purposes.

            Returns:
                bool: Always returns True after scheduling the task.
            """

            async def sleep_then_error():
                print(f"Start time: {time.time()}")
                await asyncio.sleep(10)
                print(f"End time: {time.time()}")
                raise Exception("test async exception for error recovery debugging")

            loop = asyncio.get_running_loop()
            loop.create_task(sleep_then_error())
            return True

        @self.post("/resend_active", tags=["private"])
        def resend_active(action_uuid: str):
            """
            Resends the most recent active action or creates a new action if none exist.

            Args:
                action_uuid (str): The UUID of the action to be created if no active actions are found.

            Returns:
                dict: A dictionary representation of the most recent active action or a new action.
            """
            l10 = [y for x, y in self.base.last_10_active]
            if l10:
                return l10[0].action.as_dict()
            else:
                return Action(action_uuid=action_uuid).as_dict()

        @self.post("/shutdown", tags=["private"])
        async def post_shutdown():
            """
            Asynchronously handles the shutdown process by awaiting the shutdown_event.

            This function is intended to be called when a shutdown signal is received,
            ensuring that the shutdown_event coroutine is executed properly.
            """
            await shutdown_event()

        @self.on_event("shutdown")
        async def shutdown_event():
            """
            Handles the shutdown event for the server.

            This method performs the following steps:
            1. Logs the shutdown action.
            2. Calls the base shutdown method.
            3. Checks if the driver has `shutdown` and `async_shutdown` methods and calls them if they exist.
            4. Disables the fault handler and closes the fault file if `root_dir` is set.

            Returns:
                dict: A dictionary containing the return values of the `shutdown` and `async_shutdown` methods, if they exist.
            """
            LOGGER.info("action shutdown")
            await self.base.shutdown()

            shutdown = getattr(self.driver, "shutdown", None)
            async_shutdown = getattr(self.driver, "async_shutdown", None)

            retvals = {}
            if shutdown is not None and callable(shutdown):
                LOGGER.info("driver has shutdown function")
                retvals["shutdown"] = shutdown()
            else:
                LOGGER.info("driver has NO shutdown function")
                retvals["shutdown"] = None
            if async_shutdown is not None and callable(async_shutdown):
                LOGGER.info("driver has async_shutdown function")
                retvals["async_shutdown"] = await async_shutdown()
            else:
                LOGGER.info("driver has NO async_shutdown function")
                retvals["async_shutdown"] = None

            if self.root_dir is not None:
                faulthandler.disable()
                self.fault_file.close()
            return retvals

        @self.post(f"/{server_key}/estop", tags=["action"])
        async def estop(
            action: Action = Body({}, embed=True),
            switch: bool = True,
        ):
            """
            Emergency stop (estop) action handler.

            This asynchronous function handles the emergency stop action. It sets up
            and contains the action, checks if the driver has an estop function, and
            either calls it or sets the estop switch accordingly. It also updates the
            action status and stops all executors.

            Args:
                action (Action): The action object containing parameters for the estop action.
                switch (bool): A flag indicating whether to switch the estop on or off.
                       Defaults to True.

            Returns:
                dict: A dictionary representation of the finished action.
            """
            active = await self.base.setup_and_contain_action(
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
                self.base.actionservermodel.estop = switch
            if switch:
                active.action.action_status.append(HloStatus.estopped)
            for executor_id in self.base.executors:
                self.base.stop_executor(executor_id)
            finished_action = await active.finish()
            return finished_action.as_dict()
