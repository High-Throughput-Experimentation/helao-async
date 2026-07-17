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
