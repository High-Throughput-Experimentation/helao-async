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
import re
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


#: `ANALYSES/<yy.ww>/<mmdd>/<HHMMSS>__<name>[__<suffix>]/` -- spec §5 row 13.
ANALYSIS_DIR_RE = re.compile(r"^\d{6}__[^/]+$")

#: `analysis/<uuid>_output_<group>.json`; the two groups `export_analysis`
#: emits, split by `isinstance(v, list)` (base_analysis.py:139-143).
OUTPUT_GROUPS = ("scalar", "array")
_OUTPUT_JSON_RE = re.compile(r"^(?P<uuid>[0-9a-f-]{36})_output_(?P<group>\w+)$")


def assert_s3_analysis_rules(disk_ana: dict, s3_ana: dict) -> list[dict]:
    """The intentional on-disk-vs-S3 differences for an analysis record.

    Measured 2026-08-08, and NOT what the P6c plan predicted: the analysis
    model is uploaded as the very dict that was dumped to the yml
    (`_calc_and_write_model` builds `model_dict`, writes `yml_dumps(model_dict)`,
    and `sync_ana` hands that same object to `to_s3`), and it is produced by
    `ana_model.clean_dict()` with the DEFAULT `strip_private=False`. So unlike
    the act/exp/seq S3 copies there is no private-key stripping here and no
    technique_name split: the two bodies are the SAME content, and equality is
    the assertion. A future divergence between them is a defect, not a rule.

    What IS asymmetric is inside the model: each `outputs[i].output` embeds
    scalars only -- even for the array group, whose `output` is therefore
    empty while the uploaded `_output_array.json` carries the arrays
    (base_analysis.py:163-169 filters `if not isinstance(..., list)` for BOTH
    groups). Pinned here so a later "fix" is a deliberate wire change.
    """
    diffs: list[dict] = []
    for key in ("analysis_uuid", "analysis_name", "process_uuid"):
        if disk_ana.get(key) != s3_ana.get(key):
            diffs.append(
                {
                    "key": key,
                    "golden": disk_ana.get(key),
                    "candidate": s3_ana.get(key),
                }
            )
    for index, output in enumerate(s3_ana.get("outputs", []) or []):
        embedded = output.get("output", {}) or {}
        arrays = [k for k, v in embedded.items() if isinstance(v, list)]
        if arrays:
            diffs.append(
                {
                    "key": f"outputs[{index}].output",
                    "golden": "scalars only (arrays live in the output json)",
                    "candidate": f"array-valued keys {sorted(arrays)}",
                }
            )
    return diffs


def internal_s3_analysis_checks(root: Path) -> list[dict]:
    """Pair S3 analysis payloads with their on-disk ANALYSES tree.

    `internal_s3_checks` covers the action row only. Deployment-C's capture
    subject also emits analysis records, whose S3 keys (`analysis/<uuid>.json`
    and `analysis/<uuid>_output_<group>.json`, `analysis_driver.py:410` and
    `base_analysis.py:153-156`) have no action counterpart at all -- so
    nothing in the rig looked at them.
    """
    diffs: list[dict] = []
    s3_root = Path(root) / "S3_SIM"
    if not s3_root.is_dir():
        return diffs

    ana_root = Path(root) / "ANALYSES"
    on_disk: dict[str, Path] = {}
    for yml in ana_root.rglob("*.yml"):
        on_disk[yml.stem.lower()] = yml
    local_outputs = {p.stem.lower(): p for p in ana_root.rglob("*.json")}

    for payload in sorted(s3_root.glob("*/analysis/*.json")):
        stem = payload.stem.lower()
        body = json.loads(_load_bytes(payload))
        output_match = _OUTPUT_JSON_RE.match(stem)
        if output_match:
            group = output_match.group("group")
            if group not in OUTPUT_GROUPS:
                diffs.append(
                    {
                        "key": f"S3 analysis output {payload.name}",
                        "golden": f"group in {list(OUTPUT_GROUPS)}",
                        "candidate": group,
                    }
                )
            model = on_disk.get(output_match.group("uuid"))
            if model is None:
                diffs.append(
                    {
                        "key": f"S3 analysis output {payload.name}",
                        "golden": "an on-disk analysis yml for its uuid",
                        "candidate": "<absent>",
                    }
                )
                continue
            # The group's key set is declared by the model, so a payload that
            # silently gained or lost a key is visible without knowing the
            # analysis class.
            disk_model = load_yml_plain(model) or {}
            declared = {
                tuple(sorted(o.get("output_keys", []) or []))
                for o in (disk_model.get("outputs") or [])
                if o.get("output_name") == group
            }
            actual = tuple(sorted(body))
            if declared and actual not in declared:
                diffs.append(
                    {
                        "key": f"{payload.name}:output_keys",
                        "golden": sorted(declared)[0],
                        "candidate": actual,
                    }
                )
            if group == "array" and not any(isinstance(v, list) for v in body.values()):
                diffs.append(
                    {
                        "key": f"{payload.name}:group",
                        "golden": "at least one list-valued key",
                        "candidate": "no arrays in the array group",
                    }
                )
            if group == "scalar" and any(isinstance(v, list) for v in body.values()):
                diffs.append(
                    {
                        "key": f"{payload.name}:group",
                        "golden": "no list-valued keys",
                        "candidate": "arrays in the scalar group",
                    }
                )
            sibling = local_outputs.get(stem)
            if sibling is None:
                diffs.append(
                    {
                        "key": f"S3 analysis output {payload.name}",
                        "golden": "a local json of the same name beside the yml",
                        "candidate": "<absent>",
                    }
                )
            continue

        model = on_disk.get(stem)
        if model is None:
            diffs.append(
                {
                    "key": f"S3 analysis model {payload.name}",
                    "golden": "matching on-disk <uuid>.yml under ANALYSES",
                    "candidate": "<absent>",
                }
            )
            continue
        if not ANALYSIS_DIR_RE.match(model.parent.name):
            diffs.append(
                {
                    "key": f"{payload.name}:directory",
                    "golden": "<HHMMSS>__<name>[__<suffix>]",
                    "candidate": model.parent.name,
                }
            )
        disk_model = load_yml_plain(model) or {}
        for d in assert_s3_analysis_rules(disk_model, body):
            d["key"] = f"{payload.name}:{d['key']}"
            diffs.append(d)
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
