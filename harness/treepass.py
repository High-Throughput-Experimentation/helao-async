"""Tree pass (spec §6.4): capture snapshot -> normalized member set.

- explode_zips: RUNS_SYNCED sequence zips are expanded into sibling
  ``<name>.zipdir`` directories inside a working copy, so the zip MEMBER SET
  (the §5.7 contract for synced sequences, .prg sidecars included) is
  asserted by the ordinary tree compare, and members join the per-file passes.
- seed_mapper: assigns uuid ordinals from meta-file content in a
  capture-independent order (row order seq -> exp -> act -> prc; within a row,
  sorted by the uuid-blanked normalized path), so uuids appearing in
  FILENAMES (prc ymls, S3 keys) normalize identically on both sides.
- snapshot: normalized-relpath -> (real path, ArtifactRow) map;
  IGNORE and LOCK rows excluded (row 11: .lock is ignored everywhere).
"""

from __future__ import annotations

import json
import shutil
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from harness.classify import (
    ArtifactRow,
    classify_file,
    normalize_name,
    normalize_relpath,
)
from harness.uuidmap import RE_UUID, UuidMapper
from harness.yaml_pass import load_yml_plain

PARITY_TOPS = (
    "RUNS_ACTIVE",
    "RUNS_FINISHED",
    "RUNS_SYNCED",
    "RUNS_DIAG",
    "RUNS_NOSYNC",
    "PROCESSES",
    "ANALYSES",
    "S3_SIM",
)

#: ANALYSIS is seeded LAST, deliberately. Appending leaves every existing
#: ordinal for seq/exp/act/prc exactly where it was, so goldens captured before
#: analysis records were seeded keep their mappings and need no re-capture.
ROW_SEED_ORDER = (
    ArtifactRow.SEQ_YML,
    ArtifactRow.EXP_YML,
    ArtifactRow.ACT_YML,
    ArtifactRow.PRC_YML,
    ArtifactRow.ANALYSIS,
)

#: `analysis_uuid` joined this list when a conversion family that writes
#: analysis records inline was first captured. Its uuid is minted per run
#: (uuid7, not the content hash the server path uses) AND appears in filenames
#: -- `<uuid>.yml` beside `<uuid>_output_<group>.json` -- so without a seed the
#: strict mapper raises on the name rather than diffing it. Every other row's
#: uuids reach filenames only through directory names that carry them.
SEED_UUID_KEYS = (
    "sequence_uuid",
    "experiment_uuid",
    "action_uuid",
    "process_uuid",
    "analysis_uuid",
)


@dataclass
class TreeSnapshot:
    root: Path
    files: dict[str, tuple[Path, ArtifactRow]] = field(default_factory=dict)


def _iter_parity_files(root: Path) -> Iterator[Path]:
    for top in PARITY_TOPS:
        top_dir = root / top
        if not top_dir.is_dir():
            continue
        for f in sorted(top_dir.rglob("*")):
            if f.is_file():
                yield f


def explode_zips(root: Path, workdir: Path) -> Path:
    """Copy ``root`` into ``workdir``, expanding every .zip into ``.zipdir``.

    reset_sync's ``.orig`` sidecar (sync_driver.py: a synced zip renamed in
    place, still a valid zip archive — see classify.RE_SEQ_ORIG) gets the
    same treatment into ``.origdir``, so its members (masked-random-data
    files included) go through the ordinary per-file passes instead of an
    opaque whole-archive byte compare.
    """
    dest = Path(workdir) / "exploded"
    shutil.copytree(root, dest)
    for zpath in sorted(dest.rglob("*.zip")):
        target = zpath.with_suffix(".zipdir")
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(target)
        zpath.unlink()
    for opath in sorted(dest.rglob("*.orig")):
        target = opath.with_suffix(".origdir")
        with zipfile.ZipFile(opath) as zf:
            zf.extractall(target)
        opath.unlink()
    return dest


