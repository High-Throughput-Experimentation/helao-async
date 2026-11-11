"""The kernel script end to end under a user namespace, with stub sudo/chown/pixi."""

import json
import os
import shlex
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


needs_unshare = pytest.mark.skipif(not _can_unshare(), reason="needs unshare -r")


def _exe(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


def _calls(log: Path) -> list[list[str]]:
    """Argv lists a stub logged (one arg per line, '---' between calls)."""
    out, cur = [], []
    for line in log.read_text(encoding="utf-8").splitlines():
        if line == "---":
            out.append(cur)
            cur = []
        else:
            cur.append(line)
    return out


def _stubs(tmp_path: Path) -> dict:
    """Stub sudo/chown/pixi, a fake env OUTSIDE any workspace, and an empty TLJH tree."""
    detached = tmp_path / "detached"
    (detached / "bin").mkdir(parents=True)
    os.symlink(sys.executable, detached / "bin/python")
    # pixi freezes the caller's PATH into the hook, as the real one does
    _exe(
        tmp_path / "stub/pixi",
        f'printf "%s\\n" "$@" >> {tmp_path}/pixi.log; echo --- >> {tmp_path}/pixi.log\n'
        f'echo "export CONDA_PREFIX={detached}"\n'
        f'echo "export PATH=\\"{detached}/bin:$PATH\\""\n'
        'echo "export PYTHONPATH=/repo"\n',
    )
    _exe(
        tmp_path / "stub/sudo",
        f'printf "%s\\n" "$@" >> {tmp_path}/sudo.log; echo --- >> {tmp_path}/sudo.log\n'
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
    return {"env": env, "tljh": tljh}


def _run(script: Path, env: dict, *args: str):
    return subprocess.run(
        ["unshare", "-r", "bash", str(script), *args],
        env=env,
        capture_output=True,
        text=True,
    )


@needs_unshare
def test_kernel_script_writes_an_activating_kernelspec(tmp_path):
    pytest.importorskip("ipykernel")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "pixi.toml").write_text("", encoding="utf-8")
    st = _stubs(tmp_path)
    r = _run(SCRIPT, st["env"], str(ws), "default", "helao-x", "Helao X")
    assert r.returncode == 0, r.stderr

    spec = json.loads(
        (st["tljh"] / "share/jupyter/kernels/helao-x/kernel.json").read_text()
    )
    act = ws / "activate-default.sh"
    assert spec["display_name"] == "Helao X"
    assert spec["argv"][:2] == ["/bin/bash", "-c"]
    assert f"source {shlex.quote(str(act))}" in spec["argv"][2]
    assert "exec python -m ipykernel_launcher" in spec["argv"][2]
    assert spec["argv"][3] == "{connection_file}"

    # the activation: owner-written, world-readable, runtime PATH, pixi's env kept
    text = act.read_text()
    assert "PYTHONPATH=/repo" in text
    assert stat.S_IMODE(act.stat().st_mode) == 0o644
    (path_line,) = [x for x in text.splitlines() if x.startswith("export PATH=")]
    assert path_line.endswith(':$PATH"')
    assert str(tmp_path / "detached/bin") in path_line
    assert str(tmp_path / "stub") not in path_line
    assert not (ws / "activate-default.sh.tmp").exists()

    # pixi ran as the invoking user, frozen, for this env and manifest
    user = st["env"]["SUDO_USER"]
    (sudo_call,) = _calls(tmp_path / "sudo.log")
    assert sudo_call[:3] == ["-u", user, "-H"]
    assert sudo_call[3] == st["env"]["PIXI"]
    (pixi_call,) = _calls(tmp_path / "pixi.log")
    assert pixi_call[0] == "shell-hook" and "--frozen" in pixi_call
    assert (
        "--shell" in pixi_call and pixi_call[pixi_call.index("--shell") + 1] == "bash"
    )
    assert pixi_call[pixi_call.index("-e") + 1] == "default"
    assert pixi_call[pixi_call.index("--manifest-path") + 1] == f"{ws}/pixi.toml"


@needs_unshare
def test_kernel_script_default_workspace_is_next_to_tools(tmp_path):
    pytest.importorskip("ipykernel")
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    (repo / ".helao-env").mkdir()
    (repo / ".helao-env/pixi.toml").write_text("", encoding="utf-8")
    script = repo / "tools/tljh_pixi_kernel.sh"
    shutil.copy(SCRIPT, script)
    st = _stubs(tmp_path)
    r = _run(script, st["env"], "", "default", "helao-y", "Y")
    assert r.returncode == 0, r.stderr
    spec = json.loads(
        (st["tljh"] / "share/jupyter/kernels/helao-y/kernel.json").read_text()
    )
    assert shlex.quote(str(repo / ".helao-env/activate-default.sh")) in spec["argv"][2]


def test_kernel_script_refuses_without_sudo(tmp_path):
    r = subprocess.run(
        ["bash", str(SCRIPT), str(tmp_path)], capture_output=True, text=True
    )
    assert r.returncode != 0 and "sudo" in r.stderr
