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


def test_unresolvable_module_names_the_server(tmp_path, monkeypatch):
    cfg = tmp_path / "x.yml"
    cfg.write_text(
        "root: " + str(tmp_path) + "\nservers:\n  BAD:\n    host: 127.0.0.1\n"
        "    port: 9999\n    group: action\n    fast: no_such_module\n"
        "    deployment: test\n",
        encoding="utf-8",
    )
    with pytest.raises(he.EnvSetupError, match="BAD"):
        he.server_folders(cfg)


def _env(folder: Path, text: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "environment.yml").write_text(text, encoding="utf-8")


def test_record_creates_states_and_returns_every_states_file(tmp_path, monkeypatch):
    root = tmp_path / "rel_root"
    cfg1 = tmp_path / "c1.yml"
    cfg1.write_text(f"root: {root}\nservers: {{}}\n", encoding="utf-8")
    cfg2 = tmp_path / "c2.yml"
    cfg2.write_text(f"root: {root}\nservers: {{}}\n", encoding="utf-8")
    other = tmp_path / "other_states.json"
    other.write_text("[]", encoding="utf-8")
    monkeypatch.setenv(he.ENV_VAR, str(other))
    he.record([cfg1])
    files = he.record([cfg2])
    mine = root / "STATES" / he.STATES_FILE
    data = json.loads(mine.read_text(encoding="utf-8"))
    assert data == sorted([str(cfg1.resolve()), str(cfg2.resolve())])
    assert files == sorted([other, mine])


def test_relative_root_resolves_against_repo_root(tmp_path, monkeypatch):
    monkeypatch.setattr(he, "REPO_ROOT", tmp_path)
    monkeypatch.delenv(he.ENV_VAR, raising=False)
    cfg = tmp_path / "c.yml"
    cfg.write_text("root: rel_root\nservers: {}\n", encoding="utf-8")
    he.record([cfg])
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


def test_main_update_without_records_tells_a_migrating_host_to_pass_prefixes(
    monkeypatch, capsys
):
    monkeypatch.delenv(he.ENV_VAR, raising=False)
    seen = []
    monkeypatch.setattr(he, "install", lambda folders, **k: seen.append((folders, k)))
    assert he.main(["update"]) == 0
    out = capsys.readouterr().out
    assert "setup_env <config prefix>" in out and "conda" in out
    assert seen == [(set(), {"states_files": [], "dry_run": False})]


def test_main_setup_without_prefixes_installs_base_only(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        he, "install", lambda folders, **k: calls.append(("install", folders))
    )
    monkeypatch.setattr(he, "record", lambda *a, **k: calls.append(("record",)))
    assert he.main(["setup"]) == 0
    assert calls == [("install", set())]
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
        he.record([cfg])


def test_main_missing_tool_exits_2(monkeypatch, capsys):
    def boom(cmd):
        raise FileNotFoundError("conda")

    monkeypatch.setattr(he, "_run", boom)
    monkeypatch.setattr(he, "install", lambda folders, **kw: boom(["x"]))
    assert he.main(["setup", "test/goldenreflex"]) == 2
    assert "error:" in capsys.readouterr().err


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


def _pip_folder(root: Path, name: str, over: str | None) -> Path:
    f = root / name
    f.mkdir()
    (f / "requirements.txt").write_text("x\n", encoding="utf-8")
    if over is not None:
        (f / "pip_env_linux-64.yml").write_text(over, encoding="utf-8")
    return f


