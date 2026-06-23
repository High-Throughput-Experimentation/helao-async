"""Unit tests for `helao.framework.domain.sync.paths` — pure path/status math.

Verified against legacy `helao/core/drivers/data/sync_driver.py`:
HelaoYml.type/timestamp/status/rename/status_idx/relative_path/
active_path/finished_path/synced_path, module funcs move_to_synced /
revert_to_finished, and HelaoSyncer._rel_under_runs / _node_keys.
"""
from datetime import datetime
from pathlib import PurePosixPath

import pytest

from helao.framework.domain.sync import paths


# Realistic legacy-style absolute paths (forward-slash). The on-disk layout is
# <runs>/<week>/<date>/<seq>/<exp>/<act>/<name>-*.yml
UUID = "abcd1234-0000-0000-0000-000000000000"
TS = "240115.120000123456"  # %y%m%d.%H%M%S%f
SEQ_DIR = f"{TS}__{UUID}__seqlabel"
EXP_DIR = f"{TS}__{UUID}__explabel"
ACT_DIR = f"{TS}__{UUID}__actlabel"

# Legacy yml filenames are just "<timestamp>-{type}.yml" (uuid lives in the
# directory name, never the file name) — see base.py write_*_meta.
SEQ_NAME = f"{TS}-seq.yml"
EXP_NAME = f"{TS}-exp.yml"
ACT_NAME = f"{TS}-act.yml"


def _seq(tree="RUNS_FINISHED"):
    return f"/INST/{tree}/2024.01/240115/{SEQ_DIR}/{SEQ_NAME}"


def _exp(tree="RUNS_FINISHED"):
    return f"/INST/{tree}/2024.01/240115/{SEQ_DIR}/{EXP_DIR}/{EXP_NAME}"


def _act(tree="RUNS_FINISHED"):
    return f"/INST/{tree}/2024.01/240115/{SEQ_DIR}/{EXP_DIR}/{ACT_DIR}/{ACT_NAME}"


# --- module constants -------------------------------------------------------

def test_runs_constant():
    assert paths.RUNS == ("RUNS_ACTIVE", "RUNS_FINISHED", "RUNS_SYNCED")


def test_abr_map():
    assert paths.ABR_MAP == {"act": "action", "exp": "experiment", "seq": "sequence"}


# --- node_type --------------------------------------------------------------

def test_node_type_seq():
    assert paths.node_type(SEQ_NAME) == "seq"


def test_node_type_exp():
    assert paths.node_type(EXP_NAME) == "exp"


def test_node_type_act():
    assert paths.node_type(ACT_NAME) == "act"


def test_node_type_accepts_full_path():
    assert paths.node_type(_act()) == "act"


def test_node_type_accepts_purepath():
    assert paths.node_type(PurePosixPath(_seq())) == "seq"


# --- node_timestamp ---------------------------------------------------------

def test_node_timestamp_two_digit_year():
    ts = paths.node_timestamp(SEQ_NAME)
    assert ts == datetime(2024, 1, 15, 12, 0, 0, 123456)


def test_node_timestamp_four_digit_year():
    name = "20240115.120000123456-seq.yml"
    ts = paths.node_timestamp(name)
    assert ts == datetime(2024, 1, 15, 12, 0, 0, 123456)


def test_node_timestamp_accepts_full_path():
    ts = paths.node_timestamp(_exp())
    assert ts == datetime(2024, 1, 15, 12, 0, 0, 123456)


# --- status_of --------------------------------------------------------------

@pytest.mark.parametrize(
    "tree,expected",
    [("RUNS_ACTIVE", "active"), ("RUNS_FINISHED", "finished"), ("RUNS_SYNCED", "synced")],
)
def test_status_of(tree, expected):
    assert paths.status_of(_seq(tree)) == expected
    assert paths.status_of(_exp(tree)) == expected
    assert paths.status_of(_act(tree)) == expected


def test_status_of_accepts_parts_sequence():
    parts = PurePosixPath(_act("RUNS_ACTIVE")).parts
    assert paths.status_of(parts) == "active"


# --- status_idx -------------------------------------------------------------

def test_status_idx_seq():
    # /INST/RUNS_FINISHED/... -> index 2 (parts[0]=='/')
    p = PurePosixPath(_seq())
    assert paths.status_idx(p) == 2
    assert p.parts[paths.status_idx(p)] == "RUNS_FINISHED"


def test_status_idx_each_tree():
    for tree in paths.RUNS:
        p = PurePosixPath(_act(tree))
        assert p.parts[paths.status_idx(p)] == tree


def test_status_idx_accepts_parts():
    parts = PurePosixPath(_seq()).parts
    assert parts[paths.status_idx(parts)] == "RUNS_FINISHED"


# --- rename_status ----------------------------------------------------------

