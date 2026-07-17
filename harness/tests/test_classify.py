"""§5.1 directory grammar (timestamp strip) + §5.2 artifact-row classification."""

from harness.classify import (
    ArtifactRow,
    classify_file,
    normalize_name,
    normalize_relpath,
)


def test_normalize_timestamp_dir_levels():
    assert normalize_name("25.28") == "YY.WW"  # %y.%U week dir
    assert normalize_name("0716") == "MMDD"
    # sequence dir: HHMMSS__name__label[-plate...]
    assert (
        normalize_name("131415__SEQNAME__golden-27509") == "TS__SEQNAME__golden-27509"
    )
    # experiment dir: YYMMDD.HHMMSS__name
    assert (
        normalize_name("250716.131420__SIM_websocket_data") == "TS__SIM_websocket_data"
    )


def test_normalize_meta_filenames():
    assert normalize_name("250716.131415123456-seq.yml") == "TS-seq.yml"
    assert normalize_name("250716.131420123456-exp.yml") == "TS-exp.yml"
    assert normalize_name("250716.131421123456-act.yml") == "TS-act.yml"
    assert normalize_name("250716.131421123456-act.prg") == "TS-act.prg"
    assert normalize_name("131415__SEQNAME__golden.zip") == "TS__SEQNAME__golden.zip"
    assert (
        normalize_name("131415__SEQNAME__golden.zipdir") == "TS__SEQNAME__golden.zipdir"
    )


def test_non_timestamp_names_pass_through():
    # action dirs and hlo filenames carry no wall-clock component
    assert normalize_name("0__0__SIM__acquire_data") == "0__0__SIM__acquire_data"
    assert normalize_name("WsSim-0.0.0.0__0.hlo") == "WsSim-0.0.0.0__0.hlo"
    assert normalize_name("MANIFEST.txt") == "MANIFEST.txt"


def test_normalize_relpath_walks_every_element():
    rel = "RUNS_FINISHED/25.28/0716/131415__S__golden/250716.131420__E/0__0__SIM__acquire_data/250716.131421123456-act.yml"
    assert (
        normalize_relpath(rel)
        == "RUNS_FINISHED/YY.WW/MMDD/TS__S__golden/TS__E/0__0__SIM__acquire_data/TS-act.yml"
    )


def test_classify_rows():
    assert classify_file("RUNS_FINISHED/a/b-seq.yml") is ArtifactRow.SEQ_YML
    assert classify_file("RUNS_FINISHED/a/b-exp.yml") is ArtifactRow.EXP_YML
    assert classify_file("RUNS_FINISHED/a/b-act.yml") is ArtifactRow.ACT_YML
    assert classify_file("PROCESSES/a/0__x__t-prc.yml") is ArtifactRow.PRC_YML
    assert classify_file("RUNS_SYNCED/a/b-act.prg") is ArtifactRow.PRG
    assert classify_file("RUNS_FINISHED/a/x.hlo") is ArtifactRow.HLO
    assert classify_file("RUNS_FINISHED/a/x.parquet") is ArtifactRow.PARQUET
    assert classify_file("RUNS_SYNCED/25.28/0716/x.zip") is ArtifactRow.SEQ_ZIP
    assert classify_file("RUNS_ACTIVE/a/x.lock") is ArtifactRow.LOCK
    assert classify_file("RUNS_FINISHED/a/MANIFEST.txt") is ArtifactRow.MICRO_MANIFEST
    assert classify_file("ANALYSES/25.28/0716/x/u.yml") is ArtifactRow.ANALYSIS
    assert classify_file("S3_SIM/helao-sim/action/u.json") is ArtifactRow.S3_RECORD
    assert classify_file("RUNS_FINISHED/a/extra_output.csv") is ArtifactRow.AUX_FILE
    assert classify_file("LOGS/ORCH.log") is ArtifactRow.IGNORE
    assert classify_file("STATES/pids_golden_.pck") is ArtifactRow.IGNORE
