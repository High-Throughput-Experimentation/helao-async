"""Offline preflight validator for a config's servers (spec §8.3; B7c re-scope).

Static gates that must pass BEFORE a config is launched at a station, with no
server launch and no hardware:

1. **config sanity** -- unique server keys, unique host:port, exactly one of
   `fast`/`bokeh`/`reflex` per server (the launcher's cross-cutting rule).
   A `reflex:` server occupies TWO consecutive ports (static frontend, then
   backend), so the uniqueness check reserves `port + 1` for it as well.
2. **module resolution** -- every `fast:`/`bokeh:` module resolves, the way the
   launcher resolves it, to exactly one `servers/<group>/<module>.py`. Zero
   matches, an explicit `deployment:` without the module, or a module that sits
   in several deployments none of which is the config's own (the launcher would
   take sorted order and only warn) are issues. Retired hexagon routing keys are
   issues too (D-B7c.2). A `reflex:` server names a bundle, not a module, and is
   skipped.
3. **endpoint-checklist presence** -- an action server's frozen endpoint
   checklist is looked up in its OWNING deployment (the one gate 2 resolved).
   Fails only when a checklist frozen at B7c's base (`CHECKLISTS_AT_B7C`) is gone;
   any other absence is reported as a note.
4. **library collision** -- the config's `experiment_libraries` +
   `sequence_libraries` lists carry no flat-namespace function-name collision
   (spec §4.3.12), unless `allow_shadow: true` is set on the config.

The runtime cross-check (launch each server, diff its live `/openapi.json`
against the frozen checklist) is NOT done here; this validator is the offline
half.

Usage: ``python -m helao.hexagon.preflight <config_prefix_or_path>`` -- exits 0
with "PREFLIGHT OK" or 1 listing the issues.
"""

from __future__ import annotations

import ast
import os
import sys
from collections import defaultdict
from glob import glob
from pathlib import Path
from typing import Optional

from helao.helpers.config_loader import read_config

#: The launcher's server code keys, pinned to ``launch.py``'s ``codeKeys``. A
#: config is validated against the SAME set the launcher will accept, so a
#: preflight pass cannot be followed by a launcher rejection (or, worse, by a
#: server the launcher silently SKIPS because its key is unrecognized).
#: ``test_code_keys_match_the_launcher`` reads launch.py's tuple and asserts
#: agreement rather than trusting this copy.
CODE_KEYS = ("fast", "bokeh", "reflex")

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKLIST_ROOT = REPO_ROOT / "helao" / "hexagon" / "tests" / "checklists"
HTE_EXP = REPO_ROOT / "helao" / "deploy" / "hte" / "experiments"
HTE_SEQ = REPO_ROOT / "helao" / "deploy" / "hte" / "sequences"
# hte's canary configs (P3a/P3e) were relocated here, OUTSIDE helao/deploy/hte/
# entirely, so they no longer carry "deploy"/"hte" in their path -- see the
# fallback in _config_deployment below.
HTE_SMOKE_CONFIGS = REPO_ROOT / "helao" / "hexagon" / "tests" / "smoke" / "configs"


def _config_deployment(config: str) -> Optional[str]:
    """The source deployment a config lives under (helao/deploy/<dep>/configs/).

    Feeds gate 4 (library collisions); gate 3 uses the owner gate 2 resolved. Returns None
    if the config is passed as a bare prefix that resolves ambiguously or the
    path shape is unexpected.
    """
    matches = sorted((REPO_ROOT / "helao" / "deploy").glob(f"*/configs/{config}.*"))
    if not matches and (Path(config).exists()):
        matches = [Path(config).resolve()]
    for m in matches:
        parts = m.parts
        if "deploy" in parts:
            i = parts.index("deploy")
            if i + 1 < len(parts):
                return parts[i + 1]
        # Relocated hte canary config: lives under HTE_SMOKE_CONFIGS instead
        # of helao/deploy/hte/configs/, so "deploy" never appears in its path.
        # Every config under this centralized, hte-only directory belongs to
        # "hte" by construction (P3a/P3e relocation) -- infer it directly so
        # gate 4's deployment-first library lookup isn't skipped post-move.
        if m.parent == HTE_SMOKE_CONFIGS:
            return "hte"
    return None


def _server_module(server: dict) -> Optional[str]:
    """The fast/bokeh module basename for a server block, or None."""
    return server.get("fast") or server.get("bokeh")


