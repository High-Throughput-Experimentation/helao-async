import os
import sys
import json
import time
import asyncio
import faulthandler
from copy import copy
from socket import gethostname

from helao.drivers.helao_driver import HelaoDriver, DriverPoller, DriverStatus
from helao.helpers.gen_uuid import gen_uuid
from helao.helpers.eval import eval_val
from helao.servers.base import Base
from helao.helpers.server_api import HelaoFastAPI
from helao.helpers.premodels import Action
from helaocore.models.machine import MachineModel
from fastapi import Body, WebSocket, WebSocketDisconnect, Request
from fastapi.routing import APIRoute
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from helaocore.models.hlostatus import HloStatus
from helaocore.models.action_start_condition import ActionStartCondition as ASC
from starlette.responses import JSONResponse, Response
from websockets.exceptions import ConnectionClosedOK

from helao.helpers import logging

global LOGGER


class BaseAPI(HelaoFastAPI):
    def __init__(
        self,
        config,
        server_key,
        server_title,
        description,
        version,
        driver_class=None,
        dyn_endpoints=None,
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
        self.poller = None
        LOGGER = logging.LOGGER

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
                    active_endpoints = [ep for ep,em in self.base.actionservermodel.endpoints.items() if em.active_dict]
                    if len(active_endpoints) > 0:
                        LOGGER.info("action endpoint is busy, queuing")
                        action_dict["action_params"] = action_dict.get("action_params", {})
                        action_dict["action_params"]["delayed_on_actserv"] = True
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
                                    "from_globalexp_params",
                                    "to_globalexp_params",
                                ]:
                                    extra_params[k] = eval_val(v)
                        action.action_name = request.url.path.strip("/").split("/")[-1]
                        action.action_server = MachineModel(
                            server_name=server_key, machine_name=gethostname().lower()
                        )
                        # send active status but don't create active object
                        await self.base.status_q.put(action.get_actmodel())
                        response = JSONResponse(action.as_dict())
                        self.base.print_message(
                            f"action request for {action.action_name} received, but server does not allow concurrency, queuing action {action.action_uuid}"
                        )
                        self.base.local_action_queue.put((action, {},))
                    else:
                        LOGGER.debug("action endpoint is available")
                        response = await call_next(request)
                elif (
                    len(self.base.actionservermodel.endpoints[endpoint].active_dict)
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
                    action = Action(**action_dict)
                    for d in (
                        request.query_params,
                        request.path_params,
                    ):
                        for k, v in d.items():
                            if k in [
                                "action_version",
                                "start_condition",
                                "from_globalexp_params",
                                "to_globalexp_params",
                            ]:
                                extra_params[k] = eval_val(v)
                    action.action_name = request.url.path.strip("/").split("/")[-1]
                    action.action_server = MachineModel(
                        server_name=server_key, machine_name=gethostname().lower()
                    )
                    # send active status but don't create active object
                    await self.base.status_q.put(action.get_actmodel())
                    response = JSONResponse(action.as_dict())
                    self.base.print_message(
                        f"simultaneous action requests for {action.action_name} received, queuing action {action.action_uuid}"
                    )
                    self.base.endpoint_queues[endpoint].put(
                        (
                            action,
                            {},
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
                for _, active in self.base.actives.items():
                    active.set_estop()
                for executor_id in self.base.executors:
                    self.base.stop_executor(executor_id)
            return await http_exception_handler(request, exc)

        @self.on_event("startup")
        def startup_event():
            self.base = Base(fastapp=self, dyn_endpoints=dyn_endpoints)

            self.root_dir = self.base.world_cfg.get("root", None)
            if self.root_dir is not None:
                self.fault_dir = os.path.join(self.root_dir, "FAULTS")
                os.makedirs(self.fault_dir, exist_ok=True)
                fault_path = os.path.join(self.fault_dir, f"{server_key}_faults.txt")
                self.fault_file = open(fault_path, "a")
                faulthandler.enable(self.fault_file)

            self.base.myinit()
            if driver_class is not None:
                if issubclass(driver_class, HelaoDriver):
                    self.driver = driver_class(config=self.server_params)
                    if poller_class is not None:
                        self.poller = poller_class(
                            self.driver, self.server_cfg.get("polling_time", 0.1)
                        )
                        self.poller._base_hook = self.base
                else:
                    self.driver = driver_class(self.base)
            self.base.dyn_endpoints_init()

        @self.on_event("startup")
        async def add_default_head_endpoints() -> None:
            for route in self.routes:
                if isinstance(route, APIRoute) and "POST" in route.methods:
                    new_route = copy(route)
                    new_route.methods = {"HEAD"}
                    new_route.include_in_schema = False
                    self.routes.append(new_route)

        @self.websocket("/ws_status")
        async def websocket_status(websocket: WebSocket):
            """Broadcast status messages.

            Args:
            websocket: a fastapi.WebSocket object
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
            """Broadcast status dicts.

            Args:
            websocket: a fastapi.WebSocket object
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
            """Broadcast live buffer dicts.

            Args:
            websocket: a fastapi.WebSocket object
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
            return self.base.world_cfg

        @self.post("/get_status", tags=["private"])
        def get_status():
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
            status_dict['_driver_status'] = driver_status
            return status_dict

        @self.post("/attach_client", tags=["private"])
        async def attach_client(
            client_servkey: str, client_host: str, client_port: int
        ):
            return await self.base.attach_client(
                client_servkey, client_host, client_port
            )

        @self.post("/stop_executor", tags=["private"])
        def stop_executor(executor_id: str):
            return self.base.stop_executor(executor_id)

        @self.post("/endpoints", tags=["private"])
        def get_all_urls():
            """Return a list of all endpoints on this server."""
            return self.base.fast_urls

        @self.post("/get_lbuf", tags=["private"])
        def get_lbuf():
            return self.base.live_buffer

        @self.post("/list_executors", tags=["private"])
        def list_executors():
            return list(self.base.executors.keys())

        @self.post("/_raise_exception", tags=["private"])
        def _raise_exception():
            raise Exception("test exception for error recovery debugging")

        @self.post("/_raise_async_exception", tags=["private"])
        async def _raise_async_exception():
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
            l10 = [y for x, y in self.base.last_10_active]
            if l10:
                return l10[0].action.as_dict()
            else:
                return Action(action_uuid=action_uuid).as_dict()

        @self.post("/shutdown", tags=["private"])
        async def post_shutdown():
            await shutdown_event()

        @self.on_event("shutdown")
        async def shutdown_event():
            self.base.print_message("action shutdown", info=True)
            await self.base.shutdown()

            shutdown = getattr(self.driver, "shutdown", None)
            async_shutdown = getattr(self.driver, "async_shutdown", None)

            retvals = {}
            if shutdown is not None and callable(shutdown):
                self.base.print_message("driver has shutdown function", info=True)
                retvals["shutdown"] = shutdown()
            else:
                self.base.print_message("driver has NO shutdown function", info=True)
                retvals["shutdown"] = None
            if async_shutdown is not None and callable(async_shutdown):
                self.base.print_message("driver has async_shutdown function", info=True)
                retvals["async_shutdown"] = await async_shutdown()
            else:
                self.base.print_message(
                    "driver has NO async_shutdown function", info=True
                )
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
            active = await self.base.setup_and_contain_action(
                json_data_keys=["estop"], action_abbr="estop"
            )
            has_estop = getattr(self.driver, "estop", None)
            if has_estop is not None and callable(has_estop):
                self.base.print_message("driver has estop function", info=True)
                await active.enqueue_data_dflt(
                    datadict={
                        "estop": await self.driver.estop(**active.action.action_params)
                    }
                )
            else:
                self.base.print_message("driver has NO estop function", info=True)
                self.base.actionservermodel.estop = switch
            if switch:
                active.action.action_status.append(HloStatus.estopped)
            for executor_id in self.base.executors:
                self.base.stop_executor(executor_id)
            finished_action = await active.finish()
            return finished_action.as_dict()
