"""Correct a plate serial that was recorded as the plate id, in synced records.

```
python -m helao.core.tests.set_plate_id record <RUNS_SYNCED/.../<seq>.zip> --old OLD --new NEW \
    [--dry-run] [--no-reset] [--process-dir DIR] [--allow-serial-mismatch]
python -m helao.core.tests.set_plate_id analyses <PROCESSES/.../<seq dir>> --sequence-uuid UUID \
    --old OLD --new NEW --analyses-root DIR [--analysis-dir DIR ...] \
    [--bucket BUCKET] [--dry-run] \
    [--allow-serial-mismatch]
```

``OLD`` is the wrong value (a 6-digit plate serial: the plate id plus one check
digit) and ``NEW`` the plate id it should have been. ``record`` rewrites the
plate identity in one synced sequence zip and in its external ``PROCESSES``
ymls, then hands the record back (``_record_rewrite.reset_to_finished``);
``analyses`` rewrites the two label fields of the record's analysis ymls and
overwrites the same ``analysis/<uuid>.json`` body in S3.

Things worth knowing before editing this:

- **Every rewrite targets a field; nothing is a string or byte replace.** A
  serial's digits turn up as numeric coincidences in ``.hlo`` data values
  (``0.1234559999``) and in analysis output arrays, so a text replace would
  corrupt data. :func:`rewrite_doc` holds the rules in one place: the tool that
  writes and any check that judges the result import the same function, so
  they cannot disagree about what counts as plate identity.
- **What is rewritten, and what is left.** ``sequence_params.plate_id``;
  ``samples_in[]``/``samples_out[]`` ``plate_id`` and the
  ``legacy__solid__{OLD}_`` prefix of ``global_label``; the same prefix in
  ``files[].sample[]``; and, for analyses, ``global_sample_label`` and
  ``inputs[].global_sample_label``. Labels that do not start with that exact
  prefix (every standard's label, a sample with no plate) are untouched. A
  value that still carries ``OLD``'s digits after the rules have run is LEFT
  when its key is a path (``*_output_dir``, ``source_foldername``) and
  UNCLASSIFIED otherwise, **and any UNCLASSIFIED occurrence makes the tool
  refuse the whole record with nothing written.** Floats are never inspected.
- **The plate is checked against the plate API first, and fails closed.** NEW
  must exist, and its ``serial_no`` must be OLD, unless
  ``--allow-serial-mismatch`` says the wrong value was not the serial. An
  unreachable API refuses too: absent and unreachable are different answers.
  Both subcommands check first; ``analyses`` also refuses when no analysis yml
  belongs to the sequence, and counts an analysis whose S3 body cannot be read
  as failed (exit 1) without stopping the run.
- **The re-sync is not automatic.** ``record`` prints the ``POST /finish_yml``
  call that makes the syncer pick the record up and never makes it; see
  :func:`~helao.core.tests._record_rewrite.reset_to_finished`.
- **An ``analyses`` body is overwritten under the same uuid.** The uuid hashes
  the label, so regenerating one would mint a duplicate record. S3 is written
  first and the yml second, so "the yml is new" implies "S3 is new"; a re-run
  after a crash between the two writes only the yml.
"""

__all__ = ["rewrite_doc", "main"]

import argparse
import asyncio
import json
import os
import re
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path

from helao.core.drivers.data import analysis_layout
from helao.core.tests import _record_rewrite
from helao.core.tests._record_rewrite import (
    Edit,
    finish_yml_hint,
    finished_dir_for,
    process_dir_for,
    reset_to_finished,
)
from helao.helpers.file_utils import staging_path
from helao.helpers.plate_api import HTEPlateAPI, PlateAPIUnavailable
from helao.helpers.yml_tools import yml_dumps, yml_load

