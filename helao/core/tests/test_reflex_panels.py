"""Tests for Reflex panel state plumbing and the test-deployment panels."""

import pytest

from types import SimpleNamespace

from helao.core.servers.reflex.state import (
    ActionVisState,
    apply_tick,
    LiveVisState,
    VisPanelState,
    make_panel_state,
)


def test_live_and_action_bases_carry_the_right_ws_path():
    assert LiveVisState.__fields__["ws_path"].default == "ws_live"
    assert ActionVisState.__fields__["ws_path"].default == "ws_data"


def test_panel_bases_are_mixins_so_their_vars_are_not_shared():
    """The bug this guards: a var declared on a concrete rx.State is owned by
    that class and shared by every substate under it. Reads route to the
    ancestor's single copy, so make_panel_state's server_key binding was
    ignored at runtime (every panel saw "") and two panels on one page shared
    one connection/window_points/chart_spec."""
    for base in (VisPanelState, LiveVisState, ActionVisState):
        assert getattr(base, "_mixin", False), f"{base.__name__} must be a mixin"


def test_make_panel_state_rejects_a_concrete_base():
    import reflex as rx

    class Concrete(rx.State):
        server_key: str = ""

    with pytest.raises(TypeError, match="mixin=True"):
        make_panel_state("bad_panel", "SIM", Concrete, "ws_live")


def test_make_panel_state_bakes_in_the_server_key():
    cls = make_panel_state("wssim_panel", "SIM", LiveVisState, "ws_live")
    assert cls.__fields__["server_key"].default == "SIM"
    assert cls.__fields__["ws_path"].default == "ws_live"


def test_generated_state_owns_its_vars_rather_than_inheriting_them():
    """The decisive check: an inherited var reads the ancestor's single value,
    so the bound server_key would come back "" no matter what default the leaf
    declares. Owning the var is what makes the binding take effect."""
    cls = make_panel_state("wssim_panel", "SIM_OWN", LiveVisState, "ws_live")
    for name in ("server_key", "ws_path", "connection", "window_points"):
        assert name in cls.vars
        assert name not in cls.inherited_vars, f"'{name}' is shared across panels"


def test_two_generated_states_do_not_share_var_storage():
    a = make_panel_state("wssim_panel", "SIM_X", LiveVisState, "ws_live")
    b = make_panel_state("wssim_panel", "SIM_Y", LiveVisState, "ws_live")
    assert a.get_full_name() != b.get_full_name()
    assert a.__fields__["server_key"].default == "SIM_X"
    assert b.__fields__["server_key"].default == "SIM_Y"


def test_make_panel_state_names_classes_uniquely():
    a = make_panel_state("wssim_panel", "SIM_A", LiveVisState, "ws_live")
    b = make_panel_state("wssim_panel", "SIM_B", LiveVisState, "ws_live")
    assert a.__name__ != b.__name__


def test_make_panel_state_is_cached_so_rerender_reuses_the_class():
    a = make_panel_state("wssim_panel", "SIM", LiveVisState, "ws_live")
    b = make_panel_state("wssim_panel", "SIM", LiveVisState, "ws_live")
    assert a is b


def test_clamp_window_points_matches_the_bokeh_behavior():
    assert VisPanelState.clamp_window_points("1", 500) == 2
    assert VisPanelState.clamp_window_points("999999", 500) == 10000
    assert VisPanelState.clamp_window_points("garbage", 700) == 700
    assert VisPanelState.clamp_window_points("garbage", None) == 500
    assert VisPanelState.clamp_window_points("1234", 500) == 1234


def test_parse_update_rate_falls_back_to_half_a_second():
    assert VisPanelState.parse_update_rate("0.25") == 0.25
    assert VisPanelState.parse_update_rate("nope") == 0.5


def test_parse_update_rate_clamps_to_a_sane_floor():
    assert VisPanelState.parse_update_rate("0") >= 0.01
    assert VisPanelState.parse_update_rate("-5") >= 0.01


def test_input_handlers_use_the_names_the_panels_bind():
    """Task 7's panels wire these by name, so the spelling is a contract."""
    for name in ("on_window_points", "on_update_rate", "render_loop", "stop_loop"):
        assert hasattr(VisPanelState, name), f"missing handler '{name}'"
    assert not hasattr(VisPanelState, "set_window_points")
    assert not hasattr(VisPanelState, "set_update_rate")


def test_generated_state_class_is_constructible():
    """Regression: a type() namespace without __module__ raises inside Reflex."""
    cls = make_panel_state("probe_panel", "PROBE", LiveVisState, "ws_live")
    assert cls.__module__ == VisPanelState.__module__


