"""Correcting a plate serial recorded as the plate id: ``record`` and ``analyses``.

Every record here is synthetic (plate 12345, serial 123455, directory
``X-1234550``) and built under ``tmp_path``. The fixture carries the real
traps: a float in an ``.hlo`` that holds the serial's digits by coincidence,
path fields that contain the serial, and a standard sample that must not move.
"""

import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from helao.core.drivers.data import analysis_layout
from helao.core.tests import set_plate_id
from helao.core.tests.set_plate_id import main, rewrite_doc
from helao.deploy.test.servers.action.sim_db_server import RecordingS3Client
from helao.helpers.plate_api import HTEPlateAPI, PlateAPIUnavailable
from helao.helpers.yml_tools import yml_dumps, yml_load

OLD, NEW = 123455, 12345
SEQ_UUID = "00000000-0000-0000-0000-000000000900"
OTHER_SEQ_UUID = "00000000-0000-0000-0000-000000000999"
EXP_UUID = "00000000-0000-0000-0000-000000000901"
ACT_SAMPLE = "00000000-0000-0000-0000-000000000902"
ACT_STD = "00000000-0000-0000-0000-000000000903"
PRC_SAMPLE = "00000000-0000-0000-0000-000000000904"
PRC_STD = "00000000-0000-0000-0000-000000000905"
ANA_UUID = "00000000-0000-0000-0000-000000000906"
OLD_LABEL = "legacy__solid__123455_7"
NEW_LABEL = "legacy__solid__12345_7"
STD_LABEL = "ref-std__solid__std_1"
SEQ_NAME = "120155__GRID_multiscan__X-1234550"
SEQ_MEMBER = "251003.120155000001-seq.yml"
SEQ_PRG = "251003.120155000001-seq.prg"
EXP_DIR = "251003.120155__GRID_scan"
EXP_MEMBER = f"{EXP_DIR}/251003.120155000002-exp.yml"
ACT_SAMPLE_DIR = f"{EXP_DIR}/0__0__X__scan"
ACT_STD_DIR = f"{EXP_DIR}/1__0__X__scan"
ACT_SAMPLE_MEMBER = f"{ACT_SAMPLE_DIR}/251003.120155000003-act.yml"
ACT_STD_MEMBER = f"{ACT_STD_DIR}/251003.120155000004-act.yml"
HLO_NAME = "scan-0.0.0.0__0.hlo"
OUT_DIR = f"25.39/1003/{SEQ_NAME}"
HLO_BYTES = (
    b"hlo_version: 1.0\naction_name: scan\ncolumn_headings: [t_s, v]\n%%\n"
    b'{"t_s": 0.0, "v": 0.1234559999}\n{"t_s": 1.0, "v": 0.2}\n'
)


@pytest.fixture(autouse=True)
def _plate_api(monkeypatch):
    """Nothing here may reach a real plate API; the default answer is the plate."""
    monkeypatch.delenv("HELAO_CREDENTIALS", raising=False)
    set_api(monkeypatch, {"plate_id": NEW, "serial_no": OLD})


def set_api(monkeypatch, answer):
    """Make ``HTEPlateAPI.lookup_plate`` return ``answer`` or raise it."""

    def lookup(self, plateid):
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(HTEPlateAPI, "lookup_plate", lookup)


def _sample(plate_id, label, act_uuid, no):
    return {
        "plate_id": plate_id,
        "global_label": label,
        "sample_type": "solid",
        "sample_no": no,
        "action_uuid": [act_uuid],
    }


def _act(act_uuid, order, prc_uuid, plate_id, label, exp_label=None):
    return {
        "action_uuid": act_uuid,
        "action_name": "scan",
        "action_order": order,
        "action_actual_order": order,
        "orch_submit_order": order,
        "action_split": 0,
        "action_timestamp": "251003.120155000100",
        "experiment_uuid": EXP_UUID,
        "process_uuid": prc_uuid,
        "process_finish": True,
        "process_contrib": ["samples_in", "files"],
        "action_params": {},
        "technique_name": "GRID_scan",
        "action_output_dir": f"{OUT_DIR}/{EXP_DIR}/{order}__0__X__scan",
        "samples_in": [_sample(plate_id, label, act_uuid, order + 7)],
        "files": [
            {
                "file_name": HLO_NAME,
                "file_type": "helao__file",
                "sample": [label],
            }
        ],
    }


