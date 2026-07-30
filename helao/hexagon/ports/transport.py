"""Transport port (spec §4.3.5, §7): ZMQ-first RPC + HTTP-fallback dispatch.

Abstracts helao/helpers/dispatcher.py + helao/core/rpc/zmq_rpc.py. Contract
highlights the P1b adapter must honor:
- RPC port pairing derive_rpc_port(http_port) = http_port + 10000; 3 s probe
  timeout IS the down-detector.
- Action dispatch: RPC method "<server_name>/<action_name>", kwargs =
  params + {"action": A.as_dict()}; HTTP fallback POST
  http://host:port/<server>/<action>, json {"action": A.as_dict()},
  <=5 retries linear backoff. Returns (response_json | None, ErrorCodes).
- Semantic difference preserved: HTTP traverses the action-queuing
  middleware; RPC bypasses it.
- NEVER self-RPC from inside the dispatch loop (in-process self-ops).
"""

from typing import Optional, Protocol, runtime_checkable

from helao.hexagon.domain.models import Action, ErrorCodes

__all__ = ["TransportPort"]


@runtime_checkable
class TransportPort(Protocol):
    async def dispatch_action(
        self,
        action: Action,
        params: Optional[dict] = None,
        timeout: float = 60,
        retries: int = 5,
    ) -> tuple[Optional[dict], ErrorCodes]: ...

    async def dispatch_private(
        self,
        server_key: str,
        host: str,
        port: int,
        private_action: str,
        params_dict: Optional[dict] = None,
        json_dict: Optional[dict] = None,
        timeout: float = 60,
        retries: int = 5,
    ) -> tuple[Optional[dict], ErrorCodes]: ...

    async def check_endpoint(self, url: str, timeout: float = 3.0) -> bool:
        """HEAD probe (endpoints_available / heartbeat monitor)."""
        ...