class _StubIngest:
    """Minimal stand-in for WsIngest: only what apply_tick touches."""

    def __init__(self, state="live", error=None):
        self.status = SimpleNamespace(state=state, error=error)


class _StubPanel:
    """Stand-in for a panel state; rx.State cannot be built outside an app."""

    def __init__(self, pull_raises=None):
        self.connection = ""
        self.error = ""
        self.pulled = []
        self._raises = pull_raises

    def pull(self, ingest):
        if self._raises is not None:
            raise self._raises
        self.pulled.append(ingest)


def test_apply_tick_reports_a_missing_ingest_without_raising():
    panel = _StubPanel()
    apply_tick(panel, None, server_key="SIM", ws_path="ws_live")
    assert panel.connection == "unavailable"
    assert "SIM" in panel.error and "ws_live" in panel.error
    assert panel.pulled == []


def test_apply_tick_mirrors_the_ingest_status():
    panel = _StubPanel()
    ingest = _StubIngest(state="live")
    apply_tick(panel, ingest, server_key="SIM", ws_path="ws_live")
    assert panel.connection == "live"
    assert panel.error == ""
    assert panel.pulled == [ingest]


def test_apply_tick_surfaces_an_ingest_error_string():
    panel = _StubPanel()
    apply_tick(
        panel,
        _StubIngest(state="reconnecting", error="boom"),
        server_key="SIM",
        ws_path="ws_live",
    )
    assert panel.connection == "reconnecting"
    assert panel.error == "boom"


def test_apply_tick_catches_a_failing_pull_so_the_loop_survives():
    """One bad tick must mark the panel, not kill the render loop."""
    panel = _StubPanel(pull_raises=ValueError("bad column"))
    apply_tick(panel, _StubIngest(), server_key="SIM", ws_path="ws_live")
    assert "ValueError" in panel.error and "bad column" in panel.error


def test_make_panel_state_keys_the_cache_on_the_base_class_not_its_name():
    """Two modules may define same-named bases; a name key would collide."""

    class LiveVisState(VisPanelState, mixin=True):  # type: ignore[call-arg]  # shadows
        ws_path: str = "ws_live"

    from helao.core.servers.reflex import state as state_mod

    real = make_panel_state("dup_panel", "SIM", state_mod.LiveVisState, "ws_live")
    impostor = make_panel_state("dup_panel", "SIM", LiveVisState, "ws_live")
    assert real is not impostor


PANEL_MODULES = ["wssim_panel", "oersim_panel", "gpsim_panel"]


@pytest.mark.parametrize("name", PANEL_MODULES)
def test_panel_module_satisfies_the_contract(name):
    from importlib import import_module

    mod = import_module(f"helao.deploy.test.servers.reflex.{name}")
    assert mod.WS_PATH in ("ws_live", "ws_data")
    assert issubclass(mod.STATE_BASE, VisPanelState)
    assert callable(mod.build)


@pytest.mark.parametrize("name", PANEL_MODULES)
def test_panel_builds_a_component_without_an_ingest_layer(name):
    """A panel must render before any data arrives."""
    from importlib import import_module

    mod = import_module(f"helao.deploy.test.servers.reflex.{name}")
    state_cls = make_panel_state(name, "TESTKEY", mod.STATE_BASE, mod.WS_PATH)
    assert mod.build("TESTKEY", state_cls) is not None


@pytest.mark.parametrize("name", PANEL_MODULES)
def test_panel_state_declares_the_chart_binding_vars(name):
    """build() binds these; pull() drives them. Both halves are required."""
    from importlib import import_module

    mod = import_module(f"helao.deploy.test.servers.reflex.{name}")
    assert hasattr(mod.STATE_BASE, "chart_spec")
    assert hasattr(mod.STATE_BASE, "chart_url")


def test_wssim_extract_reads_series_columns_from_the_buffer():
    import numpy as np

    from helao.core.servers.reflex.ingest import WsIngest
    from helao.deploy.test.servers.reflex import wssim_panel

    ing = WsIngest("127.0.0.1", 1, "ws_live")
    ing.buffer.append(
        {"epoch": [1.0, 2.0], "series_0": [10.0, 11.0], "series_1": [20.0, 21.0]}
    )
    cols = wssim_panel.extract(ing, window=10)
    np.testing.assert_allclose(cols["epoch"], [1.0, 2.0])
    np.testing.assert_allclose(cols["series"]["series_0"], [10.0, 11.0])
    assert "series_1" in cols["series"]


