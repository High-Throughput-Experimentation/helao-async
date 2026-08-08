"""Row-15 negative, run live against a launched group (P7g gate).

Drives all five private control routes against a running ``controlneg`` group
through the **same** shared wrappers both UI stacks use -- via the hexagon's
``ControlSurface`` -- and asserts the run tree is unchanged afterwards.

The two things that make this more than a tautology:

1. **Every call must be observed to have worked** before the tree verdict
   counts. A dead server, a 404, or a toggle the device silently ignored each
   leaves the tree exactly as unchanged as a healthy run does, and each fails
   here. ``harness/control_negative.py`` owns that judgement and
   ``harness/tests/test_control_negative.py`` proves it goes red on all three.
2. **The baseline is not empty.** ``--seed-tree`` plants one finished-sequence
   tree under the run root first, so "unchanged" is a statement about a real
   member set surviving the toggles rather than about two empty sets matching.
   That tree is a *baseline*, never a parity golden -- it carries no
   provenance manifest and nothing here compares content.

Usage (the launcher is ``control_negative_run.sh``; this drives an already
running group)::

    python -m helao.hexagon.tests.smoke.control_negative_check \\
        --prefix controlneg [--seed-tree] [--keep-stage DIR]

Exit codes: 0 pass, 1 assertion failure, 2 error.
"""

import argparse
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

from harness.control_negative import ControlTarget, run_negative
from helao.helpers.config_loader import read_config

#: Which config keys carry which controls. Read from the config rather than
#: hardcoded so that a config edit cannot leave this driver silently probing a
#: server that no longer has the routes -- it would simply find no target and
#: the harness would report "no control calls made", which is a failure.
IO_VIS = "digital_out_control"
MOTION_VIS_PREFIX = "motion_control"


def targets_from_config(config: dict) -> list:
    """Build the drive list from a launched config's ``control_vis`` keys.

    A server contributes a ``do_name`` when it declares the digital-output
    panel and has a **readable** line configured, and an ``axis`` when it
    declares a motion panel. An unreadable line (config value ``null``) is
    skipped deliberately: it always reads back unknown, so it can never
    satisfy the success precondition -- which is the honest behaviour, and
    exactly why it cannot serve as proof.
    """
    targets = []
    for key, server in (config.get("servers") or {}).items():
        vis = server.get("control_vis")
        if not vis:
            continue
        params = server.get("params") or {}
        do_name = None
        axis = None
        if vis == IO_VIS:
            readable = [
                n for n, v in (params.get("dev_do") or {}).items() if v is not None
            ]
            do_name = readable[0] if readable else None
        elif str(vis).startswith(MOTION_VIS_PREFIX):
            names = list(params.get("axis_id") or params.get("axes") or {})
            axis = names[0] if names else None
        if do_name or axis:
            targets.append(
                ControlTarget(
                    server_key=key,
                    host=server["host"],
                    port=server["port"],
                    do_name=do_name,
                    axis=axis,
                )
            )
    return targets


def seed_baseline(root: Path) -> None:
    """Plant one finished-sequence tree so the member set is non-empty.

    Skipped when the root already holds run artifacts -- a group that has
    genuinely run something is a better baseline than a synthetic one.
    """
    from harness.tests.synthtree import build_tree

    if (root / "RUNS_FINISHED").is_dir() and any(
        (root / "RUNS_FINISHED").rglob("*.yml")
    ):
        print("[control_negative] RUNS_FINISHED already populated; not seeding")
        return
    root.mkdir(parents=True, exist_ok=True)
    build_tree(root)
    print(f"[control_negative] seeded a baseline run tree under {root}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="controlneg")
    parser.add_argument(
        "--seed-tree",
        action="store_true",
        help="plant a baseline run tree first, so the diff compares a real member set",
    )
    parser.add_argument(
        "--keep-stage",
        default=None,
        help="staging directory for the two snapshots (kept, for inspection)",
    )
    args = parser.parse_args(argv)

    try:
        config = read_config(args.prefix)
    except Exception as exc:  # noqa: BLE001 -- reported, not swallowed
        print(f"[control_negative] ERROR reading config '{args.prefix}': {exc}")
        return 2

    root = Path(config["root"])
    targets = targets_from_config(config)
    print(f"[control_negative] root={root}")
    for t in targets:
        print(
            f"[control_negative] target {t.server_key} @ {t.host}:{t.port} "
            f"do={t.do_name!r} axis={t.axis!r}"
        )
    if not targets:
        print(
            "[control_negative] FAIL no control targets in the config; an "
            "unchanged tree would mean nothing"
        )
        return 1

    if args.seed_tree:
        seed_baseline(root)

    stage = Path(args.keep_stage) if args.keep_stage else Path(tempfile.mkdtemp())
    try:
        result = asyncio.run(run_negative(root, targets, workdir=stage))
    except Exception as exc:  # noqa: BLE001
        print(f"[control_negative] ERROR driving the control surface: {exc}")
        return 2
    finally:
        if not args.keep_stage:
            shutil.rmtree(stage, ignore_errors=True)

    print(result.report())
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
