"""Deployment-compatible FastAPI subclass wrapping FrameworkBase.

Port of the ``BaseAPI`` pattern from ``helao.core.servers.base_api``.
Deployment action servers do:

    app = BaseAPI(server_key=server_key, driver_classes=[MyDriver])

and then decorate ``@app.post(...)`` endpoints that call
``await app.base.setup_and_contain_action()``. This class wires a
``FrameworkBase`` with real adapters and exposes it as ``app.base``.

Only the action-server surface is implemented here. WebSocket status/data
publishers and the per-server admin endpoints are added in the full
production wiring (a later SP).
"""

__all__ = ["BaseAPI"]

import tempfile
from typing import Dict, List, Optional, Type

from fastapi import FastAPI

from helao.framework.app.base_api import FrameworkBase
from helao.framework.adapters.fs_storage import FsStorage
from helao.framework.adapters.ntp_clock import NtpClock
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.adapters.fakes.transport import FakeTransport
import helao.framework.support.config_loader as _cfg


def _load_world_cfg() -> Dict:
    cfg = _cfg.CONFIG
    if cfg is None:
        return {}
    try:
        return dict(cfg)
    except Exception:
        return {}


class BaseAPI(FastAPI):
    """FastAPI subclass that wires ``FrameworkBase`` for deployment action servers."""

    def __init__(
        self,
        server_key: str,
        *,
        driver_classes: Optional[List[Type]] = None,
        save_root: Optional[str] = None,
        **fastapi_kwargs,
    ) -> None:
        super().__init__(**fastapi_kwargs)
        self.server_key = server_key
        world_cfg = _load_world_cfg()
        server_cfg = world_cfg.get("servers", {}).get(server_key, {})
        self.base = FrameworkBase(
            server_key=server_key,
            storage=FsStorage(
                save_root=save_root
                or server_cfg.get("root", None)
                or tempfile.mkdtemp()
            ),
            eventsink=QueueEventSink(),
            clock=NtpClock(),
            transport=FakeTransport(),  # TODO SP8: replace with real transport wiring
            world_cfg=world_cfg,
        )
        self.driver = None
        self.drivers: dict = {}
        if driver_classes:
            for cls in driver_classes:
                inst = cls(self.base)
                self.drivers[cls.__name__] = inst
            self.driver = next(iter(self.drivers.values())) if self.drivers else None

        @self.post("/get_status", tags=["private"])
        def get_status():
            driver_status = "not_implemented"
            if self.driver is not None and hasattr(self.driver, "get_status"):
                try:
                    resp = self.driver.get_status()
                    driver_status = getattr(resp, "status", "ok")
                except Exception:
                    driver_status = "error"
            return {"_driver_status": driver_status, "endpoints": {}}

        @self.post("/attach_client", tags=["private"])
        async def attach_client(
            client_servkey: str, client_host: str, client_port: int
        ):
            # TODO SP8: implement real status-subscriber wiring
            return True