def _checklist_dir(deployment: Optional[str]) -> Optional[Path]:
    """Where a deployment's frozen endpoint checklists live.

    A PRIVATE nested deployment keeps its checklists INSIDE its own repo
    (helao/deploy/<dep>/tests/checklists/) — the public parent cannot host a
    directory named after a private deployment. The public deployments (hte,
    test) keep theirs centrally under helao/hexagon/tests/checklists/<dep>/.
    Prefer the in-repo location when it exists, else the central one; the path
    is BUILT from the resolved deployment at runtime, so this parent source
    names nothing private.
    """
    if not deployment:
        return None
    in_repo = REPO_ROOT / "helao" / "deploy" / deployment / "tests" / "checklists"
    if in_repo.exists():
        return in_repo
    central = CHECKLIST_ROOT / deployment
    return central if central.exists() else None


#: Label suffixes for a server's SECONDARY port claims -- ones that appear
#: nowhere in the config as their own key, so a collision message must name
#: WHICH invisible claim it is or it reads as a plain typo.
_REFLEX_BACKEND_LABEL = "reflex backend port, port + 1"
_ALIGNER_BOKEH_LABEL = "aligner Bokeh port, params.bokeh_port or port + 1000"


def aligner_bokeh_port(server_cfg: dict) -> int:
    """Bokeh port of a server's plate aligner: ``params.bokeh_port`` when set
    (not ``None``), else ``server_cfg['port'] + 1000``. A null value counts as
    unset, which ``dict.get(key, default)`` would not."""
    port = (server_cfg.get("params") or {}).get("bokeh_port")
    return int(int(server_cfg["port"]) + 1000 if port is None else port)


def _aligner_port(server: dict) -> Optional[int]:
    """The extra Bokeh-aligner port a server claims, or ``None``.

    Any server whose ``params.enable_aligner`` is truthy hosts a second Bokeh
    server for the plate aligner (``GalilAlignerHost`` and a private
    deployment's equivalent both share this contract) on ``params.bokeh_port`` when set,
    else ``server['port'] + 1000`` -- the fallback every aligner-host
    implementation falls back to (spec §8.3(3d), §9.2 item 6: a station has
    already shipped a control panel on the port a Galil aligner bound). The
    IMPLICIT default is reserved too, not just an explicit ``bokeh_port``
    key: it is the more invisible of the two shapes -- nothing in the config
    names it at all -- and every tracked config that sets ``enable_aligner``
    today writes ``bokeh_port`` explicitly anyway, so this costs nothing on
    the configs that exist and closes the gap for the ones that don't.
    """
    params = server.get("params") or {}
    if not params.get("enable_aligner"):
        return None
    port = server.get("port")
    if port is None:
        return None
    return aligner_bokeh_port(server)


def _claimed_addresses(server: dict) -> list[tuple[str, str]]:
    """(address, label) pairs one server entry claims.

    ``label`` is ``""`` for the server's own ``host:port`` (an ordinary
    collision there already reads fine unlabeled); a SECONDARY claim gets a
    label identifying which invisible claim it is.
    """
    host, port = server.get("host"), server.get("port")
    claims = [(f"{host}:{port}", "")]
    # A missing/garbage port is reported by the required-keys check; deriving a
    # secondary claim from it would crash here instead, so skip it — same guard
    # `_aligner_port` already applies.
    if server.get("reflex") and port is not None:
        claims.append((f"{host}:{int(port) + 1}", _REFLEX_BACKEND_LABEL))
    aligner_port = _aligner_port(server)
    if aligner_port is not None:
        claims.append((f"{host}:{aligner_port}", _ALIGNER_BOKEH_LABEL))
    return claims


def _config_sanity(servers: dict) -> list[str]:
    issues: list[str] = []
    #: "host:port" -> (server key, label) that claimed it. A reflex server
    #: claims two addresses and an aligner-hosting server claims two more;
    #: none of the SECOND ones appear anywhere in the config as their own
    #: key -- which is exactly why they have to be reserved here: a station
    #: has already shipped a control panel on a port the Galil aligner binds,
    #: invisible to a per-entry check.
    claimed: dict[str, tuple[str, str]] = {}
    for key, s in servers.items():
        declared = [k for k in CODE_KEYS if k in s]
        if len(declared) != 1:
            issues.append(
                f"{key}: must declare exactly one of {'/'.join(CODE_KEYS)}"
                + (f" (declares {'+'.join(declared)})" if declared else "")
            )
        if s.get("host") is None or s.get("port") is None:
            issues.append(f"{key}: missing host/port")
            continue
        for addr, label in _claimed_addresses(s):
            if addr in claimed:
                owner, owner_label = claimed[addr]
                detail = f"{key}: {addr} collides with {owner}"
                # Name the invisible claim explicitly, or the message reads as a
                # config typo when in fact one of the two entries never wrote
                # that port down.
                if label:
                    detail += f" ({key}'s {label})"
                elif owner_label:
                    detail += f" ({owner}'s {owner_label})"
                issues.append(detail)
            else:
                claimed[addr] = (key, label)
    return issues


