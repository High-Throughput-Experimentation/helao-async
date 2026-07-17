"""Status port (spec §4.3.6): push + dual WS stacks.

Both parallel WS mechanisms survive (consumers exist for each): the
WsPublisher-backed /ws_status /ws_data /ws_live routes AND the _ws_relay
zstd-compressed-pickle streams. Serialization happens ONLY in the adapter
(KEEP #4: _json_clean at the relay). The legacy blocking 0.3 s per-client
pacing is preserved behavior until post-parity.
"""

from typing import Protocol, runtime_checkable
from uuid import UUID

from helao.hexagon.domain.models import ActionServerModel

__all__ = ["StatusPort"]


@runtime_checkable
class StatusPort(Protocol):
    async def attach_client(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        retry_limit: int = 5,
    ) -> bool: ...

    async def detach_client(
        self, client_servkey: str, client_host: str, client_port: int
    ) -> None: ...

    async def send_status(self, asm: ActionServerModel, retries: int = 5) -> None:
        """POST the full/filtered ActionServerModel to every registered
        client's private /update_status."""
        ...

    async def send_nonblocking_status(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        server_key: str,
        exec_id: str,
        act_uuid: UUID,
        status: str,
        retries: int = 3,
    ) -> None:
        """Nonblocking executors push /update_nonblocking directly."""
        ...

    async def publish_status(self, payload: dict) -> None: ...

    async def publish_data(self, payload: dict) -> None: ...

    async def publish_live(self, payload: dict) -> None: ...