def _prc(prc_uuid, act, sequence_uuid=SEQ_UUID):
    return {
        "process_uuid": prc_uuid,
        "sequence_uuid": sequence_uuid,
        "experiment_uuid": EXP_UUID,
        "technique_name": "GRID_scan",
        "samples_in": act["samples_in"],
        "files": act["files"],
    }


def build_record(tmp_path, *, exp_params=None, seq_plate_id=OLD):
    """The zip, its ``PROCESSES`` mirror and the member table.

    Returns ``(zip_path, process_dir, sample_prc_path)``.
    """
    sample = _act(ACT_SAMPLE, 0, PRC_SAMPLE, OLD, OLD_LABEL)
    std = _act(ACT_STD, 1, PRC_STD, None, STD_LABEL)
    seq = {
        "sequence_uuid": SEQ_UUID,
        "sequence_name": "GRID_multiscan",
        "sequence_label": "X",
        "sequence_params": {
            "plate_id": seq_plate_id,
            "source_foldername": "20251003_X_123455",
        },
        "sequence_output_dir": OUT_DIR,
        "planned_experiments": [{"experiment_output_dir": f"{OUT_DIR}/{EXP_DIR}"}],
    }
    exp = {
        "experiment_uuid": EXP_UUID,
        "experiment_name": "GRID_scan",
        "sequence_uuid": SEQ_UUID,
        "technique_name": "GRID_scan",
        "run_type": "test",
        "experiment_params": exp_params or {},
        "experiment_output_dir": f"{OUT_DIR}/{EXP_DIR}",
        "planned_actions": [
            {"action_output_dir": sample["action_output_dir"]},
            {"action_output_dir": std["action_output_dir"]},
        ],
        "process_order_groups": {0: [0], 1: [1]},
        "process_list": [PRC_SAMPLE, PRC_STD],
    }
    day = tmp_path / "RUNS_SYNCED" / "25.39" / "1003"
    day.mkdir(parents=True)
    z = day / f"{SEQ_NAME}.zip"
    members = [
        (SEQ_MEMBER, yml_dumps(seq), zipfile.ZIP_DEFLATED, (2025, 10, 3, 12, 1, 55)),
        (
            SEQ_PRG,
            "yml: /x/y-seq.yml\napi: true\ns3: true\n",
            zipfile.ZIP_DEFLATED,
            (2025, 10, 3, 12, 2, 0),
        ),
        (EXP_MEMBER, yml_dumps(exp), zipfile.ZIP_DEFLATED, (2025, 10, 3, 12, 2, 2)),
        (
            ACT_SAMPLE_MEMBER,
            yml_dumps(sample),
            zipfile.ZIP_DEFLATED,
            (2025, 10, 3, 12, 2, 4),
        ),
        (
            ACT_SAMPLE_MEMBER[:-3] + "prg",
            "yml: /x/a-act.yml\ns3: true\n",
            zipfile.ZIP_DEFLATED,
            (2025, 10, 3, 12, 2, 6),
        ),
        (
            f"{ACT_SAMPLE_DIR}/{HLO_NAME}",
            HLO_BYTES,
            zipfile.ZIP_STORED,
            (2025, 10, 3, 12, 2, 8),
        ),
        (
            ACT_STD_MEMBER,
            yml_dumps(std),
            zipfile.ZIP_DEFLATED,
            (2025, 10, 3, 12, 2, 10),
        ),
        (
            ACT_STD_MEMBER[:-3] + "prg",
            "yml: /x/b-act.yml\ns3: true\n",
            zipfile.ZIP_DEFLATED,
            (2025, 10, 3, 12, 2, 12),
        ),
        (
            f"{ACT_STD_DIR}/{HLO_NAME}",
            HLO_BYTES,
            zipfile.ZIP_STORED,
            (2025, 10, 3, 12, 2, 14),
        ),
    ]
    with zipfile.ZipFile(z, "w") as zf:
        for name, data, ctype, stamp in members:
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = ctype
            zf.writestr(info, data)

    pdir = tmp_path / "PROCESSES" / "25.39" / "1003" / SEQ_NAME / EXP_DIR
    pdir.mkdir(parents=True)
    sample_prc = pdir / f"0__{PRC_SAMPLE}__GRID_scan-prc.yml"
    sample_prc.write_text(yml_dumps(_prc(PRC_SAMPLE, sample)))
    (pdir / f"1__{PRC_STD}__GRID_scan-prc.yml").write_text(
        yml_dumps(_prc(PRC_STD, std))
    )
    (pdir / f"0__{OTHER_SEQ_UUID}__GRID_scan-prc.yml").write_text(
        yml_dumps(_prc(OTHER_SEQ_UUID, sample, sequence_uuid=OTHER_SEQ_UUID))
    )
    return z, pdir.parent, sample_prc


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tree_bytes(root: Path) -> dict:
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _members(z: Path) -> dict:
    with zipfile.ZipFile(z) as zf:
        return {
            i.filename: (
                hashlib.sha256(zf.read(i)).hexdigest(),
                i.compress_type,
                i.date_time,
            )
            for i in zf.infolist()
        }


