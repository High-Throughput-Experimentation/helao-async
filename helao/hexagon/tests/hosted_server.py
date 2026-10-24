"""Shared helper: start an hte action server under its station config, connect raising.

Used by the per-server "disconnected-server" tests. It loads the real station config
but points ``root`` at ``tmp_path``, so no run, state, log or database file lands on a
station path. The driver class's ``connect`` is made to raise; the host must catch it,
log ERROR and alert, and still serve.
"""

import importlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import pytest
from fastapi.testclient import TestClient

from helao.helpers import config_loader


@dataclass
class Started:
    startup_errors: list = field(default_factory=list)
    get_status_code: Optional[int] = None
    route_paths: set = field(default_factory=set)
    app: object = None
    probe: Any = None


def start_with_raising_connect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    *,
    module: str,
    prefix: str,
    server_key: str,
    driver_class: type,
    ready: Optional[Callable[[Any], bool]] = None,
    probe: Optional[Callable[[Any], Any]] = None,
    wait_s: float = 5.0,
) -> Started:
    """Run startup with ``driver_class.connect`` raising; return what was observed.

    ``ready(app)`` says when the late routes are in; the default waits for the first
    route added after construction, so ``dyn_endpoints`` has run. ``probe(app)`` is
    evaluated once, before shutdown, and returned as ``Started.probe``.
    """
    from helao.hexagon.app import action_host

    cfg = config_loader.read_config(prefix)
    cfg["root"] = str(tmp_path)
    (tmp_path / "LOGS").mkdir(exist_ok=True)
    monkeypatch.setattr(config_loader, "CONFIG", cfg)

    def _raise(self):
        raise OSError("no device")

    monkeypatch.setattr(driver_class, "connect", _raise)
    mod = importlib.import_module(f"helao.deploy.hte.servers.action.{module}")
    app = mod.makeApp(server_key)
    before = {getattr(r, "path", None) for r in app.routes}

    lg = action_host.LOGGER
    old_level = lg.level
    lg.setLevel(logging.DEBUG)
    lg.addHandler(caplog.handler)
    out = Started(app=app)
    try:
        with TestClient(app) as client:
            end = time.time() + wait_s
            while time.time() < end:
                now = {getattr(r, "path", None) for r in app.routes}
                if ready(app) if ready else now != before:
                    break
                time.sleep(0.05)
            out.get_status_code = client.post("/get_status").status_code
            out.route_paths = {getattr(r, "path", None) for r in app.routes}
            if probe is not None:
                out.probe = probe(app)  # while the app is still running
    finally:
        lg.removeHandler(caplog.handler)
        lg.setLevel(old_level)
    out.startup_errors = [
        r
        for r in caplog.records
        if "connect() at startup raised" in r.getMessage()
        and r.levelno == logging.ERROR
    ]
    return out
