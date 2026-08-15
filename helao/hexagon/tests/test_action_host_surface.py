"""The action-server system surface, captured live rather than asserted by hand.

``_baseapi_system_surface.md`` was hand-written and its own note records that the
runtime ``/openapi.json`` cross-check was "deferred to P3b/P3e". That deferral
never closed, and the file drifted: measured 2026-08-14 against a running SIM
server it omits 8 routes and marks 5 POST routes as GET. This module pins the
real surface so a host that under-builds it cannot pass.
"""

import json
import tempfile
from pathlib import Path
from typing import Final

from harness import openapi_capture

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
FROZEN: Final[Path] = (
    REPO_ROOT / "helao/hexagon/tests/checklists/hte/_baseapi_system_surface.json"
)

#: Every private route BaseAPI/Base registers on an action server, captured live
#: from a SIM server on `goldenhex` (2026-08-14). The server's own action-tagged
#: routes are excluded; `/{key}/estop` is action-tagged but host-registered and is
#: checked separately.
EXPECTED_PRIVATE: Final[frozenset[str]] = frozenset(
    {
        "/_raise_async_exception",
        "/_raise_exception",
        "/attach_client",
        "/detach_client",
        "/endpoints",
        "/get_config",
        "/get_lbuf",
        "/get_status",
        "/hotreload_busy",
        "/list_executors",
        "/loaded_modules",
        "/resend_active",
        "/shutdown",
        "/stop_executor",
        "/test_alert",
        "/test_receive",
    }
)

#: Absent from openapi.json entirely -- websockets are invisible to an OpenAPI
#: diff, so a surface diff reporting "identical" says nothing about these. They
#: get their own connect test.
EXPECTED_WEBSOCKETS: Final[tuple[str, ...]] = ("ws_status", "ws_data", "ws_live")


def test_every_private_route_is_a_post() -> None:
    """The frozen checklist marked five of these GET. They are all POST."""
    frozen = json.loads(FROZEN.read_text())
    methods = {r["method"] for r in frozen["routes"] if r["path"] in EXPECTED_PRIVATE}
    assert methods == {"post"}, f"non-POST private routes: {methods}"


def test_frozen_surface_matches_the_expected_private_set() -> None:
    frozen = json.loads(FROZEN.read_text())
    got = {r["path"] for r in frozen["routes"] if "private" in (r["tags"] or [])}
    assert got == EXPECTED_PRIVATE, (
        f"missing: {sorted(EXPECTED_PRIVATE - got)}\n"
        f"unexpected: {sorted(got - EXPECTED_PRIVATE)}"
    )


def test_capture_normalizes_deterministically() -> None:
    """Two captures of the same document compare equal, and routes sort."""
    doc = {
        "paths": {
            "/b": {"post": {"tags": ["private"]}},
            "/a": {"post": {"tags": ["action"]}},
        }
    }
    assert openapi_capture.normalize(doc) == openapi_capture.normalize(doc)
    assert [r["path"] for r in openapi_capture.normalize(doc)["routes"]] == ["/a", "/b"]


# ---------------------------------------------------------------------------
# The host's own surface (B1 Task 3a)
# ---------------------------------------------------------------------------
# Asserted against a constructed host rather than a launched one: this is the
# gate that fails while the host is under-built, and it needs no server.


def _host():
    """Build an ActionHost against an injected config and wiring."""
    from helao.hexagon.app.action_host import ActionHost
    from helao.hexagon.app.wiring import PortWiring

    cfg = {
        # A real directory: HelaoFastAPI initializes the process logger under
        # <root>/LOGS, so a None root fails in os.path.join before any route
        # is registered.
        "root": tempfile.mkdtemp(prefix="helao_surface_test_"),
        "servers": {"SIM": {"host": "127.0.0.1", "port": 8002, "params": {}}},
    }

    class _Stub:
        # meta_writer_for IS used during construction -- the host owns the
        # native meta writer so the session can derive the default file-conn
        # key. Every other port member must stay untouched.
        def meta_writer_for(self, base):
            return object()

        def __getattr__(self, name):
            raise AssertionError(f"port member {name!r} used during construction")

    wiring = PortWiring(
        config=_Stub(),
        logging=_Stub(),
        clock=_Stub(),
        transport=_Stub(),
        state_persistence=_Stub(),
        status=_Stub(),
        health=_Stub(),
        artifact_store=_Stub(),
        data_sink=_Stub(),
    )
    return ActionHost(
        server_key="SIM",
        server_title="SIM",
        description="surface test",
        version=1.0,
        wiring=wiring,
        helao_cfg=cfg,
    )


def test_the_host_registers_every_private_route_captured_from_legacy() -> None:
    host = _host()
    got = {
        r["path"]
        for r in openapi_capture.normalize(host.openapi())["routes"]
        if "private" in r["tags"]
    }
    assert got == EXPECTED_PRIVATE, (
        f"missing: {sorted(EXPECTED_PRIVATE - got)}\n"
        f"unexpected: {sorted(got - EXPECTED_PRIVATE)}"
    )


def test_every_host_route_is_a_post() -> None:
    """Legacy registers no GET on an action server; the checklist claimed five."""
    routes = openapi_capture.normalize(_host().openapi())["routes"]
    assert {r["method"] for r in routes} == {"post"}


def test_the_host_registers_its_estop_route() -> None:
    routes = openapi_capture.normalize(_host().openapi())["routes"]
    estop = [r for r in routes if r["path"] == "/SIM/estop"]
    assert estop and estop[0]["tags"] == ["action"]


def test_the_host_surface_matches_the_frozen_capture() -> None:
    """The whole point: a host that under-builds the captured surface fails."""
    frozen = {
        r["path"]
        for r in json.loads(FROZEN.read_text())["routes"]
        if r["path"] != "/SIM/acquire_data"
    }
    frozen -= {"/SIM/cancel_acquire_data"}  # the sim's own action routes
    got = {r["path"] for r in openapi_capture.normalize(_host().openapi())["routes"]}
    assert (
        got == frozen
    ), f"missing: {sorted(frozen - got)}\nunexpected: {sorted(got - frozen)}"


def test_base_is_the_host() -> None:
    """21 hte modules reach app.base.<member>; both names are the same object."""
    host = _host()
    assert host.base is host
