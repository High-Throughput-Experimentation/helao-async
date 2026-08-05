"""Additive checklist freezer tests (spec §8.3(5))."""

from __future__ import annotations

from harness import freeze


def _route(path: str, method: str = "post", **kw) -> dict:
    return {
        "path": path,
        "method": method,
        "tags": kw.get("tags", ["action"]),
        "handler": kw.get("handler", "h"),
        "params": kw.get("params", []),
    }


def test_merge_keeps_frozen_entries_verbatim_and_appends():
    """A surviving entry is copied through untouched; a new route is appended."""
    frozen = [
        _route(
            "/K/a", params=[{"name": "x", "annotation": "List[float]", "default": None}]
        )
    ]
    # Same route, PEP 585 spelling changed by a typing sweep -- NOT surface drift,
    # because diff_route_sets normalizes the alias when it compares.
    current = [
        _route(
            "/K/a", params=[{"name": "x", "annotation": "list[float]", "default": None}]
        ),
        _route("/K/b"),
    ]
    merged, drift = freeze.merge_routes(frozen, current)
    assert drift == []
    assert (
        merged[0]["params"][0]["annotation"] == "List[float]"
    ), "frozen entry rewritten"
    assert [r["path"] for r in merged] == ["/K/a", "/K/b"]


def test_merge_reports_removal_and_change_without_applying_them():
    frozen = [
        _route("/K/gone"),
        _route(
            "/K/changed", params=[{"name": "x", "annotation": "int", "default": None}]
        ),
    ]
    current = [
        _route(
            "/K/changed", params=[{"name": "x", "annotation": "str", "default": None}]
        )
    ]
    merged, drift = freeze.merge_routes(frozen, current)
    kinds = {(d["kind"], d["path"]) for d in drift}
    assert ("missing", "/K/gone") in kinds
    assert ("changed", "/K/changed") in kinds
    # Neither is applied: the removed route survives and the changed one keeps its
    # frozen schema. Shrinking a parity baseline must be deliberate. And with no
    # additions the frozen list comes back in its stored order, untouched.
    assert merged == frozen
    assert [r["path"] for r in merged] == ["/K/gone", "/K/changed"]
    assert merged[1]["params"][0]["annotation"] == "int"


def test_merge_does_not_reorder_a_file_it_has_nothing_to_add_to():
    """A frozen file need not be sorted, and must not be rewritten just to sort it.

    One checklist in a private deployment is stored in source-declaration order.
    Returning `sorted(frozen)` when there is nothing to add would rewrite a
    verbatim record for no gain -- caught by the tool's own report showing a
    "5 -> 5 routes" write.
    """
    frozen = [_route("/K/get"), _route("/K/set"), _route("/K/home")]
    merged, drift = freeze.merge_routes(frozen, list(frozen))
    assert drift == []
    assert merged == frozen, "declaration order not preserved"
    assert [r["path"] for r in merged] == ["/K/get", "/K/set", "/K/home"]


def test_accept_drift_touches_only_the_flagged_parameter():
    """Correcting one param must not rewrite its neighbours' verbatim spelling.

    `diff_route_sets` reports `params` as a single field, so a naive accept
    replaces the whole list. The first version of this tool did that per SERVER
    and rewrote four unrelated annotations while fixing six real ones.
    """
    frozen = [
        _route(
            "/K/move",
            params=[
                # A real defect: an annotation the source never had.
                {"name": "speed", "annotation": "Optional[int]", "default": "None"},
                # Spelling-only: a typing sweep moved it; the gate ignores this.
                {"name": "d_mm", "annotation": "List[float]", "default": "[0, 0]"},
            ],
        )
    ]
    current = [
        _route(
            "/K/move",
            params=[
                {"name": "speed", "annotation": "int", "default": "None"},
                {"name": "d_mm", "annotation": "list[float]", "default": "[0, 0]"},
            ],
        )
    ]
    merged, drift = freeze.merge_routes(frozen, current, accept_drift=True)
    anns = {p["name"]: p["annotation"] for p in merged[0]["params"]}
    assert anns["speed"] == "int", "the flagged correction was not applied"
    assert anns["d_mm"] == "List[float]", "verbatim spelling was churned"
    assert [d["kind"] for d in drift] == ["changed"]


def test_accept_drift_drops_a_removed_route_and_leaves_the_rest_verbatim():
    frozen = [_route("/K/gone"), _route("/K/kept")]
    current = [_route("/K/kept")]
    merged, _ = freeze.merge_routes(frozen, current, accept_drift=True)
    assert [r["path"] for r in merged] == ["/K/kept"]
    assert merged[0] is frozen[1], "surviving entry was rebuilt rather than kept"


def test_accept_drift_is_inert_when_there_is_no_drift():
    frozen = [_route("/K/a"), _route("/K/b")]
    merged, drift = freeze.merge_routes(frozen, list(frozen), accept_drift=True)
    assert drift == []
    assert merged == frozen


def test_synthesized_key_detects_a_concrete_prefix():
    assert freeze.synthesized_key([_route("/CALC/a"), _route("/CALC/b")]) == "CALC"


def test_synthesized_key_ignores_the_unsubstituted_placeholder():
    """`{server_key}` means no key was supplied — that is not a synthesized key.

    This is the case that must still be frozen: a manifest with no key and a
    checklist frozen with the placeholder agree with each other, and skipping
    them would silently stop covering routes added to those modules later.
    """
    assert freeze.synthesized_key([_route("/{server_key}/a")]) is None


def test_synthesized_key_none_when_ambiguous_or_absent():
    assert freeze.synthesized_key([_route("/A/x"), _route("/B/y")]) is None
    assert freeze.synthesized_key([_route("/bare", tags=["private"])]) is None
    assert freeze.synthesized_key([]) is None


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
