"""The action-server system surface, captured live rather than asserted by hand.

``_baseapi_system_surface.md`` was hand-written and its own note records that the
runtime ``/openapi.json`` cross-check was "deferred to P3b/P3e". That deferral
never closed, and the file drifted: measured 2026-08-14 against a running SIM
server it omits 8 routes and marks 5 POST routes as GET. This module pins the
real surface so a host that under-builds it cannot pass.
"""

import json
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
