"""Tests for LocalLoader in the framework adapters/loaders/localfs adapter.

Uses the existing test fixture tree at
  helao/framework/tests/fixtures/sync/RUNS_FINISHED/...
which contains one sequence / one experiment / one action yml in the standard
HELAO directory layout.  All tests perform real disk I/O via LocalLoader (no
mocks) — the fixture tree is read-only and small.

Skipped paths
-------------
- get_prc / HelaoProcess: no ``-prc.yml`` fixtures exist; the dataframe will be
  empty and ``get_prc`` would fail.  Those paths are noted but not tested here.
- Zip-archive branch: requires a real zip, which is not part of the fixture set.
- get_parquet / get_bytes(zip): same reason.
"""

import os
import inspect
import pytest

from helao.framework.adapters.loaders.localfs import (
    LocalLoader,
    HelaoModel,
    HelaoDataModel,
    HelaoAction,
    HelaoExperiment,
    HelaoSequence,
    HelaoProcess,
    parse_seq_path,
    parse_exp_path,
    parse_act_path,
    ABBR_MAP,
)
from helao.framework.adapters.loaders.model_base import HelaoDataModelMixin

# ---------------------------------------------------------------------------
# Fixture path helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = os.path.join(
    os.path.dirname(__file__),
    "fixtures",
    "sync",
    "RUNS_FINISHED",
)

SEQ_DIR = os.path.join(
    FIXTURES_DIR,
    "26.25",
    "0622",
    "240622.120000000000__demo_seq",
)

EXP_DIR = os.path.join(SEQ_DIR, "240622.120001000000__demo_exp")

ACT_DIR = os.path.join(
    EXP_DIR, "240622.120002000000__0__act__measure"
)

SEQ_YML = os.path.join(SEQ_DIR, "240622.120000000000-seq.yml")
EXP_YML = os.path.join(EXP_DIR, "240622.120001000000-exp.yml")
ACT_YML = os.path.join(ACT_DIR, "240622.120002000000-act.yml")
HLO_FILE = os.path.join(ACT_DIR, "measure.hlo")


# ---------------------------------------------------------------------------
# 1. Module-level imports / public API
# ---------------------------------------------------------------------------


def test_localloader_importable():
    """LocalLoader can be imported from the framework adapter."""
    assert LocalLoader is not None


def test_wrapper_classes_importable():
    """All wrapper model classes are importable."""
    for cls in (HelaoModel, HelaoDataModel, HelaoAction, HelaoExperiment,
                HelaoSequence, HelaoProcess):
        assert cls is not None, f"{cls} not importable"


def test_helao_data_model_inherits_mixin():
    """HelaoDataModel inherits from HelaoDataModelMixin."""
    assert issubclass(HelaoDataModel, HelaoDataModelMixin)


def test_abbr_map_keys():
    """ABBR_MAP maps the four yml suffixes to full record type names."""
    assert ABBR_MAP["act"] == "action"
    assert ABBR_MAP["exp"] == "experiment"
    assert ABBR_MAP["seq"] == "sequence"
    assert ABBR_MAP["prc"] == "process"


# ---------------------------------------------------------------------------
# 2. Parse helpers (pure functions, no disk I/O)
# ---------------------------------------------------------------------------


def test_parse_seq_path_fixture():
    """parse_seq_path returns expected fields for the fixture sequence yml."""
    ts, seq_name, seq_lab, plate_id, sample_no, yml_dir, path = parse_seq_path(
        SEQ_YML, FIXTURES_DIR
    )
    assert seq_name == "demo_seq"
    assert yml_dir == "240622.120000000000__demo_seq"
    assert path == SEQ_YML


def test_parse_exp_path_fixture():
    """parse_exp_path returns expected fields for the fixture experiment yml."""
    ts, exp_name, yml_dir, path = parse_exp_path(EXP_YML)
    assert exp_name == "demo_exp"
    assert yml_dir == "240622.120001000000__demo_exp"
    assert path == EXP_YML


def test_parse_act_path_fixture():
    """parse_act_path returns expected fields for the fixture action yml."""
    ts, act_order, act_split, server_name, act_name, yml_dir, path = parse_act_path(
        ACT_YML
    )
    assert act_name == "measure"
    assert act_order == "240622.120002000000"
    assert yml_dir == "240622.120002000000__0__act__measure"
    assert path == ACT_YML


# ---------------------------------------------------------------------------
# 3. LocalLoader construction with fixture tree
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def loader():
    """Construct a LocalLoader over the fixture RUNS_FINISHED tree."""
    return LocalLoader(FIXTURES_DIR)


def test_loader_constructs(loader):
    """LocalLoader.__init__ completes without error on the fixture tree."""
    assert loader is not None


def test_loader_target_is_absolute(loader):
    """loader.target is an absolute path."""
    assert os.path.isabs(loader.target)


def test_sequences_dataframe(loader):
    """loader.sequences has at least one row with the expected sequence_name.

    The LocalLoader scans all four RUNS_* sibling dirs; when data_path IS a
    RUNS_* root it will find the same files via more than one state replacement,
    so the count may be >1.  We test presence rather than exact count.
    """
    assert len(loader.sequences) >= 1
    assert "demo_seq" in loader.sequences.sequence_name.values


def test_experiments_dataframe(loader):
    """loader.experiments has at least one row with the expected experiment_name."""
    assert len(loader.experiments) >= 1
    assert "demo_exp" in loader.experiments.experiment_name.values


def test_actions_dataframe(loader):
    """loader.actions has at least one row with the expected action_name after merge."""
    assert len(loader.actions) >= 1
    assert "measure" in loader.actions.action_name.values


def test_processes_dataframe_empty(loader):
    """loader.processes is empty (no -prc.yml fixtures exist)."""
    assert len(loader.processes) == 0


