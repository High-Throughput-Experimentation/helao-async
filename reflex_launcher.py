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
    "BUNDLE_DIRNAME",
    "backend_port",
    "build_env",
    "install_pdeathsig",
    "may_build_locally",
    "parent_is_gone",
    "parent_watch_target",
    "port_holder",
    "process_start_time",
    "resolve_bundle",
    "signal_group",
    "terminate_tree",
    "wait_for_backend",
    "watch_parent",
]

import asyncio
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

import colorama
import psutil

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

#: How often the parent-liveness watchdog checks that ``launch.py`` is still
#: there. Short enough that the next launch of the same config is not blocked
#: for long, long enough to be free.
PARENT_POLL_SECONDS = 2.0

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


# --- Dying with the group ---------------------------------------------------
#
# `launch.py` tears a group down by signalling each server's own pid. Nothing
# covers the two cases where that signal is never sent or never reaches the
# whole tree, and both were observed repeatedly:
#
#   * `launch.py` itself dies without cleaning up -- SIGKILL, a closed
#     terminal, a crash -- and this launcher just keeps running, holding
#     `port` and `port + 1` until someone finds it by hand.
#   * this launcher is SIGKILLed (launch.py escalates after GRACEFUL_WAIT),
#     so the `finally` never runs and the Reflex backend it spawned survives
#     holding `port + 1`.
#
# Either way the next launch of the same config cannot bind. The preflight
# added earlier names the squatter; these functions stop it existing.


def process_start_time(pid: int):
    """Return a process's creation time, or ``None`` if it is not running.

    The creation time is what makes a pid safe to compare against later: pids
    are recycled, so "a process with this pid exists" is not the same question
    as "my parent is still alive".

    Args:
        pid: Process id to probe.

    Returns:
        float | None: Creation timestamp, or ``None`` when no such process.
    """
    try:
        return psutil.Process(pid).create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        return None


def parent_watch_target(ppid: int, probe=process_start_time):
    """Identify the parent to watch, or ``None`` when there is nothing to watch.

    Args:
        ppid: This process's parent pid at startup.
        probe: Callable returning a pid's creation time.

    Returns:
        tuple[int, float] | None: ``(pid, create_time)``, or ``None`` when the
        launcher was started directly from a shell rather than by ``launch.py``
        (pid 1 or already reparented), where dying with the parent is wrong.
    """
    if ppid is None or ppid <= 1:
        return None
    created = probe(ppid)
    if created is None:
        return None
    return (ppid, created)


def parent_is_gone(watch, probe=process_start_time) -> bool:
    """Whether the watched parent has exited.

    Pure apart from ``probe``, so the pid-reuse case is testable without
    orchestrating real process deaths.

    Args:
        watch: The :func:`parent_watch_target` result, or ``None``.
        probe: Callable returning a pid's creation time.

    Returns:
        bool: ``True`` when the parent is gone, including when its pid has been
        recycled by an unrelated process. ``False`` when there is no parent to
        watch -- a launcher run by hand must not shut itself down.
    """
    if watch is None:
        return False
    pid, created = watch
    return probe(pid) != created


def install_pdeathsig(sig=signal.SIGTERM) -> bool:
    """Ask the kernel to signal this process when its parent dies.

    Linux-only (``prctl(PR_SET_PDEATHSIG)``). Instant and immune to a parent
    that dies uncatchably, which polling cannot match -- but it is a
    best-effort optimization, not the mechanism: :func:`watch_parent` is what
    every platform relies on, and it also covers the race where the parent dies
    before this call lands.

    Args:
        sig: Signal the kernel should deliver on parent death.

    Returns:
        bool: ``True`` if installed.
    """
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes

        pr_set_pdeathsig = 1
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        return libc.prctl(pr_set_pdeathsig, int(sig), 0, 0, 0) == 0
    except Exception:
        return False


