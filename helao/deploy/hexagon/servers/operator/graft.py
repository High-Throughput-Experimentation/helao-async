"""Generic config-driven hexagon OPERATOR graft (P7e; sibling of
``helao/deploy/hexagon/servers/visualizer/graft.py``).

The per-server hexagon shim beside this one (``standalone_operator.py``)
HARDCODES a ``LEGACY_MODULE`` naming one public deployment's module. That is
fine for the public ``hte``/``test`` deployments, but a shim for a PRIVATE
nested deployment would have to name ``helao.deploy.<private>...`` in this
public parent repo — which is forbidden (private deployment repos are never
named in parent-tracked code).

This generic shim names NOTHING: the legacy module path lives ONLY in the
private deployment's own config (inside the private repo), under a top-level
per-server ``legacy_module:`` key:

    OPERATOR:
      host: 127.0.0.1
      port: 5xxx
      group: operator
      bokeh: graft                # <- resolves to THIS module, names nothing
      deployment: hexagon
      legacy_module: helao.deploy.<private>.servers.operator.<module>
      params: { ...verbatim original server params... }

``bokeh_launcher.py`` resolves ``deployment: hexagon`` + ``bokeh: graft`` to
``helao.deploy.hexagon.servers.operator.graft.makeBokehApp``, which looks up the
config's ``legacy_module`` and delegates to the same ``makeVisApp`` composition
the hardcoded shim uses.

``legacy_module`` is a top-level server key (sibling of ``bokeh:``), NOT a
``params:`` entry, so the wrapped legacy ``makeBokehApp`` sees its original
``params`` (``orch_key``, ``poll_interval``, ...) unchanged.
"""

from helao.helpers import config_loader
from helao.hexagon.app.factory import makeVisApp

__all__ = ["makeBokehApp"]


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build a hexagon-hosted Bokeh operator document for ``server_key``.

    Reads the legacy target from
    ``CONFIG['servers'][server_key]['legacy_module']`` (fail loud with a clear
    message if absent — a ``bokeh: graft`` server MUST declare it) and delegates
    to the shared ``makeVisApp`` composition.

    ``config_loader.CONFIG`` is read through the MODULE, not bound at import
    time: Bokeh imports this shim once per process but calls ``makeBokehApp``
    once per browser session, and a module-level ``from ... import CONFIG``
    would freeze whatever value happened to be installed at import time.
    """
    if config_loader.CONFIG is None:
        raise RuntimeError(
            "config_loader.CONFIG is not installed; graft.makeBokehApp must "
            "run after the launcher has loaded the config"
        )
    scfg = config_loader.CONFIG["servers"][server_key]
    legacy_module = scfg.get("legacy_module")
    if not legacy_module:
        raise KeyError(
            f"server '{server_key}' uses `bokeh: graft` but declares no "
            "`legacy_module:` key. Add a top-level `legacy_module: "
            "helao.deploy.<deployment>.servers.operator.<module>` to its "
            "config block so the generic hexagon graft knows which legacy "
            "makeBokehApp to wrap."
        )
    return makeVisApp(legacy_module, doc, confPrefix, server_key, helao_repo_root)
