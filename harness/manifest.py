"""Provenance manifest for golden-master capture sets (spec §6.1 / §6.5).

A golden set without a manifest is REJECTED by the parity gate — this is the
structural countermeasure to failure mode F1 (hand-built fixture trees have
no capture provenance and must fail loudly, not silently pass).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Dict, List

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
