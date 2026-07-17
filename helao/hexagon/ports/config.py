"""Config port (spec §4.3.9, §9.2): raw-dict identity.

The raw config dict is the runtime source of truth. Object identity of
CONFIG["servers"][key] with each server's server_cfg MUST be preserved (the
--restore in-place mutation gate rides on it) -- see
helao/helpers/config_loader.py's install_global_config, which installs the
dict returned by read_config() AS-IS for exactly this reason. Typed views are
read-only and derived; they are never installed as the runtime dict.
"""

from typing import Protocol, runtime_checkable

__all__ = ["ConfigPort"]


@runtime_checkable
class ConfigPort(Protocol):
    def world_cfg(self) -> dict:
        """THE raw config dict (same object every call)."""
        ...

    def server_cfg(self, server_key: str) -> dict:
        """Identity-preserving view: world_cfg()['servers'][server_key]."""
        ...

    def server_params(self, server_key: str) -> dict:
        """The server's params: block (empty dict when absent)."""
        ...

    def root(self) -> str:
        """The config root: path (raises if undefined, like helao_dirs)."""
        ...