def _read(z: Path, name: str) -> dict:
    with zipfile.ZipFile(z) as zf:
        return yml_load(zf.read(name).decode())


def _run(z, *extra, old=OLD, new=NEW):
    return main(["record", str(z), "--old", str(old), "--new", str(new), *extra])


def _twin(tmp_path: Path) -> Path:
    return tmp_path / "RUNS_FINISHED" / "25.39" / "1003" / SEQ_NAME


# --------------------------------------------------------------- rewrite_doc


def test_rewrite_doc_returns_a_copy_and_keeps_types():
    doc = {
        "sequence_params": {"plate_id": OLD, "source_foldername": "a_123455"},
        "sequence_output_dir": "x/X-1234550",
    }
    new, changes, unclassified = rewrite_doc(doc, "seq", OLD, NEW)
    assert doc["sequence_params"]["plate_id"] == OLD  # the input is never mutated
    assert new["sequence_params"]["plate_id"] == NEW
    assert type(new["sequence_params"]["plate_id"]) is int
    assert changes == [f"sequence_params.plate_id {OLD} -> {NEW}"]
    assert unclassified == []

    as_text = {"sequence_params": {"plate_id": str(OLD)}}
    new, _, _ = rewrite_doc(as_text, "seq", OLD, NEW)
    assert new["sequence_params"]["plate_id"] == str(NEW)


def test_rewrite_doc_reports_unclassified_and_ignores_floats():
    doc = {
        "experiment_params": {"note": "plate 123455", "n": OLD, "f": 0.1234559999},
        "experiment_output_dir": "x/X-1234550",
    }
    _, changes, unclassified = rewrite_doc(doc, "exp", OLD, NEW)
    assert changes == []
    assert sorted(unclassified) == [
        "experiment_params.n = 123455",
        "experiment_params.note = plate 123455",
    ]


# ------------------------------------------------------------------ record


