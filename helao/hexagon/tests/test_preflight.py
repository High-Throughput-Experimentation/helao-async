"""P3e — offline preflight validator tests (spec §8.3)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from helao.hexagon import preflight

# hte canary configs (P3a/P3e) were relocated out of helao/deploy/hte/configs/
# into this centralized, hte-only directory; bare-prefix resolution (which
# globs helao/deploy/*/configs/) no longer finds them, so they must be passed
# by full path.
SMOKE_CONFIGS = preflight.HTE_SMOKE_CONFIGS

#: A server block declaring the hexagon deployment, in either config dialect:
#: `deployment: hexagon` in YAML, `"deployment": "hexagon"` in a .py config.
_DECLARES_HEXAGON = re.compile(
    r"""["']?deployment["']?\s*[:=]\s*["']?%s\b""" % preflight.HEXAGON
)

#: Config suffixes `read_config` accepts.
_CONFIG_SUFFIXES = (".yml", ".py")


def _hexagon_configs() -> list[Path]:
    """Every config in the tree that flips at least one server to hexagon.

    DERIVED, not hand-listed: a hand list silently misses the next config
    added, which is the failure mode this pin exists to prevent. Two roots,
    because the hexagon configs live in two places -- the per-deployment
    `configs/` directories, and the centralized hte smoke directory the P3a/P3e
    canaries were relocated into (which is outside helao/deploy/ entirely).

    Selection is by TEXT MATCH, deliberately: a `.py` config is executed by
    `read_config`, and one belonging to an unrelated deployment can fail to
    import on this platform (a Windows-only vendor SDK at module scope). That
    must not turn "which configs exist" into a collection error for everyone
    else. Loading is left to the preflight run itself, on the selected set.
    """
    candidates = sorted((preflight.REPO_ROOT / "helao" / "deploy").glob("*/configs/*"))
    candidates += sorted(SMOKE_CONFIGS.glob("*"))
    return [
        p
        for p in candidates
        if p.is_file()
        and p.suffix in _CONFIG_SUFFIXES
        and p.name != "__init__.py"
        and _DECLARES_HEXAGON.search(p.read_text(errors="ignore"))
    ]


#: Hexagon configs whose presence in the derived set is itself asserted. An
#: inert glob (wrong root, renamed directory, regex drift) yields an empty
#: parametrization, which pytest reports as PASSED -- so the derivation needs a
#: floor it cannot pass without. Named by phase: P2's four, P7e's graft, P7f's
#: Reflex flip, P7k's hte Reflex flip, and the two hte canaries.
KNOWN_HEXAGON_CONFIGS = frozenset(
    {
        "goldenhex",
        "goldenhexvis",
        "goldenhexid",
        "goldenhexconc",
        "goldenhexgraft",
        "goldenhexreflex",
        "htehexreflex",
        "gamryhex",
        "samplegraft",
    }
)


def test_gamryhex_canary_passes():
    """The hte hexagon canary config passes every offline gate."""
    assert preflight.preflight_config(str(SMOKE_CONFIGS / "gamryhex.yml")) == []


def test_the_derived_hexagon_config_set_is_not_vacuous():
    """The guard on the guard: an empty derived set parametrizes to nothing
    and reports green. Assert both that it found something and that it found
    the configs we know exist."""
    stems = {p.stem for p in _hexagon_configs()}
    assert stems, "no hexagon configs discovered — the glob is inert"
    assert KNOWN_HEXAGON_CONFIGS <= stems, sorted(KNOWN_HEXAGON_CONFIGS - stems)


@pytest.mark.parametrize("config", _hexagon_configs(), ids=lambda p: p.stem)
def test_every_hexagon_config_in_the_tree_preflights(config):
    """Every tracked hexagon-variant config passes every offline gate.

    Covers P2's goldenhex family, P7e's generic graft, P7f's `goldenhexreflex`
    and P7k's `htehexreflex`, and each per-family canary — and, on a checkout
    that has them, any private deployment's hexagon configs, without this
    public file naming one.
    """
    assert preflight.preflight_config(str(config)) == [], config.name


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


def _hexagon_reflex_server():
    return {
        "UI": {
            "host": "127.0.0.1",
            "port": 5010,
            "group": "visualizer",
            "reflex": "helao_ui",
            "deployment": "hexagon",
        }
    }


def test_reflex_server_may_be_hexagon_hosted():
    """P7f lifts the D9 rejection this test used to pin.

    Until P7f a `reflex:` server declaring `deployment: hexagon` was rejected
    outright ("there is no hexagon UI shim to find"). It is now the supported
    flip, and it is checked like any other hexagon server: nothing missing,
    and in particular NOT reported as a missing group/module -- there is no
    `servers/<group>/<module>.py` for a reflex server to have.
    """
    assert preflight._shim_completeness(_hexagon_reflex_server()) == []


def test_hexagon_reflex_routing_target_is_resolved_to_a_file():
    """Presence of the key is a weak gate; the module it routes to is the
    real precondition. The launcher imports it in-process (for the
    loaded-modules snapshot and the bundle stamp) and the backend child
    imports it again, so an absent module is a launch-time
    ModuleNotFoundError in two processes -- exactly what an offline gate is
    for. Mirrors `_graft_target_issues`, path resolution and all.
    """
    dotted = preflight._hexagon_reflex_app_module()
    target = preflight.REPO_ROOT.joinpath(*dotted.split("."))
    assert target.with_suffix(".py").exists(), target

    # and the check is not vacuous: point it at a module that does not exist
    # and the same config becomes a finding naming it.
    original = preflight._hexagon_reflex_app_module
    preflight._hexagon_reflex_app_module = lambda: "helao.hexagon.app.no_such_host"
    try:
        issues = preflight._shim_completeness(_hexagon_reflex_server())
    finally:
        preflight._hexagon_reflex_app_module = original
    assert len(issues) == 1
    assert "no_such_host" in issues[0]
    assert "resolves to no module on disk" in issues[0]


def test_preflight_and_the_launcher_agree_on_the_routing_target():
    """A preflight that passes while the launcher routes elsewhere is worse
    than no preflight: it certifies a config that cannot start."""
    import reflex_bundle

    assert preflight._hexagon_reflex_app_module() == reflex_bundle.HEXAGON_APP_MODULE
    assert preflight.HEXAGON == reflex_bundle.HEXAGON_DEPLOYMENT
    # ...including the literal behind the ImportError fallback, which the
    # equality above can never reach: it only runs when `reflex_bundle` is not
    # importable, and then there is nothing to compare it against.
    source = open(preflight.__file__, encoding="utf8").read()
    assert f'return "{reflex_bundle.HEXAGON_APP_MODULE}"' in source


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


def test_a_scratch_copy_of_a_config_does_not_exercise_the_checklist_gate(
    tmp_path, monkeypatch
):
    """P4f's silent-pass trap, as a negative control on the pins above.

    `preflight` infers the deployment from the config's PATH, so the very same
    bytes preflight differently depending on where the file sits: in-tree the
    checklist gate runs, in a scratch directory there is no deployment, hence
    no checklist directory, hence nothing checked. Both return `[]`, so the
    result alone cannot tell them apart — which is exactly why a preflight run
    against a copied-out config certifies less than it appears to.

    What is asserted is therefore the DIFFERENCE, measured three ways: the
    inferred deployment, the checklist directory it resolves to, and — the
    consequence that matters — that with the checklist set emptied the in-tree
    config reports a real finding while the scratch copy stays clean.
    """
    src = SMOKE_CONFIGS / "gamryhex.yml"
    scratch = tmp_path / src.name
    shutil.copy2(src, scratch)

    # 1. the deployment, which is the only thing the path carries
    assert preflight._config_deployment(str(src)) == "hte"
    assert preflight._config_deployment(str(scratch)) is None

    # 2. and so the gate has no baseline directory to check against
    assert preflight._checklist_dir(preflight._config_deployment(str(src))) is not None
    assert preflight._checklist_dir(preflight._config_deployment(str(scratch))) is None

    # 3. identical bytes, identical clean result, in-tree and out
    assert preflight.preflight_config(str(src)) == []
    assert preflight.preflight_config(str(scratch)) == []

    # 4. now make the checklist gate bite: point it at an empty (but existing)
    #    hte checklist set, so every hexagon action server is missing its
    #    frozen baseline. The in-tree config notices; the scratch copy cannot.
    empty = tmp_path / "checklists"
    (empty / "hte").mkdir(parents=True)
    monkeypatch.setattr(preflight, "CHECKLIST_ROOT", empty)
    in_tree = preflight.preflight_config(str(src))
    assert len(in_tree) == 1 and "frozen endpoint checklist missing" in in_tree[0]
    assert preflight.preflight_config(str(scratch)) == []
