"""Derive a fully hexagon-composed config from a legacy one.

A station's `<name>_hex` config is not a copy of `<name>` -- it *is* `<name>`,
loaded at launch and re-composed onto the hexagon app layer:

    import os
    from helao.hexagon.hexconfig import hexagon_variant

    config = hexagon_variant(os.path.join(os.path.dirname(__file__), "ccsi2.yml"))

**Why derived rather than copied.** P4f and P5g both rejected parallel hexagon
configs, for one reason: two copies of a station's real hardware params drift,
and the copy is the one nobody notices is stale. That objection is fatal to a
duplicated file and does not apply to a derived one -- ports, addresses,
channel maps and credentials exist in exactly one file, and editing the base
moves the variant with it. The cost is that the variant is not readable as a
flat document; `python -m helao.hexagon.preflight <path>` prints what it
resolves to.

**What the flip does, per server.** The composition is the only thing that
changes; `root:`, ports, `params:` and every other key are untouched, because
this is the same station writing to the same tree.

* A server whose module has a **named shim** whose hardcoded `LEGACY_MODULE`
  matches where that module really resolves gains one key: `deployment:
  hexagon`. The shim shares the legacy basename precisely so the code key does
  not move.
* Anything else routes through the **generic graft**: `<code key>: graft`,
  `deployment: hexagon`, and a `legacy_module:` naming the real target. This is
  the only route available to a deployment whose name may not appear in this
  public repo, and it is equally correct for public ones.
* An `orchestrator` entry needs no legacy target at all -- its shim calls
  `makeOrchApp`, which is core rather than deployment-specific -- so it gains
  only `deployment: hexagon`.
* A `reflex:` value names a *bundle*, not a module, so it likewise gains only
  `deployment: hexagon`; the launcher routes it through
  `HELAO_REFLEX_APP_MODULE`.

**Where a module really resolves is measured, never assumed.** The launcher
falls back to `hte` when a deployment has no module of that name, so a config
outside `hte` can legitimately be served by an `hte` module -- and a named shim
is correct only if its hardcoded target is that same module. A private
deployment carrying its own module of a colliding name must NOT get the `hte`
shim; it gets the graft. `_legacy_target` decides by file existence in the same
order the launcher searches.

**The function is strict on purpose.** A server it cannot compose raises
:class:`UnflippableServerError` rather than being left legacy, because the
whole value of these configs is that "fully hexagon" is a fact about the file
instead of a hope about it.
"""

from __future__ import annotations

import ast
import copy
import os
from typing import Optional

from helao.helpers.config_loader import read_config

__all__ = [
    "HEXAGON",
    "UnflippableServerError",
    "hexagon_variant",
    "plan_flip",
]

#: The deployment name that routes a server to `helao/deploy/hexagon/servers/`.
HEXAGON = "hexagon"

#: Config keys naming the code a server runs, in launcher order.
CODE_KEYS = ("fast", "bokeh", "reflex")

#: Deployments searched, in order, when resolving where a module really lives.
#: Mirrors the launcher's own fallback: the server's own deployment first, then
#: `hte`, then `test`.
_FALLBACK_ORDER = ("hte", "test")


class UnflippableServerError(RuntimeError):
    """A server could not be composed onto hexagon.

    Raised rather than skipped: a `_hex` config that quietly left one server
    legacy would be a mixed composition wearing a name that says otherwise,
    and the mixed case already has a representation -- flipping the base config
    per server, which is what P4f/P5g prescribe.
    """


def _repo_root() -> str:
    here = os.path.abspath(__file__)
    while os.path.basename(here) != "helao":
        here = os.path.dirname(here)
        if here == os.path.sep:
            raise FileNotFoundError("could not locate the helao repo root")
    return os.path.dirname(here)


def _shim_path(root: str, group: str, module: str) -> str:
    return os.path.join(
        root, "helao", "deploy", HEXAGON, "servers", group, f"{module}.py"
    )


