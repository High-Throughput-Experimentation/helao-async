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
* a **changed** schema is a real surface change, reported and left UNAPPLIED
  unless ``--accept-drift`` says otherwise — and even then applied
  **surgically**, touching only the flagged route and field;
* a **removed** route is stronger still: ``--accept-drift`` will NOT drop it.
  Each removal must be named with ``--accept-missing <path>``.

The asymmetry is deliberate and was learned the hard way. A blanket
``--accept-drift`` over a whole deployment once applied a server's 11 ``missing``
records and cut its frozen baseline from 16 routes to 5 — silently deleting the
runtime-registered routes that baseline existed to assert. Widening a schema is
recoverable; deleting the thing the gate checks is how a gate stops gating. So
the two authorities are separate, and the destructive one is per-route.

That default is the important one. Regenerating a checklist to make a diff pass
is the failure mode the frozen-checklist gate exists to prevent, so widening the
baseline has to be a deliberate act with a reason recorded in the commit.

And it skips a checklist frozen under a **synthesized** server key — see
:func:`synthesized_key` for why that is a scope decision rather than drift, and
why the superficially similar "frozen with ``{server_key}`` unsubstituted" case
must still be frozen normally.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from collections.abc import Iterable
from typing import Optional

from harness.endpoints import diff_route_sets, extract_routes, normalize_annotation
from helao.hexagon.preflight import _checklist_dir

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Manifest filename inside a deployment's checklist directory. Maps each
#: action-server module to the server key substituted for ``{server_key}``.
MANIFEST = "servers.json"


def _route_key(route: dict) -> tuple[str, str]:
    return (route["path"], route["method"])


def synthesized_key(frozen: list[dict]) -> Optional[str]:
    """The concrete server key a checklist's paths were frozen under, if any.

    Returns the single ``/<KEY>/...`` prefix shared by every key-prefixed path in
    ``frozen``, or None when the paths carry the literal ``{server_key}`` (never
    substituted), when they disagree, or when there are none.

    This distinguishes two situations that both show up as
    ``representative_key: null`` in a manifest, and must NOT be treated alike:

    * **Frozen unsubstituted** (``{server_key}`` in the paths) — the manifest and
      the checklist agree that no key was supplied. Freezing works normally and
      must keep working, or a route added to such a module later goes unnoticed.
    * **Frozen under a synthesized key** (a concrete prefix) — the checklist was
      produced from a canary config invented to give an *unwired, non-gating*
      server openapi-only coverage, while the manifest surveyed the operational
      configs and correctly recorded no key. Both artifacts are right about
      different questions, and re-extracting with no key reports every frozen
      path as ``missing`` — a defect list manufactured out of a scope decision.
    """
    prefixes = {
        p.split("/")[1]
        for p in (r["path"] for r in frozen)
        if p.startswith("/") and len(p.split("/")) > 2
    }
    if len(prefixes) != 1:
        return None
    only = prefixes.pop()
    return None if only == "{server_key}" else only


def _merge_params(frozen_params: list, current_params: list) -> list:
    """``current_params``, but keeping a frozen param's verbatim text where the
    type is unchanged and only its PEP 585 spelling moved.

    Needed because ``diff_route_sets`` reports ``params`` as one field, so
    accepting a real correction to ONE parameter would otherwise rewrite every
    other parameter on that route — including spellings the gate already ignores.
    """
    frozen_by_name = {
        p["name"]: p for p in frozen_params if isinstance(p, dict) and "name" in p
    }

    def same_modulo_spelling(a: dict, b: dict) -> bool:
        def norm(p: dict) -> dict:
            out = dict(p)
            ann = out.get("annotation")
            if isinstance(ann, str):
                out["annotation"] = normalize_annotation(ann)
            return out

        return norm(a) == norm(b)

    out = []
    for cur in current_params:
        fz = frozen_by_name.get(cur.get("name")) if isinstance(cur, dict) else None
        out.append(fz if fz is not None and same_modulo_spelling(fz, cur) else cur)
    return out


