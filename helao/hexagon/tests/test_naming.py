"""Pin the §5.1/§5.2 naming grammar (pure functions + reused premodels)."""

from datetime import datetime
from uuid import UUID

from helao.hexagon.domain import naming
from helao.hexagon.domain.models import Sequence, Experiment


def test_meta_yml_filename_grammar():
    ts = datetime(2026, 7, 17, 13, 5, 9, 123456)
    assert naming.meta_yml_filename(ts, "act") == "260717.130509123456-act.yml"
    assert naming.meta_yml_filename(ts, "exp") == "260717.130509123456-exp.yml"
    assert naming.meta_yml_filename(ts, "seq") == "260717.130509123456-seq.yml"


def test_meta_yml_filename_rejects_unknown_kind():
    import pytest

    with pytest.raises(ValueError):
        naming.meta_yml_filename(datetime(2026, 1, 1), "prc")


def test_hlo_filename_grammar():
    # active_data_file.py:139 template, filenum = index in file_conn_keys
    assert naming.hlo_filename("CA", 3, 0, 0, 1, 0) == "CA-3.0.0.1__0.hlo"
    assert (
        naming.hlo_filename("OCV", 0, 2, 1, 0, 2, file_ext="csv")
        == "OCV-0.2.1.0__2.csv"
    )


def test_file_conn_key_is_md5_uuid():
    # base_meta_writer.py:154-168: UUID(md5(key).hexdigest())
    import hashlib

    key = "somekey"
    expect = UUID(hashlib.md5(key.encode("utf-8")).hexdigest())
    assert naming.new_file_conn_key(key) == expect


def test_dflt_file_conn_key_is_md5_of_str_none():
    assert naming.dflt_file_conn_key() == naming.new_file_conn_key(str(None))


def test_redirect_manual_dir():
    # the RUNS_ACTIVE -> RUNS_DIAG substitution, centralized (spec §4.2.3)
    assert (
        naming.redirect_manual_dir("C:/INST/RUNS_ACTIVE/26.28/0717/x")
        == "C:/INST/RUNS_DIAG/26.28/0717/x"
    )
    assert naming.redirect_manual_dir("no_state_dir/here") == "no_state_dir/here"


def test_is_nosync_file():
    # FileInfo.nosync=True for .hlo when action.sync_data is False
    assert naming.is_nosync_file("a__0.hlo", sync_data=False) is True
    assert naming.is_nosync_file("a__0.hlo", sync_data=True) is False
    assert naming.is_nosync_file("notes.csv", sync_data=False) is False


def test_sequence_dir_grammar_reused_from_premodels():
    seq = Sequence(
        sequence_name="test_seq",
        sequence_label="lab",
        sequence_params={"plate_id": 1234, "plate_sample_no_list": [7]},
    )
    seq.sequence_timestamp = datetime(2026, 7, 17, 13, 5, 9)
    # checksum: digit-sum of 1234 = 10, mod 10 = 0 -> serial "12340"
    assert seq.get_sequence_dir() == "26.28/0717/130509__test_seq__lab-12340-7"


def test_experiment_dir_grammar_reused_from_premodels():
    exp = Experiment(experiment_name="test_exp")
    # legacy assigns str here too (premodels.py:116); field is typed
    # Optional[Path] but get_sequence_dir()/get_experiment_dir() are str-only
    # -- pre-existing legacy pyright drift, not introduced here.
    exp.sequence_output_dir = "26.28/0717/130509__test_seq__lab"  # type: ignore[assignment]
    exp.experiment_timestamp = datetime(2026, 7, 17, 13, 6, 1)
    assert (
        exp.get_experiment_dir()
        == "26.28/0717/130509__test_seq__lab/260717.130601__test_exp"
    )
