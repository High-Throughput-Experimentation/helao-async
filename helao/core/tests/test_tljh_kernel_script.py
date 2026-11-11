"""The kernel script end to end under a user namespace, with stub sudo/chown/pixi."""

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "tools" / "tljh_pixi_kernel.sh"


def _can_unshare() -> bool:
    if sys.platform == "win32" or not shutil.which("unshare"):
        return False
    return (
        subprocess.run(["unshare", "-r", "true"], capture_output=True).returncode == 0
    )


pytestmark = pytest.mark.skipif(not _can_unshare(), reason="needs unshare -r")


def _exe(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


def test_kernel_script_writes_an_activating_kernelspec(tmp_path):
    pytest.importorskip("ipykernel")
    ws = tmp_path / "ws"
    envbin = ws / ".pixi/envs/default/bin"
    envbin.mkdir(parents=True)
    (ws / "pixi.toml").write_text("", encoding="utf-8")
    os.symlink(sys.executable, envbin / "python")
    prefix = ws / ".pixi/envs/default"
    _exe(
        tmp_path / "stub/pixi",
        f'echo "export CONDA_PREFIX={prefix}; export PATH={envbin}:\\$PATH; '
        'export PYTHONPATH=/repo"\n',
    )
    _exe(
        tmp_path / "stub/sudo",
        'while [[ "$1" == -* ]]; do [ "$1" = -u ] && shift; shift; done; exec "$@"\n',
    )
    _exe(tmp_path / "stub/chown", "exit 0\n")
    tljh = tmp_path / "tljh"
    (tljh / "share/jupyter/kernels").mkdir(parents=True)
    env = {
        **os.environ,
        "PATH": f"{tmp_path / 'stub'}:{os.environ['PATH']}",
        "SUDO_USER": os.environ.get("USER", "nobody"),
        "PIXI": str(tmp_path / "stub/pixi"),
        "TLJH_PREFIX": str(tljh),
    }
    r = subprocess.run(
        [
            "unshare",
            "-r",
            "bash",
            str(SCRIPT),
            str(ws),
            "default",
            "helao-x",
            "Helao X",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    spec = json.loads((tljh / "share/jupyter/kernels/helao-x/kernel.json").read_text())
    assert spec["display_name"] == "Helao X"
    assert spec["argv"][:2] == ["/bin/bash", "-c"]
    assert f"source '{ws}/activate-default.sh'" in spec["argv"][2]
    assert "exec python -m ipykernel_launcher" in spec["argv"][2]
    assert spec["argv"][3] == "{connection_file}"
    assert "PYTHONPATH=/repo" in (ws / "activate-default.sh").read_text()


def test_kernel_script_refuses_without_sudo(tmp_path):
    r = subprocess.run(
        ["bash", str(SCRIPT), str(tmp_path)], capture_output=True, text=True
    )
    assert r.returncode != 0 and "sudo" in r.stderr
