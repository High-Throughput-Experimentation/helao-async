"""P3e — offline preflight validator tests (spec §8.3)."""

from __future__ import annotations

import re
import shutil

import pytest

from helao.hexagon import preflight
from helao.helpers.config_loader import read_config

# hte canary configs (P3a/P3e) were relocated out of helao/deploy/hte/configs/
# into this centralized, hte-only directory; bare-prefix resolution (which
# globs helao/deploy/*/configs/) no longer finds them, so they must be passed
# by full path.
SMOKE_CONFIGS = preflight.HTE_SMOKE_CONFIGS


def test_config_sanity_duplicate_hostport():
    servers = {
        "A": {"host": "127.0.0.1", "port": 8001, "fast": "x"},
        "B": {"host": "127.0.0.1", "port": 8001, "fast": "y"},
    }
    issues = preflight._config_sanity(servers)
    assert any("collides" in i for i in issues)


def test_config_sanity_exactly_one_code_key():
    """Two code keys on one server, and none at all, both fail."""
    servers = {"A": {"host": "127.0.0.1", "port": 8001, "fast": "x", "bokeh": "y"}}
    issues = preflight._config_sanity(servers)
    assert any("exactly one of fast/bokeh/reflex" in i for i in issues)
    assert any("declares fast+bokeh" in i for i in issues)

    servers = {"A": {"host": "127.0.0.1", "port": 8001, "group": "visualizer"}}
    issues = preflight._config_sanity(servers)
    assert any("exactly one of fast/bokeh/reflex" in i for i in issues)


def test_code_keys_match_the_launcher():
    """preflight.CODE_KEYS is pinned to launch.py's codeKeys by reading it.

    A config must be validated against the same key set the launcher accepts. If
    they drift, a config can preflight clean and then have a server SILENTLY
    SKIPPED at launch (launch.py skips an entry whose key it does not recognize
    rather than failing), which is the worst of both worlds.
    """
    src = (preflight.REPO_ROOT / "launch.py").read_text(encoding="utf-8")
    match = re.search(r"self\.codeKeys\s*=\s*\(([^)]*)\)", src)
    assert match, "could not find codeKeys in launch.py"
    launcher_keys = tuple(
        part.strip().strip("\"'") for part in match.group(1).split(",") if part.strip()
    )
    assert launcher_keys == preflight.CODE_KEYS


def test_reflex_server_is_a_valid_code_key():
    """A reflex UI server passes config sanity (regression: it used to fail).

    'must declare exactly one of fast/bokeh' rejected every config carrying a
    reflex server outright, which blocked the P3e/P4f preflight gate for every
    station that had adopted the Reflex UI.
    """
    servers = {"UI": {"host": "127.0.0.1", "port": 5010, "reflex": "helao_ui"}}
    assert preflight._config_sanity(servers) == []


def test_reflex_backend_port_is_reserved():
    """A reflex server claims port AND port+1; the second collision is named.

    The backend port appears nowhere in the config, so a plain per-entry check
    cannot see the clash -- one station shipped a control panel on a port the
    Galil aligner binds.
    """
    servers = {
        "UI": {"host": "127.0.0.1", "port": 5010, "reflex": "helao_ui"},
        "VIS": {"host": "127.0.0.1", "port": 5011, "bokeh": "live_visualizer"},
    }
    issues = preflight._config_sanity(servers)
    assert any("127.0.0.1:5011" in i and "collides" in i for i in issues)
    assert any("port + 1" in i for i in issues), issues


def test_aligner_explicit_bokeh_port_is_reserved():
    """spec §8.3(3d): an explicit `params.bokeh_port` claim collides visibly.

    A private deployment's station config gives its MOTOR server `params: {enable_aligner: true,
    bokeh_port: 5003}`; nothing before this change reserved that port, so a
    second server on 5003 preflighted clean and only failed at launch
    (`WinError 10048`, documented as a config comment rather than a gate
    finding).
    """
    servers = {
        "MOTOR": {
            "host": "127.0.0.1",
            "port": 4003,
            "fast": "galil_motion",
            "params": {"enable_aligner": True, "bokeh_port": 5003},
        },
        "DATABROWSE": {"host": "127.0.0.1", "port": 5003, "bokeh": "data_browser"},
    }
    issues = preflight._config_sanity(servers)
    assert any("127.0.0.1:5003" in i and "collides" in i for i in issues), issues
    assert any("bokeh_port" in i for i in issues), issues


def test_aligner_implicit_default_bokeh_port_is_reserved():
    """The IMPLICIT default (`port + 1000`) is reserved too, not just an
    explicit `bokeh_port` key -- it is the more invisible of the two shapes:
    nothing in the config names it at all."""
    servers = {
        "MOTOR": {
            "host": "127.0.0.1",
            "port": 4003,
            "fast": "galil_motion",
            "params": {"enable_aligner": True},  # no bokeh_port -> port+1000
        },
        "OTHER": {"host": "127.0.0.1", "port": 5003, "bokeh": "data_browser"},
    }
    issues = preflight._config_sanity(servers)
    assert any("127.0.0.1:5003" in i and "collides" in i for i in issues), issues
    assert any("port + 1000" in i for i in issues), issues


