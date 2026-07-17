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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

from harness.classify import ArtifactRow, classify_file, normalize_relpath
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
    files: Dict[str, Tuple[Path, ArtifactRow]] = field(default_factory=dict)


def _iter_parity_files(root: Path) -> Iterator[Path]:
    for top in PARITY_TOPS:
        top_dir = root / top
        if not top_dir.is_dir():
            continue
        for f in sorted(top_dir.rglob("*")):
            if f.is_file():
                yield f


def explode_zips(root: Path, workdir: Path) -> Path:
    """Copy ``root`` into ``workdir`` and expand every .zip into ``.zipdir``."""
    dest = Path(workdir) / "exploded"
    shutil.copytree(root, dest)
    for zpath in sorted(dest.rglob("*.zip")):
        target = zpath.with_suffix(".zipdir")
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(target)
        zpath.unlink()
    return dest


def seed_mapper(root: Path, mapper: UuidMapper) -> None:
    """Assign uuid ordinals in a capture-independent order (meta files first).

    The sort key blanks raw uuids out of the normalized path so ordering is
    identical for two captures of the same scenario. prc ymls additionally
    attempt the uuid5 derivation registration (spec §5.5 exception-with-
    structure): register_derived is a checked no-op when the process uuid is
    not derived.
    """
    buckets: Dict[ArtifactRow, List[Tuple[str, Path]]] = {
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


def snapshot(root: Path, mapper: UuidMapper) -> TreeSnapshot:
    """Build the normalized member map; strict uuid substitution in names."""
    snap = TreeSnapshot(root=root)
    for f in _iter_parity_files(root):
        rel = f.relative_to(root).as_posix()
        row = classify_file(rel)
        if row in (ArtifactRow.IGNORE, ArtifactRow.LOCK):
            continue
        norm = mapper.sub(normalize_relpath(rel), strict=True)
        if norm in snap.files:
            raise ValueError(f"normalized-name collision: {norm} ({rel})")
        snap.files[norm] = (f, row)
    return snap


def diff_member_sets(golden: TreeSnapshot, candidate: TreeSnapshot) -> List[dict]:
    diffs: List[dict] = []
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
