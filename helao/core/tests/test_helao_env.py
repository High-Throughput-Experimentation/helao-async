import json
import os
import sys
from pathlib import Path

import pytest

import helao_env as he


def _touch(root: Path, rel: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("servers: {}\n", encoding="utf-8")
    return p


@pytest.fixture
def root(tmp_path):
    _touch(tmp_path, "a/configs/solo.yml")
    _touch(tmp_path, "a/configs/dup.yml")
    _touch(tmp_path, "b/configs/dup.yml")
    _touch(tmp_path, "b/configs/pyonly.py")
    return tmp_path


def test_unique_prefix(root):
    assert he.resolve_config("solo", root) == (root / "a/configs/solo.yml").resolve()


def test_qualified_prefix_skips_prompt(root):
    assert (
        he.resolve_config("b/dup", root, interactive=False)
        == (root / "b/configs/dup.yml").resolve()
    )


def test_full_path(root):
    p = root / "a/configs/dup.yml"
    assert he.resolve_config(str(p), root) == p.resolve()


def test_py_config_when_no_yml(root):
    assert he.resolve_config("pyonly", root).name == "pyonly.py"


def test_duplicate_prompts_on_tty(root):
    answers = iter(["2"])
    got = he.resolve_config("dup", root, ask=lambda _: next(answers), interactive=True)
    assert got == (root / "b/configs/dup.yml").resolve()


def test_duplicate_reprompts_on_bad_answer(root):
    answers = iter(["9", "x", "1"])
    got = he.resolve_config("dup", root, ask=lambda _: next(answers), interactive=True)
    assert got == (root / "a/configs/dup.yml").resolve()


def test_duplicate_without_tty_exits_with_list(root):
    with pytest.raises(
        he.EnvSetupError,
        match=r"a[/\\]configs[/\\]dup\.yml[\s\S]*b[/\\]configs[/\\]dup\.yml",
    ):
        he.resolve_config("dup", root, interactive=False)


def test_unknown_prefix(root):
    with pytest.raises(he.EnvSetupError, match="nope"):
        he.resolve_config("nope", root)


def test_server_folders_of_a_real_hte_config():
    cfg = (
        he.resolve_config("hte/anec")
        if (he.DEPLOY_ROOT / "hte/configs/anec.yml").exists()
        else None
    )
    if cfg is None:
        pytest.skip("anec config not present")
    folders = {f.name for f in he.server_folders(cfg)}
    assert {"gamry", "nidaqmx", "galil_motion"} <= folders


def test_unresolvable_module_names_the_server(tmp_path, monkeypatch):
    cfg = tmp_path / "x.yml"
    cfg.write_text(
        "root: " + str(tmp_path) + "\nservers:\n  BAD:\n    host: 127.0.0.1\n"
        "    port: 9999\n    group: action\n    fast: no_such_module\n"
        "    deployment: hte\n",
        encoding="utf-8",
    )
    with pytest.raises(he.EnvSetupError, match="BAD"):
        he.server_folders(cfg)


def _env(folder: Path, text: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "environment.yml").write_text(text, encoding="utf-8")


def test_merge_unions_channels_deps_and_pip(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _env(a, "channels: [conda-forge]\ndependencies: [pyserial, {pip: [x==1]}]\n")
    _env(
        b,
        "channels: [conda-forge, other]\ndependencies: [pyserial, pyvisa=1.13, {pip: [x==2]}]\n",
    )
    env = he.merge_environment({a, b})
    assert env is not None
    assert env["channels"] == ["conda-forge", "other"]
    assert env["dependencies"][:2] == ["pyserial", "pyvisa=1.13"]
    assert env["dependencies"][-1] == {"pip": ["x==1", "x==2"]}  # both pins kept


def test_merge_none_when_no_env_files(tmp_path):
    assert he.merge_environment({tmp_path}) is None


def test_install_runs_conda_once_then_uv_per_folder(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _env(a, "dependencies: [pyserial]\n")
    b.mkdir()
    (b / "requirements.txt").write_text("nidaqmx\n", encoding="utf-8")
    cmds = []
    he.install({a, b}, runner=lambda c, e=None: cmds.append(c))
    assert [c[1:3] for c in cmds] == [["env", "update"], ["pip", "install"]]
    assert cmds[1][-1] == str(b / "requirements.txt")


def test_record_creates_states_and_merges(tmp_path, monkeypatch):
    root = tmp_path / "rel_root"
    cfg1 = tmp_path / "c1.yml"
    cfg1.write_text(f"root: {root}\nservers: {{}}\n", encoding="utf-8")
    cfg2 = tmp_path / "c2.yml"
    cfg2.write_text(f"root: {root}\nservers: {{}}\n", encoding="utf-8")
    other = tmp_path / "other_states.json"
    other.write_text("[]", encoding="utf-8")
    monkeypatch.setenv(he.ENV_VAR, str(other))
    calls = []
    he.record([cfg1], runner=calls.append)
    files = he.record([cfg2], runner=calls.append)
    data = json.loads((root / "STATES" / he.STATES_FILE).read_text(encoding="utf-8"))
    assert data == sorted([str(cfg1.resolve()), str(cfg2.resolve())])
    assert files == [root / "STATES" / he.STATES_FILE]
    mine = root / "STATES" / he.STATES_FILE
    assert calls[-1][-1] == f"{he.ENV_VAR}=" + os.pathsep.join(
        sorted([str(other), str(mine)])
    )


def test_relative_root_resolves_against_repo_root(tmp_path, monkeypatch):
    monkeypatch.setattr(he, "REPO_ROOT", tmp_path)
    monkeypatch.delenv(he.ENV_VAR, raising=False)
    cfg = tmp_path / "c.yml"
    cfg.write_text("root: rel_root\nservers: {}\n", encoding="utf-8")
    he.record([cfg], runner=lambda cmd: None)
    assert (tmp_path / "rel_root" / "STATES" / he.STATES_FILE).is_file()


def test_stored_configs_skips_missing_files_and_configs(tmp_path, capsys):
    good = tmp_path / "c.yml"
    good.write_text("servers: {}\n", encoding="utf-8")
    states = tmp_path / "s.json"
    states.write_text(
        json.dumps([str(good), str(tmp_path / "gone.yml")]), encoding="utf-8"
    )
    env = {he.ENV_VAR: os.pathsep.join([str(states), str(tmp_path / "missing.json")])}
    assert he.stored_configs(env) == [good]
    err = capsys.readouterr().err
    assert "gone.yml" in err and "missing.json" in err


def test_main_update_without_anything_is_a_hint(monkeypatch, capsys):
    monkeypatch.delenv(he.ENV_VAR, raising=False)
    assert he.main(["update"]) == 0
    assert "setup_env" in capsys.readouterr().out


def test_main_setup_without_prefixes_is_base_only(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(he, "install", lambda *a, **k: calls.append("install"))
    monkeypatch.setattr(he, "record", lambda *a, **k: calls.append("record"))
    assert he.main(["setup"]) == 0
    assert calls == []
    assert "no config prefix given" in capsys.readouterr().out


def test_main_bad_prefix_exits_2(capsys):
    assert he.main(["setup", "definitely_not_a_config"]) == 2
    assert "error:" in capsys.readouterr().err


def test_backslash_qualified_prefix(root):
    assert (
        he.resolve_config("b\\dup", root, interactive=False)
        == (root / "b/configs/dup.yml").resolve()
    )


def test_eof_at_duplicate_prompt_is_a_clean_error(root):
    def eof(_):
        raise EOFError

    with pytest.raises(he.EnvSetupError, match="dup"):
        he.resolve_config("dup", root, ask=eof, interactive=True)


def test_malformed_states_json_names_the_file(tmp_path, monkeypatch, capsys):
    states = tmp_path / "s.json"
    states.write_text("[not json", encoding="utf-8")
    monkeypatch.setenv(he.ENV_VAR, str(states))
    assert he.main(["update"]) == 2
    assert "s.json" in capsys.readouterr().err


def test_record_malformed_states_json_raises_env_error(tmp_path, monkeypatch):
    root = tmp_path / "r"
    (root / "STATES").mkdir(parents=True)
    (root / "STATES" / he.STATES_FILE).write_text("{oops", encoding="utf-8")
    cfg = tmp_path / "c.yml"
    cfg.write_text(f"root: {root}\nservers: {{}}\n", encoding="utf-8")
    monkeypatch.delenv(he.ENV_VAR, raising=False)
    with pytest.raises(he.EnvSetupError, match=he.STATES_FILE):
        he.record([cfg], runner=lambda cmd: None)


def test_main_missing_tool_exits_2(monkeypatch, capsys):
    def boom(cmd):
        raise FileNotFoundError("conda")

    monkeypatch.setattr(he, "_run", boom)
    monkeypatch.setattr(he, "install", lambda folders, **kw: boom(["x"]))
    assert he.main(["setup", "hte/anec"]) == 2
    assert "error:" in capsys.readouterr().err


def test_install_removes_tmp_dir_and_dry_run_prints_plus_form(
    tmp_path, monkeypatch, capsys
):
    a = tmp_path / "a"
    _env(a, "dependencies: [pyserial]\n")
    seen = []
    he.install({a}, runner=lambda cmd, env=None: seen.append(Path(cmd[-1]).parent))
    assert not seen[0].exists()
    he.install({a}, dry_run=True)
    assert capsys.readouterr().out.startswith("+ ")


def test_main_malformed_yaml_config_exits_2(tmp_path, capsys):
    cfg = tmp_path / "bad.yml"
    cfg.write_text("servers: [unclosed\n  x: : :\n", encoding="utf-8")
    assert he.main(["setup", str(cfg)]) == 2
    assert "error:" in capsys.readouterr().err


def test_yml_and_py_in_different_deployments_are_both_matches(tmp_path):
    _touch(tmp_path, "a/configs/mix.yml")
    _touch(tmp_path, "b/configs/mix.py")
    with pytest.raises(he.EnvSetupError, match="several deployments"):
        he.resolve_config("mix", tmp_path, interactive=False)


def test_yml_beats_py_within_one_deployment(tmp_path):
    _touch(tmp_path, "a/configs/both.yml")
    _touch(tmp_path, "a/configs/both.py")
    assert he.resolve_config("both", tmp_path).name == "both.yml"


def test_platform_file_merged_only_for_matching_platform(tmp_path, monkeypatch):
    a = tmp_path / "a"
    _env(a, "dependencies: [base]\n")
    (a / "environment_win-64.yml").write_text("dependencies: [winonly]\n", "utf-8")
    (a / "environment_linux-64.yml").write_text("dependencies: [linonly]\n", "utf-8")
    monkeypatch.setattr(he, "platform_tag", lambda: "win-64")
    assert he.merge_environment({a})["dependencies"] == ["base", "winonly"]
    monkeypatch.setattr(he, "platform_tag", lambda: "linux-64")
    assert he.merge_environment({a})["dependencies"] == ["base", "linonly"]
    monkeypatch.setattr(he, "platform_tag", lambda: "osx-64")
    assert he.merge_environment({a})["dependencies"] == ["base"]


def _pip_folder(root: Path, name: str, over: str | None) -> Path:
    f = root / name
    f.mkdir()
    (f / "requirements.txt").write_text("x\n", encoding="utf-8")
    if over is not None:
        (f / "pip_env_linux-64.yml").write_text(over, encoding="utf-8")
    return f


def test_pip_env_reaches_only_its_folder_and_expands(tmp_path, monkeypatch):
    monkeypatch.setattr(he, "platform_tag", lambda: "linux-64")
    monkeypatch.setenv("PATH", "/orig")
    monkeypatch.setenv("FC_LD", "keepme")
    monkeypatch.delenv("CC", raising=False)
    a = _pip_folder(tmp_path, "a", 'CC: gcc\nFC_LD: ""\nPATH: "{prefix}/bin;{PATH}"\n')
    b = _pip_folder(tmp_path, "b", None)
    _env(tmp_path / "c", "dependencies: [pyserial]\n")
    calls = []
    he.install({a, b, tmp_path / "c"}, runner=lambda c, e=None: calls.append((c, e)))
    by_dir = {
        Path(c[-1]).parent.name if c[1] == "pip" else "conda": e for c, e in calls
    }
    assert by_dir["conda"] is None and by_dir["b"] is None
    env = by_dir["a"]
    assert env["CC"] == "gcc"
    assert "FC_LD" not in env  # empty string unsets, even if set in os.environ
    assert env["PATH"] == f"{sys.prefix}/bin;/orig"
    assert "CC" not in os.environ and os.environ["FC_LD"] == "keepme"
    assert os.environ["PATH"] == "/orig"


def test_pip_env_without_requirements_warns_and_is_ignored(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(he, "platform_tag", lambda: "linux-64")
    (tmp_path / "pip_env_linux-64.yml").write_text("CC: gcc\n", encoding="utf-8")
    (tmp_path / "environment.yml").write_text("dependencies: [x]\n", "utf-8")
    he.install({tmp_path}, dry_run=True)
    cap = capsys.readouterr()
    assert "requirements.txt" in cap.err
    assert "CC" not in cap.out.replace("conda dependencies", "")


@pytest.mark.parametrize("body", ["- a\n- b\n", "CC: [gcc]\n", "CC: {a: b}\n"])
def test_pip_env_not_flat_mapping_is_a_clean_error(tmp_path, monkeypatch, body, capsys):
    monkeypatch.setattr(he, "platform_tag", lambda: "linux-64")
    f = _pip_folder(tmp_path, "a", body)
    with pytest.raises(he.EnvSetupError, match="flat VAR: value mapping"):
        he.pip_env_overrides(f)
    cfg = tmp_path / "c.yml"
    cfg.write_text("servers: {}\n", encoding="utf-8")
    monkeypatch.setattr(he, "server_folders", lambda c: {f})
    assert he.main(["setup", str(cfg), "--dry-run"]) == 2
    assert "flat VAR: value mapping" in capsys.readouterr().err


def test_pip_env_keys_uppercased_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(he, "platform_tag", lambda: "win-64")
    f = _pip_folder(tmp_path, "a", None)
    (f / "pip_env_win-64.yml").write_text("Path: x\n", encoding="utf-8")
    assert he.pip_env_overrides(f) == {"PATH": "x"}


def test_dry_run_shows_templates_and_conda_deps(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(he, "platform_tag", lambda: "linux-64")
    a = _pip_folder(tmp_path, "a", "CC: gcc\nPATH: '{prefix}\\Library;{PATH}'\n")
    _env(a, "dependencies: [pyserial]\n")
    he.install({a}, dry_run=True)
    out = capsys.readouterr().out
    assert "CC=gcc" in out and "PATH={prefix}\\Library;{PATH}" in out
    assert "['pyserial']" in out


def test_gpsim_folder_brings_pytorch_and_gpytorch():
    cfg = he.resolve_config("test/demo1")
    env = he.merge_environment(he.server_folders(cfg))
    assert env is not None
    assert {"pytorch-cpu", "gpytorch"} <= set(env["dependencies"])


import subprocess

_REAL_ENSURE_HTE = he.ensure_hte
_REAL_HTE_STATE = he.hte_state


@pytest.fixture(autouse=True)
def _no_network_hte(monkeypatch):
    """No test may clone or pull the real hte remote; opt in by calling _REAL_*."""

    def refuse(*a, **kw):
        raise AssertionError("ensure_hte called without a test stub")

    monkeypatch.setattr(he, "ensure_hte", refuse)
    monkeypatch.setattr(he, "hte_state", lambda *a, **k: "tracked")


def _git(*args, cwd):
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "-C",
            str(cwd),
            *args,
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture()
def remote(tmp_path, monkeypatch):
    """A bare repo standing in for helao-hte-deployment, plus a work clone to push from.

    Restores the real hte_state, which the autouse fixture stubs: the real
    ensure_hte calls it through the module global."""
    monkeypatch.setattr(he, "hte_state", _REAL_HTE_STATE)
    src = tmp_path / "src"
    src.mkdir()
    _git("init", "-b", "main", cwd=src)
    (src / "servers").mkdir()
    (src / "servers" / "__init__.py").write_text("", encoding="utf-8")
    (src / "README.md").write_text("v1\n", encoding="utf-8")
    _git("add", "-A", cwd=src)
    _git("commit", "-m", "init", cwd=src)
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "clone", "--bare", str(src), str(bare)], check=True, capture_output=True
    )
    _git("remote", "add", "origin", str(bare), cwd=src)
    return bare, src


def _push(src, name, text):
    (src / name).write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=src)
    _git("commit", "-m", name, cwd=src)
    _git("push", "origin", "main", cwd=src)


def test_hte_state_names_all_four_shapes(tmp_path, remote):
    deploy = tmp_path / "parent" / "helao" / "deploy"
    deploy.mkdir(parents=True)
    parent = tmp_path / "parent"
    _git("init", "-b", "main", cwd=parent)
    assert _REAL_HTE_STATE(deploy, parent) == "missing"
    (deploy / "hte").mkdir()
    (deploy / "hte" / "x.py").write_text("", encoding="utf-8")
    assert _REAL_HTE_STATE(deploy, parent) == "leftover"
    _git("add", "-A", cwd=parent)
    _git("commit", "-m", "track hte", cwd=parent)
    assert _REAL_HTE_STATE(deploy, parent) == "tracked"
    (deploy / "hte" / ".git").mkdir()
    assert _REAL_HTE_STATE(deploy, parent) == "repo"


def test_ensure_hte_clones_when_missing(tmp_path, remote):
    bare, _ = remote
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    assert _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare)) == "cloned"
    assert (deploy / "hte" / ".git").exists()
    assert (deploy / "hte" / "README.md").read_text(encoding="utf-8") == "v1\n"


def test_ensure_hte_pulls_an_existing_repo_and_never_deletes_it(tmp_path, remote):
    bare, src = remote
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    subprocess.run(
        ["git", "clone", str(bare), str(deploy / "hte")],
        check=True,
        capture_output=True,
    )
    marker = (
        deploy / "hte" / "station_local.txt"
    )  # untracked: survives a pull, not a re-clone
    marker.write_text("keep", encoding="utf-8")
    _push(src, "new.txt", "v2\n")
    assert _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare)) == "pulled"
    assert (deploy / "hte" / "new.txt").is_file()
    assert marker.read_text(encoding="utf-8") == "keep"


