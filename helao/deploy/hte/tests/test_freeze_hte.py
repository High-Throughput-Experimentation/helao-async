"""hte's share of the freezer tests (moved from harness/tests/test_freeze.py).

These freeze or verify against hte's own checklists and registrars, so they live
with hte; the freezer and its helpers stay in the parent.
"""

from __future__ import annotations

from harness import freeze
from harness.tests.test_freeze import _external


def test_unnamed_removal_stays_a_blocker_and_says_how_to_name_it():
    """Otherwise --accept-drift looks like a broken flag rather than a guard."""
    _, blockers = freeze.freeze_deployment(
        "hte", only="galil_io", key_override="WRONGKEY", accept_drift=True, dry_run=True
    )
    assert blockers, "wrong key should still report every frozen path as missing"
    assert all("--accept-missing" in b for b in blockers if "missing" in b), blockers


def test_key_override_substitutes_the_server_key():
    """`--key` is how a synthesized-key checklist stays maintainable.

    The manifest correctly records no OPERATIONAL key for an unwired server, but
    its checklist's paths were frozen under one, so re-freezing needs that key
    supplied rather than inferred. Exercised here against hte's galil_io, whose
    real key happens to be IO: passing it changes nothing, and passing a wrong
    key makes every frozen path read as missing.
    """
    lines, blockers = freeze.freeze_deployment(
        "hte", only="galil_io", key_override="IO", dry_run=True
    )
    assert blockers == []
    assert any("unchanged" in ln for ln in lines), lines

    _, blockers = freeze.freeze_deployment(
        "hte", only="galil_io", key_override="WRONGKEY", dry_run=True
    )
    assert any("missing" in b for b in blockers), "a wrong key should not pass"


def test_verify_external_confirms_the_route_in_its_registrar():
    """The marker is a check, not a mute button.

    Suppressing these routes outright would mean the baseline silently stops
    noticing if the upstream registrar drops one -- trading a false alarm for a
    blind spot. So the registrar's own module is extracted and the route is looked
    up there.
    """
    ref = "helao.deploy.hte.servers.gamry.gamry_server2:gamry_dyn_endpoints"
    ok, problems = freeze.verify_external([_external("/PSTAT/run_CA", ref)], "PSTAT")
    assert ok == ["/PSTAT/run_CA"] and problems == []

    # A route the registrar does not register is a problem: the baseline would be
    # asserting something nothing registers.
    ok, problems = freeze.verify_external([_external("/PSTAT/nope", ref)], "PSTAT")
    assert ok == [] and any("no longer registers it" in p for p in problems)

    # So is a marker naming a module that does not exist.
    ok, problems = freeze.verify_external([_external("/K/x", "no.such.module:fn")], "K")
    assert any("not a file" in p for p in problems)


def test_hte_freeze_is_clean_and_skips_nothing():
    """hte is the public regression case for the skip NOT firing.

    Four hte modules have `representative_key: null`, and all four are frozen
    with `{server_key}` unsubstituted — so every one must still be frozen, and
    the whole deployment must report no drift and no skips.
    """
    lines, blockers = freeze.freeze_deployment("hte", dry_run=True)
    assert blockers == []
    assert not [ln for ln in lines if "skipped" in ln], lines
    assert all("would write" not in ln for ln in lines), lines
