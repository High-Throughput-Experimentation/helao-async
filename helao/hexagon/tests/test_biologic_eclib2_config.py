"""The `biologiceclib2` dev config, launchable on Linux with no hardware.

`launch.py biologiceclib2` brings up the orchestrator, the action server on the
eclib2 backend, and the visualizer, with no potentiostat, no EC-Lib DLL and no
license file. These tests pin the parts of the config that make that true; the
launch itself is not something pytest can assert, so it is recorded in the
commit rather than here.
"""

import pytest

from helao.deploy.hte.drivers.pstat.biologic_eclib2.driver import BiologicEclib2Driver

PREFIX = "biologiceclib2"


@pytest.fixture
def config():
    from helao.helpers.config_loader import read_config

    return read_config(PREFIX)


def test_the_prefix_resolves_to_a_config(config):
    # launch.py globs helao/deploy/*/configs/<prefix>.*, so a prefix that does
    # not resolve fails at launch with "config not found" and nothing else.
    assert "servers" in config


def test_it_selects_the_eclib2_backend_in_simulation(config):
    params = config["servers"]["BIOLOGIC"]["params"]
    assert params["pstat_backend"] == "eclib2"
    assert params["simulate"] is True


def test_it_needs_no_sdk_path_because_it_simulates(config):
    # The vendor package is not importable off-station, so a dev config that
    # required a path would not be launchable at all.
    assert "sdk_path" not in config["servers"]["BIOLOGIC"]["params"]


def test_the_driver_it_names_is_constructible_from_these_params(config):
    # The config is only useful if the params it carries actually satisfy the
    # driver's constructor.
    params = config["servers"]["BIOLOGIC"]["params"]
    driver = BiologicEclib2Driver(params)
    try:
        assert driver.simulate is True
        assert driver.num_channels == 1
    finally:
        driver.shutdown()


def test_it_connects_and_reports_ready_with_no_hardware(config):
    params = config["servers"]["BIOLOGIC"]["params"]
    driver = BiologicEclib2Driver(params)
    try:
        response = driver.connect()
        assert response.response == "success", response.message
        assert driver.ready is True
        # The simulated SP-300 has a board in slot 0 only, and num_channels
        # matches, so nothing is reported missing.
        assert driver.usable_channels == [0]
        assert driver.missing_channels == []
    finally:
        driver.shutdown()


def test_num_channels_matches_what_the_simulator_provides(config):
    # A larger value would come up with channels reporting not_plugged, which
    # is correct behaviour but confusing in a dev config.
    assert config["servers"]["BIOLOGIC"]["params"]["num_channels"] == 1


def test_no_duplicate_host_ports(config):
    # launch.py refuses a group whose servers collide, and the failure names
    # the port rather than the config.
    endpoints = [(s["host"], s["port"]) for s in config["servers"].values()]
    assert len(endpoints) == len(set(endpoints)), endpoints


def test_the_ports_do_not_collide_with_another_hte_config():
    # Two dev configs launched together would fight over a port; htereflex
    # already occupies 8101-8112.
    from pathlib import Path

    import yaml

    mine = set()
    others = set()
    for path in Path("helao/deploy/hte/configs").glob("*.yml"):
        loaded = yaml.safe_load(path.read_text()) or {}
        ports = {
            server.get("port")
            for server in (loaded.get("servers") or {}).values()
            if isinstance(server, dict)
        }
        (mine if path.stem == PREFIX else others).update(ports)
    assert mine, "the config declares no ports"
    assert not (mine & others), sorted(mine & others)


def test_it_names_a_visualizer_the_biologic_panels_answer_to(config):
    # Both UI stacks resolve their panel from this key; a typo yields an empty
    # visualizer rather than an error.
    assert config["servers"]["BIOLOGIC"]["action_vis"] == "biologic_vis"


def test_it_is_marked_as_a_simulation_group(config):
    # `dummy`/`simulation` drive the banner colour and are how an operator
    # tells a dev launch from a station at a glance.
    assert config["dummy"] is True
    assert config["simulation"] is True


def test_the_root_is_an_absolute_path_outside_the_repo(config):
    # HELAO does not expand `~`, so a tilde would create a literal '~'
    # directory in the working directory -- for a dev launch, the repo itself.
    root = config["root"]
    assert not root.startswith("~"), root
    assert root.startswith("/"), root


def test_it_declares_an_orchestrator_so_the_group_is_a_real_group(config):
    groups = {s.get("group") for s in config["servers"].values()}
    assert "orchestrator" in groups
    assert "action" in groups


def test_the_action_server_names_the_biologic_module(config):
    # The launcher finds makeApp by import path, so this value and the file
    # name under servers/action/ must agree.
    assert config["servers"]["BIOLOGIC"]["fast"] == "biologic_server"


def test_the_server_key_is_the_one_the_technique_endpoints_are_named_from(config):
    # Routes are /<server_key>/<action>, and the hte experiment libraries
    # dispatch to /BIOLOGIC/run_*.
    assert "BIOLOGIC" in config["servers"]
