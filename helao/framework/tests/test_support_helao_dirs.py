"""Unit tests for the framework helao_dirs directory-tree helper."""
import os
import zipfile

import pytest

from helao.framework.support.helao_dirs import helao_dirs


def test_builds_tree_under_root(tmp_path):
    root = str(tmp_path / "INST")
    dirs = helao_dirs({"root": root})
    assert str(dirs.root) == root
    # Framework logs go to LOGS_FW (parallel to legacy LOGS) until the migration
    # completes and LOGS_FW is renamed to LOGS.
    for sub in ("RUNS_ACTIVE", "LOGS_FW", "STATES", "DATABASE", "ANALYSES", "PROCESSES"):
        assert os.path.isdir(os.path.join(root, sub))
    assert os.path.isdir(os.path.join(root, "USER_CONFIG", "EXP"))
    assert os.path.isdir(os.path.join(root, "USER_CONFIG", "SEQ"))
    assert str(dirs.save_root) == os.path.join(root, "RUNS_ACTIVE")
    assert str(dirs.log_root) == os.path.join(root, "LOGS_FW")


def test_no_root_returns_all_none():
    dirs = helao_dirs({})
    assert dirs.root is None
    assert dirs.save_root is None
    assert dirs.log_root is None


def test_rotates_old_txt_logs(tmp_path):
    root = str(tmp_path / "INST")
    server = "TESTSRV"
    log_dir = os.path.join(root, "LOGS_FW", server)
    os.makedirs(log_dir)
    log_path = os.path.join(log_dir, "TESTSRV.txt")
    with open(log_path, "w") as f:
        f.write("[12:34:56] startup line\n")

    helao_dirs({"root": root}, server_name=server)

    assert not os.path.exists(log_path)  # original removed
    zips = [n for n in os.listdir(log_dir) if n.endswith(".zip")]
    assert len(zips) == 1
    with zipfile.ZipFile(os.path.join(log_dir, zips[0])) as zf:
        assert any(name.endswith("123456.txt") for name in zf.namelist())
