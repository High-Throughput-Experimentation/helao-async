"""Structural diff of two FastAPI /openapi.json dumps for the gamryhex canary.

Compares the route surface (method + path) and the component schemas of a
legacy vs hexagon server. Exit 0 == identical surface (parity), 1 == diffs,
2 == usage/load error. Volatile top-level fields (info, servers) are ignored;
only the route table and schema definitions gate parity.

Usage: python openapi_diff.py <legacy_openapi.json> <candidate_openapi.json>
"""

import json
import sys
from typing import Dict, List, Set, Tuple


def _load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _routes(spec: dict) -> Set[Tuple[str, str]]:
    """Set of (METHOD, path) over paths.<path>.<method>."""
    out: Set[Tuple[str, str]] = set()
    for path, ops in (spec.get("paths") or {}).items():
        for method in ops:
            if method.lower() in {
                "get",
                "put",
                "post",
                "delete",
                "patch",
                "head",
                "options",
                "trace",
            }:
                out.add((method.upper(), path))
    return out


def _schemas(spec: dict) -> Dict[str, dict]:
    return (spec.get("components") or {}).get("schemas") or {}


def main(argv: List[str]) -> int:
    if len(argv) != 3:
        print("usage: openapi_diff.py <legacy.json> <candidate.json>")
        return 2
    try:
        legacy = _load(argv[1])
        cand = _load(argv[2])
    except (OSError, json.JSONDecodeError) as exc:
        print(f"load error: {exc}")
        return 2

    diffs = 0

    lr, cr = _routes(legacy), _routes(cand)
    removed = sorted(lr - cr)
    added = sorted(cr - lr)
    if removed:
        diffs += 1
        print(f"ROUTES MISSING in candidate ({len(removed)}):")
        for m, p in removed:
            print(f"  - {m} {p}")
    if added:
        diffs += 1
        print(f"ROUTES ADDED in candidate ({len(added)}):")
        for m, p in added:
            print(f"  + {m} {p}")

    ls, cs = _schemas(legacy), _schemas(cand)
    lk, ck = set(ls), set(cs)
    s_removed = sorted(lk - ck)
    s_added = sorted(ck - lk)
    if s_removed:
        diffs += 1
        print(f"SCHEMAS MISSING in candidate ({len(s_removed)}): {s_removed}")
    if s_added:
        diffs += 1
        print(f"SCHEMAS ADDED in candidate ({len(s_added)}): {s_added}")

    changed = sorted(k for k in (lk & ck) if ls[k] != cs[k])
    if changed:
        diffs += 1
        print(f"SCHEMAS CHANGED in candidate ({len(changed)}): {changed}")

    if diffs == 0:
        print(f"OK: {len(cr)} routes, {len(ck)} schemas -- identical surface")
        return 0
    print(f"DIFFS: {diffs} category(ies) differ")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
