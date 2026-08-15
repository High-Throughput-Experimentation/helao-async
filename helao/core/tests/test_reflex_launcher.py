"""Unit tests for reflex_launcher's pure helpers."""

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time

import pytest

import reflex_launcher as rl


def _believable_stamp():
    """A stamp that passes ``validate_stamp``, for the resolution tests.

    Its content is irrelevant here -- what matters is that a stamp compared
    against an identical recorded one reports no mismatch, so these tests
    exercise the *presence* guards rather than the staleness rule (which
    ``test_reflex_bundle.py`` covers field by field).
    """
    import reflex_bundle as rb

    return {
        "schema": rb.STAMP_SCHEMA,
        "api_url": "http://127.0.0.1:5011",
        "config_prefix": "golden",
        "server_key": "UI",
        "git_revs": {".": "a" * 40},
        "dirty_digests": {".": ""},
        "extra_files": {"rxconfig.py": "b" * 40},
        "tool_versions": {"reflex": "0.9.7"},
        "modules": {
            rb.APP_MODULE_REL: "c" * 40,
            **{f"helao/ui/reflex/m{i}.py": "d" * 40 for i in range(20)},
        },
    }


def test_backend_port_is_one_above_the_frontend_port():
    assert rl.backend_port(5010) == 5011


def test_resolve_bundle_returns_none_when_absent(tmp_path):
    choice = rl.resolve_bundle(str(tmp_path), None, "golden", "UI", {})
    assert choice.path == "" and choice.source is None


def test_resolve_bundle_finds_an_exported_bundle(tmp_path):
    import reflex_bundle as rb

    bundle = tmp_path / ".reflex-bundle" / "golden_UI" / "helao_ui"
    bundle.mkdir(parents=True)
    (bundle / "index.html").write_text("<html></html>")
    rb.write_stamp(
        rb.stamp_path(str(tmp_path), None, "golden", "UI"), _believable_stamp()
    )
    choice = rl.resolve_bundle(str(tmp_path), None, "golden", "UI", _believable_stamp())
    assert choice.path == str(bundle) and choice.source == "config"


def test_resolve_bundle_rejects_a_directory_without_index_html(tmp_path):
    (tmp_path / ".reflex-bundle" / "golden_UI" / "helao_ui").mkdir(parents=True)
    choice = rl.resolve_bundle(str(tmp_path), None, "golden", "UI", {})
    assert choice.path == ""


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


def test_a_warm_node_modules_lets_a_launch_rebuild_by_itself(monkeypatch):
    """The point of the whole change: 4-5 seconds, so it just happens."""
    import reflex_bundle as rb

    monkeypatch.delenv("REFLEX_ALLOW_LOCAL_BUILD", raising=False)
    monkeypatch.setattr(rl.shutil, "which", lambda name: "/usr/bin/bun")
    monkeypatch.setattr(rb, "node_modules_present", lambda root: True)
    assert rl.may_build_at_launch("/repo") is True


def test_a_cold_build_is_refused_at_launch_without_the_opt_in(monkeypatch):
    """~270 MB of npm packages must never be fetched unasked on a station.

    An operator waiting on an instrument UI gets a clear error and the exact
    command instead.
    """
    import reflex_bundle as rb

    monkeypatch.delenv("REFLEX_ALLOW_LOCAL_BUILD", raising=False)
    monkeypatch.setattr(rl.shutil, "which", lambda name: "/usr/bin/bun")
    monkeypatch.setattr(rb, "node_modules_present", lambda root: False)
    assert rl.may_build_at_launch("/repo") is False


def test_a_cold_build_is_allowed_at_launch_with_the_opt_in(monkeypatch):
    import reflex_bundle as rb

    monkeypatch.setenv("REFLEX_ALLOW_LOCAL_BUILD", "1")
    monkeypatch.setattr(rl.shutil, "which", lambda name: "/usr/bin/bun")
    monkeypatch.setattr(rb, "node_modules_present", lambda root: False)
    assert rl.may_build_at_launch("/repo") is True


def test_no_javascript_runtime_means_no_build_however_warm(monkeypatch):
    import reflex_bundle as rb

    monkeypatch.setenv("REFLEX_ALLOW_LOCAL_BUILD", "1")
    monkeypatch.setattr(rl.shutil, "which", lambda name: None)
    monkeypatch.setattr(rb, "node_modules_present", lambda root: True)
    assert rl.may_build_at_launch("/repo") is False


