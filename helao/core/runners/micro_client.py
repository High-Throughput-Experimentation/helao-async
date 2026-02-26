import asyncio
from typing import Optional

from fastapi import Body

from helao.core.models.hlostatus import HloStatus
from helao.core.models.orchstatus import OrchStatus, LoopStatus
from helao.core.models.server import ActionServerModel, GlobalStatusModel
from helao.helpers.server_api import HelaoFastAPI
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class MinimalOrch:
    """Minimal Orch implementation supporting update_status only."""

    def __init__(self, fastapp: HelaoFastAPI):
        self.fastapp = fastapp
        self.aiolock = asyncio.Lock()
        self.interrupt_q = asyncio.Queue()
        self.last_50_action_uuids = []
        self.globalstatusmodel = GlobalStatusModel(orchestrator=self.fastapp.server)
        self.globalstatusmodel._sort_status()

    def register_action_uuid(self, action_uuid: str) -> None:
        if action_uuid not in self.last_50_action_uuids:
            while len(self.last_50_action_uuids) >= 50:
                self.last_50_action_uuids.pop(0)
            self.last_50_action_uuids.append(action_uuid)

    async def update_status(
        self, actionservermodel: Optional[ActionServerModel] = None
    ) -> bool:
        if actionservermodel is None:
            return False

        async with self.aiolock:
            if actionservermodel.last_action_uuid is not None:
                self.register_action_uuid(actionservermodel.last_action_uuid)

            estop_uuids = self.globalstatusmodel.find_hlostatus_in_finished(
                hlostatus=HloStatus.estopped
            )
            error_uuids = self.globalstatusmodel.find_hlostatus_in_finished(
                hlostatus=HloStatus.errored
            )

            if estop_uuids and self.globalstatusmodel.loop_state == LoopStatus.started:
                self.globalstatusmodel.loop_state = LoopStatus.estopped
                self.globalstatusmodel.orch_state = OrchStatus.error
            elif error_uuids and self.globalstatusmodel.loop_state == LoopStatus.started:
                self.globalstatusmodel.orch_state = OrchStatus.error
            elif not self.globalstatusmodel.active_dict:
                self.globalstatusmodel.orch_state = OrchStatus.idle
            else:
                self.globalstatusmodel.orch_state = OrchStatus.busy

            await self.interrupt_q.put(self.globalstatusmodel)
            return True


class MicroOrchAPI(HelaoFastAPI):
    """Minimal OrchAPI implementation with update_status endpoint."""

    orch: MinimalOrch

    def __init__(
        self,
        server_key: str,
        server_title: str,
        description: str,
        version: str,
    ):
        """
        Initialize the minimal OrchAPI server.

        Args:
            server_key (str): Unique key identifying the server.
            server_title (str): Title of the server.
            description (str): Description of the server.
            version (str): Version of the server.
        """
        super().__init__(
            helao_srv=server_key,
            title=server_title,
            description=description,
            version=str(version),
        )

        @self.on_event("startup")
        async def startup_event():
            """Initialize the orchestrator on startup."""
            self.orch = MinimalOrch(fastapp=self)

        @self.post("/update_status", tags=["private"])
        async def update_status(
            actionservermodel: ActionServerModel = Body({}, embed=True),
            regular_task: str = "false",
        ):
            """
            Asynchronously updates the status of an action server.

            Args:
                actionservermodel (ActionServerModel, optional): The model containing the action server's status information.
                regular_task (str): Flag indicating if this is a regular task update.

            Returns:
                bool: Returns False if the actionservermodel is None, otherwise returns the result of the orch's update_status method.
            """
            if actionservermodel is None:
                LOGGER.warning("Received None actionservermodel")
                return False

            if regular_task == "false":
                LOGGER.info(
                    f"Received status update from {actionservermodel.action_server.server_name}"
                )

            return await self.orch.update_status(actionservermodel=actionservermodel)

