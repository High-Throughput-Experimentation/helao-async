"""reorg_deploy: git mv per a mapping, then rewrite every import to the new path."""

import json
import subprocess
import sys
from pathlib import Path

from harness import reorg_deploy as rd


def _w(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    _w(r, "helao/__init__.py", "")
    _w(r, "helao/deploy/__init__.py", "")
    _w(r, "helao/deploy/d/__init__.py", "")
    _w(r, "helao/deploy/d/servers/__init__.py", "")
    _w(r, "helao/deploy/d/servers/action/__init__.py", "")
    _w(r, "helao/deploy/d/drivers/__init__.py", "")
    _w(r, "helao/deploy/d/drivers/pump/__init__.py", "")
    _w(r, "helao/deploy/d/drivers/pump/enum.py", "SPEED = 3\n")
    _w(
        r,
        "helao/deploy/d/drivers/pump/driver.py",
        "from .enum import SPEED\nfrom helao.deploy.d.drivers.pump import enum as E\n",
    )
    _w(
        r,
        "helao/deploy/d/servers/action/pump_server.py",
        "from ...drivers.pump.driver import SPEED\n"
        "from ...drivers.pump import enum\n"
        "def f():\n    import helao.deploy.d.drivers.pump.driver as drv\n    return drv\n",
    )
    _w(
        r,
        "helao/other/user.py",
        "from helao.deploy.d.drivers.pump.enum import SPEED\n"
        "MOD = 'helao.deploy.d.drivers.pump.driver'\n",
    )
    _w(
        r,
        "helao/other/multi.py",
        "from helao.deploy.d.drivers.pump.enum import (\n"
        "    SPEED,\n"
        ")\n"
        "from helao.deploy.d.drivers import pump\n",
    )
    _w(r, "helao/other/__init__.py", "")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(r),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-qm",
            "init",
        ],
        check=True,
    )
    _w(
        r,
        "map.json",
        json.dumps(
            {
                "scan": ["helao"],
                "moves": [
                    ["helao/deploy/d/drivers/pump", "helao/deploy/d/servers/pump"],
                    [
                        "helao/deploy/d/servers/action/pump_server.py",
                        "helao/deploy/d/servers/pump/pump_server.py",
                    ],
                ],
            }
        ),
    )
    return r


def test_moves_rewrites_and_imports(tmp_path):
    r = _repo(tmp_path)
    report = rd.apply(r / "map.json", r, dry_run=False)
    srv = (r / "helao/deploy/d/servers/pump/pump_server.py").read_text(encoding="utf-8")
    assert "from helao.deploy.d.servers.pump.driver import SPEED" in srv
    assert "from helao.deploy.d.servers.pump import enum" in srv
    assert "import helao.deploy.d.servers.pump.driver as drv" in srv
    drv = (r / "helao/deploy/d/servers/pump/driver.py").read_text(encoding="utf-8")
    assert "from .enum import SPEED" in drv  # moved together: relative kept
    assert "from helao.deploy.d.servers.pump import enum as E" in drv
    user = (r / "helao/other/user.py").read_text(encoding="utf-8")
    assert "from helao.deploy.d.servers.pump.enum import SPEED" in user
    assert not (r / "helao/deploy/d/drivers/pump").exists()
    # the string literal is reported, not rewritten
    assert any("helao/other/user.py" in line for line in report.leftovers)
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "import helao.deploy.d.servers.pump.pump_server as m; print(m.SPEED)",
        ],
        cwd=r,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(r)},
    )
    assert out.stdout.strip() == "3", out.stderr


def test_multiline_import_only_module_line_changes(tmp_path):
    r = _repo(tmp_path)
    rd.apply(r / "map.json", r, dry_run=False)
    text = (r / "helao/other/multi.py").read_text(encoding="utf-8")
    assert text.startswith(
        "from helao.deploy.d.servers.pump.enum import (\n    SPEED,\n)\n"
    )


def test_moved_submodule_of_unmoved_package_is_reported(tmp_path):
    r = _repo(tmp_path)
    report = rd.apply(r / "map.json", r, dry_run=False)
    # `from helao.deploy.d.drivers import pump` cannot be fixed by a module rewrite
    assert any("MANUAL helao/other/multi.py:4" in line for line in report.leftovers)


def test_dir_with_foreign_file_is_not_removed(tmp_path):
    r = _repo(tmp_path)
    _w(r, "helao/deploy/d/servers/action/notes.txt", "keep me\n")
    rd.apply(r / "map.json", r, dry_run=False)
    assert (r / "helao/deploy/d/servers/action/notes.txt").exists()


def test_dry_run_changes_nothing(tmp_path):
    r = _repo(tmp_path)
    rd.apply(r / "map.json", r, dry_run=True)
    assert (r / "helao/deploy/d/drivers/pump/driver.py").exists()


def test_nested_git_repo_is_not_scanned(tmp_path):
    r = _repo(tmp_path)
    _w(
        r,
        "helao/deploy/nested/x.py",
        "from helao.deploy.d.drivers.pump.enum import SPEED\n",
    )
    (r / "helao/deploy/nested/.git").mkdir()
    rd.apply(r / "map.json", r, dry_run=False)
    text = (r / "helao/deploy/nested/x.py").read_text(encoding="utf-8")
    assert "drivers.pump.enum" in text
