"""S3 pass (spec §5.6, §5.5, §6.4): recorded uploads from the sim DB server.

Recorder layout (Task 11 / sim_db_server.RecordingS3Client):
    S3_SIM/<bucket>/<key>          — the uploaded object bytes
    S3_SIM/manifest.jsonl          — one {"bucket","key","mode","gzip"} per upload

Key templates are asserted by the tree pass (uuid-mapped names); this module
compares payload CONTENT and the recorder manifest, and asserts the two
INTENTIONAL on-disk-vs-S3 differences that §5.5 requires the harness to
check as differences, not sameness:
  1. FileInfo rename rule in the S3 action meta:
     file_name  x.hlo        -> x.hlo.json (or x.hlo.json.gz if compressed)
     file_type  <prefix>helao__file -> <prefix>helao__<ext>_file, where
                <ext> is the trailing extension of the S3 key ("json", or
                "gz" when compressed) — never "hlo" itself.
  2. technique_name list -> str split applied ONLY in the S3/prc copies.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path, PurePosixPath

from harness.hlo_pass import (
    diff_hlo_body,
    masked_columns_for,
    normalize_hlo_header,
    row_tolerance_for,
)
from harness.manifest import ProvenanceManifest, content_mask_mode
from harness.uuidmap import UuidMapper
from harness.yaml_pass import diff_meta, load_yml_plain, normalize_meta


def _load_bytes(path: Path) -> bytes:
    raw = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    return raw


def _manifest_entry_key(entry: tuple) -> str:
    bucket, key, is_gz = entry
    suffix = ":gzip" if is_gz else ""
    return f"s3_manifest.{bucket}/{key}{suffix}"


def diff_s3_manifest(
    gpath: Path, cpath: Path, mg: UuidMapper, mc: UuidMapper
) -> list[dict]:
    def entries(path: Path, mapper: UuidMapper) -> set:
        out = set()
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            out.add((e["bucket"], mapper.sub(e["key"]), bool(e.get("gzip"))))
        return out

    g, c = entries(gpath, mg), entries(cpath, mc)
    diffs: list[dict] = []
    for missing in sorted(g - c):
        diffs.append(
            {
                "key": _manifest_entry_key(missing),
                "golden": "present",
                "candidate": "absent",
            }
        )
    for extra in sorted(c - g):
        diffs.append(
            {
                "key": _manifest_entry_key(extra),
                "golden": "absent",
                "candidate": "present",
            }
        )
    return diffs


def diff_s3_record(
    norm: str,
    gpath: Path,
    cpath: Path,
    mg: UuidMapper,
    mc: UuidMapper,
    manifest: ProvenanceManifest,
) -> list[dict]:
    name = PurePosixPath(norm).name
    if name == "manifest.jsonl":
        return diff_s3_manifest(gpath, cpath, mg, mc)
    if ".hlo.json" in name:
        g = json.loads(_load_bytes(gpath))
        c = json.loads(_load_bytes(cpath))
        diffs = diff_meta(
            normalize_hlo_header(g.get("meta", {}), mg),
            normalize_hlo_header(c.get("meta", {}), mc),
            path="meta",
        )
        diffs.extend(
            diff_hlo_body(
                g.get("data", {}),
                c.get("data", {}),
                masked_columns_for(norm, manifest.masked_hlo_columns),
                row_tolerance_for(norm, manifest.hlo_row_count_tolerance),
            )
        )
        return diffs
    if name.endswith(".json") or name.endswith(".json.gz"):
        g = json.loads(_load_bytes(gpath))
        c = json.loads(_load_bytes(cpath))
        return diff_meta(normalize_meta(g, mg), normalize_meta(c, mc))
    # other raw_data misc uploads (e.g. the hlo_to_csv postprocess output,
    # re-uploaded to S3 alongside the .hlo): honor the SAME manifest-resident
    # content_masked_files lever the on-disk copy gets via the parity
    # dispatcher's AUX_FILE branch (§6.4) — S3_SIM classifies everything
    # under it as S3_RECORD, not AUX_FILE, so that branch never sees these
    # and unseeded-random-derived files would otherwise be exact-byte
    # compared here and spuriously fail.
    mode = content_mask_mode(norm, manifest)
    if mode == "skip":
        return []
    if mode == "line-count":
        g_n = len(_load_bytes(gpath).splitlines())
        c_n = len(_load_bytes(cpath).splitlines())
        if g_n != c_n:
            return [{"key": "line_count", "golden": g_n, "candidate": c_n}]
        return []
    if _load_bytes(gpath) != _load_bytes(cpath):
        return [{"key": "<bytes>", "golden": "differs", "candidate": "differs"}]
    return []


def assert_s3_meta_rules(disk_act: dict, s3_act: dict) -> list[dict]:
    """Per-capture consistency: the intentional on-disk vs S3 differences hold."""
    diffs: list[dict] = []
    disk_files = {
        fi.get("file_name"): fi
        for fi in disk_act.get("files", [])
        if isinstance(fi, dict)
    }
    for fi in s3_act.get("files", []):
        if not isinstance(fi, dict):
            continue
        name = fi.get("file_name", "")
        if ".hlo.json" in name:
            # Real legacy rename (sync_driver.py ~1213-1239): the S3 key gets
            # a trailing extension appended to the uploaded .hlo filename
            # (".json", plus ".gz" when compressed), and file_type has
            # "helao__file" replaced with "helao__<last-S3-key-ext>_file",
            # preserving any server-name prefix (e.g. "wssim_helao__file" ->
            # "wssim_helao__json_file"). Derive the expected extension from
            # the S3-side name itself rather than assuming a fixed value.
            if name.endswith(".gz"):
                ext = "gz"
                orig = name[: -len(".gz")]
            else:
                ext = name.rsplit(".", 1)[-1]
                orig = name
            if orig.endswith(".json"):
                orig = orig[: -len(".json")]
            if orig not in disk_files:
                diffs.append(
                    {
                        "key": f"files[{name}].file_name",
                        "golden": "rename rule: on-disk .hlo FileInfo expected",
                        "candidate": "no matching on-disk entry",
                    }
                )
            elif not fi.get("file_type", "").endswith(f"helao__{ext}_file"):
                diffs.append(
                    {
                        "key": f"files[{name}].file_type",
                        "golden": f"*helao__{ext}_file (rename rule)",
                        "candidate": fi.get("file_type"),
                    }
                )
    tn_disk = disk_act.get("technique_name")
    tn_s3 = s3_act.get("technique_name")
    if isinstance(tn_disk, list):
        if not isinstance(tn_s3, str) or tn_s3 not in tn_disk:
            diffs.append(
                {
                    "key": "technique_name",
                    "golden": f"str member of {tn_disk} (S3 split patch)",
                    "candidate": tn_s3,
                }
            )
    return diffs


def internal_s3_checks(root: Path) -> list[dict]:
    """Pair S3 action metas with on-disk act ymls (raw uuid) in ONE capture."""
    act_index: dict = {}
    for act_yml in Path(root).rglob("*-act.yml"):
        d = load_yml_plain(act_yml)
        if isinstance(d, dict) and d.get("action_uuid"):
            act_index[str(d["action_uuid"]).lower()] = d
    diffs: list[dict] = []
    s3_root = Path(root) / "S3_SIM"
    if not s3_root.is_dir():
        return diffs
    for meta_json in sorted(s3_root.glob("*/action/*.json")):
        raw_uuid = meta_json.stem.lower()
        disk_act = act_index.get(raw_uuid)
        if disk_act is None:
            diffs.append(
                {
                    "key": f"S3 action meta {meta_json.name}",
                    "golden": "matching on-disk -act.yml",
                    "candidate": "<absent>",
                }
            )
            continue
        s3_act = json.loads(_load_bytes(meta_json))
        for d in assert_s3_meta_rules(disk_act, s3_act):
            d["key"] = f"{meta_json.name}:{d['key']}"
            diffs.append(d)
    return diffs