def test_aligner_without_enable_flag_claims_nothing():
    """`bokeh_port` sitting in `params` with no `enable_aligner: true` is not
    a live claim -- the aligner host is never constructed, so nothing binds
    that port and reserving it would be a false positive."""
    servers = {
        "MOTOR": {
            "host": "127.0.0.1",
            "port": 4003,
            "fast": "galil_motion",
            "params": {"bokeh_port": 5003},
        },
        "OTHER": {"host": "127.0.0.1", "port": 5003, "bokeh": "data_browser"},
    }
    assert preflight._config_sanity(servers) == []


def _twin_libraries(tmp_path):
    """Two synthetic experiment libraries that define the same function name."""
    paths = []
    for mod in ("twin_a_exp", "twin_b_exp"):
        p = tmp_path / f"{mod}.py"
        p.write_text("def shared_sub_exp():\n    return []\n", encoding="utf-8")
        paths.append(str(p))
    return paths


def test_library_collision_detected(tmp_path):
    cfg = {"experiment_libraries": _twin_libraries(tmp_path)}
    issues = preflight._library_collisions(cfg)
    assert any("collision" in i and "shared_sub_exp" in i for i in issues)


def test_library_collision_overridable(tmp_path):
    cfg = {
        "experiment_libraries": _twin_libraries(tmp_path),
        "allow_shadow": True,
    }
    assert preflight._library_collisions(cfg) == []


def _synthetic_tree(tmp_path, own_has_module=False):
    """helao/deploy/{alpha,beta}/servers/action/twin_server.py, and a config under own/."""
    deploy = tmp_path / "helao" / "deploy"
    deps = ["alpha", "beta"] + (["own"] if own_has_module else [])
    for dep in deps:
        p = deploy / dep / "servers" / "action"
        p.mkdir(parents=True)
        (p / "twin_server.py").write_text("", encoding="utf-8")
    (deploy / "own" / "configs").mkdir(parents=True, exist_ok=True)
    return deploy, deploy / "own" / "configs" / "synthetic.yml"


def _one_server_cfg(cfg_path, **entry):
    server = {
        "host": "127.0.0.1",
        "port": 8001,
        "group": "action",
        "fast": "twin_server",
    }
    server.update(entry)
    return {"loaded_config_path": str(cfg_path), "servers": {"TWIN": server}}


def test_a_module_in_two_foreign_deployments_is_ambiguous(tmp_path):
    """D-B7c.5: the launcher would take sorted order and warn; preflight refuses."""
    deploy, cfg_path = _synthetic_tree(tmp_path)
    issues, resolved = preflight._module_resolution(_one_server_cfg(cfg_path), deploy)
    assert resolved == {}
    assert len(issues) == 1 and "['alpha', 'beta']" in issues[0], issues


def test_an_explicit_deployment_clears_the_ambiguity(tmp_path):
    deploy, cfg_path = _synthetic_tree(tmp_path)
    cfg = _one_server_cfg(cfg_path, deployment="beta")
    assert preflight._module_resolution(cfg, deploy) == ([], {"TWIN": "beta"})


def test_an_explicit_deployment_without_the_module_is_an_issue(tmp_path):
    deploy, cfg_path = _synthetic_tree(tmp_path)
    issues, resolved = preflight._module_resolution(
        _one_server_cfg(cfg_path, deployment="gamma"), deploy
    )
    assert resolved == {} and len(issues) == 1 and "gamma" in issues[0], issues


def test_the_config_s_own_deployment_wins_without_a_key(tmp_path):
    deploy, cfg_path = _synthetic_tree(tmp_path, own_has_module=True)
    assert preflight._module_resolution(_one_server_cfg(cfg_path), deploy) == (
        [],
        {"TWIN": "own"},
    )


def test_a_module_in_no_deployment_is_an_issue(tmp_path):
    deploy, cfg_path = _synthetic_tree(tmp_path)
    issues, resolved = preflight._module_resolution(
        _one_server_cfg(cfg_path, fast="no_such_server"), deploy
    )
    assert resolved == {} and len(issues) == 1 and "no deployment" in issues[0], issues


@pytest.mark.parametrize("blank", [None, ""], ids=["null", "empty"])
def test_a_blank_deployment_key_is_an_issue(tmp_path, blank):
    """The launcher tests key presence, so a blank value would crash it at import."""
    deploy, cfg_path = _synthetic_tree(tmp_path, own_has_module=True)
    issues, resolved = preflight._module_resolution(
        _one_server_cfg(cfg_path, deployment=blank), deploy
    )
    assert resolved == {} and len(issues) == 1 and "blank" in issues[0], issues


def test_a_scratch_config_without_a_deployment_key_fails_gate_2(tmp_path):
    """Outside helao/deploy nothing resolves implicitly: the failure is loud."""
    deploy, _ = _synthetic_tree(tmp_path)
    cfg_path = tmp_path / "scratch.yml"
    issues, resolved = preflight._module_resolution(_one_server_cfg(cfg_path), deploy)
    assert resolved == {} and len(issues) == 1 and "no deployment" in issues[0], issues


