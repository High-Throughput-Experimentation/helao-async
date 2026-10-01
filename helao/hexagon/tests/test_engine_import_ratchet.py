"""Nothing outside the legacy engine imports it (B7a, spec section 6).

``helao/core/servers/`` is the engine B7b deletes. B7a moved every symbol
native code still borrowed from it to one home outside it; this ratchet keeps
it that way and is the first test B7b runs.

Static half. Every tracked ``.py`` outside the engine, tests included, is
parsed, and any ``import``/``from`` that names ``helao.core.servers`` -- at
module top, in a function body, or under ``TYPE_CHECKING`` -- is an offender.
There is no allowlist: B7b deleted the graft machinery and re-pointed the
harness encoder, the last three files B7a allowed.

Runtime half. A fresh interpreter constructs an ``ActionHost``, an
``OrchHost`` and a ``makeActionApp`` composition under the ``goldenhex``
server entries and must end with no ``helao.core.servers`` module loaded. A
subprocess, because this pytest process may already hold the engine through
other imports. On 415c0bb2 the import-time count was 2 and the
construction-time count 17; on e60d800a ``makeActionApp`` alone still loaded
12, through its unconditional ``active_graft`` import. A helper that imports
the engine lazily is an importer even when no static read of the hosts finds
it.

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


def _is_engine(name: str) -> bool:
    return name == ENGINE or name.startswith(ENGINE + ".")


def swept_files() -> list[str]:
    """Tracked ``.py`` files outside the engine, tests included."""
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
        if rel and not rel.startswith("helao/core/servers/")
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


def test_nothing_outside_the_engine_imports_it() -> None:
    found = offenders()
    assert found == {}, f"engine imports outside helao/core/servers/: {found}"


_PROBE: Final[str] = r"""
import json, sys, tempfile
import yaml
from fastapi.routing import APIRoute
from helao.helpers import config_loader

cfg = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
cfg["root"] = tempfile.mkdtemp(prefix="b7a_ratchet_")
config_loader.CONFIG = cfg
from helao.hexagon.app.action_host import ActionHost
from helao.hexagon.app.factory import makeActionApp
from helao.hexagon.app.orch_host import OrchHost

hosts = {
    "ActionHost": ActionHost("SIM", "SIM", "ratchet", 1.0, helao_cfg=cfg),
    "OrchHost": OrchHost("ORCH", "ORCH", "ratchet", version=3.0, helao_cfg=cfg),
    # B7b: the composition every `deployment: hexagon` action server is
    # built through. Until B7b it imported active_graft, and with it
    # twelve engine modules, though no target needed the graft.
    "makeActionApp": makeActionApp(
        "SIM", "helao.deploy.test.servers.action.ws_simulator"
    ),
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


def test_the_native_hosts_construct_without_the_engine(native) -> None:
    assert native["engine_modules"] == []


def test_every_native_route_is_built_by_the_host_bound_class(native) -> None:
    for name, host in native["hosts"].items():
        assert host["installed"] == "helao.hexagon.app.action_route.BoundActionRoute", (
            name,
            host["installed"],
        )
        assert host["api_routes"] > 0 and host["wrong_class"] == [], (name, host)


_GONE_PROBE: Final[str] = r"""
import importlib.util, json
spec = importlib.util.find_spec("helao.core.servers")
try:
    import helao.core.servers.base  # noqa: F401
    base = "imported"
except ModuleNotFoundError:
    base = "ModuleNotFoundError"
where = None if spec is None else sorted(spec.submodule_search_locations or [spec.origin])
print("B7B-GONE " + json.dumps({"spec": where, "base": base}))
"""


def test_the_engine_package_cannot_be_imported() -> None:
    """D-B7b.9: B7b deleted ``helao/core/servers/``, and it must stay unimportable.

    ``helao/core/`` has no ``__init__.py`` and ``__pycache__`` is gitignored, so
    a ``git pull`` that deletes the tracked files leaves the directory behind
    on every checkout that ever ran the engine. While it exists,
    ``import helao.core.servers`` succeeds as a namespace package. Nothing
    imports it, so at runtime that is harmless, but it is exactly the silent
    import this ratchet exists to rule out. A fresh interpreter, because this
    pytest process may have imported anything.
    """
    proc = subprocess.run(
        [sys.executable, "-c", _GONE_PROBE],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("B7B-GONE ")]
    assert (
        proc.returncode == 0 and len(lines) == 1
    ), f"probe failed (rc={proc.returncode}):\n{proc.stderr[-4000:]}"
    report = json.loads(lines[0][len("B7B-GONE ") :])
    assert report["spec"] is None, (
        f"helao.core.servers still resolves, to {report['spec']}. The engine's "
        "tracked files are gone, but git leaves the untracked __pycache__ "
        "directory behind, and a leftover helao/core/servers/ imports as a "
        "namespace package. Remove it once in this checkout, from the repo "
        "root: `rm -rf helao/core/servers` (Linux) or "
        "`rmdir /s /q helao\\core\\servers` (Windows cmd)."
    )
    assert report["base"] == "ModuleNotFoundError", report