def test_pip_env_without_requirements_warns_and_is_ignored(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(he, "platform_tag", lambda: "linux-64")
    (tmp_path / "pip_env_linux-64.yml").write_text("CC: gcc\n", encoding="utf-8")
    assert he.pip_env_overrides(tmp_path) == {}
    assert "requirements.txt" in capsys.readouterr().err


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


def test_gpsim_folder_brings_pytorch_cpu_and_gpytorch():
    import tomllib

    import pixi_compose as pc

    cfg = he.resolve_config("test/demo1")
    base = tomllib.loads(he.BASE_MANIFEST.read_text(encoding="utf-8"))
    deps = pc.compose(base, he.server_folders(cfg), "linux-64", he.REPO_ROOT)[
        "dependencies"
    ]
    assert {"pytorch-cpu", "gpytorch"} <= set(deps)


def _ws_base(tmp_path, monkeypatch):
    base = tmp_path / "pixi.toml"
    base.write_text(
        '[workspace]\nname = "helao"\nchannels = ["conda-forge"]\n'
        'platforms = ["linux-64", "win-64"]\n[dependencies]\npython = "3.14.*"\n',
        encoding="utf-8",
    )
    lock = tmp_path / "pixi.lock"
    lock.write_text("version: 6\nenvironments: {}\npackages: []\n", encoding="utf-8")
    monkeypatch.setattr(he, "BASE_MANIFEST", base)
    monkeypatch.setattr(he, "BASE_LOCK", lock)
    monkeypatch.setattr(he, "platform_tag", lambda: "linux-64")
    monkeypatch.setenv("PIXI", "/opt/fake/pixi")
    return tmp_path / "ws"


def test_install_writes_manifest_seeds_lock_and_runs_pixi(tmp_path, monkeypatch):
    import tomllib

    ws = _ws_base(tmp_path, monkeypatch)
    f = tmp_path / "srv"
    _env(f, "dependencies: [pyserial]\n")
    cmds = []
    he.install(
        {f}, states_files=[tmp_path / "s.json"], runner=cmds.append, workspace=ws
    )
    m = tomllib.loads((ws / "pixi.toml").read_text(encoding="utf-8"))
    assert m["dependencies"]["pyserial"] == "*"
    assert m["activation"]["env"]["HELAO_STATION_PREFIXES"] == str(tmp_path / "s.json")
    assert (ws / "pixi.lock").is_file() and (ws / ".seed").is_file()
    assert cmds == [
        ["/opt/fake/pixi", "install", "--manifest-path", str(ws / "pixi.toml")]
    ]


def test_install_dry_run_prints_and_writes_nothing(tmp_path, monkeypatch, capsys):
    ws = _ws_base(tmp_path, monkeypatch)
    he.install(set(), dry_run=True, runner=lambda c: pytest.fail("ran"), workspace=ws)
    out = capsys.readouterr().out
    assert "[dependencies]" in out and "pixi install --manifest-path" in out
    assert not ws.exists()


def test_install_reports_compose_conflicts_as_env_errors(tmp_path, monkeypatch):
    ws = _ws_base(tmp_path, monkeypatch)
    a, b = tmp_path / "a", tmp_path / "b"
    _env(a, "dependencies: [pyvisa=1.13]\n")
    _env(b, "dependencies: [pyvisa=1.14]\n")
    with pytest.raises(he.EnvSetupError, match="pyvisa"):
        he.install({a, b}, runner=lambda c: None, workspace=ws)


def test_install_warns_on_base_drift(tmp_path, monkeypatch, capsys):
    ws = _ws_base(tmp_path, monkeypatch)
    import pixi_compose as pc

    seen = []
    monkeypatch.setattr(
        pc, "drift", lambda *a: seen.append(a) or [("numpy", "2.2.6", "2.5.4")]
    )
    he.install(set(), runner=lambda c: None, workspace=ws)
    assert seen == [(he.BASE_LOCK, ws / "pixi.lock", "linux-64")]
    assert "base package numpy 2.2.6 -> 2.5.4" in capsys.readouterr().err


def test_pixi_lookup_prefers_env_var_then_path(monkeypatch, tmp_path):
    monkeypatch.setenv("PIXI", "/x/pixi")
    assert he._pixi() == "/x/pixi"
    monkeypatch.delenv("PIXI")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(he.Path, "home", lambda: tmp_path / "nohome")
    with pytest.raises(he.EnvSetupError, match="pixi not found"):
        he._pixi()


def _fake_pixi(d):
    d.mkdir(parents=True, exist_ok=True)
    exe = d / "pixi"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    return exe


@pytest.mark.skipif(sys.platform == "win32", reason="posix exec bit")
def test_pixi_lookup_finds_path_then_home(monkeypatch, tmp_path):
    monkeypatch.delenv("PIXI", raising=False)
    exe = _fake_pixi(tmp_path / "bin")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    assert he._pixi() == str(exe)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    home = tmp_path / "home"
    exe2 = _fake_pixi(home / ".pixi" / "bin")
    monkeypatch.setattr(he.Path, "home", lambda: home)
    assert he._pixi() == str(exe2)


def _station_cfg(tmp_path, monkeypatch):
    root = tmp_path / "root"
    cfg = tmp_path / "c.yml"
    cfg.write_text(f"root: {root}\nservers: {{}}\n", encoding="utf-8")
    monkeypatch.setattr(he, "resolve_config", lambda x, *a, **k: cfg)
    monkeypatch.setattr(he, "config_hte_use", lambda c: "none")
    monkeypatch.delenv(he.ENV_VAR, raising=False)
    return cfg, root / "STATES" / he.STATES_FILE


def test_failed_install_records_nothing_and_success_records(tmp_path, monkeypatch):
    ws = _ws_base(tmp_path, monkeypatch)
    monkeypatch.setattr(he, "WORKSPACE", ws)
    cfg, states = _station_cfg(tmp_path, monkeypatch)

    def fail(cmd):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(he, "_run", fail)
    assert he.main(["setup", "x"]) == 2
    assert not states.exists()
    monkeypatch.setattr(he, "_run", lambda cmd: None)
    assert he.main(["setup", "x"]) == 0
    assert json.loads(states.read_text(encoding="utf-8")) == [str(cfg.resolve())]


def test_dry_run_with_prefix_shows_states_path_and_writes_nothing(
    tmp_path, monkeypatch, capsys
):
    ws = _ws_base(tmp_path, monkeypatch)
    monkeypatch.setattr(he, "WORKSPACE", ws)
    _, states = _station_cfg(tmp_path, monkeypatch)
    assert he.main(["setup", "x", "--dry-run"]) == 0
    assert str(states) in capsys.readouterr().out
    assert not states.exists() and not ws.exists()


def test_failed_install_restores_the_previous_workspace(tmp_path, monkeypatch):
    ws = _ws_base(tmp_path, monkeypatch)
    ws.mkdir()
    for n in ("pixi.toml", "pixi.lock", ".seed"):
        (ws / n).write_text(f"A-{n}", encoding="utf-8")
    he.BASE_LOCK.write_text("version: 6\n# changed parent\n", encoding="utf-8")

    def fail(cmd):
        raise subprocess.CalledProcessError(1, cmd)

    with pytest.raises(subprocess.CalledProcessError):
        he.install(set(), runner=fail, workspace=ws)
    for n in ("pixi.toml", "pixi.lock", ".seed"):
        assert (ws / n).read_text(encoding="utf-8") == f"A-{n}"


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


_REAL_RUN = he._run
_REAL_WRITE_STATES = he._write_states


@pytest.fixture(autouse=True)
def _no_real_side_effects(tmp_path, monkeypatch):
    """No test may run a real command or write a states file outside tmp_path."""

    def refuse(cmd, *a, **k):
        raise AssertionError(f"real command in test: {cmd}")

    def guarded(states, cfg):
        if tmp_path not in Path(states).resolve().parents:
            raise AssertionError(f"states write outside tmp_path: {states}")
        _REAL_WRITE_STATES(states, cfg)

    monkeypatch.setattr(he, "WORKSPACE", tmp_path / "ws")
    monkeypatch.setattr(he, "_run", refuse)
    monkeypatch.setattr(he, "_write_states", guarded)


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
    cap = capsys.readouterr()
    err = cap.err
    assert "station_local.yml" in err
    assert "a.cpython-314.pyc" not in err and "b.pyc" not in err
    assert (left / ".git").exists() and not (
        left / "configs" / "station_local.yml"
    ).exists()
    (listing,) = (tmp_path / "STATES").glob("hte_leftover_*.txt")
    archive = listing.with_suffix("")  # same stamp, no .txt
    assert (archive / "configs" / "station_local.yml").read_text(
        encoding="utf-8"
    ) == "x: 1\n"
    assert str(archive) in cap.out
    assert not list(tmp_path.glob(".hte-*.tmp"))
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
    )
    order = [out.index(m) for m in marks]
    assert order == sorted(order) and "git clone" in out
    assert "STATES" in out and not (tmp_path / "STATES").exists()


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


