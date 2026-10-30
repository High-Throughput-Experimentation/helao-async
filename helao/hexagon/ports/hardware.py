"""Hardware-side port: what a driver, poller or executor may read from its host.

The hardware contract itself is the ``HelaoDriver`` ABC
(``helao/core/drivers/helao_driver.py``) plus its ``connect_on_startup`` flag;
there is no driver-lifecycle port. ``ActionHost`` satisfies ``DriverHostPort``
structurally and there is no adapter. ``test_driver_host_surface.py`` gates
hardware-side classes to these members.

Data members are read-only properties, which are covariant: a plain
``poller: Optional[DriverPoller]`` attribute is invariant and would reject the
host's own attribute. Each member's thread class is in a trailing comment.
"""

from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from helao.core.drivers.helao_driver import DriverPoller

__all__ = ["DriverHostPort"]


@runtime_checkable
class DriverHostPort(Protocol):
    def get_lbuf(self, live_key: str) -> tuple:  # thread-safe (dict read)
        ...

    async def put_lbuf(self, live_dict: dict) -> None:  # loop
        ...

    def dflt_file_conn_key(self) -> Any:  # loop
        ...

    # HelaoDirs / ActionServerModel live under helao.core.models, which a port
    # may not import (test_boundaries), so they are typed Any.
    @property
    def helaodirs(self) -> Any:  # read-only
        ...

    @property
    def actionservermodel(self) -> Any:  # thread-safe (bool read of .estop)
        ...

    @property
    def executors(self) -> dict:  # loop
        ...

    @property
    def server_params(self) -> dict:  # read-only
        ...

    @property
    def world_cfg(self) -> dict:  # read-only
        ...

    @property
    def poller(self) -> "Optional[DriverPoller]":  # read-only
        ...

    @property
    def server_key(self) -> str:  # read-only
        ...
