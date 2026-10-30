"""Hardware-side classes may read only ``DriverHostPort`` members off their host.

A driver, poller or executor reaches its host through ``<x>.base`` or
``<x>._base_hook``. This gate walks every class deriving (transitively, by base
name) from ``Executor``, ``HelaoDriver`` or ``DriverPoller`` and fails on

* ``<expr>.base.X`` / ``<expr>._base_hook.X`` where ``X`` is not a
  ``DriverHostPort`` member,
* ``getattr``/``hasattr`` of such an expression with a literal ``X`` that is not a
  member,
* a bare ``<expr>.base`` / ``<expr>._base_hook`` passed as a call argument, except
  as the first argument of ``getattr``/``hasattr`` (the rule above judges the
  literal name there).

The allowed set is read off the Protocol, so ``DriverHostPort`` is the single
source. Endpoint closures in ``makeApp`` / ``*_dyn_endpoints`` are not classes and
are not scanned. The scanner takes paths so the mutation checks run on scratch
files and never edit a tracked driver.
"""

import ast
from pathlib import Path
from typing import Final

from helao.hexagon.ports.hardware import DriverHostPort

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
ROOTS: Final[tuple[str, ...]] = (
    "helao/deploy/hte",
    "helao/hexagon/adapters/native",
    "helao/core/drivers",
)
SEEDS: Final[frozenset[str]] = frozenset({"Executor", "HelaoDriver", "DriverPoller"})
HOST_ATTRS: Final[frozenset[str]] = frozenset({"base", "_base_hook"})
ALLOWED: Final[frozenset[str]] = frozenset(
    n for n in vars(DriverHostPort) if not n.startswith("_")
)


def _source_files() -> list[Path]:
    return [
        p
        for root in ROOTS
        for p in sorted((REPO_ROOT / root).rglob("*.py"))
        if "__pycache__" not in p.parts and "tests" not in p.parts
    ]


def _is_host(e: ast.AST) -> bool:
    return isinstance(e, ast.Attribute) and e.attr in HOST_ATTRS


def _is_host_getattr(e: ast.AST) -> bool:
    """``getattr(<x>, "base"|"_base_hook"[, default])``."""
    return (
        isinstance(e, ast.Call)
        and isinstance(e.func, ast.Name)
        and e.func.id == "getattr"
        and len(e.args) > 1
        and isinstance(e.args[1], ast.Constant)
        and e.args[1].value in HOST_ATTRS
    )


def scan(paths: list[Path]) -> tuple[list[str], int, set[str]]:
    """Return ``(violations, host reads, files holding a read)`` over ``paths``."""
    classes: list[tuple[list[str], ast.ClassDef, Path]] = []
    for p in paths:
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.ClassDef):
                bases = [ast.unparse(b).split(".")[-1] for b in n.bases]
                classes.append((bases, n, p))
    known = set(SEEDS)
    # the seed classes themselves are in scope: DriverPoller reads put_lbuf off its host
    in_scope: dict[int, tuple[ast.ClassDef, Path]] = {
        id(node): (node, p) for _, node, p in classes if node.name in SEEDS
    }
    changed = True
    while changed:
        changed = False
        for bases, node, p in classes:
            if id(node) not in in_scope and any(b in known for b in bases):
                in_scope[id(node)] = (node, p)
                known.add(node.name)
                changed = True
    violations: list[str] = []
    reads = 0
    files: set[str] = set()

    def read(name: object, where: str, p: Path) -> None:
        nonlocal reads
        reads += 1
        files.add(str(p))
        if name not in ALLOWED:
            violations.append(f"{where}: host member {name!r} is not in DriverHostPort")

    for node, p in in_scope.values():
        for n in ast.walk(node):
            where = f"{p}:{getattr(n, 'lineno', 0)}"
            if isinstance(n, ast.Attribute) and _is_host(n.value):
                read(n.attr, where, p)
            if not isinstance(n, ast.Call):
                continue
            is_probe = isinstance(n.func, ast.Name) and n.func.id in (
                "getattr",
                "hasattr",
            )
            if is_probe and n.args:
                first = n.args[0]
                if _is_host(first) or _is_host_getattr(first):
                    if len(n.args) > 1 and isinstance(n.args[1], ast.Constant):
                        read(n.args[1].value, where, p)
                rest = n.args[1:]
            else:
                rest = n.args
            for a in [*rest, *(k.value for k in n.keywords)]:
                if _is_host(a):
                    violations.append(f"{where}: bare host passed as a call argument")
    return violations, reads, files


def _scratch(tmp_path: Path, body: str) -> list[Path]:
    f = tmp_path / "scratch.py"
    f.write_text(body, encoding="utf-8")
    return [f]


def test_no_forbidden_host_read() -> None:
    violations, _, _ = scan(_source_files())
    assert not violations, "\n".join(violations)


def test_the_scan_sees_every_measured_read() -> None:
    _, reads, files = scan(_source_files())
    # floor dropped by one read/file when the legacy galil_motion_driver was deleted
    assert reads >= 30 and len(files) >= 15, (reads, len(files))


def test_allowed_set_is_the_ten_members() -> None:
    assert ALLOWED == {
        "get_lbuf",
        "put_lbuf",
        "dflt_file_conn_key",
        "helaodirs",
        "actionservermodel",
        "executors",
        "server_params",
        "world_cfg",
        "poller",
        "server_key",
    }


def test_action_host_satisfies_the_port() -> None:
    from helao.hexagon.tests.test_get_status_survives_a_down_driver import _host

    assert isinstance(_host(), DriverHostPort)


def test_gate_catches_a_member_read_in_a_poller(tmp_path: Path) -> None:
    body = "class P(DriverPoller):\n    def f(self):\n        return self._base_hook.aloop\n"
    assert scan(_scratch(tmp_path, body))[0]


def test_gate_catches_the_host_passed_whole(tmp_path: Path) -> None:
    body = "class E(Executor):\n    def f(self):\n        helper(self.active.base)\n"
    assert scan(_scratch(tmp_path, body))[0]


def test_gate_catches_a_getattr_of_a_forbidden_member(tmp_path: Path) -> None:
    body = (
        "class D(HelaoDriver):\n    def f(self):\n"
        "        return getattr(self._base_hook, 'aloop', None)\n"
    )
    assert scan(_scratch(tmp_path, body))[0]


def test_gate_exempts_the_first_argument_of_getattr(tmp_path: Path) -> None:
    body = (
        "class D(HelaoDriver):\n    def f(self):\n"
        "        return getattr(self._base_hook, 'helaodirs', None)\n"
    )
    assert scan(_scratch(tmp_path, body))[0] == []
