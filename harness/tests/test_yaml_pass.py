"""§5.5 volatile normalization: exactly the spec list, nothing more."""

from harness.uuidmap import UuidMapper
from harness.yaml_pass import canonicalize, diff_meta, diff_prg, normalize_meta

U1 = "00000000-0000-0000-0000-000000000001"
U2 = "00000000-0000-0000-0000-000000000002"


def test_uuid_keys_are_mapped_not_dropped():
    m = UuidMapper()
    out = normalize_meta({"action_uuid": U1, "experiment_uuid": U2, "run_id": U1}, m)
    assert out == {
        "action_uuid": "UUID-0",
        "experiment_uuid": "UUID-1",
        "run_id": "UUID-0",  # same raw uuid -> same ordinal: the LINK is checked
    }


def test_timestamps_and_code_identity():
    m = UuidMapper()
    out = normalize_meta(
        {
            "action_timestamp": "2025-07-16 13:14:21.123456",
            "action_finished_timestamp": "2025-07-16 13:15:00.000001",
            "epoch_ns": 1752671661000000000,
            "action_codehash": "abc123",
            "action_codepath": "/abs/host/path.py",
            "experiment_funcname": "SIM_websocket_data",
            "hlo_version": "2025.07.07",
            "exec_id": "acquire_data deadbeef",
            "dummy": True,
            "simulation": True,
            "access": "hte",
            "aux_file_paths": ["/abs/somewhere"],
            "orch_key": "ORCH",
            "orch_host": "127.0.0.1",
            "orch_port": 8001,
            "machine_name": "somehostname",
            "action_name": "acquire_data",
        },
        m,
    )
    assert out == {
        "action_timestamp": "TS",
        "action_finished_timestamp": "TS",
        "epoch_ns": "TS",
        "orch_key": "HOST",
        "orch_host": "HOST",
        "orch_port": "HOST",
        "machine_name": "HOST",
        "action_name": "acquire_data",
    }


def test_output_dir_paths_are_grammar_normalized():
    m = UuidMapper()
    out = normalize_meta(
        {
            "action_output_dir": "25.28/0716/131415__S__golden/250716.131420__E/0__0__SIM__acquire_data"
        },
        m,
    )
    assert out == {
        "action_output_dir": "YY.WW/MMDD/TS__S__golden/TS__E/0__0__SIM__acquire_data"
    }


def test_ordering_hazard_lists_are_sorted():
    m = UuidMapper()
    a = normalize_meta(
        {"samples_in": [{"global_label": "b"}, {"global_label": "a"}]}, m
    )
    b = normalize_meta(
        {"samples_in": [{"global_label": "a"}, {"global_label": "b"}]}, m
    )
    assert a == b


def test_absent_equals_empty():
    m = UuidMapper()
    a = normalize_meta({"action_params": {}, "files": [], "comment": "", "x": 1}, m)
    b = normalize_meta({"x": 1}, m)
    assert a == b == {"x": 1}
    assert canonicalize({"n": None, "s": "", "l": [], "d": {}, "keep": 0}) == {
        "keep": 0
    }


def test_non_volatile_content_diffs_are_reported():
    m1, m2 = UuidMapper(), UuidMapper()
    g = normalize_meta({"action_params": {"duration": 2.0}}, m1)
    c = normalize_meta({"action_params": {"duration": 3.0}}, m2)
    diffs = diff_meta(g, c)
    assert diffs == [{"key": "action_params.duration", "golden": 2.0, "candidate": 3.0}]


def test_diff_meta_reports_absent_keys_and_list_lengths():
    assert diff_meta({"a": 1}, {}) == [
        {"key": "a", "golden": 1, "candidate": "<absent>"}
    ]
    assert diff_meta({"l": [1, 2]}, {"l": [1]}) == [
        {"key": "l.len", "golden": 2, "candidate": 1}
    ]


def test_volatile_field_raw_difference_does_not_diff():
    """Two captures with different raw timestamps/uuids/hosts normalize to the
    same tokens, so a real content diff is the ONLY thing diff_meta reports."""
    m1, m2 = UuidMapper(), UuidMapper()
    g = normalize_meta(
        {
            "action_uuid": U1,
            "action_timestamp": "2025-07-16 13:14:21.123456",
            "orch_host": "10.0.0.1",
            "action_params": {"duration": 2.0},
        },
        m1,
    )
    c = normalize_meta(
        {
            "action_uuid": U2,
            "action_timestamp": "2025-07-16 14:00:00.000000",
            "orch_host": "192.168.1.5",
            "action_params": {"duration": 3.0},
        },
        m2,
    )
    assert diff_meta(g, c) == [
        {"key": "action_params.duration", "golden": 2.0, "candidate": 3.0}
    ]


def test_prg_compares_only_terminal_booleans():
    g = {"yml": "/abs/a", "s3": True, "api": True, "files_pending": ["x"]}
    c = {"yml": "/abs/b", "s3": True, "api": True, "files_pending": []}
    assert diff_prg(g, c) == []
    c2 = dict(c, s3=False)
    assert diff_prg(g, c2) == [{"key": "s3", "golden": True, "candidate": False}]
