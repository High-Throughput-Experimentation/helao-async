"""Framework code names no deployment: no hte import, no hte path or module literal."""

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ROOTS = [
    "helao/core",
    "helao/hexagon",
    "helao/helpers",
    "helao/ui",
    "harness",
    "helao/deploy/base",
]
FILES = [
    "fast_launcher.py",
    "bokeh_launcher.py",
    "reflex_launcher.py",
    "launch.py",
    "run_tests.py",
    "helao_env.py",
]
IMPORT = re.compile(r"helao\.deploy\.hte\b")
HTE = re.compile(r"""helao\.deploy\.hte\b|deploy[/\\]hte\b|^hte$""")
# data label on records (``access``), not a deployment reference
ALLOWED_FIELD = {"access"}
# env bootstrap: clones/pulls the public hte deployment repo (spec 2026-11-10 §3)
EXEMPT_FILES = {"helao_env.py"}


def _py_files():
    for root in ROOTS:
        yield from (REPO / root).rglob("*.py")
    for name in FILES:
        if (REPO / name).exists():
            yield REPO / name


def _hits(path: Path) -> list[str]:
    if path.name in EXEMPT_FILES and path.parent == REPO:
        return []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # resolver tests use the real hte deployment as fixture data
    in_tests = "tests" in path.relative_to(REPO).parts
    allowed = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in ALLOWED_FIELD and isinstance(node.value, ast.Constant):
                allowed.add(id(node.value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            else:  # also ``from helao.deploy import hte``
                names = [node.module or ""] + [
                    f"{node.module}.{a.name}" for a in node.names
                ]
            out += [f"import {n}" for n in names if IMPORT.match(n)]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if in_tests or id(node) in allowed:
                continue
            if HTE.search(node.value):
                out.append(repr(node.value))
    return [f"{path.relative_to(REPO)}:{h}" for h in out]


def test_framework_names_no_deployment():
    hits = [h for f in _py_files() for h in _hits(f)]
    assert not hits, "\n".join(hits)
