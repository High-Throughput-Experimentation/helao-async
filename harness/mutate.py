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
from collections.abc import Callable
from pathlib import Path

from harness.parity import run_parity
from harness.treepass import explode_zips

#: The first numeric leaf inside an ``action_params:`` block. The KEY NAME is
#: deliberately not hardcoded. ``duration`` exists only in the public simulator
#: trees, so keying on it made this mutation class silently inapplicable to
#: every other deployment's goldens: it raised instead of mutating, which reads
#: as a broken harness when it really means "this tree has different
#: parameters". A conversion-family tree carries none of the sim param names.
_PARAM_RE = re.compile(
    r"^action_params:\n(?:[ \t]+.*\n)*?[ \t]+(?P<key>\w+): (?P<val>-?\d+(?:\.\d+)?)[ \t]*$",
    re.MULTILINE,
)


def mutate_param_value(root: Path) -> str:
    """Mutate an existing numeric action_params value in an -act.yml:
    action_params are bit-exact (D7).

    A real multi-action sequence (e.g. GM-1/GM-5's ORCH ``wait`` + SIM
    ``acquire_data`` actions) has action files whose params differ by
    action type, so the alphabetically-first ``-act.yml`` is not guaranteed
    to carry a ``duration`` param at all (ORCH ``wait`` carries `waittime`
    instead) — and the value itself is scenario-parameterized (GM-1 uses
    `data_duration: 4.0`, the synthetic single-action fixture in
    synthtree.py hardcodes 2.0), so a fixed literal target string is not
    general. Search every action file, in sorted order for capture-
    independence, for the first NUMERIC action_params entry and perturb that
    value rather than assuming a fixed key or a fixed old/new literal pair.
    """
    for act in sorted(root.rglob("*-act.yml")):
        text = act.read_text()
        m = _PARAM_RE.search(text)
        if m:
            key, old_val = m.group("key"), m.group("val")
            new_val = str(float(old_val) + 0.5)
            mutated = text[: m.start("val")] + new_val + text[m.end("val") :]
            act.write_text(mutated)
            return f"mutated action_params.{key} in {act.name} ({old_val} -> {new_val})"
    raise RuntimeError(
        f"no numeric action_params entry found in any -act.yml under {root}"
    )


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


MUTATIONS: dict[str, Callable[[Path], str]] = {
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
    caught: dict[str, bool] = {}
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
