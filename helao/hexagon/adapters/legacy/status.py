"""StatusPort adapter: wire-level status push over the legacy dispatcher.

Wraps the SAME wire calls base_status's broadcaster makes: private
/update_status (full ActionServerModel + regular_task flag) and
/update_nonblocking (an actionmodel body + the reporting server's own
host/port). Keeps its own client registry (attach/detach). The WS publish_*
members (WsPublisher / _ws_relay zstd-pickle) are deliberately deferred
(DD-7) — they raise HexagonDeferred loudly; in the P1b1 wrapped-legacy
composition the live WS channels run on legacy Base relays.

Drift fixed against the brief's sketch: the real ``/update_nonblocking``
endpoint (helao/core/servers/orch_api.py) takes ``server_host``/``server_port``
as query params and an ``actionmodel`` (Action-shaped dict) as the JSON body
-- NOT flat ``server_key``/``executor_id``/``action_uuid``/``status`` query
keys with an empty body, as a first pass would suggest. This adapter sends
the actionmodel sub-fields the port gives us (exec_id, action_uuid,
action_status, action_server.server_name) under the correct ``actionmodel``
body key, and ``server_host``/``server_port`` under the correct query keys.

Known gap (flagged, not silently papered over): ``StatusPort.send_nonblocking_status``
does not pass the reporting server's own host/port, only the port's
constructor knows them (``own_host``/``own_port``, defaulting to ``""``/``0``
when unset) -- a real composition must supply them at construction time or
downstream ``clear_nonblocking`` bookkeeping (keyed on host/port) will be
wrong. This is a P1b2-scoped follow-up, not a P1b1 blocker (send/attach/detach
still function correctly for the push path).

Second drift (flagged, adapter-local fix only -- the port itself is P1a-owned
and out of scope here): ``StatusPort.send_nonblocking_status`` declares
``act_uuid: UUID`` (non-Optional), but a nonblocking transition can be
reported before an action UUID is known; this adapter widens its own
parameter to ``Optional[UUID]`` to accept that and passes it through as
``None`` in the actionmodel body when absent."""

from typing import List, Optional, Tuple
from uuid import UUID

from helao.helpers.dispatcher import async_private_dispatcher
from helao.hexagon.adapters.errors import HexagonDeferred
from helao.hexagon.domain.models import ActionServerModel

__all__ = ["DispatcherStatusAdapter"]


class DispatcherStatusAdapter:
    def __init__(self, server_key: str, own_host: str = "", own_port: int = 0):
        self._server_key = server_key
        self._own_host = own_host
        self._own_port = own_port
        self.clients: List[Tuple[str, str, int]] = []

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
        raise HexagonDeferred("WS publish bridge is P1b2 (DD-7)")

    async def publish_data(self, payload: dict) -> None:
        raise HexagonDeferred("WS publish bridge is P1b2 (DD-7)")

    async def publish_live(self, payload: dict) -> None:
        raise HexagonDeferred("WS publish bridge is P1b2 (DD-7)")
