"""Launch the HELAO Reflex UI app for one config entry.

Sibling of ``bokeh_launcher.py``. A Reflex server occupies two consecutive
ports: the prebuilt static frontend is served on ``port`` by a small uvicorn +
StaticFiles app defined here, and the Reflex backend runs on ``port + 1``.
Serving the frontend ourselves means a lab station never needs Node or Bun at
runtime — only the dev machine that produced the bundle does.

Usage:
    python reflex_launcher.py <config_file> <server_key>

Build the frontend bundle on a development machine before deploying::

    cd helao/core/servers/reflex/_app
    reflex export --frontend-only
    # then place the export under <repo_root>/.reflex-bundle/helao_ui/
"""

__all__ = [
    "APP_NAME",
    "wait_for_backend",
    "port_holder",
    "BUNDLE_DIRNAME",
    "backend_port",
    "resolve_bundle",
    "build_env",
    "may_build_locally",
]

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import time

import colorama

#: Must match ``app_name`` in ``helao/core/servers/reflex/_app/rxconfig.py``.
APP_NAME = "helao_ui"

#: Gitignored directory under the repo root holding the exported frontend.
BUNDLE_DIRNAME = ".reflex-bundle"

#: Reflex project directory the CLI is invoked from.
APP_DIR = os.path.join("helao", "core", "servers", "reflex", "_app")

#: Seconds allowed for the backend to exit on SIGTERM before escalating, and
#: for the killed process to be reaped. These must add up to comfortably less
#: than ``Pidd.GRACEFUL_WAIT`` (7.0s, launch.py) -- that is the window before
#: the orchestrator SIGKILLs *this* launcher. Overrunning it means the launcher
#: dies mid-cleanup and leaves an untracked backend holding ``port + 1``, so the
#: next launch of the same config cannot bind.
BACKEND_TERM_WAIT = 3.0
BACKEND_KILL_WAIT = 1.0

#: Seconds to wait for the backend to begin listening before giving up. A
#: backend that dies at startup leaves the frontend serving a page that can only
#: report "websocket error", with nothing in the logs to say why.
BACKEND_START_TIMEOUT = 30.0

#: Bound the frontend's own graceful shutdown. uvicorn defaults to waiting
#: indefinitely for open connections, which would blow the same budget: a single
#: browser tab left open on the panel page is enough.
FRONTEND_SHUTDOWN_TIMEOUT = 2

#: Reflex assets directory, served from the site root. xy's ESM client is
#: copied here before the frontend build so the bundle ships it and the browser
#: never reaches for a CDN.
ASSETS_DIR = os.path.join(APP_DIR, "assets")


def backend_port(port: int) -> int:
    """Return the Reflex backend port for a server whose frontend is on ``port``."""
    return int(port) + 1


def resolve_bundle(repo_root: str):
    """Locate the exported frontend bundle.

    Args:
        repo_root: HELAO repository root.

    Returns:
        The bundle directory, or ``None`` when no usable bundle is present. A
        directory without ``index.html`` is treated as absent — a half-written
        export must not be served.
    """
    candidate = os.path.join(repo_root, BUNDLE_DIRNAME, APP_NAME)
    index = os.path.join(candidate, "index.html")
    if not (os.path.isdir(candidate) and os.path.isfile(index)):
        return None
    # A zero-byte index.html means an interrupted export or a partial copy.
    # Serving it silently yields a blank page in the browser with nothing in
    # the logs; treating it as absent routes into the loud failure path.
    if os.path.getsize(index) == 0:
        return None
    return candidate


def build_env(config_path: str, server_key: str, host: str, port: int, root):
    """Return the child environment for the Reflex backend process.

    Args:
        config_path: Config argument forwarded to the child.
        server_key: Config key of this Reflex server.
        host: Host the servers bind to.
        port: Frontend port; the backend uses ``port + 1``.
        root: HELAO output root, or ``None``.

    Returns:
        dict: A copy of the parent environment plus the HELAO Reflex vars.
    """
    env = dict(os.environ)
    env["HELAO_REFLEX_SERVER_KEY"] = server_key
    env["HELAO_REFLEX_CONFIG"] = str(config_path)
    env["HELAO_REFLEX_FRONTEND_PORT"] = str(port)
    env["HELAO_REFLEX_BACKEND_PORT"] = str(backend_port(port))
    env["HELAO_REFLEX_API_URL"] = f"http://{host}:{backend_port(port)}"
    if root:
        env["HELAO_REFLEX_ROOT"] = str(root)
    return env


