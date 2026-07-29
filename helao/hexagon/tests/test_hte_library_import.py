"""P3c — hte experiment/sequence library import sweep + collision guard.

Two Linux-complete gates for the P3 hte wave (spec §8.3(3) AVOID #8: the
experiment/sequence libraries are in the wave from day one, not bolted on after
the action-server ports):

1. **Import sweep** — every hte experiment/sequence library module imports on a
   vendor-less Linux box. This depends on P3a-1/P3a-2 having made the driver
   modules lazily importable (several libraries import enums/classes — e.g.
   ``Spacingmethod``/``PALtools``/``MoveModes`` — directly from
   ``galil_motion_driver``/``pal_driver``). If a driver regresses to a
   module-top vendor import, the dependent libraries break here loudly.

2. **Flat-namespace collision guard** (spec §4.3.12 Library port) — the known
   ``CCSI_exp``/``CSIL_exp`` (shared ``CCSI_sub_*`` names) and
   ``ECHEUVIS_seq``/``HISPEC_seq`` (``ECHEUVIS_postseq``) shadowing hazards are
   asserted to still be detectable, so the eventual Library-port load-time
   collision check has a frozen expected set. These collisions are currently
   **latent** — no hte config lists a colliding pair in one ``*_libraries:``
   list — but the guard keeps them from silently going live.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from harness.hte_collisions import scan_collisions

HTE = Path("helao/deploy/hte")
EXP_DIR = HTE / "experiments"
SEQ_DIR = HTE / "sequences"


def _library_modules(sub: str, pkg: str) -> list[str]:
    return [
        f"{pkg}.{f.stem}"
        for f in sorted((HTE / sub).glob("*.py"))
        if f.name != "__init__.py"
    ]


LIBRARY_MODULES = _library_modules(
    "experiments", "helao.deploy.hte.experiments"
) + _library_modules("sequences", "helao.deploy.hte.sequences")


def test_library_module_set_nonempty():
    # 13 experiment modules + 13 sequence modules on unstable (spec §8.1).
    # Deliberately an exact count, not a floor: adding an hte library should
    # force a conscious look at this sweep. Update it when the set changes.
    assert len(LIBRARY_MODULES) == 26, LIBRARY_MODULES


@pytest.mark.parametrize("mod", LIBRARY_MODULES)
def test_hte_library_imports_on_linux(mod):
    """Every hte exp/seq library imports without hardware/vendor runtime."""
    importlib.import_module(mod)


def test_known_exp_collision_still_detected():
    cols = scan_collisions(EXP_DIR)
    ccsi = {n: m for n, m in cols.items() if n.startswith("CCSI_sub_")}
    assert ccsi, "expected CCSI_sub_* forks across CCSI_exp.py/CSIL_exp.py"
    for mods in ccsi.values():
        assert {"CCSI_exp.py", "CSIL_exp.py"} <= set(mods)


def test_known_seq_collision_still_detected():
    cols = scan_collisions(SEQ_DIR)
    assert "ECHEUVIS_postseq" in cols
    assert {"ECHEUVIS_seq.py", "HISPEC_seq.py"} <= set(cols["ECHEUVIS_postseq"])
