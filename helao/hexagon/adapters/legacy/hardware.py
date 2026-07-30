"""HardwarePort adapter (spec §4.3.1): HelaoDriver passthrough.

Wraps any legacy HelaoDriver with explicit thread offload (the ABC's sync
methods must never block the event loop). Lifecycle mapping uses the legacy
naming conventions (arm->setup, start->measure, drain->get_data,
abort->stop); a driver lacking a mapped method raises AttributeError at call
time — fail loud, never a silent no-op. Per-driver mapping refinement is P3
work; the disconnected-construct rule (no I/O in __init__) is the driver's
own contract, inherited unchanged."""

import asyncio
from typing import Any
from collections.abc import Callable

from helao.core.drivers.helao_driver import DriverResponse, HelaoDriver

__all__ = ["LegacyDriverHardwareAdapter"]

_METHOD_MAP = {
    "arm": ("setup",),
    "start": ("measure", "start_channel", "start"),
    "drain": ("get_data",),
    "abort": ("stop",),
    "cleanup": ("cleanup",),
    "estop": ("estop",),
    "shutdown": ("shutdown",),
}


class LegacyDriverHardwareAdapter:
    def __init__(self, driver: HelaoDriver):
        self._driver = driver

    def _resolve(self, port_name: str) -> Callable[..., Any]:
        for legacy_name in _METHOD_MAP[port_name]:
            fn = getattr(self._driver, legacy_name, None)
            if callable(fn):
                return fn
        raise AttributeError(
            f"{type(self._driver).__name__} has no legacy method for "
            f"'{port_name}' (tried {_METHOD_MAP[port_name]})"
        )

    async def connect(self) -> DriverResponse:
        return await asyncio.to_thread(self._driver.connect)

    async def get_status(self) -> DriverResponse:
        return await asyncio.to_thread(self._driver.get_status)

    async def arm(self, **setup_params) -> DriverResponse:
        return await asyncio.to_thread(self._resolve("arm"), **setup_params)

    async def start(self, **measure_params) -> DriverResponse:
        return await asyncio.to_thread(self._resolve("start"), **measure_params)

    async def drain(self, **kwargs) -> DriverResponse:
        return await asyncio.to_thread(self._resolve("drain"), **kwargs)

    async def abort(self, **kwargs) -> DriverResponse:
        return await asyncio.to_thread(self._resolve("abort"), **kwargs)

    async def cleanup(self, **kwargs) -> DriverResponse:
        return await asyncio.to_thread(self._resolve("cleanup"), **kwargs)

    async def reset(self) -> DriverResponse:
        return await asyncio.to_thread(self._driver.reset)

    async def disconnect(self) -> DriverResponse:
        return await asyncio.to_thread(self._driver.disconnect)

    async def estop(self, switch: bool) -> DriverResponse:
        return await asyncio.to_thread(self._resolve("estop"), switch)

    async def shutdown(self) -> DriverResponse:
        return await asyncio.to_thread(self._resolve("shutdown"))
