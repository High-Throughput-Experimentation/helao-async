import json
import os
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
    he.install({a, b}, runner=cmds.append)
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
    he.install({a}, runner=lambda cmd: seen.append(Path(cmd[-1]).parent))
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
