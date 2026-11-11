"""hte's share of two parent sweeps whose roots named hte (spec §2, OQ-3)."""

from pathlib import Path

import pytest

from helao.hexagon.tests.test_driver_host_surface import scan
from helao.hexagon.tests.test_external_composition_contract import (
    _registrar_module,
    _registrar_reads,
)

HTE = Path(__file__).resolve().parents[1]


def _sources():
    return [
        p
        for p in sorted(HTE.rglob("*.py"))
        if "__pycache__" not in p.parts and "tests" not in p.parts
    ]


def test_no_forbidden_host_read_in_hte():
    violations, _, _ = scan(_sources())
    assert not violations, "\n".join(violations)


def test_the_hte_scan_sees_every_measured_read():
    _, reads, files = scan(_sources())
    assert reads >= 29 and len(files) >= 14, (reads, len(files))  # measured 2026-11-10


#: Every ``app.<attr>`` an hte ``*_dyn_endpoints`` registrar reads, by module.
#: These functions are exported, and at least one is composed by a deployment
#: outside this repo (through ``overlay_dyn_endpoints``), so the attribute set
#: is a published interface: a consumer stubs exactly these.
#:
#: Changing one is allowed. Changing one *silently* is what B5 did, and what
#: cost a private repo a red suite that nothing here reported. Update the entry
#: in the same commit, and treat the diff as the list of consumers to warn.
REGISTRAR_CONTRACT = {
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


@pytest.mark.parametrize("module_stem", sorted(REGISTRAR_CONTRACT))
def test_registrar_reads_exactly_the_pinned_attributes(module_stem):
    expected = REGISTRAR_CONTRACT[module_stem]
    actual = _registrar_reads(module_stem)
    assert actual == expected, (
        f"{module_stem}'s registrar now reads {sorted(actual)}, pinned as "
        f"{sorted(expected)}. This function is composed by a deployment outside "
        "this repo, which stubs exactly this set -- added: "
        f"{sorted(actual - expected)}, removed: {sorted(expected - actual)}."
    )


def test_the_contract_probe_is_not_vacuous():
    """A typo'd module stem would make the pin above assert over nothing."""
    for stem in REGISTRAR_CONTRACT:
        assert _registrar_module(stem).exists(), f"{stem} is pinned but has no module"
        assert _registrar_reads(stem), f"{stem}'s registrar reads no app attributes"
