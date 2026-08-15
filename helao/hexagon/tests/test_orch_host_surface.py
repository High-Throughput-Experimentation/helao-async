"""OrchHost construction and route surface (B3a)."""

import tempfile


def _host():
    from helao.helpers import config_loader
    from helao.hexagon.app.orch_host import OrchHost

    config_loader.CONFIG = {
        "root": tempfile.mkdtemp(prefix="helao_orchhost_"),
        "dummy": True,
        "simulation": True,
        "run_type": "simulation",
        "servers": {
            "ORCH": {
                "host": "127.0.0.1",
                "port": 8001,
                "group": "orchestrator",
                "params": {},
            },
            "SIM": {
                "host": "127.0.0.1",
                "port": 8002,
                "group": "action",
                "params": {},
            },
        },
    }
    return OrchHost("ORCH", "ORCH", "test orchestrator", version=3.0)


def test_the_host_is_its_own_orch_and_its_own_base():
    """Legacy spells the back-reference both ways and both have call sites:
    orch_api reaches self.orch at 60 sites, and Orch extends Base."""
    host = _host()
    assert host.orch is host
    assert host.base is host


def test_construction_populates_the_three_queues_and_the_status_model():
    host = _host()
    assert list(host.sequence_dq) == []
    assert list(host.experiment_dq) == []
    assert list(host.action_dq) == []
    assert host.globalstatusmodel is not None
    assert host.active_experiment is None
    assert host.active_sequence is None


def _legacy_orch_api_routes() -> set[str]:
    """Every route ``orch_api`` declares by decorator, paths substituted.

    Static, and knowingly incomplete: ``orch_api`` also calls
    ``_register_utility_endpoints(self)``, whose routes no decorator scan
    can see. That is why the real gate (B3a Task 7) diffs a LIVE
    /openapi.json instead -- B1 measured its hand-written surface
    checklist stale, at 9 routes with 5 GETs where the live server had 19,
    all POST. This function is the cheap lower bound, not the gate.
    """
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[3] / "helao/core/servers/orch_api.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        for dec in getattr(node, "decorator_list", []):
            if not (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr in {"post", "get", "websocket"}
                and dec.args
            ):
                continue
            arg = dec.args[0]
            if isinstance(arg, ast.Constant):
                found.add(arg.value)
            elif isinstance(arg, ast.JoinedStr):
                found.add(
                    "".join(
                        v.value if isinstance(v, ast.Constant) else "ORCH"
                        for v in arg.values
                    )
                )
    return found


def test_every_orch_api_route_exists_on_the_host():
    """No route may be missing, including the nine action endpoints.

    The 24 loop routes are PRESENT and raise; absence would read as a
    missing server and send a caller looking at config and ports.
    """
    host = _host()
    paths = {getattr(r, "path", "") for r in host.routes}
    missing = sorted(_legacy_orch_api_routes() - paths)
    assert missing == [], f"routes orch_api declares that OrchHost lacks: {missing}"


def test_estop_is_registered_exactly_once():
    """ActionHost already registers /{server_key}/estop with the same body.

    A second registration is accepted silently by FastAPI and the first
    wins, so the duplicate would sit shadowed and never execute -- while a
    path-level surface check still passed, because the path is there
    either way.
    """
    host = _host()
    estops = [r for r in host.routes if getattr(r, "path", "") == "/ORCH/estop"]
    assert len(estops) == 1, f"expected exactly one /ORCH/estop, got {len(estops)}"
