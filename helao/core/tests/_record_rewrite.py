"""Shared machinery for the standalone record-rewriting tools.

``set_run_use`` and ``set_plate_id`` both edit an already-synced sequence
record: the yml members of its ``RUNS_SYNCED`` zip, the ``-prc.yml`` files in
the parallel ``PROCESSES`` tree, and then a hand-back to the syncer. Only the
edit itself differs, so the rest lives here and each tool passes an
``apply(doc, kind) -> (changed, note)`` callable.

``apply`` mutates the loaded, round-trip (comment-preserving) document in
place and returns the field descriptions it changed plus a "left alone" note
(either may be empty). A yml with neither is not reported.

Things worth knowing before editing this:

- **A zip cannot be edited in place.** The archive is rebuilt into a staging
  sibling (``file_utils.staging_path``, which is shorter than the name it
  stages and so cannot push a station path past Windows' ``MAX_PATH``) and
  ``os.replace``'d onto the original. Every member a tool does not rewrite is
  copied byte-for-byte with its own ``compress_type``, ``date_time`` and
  attributes, so ``.hlo``/``.prg``/vendor payloads come out unchanged.
- **Process ymls are matched on ``sequence_uuid``, not on path alone.** The
  ``PROCESSES`` mirror is derived from the zip's own path, but every candidate
  is checked against the zip's sequence uuid and skipped (reported, not
  rewritten) if it belongs to something else.
- **Handing the record back does not make the syncer notice it.** See
  :func:`reset_to_finished`.
- **A sequence directory in the single ``RUNS`` tree is the second source.**
  Its records are edited in place in their own format (``.yml`` round-trip,
  comments kept; ``.json`` through ``meta_io.write_meta``), only once
  :func:`unsynced_records` finds every record shipped, and handed back by
  :func:`reset_runs_dir` deleting its ``.prg`` files -- what
  ``SyncDriver.reset_sync`` does to a legacy synced directory. A record whose
  ``.prg`` is not ``synced: true`` may still be mid-upload, so editing it would
  race the syncer. See :func:`runs_gate` for what else refuses.
"""

__all__ = [
    "Edit",
    "PROCESS_DIR_NAME",
    "finish_yml_hint",
    "finished_dir_for",
    "is_runs_dir",
    "kind_for",
    "process_dir_for",
    "reset_runs_dir",
    "reset_to_finished",
    "rewrite_dir",
    "run_reset_only",
    "runs_gate",
    "rewrite_processes",
    "rewrite_zip",
    "unsynced_records",
]

import os
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from helao.core.models.run_dir import RunDir, is_legacy_path
from helao.helpers.file_utils import staging_path
from helao.helpers.meta_io import meta_glob, read_meta, write_meta
from helao.helpers.run_state import _prg_is_complete
from helao.helpers.yml_tools import yml_dumps, yml_load
from helao.hexagon.domain.naming import meta_kind

#: ``apply(doc, kind) -> (changed field descriptions, "left alone" note)``.
Apply = Callable[[dict, str], "tuple[list[str], str]"]

#: The parallel tree older builds wrote process ymls into. Not a ``RunDir``
#: member: it is not a run state, it sits beside ``RUNS_*`` under the station
#: root (see ``helao.helpers.helao_dirs``).
PROCESS_DIR_NAME = "PROCESSES"

#: ``naming.meta_kind`` -> the record kind it names.
_KINDS = {
    "seq": "sequence",
    "exp": "experiment",
    "act": "action",
    "prc": "process",
}


