"""Rewrite the ``run_use`` tag on an already-synced sequence record.

```
python -m helao.core.tests.set_run_use <RUNS_SYNCED/.../<sequence>.zip | RUNS/<year>/<day>/<sequence>> \
    [--run-use data] [--dry-run] [--no-reset] [--process-dir DIR]
```

A sequence directory in the single ``RUNS`` tree is accepted as well as a
legacy zip: its records (``.json`` or ``.yml``) are retagged in place in their
own format, but only when every seq/exp/act record's ``.prg`` says
``synced: true`` -- otherwise the tool refuses and writes nothing (a
``--dry-run`` reports the refusal too). The hand-back there deletes every
``.prg`` under the sequence, then prints the ``/finish_yml`` call -- unless
there was nothing to change, when it exits 0 and deletes nothing. A zip
holding no record yml at all exits 1.

Retags a record whose ``run_use`` was wrong when it ran -- a plate measured as
a reference and filed as ``data``, or the reverse. It touches the record's own
``-act.yml``/``-exp.yml`` members inside the zip, any ``-prc.yml`` the zip
carries, and the ``-prc.yml`` files in the parallel ``PROCESSES`` tree that
older builds wrote outside the zip (``sync_driver`` writes them beside the
``-exp.yml`` now, so a modern record has both or neither).

Things worth knowing before editing this:

- **A zip cannot be edited in place.** The archive is rebuilt into a staging
  sibling (``file_utils.staging_path``, which is shorter than the name it
  stages and so cannot push a station path past Windows' ``MAX_PATH``) and
  ``os.replace``'d onto the original. Every member this tool does not rewrite
  is copied byte-for-byte with its own ``compress_type``, ``date_time`` and
  attributes, so ``.hlo``/``.prg``/vendor payloads come out unchanged.
- **``process_contrib`` contains the literal string ``run_use``.** It is a
  list of which fields an action contributes to its process, not a value to
  retag. Only mapping keys named ``run_use`` are rewritten; a sequence item is
  never touched.
- **A sequence yml has no ``run_use`` field.** ``SequenceModel`` does not
  define one, so a ``-seq.yml`` is reported and left alone rather than given a
  key that the model would not round-trip. ``ActionModel``, ``ExperimentModel``
  and ``ProcessModel`` all define it, so those get the key even when the
  written record omitted it -- the experiment writer strips it, which is why
  a real ``-exp.yml`` on disk usually has none.
- **An action's ``files[].run_use`` is rewritten too**, where recorded. It
  describes the same data as the action's own tag, and leaving the two
  disagreeing is how a retagged record ends up half-retagged downstream. A
  file entry that recorded no ``run_use`` keeps none.
- **Process ymls are matched on ``sequence_uuid``, not on path alone.** The
  ``PROCESSES`` mirror is derived from the zip's own path, but every candidate
  is checked against the zip's sequence uuid and skipped (reported, not
  rewritten) if it belongs to something else.
- **The retag reaches S3 only by re-syncing, and the syncer does not notice a
  handed-back record by itself.** The run ends by extracting the zip into the
  parallel ``RUNS_FINISHED`` directory without its ``.prg``/``.progress``/
  ``.lock`` members and renaming it ``.orig``; dropping the ``.prg`` sidecars
  is what makes a re-sync upload the record again (a ``.prg`` records which of
  a record's files already reached S3, so one restored intact reads as
  finished). **But since the single-``RUNS``-tree cut-over SYNC's startup sweep
  and ``/finish_pending`` scan only ``<root>/RUNS``, so a record in
  ``RUNS_FINISHED`` is never discovered.** It syncs only when its ``-seq.yml``
  is named in ``POST /finish_yml?yml_path=...`` on the station's SYNC server,
  which this tool prints and does not make; the record then syncs in place and
  stays in ``RUNS_FINISHED`` with a complete ``.prg``, beside the ``.orig``.
  There is no API leg: the metadata API is fed from S3 by ingestion outside
  this repo. ``--no-reset`` skips the hand-back and leaves the zip where it
  was, which retags the archive and nothing else. See
  :func:`~helao.core.tests._record_rewrite.reset_to_finished`, including why
  this does not call the syncer's own ``reset_sync`` and why a non-empty
  ``RUNS_FINISHED`` twin is refused.
- **The upload is the syncer's job, not this tool's.** Nothing here talks to
  S3 or the database. Until the station's SYNC server has processed the
  ``/finish_yml`` call, the old tag stands downstream.
"""