def _analysis_tiebreak(row: ArtifactRow, doc, mapper: UuidMapper) -> str:
    """Content key ordering ANALYSIS records whose blanked paths are identical.

    Every analysis record of one conversion sits in the same directory and is
    named only by its uuid, so all of them blank to the SAME sort key and the
    order falls to the remaining tiebreak -- the raw uuid. That was
    capture-independent only by accident: while analysis uuids were uuid7 they
    sorted by creation order, which two captures of a scenario share. A
    content-hash analysis uuid (spec §5 row 13) does not sort by anything, so
    the two sides would assign the same ordinals to DIFFERENT records and every
    record would then diff against the wrong counterpart -- reported as content
    mismatches, with nothing pointing at the ordering as the cause.

    Ordering by the record's own identity instead makes the assignment
    capture-independent for either uuid scheme. Only ANALYSIS needs it: seq,
    exp, act and prc uuids are minted in a deterministic order by the run
    itself, so their existing path tiebreak already reproduces it.

    The process the record describes is part of that identity, but its RAW uuid
    is not usable here -- a post-hoc converter mints a fresh process identity
    per conversion, so the raw value differs between two captures of the same
    scenario. Its already-assigned ordinal does not, which is why the mapper is
    consulted read-only (:meth:`UuidMapper.known`): PRC rows seed before
    ANALYSIS, so the ordinal is normally present, and when it is not the key
    simply contributes nothing rather than assigning an ordinal mid-sort.
    """
    if row is not ArtifactRow.ANALYSIS or not isinstance(doc, dict):
        return ""
    return json.dumps(
        [
            doc.get("analysis_name"),
            doc.get("global_sample_label"),
            doc.get("analysis_params"),
            mapper.known(doc.get("process_uuid") or ""),
        ],
        sort_keys=True,
        default=str,
    )


def seed_mapper(root: Path, mapper: UuidMapper) -> None:
    """Assign uuid ordinals in a capture-independent order (meta files first).

    The sort key blanks raw uuids out of the normalized path so ordering is
    identical for two captures of the same scenario; ANALYSIS rows, whose
    blanked paths all collapse onto one another, are then ordered by record
    identity (see :func:`_analysis_tiebreak`). prc ymls additionally attempt the
    uuid5 derivation registration (spec §5.5 exception-with-structure):
    register_derived is a checked no-op when the process uuid is not derived.
    """
    buckets: dict[ArtifactRow, list[tuple[str, Path]]] = {
        row: [] for row in ROW_SEED_ORDER
    }
    docs: dict[Path, object] = {}
    for f in _iter_parity_files(root):
        rel = f.relative_to(root).as_posix()
        row = classify_file(rel)
        if row in buckets:
            docs[f] = load_yml_plain(f)
            buckets[row].append((RE_UUID.sub("UUID", normalize_relpath(rel)), f))
    for row in ROW_SEED_ORDER:
        # The tiebreak is evaluated per row, so ANALYSIS -- seeded last -- can
        # consult the process ordinals the earlier rows have already assigned.
        ordered = sorted(
            (key, _analysis_tiebreak(row, docs[f], mapper), f)
            for key, f in buckets[row]
        )
        for _, _, f in ordered:
            d = docs[f]
            if not isinstance(d, dict):
                continue
            if row is ArtifactRow.PRC_YML:
                pu = d.get("process_uuid")
                eu = d.get("experiment_uuid")
                pidx = d.get("process_group_index")
                if pu and eu and pidx is not None:
                    mapper.register_derived(str(pu), str(eu), pidx)
            for k in SEED_UUID_KEYS:
                if d.get(k):
                    mapper.map(str(d[k]))


def _sibling_tokens(root: Path) -> dict[Path, str]:
    """Disambiguate directory-name collisions the §5.5 TS-strip grammar creates.

    ``normalize_name`` collapses every wall-clock-derived directory prefix to
    a fixed "TS" token, which is correct when a run only ever has ONE
    experiment/sequence of a given name. It is NOT correct when the same run
    legitimately repeats an experiment/sequence name (e.g. a sequence that
    invokes the same experiment twice, or a `cycles=N` scenario) — two real
    sibling directories then collapse onto the identical normalized string.
    This is not volatile noise (§5.5) to be masked away; the sibling identity
    is real run structure that both a golden and a candidate capture must
    still be checked against, so we assign a stable ordinal suffix
    (``#0``, ``#1``, ...) in chronological order (raw dir names sort
    lexically = chronologically given the legacy %H%M%S.../%y%m%d.%H%M%S...
    prefixes), matching only siblings of the SAME real parent directory. Two
    independent captures of the same scenario execute experiments/sequences
    in the same relative order, so the ordinal is capture-independent.
    Directories whose normalized token is unique among their siblings are
    left exactly as before (no suffix) so existing single-experiment
    scenarios and unit tests are unaffected.
    """
    children: dict[Path, list[str]] = {}
    for f in _iter_parity_files(root):
        parts = f.relative_to(root).parts
        cur = root
        for name in parts[:-1]:
            names = children.setdefault(cur, [])
            if name not in names:
                names.append(name)
            cur = cur / name
    token_of: dict[Path, str] = {}
    for parent, names in children.items():
        groups: dict[str, list[str]] = {}
        for name in names:
            groups.setdefault(normalize_name(name), []).append(name)
        for norm_tok, siblings in groups.items():
            if len(siblings) == 1:
                token_of[parent / siblings[0]] = norm_tok
            else:
                for i, name in enumerate(sorted(siblings)):
                    token_of[parent / name] = f"{norm_tok}#{i}"
    return token_of


