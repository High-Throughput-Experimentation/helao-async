"""Panels and visualizers resolve from instrument bokeh/ and reflex/ subfolders."""

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


def test_search_order_has_no_hardcoded_second_entry(monkeypatch):
    monkeypatch.setattr(config_loader, "CONFIG", {"deployment": "test"})
    order = discovery.deployment_search_order()
    assert order[0] == "test"
    assert order[1:] == sorted(order[1:])


def test_search_order_is_configured_then_sorted_rest(tmp_path, monkeypatch):
    for name in ("aaa", "hte", "zzz"):
        (tmp_path / name / "servers").mkdir(parents=True)
    monkeypatch.setattr(discovery, "_deploy_root", lambda: str(tmp_path))
    monkeypatch.setattr(config_loader, "CONFIG", {"deployment": "zzz"})
    assert discovery.deployment_search_order() == ["zzz", "aaa", "hte"]


def test_unknown_panel_still_raises_module_not_found():
    with pytest.raises(ModuleNotFoundError, match="no_such_panel"):
        discovery.resolve_panel_module("no_such_panel")


def test_unknown_visualizer_still_raises_module_not_found():
    with pytest.raises(ModuleNotFoundError, match="no_such_vis"):
        vis_subscriber.import_vis_class("no_such_vis")
