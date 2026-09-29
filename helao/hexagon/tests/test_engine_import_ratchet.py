"""Nothing outside the legacy engine imports it (B7a, spec section 6).

``helao/core/servers/`` is the engine B7b deletes. B7a moved every symbol
native code still borrowed from it to one home outside it; this ratchet keeps
it that way and is the first test B7b runs.

Static half. Every tracked ``.py`` outside the engine and outside tests is
parsed, and any ``import``/``from`` that names ``helao.core.servers`` -- at
module top, in a function body, or under ``TYPE_CHECKING`` -- is an offender.
Three files may keep importing it, and only until B7b deletes them: the graft
machinery and the harness encoder that produces the legacy bytes the parity
tests compare against. The allowlist is shrink-only: an entry that stops
importing the engine fails, so B7b cannot leave a stale one behind.

Runtime half. A fresh interpreter constructs an ``ActionHost`` and an
``OrchHost`` under the ``goldenhex`` server entries and must end with no
``helao.core.servers`` module loaded. A subprocess, because this pytest
process may already hold the engine through other imports. On 415c0bb2 the
import-time count was 2 and the construction-time count 17: a helper that
imports the engine lazily is an importer even when no static read of the
hosts finds it.

The route-class tests pin D-B7a.4. ``HelaoFastAPI`` no longer installs
``ActionAPIRoute``, so each host installs its own route class before its first
route, and every ``APIRoute`` a host holds must be of that class. A route
registered before the install would be a plain ``APIRoute`` and would lose its
action wrapping without any other test noticing.
"""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
ENGINE: Final[str] = "helao.core.servers"
CONFIG: Final[Path] = REPO_ROOT / "helao/deploy/test/configs/goldenhex.yml"

#: B7b's files, and nothing else: B7b deletes the graft (active_graft.py,
#: factory.py's makeOrchApp) and re-baselines the harness (ws_frames.py).
ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "harness/ws_frames.py",
        "helao/hexagon/app/active_graft.py",
        "helao/hexagon/app/factory.py",
    }
)


def _is_engine(name: str) -> bool:
    return name == ENGINE or name.startswith(ENGINE + ".")


def _is_test_file(rel: str) -> bool:
    parts = rel.split("/")
    return "tests" in parts[:-1] or parts[-1].startswith(("test_", "unit_test_"))


def swept_files() -> list[str]:
    """Tracked ``.py`` files outside the engine and outside tests."""
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(
        rel
        for rel in out.split("\0")
        if rel and not rel.startswith("helao/core/servers/") and not _is_test_file(rel)
        # Tracked but deleted in the working tree and not yet committed.
        and (REPO_ROOT / rel).exists()
    )


def engine_imports(source: str, rel: str) -> list[str]:
    """``rel:lineno`` of every import in ``source`` that names the engine.

    Relative imports are resolved against ``rel``'s package, and
    ``from helao.core import servers`` counts, so neither spelling hides one.
    """
    package = rel[: -len(".py")].split("/")[:-1]
    found = []
    for node in ast.walk(ast.parse(source, filename=rel)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            names = [module] + [f"{module}.{alias.name}" for alias in node.names]
        else:
            continue
        if any(_is_engine(name) for name in names):
            found.append(f"{rel}:{node.lineno}")
    return found


def offenders() -> dict[str, list[str]]:
    """``{file: [site, ...]}`` for every swept file that imports the engine."""
    result = {}
    for rel in swept_files():
        sites = engine_imports((REPO_ROOT / rel).read_text(encoding="utf-8"), rel)
        if sites:
            result[rel] = sites
    return result


def test_the_detector_sees_every_spelling() -> None:
    """A detector that misses a spelling makes the sweep pass for free."""
    rel = "helao/hexagon/app/x.py"
    for source in (
        "import helao.core.servers.orch",
        "from helao.core.servers.orch import move_dir",
        "from helao.core.servers import orch_unpack",
        "from helao.core import servers",
        "def f():\n    from helao.core.servers.base import Active",
        "if TYPE_CHECKING:\n    from helao.core.servers.base import Active",
    ):
        assert engine_imports(source, rel), f"missed: {source!r}"
    assert engine_imports("from ...core.servers import orch", rel)
    assert not engine_imports("from helao.core.models import status_transitions", rel)
    assert not engine_imports("import helao.core.serversx", rel)


def test_the_sweep_is_not_vacuous() -> None:
    files = swept_files()
    assert len(files) > 500, f"swept only {len(files)} files"


def test_every_allowlisted_file_still_imports_the_engine() -> None:
    """Shrink-only: an entry whose file stopped importing the engine is stale."""
    found = offenders()
    stale = sorted(rel for rel in ALLOWLIST if rel not in found)
    assert (
        stale == []
    ), f"delete these from ALLOWLIST, they no longer import it: {stale}"


def test_nothing_outside_the_engine_imports_it() -> None:
    extra = {rel: sites for rel, sites in offenders().items() if rel not in ALLOWLIST}
    assert extra == {}, f"engine imports outside helao/core/servers/: {extra}"


_PROBE: Final[str] = r"""
import json, sys, tempfile
import yaml
from fastapi.routing import APIRoute
from helao.helpers import config_loader

cfg = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
cfg["root"] = tempfile.mkdtemp(prefix="b7a_ratchet_")
config_loader.CONFIG = cfg
if sys.argv[2] == "native":
    from helao.hexagon.app.action_host import ActionHost
    from helao.hexagon.app.orch_host import OrchHost

    hosts = {
        "ActionHost": ActionHost("SIM", "SIM", "ratchet", 1.0, helao_cfg=cfg),
        "OrchHost": OrchHost("ORCH", "ORCH", "ratchet", version=3.0, helao_cfg=cfg),
    }
else:
    from helao.core.servers.base_api import BaseAPI
    from helao.core.servers.orch_api import OrchAPI

    hosts = {
        "BaseAPI": BaseAPI("SIM", "SIM", "ratchet", 1.0),
        "OrchAPI": OrchAPI("ORCH", "ORCH", "ratchet", 3.0),
    }
report = {
    "engine_modules": sorted(
        m for m in sys.modules
        if m == "helao.core.servers" or m.startswith("helao.core.servers.")
    ),
    "hosts": {},
}
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


def _probe(mode: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(CONFIG), mode],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=180,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("B7A-PROBE ")]
    assert (
        proc.returncode == 0 and len(lines) == 1
    ), f"{mode} probe failed (rc={proc.returncode}):\n{proc.stderr[-4000:]}"
    return json.loads(lines[0][len("B7A-PROBE ") :])


@pytest.fixture(scope="module")
def native() -> dict:
    return _probe("native")


@pytest.fixture(scope="module")
def legacy() -> dict:
    return _probe("legacy")


def test_the_native_hosts_construct_without_the_engine(native) -> None:
    assert native["engine_modules"] == []


def test_every_native_route_is_built_by_the_host_bound_class(native) -> None:
    for name, host in native["hosts"].items():
        assert host["installed"] == "helao.hexagon.app.action_route.BoundActionRoute", (
            name,
            host["installed"],
        )
        assert host["api_routes"] > 0 and host["wrong_class"] == [], (name, host)


def test_every_legacy_route_is_built_by_action_api_route(legacy) -> None:
    for name, host in legacy["hosts"].items():
        assert host["installed"] == "helao.core.servers.base_api.ActionAPIRoute", (
            name,
            host["installed"],
        )
        assert host["api_routes"] > 0 and host["wrong_class"] == [], (name, host)
