"""Synthetic mini-trees for NORMALIZER unit tests ONLY.

These trees are NOT parity fixtures: spec §6.1/D4 forbids hand-built golden
masters, and the gate enforces that with the provenance-manifest hard-fail.
Unit tests of the normalizer itself are the sanctioned exception; when a test
needs the gate to accept a synthetic tree it attaches a manifest EXPLICITLY
via attach_manifest(), whose notes field says exactly what it is.
"""

import shutil
import uuid
import zipfile
from pathlib import Path

from harness import HARNESS_VERSION
from harness.manifest import ProvenanceManifest
from helao.helpers.meta_io import write_meta
from helao.helpers.to_json import hlo_json_dumps

_HEADER = {
    "hlo_version": "2025.07.07",
    "action_name": "WsSim",
    "column_headings": ["t_s", "series_0"],
    "epoch_ns": 1752671661000000000,
}
_ROWS = [{"t_s": 0.0, "series_0": 0.5}, {"t_s": 0.1, "series_0": 0.6}]


def _u(n: int) -> str:
    return str(uuid.UUID(int=n))


def build_tree(
    root: Path, seed: int = 0, fmt: str = "legacy", extended: bool = False
) -> dict:
    """Create <root>/RUNS_FINISHED/... with 1 seq / 1 exp / 1 act / 1 data file.

    ``seed`` offsets every uuid so two builds simulate two captures of the
    same run differing only in volatile identity. ``fmt`` picks the storage
    format: ``legacy`` (.yml records, .hlo data), ``new`` (.json records,
    .meta.json + .jsonl data) or ``mixed`` (a legacy -seq.yml above new
    -exp/-act records and a pair -- a sequence that straddled the upgrade).
    ``extended`` adds the action's ``files`` entry and a colocated process
    record, which reader-parity tests need and normalizer tests must not see.
    Returns the identifiers and directories used, for assertions.
    """
    seq_uuid = _u(seed + 1)
    exp_uuid = _u(seed + 2)
    act_uuid = _u(seed + 3)
    prc_uuid = _u(seed + 4)
    seq_dir = root / "RUNS_FINISHED" / "25.28" / "0716" / "131415__GMTEST__golden"
    exp_dir = seq_dir / "250716.131420__TEST_exp"
    act_dir = exp_dir / "0__0__SIM__acquire_data"
    act_dir.mkdir(parents=True)
    new_seq = fmt == "new"
    new_rest = fmt in ("new", "mixed")
    seq_meta = {
        "file_type": "sequence",
        "sequence_uuid": seq_uuid,
        "sequence_name": "GMTEST",
        "sequence_label": "golden",
        "sequence_timestamp": "2025-07-16 13:14:15.123456",
        "sequence_status": ["finished"],
        "dummy": True,
    }
    exp_meta = {
        "file_type": "experiment",
        "experiment_uuid": exp_uuid,
        "sequence_uuid": seq_uuid,
        "experiment_name": "TEST_exp",
        "experiment_timestamp": "2025-07-16 13:14:20.123456",
        "experiment_status": ["finished"],
    }
    act_meta = {
        "file_type": "action",
        "action_uuid": act_uuid,
        "experiment_uuid": exp_uuid,
        "sequence_uuid": seq_uuid,
        "action_name": "acquire_data",
        "action_timestamp": "2025-07-16 13:14:21.123456",
        "action_status": ["finished"],
        "action_params": {"duration": 2.0},
    }
    data_name = "WsSim-0.0.0.0__0" + (".jsonl" if new_rest else ".hlo")
    if extended:
        act_meta["files"] = [{"file_name": data_name, "file_type": "wssim_helao__file"}]
    if new_seq:
        write_meta(seq_dir / "250716.131415123456-seq.json", seq_meta)
    else:
        (seq_dir / "250716.131415123456-seq.yml").write_text(
            "file_type: sequence\n"
            f"sequence_uuid: {seq_uuid}\n"
            "sequence_name: GMTEST\n"
            "sequence_label: golden\n"
            "sequence_timestamp: 2025-07-16 13:14:15.123456\n"
            "sequence_status:\n  - finished\n"
            "dummy: true\n",
            encoding="utf-8",
        )
    if new_rest:
        write_meta(exp_dir / "250716.131420123456-exp.json", exp_meta)
        write_meta(act_dir / "250716.131421123456-act.json", act_meta)
        write_meta(act_dir / "WsSim-0.0.0.0__0.meta.json", _HEADER)
        (act_dir / "WsSim-0.0.0.0__0.jsonl").write_text(
            "".join(hlo_json_dumps(r) + "\n" for r in _ROWS), encoding="utf-8"
        )
    else:
        (exp_dir / "250716.131420123456-exp.yml").write_text(
            "file_type: experiment\n"
            f"experiment_uuid: {exp_uuid}\n"
            f"sequence_uuid: {seq_uuid}\n"
            "experiment_name: TEST_exp\n"
            "experiment_timestamp: 2025-07-16 13:14:20.123456\n"
            "experiment_status:\n  - finished\n",
            encoding="utf-8",
        )
        act_text = (
            "file_type: action\n"
            f"action_uuid: {act_uuid}\n"
            f"experiment_uuid: {exp_uuid}\n"
            f"sequence_uuid: {seq_uuid}\n"
            "action_name: acquire_data\n"
            "action_timestamp: 2025-07-16 13:14:21.123456\n"
            "action_status:\n  - finished\n"
            "action_params:\n  duration: 2.0\n"
        )
        if extended:
            act_text += (
                f"files:\n  - file_name: {data_name}\n"
                "    file_type: wssim_helao__file\n"
            )
        (act_dir / "250716.131421123456-act.yml").write_text(act_text, encoding="utf-8")
        (act_dir / "WsSim-0.0.0.0__0.hlo").write_text(
            "hlo_version: '2025.07.07'\n"
            "action_name: WsSim\n"
            "column_headings:\n"
            "  - t_s\n"
            "  - series_0\n"
            "epoch_ns: 1752671661000000000\n"
            "%%\n"
            '{"t_s": 0.0, "series_0": 0.5}\n'
            '{"t_s": 0.1, "series_0": 0.6}\n',
            encoding="utf-8",
        )
    if extended:
        prc = {
            "process_uuid": prc_uuid,
            "experiment_uuid": exp_uuid,
            "process_group_index": 0,
        }
        if new_rest:
            write_meta(exp_dir / f"0__{prc_uuid}__SIM-prc.json", prc)
        else:
            (exp_dir / f"0__{prc_uuid}__SIM-prc.yml").write_text(
                f"process_uuid: {prc_uuid}\nexperiment_uuid: {exp_uuid}\n"
                "process_group_index: 0\n",
                encoding="utf-8",
            )
    return {
        "seq_uuid": seq_uuid,
        "exp_uuid": exp_uuid,
        "act_uuid": act_uuid,
        "prc_uuid": prc_uuid,
        "seq_dir": seq_dir,
        "exp_dir": exp_dir,
        "act_dir": act_dir,
    }


def zip_sequence(root: Path, info: dict) -> Path:
    """Archive ``info['seq_dir']`` as a synced sequence zip and remove the directory."""
    seq_dir = info["seq_dir"]
    zp = root / "RUNS_SYNCED" / "25.28" / "0716" / f"{seq_dir.name}.zip"
    zp.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zp, "w") as zf:
        for f in sorted(seq_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(seq_dir).as_posix())
    shutil.rmtree(seq_dir)
    return zp


def attach_manifest(
    golden_dir: Path,
    masked: dict | None = None,
    tolerance: dict | None = None,
    content_masked: dict | None = None,
    meta_masked: dict | None = None,
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
        masked_meta_keys=meta_masked or {},
        notes="synthetic tree for normalizer unit tests ONLY — never a parity golden",
    ).save(golden_dir)