#: Record kinds as ``_record_rewrite`` names them -> the kinds ``rewrite_doc`` takes.
_SHORT = {"sequence": "seq", "experiment": "exp", "action": "act", "process": "prc"}
_DOC_KINDS = frozenset({"seq", "exp", "act", "prc", "analysis"})

_UNCLASSIFIED = "UNCLASSIFIED "
_LEFT = "LEFT "

#: Bytes of an analysis yml read to pre-filter it on process_uuid (the key sits
#: near line 23 of ~495 lines). A miss is caught by the refusal on zero matches
#: and by the dry-run's expected per-record counts.
_HEADER_BYTES = 8192


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _relabel(label, old: int, new: int) -> "str | None":
    """``label`` with its ``legacy__solid__{old}_`` prefix swapped, else ``None``."""
    prefix = f"legacy__solid__{old}_"
    if isinstance(label, str) and label.startswith(prefix):
        return f"legacy__solid__{new}_" + label[len(prefix) :]
    return None


def _set_label(holder, key, path: str, old: int, new: int, changes: list) -> None:
    fixed = _relabel(holder[key], old, new)
    if fixed is not None:
        changes.append(f"{path} {holder[key]} -> {fixed}")
        holder[key] = fixed


def _apply_rules(doc, kind: str, old: int, new: int) -> "list[str]":
    """Rewrite the plate-identity fields of ``doc`` in place; return the changes."""
    changes: list[str] = []
    if kind == "seq":
        params = doc.get("sequence_params")
        if isinstance(params, dict):
            v = params.get("plate_id")
            if _is_int(v) and v == old:
                params["plate_id"] = new
                changes.append(f"sequence_params.plate_id {old} -> {new}")
            elif isinstance(v, str) and v == str(old):
                params["plate_id"] = str(new)
                changes.append(f"sequence_params.plate_id {v} -> {new}")
    if kind in ("exp", "act", "prc"):
        for key in ("samples_in", "samples_out"):
            for i, sample in enumerate(doc.get(key) or []):
                if not isinstance(sample, dict):
                    continue
                if _is_int(sample.get("plate_id")) and sample["plate_id"] == old:
                    sample["plate_id"] = new
                    changes.append(f"{key}[{i}].plate_id {old} -> {new}")
                if "global_label" in sample:
                    _set_label(
                        sample,
                        "global_label",
                        f"{key}[{i}].global_label",
                        old,
                        new,
                        changes,
                    )
        for i, entry in enumerate(doc.get("files") or []):
            labels = entry.get("sample") if isinstance(entry, dict) else None
            if isinstance(labels, list):
                for j in range(len(labels)):
                    _set_label(labels, j, f"files[{i}].sample[{j}]", old, new, changes)
    if kind == "analysis":
        if "global_sample_label" in doc:
            _set_label(
                doc, "global_sample_label", "global_sample_label", old, new, changes
            )
        for i, entry in enumerate(doc.get("inputs") or []):
            if isinstance(entry, dict) and "global_sample_label" in entry:
                _set_label(
                    entry,
                    "global_sample_label",
                    f"inputs[{i}].global_sample_label",
                    old,
                    new,
                    changes,
                )
    return changes


def _scan(node, key: str, path: str, old: int, left: list, unclassified: list) -> None:
    """Collect every remaining occurrence of ``old`` in ``node``'s values."""
    if isinstance(node, dict):
        for k, v in node.items():
            _scan(v, str(k), f"{path}.{k}" if path else str(k), old, left, unclassified)
        return
    if isinstance(node, list):
        for i, v in enumerate(node):
            _scan(v, key, f"{path}[{i}]", old, left, unclassified)
        return
    if isinstance(node, bool) or isinstance(node, float):
        return  # floats hold the numeric coincidences; never inspected
    if _is_int(node):
        hit = node == old
    elif isinstance(node, str):
        hit = str(old) in node
    else:
        return
    if not hit:
        return
    if key.endswith("_output_dir") or key == "source_foldername":
        left.append(re.sub(r"\[\d+\]", "[]", path))
    else:
        unclassified.append(f"{path} = {str(node)[:120]}")


