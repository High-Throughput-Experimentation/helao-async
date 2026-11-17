"""Run or describe a runner module (spec: Launcher).

python -m helao.core.runners.launch --describe <module>
python -m helao.core.runners.launch <config> <module> [--key K] [--params JSON] [--host H]
"""

import argparse
import asyncio
import contextlib
import importlib
import inspect
import json
import random
import signal
import socket
import sys
from typing import Optional

from helao.core.rpc import derive_rpc_port
from helao.core.runners.micro_orch import MicroOrch, RunnerStopped
from helao.core.runners.requirements import default_key, inferred
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

PORT_WINDOW = (20000, 40000)
TYPES = {"int": int, "float": float, "str": str, "bool": bool}


class NotRunner(TypeError):
    """The module has no async ``run(orch, ...)``: a helper, not a runner."""


def _run_func(mod):
    fn = getattr(mod, "run", None)
    if not inspect.iscoroutinefunction(fn):
        raise NotRunner("no async run(orch, ...)")
    params = list(inspect.signature(fn).parameters.values())
    if not params:
        raise TypeError("run() takes no orch argument")
    return fn, params[1:]


def _ann_type(ann):
    """Annotation -> int/float/str/bool or None; strings (PEP 563) are looked up."""
    t = TYPES.get(ann.strip()) if isinstance(ann, str) else ann
    return t if t in TYPES.values() else None


def _type_name(ann) -> str:
    t = _ann_type(ann)
    return t.__name__ if t else "unspecified"


def describe(module_name: str) -> dict:
    """The describe JSON; raises on import or contract failure."""
    with contextlib.redirect_stdout(sys.stderr):
        mod = importlib.import_module(module_name)
    fn, params = _run_func(mod)
    for p in params:
        if p.default is inspect.Parameter.empty:
            raise TypeError(f"run() parameter '{p.name}' has no default")
    try:
        source = inspect.getsource(mod)
    except (OSError, TypeError):
        source = ""
    requires = getattr(mod, "REQUIRES", None)
    return {
        "module": module_name,
        "doc": inspect.getdoc(fn) or inspect.getdoc(mod) or "",
        "args": [p.name for p in params],
        "defaults": [p.default for p in params],
        "argtypes": [_type_name(p.annotation) for p in params],
        "requires": requires if isinstance(requires, dict) else None,
        "inferred": inferred(source),
    }


def _to_bool(v):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off", ""):
        return False
    raise ValueError(f"not a bool: {v!r}")


def coerce(params: dict, sig: inspect.Signature) -> dict:
    """Coerce ``params`` by ``run``'s annotations; ValueError names the field."""
    known = {n: p for n, p in list(sig.parameters.items())[1:]}
    out = {}
    for name, value in params.items():
        if name not in known:
            raise ValueError(f"unknown parameter '{name}'")
        ann = _ann_type(known[name].annotation)
        try:
            if ann is bool:
                out[name] = _to_bool(value)
            elif ann in (int, float, str):
                out[name] = ann(value)
            else:
                out[name] = value
        except (TypeError, ValueError) as exc:
            raise ValueError(f"parameter '{name}': {exc}") from exc
    return out


