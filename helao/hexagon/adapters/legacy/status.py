"""StatusPort adapter: wire-level status push over the legacy dispatcher.

Wraps the SAME wire calls base_status's broadcaster makes: private
/update_status (full ActionServerModel + regular_task flag) and
/update_nonblocking (an actionmodel body + the reporting server's own
host/port). Keeps its own client registry (attach/detach). The WS publish_*
members are WIRED (P2b-2 — DD-7 discharged): they delegate to a
WsPublishBridge bound at makeActionApp startup, which model-validates each
payload back to its channel's wire type and puts it on the legacy fan-out
queues (adapter-local drift fix D1, like the three drifts below). Before
binding they raise UnwiredPortError loudly. Orch compositions never bind
the bridge — their live WS channels stay on legacy Base relays (Q1).

Drift fixed against the brief's sketch: the real ``/update_nonblocking``
endpoint (helao/core/servers/orch_api.py) takes ``server_host``/``server_port``
as query params and an ``actionmodel`` (Action-shaped dict) as the JSON body
-- NOT flat ``server_key``/``executor_id``/``action_uuid``/``status`` query
keys with an empty body, as a first pass would suggest. This adapter sends
the actionmodel sub-fields the port gives us (exec_id, action_uuid,
action_status, action_server.server_name) under the correct ``actionmodel``
body key, and ``server_host``/``server_port`` under the correct query keys.

Own identity (closed P1b1 gap): the composition (factory.build_wiring)
constructs this adapter with ``own_host``/``own_port`` taken from the
server's own config entry, so downstream ``clear_nonblocking`` bookkeeping
(keyed on host/port in orch_status_sync) sees the real reporting identity.
The ``""``/``0`` defaults remain only for unit construction convenience.

Second drift (flagged, adapter-local fix only -- the port itself is P1a-owned
and out of scope here): ``StatusPort.send_nonblocking_status`` declares
``act_uuid: UUID`` (non-Optional), but a nonblocking transition can be
reported before an action UUID is known; this adapter widens its own
parameter to ``Optional[UUID]`` to accept that and passes it through as
``None`` in the actionmodel body when absent.

Third drift (P1b2b Task 6, adapter-local fix): the real ``/update_nonblocking``
endpoint's ``Orch.update_nonblocking`` (orch_status_sync.py) unconditionally
f-string-formats ``actionmodel.action_timestamp`` with a ``%m-%d %H:%M:%S``
format spec (``f"{actionmodel.action_timestamp: %m-%d %H:%M:%S}"``), which
raises on ``None`` (``NoneType.__format__`` rejects a format spec). This
adapter therefore always sends a real, well-formed ISO timestamp under
``actionmodel.action_timestamp`` -- pydantic's ``Action.action_timestamp:
Optional[datetime]`` parses the ISO string back into a ``datetime`` on the
legacy side, so the format spec always has a real datetime to work with."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from helao.helpers.dispatcher import async_private_dispatcher
from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.native.ws_publish import WsPublishBridge
from helao.hexagon.domain.models import ActionServerModel

__all__ = ["DispatcherStatusAdapter"]


class DispatcherStatusAdapter:
    def __init__(self, server_key: str, own_host: str = "", own_port: int = 0):
        self._server_key = server_key
        self._own_host = own_host
        self._own_port = own_port
        self.clients: list[tuple[str, str, int]] = []
        self._publish_bridge: Optional[WsPublishBridge] = None

    def bind_publish_bridge(self, bridge: WsPublishBridge) -> None:
        """Late-bind the WS publish bridge (P2b-2 D3): the fan-out queues
        live on the legacy Base, which only exists once the app has started,
        so makeActionApp's startup hook constructs the bridge and binds it
        here (mirror of the P2b-1 NativeArtifactStoreAdapter.bind_base
        pattern)."""
        self._publish_bridge = bridge

    async def attach_client(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        retry_limit: int = 5,
    ) -> bool:
        key = (client_servkey, client_host, client_port)
        if key not in self.clients:
            self.clients.append(key)
        return True

    async def detach_client(
        self, client_servkey: str, client_host: str, client_port: int
    ) -> None:
        try:
            self.clients.remove((client_servkey, client_host, client_port))
        except ValueError:
            pass  # legacy detach tolerates unknown clients

    async def send_status(self, asm: ActionServerModel, retries: int = 5) -> None:
        for client_servkey, host, port in list(self.clients):
            for _ in range(retries):
                resp, _err = await async_private_dispatcher(
                    client_servkey,
                    host,
                    port,
                    "update_status",
                    {},
                    {"actionservermodel": asm.as_dict()},
                )
                if resp is not None:
                    break

    async def send_nonblocking_status(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        server_key: str,
        exec_id: str,
        act_uuid: Optional[UUID],
        status: str,
        retries: int = 3,
    ) -> None:
        params_dict = {"server_host": self._own_host, "server_port": self._own_port}
        json_dict = {
            "actionmodel": {
                "action_uuid": str(act_uuid) if act_uuid is not None else None,
                "exec_id": exec_id,
                "action_status": [status],
                "action_server": {"server_name": server_key},
                # real, well-formed timestamp (third drift, above): a missing
                # one 500s the legacy endpoint's f-string format spec.
                "action_timestamp": datetime.now().isoformat(),
            }
        }
        for _ in range(retries):
            resp, _err = await async_private_dispatcher(
                client_servkey,
                client_host,
                client_port,
                "update_nonblocking",
                params_dict,
                json_dict,
            )
            if resp is not None:
                break

    async def publish_status(self, payload: dict) -> None:
        if self._publish_bridge is None:
            raise UnwiredPortError(
                "publish_status before bind_publish_bridge (bound at "
                "makeActionApp startup; orch compositions stay on legacy WS)"
            )
        await self._publish_bridge.publish_status(payload)

    async def publish_data(self, payload: dict) -> None:
        if self._publish_bridge is None:
            raise UnwiredPortError(
                "publish_data before bind_publish_bridge (bound at "
                "makeActionApp startup; orch compositions stay on legacy WS)"
            )
        await self._publish_bridge.publish_data(payload)

    async def publish_live(self, payload: dict) -> None:
        if self._publish_bridge is None:
            raise UnwiredPortError(
                "publish_live before bind_publish_bridge (bound at "
                "makeActionApp startup; orch compositions stay on legacy WS)"
            )
        await self._publish_bridge.publish_live(payload)
