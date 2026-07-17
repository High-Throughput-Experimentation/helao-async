"""Hardware port (spec §4.3.1): the HelaoDriver seam, promoted to an interface.

Contract (normative, from helao/core/drivers/helao_driver.py + core-03):
- Construction from ``config: dict`` (the server YAML ``params:`` block) with
  NO I/O in ``__init__`` — the port bans constructor-connect. Adapters that
  wrap legacy constructor-connecting drivers defer real connection to
  ``connect()``.
- Disconnected construct is first-class: every adapter must be constructible
  (and schema-introspectable) without hardware or vendor runtime present.
- ``DriverResponse`` two-axis result kept verbatim (``response`` = did this
  call work; ``status`` = driver state), including ``DriverStatus.retry`` and
  the empty-``DriverResponse()`` = "skip this sample" poller sentinel.
- Lifecycle is async-first; adapters wrap legacy sync drivers with explicit
  thread offload where needed.
"""

from typing import AsyncContextManager, Protocol, runtime_checkable

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
)
from helao.hexagon.domain.models import ErrorCodes

__all__ = [
    "ExclusiveAccess",
    "HardwarePort",
    "driver_response_to_error_code",
]


def driver_response_to_error_code(resp: DriverResponse) -> ErrorCodes:
    """The single DriverResponse -> ErrorCodes mapping (spec §4.3.1).

    Legacy duplicates this string-compare in every executor phase
    (``resp.response == "success"``); adapters and executors must use this
    function instead.
    """
    if resp.response == DriverResponseType.success:
        return ErrorCodes.none
    if resp.status == DriverStatus.busy:
        return ErrorCodes.in_progress
    return ErrorCodes.critical_error


@runtime_checkable
class ExclusiveAccess(Protocol):
    """Async context manager serializing poller-vs-command bus contention.

    Replaces the ad-hoc ``polling``-flag handshakes (AliCat, legato
    ``_send_sync`` fork, Advantech pause/resume) and the disabled Gamry poller.
    """

    def exclusive(self) -> AsyncContextManager[None]: ...


@runtime_checkable
class HardwarePort(Protocol):
    """Async driver lifecycle: connect/arm/start/drain/abort/cleanup/disconnect."""

    async def connect(self) -> DriverResponse: ...

    async def get_status(self) -> DriverResponse: ...

    async def arm(self, **setup_params) -> DriverResponse:
        """Legacy convention ``setup(...)`` — arm a measurement."""
        ...

    async def start(self, **measure_params) -> DriverResponse:
        """Legacy convention ``measure()`` / ``start_channel()``."""
        ...

    async def drain(self, **kwargs) -> DriverResponse:
        """Legacy convention ``get_data(...)`` — incremental column-dict delta."""
        ...

    async def abort(self, **kwargs) -> DriverResponse:
        """Legacy ABC ``stop()`` — abort ALL activity."""
        ...

    async def cleanup(self, **kwargs) -> DriverResponse:
        """De-arm without disconnecting."""
        ...

    async def reset(self) -> DriverResponse: ...

    async def disconnect(self) -> DriverResponse: ...

    async def estop(self, switch: bool) -> DriverResponse: ...

    async def shutdown(self) -> DriverResponse: ...
