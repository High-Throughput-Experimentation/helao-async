"""hte's panel twin resolution per stack (moved from the parent's test_panel_discovery_stacks.py)."""

import pytest

from helao.helpers import config_loader
from helao.ui.bokeh import vis_subscriber
from helao.ui.shared import discovery


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    discovery.resolve_panel_module.cache_clear()
    vis_subscriber.import_vis_class.cache_clear()
    monkeypatch.setattr(config_loader, "CONFIG", {"deployment": "hte"})
    yield
    discovery.resolve_panel_module.cache_clear()
    vis_subscriber.import_vis_class.cache_clear()


def test_existing_hte_twin_resolves_per_stack():
    panel = discovery.resolve_panel_module("gamry_vis")
    assert ".reflex." in panel.__name__
    cls = vis_subscriber.import_vis_class("gamry_vis")
    assert ".reflex." not in cls.__module__
