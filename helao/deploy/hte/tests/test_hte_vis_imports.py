"""Every hte instrument Bokeh panel (servers/*/bokeh/*.py) imports on Linux.

The base visualizers have the same check in helao/deploy/base/tests/test_vis_gate_config.py.
"""

import importlib
from pathlib import Path

import pytest

from helao.helpers.server_modules import import_path

SERVERS = Path(__file__).resolve().parents[1] / "servers"
MODULES = sorted(p for p in SERVERS.glob("*/bokeh/*.py") if p.name != "__init__.py")


def test_the_sweep_is_not_vacuous():
    assert len(MODULES) >= 10, MODULES


@pytest.mark.parametrize("path", MODULES, ids=[p.stem for p in MODULES])
def test_hte_bokeh_panel_imports_on_linux(path):
    importlib.import_module(import_path(path))
