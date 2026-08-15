"""The ``test`` deployment must not reach the legacy engine (B4).

B4's stated scope was "9 action + 4 visualizer modules onto the new API".
Measured when it came up, most of that was already done: B1 ported all
nine action modules to ``ActionHost``, and B0 re-homed the UI stack to
``helao/ui/``, which is engine-free. What actually remained was two
DRIVER files importing ``Base``/``Active`` -- for type annotations only,
and annotations that had become wrong: ``ActionHost`` constructs these
drivers (``driver_class(self)``) and hands them an ``ActionSession``.

So the deliverable is this invariant rather than a port: the deployment
reaches ``helao/core/servers`` nowhere. It is worth a test because the
imports it forbids are the cheapest thing in the world to add back --
an annotation, a convenience import, an editor autocomplete -- and each
one silently re-binds a ported deployment to the engine B7 has to delete.

Scope note: ``helao/core`` at large is NOT forbidden. Models, drivers,
error codes and helpers under it are shared framework and stay. Only
``helao/core/servers`` -- the engine -- is out of bounds.
"""

import ast
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEPLOYMENT: Final[Path] = REPO_ROOT / "helao/deploy/test"

#: The engine package a ported deployment must not import, at runtime or
#: under TYPE_CHECKING. A typing-only import still names the class, and the
#: name is what B7 deletes.
FORBIDDEN: Final[str] = "helao.core.servers"


def _imports(path: Path) -> set[str]:
    """Every module this file imports, by dotted name."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _deployment_files() -> list[Path]:
    return sorted(p for p in DEPLOYMENT.rglob("*.py") if "__pycache__" not in p.parts)


def test_the_sweep_actually_sees_the_deployment() -> None:
    """A wrong root would make the assertion below pass over nothing."""
    files = _deployment_files()
    assert len(files) > 20, f"only {len(files)} files found under {DEPLOYMENT}"
    names = {p.name for p in files}
    for known in ("ws_simulator.py", "sim_db_server.py", "gpsim_driver.py"):
        assert known in names, f"{known} missing -- is the root right?"


def test_no_module_reaches_the_legacy_engine() -> None:
    offenders = {
        str(path.relative_to(REPO_ROOT)): sorted(
            m for m in _imports(path) if m.startswith(FORBIDDEN)
        )
        for path in _deployment_files()
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert offenders == {}, (
        f"the test deployment imports {FORBIDDEN} in {len(offenders)} file(s): "
        f"{offenders}\nA typing-only import counts: it still names a class B7 "
        "deletes, and it binds a ported deployment to the engine for nothing."
    )


def test_every_action_module_builds_on_the_native_host() -> None:
    """The positive half: not merely 'no legacy', but 'yes native'."""
    action_dir = DEPLOYMENT / "servers/action"
    modules = [p for p in sorted(action_dir.glob("*.py")) if p.name != "__init__.py"]
    assert len(modules) == 9, f"expected 9 action modules, found {len(modules)}"
    for path in modules:
        # Imported NAMES, not raw text. A grep over source also matches
        # prose, and the first run of this test failed on a docstring that
        # said "BaseAPI" in a module which builds an ActionHost -- a stale
        # sentence reported as an unported module.
        imported: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                imported.update(alias.name for alias in node.names)
        assert "ActionHost" in imported, f"{path.name} does not import ActionHost"
        assert "BaseAPI" not in imported, f"{path.name} still imports BaseAPI"
