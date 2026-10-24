"""Every native host installs its own route class (D-B7a.4).

``HelaoFastAPI`` no longer installs ``ActionAPIRoute``, so each host installs its
own route class before its first route, and every ``APIRoute`` a host holds must
be of that class. A route registered before the install would be a plain
``APIRoute`` and would lose its action wrapping without any other test noticing.
A subprocess builds the hosts, because this pytest process may have imported
anything.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG: Final[Path] = REPO_ROOT / "helao/deploy/test/configs/goldenhex.yml"


_PROBE: Final[str] = r"""
import json, sys, tempfile
import yaml
from fastapi.routing import APIRoute
from helao.helpers import config_loader

cfg = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
cfg["root"] = tempfile.mkdtemp(prefix="b7a_ratchet_")
config_loader.CONFIG = cfg
from helao.hexagon.app.action_host import ActionHost
from helao.deploy.test.servers.action.ws_simulator import makeApp
from helao.hexagon.app.orch_host import OrchHost

hosts = {
    "ActionHost": ActionHost("SIM", "SIM", "ratchet", 1.0, helao_cfg=cfg),
    "OrchHost": OrchHost("ORCH", "ORCH", "ratchet", version=3.0, helao_cfg=cfg),
    # An action server module's own makeApp.
    "ws_simulator makeApp": makeApp("SIM"),
}
report = {"hosts": {}}
for name, host in hosts.items():
    installed = host.router.route_class
    api_routes = [r for r in host.routes if isinstance(r, APIRoute)]
    report["hosts"][name] = {
        "installed": installed.__module__ + "." + installed.__name__,
        "api_routes": len(api_routes),
        "wrong_class": sorted(r.path for r in api_routes if type(r) is not installed),
    }
print("B7A-PROBE " + json.dumps(report))
"""


def _probe() -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(CONFIG)],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=180,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("B7A-PROBE ")]
    assert (
        proc.returncode == 0 and len(lines) == 1
    ), f"native probe failed (rc={proc.returncode}):\n{proc.stderr[-4000:]}"
    return json.loads(lines[0][len("B7A-PROBE ") :])


@pytest.fixture(scope="module")
def native() -> dict:
    return _probe()


def test_every_native_route_is_built_by_the_host_bound_class(native) -> None:
    for name, host in native["hosts"].items():
        assert host["installed"] == "helao.hexagon.app.action_route.BoundActionRoute", (
            name,
            host["installed"],
        )
        assert host["api_routes"] > 0 and host["wrong_class"] == [], (name, host)
