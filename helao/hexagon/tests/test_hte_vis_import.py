"""P3d — hte visualizer import sweep.

The two visualizer hosts (`action_visualizer`, `live_visualizer`) are launched
Bokeh apps and already have hexagon shims under
`helao/deploy/hexagon/servers/visualizer/` (created in P2d, pointing at the hte
legacy modules). The 12 per-instrument `*_vis` modules are NOT separately
launched — the hosts mount them in-process via `vis_subscriber`, selected by the
`action_vis:`/`live_vis:` config keys — so their entire Linux-verifiable surface
is that they import without hardware/vendor runtime. `data_browser` is a thin
shim over the core builder.

This sweep guards all 15 hte visualizer modules against a regression that makes
one un-importable (e.g. a driver reverting to a module-top vendor import that a
vis module transitively pulls).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

VIS_DIR = Path("helao/deploy/hte/servers/visualizer")
PKG = "helao.deploy.hte.servers.visualizer"

VIS_MODULES = [
    f"{PKG}.{f.stem}" for f in sorted(VIS_DIR.glob("*.py")) if f.name != "__init__.py"
]

HEXAGON_VIS_HOSTS = [
    "helao.deploy.hexagon.servers.visualizer.action_visualizer",
    "helao.deploy.hexagon.servers.visualizer.live_visualizer",
]


def test_vis_module_set_nonempty():
    # 2 hosts + data_browser + 12 per-instrument *_vis = 15 (spec §8.1: 13
    # config-selectable mount artifacts + the hosts).
    assert len(VIS_MODULES) == 15, VIS_MODULES


@pytest.mark.parametrize("mod", VIS_MODULES)
def test_hte_vis_imports_on_linux(mod):
    """Every hte visualizer module imports without hardware/vendor runtime."""
    importlib.import_module(mod)


@pytest.mark.parametrize("mod", HEXAGON_VIS_HOSTS)
def test_hexagon_vis_host_shim(mod):
    """The P2d hexagon vis-host shims import and expose makeBokehApp pointing
    at the hte legacy visualizer host."""
    m = importlib.import_module(mod)
    assert callable(m.makeBokehApp)
    assert m.LEGACY_MODULE.startswith("helao.deploy.hte.servers.visualizer.")
