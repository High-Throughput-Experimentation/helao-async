"""Rewrite the ``run_use`` tag on an already-synced sequence record.

```
python -m helao.core.tests.set_run_use <RUNS_SYNCED/.../<sequence>.zip> \
    [--run-use data] [--dry-run] [--no-reset] [--process-dir DIR]
```

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
- **The retag reaches S3 and the API only by re-syncing, so the run ends by
  handing the record back.** The zip is extracted into the parallel
  ``RUNS_FINISHED`` directory without its ``.prg``/``.progress``/``.lock``
  members and renamed to ``.orig``; the syncer then picks the record up as
  unfinished work and re-uploads it. **Dropping the ``.prg`` sidecars is the
  whole mechanism** -- a ``.prg`` records which of a record's files already
  reached S3 and the API, so a record restored with them intact reads as
  finished and is never re-uploaded. ``--no-reset`` skips this and leaves the
  zip where it was, which retags the archive and nothing else. See
  :func:`reset_to_finished` for why this does not call the syncer's own
  ``reset_sync``.
- **The upload is the syncer's job, not this tool's.** Nothing here talks to
  S3 or the database; the record simply becomes eligible again. Until the
  station's SYNC server processes it, the old tag stands downstream.
"""

__all__ = [
    "Edit",
    "apply_run_use",
    "finished_dir_for",
    "kind_for",
    "process_dir_for",
    "reset_to_finished",
    "rewrite_processes",
    "rewrite_zip",
    "main",
]

import argparse
import os
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from helao.core.models.run_dir import RunDir
from helao.core.models.run_use import RunUse
from helao.helpers.file_utils import staging_path
from helao.helpers.yml_tools import yml_dumps, yml_load

#: The parallel tree older builds wrote process ymls into. Not a ``RunDir``
#: member: it is not a run state, it sits beside ``RUNS_*`` under the station
#: root (see ``helao.helpers.helao_dirs``).
PROCESS_DIR_NAME = "PROCESSES"

#: Record yml suffix -> the record kind it names.
_KINDS = {
    "-seq.yml": "sequence",
    "-exp.yml": "experiment",
    "-act.yml": "action",
    "-prc.yml": "process",
}

#: Kinds whose model defines ``run_use`` (``helao.core.models``). A sequence is
#: absent on purpose -- see the module docstring.
_TAGGED_KINDS = frozenset({"action", "experiment", "process"})


@dataclass
class Edit:
    """One yml this tool looked at, and what it did to it.

    An entry with an empty ``changed`` and a ``note`` is something deliberately
    left alone: a sequence yml, or a process yml belonging to another sequence.
    An entry with an empty ``changed`` and no note is not reported at all --
    the value was already what was asked for.
    """

    path: str
    kind: str
    changed: list[str] = field(default_factory=list)
    note: str = ""


def kind_for(name: "str | os.PathLike[str]") -> "str | None":
    """The record kind a yml's name declares, or ``None`` if it names none."""
    text = str(name)
    for suffix, kind in _KINDS.items():
        if text.endswith(suffix):
            return kind
    return None


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


def rewrite_zip(
    zip_path: "str | os.PathLike[str]", run_use: str, *, dry_run: bool = False
) -> "tuple[list[Edit], str | None]":
    """Retag every record yml inside one sequence zip.

    Returns:
        ``(edits, sequence_uuid)``. The uuid comes from the ``-seq.yml`` and is
        what :func:`rewrite_processes` matches the external process ymls
        against; ``None`` if the zip carries no readable sequence yml, in which
        case those ymls cannot be safely identified and are left alone.

    Raises:
        zipfile.BadZipFile: If the archive cannot be read. Nothing is written
            in that case -- the rebuild only starts once every member has been
            read and retagged in memory.
    """
    zip_path = Path(zip_path)
    edits: list[Edit] = []
    payload: dict[str, bytes] = {}
    sequence_uuid: "str | None" = None

    with zipfile.ZipFile(zip_path) as zin:
        infos = zin.infolist()
        for info in infos:
            kind = kind_for(info.filename)
            if kind is None:
                continue
            doc = yml_load(zin.read(info).decode())
            if kind == "sequence":
                uuid = doc.get("sequence_uuid") if isinstance(doc, dict) else None
                if uuid is not None:
                    sequence_uuid = str(uuid)
                edits.append(
                    Edit(
                        info.filename,
                        kind,
                        note="a sequence yml has no run_use field",
                    )
                )
                continue
            if not isinstance(doc, dict):
                edits.append(
                    Edit(info.filename, kind, note="not a yml mapping; left alone")
                )
                continue
            changed = apply_run_use(doc, kind, run_use)
            if changed:
                payload[info.filename] = yml_dumps(doc).encode()
                edits.append(Edit(info.filename, kind, changed))

        if dry_run or not payload:
            return edits, sequence_uuid

        staged = staging_path(zip_path)
        try:
            with zipfile.ZipFile(staged, "w") as zout:
                for info in infos:
                    data = payload.get(info.filename)
                    if data is None:
                        data = zin.read(info)
                    # Rebuilt member by member rather than copied wholesale:
                    # the point is that everything this tool did not retag
                    # comes out identical, compression and timestamps included.
                    out = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                    out.compress_type = info.compress_type
                    out.external_attr = info.external_attr
                    out.internal_attr = info.internal_attr
                    out.create_system = info.create_system
                    out.comment = info.comment
                    zout.writestr(out, data)
        except BaseException:
            # Including KeyboardInterrupt: a half-written staging file beside a
            # station record is exactly the litter the .tmp convention exists
            # to keep out of the syncer's upload glob, and it is only safe to
            # remove here, before anything has been replaced.
            if os.path.exists(staged):
                os.remove(staged)
            raise

    # Outside the read handle: on Windows the original cannot be replaced while
    # it is still open.
    os.replace(staged, zip_path)
    return edits, sequence_uuid


