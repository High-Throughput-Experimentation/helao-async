"""What a deployment outside this repo may depend on, pinned here (B6.1).

Two gates, both prompted by one incident. B5 moved hte's action modules onto
``ActionHost``: ``gamry_dyn_endpoints`` started reading ``app.server`` instead
of ``app.base.server`` and registering through ``@app.action()`` instead of
``@app.post(...)``. Every gate in this repo stayed green. A private deployment
that composes that exact registrar through ``overlay_dyn_endpoints`` went red,
because its stub app carried the pre-B5 shape.

Nothing here could see it. The B4/B5 ratchets sweep `helao/deploy/test` and
`helao/deploy/hte`; the route checklists read source in this repo; the build
probe constructs apps from this repo's configs. The consumer was a repository
this repo never walks, reaching through a registrar this repo owns.

**Neither test names a deployment.** This repo is a public remote. The first
walks whatever `helao/deploy/*` directories happen to be present and skips the
ones git tracks, so it works on a checkout that has no private deployments at
all — and reports what it found by path only when something is actually wrong.
The second is about a parent-repo function's own contract and needs no
knowledge of who consumes it.
"""

import ast
import subprocess
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEPLOY: Final[Path] = REPO_ROOT / "helao/deploy"
FORBIDDEN: Final[str] = "helao.core.servers"

#: Ceiling on how many action modules across the *untracked* deployments still
#: import the engine. **May only shrink.** A count rather than a list because a
#: list would have to name them.
#:
#: 13 at B6's start. **Not 0 yet, and that was a mistake worth recording.** It
#: was set to 0 the moment B6's ports were committed -- but they were committed
#: to feature BRANCHES, and this count reads whatever the sibling repositories
#: happen to have checked out. Anyone on their `main`, which is every fresh
#: clone until those branches merge, measured 13 against a ceiling of 0 and got
#: a red suite for work that was perfectly fine.
#:
#: So the ceiling tracks what is merged to the siblings' `main`, not what has
#: been written somewhere. Drop it to 0 when B6 merges there, and this becomes
#: the absolute invariant B7 needs: nothing outside `helao/core/servers/`
#: constructs the engine, so the engine can be deleted.
#:
#: The count is deliberately not pinned to the live measurement for the same
#: underlying reason -- three repositories this one neither controls nor can
#: see. A checkout carrying none of them measures 0 and passes, which is the
#: right answer for a different reason: the gate is "no NEW engine coupling",
#: not "the deployments are here".
MAX_UNPORTED_PRIVATE_MODULES: Final[int] = 13


def _tracked(path: Path) -> bool:
    """True when git tracks this directory in THIS repo.

    A nested private repository is untracked here even though it is a git
    repository itself, which is exactly the distinction the sweep needs.
    """
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(path.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    return result.returncode == 0


def _external_deployments() -> list[Path]:
    if not DEPLOY.is_dir():
        return []
    return [
        d
        for d in sorted(DEPLOY.iterdir())
        if d.is_dir() and d.name != "__pycache__" and not _tracked(d)
    ]


def _imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def test_external_deployments_do_not_gain_engine_coupling() -> None:
    """The B4/B5 ratchet, generalised past the repo boundary.

    ``notes/`` is excluded everywhere: it holds working material rather than
    anything a station launches, and sweeping it produces findings nobody acts
    on.
    """
    offenders = []
    for deployment in _external_deployments():
        action_dir = deployment / "servers/action"
        if not action_dir.is_dir():
            continue
        for module in sorted(action_dir.glob("*.py")):
            if module.name == "__init__.py" or "notes" in module.parts:
                continue
            if any(m.startswith(FORBIDDEN) for m in _imports(module)):
                offenders.append(str(module.relative_to(REPO_ROOT)))

    assert len(offenders) <= MAX_UNPORTED_PRIVATE_MODULES, (
        f"{len(offenders)} action modules outside this repo import {FORBIDDEN}, "
        f"above the ceiling of {MAX_UNPORTED_PRIVATE_MODULES}. Lower the ceiling "
        f"when porting; never raise it.\n{offenders}"
    )


def test_the_sweep_is_not_vacuous() -> None:
    """The ratchet above must actually be walking modules, not an empty set.

    This asserted ``coupled == MAX_UNPORTED_PRIVATE_MODULES`` in its first
    form, to stop the ceiling drifting far above the truth. That was wrong, and
    the test caught itself: the measurement depends on which BRANCH each of
    three separate repositories happens to have checked out, so pinning it made
    this repo's suite go red whenever a sibling repo was mid-port -- which is
    exactly when it is most useful for the suite to be green. A ceiling is a
    ceiling; equality is somebody else's business.

    What is worth asserting is that the sweep found real files to read. A
    ratchet over nothing passes forever.
    """
    deployments = _external_deployments()
    if not deployments:
        pytest.skip("no external deployments on this checkout")

    modules = 0
    for deployment in deployments:
        action_dir = deployment / "servers/action"
        if not action_dir.is_dir():
            continue
        modules += sum(1 for m in action_dir.glob("*.py") if m.name != "__init__.py")

    assert modules > 0, (
        f"{len(deployments)} external deployment(s) present but the sweep found "
        "no action modules -- the ratchet is passing over nothing."
    )


# ---------------------------------------------------------------------------
# The registrar contract
# ---------------------------------------------------------------------------

#: Every ``app.<attr>`` an hte ``*_dyn_endpoints`` registrar reads, by module.
#: These functions are exported, and at least one is composed by a deployment
#: outside this repo (through ``overlay_dyn_endpoints``), so the attribute set
#: is a published interface: a consumer stubs exactly these.
#:
#: Changing one is allowed. Changing one *silently* is what B5 did, and what
#: cost a private repo a red suite that nothing here reported. Update the entry
#: in the same commit, and treat the diff as the list of consumers to warn.
REGISTRAR_CONTRACT: Final[dict[str, set[str]]] = {
    "gamry_server2": {
        "action",
        "driver",
        "executors",
        "post",
        "server",
        "server_params",
        "stop_executor",
    },
}


def _registrar_reads(module_stem: str) -> set[str]:
    path = REPO_ROOT / f"helao/deploy/hte/servers/action/{module_stem}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.endswith("dyn_endpoints")
        ),
        None,
    )
    assert fn is not None, f"{module_stem} exports no *_dyn_endpoints registrar"
    return {
        node.attr
        for node in ast.walk(fn)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "app"
    }


@pytest.mark.parametrize("module_stem", sorted(REGISTRAR_CONTRACT))
def test_registrar_reads_exactly_the_pinned_attributes(module_stem: str) -> None:
    expected = REGISTRAR_CONTRACT[module_stem]
    actual = _registrar_reads(module_stem)
    assert actual == expected, (
        f"{module_stem}'s registrar now reads {sorted(actual)}, pinned as "
        f"{sorted(expected)}. This function is composed by a deployment outside "
        "this repo, which stubs exactly this set -- added: "
        f"{sorted(actual - expected)}, removed: {sorted(expected - actual)}."
    )


def test_the_contract_probe_is_not_vacuous() -> None:
    """A typo'd module stem would make the pin above assert over nothing."""
    for stem in REGISTRAR_CONTRACT:
        assert (
            REPO_ROOT / f"helao/deploy/hte/servers/action/{stem}.py"
        ).exists(), f"{stem} is pinned but has no module"
        assert _registrar_reads(stem), f"{stem}'s registrar reads no app attributes"
