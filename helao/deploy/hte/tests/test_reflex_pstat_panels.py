"""Tests for the hte deployment's Reflex potentiostat panels.

Gamry and BioLogic share a shape the other action panels do not: the operator
picks which column is x and which is y, with a per-technique default, and
BioLogic draws one plot pair per hardware channel. That logic lives in
``servers/reflex/_pstat.py``.
"""

import numpy as np

from helao.deploy.hte.servers.reflex import _pstat


def _snap(**cols):
    return {k: np.asarray(v, dtype=float) for k, v in cols.items()}


COLUMNS = ["t_s", "Ewe_V", "I_A", "Zreal", "Zimag"]
AXIS_MAP = {"run_CA": ("t_s", "I_A"), "run_CV": ("Ewe_V", "I_A")}


# -- axis defaults -----------------------------------------------------------


def test_the_technique_chooses_the_axes():
    """A CV is read as current against potential; a CA against time. Plotting
    either on the other's axes makes the measurement unreadable."""
    assert _pstat.axis_defaults(AXIS_MAP, "run_CV", COLUMNS) == ("Ewe_V", "I_A")
    assert _pstat.axis_defaults(AXIS_MAP, "run_CA", COLUMNS) == ("t_s", "I_A")


def test_an_unmapped_action_falls_back_to_the_first_two_columns():
    """New techniques appear before the map is updated; the panel must still
    plot something rather than nothing."""
    assert _pstat.axis_defaults(AXIS_MAP, "run_SOMETHING_NEW", COLUMNS) == (
        "t_s",
        "Ewe_V",
    )


def test_no_action_name_still_yields_axes():
    assert _pstat.axis_defaults(AXIS_MAP, "", COLUMNS) == ("t_s", "Ewe_V")


def test_axis_defaults_with_too_few_columns():
    assert _pstat.axis_defaults(AXIS_MAP, "", ["only"]) == ("only", "only")


def test_axis_defaults_on_no_columns():
    assert _pstat.axis_defaults(AXIS_MAP, "", []) == ("", "")


def test_a_mapped_axis_the_stream_lacks_falls_back():
    """The map names Zreal/Zimag for EIS, but a server that never streams them
    must not leave the panel pointed at a column that does not exist."""
    axis_map = {"run_PEIS": ("Zreal", "Zimag")}
    assert _pstat.axis_defaults(axis_map, "run_PEIS", ["t_s", "Ewe_V"]) == (
        "t_s",
        "Ewe_V",
    )


# -- xy selection ------------------------------------------------------------


def test_xy_pair_picks_the_two_named_columns():
    snap = _snap(t_s=[0, 1], Ewe_V=[1, 2], I_A=[3, 4])
    x, series = _pstat.xy_pair(snap, "t_s", "I_A")
    assert list(x) == [0.0, 1.0]
    assert list(series) == ["I_A"]
    assert list(series["I_A"]) == [3.0, 4.0]


def test_xy_pair_with_a_missing_y_is_empty():
    """Rendering an absent column as an empty series beats raising inside the
    chart, which takes the whole panel down."""
    x, series = _pstat.xy_pair(_snap(t_s=[0, 1]), "t_s", "I_A")
    assert series == {}


def test_xy_pair_with_a_missing_x_is_empty():
    x, series = _pstat.xy_pair(_snap(I_A=[1.0]), "t_s", "I_A")
    assert x.size == 0
    assert series == {}


def test_xy_pair_negates_zimag():
    """A Nyquist plot is -Zimag against Zreal; the Bokeh panel relabels it and
    plots the negation."""
    snap = _snap(Zreal=[1.0, 2.0], Zimag=[3.0, 4.0])
    _, series = _pstat.xy_pair(snap, "Zreal", "Zimag")
    assert list(series) == ["-Zimag"]
    assert list(series["-Zimag"]) == [-3.0, -4.0]


def test_xy_pair_leaves_other_columns_signed_as_they_are():
    snap = _snap(t_s=[0.0], I_A=[-5.0])
    _, series = _pstat.xy_pair(snap, "t_s", "I_A")
    assert list(series["I_A"]) == [-5.0]


# -- channels ----------------------------------------------------------------


def test_channels_are_discovered_from_the_stream():
    snap = _snap(channel=[0, 0, 1, 2], t_s=[0, 1, 0, 0])
    assert _pstat.channels_in(snap) == [0, 1, 2]


def test_no_channel_column_means_a_single_unnumbered_channel():
    """Gamry streams no channel column; it is one potentiostat."""
    assert _pstat.channels_in(_snap(t_s=[0.0])) == []


def test_select_channel_keeps_only_that_channel_rows():
    snap = _snap(channel=[0, 1, 0], t_s=[10, 20, 30], I_A=[1, 2, 3])
    picked = _pstat.select_channel(snap, 0)
    assert list(picked["t_s"]) == [10.0, 30.0]
    assert list(picked["I_A"]) == [1.0, 3.0]


def test_select_channel_drops_the_channel_column_itself():
    """It is a routing key, not a measurement, and plotting it is noise."""
    snap = _snap(channel=[0, 0], t_s=[1, 2])
    assert "channel" not in _pstat.select_channel(snap, 0)


def test_select_channel_with_no_matching_rows():
    snap = _snap(channel=[0, 0], t_s=[1, 2])
    picked = _pstat.select_channel(snap, 7)
    assert picked["t_s"].size == 0


def test_select_channel_without_a_channel_column_returns_everything():
    snap = _snap(t_s=[1.0, 2.0])
    assert list(_pstat.select_channel(snap, 0)["t_s"]) == [1.0, 2.0]


def test_select_channel_keeps_every_column_the_same_length():
    snap = _snap(channel=[0, 1, 0], t_s=[1, 2, 3], I_A=[4, 5, 6])
    picked = _pstat.select_channel(snap, 0)
    assert len({v.size for v in picked.values()}) == 1


# -- the panels --------------------------------------------------------------


def test_both_pstat_panels_expose_the_contract():
    from helao.deploy.hte.servers.reflex import biologic_vis, gamry_vis

    for module in (gamry_vis, biologic_vis):
        assert module.WS_PATH == "ws_data"
        assert callable(module.build)
        assert getattr(module.STATE_BASE, "_mixin", False), module.__name__


def test_the_pstat_panels_do_not_share_a_state_class():
    from helao.deploy.hte.servers.reflex import biologic_vis, gamry_vis

    assert gamry_vis.STATE_BASE is not biologic_vis.STATE_BASE


def test_each_pstat_panel_keeps_its_own_axis_map():
    """The two potentiostats support different techniques; Gamry has EIS
    columns BioLogic does not."""
    from helao.deploy.hte.servers.reflex import biologic_vis, gamry_vis

    assert gamry_vis.AXIS_MAP != biologic_vis.AXIS_MAP
    assert "Zreal" in gamry_vis.COLUMNS
    assert "R_ohm" in biologic_vis.COLUMNS


def test_pstat_panel_ids_are_distinct():
    from helao.deploy.hte.servers.reflex import biologic_vis, gamry_vis

    assert gamry_vis.panel_id("PSTAT", "t") != biologic_vis.panel_id("PSTAT", "t")
