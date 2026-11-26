"""Only ActionModel.set_output writes action_output (spec §4.2)."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ALLOWED = {("helao/core/models/action.py", "set_output")}


def _hits(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    scopes = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                scopes.setdefault(id(node), fn.name)
    for node in ast.walk(tree):
        bad = False
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                base = t.value if isinstance(t, ast.Subscript) else t
                if isinstance(base, ast.Attribute) and base.attr == "action_output":
                    bad = True
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if (
                node.func.attr in {"update", "setdefault", "pop", "clear"}
                and isinstance(owner, ast.Attribute)
                and owner.attr == "action_output"
            ):
                bad = True
        if bad:
            yield node.lineno, scopes.get(id(node), "<module>")


def test_action_output_has_one_writer():
    found = []
    for path in sorted((ROOT / "helao").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if "/tests/" in rel or "/notes/" in rel:
            continue
        for line, scope in _hits(path):
            if (rel, scope) not in ALLOWED:
                found.append(f"{rel}:{line} ({scope})")
    assert not found, "write action_output via set_output:\n" + "\n".join(found)
