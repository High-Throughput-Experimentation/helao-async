"""P3e — offline preflight validator tests (spec §8.3)."""

from __future__ import annotations

import re

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


def test_aligner_explicit_bokeh_port_is_reserved():
    """spec §8.3(3d): an explicit `params.bokeh_port` claim collides visibly.

    `uvis4.yml`'s MOTOR server carries `params: {enable_aligner: true,
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


def test_claimed_addresses_agrees_with_the_launcher_on_reflex():
    """Two implementations of "what does this server claim" now exist.

    `launch.py` reserves addresses via `reflex.discovery.reserved_addresses`;
    preflight computes its own claims so it can add the aligner's invisible
    Bokeh port, which the launcher does not know about. Nothing forces the two
    to agree, and a preflight that under-reserves relative to the launcher would
    pass a config the launcher then rejects. Pin the overlap: on the reflex
    claim they must be identical.
    """
    from helao.core.servers.reflex.discovery import reserved_addresses

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