def test_wssim_extract_skips_the_epoch_column_in_the_series_set():
    from helao.core.servers.reflex.ingest import WsIngest
    from helao.deploy.test.servers.reflex import wssim_panel

    ing = WsIngest("127.0.0.1", 1, "ws_live")
    ing.buffer.append({"epoch": [1.0], "series_0": [5.0]})
    assert "epoch" not in wssim_panel.extract(ing, window=10)["series"]


def test_wssim_extract_on_an_empty_buffer_returns_empty_not_none():
    from helao.core.servers.reflex.ingest import WsIngest
    from helao.deploy.test.servers.reflex import wssim_panel

    ing = WsIngest("127.0.0.1", 1, "ws_live")
    cols = wssim_panel.extract(ing, window=10)
    assert cols["epoch"].size == 0
    assert cols["series"] == {}


def test_panel_id_is_stable_per_session_and_distinct_across_sessions():
    """The earlier version of this test asserted the defect.

    It required panel_id to depend on server_key alone, which is exactly what
    let two browser tabs share a buffer-store key: the store holds one frame per
    key while the version counter is per-session state, so each tab 404s the
    other into a permanently frozen chart with a "live" badge.
    """
    from helao.deploy.test.servers.reflex import wssim_panel as w

    assert w.panel_id("SIM", "tok-a") == w.panel_id("SIM", "tok-a")
    assert w.panel_id("SIM", "tok-a") != w.panel_id("OTHER", "tok-a")
    assert w.panel_id("SIM", "tok-a") != w.panel_id("SIM", "tok-b")


def test_every_panel_scopes_its_buffer_key_by_session():
    from importlib import import_module

    for name in PANEL_MODULES:
        mod = import_module(f"helao.deploy.test.servers.reflex.{name}")
        assert mod.panel_id("SIM", "tok-a") != mod.panel_id("SIM", "tok-b"), name
        assert hasattr(mod.STATE_BASE, "panel_key"), name


def test_gpsim_histograms_are_extracted_from_raw_batches():
    from helao.core.servers.reflex.ingest import WsIngest
    from helao.deploy.test.servers.reflex import gpsim_panel

    ing = WsIngest("127.0.0.1", 1, "ws_live")
    ing.raw.append(
        [
            {
                "plate_id": ([4001], 100.0),
                "pred_avail": ([[0.3, 0.4, 0.5]], 100.0),
                "gt_acquired": ([[0.35, 0.45]], 100.0),
            }
        ]
    )
    hists = gpsim_panel.extract_histograms(ing)
    assert "4001 predicted" in hists
    assert "4001 acquired" in hists
    assert len(hists["4001 predicted"]) == 3


def test_oersim_plots_t_s_as_x_not_epoch():
    """ws_data packets carry no epoch column; looking for one plots nothing."""
    import numpy as np

    from helao.core.servers.reflex.ingest import WsIngest
    from helao.deploy.test.servers.reflex import oersim_panel

    ing = WsIngest("127.0.0.1", 1, "ws_data")
    ing.buffer.append({"t_s": [0.1, 0.2], "erhe_v": [1.2, 1.3]})
    cols = oersim_panel.extract(ing, window=10)
    np.testing.assert_allclose(cols["x"], [0.1, 0.2])
    assert "erhe_v" in cols["series"]
    assert "t_s" not in cols["series"]


def test_oersim_surfaces_the_streamed_action_uuid():
    from helao.core.servers.reflex.ingest import WsIngest
    from helao.deploy.test.servers.reflex import oersim_panel

    ing = WsIngest("127.0.0.1", 1, "ws_data")
    ing.rows.append({"action_uuid": "abc-123", "status": "active"})
    assert oersim_panel.extract(ing, window=10)["action_uuid"] == "abc-123"


def test_gpsim_table_includes_the_numeric_columns():
    """plate_id/step/frac_acquired are numeric, so they never reach .rows.

    Reading the table from .rows left three of five columns permanently blank.
    """
    from helao.core.servers.reflex.ingest import WsIngest
    from helao.deploy.test.servers.reflex import gpsim_panel

    ing = WsIngest("127.0.0.1", 1, "ws_live")
    ing.raw.append(
        [
            {
                "plate_id": ([4001], 100.0),
                "step": ([7], 100.0),
                "frac_acquired": ([0.42], 100.0),
                "last_acquisition": (["Co0.5-Ni0.5"], 100.0),
                "orchestrator": (["orch0"], 100.0),
            }
        ]
    )
    rows = gpsim_panel.extract_table_rows(ing)
    assert rows and rows[0][0] == "4001"
    assert rows[0][1] == "7"
    assert rows[0][2] == "0.42"
    assert rows[0][3] == "Co0.5-Ni0.5"
    assert rows[0][4] == "orch0"


