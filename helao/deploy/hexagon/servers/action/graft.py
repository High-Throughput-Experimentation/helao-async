"""Generic config-driven hexagon action-server graft (P3-private, decision A).

The per-server hexagon shims in this package (gamry_server2.py, spec_server.py,
...) each HARDCODE their `LEGACY_MODULE = "helao.deploy.<dep>.servers.action.
<mod>"`. That is fine for the public `hte`/`test` deployments, but a shim for a
PRIVATE nested deployment would have to name `helao.deploy.<private>...` in this
public parent repo — which is forbidden (private deployment repos are never
named in parent-tracked code).

This generic shim removes that coupling: it names NOTHING. The private module
path lives ONLY in the private deployment's own config (inside the private
repo), under a top-level per-server `legacy_module:` key. A private hexagon
canary config therefore reads:

    SOMEKEY:
      host: 127.0.0.1
      port: 8xxx
      group: action
      fast: graft                 # <- resolves to THIS module, names nothing
      deployment: hexagon
      legacy_module: helao.deploy.<private>.servers.action.<module>   # private
      params: { ...verbatim original server params... }

The launcher resolves `deployment: hexagon` + `fast: graft` to
`helao.deploy.hexagon.servers.action.graft.makeApp`, which looks up the config's
`legacy_module` and delegates to the same `makeActionApp(server_key,
legacy_module)` factory every hardcoded shim uses — identical graft (fail-loud
wiring, co-located RPC, native write/WS graft), just with the legacy target
sourced from config instead of a hardcoded string. Public deployments may use
this too, but keep using their explicit per-server shims for readability.

`legacy_module` is a top-level server key (sibling of `fast:`), NOT a `params:`
entry, so the wrapped legacy `makeApp` sees its original `params` unchanged.
"""

from helao.helpers.config_loader import CONFIG
from helao.hexagon.app.factory import makeActionApp

__all__ = ["makeApp"]


def makeApp(server_key):
    """Build a hexagon-grafted action app for ``server_key``.

    Reads the legacy target from ``CONFIG['servers'][server_key]['legacy_module']``
    (fail loud with a clear message if absent — a `fast: graft` server MUST
    declare it) and delegates to the shared ``makeActionApp`` factory.
    """
    if CONFIG is None:
        raise RuntimeError(
            "config_loader.CONFIG is not installed; graft.makeApp must run "
            "after the launcher has loaded the config"
        )
    scfg = CONFIG["servers"][server_key]
    legacy_module = scfg.get("legacy_module")
    if not legacy_module:
        raise KeyError(
            f"server '{server_key}' uses `fast: graft` but declares no "
            "`legacy_module:` key. Add a top-level `legacy_module: "
            "helao.deploy.<deployment>.servers.action.<module>` to its config "
            "block so the generic hexagon graft knows which legacy makeApp to "
            "wrap."
        )
    return makeActionApp(server_key, legacy_module)