@pytest.mark.parametrize(
    "entry",
    [
        {"legacy_module": "helao.deploy.alpha.servers.action.twin_server"},
        {"deployment": "hexagon"},
        {"fast": "graft"},
    ],
    ids=["legacy_module", "deployment_hexagon", "graft"],
)
def test_retired_routing_keys_are_issues_that_cite_the_rule(tmp_path, entry):
    deploy, cfg_path = _synthetic_tree(tmp_path)
    issues, _ = preflight._module_resolution(_one_server_cfg(cfg_path, **entry), deploy)
    assert len(issues) == 1 and "D-B7c.2" in issues[0], issues


def test_a_missing_checklist_is_reported_not_failed():
    servers = {"SIM": {"group": "action", "fast": "ws_simulator"}}
    issues, notes = preflight._checklist_presence(servers, {"SIM": "test"})
    assert issues == [] and notes == ["no checklist: SIM (test/ws_simulator)"]


def test_a_checklist_that_existed_at_b7c_and_is_gone_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "_checklist_dir", lambda dep: tmp_path)
    servers = {"GAMRY": {"group": "action", "fast": "gamry_server2"}}
    issues, notes = preflight._checklist_presence(servers, {"GAMRY": "hte"})
    assert len(issues) == 1 and "gamry_server2" in issues[0] and notes == []


KNOWN_STATION_CONFIGS = [
    "adss3",
    "anec",
    "ccsi2",
    "clad",
    "eche10",
    "ecms3",
    "hispec",
    "test",
]


@pytest.mark.parametrize("prefix", KNOWN_STATION_CONFIGS)
def test_every_station_config_preflights_with_resolved_servers(prefix, capsys):
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


#: Deployments whose checklists live centrally, and which this public repo may
#: name because it tracks them.
PUBLIC_DEPLOYMENTS = ("hte", "test")


def _a_nested_deployment_with_checklists() -> str | None:
    """Name of any nested deployment holding in-repo checklists, else ``None``.

    Discovered at runtime rather than hardcoded, for the same reason
    ``preflight._checklist_dir`` builds its path from its argument: this repo is
    public and must not name the private deployments nested in-tree. It also
    makes the test honest on a machine where a different set of them (or none)
    is checked out.
    """
    deploy_root = preflight.REPO_ROOT / "helao" / "deploy"
    if not deploy_root.is_dir():
        return None
    for candidate in sorted(deploy_root.iterdir()):
        if not candidate.is_dir() or candidate.name in PUBLIC_DEPLOYMENTS:
            continue
        if (candidate / "tests" / "checklists").is_dir():
            return candidate.name
    return None


def test_checklist_dir_prefers_private_in_repo_then_central():
    """A nested deployment's checklists live in its own repo
    (helao/deploy/<dep>/tests/checklists); hte/test use the central
    helao/hexagon/tests/checklists/<dep>. Unknown/None -> None."""
    hte = preflight._checklist_dir("hte")
    assert hte is not None and hte.parts[-3:] == ("tests", "checklists", "hte")
    assert "hexagon" in hte.parts  # central location

    nested = _a_nested_deployment_with_checklists()
    if nested is not None:  # only when such a nested repo is checked out
        found = preflight._checklist_dir(nested)
        assert found is not None
        assert found.parts[-3:] == (nested, "tests", "checklists")
        assert "deploy" in found.parts and "hexagon" not in found.parts  # in-repo

    assert preflight._checklist_dir(None) is None
    assert preflight._checklist_dir("no_such_deployment") is None


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
    (empty / "hte").mkdir(parents=True)
    monkeypatch.setattr(preflight, "CHECKLIST_ROOT", empty)
    for config in (src, scratch):
        found = preflight.preflight_config(str(config))
        assert len(found) == 1 and "frozen endpoint checklist" in found[0], found


def test_claimed_addresses_agrees_with_the_launcher_on_reflex():
    """Two implementations of "what does this server claim" now exist.

    `launch.py` reserves addresses via `reflex.discovery.reserved_addresses`;
    preflight computes its own claims so it can add the aligner's invisible
    Bokeh port, which the launcher does not know about. Nothing forces the two
    to agree, and a preflight that under-reserves relative to the launcher would
    pass a config the launcher then rejects. Pin the overlap: on the reflex
    claim they must be identical.
    """
    from helao.ui.shared.discovery import reserved_addresses

    for server in (
        {"host": "127.0.0.1", "port": 5010, "reflex": "helao_ui"},
        {"host": "127.0.0.1", "port": 5010},  # no reflex -> own address only
    ):
        launcher = set(reserved_addresses(server))
        ours = {addr for addr, _ in preflight._claimed_addresses(server)}
        assert ours == launcher, (server, sorted(ours), sorted(launcher))


def test_claimed_addresses_survives_a_port_less_entry():
    """A config missing `port` is reported by the required-keys check; deriving
    a secondary claim from it must not crash the sanity pass first."""
    claims = preflight._claimed_addresses({"host": "127.0.0.1", "reflex": "helao_ui"})
    assert [label for _, label in claims] == [""]
