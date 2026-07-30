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

ROW_SEED_ORDER = (
    ArtifactRow.SEQ_YML,
    ArtifactRow.EXP_YML,
    ArtifactRow.ACT_YML,
    ArtifactRow.PRC_YML,
)

SEED_UUID_KEYS = ("sequence_uuid", "experiment_uuid", "action_uuid", "process_uuid")


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


def seed_mapper(root: Path, mapper: UuidMapper) -> None:
    """Assign uuid ordinals in a capture-independent order (meta files first).

    The sort key blanks raw uuids out of the normalized path so ordering is
    identical for two captures of the same scenario. prc ymls additionally
    attempt the uuid5 derivation registration (spec §5.5 exception-with-
    structure): register_derived is a checked no-op when the process uuid is
    not derived.
    """
    buckets: dict[ArtifactRow, list[tuple[str, Path]]] = {
        row: [] for row in ROW_SEED_ORDER
    }
    for f in _iter_parity_files(root):
        rel = f.relative_to(root).as_posix()
        row = classify_file(rel)
        if row in buckets:
            sort_key = RE_UUID.sub("UUID", normalize_relpath(rel))
            buckets[row].append((sort_key, f))
    for row in ROW_SEED_ORDER:
        for _, f in sorted(buckets[row]):
            d = load_yml_plain(f)
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
