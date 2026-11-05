"""List module names found in more than one deployment.

Run before the resolver stops preferring one deployment by name: a collision a
config relies on must be settled first (an explicit ``deployment:`` key, an
explicit library path, or a rename).

    python -m harness.deploy_collisions
"""

from __future__ import annotations

import sys
from pathlib import Path

from helao.helpers.server_modules import DEPLOY_ROOT, deployments

_GLOBS = {
    "processors": ("processors/*.py",),
    "experiments": ("experiments/*.py",),
    "sequences": ("sequences/*.py",),
    "bokeh": ("servers/visualizer/*.py", "servers/*/bokeh/*.py"),
    "reflex": ("servers/reflex/*.py", "servers/*/reflex/*.py"),
}


def collisions(deploy_root: Path = DEPLOY_ROOT) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for kind, patterns in _GLOBS.items():
        seen: dict[str, set[str]] = {}
        for dep in deployments(deploy_root):
            for pattern in patterns:
                for p in (deploy_root / dep).glob(pattern):
                    if not p.name.startswith("_"):
                        seen.setdefault(p.stem, set()).add(dep)
        out[kind] = {n: sorted(d) for n, d in sorted(seen.items()) if len(d) > 1}
    return out


def main() -> int:
    found = collisions()
    for kind, names in found.items():
        for name, deps in names.items():
            print(f"{kind}: {name} in {deps}")
    return 1 if any(found.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
