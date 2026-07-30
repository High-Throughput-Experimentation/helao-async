"""Guard against destructive deletes of a HELAO ``root`` on a station.

A station ``root`` (e.g. ``C:\\INST_hlo``) holds irreplaceable production data
-- run output, the sample DATABASE, and USER_CONFIG calibration matrices -- and
on a misconfigured host may even contain the code repo itself. A smoke/canary
script must therefore NEVER ``rmdir /s /q`` the root (this exact mistake wiped a
station once; ``rmdir /s /q`` bypasses the Recycle Bin, so the loss was
unrecoverable).

This module is the single choke point for two things:

* ``validate_root(root)`` -- refuse a root that is empty, a filesystem/drive
  anchor (``C:\\``, ``/``), or an ancestor of the code repo. Any station script
  should call ``--check`` before doing anything with the root.
* ``reset_generated(root, names)`` -- delete ONLY code-generated subdirs, and by
  default only the *ephemeral* ones (``STATES``, ``RUNS_ACTIVE``). It refuses any
  name not in the generated allowlist, refuses the data-bearing subdirs unless
  explicitly forced, and can never target the root itself.

The generated-directory names are the source of truth from
``helao/helpers/helao_dirs.py`` (which creates them) and
``helao/core/models/run_dir.py`` (the ``RUNS_*`` enum).
"""

import argparse
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Optional

from helao.core.models.run_dir import ALL_RUN_DIRS, RunDir

# Non-run subdirs created by helao_dirs.helao_dirs() directly under root.
# Keep in sync with helao/helpers/helao_dirs.py.
_NON_RUN_GENERATED = (
    "LOGS",
    "STATES",
    "DATABASE",
    "USER_CONFIG",
    "ANALYSES",
    "PROCESSES",
)

#: Names that must NEVER be deleted, even if one is passed explicitly or gets
#: added to the generated allowlist by mistake. A station commonly keeps its
#: helao code checkout under the data root at ``<root>\CODE``; protect it by name
#: so a reset can never touch it (belt-and-suspenders on top of GENERATED_DIRS,
#: which already excludes it). This is separate from validate_root(), which
#: refuses a root that contains *this running* repo -- a station's ``CODE`` copy
#: may be a different checkout, so it is guarded here by name too.
PROTECTED_DIRS: set[str] = {"CODE"}

#: Every subdirectory name HELAO generates under ``root``. Only these may ever
#: be considered for deletion; anything else is out of scope by construction.
#: PROTECTED_DIRS is subtracted so a protected name can never leak into the
#: deletable set even if _NON_RUN_GENERATED is later edited.
GENERATED_DIRS: set[str] = (
    {d.value for d in ALL_RUN_DIRS} | set(_NON_RUN_GENERATED)
) - PROTECTED_DIRS

#: The only subdirs safe to delete without special intent: transient launch
#: state and in-flight (not-yet-finished) run output. Everything else
#: (USER_CONFIG calibration, DATABASE, RUNS_FINISHED/SYNCED, ANALYSES,
#: PROCESSES, LOGS) holds data that is expensive or impossible to regenerate.
#: RunDir.ACTIVE.value is used (not a literal) so an enum rename is caught here.
EPHEMERAL_DIRS: set[str] = {"STATES", RunDir.ACTIVE.value}  # RUNS_ACTIVE


def _repo_root() -> Path:
    # this file lives at helao/hexagon/tests/smoke/safe_root.py -> repo is 4 up
    return Path(__file__).resolve().parents[4]


def validate_root(root: Optional[str]) -> Path:
    """Return the resolved root or raise ``ValueError`` if it is unsafe to touch.

    Rejects empty/whitespace, a filesystem or drive anchor (``/``, ``C:\\``),
    and any root that is an ancestor of (or equal to) the code repository.
    """
    if root is None or not str(root).strip():
        raise ValueError("root is empty")
    p = Path(str(root).strip())
    rp = p.resolve()

    # drive / filesystem anchor: parent of the anchor is itself
    if rp == rp.parent:
        raise ValueError(f"root {rp!r} is a filesystem/drive anchor")
    if str(rp) == rp.anchor:
        raise ValueError(f"root {rp!r} is a drive root")

    repo = _repo_root()
    # refuse if the repo is the root or lives underneath it (the wipe-the-code bug)
    if repo == rp or repo.is_relative_to(rp):
        raise ValueError(
            f"root {rp!r} contains the code repo {repo!r}; refusing destructive use"
        )
    return rp


def reset_generated(
    root: Optional[str],
    names: Optional[Iterable[str]] = None,
    dry_run: bool = False,
) -> list[str]:
    """Delete code-generated subdirs under ``root``; return the paths removed.

    ``names`` defaults to :data:`EPHEMERAL_DIRS`. Every requested name must be in
    :data:`GENERATED_DIRS` or a ``ValueError`` is raised. Each target must resolve
    to a direct child of ``root`` (no traversal) and can never be the root itself.
    """
    rp = validate_root(root)
    requested = set(names) if names is not None else set(EPHEMERAL_DIRS)

    # explicit protection first: a protected name (e.g. CODE) is never deletable,
    # even ahead of the generated-allowlist check, so the error is unambiguous.
    protected_hit = requested & PROTECTED_DIRS
    if protected_hit:
        raise ValueError(
            f"refusing to delete protected path(s): {sorted(protected_hit)}"
        )

    illegal = requested - GENERATED_DIRS
    if illegal:
        raise ValueError(
            f"refusing to delete non-generated path(s): {sorted(illegal)}; "
            f"allowed generated dirs: {sorted(GENERATED_DIRS)}"
        )

    removed: list[str] = []
    for name in sorted(requested):
        # last-ditch guard: never delete a protected dir under any code path
        if name in PROTECTED_DIRS:
            raise ValueError(f"refusing to delete protected path {name!r}")
        target = (rp / name).resolve()
        # defense in depth: must be a direct child of root, never root
        if target == rp or target.parent != rp:
            raise ValueError(f"unsafe target {target!r} for root {rp!r}")
        if not target.exists():
            continue
        if dry_run:
            print(f"[safe_root] would remove {target}")
        else:
            shutil.rmtree(target)
            print(f"[safe_root] removed {target}")
        removed.append(str(target))
    return removed


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="validate that root is safe to touch")
    p_check.add_argument("root")

    p_reset = sub.add_parser(
        "reset", help="delete ephemeral (or named) generated subdirs under root"
    )
    p_reset.add_argument("root")
    p_reset.add_argument(
        "--include",
        nargs="*",
        default=None,
        metavar="DIR",
        help=f"generated dirs to remove (default: {sorted(EPHEMERAL_DIRS)}); "
        f"must be in {sorted(GENERATED_DIRS)}",
    )
    p_reset.add_argument("--dry-run", action="store_true")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "check":
            rp = validate_root(args.root)
            print(f"[safe_root] OK: {rp} is safe (repo not underneath, not a root)")
            return 0
        if args.cmd == "reset":
            reset_generated(args.root, names=args.include, dry_run=args.dry_run)
            return 0
    except ValueError as exc:
        print(f"[safe_root] REFUSED: {exc}")
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