def test_ensure_hte_logs_and_replaces_a_leftover(tmp_path, remote, capsys):
    bare, _ = remote
    _git("init", "-b", "main", cwd=tmp_path)
    deploy = tmp_path / "deploy"
    left = deploy / "hte"
    (left / "servers" / "__pycache__").mkdir(parents=True)
    (left / "servers" / "__pycache__" / "a.cpython-314.pyc").write_bytes(b"\0")
    (left / "servers" / "b.pyc").write_bytes(b"\0")  # R3: a .pyc outside __pycache__
    (left / "configs").mkdir()
    (left / "configs" / "station_local.yml").write_text("x: 1\n", encoding="utf-8")
    assert _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare)) == "replaced"
    err = capsys.readouterr().err
    assert "station_local.yml" in err
    assert "a.cpython-314.pyc" not in err and "b.pyc" not in err
    assert (left / ".git").exists() and not (
        left / "configs" / "station_local.yml"
    ).exists()
    assert not list(tmp_path.glob(".hte-*.tmp"))
    (listing,) = (tmp_path / "STATES").glob("hte_leftover_*.txt")
    text = listing.read_text(encoding="utf-8")
    assert "station_local.yml" in text and ".pyc" not in text


def test_ensure_hte_dry_run_changes_nothing(tmp_path, remote, capsys):
    bare, _ = remote
    _git("init", "-b", "main", cwd=tmp_path)
    deploy = tmp_path / "deploy"
    (deploy / "hte").mkdir(parents=True)
    (deploy / "hte" / "keep.txt").write_text("k", encoding="utf-8")
    assert _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare), dry_run=True) == "replaced"
    assert (deploy / "hte" / "keep.txt").is_file() and not (
        deploy / "hte" / ".git"
    ).exists()
    out = capsys.readouterr().out
    marks = (
        "git clone",
        "mv " + str(deploy / "hte"),
        "mv " + str(tmp_path / ".hte-clone"),
        "rm -r",
    )
    order = [out.index(m) for m in marks]
    assert order == sorted(order) and "git clone" in out


