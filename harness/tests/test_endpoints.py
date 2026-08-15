"""AST route extraction against a REAL legacy server module (ws_simulator)."""

from pathlib import Path

from harness.endpoints import diff_route_sets, extract_routes

WS_SIM = Path("helao/deploy/test/servers/action/ws_simulator.py")


def test_extracts_action_routes_with_server_key_substitution():
    routes = extract_routes(WS_SIM, server_key="SIM")
    by_path = {r["path"]: r for r in routes}
    assert "/SIM/acquire_data" in by_path
    acq = by_path["/SIM/acquire_data"]
    assert acq["method"] == "post"
    assert acq["tags"] == ["action"]
    params = {p["name"]: p for p in acq["params"]}
    assert params["duration"]["annotation"] == "float"
    assert params["duration"]["default"] == "-1"
    assert params["acquisition_rate"]["default"] == "0.2"
    assert "fast_samples_in" in params
    assert "/SIM/cancel_acquire_data" in by_path


def test_fstring_paths_keep_placeholder_without_server_key():
    routes = extract_routes(WS_SIM)
    paths = [r["path"] for r in routes]
    assert "/{server_key}/acquire_data" in paths


def test_diff_route_sets_reports_gaps():
    frozen = extract_routes(WS_SIM, server_key="SIM")
    assert diff_route_sets(frozen, frozen) == []
    shrunk = [r for r in frozen if r["path"] != "/SIM/acquire_data"]
    diffs = diff_route_sets(frozen, shrunk)
    assert any(
        d["path"] == "/SIM/acquire_data" and d["kind"] == "missing" for d in diffs
    )
    mutated = [dict(r) for r in frozen]
    for r in mutated:
        if r["path"] == "/SIM/acquire_data":
            r["params"] = [p for p in r["params"] if p["name"] != "duration"]
    diffs = diff_route_sets(frozen, mutated)
    assert any(d["kind"] == "changed" for d in diffs)


def test_action_decorator_honours_an_explicit_path_and_tags(tmp_path):
    """``@host.action(path=...)`` must extract at the path it declares.

    A few legacy hte routes were served at a path that did not match their
    handler's name -- ``get_positions`` answered ``/SAMPLE/get_loaded_positions``
    -- so their B5 ports pass ``path=`` to keep the route where it was rather
    than renaming the handler and moving both the route and the operation_id.
    Deriving the path from the handler name regardless would report those
    correct ports as a missing/extra pair against the frozen checklist.
    """
    module = tmp_path / "ported.py"
    module.write_text(
        "def makeApp(server_key):\n"
        "    @app.action()\n"
        "    async def plain(ctx: ActionContext, duration: float = -1):\n"
        "        pass\n"
        '    @app.action(path=f"/{server_key}/get_loaded_positions")\n'
        "    async def get_positions(ctx: ActionContext):\n"
        "        pass\n"
        '    @app.action(tags=["private"])\n'
        "    async def internal(ctx: ActionContext):\n"
        "        pass\n"
    )
    by_path = {r["path"]: r for r in extract_routes(module, server_key="SAMPLE")}

    assert "/SAMPLE/plain" in by_path
    assert by_path["/SAMPLE/plain"]["tags"] == ["action"]
    # `ctx` is injected by the host and stripped before FastAPI sees it, so it
    # must not appear in the extracted signature.
    assert [p["name"] for p in by_path["/SAMPLE/plain"]["params"]] == ["duration"]

    assert "/SAMPLE/get_loaded_positions" in by_path
    assert "/SAMPLE/get_positions" not in by_path

    assert by_path["/SAMPLE/internal"]["tags"] == ["private"]
