"""YAML/meta content normalization + structural diff (spec §5.3, §5.5).

The volatile lists below are EXACTLY the spec §5.5 contract. Do NOT add
entries without a master-spec amendment: an over-broad normalizer re-creates
failure mode F1 by masking real diffs. Per-scenario VALUE masking (random sim
data) is manifest-driven and handled by hlo_pass/s3_pass, never here.

Normalization semantics per §5.5:
- identity fields (uuids, run_id, data_request_id): uuid-MAPPED via
  UuidMapper so parent/child links and the uuid5 process derivation are
  checked, not ignored;
- time fields (any *_timestamp, epoch_ns): collapsed to "TS";
- environment/code identity (codehash/codepath/funcname, hlo_version,
  exec_id, action_etc, dummy/simulation/access, aux_file_paths): DROPPED;
- host identity (orch_key/orch_host/orch_port, and `machine_name` when it
  belongs to a MachineModel — the `orchestrator`/`action_server` sub-dicts,
  or a bare top-level key): collapsed to "HOST" (presence still checked).
  `machine_name` inside a `samples_in`/`samples_out` entry is SampleModel
  identity (interpolated into `global_label`), not host identity, so it is
  NOT collapsed there — a differing sample `machine_name` must surface as a
  real diff;
- *_output_dir strings: timestamp components normalized via the §5.1 grammar;
- ordering hazards (samples_in/out, files, dispatched_*_abbr): stable-sorted
  before diffing;
- absent == empty (clean_dict pruning, §5.3): canonicalize drops
  None/''/[]/{} recursively on BOTH sides.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional, Union

from helao.helpers.yml_tools import yml_load

from harness.classify import normalize_name, normalize_relpath
from harness.uuidmap import UuidMapper

# --- §5.5 volatile lists (exhaustive; keep in lockstep with the spec) ------
UUID_KEY_SUFFIXES = ("_uuid",)
UUID_EXACT_KEYS = {"run_id", "data_request_id"}
TIMESTAMP_KEY_SUFFIXES = ("_timestamp",)
TIMESTAMP_EXACT_KEYS = {"epoch_ns"}
DROP_KEY_SUFFIXES = ("_codehash", "_codepath", "_funcname")
DROP_EXACT_KEYS = {
    "hlo_version",
    "exec_id",
    "action_etc",
    "dummy",
    "simulation",
    "access",
    "aux_file_paths",
}
HOST_EXACT_KEYS = {"orch_key", "orch_host", "orch_port", "machine_name"}
OUTPUT_DIR_KEY_SUFFIX = "_output_dir"
# §5.5: FileInfo.file_name (in an -act.yml `files` entry) is
# os.path.basename(file_path) — a single path element that may carry a volatile
# wall-clock component (e.g. AxisCamExec's cam_NNNNNN_<%y%m%d.%H%M%S>.jpg).
# Route it through the §5.1 name grammar (normalize_name) so timestamped frame
# filenames normalize identically on both sides; deterministic basenames (the
# common case: <label>-<idx>.hlo) match no grammar rule and pass through
# unchanged, so this is a no-op for every existing scenario.
FILENAME_KEYS = {"file_name"}
# §5.5 ordering hazards: sort by a stable key before diffing.
SORT_LIST_KEYS = {
    "dispatched_actions_abbr",
    "dispatched_experiments_abbr",
    "files",
    "samples_in",
    "samples_out",
}


def to_plain(obj: Any) -> Any:
    """Convert ruamel round-trip containers to plain dict/list recursively."""
    if isinstance(obj, dict):
        return {str(k): to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    return obj


def load_yml_plain(path: Union[str, Path]) -> Any:
    """Load a YAML file into plain Python containers."""
    return to_plain(yml_load(Path(path)))


def _stable_key(item: Any) -> str:
    return json.dumps(item, sort_keys=True, default=str)


def canonicalize(d: dict) -> dict:
    """absent == empty (§5.3): drop None/''/[]/{}, and NaN.

    clean_dict's `as_dict()` maps NaN -> None (`nan2None`), and its
    `_cleanupdict` pruning then drops that None as empty — so a NaN field is
    effectively DROPPED (absent), never a present null. Match that here.
    """
    out = {}
    for k, v in d.items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        if isinstance(v, float) and math.isnan(v):
            continue
        out[k] = v
    return out


def normalize_meta(
    obj: Any,
    mapper: UuidMapper,
    key: Optional[str] = None,
    in_samples: bool = False,
) -> Any:
    """Apply §5.5 normalization to a loaded YAML/JSON object, recursively.

    `in_samples` threads whether the current subtree is nested inside a
    `samples_in`/`samples_out` entry. `machine_name` is ambiguous by bare key
    name alone: on `MachineModel` (the `orchestrator`/`action_server`
    sub-dicts, or a top-level key) it is host identity and gets collapsed to
    "HOST"; on `SampleModel` (inside `samples_in`/`samples_out`) it is sample
    identity and must be left alone so a real difference surfaces.
    """
    if isinstance(obj, dict):
        out: dict = {}
        for k, v in obj.items():
            ks = str(k)
            child_in_samples = in_samples or ks in ("samples_in", "samples_out")
            if ks.endswith(DROP_KEY_SUFFIXES) or ks in DROP_EXACT_KEYS:
                continue
            if ks in HOST_EXACT_KEYS and not (
                ks == "machine_name" and child_in_samples
            ):
                out[ks] = "HOST"
                continue
            if ks.endswith(TIMESTAMP_KEY_SUFFIXES) or ks in TIMESTAMP_EXACT_KEYS:
                out[ks] = "TS"
                continue
            if ks.endswith(UUID_KEY_SUFFIXES) or ks in UUID_EXACT_KEYS:
                out[ks] = mapper.sub_any(v)
                continue
            out[ks] = normalize_meta(v, mapper, key=ks, in_samples=child_in_samples)
        for k in SORT_LIST_KEYS:
            if k in out and isinstance(out[k], list):
                out[k] = sorted(out[k], key=_stable_key)
        return canonicalize(out)
    if isinstance(obj, list):
        return [normalize_meta(v, mapper, key=key, in_samples=in_samples) for v in obj]
    if isinstance(obj, str):
        # embedded uuids (per-sample action_uuid strings, S3 key strings) map;
        # *_output_dir values additionally get the §5.1 grammar treatment.
        s = mapper.sub(obj)
        if key is not None and key.endswith(OUTPUT_DIR_KEY_SUFFIX):
            s = normalize_relpath(s)
        elif key in FILENAME_KEYS:
            s = normalize_name(s)
        return s
    return obj


def apply_meta_key_mask(
    meta: Any, dotted_keys: list[str], sentinel: str = "MASKED"
) -> Any:
    """Neutralize the VALUE at each dotted key path, in place, if present.

    The manifest-driven meta-side analogue of masked_hlo_columns (§6.4): a
    driver may write data-derived summary values back into -act.yml
    ``action_params`` (e.g. ``t_s__mean_final``) that vary run-to-run and are
    not covered by the §5.5 volatile lists in ``normalize_meta``. Masking sets
    the leaf to ``sentinel`` on BOTH sides so the value stops diffing, while
    leaving the key present so a one-sided presence difference still surfaces.
    A dotted path whose intermediate or leaf key is absent is left untouched
    (nothing is created), so structural absence is still diffed normally.
    """
    for dotted in dotted_keys:
        parts = dotted.split(".")
        node = meta
        for p in parts[:-1]:
            if isinstance(node, dict) and p in node:
                node = node[p]
            else:
                node = None
                break
        if isinstance(node, dict) and parts[-1] in node:
            node[parts[-1]] = sentinel
    return meta


def diff_meta(golden: Any, candidate: Any, path: str = "") -> list[dict]:
    """Structural diff of two ALREADY-NORMALIZED objects; [] when identical."""
    diffs: list[dict] = []
    if isinstance(golden, bool) != isinstance(candidate, bool) or (
        type(golden) is not type(candidate)
        and not (
            isinstance(golden, (int, float)) and isinstance(candidate, (int, float))
        )
    ):
        diffs.append(
            {"key": path, "golden": repr(golden), "candidate": repr(candidate)}
        )
        return diffs
    if isinstance(golden, dict) and isinstance(candidate, dict):
        for k in sorted(set(golden) | set(candidate)):
            kp = f"{path}.{k}" if path else str(k)
            if k not in golden:
                diffs.append(
                    {"key": kp, "golden": "<absent>", "candidate": candidate[k]}
                )
            elif k not in candidate:
                diffs.append({"key": kp, "golden": golden[k], "candidate": "<absent>"})
            else:
                diffs.extend(diff_meta(golden[k], candidate[k], kp))
        return diffs
    if isinstance(golden, list) and isinstance(candidate, list):
        if len(golden) != len(candidate):
            diffs.append(
                {
                    "key": f"{path}.len" if path else "len",
                    "golden": len(golden),
                    "candidate": len(candidate),
                }
            )
            return diffs
        for i, (g, c) in enumerate(zip(golden, candidate)):
            diffs.extend(diff_meta(g, c, f"{path}[{i}]"))
        return diffs
    if golden != candidate:
        diffs.append({"key": path, "golden": golden, "candidate": candidate})
    return diffs


def diff_prg(golden: dict, candidate: dict) -> list[dict]:
    """.prg sidecars: only the terminal s3/api booleans are contractual (§5.7)."""
    diffs = []
    for k in ("s3", "api"):
        if golden.get(k) != candidate.get(k):
            diffs.append(
                {"key": k, "golden": golden.get(k), "candidate": candidate.get(k)}
            )
    return diffs