__all__ = [
    "Edit",
    "apply_run_use",
    "finished_dir_for",
    "kind_for",
    "process_dir_for",
    "reset_runs_dir",
    "reset_to_finished",
    "rewrite_processes",
    "rewrite_zip",
    "main",
]

import argparse
import os
import sys
import zipfile
from pathlib import Path

from helao.core.models.run_use import RunUse
from helao.core.tests import _record_rewrite
from helao.core.tests._record_rewrite import (
    PROCESS_DIR_NAME,
    Edit,
    _report,
    finish_yml_hint,
    finished_dir_for,
    is_runs_dir,
    kind_for,
    process_dir_for,
    reset_runs_dir,
    reset_to_finished,
    gate_message,
    run_reset_only,
    runs_gate,
)

#: Kinds whose model defines ``run_use`` (``helao.core.models``). A sequence is
#: absent on purpose -- see the module docstring.
_TAGGED_KINDS = frozenset({"action", "experiment", "process"})


def apply_run_use(doc, kind: str, run_use: str) -> list[str]:
    """Retag one loaded yml document in place.

    Args:
        doc: The parsed mapping, round-trip loaded so a re-emit keeps its
            comments and key order.
        kind: One of :data:`_KINDS`' values.
        run_use: The value to write.

    Returns:
        The field paths actually changed (``"run_use"``,
        ``"files[2].run_use"``, ...) -- empty when the document already carried
        the requested value, or when ``kind`` has no such field.
    """
    if kind not in _TAGGED_KINDS:
        return []

    changed: list[str] = []
    if doc.get("run_use") != run_use:
        # Added when absent: every kind reaching this line defines run_use on
        # its model, and an experiment yml on disk usually omits it.
        doc["run_use"] = run_use
        changed.append("run_use")

    files = doc.get("files")
    if isinstance(files, list):
        for i, entry in enumerate(files):
            # Only where recorded. A FileInfo defaults to no run_use at all,
            # and "not recorded" is not the same claim as "recorded as data".
            if not isinstance(entry, dict) or "run_use" not in entry:
                continue
            if entry["run_use"] != run_use:
                entry["run_use"] = run_use
                changed.append(f"files[{i}].run_use")

    return changed


def _retag(run_use: str):
    """The ``apply`` callable :mod:`_record_rewrite` wants, for one tag value."""

    def apply(doc, kind: str) -> "tuple[list[str], str]":
        if kind not in _TAGGED_KINDS:
            return [], "a sequence yml has no run_use field"
        return apply_run_use(doc, kind, run_use), ""

    return apply


def rewrite_zip(
    zip_path: "str | os.PathLike[str]", run_use: str, *, dry_run: bool = False
) -> "tuple[list[Edit], str | None]":
    """Retag every record yml inside one sequence zip.

    Returns:
        ``(edits, sequence_uuid)``; see
        :func:`~helao.core.tests._record_rewrite.rewrite_zip`.
    """
    return _record_rewrite.rewrite_zip(zip_path, _retag(run_use), dry_run=dry_run)


def rewrite_processes(
    process_dir: "str | os.PathLike[str]",
    sequence_uuid: "str | None",
    run_use: str,
    *,
    dry_run: bool = False,
) -> list[Edit]:
    """Retag the ``-prc.yml`` files under ``process_dir``.

    Matched on ``sequence_uuid``; see
    :func:`~helao.core.tests._record_rewrite.rewrite_processes`.
    """
    return _record_rewrite.rewrite_processes(
        process_dir, sequence_uuid, _retag(run_use), dry_run=dry_run
    )


