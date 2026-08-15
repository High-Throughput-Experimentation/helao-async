"""The hte deployment's march off the legacy engine (B5).

B4 gave the ``test`` deployment an absolute invariant -- it imports
``helao.core.servers`` nowhere -- because all nine of its modules were already
ported when the test was written. hte is 23 modules ported across six batches
with station gates between them, so an absolute test could only be added at
the very end and would police nothing in between.

This is a ratchet instead. ``NOT_YET_PORTED`` may only SHRINK: a module removed
from it must never import the engine again, and a module still in it is
expected to. The list doubles as the phase's progress record, and B5's final
commit empties it -- at which point this file asserts exactly what B4's does.

Scope note, inherited from B4: ``helao/core`` at large is not forbidden. Models,
drivers, error codes and helpers under it are shared framework and stay. Only
``helao/core/servers`` -- the engine -- is out of bounds.
"""

import ast
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
ACTION_DIR: Final[Path] = REPO_ROOT / "helao/deploy/hte/servers/action"

#: The engine package a ported module must not import, at runtime or under
#: TYPE_CHECKING. A typing-only import still names the class, and the name is
#: what B7 deletes.
FORBIDDEN: Final[str] = "helao.core.servers"

#: Modules that have NOT yet been ported. Remove a name when its module lands;
#: never add one back. Seeded with all 23 at B5's start, emptied by B5.6 --
#: kept rather than deleted so a later phase adding an hte action server has
#: somewhere to declare it, and so the tests below keep their shape.
NOT_YET_PORTED: Final[frozenset[str]] = frozenset()


def _modules() -> list[Path]:
    return sorted(p for p in ACTION_DIR.glob("*.py") if p.name != "__init__.py")


def _imports(path: Path) -> set[str]:
    """Every module this file imports, by dotted name."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _names(path: Path) -> set[str]:
    """Every name imported FROM somewhere -- AST, so prose never matches.

    Grepping source for "BaseAPI" matched a docstring twice during B3 and B4
    and reported a ported module as unported both times.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            found.update(alias.name for alias in node.names)
    return found


def test_the_sweep_sees_every_module() -> None:
    """A wrong ACTION_DIR would make every assertion below pass over nothing."""
    modules = _modules()
    assert len(modules) == 23, f"found {len(modules)} modules under {ACTION_DIR}"


def test_ported_modules_reach_the_engine_nowhere() -> None:
    offenders = {}
    for path in _modules():
        if path.stem in NOT_YET_PORTED:
            continue
        bad = sorted(m for m in _imports(path) if m.startswith(FORBIDDEN))
        if bad:
            offenders[path.name] = bad
    assert offenders == {}, (
        f"ported hte modules re-acquired {FORBIDDEN}: {offenders}\n"
        "A typing-only import counts: it still names a class B7 deletes."
    )


def test_ported_modules_build_on_the_native_host() -> None:
    """The positive half: not merely 'no BaseAPI', but 'yes ActionHost'."""
    offenders = {}
    for path in _modules():
        if path.stem in NOT_YET_PORTED:
            continue
        names = _names(path)
        if "ActionHost" not in names or "BaseAPI" in names:
            offenders[path.name] = sorted(names & {"ActionHost", "BaseAPI"})
    assert offenders == {}, f"ported modules not on ActionHost: {offenders}"


def test_unported_modules_really_are_unported() -> None:
    """The ratchet's other direction.

    A name left in the list after its module was ported is an exemption that
    silently stops policing it -- and B5's last commit, which empties the list,
    would then be the first thing to notice. Cheaper to notice per batch.
    """
    stale = sorted(
        p.stem
        for p in _modules()
        if p.stem in NOT_YET_PORTED
        and not any(m.startswith(FORBIDDEN) for m in _imports(p))
    )
    assert stale == [], (
        f"these modules no longer import {FORBIDDEN} but are still listed as "
        f"NOT_YET_PORTED: {stale}. Remove them from the list."
    )


def test_the_ratchet_only_names_modules_that_exist() -> None:
    """A typo'd entry would exempt nothing and hide a real module."""
    stems = {p.stem for p in _modules()}
    unknown = sorted(NOT_YET_PORTED - stems)
    assert unknown == [], f"NOT_YET_PORTED names modules that do not exist: {unknown}"


def test_the_ratchet_is_empty_and_b5_is_done() -> None:
    """B5's terminal assertion. Once this passes the file says what B4's says."""
    assert NOT_YET_PORTED == frozenset(), (
        f"{len(NOT_YET_PORTED)} hte module(s) still on the legacy engine: "
        f"{sorted(NOT_YET_PORTED)}"
    )


def test_the_whole_deployment_reaches_the_engine_nowhere() -> None:
    """Wider than the action directory: drivers, orchestrator, tests, all of it.

    The per-module ratchet above policed ``servers/action/`` because that is
    where the 23 modules were. B5 also retyped ``drivers/data/archive_driver``
    and moved the orchestrator entrypoint onto OrchHost, and neither lives
    under that directory -- so this is the assertion that actually says the
    deployment is done.
    """
    deployment = REPO_ROOT / "helao/deploy/hte"
    offenders = {}
    for path in sorted(deployment.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        bad = sorted(m for m in _imports(path) if m.startswith(FORBIDDEN))
        if bad:
            offenders[str(path.relative_to(REPO_ROOT))] = bad
    assert offenders == {}, f"hte imports {FORBIDDEN} in: {offenders}"


def test_the_wide_sweep_is_not_vacuous() -> None:
    """The sweep above passes trivially if it walks an empty tree."""
    deployment = REPO_ROOT / "helao/deploy/hte"
    files = [p for p in deployment.rglob("*.py") if "__pycache__" not in p.parts]
    assert len(files) > 100, f"only {len(files)} files under {deployment}"
