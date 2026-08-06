"""P3e — offline preflight validator for hexagon-composed configs (spec §8.3).

Runs the hexagon-specific static gates that must pass BEFORE a config's
`deployment: hexagon` servers are launched at a station — with disconnected
adapters, on Linux, no server launch and no hardware:

1. **config sanity** — unique server keys, unique host:port, exactly one of
   `fast`/`bokeh`/`reflex` per server (the launcher's cross-cutting rule).
   A `reflex:` server occupies TWO consecutive ports (static frontend, then
   backend), so the uniqueness check reserves `port + 1` for it as well.
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

#: The launcher's server code keys, pinned to ``launch.py``'s ``codeKeys``. A
#: config is validated against the SAME set the launcher will accept, so a
#: preflight pass cannot be followed by a launcher rejection (or, worse, by a
#: server the launcher silently SKIPS because its key is unrecognized).
#: ``test_code_keys_match_the_launcher`` reads launch.py's tuple and asserts
#: agreement rather than trusting this copy.
CODE_KEYS = ("fast", "bokeh", "reflex")

REPO_ROOT = Path(__file__).resolve().parents[2]
HEXAGON_SERVERS = REPO_ROOT / "helao" / "deploy" / "hexagon" / "servers"
CHECKLIST_ROOT = REPO_ROOT / "helao" / "hexagon" / "tests" / "checklists"
HTE_EXP = REPO_ROOT / "helao" / "deploy" / "hte" / "experiments"
HTE_SEQ = REPO_ROOT / "helao" / "deploy" / "hte" / "sequences"
# hte's canary configs (P3a/P3e) were relocated here, OUTSIDE helao/deploy/hte/
# entirely, so they no longer carry "deploy"/"hte" in their path -- see the
# fallback in _config_deployment below.
HTE_SMOKE_CONFIGS = REPO_ROOT / "helao" / "hexagon" / "tests" / "smoke" / "configs"

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
        # Relocated hte canary config: lives under HTE_SMOKE_CONFIGS instead
        # of helao/deploy/hte/configs/, so "deploy" never appears in its path.
        # Every config under this centralized, hte-only directory belongs to
        # "hte" by construction (P3a/P3e relocation) -- infer it directly so
        # the checklist-presence gate isn't silently skipped post-move.
        if m.parent == HTE_SMOKE_CONFIGS:
            return "hte"
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


#: Label suffixes for a server's SECONDARY port claims -- ones that appear
#: nowhere in the config as their own key, so a collision message must name
#: WHICH invisible claim it is or it reads as a plain typo.
_REFLEX_BACKEND_LABEL = "reflex backend port, port + 1"
_ALIGNER_BOKEH_LABEL = "aligner Bokeh port, params.bokeh_port or port + 1000"


def _aligner_port(server: dict) -> Optional[int]:
    """The extra Bokeh-aligner port a server claims, or ``None``.

    Any server whose ``params.enable_aligner`` is truthy hosts a second Bokeh
    server for the plate aligner (``GalilAlignerHost`` and its lila
    equivalent both share this contract) on ``params.bokeh_port`` when set,
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
    return int(params.get("bokeh_port", int(port) + 1000))


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


def _shim_completeness(servers: dict) -> list[str]:
    issues: list[str] = []
    for key, s in servers.items():
        if s.get("deployment") != HEXAGON:
            continue
        if "reflex" in s:
            # Master spec D9: both UI stacks stay on legacy core through P0-P6 and
            # migrate together in P7-UI, so there is no hexagon UI shim to find.
            # Say that, rather than reporting a missing group/module.
            issues.append(
                f"{key}: reflex servers are not hexagon-composed (spec D9 — UI "
                f"hosting is P7-UI); drop 'deployment: hexagon' from this server"
            )
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
    if deployment and deployment != HEXAGON:
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
    tree = ast.parse(path.read_text())
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
    issues += _library_collisions(cfg, deployment)
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