def test_ensure_hte_leaves_a_tracked_folder_alone(tmp_path, remote):
    """Before the cutover the developer's hte has no .git and is tracked: never touch it."""
    bare, _ = remote
    parent = tmp_path / "parent"
    deploy = parent / "helao" / "deploy"
    (deploy / "hte").mkdir(parents=True)
    (deploy / "hte" / "x.py").write_text("tracked\n", encoding="utf-8")
    _git("init", "-b", "main", cwd=parent)
    _git("add", "-A", cwd=parent)
    _git("commit", "-m", "track", cwd=parent)
    assert _REAL_ENSURE_HTE(deploy, parent, url=str(bare)) == "tracked"
    assert (deploy / "hte" / "x.py").read_text(encoding="utf-8") == "tracked\n"
    assert not (deploy / "hte" / ".git").exists()


def test_a_local_edit_that_conflicts_makes_the_pull_refuse(tmp_path, remote):
    bare, src = remote
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    subprocess.run(
        ["git", "clone", str(bare), str(deploy / "hte")],
        check=True,
        capture_output=True,
    )
    (deploy / "hte" / "README.md").write_text("station edit\n", encoding="utf-8")
    _push(src, "README.md", "v2\n")
    with pytest.raises(subprocess.CalledProcessError):
        _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare))
    assert (deploy / "hte" / "README.md").read_text(
        encoding="utf-8"
    ) == "station edit\n"


