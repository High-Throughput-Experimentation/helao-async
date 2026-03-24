from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Callable, Dict, Optional, TYPE_CHECKING

from fastapi import Body, WebSocket
from starlette.websockets import WebSocketDisconnect

from helao.core.models.server import ActionServerModel
from helao.core.models.orchstatus import LoopStatus, OrchStatus
from helao.core.models.hlostatus import HloStatus
from helao.helpers.server_api import HelaoFastAPI
from helao.helpers import helao_logging as logging

if TYPE_CHECKING:
	from helao.core.servers.orch import Orch


LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class StatusClient:
	"""Receives and applies action-server status updates to an orchestrator."""

	def __init__(self, orch_getter: Callable[[], Orch]):
		self._orch_getter = orch_getter
		self._receivers: Dict[str, Receiver] = {}

	@property
	def orch(self) -> Orch:
		orch = self._orch_getter()
		if orch is None:
			raise RuntimeError("Orchestrator has not been initialized yet.")
		return orch

	def register_receiver(self, protocol: str, receiver: "Receiver"):
		self._receivers[protocol.lower()] = receiver

	def get_receiver(self, protocol: str) -> "Receiver":
		recv = self._receivers.get(protocol.lower())
		if recv is None:
			raise ValueError(f"No receiver registered for protocol '{protocol}'.")
		return recv

	async def receive_status(
		self,
		actionservermodel: Optional[ActionServerModel] = None,
		regular_task: str = "false",
		protocol: str = "rest",
	) -> bool:
		receiver = self.get_receiver(protocol)
		return await receiver.receive_status(
			actionservermodel=actionservermodel,
			regular_task=regular_task,
		)

	async def update_status(
		self,
		actionservermodel: Optional[ActionServerModel] = None,
	) -> bool:
		"""Replicates Orch.update_status for externally received status updates."""
		orch = self.orch

		if actionservermodel is None:
			return False

		async with orch.aiolock:
			if actionservermodel.last_action_uuid is not None:
				for _, endpoint_model in actionservermodel.endpoints.items():
					for _, act_dict in endpoint_model.nonactive_dict.items():
						for act_uuid, act_model in act_dict.items():
							if act_uuid == actionservermodel.last_action_uuid:
								orch.register_action_uuid(
									act_uuid,
									{
										"action_name": act_model.action_name,
										"action_status": act_model.action_status,
										"action_server": act_model.action_server.server_name,
										"action_timestamp": f"{act_model.action_timestamp: %m-%d %H:%M:%S}",
										"action_finished_timestamp": (
											f"{act_model.action_finished_timestamp: %m-%d %H:%M:%S}"
											if act_model.action_finished_timestamp
											is not None
											else None
										),
										"experiment_name": (
											orch.active_experiment.experiment_name
											if orch.active_experiment is not None
											else None
										),
										"experiment_uuid": act_model.experiment_uuid,
										"sequence_name": (
											orch.active_sequence.sequence_name
											if orch.active_sequence is not None
											else None
										),
										"sequence_label": (
											orch.active_sequence.sequence_label
											if orch.active_sequence is not None
											else None
										),
										"sequence_uuid": (
											orch.active_sequence.sequence_uuid
											if orch.active_sequence is not None
											else None
										),
									},
								)
								break

			recent_nonactive = orch.globalstatusmodel.update_global_with_acts(
				actionservermodel=actionservermodel
			)

			for act_uuid, act_status in recent_nonactive:
				await orch.put_lbuf({act_uuid: {"status": act_status}})

			estop_uuids = orch.globalstatusmodel.find_hlostatus_in_finished(
				hlostatus=HloStatus.estopped,
			)
			error_uuids = orch.globalstatusmodel.find_hlostatus_in_finished(
				hlostatus=HloStatus.errored,
			)

			if estop_uuids and orch.globalstatusmodel.loop_state == LoopStatus.started:
				await orch.estop_loop(reason=f"due to action uuid(s): {estop_uuids}")
			elif (
				error_uuids and orch.globalstatusmodel.loop_state == LoopStatus.started
			):
				orch.globalstatusmodel.orch_state = OrchStatus.error
			elif not orch.globalstatusmodel.active_dict:
				orch.globalstatusmodel.orch_state = OrchStatus.idle
			else:
				orch.globalstatusmodel.orch_state = OrchStatus.busy
				LOGGER.info(f"running_states: {orch.globalstatusmodel.active_dict}")

			await orch.interrupt_q.put(orch.globalstatusmodel)
			await orch.update_operator(True)
			return True


class Receiver(ABC):
	"""Protocol-specific status receiver."""

	protocol: str = ""

	def __init__(self, status_client: StatusClient):
		self.status_client = status_client

	@abstractmethod
	async def receive_status(
		self,
		actionservermodel: Optional[ActionServerModel] = None,
		regular_task: str = "false",
	) -> bool:
		raise NotImplementedError

	@abstractmethod
	def register(self, app: HelaoFastAPI):
		raise NotImplementedError