def _rewrite(doc, kind: str, old: int, new: int):
    """Rewrite ``doc`` in place; return ``(changes, left, unclassified)``."""
    if kind not in _DOC_KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {sorted(_DOC_KINDS)}")
    changes = _apply_rules(doc, kind, old, new)
    left: list[str] = []
    unclassified: list[str] = []
    _scan(doc, "", "", old, left, unclassified)
    return changes, left, unclassified


def rewrite_doc(
    doc, kind: str, old: int, new: int
) -> "tuple[dict, list[str], list[str]]":
    """Apply the plate-identity rules to one yml document or S3 body.

    Args:
        doc: The parsed mapping. Never mutated.
        kind: ``seq``, ``exp``, ``act``, ``prc`` or ``analysis``.
        old: The wrong value (the serial).
        new: The right value (the plate id).

    Returns:
        ``(new_doc, changes, unclassified)``: a rewritten deep copy, one
        ``"<path> <old> -> <new>"`` line per field changed, and every other
        occurrence of ``old`` that is neither a rewritten field nor a path
        (``"<path> = <value>"``). A caller must treat any unclassified
        occurrence as a refusal.
    """
    out = deepcopy(doc)
    changes, _left, unclassified = _rewrite(out, kind, old, new)
    return out, changes, unclassified


def _applier(old: int, new: int, seen: dict):
    """The ``apply`` callable for ``_record_rewrite``; ``seen`` collects side facts."""

    def apply(doc, kind: str) -> "tuple[list[str], str]":
        short = _SHORT[kind]
        if short == "seq":
            params = doc.get("sequence_params")
            if isinstance(params, dict):
                seen["seq_plate_id"] = params.get("plate_id")
        changes, left, unclassified = _rewrite(doc, short, old, new)
        lines = [f"{_LEFT}{p} x{n}" for p, n in sorted(Counter(left).items())]
        lines += [f"{_UNCLASSIFIED}{u}" for u in unclassified]
        return changes, "\n".join(lines)

    return apply


def _note_lines(edits: "list[Edit]", prefix: str):
    for edit in edits:
        for line in edit.note.splitlines():
            if line.startswith(prefix):
                yield edit.path, line[len(prefix) :]


def _print_edits(edits: "list[Edit]") -> None:
    for edit in edits:
        short = _SHORT.get(edit.kind, edit.kind)
        for change in edit.changed:
            print(f"  {short} {edit.path}: {change}")
        for line in edit.note.splitlines():
            print(f"  {short} {edit.path}: {line}")


def _refuse(message: str) -> int:
    print(f"REFUSED: {message}", file=sys.stderr)
    print("nothing was written.", file=sys.stderr)
    return 1


def _check_plate(old: int, new: int, allow_serial_mismatch: bool) -> "str | None":
    """Return a refusal reason, or ``None`` when NEW is this plate and OLD its serial."""
    try:
        rec = HTEPlateAPI().lookup_plate(new)
    except PlateAPIUnavailable as exc:
        return f"the plate API is unavailable ({exc}); cannot confirm plate {new}"
    if rec is None:
        return f"plate {new} does not exist in the plate API"
    serial = rec.get("serial_no")
    print(f"plate {new}: serial_no {serial}")
    if str(serial) != str(old):
        if not allow_serial_mismatch:
            return (
                f"old value {old} is not plate {new}'s serial ({serial}); pass "
                "--allow-serial-mismatch only if the wrong value was not the serial"
            )
        print(
            f"WARNING: old value {old} is not plate {new}'s serial ({serial}); "
            "continuing because of --allow-serial-mismatch"
        )
    return None