def _leftover(tmp_path):
    deploy = tmp_path / "deploy"
    (deploy / "hte").mkdir(parents=True)
    (deploy / "hte" / "station_only.yml").write_text("x: 1\n", encoding="utf-8")
    return deploy


def test_a_non_repo_root_raises_and_deletes_nothing(tmp_path, remote):
    bare, _ = remote  # tmp_path is deliberately not a git repo
    deploy = _leftover(tmp_path)
    with pytest.raises(he.EnvSetupError):
        _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare))
    assert (deploy / "hte" / "station_only.yml").is_file()


def test_a_stray_git_dir_raises_and_deletes_nothing(tmp_path, remote, monkeypatch):
    """A GIT_DIR naming another repo makes git call a tracked folder untracked."""
    bare, _ = remote
    _git("init", "-b", "main", cwd=tmp_path)
    deploy = _leftover(tmp_path)
    _git("add", "-A", cwd=tmp_path / "deploy")
    _git("commit", "-m", "track", cwd=tmp_path)
    other = tmp_path.parent / (tmp_path.name + "_other")
    other.mkdir()
    _git("init", "-b", "main", cwd=other)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    with pytest.raises(he.EnvSetupError):
        _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare))
    assert (deploy / "hte" / "station_only.yml").is_file()


def test_a_corrupt_index_raises_and_deletes_nothing(tmp_path, remote):
    bare, _ = remote
    _git("init", "-b", "main", cwd=tmp_path)
    deploy = _leftover(tmp_path)
    (tmp_path / ".git" / "index").write_bytes(b"garbage")
    with pytest.raises(subprocess.CalledProcessError):
        _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare))
    assert (deploy / "hte" / "station_only.yml").is_file()


