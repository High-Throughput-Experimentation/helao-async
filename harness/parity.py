"""THE parity gate (spec §6.5): python -m harness.parity --golden X --candidate Y.

Golden-set layout: <set>/provenance.yml + <set>/root/{RUNS_*,PROCESSES,S3_SIM}.
The candidate may be another golden set or a bare capture root. Any
unnormalized difference fails; phase gates cite the printed run_id.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from harness import HARNESS_VERSION
from harness.classify import ArtifactRow
from harness.hlo_pass import diff_hlo
from harness.manifest import ManifestMissingError, ProvenanceManifest, content_mask_mode
from harness.s3_pass import diff_s3_record, internal_s3_checks
from harness.treepass import (
    diff_member_sets,
    explode_zips,
    seed_mapper,
    snapshot,
)
from harness.uuidmap import UuidMapper
from harness.yaml_pass import (
    apply_meta_key_mask,
    diff_meta,
    diff_prg,
    load_yml_plain,
    normalize_meta,
)


def _diff_aux(norm, gpath, cpath, manifest):
    mode = content_mask_mode(norm, manifest)
    if mode == "skip":
        return []
    if mode == "line-count":
        g_n = len(Path(gpath).read_bytes().splitlines())
        c_n = len(Path(cpath).read_bytes().splitlines())
        if g_n != c_n:
            return [{"key": "line_count", "golden": g_n, "candidate": c_n}]
        return []
    if Path(gpath).read_bytes() != Path(cpath).read_bytes():
        return [{"key": "<bytes>", "golden": "differs", "candidate": "differs"}]
    return []


def _diff_lines_sorted(gpath, cpath, mg, mc):
    g = sorted(mg.sub(x) for x in Path(gpath).read_text().splitlines())
    c = sorted(mc.sub(x) for x in Path(cpath).read_text().splitlines())
    if g != c:
        return [{"key": "manifest_lines", "golden": g, "candidate": c}]
    return []


YAML_ROWS = (
    ArtifactRow.SEQ_YML,
    ArtifactRow.EXP_YML,
    ArtifactRow.ACT_YML,
    ArtifactRow.PRC_YML,
    ArtifactRow.ANALYSIS,
)


def compare_file(row, norm, gpath, cpath, mg, mc, manifest):
    if row in YAML_ROWS:
        g = normalize_meta(load_yml_plain(gpath), mg)
        c = normalize_meta(load_yml_plain(cpath), mc)
        mkeys = manifest.masked_meta_keys_for(norm)
        if mkeys:
            g = apply_meta_key_mask(g, mkeys)
            c = apply_meta_key_mask(c, mkeys)
        return diff_meta(g, c)
    if row is ArtifactRow.PRG:
        return diff_prg(load_yml_plain(gpath), load_yml_plain(cpath))
    if row is ArtifactRow.HLO:
        return diff_hlo(gpath, cpath, norm, mg, mc, manifest)
    if row is ArtifactRow.PARQUET:
        from helao.helpers.hlo_data import read_helao_metadata

        return diff_meta(
            normalize_meta(read_helao_metadata(str(gpath)), mg),
            normalize_meta(read_helao_metadata(str(cpath)), mc),
            "helao_metadata",
        )
    if row is ArtifactRow.S3_RECORD:
        return diff_s3_record(norm, gpath, cpath, mg, mc, manifest)
    if row is ArtifactRow.MICRO_MANIFEST:
        return _diff_lines_sorted(gpath, cpath, mg, mc)
    return _diff_aux(norm, gpath, cpath, manifest)  # AUX_FILE and anything new


def _resolve_root(path: Path) -> Path:
    return path / "root" if (path / "root").is_dir() else path


def run_parity(
    golden_set: Path,
    candidate: Path,
    report_path: Optional[Path] = None,
) -> dict:
    golden_set, candidate = Path(golden_set), Path(candidate)
    manifest = ProvenanceManifest.load(golden_set)  # hard-fails when missing (F1)
    golden_root = golden_set / "root"
    cand_root = _resolve_root(candidate)
    run_id = uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="parity_") as td:
        g_ex = explode_zips(golden_root, Path(td) / "g")
        c_ex = explode_zips(cand_root, Path(td) / "c")
        mg, mc = UuidMapper(), UuidMapper()
        seed_mapper(g_ex, mg)
        seed_mapper(c_ex, mc)
        g_snap = snapshot(g_ex, mg)
        c_snap = snapshot(c_ex, mc)
        tree_diffs = diff_member_sets(g_snap, c_snap)
        file_diffs = {}
        for norm in sorted(set(g_snap.files) & set(c_snap.files)):
            gpath, row = g_snap.files[norm]
            cpath, _ = c_snap.files[norm]
            fdiffs = compare_file(row, norm, gpath, cpath, mg, mc, manifest)
            if fdiffs:
                file_diffs[norm] = fdiffs
        consistency = internal_s3_checks(g_ex) + internal_s3_checks(c_ex)
        # F1 guard: an empty golden set has nothing to compare and would PASS
        # with 0 diffs vacuously (e.g. a capture that snapshotted before the run
        # wrote any output). A golden master with no comparable files is never
        # legitimate -- fail loudly instead.
        if not g_snap.files:
            consistency.append(
                {
                    "check": "empty_golden",
                    "detail": (
                        "golden set has 0 comparable files; refusing a vacuous "
                        "0-diff pass (capture likely produced no run output)"
                    ),
                }
            )
    n_diffs = (
        len(tree_diffs) + sum(len(v) for v in file_diffs.values()) + len(consistency)
    )
    report = {
        "run_id": run_id,
        "harness_version": HARNESS_VERSION,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "scenario": manifest.scenario,
        "golden": str(golden_set),
        "candidate": str(candidate),
        "status": "pass" if n_diffs == 0 else "fail",
        "n_diffs": n_diffs,
        "tree_diffs": tree_diffs,
        "file_diffs": file_diffs,
        "consistency_diffs": consistency,
    }
    if report_path is not None:
        Path(report_path).write_text(json.dumps(report, indent=2, default=str))
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m harness.parity", description=__doc__
    )
    parser.add_argument("--golden", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        report = run_parity(args.golden, args.candidate, args.report)
    except ManifestMissingError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    print(
        f"parity run {report['run_id']}: {report['status'].upper()} "
        f"({report['n_diffs']} diffs) scenario={report['scenario']}"
    )
    if report["status"] != "pass" and args.report is None:
        print(json.dumps(report, indent=2, default=str))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
