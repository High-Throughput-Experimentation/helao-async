"""P3e — offline preflight validator tests (spec §8.3)."""

from __future__ import annotations

import re

import pytest

from helao.hexagon import preflight

# hte canary configs (P3a/P3e) were relocated out of helao/deploy/hte/configs/
# into this centralized, hte-only directory; bare-prefix resolution (which
# globs helao/deploy/*/configs/) no longer finds them, so they must be passed
# by full path.
SMOKE_CONFIGS = preflight.HTE_SMOKE_CONFIGS


def test_gamryhex_canary_passes():
    """The hte hexagon canary config passes every offline gate."""
    assert preflight.preflight_config(str(SMOKE_CONFIGS / "gamryhex.yml")) == []


def test_goldenhex_configs_pass():
    """P2's hexagon test configs also pass (deployment-aware checklist gate);
    goldenhexgraft is P7e's, whose bokeh servers ride the generic graft."""
    for cfg in ("goldenhex", "goldenhexvis", "goldenhexid", "goldenhexgraft"):
        assert preflight.preflight_config(cfg) == [], cfg


def test_missing_shim_detected():
    servers = {
        "PSTAT": {
            "host": "127.0.0.1",
            "port": 8001,
            "group": "action",
            "fast": "no_such_server",
            "deployment": "hexagon",
        }
    }
    issues = preflight._shim_completeness(servers)
    assert any("hexagon shim missing" in i for i in issues)


def test_legacy_server_not_shim_checked():
    """A server without deployment:hexagon is not shim-checked."""
    servers = {
        "PSTAT": {
            "host": "127.0.0.1",
            "port": 8001,
            "group": "action",
            "fast": "no_such_server",
        }
    }
    assert preflight._shim_completeness(servers) == []


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
    src = (preflight.REPO_ROOT / "launch.py").read_text()
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


def test_reflex_server_rejected_as_hexagon_composed():
    """Spec D9: UI hosting is P7-UI, so there is no hexagon shim to find."""
    servers = {
        "UI": {
            "host": "127.0.0.1",
            "port": 5010,
            "group": "visualizer",
            "reflex": "helao_ui",
            "deployment": "hexagon",
        }
    }
    issues = preflight._shim_completeness(servers)
    assert any("not hexagon-composed" in i for i in issues)
    assert not any("missing group/module" in i for i in issues)


def test_library_collision_detected():
    cfg = {
        "experiment_libraries": ["CCSI_exp", "CSIL_exp"],  # share CCSI_sub_* names
    }
    issues = preflight._library_collisions(cfg)
    assert any("collision" in i for i in issues)


def test_library_collision_overridable():
    cfg = {
        "experiment_libraries": ["CCSI_exp", "CSIL_exp"],
        "allow_shadow": True,
    }
    assert preflight._library_collisions(cfg) == []


def test_samplegraft_generic_graft_passes():
    """The generic config-driven graft (fast: graft + legacy_module) passes
    every offline gate — its checklist resolves from the legacy module."""
    assert preflight.preflight_config(str(SMOKE_CONFIGS / "samplegraft.yml")) == []


def _graft_server(code_key, group, **extra):
    srv = {
        "host": "127.0.0.1",
        "port": 8001,
        "group": group,
        code_key: "graft",
        "deployment": "hexagon",
    }
    srv.update(extra)
    return {"G": srv}


@pytest.mark.parametrize(
    "code_key,group",
    [("fast", "action"), ("bokeh", "visualizer"), ("bokeh", "operator")],
)
def test_graft_without_legacy_module_is_a_finding(code_key, group):
    """A generic graft names nothing, so an absent `legacy_module:` leaves it
    with no target at all. It raises only when the launcher calls the factory —
    for a bokeh server, not until the first browser session — so this gate is
    the only place it surfaces before a station notices a blank page."""
    issues = preflight._shim_completeness(_graft_server(code_key, group))
    assert len(issues) == 1, issues
    assert "declares no `legacy_module:`" in issues[0]
    assert f"{code_key}: graft" in issues[0]
    assert f"servers.{group}.<module>" in issues[0]


@pytest.mark.parametrize(
    "code_key,group,legacy",
    [
        ("fast", "action", "helao.deploy.hte.servers.action.sample_server"),
        (
            "bokeh",
            "visualizer",
            "helao.deploy.hte.servers.visualizer.live_visualizer",
        ),
        (
            "bokeh",
            "operator",
            "helao.deploy.hte.servers.operator.standalone_operator",
        ),
    ],
)
def test_graft_with_a_resolvable_legacy_module_passes(code_key, group, legacy):
    assert (
        preflight._shim_completeness(
            _graft_server(code_key, group, legacy_module=legacy)
        )
        == []
    )


def test_graft_with_an_unresolvable_legacy_module_is_a_finding():
    """Presence alone is a weak gate: a typo'd dotted path satisfies it and
    then fails at launch with ModuleNotFoundError. Resolution is by PATH — the
    validator is offline and must not import deployment code."""
    issues = preflight._shim_completeness(
        _graft_server(
            "bokeh", "visualizer", legacy_module="helao.deploy.hte.servers.nope.typo"
        )
    )
    assert len(issues) == 1, issues
    assert "resolves to no module on disk" in issues[0]


def test_explicit_hexagon_shims_are_not_graft_checked():
    """The three explicit vis/operator shims name their target in code, so the
    `legacy_module:` requirement must not fire on them."""
    servers = {
        "OPERATOR": {
            "host": "127.0.0.1",
            "port": 5001,
            "group": "operator",
            "bokeh": "standalone_operator",
            "deployment": "hexagon",
        },
        "LIVE": {
            "host": "127.0.0.1",
            "port": 5002,
            "group": "visualizer",
            "bokeh": "live_visualizer",
            "deployment": "hexagon",
        },
        "ACTVIS": {
            "host": "127.0.0.1",
            "port": 5003,
            "group": "visualizer",
            "bokeh": "action_visualizer",
            "deployment": "hexagon",
        },
    }
    assert preflight._shim_completeness(servers) == []


def test_checklist_module_resolves_graft_from_legacy_module():
    """fast: graft keys its checklist by the legacy_module basename, not by the
    generic shim name 'graft'."""
    graft_srv = {
        "fast": "graft",
        "legacy_module": "helao.deploy.hte.servers.action.sample_server",
    }
    assert preflight._checklist_module(graft_srv) == "sample_server"
    # a graft server missing legacy_module resolves to None (no checklist name)
    assert preflight._checklist_module({"fast": "graft"}) is None
    # ordinary servers still key by their fast/bokeh module
    assert preflight._checklist_module({"fast": "gamry_server2"}) == "gamry_server2"


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
