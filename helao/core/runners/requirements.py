"""What a runner needs from the group's action servers (spec: Requirement check).

Pure functions: no network, no Reflex. The page gathers endpoints and status;
the launcher's ``--describe`` calls :func:`inferred`.
"""

import ast
from typing import Optional

ACT_HELPERS = ("_act", "make_action")


def _lit(node) -> Optional[str]:
    return (
        node.value
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        else None
    )


def _add(out: dict, server, action) -> None:
    if server and action:
        names = out.setdefault(server, [])
        if action not in names:
            names.append(action)


def inferred(source: str) -> dict:
    """``{server: [action, ...]}`` from literal action-building calls; ``{}`` if unparsable."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    out: dict = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name in ACT_HELPERS and len(node.args) >= 2:
            _add(out, _lit(node.args[0]), _lit(node.args[1]))
        elif name == "Action":
            kw = {k.arg: k.value for k in node.keywords}
            action = _lit(kw.get("action_name"))
            server = None
            srv = kw.get("action_server")
            if isinstance(srv, ast.Call):
                skw = {k.arg: k.value for k in srv.keywords}
                server = _lit(skw.get("server_name"))
            _add(out, server, action)
    return out


def _busy(status: Optional[dict]) -> bool:
    """Server-level: any endpoint with an active action."""
    eps = (status or {}).get("endpoints") or {}
    return any(ep.get("active_dict") for ep in eps.values())


def check(requires, world_cfg, endpoints, status, *, inferred_only=False) -> list:
    """One row per required (server, action); see the module docstring."""
    servers = (world_cfg or {}).get("servers") or {}
    rows = []
    for server, actions in (requires or {}).items():
        if isinstance(actions, str):
            actions = [actions]
        eps = (endpoints or {}).get(server)
        st = (status or {}).get(server)
        for action in actions:
            in_config = server in servers
            reachable = eps is not None
            has_endpoint = reachable and action in eps
            estopped = bool((st or {}).get("estop"))
            busy = _busy(st)
            failed = not (in_config and reachable and has_endpoint) or estopped
            verdict = "fail" if failed else ("warn" if busy else "ok")
            if inferred_only and verdict == "fail":
                verdict = "warn"
            rows.append(
                {
                    "server": server,
                    "action": action,
                    "in_config": in_config,
                    "reachable": reachable,
                    "has_endpoint": has_endpoint,
                    "estopped": estopped,
                    "busy": busy,
                    "verdict": verdict,
                }
            )
    return rows
