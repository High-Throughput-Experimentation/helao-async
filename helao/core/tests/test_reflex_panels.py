"""Tests for Reflex panel state plumbing and the test-deployment panels."""

import pytest

from types import SimpleNamespace

from helao.core.servers.reflex.state import (
    ActionVisState,
    apply_tick,
    loop_superseded,
    may_clear_running,
    LiveVisState,
    VisPanelState,
    make_panel_state,
)


def test_live_and_action_bases_carry_the_right_ws_path():
    assert LiveVisState.ws_path_default == "ws_live"
    assert ActionVisState.ws_path_default == "ws_data"


def test_make_panel_state_bakes_in_the_server_key():
    cls = make_panel_state("wssim_panel", "SIM", LiveVisState, "ws_live")
    assert cls.server_key_default == "SIM"
    assert cls.ws_path_default == "ws_live"


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


def test_a_loop_holding_the_current_generation_keeps_running():
    assert loop_superseded(current_generation=3, token=3) is False


def test_a_loop_whose_generation_was_bumped_exits():
    """The race: a newer loop started, or stop_loop fired, while we slept."""
    assert loop_superseded(current_generation=4, token=3) is True


def test_only_the_current_loop_may_clear_the_running_flag():
    assert may_clear_running(current_generation=3, token=3) is True


def test_a_superseded_loop_must_not_clear_the_running_flag():
    """Clearing it would report the live loop as stopped."""
    assert may_clear_running(current_generation=4, token=3) is False


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

    class LiveVisState(VisPanelState):  # deliberately shadows the real name
        ws_path: str = "ws_live"
        ws_path_default: str = "ws_live"

    from helao.core.servers.reflex import state as state_mod

    real = make_panel_state("dup_panel", "SIM", state_mod.LiveVisState, "ws_live")
    impostor = make_panel_state("dup_panel", "SIM", LiveVisState, "ws_live")
    assert real is not impostor
