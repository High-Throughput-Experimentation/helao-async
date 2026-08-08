"""The analysis arm of the S3 pass (P6c task 4).

`internal_s3_checks` pairs S3 *action* metas with on-disk act ymls. Analysis
records have no action counterpart -- their keys are `analysis/<uuid>.json`
and `analysis/<uuid>_output_<group>.json` -- so nothing in the rig looked at
them, which is the gap this closes for the deployment whose capture subject
emits them.

Every rule asserted here was read off the live writers on 2026-08-08:
`analysis_driver._calc_and_write_model` (the yml), `.sync_ana` (the uploads),
and `base_analysis.export_analysis` (the scalar/array split).
"""

import json
from pathlib import Path

from harness.s3_pass import (
    OUTPUT_GROUPS,
    assert_s3_analysis_rules,
    internal_s3_analysis_checks,
)

UUID = "3b1f0c2a-0000-4000-8000-00000000abcd"


def model_dict(**over) -> dict:
    base = {
        "analysis_uuid": UUID,
        "analysis_name": "icpms_local",
        "process_uuid": "9c2e0000-0000-4000-8000-0000000000ff",
        "outputs": [
            {
                "output_name": "scalar",
                "output_keys": ["mean", "n"],
                "output": {"mean": 1.5, "n": 3},
                "analysis_output_path": {"key": f"analysis/{UUID}_output_scalar.json"},
            },
            {
                "output_name": "array",
                "output_keys": ["trace"],
                # Empty BY CONSTRUCTION: export_analysis filters the embedded
                # copy to scalars for both groups. The arrays live in the
                # uploaded json, not here.
                "output": {},
                "analysis_output_path": {"key": f"analysis/{UUID}_output_array.json"},
            },
        ],
    }
    base.update(over)
    return base


def build_tree(
    tmp_path: Path,
    dir_name: str = "141530__icpms_local__A12",
    scalar: dict | None = None,
    array: dict | None = None,
    s3_model: dict | None = None,
) -> Path:
    """A capture root with one analysis, on disk and in the S3 recorder."""
    root = tmp_path / "root"
    ana_dir = root / "ANALYSES" / "26.31" / "0808" / dir_name
    ana_dir.mkdir(parents=True)
    disk = model_dict()
    (ana_dir / f"{UUID}.yml").write_text(json.dumps(disk))  # JSON is valid YAML

    scalar = {"mean": 1.5, "n": 3} if scalar is None else scalar
    array = {"trace": [1.0, 2.0, 3.0]} if array is None else array
    for group, payload in (("scalar", scalar), ("array", array)):
        (ana_dir / f"{UUID}_output_{group}.json").write_text(json.dumps(payload))

    s3_dir = root / "S3_SIM" / "helao-sim" / "analysis"
    s3_dir.mkdir(parents=True)
    (s3_dir / f"{UUID}.json").write_text(json.dumps(s3_model or disk))
    for group, payload in (("scalar", scalar), ("array", array)):
        (s3_dir / f"{UUID}_output_{group}.json").write_text(json.dumps(payload))
    return root


# --- the happy path, and the guard that it is not vacuous --------------------
def test_a_well_formed_analysis_capture_is_clean(tmp_path):
    assert internal_s3_analysis_checks(build_tree(tmp_path)) == []


def test_a_root_with_no_s3_recorder_yields_nothing_rather_than_erroring(tmp_path):
    (tmp_path / "root").mkdir()
    assert internal_s3_analysis_checks(tmp_path / "root") == []


def test_an_unpaired_s3_model_is_reported(tmp_path):
    root = build_tree(tmp_path)
    next((root / "ANALYSES").rglob(f"{UUID}.yml")).unlink()
    diffs = internal_s3_analysis_checks(root)
    assert any("matching on-disk" in str(d["golden"]) for d in diffs)


def test_a_directory_off_the_row_13_grammar_is_reported(tmp_path):
    root = build_tree(tmp_path, dir_name="icpms_local")
    diffs = internal_s3_analysis_checks(root)
    assert any(d["key"].endswith(":directory") for d in diffs)


# --- the group split ---------------------------------------------------------
def test_the_two_output_groups_are_the_only_ones_expected():
    assert OUTPUT_GROUPS == ("scalar", "array")


def test_an_array_in_the_scalar_group_is_reported(tmp_path):
    root = build_tree(tmp_path, scalar={"mean": [1.5], "n": 3})
    diffs = internal_s3_analysis_checks(root)
    assert any(d["key"].endswith(":group") for d in diffs)


def test_an_array_group_carrying_no_arrays_is_reported(tmp_path):
    root = build_tree(tmp_path, array={"trace": 1.0})
    diffs = internal_s3_analysis_checks(root)
    assert any(d["key"].endswith(":group") for d in diffs)


def test_a_payload_whose_keys_the_model_did_not_declare_is_reported(tmp_path):
    root = build_tree(tmp_path, scalar={"mean": 1.5, "n": 3, "smuggled": 0.0})
    diffs = internal_s3_analysis_checks(root)
    assert any(d["key"].endswith(":output_keys") for d in diffs)


def test_an_output_json_with_no_local_sibling_is_reported(tmp_path):
    root = build_tree(tmp_path)
    next((root / "ANALYSES").rglob(f"{UUID}_output_array.json")).unlink()
    diffs = internal_s3_analysis_checks(root)
    assert any("a local json of the same name" in str(d["golden"]) for d in diffs)


# --- the model body ----------------------------------------------------------
def test_the_s3_model_body_equals_the_yml_body():
    """MEASURED, and contrary to the P6c plan's prediction: there is no
    `strip_private` difference on this row. The uploaded object is the same
    `model_dict` the yml was dumped from, produced by `clean_dict()` with the
    default `strip_private=False`."""
    assert assert_s3_analysis_rules(model_dict(), model_dict()) == []
    drifted = model_dict(analysis_name="something_else")
    assert assert_s3_analysis_rules(model_dict(), drifted) != []


def test_a_divergent_uuid_between_the_two_copies_is_reported(tmp_path):
    root = build_tree(tmp_path, s3_model=model_dict(process_uuid="0" * 36))
    diffs = internal_s3_analysis_checks(root)
    assert any(d["key"].endswith(":process_uuid") for d in diffs)


def test_arrays_embedded_in_the_models_output_are_reported():
    """The array group's embedded `output` is empty by construction. If a
    future change starts embedding the arrays, the model body doubles in size
    and this fires rather than passing silently."""
    fat = model_dict()
    fat["outputs"][1]["output"] = {"trace": [1.0, 2.0, 3.0]}
    diffs = assert_s3_analysis_rules(model_dict(), fat)
    assert any(d["key"] == "outputs[1].output" for d in diffs)
