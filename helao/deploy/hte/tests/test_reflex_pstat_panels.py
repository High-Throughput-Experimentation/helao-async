"""Reflex contract checks for hte's potentiostat panels (Gamry, BioLogic); the shared `_pstat` helpers' own tests are in helao/deploy/base/tests/test_reflex_pstat_panels.py."""


def test_both_pstat_panels_expose_the_contract():
    from helao.deploy.hte.servers.biologic.reflex import biologic_vis
    from helao.deploy.hte.servers.gamry.reflex import gamry_vis

    for module in (gamry_vis, biologic_vis):
        assert module.WS_PATH == "ws_data"
        assert callable(module.build)
        assert getattr(module.STATE_BASE, "_mixin", False), module.__name__


def test_the_pstat_panels_do_not_share_a_state_class():
    from helao.deploy.hte.servers.biologic.reflex import biologic_vis
    from helao.deploy.hte.servers.gamry.reflex import gamry_vis

    assert gamry_vis.STATE_BASE is not biologic_vis.STATE_BASE


def test_each_pstat_panel_keeps_its_own_axis_map():
    """The two potentiostats support different techniques; Gamry has EIS
    columns BioLogic does not."""
    from helao.deploy.hte.servers.biologic.reflex import biologic_vis
    from helao.deploy.hte.servers.gamry.reflex import gamry_vis

    assert gamry_vis.AXIS_MAP != biologic_vis.AXIS_MAP
    assert "Zreal" in gamry_vis.COLUMNS
    assert "R_ohm" in biologic_vis.COLUMNS


def test_pstat_panel_ids_are_distinct():
    from helao.deploy.hte.servers.biologic.reflex import biologic_vis
    from helao.deploy.hte.servers.gamry.reflex import gamry_vis

    assert gamry_vis.panel_id("PSTAT", "t") != biologic_vis.panel_id("PSTAT", "t")


def test_the_ocv_columns_the_gamry_driver_streams_resolve_to_its_default_axes():
    """The reported case: run_OCV against a real Gamry, whose dtaq emits eight
    columns beyond the two this panel plots."""
    from helao.deploy.hte.servers.gamry.dtaq import DTAQ_OCV
    from helao.deploy.hte.servers.gamry.reflex import gamry_vis
    from helao.deploy.base.servers.reflex._pstat import axis_defaults, plottable_columns

    snapshot = {key: [0.0] for key in DTAQ_OCV.output_keys}
    present = plottable_columns(snapshot, gamry_vis.COLUMNS)
    assert present[:2] == ["t_s", "Ewe_V"]
    assert axis_defaults(gamry_vis.AXIS_MAP, "run_OCV", present) == ("t_s", "Ewe_V")