def snapshot(root: Path, mapper: UuidMapper) -> TreeSnapshot:
    """Build the normalized member map; strict uuid substitution in names."""
    snap = TreeSnapshot(root=root)
    token_of = _sibling_tokens(root)
    for f in _iter_parity_files(root):
        rel = f.relative_to(root).as_posix()
        row = classify_file(rel)
        if row in (ArtifactRow.IGNORE, ArtifactRow.LOCK):
            continue
        parts = f.relative_to(root).parts
        if row is ArtifactRow.PRC_YML:
            # A process artifact is keyed by its filename alone, never by its
            # full path. The write moved from root/PROCESSES into the RUNS_*
            # tree (and so into the sequence zip), and the golden sets predate
            # that move; keying by path would report every process as both
            # missing and extra. The filename is
            # {pidx}__{process_uuid}__{technique}-prc.yml, so the key is unique
            # by construction -- EXCEPT across a reset_sync round trip, where
            # the pre-reset zip survives as a ``.orig`` sidecar (exploded to
            # ``.origdir``) beside the freshly rebuilt ``.zip`` (``.zipdir``):
            # both legitimately carry a byte-identical copy of the SAME
            # process now that it travels inside the zip, and a bare filename
            # key cannot tell that expected backup duplication apart from an
            # actual collision.
            #
            # The prefix therefore covers ONLY an ``.origdir`` ancestor, never
            # a ``.zipdir`` one. A live post-move prc ALWAYS sits inside a
            # ``.zipdir`` in production -- the sequence directory is zipped and
            # removed -- so prefixing on ``.zipdir`` too would apply to every
            # real prc unconditionally, making the golden's PROCESSES-shaped
            # `PRC/<name>` key permanently unreachable and silently turning a
            # field-by-field content comparison into a present/absent tree
            # diff for every process in the golden gate. Prefixing only the
            # backup keeps the live copy's key exactly as Task 4 intended
            # while still telling it apart from its own ``.orig`` sidecar. A
            # process that sits directly in RUNS_SYNCED (no zip involved) or
            # under the old PROCESSES mirror has no ``.origdir`` ancestor
            # either and keys exactly as before. snapshot still raises on a
            # same-container collision, so a real mistake fails loud rather
            # than merging two processes.
            #
            # Accepted gap: a tree holding BOTH an old PROCESSES-mirror copy
            # AND a colocated in-zip copy of the SAME process would still
            # collide under this rule (neither has an ``.origdir`` ancestor).
            # That mixed-era shape is unreachable in the tests and in
            # production -- a run is captured either fully pre-move or fully
            # post-move, never both for the same process -- and if it ever
            # did happen, snapshot() raises loudly rather than silently
            # merging the two, so it is accepted rather than overlooked.
            container = ""
            cur = root
            for name in parts[:-1]:
                cur = cur / name
                tok = token_of[cur]
                if tok.endswith(".origdir"):
                    container = tok
            prefix = f"{container}/" if container else ""
            norm = mapper.sub(f"PRC/{prefix}{normalize_name(parts[-1])}", strict=True)
        else:
            norm_parts = []
            cur = root
            for name in parts[:-1]:
                cur = cur / name
                norm_parts.append(token_of[cur])
            norm_parts.append(normalize_name(parts[-1]))
            norm = mapper.sub("/".join(norm_parts), strict=True)
        if norm in snap.files:
            raise ValueError(f"normalized-name collision: {norm} ({rel})")
        snap.files[norm] = (f, row)
    return snap


def diff_member_sets(golden: TreeSnapshot, candidate: TreeSnapshot) -> list[dict]:
    diffs: list[dict] = []
    gset, cset = set(golden.files), set(candidate.files)
    for missing in sorted(gset - cset):
        diffs.append(
            {
                "file": missing,
                "key": "<tree>",
                "golden": "present",
                "candidate": "absent",
            }
        )
    for extra in sorted(cset - gset):
        diffs.append(
            {"file": extra, "key": "<tree>", "golden": "absent", "candidate": "present"}
        )
    return diffs
