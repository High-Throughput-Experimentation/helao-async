"""Backend of the /runners page (spec: Page). No Reflex state.

The page never imports runner code: the catalog comes from the launcher's
``--describe`` subprocesses, so edits, additions and deletions show on Refresh.
"""

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

from helao.core.error import ErrorCodes
from helao.helpers import helao_logging as logging
from helao.helpers.dispatcher import async_private_dispatcher
from helao.helpers.parent_death import DETACH_MARKER_ENV, PARENT_PID_ENV
from helao.ui.reflex import group

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

DESCRIBE_TIMEOUT_S = 10.0
PROBE = {"timeout": 5, "retries": 1}
LAUNCH = [sys.executable, "-m", "helao.core.runners.launch"]
_DEP_RE = re.compile(r"helao[\\/]deploy[\\/]([^\\/]+)[\\/]configs[\\/]")

CATALOG: dict = {}
PROCS: dict = {}
_WATCHERS: set = set()
# rc after Stop that mean "stopped": clean 0, SIGTERM, Windows CTRL_BREAK
_CLEAN_STOP_RC = (0, -signal.SIGTERM) + ((0xC000013A,) if os.name == "nt" else ())
_LAUNCHING: set = set()  # keys reserved between the check and PROCS[key]


def _platform_ops(name: Optional[str] = None) -> tuple:
    """(spawn kwargs, stop signal) for the platform; `name` defaults to os.name.

    Windows has no SIGTERM for another process: the child gets its own process
    group and the stop is CTRL_BREAK_EVENT, which the launcher handles as SIGBREAK.
    """
    if (name or os.name) == "nt":
        return (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP},
            signal.CTRL_BREAK_EVENT,
        )
    return {}, signal.SIGTERM


def deployment_of(world_cfg: dict) -> Optional[str]:
    m = _DEP_RE.search(str((world_cfg or {}).get("loaded_config_path") or ""))
    return m.group(1) if m else None


def runner_modules(deployment: str, repo_root: str) -> list:
    folder = os.path.join(repo_root, "helao", "deploy", deployment, "runners")
    if not os.path.isdir(folder):
        return []
    return sorted(
        f"helao.deploy.{deployment}.runners.{f[:-3]}"
        for f in os.listdir(folder)
        if f.endswith(".py") and f != "__init__.py"
    )


def _module_file(module: str, repo_root: str) -> str:
    return os.path.join(repo_root, *module.split(".")) + ".py"


async def _describe(module: str) -> dict:
    proc = await asyncio.create_subprocess_exec(
        *LAUNCH,
        "--describe",
        module,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # stops the describe writing a same-second .pyc (reading one is not stopped)
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), DESCRIBE_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {
            "module": module,
            "error": f"describe timed out after {DESCRIBE_TIMEOUT_S:.0f} s",
        }
    try:
        lines = [x for x in out.decode("utf-8").splitlines() if x.strip()]
        return json.loads(lines[-1])
    except (ValueError, IndexError):
        tail = err.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no output"]
        return {"module": module, "error": tail[0]}


async def describe_all(modules: list, repo_root: Optional[str] = None) -> list:
    entries = await asyncio.gather(*(_describe(m) for m in modules))
    for e in entries:
        path = _module_file(e["module"], repo_root) if repo_root else None
        e["mtime"] = os.path.getmtime(path) if path and os.path.exists(path) else None
    return list(entries)


async def refresh_catalog(world_cfg: dict, repo_root: str) -> list:
    dep = deployment_of(world_cfg)
    entries = (
        await describe_all(runner_modules(dep, repo_root), repo_root) if dep else []
    )
    # a module with no async run(orch, ...) is a helper, not a runner: unlisted
    entries = [e for e in entries if not e.get("not_runner")]
    CATALOG.clear()
    CATALOG.update({e["module"]: e for e in entries})
    return entries


