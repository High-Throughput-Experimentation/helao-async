"""NativeAnalysisArtifact + the shared analysis layout (hexagon P6e).

These pin the grammar that used to exist twice: once in the live analysis
server and once, drifted, inside a post-hoc converter. Every assertion here is
about a value that reaches disk or the bucket, so a future edit that changes one
of them has to change a test that says what the old value was.
"""

import asyncio
import json
from datetime import datetime

import pytest

from helao.core.drivers.data.analysis_layout import (
    analysis_dir,
    analysis_model_key,
    analysis_output_models,
    analysis_root,
    analysis_suffix,
    analysis_uuid_for,
    parse_analysis_timestamp,
    publish_outputs,
    sequence_part_of,
    upload_json,
)
from helao.hexagon.adapters.native.analysis_artifact import NativeAnalysisArtifact
from helao.hexagon.ports.analysis import AnalysisArtifactPort, AnalysisRecord
from helao.helpers.yml_tools import yml_load

BUCKET = "helao.data"
REGION = "us-west-2"
UUID_A = "06a77d44-4267-792f-8000-7304487140e5"
UUID_B = "06a77d44-432e-721e-8000-bebee862c3e7"
#: A real GM-C3 sequence directory: three ``__``-separated parts, so the
#: directory suffix comes from its trailing label.
SEQ_DIR = "115817__XAFS_wafer_grid_multiscan__Zn-100348"
ACTION_DIR = f"RUNS_FINISHED/26.19/0511/{SEQ_DIR}/260511.115817__XAFS_exp/{UUID_A}"


class RecordingUploader:
    """Stands in for S3: remembers every (key, body, compress) it is handed."""

    def __init__(self, ok: bool = True):
        self.ok = ok
        self.calls: list[tuple] = []

    async def __call__(self, msg, target, compress=False):
        self.calls.append((target, msg, compress))
        return self.ok

    @property
    def keys(self) -> list[str]:
        return [c[0] for c in self.calls]


def make_model(
    analysis_uuid: str = UUID_A,
    timestamp: str = "2026-08-08 18:13:40.157007",
    label: str = "legacy__solid__10034_13999",
) -> dict:
    """A cleaned analysis-model dict shaped like the GM-C3 golden's."""
    outputs = analysis_output_models(
        analysis_uuid,
        BUCKET,
        REGION,
        "processed.xafs_scan",
        [
            ("scalar", {"e0": 9665.5, "flat_coefs": [1.0, 2.0]}),
            ("array", {"processed_Energy": [1.0, 2.0, 3.0]}),
        ],
    )
    return {
        "analysis_uuid": analysis_uuid,
        "analysis_timestamp": timestamp,
        "analysis_name": "XAFS_normalize_flatten",
        "global_sample_label": label,
        "outputs": [o.model_dump(mode="json") for o in outputs],
    }


def make_record(**kwargs) -> AnalysisRecord:
    return AnalysisRecord(
        model=make_model(**kwargs),
        values={
            "e0": 9665.5,
            "flat_coefs": [1.0, 2.0],
            "processed_Energy": [1.0, 2.0, 3.0],
        },
        source_action_dir=ACTION_DIR,
    )


# --- grammar --------------------------------------------------------------


def test_analysis_root_hangs_off_the_config_root():
    assert analysis_root("/data/inst") == "/data/inst/ANALYSES"


def test_sequence_part_reads_the_third_element_from_the_end():
    assert sequence_part_of(ACTION_DIR) == SEQ_DIR


def test_sequence_part_accepts_a_windows_separated_path():
    """``action_output_dir`` is a Path field; on Windows str() backslashes it."""
    assert sequence_part_of(ACTION_DIR.replace("/", "\\")) == SEQ_DIR


def test_suffix_prefers_the_sequence_label():
    assert analysis_suffix(SEQ_DIR, "legacy__solid__10034_13999") == "__Zn-100348"


def test_suffix_falls_back_to_plate_id_plus_check_digit():
    # 1+0+0+3+4 = 8; the check digit is that sum mod 10.
    assert analysis_suffix("115817__XAFS", "legacy__solid__10034_13999") == "__100348"


def test_suffix_is_empty_when_neither_rule_applies():
    assert analysis_suffix("115817__XAFS", "some-other-label") == ""


def test_analysis_dir_takes_every_time_component_from_one_stamp():
    ts = datetime(2026, 8, 8, 18, 13, 40)
    assert analysis_dir("/r/ANALYSES", ts, "AN", "__lbl") == (
        "/r/ANALYSES/26.31/0808/181340__AN__lbl"
    )