def may_build_locally() -> bool:
    """Whether a local frontend build is permitted in this environment.

    Requires both the ``REFLEX_ALLOW_LOCAL_BUILD=1`` opt-in and a JavaScript
    runtime on ``PATH``. Lab stations set neither, so they fail loudly on a
    missing bundle instead of silently attempting a multi-minute network build.
    """
    if os.environ.get("REFLEX_ALLOW_LOCAL_BUILD") != "1":
        return False
    return bool(shutil.which("bun") or shutil.which("node"))


def port_holder(host: str, port: int) -> str:
    """Describe what already listens on ``host:port``, if anything.

    Args:
        host: Host to probe.
        port: Port to probe.

    Returns:
        str: ``""`` when the port is free, otherwise a message naming the
        holding process where it can be identified.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex((host, port)) != 0:
            return ""
    holder = ""
    try:
        import psutil

        for conn in psutil.net_connections(kind="inet"):
            laddr = getattr(conn, "laddr", None)
            if not laddr or laddr.port != port or conn.status != "LISTEN":
                continue
            if conn.pid:
                proc = psutil.Process(conn.pid)
                holder = f" (pid {conn.pid}: {' '.join(proc.cmdline())[:90]})"
            break
    except Exception:  # psutil optional/racy; the address is the useful part
        pass
    return f"{host}:{port} is already in use{holder}"


def wait_for_backend(process, host: str, port: int, timeout: float) -> str:
    """Wait for the backend to listen, or explain why it will not.

    Args:
        process: The spawned backend ``Popen``.
        host: Host it should bind.
        port: Port it should bind.
        timeout: Seconds to wait before giving up.

    Returns:
        str: ``""`` once the port accepts a connection, otherwise a message
        naming the reason -- the process exited, or it never bound in time.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return (
                f"the Reflex backend exited immediately with code "
                f"{process.returncode} and never bound {host}:{port}"
            )
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            if probe.connect_ex((host, port)) == 0:
                return ""
        time.sleep(0.25)
    return (
        f"the Reflex backend did not begin listening on {host}:{port} in {timeout:.0f}s"
    )


def _serve_frontend(bundle_dir: str, host: str, port: int):
    """Serve the exported static frontend. Blocks until interrupted."""
    import uvicorn
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    static_app = FastAPI()
    static_app.mount("/", StaticFiles(directory=bundle_dir, html=True), name="frontend")
    uvicorn.run(
        static_app,
        host=host,
        port=port,
        log_level="warning",
        timeout_graceful_shutdown=FRONTEND_SHUTDOWN_TIMEOUT,
    )


