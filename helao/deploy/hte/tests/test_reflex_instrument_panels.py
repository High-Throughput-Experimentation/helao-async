"""Reflex contract checks for hte's instrument panels; the shared helpers' own tests are in helao/deploy/base/tests."""


def test_every_action_panel_exposes_the_contract():
    from helao.deploy.hte.servers.nidaqmx.reflex import nidaqmx_vis
    from helao.deploy.hte.servers.power_supply.reflex import power_supply_vis

    for module in (nidaqmx_vis, power_supply_vis):
        assert module.WS_PATH == "ws_data"
        assert callable(module.build)
        assert getattr(module.STATE_BASE, "_mixin", False), module.__name__


def test_the_action_panels_do_not_share_a_state_class():
    from helao.deploy.hte.servers.nidaqmx.reflex import nidaqmx_vis
    from helao.deploy.hte.servers.power_supply.reflex import power_supply_vis

    assert nidaqmx_vis.STATE_BASE is not power_supply_vis.STATE_BASE


def test_action_panel_ids_are_distinct_per_panel_and_session():
    from helao.deploy.hte.servers.nidaqmx.reflex import nidaqmx_vis
    from helao.deploy.hte.servers.power_supply.reflex import power_supply_vis

    assert nidaqmx_vis.panel_id("NI", "tok") != power_supply_vis.panel_id("NI", "tok")
    assert nidaqmx_vis.panel_id("NI", "a") != nidaqmx_vis.panel_id("NI", "b")


def test_nidaqmx_declares_the_columns_its_server_streams():
    """t_s is the x axis and must not be plotted as a series."""
    from helao.deploy.hte.servers.nidaqmx.reflex import nidaqmx_vis

    assert nidaqmx_vis.X_COLUMN == "t_s"


def test_every_live_panel_exposes_the_contract():
    """A panel missing one of these fails at render time inside the page, not
    at import, so the check is worth making explicitly."""
    from helao.deploy.hte.servers.co2sensor.reflex import co2_vis
    from helao.deploy.hte.servers.mfc.reflex import mfc_vis
    from helao.deploy.base.servers.reflex import pressure_vis
    from helao.deploy.base.servers.reflex import temp_vis

    for module in (co2_vis, mfc_vis, pressure_vis, temp_vis):
        assert module.WS_PATH == "ws_live"
        assert callable(module.build)
        assert getattr(module.STATE_BASE, "_mixin", False), module.__name__


def test_each_panel_declares_its_own_axis_label():
    from helao.deploy.hte.servers.co2sensor.reflex import co2_vis
    from helao.deploy.hte.servers.mfc.reflex import mfc_vis
    from helao.deploy.base.servers.reflex import pressure_vis
    from helao.deploy.base.servers.reflex import temp_vis

    labels = {module.Y_LABEL for module in (co2_vis, mfc_vis, pressure_vis, temp_vis)}
    assert len(labels) == 4


def test_the_panels_do_not_share_a_state_class():
    """A var declared on a concrete rx.State is shared by every substate under
    it; each panel needs its own mixin."""
    from helao.deploy.hte.servers.co2sensor.reflex import co2_vis
    from helao.deploy.base.servers.reflex import temp_vis

    assert co2_vis.STATE_BASE is not temp_vis.STATE_BASE


def test_panel_ids_are_distinct_per_panel_and_session():
    from helao.deploy.hte.servers.co2sensor.reflex import co2_vis
    from helao.deploy.base.servers.reflex import temp_vis

    assert co2_vis.panel_id("CO2", "tok") != temp_vis.panel_id("CO2", "tok")
    assert co2_vis.panel_id("CO2", "tok-a") != co2_vis.panel_id("CO2", "tok-b")


def test_both_panels_expose_the_contract():
    from helao.deploy.hte.servers.sample.reflex import sample_vis
    from helao.deploy.hte.servers.spec.reflex import spec_vis

    for module in (spec_vis, sample_vis):
        assert module.WS_PATH == "ws_data"
        assert callable(module.build)
        assert getattr(module.STATE_BASE, "_mixin", False), module.__name__


def test_they_do_not_share_a_state_class():
    from helao.deploy.hte.servers.sample.reflex import sample_vis
    from helao.deploy.hte.servers.spec.reflex import spec_vis

    assert spec_vis.STATE_BASE is not sample_vis.STATE_BASE