#: Suffixes dropped on the way out of the zip. ``.prg``/``.progress`` are the
#: syncer's own progress sidecars and ``.lock`` its file lock; a record
#: restored with them reads as already finished.
_SYNC_STATE_SUFFIXES = (".prg", ".progress", ".lock")


def reset_to_finished(
    zip_path: "str | os.PathLike[str]", *, dry_run: bool = False
) -> "tuple[bool, Path | None, str]":
    """Hand the retagged record back to the syncer.

    Extracts the zip into the parallel ``RUNS_FINISHED`` directory **without
    its ``.prg``/``.progress``/``.lock`` members** and renames the zip to
    ``.orig``. Dropping the progress sidecars is the whole mechanism: a
    ``.prg`` records which of a record's files already reached S3 and the API,
    so a record restored with them intact reads as finished and is never
    re-uploaded.

    **Why not just call ``SyncDriver.reset_sync``, which does this.** It
    refuses any zip with no ``-seq.prg`` member, and a batch-converted record
    has none: the XRFS record measured while writing this is 506 members, 203
    ymls and 303 hlos, and not one ``.prg``. Those are exactly the records a
    retag is most likely to be aimed at. The validity check here is a readable
    ``-seq.yml`` instead, which this tool has already parsed by the time it
    gets here. Everything else matches ``reset_sync``'s zip branch, including
    leaving the zip alone when an ``.orig`` is already beside it.

    Returns:
        ``(ok, dest, note)``. ``dest`` is where the record was (or would be)
        extracted, ``None`` when the path is not under ``RUNS_SYNCED``.
    """
    zip_path = Path(zip_path)
    dest = finished_dir_for(zip_path)
    if dest is None:
        return False, None, f"not under {RunDir.SYNCED.value}; not reset"

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if not any(n.endswith("-seq.yml") for n in names):
            return False, dest, "no -seq.yml member; not a sequence record"
        keep = [n for n in names if not n.endswith(_SYNC_STATE_SUFFIXES)]
        dropped = len(names) - len(keep)
        if dry_run:
            return (
                True,
                dest,
                f"would extract {len(keep)} member(s) here, dropping {dropped} "
                "sync-state file(s), and rename the zip .orig",
            )
        dest.mkdir(parents=True, exist_ok=True)
        zf.extractall(dest, members=keep)

    note = f"extracted {len(keep)} member(s), dropped {dropped} sync-state file(s)"
    orig = zip_path.with_suffix(".orig")
    if orig.exists():
        # Same rule as reset_sync: an .orig already there is an earlier
        # reset's, and overwriting it would destroy the only copy of the
        # record as it was before that one.
        return True, dest, note + "; zip left in place (an .orig already exists)"
    os.replace(zip_path, orig)
    return True, dest, note + f"; zip renamed {orig.name}"


def finished_dir_for(zip_path: "str | os.PathLike[str]") -> "Path | None":
    """Where a reset record goes: ``zip_path``'s ``RUNS_FINISHED`` twin.

    Computed the same way ``SyncDriver.reset_sync`` computes it -- character
    for character, as the ECMS backlog converter's ``_finished_dir_for_zip``
    also does, because that method returns a bool and never the path it used.
    """
    zip_path = Path(zip_path)
    if RunDir.SYNCED.value not in zip_path.parts:
        return None
    parent = str(zip_path.parent).replace(RunDir.SYNCED.value, RunDir.FINISHED.value)
    return Path(parent) / zip_path.stem


