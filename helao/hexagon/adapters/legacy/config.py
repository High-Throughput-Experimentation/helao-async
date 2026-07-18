"""ConfigPort adapter (spec §9.2): raw-dict identity, wrap-not-modify.

Hands out views of the SAME dict object install_global_config published.
Never validates into a copy: pydantic HelaoConfig drops launcher-added keys
(loaded_config_path, deployment, ...) and breaks --restore's same-object
aliasing CONFIG["servers"][key] is server.server_cfg.
"""

__all__ = ["LegacyConfigAdapter", "from_global_config"]


class LegacyConfigAdapter:
    def __init__(self, world_cfg: dict):
        if not isinstance(world_cfg, dict):
            raise TypeError("world_cfg must be the raw config dict")
        self._cfg = world_cfg

    def world_cfg(self) -> dict:
        return self._cfg

    def server_cfg(self, server_key: str) -> dict:
        return self._cfg["servers"][server_key]

    def server_params(self, server_key: str) -> dict:
        return self.server_cfg(server_key).get("params", {}) or {}

    def root(self) -> str:
        return self._cfg["root"]  # KeyError when undefined, like helao_dirs


def from_global_config() -> LegacyConfigAdapter:
    """Adapter over the launcher-installed module-global CONFIG (fail loud)."""
    from helao.helpers import config_loader

    if config_loader.CONFIG is None:
        raise RuntimeError(
            "config_loader.CONFIG is not installed; launch via fast_launcher/"
            "bokeh_launcher (or install_global_config) before composing"
        )
    return LegacyConfigAdapter(config_loader.CONFIG)