if __name__ == "__main__":
    # Same handling as fast_launcher/bokeh_launcher: launch.py sets
    # HELAO_FORCE_COLOR when it pumps our output through its own tty stdout, so
    # emit raw ANSI and let the launcher's colorama translate it (which on
    # Windows must happen against a real console handle, not our pipe) rather
    # than stripping just because our own stdout is a pipe.
    if os.environ.get("HELAO_FORCE_COLOR") == "1":
        colorama.init(strip=False, convert=False)
    else:
        colorama.init(strip=not sys.stdout.isatty())

    if sys.platform == "win32":
        # Match bokeh_launcher.py: a selector loop, so a co-located ZMQ RPC
        # socket works without the Proactor loop's missing add_reader family.
        asyncio.set_event_loop(asyncio.SelectorEventLoop())

    from helao.helpers import config_loader
    from helao.helpers import helao_logging as logging
    from helao.helpers.yml_tools import yml_load

    helao_repo_root = os.path.dirname(os.path.realpath(__file__))
    confArg = sys.argv[1]
    server_key = sys.argv[2]

    if config_loader.CONFIG is None:
        config_dict, _validated = config_loader.read_validated_config(confArg)
        config_loader.install_global_config(config_dict)
    CONFIG = config_loader.CONFIG

    server_config = CONFIG["servers"][server_key]
    root = CONFIG.get("root", None)
    log_root = os.path.join(root, "LOGS") if root else None
    email_config = (
        yml_load(CONFIG["alert_config_path"])
        if CONFIG.get("alert_config_path", False)
        else {}
    )
    if logging.LOGGER is None:
        logging.LOGGER = logging.make_logger(
            logger_name=server_key,
            log_dir=log_root,
            email_config=email_config,
            log_level=server_config.get("log_level", CONFIG.get("log_level", 20)),
        )
    LOGGER = logging.LOGGER
    LOGGER.info(f"Loaded config from: {CONFIG['loaded_config_path']}")

    servHost = server_config["host"]
    servPort = server_config["port"]

    config_path = CONFIG["loaded_config_path"]
    CONFIG["deployment"] = server_config.get(
        "deployment",
        os.path.basename(os.path.dirname(os.path.dirname(config_path))),
    )

    bundle = resolve_bundle(helao_repo_root)
    if bundle is None:
        expected = os.path.join(helao_repo_root, BUNDLE_DIRNAME, APP_NAME)
        if not may_build_locally():
            LOGGER.error(
                f"no Reflex frontend bundle at '{expected}'. Build one on a "
                f"development machine with:\n"
                f"    cd {APP_DIR} && reflex export --frontend-only\n"
                f"then copy the export to that path. To build here instead, set "
                f"REFLEX_ALLOW_LOCAL_BUILD=1 and install bun or node."
            )
            sys.exit(1)
        LOGGER.warning(f"no bundle at '{expected}'; building locally (dev only)")
        from helao.core.servers.reflex.xy_component import copy_client_asset

        asset = copy_client_asset(os.path.join(helao_repo_root, ASSETS_DIR))
        LOGGER.info(f"copied xy ESM client to {asset}")
        subprocess.run(
            ["reflex", "export", "--frontend-only"],
            cwd=os.path.join(helao_repo_root, APP_DIR),
            env=build_env(confArg, server_key, servHost, servPort, root),
            check=True,
        )
        bundle = resolve_bundle(helao_repo_root)
        if bundle is None:
            LOGGER.error("local build completed but produced no usable bundle")
            sys.exit(1)

    LOGGER.info(f"serving Reflex frontend bundle from {bundle}")

    # Import the app before snapshotting so the loaded-modules map includes the
    # panel modules resolved from config strings. Same reason bokeh_launcher
    # refreshes its snapshot after mount_visualizers.
    from helao.core.servers.reflex import app as _reflex_app  # noqa: F401

    if root is not None:
        from helao.helpers.loaded_modules import write_loaded_modules_snapshot

        snap_path = write_loaded_modules_snapshot(
            os.path.join(root, "STATES"), server_key
        )
        if snap_path is not None:
            LOGGER.info(f"wrote loaded-modules snapshot: {snap_path}")
        else:
            LOGGER.warning("failed to write loaded-modules snapshot")

    # Preflight both ports before spawning anything. Without this the backend
    # starts, uvicorn then fails to bind the frontend deep in its own startup,
    # and the finally tears the backend down again -- leaving a browser stuck on
    # "connecting" and the real cause buried in a uvicorn traceback. A stale
    # launcher from a previous run is the usual culprit.
    for label, probe_port in (
        ("frontend", servPort),
        ("backend", backend_port(servPort)),
    ):
        conflict = port_holder(servHost, probe_port)
        if conflict:
            LOGGER.error(
                f"cannot start {server_key}: {label} port {conflict}. Stop that "
                "process first (a launcher left over from an earlier run holds "
                "the port even after the rest of the group exits)."
            )
            sys.exit(1)

    LOGGER.info(f" ---- starting  {server_key} ----")

    backend = subprocess.Popen(
        [
            "reflex",
            "run",
            "--env",
            "prod",
            "--backend-only",
            "--backend-port",
            str(backend_port(servPort)),
        ],
        cwd=os.path.join(helao_repo_root, APP_DIR),
        env=build_env(confArg, server_key, servHost, servPort, root),
    )
    problem = wait_for_backend(
        backend, servHost, backend_port(servPort), BACKEND_START_TIMEOUT
    )
    if problem:
        # Serving the frontend anyway would produce a page whose only symptom is
        # a websocket error, with the real cause absent from every log.
        LOGGER.error(
            f"{problem}. The frontend will not be served. Run the same command "
            f"by hand from {APP_DIR} to see its output: "
            f"reflex run --env prod --backend-only --backend-port "
            f"{backend_port(servPort)}"
        )
        backend.terminate()
        sys.exit(1)

    LOGGER.info(
        f"started {server_key}: frontend {servHost}:{servPort}, "
        f"backend {servHost}:{backend_port(servPort)}"
    )
    try:
        _serve_frontend(bundle, servHost, servPort)
    finally:
        backend.terminate()
        try:
            backend.wait(timeout=BACKEND_TERM_WAIT)
        except subprocess.TimeoutExpired:
            backend.kill()
            try:
                # Reap it: an unreaped child stays a zombie whose PID
                # psutil.pid_exists() still reports as alive.
                backend.wait(timeout=BACKEND_KILL_WAIT)
            except subprocess.TimeoutExpired:
                LOGGER.warning(
                    f"reflex backend pid {backend.pid} did not exit after kill"
                )
