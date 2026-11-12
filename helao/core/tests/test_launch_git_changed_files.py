"""The hot-reload watcher must see the OLD path of a moved module.

``git diff --name-only`` collapses a rename into the new path alone, so a server
that loaded ``a.py`` was never restarted after ``a.py`` moved into a subfolder.

Run:  python -m pytest helao/core/tests/test_launch_git_changed_files.py
"""

import os
import subprocess

import launch


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def test_pure_rename_reports_the_old_path(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.py").write_text("x = 1\n" * 20, encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "one")
    old = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
    ).strip()
    (tmp_path / "b").mkdir()
    _git(tmp_path, "mv", "a.py", "b/a.py")
    _git(tmp_path, "commit", "-qm", "move")
    new = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
    ).strip()
    got = launch.git_changed_files(str(tmp_path), old, new)
    assert os.path.abspath(tmp_path / "a.py") in got
    assert os.path.abspath(tmp_path / "b" / "a.py") in got
