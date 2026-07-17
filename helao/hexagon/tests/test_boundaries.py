"""AST boundary test for helao/hexagon (master spec §4.1).

Walks every .py file under helao/hexagon and fails the suite if a layer
imports outside its allow-list. This test exists from the first commit and
must never be weakened; allow-list changes require a spec amendment.

Layer rules:
- domain/  : stdlib (minus I/O denylist), pydantic, numpy,
             helao.core.models.*, helao.helpers.premodels,
             helao.core.helaodict, helao.core.error, helao.hexagon.domain.*
- ports/   : stdlib (minus I/O denylist), helao.hexagon.domain.*,
             helao.hexagon.ports.*, helao.core.drivers.helao_driver
             (declared exception: DriverResponse value objects, spec §4.3.1)
- adapters/: anything EXCEPT helao.hexagon.app
- app/     : anything
- tests/   : anything (fakes live here in P1a)
"""

import ast
import sys
from pathlib import Path
from typing import List, Tuple

HEXAGON_ROOT = Path(__file__).resolve().parents[1]  # .../helao/hexagon
HEXAGON_PKG = "helao.hexagon"

# stdlib modules that smuggle I/O, event loops, or concurrency into "pure"
# layers.  asyncio is banned in domain/ports on purpose: the domain is sync
# and pure; async signatures in ports need no asyncio import.
STDLIB_DENY = frozenset(
    {
        "asyncio",
        "socket",
        "ssl",
        "selectors",
        "subprocess",
        "http",
        "urllib",
        "ftplib",
        "smtplib",
        "multiprocessing",
        "threading",
        "concurrent",
    }
)

# named explicitly so a violation message is unambiguous (spec §4.1 list)
VENDOR_BANNED = frozenset(
    {
        "fastapi",
        "aiohttp",
        "httpx",
        "zmq",
        "bokeh",
        "boto3",
        "aiofiles",
        "requests",
        "websockets",
        "uvicorn",
        "starlette",
        "pyzstd",
        "psutil",
    }
)

DOMAIN_THIRD_PARTY = frozenset({"pydantic", "numpy"})

DOMAIN_ALLOW_PREFIXES: Tuple[str, ...] = (
    "helao.core.models",
    "helao.helpers.premodels",
    "helao.core.helaodict",
    "helao.core.error",
    "helao.hexagon.domain",
)

PORTS_ALLOW_PREFIXES: Tuple[str, ...] = (
    "helao.hexagon.domain",
    "helao.hexagon.ports",
    "helao.core.drivers.helao_driver",
)

_STDLIB = frozenset(sys.stdlib_module_names)


def _layer_of(pyfile: Path) -> str:
    rel = pyfile.resolve().relative_to(HEXAGON_ROOT)
    return rel.parts[0] if len(rel.parts) > 1 else "root"


def _absolutize(pyfile: Path, node: ast.ImportFrom) -> str:
    """Resolve a relative import to its absolute module path."""
    if node.level == 0:
        return node.module or ""
    rel = pyfile.resolve().relative_to(HEXAGON_ROOT)
    # package parts of the importing module (drop the filename)
    pkg = ".".join(HEXAGON_PKG.split(".") + list(rel.parts[:-1]))
    parts = pkg.split(".")
    parts = parts[: len(parts) - (node.level - 1)]
    if node.module:
        parts.append(node.module)
    return ".".join(parts)


def _imported_modules(pyfile: Path) -> List[Tuple[int, str]]:
    tree = ast.parse(pyfile.read_text(encoding="utf-8"))
    found: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            found.append((node.lineno, _absolutize(pyfile, node)))
    return found