DEPLOY_ROOT = REPO_ROOT / "helao" / "deploy"

#: B7c's config rule, cited by every gate-2 message about a retired key.
_RULE = (
    "rule D-B7c.2 in docs/config-schema.md: name the module itself in fast:/bokeh:, "
    "and add deployment: <owner> only where preflight reports the module ambiguous"
)
#: The retired routing deployment; matched only to reject it.
_RETIRED_DEPLOYMENT = "hexagon"

#: E4: the per-server hte checklists tracked at 7592729b. Gate 3 fails only when one
#: of these goes missing; any other absent checklist is reported.
CHECKLISTS_AT_B7C: dict[str, frozenset[str]] = {
    "hte": frozenset(
        {
            "HTEdata_server",
            "analysis_server",
            "andor_server",
            "biologic_server",
            "calc_server",
            "cam_server",
            "co2sensor_server",
            "diapump_server",
            "galil_io",
            "galil_motion",
            "gamry_server2",
            "kinesis_server",
            "mfc_server",
            "nidaqmx_server",
            "o2sensor_server",
            "pal_server",
            "pdu_server",
            "power_supply_server",
            "sample_server",
            "spec_server",
            "sync_server",
            "syringe_server",
            "tec_server",
        }
    ),
}


def _launcher_deployment(config_path: str, group: str, module: str):
    """fast_launcher.py:102-152's auto-detection, with its own string operations.

    Returns ``(deployment or None, candidate deployments)``. ``None`` with candidates
    means ambiguous: more than one deployment has the module, none is the config's own,
    and the launcher would take the first in sorted order (and only warn).
    The glob root is the config's great-grandparent, as in the launcher: for a smoke
    config that root holds no deployments, so every smoke entry needs deployment:.
    """
    search = os.path.dirname(os.path.dirname(os.path.dirname(config_path)))
    found = sorted(glob(os.path.join(search, "*", "servers", group, f"{module}.py")))
    deps = [
        os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(p))))
        for p in found
    ]
    if len(found) == 1:
        return deps[0], deps
    own_dir = os.path.dirname(os.path.dirname(config_path))
    own = [d for p, d in zip(found, deps) if p.startswith(own_dir)]
    return (own[0] if own else None), deps


def _module_resolution(cfg: dict, deploy_root: Path = DEPLOY_ROOT):
    """Gate 2: every fast:/bokeh: resolves to exactly one module on disk (D-B7c.5/6).

    Returns ``(issues, resolved)``; ``resolved`` maps server key to the deployment the
    launcher will import its module from. A reflex: server names a bundle, not a module,
    and is skipped. Retired hexagon routing keys are issues (D-B7c.2).
    """
    issues: list[str] = []
    resolved: dict[str, str] = {}
    config_path = str(cfg.get("loaded_config_path") or "")
    for key, s in (cfg.get("servers") or {}).items():
        retired = []
        if "legacy_module" in s:
            retired.append("`legacy_module:`")
        if s.get("deployment") == _RETIRED_DEPLOYMENT:
            retired.append("`deployment: hexagon`")
        if "graft" in (s.get("fast"), s.get("bokeh")):
            retired.append("a `graft` code key")
        if retired:
            issues.append(
                f"{key}: {', '.join(retired)} is retired hexagon routing; {_RULE}"
            )
            continue
        module, group = _server_module(s), s.get("group")
        if not module:
            continue
        if not group:
            issues.append(f"{key}: no group:, so its module cannot be resolved")
            continue
        if "deployment" in s:
            explicit = s["deployment"]
            if not explicit:
                issues.append(
                    f"{key}: deployment: is blank; the launcher tests key presence "
                    f"and would import a deployment named {explicit!r}"
                )
                continue
            if (deploy_root / explicit / "servers" / group / f"{module}.py").is_file():
                resolved[key] = explicit
            else:
                issues.append(
                    f"{key}: deployment: {explicit} has no servers/{group}/{module}.py"
                )
            continue
        dep, found = _launcher_deployment(config_path, group, module)
        if dep:
            resolved[key] = dep
        elif not found:
            issues.append(
                f"{key}: {group}/{module}.py exists in no deployment the launcher searches"
            )
        else:
            issues.append(
                f"{key}: {group}/{module}.py exists in {found}, none of them this config's "
                f"own, so the launcher would pick '{found[0]}' by sorted order; add "
                f"deployment: <owner>"
            )
    return issues, resolved