def _clone_repo(tmp_path, bare):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    subprocess.run(
        ["git", "clone", str(bare), str(deploy / "hte")],
        check=True,
        capture_output=True,
    )
    return deploy


def test_a_repo_clone_gets_its_deleted_tracked_files_back(tmp_path, remote, capsys):
    bare, _ = remote
    deploy = _clone_repo(tmp_path, bare)
    hte = deploy / "hte"
    (hte / "README.md").unlink()
    (hte / "servers" / "__init__.py").unlink()
    assert _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare)) == "pulled"
    assert (hte / "README.md").read_text(encoding="utf-8") == "v1\n"
    assert (hte / "servers" / "__init__.py").is_file()
    assert "restoring 2 deleted" in capsys.readouterr().out


def test_restore_leaves_modified_and_untracked_files_alone(tmp_path, remote):
    bare, _ = remote
    deploy = _clone_repo(tmp_path, bare)
    hte = deploy / "hte"
    (hte / "servers" / "__init__.py").unlink()
    (hte / "README.md").write_text("edited\n", encoding="utf-8")
    (hte / "mine.txt").write_text("keep", encoding="utf-8")
    _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare))
    assert (hte / "servers" / "__init__.py").is_file()
    assert (hte / "README.md").read_text(encoding="utf-8") == "edited\n"
    assert (hte / "mine.txt").read_text(encoding="utf-8") == "keep"