def test_a_deploy_root_outside_the_repo_raises(tmp_path, remote):
    bare, _ = remote
    parent = tmp_path / "parent"
    parent.mkdir()
    _git("init", "-b", "main", cwd=parent)
    deploy = _leftover(tmp_path)  # tmp_path/deploy is outside tmp_path/parent
    with pytest.raises(he.EnvSetupError):
        _REAL_ENSURE_HTE(deploy, parent, url=str(bare))
    assert (deploy / "hte" / "station_only.yml").is_file()


def test_a_failed_clone_leaves_the_leftover_and_no_scratch(tmp_path, remote):
    _git("init", "-b", "main", cwd=tmp_path)
    deploy = _leftover(tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        _REAL_ENSURE_HTE(deploy, tmp_path, url=str(tmp_path / "nope.git"))
    assert (deploy / "hte" / "station_only.yml").is_file()
    assert not list(tmp_path.glob(".hte-*.tmp"))


@pytest.mark.parametrize("rebase", ["false", "true"])
def test_a_diverged_pull_refuses_and_leaves_no_partial_merge(
    tmp_path, remote, monkeypatch, rebase
):
    bare, src = remote
    for k, v in {"NAME": "t", "EMAIL": "t@example.invalid"}.items():
        monkeypatch.setenv(f"GIT_AUTHOR_{k}", v)
        monkeypatch.setenv(f"GIT_COMMITTER_{k}", v)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "pull.rebase")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", rebase)
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    hte = deploy / "hte"
    subprocess.run(
        ["git", "clone", str(bare), str(hte)], check=True, capture_output=True
    )
    (hte / "README.md").write_text("station\n", encoding="utf-8")
    _git("commit", "-am", "station", cwd=hte)
    _push(src, "README.md", "upstream\n")
    with pytest.raises(subprocess.CalledProcessError):
        _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare))
    g = hte / ".git"
    assert not (g / "MERGE_HEAD").exists()
    assert not (g / "rebase-merge").exists() and not (g / "rebase-apply").exists()
    assert (hte / "README.md").read_text(encoding="utf-8") == "station\n"