def applicable_drift(
    drift: list[dict],
    *,
    accept_drift: bool = False,
    accept_missing: Iterable[str] = (),
) -> list[dict]:
    """The subset of ``drift`` the caller has actually authorized applying.

    Two separate authorities, because the two record kinds carry very different
    risk:

    * ``changed`` — a schema difference. Authorized in bulk by ``accept_drift``;
      widening or narrowing a param schema is visible in the next diff and
      recoverable.
    * ``missing`` — a route the module no longer registers. Authorized ONLY by
      naming its path in ``accept_missing``, because applying it DELETES the
      route from the baseline, and a deleted route is one the gate silently
      stops asserting. ``accept_drift`` alone never drops a route.

    Anything not authorized stays in the caller's blocker list, so the freeze
    exits non-zero rather than quietly narrowing the record.
    """
    named = set(accept_missing or ())
    out: list[dict] = []
    for d in drift:
        if d["kind"] == "changed" and accept_drift:
            out.append(d)
        elif d["kind"] == "missing" and d["path"] in named:
            out.append(d)
    return out


def apply_drift(
    frozen: list[dict], current: list[dict], drift: list[dict]
) -> list[dict]:
    """``frozen`` with ONLY the reported ``drift`` records applied.

    A ``missing`` record drops that route; a ``changed`` record replaces just the
    named field on that route (and, for ``params``, only the parameters that truly
    differ — see :func:`_merge_params`). Every other route and field stays
    byte-verbatim, and the surviving order is preserved.

    The alternative — taking the current extraction wholesale for that server —
    is what the first version did, and it silently rewrote four unrelated verbatim
    annotations while correcting six real ones, two of them on routes the diff had
    not even flagged. An escape hatch that churns the record it is editing defeats
    the point of freezing additively at all.
    """
    cur_by_key = {_route_key(r): r for r in current}
    dropped = {(d["path"], d["method"]) for d in drift if d["kind"] == "missing"}
    changes: dict[tuple[str, str], list[str]] = {}
    for d in drift:
        if d["kind"] == "changed":
            changes.setdefault((d["path"], d["method"]), []).append(d["field"])

    out: list[dict] = []
    for route in frozen:
        key = _route_key(route)
        if key in dropped:
            continue
        fields = changes.get(key)
        if fields:
            cur = cur_by_key[key]
            route = dict(route)
            for field in fields:
                route[field] = (
                    _merge_params(route[field], cur[field])
                    if field == "params"
                    else cur[field]
                )
        out.append(route)
    return out


def merge_routes(
    frozen: list[dict],
    current: list[dict],
    *,
    accept_drift: bool = False,
    accept_missing: Iterable[str] = (),
) -> tuple[list[dict], list[dict]]:
    """Merge ``current`` into ``frozen`` additively.

    Returns ``(merged, drift)``. ``merged`` keeps every surviving frozen entry
    byte-verbatim and appends routes absent from ``frozen``. ``drift`` holds the
    ``diff_route_sets`` records that a merge must NOT silently apply — ``missing``
    (a frozen route the module no longer registers) and ``changed`` (same route,
    different schema beyond PEP 585 spelling). ``extra`` records are the additions
    and are applied, not reported as drift.

    Authorized drift records are applied too, surgically (:func:`apply_drift`)
    rather than by replacing the server's whole route list — and which records
    count as authorized is :func:`applicable_drift`'s decision, not this
    function's. Notably ``accept_drift`` alone never drops a route.
    """
    drift = [d for d in diff_route_sets(frozen, current) if d["kind"] != "extra"]
    frozen_keys = {_route_key(r) for r in frozen}
    additions = [r for r in current if _route_key(r) not in frozen_keys]
    applied = applicable_drift(
        drift, accept_drift=accept_drift, accept_missing=accept_missing
    )
    if applied:
        frozen = apply_drift(frozen, current, applied)
    if not additions:
        # Return the frozen list AS IT STANDS -- untouched when no drift was
        # accepted, patched in place when it was. Not `sorted(...)`: a frozen file
        # need not be stored in sorted order (one is kept in source-declaration
        # order), and re-sorting it would rewrite a verbatim record to no effect --
        # the very thing this module exists to avoid. Callers detect "nothing to do"
        # by equality with what they read.
        return frozen, drift
    # Adding a route does normalize the file to sorted order. Harmless: the gate
    # compares by (path, method), so order carries no meaning, and entry CONTENT is
    # still copied through verbatim.
    return sorted(frozen + additions, key=_route_key), drift