def test_dry_run_reports_the_restore_and_changes_nothing(tmp_path, remote, capsys):
    bare, _ = remote
    deploy = _clone_repo(tmp_path, bare)
    (deploy / "hte" / "README.md").unlink()
    _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare), dry_run=True)
    assert "would restore 1 deleted" in capsys.readouterr().out
    assert not (deploy / "hte" / "README.md").exists()


def test_a_dangling_scratch_symlink_is_removed(tmp_path, remote):
    bare, _ = remote
    deploy = _replace_ready(tmp_path)
    (tmp_path / ".hte-clone.tmp").symlink_to(tmp_path / "nowhere")
    assert _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare)) == "replaced"
    assert not list(tmp_path.glob(".hte-*.tmp"))
    assert (deploy / "hte" / ".git").exists()


def test_a_cross_device_archive_fails_closed(tmp_path, remote, monkeypatch):
    bare, _ = remote
    deploy = _replace_ready(tmp_path)
    real = Path.rename

    def boom(self, target):
        if self.name == "hte" and "STATES" in str(target):
            raise OSError("EXDEV")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", boom)
    with pytest.raises(OSError):
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
    real = _REAL_RUN

    def clone_then_write(cmd):
        real(cmd)
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


def test_rmtree_force_leaves_the_parent_mode_alone(tmp_path):
    parent = tmp_path / "p"
    parent.mkdir()
    parent.chmod(0o775)
    top = parent / "t"
    top.mkdir()
    (top / "f").write_text("x", encoding="utf-8")
    top.chmod(0o000)
    he._rmtree_force(top)
    assert not top.exists() and (parent.stat().st_mode & 0o777) == 0o775


def test_rmtree_force_handles_an_unreadable_subdir(tmp_path):
    top = tmp_path / "t"
    (top / "sub").mkdir(parents=True)
    (top / "sub" / "f").write_text("x", encoding="utf-8")
    (top / "sub").chmod(0o000)
    he._rmtree_force(top)  # never TypeError; here the chmod lets it succeed
    assert not top.exists()


def test_rmtree_force_unlinks_a_symlinked_top_and_keeps_the_target(tmp_path):
    tmp_path.chmod(0o775)
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("k", encoding="utf-8")
    link = tmp_path / ".hte-clone.tmp"
    link.symlink_to(target)
    he._rmtree_force(link)
    assert not link.is_symlink() and not link.exists()
    assert (target / "keep.txt").is_file()
    assert (tmp_path.stat().st_mode & 0o777) == 0o775


