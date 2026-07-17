"""Capture-rig pure parts: scenario builders + snapshot layout."""

from harness.capture import (
    SCENARIOS,
    build_gm1_sequence,
    build_gm2_sequence,
    build_gm4_sequence,
    snapshot_capture,
)


def test_gm1_sequence_shape():
    seq = build_gm1_sequence()
    assert seq.sequence_name == "SIM_websocket_data_seq"
    assert len(seq.planned_experiments) == 2
    d = seq.as_dict()
    assert d["planned_experiments"][0]["experiment_name"] == "SIM_websocket_data"
    assert d["planned_experiments"][0]["experiment_params"] == {
        "wait_time": 2.0,
        "data_duration": 4.0,
    }


def test_gm2_sequence_uses_library_function():
    seq = build_gm2_sequence()
    assert seq.sequence_name == "TEST_consecutive_noblocking"
    # 2 samples x 2 cycles = 4 experiments; cycles > 0 carry the global handoff
    assert len(seq.planned_experiments) == 4


def test_gm4_sequence_has_long_first_waits():
    seq = build_gm4_sequence("GM4_stop")
    d = seq.as_dict()
    assert all(
        e["experiment_params"]["wait_time"] == 20.0 for e in d["planned_experiments"]
    )


def test_scenario_registry_is_complete():
    assert set(SCENARIOS) == {"GM-1", "GM-2", "GM-3", "GM-4", "GM-5"}


def test_snapshot_capture_layout_and_freshness(tmp_path):
    root = tmp_path / "captroot"
    (root / "RUNS_FINISHED" / "x").mkdir(parents=True)
    (root / "RUNS_FINISHED" / "x" / "a-seq.yml").write_text("file_type: sequence\n")
    (root / "LOGS").mkdir()
    (root / "LOGS" / "ORCH.log").write_text("not captured")
    out = tmp_path / "golden" / "run1"
    snapshot_capture(
        root=root,
        out_dir=out,
        scenario="GM-1",
        config_prefix="golden",
        sequence_name="SIM_websocket_data_seq",
        sequence_params={},
        masked_hlo={},
        tolerance={},
        content_masked={},
    )
    assert (out / "root" / "RUNS_FINISHED" / "x" / "a-seq.yml").exists()
    assert not (out / "root" / "LOGS").exists()  # non-parity tops excluded
    assert (out / "provenance.yml").exists()
    import pytest

    with pytest.raises(FileExistsError):
        snapshot_capture(
            root=root,
            out_dir=out,
            scenario="GM-1",
            config_prefix="golden",
            sequence_name="x",
            sequence_params={},
            masked_hlo={},
            tolerance={},
            content_masked={},
        )