def test_rename_status_to_synced():
    out = paths.rename_status(_seq("RUNS_FINISHED"), "synced")
    assert out == PurePosixPath(_seq("RUNS_SYNCED"))


def test_rename_status_to_active():
    out = paths.rename_status(_act("RUNS_FINISHED"), "active")
    assert out == PurePosixPath(_act("RUNS_ACTIVE"))


def test_rename_status_to_finished():
    out = paths.rename_status(_exp("RUNS_SYNCED"), "finished")
    assert out == PurePosixPath(_exp("RUNS_FINISHED"))


# --- active/finished/synced_path -------------------------------------------

def test_active_path():
    assert paths.active_path(_seq("RUNS_FINISHED")) == PurePosixPath(_seq("RUNS_ACTIVE"))


def test_finished_path():
    assert paths.finished_path(_seq("RUNS_SYNCED")) == PurePosixPath(_seq("RUNS_FINISHED"))


def test_synced_path():
    assert paths.synced_path(_seq("RUNS_FINISHED")) == PurePosixPath(_seq("RUNS_SYNCED"))


def test_path_helpers_idempotent_same_tree():
    assert paths.finished_path(_exp("RUNS_FINISHED")) == PurePosixPath(_exp("RUNS_FINISHED"))


# --- relative_under_runs ----------------------------------------------------

def test_relative_under_runs_seq():
    assert paths.relative_under_runs(_seq()) == f"2024.01/240115/{SEQ_DIR}/{SEQ_NAME}"


def test_relative_under_runs_exp():
    assert (
        paths.relative_under_runs(_exp())
        == f"2024.01/240115/{SEQ_DIR}/{EXP_DIR}/{EXP_NAME}"
    )


def test_relative_under_runs_act():
    assert (
        paths.relative_under_runs(_act())
        == f"2024.01/240115/{SEQ_DIR}/{EXP_DIR}/{ACT_DIR}/{ACT_NAME}"
    )


def test_relative_under_runs_none_when_not_under_runs():
    assert paths.relative_under_runs("/INST/LOGS/foo/bar.yml") is None


def test_relative_under_runs_stable_across_trees():
    # same logical record => same relative path regardless of tree
    rels = {paths.relative_under_runs(_act(t)) for t in paths.RUNS}
    assert len(rels) == 1


# --- compute_synced_path ----------------------------------------------------

def test_compute_synced_path_from_finished():
    assert paths.compute_synced_path(_act("RUNS_FINISHED")) == PurePosixPath(
        _act("RUNS_SYNCED")
    )


def test_compute_synced_path_already_synced_noop():
    # legacy returns the str-replaced target even when already synced
    assert paths.compute_synced_path(_seq("RUNS_SYNCED")) == PurePosixPath(
        _seq("RUNS_SYNCED")
    )


# --- compute_finished_path --------------------------------------------------

def test_compute_finished_path_from_synced():
    assert paths.compute_finished_path(_exp("RUNS_SYNCED")) == PurePosixPath(
        _exp("RUNS_FINISHED")
    )


def test_compute_finished_path_raises_without_synced():
    with pytest.raises(ValueError):
        paths.compute_finished_path(_exp("RUNS_FINISHED"))


# --- node_keys --------------------------------------------------------------

def test_node_keys_seq():
    seq_dir_rel = f"2024.01/240115/{SEQ_DIR}"
    assert paths.node_keys(_seq()) == (seq_dir_rel, None)


def test_node_keys_exp():
    seq_dir_rel = f"2024.01/240115/{SEQ_DIR}"
    exp_dir_rel = f"2024.01/240115/{SEQ_DIR}/{EXP_DIR}"
    assert paths.node_keys(_exp()) == (seq_dir_rel, exp_dir_rel)


def test_node_keys_act():
    seq_dir_rel = f"2024.01/240115/{SEQ_DIR}"
    exp_dir_rel = f"2024.01/240115/{SEQ_DIR}/{EXP_DIR}"
    assert paths.node_keys(_act()) == (seq_dir_rel, exp_dir_rel)


def test_node_keys_unknown_suffix():
    p = f"/INST/RUNS_FINISHED/2024.01/240115/{SEQ_DIR}/{TS}-other.yml"
    assert paths.node_keys(p) == (None, None)


def test_node_keys_not_under_runs():
    assert paths.node_keys("/INST/LOGS/foo-act.yml") == (None, None)


# --- prg_path ---------------------------------------------------------------

def test_prg_path_seq():
    assert paths.prg_path(_seq()) == PurePosixPath(_seq()).with_suffix(".prg")


def test_prg_path_act():
    p = paths.prg_path(_act())
    assert p.suffix == ".prg"
    assert p.stem == PurePosixPath(_act()).stem
    assert p.parent == PurePosixPath(_act()).parent
