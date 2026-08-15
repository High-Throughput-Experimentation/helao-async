"""OrchHost construction and route surface (B3a)."""

import json
import tempfile
from pathlib import Path


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


CHECKLIST = (
    Path(__file__).resolve().parents[1] / "tests/checklists/orch_openapi_legacy.json"
)


#: Routes still registered as raising stubs. EMPTY as of B3b: every loop
#: route now has a real body and a real parameter schema, so the parameter
#: gate below covers the whole surface with no exemption.
STUB_ROUTES: frozenset[str] = frozenset()


def _by_key(doc: dict) -> dict:
    return {(r["path"], r["method"]): r for r in doc["routes"]}


def test_the_route_surface_matches_the_live_legacy_orchestrator():
    """Captured from a LAUNCHED legacy orchestrator, not hand-written.

    B1 measured its hand-written surface checklist stale: 9 routes listed
    with 5 marked GET where the live server had 19, every one POST. A
    decorator scan is no better here -- orch_api also calls
    _register_utility_endpoints, whose routes it cannot see.

    WebSockets are absent from openapi.json entirely, so this says nothing
    about ws_status/ws_data/ws_live. Those are B3b's, and they need a
    connect test rather than a schema diff.
    """
    from harness import openapi_capture

    legacy = _by_key(json.loads(CHECKLIST.read_text(encoding="utf-8")))
    current = _by_key(openapi_capture.normalize(_host().openapi()))

    missing = sorted(k for k in legacy if k not in current)
    assert (
        missing == []
    ), f"routes the live legacy orchestrator has, OrchHost lacks: {missing}"


def test_parameter_schemas_match_the_live_legacy_orchestrator():
    """A route can be present, correctly tagged, and still reject every
    request its predecessor accepted -- a renamed parameter, a lost
    default, a changed type. None of that shows in a path-set diff."""
    from harness import openapi_capture

    legacy = _by_key(json.loads(CHECKLIST.read_text(encoding="utf-8")))
    current = _by_key(openapi_capture.normalize(_host().openapi()))

    drifted = {
        key: {"legacy": legacy[key]["params"], "host": current[key]["params"]}
        for key in legacy
        if key in current
        and key[0] not in STUB_ROUTES
        and legacy[key]["params"] != current[key]["params"]
    }
    assert drifted == {}, f"parameter drift on {len(drifted)} route(s): {drifted}"


def test_the_stub_exemption_list_is_exactly_the_routes_that_still_raise():
    """The exemption must not outlive the stubs, and it no longer does.

    Both sets are empty together, which is the invariant: a member left on
    NOT_YET_PORTED means a route still raises and must stay exempt, and an
    exemption with nothing outstanding silently stops covering a route that
    now has a real body. Tied to the ratchet rather than to a second
    hand-written list, which would drift.
    """
    from helao.hexagon.tests.test_orch_host_member_coverage import NOT_YET_PORTED

    assert bool(NOT_YET_PORTED) == bool(STUB_ROUTES), (
        f"NOT_YET_PORTED={sorted(NOT_YET_PORTED)} but "
        f"STUB_ROUTES={sorted(STUB_ROUTES)} -- these empty together"
    )


def test_the_ws_routes_use_the_ORCH_family_encoding_not_the_action_one():
    """The one difference no surface gate can see.

    WebSockets are absent from openapi.json, so the 74-route diff -- which
    covers every parameter schema -- says nothing about them. And the two
    families really do differ: base_api streams through WsPublisher with
    the IDENTITY xform (pickling the model object), while orch_api streams
    through Base._ws_relay, which pickles msg.as_dict() for status and data
    and the raw message for the live buffer.

    Inheriting ActionHost's registration sends objects to consumers that
    expect dicts. Nothing errors -- the frame decodes and the attribute
    access after it does not -- so every Bokeh visualizer and Reflex panel
    on the orchestrator goes quietly blank.
    """
    host = _host()

    def _calls_as_dict(publisher) -> bool:
        return "as_dict" in publisher.xform_func.__code__.co_names

    assert _calls_as_dict(host.status_publisher), "/ws_status must send dicts"
    assert _calls_as_dict(host.data_publisher), "/ws_data must send dicts"
    assert not _calls_as_dict(
        host.live_publisher
    ), "/ws_live is dict-native; legacy passes use_as_dict=False"

    for path in ("/ws_status", "/ws_data", "/ws_live"):
        matches = [r for r in host.routes if getattr(r, "path", "") == path]
        assert len(matches) == 1, (
            f"{path} registered {len(matches)} times -- ActionHost registers "
            "first, so a duplicate leaves the action-family handler serving"
        )