def test_build_env_and_the_stamp_agree_on_the_backend_url():
    """Two spellings of this string would make every bundle read as stale, or
    -- worse -- a genuinely mismatched one read as current."""
    import reflex_bundle as rb

    env = rl.build_env("golden.yml", "UI", "station5", 5010, None)
    assert env["HELAO_REFLEX_API_URL"] == rb.api_url_for("station5", 5010)


# --- P7f: hexagon hosting seam ----------------------------------------------


def test_app_module_env_is_absent_for_a_legacy_reflex_server(monkeypatch):
    """No config key, no variable -- the whole rollback story.

    Asserted for both shapes a legacy entry takes: no ``deployment:`` at all,
    and one naming its own deployment (which is what an hte station's reflex
    server looks like once the launcher has resolved it).
    """
    import reflex_bundle as rb

    monkeypatch.delenv(rb.APP_MODULE_ENV, raising=False)
    for scfg in (None, {}, {"deployment": "test"}, {"deployment": "hte"}):
        env = rl.build_env("golden.yml", "UI", "127.0.0.1", 5010, None, scfg)
        assert rb.APP_MODULE_ENV not in env, scfg


def test_app_module_env_is_set_for_a_hexagon_reflex_server():
    import reflex_bundle as rb

    env = rl.build_env(
        "golden.yml", "UI", "127.0.0.1", 5010, None, {"deployment": "hexagon"}
    )
    assert env[rb.APP_MODULE_ENV] == "helao.hexagon.app.reflex_host"
    assert env[rb.APP_MODULE_ENV] == rb.HEXAGON_APP_MODULE


def test_an_inherited_app_module_variable_is_stripped_for_a_legacy_server(
    monkeypatch,
):
    """This launcher's own environment can carry the variable -- a shell that
    exported it, a parent that set it. Passing it through would hexagon-host a
    server whose config says nothing of the kind, and the only visible symptom
    would be a bundle that reads stale on every launch."""
    import reflex_bundle as rb

    monkeypatch.setenv(rb.APP_MODULE_ENV, rb.HEXAGON_APP_MODULE)
    env = rl.build_env("golden.yml", "UI", "127.0.0.1", 5010, None, {})
    assert rb.APP_MODULE_ENV not in env


def test_snapshot_import_follows_the_same_routing_as_the_child():
    """The loaded-modules snapshot and the bundle stamp are both read out of
    THIS process's sys.modules, so the launcher must import what the backend
    child will serve. Importing the legacy app while the child serves the
    facade leaves the hot-reload watcher blind to the facade and the stamp
    describing a bundle nobody built."""
    seen: list = []

    def _spy(name):
        seen.append(name)
        return name

    assert rl.import_app_module({}, importer=_spy) == "helao.ui.reflex.app"
    assert (
        rl.import_app_module({"deployment": "hexagon"}, importer=_spy)
        == "helao.hexagon.app.reflex_host"
    )
    assert seen == [
        "helao.ui.reflex.app",
        "helao.hexagon.app.reflex_host",
    ]


def test_the_launcher_hands_its_server_config_to_both_routing_calls():
    """Routing degrades SILENTLY to legacy when the server block is not
    passed: ``app_module_for(None)`` is the legacy module, so a call site that
    forgets the argument produces a launch that logs nothing, serves the
    legacy app, and looks entirely healthy under a ``deployment: hexagon``
    config. Only the call sites can prove that did not happen, so they are
    read here rather than trusted.
    """
    import ast

    tree = ast.parse(open(rl.__file__, encoding="utf8").read())
    calls = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in ("build_env", "import_app_module", "app_module_for"):
            continue
        args = [a for a in node.args if isinstance(a, ast.Name)]
        calls.setdefault(node.func.id, []).append([a.id for a in args])

    # build_env's 6th positional argument is the server block
    assert any(
        len(a) >= 6 and a[5] == "server_config" for a in calls.get("build_env", [])
    ), calls
    assert ["server_config"] in calls.get("import_app_module", []), calls
    assert ["server_config"] in calls.get("app_module_for", []), calls


