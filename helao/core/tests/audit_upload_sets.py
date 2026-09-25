"""Report files the syncer's directory glob would upload that ``files`` omits.

Standalone report utility, in the style of ``check_long_paths`` and
``scan_prg_ghosts``. Not a pytest module: ``run_tests.py`` reports it as
NOTESTS and it must be invoked directly.

    python helao/core/tests/audit_upload_sets.py <archive_root> [--limit N]

``archive_root`` is any directory containing action ymls -- a whole
``RUNS_SYNCED`` tree, or one sequence directory. The script pairs each
``*-act.yml`` with its own directory and prints every name that a glob would
have picked up but the yml's ``files`` list does not mention.

Spec: docs/superpowers/specs/2026-09-25-runs-layout-and-state-journal-design.md §3.5.1
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from helao.helpers.yml_tools import yml_load


def _is_bookkeeping(path: Path) -> bool:
    """Staging and lock files that no upload set should ever contain.

    Mirrors ``HelaoYml._is_syncable_misc_file``'s exclusions: every meta and
    data writer here stages ``.<hex>.tmp`` beside its target and renames into
    place, so a scan landing mid-write sees a name that is not a run artifact.
    """
    return path.suffix in (".lock", ".tmp") or path.name.startswith(".")


def glob_set(action_dir: Path) -> set[str]:
    """What the syncer uploads today: every non-bookkeeping file, recursively.

    Returns forward-slash paths relative to ``action_dir``. Action ymls recurse
    (``sync_driver.HelaoYml.misc_files`` uses ``rglob`` for actions), so a file
    in a subdirectory is included.
    """
    out = set()
    for p in action_dir.rglob("*"):
        if not p.is_file() or _is_bookkeeping(p):
            continue
        if p.suffix == ".yml":
            continue
        out.add(p.relative_to(action_dir).as_posix())
    return out


def files_set(act_yml: Path) -> set[str]:
    """What the action's own ``files`` list names, nosync entries included.

    nosync entries are kept here deliberately: this audit measures
    *addressability*, not the upload decision. A nosync file that ``files``
    names is not a gap.
    """
    meta = yml_load(act_yml, fast=True) or {}
    out = set()
    for entry in meta.get("files") or []:
        name = (entry or {}).get("file_name")
        if name:
            out.add(str(name).replace("\\", "/"))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("archive_root", type=Path)
    ap.add_argument("--limit", type=int, default=0, help="stop after N actions")
    args = ap.parse_args(argv)

    if not args.archive_root.is_dir():
        print(f"not a directory: {args.archive_root}", file=sys.stderr)
        return 2

    scanned = 0
    with_gap = 0
    by_suffix: Counter = Counter()
    examples: dict[str, str] = {}

    for act_yml in args.archive_root.rglob("*-act.yml"):
        scanned += 1
        gap = glob_set(act_yml.parent) - files_set(act_yml)
        if gap:
            with_gap += 1
            for rel in gap:
                suffix = Path(rel).suffix or "<none>"
                by_suffix[suffix] += 1
                examples.setdefault(suffix, str(act_yml.parent / rel))
        if args.limit and scanned >= args.limit:
            break

    print(f"actions scanned : {scanned}")
    print(f"actions with gap: {with_gap}")
    print()
    if not by_suffix:
        print("no gap: every globbed file is named in its action's files list")
        return 0
    print(f"{'suffix':<12}{'count':>8}  example")
    for suffix, count in by_suffix.most_common():
        print(f"{suffix:<12}{count:>8}  {examples[suffix]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
