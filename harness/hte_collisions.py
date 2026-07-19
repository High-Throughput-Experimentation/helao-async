"""Flat-namespace collision scanner for hte exp/seq libraries (spec §4.3.12).

The Library port registers experiment/sequence functions in a flat name-keyed
dict; two modules defining the same top-level function name silently shadow
under one config's *_libraries list. This surfaces those collisions loudly so
the P3c load-time collision check has a frozen expected set.
"""

from __future__ import annotations
import ast
from collections import defaultdict
from pathlib import Path


def _top_level_funcs(module_path: Path) -> list[str]:
    tree = ast.parse(module_path.read_text())
    return [
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def scan_collisions(lib_dir: Path) -> dict[str, list[str]]:
    name_to_modules: dict[str, list[str]] = defaultdict(list)
    for f in sorted(Path(lib_dir).glob("*.py")):
        if f.name == "__init__.py":
            continue
        for fn in _top_level_funcs(f):
            name_to_modules[fn].append(f.name)
    return {n: m for n, m in name_to_modules.items() if len(m) >= 2}
