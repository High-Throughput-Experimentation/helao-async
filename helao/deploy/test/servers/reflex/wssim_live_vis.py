"""``wssim_panel`` under the name the Bokeh visualizer answers to.

Panel discovery resolves a ``live_vis`` value to a module of exactly that name
(:func:`helao.core.servers.reflex.discovery.resolve_panel_module` does no
suffix rewriting), and the Bokeh stack resolves the same key to
``servers/visualizer/wssim_live_vis.py``. A config that names ``wssim_panel``
therefore has no Bokeh panel, and one that names ``wssim_live_vis`` -- as
``test.yml`` does, because its Bokeh live visualizer predates the Reflex stack
-- had no Reflex panel. This module closes that gap the way the hte panels
already do: one name, two subpackages.

It re-exports rather than re-implements, so there is nothing here to drift from
``wssim_panel``.
"""

from helao.deploy.test.servers.reflex.wssim_panel import (
    STATE_BASE,
    WS_PATH,
    build,
    extract,
    panel_id,
)

__all__ = ["WS_PATH", "STATE_BASE", "build", "extract", "panel_id"]