def test_resolve_bundle_rejects_a_zero_byte_index_html(tmp_path):
    """An interrupted export leaves a truncated index.html.

    Serving it yields a blank browser page and a silent log; treating it as
    absent routes into the loud failure path instead.
    """
    bundle = tmp_path / ".reflex-bundle" / "golden_UI" / "helao_ui"
    bundle.mkdir(parents=True)
    (bundle / "index.html").write_text("")
    assert rl.resolve_bundle(str(tmp_path), None, "golden", "UI", {}).path == ""


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
    assert "build_reflex_bundle.py" in combined, (
        "the failure did not name the command that fixes it:\n" + combined
    )
    assert "--server UI" in combined, (
        "the suggested command did not name this server:\n" + combined
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


def test_frontend_proxies_the_buffer_route_to_the_backend():
    """The blank-chart bug this guards, seen in a live browser.

    The chart-buffer route lives on the Reflex backend (port + 1), but pages
    are served from the frontend port, and the browser resolves the payload's
    relative URL against the page origin. Every fetch hit the static server and
    404'd, so the chart mounted and never painted -- while the state stream
    looked entirely healthy, latest-value table and all.
    """
    import threading

    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import Response
    from fastapi.testclient import TestClient
    from fastapi.staticfiles import StaticFiles

    from helao.ui.reflex.xy_component import BUFFER_ROUTE_PREFIX

    backend = FastAPI()

    @backend.get(f"{BUFFER_ROUTE_PREFIX}/{{panel_id}}")
    async def buffers(panel_id: str, v: int):
        if v != 7:
            return Response(status_code=404)
        return Response(
            content=b"FRAME" + panel_id.encode(),
            media_type="application/octet-stream",
        )

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        backend_free = probe.getsockname()[1]

    server = uvicorn.Server(
        uvicorn.Config(backend, host="127.0.0.1", port=backend_free, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started, "test backend never started"

        # _serve_frontend blocks on uvicorn.run, so its route wiring is
        # reproduced here against the same _buffer_proxy the launcher installs.
        front = FastAPI()
        front.add_route(
            f"{BUFFER_ROUTE_PREFIX}/{{panel_id}}",
            rl._buffer_proxy("127.0.0.1", backend_free),
            methods=["GET"],
        )
        with tempfile.TemporaryDirectory() as bundle:
            with open(os.path.join(bundle, "index.html"), "w") as fh:
                fh.write("<html></html>")
            front.mount("/", StaticFiles(directory=bundle, html=True), name="frontend")

            client = TestClient(front)
            ok = client.get(f"{BUFFER_ROUTE_PREFIX}/panel-x?v=7")
            assert ok.status_code == 200, "buffer route did not reach the backend"
            assert ok.content == b"FRAMEpanel-x"
            assert ok.headers["content-type"] == "application/octet-stream"
            # A stale version must still 404 through, not become a 200.
            assert client.get(f"{BUFFER_ROUTE_PREFIX}/panel-x?v=6").status_code == 404
            # The static mount still serves the app.
            assert client.get("/").status_code == 200
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_buffer_proxy_reports_a_dead_backend_as_502():
    """A 502 keeps the chart on its last good frame; a raised exception would
    surface as an opaque 500 and tell nobody which side failed."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from helao.ui.reflex.xy_component import BUFFER_ROUTE_PREFIX

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]

    front = FastAPI()
    front.add_route(
        f"{BUFFER_ROUTE_PREFIX}/{{panel_id}}",
        rl._buffer_proxy("127.0.0.1", dead_port),
        methods=["GET"],
    )
    resp = TestClient(front).get(f"{BUFFER_ROUTE_PREFIX}/panel-x?v=1")
    assert resp.status_code == 502
    assert "unreachable" in resp.text


# --- Dying with the group ---------------------------------------------------


def test_parent_watch_target_is_none_when_started_from_a_shell():
    """A launcher run by hand has no group to die with, and shutting itself
    down because 'the parent went away' would be wrong."""
    assert rl.parent_watch_target(1) is None
    assert rl.parent_watch_target(0) is None
    assert rl.parent_watch_target(None) is None


def test_parent_watch_target_is_none_when_the_parent_already_exited():
    assert rl.parent_watch_target(4242, probe=lambda pid: None) is None


def test_parent_watch_target_records_the_creation_time():
    assert rl.parent_watch_target(4242, probe=lambda pid: 111.0) == (4242, 111.0)


def test_parent_is_gone_is_false_while_the_parent_lives():
    assert rl.parent_is_gone((4242, 111.0), probe=lambda pid: 111.0) is False


def test_parent_is_gone_is_true_once_the_parent_exits():
    assert rl.parent_is_gone((4242, 111.0), probe=lambda pid: None) is True


def test_parent_is_gone_survives_pid_reuse():
    """The reason the creation time is carried at all: pids are recycled, and
    an unrelated process landing on launch.py's old pid must not read as 'my
    group is still alive' -- that is the orphan this exists to prevent."""
    assert rl.parent_is_gone((4242, 111.0), probe=lambda pid: 999.0) is True


def test_parent_is_gone_is_false_with_nothing_to_watch():
    assert rl.parent_is_gone(None, probe=lambda pid: None) is False


def test_watch_parent_does_nothing_without_a_parent():
    fired = []
    rl.watch_parent(None, lambda: fired.append(1), sleep=lambda s: None)
    assert fired == []


def test_watch_parent_fires_once_the_parent_disappears():
    states = [111.0, 111.0, None]
    fired = []
    slept = []
    rl.watch_parent(
        (4242, 111.0),
        lambda: fired.append(1),
        poll=0.5,
        sleep=slept.append,
        probe=lambda pid: states.pop(0),
    )
    assert fired == [1]
    assert slept == [0.5, 0.5]


def test_terminate_tree_is_a_noop_for_a_pid_that_is_gone():
    assert rl.terminate_tree(2**22 - 1, 0.5, 0.5) is True


def test_terminate_tree_kills_grandchildren_too():
    """`reflex run` is a supervisor whose worker holds the backend port, so
    signalling only the direct child leaves the port bound."""
    import psutil

    parent = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
            "time.sleep(300)\n",
        ]
    )
    try:
        deadline = time.time() + 10
        kids = []
        while time.time() < deadline:
            kids = psutil.Process(parent.pid).children(recursive=True)
            if kids:
                break
            time.sleep(0.1)
        assert kids, "test grandchild never started"
        grandchild = kids[0].pid

        assert rl.terminate_tree(parent.pid, 3.0, 1.0) is True
        parent.poll()
        assert (
            not psutil.pid_exists(grandchild)
            or not psutil.Process(grandchild).is_running()
        )
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX-only")
def test_terminate_tree_reaches_a_reparented_process_through_its_group():
    """The leak this guards, reproduced against a live launcher: `reflex run`
    starts its server through multiprocessing, and the instant the CLI dies
    those workers are reparented to init -- invisible to any tree walk, still
    holding the backend port. The process group is the only handle left."""
    import psutil

    # A session leader whose grandchild outlives it, like reflex's worker.
    leader = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
            "time.sleep(0.5)\n",  # exits, orphaning the grandchild
        ],
        start_new_session=True,
    )
    pgid = leader.pid
    try:
        deadline = time.time() + 10
        grandchild = None
        while time.time() < deadline:
            kids = psutil.Process(leader.pid).children(recursive=True)
            if kids:
                grandchild = kids[0].pid
                break
            time.sleep(0.1)
        assert grandchild is not None, "test grandchild never started"

        leader.wait(timeout=10)  # now the grandchild is reparented
        assert psutil.Process(grandchild).is_running()
        assert grandchild not in [
            p.pid for p in psutil.Process(os.getpid()).children(recursive=True)
        ], "grandchild should no longer be reachable by walking our tree"

        rl.signal_group(pgid, signal.SIGKILL)
        gone = False
        deadline = time.time() + 10
        while time.time() < deadline:
            if (
                not psutil.pid_exists(grandchild)
                or psutil.Process(grandchild).status() == psutil.STATUS_ZOMBIE
            ):
                gone = True
                break
            time.sleep(0.1)
        assert gone, "reparented process survived the group kill"
    finally:
        if leader.poll() is None:
            leader.kill()
        rl.signal_group(pgid, signal.SIGKILL)


def test_signal_group_ignores_a_group_that_is_already_gone():
    """Shutdown runs the group kill unconditionally; a vanished group is the
    normal case, not an error."""
    rl.signal_group(2**22 - 1, signal.SIGTERM)