async def probe(servers: list, world_cfg: dict) -> tuple:
    cfg = (world_cfg or {}).get("servers") or {}

    async def one(key):
        c = cfg.get(key)
        if not c:
            return key, None, None
        try:
            eps, err = await async_private_dispatcher(
                key, c["host"], c["port"], "endpoints", json_dict={}, **PROBE
            )
        except Exception:
            return key, None, None
        if err != ErrorCodes.none or not isinstance(eps, list):
            return key, None, None
        names = []
        for d in eps:
            parts = (
                str(d.get("path", "")).strip("/").split("/")
                if isinstance(d, dict)
                else []
            )
            if len(parts) == 2 and parts[0] == key:
                names.append(parts[1])
        try:
            st, err2 = await async_private_dispatcher(
                key, c["host"], c["port"], "get_status", json_dict={}, **PROBE
            )
        except Exception:
            st, err2 = None, None
        ok = err2 == ErrorCodes.none and isinstance(st, dict)
        return key, names, st if ok else None

    results = await asyncio.gather(*(one(k) for k in servers))
    return {k: e for k, e, _ in results}, {k: s for k, _, s in results}


@dataclass
class RunnerProc:
    key: str
    module: str
    log_path: str
    proc: object
    started: float = field(default_factory=time.time)
    state: str = "running"
    rc: Optional[int] = None

    @property
    def pid(self) -> int:
        return self.proc.pid


def _taken(key: str) -> bool:
    if key in _LAUNCHING:
        return True
    p = PROCS.get(key)
    if p is not None and p.state in ("running", "stopping"):
        return True
    entry = group.REGISTRY.get(key)
    return entry is not None and not entry.lost(time.time())


async def _watch(p: RunnerProc) -> None:
    p.rc = await p.proc.wait()
    if p.state == "stopping" and p.rc in _CLEAN_STOP_RC:  # early Stop can give -15
        p.state = "stopped"
    elif p.state != "killed":
        p.state = "exited"


async def launch(world_cfg: dict, module: str, key: str, params: dict) -> RunnerProc:
    if _taken(key):
        raise ValueError(f"key {key} is already running")
    _LAUNCHING.add(key)
    try:
        logs = os.path.join(world_cfg["root"], "LOGS")
        os.makedirs(logs, exist_ok=True)
        log_path = os.path.join(
            logs, f"runner_{key}_{time.strftime('%Y%m%d-%H%M%S')}.log"
        )
        env = {**os.environ, PARENT_PID_ENV: str(os.getpid()), "HELAO_SERVER_KEY": key}
        env.pop(DETACH_MARKER_ENV, None)
        kwargs, _ = _platform_ops()
        with open(log_path, "w", encoding="utf-8") as log:
            proc = await asyncio.create_subprocess_exec(
                *LAUNCH,
                world_cfg["loaded_config_path"],
                module,
                "--key",
                key,
                "--params",
                json.dumps(params),
                stdout=log,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                **kwargs,
            )
        p = RunnerProc(key=key, module=module, log_path=log_path, proc=proc)
        PROCS[key] = p
    finally:
        _LAUNCHING.discard(key)
    task = asyncio.get_running_loop().create_task(_watch(p))
    _WATCHERS.add(task)
    task.add_done_callback(_WATCHERS.discard)
    LOGGER.info(f"runner {key}: launched {module} pid {p.pid} log {log_path}")
    return p


def stop(key: str) -> None:
    p = PROCS.get(key)
    if p and p.state == "running":
        try:
            p.proc.send_signal(_platform_ops()[1])
        except ProcessLookupError:
            return
        p.state = "stopping"
        LOGGER.info(f"runner {key}: stop requested (pid {p.pid})")


def force_kill(key: str) -> None:
    p = PROCS.get(key)
    if p and p.state in ("running", "stopping"):
        try:
            p.proc.kill()
        except ProcessLookupError:
            return
        p.state = "killed"
        LOGGER.warning(f"runner {key}: force kill (pid {p.pid})")


def busy() -> bool:
    """True while any runner is being spawned, running or stopping."""
    return bool(_LAUNCHING) or any(
        p.state in ("running", "stopping") for p in PROCS.values()
    )


def dismiss(key: str) -> None:
    p = PROCS.get(key)
    if p and p.state not in ("running", "stopping"):
        del PROCS[key]


def overlap() -> dict:
    busy: dict = {}
    for k in group.feed_keys():
        feed = group.feed_for(k)
        if group.stream_lost(feed, time.time()):
            continue
        frame = group.latest_frame(feed) or {}
        for row in frame.get("servers", []):
            if row.get("status") == "busy":
                busy.setdefault(row["key"], []).append(k)
    return {s: ks for s, ks in busy.items() if len(ks) > 1}
