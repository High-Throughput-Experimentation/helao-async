"""P3e — offline preflight validator tests (spec §8.3)."""

from __future__ import annotations

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
    """P2's hexagon test configs also pass (deployment-aware checklist gate)."""
    for cfg in ("goldenhex", "goldenhexvis", "goldenhexid"):
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


def test_config_sanity_fast_xor_bokeh():
    servers = {"A": {"host": "127.0.0.1", "port": 8001, "fast": "x", "bokeh": "y"}}
    issues = preflight._config_sanity(servers)
    assert any("exactly one of fast/bokeh" in i for i in issues)


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