def test_rules_rewrite_plate_identity_and_nothing_else(tmp_path, capsys):
    z, pdir, _ = build_record(tmp_path)
    assert _run(z, "--no-reset") == 0
    out = capsys.readouterr().out

    seq = _read(z, SEQ_MEMBER)
    assert seq["sequence_params"]["plate_id"] == NEW
    assert type(seq["sequence_params"]["plate_id"]) is int
    sample = _read(z, ACT_SAMPLE_MEMBER)
    assert sample["samples_in"][0]["plate_id"] == NEW
    assert sample["samples_in"][0]["global_label"] == NEW_LABEL
    assert sample["files"][0]["sample"] == [NEW_LABEL]
    std = _read(z, ACT_STD_MEMBER)
    assert std["samples_in"][0]["plate_id"] is None
    assert std["samples_in"][0]["global_label"] == STD_LABEL
    assert std["files"][0]["sample"] == [STD_LABEL]
    # Paths keep the serial: they are where the files really are.
    assert seq["sequence_output_dir"] == OUT_DIR
    assert seq["sequence_params"]["source_foldername"] == "20251003_X_123455"
    assert sample["action_output_dir"].startswith(OUT_DIR)
    assert "123455" in sample["action_output_dir"]
    assert "action_output_dir x" in out and "source_foldername x1" in out
    assert "LEFT sequence_output_dir x1" in out


def test_dry_run_writes_nothing_and_reports_seven_changes(tmp_path, capsys):
    z, pdir, _ = build_record(tmp_path)
    zip_before = _sha(z)
    prc_before = _tree_bytes(pdir)

    assert _run(z, "--dry-run") == 0
    out = capsys.readouterr().out

    assert _sha(z) == zip_before
    assert _tree_bytes(pdir) == prc_before
    assert not _twin(tmp_path).exists()
    assert not z.with_suffix(".orig").exists()
    # seq plate_id (1) + sample act (3) + sample prc (3)
    assert len([ln for ln in out.splitlines() if " -> " in ln]) == 7
    assert "--dry-run: nothing written." in out


def test_real_run_changes_exactly_the_seq_and_the_sample_act(tmp_path):
    z, pdir, sample_prc = build_record(tmp_path)
    before = _members(z)

    assert _run(z) == 0

    orig = z.with_suffix(".orig")  # the handback renames the rewritten zip
    after = _members(orig)
    assert set(after) == set(before)
    changed = {n for n in before if before[n][0] != after[n][0]}
    assert changed == {SEQ_MEMBER, ACT_SAMPLE_MEMBER}
    for name in before:  # sha256 differs only for those two; the rest is identical
        assert before[name][1:] == after[name][1:], name  # compress_type, date_time
    # The hlo holding the numeric coincidence is byte-identical.
    with zipfile.ZipFile(orig) as zf:
        assert b"0.1234559999" in zf.read(f"{ACT_SAMPLE_DIR}/{HLO_NAME}")
    prc = yml_load(sample_prc)
    assert prc["samples_in"][0]["global_label"] == NEW_LABEL
    assert prc["files"][0]["sample"] == [NEW_LABEL]


def test_a_second_run_is_a_no_op_reported_as_already_corrected(tmp_path, capsys):
    z, _, _ = build_record(tmp_path)
    assert _run(z, "--no-reset") == 0
    capsys.readouterr()
    after_first = _sha(z)

    assert _run(z) == 0
    out = capsys.readouterr().out

    assert "already corrected" in out
    assert "made 0 change(s)" in out
    assert _sha(z.with_suffix(".orig")) == after_first  # nothing was rewritten again


@pytest.mark.parametrize(
    "case",
    [
        "seq_plate_999999",
        "unclassified",
        "api_none",
        "api_unavailable",
        "serial_mismatch",
        "orig_exists",
        "twin_not_empty",
    ],
)
def test_refusals_write_nothing(tmp_path, monkeypatch, capsys, case):
    z, pdir, _ = build_record(
        tmp_path,
        exp_params={"note": "plate 123455"} if case == "unclassified" else None,
        seq_plate_id=999999 if case == "seq_plate_999999" else OLD,
    )
    if case == "api_none":
        set_api(monkeypatch, None)
    elif case == "api_unavailable":
        set_api(monkeypatch, PlateAPIUnavailable("HTTP 500"))
    elif case == "serial_mismatch":
        set_api(monkeypatch, {"plate_id": NEW, "serial_no": 123450})
    elif case == "orig_exists":
        z.with_suffix(".orig").write_bytes(b"earlier")
    elif case == "twin_not_empty":
        _twin(tmp_path).mkdir(parents=True)
        (_twin(tmp_path) / "earlier.txt").write_text("x")
    zip_before, prc_before = _sha(z), _tree_bytes(pdir)

    assert _run(z) == 1

    assert _sha(z) == zip_before
    assert _tree_bytes(pdir) == prc_before
    assert "REFUSED" in capsys.readouterr().err