def load_manifest(checklist_dir: Path) -> list[dict]:
    manifest = checklist_dir / MANIFEST
    if not manifest.is_file():
        raise FileNotFoundError(f"no {MANIFEST} in {checklist_dir}")
    return json.loads(manifest.read_text())["servers"]


def freeze_deployment(
    deployment: str,
    *,
    accept_drift: bool = False,
    accept_missing: Iterable[str] = (),
    dry_run: bool = False,
    only: Optional[str] = None,
    include_unwired: bool = False,
    key_override: Optional[str] = None,
) -> tuple[list[str], list[str]]:
    """Freeze one deployment's action-server checklists additively.

    Args:
        deployment: Deployment directory name under ``helao/deploy/``.
        accept_drift: Apply ``changed`` records too, altering param schemas in
            the baseline. Requires a recorded reason in the commit. Does NOT
            drop routes — see ``accept_missing``.
        accept_missing: Paths whose ``missing`` records may be applied, i.e.
            whose routes may be DELETED from the baseline. Named per route on
            purpose (:func:`applicable_drift`).
        dry_run: Report without writing.
        only: Restrict to one module basename (with or without ``.py``).
        include_unwired: Freeze synthesized-key checklists too (see
            :func:`synthesized_key`). Off by default so a deliberate scope
            decision is not reported as drift; passing it re-extracts those with
            no key, which WILL report every frozen path as missing.
        key_override: Substitute this server key instead of the manifest's, and
            do not skip on a synthesized key. This is how a synthesized-key
            checklist is legitimately maintained: the manifest correctly records
            no OPERATIONAL key, but the checklist's paths were frozen under one,
            so re-freezing it needs that key supplied rather than inferred.
            Meaningful only with ``only``.

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
        dst = checklist_dir / f"{stem}.json"
        frozen = json.loads(dst.read_text()) if dst.is_file() else []
        key = key_override or entry.get("representative_key")
        if key is None and not include_unwired:
            invented = synthesized_key(frozen)
            if invented is not None:
                note = entry.get("note")
                lines.append(
                    f"  skipped    {stem} — frozen under synthesized key "
                    f"'{invented}'; manifest declares no operational key"
                    + (f" ({note})" if note else "")
                )
                continue
        current = extract_routes(src, server_key=key)
        merged, drift = merge_routes(
            frozen,
            current,
            accept_drift=accept_drift,
            accept_missing=accept_missing,
        )
        applied = applicable_drift(
            drift, accept_drift=accept_drift, accept_missing=accept_missing
        )

        for d in drift:
            msg = f"{stem}: {d['kind']} {d['method'].upper()} {d['path']}"
            if d["kind"] == "changed":
                msg += f" [{d['field']}]"
            if d in applied:
                lines.append(f"  ACCEPTED {msg}")
            elif d["kind"] == "missing":
                # Say how, or the reader reaches for --accept-drift and finds it
                # does nothing -- which reads as a broken flag rather than a guard.
                blockers.append(f"{msg}  (name it: --accept-missing {d['path']})")
            else:
                blockers.append(msg)

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
        help="also apply changed param schemas, surgically (record why in the "
        "commit); never drops a route",
    )
    p.add_argument(
        "--accept-missing",
        action="append",
        metavar="PATH",
        help="allow DELETING this route from the baseline; repeatable. Named per "
        "route because a dropped route is one the gate stops asserting",
    )
    p.add_argument("--dry-run", action="store_true", help="report without writing")
    p.add_argument(
        "--key",
        help="substitute this server key instead of the manifest's (use with "
        "--only, to maintain a checklist frozen under a synthesized key)",
    )
    p.add_argument(
        "--include-unwired",
        action="store_true",
        help="also freeze checklists held under a synthesized server key "
        "(unwired, non-gating servers — skipped by default)",
    )
    a = p.parse_args(argv)
    try:
        lines, blockers = freeze_deployment(
            a.deployment,
            accept_drift=a.accept_drift,
            accept_missing=a.accept_missing or (),
            dry_run=a.dry_run,
            only=a.only,
            include_unwired=a.include_unwired,
            key_override=a.key,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"deployment {a.deployment}:")
    for line in lines:
        print(line)
    if blockers:
        print("\nUNAPPLIED surface drift:")
        for b in blockers:
            print(f"  {b}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
