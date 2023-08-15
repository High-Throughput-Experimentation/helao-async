from helao.servers.base import Base
from helao.helpers.server_api import HelaoFastAPI
from helao.helpers.premodels import Action
from fastapi import Body, WebSocket, WebSocketDisconnect, Request
from helaocore.models.hlostatus import HloStatus


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

        @self.on_event("startup")
        def startup_event():
            self.base = Base(fastapp=self, dyn_endpoints=dyn_endpoints)
            self.base.myinit()
            if driver_class is not None:
                self.driver = driver_class(self.base)
            self.base.dyn_endpoints_init()

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

        @self.middleware("http")
        async def check_resource(request: Request, call_next):
            async with self.base.aiolock:
                reqd = await request.json()
                self.base.print_message(reqd)
            response = await call_next(request)
            return response, reqd

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