def test_unclassified_refusal_names_the_file_and_path(tmp_path, capsys):
    z, _, _ = build_record(tmp_path, exp_params={"note": "plate 123455"})
    assert _run(z) == 1
    err = capsys.readouterr().err
    assert f"{EXP_MEMBER}: experiment_params.note = plate 123455" in err


def test_allow_serial_mismatch_continues_with_a_warning(tmp_path, monkeypatch, capsys):
    z, _, _ = build_record(tmp_path)
    set_api(monkeypatch, {"plate_id": NEW, "serial_no": 123450})
    assert _run(z) == 1
    capsys.readouterr()

    assert _run(z, "--allow-serial-mismatch") == 0
    out = capsys.readouterr().out
    assert "WARNING" in out and "123450" in out
    assert (
        _read(z.with_suffix(".orig"), SEQ_MEMBER)["sequence_params"]["plate_id"] == NEW
    )


def test_a_foreign_sequences_process_yml_is_left_alone_and_reported(tmp_path, capsys):
    z, pdir, _ = build_record(tmp_path)
    foreign = next(pdir.rglob(f"*{OTHER_SEQ_UUID}*-prc.yml"))
    before = foreign.read_bytes()

    assert _run(z, "--no-reset") == 0

    assert foreign.read_bytes() == before
    assert "not this record's" in capsys.readouterr().out


def test_handback_extracts_without_prg_and_prints_the_finish_yml_call(tmp_path, capsys):
    z, _, _ = build_record(tmp_path)
    assert _run(z) == 0
    out = capsys.readouterr().out

    twin = _twin(tmp_path)
    assert (twin / SEQ_MEMBER).is_file()
    assert not list(twin.rglob("*.prg"))
    assert not z.exists()
    assert z.with_suffix(".orig").is_file()
    assert "/finish_yml" in out
    assert str(twin / SEQ_MEMBER) in out
    # The corrected yml is what was extracted.
    assert yml_load(twin / SEQ_MEMBER)["sequence_params"]["plate_id"] == NEW


# ---------------------------------------------------------------- analyses


def _ana_yml(label=OLD_LABEL):
    return {
        "analysis_uuid": ANA_UUID,
        "analysis_name": "GRID_normalize",
        "process_uuid": PRC_SAMPLE,
        "global_sample_label": label,
        "inputs": [
            {"global_sample_label": label},
            {"global_sample_label": STD_LABEL},
        ],
    }


class FakeLoader:
    """The slice of ``HelaoLoader`` the tool uses, over a recording S3 client."""

    def __init__(self, root: Path, stored: dict, cli: object = "recording"):
        self.root = root
        self.stored = stored
        self.cli = RecordingS3Client(root) if cli == "recording" else cli
        self.s3_bucket = "b"

    def get_bytes(self, bucket, key):
        written = self.root / bucket / key
        if written.exists():
            return io.BytesIO(written.read_bytes())
        return io.BytesIO(json.dumps(self.stored[key]).encode())

    @property
    def uploads(self) -> int:
        manifest = self.root / "manifest.jsonl"
        return len(manifest.read_text().splitlines()) if manifest.exists() else 0


