"""``get_hlo_version`` resolves the repo from the module, not the cwd."""

import subprocess
from pathlib import Path

from helao.core import version as version_mod

REPO = Path(version_mod.__file__).resolve().parents[2]


def test_version_ignores_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # not a git checkout
    want = subprocess.check_output(
        ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], text=True
    ).strip()
    assert version_mod.get_hlo_version() == want


def test_version_falls_back_when_no_hash(monkeypatch):
    monkeypatch.setattr(version_mod, "get_branch_commithash", lambda p: ("", ""))
    monkeypatch.setattr(version_mod, "gethostname", lambda: "box")
    assert version_mod.get_hlo_version().startswith("box_")