def _record(args) -> int:
    old, new = args.old, args.new
    reason = _check_plate(old, new, args.allow_serial_mismatch)
    if reason:
        return _refuse(reason)

    zip_path = Path(args.zip_path)
    if not zip_path.is_file():
        return _refuse(f"not a file: {zip_path}")
    seen: dict = {}
    apply = _applier(old, new, seen)
    try:
        zip_edits, sequence_uuid = _record_rewrite.rewrite_zip(
            zip_path, apply, dry_run=True
        )
    except Exception as exc:  # BadZipFile, a yml that will not parse
        return _refuse(f"cannot read {zip_path}: {type(exc).__name__}: {exc}")

    plate = seen.get("seq_plate_id")
    if sequence_uuid is None or plate is None:
        return _refuse("the zip has no -seq.yml carrying sequence_params.plate_id")
    if str(plate) not in (str(old), str(new)):
        return _refuse(
            f"sequence_params.plate_id is {plate}, expected {old} (or {new} for a re-run)"
        )

    process_dir = (
        Path(args.process_dir) if args.process_dir else process_dir_for(zip_path)
    )
    process_edits: "list[Edit]" = []
    if process_dir is not None and process_dir.is_dir():
        process_edits = _record_rewrite.rewrite_processes(
            process_dir, sequence_uuid, apply, dry_run=True
        )

    bad = list(_note_lines(zip_edits + process_edits, _UNCLASSIFIED))
    if bad:
        return _refuse(
            "unclassified occurrence(s) of "
            f"{old}:\n" + "\n".join(f"  {path}: {item}" for path, item in bad)
        )

    if not args.no_reset:
        if finished_dir_for(zip_path) is None:
            return _refuse(
                f"{zip_path} is not under a RUNS_SYNCED tree to hand back (--no-reset "
                "rewrites the archive only)"
            )
        if zip_path.with_suffix(".orig").exists():
            return _refuse(f"{zip_path.with_suffix('.orig')} already exists")
        twin = finished_dir_for(zip_path)
        if twin is not None and twin.is_dir() and any(twin.iterdir()):
            return _refuse(f"{twin} already exists and is not empty")

    verb = "would make" if args.dry_run else "made"
    print(f"{zip_path}: sequence_uuid {sequence_uuid}")
    if str(plate) == str(new):
        print(f"  sequence_params.plate_id is already {new}: already corrected")
    _print_edits(zip_edits)
    if process_dir is None:
        print("  no RUNS_* segment in the path; external process ymls not searched")
    elif process_dir.is_dir():
        print(f"{process_dir}:")
        _print_edits(process_edits)
    else:
        print(f"  no external process directory at {process_dir}")
    edits = zip_edits + process_edits
    n_changes = sum(len(e.changed) for e in edits)
    n_left = sum(int(line.rsplit(" x", 1)[1]) for _, line in _note_lines(edits, _LEFT))
    print(
        f"{verb} {n_changes} change(s) in {len([e for e in edits if e.changed])} yml(s); "
        f"{n_left} path value(s) left alone"
    )
    if args.dry_run:
        print("--dry-run: nothing written.")
        return 0

    _record_rewrite.rewrite_zip(zip_path, apply)
    if process_dir is not None and process_dir.is_dir():
        _record_rewrite.rewrite_processes(process_dir, sequence_uuid, apply)
    if args.no_reset:
        print("--no-reset: the record stays in RUNS_SYNCED and will not re-sync.")
        return 0
    ok, dest, note = reset_to_finished(zip_path)
    print(f"handback {dest}: {note}")
    if not ok or dest is None:
        print("the record was NOT handed back to the syncer", file=sys.stderr)
        return 1
    print(finish_yml_hint(dest))
    return 0


def _make_loader():
    """The S3 loader for ``analyses``. A module-level seam so tests can fake it."""
    from helao.core.drivers.data.loaders.helao_loader import HelaoLoader

    return HelaoLoader(os.environ["HELAO_CREDENTIALS"])


def _paths(changes: "list[str]") -> "list[str]":
    return [c.split(" ", 1)[0] for c in changes]


