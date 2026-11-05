"""Shared serial-connection lifecycle for single-port HTE drivers.

``get_status``/``stop``/``reset``/``disconnect`` were byte-identical in the
KDS100, SIMDOS and SprintIR drivers. A driver mixing this in (listed *before*
``HelaoDriver``) supplies ``connect`` and holds its open port in ``self.com``.
"""

from typing import Callable

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
)
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class SerialLifecycleMixin:
    """``get_status``/``stop``/``reset``/``disconnect`` over ``self.com``."""

    com = None
    connect: Callable[[], DriverResponse]  # annotation only; the driver defines it

    def get_status(self) -> DriverResponse:
        """``status=ok`` if the serial connection is open, else ``uninitialized``."""
        if self.com is not None:
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.uninitialized
        )

    def stop(self) -> DriverResponse:
        """No active operation to abort; reports current status."""
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    def reset(self) -> DriverResponse:
        """Force-close and reopen the serial connection."""
        self.disconnect()
        return self.connect()

    def disconnect(self) -> DriverResponse:
        """Close the underlying serial port."""
        try:
            if self.com is not None:
                self.com.close()
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("disconnect failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        finally:
            self.com = None
        return response