@dataclass
class Edit:
    """One yml a tool looked at, and what it did to it.

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
    """The record kind a ``.yml``/``.json`` name declares, or ``None``."""
    return _KINDS.get(meta_kind(name) or "")


def _load(path: Path):
    """A record as a mapping: ``.yml`` round-trip (comments kept), else JSON.

    Written back with ``meta_io.write_meta``, which keeps each file's format:
    ``yml_dumps`` re-emits a round-trip document with its comments.
    """
    return yml_load(path) if path.suffix == ".yml" else read_meta(path)


def is_runs_dir(path: "str | os.PathLike[str]") -> bool:
    """Whether ``path`` is a sequence directory of the single ``RUNS`` tree."""
    path = Path(path).resolve()
    return path.is_dir() and not is_legacy_path(path) and bool(meta_glob(path, "seq"))


#: Records that carry their own ``.prg``; a process has none.
_SYNCED_KINDS = ("seq", "exp", "act")


def unsynced_records(seq_dir: "str | os.PathLike[str]") -> "list[Path]":
    """Records under ``seq_dir`` whose sibling ``.prg`` is not ``synced: true``."""
    return [
        p
        for p in meta_glob(seq_dir, _SYNCED_KINDS, "**/*")
        if not _prg_is_complete(p.with_suffix(".prg"))
    ]


def _prg_has_write_off(prg: Path) -> bool:
    """Whether ``prg`` carries a top-level ``write_off`` block (flat-text read)."""
    try:
        lines = prg.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    for line in lines:
        if line.startswith("write_off:"):
            return line.split(":", 1)[1].strip() not in ("null", "~", "{}")
    return False


def runs_gate(seq_dir: "str | os.PathLike[str]", *, reset_only: bool = False):
    """Why a ``RUNS`` sequence may not be rewritten or reset; empty when it may.

    - A ``.prg`` with a ``write_off`` block always refuses: the operator wrote
      the experiment off (``SyncDriver.write_off``), and deleting the ``.prg``
      drops that, so a re-sync would park the experiment again forever.
    - An edit run needs every seq/exp/act record's ``.prg`` present and
      ``synced: true``; anything else may still be uploading.
    - ``reset_only`` instead tolerates a *missing* ``.prg`` (an interrupted
      reset already deleted it) and refuses only one that exists unsynced.
    """
    seq_dir = Path(seq_dir)
    prgs = sorted(seq_dir.rglob("*.prg"))
    problems = [
        f"{p}: carries a write_off block" for p in prgs if _prg_has_write_off(p)
    ]
    if reset_only:
        problems += [
            f"{p}: not synced: true (a sync may be in flight)"
            for p in prgs
            if not _prg_is_complete(p)
        ]
    else:
        problems += [
            f"{p}: its .prg is missing or not synced: true"
            for p in unsynced_records(seq_dir)
        ]
    return problems


def gate_message(problems: "list[str]") -> str:
    """The refusal text for :func:`runs_gate`'s ``problems``."""
    return (
        "this sequence cannot be rewritten or reset:\n"
        + "\n".join(f"  {p}" for p in problems)
        + "\na written-off sequence is never reset (it would be re-parked); a "
        ".prg missing after an interrupted reset is finished with --reset-only "
        "(only if an earlier run of this tool made the edits: a record SYNC has "
        "not reached yet also has no .prg)"
    )


def run_reset_only(path: "str | os.PathLike[str]", *, dry_run: bool = False) -> int:
    """``--reset-only``: hand a ``RUNS`` sequence back without editing anything.

    For a sequence whose edits are already on disk -- a ``--no-reset`` run, or
    a reset that stopped part way through deleting the ``.prg`` files.
    """
    path = Path(path)
    if not is_runs_dir(path):
        print(
            f"--reset-only needs a sequence directory under RUNS, not {path}",
            file=sys.stderr,
        )
        return 1
    problems = runs_gate(path, reset_only=True)
    if problems:
        print(f"REFUSED: {gate_message(problems)}", file=sys.stderr)
        print("nothing was written.", file=sys.stderr)
        return 1
    prgs = reset_runs_dir(path, dry_run=dry_run)
    print(f"{'would delete' if dry_run else 'deleted'} {len(prgs)} .prg file(s)")
    if dry_run:
        print("--dry-run: nothing written.")
    else:
        print(finish_yml_hint(path))
    return 0


def rewrite_dir(
    seq_dir: "str | os.PathLike[str]", apply: Apply, *, dry_run: bool = False
) -> "tuple[list[Edit], str | None]":
    """Run ``apply`` over the seq/exp/act records of a ``RUNS`` sequence directory.

    The directory twin of :func:`rewrite_zip`, editing each record in place.
    Processes are left to :func:`rewrite_processes`, which checks their
    ``sequence_uuid``. The caller gates on :func:`unsynced_records` first.
    """
    seq_dir = Path(seq_dir)
    edits: list[Edit] = []
    sequence_uuid: "str | None" = None
    for path in meta_glob(seq_dir, _SYNCED_KINDS, "**/*"):
        kind = kind_for(path)
        assert kind is not None  # meta_glob filtered on it
        doc = _load(path)
        if not isinstance(doc, dict):
            edits.append(Edit(str(path), kind, note="not a mapping; left alone"))
            continue
        if kind == "sequence" and path.parent == seq_dir:
            uuid = doc.get("sequence_uuid")
            if uuid is not None:
                sequence_uuid = str(uuid)
        changed, note = apply(doc, kind)
        if changed and not dry_run:
            write_meta(path, doc)
        if changed or note:
            edits.append(Edit(str(path), kind, changed, note))
    return edits, sequence_uuid