def _labels(doc) -> tuple:
    return (
        doc.get("global_sample_label"),
        [i.get("global_sample_label") for i in doc.get("inputs") or []],
    )


def _as_body(doc) -> dict:
    """``doc`` the way it reads after a JSON round trip, for yml-vs-body equality."""
    return json.loads(json.dumps(doc, default=str))


def _process_uuids(process_dir: Path, sequence_uuid: str) -> "set[str]":
    found: set[str] = set()
    for path in sorted(process_dir.rglob("*-prc.yml")):
        doc = yml_load(path)
        if not isinstance(doc, dict) or str(doc.get("sequence_uuid")) != sequence_uuid:
            print(f"  {path}: not this sequence's process; skipped")
            continue
        found.add(str(doc.get("process_uuid")))
    return found


def _write_yml(path: Path, doc) -> None:
    staged = staging_path(path)
    try:
        with open(staged, "w", encoding="utf-8") as fh:
            fh.write(yml_dumps(doc))
    except BaseException:
        if os.path.exists(staged):
            os.remove(staged)
        raise
    os.replace(staged, path)


def _analysis_candidates(args) -> list:
    """The analysis ymls to consider: the named directories, else the whole tree."""
    root = Path(args.analyses_root)
    dirs = getattr(args, "analysis_dir", None)
    if not dirs:
        return sorted(root.glob("*/*/*/*.yml"))
    found = []
    for d in dirs:
        path = Path(d)
        if not path.is_absolute():
            path = root.parent / path
        if not path.is_dir():
            raise FileNotFoundError(f"--analysis-dir {d} is not a directory")
        found.extend(sorted(path.glob("*.yml")))
    return found


