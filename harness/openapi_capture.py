"""Capture a live server's route surface to a normalized, diffable form.

The static extractor in :mod:`harness.endpoints` sees only ``@app.<method>(...)``
decorators on a module's own functions; it cannot see the routes ``ActionHost``/
``OrchHost`` register at runtime, which is exactly the surface a host replacement has
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
        ``{"routes": [{"path", "method", "tags", "params"[, "body"]}, ...]}``
        sorted by ``(path, method)`` with tags sorted, so two captures of the
        same server compare equal regardless of dict ordering. ``body`` is
        present only on a route that declares a request body.
    """
    schemas = (doc.get("components") or {}).get("schemas") or {}
    routes = []
    for path, ops in (doc.get("paths") or {}).items():
        for method, op in ops.items():
            route = {
                "path": path,
                "method": method.lower(),
                "tags": sorted((op or {}).get("tags") or []),
                "params": _params(op or {}, schemas),
            }
            body = _body(op or {}, schemas)
            if body is not None:
                route["body"] = body
            routes.append(route)
    routes.sort(key=lambda r: (r["path"], r["method"]))
    return {"routes": routes}


def _ref_name(schema: dict[str, Any]) -> Any:
    """The component a schema points at, directly or through one ``anyOf`` arm.

    ``Optional[SomeEnum]`` renders as ``anyOf: [{$ref}, {type: null}]`` and a
    bare enum parameter as ``{$ref}``; both name the component that holds the
    members a caller may send.
    """
    for variant in (schema, *(schema.get("anyOf") or [])):
        if "$ref" in variant:
            return variant["$ref"].rsplit("/", 1)[-1]
    return None


def _describe(schema: dict[str, Any], schemas: dict[str, Any]) -> dict[str, Any]:
    """``type``, plus ``ref`` and ``enum`` when the schema points at a component.

    A ``$ref`` schema has no ``type`` of its own, so before this every enum
    parameter recorded ``type: null`` and two different enums compared equal.
    The component's name is kept because FastAPI takes it from the Python
    class name, which is part of the contract; the enum members are what a
    caller actually sends.
    """
    out = {"type": schema.get("type") or _any_of_type(schema)}
    ref = _ref_name(schema)
    if ref is not None:
        component = schemas.get(ref) or {}
        out["ref"] = ref
        if out["type"] is None:
            out["type"] = component.get("type")
        if "enum" in component:
            out["enum"] = sorted(component["enum"], key=str)
    return out


def _body(op: dict[str, Any], schemas: dict[str, Any]) -> Any:
    """A route's request body, resolved one level into its component.

    Returns None for a route without one, so those routes keep their shape.
    The body component's own name is NOT recorded: FastAPI derives it from the
    handler's function name (``Body_<func>_<path>_post``), which differs
    between two correct implementations for the same reason ``title`` does.
    """
    request_body = op.get("requestBody")
    if not request_body:
        return None
    content = request_body.get("content") or {}
    schema = (next(iter(content.values()), None) or {}).get("schema") or {}
    ref = _ref_name(schema)
    target = (schemas.get(ref) or {}) if ref is not None else schema
    body = {
        "required": bool(request_body.get("required", False)),
        "type": target.get("type") or _any_of_type(target),
        "properties": sorted(
            (
                [name, _describe(prop, schemas)]
                for name, prop in (target.get("properties") or {}).items()
            ),
            key=lambda pair: pair[0],
        ),
        "required_props": sorted(target.get("required") or []),
    }
    if "items" in target:
        body["items"] = _describe(target["items"], schemas)
    return body


def _params(op: dict[str, Any], schemas: dict[str, Any]) -> list[dict[str, Any]]:
    """The query/path parameters a route accepts, reduced to what callers see.

    Paths and methods alone are too weak a gate for a host replacement: a
    route can be present with the right tag and still reject every request
    its predecessor accepted, because a parameter was renamed, lost its
    default, or changed type. That is invisible to a path-set comparison
    and immediate to a caller.

    Only ``name``/``in``/``required``/``type``/``default`` are kept, plus
    ``ref``/``enum`` for a parameter whose schema is a component
    (:func:`_describe`). The full JSON Schema carries generated ``title``
    strings derived from the handler's own function name, which differ
    between two correct implementations and would make every route diff.
    """
    out = []
    for prm in op.get("parameters") or []:
        schema = prm.get("schema") or {}
        entry = {
            "name": prm.get("name"),
            "in": prm.get("in"),
            "required": bool(prm.get("required", False)),
            **_describe(schema, schemas),
        }
        if "default" in schema:
            entry["default"] = schema["default"]
        out.append(entry)
    out.sort(key=lambda p: (str(p["in"]), str(p["name"])))
    return out


def _any_of_type(schema: dict[str, Any]) -> Any:
    """The type of an ``anyOf`` schema, which is how Optional[...] renders.

    ``Optional[int]`` becomes ``anyOf: [{type: integer}, {type: null}]`` with
    no top-level ``type``; reading only ``schema["type"]`` reports None for
    every optional parameter and makes them all compare equal.
    """
    variants = schema.get("anyOf")
    if not variants:
        return None
    types = sorted(v.get("type") for v in variants if v.get("type"))
    return types[0] if len(types) == 1 else types or None


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
