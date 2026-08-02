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


def test_resolve_bundle_rejects_a_zero_byte_index_html(tmp_path):
    """An interrupted export leaves a truncated index.html.

    Serving it yields a blank browser page and a silent log; treating it as
    absent routes into the loud failure path instead.
    """
    bundle = tmp_path / ".reflex-bundle" / "helao_ui"
    bundle.mkdir(parents=True)
    (bundle / "index.html").write_text("")
    assert rl.resolve_bundle(str(tmp_path)) is None


def test_cleanup_budget_fits_inside_the_orchestrator_kill_window():
    """launch.py SIGKILLs this launcher after Pidd.GRACEFUL_WAIT seconds.

    Overrunning that window means dying mid-cleanup and orphaning a backend
    that still holds `port + 1`, so the next launch of the config cannot bind.
    """
    import inspect
    import re

    import launch

    # Read the literal from the class initializer rather than constructing a
    # Pidd (which touches the filesystem).
    src = inspect.getsource(launch.Pidd.__init__)
    match = re.search(r"self\.GRACEFUL_WAIT\s*=\s*([0-9.]+)", src)
    assert match, "could not read GRACEFUL_WAIT from launch.Pidd"
    graceful_wait = float(match.group(1))

    budget = rl.BACKEND_TERM_WAIT + rl.BACKEND_KILL_WAIT + rl.FRONTEND_SHUTDOWN_TIMEOUT
    assert budget < graceful_wait, (
        f"cleanup budget {budget}s exceeds the orchestrator's {graceful_wait}s "
        "kill window; the backend would be orphaned"
    )


def test_launcher_exits_nonzero_when_no_bundle_and_no_opt_in(tmp_path):
    """The composed fail-loud contract, not just its ingredients.

    A silent multi-minute network build on an instrument PC is a worse outcome
    than a clear error, so this drives the real __main__ path end to end.

    The brief's version of this test invokes a `goldenreflex` config that
    Task 9 creates; that config does not exist yet, so a minimal synthetic
    config carrying a `reflex:` server entry is written here instead (an
    absolute path to a `.yml` file is loaded directly by config_loader,
    bypassing the `helao/deploy/*/configs/` prefix search).
    """
    import os
    import subprocess
    import sys

    root_dir = tmp_path / "root"
    config_path = tmp_path / "reflex_e2e.yml"
    config_path.write_text(
        "run_type: test\n"
        f"root: {root_dir}\n"
        "servers:\n"
        "  UI:\n"
        "    host: 127.0.0.1\n"
        "    port: 15010\n"
        "    group: operator\n"
        "    reflex: app\n"
    )

    env = dict(os.environ)
    env.pop("REFLEX_ALLOW_LOCAL_BUILD", None)
    env["PATH"] = str(tmp_path)  # hide any node/bun so a build is impossible
    proc = subprocess.run(
        [sys.executable, "reflex_launcher.py", str(config_path), "UI"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        cwd=os.path.dirname(os.path.abspath(rl.__file__)),
    )
    assert proc.returncode != 0, "launcher started without a frontend bundle"
    combined = proc.stdout + proc.stderr
    assert "reflex export" in combined or "bundle" in combined.lower(), (
        "failure did not name the bundle path or the build command:\n" + combined
    )


def test_wait_for_backend_reports_a_backend_that_died():
    """A dead backend must be named, not ignored.

    The launcher used to Popen the backend and go straight to serving the
    frontend. When the backend aborted at startup the only symptom was a
    "websocket error" popup in the browser, with nothing in any log.
    """
    import subprocess
    import sys

    dead = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
    problem = rl.wait_for_backend(dead, "127.0.0.1", 5099, timeout=5.0)
    assert "exited immediately with code 3" in problem


def test_wait_for_backend_reports_a_backend_that_never_binds():
    import subprocess
    import sys

    idle = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        problem = rl.wait_for_backend(idle, "127.0.0.1", 5098, timeout=1.0)
        assert "did not begin listening" in problem
    finally:
        idle.terminate()
        idle.wait(timeout=5)


def test_wait_for_backend_returns_empty_once_the_port_is_open():
    import socket
    import subprocess
    import sys

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        alive = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            assert rl.wait_for_backend(alive, "127.0.0.1", port, timeout=5.0) == ""
        finally:
            alive.terminate()
            alive.wait(timeout=5)


def test_port_holder_names_the_process_squatting_on_a_port():
    """A stale launcher from an earlier run is the usual cause of a dead UI.

    Without the preflight, the backend starts, uvicorn fails to bind the
    frontend deep in its own startup, the finally tears the backend down, and
    the browser sits on "connecting" with the real cause buried in a traceback.
    """
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        message = rl.port_holder("127.0.0.1", port)
        assert "already in use" in message
        assert str(port) in message
    finally:
        sock.close()


def test_port_holder_is_silent_on_a_free_port():
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    assert rl.port_holder("127.0.0.1", port) == ""


def test_rxconfig_does_not_set_frontend_port():
    """Reflex aborts `run --backend-only` if frontend_port is configured.

    We never let reflex serve the frontend -- the launcher serves the exported
    bundle itself -- so setting it only breaks the backend.
    """
    import ast
    import pathlib as _p

    tree = ast.parse(_p.Path(rl.APP_DIR, "rxconfig.py").read_text())
    kwargs = [
        kw.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
    ]
    # Parsed, not substring-matched: the file's own comment explains why the
    # kwarg is absent and therefore contains the word.
    assert "backend_port" in kwargs, "rxconfig no longer configures the backend"
    assert "frontend_port" not in kwargs


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