def _tree(tmp_path):
    for rel in (
        "own/servers/a/own_server.py",
        "hte/servers/g/g_server.py",
        "hte/servers/g/reflex/g_vis.py",
        "base/servers/orchestrator/async_orch2.py",
    ):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("", encoding="utf-8")
    (tmp_path / "own" / "configs").mkdir()
    return tmp_path


def _cfg(root, body):
    p = root / "own" / "configs" / "c.yml"
    p.write_text("root: x\nservers:\n" + body, encoding="utf-8")
    return p


def test_config_hte_use_reads_fast_modules(tmp_path):
    root = _tree(tmp_path)
    assert (
        he.config_hte_use(
            _cfg(root, "  O:\n    group: orchestrator\n    fast: async_orch2\n"), root
        )
        == "none"
    )
    assert (
        he.config_hte_use(
            _cfg(root, "  G:\n    group: action\n    fast: g_server\n"), root
        )
        == "hte"
    )
    assert (
        he.config_hte_use(
            _cfg(root, "  N:\n    group: action\n    fast: nowhere_server\n"), root
        )
        == "unresolved"
    )


def test_config_hte_use_counts_panels(tmp_path):
    root = _tree(tmp_path)
    body = "  O:\n    group: orchestrator\n    fast: async_orch2\n  UI:\n    group: visualizer\n    reflex: ui\n    action_vis: g_vis\n"
    assert he.config_hte_use(_cfg(root, body), root) == "hte"


def test_wants_hte_truth_table():
    w = he.wants_hte
    assert not w("tracked", no_prefix=True, unresolved=True, uses_hte=True)
    assert not w("unknown", no_prefix=True, unresolved=True, uses_hte=True)
    for kw in (
        dict(no_prefix=False, unresolved=False, uses_hte=False),
        dict(no_prefix=True, unresolved=False, uses_hte=False),
        dict(no_prefix=False, unresolved=False, uses_hte=True),
    ):
        assert w("repo", **kw)  # a clone is always pulled
    for s in ("missing", "leftover"):
        assert w(s, no_prefix=True, unresolved=False, uses_hte=False)
        assert w(s, no_prefix=False, unresolved=True, uses_hte=False)
        assert not w(s, no_prefix=False, unresolved=False, uses_hte=False)


def _stub_install(monkeypatch):
    monkeypatch.setattr(he, "server_folders", lambda c: set())
    monkeypatch.setattr(he, "install", lambda folders, **k: [])
    monkeypatch.setattr(he, "record", lambda configs, **k: [])