def build_analysis(
    tmp_path, monkeypatch, *, stored_label=OLD_LABEL, cli: object = "recording"
):
    """One analysis yml on disk, its S3 body in the fake loader, and the loader."""
    _, pdir, _ = build_record(tmp_path)
    ana_dir = (
        tmp_path / "ANALYSES" / "2025" / "1004" / "101010__GRID_normalize__X-1234550"
    )
    ana_dir.mkdir(parents=True)
    yml = ana_dir / f"{ANA_UUID}.yml"
    yml.write_text(yml_dumps(_ana_yml()))
    (ana_dir / f"{ANA_UUID}_output_array.json").write_text('{"v": [0.1234559999]}')
    loader = FakeLoader(
        tmp_path / "S3",
        {f"analysis/{ANA_UUID}.json": json.loads(json.dumps(_ana_yml(stored_label)))},
        cli=cli,
    )
    monkeypatch.setattr(set_plate_id, "_make_loader", lambda: loader)

    async def no_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(analysis_layout.asyncio, "sleep", no_sleep)
    return pdir, yml, ana_dir, loader


def _ana(pdir, tmp_path, *extra):
    return main(
        [
            "analyses",
            str(pdir),
            "--sequence-uuid",
            SEQ_UUID,
            "--old",
            str(OLD),
            "--new",
            str(NEW),
            "--analyses-root",
            str(tmp_path / "ANALYSES"),
            *extra,
        ]
    )


def _s3_body(tmp_path):
    return json.loads(
        (tmp_path / "S3" / "b" / "analysis" / f"{ANA_UUID}.json").read_text()
    )


def test_analyses_dry_run_records_nothing(tmp_path, monkeypatch, capsys):
    pdir, yml, _, loader = build_analysis(tmp_path, monkeypatch)
    before = yml.read_bytes()

    assert _ana(pdir, tmp_path, "--dry-run") == 0
    out = capsys.readouterr().out

    assert loader.uploads == 0
    assert yml.read_bytes() == before
    assert len([ln for ln in out.splitlines() if ln.startswith("  yml ")]) == 2
    assert len([ln for ln in out.splitlines() if ln.startswith("  s3 ")]) == 2
    assert f"s3://b/analysis/{ANA_UUID}.json" in out


def test_analyses_real_run_overwrites_the_same_body_and_yml(tmp_path, monkeypatch):
    pdir, yml, ana_dir, loader = build_analysis(tmp_path, monkeypatch)
    array_before = (ana_dir / f"{ANA_UUID}_output_array.json").read_bytes()

    assert _ana(pdir, tmp_path) == 0

    assert loader.uploads == 1
    for doc in (_s3_body(tmp_path), yml_load(yml)):
        assert doc["global_sample_label"] == NEW_LABEL
        assert doc["inputs"][0]["global_sample_label"] == NEW_LABEL
        assert doc["inputs"][1]["global_sample_label"] == STD_LABEL
        assert doc["analysis_uuid"] == ANA_UUID  # never re-minted
    assert (ana_dir / f"{ANA_UUID}_output_array.json").read_bytes() == array_before
    assert yml.parent.name.endswith("X-1234550")  # the directory is a path; left alone


def test_analyses_refuse_a_body_that_disagrees_with_the_yml(tmp_path, monkeypatch):
    pdir, yml, _, loader = build_analysis(
        tmp_path, monkeypatch, stored_label="legacy__solid__123455_8"
    )
    before = yml.read_bytes()

    assert _ana(pdir, tmp_path) == 1

    assert loader.uploads == 0
    assert yml.read_bytes() == before


def test_analyses_upload_failure_leaves_the_yml_unchanged(tmp_path, monkeypatch):
    class Failing:
        def upload_fileobj(self, *a, **k):
            raise OSError("S3 down")

    pdir, yml, _, _ = build_analysis(tmp_path, monkeypatch, cli=Failing())
    before = yml.read_bytes()

    assert _ana(pdir, tmp_path) == 1

    assert yml.read_bytes() == before


