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
    _w(r, "helao/deploy/d/common.py", "X = 1\n")
    _w(
        r,
        "helao/deploy/d/rel_user.py",
        "from .drivers.pump import enum\nfrom .drivers.pump.enum import SPEED\n",
    )
    _w(r, "helao/deploy/d/drivers/pump/sib.py", "from . import enum\n")
    _w(
        r,
        "helao/deploy/d/drivers/pump/rel.py",
        "from ... import common\nfrom ...common import X\n",
    )
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


def _map(r: Path, moves) -> Path:
    _w(r, "map2.json", json.dumps({"scan": ["helao"], "moves": moves}))
    return r / "map2.json"


def test_file_by_file_sibling_relative_import_kept(tmp_path):
    r = _repo(tmp_path)
    pump = "helao/deploy/d/drivers/pump/"
    new = "helao/deploy/d/servers/pump/"
    m = _map(
        r, [[pump + "sib.py", new + "sib.py"], [pump + "enum.py", new + "enum.py"]]
    )
    report = rd.apply(m, r, dry_run=False)
    assert (r / new / "sib.py").read_text(encoding="utf-8") == "from . import enum\n"
    assert not any("sib.py" in line for line in report.leftovers)


def test_relative_import_in_moved_package_to_unmoved_target(tmp_path):
    r = _repo(tmp_path)
    m = _map(
        r,
        [["helao/deploy/d/drivers/pump", "helao/deploy/d/servers/deep/pump"]],
    )
    rd.apply(m, r, dry_run=False)
    text = (r / "helao/deploy/d/servers/deep/pump/rel.py").read_text(encoding="utf-8")
    assert (
        text
        == "from helao.deploy.d import common\nfrom helao.deploy.d.common import X\n"
    )


def test_unmoved_file_relative_import_of_moved_module(tmp_path):
    r = _repo(tmp_path)
    rd.apply(r / "map.json", r, dry_run=False)
    text = (r / "helao/deploy/d/rel_user.py").read_text(encoding="utf-8")
    assert text == (
        "from helao.deploy.d.servers.pump import enum\n"
        "from helao.deploy.d.servers.pump.enum import SPEED\n"
    )


def _dup_dst_map(r: Path) -> Path:
    return _map(
        r,
        [
            ["helao/deploy/d/drivers/pump/enum.py", "helao/other/x.py"],
            ["helao/deploy/d/drivers/pump/driver.py", "helao/other/x.py"],
        ],
    )


def test_duplicate_destination_aborts_before_any_move(tmp_path):
    import pytest

    r = _repo(tmp_path)
    with pytest.raises(ValueError, match="destination listed twice"):
        rd.apply(_dup_dst_map(r), r, dry_run=False)
    assert (r / "helao/deploy/d/drivers/pump/enum.py").exists()
    assert not (r / "helao/other/x.py").exists()


def test_dry_run_reports_preflight_error(tmp_path):
    import pytest

    r = _repo(tmp_path)
    with pytest.raises(ValueError, match="destination listed twice"):
        rd.apply(_dup_dst_map(r), r, dry_run=True)


def test_existing_destination_and_untracked_source_rejected(tmp_path):
    import pytest

    r = _repo(tmp_path)
    _w(r, "helao/other/new.py", "")  # untracked
    m = _map(
        r,
        [
            ["helao/other/new.py", "helao/other/z.py"],
            ["helao/deploy/d/common.py", "helao/other/user.py"],
        ],
    )
    with pytest.raises(ValueError) as e:
        rd.apply(m, r, dry_run=False)
    assert "source not tracked" in str(e.value) and "destination exists" in str(e.value)
    assert (r / "helao/deploy/d/common.py").exists()


def test_rewrite_only_rewrites_inside_nested_repo_and_moves_nothing(tmp_path):
    r = tmp_path / "repo"
    _w(
        r,
        "helao/deploy/nested/x.py",
        "from helao.deploy.d.drivers.pump.enum import SPEED\n"
        "from helao.deploy.d.drivers import pump\n"
        "OTHER = 'helao.deploy.d.drivers.pump.enum'\n",
    )
    (r / "helao/deploy/nested/.git").mkdir()
    _w(
        r,
        "m.json",
        json.dumps(
            {
                "moves": [
                    [
                        "helao/deploy/d/drivers/pump/enum.py",
                        "helao/deploy/d/servers/pump/enum.py",
                    ],
                    ["helao/deploy/d/drivers/pump", "helao/deploy/d/servers/pump"],
                ]
            }
        ),
    )
    rep = rd.rewrite_only([r / "m.json"], "helao/deploy/nested", r)
    text = (r / "helao/deploy/nested/x.py").read_text(encoding="utf-8")
    assert "from helao.deploy.d.servers.pump.enum import SPEED" in text
    assert "from helao.deploy.d.servers.pump import" not in text  # pkg-level: MANUAL
    assert any(line.startswith("MANUAL") for line in rep.leftovers)
    assert any("drivers.pump.enum'" in line for line in rep.leftovers)
    assert rep.moved == []
