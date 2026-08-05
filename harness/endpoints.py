"""AST route-set extractor + checklist diff (spec §8.3).

Extracts every route registered via ``@app.<method>(path, tags=[...])`` (or
``@self.<method>`` inside API classes) from a server module WITHOUT importing
it — so modules with Windows-only vendor imports extract fine on Linux, and
the frozen legacy extraction becomes the endpoint-parity checklist a later
phase's composition is diffed against.

Limits (by design, documented): decorator paths built from anything other
than constants and simple f-string ``{name}`` substitutions extract as
``{?}``; routes registered dynamically at runtime (BaseAPI system surface,
config-shaped dyn endpoints) are NOT visible statically — §8.3 pairs this
static pass with the runtime /openapi.json cross-check at preflight (P1+).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Optional

HTTP_METHODS = {"post", "get", "put", "delete", "head", "websocket"}

#: typing aliases that PEP 585 replaced with the builtin generics. Annotations
#: are extracted as literal source text, so a repo-wide PEP 585 sweep rewriting
#: ``List[float]`` to ``list[float]`` changes the recorded string while the
#: TYPE -- and therefore the FastAPI/pydantic wire schema the checklist exists
#: to gate -- is identical. Normalizing the spelling on comparison keeps the
#: frozen JSONs as verbatim records of the pre-migration legacy surface and
#: makes the gate immune to future sweeps, while still failing on any real
#: annotation change (``List[float]`` -> ``list[str]`` still diffs).
#:
#: FrozenSet precedes Set only for readability; \b already prevents matching
#: the "Set" inside "FrozenSet". Optional/Union are deliberately absent -- the
#: PEP 604 ``X | Y`` rewrite is a separate change and is not normalized here.
_PEP585_ALIASES = ("FrozenSet", "List", "Dict", "Tuple", "Set", "Type")
_PEP585_RE = re.compile(r"\b(" + "|".join(_PEP585_ALIASES) + r")\b")


def _path_str(node: ast.expr) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            elif isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name):
                parts.append("{" + v.value.id + "}")
            else:
                parts.append("{?}")
        return "".join(parts)
    return None


def _decorator_route(dec: ast.expr) -> Optional[dict]:
    if not isinstance(dec, ast.Call):
        return None
    func = dec.func
    if not (isinstance(func, ast.Attribute) and func.attr in HTTP_METHODS):
        return None
    if not dec.args:
        return None
    path = _path_str(dec.args[0])
    if path is None:
        return None
    tags: list[str] = []
    for kw in dec.keywords:
        if kw.arg == "tags" and isinstance(kw.value, ast.List):
            tags = [
                e.value
                for e in kw.value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
    return {"path": path, "method": func.attr, "tags": tags}


def _params(fn) -> list[dict]:
    out: list[dict] = []
    args = fn.args
    defaults = [None] * (len(args.args) - len(args.defaults)) + list(args.defaults)
    for a, d in zip(args.args, defaults):
        if a.arg == "self":
            continue
        out.append(
            {
                "name": a.arg,
                "annotation": ast.unparse(a.annotation) if a.annotation else None,
                "default": ast.unparse(d) if d is not None else None,
            }
        )
    return out


def extract_routes(module_path: Path, server_key: Optional[str] = None) -> list[dict]:
    tree = ast.parse(Path(module_path).read_text())
    routes: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                r = _decorator_route(dec)
                if r is None:
                    continue
                path = r["path"]
                if server_key is not None:
                    path = path.replace("{server_key}", server_key)
                routes.append(
                    {
                        "path": path,
                        "method": r["method"],
                        "tags": r["tags"],
                        "handler": node.name,
                        "params": _params(node),
                    }
                )
    return sorted(routes, key=lambda r: (r["path"], r["method"]))


def normalize_annotation(text: str) -> str:
    """An annotation with PEP 585 alias spelling folded to the builtin generics.

    ``List[float]`` -> ``list[float]``. Public because two callers must agree
    exactly on what counts as a spelling-only difference: this module's diff (so
    the gate ignores a typing sweep) and the freezer (so it keeps the frozen
    verbatim text when only the spelling moved). A second implementation would
    drift.
    """
    return _PEP585_RE.sub(lambda m: m.group(1).lower(), text)


def diff_route_sets(frozen: list[dict], current: list[dict]) -> list[dict]:
    """Checklist diff: every frozen route present with equal schema, no extras."""

    def key(r: dict):
        return (r["path"], r["method"])

    def norm(field: str, value):
        """Compare ``params`` with PEP 585 alias spelling normalized away."""
        if field != "params" or not isinstance(value, list):
            return value
        return [
            (
                {
                    k: (
                        normalize_annotation(v)
                        if k == "annotation" and isinstance(v, str)
                        else v
                    )
                    for k, v in p.items()
                }
                if isinstance(p, dict)
                else p
            )
            for p in value
        ]

    fmap = {key(r): r for r in frozen}
    cmap = {key(r): r for r in current}
    diffs: list[dict] = []
    for k in sorted(set(fmap) - set(cmap)):
        diffs.append({"path": k[0], "method": k[1], "kind": "missing"})
    for k in sorted(set(cmap) - set(fmap)):
        diffs.append({"path": k[0], "method": k[1], "kind": "extra"})
    for k in sorted(set(fmap) & set(cmap)):
        f, c = fmap[k], cmap[k]
        for field in ("tags", "params"):
            if norm(field, f[field]) != norm(field, c[field]):
                diffs.append(
                    {
                        "path": k[0],
                        "method": k[1],
                        "kind": "changed",
                        "field": field,
                        "frozen": f[field],
                        "current": c[field],
                    }
                )
    return diffs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m harness.endpoints")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_ext = sub.add_parser("extract")
    p_ext.add_argument("module", type=Path)
    p_ext.add_argument("--server-key", default=None)
    p_ext.add_argument("--out", type=Path, default=None)
    p_diff = sub.add_parser("diff")
    p_diff.add_argument("frozen", type=Path)
    p_diff.add_argument("current", type=Path)
    args = parser.parse_args(argv)
    if args.cmd == "extract":
        routes = extract_routes(args.module, server_key=args.server_key)
        text = json.dumps(routes, indent=2)
        if args.out:
            args.out.write_text(text)
        else:
            print(text)
        return 0
    frozen = json.loads(args.frozen.read_text())
    current = json.loads(args.current.read_text())
    diffs = diff_route_sets(frozen, current)
    for d in diffs:
        print(json.dumps(d))
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
