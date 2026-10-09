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
    (root / "RUNS_FINISHED" / "x" / "a-seq.yml").write_text(
        "file_type: sequence\n", encoding="utf-8"
    )
    (root / "LOGS").mkdir()
    (root / "LOGS" / "ORCH.log").write_text("not captured", encoding="utf-8")
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


def test_assert_fresh_rejects_a_root_holding_only_a_manual_run(tmp_path):
    """RUNS_DIAG counts. A manual action lands ONLY there.

    This is the case that produced a bad golden: the GM-4 legacy baseline
    was captured on a root still holding GM-3's manual action, because the
    freshness check looked at RUNS_FINISHED and RUNS_SYNCED only. Those
    three stale artifacts mint three uuids before GM-4's own first
    sequence, so every downstream uuid index shifts -- 365 diffs against a
    candidate that was byte-identical everywhere the scenario wrote.
    """
    import pytest

    from harness.capture import assert_fresh

    diag = tmp_path / "RUNS_DIAG" / "26.32" / "0814" / "TS__seq--acquire_data__manual"
    diag.mkdir(parents=True)
    (diag / "260814.132716737675-seq.yml").write_text(
        "sequence_uuid: x\n", encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="RUNS_DIAG"):
        assert_fresh(tmp_path)


def test_assert_fresh_accepts_a_root_with_empty_run_trees(tmp_path):
    """Empty directories are what a launched-but-unused rig leaves."""
    from harness.capture import assert_fresh

    for tree in ("RUNS_ACTIVE", "RUNS_FINISHED", "RUNS_SYNCED", "RUNS_DIAG"):
        (tmp_path / tree / "26.32").mkdir(parents=True)

    assert_fresh(tmp_path)  # must not raise


def _act(dir_, status: str) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "260925.120000000000-act.yml").write_text(
        f"file_type: action\naction_status:\n- {status}\n", encoding="utf-8"
    )


def test_assert_fresh_refuses_a_root_dirty_under_the_new_trees(tmp_path):
    """A29/A28: the guard was blind to RUNS and DIAG, so a root holding a
    whole previous run read as fresh and every uuid index in the capture
    shifted -- the 365-phantom-diff failure, one layout later."""
    from harness.capture import assert_fresh

    import pytest

    _act(tmp_path / "RUNS" / "2026" / "0925" / "seq" / "exp" / "act", "finished")

    with pytest.raises(RuntimeError, match="RUNS"):
        assert_fresh(tmp_path)


def test_runs_active_empty_is_not_vacuous_under_the_single_tree(tmp_path):
    """The legacy check returned True over a RUNS_ACTIVE that is never
    created, so quiesce settled instantly and snapshotted a mid-flight tree."""
    from harness.capture import runs_active_empty

    assert not runs_active_empty(tmp_path), "an empty root is not a settled run"

    act_dir = tmp_path / "RUNS" / "2026" / "0925" / "seq" / "exp" / "act"
    _act(act_dir, "active")
    assert not runs_active_empty(tmp_path), "an active -act.yml means in flight"

    _act(act_dir, "finished")
    assert runs_active_empty(tmp_path)


def test_runs_active_empty_keeps_the_legacy_arm(tmp_path):
    """A pre-cut-over station still answers from RUNS_ACTIVE."""
    from harness.capture import runs_active_empty

    (tmp_path / "RUNS_ACTIVE" / "26.39").mkdir(parents=True)
    assert runs_active_empty(tmp_path)
    (tmp_path / "RUNS_ACTIVE" / "26.39" / "x-act.yml").write_text(
        "file_type: action\n", encoding="utf-8"
    )
    assert not runs_active_empty(tmp_path)
