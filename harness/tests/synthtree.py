"""Synthetic mini-trees for NORMALIZER unit tests ONLY.

These trees are NOT parity fixtures: spec §6.1/D4 forbids hand-built golden
masters, and the gate enforces that with the provenance-manifest hard-fail.
Unit tests of the normalizer itself are the sanctioned exception; when a test
needs the gate to accept a synthetic tree it attaches a manifest EXPLICITLY
via attach_manifest(), whose notes field says exactly what it is.
"""

import uuid
from pathlib import Path

from harness import HARNESS_VERSION
from harness.manifest import ProvenanceManifest


def _u(n: int) -> str:
    return str(uuid.UUID(int=n))


def build_tree(root: Path, seed: int = 0) -> dict:
    """Create <root>/RUNS_FINISHED/... with 1 seq / 1 exp / 1 act / 1 hlo.

    ``seed`` offsets every uuid so two builds simulate two captures of the
    same run differing only in volatile identity. Returns the identifiers and
    directories used, for assertions.
    """
    seq_uuid = _u(seed + 1)
    exp_uuid = _u(seed + 2)
    act_uuid = _u(seed + 3)
    seq_dir = root / "RUNS_FINISHED" / "25.28" / "0716" / "131415__GMTEST__golden"
    exp_dir = seq_dir / "250716.131420__TEST_exp"
    act_dir = exp_dir / "0__0__SIM__acquire_data"
    act_dir.mkdir(parents=True)
    (seq_dir / "250716.131415123456-seq.yml").write_text(
        "file_type: sequence\n"
        f"sequence_uuid: {seq_uuid}\n"
        "sequence_name: GMTEST\n"
        "sequence_label: golden\n"
        "sequence_timestamp: 2025-07-16 13:14:15.123456\n"
        "sequence_status:\n  - finished\n"
        "dummy: true\n"
    )
    (exp_dir / "250716.131420123456-exp.yml").write_text(
        "file_type: experiment\n"
        f"experiment_uuid: {exp_uuid}\n"
        f"sequence_uuid: {seq_uuid}\n"
        "experiment_name: TEST_exp\n"
        "experiment_timestamp: 2025-07-16 13:14:20.123456\n"
        "experiment_status:\n  - finished\n"
    )
    (act_dir / "250716.131421123456-act.yml").write_text(
        "file_type: action\n"
        f"action_uuid: {act_uuid}\n"
        f"experiment_uuid: {exp_uuid}\n"
        f"sequence_uuid: {seq_uuid}\n"
        "action_name: acquire_data\n"
        "action_timestamp: 2025-07-16 13:14:21.123456\n"
        "action_status:\n  - finished\n"
        "action_params:\n  duration: 2.0\n"
    )
    (act_dir / "WsSim-0.0.0.0__0.hlo").write_text(
        "hlo_version: '2025.07.07'\n"
        "action_name: WsSim\n"
        "column_headings:\n"
        "  - t_s\n"
        "  - series_0\n"
        "epoch_ns: 1752671661000000000\n"
        "%%\n"
        '{"t_s": 0.0, "series_0": 0.5}\n'
        '{"t_s": 0.1, "series_0": 0.6}\n'
    )
    return {
        "seq_uuid": seq_uuid,
        "exp_uuid": exp_uuid,
        "act_uuid": act_uuid,
        "seq_dir": seq_dir,
        "exp_dir": exp_dir,
        "act_dir": act_dir,
    }


def attach_manifest(
    golden_dir: Path,
    masked: dict | None = None,
    tolerance: dict | None = None,
    content_masked: dict | None = None,
) -> None:
    ProvenanceManifest(
        scenario="SYNTH",
        config_prefix="synthetic-unit-test",
        config_path="synthetic-unit-test",
        legacy_git_sha="0" * 40,
        launch_cmd="synthetic-unit-test",
        sequence_name="GMTEST",
        sequence_params={},
        capture_timestamp="2026-07-16T00:00:00",
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=masked or {},
        hlo_row_count_tolerance=tolerance or {},
        content_masked_files=content_masked or {},
        notes="synthetic tree for normalizer unit tests ONLY — never a parity golden",
    ).save(golden_dir)
