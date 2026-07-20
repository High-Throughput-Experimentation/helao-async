"""Provenance manifest for golden-master capture sets (spec §6.1 / §6.5).

A golden set without a manifest is REJECTED by the parity gate — this is the
structural countermeasure to failure mode F1 (hand-built fixture trees have
no capture provenance and must fail loudly, not silently pass).
"""

from __future__ import annotations

import dataclasses
import fnmatch
from pathlib import Path
from typing import Dict, List, Optional

from ruamel.yaml import YAML

_yaml = YAML(typ="safe")
_yaml.default_flow_style = False

MANIFEST_NAME = "provenance.yml"


class ManifestMissingError(Exception):
    """Raised when a golden set lacks a provenance manifest."""


@dataclasses.dataclass
class ProvenanceManifest:
    """Records how a golden set was captured from a real legacy run.

    The three masking fields are the ONLY sanctioned per-scenario value-masking
    configuration (§6.4): they live here, in the capture record, never in
    harness code, so the §5.5 volatile list stays exhaustive and auditable.

    - masked_hlo_columns: fnmatch pattern on the normalized .hlo (or
      .hlo.json) path -> data columns whose VALUES are masked (structure,
      presence, and — within tolerance — row counts are still compared).
    - hlo_row_count_tolerance: fnmatch pattern -> max |row-count difference|
      allowed for masked columns (poll-paced sim executors jitter by a row
      or two run-to-run; 0 = exact).
    - content_masked_files: fnmatch pattern -> "line-count" (compare number
      of lines only; for files derived from masked random data, e.g. the
      hlo_to_csv output) or "skip" (presence only).
    - masked_meta_keys: fnmatch pattern on the normalized YAML meta path
      (-act/-exp/-seq/-prc.yml, analysis) -> dotted key paths whose VALUES are
      masked in BOTH golden and candidate before diffing (e.g.
      "action_params.t_s__mean_final"). Presence is still compared (a key
      present on only one side still surfaces); only the leaf value is
      neutralized. This is the meta-side analogue of masked_hlo_columns, for
      data-derived summary values a driver writes back into -act.yml
      action_params (which normalize_meta's §5.5 volatile lists do not cover).
    """

    scenario: str
    config_prefix: str
    config_path: str
    legacy_git_sha: str
    launch_cmd: str
    sequence_name: str
    sequence_params: dict
    capture_timestamp: str
    harness_version: str
    masked_hlo_columns: Dict[str, List[str]] = dataclasses.field(default_factory=dict)
    hlo_row_count_tolerance: Dict[str, int] = dataclasses.field(default_factory=dict)
    content_masked_files: Dict[str, str] = dataclasses.field(default_factory=dict)
    masked_meta_keys: Dict[str, List[str]] = dataclasses.field(default_factory=dict)
    notes: str = ""

    def save(self, golden_dir: Path) -> Path:
        path = Path(golden_dir) / MANIFEST_NAME
        with open(path, "w") as f:
            _yaml.dump(dataclasses.asdict(self), f)
        return path

    @classmethod
    def load(cls, golden_dir: Path) -> "ProvenanceManifest":
        path = Path(golden_dir) / MANIFEST_NAME
        if not path.exists():
            raise ManifestMissingError(
                f"golden set {golden_dir} has no {MANIFEST_NAME}; golden masters "
                "must be captured from real legacy runs (spec §6.5, D4) — "
                "hand-built fixture trees are forbidden in the parity suite"
            )
        with open(path) as f:
            data = _yaml.load(f)
        return cls(**{k: v for k, v in dict(data).items()})

    def masked_meta_keys_for(self, norm: str) -> List[str]:
        """Dotted meta keys to mask for a normalized YAML path (fnmatch)."""
        out: List[str] = []
        for pattern, keys in (self.masked_meta_keys or {}).items():
            if fnmatch.fnmatch(norm, pattern):
                out.extend(keys)
        return out


def content_mask_mode(norm: str, manifest: "ProvenanceManifest") -> Optional[str]:
    """Look up a normalized path's ``content_masked_files`` mode, if any.

    Shared by the parity dispatcher (AUX_FILE rows) and the S3 pass (raw
    uploads under ``S3_SIM/`` classify as S3_RECORD, not AUX_FILE, but a
    masked-random-data file like a WsSim ``*.csv`` postprocess output is
    uploaded to S3 too and must be masked there the same way, per the same
    manifest-resident §6.4 lever — not a second, diverging code path).
    """
    for pattern, mode in (manifest.content_masked_files or {}).items():
        if fnmatch.fnmatch(norm, pattern):
            return mode
    return None