def test_analyses_second_run_does_nothing(tmp_path, monkeypatch, capsys):
    pdir, yml, _, loader = build_analysis(tmp_path, monkeypatch)
    assert _ana(pdir, tmp_path) == 0
    done = yml.read_bytes()
    capsys.readouterr()

    assert _ana(pdir, tmp_path) == 0

    assert loader.uploads == 1  # still only the first run's
    assert yml.read_bytes() == done
    assert "already corrected" in capsys.readouterr().out


def test_analyses_complete_the_local_write_when_s3_is_already_new(
    tmp_path, monkeypatch
):
    pdir, yml, _, loader = build_analysis(tmp_path, monkeypatch, stored_label=NEW_LABEL)

    assert _ana(pdir, tmp_path) == 0

    assert loader.uploads == 0
    doc = yml_load(yml)
    assert doc["global_sample_label"] == NEW_LABEL
    assert doc["inputs"][0]["global_sample_label"] == NEW_LABEL
    assert doc["inputs"][1]["global_sample_label"] == STD_LABEL


def test_analyses_refuse_when_the_s3_client_is_not_configured(tmp_path, monkeypatch):
    pdir, yml, _, loader = build_analysis(tmp_path, monkeypatch, cli=None)
    before = yml.read_bytes()

    assert _ana(pdir, tmp_path) == 1

    assert loader.uploads == 0
    assert yml.read_bytes() == before


@pytest.mark.parametrize(
    "case", ["api_none", "api_unavailable", "serial_mismatch"], ids=str
)
def test_analyses_refuse_unless_the_plate_checks_out(
    tmp_path, monkeypatch, capsys, case
):
    pdir, yml, _, loader = build_analysis(tmp_path, monkeypatch)
    set_api(
        monkeypatch,
        {
            "api_none": None,
            "api_unavailable": PlateAPIUnavailable("HTTP 500"),
            "serial_mismatch": {"plate_id": NEW, "serial_no": 123450},
        }[case],
    )
    before = yml.read_bytes()

    assert _ana(pdir, tmp_path) == 1

    assert loader.uploads == 0
    assert yml.read_bytes() == before
    assert "REFUSED" in capsys.readouterr().err


def test_analyses_allow_serial_mismatch_continues_with_a_warning(
    tmp_path, monkeypatch, capsys
):
    pdir, yml, _, loader = build_analysis(tmp_path, monkeypatch)
    set_api(monkeypatch, {"plate_id": NEW, "serial_no": 123450})

    assert _ana(pdir, tmp_path, "--allow-serial-mismatch") == 0

    assert "WARNING" in capsys.readouterr().out
    assert loader.uploads == 1
    assert yml_load(yml)["global_sample_label"] == NEW_LABEL


def test_analyses_refuse_when_no_analysis_yml_matches(tmp_path, monkeypatch, capsys):
    pdir, yml, _, loader = build_analysis(tmp_path, monkeypatch)
    empty = tmp_path / "EMPTY_ANALYSES"
    empty.mkdir()
    before = yml.read_bytes()

    rc = main(
        [
            "analyses",
            str(pdir),
            "--sequence-uuid",
            SEQ_UUID,
            "--old",
            str(OLD),
            "--new",
            str(NEW),
            "--analyses-root",
            str(empty),
        ]
    )

    assert rc == 1
    assert loader.uploads == 0
    assert yml.read_bytes() == before
    assert "no analysis yml" in capsys.readouterr().err


@pytest.mark.parametrize("failure", [KeyError("gone"), OSError("S3 down")], ids=type)
def test_analyses_an_unreadable_s3_body_fails_that_analysis_and_the_run_goes_on(
    tmp_path, monkeypatch, capsys, failure
):
    pdir, yml, ana_dir, loader = build_analysis(tmp_path, monkeypatch)
    lost_uuid = "00000000-0000-0000-0000-000000000895"  # sorts before ANA_UUID
    lost = ana_dir / f"{lost_uuid}.yml"
    lost.write_text(yml_dumps({**_ana_yml(), "analysis_uuid": lost_uuid}))
    lost_before = lost.read_bytes()
    real_get = loader.get_bytes

    def get_bytes(bucket, key):
        if lost_uuid in key:
            raise failure
        return real_get(bucket, key)

    monkeypatch.setattr(loader, "get_bytes", get_bytes)

    assert _ana(pdir, tmp_path) == 1

    assert lost.read_bytes() == lost_before
    assert yml_load(yml)["global_sample_label"] == NEW_LABEL  # the run went on
    assert loader.uploads == 1
    assert lost_uuid in capsys.readouterr().err


