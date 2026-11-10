"""Shared logic of a deployment's frozen action-route gate, and its anti-vacuity guards.

A deployment keeps ``tests/checklists/`` (a ``servers.json`` manifest, one
frozen ``<module>.json`` per module, ``_additions.json`` for deliberate new
routes, optionally ``_param_additions.json``). Its ``test_route_checklist.py``
calls these functions, so every deployment with a gate gets the same checks and
the same guards against a gate that passes over nothing: a by-name population
check, well-formedness of every addition, and stale-addition detection.

Never regenerate the frozen JSONs (``python -m harness.freeze``): a regenerated
record is the current source's own output and proves nothing.
"""

import json
from pathlib import Path
from typing import Optional

from harness.endpoints import (
    diff_route_sets,
    extract_routes,
    filter_allowed_additions,
    filter_allowed_param_additions,
)
from harness.freeze import load_manifest
from helao.helpers.server_modules import module_file


def load_servers(out: Path) -> list[tuple[str, Optional[str]]]:
    """(module filename, representative server_key) from the frozen manifest."""
    return [(e["module"], e["representative_key"]) for e in load_manifest(out)]


def module_path(deployment: str, filename: str) -> Path:
    """The action module file for ``filename`` (``andor_server.py``) in a deployment."""
    path = module_file(deployment, Path(filename).stem, "app")
    if path is None:
        raise FileNotFoundError(f"{deployment} has no action module {filename!r}")
    return path


def load_additions(out: Path) -> list[dict]:
    return json.loads((out / "_additions.json").read_text(encoding="utf-8"))


def load_param_additions(out: Path) -> list[dict]:
    """``_param_additions.json`` is optional; a deployment without one has none."""
    p = out / "_param_additions.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def missing_module_checklists(
    servers: list[tuple[str, Optional[str]]], directory: Path
) -> list[str]:
    """Modules in ``servers`` with no frozen checklist in ``directory``.

    ``_*.json`` never counts, and neither does ``servers.json`` (the
    module-to-server_key manifest), which is why this answers by NAME rather
    than by count: two non-checklists in the directory are two deletions a
    bare count would absorb.
    """
    present = {p.name for p in directory.glob("*.json") if not p.name.startswith("_")}
    return [m for m, _ in servers if (Path(m).stem + ".json") not in present]


def module_diffs(
    deployment: str, out: Path, module: str, server_key: Optional[str]
) -> list[dict]:
    """Route diffs of ``module`` against its frozen checklist, additions applied."""
    frozen = json.loads((out / (Path(module).stem + ".json")).read_text("utf-8"))
    current = extract_routes(module_path(deployment, module), server_key=server_key)
    diffs, _ = filter_allowed_additions(
        diff_route_sets(frozen, current),
        [a for a in load_additions(out) if a["module"] == module],
    )
    diffs, _ = filter_allowed_param_additions(
        diffs, [a for a in load_param_additions(out) if a["module"] == module]
    )
    return diffs


def malformed_additions(
    out: Path, servers: list[tuple[str, Optional[str]]]
) -> list[str]:
    """Entries without ``why``/date/etc., or naming a module outside ``servers``."""
    modules = {m for m, _ in servers}
    bad = []
    for entry in load_additions(out):
        missing = {"module", "path", "method", "date", "why"} - set(entry)
        if missing:
            bad.append(f"{entry} is missing {sorted(missing)}")
        elif not entry["why"].strip():
            bad.append(f"{entry['path']} has an empty `why`")
        elif entry["module"] not in modules:
            bad.append(f"{entry['module']} is not a module of this gate")
    return bad


def unresolved_additions(
    deployment: str, out: Path, servers: list[tuple[str, Optional[str]]]
) -> list[str]:
    """Listed additions that resolve to no route in current source.

    An entry naming a route that is gone pre-authorizes a future route at the
    same path and method, invisibly, because the gate stays green.
    """
    by_module = dict(servers)
    gone = []
    for entry in load_additions(out):
        current = extract_routes(
            module_path(deployment, entry["module"]),
            server_key=by_module[entry["module"]],
        )
        if (entry["path"], entry["method"]) not in {
            (r["path"], r["method"]) for r in current
        }:
            gone.append(f"{entry['path']} ({entry['method']}) in {entry['module']}")
    return gone


def frozen_totals(
    out: Path, servers: list[tuple[str, Optional[str]]]
) -> tuple[int, int]:
    """(action, private) route counts measured from the frozen JSONs."""
    action = private = 0
    for module, _ in servers:
        for route in json.loads(
            (out / (Path(module).stem + ".json")).read_text("utf-8")
        ):
            if "action" in route["tags"]:
                action += 1
            elif "private" in route["tags"]:
                private += 1
    return action, private
