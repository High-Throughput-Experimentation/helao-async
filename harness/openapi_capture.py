"""Capture a live server's route surface to a normalized, diffable form.

The static extractor in :mod:`harness.endpoints` sees only ``@app.<method>(...)``
decorators on a module's own functions; it cannot see the routes ``BaseAPI``/
``Base`` register at runtime, which is exactly the surface a host replacement has
to reproduce. This module reads them off a launched server instead.

**WebSockets are deliberately out of scope here.** They do not appear in
``openapi.json`` at all, so a surface diff that reports "identical" says nothing
about ``ws_status``/``ws_data``/``ws_live``. Those need a connect test.

Why this exists: the hand-written ``_baseapi_system_surface.md`` checklist listed
9 routes and marked 5 of them GET. Measured against a running SIM action server
on 2026-08-14 the real surface is 19 routes, every one POST -- eight omitted,
five with the wrong method. The checklist's own note recorded that the runtime
cross-check was "deferred to P3b/P3e"; that deferral never closed.
"""

import json
from typing import Any

import requests

__all__ = ["normalize", "capture", "capture_to_file"]


def normalize(doc: dict[str, Any]) -> dict[str, Any]:
    """Reduce an OpenAPI document to a sorted, comparable route list.

    Args:
        doc: A parsed ``openapi.json`` document.

    Returns:
        ``{"routes": [{"path", "method", "tags"}, ...]}`` sorted by
        ``(path, method)`` with tags sorted, so two captures of the same server
        compare equal regardless of dict ordering.
    """
    routes = []
    for path, ops in (doc.get("paths") or {}).items():
        for method, op in ops.items():
            routes.append(
                {
                    "path": path,
                    "method": method.lower(),
                    "tags": sorted((op or {}).get("tags") or []),
                }
            )
    routes.sort(key=lambda r: (r["path"], r["method"]))
    return {"routes": routes}


def capture(base_url: str, timeout: float = 10.0) -> dict[str, Any]:
    """Fetch and normalize ``/openapi.json`` from a launched server.

    Args:
        base_url: e.g. ``http://127.0.0.1:8002``.
        timeout: Per-request timeout in seconds.

    Returns:
        The normalized route list from :func:`normalize`.
    """
    resp = requests.get(f"{base_url.rstrip('/')}/openapi.json", timeout=timeout)
    resp.raise_for_status()
    return normalize(resp.json())


def capture_to_file(base_url: str, path, timeout: float = 10.0) -> dict[str, Any]:
    """Capture a server's surface and write it as stable, diffable JSON.

    Args:
        base_url: e.g. ``http://127.0.0.1:8002``.
        path: Destination file.
        timeout: Per-request timeout in seconds.

    Returns:
        The captured route list, so a caller can assert on it without re-reading.
    """
    captured = capture(base_url, timeout=timeout)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(captured, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return captured