class RESTReceiver(Receiver):
	"""REST receiver that mirrors the /update_status private endpoint semantics."""

	protocol = "rest"

	async def receive_status(
		self,
		actionservermodel: Optional[ActionServerModel] = None,
		regular_task: str = "false",
	) -> bool:
		if actionservermodel is None:
			return False
		if regular_task == "false":
			LOGGER.debug(
				f"orch '{self.status_client.orch.server.server_name}' got status from '{actionservermodel.action_server.server_name}': {actionservermodel.endpoints}"
			)
		return await self.status_client.update_status(actionservermodel=actionservermodel)

	def register(self, app: HelaoFastAPI):
		self.status_client.register_receiver(self.protocol, self)

		@app.post("/update_status", tags=["private"])
		async def update_status(
			actionservermodel: ActionServerModel = Body({}, embed=True),
			regular_task: str = "false",
		):
			return await self.receive_status(
				actionservermodel=actionservermodel,
				regular_task=regular_task,
			)


class WebSocketReceiver(Receiver):
	"""WebSocket receiver scaffold for status updates."""

	protocol = "websocket"

	def __init__(self, status_client: StatusClient, ws_path: str = "/ws_update_status"):
		super().__init__(status_client)
		self.ws_path = ws_path

	async def receive_status(
		self,
		actionservermodel: Optional[ActionServerModel] = None,
		regular_task: str = "false",
	) -> bool:
		if actionservermodel is None:
			return False
		if regular_task == "false":
			LOGGER.debug(
				f"orch '{self.status_client.orch.server.server_name}' got websocket status from '{actionservermodel.action_server.server_name}': {actionservermodel.endpoints}"
			)
		return await self.status_client.update_status(actionservermodel=actionservermodel)

	def register(self, app: HelaoFastAPI):
		self.status_client.register_receiver(self.protocol, self)

		@app.websocket(self.ws_path)
		async def ws_update_status(websocket: WebSocket):
			await websocket.accept()
			try:
				while True:
					payload = await websocket.receive_json()
					regular_task = str(payload.get("regular_task", "false"))
					actionservermodel_dict = payload.get("actionservermodel")
					if actionservermodel_dict is None:
						await websocket.send_json(
							{
								"success": False,
								"error": "missing 'actionservermodel' in payload",
							}
						)
						continue
					actionservermodel = ActionServerModel(**actionservermodel_dict)
					success = await self.receive_status(
						actionservermodel=actionservermodel,
						regular_task=regular_task,
					)
					await websocket.send_json({"success": success})
			except WebSocketDisconnect:
				LOGGER.debug("status websocket client disconnected")
			except Exception as exc:
				LOGGER.warning(f"status websocket receiver error: {exc}")


class QueueReceiver(Receiver):
	"""Queue-based receiver scaffold for status updates."""

	protocol = "queue"

	def __init__(self, status_client: StatusClient, queue: Optional[asyncio.Queue] = None):
		super().__init__(status_client)
		self.queue = queue or asyncio.Queue()
		self.consumer_task: Optional[asyncio.Task] = None

	async def receive_status(
		self,
		actionservermodel: Optional[ActionServerModel] = None,
		regular_task: str = "false",
	) -> bool:
		if actionservermodel is None:
			return False
		if regular_task == "false":
			LOGGER.debug(
				f"orch '{self.status_client.orch.server.server_name}' got queued status from '{actionservermodel.action_server.server_name}': {actionservermodel.endpoints}"
			)
		return await self.status_client.update_status(actionservermodel=actionservermodel)

	def register(self, app: HelaoFastAPI):
		self.status_client.register_receiver(self.protocol, self)

	async def enqueue(
		self,
		actionservermodel: ActionServerModel,
		regular_task: str = "false",
	):
		await self.queue.put(
			{
				"actionservermodel": actionservermodel,
				"regular_task": regular_task,
			}
		)

	async def consume_once(self) -> bool:
		item = await self.queue.get()
		try:
			actionservermodel = item.get("actionservermodel")
			regular_task = str(item.get("regular_task", "false"))
			return await self.receive_status(
				actionservermodel=actionservermodel,
				regular_task=regular_task,
			)
		finally:
			self.queue.task_done()

	async def consume_forever(self):
		while True:
			await self.consume_once()

	def start_consumer(self):
		if self.consumer_task is None or self.consumer_task.done():
			self.consumer_task = asyncio.create_task(self.consume_forever())

	async def stop_consumer(self):
		if self.consumer_task is not None and not self.consumer_task.done():
			self.consumer_task.cancel()
			try:
				await self.consumer_task
			except asyncio.CancelledError:
				pass

