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

# ---------------------------------------------------------------------------
# Helpers shared by async tests
# ---------------------------------------------------------------------------


class FakeWss:
    """Fake WsSubscriber; returns a scripted sequence of message batches."""

    def __init__(self, batches):
        self._batches = list(batches)
        self._idx = 0

    async def read_messages(self):
        if self._idx < len(self._batches):
            result = self._batches[self._idx]
            self._idx += 1
            return result
        # block forever after scripted batches are exhausted
        await asyncio.sleep(9999)
        return []  # pragma: no cover


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


# ---------------------------------------------------------------------------
# Async tests: _mount / cleanup_session / IOloop_data semantics
# ---------------------------------------------------------------------------


def _make_sub_with_wss(cls, batches):
    """Build a subscriber subclass with a fake wss and scripted message batches."""
    fake_wss = FakeWss(batches)

    class _Sub(cls):
        USE_WSS = False  # suppress real Wss construction

        def add_points(self, datapackage_list):
            self.received = getattr(self, "received", [])
            self.received.append(datapackage_list)

    sub = _Sub(vis_serv=FakeVis({"ACT": {"host": "h", "port": 1}}), serv_key="ACT")
    sub.wss = fake_wss
    return sub


async def test_mount_adds_root_and_spacer_and_registers_destroyed():
    """_mount: layout added as root, spacer added, on_session_destroyed registered."""
    sub = _make_sub_with_wss(VisSubscriber, [])
    sentinel = object()
    sub.layout = sentinel

    sub._mount(add_spacer=True)
    try:
        # layout was added as first root
        assert sub.vis.doc.roots[0] is sentinel
        # a Spacer was appended after the layout
        from bokeh.layouts import Spacer as BokehSpacer
        assert any(isinstance(r, BokehSpacer) for r in sub.vis.doc.roots)
        # session-destroyed callback registered
        assert sub.vis.doc.session_destroyed_cb is not None
    finally:
        sub.IOtask.cancel()
        # let the event loop process the cancellation
        await asyncio.sleep(0)


async def test_cleanup_session_stops_ioloop():
    """cleanup_session: sets IOloop_data_run=False and cancels IOtask."""
    sub = _make_sub_with_wss(VisSubscriber, [])
    sub.layout = object()
    sub._mount()
    # give the task a tick to start
    await asyncio.sleep(0)

    sub.cleanup_session(None)
    # run flag must be False immediately
    assert sub.IOloop_data_run is False
    # let the cancellation propagate
    await asyncio.sleep(0)
    assert sub.IOtask.cancelled()


async def test_ioloop_data_schedules_add_points_for_nonempty():
    """IOloop_data: non-empty batch schedules add_points via next_tick_callback."""
    sub = _make_sub_with_wss(VisSubscriber, [["pkg1", "pkg2"]])
    sub.layout = object()
    # open the rate gate so the first iteration fires immediately
    sub.update_rate = 0
    sub.last_update_time = 0

    sub._mount()
    # give the IOloop task enough ticks to read the batch and schedule the callback
    for _ in range(5):
        await asyncio.sleep(0)

    sub.IOtask.cancel()
    await asyncio.sleep(0)

    assert len(sub.vis.doc.next_ticks) >= 1


async def test_ioloop_data_guard_empty_live_vs_action():
    """GUARD_EMPTY_MESSAGES: LiveVisualizer skips empty batch; ActionVisualizer fires."""
    # --- LiveVisualizer (GUARD=True): empty batch must NOT schedule add_points ---
    live_sub = _make_sub_with_wss(LiveVisualizer, [[]])  # one empty batch
    live_sub.layout = object()
    live_sub.update_rate = 0
    live_sub.last_update_time = 0

    live_sub._mount()
    for _ in range(5):
        await asyncio.sleep(0)
    live_sub.IOtask.cancel()
    await asyncio.sleep(0)

    assert len(live_sub.vis.doc.next_ticks) == 0, (
        "LiveVisualizer (GUARD=True) must not schedule add_points for empty batch"
    )

    # --- ActionVisualizer (GUARD=False): empty batch MUST schedule add_points ---
    act_sub = _make_sub_with_wss(ActionVisualizer, [[]])  # one empty batch
    act_sub.layout = object()
    act_sub.update_rate = 0
    act_sub.last_update_time = 0

    act_sub._mount()
    for _ in range(5):
        await asyncio.sleep(0)
    act_sub.IOtask.cancel()
    await asyncio.sleep(0)

    assert len(act_sub.vis.doc.next_ticks) >= 1, (
        "ActionVisualizer (GUARD=False) must schedule add_points even for empty batch"
    )