def test_main_clones_hte_when_a_prefix_only_resolves_after_the_clone(
    monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(he, "hte_state", lambda *a, **k: "missing")
    monkeypatch.setattr(he, "ensure_hte", lambda **k: calls.append(k) or "cloned")
    cfg = tmp_path / "c.yml"
    cfg.write_text("root: x\nservers: {}\n", encoding="utf-8")
    answers = iter([he.ConfigNotFound("no config named 'eche10'"), cfg])

    def fake_resolve(arg, *a, **k):
        r = next(answers)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(he, "resolve_config", fake_resolve)
    monkeypatch.setattr(he, "config_hte_use", lambda c: "hte")
    _stub_install(monkeypatch)
    assert he.main(["setup", "eche10"]) == 0
    assert calls == [{"dry_run": False}]


def test_main_never_touches_a_tracked_hte(monkeypatch):
    monkeypatch.setattr(he, "hte_state", lambda *a, **k: "tracked")
    _stub_install(monkeypatch)
    assert he.main(["setup"]) == 0  # the autouse stub raises if ensure_hte is reached


def test_update_replay_clones_hte_then_reinstalls_the_replayed_configs(
    monkeypatch, tmp_path
):
    calls = []
    cfg = tmp_path / "eche10.yml"  # recorded, but absent until the clone brings it back
    states = tmp_path / "setup_env_prefixes.json"
    states.write_text(json.dumps([str(cfg)]), encoding="utf-8")
    monkeypatch.setenv(he.ENV_VAR, str(states))
    monkeypatch.setattr(he, "hte_state", lambda *a, **k: "leftover")

    def fake_ensure(**k):
        calls.append(k)
        cfg.write_text("root: x\nservers: {}\n", encoding="utf-8")
        return "replaced"

    monkeypatch.setattr(he, "ensure_hte", fake_ensure)
    monkeypatch.setattr(he, "_recorded_paths_exist", lambda: False)
    monkeypatch.setattr(he, "config_hte_use", lambda c: "hte")
    seen, installed = [], []
    folder = tmp_path / "servers" / "g"
    monkeypatch.setattr(he, "server_folders", lambda c: seen.append(c) or {folder})
    monkeypatch.setattr(he, "install", lambda folders, **k: installed.append(folders))
    monkeypatch.setattr(he, "record", lambda configs, **k: [])
    assert he.main(["update"]) == 0
    assert calls == [{"dry_run": False}]
    assert seen == [cfg]
    assert installed == [{folder}]


def test_recorded_paths_exist(monkeypatch, tmp_path):
    deploy = tmp_path / "deploy"
    (deploy / "hte" / "configs").mkdir(parents=True)
    there = deploy / "hte" / "configs" / "a.yml"
    there.write_text("", encoding="utf-8")
    other = deploy / "own" / "configs" / "x.yml"  # outside hte: never counts
    monkeypatch.setattr(he, "DEPLOY_ROOT", deploy)
    states = tmp_path / "s.json"

    def env(paths):
        states.write_text(json.dumps([str(p) for p in paths]), encoding="utf-8")
        return {he.ENV_VAR: str(states)}

    assert he._recorded_paths_exist(env([there])) is True
    assert (
        he._recorded_paths_exist(env([there, deploy / "hte" / "configs" / "b.yml"]))
        is False
    )
    assert he._recorded_paths_exist(env([other])) is True
    assert he._recorded_paths_exist({}) is True  # no records: nothing is missing


def _cfg_file(tmp_path, name="c.yml"):
    cfg = tmp_path / name
    cfg.write_text("root: x\nservers: {}\n", encoding="utf-8")
    return cfg


def _spy(monkeypatch, state, use="none", ensure=None):
    """Stub the hte seams; returns (ensure calls, installed folder sets)."""
    calls, installed = [], []

    def fake_ensure(**k):
        calls.append(k)
        if ensure:
            raise ensure
        return "pulled"

    monkeypatch.setattr(
        he, "hte_state", state if callable(state) else lambda *a, **k: state
    )
    monkeypatch.setattr(he, "ensure_hte", fake_ensure)
    monkeypatch.setattr(he, "config_hte_use", lambda c: use)
    monkeypatch.setattr(he, "server_folders", lambda c: {Path("f")})
    monkeypatch.setattr(he, "install", lambda folders, **k: installed.append(folders))
    monkeypatch.setattr(he, "record", lambda configs, **k: [])
    return calls, installed


def _resolve_to(monkeypatch, cfg):
    monkeypatch.setattr(he, "resolve_config", lambda arg, *a, **k: cfg)


def test_repo_with_a_non_hte_config_is_still_pulled(monkeypatch, tmp_path):
    calls, installed = _spy(monkeypatch, "repo", use="none")
    _resolve_to(monkeypatch, _cfg_file(tmp_path))
    assert he.main(["setup", "x"]) == 0
    assert calls == [{"dry_run": False}] and installed == [{Path("f")}]


def test_repo_pull_failure_is_tolerated_when_hte_is_not_needed(
    monkeypatch, tmp_path, capsys
):
    err = he.subprocess.CalledProcessError(1, ["git"])
    calls, installed = _spy(monkeypatch, "repo", use="none", ensure=err)
    _resolve_to(monkeypatch, _cfg_file(tmp_path))
    assert he.main(["setup", "x"]) == 0
    assert installed == [{Path("f")}]
    assert "hte not updated" in capsys.readouterr().err


def test_repo_pull_failure_aborts_when_a_config_needs_hte(monkeypatch, tmp_path):
    err = he.subprocess.CalledProcessError(1, ["git"])
    calls, installed = _spy(monkeypatch, "repo", use="hte", ensure=err)
    _resolve_to(monkeypatch, _cfg_file(tmp_path))
    assert he.main(["setup", "x"]) == 2
    assert installed == []


def test_no_arg_update_clones_a_missing_hte_for_non_hte_records(monkeypatch, tmp_path):
    cfg = _cfg_file(tmp_path)
    states = tmp_path / "s.json"
    states.write_text(json.dumps([str(cfg)]), encoding="utf-8")
    monkeypatch.setenv(he.ENV_VAR, str(states))
    calls, installed = _spy(monkeypatch, "missing", use="none")
    assert he.main(["update"]) == 0
    assert calls == [{"dry_run": False}] and installed == [{Path("f")}]


def test_unknown_hte_state_degrades_with_a_warning(monkeypatch, tmp_path, capsys):
    def boom(*a, **k):
        raise FileNotFoundError("git")

    calls, installed = _spy(monkeypatch, boom, use="none")
    _resolve_to(monkeypatch, _cfg_file(tmp_path))
    assert he.main(["setup", "x"]) == 0
    assert calls == [] and installed == [{Path("f")}]
    assert "hte state unknown" in capsys.readouterr().err


def test_unknown_hte_state_aborts_when_hte_is_needed(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise FileNotFoundError("git")

    calls, installed = _spy(monkeypatch, boom, use="unresolved")
    _resolve_to(monkeypatch, _cfg_file(tmp_path))
    assert he.main(["setup", "x"]) == 2
    assert calls == [] and installed == []


def test_dry_run_reaches_ensure_hte_and_stops_before_resolving(monkeypatch, capsys):
    calls, installed = _spy(monkeypatch, "missing")

    def nf(arg, *a, **k):
        raise he.ConfigNotFound("no config named 'x'")

    monkeypatch.setattr(he, "resolve_config", nf)
    assert he.main(["setup", "--dry-run", "x"]) == 0
    assert calls == [{"dry_run": True}] and installed == []
    out = capsys.readouterr().out
    assert "hte: would be pulled" in out and "base env only" not in out


def test_unrelated_resolve_errors_do_not_clone(monkeypatch):
    calls, _ = _spy(monkeypatch, "missing")

    def amb(arg, *a, **k):
        raise he.EnvSetupError("exists in several deployments")

    monkeypatch.setattr(he, "resolve_config", amb)
    assert he.main(["setup", "x"]) == 2
    assert calls == []


def test_resolve_config_raises_config_not_found(tmp_path):
    (tmp_path / "a" / "configs").mkdir(parents=True)
    with pytest.raises(he.ConfigNotFound):
        he.resolve_config("nope", tmp_path)


def test_failed_clone_without_a_prefix_warns_and_installs(
    monkeypatch, tmp_path, capsys
):
    cfg = _cfg_file(tmp_path)
    states = tmp_path / "s.json"
    states.write_text(json.dumps([str(cfg)]), encoding="utf-8")
    monkeypatch.setenv(he.ENV_VAR, str(states))
    err = he.subprocess.CalledProcessError(1, ["git"])
    calls, installed = _spy(monkeypatch, "missing", use="none", ensure=err)
    assert he.main(["update"]) == 0
    assert len(calls) == 1 and installed == [{Path("f")}]
    assert "hte not updated" in capsys.readouterr().err


def test_failed_clone_aborts_when_a_recorded_config_uses_hte(monkeypatch, tmp_path):
    cfg = _cfg_file(tmp_path)
    states = tmp_path / "s.json"
    states.write_text(json.dumps([str(cfg)]), encoding="utf-8")
    monkeypatch.setenv(he.ENV_VAR, str(states))
    err = he.subprocess.CalledProcessError(1, ["git"])
    calls, installed = _spy(monkeypatch, "missing", use="hte", ensure=err)
    assert he.main(["update"]) == 2
    assert installed == []


def test_update_dry_run_with_a_vanished_hte_config_stops_early(monkeypatch, capsys):
    calls, installed = _spy(monkeypatch, "missing", use="none")
    monkeypatch.setattr(he, "_recorded_paths_exist", lambda: False)
    monkeypatch.setattr(he, "stored_configs", lambda: [])
    assert he.main(["update", "--dry-run"]) == 0
    assert calls == [{"dry_run": True}] and installed == []
    out = capsys.readouterr().out
    assert "hte: would be pulled" in out and "base env only" not in out