def process_dir_for(zip_path: "str | os.PathLike[str]") -> "Path | None":
    """The ``PROCESSES`` directory mirroring ``zip_path``'s own run tree.

    ``<root>/RUNS_SYNCED/<week>/<day>/<seq>.zip`` ->
    ``<root>/PROCESSES/<week>/<day>/<seq>/``. ``None`` when the path has no
    ``RUNS_*`` segment to mirror, which is also the case for a zip copied out
    of a station tree -- there the caller must name the directory explicitly.
    """
    parts = Path(zip_path).resolve().parts
    idx = next(
        (i for i, part in enumerate(parts) if part.startswith("RUNS_")),
        None,
    )
    if idx is None:
        return None
    root = Path(*parts[:idx])
    rel = Path(*parts[idx + 1 :])
    return root / PROCESS_DIR_NAME / rel.with_suffix("")


def rewrite_processes(
    process_dir: "str | os.PathLike[str]",
    sequence_uuid: "str | None",
    run_use: str,
    *,
    dry_run: bool = False,
) -> list[Edit]:
    """Retag the ``-prc.yml`` files under ``process_dir``.

    Every candidate is checked against ``sequence_uuid`` first: the directory
    is derived from a path convention, and a mirrored directory that turns out
    to hold another sequence's processes is reported and left alone rather
    than rewritten. A ``sequence_uuid`` of ``None`` (no readable sequence yml
    in the zip) skips every file for the same reason.
    """
    process_dir = Path(process_dir)
    edits: list[Edit] = []
    for path in sorted(process_dir.rglob("*-prc.yml")):
        doc = yml_load(path)
        if not isinstance(doc, dict):
            edits.append(Edit(str(path), "process", note="not a yml mapping"))
            continue
        found = doc.get("sequence_uuid")
        if sequence_uuid is None or str(found) != sequence_uuid:
            edits.append(
                Edit(
                    str(path),
                    "process",
                    note=f"sequence_uuid {found} is not this record's; left alone",
                )
            )
            continue
        changed = apply_run_use(doc, "process", run_use)
        if not changed:
            continue
        edits.append(Edit(str(path), "process", changed))
        if dry_run:
            continue
        staged = staging_path(path)
        try:
            with open(staged, "w") as fh:
                fh.write(yml_dumps(doc))
        except BaseException:
            if os.path.exists(staged):
                os.remove(staged)
            raise
        os.replace(staged, path)
    return edits


def _report(edits: list[Edit]) -> None:
    for edit in edits:
        if edit.changed:
            print(f"  {edit.kind:10s} {edit.path}: {', '.join(edit.changed)}")
        elif edit.note:
            print(f"  {edit.kind:10s} {edit.path}: {edit.note}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=("Rewrite run_use on a synced sequence zip and its process ymls.")
    )
    parser.add_argument(
        "zip_path", help="the sequence zip, normally under a RUNS_SYNCED tree"
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
            "RUNS_* segment to mirror"
        ),
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help=(
            "leave the retagged zip in RUNS_SYNCED instead of extracting it "
            "back to RUNS_FINISHED for the syncer to pick up. The retag then "
            "reaches nothing downstream: S3 and the API keep the old tag"
        ),
    )
    args = parser.parse_args(argv)

    try:
        run_use = RunUse(args.run_use).value
    except ValueError:
        parser.error(
            f"unknown run_use {args.run_use!r}; expected one of "
            + ", ".join(m.value for m in RunUse)
        )
        return 2  # unreachable: parser.error exits

    zip_path = Path(args.zip_path)
    if not zip_path.is_file():
        print(f"not a file: {zip_path}", file=sys.stderr)
        return 1

    zip_edits, sequence_uuid = rewrite_zip(zip_path, run_use, dry_run=args.dry_run)
    print(f"{zip_path}: sequence_uuid {sequence_uuid}")
    _report(zip_edits)

    process_dir = (
        Path(args.process_dir) if args.process_dir else process_dir_for(zip_path)
    )
    process_edits: list[Edit] = []
    if process_dir is None:
        print(
            "  no RUNS_* segment in the path -- external process ymls not "
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

    if args.no_reset:
        print("--no-reset: the record stays in RUNS_SYNCED and will not re-sync.")
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

    if args.dry_run:
        print("--dry-run: nothing written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
