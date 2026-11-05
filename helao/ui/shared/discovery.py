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
from pathlib import Path

import helao
from helao.helpers import config_loader, server_modules

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
    """Configured deployment first, then every other deployment, sorted."""
    current = (config_loader.CONFIG or {}).get("deployment")
    others = [
        d for d in server_modules.deployments(Path(_deploy_root())) if d != current
    ]
    return ([current] if current else []) + others


def _resolve(module_name: str, stack: str):
    root = Path(_deploy_root())
    own = (config_loader.CONFIG or {}).get("deployment")
    deployment, found = server_modules.locate(
        module_name, stack, own=own, deploy_root=root
    )
    if deployment is None:
        where = f"several deployments {found}" if found else "no deployment"
        raise ModuleNotFoundError(
            f"could not locate {stack} module '{module_name}': found in {where}; "
            f"the config's own deployment is {own!r}"
        )
    path = server_modules.module_file(deployment, module_name, stack, root)
    assert path is not None  # locate() only returns deployments that have it
    return import_module(server_modules.import_path(path, root))


@lru_cache(maxsize=None)
def resolve_panel_module(module_name: str):
    """Import the Reflex panel module ``module_name`` (see ``server_modules``)."""
    return _resolve(module_name, "reflex")


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
