"""Tests for Reflex panel state plumbing and the test-deployment panels."""

import pytest

from helao.core.servers.reflex.state import (
    ActionVisState,
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