def _shim_legacy_target(path: str) -> Optional[str]:
    """The `LEGACY_MODULE` a named shim hardcodes, or None if it names nothing.

    Parsed from source rather than imported: importing a shim pulls in the
    hexagon factory and, through it, whatever the legacy module imports --
    which for a hardware server means vendor SDKs that are not present on every
    platform. Reading the assignment is enough and cannot fail that way.
    """
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "LEGACY_MODULE":
                if isinstance(node.value, ast.Constant) and isinstance(
                    node.value.value, str
                ):
                    return node.value.value
    return None


def _legacy_target(
    root: str, deployment: str, group: str, module: str
) -> Optional[str]:
    """Dotted path of the module the launcher would actually import."""
    for dep in (deployment, *_FALLBACK_ORDER):
        if not dep:
            continue
        candidate = os.path.join(
            root, "helao", "deploy", dep, "servers", group, f"{module}.py"
        )
        if os.path.isfile(candidate):
            return f"helao.deploy.{dep}.servers.{group}.{module}"
    return None


def _base_deployment(base_path: str) -> str:
    """The deployment owning a config, inferred from its path the way
    `preflight` does -- `helao/deploy/<dep>/configs/<name>`."""
    parts = os.path.abspath(base_path).split(os.sep)
    try:
        return parts[parts.index("deploy") + 1]
    except (ValueError, IndexError):
        return ""


def plan_flip(config: dict, base_path: str) -> dict:
    """Return `{server_key: (code_key, value, legacy_module_or_None)}`.

    Exposed so a test can assert what a variant composes to without launching
    anything, and so `hexagon_variant` and its tests cannot disagree about the
    rule.
    """
    root = config.get("helao_repo_root") or _repo_root()
    base_dep = _base_deployment(base_path)
    plan: dict[str, tuple[str, str, Optional[str]]] = {}

    for key, server in (config.get("servers") or {}).items():
        if not isinstance(server, dict):
            continue
        code_key = next((k for k in CODE_KEYS if k in server), None)
        if code_key is None:
            continue
        if server.get("deployment") == HEXAGON:
            plan[key] = (code_key, server[code_key], server.get("legacy_module"))
            continue

        module = server[code_key]
        group = server.get("group") or "action"
        deployment = server.get("deployment") or base_dep

        # A bundle name, not a module: nothing to re-target.
        if code_key == "reflex":
            plan[key] = (code_key, module, None)
            continue

        shim = _shim_path(root, group, module)
        if os.path.isfile(shim):
            hardcoded = _shim_legacy_target(shim)
            if hardcoded is None:
                # A shim naming nothing is deployment-independent (the
                # orchestrator) -- unless it is the generic graft itself, which
                # a legacy config never names.
                if module != "graft":
                    plan[key] = (code_key, module, None)
                    continue
            elif hardcoded == _legacy_target(root, deployment, group, module):
                plan[key] = (code_key, module, None)
                continue

        target = _legacy_target(root, deployment, group, module)
        if target is None:
            raise UnflippableServerError(
                f"server {key!r} names {group}/{module!r}, which does not exist "
                f"under deployment {deployment!r}, 'hte' or 'test'; cannot "
                f"resolve a legacy target for the hexagon graft"
            )
        if not os.path.isfile(_shim_path(root, group, "graft")):
            raise UnflippableServerError(
                f"server {key!r} needs the generic graft, but no graft exists "
                f"for group {group!r} (have: "
                f"{sorted(os.listdir(os.path.dirname(_shim_path(root, group, 'x'))))})"
            )
        plan[key] = (code_key, "graft", target)
    return plan


def hexagon_variant(base_path: str) -> dict:
    """Load `base_path` and return it composed entirely onto hexagon.

    Args:
        base_path: Path to the legacy config this variant derives from.

    Returns:
        The config dict, with every server carrying `deployment: hexagon` and
        (where the generic graft is used) a `legacy_module:`. Every other key
        is the base's, unchanged.

    Raises:
        UnflippableServerError: A server could not be composed.
    """
    config = copy.deepcopy(read_config(base_path))
    plan = plan_flip(config, base_path)
    for key, (code_key, value, legacy_module) in plan.items():
        server = config["servers"][key]
        server[code_key] = value
        server["deployment"] = HEXAGON
        if legacy_module:
            server["legacy_module"] = legacy_module
    config["hexagon_variant_of"] = os.path.abspath(base_path)
    return config