def test_analyses_parse_only_ymls_whose_header_names_this_sequence(
    tmp_path, monkeypatch, capsys
):
    """A station's ANALYSES tree holds ~10^5 ymls; only this sequence's are parsed."""
    pdir, _yml, ana_dir, _loader = build_analysis(tmp_path, monkeypatch)
    foreign = ana_dir.parent / "101011__GRID_normalize__X-1234550"
    foreign.mkdir()
    for i in range(5):
        other = dict(
            _ana_yml(), process_uuid=f"00000000-0000-0000-0000-00000000{i:04d}"
        )
        (foreign / f"other{i}.yml").write_text(yml_dumps(other))
    parsed = []
    real_load = set_plate_id.yml_load

    def counting_load(path, *a, **k):
        parsed.append(Path(path).name)
        return real_load(path, *a, **k)

    monkeypatch.setattr(set_plate_id, "yml_load", counting_load)
    assert _ana(pdir, tmp_path, "--dry-run") == 0
    assert not any(name.startswith("other") for name in parsed)
    assert f"{ANA_UUID}.yml" in parsed


def test_analyses_still_parse_a_yml_whose_header_lacks_process_uuid(
    tmp_path, monkeypatch, capsys
):
    pdir, yml, _ana_dir, _loader = build_analysis(tmp_path, monkeypatch)
    doc = _ana_yml()
    uuid = doc.pop("process_uuid")
    padded = {"zz_padding": "x" * (set_plate_id._HEADER_BYTES + 100), **doc}
    padded["process_uuid"] = uuid  # last, beyond the header window
    yml.write_text(yml_dumps(padded))
    assert _ana(pdir, tmp_path, "--dry-run") == 0
    out = capsys.readouterr().out
    assert len([ln for ln in out.splitlines() if ln.startswith("  yml ")]) == 2


def test_analyses_search_only_the_named_analysis_dirs(tmp_path, monkeypatch, capsys):
    pdir, _yml, ana_dir, _loader = build_analysis(tmp_path, monkeypatch)
    rel = ana_dir.relative_to(tmp_path)  # ANALYSES/2025/1004/<dir>
    parsed = []
    real_load = set_plate_id.yml_load

    def counting_load(path, *a, **k):
        parsed.append(Path(path))
        return real_load(path, *a, **k)

    monkeypatch.setattr(set_plate_id, "yml_load", counting_load)
    decoy = tmp_path / "ANALYSES" / "2025" / "1005" / "101012__GRID_normalize__X"
    decoy.mkdir(parents=True)
    (decoy / "decoy.yml").write_text(yml_dumps(dict(_ana_yml())))
    assert _ana(pdir, tmp_path, "--dry-run", "--analysis-dir", str(rel)) == 0
    assert not any(p.parent == decoy for p in parsed)
    out = capsys.readouterr().out
    assert len([ln for ln in out.splitlines() if ln.startswith("  yml ")]) == 2


def test_analyses_refuse_a_missing_analysis_dir(tmp_path, monkeypatch, capsys):
    pdir, yml, _ana_dir, loader = build_analysis(tmp_path, monkeypatch)
    before = yml.read_bytes()
    assert _ana(pdir, tmp_path, "--dry-run", "--analysis-dir", "ANALYSES/no/such") == 1
    assert yml.read_bytes() == before and loader.uploads == 0
    captured = capsys.readouterr()
    assert (
        "--analysis-dir ANALYSES/no/such is not a directory"
        in captured.out + captured.err
    )
