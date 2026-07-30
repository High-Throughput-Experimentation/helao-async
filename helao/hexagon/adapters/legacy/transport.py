"""TransportPort adapter (spec §4.3.5/§7): wraps the legacy dispatchers.

ZMQ-first RPC on derive_rpc_port(http_port)=http_port+10000 with the 3 s
probe timeout as down-detector, HTTP fallback with the legacy retry/backoff —
all inside helao.helpers.dispatcher; this adapter is thin delegation. The
co-located RPC SERVER side (ROUTER bind to the configured host with 0.0.0.0
fallback, commits 8dc8a0a8/7e737137) lives in HelaoFastAPI and is inherited
by every hexagon-composed app; test_adapter_transport pins the fast path.
NEVER self-RPC from inside the dispatch loop (KEEP #3) — the loop calls orch
methods directly; this adapter is for PEER dispatch only.
"""

import asyncio
from typing import Optional

from helao.helpers.dispatcher import (
    async_action_dispatcher,
    async_private_dispatcher,
    check_endpoint,
)
from helao.hexagon.domain.models import Action, ErrorCodes
from helao.hexagon.ports.config import ConfigPort

__all__ = ["LegacyTransportAdapter"]


class LegacyTransportAdapter:
    def __init__(self, config: ConfigPort):
        self._config = config

    async def dispatch_action(
        self,
        action: Action,
        params: Optional[dict] = None,
        timeout: float = 60,
        retries: int = 5,
    ) -> tuple[Optional[dict], ErrorCodes]:
        return await async_action_dispatcher(
            self._config.world_cfg(),
            action,
            params=params or {},
            # Legacy signature types `timeout` as `int`; the port contract
            # is `float`. Runtime accepts float fine (asyncio.wait_for /
            # aiohttp.ClientTimeout both do) — narrower legacy annotation
            # only, not a real constraint. NOT a legacy edit.
            timeout=timeout,  # type: ignore[arg-type]
            retries=retries,
        )

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
    ) -> tuple[Optional[dict], ErrorCodes]:
        return await async_private_dispatcher(
            server_key,
            host,
            port,
            private_action,
            params_dict or {},
            json_dict or {},
            timeout=timeout,  # type: ignore[arg-type]  # see dispatch_action
            retries=retries,
        )

    async def check_endpoint(self, url: str, timeout: float = 3.0) -> bool:
        try:
            code = await asyncio.wait_for(check_endpoint(url), timeout=timeout)
        except Exception:
            return False
        return 200 <= int(code) < 400
