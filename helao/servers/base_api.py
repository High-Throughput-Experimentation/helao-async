import json
from copy import copy
from socket import gethostname
from helao.servers.base import Base
from helao.helpers.server_api import HelaoFastAPI
from helao.helpers.premodels import Action
from helao.helpers.active_params import ActiveParams
from helaocore.models.machine import MachineModel
from fastapi import Body, WebSocket, WebSocketDisconnect, Request
from helaocore.models.hlostatus import HloStatus
from helaocore.models.action_start_condition import ActionStartCondition as ASC
from starlette.types import Message
from starlette.responses import JSONResponse


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
    ):
        super().__init__(
            helao_cfg=config,
            helao_srv=server_key,
            title=server_title,
            description=description,
            version=version,
        )
        self.driver = None

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
            endpoint_name = request.url.path.strip("/").split("/")[-1]
            if request.url.path.strip("/").startswith(f"{server_key}/"):
                # copy original request for queuing
                self.base.aiolock.acquire()
                original_req = copy(request)
                await set_body(request, await request.body())
                body_bytes = await get_body(request)
                body_dict = json.loads(body_bytes.decode("utf8").replace("'", '"'))
                action_dict = body_dict.get("action", {})
                start_cond = action_dict.get("action_start_condition", ASC.wait_for_all)
                if start_cond == ASC.no_wait:
                    self.base.aiolock.release()
                    response = await call_next(request)
                elif start_cond == ASC.wait_for_server and all(
                    [q.qsize() == 0 for q in self.base.endpoint_queues.values()]
                ):
                    self.base.aiolock.release()
                    response = await call_next(request)
                elif (
                    start_cond == ASC.wait_for_endpoint
                    and self.base.endpoint_queues[endpoint_name].qsize() == 0
                ):
                    self.base.aiolock.release()
                    response = await call_next(request)
                else:  # collision between two orch requests for one resource, queue
                    action_dict["action_params"] = action_dict.get("action_params", {})
                    for d in (
                        request.query_params,
                        request.path_params,
                    ):
                        for k, v in d.items():
                            if k == "action_version":
                                action_dict[k] = v
                            else:
                                action_dict["action_params"][k] = v

                    action = Action(**action_dict)
                    action.action_name = request.url.path.strip("/").split("/")[-1]
                    action.action_server = MachineModel(
                        server_name=server_key, machine_name=gethostname().lower()
                    )
                    # activate a placeholder action while queued
                    active = await self.base.contain_action(
                        activeparams=ActiveParams(action=action)
                    )
                    return_dict = active.action.as_dict()
                    return_dict["action_status"].append("queued")
                    response = JSONResponse(return_dict)
                    self.base.endpoint_queues[endpoint_name].put(
                        (action_dict.get("orch_priority", 1), (original_req, call_next))
                    )
                    self.base.aiolock.release()
            else:
                response = await call_next(request)
            return response

        @self.on_event("startup")
        def startup_event():
            self.base = Base(fastapp=self, dyn_endpoints=dyn_endpoints)
            self.base.myinit()
            if driver_class is not None:
                self.driver = driver_class(self.base)
            self.base.dyn_endpoints_init()
            self.base.endpoint_queues_init()

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

        @self.post("/get_config", tags=["private"])
        def get_config():
            return self.base.world_cfg

        @self.post("/get_status", tags=["private"])
        def get_status():
            return self.base.actionservermodel

        @self.post("/attach_client", tags=["private"])
        async def attach_client(client_servkey: str):
            return await self.base.attach_client(client_servkey)

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
            finished_action = await active.finish()
            return finished_action.as_dict()
