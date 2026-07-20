"""P3e — offline preflight validator for hexagon-composed configs (spec §8.3).

Runs the hexagon-specific static gates that must pass BEFORE a config's
`deployment: hexagon` servers are launched at a station — with disconnected
adapters, on Linux, no server launch and no hardware:

1. **config sanity** — unique server keys, unique host:port, exactly one of
   `fast`/`bokeh` per server (the launcher's cross-cutting rule).
2. **shim completeness** — every `deployment: hexagon` server has a hexagon
   shim module at `helao/deploy/hexagon/servers/<group>/<fast|bokeh>.py`
   (missing shim = `ModuleNotFoundError` at launch — must be caught here).
3. **endpoint-checklist presence** — every hexagon ACTION server has a frozen
   legacy endpoint checklist under `helao/hexagon/tests/checklists/hte/` (the
   baseline the runtime `/openapi.json` diff is checked against at station).
4. **library collision** — the config's `experiment_libraries` +
   `sequence_libraries` lists carry no flat-namespace function-name collision
   (spec §4.3.12), unless `allow_shadow: true` is set on the config.

The runtime cross-check (§8.3(2): launch each hexagon server, diff its live
`/openapi.json` against the frozen checklist) is NOT done here — it needs a
launch, which for hte is an at-station step (only the sim `gamryhex` config is
Linux-launchable). This validator is the offline half.

Usage: ``python -m helao.hexagon.preflight <config_prefix_or_path>`` — exits 0
with "PREFLIGHT OK" or 1 listing the issues.
"""

from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

from helao.helpers.config_loader import read_config

REPO_ROOT = Path(__file__).resolve().parents[2]
HEXAGON_SERVERS = REPO_ROOT / "helao" / "deploy" / "hexagon" / "servers"
CHECKLIST_ROOT = REPO_ROOT / "helao" / "hexagon" / "tests" / "checklists"
HTE_EXP = REPO_ROOT / "helao" / "deploy" / "hte" / "experiments"
HTE_SEQ = REPO_ROOT / "helao" / "deploy" / "hte" / "sequences"

HEXAGON = "hexagon"


def _config_deployment(config: str) -> Optional[str]:
    """The source deployment a config lives under (helao/deploy/<dep>/configs/).

    Used to locate the per-deployment frozen endpoint checklists. Returns None
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
    return None


def _server_module(server: dict) -> Optional[str]:
    """The fast/bokeh module basename for a server block, or None."""
    return server.get("fast") or server.get("bokeh")


def _checklist_module(server: dict) -> Optional[str]:
    """The module a server's endpoint checklist is keyed by.

    Normally the `fast`/`bokeh` module basename, but a `fast: graft` server
    (the generic config-driven hexagon graft, helao/deploy/hexagon/servers/
    action/graft.py) wraps the module named by its top-level `legacy_module:`
    key, so its checklist is keyed by that legacy module's basename, not by the
    generic shim name "graft".
    """
    module = _server_module(server)
    if module == "graft":
        legacy = server.get("legacy_module")
        return legacy.rsplit(".", 1)[-1] if legacy else None
    return module


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


def _config_sanity(servers: dict) -> list[str]:
    issues: list[str] = []
    hostports: dict[tuple, str] = {}
    for key, s in servers.items():
        has_fast, has_bokeh = "fast" in s, "bokeh" in s
        if has_fast == has_bokeh:
            issues.append(f"{key}: must declare exactly one of fast/bokeh")
        hp = (s.get("host"), s.get("port"))
        if None in hp:
            issues.append(f"{key}: missing host/port")
        elif hp in hostports:
            issues.append(f"{key}: host:port {hp} collides with {hostports[hp]}")
        else:
            hostports[hp] = key
    return issues


def _shim_completeness(servers: dict) -> list[str]:
    issues: list[str] = []
    for key, s in servers.items():
        if s.get("deployment") != HEXAGON:
            continue
        module = _server_module(s)
        group = s.get("group")
        if not module or not group:
            issues.append(f"{key}: hexagon server missing group/module")
            continue
        shim = HEXAGON_SERVERS / group / f"{module}.py"
        if not shim.exists():
            issues.append(
                f"{key}: hexagon shim missing — expected {shim.relative_to(REPO_ROOT)}"
            )
    return issues


def _checklist_presence(servers: dict, checklist_dir: Optional[Path]) -> list[str]:
    # Only enforced for deployments that have a frozen checklist set (hte). A
    # deployment with no checklist dir (e.g. test) is out of scope for this gate.
    if checklist_dir is None or not checklist_dir.exists():
        return []
    issues: list[str] = []
    for key, s in servers.items():
        if s.get("deployment") != HEXAGON or s.get("group") != "action":
            continue
        module = _checklist_module(s)
        if module and not (checklist_dir / f"{module}.json").exists():
            issues.append(
                f"{key}: frozen endpoint checklist missing for '{module}' "
                f"(run harness.hte_freeze)"
            )
    return issues


def _lib_module_path(entry: str, default_dir: Path) -> Optional[Path]:
    """Resolve a library list entry (bare name or repo-relative path) to a file."""
    if entry.endswith(".py") or "/" in entry:
        p = (REPO_ROOT / entry) if not Path(entry).is_absolute() else Path(entry)
        return p if p.exists() else None
    p = default_dir / f"{entry}.py"
    return p if p.exists() else None


def _top_level_funcs(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    return [
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _library_collisions(cfg: dict) -> list[str]:
    if cfg.get("allow_shadow"):
        return []
    issues: list[str] = []
    for cfg_key, default_dir in (
        ("experiment_libraries", HTE_EXP),
        ("sequence_libraries", HTE_SEQ),
    ):
        name_to_mods: dict[str, list[str]] = defaultdict(list)
        for entry in cfg.get(cfg_key, []) or []:
            path = _lib_module_path(str(entry), default_dir)
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


def preflight_config(config: str) -> list[str]:
    """Return a list of preflight issues for a config prefix/path (empty = pass)."""
    cfg = read_config(config)
    servers = cfg.get("servers", {})
    deployment = _config_deployment(config)
    checklist_dir = _checklist_dir(deployment)
    issues: list[str] = []
    issues += _config_sanity(servers)
    issues += _shim_completeness(servers)
    issues += _checklist_presence(servers, checklist_dir)
    issues += _library_collisions(cfg)
    return issues


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print("usage: python -m helao.hexagon.preflight <config_prefix_or_path>")
        return 2
    issues = preflight_config(argv[0])
    if not issues:
        print(f"PREFLIGHT OK: {argv[0]}")
        return 0
    print(f"PREFLIGHT FAILED: {argv[0]} ({len(issues)} issue(s))")
    for i in issues:
        print(f"  - {i}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
