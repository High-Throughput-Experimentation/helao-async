__all__ = ["MachineModel"]

from typing import Optional
from pydantic import BaseModel

from helao.core.helaodict import HelaoDict


class MachineModel(BaseModel, HelaoDict):
    server_name: Optional[str] = None
    machine_name: Optional[str] = None
    hostname: Optional[str] = None
    port: Optional[int] = None

    def as_key(self):
        """generates a unique machine/servername
        which can used in dicts as a key"""
        return (self.server_name, self.machine_name)

    def disp_name(self):
        return f"{self.server_name}@{self.machine_name}"
