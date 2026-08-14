"""Boundary gate on ``helao/ui/``: the UI layer may not import the legacy engine.

B0 moves the UI out of ``helao/core/servers/`` so that B1-B6 can replace the
engine underneath it. This test is what stops a port quietly reaching back into
legacy hosting from UI code -- an edge that would otherwise stay invisible until
B7 tried to delete ``helao/core/servers/``.

AST-walked rather than grepped, so a dynamic
``import_module("helao.core.servers...")`` is caught too: the Reflex stack
resolves panel modules from config strings, which a grep for ``from`` would miss
entirely.
"""

import ast
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
UI_ROOT: Final[Path] = REPO_ROOT / "helao" / "ui"

#: Raised to the real module count by later B0 tasks. Its only job is to make an
#: empty or mis-rooted glob fail loudly instead of passing by reaching nothing.
MIN_UI_MODULES: Final[int] = 6

BANNED_PREFIX: Final[str] = "helao.core.servers"


def _ui_modules() -> list[Path]:
    return sorted(p for p in UI_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


def _imported_names(tree: ast.AST) -> list[str]:
    """Every module name this AST references, statically or dynamically."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None and node.level == 0:
                names.append(node.module)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # dynamic import targets and config-resolved module strings
            if node.value.startswith(BANNED_PREFIX):
                names.append(node.value)
    return names


def test_ui_tree_exists_and_is_not_empty() -> None:
    """Vacuity guard: an empty glob would make the boundary test pass for free."""
    assert UI_ROOT.is_dir(), f"{UI_ROOT} does not exist"
    modules = _ui_modules()
    assert len(modules) >= MIN_UI_MODULES, (
        f"only {len(modules)} modules under helao/ui/; expected at least "
        f"{MIN_UI_MODULES}. A mis-rooted glob passes the boundary test by "
        f"reaching nothing."
    )


def test_ui_does_not_import_the_legacy_engine() -> None:
    offenders: list[str] = []
    for path in _ui_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _imported_names(tree):
            if name == BANNED_PREFIX or name.startswith(BANNED_PREFIX + "."):
                offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {name}")
    assert offenders == [], (
        "helao/ui/ must not import helao.core.servers -- the UI layer is being "
        "separated from the legacy engine that B7 deletes:\n  " + "\n  ".join(offenders)
    )
