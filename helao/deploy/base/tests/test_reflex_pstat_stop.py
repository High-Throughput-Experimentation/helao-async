"""Base-only checks under the Reflex potentiostat stop button: the `_pstat` and `_pstat_panel` helpers. The panel-driven stop cases are in hte's test_reflex_pstat_stop.py."""

from helao.ui.shared import palette
from helao.deploy.base.servers.reflex import _pstat, _pstat_panel

SERV_KEY = "PSTAT"
SERVERS = {SERV_KEY: {"host": "127.0.0.1", "port": 8004}}
WORLD = {"servers": SERVERS}


def test_stop_params_shapes():
    assert _pstat.stop_params() == {}
    assert _pstat.stop_params(None) == {}
    assert _pstat.stop_params("") == {}
    assert _pstat.stop_params(0) == {"channel": 0}
    assert _pstat.stop_params("2") == {"channel": 2}
    print("test_stop_params_shapes PASS")


def test_channel_zero_is_a_channel_not_an_absent_one():
    """``0`` is falsy and is BioLogic's first channel; a truthiness test here
    would silently turn "stop channel 0" into "stop everything"."""
    assert _pstat.stop_params(0) == {"channel": 0}
    print("test_channel_zero_is_a_channel_not_an_absent_one PASS")


def test_server_address_reads_the_same_config_the_bokeh_panel_does():
    assert _pstat.server_address(WORLD, SERV_KEY) == ("127.0.0.1", 8004)
    assert _pstat.server_address(WORLD, "NOPE") == (None, None)
    assert _pstat.server_address({}, SERV_KEY) == (None, None)
    print("test_server_address_reads_the_same_config_the_bokeh_panel_does PASS")


def test_world_config_falls_back_to_the_installed_global(monkeypatch):
    """A stop pressed before ingest has started still needs an address."""
    monkeypatch.setattr(_pstat_panel, "get_registry", lambda: None)
    monkeypatch.setattr(_pstat_panel.config_loader, "CONFIG", WORLD, raising=False)

    assert _pstat_panel.world_config() is WORLD
    print("test_world_config_falls_back_to_the_installed_global PASS")


def test_the_stop_button_is_not_painted_as_the_estop():
    """It aborts one server's measurement; the station-wide cascade is a
    different authority and a different red."""
    assert palette.TW["red-700"] != palette.ESTOP_BG
    print("test_the_stop_button_is_not_painted_as_the_estop PASS")