def _analyses(args) -> int:
    old, new = args.old, args.new
    reason = _check_plate(old, new, args.allow_serial_mismatch)
    if reason:
        return _refuse(reason)
    process_dir = Path(args.process_dir)
    if not process_dir.is_dir():
        return _refuse(f"not a directory: {process_dir}")
    uuids = _process_uuids(process_dir, args.sequence_uuid)
    if not uuids:
        return _refuse(
            f"no process of sequence {args.sequence_uuid} under {process_dir}"
        )
    ymls = []
    try:
        candidates = _analysis_candidates(args)
    except FileNotFoundError as exc:
        return _refuse(str(exc))
    for path in candidates:
        # A station's ANALYSES tree can hold ~10^5 ymls; parsing each one to
        # read its process_uuid took over half an hour. The uuid is near the
        # top of every analysis yml, so a header without any of this
        # sequence's process uuids is skipped unparsed. A header naming no
        # process_uuid at all is still parsed, so a reordered yml is not lost.
        with open(path, encoding="utf-8", errors="replace") as fh:
            head = fh.read(_HEADER_BYTES)
        if "process_uuid" in head and not any(u in head for u in uuids):
            continue
        doc = yml_load(path)
        if isinstance(doc, dict) and str(doc.get("process_uuid")) in uuids:
            ymls.append((path, doc))
    if not ymls:
        return _refuse(
            f"no analysis yml under {args.analyses_root} belongs to sequence "
            f"{args.sequence_uuid}"
        )

    try:
        loader = _make_loader()
    except Exception as exc:
        return _refuse(f"cannot build the S3 loader: {type(exc).__name__}: {exc}")
    if getattr(loader, "cli", None) is None:
        # upload_json(None, ...) logs "S3 is not configured" and reports success,
        # which would let every yml be written with nothing uploaded.
        return _refuse("the S3 client is not configured; nothing could be uploaded")
    bucket = args.bucket or loader.s3_bucket
    print(f"bucket {bucket}; {len(ymls)} analysis yml(s) for {len(uuids)} process(es)")

    failed = 0
    n_changes = 0
    n_uploads = 0
    for path, ydoc in ymls:
        uuid = str(ydoc.get("analysis_uuid") or path.stem)
        key = analysis_layout.analysis_model_key(uuid)
        ynew, ychanges, yunc = rewrite_doc(ydoc, "analysis", old, new)
        try:
            body = json.loads(loader.get_bytes(bucket, key).read())
        except Exception as exc:  # missing key, network error, a body that is not JSON
            print(
                f"{path}: cannot read s3://{bucket}/{key}: "
                f"{type(exc).__name__}: {exc}; left unchanged",
                file=sys.stderr,
            )
            failed += 1
            continue
        bnew, bchanges, bunc = rewrite_doc(body, "analysis", old, new)
        problem = None
        mode = ""
        if yunc or bunc:
            problem = f"unclassified occurrence(s): {(yunc + bunc)[:3]}"
        elif not ychanges and not bchanges:
            print(f"{path}: already corrected")
            continue
        elif ychanges and not bchanges and _as_body(ynew) == body:
            mode = "yml"  # S3 already new: complete the local write only
        elif _paths(ychanges) == _paths(bchanges) and _labels(body) == _labels(ydoc):
            mode = "both"
        else:
            problem = (
                f"the S3 body disagrees with the yml ({len(ychanges)} vs "
                f"{len(bchanges)} change(s), or a different current label)"
            )
        if problem:
            print(f"{path}: REFUSED: {problem}", file=sys.stderr)
            failed += 1
            continue

        print(f"{path}:")
        for c in ychanges:
            print(f"  yml {c}")
        if mode == "both":
            print(f"s3://{bucket}/{key}:")
            for c in bchanges:
                print(f"  s3 {c}")
        n_changes += len(ychanges) + (len(bchanges) if mode == "both" else 0)
        if args.dry_run:
            continue
        if mode == "both":
            if not asyncio.run(
                analysis_layout.upload_json(loader.cli, bucket, bnew, key)
            ):
                print(f"  upload of {key} failed; yml left unchanged", file=sys.stderr)
                failed += 1
                continue
            n_uploads += 1
        _write_yml(path, ynew)

    verb = "would make" if args.dry_run else "made"
    print(
        f"{verb} {n_changes} change(s); {n_uploads} upload(s); {failed} refused/failed"
    )
    if args.dry_run:
        print("--dry-run: nothing written.")
    return 1 if failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Correct a plate serial recorded as the plate id."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, helptext in (
        ("record", "rewrite one synced sequence zip and its process ymls"),
        ("analyses", "rewrite the labels of a record's analyses (yml and S3)"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument(
            "zip_path" if name == "record" else "process_dir",
            help=(
                "the sequence zip under RUNS_SYNCED"
                if name == "record"
                else "the record's PROCESSES directory"
            ),
        )
        p.add_argument(
            "--old", type=int, required=True, help="the wrong value (serial)"
        )
        p.add_argument("--new", type=int, required=True, help="the plate id")
        p.add_argument("--dry-run", action="store_true", help="write nothing")
        if name == "record":
            p.add_argument("--no-reset", action="store_true", help="no hand-back")
            p.add_argument("--process-dir", default=None, help="PROCESSES directory")
        p.add_argument("--allow-serial-mismatch", action="store_true")
        if name == "analyses":
            p.add_argument("--sequence-uuid", required=True)
            p.add_argument("--analyses-root", required=True)
            p.add_argument(
                "--analysis-dir",
                action="append",
                default=None,
                help="search only this analysis directory (repeatable; relative "
                "to --analyses-root's parent or absolute) instead of the whole "
                "tree, which on a station holds ~10^5 ymls",
            )
            p.add_argument("--bucket", default=None)
    args = parser.parse_args(argv)
    if args.old == args.new or args.old <= 0 or args.new <= 0:
        parser.error("--old and --new must be different positive integers")
        return 2  # unreachable: parser.error exits
    return _record(args) if args.command == "record" else _analyses(args)


if __name__ == "__main__":
    raise SystemExit(main())
