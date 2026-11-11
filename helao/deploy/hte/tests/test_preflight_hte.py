"""Preflight and config gates over hte's own configs (moved from parent tests)."""

import re
import shutil
from pathlib import Path

import pytest

from helao.helpers.config_loader import read_config
from helao.hexagon import preflight

HTE = Path(__file__).resolve().parents[1]
REPO_ROOT = HTE.parents[2]
# hte canary configs (P3a/P3e) live in this centralized, hte-only directory;
# bare-prefix resolution (which globs helao/deploy/*/configs/) does not find
# them, so they must be passed by full path.
SMOKE_CONFIGS = HTE / "tests" / "smoke" / "configs"
STATION_CONFIGS = ["adss3", "anec", "ccsi2", "clad", "eche10", "ecms3", "hispec"]


@pytest.mark.parametrize("prefix", STATION_CONFIGS)
def test_every_hte_station_config_preflights_with_resolved_servers(prefix, capsys):
    assert preflight.main([prefix]) == 0
    out = capsys.readouterr().out
    m = re.search(r"PREFLIGHT OK: .* \(resolved (\d+) server\(s\)\)", out)
    assert m and int(m.group(1)) >= 1, out


@pytest.mark.parametrize("prefix", ["htereflex", "htehexreflex"])
def test_the_reflex_configs_pin_ws_simulator_to_test(prefix):
    """D-B7c.5 / §2.4: with Deployment-A checked out, sorted order would pick its
    ws_simulator. The pin is the explicit key, so assert the key, not the resolution."""
    cfg = read_config(prefix)
    entries = [s for s in cfg["servers"].values() if s.get("fast") == "ws_simulator"]
    assert len(entries) == 4 and all(s.get("deployment") == "test" for s in entries)
    issues, resolved = preflight._module_resolution(cfg)
    assert issues == []
    assert {
        resolved[k]
        for k, s in cfg["servers"].items()
        if s.get("fast") == "ws_simulator"
    } == {"test"}


def test_a_scratch_copy_of_a_config_still_exercises_the_checklist_gate(
    tmp_path, monkeypatch
):
    """P4f's silent-pass trap, closed by D-B7c.5, as a positive control.

    `_config_deployment` infers the deployment from the config's PATH, so a
    scratch copy has none. Gate 3 no longer depends on it: it looks up the
    OWNING deployment gate 2 resolved (here the explicit `deployment: hte`), so
    identical bytes are checked identically in-tree and out. With the checklist
    set emptied, both report the same real finding.
    """
    src = SMOKE_CONFIGS / "gamry.yml"
    scratch = tmp_path / src.name
    shutil.copy2(src, scratch)

    assert preflight._config_deployment(str(src)) == "hte"
    assert preflight._config_deployment(str(scratch)) is None
    assert preflight.preflight_config(str(src)) == []
    assert preflight.preflight_config(str(scratch)) == []

    empty = tmp_path / "checklists"
    empty.mkdir()
    (empty / "_at_b7c.json").write_text('["gamry_server2"]', encoding="utf-8")
    monkeypatch.setattr(preflight, "_checklist_dir", lambda deployment: empty)
    for config in (src, scratch):
        found = preflight.preflight_config(str(config))
        assert len(found) == 1 and "frozen endpoint checklist" in found[0], found


def test_smoke_canary_configs_carry_no_alert_config_path():
    cfgs = list(SMOKE_CONFIGS.glob("*.yml"))
    assert cfgs
    bad = [c.name for c in cfgs if "alert_config_path" in c.read_text(encoding="utf-8")]
    assert not bad, bad


HTE_HEX = HTE / "configs" / "htehexreflex.yml"
HTE_LEGACY = HTE / "configs" / "htereflex.yml"


def _load(path):
    return read_config(str(path))


@pytest.mark.parametrize("path", [HTE_HEX])
def test_gate_config_validates(path):
    import types

    from launch import validateConfig

    conf = _load(path)
    pidd = types.SimpleNamespace(
        reqKeys=("host", "port", "group"), codeKeys=("fast", "bokeh", "reflex")
    )
    assert validateConfig(pidd, conf, str(REPO_ROOT)) is True


@pytest.mark.parametrize("path", [HTE_HEX])
def test_gate_config_preflights_clean(path):
    """Each gate config preflights with no findings."""
    assert preflight.preflight_config(str(path)) == []


@pytest.mark.parametrize("path", [HTE_HEX])
def test_the_reflex_key_still_names_the_bundle_not_a_module(path):
    """The rejected alternative, pinned. `reflex:`'s value is read by
    `resolve_bundle`/`build_reflex_bundle.py` as a directory name; making it a
    module path would break the bundle contract and all tracked configs."""
    import reflex_bundle

    assert _load(path)["servers"]["UI"]["reflex"] == reflex_bundle.APP_NAME


@pytest.mark.parametrize("path", [HTE_HEX])
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


@pytest.mark.parametrize("path", [HTE_HEX, HTE_LEGACY])
def test_the_hte_pair_carries_the_panel_sources_too(path):
    """Same rendering-gate requirement for the hte dev pair, whose panels are
    the hte ones resolved from `live_vis`/`action_vis` (the sources are the
    test deployment's simulators pointed at hte column names)."""
    servers = _load(path)["servers"]
    assert servers["CO2SENSOR"]["live_vis"] == "co2_vis"
    assert servers["GAMRY"]["action_vis"] == "gamry_vis"
    assert servers["UI"]["params"]["pages"] == ["live", "action"]
