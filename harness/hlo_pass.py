"""HLO pass (spec §5.2 row 4/5, §5.5, §6.4).

Header: parsed by the legacy reader (real consumer's decoder — §10.1 rule 3),
then epoch_ns is dropped (stamped at lazy-open OR header-finish, two legal
code paths — §5.4 item 10) and hlo_version dropped (release string), then
§5.5-normalized like any meta dict.

Body: one JSON object per line after ``%%``; compared column-by-column as
parsed values. Columns listed in the golden manifest's masked_hlo_columns
(matched by fnmatch on the NORMALIZED path) have their VALUES masked —
presence and row counts are still asserted, within the manifest's optional
hlo_row_count_tolerance (poll-paced sim executors jitter by a row or two).
"""

from __future__ import annotations

import fnmatch
import math
from pathlib import Path

from helao.helpers.hlo_data import read_hlo

from harness.manifest import ProvenanceManifest
from harness.uuidmap import UuidMapper
from harness.yaml_pass import diff_meta, normalize_meta


def _is_nan(v: object) -> bool:
    return isinstance(v, float) and math.isnan(v)


def _values_equal(g: object, c: object) -> bool:
    """Structural equality with NaN-at-matching-position treated as equal.

    Plain ``==`` makes ``NaN != NaN`` (JSON body values may legitimately be
    NaN/Infinity per the legacy reader's tolerance), so this recurses through
    dict/list containers and special-cases float NaN pairs instead of relying
    on ``==`` directly.
    """
    if _is_nan(g) and _is_nan(c):
        return True
    if isinstance(g, dict) and isinstance(c, dict):
        return set(g) == set(c) and all(_values_equal(g[k], c[k]) for k in g)
    if isinstance(g, list) and isinstance(c, list):
        return len(g) == len(c) and all(_values_equal(gi, ci) for gi, ci in zip(g, c))
    return g == c


def normalize_hlo_header(header: dict, mapper: UuidMapper) -> dict:
    hdr = {
        k: v for k, v in dict(header).items() if k not in ("epoch_ns", "hlo_version")
    }
    return normalize_meta(hdr, mapper)


def masked_columns_for(norm_name: str, masked_hlo_columns: dict) -> set[str]:
    cols: set[str] = set()
    for pattern, columns in (masked_hlo_columns or {}).items():
        if fnmatch.fnmatch(norm_name, pattern):
            cols.update(columns)
    return cols


def row_tolerance_for(norm_name: str, tolerances: dict) -> int:
    best = 0
    for pattern, tol in (tolerances or {}).items():
        if fnmatch.fnmatch(norm_name, pattern):
            best = max(best, int(tol))
    return best


def diff_hlo_body(
    g_data: dict, c_data: dict, masked: set[str], tolerance: int
) -> list[dict]:
    diffs: list[dict] = []
    for col in sorted(set(g_data) | set(c_data)):
        if col not in g_data:
            diffs.append(
                {"key": f"body.{col}", "golden": "<absent>", "candidate": "present"}
            )
            continue
        if col not in c_data:
            diffs.append(
                {"key": f"body.{col}", "golden": "present", "candidate": "<absent>"}
            )
            continue
        g_col, c_col = g_data[col], c_data[col]
        if col in masked:
            if abs(len(g_col) - len(c_col)) > tolerance:
                diffs.append(
                    {
                        "key": f"body.{col}.len",
                        "golden": len(g_col),
                        "candidate": len(c_col),
                    }
                )
            continue
        if len(g_col) != len(c_col):
            diffs.append(
                {
                    "key": f"body.{col}.len",
                    "golden": len(g_col),
                    "candidate": len(c_col),
                }
            )
            continue
        for gv, cv in zip(g_col, c_col):
            if not _values_equal(gv, cv):
                diffs.append({"key": f"body.{col}", "golden": gv, "candidate": cv})
    return diffs


def diff_hlo(
    golden_path: Path,
    candidate_path: Path,
    norm_name: str,
    mapper_g: UuidMapper,
    mapper_c: UuidMapper,
    manifest: ProvenanceManifest,
) -> list[dict]:
    g_meta, g_data = read_hlo(str(golden_path))
    c_meta, c_data = read_hlo(str(candidate_path))
    diffs = diff_meta(
        normalize_hlo_header(g_meta, mapper_g),
        normalize_hlo_header(c_meta, mapper_c),
        path="header",
    )
    diffs.extend(
        diff_hlo_body(
            dict(g_data),
            dict(c_data),
            masked_columns_for(norm_name, manifest.masked_hlo_columns),
            row_tolerance_for(norm_name, manifest.hlo_row_count_tolerance),
        )
    )
    return diffs
