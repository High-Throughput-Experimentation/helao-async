"""The hte station canaries no longer compare against legacy (B5).

`helao/hexagon/tests/smoke/` holds 19 per-hardware-family station canaries,
each a config pair: `<family>.yml` carrying `deployment: hte` and
`<family>hex.yml` carrying `deployment: hexagon`, plus a `<family>gold` pair
for the runtime golden diff. They were built for P3a to prove, at a station,
that the hexagon composition produced the same routes and the same run tree as
the legacy one.

**B5 ends that.** The `hte` side imports
`helao.deploy.hte.servers.action.<fast>` and calls its `makeApp`. The `hexagon`
side goes through `helao/deploy/hexagon/servers/action/<fast>.py`, whose
`LEGACY_MODULE` names *that same module*, and `makeActionApp` calls the same
`makeApp` before skipping the write graft (which is a no-op on a native host).
Once B5 ported those 23 modules to `ActionHost`, **both sides run identical
code**. Measured 2026-08-15: 29 of the 31 config pairs build an `ActionHost` on
both sides; the two remaining are the biologic pair, which raises the same
Windows-only import error on both sides off-station and would be a self-
comparison at hispec too.

Why this is a test and not a note. A station report saying `co2_diff.bat PASS`
reads as evidence the port preserved behaviour. On this branch it is evidence
of nothing -- the diff compared a native host against itself and could not have
failed. That is a conclusion someone will draw from a green run unless
something states otherwise at the point of contact, and these canaries are the
obvious thing to reach for at a station.

What replaces them for B5's station gate: capture the station's run tree with
`unstable` checked out (where hte's modules still build a legacy `BaseAPI`),
then again on this branch, and diff those two. The reference is a git revision
now, not a config key. See
`docs/superpowers/notes/2026-08-15-B5-station-gate-runbook.md`.

This test fails if someone restores a genuine legacy reference to a pair -- at
which point that canary regains its meaning and this file should shrink.
"""

import ast
from pathlib import Path
from typing import Final

import pytest
import yaml

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
SMOKE_CONFIGS: Final[Path] = REPO_ROOT / "helao/hexagon/tests/smoke/configs"
HTE_ACTION: Final[Path] = REPO_ROOT / "helao/deploy/hte/servers/action"
HEXAGON_SHIMS: Final[Path] = REPO_ROOT / "helao/deploy/hexagon/servers/action"


def _action_server(cfg_path: Path) -> tuple[str, str] | None:
    """``(deployment, fast)`` of the config's action server, if it has one."""
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    for entry in (cfg.get("servers") or {}).values():
        if isinstance(entry, dict) and entry.get("group") == "action":
            return entry.get("deployment", ""), entry.get("fast", "")
    return None


def _pairs() -> list[tuple[Path, Path]]:
    out = []
    for legacy in sorted(SMOKE_CONFIGS.glob("*.yml")):
        if legacy.stem.endswith("hex") or legacy.stem.endswith("graft"):
            continue
        partner = SMOKE_CONFIGS / f"{legacy.stem}hex.yml"
        if partner.exists():
            out.append((legacy, partner))
    return out


def _shim_target(fast: str) -> str | None:
    """The module a hexagon shim delegates to, read from its LEGACY_MODULE."""
    shim = HEXAGON_SHIMS / f"{fast}.py"
    if not shim.exists():
        return None
    for node in ast.walk(ast.parse(shim.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "LEGACY_MODULE":
                    if isinstance(node.value, ast.Constant):
                        return str(node.value.value)
    return None


def test_the_sweep_finds_the_canary_pairs() -> None:
    """A wrong SMOKE_CONFIGS would make every case below pass over nothing."""
    pairs = _pairs()
    assert len(pairs) >= 25, f"only {len(pairs)} config pairs under {SMOKE_CONFIGS}"


@pytest.mark.parametrize("legacy,hexagon", _pairs(), ids=[p[0].stem for p in _pairs()])
def test_both_sides_of_the_pair_now_run_the_same_module(
    legacy: Path, hexagon: Path
) -> None:
    """The `hte` side and the `hexagon` side resolve to one deployment module.

    Established statically, from the shim's own ``LEGACY_MODULE`` constant --
    the same string ``test_hte_action_shims`` pins -- rather than by building
    both apps, so this stays fast and works for the Windows-only families.
    """
    left, right = _action_server(legacy), _action_server(hexagon)
    if left is None or right is None:
        pytest.skip(f"{legacy.stem}: no action server in the pair")

    left_dep, left_fast = left
    right_dep, right_fast = right
    assert left_fast == right_fast, (
        f"{legacy.stem}: the pair names different modules "
        f"({left_fast!r} vs {right_fast!r}) -- this is not a canary pair"
    )
    if left_dep != "hte" or right_dep != "hexagon":
        pytest.skip(f"{legacy.stem}: not an hte/hexagon pair ({left_dep}/{right_dep})")

    target = _shim_target(right_fast)
    assert (
        target == f"helao.deploy.hte.servers.action.{right_fast}"
    ), f"{right_fast} shim delegates to {target!r}, not the hte module"


def test_every_module_those_canaries_exercise_is_native_now() -> None:
    """Which is what makes both sides identical, and the diff a self-comparison.

    Reads imported names by AST, so a docstring mentioning BaseAPI is not
    mistaken for an import -- a confusion that cost time twice in B3 and B4.
    """
    exercised = set()
    for legacy, _ in _pairs():
        found = _action_server(legacy)
        if found and found[0] == "hte" and found[1]:
            exercised.add(found[1])
    assert exercised, "no hte action modules found across the canary pairs"

    still_legacy = []
    for fast in sorted(exercised):
        path = HTE_ACTION / f"{fast}.py"
        if not path.exists():
            continue
        names = {
            alias.name
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        if "BaseAPI" in names:
            still_legacy.append(fast)

    assert still_legacy == [], (
        "these canary families still have a genuine legacy reference: "
        f"{still_legacy}. Their runtime golden diff is meaningful again, and "
        "this file should be narrowed to exclude them."
    )
