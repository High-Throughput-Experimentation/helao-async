"""Additive, verbatim-preserving endpoint-checklist freezer (spec §8.3).

Generic over deployments: the module list and its ``{server_key}`` substitutions
come from the deployment's own ``servers.json`` manifest, and the output goes to
the same directory the preflight gate reads. Nothing private is named in this
file — a private deployment's manifest and checklists live inside its own repo,
and the path is BUILT from the deployment name passed at runtime (the rule
`helao.hexagon.preflight._checklist_dir` implements; imported here rather than
re-spelled so the freezer and the gate cannot disagree about where a checklist
lives).

Why additive rather than a plain re-extract
-------------------------------------------
A frozen checklist is a **verbatim record of the pre-migration legacy surface**,
and `harness.endpoints.diff_route_sets` already normalizes PEP 585 alias
spelling when it compares. Those two facts together mean a repo-wide typing or
formatting sweep must NOT cause a re-freeze: the gate is immune to the spelling
change, so rewriting the stored record only destroys its provenance.

So this tool never blindly overwrites:

* a route that still exists and whose schema matches the frozen entry modulo
  PEP 585 spelling is copied through **byte-verbatim** from the frozen file;
* a genuinely new route is appended;
* a **changed** schema or a **removed** route is a real surface change, and is
  reported and left UNAPPLIED unless ``--accept-drift`` says otherwise.

That default is the important one. Regenerating a checklist to make a diff pass
is the failure mode the frozen-checklist gate exists to prevent, so widening the
baseline has to be a deliberate act with a reason recorded in the commit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from harness.endpoints import diff_route_sets, extract_routes
from helao.hexagon.preflight import _checklist_dir

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Manifest filename inside a deployment's checklist directory. Maps each
#: action-server module to the server key substituted for ``{server_key}``.
MANIFEST = "servers.json"


def _route_key(route: dict) -> tuple[str, str]:
    return (route["path"], route["method"])


def merge_routes(
    frozen: list[dict], current: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Merge ``current`` into ``frozen`` additively.

    Returns ``(merged, drift)``. ``merged`` keeps every surviving frozen entry
    byte-verbatim and appends routes absent from ``frozen``. ``drift`` holds the
    ``diff_route_sets`` records that a merge must NOT silently apply — ``missing``
    (a frozen route the module no longer registers) and ``changed`` (same route,
    different schema beyond PEP 585 spelling). ``extra`` records are the additions
    and are applied, not reported as drift.
    """
    drift = [d for d in diff_route_sets(frozen, current) if d["kind"] != "extra"]
    frozen_keys = {_route_key(r) for r in frozen}
    additions = [r for r in current if _route_key(r) not in frozen_keys]
    merged = sorted(frozen + additions, key=_route_key)
    return merged, drift


def load_manifest(checklist_dir: Path) -> list[dict]:
    manifest = checklist_dir / MANIFEST
    if not manifest.is_file():
        raise FileNotFoundError(f"no {MANIFEST} in {checklist_dir}")
    return json.loads(manifest.read_text())["servers"]


def freeze_deployment(
    deployment: str,
    *,
    accept_drift: bool = False,
    dry_run: bool = False,
    only: Optional[str] = None,
) -> tuple[list[str], list[str]]:
    """Freeze one deployment's action-server checklists additively.

    Args:
        deployment: Deployment directory name under ``helao/deploy/``.
        accept_drift: Apply ``changed``/``missing`` records too, widening or
            shrinking the baseline. Requires a recorded reason in the commit.
        dry_run: Report without writing.
        only: Restrict to one module basename (with or without ``.py``).

    Returns:
        ``(lines, blockers)`` — human-readable report lines, and the subset that
        represent unapplied drift. A non-empty ``blockers`` list means the freeze
        is incomplete by design, and is what makes the CLI exit non-zero.
    """
    checklist_dir = _checklist_dir(deployment)
    if checklist_dir is None:
        raise FileNotFoundError(f"no checklist directory for deployment {deployment!r}")
    lines: list[str] = []
    blockers: list[str] = []
    wanted = only[:-3] if only and only.endswith(".py") else only

    for entry in load_manifest(checklist_dir):
        module = entry["module"]
        stem = Path(module).stem
        if wanted and stem != wanted:
            continue
        src = REPO_ROOT / "helao" / "deploy" / deployment
        src = src / "servers" / entry.get("group", "action") / module
        if not src.is_file():
            blockers.append(f"{stem}: module missing at {src.relative_to(REPO_ROOT)}")
            continue
        current = extract_routes(src, server_key=entry.get("representative_key"))
        dst = checklist_dir / f"{stem}.json"
        frozen = json.loads(dst.read_text()) if dst.is_file() else []
        merged, drift = merge_routes(frozen, current)

        for d in drift:
            msg = f"{stem}: {d['kind']} {d['method'].upper()} {d['path']}"
            if d["kind"] == "changed":
                msg += f" [{d['field']}]"
            if accept_drift:
                lines.append(f"  ACCEPTED {msg}")
            else:
                blockers.append(msg)
        if accept_drift and drift:
            merged = sorted(current, key=_route_key)

        if merged == frozen:
            lines.append(f"  unchanged  {stem} ({len(frozen)} routes)")
            continue
        verb = "would write" if dry_run else "wrote"
        lines.append(f"  {verb}     {stem} ({len(frozen)} -> {len(merged)} routes)")
        if not dry_run:
            dst.write_text(json.dumps(merged, indent=2) + "\n")
        for r in merged:
            if _route_key(r) not in {_route_key(f) for f in frozen}:
                tags = ",".join(r["tags"]) or "-"
                lines.append(f"      + {r['method'].upper()} {r['path']} [{tags}]")
    return lines, blockers


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m harness.freeze")
    p.add_argument("deployment", help="deployment directory name under helao/deploy/")
    p.add_argument("--only", help="restrict to one action-server module basename")
    p.add_argument(
        "--accept-drift",
        action="store_true",
        help="also apply changed/removed routes (widens the gate — record why)",
    )
    p.add_argument("--dry-run", action="store_true", help="report without writing")
    a = p.parse_args(argv)
    try:
        lines, blockers = freeze_deployment(
            a.deployment,
            accept_drift=a.accept_drift,
            dry_run=a.dry_run,
            only=a.only,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"deployment {a.deployment}:")
    for line in lines:
        print(line)
    if blockers:
        print("\nUNAPPLIED surface drift (re-run with --accept-drift to apply):")
        for b in blockers:
            print(f"  {b}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
