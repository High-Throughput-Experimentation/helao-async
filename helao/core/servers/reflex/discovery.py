"""Deployment module resolution shared by the Bokeh and Reflex UI stacks.

``vis_subscriber`` originally owned the deployment search order. It lives here
now so both stacks resolve deployment modules identically and cannot drift;
``vis_subscriber`` imports it back under its original private name.
"""

__all__ = [
    "deployment_search_order",
    "resolve_panel_module",
    "reserved_addresses",
    "PANEL_SUBPACKAGE",
]

import os
from functools import lru_cache
from importlib import import_module
from importlib import util as importlib_util

import helao
from helao.helpers import config_loader

#: Subpackage under ``helao/deploy/<deployment>/servers/`` holding Reflex panels.
PANEL_SUBPACKAGE = "reflex"


def _deploy_root() -> str:
    """Absolute path of ``helao/deploy``.

    Derived from the package location rather than by counting ``dirname`` calls
    up from this file. The counted form was correct in ``vis_subscriber`` and
    silently wrong here -- this module sits one directory deeper, so it resolved
    to ``helao/core/deploy``, which does not exist. The fallback scan then found
    no deployments at all and only the configured one (or ``hte``) was ever
    searched.
    """
    return os.path.join(os.path.dirname(os.path.abspath(helao.__file__)), "deploy")


def deployment_search_order() -> list:
    """Return the deployment names to search when resolving a UI module.

    The configured deployment (``CONFIG["deployment"]``) is tried first so a
    deployment can override a shared module, then ``hte`` as the canonical home
    of the generic visualizers, then any remaining deployment that ships a
    ``servers/visualizer`` package (sorted for determinism).

    Returns:
        list: Ordered, de-duplicated deployment directory names.
    """
    order = []
    cfg = config_loader.CONFIG or {}
    current = cfg.get("deployment")
    if current:
        order.append(current)
    if "hte" not in order:
        order.append("hte")
    deploy_root = _deploy_root()
    if os.path.isdir(deploy_root):
        for name in sorted(os.listdir(deploy_root)):
            if name in order:
                continue
            if os.path.isdir(os.path.join(deploy_root, name, "servers", "visualizer")):
                order.append(name)
    return order


@lru_cache(maxsize=None)
def resolve_panel_module(module_name: str):
    """Import a Reflex panel module by short name, searching deployments.

    Args:
        module_name: Short module name from a server's ``live_vis`` /
            ``action_vis`` config key (e.g. ``"wssim_panel"``).

    Returns:
        The imported module.

    Raises:
        ModuleNotFoundError: If no deployment provides ``module_name``.
    """
    tried = []
    for deployment in deployment_search_order():
        modpath = f"helao.deploy.{deployment}.servers.{PANEL_SUBPACKAGE}.{module_name}"
        tried.append(modpath)
        try:
            spec = importlib_util.find_spec(modpath)
        except ModuleNotFoundError:
            spec = None
        if spec is None:
            continue
        return import_module(modpath)
    raise ModuleNotFoundError(
        f"could not locate Reflex panel module '{module_name}' in any "
        f"deployment; tried: {tried}"
    )


def reserved_addresses(server_cfg: dict) -> list:
    """Return every ``host:port`` a server entry occupies.

    A Reflex server occupies two consecutive ports (static frontend, then
    backend), so uniqueness checks must account for both.

    Args:
        server_cfg: One entry of the config's ``servers:`` mapping.

    Returns:
        list: ``"host:port"`` strings claimed by this server.
    """
    host = server_cfg.get("host")
    port = server_cfg.get("port")
    if host is None or port is None:
        return []
    addrs = [f"{host}:{port}"]
    if server_cfg.get("reflex"):
        addrs.append(f"{host}:{int(port) + 1}")
    return addrs