def reset_runs_dir(
    seq_dir: "str | os.PathLike[str]", *, dry_run: bool = False
) -> "list[Path]":
    """Delete every ``.prg`` under ``seq_dir`` so SYNC re-pushes the sequence.

    Returns the ``.prg`` files deleted (or, with ``dry_run``, that would be).
    """
    prgs = sorted(Path(seq_dir).rglob("*.prg"))
    if not dry_run:
        for prg in prgs:
            prg.unlink()
    return prgs


def rewrite_zip(
    zip_path: "str | os.PathLike[str]", apply: Apply, *, dry_run: bool = False
) -> "tuple[list[Edit], str | None]":
    """Run ``apply`` over every record yml inside one sequence zip.

    Returns:
        ``(edits, sequence_uuid)``. The uuid comes from the ``-seq.yml`` and is
        what :func:`rewrite_processes` matches the external process ymls
        against; ``None`` if the zip carries no readable sequence yml, in which
        case those ymls cannot be safely identified and are left alone.

    Raises:
        zipfile.BadZipFile: If the archive cannot be read. Nothing is written
            in that case -- the rebuild only starts once every member has been
            read and rewritten in memory.
    """
    zip_path = Path(zip_path)
    edits: list[Edit] = []
    payload: dict[str, bytes] = {}
    sequence_uuid: "str | None" = None

    with zipfile.ZipFile(zip_path) as zin:
        infos = zin.infolist()
        for info in infos:
            kind = kind_for(info.filename)
            if kind is None or not info.filename.endswith(".yml"):
                continue
            doc = yml_load(zin.read(info).decode())
            if not isinstance(doc, dict):
                edits.append(
                    Edit(info.filename, kind, note="not a yml mapping; left alone")
                )
                continue
            if kind == "sequence":
                uuid = doc.get("sequence_uuid")
                if uuid is not None:
                    sequence_uuid = str(uuid)
            changed, note = apply(doc, kind)
            if changed:
                payload[info.filename] = yml_dumps(doc).encode()
            if changed or note:
                edits.append(Edit(info.filename, kind, changed, note))

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
                    # the point is that everything a tool did not rewrite
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
    """Hand the rewritten record back for re-syncing.

    Extracts the zip into the parallel ``RUNS_FINISHED`` directory **without
    its ``.prg``/``.progress``/``.lock`` members** and renames the zip to
    ``.orig``. Dropping the progress sidecars is what makes a re-sync upload
    the record again: a ``.prg`` records which of a record's files already
    reached S3, so a record restored with them intact reads as finished.

    **This does not make the syncer notice the record.** Since the
    single-``RUNS``-tree cut-over, SYNC's startup sweep and ``/finish_pending``
    scan only ``<root>/RUNS``; a record extracted into ``RUNS_FINISHED`` is
    never discovered. It syncs only when its ``-seq.yml`` is named in
    ``POST /finish_yml?yml_path=...`` (see :func:`finish_yml_hint`), it then
    syncs *in place* and stays in ``RUNS_FINISHED`` with a complete ``.prg``,
    beside the ``.orig`` in ``RUNS_SYNCED``. There is no API leg either: the
    metadata API is fed from S3 by ingestion outside this repo.

    **Why not just call ``SyncDriver.reset_sync``, which does this.** It
    refuses any zip with no ``-seq.prg`` member, and a batch-converted record
    has none: the XRFS record measured while writing this is 506 members, 203
    ymls and 303 hlos, and not one ``.prg``. Those are exactly the records a
    rewrite is most likely to be aimed at. The validity check here is a
    readable ``-seq.yml`` instead, which the caller has already parsed by the
    time it gets here. Everything else matches ``reset_sync``'s zip branch,
    including leaving the zip alone when an ``.orig`` is already beside it.

    **A non-empty ``RUNS_FINISHED`` twin is refused.** ``extractall`` would
    merge the rewritten members into whatever is there -- an earlier record
    synced in place, or a half-finished extraction. The one crash state that
    turns into this refusal: a crash after ``extractall`` and before the
    ``.orig`` rename leaves the zip in place **and** a non-empty twin, so a
    re-run refuses. The manual step is to confirm the syncer's ``/tasks`` names
    nothing under the twin and that no ``/finish_yml`` was posted for it, then
    ``rm -r`` exactly that twin directory and re-run. The refusal note prints
    the twin's path.

    Returns:
        ``(ok, dest, note)``. ``dest`` is where the record was (or would be)
        extracted, ``None`` when the path is not under ``RUNS_SYNCED``.
    """
    zip_path = Path(zip_path)
    dest = finished_dir_for(zip_path)
    if dest is None:
        return False, None, f"not under {RunDir.SYNCED.value}; not reset"
    if dest.is_dir() and any(dest.iterdir()):
        return (
            False,
            dest,
            f"{dest} already exists and is not empty; nothing extracted. If it "
            "is a crashed earlier extraction of this record: confirm the "
            "syncer's /tasks names nothing under it and that no /finish_yml was "
            f"posted for it, then rm -r exactly {dest} and re-run",
        )

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