def watch_parent(
    watch,
    on_gone,
    poll: float = PARENT_POLL_SECONDS,
    sleep=time.sleep,
    probe=process_start_time,
):
    """Block until the watched parent exits, then call ``on_gone``.

    Returns immediately when there is nothing to watch.

    ``probe`` is threaded through to :func:`parent_is_gone` rather than left to
    that function's own default: a default argument binds at definition time,
    so a test replacing the module-level probe would have no effect here and
    would silently exercise the real one.

    Args:
        watch: The :func:`parent_watch_target` result, or ``None``.
        on_gone: Called once, when the parent is gone.
        poll: Seconds between checks.
        sleep: Injected for tests.
        probe: Callable returning a pid's creation time.
    """
    if watch is None:
        return
    while not parent_is_gone(watch, probe=probe):
        sleep(poll)
    on_gone()


def signal_group(pgid: int, sig) -> None:
    """Signal a whole process group, ignoring one that is already gone.

    A tree walk finds only processes that are still descendants. ``reflex run``
    starts its server through ``multiprocessing``, and the moment the CLI dies
    those workers are reparented to init -- at which point no walk can reach
    them, while they still hold the backend port. They keep their process
    group, so the group is the only handle that survives.

    Args:
        pgid: Process group id.
        sig: Signal to deliver.
    """
    if os.name != "posix":
        return
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def terminate_tree(
    pid: int, term_wait: float, kill_wait: float, logger=None, pgid=None
) -> bool:
    """Terminate a process, every descendant, and its process group.

    Signalling only the direct child is not enough: ``reflex run`` is a
    supervisor whose worker is what actually holds the backend port, and that
    worker outlives the CLI as a reparented orphan.

    Args:
        pid: Root of the tree to terminate.
        term_wait: Seconds to allow for cooperative exit before SIGKILL.
        kill_wait: Seconds to wait after SIGKILL, so nothing is left unreaped.
        logger: Optional logger for survivors.
        pgid: Process group to sweep as well. POSIX only.

    Returns:
        bool: ``True`` if the whole tree is gone.
    """
    try:
        root = psutil.Process(pid)
        procs = root.children(recursive=True) + [root]
    except psutil.NoSuchProcess:
        procs = []

    for proc in procs:
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if pgid is not None:
        signal_group(pgid, signal.SIGTERM)

    _, alive = psutil.wait_procs(procs, timeout=term_wait)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if pgid is not None:
        signal_group(pgid, signal.SIGKILL)

    _, still_alive = psutil.wait_procs(alive, timeout=kill_wait)
    if still_alive and logger is not None:
        pids = ", ".join(str(p.pid) for p in still_alive)
        logger.warning(f"reflex backend pids {pids} did not exit after kill")
    return not still_alive


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


def _buffer_proxy(backend_host: str, target_port: int):
    """Build the handler that relays chart-buffer requests to the backend.

    The chart buffer route is registered on the Reflex *backend*, but the page
    is served from the frontend port, and the browser resolves the relative
    URL in the chart payload against the page's own origin. Every fetch
    therefore landed on the static server and 404'd, leaving a mounted-but-
    never-painted chart while the state stream itself looked perfectly healthy.

    Proxying rather than emitting an absolute backend URL keeps the request
    same-origin (no CORS on a route that carries raw binary) and keeps the
    payload free of any build-time host baking. The hop is loopback.

    Args:
        backend_host: Host the Reflex backend listens on.
        target_port: The backend's port.

    Returns:
        An ASGI endpoint suitable for ``add_route``.
    """
    import httpx
    from starlette.responses import Response as StarletteResponse

    base = f"http://{backend_host}:{target_port}"

    async def relay(request):
        url = f"{base}{request.url.path}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                upstream = await client.get(url, params=dict(request.query_params))
        except httpx.HTTPError as exc:
            # The chart keeps its last good frame on a non-200, so a backend
            # blip degrades to a stale chart rather than a blank one.
            return StarletteResponse(f"buffer backend unreachable: {exc}", 502)
        return StarletteResponse(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type"),
        )

    return relay