def _checklist_presence(servers: dict, resolved: dict) -> tuple[list[str], list[str]]:
    """Gate 3 (Q15): look up the OWNING deployment's checklist only. Fail only when a
    checklist frozen at B7c's base is gone; report every other absence."""
    issues: list[str] = []
    notes: list[str] = []
    for key, s in servers.items():
        if s.get("group") != "action" or key not in resolved:
            continue
        module, owner = _server_module(s), resolved[key]
        cdir = _checklist_dir(owner)
        if cdir is not None and (cdir / f"{module}.json").exists():
            continue
        if cdir is not None and module in CHECKLISTS_AT_B7C.get(owner, frozenset()):
            issues.append(
                f"{key}: frozen endpoint checklist {module}.json is gone from {cdir}"
            )
        else:
            notes.append(f"no checklist: {key} ({owner}/{module})")
    return issues, notes


def _lib_module_path(
    entry: str, default_dir: Path, deployment: Optional[str] = None
) -> Optional[Path]:
    """Resolve a library list entry (bare name or repo-relative path) to a file.

    Bare names resolve the way `helao.helpers.import_autolibs` does at runtime:
    the config's own deployment first, then the `hte` fallback. Without the
    deployment leg, a config whose libraries live only in its own deployment
    resolves to None here and is silently skipped by the collision check --
    the gate reads as passing while checking nothing.
    """
    if entry.endswith(".py") or "/" in entry:
        p = (REPO_ROOT / entry) if not Path(entry).is_absolute() else Path(entry)
        return p if p.exists() else None
    if deployment:
        p = (
            REPO_ROOT
            / "helao"
            / "deploy"
            / deployment
            / default_dir.name
            / f"{entry}.py"
        )
        if p.exists():
            return p
    p = default_dir / f"{entry}.py"
    return p if p.exists() else None


def _top_level_funcs(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _library_collisions(cfg: dict, deployment: Optional[str] = None) -> list[str]:
    if cfg.get("allow_shadow"):
        return []
    issues: list[str] = []
    for cfg_key, default_dir in (
        ("experiment_libraries", HTE_EXP),
        ("sequence_libraries", HTE_SEQ),
    ):
        name_to_mods: dict[str, list[str]] = defaultdict(list)
        for entry in cfg.get(cfg_key, []) or []:
            path = _lib_module_path(str(entry), default_dir, deployment)
            if path is None:
                continue
            for fn in _top_level_funcs(path):
                name_to_mods[fn].append(path.name)
        for fn, mods in sorted(name_to_mods.items()):
            if len(mods) >= 2:
                issues.append(
                    f"{cfg_key}: '{fn}' defined in {mods} (flat-namespace "
                    f"collision; set allow_shadow: true to override)"
                )
    return issues


def preflight_report(config: str) -> tuple[list[str], list[str], dict]:
    """``(issues, notes, resolved)`` for a config prefix or path."""
    cfg = read_config(config)
    servers = cfg.get("servers", {})
    issues = _config_sanity(servers)
    gate2, resolved = _module_resolution(cfg)
    gate3, notes = _checklist_presence(servers, resolved)
    issues += gate2 + gate3 + _library_collisions(cfg, _config_deployment(config))
    return issues, notes, resolved


def preflight_config(config: str) -> list[str]:
    """Return a list of preflight issues for a config prefix/path (empty = pass)."""
    return preflight_report(config)[0]


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print("usage: python -m helao.hexagon.preflight <config_prefix_or_path>")
        return 2
    issues, notes, resolved = preflight_report(argv[0])
    if not issues:
        print(f"PREFLIGHT OK: {argv[0]} (resolved {len(resolved)} server(s))")
    else:
        print(f"PREFLIGHT FAILED: {argv[0]} ({len(issues)} issue(s))")
        for i in issues:
            print(f"  - {i}")
    for n in notes:
        print(f"  - {n}")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
