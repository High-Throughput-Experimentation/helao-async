"""P7f/P7k gate configs: a hexagon-hosted Reflex server, in two deployments.

`goldenreflex.yml` is the legacy original; `goldenhexreflex.yml` is that file
with ONE key added. `htereflex.yml` / `htehexreflex.yml` (P7k) are the same
pair for the hte deployment's dev Reflex config. That relationship is asserted
structurally rather than described, because it is the rollback claim: if a
pair ever differs by more than `deployment:` (and the `root:` each bundle
lives under), "delete the key" is no longer a complete rollback and this suite
should say so.
"""

import os

import pytest

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
_CONFIGS = os.path.join(_REPO_ROOT, "helao", "deploy", "test", "configs")
_HTE_CONFIGS = os.path.join(_REPO_ROOT, "helao", "deploy", "hte", "configs")
_HEX = os.path.join(_CONFIGS, "goldenhexreflex.yml")
_LEGACY = os.path.join(_CONFIGS, "goldenreflex.yml")
_HTE_HEX = os.path.join(_HTE_CONFIGS, "htehexreflex.yml")
_HTE_LEGACY = os.path.join(_HTE_CONFIGS, "htereflex.yml")

#: (hexagon variant, legacy sibling) — every tracked pair, so a second
#: deployment's flip is held to the same one-key rollback as the first.
_PAIRS = [(_HEX, _LEGACY), (_HTE_HEX, _HTE_LEGACY)]

#: Keys the two configs are allowed to differ by. `root:` is not part of the
#: seam -- a bundle and a run tree are per config, and sharing goldenreflex's
#: would have each launch invalidate the other's bundle.
_ALLOWED_DIFFS = {"deployment", "root"}


def _load(path):
    from helao.helpers.config_loader import read_config

    return read_config(path)


@pytest.mark.parametrize("path", [_HEX, _HTE_HEX])
def test_gate_config_validates(path):
    import types

    from launch import validateConfig

    conf = _load(path)
    pidd = types.SimpleNamespace(
        reqKeys=("host", "port", "group"), codeKeys=("fast", "bokeh", "reflex")
    )
    assert validateConfig(pidd, conf, _REPO_ROOT) is True


@pytest.mark.parametrize("path", [_HEX, _HTE_HEX])
def test_gate_config_preflights_clean(path):
    """The D9 rejection these configs would have tripped before P7f."""
    from helao.hexagon import preflight

    assert preflight.preflight_config(path) == []


@pytest.mark.parametrize("hex_path,legacy_path", _PAIRS)
def test_the_flip_is_exactly_one_key(hex_path, legacy_path):
    """The rollback, asserted as a diff rather than promised in prose."""
    hexa, legacy = _load(hex_path), _load(legacy_path)
    assert set(hexa["servers"]) == set(legacy["servers"])
    for key in hexa["servers"]:
        a, b = hexa["servers"][key], legacy["servers"][key]
        differing = {
            k for k in set(a) | set(b) if a.get(k) != b.get(k)
        } - _ALLOWED_DIFFS
        assert not differing, f"{key} differs by {sorted(differing)}"
    assert hexa["servers"]["UI"]["deployment"] == "hexagon"
    assert "deployment" not in legacy["servers"]["UI"]
    # every other server is deliberately left legacy: the seam under test is
    # the Reflex hosting route alone
    assert [k for k, v in hexa["servers"].items() if v.get("deployment")] == ["UI"]


@pytest.mark.parametrize("path", [_HEX, _HTE_HEX])
def test_the_reflex_key_still_names_the_bundle_not_a_module(path):
    """The rejected alternative, pinned. `reflex:`'s value is read by
    `resolve_bundle`/`build_reflex_bundle.py` as a directory name; making it a
    module path would break the bundle contract and all tracked configs."""
    import reflex_bundle

    assert _load(path)["servers"]["UI"]["reflex"] == reflex_bundle.APP_NAME


@pytest.mark.parametrize("hex_path,legacy_path", _PAIRS)
def test_the_config_routes_the_entry_module_to_the_facade(hex_path, legacy_path):
    """The config key and the routing decision, joined end to end: this is
    the function `build_env`, `import_app_module` and `build_reflex_bundle`
    all consult."""
    import reflex_bundle

    servers = _load(hex_path)["servers"]
    assert (
        reflex_bundle.app_module_for(servers["UI"]) == reflex_bundle.HEXAGON_APP_MODULE
    )
    # a legacy entry in the same config family routes nowhere new
    assert (
        reflex_bundle.app_module_for(_load(legacy_path)["servers"]["UI"])
        == reflex_bundle.LEGACY_APP_MODULE
    )


@pytest.mark.parametrize("path", [_HEX, _HTE_HEX])
def test_the_backend_port_is_reserved_by_the_gate_config(path):
    """A reflex server claims `port` and `port + 1`; nothing else in this
    config may hold either, and preflight is what enforces it. The backend
    port is computed from the config rather than written down twice -- a
    second copy of it here would be the same invisible claim the check is
    about."""
    from helao.ui.shared.discovery import reserved_addresses

    servers = _load(path)["servers"]
    ui = servers["UI"]
    backend = f"{ui['host']}:{ui['port'] + 1}"
    assert reserved_addresses(ui) == [f"{ui['host']}:{ui['port']}", backend]
    claimed = [f"{v['host']}:{v['port']}" for v in servers.values()]
    assert backend not in claimed


@pytest.mark.parametrize("path", [_HEX, _LEGACY])
def test_both_configs_carry_the_ws_sources_the_panels_need(path):
    """The gate is a rendering gate: without a live_vis and an action_vis
    server the pages render empty and prove nothing about hosting."""
    servers = _load(path)["servers"]
    assert servers["SIM"]["live_vis"] == "wssim_panel"
    assert servers["CPSIM"]["action_vis"] == "oersim_panel"
    assert servers["GPSIM"]["live_vis"] == "gpsim_panel"
    assert servers["UI"]["params"]["pages"] == ["live", "action"]


@pytest.mark.parametrize("path", [_HTE_HEX, _HTE_LEGACY])
def test_the_hte_pair_carries_the_panel_sources_too(path):
    """Same rendering-gate requirement for the hte dev pair, whose panels are
    the hte ones resolved from `live_vis`/`action_vis` (the sources are the
    test deployment's simulators pointed at hte column names)."""
    servers = _load(path)["servers"]
    assert servers["CO2SENSOR"]["live_vis"] == "co2_vis"
    assert servers["GAMRY"]["action_vis"] == "gamry_vis"
    assert servers["UI"]["params"]["pages"] == ["live", "action"]
