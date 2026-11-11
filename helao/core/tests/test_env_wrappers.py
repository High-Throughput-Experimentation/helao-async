"""Bash wrappers against stub pixi/conda executables (no real env needed)."""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash wrappers")


def _exe(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.fixture
def repo(tmp_path):
    """A copy of the wrappers in a directory whose name has a space."""
    r = tmp_path / "helao async"
    r.mkdir()
    for name in ("activate_helao.sh", "helao.sh", "setup_env.sh", "update_env.sh"):
        if (REPO / name).exists():
            shutil.copy2(REPO / name, r / name)
    (r / "pixi.toml").write_text("[workspace]\n", encoding="utf-8")
    (r / "pixi.lock").write_text("version: 6\n", encoding="utf-8")
    (r / "launch.py").write_text(
        "import os, sys\n"
        "open(os.environ['OUT'], 'w').write(repr((sys.argv[1:], "
        "os.environ.get('HOOKED'), os.environ.get('CONDA_STUB'))))\n",
        encoding="utf-8",
    )
    return r


def _stub_pixi(bindir: Path, log: Path) -> Path:
    # shell-hook prints an activation that marks itself and puts a python on PATH
    py = bindir / "envpy"
    py.mkdir(parents=True, exist_ok=True)
    os.symlink(sys.executable, py / "python")
    return _exe(
        bindir / "pixi",
        f'printf \'%s\\n\' "$@" >> "{log}"\n'
        f"printf -- '---\\n' >> \"{log}\"\n"
        'case "$1" in\n'
        f'  shell-hook) echo "export HOOKED=1; export PATH=\\"{py}:$PATH\\"";;\n'
        "esac\n",
    )


def _run(cmd, env, cwd):
    return subprocess.run(
        ["bash", *cmd], env=env, cwd=cwd, capture_output=True, text=True
    )


def _env(tmp_path, path_dirs, home=None):
    return {
        "PATH": os.pathsep.join(map(str, path_dirs)) + ":/usr/bin:/bin",
        "HOME": str(home or tmp_path / "home"),
        "OUT": str(tmp_path / "out.txt"),
    }


def test_helao_sh_activates_with_pixi_and_passes_args(repo, tmp_path):
    (repo / ".helao-env").mkdir()
    (repo / ".helao-env" / "pixi.toml").write_text("", encoding="utf-8")
    log = tmp_path / "pixi.log"
    bindir = tmp_path / "bin"
    _stub_pixi(bindir, log)
    r = _run(
        [str(repo / "helao.sh"), "demo1", "--restore"], _env(tmp_path, [bindir]), repo
    )
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "out.txt").read_text() == repr(
        (["demo1", "--restore"], "1", None)
    )
    call = log.read_text().split("---\n")[0].splitlines()
    assert call == [
        "shell-hook",
        "--frozen",
        "--manifest-path",
        str(repo / ".helao-env" / "pixi.toml"),
        "--shell",
        "bash",
    ]


def test_activate_finds_pixi_in_home_bin(repo, tmp_path):
    (repo / ".helao-env").mkdir()
    (repo / ".helao-env" / "pixi.toml").write_text("", encoding="utf-8")
    home = tmp_path / "home"
    _stub_pixi(home / ".pixi" / "bin", tmp_path / "pixi.log")
    r = _run([str(repo / "helao.sh"), "x"], _env(tmp_path, [], home=home), repo)
    assert r.returncode == 0, r.stderr


def test_activate_without_pixi_names_it(repo, tmp_path):
    (repo / ".helao-env").mkdir()
    (repo / ".helao-env" / "pixi.toml").write_text("", encoding="utf-8")
    r = _run([str(repo / "helao.sh"), "x"], _env(tmp_path, []), repo)
    assert r.returncode != 0
    assert "pixi" in r.stderr and "setup_env" in r.stderr


def test_helao_sh_falls_back_to_conda_with_a_warning(repo, tmp_path):
    bindir = tmp_path / "bin"
    _exe(
        bindir / "conda",
        'case "$1" in\n'
        '  env) echo "helao   /x/miniforge3/envs/helao";;\n'
        '  shell.bash) echo "conda() { export CONDA_STUB=\\"\\$*\\"; export PATH=\\"'
        + str(Path(sys.executable).parent)
        + ':\\$PATH\\"; }";;\n'
        "esac\n",
    )
    r = _run([str(repo / "helao.sh"), "x"], _env(tmp_path, [bindir]), repo)
    assert r.returncode == 0, r.stderr
    assert "still on conda" in r.stderr
    assert (tmp_path / "out.txt").read_text() == repr((["x"], None, "activate helao"))


def test_helao_sh_without_any_env_says_run_setup_env(repo, tmp_path):
    r = _run([str(repo / "helao.sh"), "x"], _env(tmp_path, []), repo)
    assert r.returncode != 0 and "setup_env" in r.stderr


def _stub_pixi_run(bindir: Path, log: Path) -> Path:
    """pixi stub: logs its args; `run` exits with the code in <log>.rc if present."""
    return _exe(
        bindir / "pixi",
        f'echo "$@" >> "{log}"\n'
        f'if [ "$1" = run ] && [ -f "{log}.rc" ]; then exit "$(cat "{log}.rc")"; fi\n',
    )


def test_setup_env_copies_base_once_then_runs_helao_env_in_the_env(repo, tmp_path):
    log = tmp_path / "pixi.log"
    bindir = tmp_path / "bin"
    _stub_pixi_run(bindir, log)
    env = _env(tmp_path, [bindir])
    r = _run([str(repo / "setup_env.sh"), "demo1"], env, repo)
    assert r.returncode == 0, r.stderr
    ws = repo / ".helao-env"
    assert (ws / "pixi.toml").read_text() == "[workspace]\n"  # copied base
    assert (ws / "pixi.lock").read_text() == "version: 6\n"
    run = f"run --frozen --manifest-path {ws / 'pixi.toml'} python {repo / 'helao_env.py'}"
    assert log.read_text().splitlines() == [f"{run} setup demo1"]
    (ws / "pixi.toml").write_text("[workspace]\n# composed\n", encoding="utf-8")
    r = _run([str(repo / "update_env.sh")], env, repo)
    assert r.returncode == 0, r.stderr
    assert (ws / "pixi.toml").read_text().endswith("# composed\n")  # not re-copied
    assert log.read_text().splitlines()[-1] == f"{run} update"


def test_setup_env_stops_when_helao_env_fails(repo, tmp_path):
    log = tmp_path / "pixi.log"
    bindir = tmp_path / "bin"
    _stub_pixi_run(bindir, log)
    Path(f"{log}.rc").write_text("2", encoding="utf-8")
    r = _run([str(repo / "setup_env.sh"), "x"], _env(tmp_path, [bindir]), repo)
    assert r.returncode != 0 and "complete" not in r.stdout
