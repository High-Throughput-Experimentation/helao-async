"""Find server, visualizer and panel modules inside deployments.

One lookup for every caller: launchers, preflight, panel discovery, the freezer
and env setup. A deployment is a directory under ``helao/deploy/`` with a
``servers/`` folder. A module lives in one of three stacks, by location:

- ``app``: a ``fast:``/``bokeh:`` module at ``servers/*/<m>.py``, never
  ``servers/reflex/``.
- ``bokeh``: a Bokeh visualizer at ``servers/visualizer/<m>.py`` or
  ``servers/*/bokeh/<m>.py``.
- ``reflex``: a Reflex panel at ``servers/reflex/<m>.py`` or
  ``servers/*/reflex/<m>.py``.

A Bokeh visualizer and a Reflex panel may share a name on purpose: one config
key (``action_vis: gamry_vis``) loads whichever stack the group runs.
"""

from __future__ import annotations

__all__ = [
    "DEPLOY_ROOT",
    "STACKS",
    "AmbiguousModule",
    "deployments",
    "module_file",
    "locate",
    "import_path",
]

from pathlib import Path

import helao

DEPLOY_ROOT = Path(helao.__file__).resolve().parent / "deploy"
STACKS = ("app", "bokeh", "reflex")


class AmbiguousModule(LookupError):
    """One deployment holds two files answering to the same module name."""


def _candidates(servers: Path, module: str, stack: str) -> list[Path]:
    name = f"{module}.py"
    if stack == "app":
        return [p for p in servers.glob(f"*/{name}") if p.parent.name != "reflex"]
    if stack == "bokeh":
        return [servers / "visualizer" / name, *servers.glob(f"*/bokeh/{name}")]
    if stack == "reflex":
        return [servers / "reflex" / name, *servers.glob(f"*/reflex/{name}")]
    raise ValueError(f"unknown stack {stack!r}; expected one of {STACKS}")


def deployments(deploy_root: Path = DEPLOY_ROOT) -> list[str]:
    """Names of the deployments under ``deploy_root`` that have ``servers/``."""
    if not deploy_root.is_dir():
        return []
    return sorted(d.name for d in deploy_root.iterdir() if (d / "servers").is_dir())


def module_file(
    deployment: str, module: str, stack: str, deploy_root: Path = DEPLOY_ROOT
) -> Path | None:
    """The one file in ``deployment`` for ``module`` in ``stack``, or ``None``.

    Raises:
        AmbiguousModule: two files in the deployment answer to the name.
    """
    servers = deploy_root / deployment / "servers"
    files = sorted({p for p in _candidates(servers, module, stack) if p.is_file()})
    if len(files) > 1:
        raise AmbiguousModule(
            f"deployment {deployment!r} has {len(files)} {stack} modules named "
            f"{module!r}: " + ", ".join(str(p) for p in files)
        )
    return files[0] if files else None


def locate(
    module: str, stack: str, own: str | None = None, deploy_root: Path = DEPLOY_ROOT
) -> tuple[str | None, list[str]]:
    """Deployment to load ``module`` from, and every deployment that has it.

    ``own`` wins when it has the module; otherwise the only deployment that has
    it. Returns ``(None, candidates)`` when none or several (none ``own``) do;
    the caller decides whether that is an error.
    """
    found = [
        d
        for d in deployments(deploy_root)
        if module_file(d, module, stack, deploy_root)
    ]
    if own in found:
        return own, found
    if len(found) == 1:
        return found[0], found
    return None, found


def import_path(path: Path, deploy_root: Path = DEPLOY_ROOT) -> str:
    """Dotted import path of a module file under ``deploy_root``."""
    rel = path.resolve().relative_to(deploy_root.resolve()).with_suffix("")
    return ".".join(("helao", "deploy", *rel.parts))
