"""Tests for the long-path probe.

The probe's dangerous failure mode is a false PASS: a station owner who is told
the ceiling is gone, and finds out three weeks later that a run died mid-
sequence. So the simulated-ceiling test matters more than the happy path, and
both assert on cleanup -- a probe that leaves a 300-character directory behind
on a machine that cannot delete it has made things worse.

Everything here runs on Linux. The registry half cannot be exercised off
Windows; what is pinned there is only that it degrades to "unreadable" rather
than raising.
"""

import os

import pytest

from helao.core.tests import check_long_paths as clp


def _probe_dir(root) -> str:
    return os.path.join(str(root), "STATES", clp._PROBE_DIRNAME)


def test_probe_passes_and_cleans_up_on_a_normal_filesystem(tmp_path):
    result = clp.probe_root(str(tmp_path), target=300)
    assert result.ok, result.error
    assert result.reached > 300
    assert result.error is None
    assert result.cleaned and not result.leftover
    assert not os.path.exists(_probe_dir(tmp_path))


def test_probe_reports_the_measured_ceiling_when_one_exists(tmp_path, monkeypatch):
    """A 260-character cap must read as FAIL, with the ceiling it measured."""
    real_mkdir = os.mkdir

    def capped_mkdir(path, *args, **kwargs):
        if len(str(path)) > 260:
            raise OSError(2, "No such file or directory", str(path))
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(clp.os, "mkdir", capped_mkdir)

    result = clp.probe_root(str(tmp_path), target=300)
    assert not result.ok
    assert result.error is not None
    # It stopped where the cap is, not at zero -- that distinction is what
    # separates "long paths are off" from "the root is unwritable".
    assert 0 < result.reached <= 260
    assert result.cleaned and not result.leftover
    assert not os.path.exists(_probe_dir(tmp_path))


def test_probe_reports_an_unusable_root_rather_than_passing(tmp_path):
    """A root that is a file, not a directory, is a failure -- never a PASS."""
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    result = clp.probe_root(str(blocker), target=300)
    assert not result.ok
    assert result.reached == 0
    assert result.error is not None


def test_main_exit_status_follows_the_probe(tmp_path, capsys):
    assert clp.main([str(tmp_path)]) == 0
    assert "RESULT: PASS" in capsys.readouterr().out

    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    assert clp.main([str(blocker)]) == 1
    assert "RESULT: FAIL" in capsys.readouterr().out


def test_main_rejects_a_bad_target(tmp_path, capsys):
    assert clp.main([str(tmp_path), "--target", "banana"]) == 1
    assert "--target needs an integer" in capsys.readouterr().out


def test_main_requires_exactly_one_root(capsys):
    assert clp.main([]) == 1
    assert clp.main(["/a", "/b"]) == 1


@pytest.mark.skipif(os.name == "nt", reason="off-Windows degradation only")
def test_registry_helpers_degrade_off_windows():
    assert clp.registry_long_paths_enabled() is None
    ok, message = clp.enable_long_paths()
    assert not ok and "not Windows" in message