def test_actions_merged_experiment_cols(loader):
    """After merge, action rows carry experiment_name from the joined frame."""
    row = loader.actions.iloc[0]
    assert row.experiment_name == "demo_exp"


# ---------------------------------------------------------------------------
# 4. get_seq / get_exp / get_act round-trips
# ---------------------------------------------------------------------------


def test_get_seq_by_index(loader):
    """get_seq(0) returns a HelaoSequence with correct attributes."""
    seq = loader.get_seq(0)
    assert isinstance(seq, HelaoSequence)
    assert seq.sequence_name == "demo_seq"
    assert seq.sequence_label == "demo"


def test_get_seq_by_path(loader):
    """get_seq(path=...) also returns the correct HelaoSequence."""
    seq = loader.get_seq(path=SEQ_YML)
    assert seq.sequence_name == "demo_seq"


def test_get_exp_by_index(loader):
    """get_exp(0) returns a HelaoExperiment with correct attributes."""
    exp = loader.get_exp(0)
    assert isinstance(exp, HelaoExperiment)
    assert exp.experiment_name == "demo_exp"


def test_get_exp_by_path(loader):
    """get_exp(path=...) also returns the correct HelaoExperiment."""
    exp = loader.get_exp(path=EXP_YML)
    assert exp.experiment_name == "demo_exp"


def test_get_act_by_index(loader):
    """get_act(0) returns a HelaoAction with correct attributes."""
    act = loader.get_act(0)
    assert isinstance(act, HelaoAction)
    assert act.action_name == "measure"


def test_get_act_by_path(loader):
    """get_act(path=...) also returns the correct HelaoAction."""
    act = loader.get_act(path=ACT_YML)
    assert act.action_name == "measure"


def test_get_act_raises_without_args(loader):
    """get_act with neither index nor path raises IndexError."""
    with pytest.raises(IndexError):
        loader.get_act()


def test_get_exp_raises_without_args(loader):
    """get_exp with neither index nor path raises IndexError."""
    with pytest.raises(IndexError):
        loader.get_exp()


def test_get_seq_raises_without_args(loader):
    """get_seq with neither index nor path raises IndexError."""
    with pytest.raises(IndexError):
        loader.get_seq()


# ---------------------------------------------------------------------------
# 5. get_yml round-trip
# ---------------------------------------------------------------------------


def test_get_yml_seq(loader):
    """get_yml returns a dict with sequence_name for the fixture seq yml."""
    d = loader.get_yml(SEQ_YML)
    assert isinstance(d, dict)
    assert d["sequence_name"] == "demo_seq"


def test_get_yml_exp(loader):
    """get_yml returns a dict with experiment_name for the fixture exp yml."""
    d = loader.get_yml(EXP_YML)
    assert isinstance(d, dict)
    assert d["experiment_name"] == "demo_exp"


def test_get_yml_act(loader):
    """get_yml returns a dict with action_name for the fixture act yml."""
    d = loader.get_yml(ACT_YML)
    assert isinstance(d, dict)
    assert d["action_name"] == "measure"


# ---------------------------------------------------------------------------
# 6. get_hlo round-trip
# ---------------------------------------------------------------------------


def test_get_hlo_returns_tuple(loader):
    """get_hlo returns a (meta, data) tuple for the fixture measure.hlo."""
    meta, data = loader.get_hlo(ACT_YML, "measure.hlo")
    assert isinstance(meta, dict)
    assert isinstance(data, dict)


def test_get_hlo_data_keys(loader):
    """The fixture measure.hlo body contains 't' and 'signal' columns."""
    _, data = loader.get_hlo(ACT_YML, "measure.hlo")
    assert "t" in data
    assert "signal" in data


def test_get_hlo_data_values(loader):
    """The fixture measure.hlo body values match the written fixture data."""
    _, data = loader.get_hlo(ACT_YML, "measure.hlo")
    assert data["t"] == [0.0, 0.1]
    assert data["signal"] == [1.5, 2.5]


# ---------------------------------------------------------------------------
# 7. clear_cache
# ---------------------------------------------------------------------------


def test_clear_cache(loader):
    """clear_cache empties all four yml caches."""
    # Warm the caches
    loader.get_seq(0)
    loader.get_exp(0)
    loader.get_act(0)
    loader.clear_cache()
    assert loader.act_cache == {}
    assert loader.exp_cache == {}
    assert loader.seq_cache == {}
    assert loader.prc_cache == {}


# ---------------------------------------------------------------------------
# 8. FileNotFoundError on bad path
# ---------------------------------------------------------------------------


def test_localloader_raises_on_missing_path():
    """LocalLoader raises FileNotFoundError for a non-existent data_path."""
    with pytest.raises(FileNotFoundError):
        LocalLoader("/nonexistent/path/RUNS_FINISHED")


# ---------------------------------------------------------------------------
# 9. Constructor signature / public method presence
# ---------------------------------------------------------------------------


_EXPECTED_METHODS = [
    "get_seq",
    "get_exp",
    "get_act",
    "get_prc",
    "get_hlo",
    "get_yml",
    "get_bytes",
    "get_parquet",
    "clear_cache",
]


@pytest.mark.parametrize("method_name", _EXPECTED_METHODS)
def test_localloader_has_method(method_name):
    """LocalLoader exposes the expected public methods."""
    assert hasattr(LocalLoader, method_name), (
        f"LocalLoader missing expected method: {method_name}"
    )
    assert callable(getattr(LocalLoader, method_name))


def test_localloader_init_signature():
    """LocalLoader.__init__ accepts a single data_path positional argument."""
    sig = inspect.signature(LocalLoader.__init__)
    params = sig.parameters
    assert "data_path" in params
