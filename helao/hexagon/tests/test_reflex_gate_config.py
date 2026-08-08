"""P7f gate config: `goldenhexreflex.yml`, a hexagon-hosted Reflex server.

`goldenreflex.yml` is the legacy original; this config is that file with ONE
key added. That relationship is asserted structurally rather than described,
because it is the rollback claim: if the two configs ever differ by more than
`deployment:` (and the `root:` each bundle lives under), "delete the key" is
no longer a complete rollback and this suite should say so.
"""

import os

import pytest

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
_CONFIGS = os.path.join(_REPO_ROOT, "helao", "deploy", "test", "configs")
_HEX = os.path.join(_CONFIGS, "goldenhexreflex.yml")
_LEGACY = os.path.join(_CONFIGS, "goldenreflex.yml")

#: Keys the two configs are allowed to differ by. `root:` is not part of the
#: seam -- a bundle and a run tree are per config, and sharing goldenreflex's
#: would have each launch invalidate the other's bundle.
_ALLOWED_DIFFS = {"deployment", "root"}


def _load(path):
    from helao.helpers.config_loader import read_config

    return read_config(path)


def test_gate_config_validates():
    import types

    from launch import validateConfig

    conf = _load(_HEX)
    pidd = types.SimpleNamespace(
        reqKeys=("host", "port", "group"), codeKeys=("fast", "bokeh", "reflex")
    )
    assert validateConfig(pidd, conf, _REPO_ROOT) is True


def test_gate_config_preflights_clean():
    """The D9 rejection this config would have tripped before P7f."""
    from helao.hexagon import preflight

    assert preflight.preflight_config(_HEX) == []


def test_the_flip_is_exactly_one_key():
    """The rollback, asserted as a diff rather than promised in prose."""
    hexa, legacy = _load(_HEX), _load(_LEGACY)
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


def test_the_reflex_key_still_names_the_bundle_not_a_module():
    """The rejected alternative, pinned. `reflex:`'s value is read by
    `resolve_bundle`/`build_reflex_bundle.py` as a directory name; making it a
    module path would break the bundle contract and all tracked configs."""
    import reflex_bundle

    assert _load(_HEX)["servers"]["UI"]["reflex"] == reflex_bundle.APP_NAME


def test_the_config_routes_the_entry_module_to_the_facade():
    """The config key and the routing decision, joined end to end: this is
    the function `build_env`, `import_app_module` and `build_reflex_bundle`
    all consult."""
    import reflex_bundle

    servers = _load(_HEX)["servers"]
    assert (
        reflex_bundle.app_module_for(servers["UI"]) == reflex_bundle.HEXAGON_APP_MODULE
    )
    # a legacy entry in the same config family routes nowhere new
    assert (
        reflex_bundle.app_module_for(_load(_LEGACY)["servers"]["UI"])
        == reflex_bundle.LEGACY_APP_MODULE
    )


def test_the_backend_port_is_reserved_by_the_gate_config():
    """A reflex server claims `port` and `port + 1`; nothing else in this
    config may hold either, and preflight is what enforces it."""
    from helao.core.servers.reflex.discovery import reserved_addresses

    servers = _load(_HEX)["servers"]
    assert reserved_addresses(servers["UI"]) == ["127.0.0.1:5010", "127.0.0.1:5011"]
    claimed = [f"{v['host']}:{v['port']}" for v in servers.values()]
    assert "127.0.0.1:5011" not in claimed


@pytest.mark.parametrize("path", [_HEX, _LEGACY])
def test_both_configs_carry_the_ws_sources_the_panels_need(path):
    """The gate is a rendering gate: without a live_vis and an action_vis
    server the pages render empty and prove nothing about hosting."""
    servers = _load(path)["servers"]
    assert servers["SIM"]["live_vis"] == "wssim_panel"
    assert servers["CPSIM"]["action_vis"] == "oersim_panel"
    assert servers["GPSIM"]["live_vis"] == "gpsim_panel"
    assert servers["UI"]["params"]["pages"] == ["live", "action"]
