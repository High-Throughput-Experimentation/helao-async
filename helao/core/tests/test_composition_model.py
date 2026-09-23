# helao/core/tests/test_composition_model.py
"""Turning a metadata-API process item into a CompositionRecord.

The fixtures here are trimmed copies of real responses captured from the
production metadata API for plate 10244 on 2026-09-22. Nothing in this file
performs a request.
"""

import pytest

from helao.ui.shared.composition import model

PROCESS_ITEM = {
    "process_uuid": "06a7e382-ee08-786f-8000-c6d582f2c3bc",
    "process_timestamp": "2026-08-13T11:57:41.000000",
    "process_name": "xrfs_nostds",
    "run_use": "pre_anneal",
    "sequence_uuid": "06a7e382-a773-731d-8000-d7e3e21eacec",
    "process_params": {
        "plate_id": 10244,
        "source_csv_label": "legacy__solid__10244_42",
        "stage_label": "42",
    },
    "files": [
        {
            "file_type": "edax_orbis_spc__file",
            "file_name": "asdep6.SPC",
            "action_uuid": "06a7e382-ee08-7843-8000-e3562725efd8",
        },
        {
            "file_type": "xrfs_quant_helao__json_file",
            "file_name": "xrfs_nostds-0.0.0.0__2.hlo.json",
            "action_uuid": "06a7e382-ee08-7843-8000-e3562725efd8",
        },
        {
            "file_type": "xrfspec_helao__json_file",
            "file_name": "xrfs_nostds-0.0.0.0__1.hlo.json",
            "action_uuid": "06a7e382-ee08-7843-8000-e3562725efd8",
        },
    ],
}

SEQUENCES = {
    "06a7e382-a773-731d-8000-d7e3e21eacec": {
        "sequence_uuid": "06a7e382-a773-731d-8000-d7e3e21eacec",
        "sequence_timestamp": "2026-08-13T11:54:21.000000",
        "sequence_label": "CoYPt-102441",
    }
}

QUANT = {
    "element": ["Co", "Y", "Y", "Pt", "Pt"],
    "transition": ["Co.K", "Y.K", "Y.L", "Pt.L", "Pt.M"],
    "net_counts": [271.2, 792.1, 1259.2, 44.7, 441.6],
    "nanomoles": [16.4, 79.8, 102.4, 1.9, 12.8],
    "atomic_fraction": [0.167, 0.814, None, 0.019, None],
    "global_sample_label": ["legacy__solid__10244_42"],
    "analysis_name": ["XRFS_quantification_analysis"],
    "output_type": ["composition.xrfs_quantification"],
    "calibration_date": ["2026-06-03"],
}


def test_sample_no_comes_from_the_source_csv_label() -> None:
    assert model.sample_no_from({"source_csv_label": "legacy__solid__10244_42"}) == 42


def test_sample_no_falls_back_to_stage_label() -> None:
    assert model.sample_no_from({"stage_label": "42"}) == 42


def test_sample_no_is_none_when_neither_is_usable() -> None:
    """A record with no sample number is dropped, never plotted at an invented
    position."""
    assert model.sample_no_from({}) is None
    assert model.sample_no_from({"source_csv_label": "no_digits_here_"}) is None
    assert model.sample_no_from({"stage_label": "centre"}) is None


def test_record_from_process_reads_both_file_roles() -> None:
    record = model.record_from_process(PROCESS_ITEM, SEQUENCES)
    assert record is not None
    assert record.quant_file_name == "xrfs_nostds-0.0.0.0__2.hlo.json"
    assert record.spectrum_file_name == "xrfs_nostds-0.0.0.0__1.hlo.json"
    assert record.quant_action_uuid == "06a7e382-ee08-7843-8000-e3562725efd8"


def test_record_from_process_carries_the_sequence_timestamp() -> None:
    """PROCESS records carry a null sequence_timestamp; it comes from the
    separate SEQUENCE search."""
    record = model.record_from_process(PROCESS_ITEM, SEQUENCES)
    assert record.sequence_timestamp == "2026-08-13T11:54:21.000000"


def test_record_from_process_survives_an_unknown_sequence() -> None:
    record = model.record_from_process(PROCESS_ITEM, {})
    assert record is not None
    assert record.sequence_timestamp == ""


def test_record_from_process_returns_none_without_a_sample_number() -> None:
    item = {**PROCESS_ITEM, "process_params": {"plate_id": 10244}}
    assert model.record_from_process(item, SEQUENCES) is None


def test_record_from_process_returns_none_without_a_quant_file() -> None:
    item = {
        **PROCESS_ITEM,
        "files": [f for f in PROCESS_ITEM["files"] if "quant" not in f["file_type"]],
    }
    assert model.record_from_process(item, SEQUENCES) is None


def test_with_values_builds_transition_to_unit() -> None:
    record = model.with_values(
        model.record_from_process(PROCESS_ITEM, SEQUENCES), QUANT
    )
    assert record.values["Co.K"]["net_counts"] == pytest.approx(271.2)
    assert record.values["Y.L"]["nanomoles"] == pytest.approx(102.4)


def test_with_values_keeps_a_null_atomic_fraction_as_none() -> None:
    """Y.L and Pt.M are uncalibrated. None is the honest value; 0.0 would plot."""
    record = model.with_values(
        model.record_from_process(PROCESS_ITEM, SEQUENCES), QUANT
    )
    assert record.values["Y.L"]["atomic_fraction"] is None
    assert record.values["Y.K"]["atomic_fraction"] == pytest.approx(0.814)


def test_with_values_drops_the_non_numeric_columns() -> None:
    """Handing a string column to `plots` raises from inside the render and
    takes the whole chart down."""
    record = model.with_values(
        model.record_from_process(PROCESS_ITEM, SEQUENCES), QUANT
    )
    for unit in record.values["Co.K"]:
        assert unit not in model.NON_NUMERIC_COLUMNS


def test_with_values_ignores_a_column_shorter_than_the_transitions() -> None:
    """`global_sample_label` has one entry for five transitions. A zip would
    silently truncate every other unit to one value."""
    record = model.with_values(
        model.record_from_process(PROCESS_ITEM, SEQUENCES), QUANT
    )
    assert len(record.values) == 5


def test_unit_and_transition_names_are_the_union_sorted() -> None:
    a = model.with_values(model.record_from_process(PROCESS_ITEM, SEQUENCES), QUANT)
    b = model.with_values(
        model.record_from_process(PROCESS_ITEM, SEQUENCES),
        {"transition": ["Fe.K"], "net_counts": [1.0]},
    )
    assert model.transition_names([a, b]) == [
        "Co.K",
        "Fe.K",
        "Pt.L",
        "Pt.M",
        "Y.K",
        "Y.L",
    ]
    assert model.unit_names([a, b]) == ["atomic_fraction", "nanomoles", "net_counts"]
