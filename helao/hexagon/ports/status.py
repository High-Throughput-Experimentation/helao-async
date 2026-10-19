"""Status port (spec §4.3.6): push + one WS mechanism, two producers.

One WS mechanism, two producers: ``ActionHost`` and ``OrchHost`` both serve
/ws_status /ws_data /ws_live through ``WsPublisher``, which sends each
message as a zstd-compressed pickle. Serialization happens ONLY in
``WsPublisher.broadcast``.

``StatusPort`` is the publish side. The consumer side (Bokeh's
``WsSubscriber``, the orchestrator relay streams, the Reflex
``helao.ui.reflex.ingest.NORMALIZERS`` map) has no port here: those readers are
UI-stack code that does not go through the hexagon.
"""

from typing import Protocol, runtime_checkable
from uuid import UUID

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
