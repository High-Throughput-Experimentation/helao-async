"""Mutation self-test (spec §6.1 determinism gate + §12 P0 gate line 3).

The harness must FAIL when fed a deliberately perturbed tree — this is the
guard against over-normalization silently recreating failure mode F1. Each
mutation is applied to a fresh EXPLODED copy of the golden root (zips are
expanded first so mutations can reach members inside RUNS_SYNCED sequence
zips; an exploded tree is itself a valid parity candidate because
explode_zips is idempotent over zip-less trees).

Exit contract: 0 only when the UNMUTATED exploded copy passes parity
against the golden (sanity) AND every mutation makes parity fail.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Callable, Dict

from harness.parity import run_parity
from harness.treepass import explode_zips


def mutate_param_value(root: Path) -> str:
    """Append a key to an -act.yml: action_params are bit-exact (D7)."""
    act = sorted(root.rglob("*-act.yml"))[0]
    act.write_text(act.read_text() + "mutation_marker: 1\n")
    return f"appended top-level key to {act.name}"


def mutate_drop_file(root: Path) -> str:
    hlos = sorted(root.rglob("*.hlo"))
    target = hlos[0] if hlos else sorted(p for p in root.rglob("*") if p.is_file())[0]
    target.unlink()
    return f"deleted {target.name}"


def mutate_add_hlo_column(root: Path) -> str:
    hlo = sorted(root.rglob("*.hlo"))[0]
    with open(hlo, "a") as f:
        f.write('{"mutated_col": 1}\n')
    return f"appended a row with a new column to {hlo.name}"


def mutate_break_uuid_link(root: Path) -> str:
    """Rewire ONE file's experiment_uuid: the ordinal mapping must notice."""
    act = sorted(root.rglob("*-act.yml"))[0]
    text = act.read_text()
    m = re.search(r"experiment_uuid: ([0-9a-fA-F-]{36})", text)
    if m is None:
        raise RuntimeError(f"no experiment_uuid found in {act}")
    replacement = str(uuid.uuid4())
    act.write_text(text.replace(m.group(1), replacement, 1))
    return f"rewired experiment_uuid in {act.name}"


MUTATIONS: Dict[str, Callable[[Path], str]] = {
    "param_value": mutate_param_value,
    "drop_file": mutate_drop_file,
    "add_hlo_column": mutate_add_hlo_column,
    "break_uuid_link": mutate_break_uuid_link,
}


def run_self_test(golden_set: Path, workdir: Path) -> dict:
    golden_set, workdir = Path(golden_set), Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    baseline = explode_zips(golden_set / "root", workdir / "baseline")
    sanity = run_parity(golden_set, baseline)
    caught: Dict[str, bool] = {}
    for name, fn in MUTATIONS.items():
        mut_root = workdir / name
        shutil.copytree(baseline, mut_root)
        desc = fn(mut_root)
        report = run_parity(golden_set, mut_root)
        caught[name] = report["status"] == "fail"
        print(f"mutation {name}: {desc} -> {report['status']}")
    result = {
        "sanity_pass": sanity["status"] == "pass",
        "caught": caught,
        "ok": sanity["status"] == "pass" and all(caught.values()),
    }
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m harness.mutate")
    parser.add_argument("--golden", required=True, type=Path)
    parser.add_argument("--workdir", required=True, type=Path)
    args = parser.parse_args(argv)
    result = run_self_test(args.golden, args.workdir)
    print(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