def test_a_symlink_or_file_hte_is_refused(tmp_path):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    real = tmp_path / "real"
    real.mkdir()
    link = deploy / "hte"
    link.symlink_to(real)
    with pytest.raises(he.EnvSetupError):
        _REAL_HTE_STATE(deploy, tmp_path)
    link.unlink()
    link.symlink_to(tmp_path / "dangling")
    with pytest.raises(he.EnvSetupError):
        _REAL_HTE_STATE(deploy, tmp_path)
    link.unlink()
    link.write_text("x", encoding="utf-8")
    with pytest.raises(he.EnvSetupError):
        _REAL_HTE_STATE(deploy, tmp_path)


def _replace_ready(tmp_path):
    _git("init", "-b", "main", cwd=tmp_path)
    return _leftover(tmp_path)


def _assert_intact(tmp_path, deploy):
    assert (deploy / "hte" / "station_only.yml").read_text(encoding="utf-8") == "x: 1\n"
    assert not list(tmp_path.glob(".hte-*.tmp"))


def test_a_failed_states_write_restores_the_leftover(tmp_path, remote, monkeypatch):
    bare, _ = remote
    deploy = _replace_ready(tmp_path)
    real = Path.write_text

    def boom(self, *a, **k):
        if self.name.startswith("hte_leftover_"):
            raise PermissionError("denied")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", boom)
    with pytest.raises(PermissionError):
        _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare))
    _assert_intact(tmp_path, deploy)


