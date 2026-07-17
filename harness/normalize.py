"""Normalizer façade (spec §6.4 names this module) + debug inventory CLI.

Re-exports every pass so callers can `from harness.normalize import ...`;
the implementation lives in focused modules (classify/uuidmap/yaml_pass/
treepass/hlo_pass/s3_pass).

CLI: python -m harness.normalize --root <capture root>
prints each parity file's normalized path, artifact row, and (for yml rows)
a sha256 of its normalized content — the debugging view of exactly what the
gate compares.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from harness.classify import (  # noqa: F401  (façade re-exports)
    ArtifactRow,
    classify_file,
    normalize_name,
    normalize_relpath,
)
from harness.hlo_pass import (  # noqa: F401
    diff_hlo,
    diff_hlo_body,
    masked_columns_for,
    normalize_hlo_header,
    row_tolerance_for,
)
from harness.s3_pass import (  # noqa: F401
    assert_s3_meta_rules,
    diff_s3_manifest,
    diff_s3_record,
    internal_s3_checks,
)
from harness.treepass import (  # noqa: F401
    PARITY_TOPS,
    TreeSnapshot,
    diff_member_sets,
    explode_zips,
    seed_mapper,
    snapshot,
)
from harness.uuidmap import RE_UUID, UuidMapper  # noqa: F401
from harness.yaml_pass import (  # noqa: F401
    canonicalize,
    diff_meta,
    diff_prg,
    load_yml_plain,
    normalize_meta,
    to_plain,
)

YAML_ROWS = (
    ArtifactRow.SEQ_YML,
    ArtifactRow.EXP_YML,
    ArtifactRow.ACT_YML,
    ArtifactRow.PRC_YML,
    ArtifactRow.ANALYSIS,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m harness.normalize")
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="normalize_") as td:
        exploded = explode_zips(args.root, Path(td))
        mapper = UuidMapper()
        seed_mapper(exploded, mapper)
        snap = snapshot(exploded, mapper)
        for norm in sorted(snap.files):
            path, row = snap.files[norm]
            line = {"path": norm, "row": row.name}
            if row in YAML_ROWS:
                normalized = normalize_meta(load_yml_plain(path), mapper)
                digest = hashlib.sha256(
                    json.dumps(normalized, sort_keys=True, default=str).encode()
                ).hexdigest()[:16]
                line["normalized_sha256"] = digest
            print(json.dumps(line))
    return 0


if __name__ == "__main__":
    sys.exit(main())
