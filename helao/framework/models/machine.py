"""Pydantic model identifying a HELAO server by name, machine, and network address."""

__all__ = ["MachineModel"]

from typing import Optional, Tuple
from pydantic import BaseModel

from helao.framework.models.helao_dict import HelaoDict


class MachineModel(BaseModel, HelaoDict):
    """Network identity of a HELAO server.

    Attributes:
        server_name (Optional[str]): Logical server key from the config.
        machine_name (Optional[str]): Host machine name.
        hostname (Optional[str]): Network hostname or IP.
        port (Optional[int]): TCP port.
    """

    server_name: Optional[str] = None
    machine_name: Optional[str] = None
    hostname: Optional[str] = None
    port: Optional[int] = None

    def as_key(self) -> Tuple[Optional[str], Optional[str]]:
        """Return a `(server_name, machine_name)` tuple suitable as a dict key."""
        return (self.server_name, self.machine_name)

    def disp_name(self) -> str:
        """Return a ``server@machine`` display string."""
        return f"{self.server_name}@{self.machine_name}"
