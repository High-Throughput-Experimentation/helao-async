"""Generic config-driven hexagon VISUALIZER graft (P7e; the bokeh twin of
``helao/deploy/hexagon/servers/action/graft.py``).

The per-server hexagon shims beside this one (``live_visualizer.py``,
``action_visualizer.py``) each HARDCODE a ``LEGACY_MODULE`` naming one public
deployment's module. That is fine for the public
``hte``/``test`` deployments, but a shim for a PRIVATE nested deployment would
have to name ``helao.deploy.<private>...`` in this public parent repo — which
is forbidden (private deployment repos are never named in parent-tracked code).

This generic shim removes that coupling: it names NOTHING. The legacy module
path lives ONLY in the private deployment's own config (inside the private
repo), under a top-level per-server ``legacy_module:`` key. A private hexagon
visualizer entry therefore reads:

    SOMEVIS:
      host: 127.0.0.1
      port: 5xxx
      group: visualizer
      bokeh: graft                # <- resolves to THIS module, names nothing
      deployment: hexagon
      legacy_module: helao.deploy.<private>.servers.visualizer.<module>
      params: { ...verbatim original server params... }

``bokeh_launcher.py`` resolves ``deployment: hexagon`` + ``bokeh: graft`` to
``helao.deploy.hexagon.servers.visualizer.graft.makeBokehApp``, which looks up
the config's ``legacy_module`` and delegates to the same ``makeVisApp``
composition every hardcoded shim uses — identical hosting (fail-loud
``VIS_REQUIRED`` wiring, ``ui_host`` port, unmodified legacy rendering), just
with the legacy target sourced from config instead of a hardcoded string.
Public deployments may use this too, but keep using their explicit per-server
shims for readability.

Naming the target explicitly also CLOSES a sleeper: without it, a deployment
that has no ``servers/visualizer/`` package of its own resolves its Bokeh host
through ``bokeh_launcher``'s auto-detect and its panels through
``vis_subscriber.import_vis_class``'s deployment search order — i.e. the module
it actually runs is decided by fallback order rather than by the config. A
``legacy_module:`` names it.

``legacy_module`` is a top-level server key (sibling of ``bokeh:``), NOT a
``params:`` entry, so the wrapped legacy ``makeBokehApp`` sees its original
``params`` unchanged.
"""

from helao.helpers import config_loader
from helao.hexagon.app.factory import makeVisApp

__all__ = ["makeBokehApp"]


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build a hexagon-hosted Bokeh visualizer document for ``server_key``.

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
            "helao.deploy.<deployment>.servers.visualizer.<module>` to its "
            "config block so the generic hexagon graft knows which legacy "
            "makeBokehApp to wrap."
        )
    return makeVisApp(legacy_module, doc, confPrefix, server_key, helao_repo_root)