def test_analysis_timestamp_parses_the_serialized_form():
    assert parse_analysis_timestamp(make_model()) == datetime(
        2026, 8, 8, 18, 13, 40, 157007
    )


def test_model_key_template():
    assert analysis_model_key(UUID_A) == f"analysis/{UUID_A}.json"


# --- output models --------------------------------------------------------


def test_output_models_strip_arrays_from_the_model_but_keep_their_keys():
    scalar, array = analysis_output_models(
        UUID_A,
        BUCKET,
        REGION,
        "t",
        [("scalar", {"e0": 1.0, "flat_coefs": [1, 2]}), ("array", {"spectrum": [1]})],
    )
    # `flat_coefs` is a list living in the SCALAR group -- the split is by
    # source, not by python type -- so it is named but not inlined.
    assert scalar.output_keys == ["e0", "flat_coefs"]
    assert scalar.output == {"e0": 1.0}
    assert array.output_keys == ["spectrum"]
    assert array.output == {}
    assert scalar.analysis_output_path.key == f"analysis/{UUID_A}_output_scalar.json"
    assert array.analysis_output_path.bucket == BUCKET


def test_empty_output_group_is_dropped():
    models = analysis_output_models(
        UUID_A, BUCKET, REGION, "t", [("scalar", {"a": 1}), ("array", {})]
    )
    assert [m.output_name for m in models] == ["scalar"]


# --- content-hash uuid ----------------------------------------------------


def _uuid(**over):
    args = dict(
        analysis_name="AN",
        analysis_params={"a": 1},
        process_uuid="p",
        global_sample_label="s",
        analysis_codehash="h",
        run_use="data",
    )
    args.update(over)
    return analysis_uuid_for(**args)


def test_analysis_uuid_is_stable_for_identical_identity():
    assert _uuid() == _uuid()


@pytest.mark.parametrize(
    "field,value",
    [
        ("analysis_name", "OTHER"),
        ("analysis_params", {"a": 2}),
        ("process_uuid", "q"),
        ("global_sample_label", "t"),
        ("analysis_codehash", "h2"),
        ("run_use", "calib"),
    ],
)
def test_every_identity_field_changes_the_analysis_uuid(field, value):
    assert _uuid(**{field: value}) != _uuid()


# --- publish --------------------------------------------------------------


def test_adapter_satisfies_the_port():
    assert isinstance(NativeAnalysisArtifact("/tmp/x"), AnalysisArtifactPort)


def test_publish_writes_the_golden_layout(tmp_path):
    art = NativeAnalysisArtifact(str(tmp_path / "ANALYSES"))
    record = make_record()
    assert asyncio.run(art.publish(record)) is True
    d = (
        tmp_path
        / "ANALYSES"
        / "26.31"
        / "0808"
        / "181340__XAFS_normalize_flatten__Zn-100348"
    )
    assert sorted(p.name for p in d.iterdir()) == [
        f"{UUID_A}.yml",
        f"{UUID_A}_output_array.json",
        f"{UUID_A}_output_scalar.json",
    ]
    assert yml_load(d / f"{UUID_A}.yml")["analysis_uuid"] == UUID_A
    # each group's JSON carries that group's values, arrays included
    assert json.loads((d / f"{UUID_A}_output_array.json").read_text()) == {
        "processed_Energy": [1.0, 2.0, 3.0]
    }
    assert json.loads((d / f"{UUID_A}_output_scalar.json").read_text()) == {
        "e0": 9665.5,
        "flat_coefs": [1.0, 2.0],
    }


def test_publishing_the_same_record_twice_leaves_one_record(tmp_path):
    art = NativeAnalysisArtifact(str(tmp_path / "ANALYSES"))
    asyncio.run(art.publish(make_record()))
    asyncio.run(art.publish(make_record()))
    files = sorted(p.name for p in (tmp_path / "ANALYSES").rglob("*") if p.is_file())
    assert files == [
        f"{UUID_A}.yml",
        f"{UUID_A}_output_array.json",
        f"{UUID_A}_output_scalar.json",
    ]


def test_local_only_writes_the_tree_and_uploads_nothing(tmp_path):
    up = RecordingUploader()
    art = NativeAnalysisArtifact(str(tmp_path / "ANALYSES"), uploader=None)
    assert asyncio.run(art.publish(make_record())) is True
    assert up.calls == []
    assert list((tmp_path / "ANALYSES").rglob("*.yml"))


