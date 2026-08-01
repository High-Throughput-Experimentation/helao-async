"""Unit tests for reflex_launcher's pure helpers."""

import os

import pytest

import reflex_launcher as rl


def test_backend_port_is_one_above_the_frontend_port():
    assert rl.backend_port(5010) == 5011


def test_resolve_bundle_returns_none_when_absent(tmp_path):
    assert rl.resolve_bundle(str(tmp_path)) is None


def test_resolve_bundle_finds_an_exported_bundle(tmp_path):
    bundle = tmp_path / ".reflex-bundle" / "helao_ui"
    bundle.mkdir(parents=True)
    (bundle / "index.html").write_text("<html></html>")
    assert rl.resolve_bundle(str(tmp_path)) == str(bundle)


def test_resolve_bundle_rejects_a_directory_without_index_html(tmp_path):
    (tmp_path / ".reflex-bundle" / "helao_ui").mkdir(parents=True)
    assert rl.resolve_bundle(str(tmp_path)) is None


def test_build_env_sets_the_ports_and_server_key():
    env = rl.build_env("golden.yml", "UI", "127.0.0.1", 5010, "/tmp/root")
    assert env["HELAO_REFLEX_FRONTEND_PORT"] == "5010"
    assert env["HELAO_REFLEX_BACKEND_PORT"] == "5011"
    assert env["HELAO_REFLEX_API_URL"] == "http://127.0.0.1:5011"
    assert env["HELAO_REFLEX_SERVER_KEY"] == "UI"


def test_build_env_preserves_the_parent_environment():
    os.environ["HELAO_TEST_SENTINEL"] = "keepme"
    try:
        env = rl.build_env("golden.yml", "UI", "127.0.0.1", 5010, "/tmp/root")
        assert env["HELAO_TEST_SENTINEL"] == "keepme"
    finally:
        del os.environ["HELAO_TEST_SENTINEL"]


def test_local_build_is_refused_without_the_opt_in(monkeypatch):
    monkeypatch.delenv("REFLEX_ALLOW_LOCAL_BUILD", raising=False)
    assert rl.may_build_locally() is False


def test_local_build_requires_a_js_runtime(monkeypatch):
    monkeypatch.setenv("REFLEX_ALLOW_LOCAL_BUILD", "1")
    monkeypatch.setattr(rl.shutil, "which", lambda name: None)
    assert rl.may_build_locally() is False


def test_local_build_allowed_with_opt_in_and_runtime(monkeypatch):
    monkeypatch.setenv("REFLEX_ALLOW_LOCAL_BUILD", "1")
    monkeypatch.setattr(rl.shutil, "which", lambda name: "/usr/bin/bun")
    assert rl.may_build_locally() is True


def test_assets_dir_sits_inside_the_reflex_project():
    """The ESM client must be inside the project so `reflex export` bundles it."""
    assert rl.ASSETS_DIR.startswith(rl.APP_DIR)
    assert rl.ASSETS_DIR.endswith("assets")


def test_launch_py_has_a_reflex_branch():
    import inspect

    import launch

    src = inspect.getsource(launch.launch_server_groups)
    assert 'codeKey == "reflex"' in src
    assert "reflex_launcher.py" in src
