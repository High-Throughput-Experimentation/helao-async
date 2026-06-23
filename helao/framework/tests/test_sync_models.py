# helao/framework/tests/test_sync_models.py
from pathlib import Path
from datetime import datetime
from helao.framework.domain.sync.sync_models import (
    HelaoYml, Progress, SyncJob,
    ABR_MAP, PLURALS,
)

# ─── HelaoYml ────────────────────────────────────────────────────────────────

def test_helao_yml_type_action():
    p = Path("/runs/RUNS_FINISHED/seq1/exp1/act1/20240101T120000_uuid-act.yml")
    assert HelaoYml(p).type == "action"


def test_helao_yml_type_experiment():
    p = Path("/runs/RUNS_FINISHED/seq1/exp1/20240101T120001_uuid-exp.yml")
    assert HelaoYml(p).type == "experiment"


def test_helao_yml_type_sequence():
    p = Path("/runs/RUNS_FINISHED/seq1/20240101T120002_uuid-seq.yml")
    assert HelaoYml(p).type == "sequence"


def test_helao_yml_status_finished():
    p = Path("/runs/RUNS_FINISHED/seq1/20240101T120002_uuid-seq.yml")
    assert HelaoYml(p).status == "finished"


def test_helao_yml_status_synced():
    p = Path("/runs/RUNS_SYNCED/seq1/20240101T120002_uuid-seq.yml")
    assert HelaoYml(p).status == "synced"


def test_helao_yml_status_active():
    p = Path("/runs/RUNS_ACTIVE/seq1/20240101T120002_uuid-seq.yml")
    assert HelaoYml(p).status == "active"


def test_helao_yml_active_path_swaps_runs_dir():
    p = Path("/runs/RUNS_FINISHED/seq1/exp1/20240101T120001_uuid-exp.yml")
    active = HelaoYml(p).active_path
    assert "RUNS_ACTIVE" in str(active)
    assert "RUNS_FINISHED" not in str(active)


def test_helao_yml_finished_path_is_unchanged():
    p = Path("/runs/RUNS_FINISHED/seq1/20240101T120002_uuid-seq.yml")
    assert HelaoYml(p).finished_path == p


def test_helao_yml_synced_path_swaps_runs_dir():
    p = Path("/runs/RUNS_FINISHED/seq1/20240101T120002_uuid-seq.yml")
    assert "RUNS_SYNCED" in str(HelaoYml(p).synced_path)


def test_helao_yml_prg_path_has_prg_suffix_under_synced():
    p = Path("/runs/RUNS_FINISHED/seq1/20240101T120002_uuid-seq.yml")
    prg = HelaoYml(p).prg_path
    assert prg.suffix == ".prg"
    assert "RUNS_SYNCED" in str(prg)


def test_helao_yml_relative_path_strips_runs_prefix():
    p = Path("/runs/RUNS_FINISHED/seq1/exp1/20240101T120001_uuid-exp.yml")
    rel = HelaoYml(p).relative_path
    assert "RUNS_FINISHED" not in rel
    assert "seq1" in rel
    assert "exp1" in rel


def test_helao_yml_timestamp_parsed():
    p = Path("/runs/RUNS_FINISHED/s/20240115T083045_uuid-seq.yml")
    ts = HelaoYml(p).timestamp
    assert ts == datetime(2024, 1, 15, 8, 30, 45)


def test_helao_yml_timestamp_missing_returns_min():
    p = Path("/runs/RUNS_FINISHED/s/no_timestamp-seq.yml")
    assert HelaoYml(p).timestamp == datetime.min


# ─── Progress ────────────────────────────────────────────────────────────────

def test_progress_defaults():
    p = Progress.from_dict({})
    assert p.s3_done is False
    assert p.api_done is False
    assert p.proc_states == {}


def test_progress_reads_s3_api_flags():
    p = Progress.from_dict({"s3": True, "api": True, "yml": "/path"})
    assert p.s3_done is True
    assert p.api_done is True


def test_progress_extra_keys_go_to_proc_states():
    p = Progress.from_dict({"s3": False, "api": False, "yml": "/p", "proc_0": "done"})
    assert p.proc_states["proc_0"] == "done"


def test_progress_to_dict_round_trip():
    data = {"s3": True, "api": False, "yml": "/p.yml", "proc_1": "pending"}
    p = Progress.from_dict(data)
    out = p.to_dict("/p.yml")
    assert out["s3"] is True
    assert out["api"] is False
    assert out["yml"] == "/p.yml"
    assert out["proc_1"] == "pending"


# ─── SyncJob ─────────────────────────────────────────────────────────────────

def test_sync_job_priority_ordering():
    def make(stem, pri):
        return SyncJob(
            yml=HelaoYml(Path(f"/runs/RUNS_FINISHED/s/e/{stem}.yml")),
            progress=Progress.from_dict({}),
            priority=pri,
        )

    act = make("20240101T120000_u-act", 0)
    exp = make("20240101T120001_u-exp", 1)
    seq = make("20240101T120002_u-seq", 2)
    assert act < exp < seq


def test_constants_present():
    assert ABR_MAP["act"] == "action"
    assert PLURALS["sequence"] == "sequences"


# ─── Edge cases ──────────────────────────────────────────────────────────────

def test_helao_yml_status_unknown_when_no_runs_prefix():
    """When path has no RUNS_* directory, status returns 'unknown'."""
    p = Path("/some/other/path/seq1/20240101T120002_uuid-seq.yml")
    assert HelaoYml(p).status == "unknown"


def test_helao_yml_relative_path_returns_full_path_when_no_runs_prefix():
    """When path has no RUNS_* directory, relative_path returns full path."""
    p = Path("/some/other/path/seq1/20240101T120002_uuid-seq.yml")
    rel = HelaoYml(p).relative_path
    assert rel == str(p)


def test_helao_yml_active_path_unchanged_when_no_runs_prefix():
    """When path has no RUNS_* directory, active_path returns the same path."""
    p = Path("/some/other/path/seq1/20240101T120002_uuid-seq.yml")
    assert HelaoYml(p).active_path == p


def test_helao_yml_finished_path_unchanged_when_no_runs_prefix():
    """When path has no RUNS_* directory, finished_path returns the same path."""
    p = Path("/some/other/path/seq1/20240101T120002_uuid-seq.yml")
    assert HelaoYml(p).finished_path == p


def test_helao_yml_synced_path_unchanged_when_no_runs_prefix():
    """When path has no RUNS_* directory, synced_path returns the same path."""
    p = Path("/some/other/path/seq1/20240101T120002_uuid-seq.yml")
    assert HelaoYml(p).synced_path == p