def finish_yml_hint(dest: Path) -> str:
    """The call that makes the syncer pick up a record handed back to ``dest``.

    ``dest`` is a ``RUNS_FINISHED`` twin or a ``RUNS`` sequence directory; the
    sequence record named is whichever format is on disk, as an absolute
    path. The tools print it and never make it: posting is a production write.
    """
    dest = Path(dest).resolve()
    seqs = sorted(meta_glob(dest, "seq", "**/*"), key=lambda p: (len(p.parts), str(p)))
    target = seqs[0] if seqs else dest / "<sequence>-seq.yml"
    hint = f"next: POST /finish_yml?yml_path={target} on the station's SYNC server"
    if not is_legacy_path(dest):
        return hint
    return (
        f"{hint} -- the syncer does not discover records in RUNS_FINISHED by "
        "itself; the record then syncs in place and stays there"
    )


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
    ``<root>/PROCESSES/<week>/<day>/<seq>/``, and likewise for a
    ``<root>/RUNS/<year>/<day>/<seq>`` directory. ``None`` when the path has no
    ``RUNS``/``RUNS_*`` segment to mirror, which is also the case for a zip
    copied out of a station tree -- there the caller must name the directory
    explicitly.
    """
    parts = Path(zip_path).resolve().parts
    idx = next(
        (
            i
            for i, part in enumerate(parts)
            if part == "RUNS" or part.startswith("RUNS_")
        ),
        None,
    )
    if idx is None:
        return None
    root = Path(*parts[:idx])
    rel = Path(*parts[idx + 1 :])
    if rel.suffix == ".zip":
        rel = rel.with_suffix("")
    return root / PROCESS_DIR_NAME / rel


def rewrite_processes(
    process_dir: "str | os.PathLike[str]",
    sequence_uuid: "str | None",
    apply: Apply,
    *,
    dry_run: bool = False,
) -> list[Edit]:
    """Run ``apply`` over the ``-prc`` records (``.yml``/``.json``) under ``process_dir``.

    Every candidate is checked against ``sequence_uuid`` first: the directory
    is derived from a path convention, and a mirrored directory that turns out
    to hold another sequence's processes is reported and left alone rather
    than rewritten. A ``sequence_uuid`` of ``None`` (no readable sequence yml
    in the zip) skips every file for the same reason.
    """
    process_dir = Path(process_dir)
    edits: list[Edit] = []
    for path in meta_glob(process_dir, "prc", "**/*"):
        doc = _load(path)
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
        changed, note = apply(doc, "process")
        if not changed:
            if note:
                edits.append(Edit(str(path), "process", note=note))
            continue
        edits.append(Edit(str(path), "process", changed, note))
        if not dry_run:
            write_meta(path, doc)
    return edits


def _report(edits: list[Edit]) -> None:
    for edit in edits:
        if edit.changed:
            print(f"  {edit.kind:10s} {edit.path}: {', '.join(edit.changed)}")
        elif edit.note:
            print(f"  {edit.kind:10s} {edit.path}: {edit.note}")