def _bindable(port: int) -> bool:
    for p in (port, derive_rpc_port(port)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", p))
            except OSError:
                return False
    return True


def free_port() -> int:
    """A port whose derived RPC port is also free (low window: no offset overflow)."""
    lo, hi = PORT_WINDOW
    start = random.randint(lo, hi - 1)
    for i in range(hi - lo):
        port = lo + (start - lo + i) % (hi - lo)
        if _bindable(port):
            return port
    raise RuntimeError("no free port pair")


def _reflex_host(world_cfg: dict) -> str:
    for cfg in (world_cfg.get("servers") or {}).values():
        if isinstance(cfg, dict) and cfg.get("reflex"):
            host = cfg.get("host") or "127.0.0.1"
            return "127.0.0.1" if host == "0.0.0.0" else host
    return "127.0.0.1"


def _install_signal_handlers(loop, on_signal) -> None:
    """POSIX: loop handlers. Windows (NotImplementedError): signal.signal fallback."""
    sigs = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        sigs.append(signal.SIGBREAK)
    try:
        for sig in sigs:
            loop.add_signal_handler(sig, on_signal)
    except NotImplementedError:
        for sig in sigs:
            try:
                signal.signal(sig, lambda *_: loop.call_soon_threadsafe(on_signal))
            except (ValueError, OSError):
                pass


async def _run(fn, world_cfg, key, params, host) -> int:
    loop = asyncio.get_running_loop()
    orch = MicroOrch(server_key=key, host=host, port=free_port(), world_cfg=world_cfg)
    hits = {"n": 0}
    task_box: dict = {}

    def on_signal():
        hits["n"] += 1
        if hits["n"] == 1:
            LOGGER.info(f"runner {key}: stop requested")
            orch.request_stop()
        elif "task" in task_box:
            task_box["task"].cancel()

    _install_signal_handlers(loop, on_signal)
    async with orch:
        task = task_box["task"] = asyncio.create_task(fn(orch, **params))
        if hits["n"] > 1:
            task.cancel()
        try:
            await task
        except RunnerStopped:
            LOGGER.info(f"runner {key}: stopped")
            return 0
        except asyncio.CancelledError:
            LOGGER.warning(f"runner {key}: forced stop")
            return 130
        except BaseExceptionGroup as eg:  # a stop raised inside a TaskGroup
            if eg.split(RunnerStopped)[1] is None:
                LOGGER.info(f"runner {key}: stopped")
                return 0
            LOGGER.exception(f"runner {key} failed")
            return 1
        except Exception:
            LOGGER.exception(f"runner {key} failed")
            return 1
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="helao.core.runners.launch")
    ap.add_argument("--describe", metavar="MODULE")
    ap.add_argument("config", nargs="?")
    ap.add_argument("module", nargs="?")
    ap.add_argument("--key")
    ap.add_argument("--params", default="{}")
    ap.add_argument("--host")
    args = ap.parse_args(argv)

    if args.describe:
        try:
            print(json.dumps(describe(args.describe), default=str))
            return 0
        except Exception as exc:
            out = {"module": args.describe, "error": f"{type(exc).__name__}: {exc}"}
            if isinstance(exc, NotRunner):
                out["not_runner"] = True
            print(json.dumps(out))
            return 1

    if not (args.config and args.module):
        ap.print_usage(sys.stderr)
        return 2
    from helao.helpers.config_loader import read_config
    from helao.helpers.parent_death import arm_parent_death_signal

    arm_parent_death_signal()
    try:
        # ponytail: read_config itself raises bare Exception (config_loader l.109/123)
        # besides FileNotFoundError and YAML errors, so this call alone is caught broadly.
        world_cfg = read_config(args.config)
    except Exception as exc:
        print(f"usage error: config: {exc}", file=sys.stderr)
        return 2
    key = args.key or default_key(args.module)
    if key in (world_cfg.get("servers") or {}):
        print(
            f"usage error: key {key!r} is a server key in the config", file=sys.stderr
        )
        return 2
    try:
        mod = importlib.import_module(args.module)
    except Exception:
        LOGGER.exception(f"runner module {args.module} failed to import")
        return 1
    try:
        fn, _ = _run_func(mod)
        raw = json.loads(args.params)
        if not isinstance(raw, dict):
            raise ValueError("--params must be a JSON object")
        params = coerce(raw, inspect.signature(fn))
        inspect.signature(fn).bind(None, **params)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return 2
    host = args.host or _reflex_host(world_cfg)
    return asyncio.run(_run(fn, world_cfg, key, params, host))


if __name__ == "__main__":
    sys.exit(main())
