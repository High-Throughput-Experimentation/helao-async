"""Tests for the hte deployment's Reflex action panels.

``ws_data`` panels are per-action rather than continuous, so the logic that can
be wrong is about action boundaries and cell selection. It lives in
``servers/reflex/_action.py`` and is tested here directly.
"""

import numpy as np

from helao.deploy.hte.servers.reflex import _action


def _series(**cols):
    return {k: np.asarray(v, dtype=float) for k, v in cols.items()}


# -- action boundaries -------------------------------------------------------


def test_a_monotonic_window_is_all_one_action():
    """Nothing restarted, so there is no previous action to show."""
    x = np.array([0.0, 1.0, 2.0])
    prev, cur = _action.split_on_restart(x, _series(a=[1.0, 2.0, 3.0]))
    assert prev[0].size == 0
    assert list(cur[0]) == [0.0, 1.0, 2.0]


def test_a_restart_splits_the_window():
    """`t_s` is elapsed seconds within one action, so a decrease is the only
    marker of a new action available in the buffer -- the row store keeps one
    row per message and cannot be aligned with the numeric columns."""
    x = np.array([0.0, 1.0, 2.0, 0.0, 1.0])
    prev, cur = _action.split_on_restart(x, _series(a=[1.0, 2.0, 3.0, 9.0, 8.0]))
    assert list(prev[0]) == [0.0, 1.0, 2.0]
    assert list(cur[0]) == [0.0, 1.0]
    assert list(prev[1]["a"]) == [1.0, 2.0, 3.0]
    assert list(cur[1]["a"]) == [9.0, 8.0]


def test_only_the_most_recent_restart_splits():
    """Three actions in the window: the operator sees the current one and the
    one before it, as the Bokeh panel's two-figure layout does."""
    x = np.array([0.0, 1.0, 0.0, 1.0, 0.0])
    prev, cur = _action.split_on_restart(x, _series(a=[1.0, 2.0, 3.0, 4.0, 5.0]))
    assert list(prev[0]) == [0.0, 1.0]
    assert list(cur[0]) == [0.0]
    assert list(prev[1]["a"]) == [3.0, 4.0]


def test_an_empty_window_splits_into_two_empties():
    prev, cur = _action.split_on_restart(np.empty(0), {})
    assert prev[0].size == 0 and cur[0].size == 0
    assert prev[1] == {} and cur[1] == {}


def test_a_single_point_is_the_current_action():
    prev, cur = _action.split_on_restart(np.array([0.0]), _series(a=[1.0]))
    assert cur[0].size == 1
    assert prev[0].size == 0


def test_a_restart_at_the_first_sample_leaves_no_previous():
    x = np.array([5.0, 6.0])
    prev, cur = _action.split_on_restart(x, _series(a=[1.0, 2.0]))
    assert prev[0].size == 0
    assert cur[0].size == 2


def test_split_keeps_every_series_the_same_length_as_x():
    """plots raises when a series and its x differ in length."""
    x = np.array([0.0, 1.0, 0.0])
    prev, cur = _action.split_on_restart(x, _series(a=[1, 2, 3], b=[4, 5, 6]))
    for segment in (prev, cur):
        for values in segment[1].values():
            assert values.size == segment[0].size


# -- cell selection ----------------------------------------------------------


def test_cell_columns_are_discovered_from_the_stream():
    series = _series(Icell1_A=[1.0], Icell2_A=[2.0], Ecell1_V=[3.0], t_s=[0.0])
    assert _action.cell_numbers(series, _action.CURRENT_PATTERN) == [1, 2]
    assert _action.cell_numbers(series, _action.VOLTAGE_PATTERN) == [1]


def test_cell_numbers_are_sorted_numerically_not_lexically():
    """`Icell10_A` sorts before `Icell2_A` as text, which would scramble both
    the legend and the selector."""
    series = _series(Icell10_A=[1.0], Icell2_A=[2.0])
    assert _action.cell_numbers(series, _action.CURRENT_PATTERN) == [2, 10]


def test_cell_numbers_ignore_unrelated_columns():
    series = _series(t_s=[0.0], something_else=[1.0])
    assert _action.cell_numbers(series, _action.CURRENT_PATTERN) == []


def test_select_cells_keeps_only_the_requested_ones():
    series = _series(Icell1_A=[1.0], Icell2_A=[2.0], Icell3_A=[3.0])
    picked = _action.select_cells(series, _action.CURRENT_PATTERN, [1, 3])
    assert set(picked) == {"Icell1_A", "Icell3_A"}


def test_selecting_no_cells_yields_nothing_to_plot():
    """An empty selection is a legitimate operator action, not an error."""
    series = _series(Icell1_A=[1.0])
    assert _action.select_cells(series, _action.CURRENT_PATTERN, []) == {}


def test_select_cells_ignores_a_cell_the_stream_does_not_carry():
    series = _series(Icell1_A=[1.0])
    picked = _action.select_cells(series, _action.CURRENT_PATTERN, [1, 7])
    assert set(picked) == {"Icell1_A"}


# -- the panels --------------------------------------------------------------


def test_every_action_panel_exposes_the_contract():
    from helao.deploy.hte.servers.reflex import nidaqmx_vis, power_supply_vis

    for module in (nidaqmx_vis, power_supply_vis):
        assert module.WS_PATH == "ws_data"
        assert callable(module.build)
        assert getattr(module.STATE_BASE, "_mixin", False), module.__name__


def test_the_action_panels_do_not_share_a_state_class():
    from helao.deploy.hte.servers.reflex import nidaqmx_vis, power_supply_vis

    assert nidaqmx_vis.STATE_BASE is not power_supply_vis.STATE_BASE


def test_action_panel_ids_are_distinct_per_panel_and_session():
    from helao.deploy.hte.servers.reflex import nidaqmx_vis, power_supply_vis

    assert nidaqmx_vis.panel_id("NI", "tok") != power_supply_vis.panel_id("NI", "tok")
    assert nidaqmx_vis.panel_id("NI", "a") != nidaqmx_vis.panel_id("NI", "b")


def test_nidaqmx_declares_the_columns_its_server_streams():
    """t_s is the x axis and must not be plotted as a series."""
    from helao.deploy.hte.servers.reflex import nidaqmx_vis

    assert nidaqmx_vis.X_COLUMN == "t_s"
