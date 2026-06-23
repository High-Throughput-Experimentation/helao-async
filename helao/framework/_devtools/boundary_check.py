"""AST-based import-boundary checker for the hexagonal layering.

`domain/` is pure and must not import I/O frameworks or the adapters/app layers.
"""
import ast
from pathlib import Path
from typing import Iterable

# Module prefixes the domain layer must never import.
DOMAIN_FORBIDDEN: set[str] = {
    "fastapi",
    "starlette",
    "uvicorn",
    "httpx",
    "aiohttp",
    "requests",
    "bokeh",
    "panel",
    "aiofiles",
    "boto3",
    "shutil",
    "ruamel",
    "helao.framework.adapters",
    "helao.framework.app",
}


def _matches(module: str, forbidden: Iterable[str]) -> str | None:
    """Return `module` if it violates any forbidden prefix, else None.

    Matching is on dotted-path boundaries: prefix 'os' matches 'os' and
    'os.path' but not 'osmosis'.
    """
    for prefix in forbidden:
        if module == prefix or module.startswith(prefix + "."):
            return module
    return None


def find_forbidden_imports(source: str, forbidden: Iterable[str]) -> list[str]:
    """Parse `source` and return the imported module names that are forbidden.

    Names are returned in source order; the returned value is the *imported*
    dotted name (e.g. 'helao.framework.adapters.fakes'), not the matched prefix.
    """
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                hit = _matches(alias.name, forbidden)
                if hit is not None:
                    found.append(hit)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None or node.level != 0:
                continue  # relative imports stay within the package; allowed
            hit = _matches(node.module, forbidden)
            if hit is not None:
                found.append(hit)
    return found


def scan_dir(directory: Path, forbidden: Iterable[str]) -> dict[str, list[str]]:
    """Scan every .py file under `directory`; return {relpath: [violations]}.

    Files with no violations are omitted. Missing directory yields {}.
    """
    forbidden = set(forbidden)
    results: dict[str, list[str]] = {}
    if not directory.exists():
        return results
    for path in sorted(directory.rglob("*.py")):
        violations = find_forbidden_imports(path.read_text(encoding="utf-8"), forbidden)
        if violations:
            results[str(path)] = violations
    return results