def _serve_frontend(bundle_dir: str, host: str, port: int):
    """Serve the exported static frontend. Blocks until interrupted."""
    import uvicorn
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    from helao.core.servers.reflex.xy_component import BUFFER_ROUTE_PREFIX

    static_app = FastAPI()
    static_app.add_route(
        f"{BUFFER_ROUTE_PREFIX}/{{panel_id}}",
        _buffer_proxy(host, backend_port(port)),
        methods=["GET"],
    )
    # Mounted last: StaticFiles at "/" swallows every path below it.
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

    from helao.core.version import get_hlo_version, hlo_version
    from helao.helpers import config_loader
    from helao.helpers import helao_logging as logging
    from helao.helpers.parent_death import arm_parent_death_signal, monitor_detached
    from helao.helpers.yml_tools import yml_load

    # Die with launch.py rather than orphaning and holding this server's two
    # ports. Armed here, at the top, so it also covers the port-preflight and
    # backend-spawn phases below. The kernel keeps exactly one PDEATHSIG per
    # process, so this is the *only* self-arming call in this launcher -- the
    # separate install_pdeathsig() call under the backend's Popen arms the
    # backend, which is a different process.
    arm_parent_death_signal()

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
    CONFIG["hlo_version"] = hlo_version
    deploy_git_path = os.path.join(helao_repo_root, "helao", "deploy", CONFIG["deployment"], ".git")
    deploy_worktree_path = os.path.dirname(deploy_git_path)
    if os.path.exists(deploy_git_path):
        CONFIG["deployment_version"] = get_hlo_version(deploy_worktree_path)
    else:
        CONFIG["deployment_version"] = hlo_version

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

    # Two mechanisms, because one alone leaks:
    #
    #   start_new_session gives the backend its own process group, which is the
    #   only handle that still reaches `reflex run`'s multiprocessing workers
    #   once the CLI dies and they are reparented to init.
    #
    #   pdeathsig fires when this launcher is SIGKILLed and the `finally` below
    #   never runs. It must be SIGTERM, not SIGKILL: SIGKILL gives the CLI no
    #   chance to stop its workers, which then survive holding `port + 1` --
    #   the exact orphan this is meant to prevent, observed in testing.
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
        start_new_session=(os.name == "posix"),
        preexec_fn=(
            (lambda: install_pdeathsig(signal.SIGTERM))
            if sys.platform.startswith("linux")
            else None
        ),
    )
    # With start_new_session the child leads its own group, so pgid == pid.
    backend_pgid = backend.pid if os.name == "posix" else None
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
        terminate_tree(
            backend.pid, BACKEND_TERM_WAIT, BACKEND_KILL_WAIT, LOGGER, backend_pgid
        )
        backend.poll()  # reap, so no zombie is left behind
        sys.exit(1)

    LOGGER.info(
        f"started {server_key}: frontend {servHost}:{servPort}, "
        f"backend {servHost}:{backend_port(servPort)}"
    )

    def _shutdown_backend():
        """Take the whole backend tree down and reap it."""
        terminate_tree(
            backend.pid, BACKEND_TERM_WAIT, BACKEND_KILL_WAIT, LOGGER, backend_pgid
        )
        backend.poll()

    # prctl was armed at the top of this block (arm_parent_death_signal). This
    # watchdog is what every platform actually depends on, and it also covers
    # the race where the parent dies before prctl lands. Both run: neither alone
    # is sufficient.
    watch = parent_watch_target(os.getppid())
    if watch is None:
        LOGGER.info(f"no parent to watch; {server_key} will run until stopped directly")
    else:
        parent_pid = watch[0]

        def _parent_died():
            if monitor_detached():
                # CTRL-d: the launcher exited on purpose and left the group
                # running. Before this check, disconnecting the monitor took the
                # Reflex UI down with it while every other server survived.
                LOGGER.info(
                    f"launch.py (pid {parent_pid}) detached deliberately (CTRL-d); "
                    f"{server_key} stays up on {servHost}:{servPort}."
                )
                return
            LOGGER.warning(
                f"launch.py (pid {parent_pid}) is gone; shutting {server_key} down "
                f"so it does not hold {servHost}:{servPort} and "
                f"{servHost}:{backend_port(servPort)}"
            )
            _shutdown_backend()
            # os._exit, not sys.exit: this runs on a watchdog thread, where
            # SystemExit would only unwind that thread and leave uvicorn
            # serving on the main one -- exactly the orphan being fixed.
            os._exit(0)

        threading.Thread(
            target=watch_parent,
            args=(watch, _parent_died),
            name="parent-watchdog",
            daemon=True,
        ).start()

    try:
        _serve_frontend(bundle, servHost, servPort)
    finally:
        _shutdown_backend()
