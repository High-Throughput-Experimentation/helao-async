"""Unit tests for the framework Bokeh ws-subscriber adapter."""
import asyncio

import pytest

from helao.framework.adapters import vis_subscriber as vsmod
from helao.framework.adapters.vis_subscriber import (
    VisSubscriber,
    LiveVisualizer,
    ActionVisualizer,
    import_vis_class,
    mount_visualizers,
)


class FakeDoc:
    def __init__(self):
        self.roots = []
        self.session_destroyed_cb = None
        self.next_ticks = []

    def add_root(self, root):
        self.roots.append(root)

    def add_next_tick_callback(self, cb):
        self.next_ticks.append(cb)

    def on_session_destroyed(self, cb):
        self.session_destroyed_cb = cb


class FakeVis:
    """Stand-in for app.vis.Vis."""

    def __init__(self, servers):
        self.doc = FakeDoc()
        self.server_cfg = {"params": {}}
        self.world_cfg = {"servers": servers}


def make_sub(cls, serv_key, servers):
    """Build a subscriber with USE_WSS off (no real ws)."""

    class _Sub(cls):
        USE_WSS = False

        def add_points(self, datapackage_list):
            self.received = getattr(self, "received", [])
            self.received.append(datapackage_list)

    return _Sub(vis_serv=FakeVis(servers), serv_key=serv_key)


def test_connected_when_server_present():
    sub = make_sub(VisSubscriber, "ACT", {"ACT": {"host": "h", "port": 1}})
    assert sub.connected is True
    assert sub.host == "h" and sub.port == 1


def test_not_connected_when_absent():
    sub = make_sub(VisSubscriber, "MISSING", {"ACT": {"host": "h", "port": 1}})
    assert sub.connected is False


def test_max_points_clamps():
    sub = make_sub(VisSubscriber, "ACT", {"ACT": {"host": "h", "port": 1}})

    class Sender:
        value = ""

    sub.callback_input_max_points("value", "500", "999999", Sender())
    assert sub.max_points == 10000
    sub.callback_input_max_points("value", "500", "0", Sender())
    assert sub.max_points == 2
    sub.callback_input_max_points("value", "500", "garbage", Sender())
    assert sub.max_points == 500


def test_update_rate_parses_and_falls_back():
    sub = make_sub(VisSubscriber, "ACT", {"ACT": {"host": "h", "port": 1}})

    class Sender:
        value = ""

    sub.callback_input_update_rate("value", "0.5", "2.5", Sender())
    assert sub.update_rate == 2.5
    sub.callback_input_update_rate("value", "0.5", "bad", Sender())
    assert sub.update_rate == 0.5


def test_class_specializations():
    assert LiveVisualizer.WS_PATH == "ws_live"
    assert LiveVisualizer.GUARD_EMPTY_MESSAGES is True
    assert ActionVisualizer.WS_PATH == "ws_data"
    assert ActionVisualizer.DEFAULT_UPDATE_RATE == 1e-3


def test_import_vis_class_missing_raises():
    with pytest.raises(ModuleNotFoundError):
        import_vis_class("definitely_not_a_real_vis_module_xyz")


def test_mount_visualizers_honors_limit_vis(monkeypatch):
    calls = []

    class FakeC:
        def __init__(self, vis_serv, serv_key):
            calls.append(serv_key)

    monkeypatch.setattr(vsmod, "import_vis_class", lambda name: FakeC)

    class App:
        server_params = {"limit_vis": ["A"]}
        vis = FakeVis(
            {
                "A": {"action_vis": "x_vis"},
                "B": {"action_vis": "x_vis"},
            }
        )

    mounted = mount_visualizers(App(), "action_vis")
    assert calls == ["A"]
    assert len(mounted) == 1