@pytest.mark.parametrize("victim", ["hte", ".hte-clone.tmp"])
def test_a_failed_rename_restores_the_leftover(tmp_path, remote, monkeypatch, victim):
    bare, _ = remote
    deploy = _replace_ready(tmp_path)
    real = Path.rename

    def boom(self, target):
        if self.name == victim:
            raise PermissionError("denied")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", boom)
    with pytest.raises(PermissionError):
        _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare))
    _assert_intact(tmp_path, deploy)


def test_rmtree_force_deletes_a_read_only_tree(tmp_path):
    d = tmp_path / "t" / "pack"
    d.mkdir(parents=True)
    (d / "f").write_text("x", encoding="utf-8")
    (d / "f").chmod(0o444)
    d.chmod(0o500)
    he._rmtree_force(tmp_path / "t")
    assert not (tmp_path / "t").exists()


def test_a_stranded_leftover_aside_blocks_every_run(tmp_path, remote):
    bare, _ = remote
    deploy = _replace_ready(tmp_path)
    aside = tmp_path / ".hte-leftover.tmp"
    aside.mkdir()
    (aside / "only_copy.yml").write_text("k", encoding="utf-8")
    with pytest.raises(he.EnvSetupError, match="hte-leftover.tmp"):
        _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare))
    assert (aside / "only_copy.yml").is_file()
    assert (deploy / "hte" / "station_only.yml").is_file()


def test_a_stale_scratch_clone_is_removed_and_the_run_continues(
    tmp_path, remote, capsys
):
    bare, _ = remote
    deploy = _replace_ready(tmp_path)
    (tmp_path / ".hte-clone.tmp").mkdir()
    (tmp_path / ".hte-clone.tmp" / "junk").write_text("j", encoding="utf-8")
    assert _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare)) == "replaced"
    assert "stale scratch clone" in capsys.readouterr().err
    assert not list(tmp_path.glob(".hte-*.tmp"))
    assert (deploy / "hte" / ".git").exists()


def test_files_written_during_the_clone_are_logged(tmp_path, remote, monkeypatch):
    bare, _ = remote
    deploy = _replace_ready(tmp_path)
    real = he._run

    def clone_then_write(cmd, env=None):
        real(cmd, env)
        (deploy / "hte" / "late.yml").write_text("late", encoding="utf-8")

    _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare), runner=clone_then_write)
    (listing,) = (tmp_path / "STATES").glob("hte_leftover_*.txt")
    assert "late.yml" in listing.read_text(encoding="utf-8")


def test_rmtree_force_raises_when_it_cannot_remove(tmp_path, monkeypatch):
    d = tmp_path / "t" / "pack"
    d.mkdir(parents=True)
    (d / "f").write_text("x", encoding="utf-8")
    d.chmod(0o500)
    monkeypatch.setattr(os, "chmod", lambda *a, **k: None)  # cannot clear the bit
    try:
        with pytest.raises(he.EnvSetupError, match="by hand"):
            he._rmtree_force(tmp_path / "t")
        assert (d / "f").is_file()
    finally:
        monkeypatch.undo()
        d.chmod(0o700)