def _refuse_unsynced(problems: "list[str]") -> int:
    print(f"REFUSED: {gate_message(problems)}", file=sys.stderr)
    print("nothing was written.", file=sys.stderr)
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=("Rewrite run_use on a synced sequence zip and its process ymls.")
    )
    parser.add_argument(
        "zip_path",
        help=(
            "the sequence zip under a RUNS_SYNCED tree, or a fully synced "
            "sequence directory under RUNS"
        ),
    )
    parser.add_argument(
        "--run-use",
        default=RunUse.data.value,
        help="the value to write (default: data)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change and write nothing",
    )
    parser.add_argument(
        "--process-dir",
        default=None,
        help=(
            "the PROCESSES directory for this sequence; derived from the zip's "
            "own path when omitted, and skipped entirely if that path has no "
            "RUNS or RUNS_* segment to mirror"
        ),
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help=(
            "leave the retagged zip in RUNS_SYNCED instead of extracting it "
            "back to RUNS_FINISHED (or keep a RUNS sequence's .prg files) for a "
            "/finish_yml re-sync. The retag then reaches nothing downstream: S3 "
            "keeps the old tag"
        ),
    )
    parser.add_argument(
        "--reset-only",
        action="store_true",
        help=(
            "RUNS sequence directory only: edit nothing, delete the remaining "
            ".prg files and print the /finish_yml call -- finishes a --no-reset "
            "run or an interrupted reset"
        ),
    )
    args = parser.parse_args(argv)
    if args.reset_only and args.no_reset:
        parser.error("--reset-only and --no-reset contradict each other")

    try:
        run_use = RunUse(args.run_use).value
    except ValueError:
        parser.error(
            f"unknown run_use {args.run_use!r}; expected one of "
            + ", ".join(m.value for m in RunUse)
        )
        return 2  # unreachable: parser.error exits

    zip_path = Path(args.zip_path)
    if args.reset_only:
        return run_reset_only(zip_path, dry_run=args.dry_run)
    runs = is_runs_dir(zip_path)
    if not runs and not zip_path.is_file():
        print(f"not a file: {zip_path}", file=sys.stderr)
        return 1
    if not runs:
        with zipfile.ZipFile(zip_path) as zf:
            if not any(kind_for(n) and n.endswith(".yml") for n in zf.namelist()):
                # Not "nothing to change": nothing was recognised at all.
                print(f"no record yml in {zip_path}", file=sys.stderr)
                return 1
    unsynced = runs_gate(zip_path) if runs else []
    if unsynced and not args.dry_run:
        return _refuse_unsynced(unsynced)

    if runs:
        zip_edits, sequence_uuid = _record_rewrite.rewrite_dir(
            zip_path, _retag(run_use), dry_run=args.dry_run
        )
        # Processes colocated beside their experiments, in the same tree.
        zip_edits += rewrite_processes(
            zip_path, sequence_uuid, run_use, dry_run=args.dry_run
        )
    else:
        zip_edits, sequence_uuid = rewrite_zip(zip_path, run_use, dry_run=args.dry_run)
    print(f"{zip_path}: sequence_uuid {sequence_uuid}")
    _report(zip_edits)

    process_dir = (
        Path(args.process_dir) if args.process_dir else process_dir_for(zip_path)
    )
    process_edits: list[Edit] = []
    if process_dir is None:
        print(
            "  no RUNS or RUNS_* segment in the path -- external process ymls not "
            "searched (name one with --process-dir)"
        )
    elif not process_dir.is_dir():
        print(f"  no external process directory at {process_dir}")
    else:
        process_edits = rewrite_processes(
            process_dir, sequence_uuid, run_use, dry_run=args.dry_run
        )
        print(f"{process_dir}:")
        _report(process_edits)

    retagged = [e for e in zip_edits + process_edits if e.changed]
    verb = "would retag" if args.dry_run else "retagged"
    print(
        f"{verb} {len(retagged)} yml(s) to run_use={run_use} "
        f"({len([e for e in retagged if e.kind == 'action'])} action, "
        f"{len([e for e in retagged if e.kind == 'experiment'])} experiment, "
        f"{len([e for e in retagged if e.kind == 'process'])} process)"
    )

    if unsynced:
        return _refuse_unsynced(unsynced)
    if not retagged and (args.no_reset or runs):
        # Idempotent re-run: no hand-back, so a RUNS sequence keeps its .prg
        # files and is not re-pushed for nothing. A zip without --no-reset is
        # still handed back, as it always was.
        print(f"nothing to change: every record already has run_use={run_use}")
        if runs and not args.no_reset:
            print(
                "if an earlier --no-reset run made these edits, hand the "
                "sequence back with --reset-only"
            )
        return 0
    if args.no_reset:
        print("--no-reset: the record stays where it is and will not re-sync.")
    elif runs:
        prgs = reset_runs_dir(zip_path, dry_run=args.dry_run)
        print(
            f"{'would delete' if args.dry_run else 'deleted'} {len(prgs)} .prg file(s)"
        )
        if not args.dry_run:
            print(finish_yml_hint(zip_path))
    else:
        ok, dest, note = reset_to_finished(zip_path, dry_run=args.dry_run)
        print(f"{'would reset' if args.dry_run else 'reset'} -> {dest}: {note}")
        if not ok:
            # The retag is already on disk and is not undone by this: the zip
            # is simply still in RUNS_SYNCED, which is where it started.
            print(
                "the record was NOT handed back to the syncer -- it keeps the "
                "old tag everywhere downstream",
                file=sys.stderr,
            )
            return 1
        if not args.dry_run and dest is not None:
            print(finish_yml_hint(dest))

    if args.dry_run:
        print("--dry-run: nothing written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