def _allowed(module: str, layer: str) -> bool:
    top = module.split(".")[0]
    if layer in ("app", "tests", "root"):
        return True
    if layer == "adapters":
        return not (
            module == f"{HEXAGON_PKG}.app" or module.startswith(f"{HEXAGON_PKG}.app.")
        )
    # domain / ports
    if top in VENDOR_BANNED:
        return False
    if top in _STDLIB:
        return top not in STDLIB_DENY
    prefixes = DOMAIN_ALLOW_PREFIXES if layer == "domain" else PORTS_ALLOW_PREFIXES
    if layer == "domain" and top in DOMAIN_THIRD_PARTY:
        return True
    return any(module == p or module.startswith(p + ".") for p in prefixes)


def iter_violations(pyfile: Path) -> List[Tuple[int, str, str]]:
    """Return (lineno, module, layer) for every disallowed import in pyfile."""
    layer = _layer_of(pyfile)
    return [
        (lineno, module, layer)
        for lineno, module in _imported_modules(pyfile)
        if module and not _allowed(module, layer)
    ]


def _walk_layer(layer: str) -> List[Path]:
    d = HEXAGON_ROOT / layer
    return sorted(d.rglob("*.py")) if d.is_dir() else []


def test_hexagon_packages_exist():
    for layer in ("domain", "ports", "adapters", "app", "tests"):
        assert (HEXAGON_ROOT / layer / "__init__.py").is_file(), layer


def test_domain_imports_only_allowlist():
    bad = [v for f in _walk_layer("domain") for v in iter_violations(f)]
    assert not bad, f"domain boundary violations: {bad}"


def test_ports_import_only_domain_and_stdlib():
    bad = [v for f in _walk_layer("ports") for v in iter_violations(f)]
    assert not bad, f"ports boundary violations: {bad}"


def test_adapters_never_import_app():
    bad = [v for f in _walk_layer("adapters") for v in iter_violations(f)]
    assert not bad, f"adapters boundary violations: {bad}"


def test_checker_flags_banned_import(tmp_path):
    """Mutation self-test: the walker must actually catch violations."""
    victim = HEXAGON_ROOT / "domain" / "_boundary_selftest_tmp.py"
    victim.write_text("import httpx\nfrom helao.hexagon.app import x\n")
    try:
        hits = iter_violations(victim)
        assert {m for _, m, _ in hits} == {"httpx", "helao.hexagon.app"}
    finally:
        victim.unlink()


def test_checker_flags_banned_relative_import(tmp_path):
    """Mutation self-test: relative imports (node.level>0 branch of
    _absolutize) must resolve to their absolute module path and be
    classified with the same allow-list as absolute imports.

    Domain modules import sibling models via `from . import x`; this
    exercises that resolution plus a `from ..foo import y` climb past the
    domain package boundary, which must be flagged like the absolute
    equivalent `import helao.hexagon.app`.
    """
    victim = HEXAGON_ROOT / "domain" / "_boundary_selftest_rel_tmp.py"
    victim.write_text("from . import x\nfrom ..app import z\n")
    try:
        # from . import x  (level=1, no module) -> resolves to the victim's
        # own package, helao.hexagon.domain -- allowed, on the allow-list.
        # from ..app import z  (level=2) -> climbs one package above domain
        # (helao.hexagon) then appends "app" -> helao.hexagon.app -- banned.
        resolved = _imported_modules(victim)
        assert resolved == [
            (1, "helao.hexagon.domain"),
            (2, "helao.hexagon.app"),
        ]
        hits = iter_violations(victim)
        assert [(m, layer) for _, m, layer in hits] == [("helao.hexagon.app", "domain")]
    finally:
        victim.unlink()


def test_checker_allows_domain_allowlist(tmp_path):
    victim = HEXAGON_ROOT / "domain" / "_boundary_selftest_ok_tmp.py"
    victim.write_text(
        "import math\nimport pydantic\nimport numpy\n"
        "from helao.core.models.hlostatus import HloStatus\n"
        "from helao.helpers.premodels import Action\n"
        "from helao.core.helaodict import HelaoDict\n"
        "from helao.core.error import ErrorCodes\n"
    )
    try:
        assert iter_violations(victim) == []
    finally:
        victim.unlink()
