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


def test_accept_drift_alone_never_drops_a_route():
    """The guard: bulk-accepting schema changes must not delete routes.

    A deployment-wide --accept-drift once applied 11 `missing` records and cut a
    frozen baseline from 16 routes to 5, deleting the runtime-registered routes it
    existed to assert. Widening a schema is recoverable; a dropped route is one
    the gate silently stops checking.
    """
    frozen = [_route("/K/gone"), _route("/K/kept")]
    current = [_route("/K/kept")]
    merged, drift = freeze.merge_routes(frozen, current, accept_drift=True)
    assert merged == frozen, "accept_drift deleted a route"
    assert [d["kind"] for d in drift] == ["missing"]


def test_accept_missing_drops_only_the_named_route():
    frozen = [_route("/K/gone"), _route("/K/also_gone"), _route("/K/kept")]
    current = [_route("/K/kept")]
    merged, _ = freeze.merge_routes(frozen, current, accept_missing=["/K/gone"])
    assert [r["path"] for r in merged] == ["/K/also_gone", "/K/kept"]
    assert merged[1] is frozen[2], "surviving entry was rebuilt rather than kept"


def test_applicable_drift_separates_the_two_authorities():
    drift = [
        {"path": "/K/a", "method": "post", "kind": "changed", "field": "params"},
        {"path": "/K/b", "method": "post", "kind": "missing"},
    ]
    assert freeze.applicable_drift(drift) == []
    assert [d["path"] for d in freeze.applicable_drift(drift, accept_drift=True)] == [
        "/K/a"
    ]
    assert [
        d["path"] for d in freeze.applicable_drift(drift, accept_missing=["/K/b"])
    ] == ["/K/b"]
    both = freeze.applicable_drift(drift, accept_drift=True, accept_missing=["/K/b"])
    assert len(both) == 2


def test_unnamed_removal_stays_a_blocker_and_says_how_to_name_it():
    """Otherwise --accept-drift looks like a broken flag rather than a guard."""
    _, blockers = freeze.freeze_deployment(
        "hte", only="galil_io", key_override="WRONGKEY", accept_drift=True, dry_run=True
    )
    assert blockers, "wrong key should still report every frozen path as missing"
    assert all("--accept-missing" in b for b in blockers if "missing" in b), blockers


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


def _external(path, ref):
    r = _route(path)
    r[freeze.EXTERNAL_KEY] = ref
    return r


def test_external_routes_are_not_reported_missing():
    """A foreign registrar's routes cannot be seen by extracting this module.

    One real server composes 15 of its 16 routes from a registrar imported out of
    another deployment. Unmarked, every freeze reported all 15 as `missing`, and
    the only escapes were deleting them from the baseline or learning to ignore
    the report.
    """
    ref = "harness.endpoints:whatever"
    frozen = [_external("/K/from_elsewhere", ref), _route("/K/local")]
    merged, drift = freeze.merge_routes(frozen, [_route("/K/local")])
    assert merged == frozen, "a foreign route must not be dropped"
    assert [d["path"] for d in drift] == ["/K/from_elsewhere"]
    assert freeze.external_routes(frozen) == {("/K/from_elsewhere", "post"): ref}


def test_verify_external_confirms_the_route_in_its_registrar():
    """The marker is a check, not a mute button.

    Suppressing these routes outright would mean the baseline silently stops
    noticing if the upstream registrar drops one -- trading a false alarm for a
    blind spot. So the registrar's own module is extracted and the route is looked
    up there.
    """
    ref = "helao.deploy.hte.servers.action.gamry_server2:gamry_dyn_endpoints"
    ok, problems = freeze.verify_external([_external("/PSTAT/run_CA", ref)], "PSTAT")
    assert ok == ["/PSTAT/run_CA"] and problems == []

    # A route the registrar does not register is a problem: the baseline would be
    # asserting something nothing registers.
    ok, problems = freeze.verify_external([_external("/PSTAT/nope", ref)], "PSTAT")
    assert ok == [] and any("no longer registers it" in p for p in problems)

    # So is a marker naming a module that does not exist.
    ok, problems = freeze.verify_external([_external("/K/x", "no.such.module:fn")], "K")
    assert any("not a file" in p for p in problems)


def _dynamic(path, ref):
    r = _route(path)
    r[freeze.DYNAMIC_KEY] = ref
    return r


def test_dynamic_routes_are_not_reported_missing():
    """A call-registered route cannot be seen by extracting ANY module --
    including the one that performs the call -- so it must not be dropped
    just because the current extraction never produces it.
    """
    ref = "harness.endpoints:whatever"
    frozen = [_dynamic("/K/from_a_loop", ref), _route("/K/local")]
    merged, drift = freeze.merge_routes(frozen, [_route("/K/local")])
    assert merged == frozen, "a dynamic route must not be dropped"
    assert [d["path"] for d in drift] == ["/K/from_a_loop"]
    assert freeze.dynamic_routes(frozen) == {("/K/from_a_loop", "post"): ref}


def test_verify_dynamic_confirms_the_module_exists_but_not_the_route():
    """Unlike `verify_external`, this can never re-find the route itself by
    AST -- that is the whole reason `DYNAMIC_KEY` exists instead of
    `EXTERNAL_KEY`. It can only confirm the named module is still there; a
    module that still exists but no longer performs the call is NOT something
    this function can catch (a runtime test in the owning deployment's own
    suite is what has to catch that).
    """
    real_ref = "harness.endpoints:extract_routes"
    ok, problems = freeze.verify_dynamic([_dynamic("/K/from_a_loop", real_ref)])
    assert ok == ["/K/from_a_loop"] and problems == []

    ok, problems = freeze.verify_dynamic([_dynamic("/K/x", "no.such.module:fn")])
    assert ok == [] and any("not a file" in p for p in problems)


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