def test_an_uploader_receives_the_model_and_every_group(tmp_path):
    up = RecordingUploader()
    art = NativeAnalysisArtifact(str(tmp_path / "ANALYSES"), uploader=up)
    assert asyncio.run(art.publish(make_record())) is True
    assert up.keys == [
        f"analysis/{UUID_A}.json",
        f"analysis/{UUID_A}_output_scalar.json",
        f"analysis/{UUID_A}_output_array.json",
    ]
    assert up.calls[0][1]["analysis_uuid"] == UUID_A


def test_a_failed_upload_fails_the_publish(tmp_path):
    art = NativeAnalysisArtifact(
        str(tmp_path / "ANALYSES"), uploader=RecordingUploader(ok=False)
    )
    assert asyncio.run(art.publish(make_record())) is False


# --- directory grouping (the determinism fix) -----------------------------

STRADDLE = [
    ("2026-08-08 20:23:32.948340", UUID_A),
    ("2026-08-08 20:23:33.005564", UUID_B),
]


def test_a_conversion_straddling_a_second_lands_in_one_directory(tmp_path):
    """The measured defect: per-analysis stamps split a batch by wall clock.

    Two golden runs of one GM-C3 conversion put all three analyses in a single
    directory; a third crossed a second boundary and produced two. The stamp is
    now taken once per conversion, so the batch cannot split.
    """
    art = NativeAnalysisArtifact(str(tmp_path / "ANALYSES"), group_dir=True)
    for ts, uid in STRADDLE:
        asyncio.run(art.publish(make_record(analysis_uuid=uid, timestamp=ts)))
    dirs = sorted(p.name for p in (tmp_path / "ANALYSES" / "26.31" / "0808").iterdir())
    assert dirs == ["202332__XAFS_normalize_flatten__Zn-100348"]


def test_the_server_shaped_ungrouped_adapter_still_splits(tmp_path):
    """``group_dir=False`` keeps the per-record stamp the live server writes."""
    art = NativeAnalysisArtifact(str(tmp_path / "ANALYSES"), group_dir=False)
    for ts, uid in STRADDLE:
        asyncio.run(art.publish(make_record(analysis_uuid=uid, timestamp=ts)))
    dirs = sorted(p.name for p in (tmp_path / "ANALYSES" / "26.31" / "0808").iterdir())
    assert dirs == [
        "202332__XAFS_normalize_flatten__Zn-100348",
        "202333__XAFS_normalize_flatten__Zn-100348",
    ]


def test_enqueue_defers_publication_and_flush_performs_it(tmp_path):
    art = NativeAnalysisArtifact(str(tmp_path / "ANALYSES"))

    async def run():
        for ts, uid in STRADDLE:
            await art.enqueue(make_record(analysis_uuid=uid, timestamp=ts))
        assert len(art.pending) == 2
        assert not (tmp_path / "ANALYSES").exists()
        assert await art.flush() is True

    asyncio.run(run())
    assert art.pending == []
    dirs = sorted(p.name for p in (tmp_path / "ANALYSES" / "26.31" / "0808").iterdir())
    assert dirs == ["202332__XAFS_normalize_flatten__Zn-100348"]


# --- uploader -------------------------------------------------------------


class FlakyClient:
    """Fails ``fail_times`` uploads, then records what it finally received."""

    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.attempts = 0
        self.received: bytes = b""

    def upload_fileobj(self, fileobj, bucket, key):
        self.attempts += 1
        fileobj.read(4)  # a partial read, as a failed transfer would leave
        if self.attempts <= self.fail_times:
            raise RuntimeError("boom")
        fileobj.seek(0)
        self.received = fileobj.read()


def test_upload_json_sends_the_serialized_body(tmp_path):
    client = FlakyClient()
    assert asyncio.run(upload_json(client, BUCKET, {"a": 1}, "k")) is True
    assert json.loads(client.received) == {"a": 1}


def test_upload_json_rewinds_before_a_retry(monkeypatch):
    """A retry that did not rewind would upload a truncated body as a success."""
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda *_: real_sleep(0))
    client = FlakyClient(fail_times=1)
    assert asyncio.run(upload_json(client, BUCKET, {"a": 1}, "k")) is True
    assert client.attempts == 2
    assert json.loads(client.received) == {"a": 1}


def test_upload_json_treats_an_unconfigured_client_as_success():
    assert asyncio.run(upload_json(None, BUCKET, {"a": 1}, "k")) is True


def test_publish_outputs_writes_group_bodies_without_an_uploader(tmp_path):
    model = make_model()
    d = tmp_path / "d"
    d.mkdir()
    ok = asyncio.run(
        publish_outputs(model, {"e0": 1.0, "processed_Energy": [1]}, str(d))
    )
    assert ok is True
    assert (d / f"{UUID_A}_output_scalar.json").is_file()