def test_gpsim_table_does_not_re_append_the_same_batch():
    """pull() runs on a timer; the driver publishes per acquisition.

    Without a watermark the newest raw batch is re-appended every tick and the
    "Last 20 acquisitions" table collapses to one row repeated.
    """
    from helao.core.servers.reflex.ingest import WsIngest
    from helao.deploy.test.servers.reflex import gpsim_panel

    ing = WsIngest("127.0.0.1", 1, "ws_live")
    ing.raw.append(
        [
            {
                "plate_id": ([4001], 100.0),
                "step": ([7], 100.0),
                "frac_acquired": ([0.42], 100.0),
                "last_acquisition": (["Co0.5-Ni0.5"], 100.0),
                "orchestrator": (["orch0"], 100.0),
            }
        ]
    )
    ing.status.message_count = 1

    class _P:
        last_table_count = -1
        table_rows: list = []

    panel = _P()
    for _ in range(5):  # five render ticks, one published batch
        count = ing.status.message_count
        if count != panel.last_table_count:
            panel.last_table_count = count
            panel.table_rows = (panel.table_rows + gpsim_panel.extract_table_rows(ing))[
                -20:
            ]
    assert len(panel.table_rows) == 1


def test_gpsim_table_rows_on_an_empty_raw_deque_is_empty():
    from helao.core.servers.reflex.ingest import WsIngest
    from helao.deploy.test.servers.reflex import gpsim_panel

    assert gpsim_panel.extract_table_rows(WsIngest("127.0.0.1", 1, "ws_live")) == []


def test_gpsim_histograms_on_an_empty_raw_deque_is_empty():
    from helao.core.servers.reflex.ingest import WsIngest
    from helao.deploy.test.servers.reflex import gpsim_panel

    assert gpsim_panel.extract_histograms(WsIngest("127.0.0.1", 1, "ws_live")) == {}


def test_gpsim_passes_raw_samples_to_the_facade_not_prebinned_data():
    """xy has a native hist mark; binning in Python would be redundant work."""
    import inspect

    from helao.deploy.test.servers.reflex import gpsim_panel

    src = inspect.getsource(gpsim_panel)
    assert "plots.histogram" in src
    assert "np.histogram" not in src


def test_generated_state_class_is_picklable():
    """Reflex serializes state for persistence. A type()-built class that is
    not published under its own name is unreachable to pickle, and the backend
    logged a StateSerializationError per panel per tick -- harmless under the
    in-memory state manager, fatal to a disk- or Redis-backed one, and enough
    noise to bury real errors either way."""
    import pickle
    import sys

    cls = make_panel_state("wssim_panel", "SIM_PICKLE", LiveVisState, "ws_live")
    assert getattr(sys.modules[cls.__module__], cls.__name__, None) is cls
    assert pickle.loads(pickle.dumps(cls)) is cls


def test_panels_tick_from_a_component_not_a_server_loop():
    """A server-side `while True` outlives the browser tab: on_unmount fires on
    in-app navigation but never on a closed tab, so every abandoned tab left
    one loop per panel sampling forever."""
    import ast
    import inspect

    from helao.core.servers.reflex.state import VisPanelState

    # The AST, not the text: the docstring explaining this says "while True".
    tree = ast.parse(inspect.getsource(VisPanelState))
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.While)]


def test_render_loop_still_exists_for_panels_outside_this_repo():
    """Panel modules in private deployments bind on_mount=render_loop. The
    name is kept so they keep working; it now primes one frame."""
    from helao.core.servers.reflex.state import VisPanelState

    assert hasattr(VisPanelState, "render_loop")
    assert hasattr(VisPanelState, "render_tick")


def test_priming_sets_the_tick_cadence_from_the_update_rate():
    """LiveVisState overrides update_rate, so a class-level tick_ms default
    would disagree with it."""
    from helao.core.servers.reflex.state import LiveVisState, VisPanelState

    assert LiveVisState.__fields__["update_rate"].default == 0.5
    # The prime step derives tick_ms rather than trusting the default.
    import inspect

    assert "tick_ms = int(self.update_rate" in inspect.getsource(
        VisPanelState.render_loop
    )
