"""Every record write outside the finalization seam logs a rehash (spec §5).

A scope (function, or a module's top level with class bodies and ``__main__``
blocks) that references a record writer must also reference a hasher.
References count, not just calls, so ``functools.partial(write_meta, ...)`` and
``asyncio.to_thread(write_meta, ...)`` are caught; ``from m import write_meta
as wm`` is resolved from the module's imports.
"""

import ast
import subprocess
from pathlib import Path

WRITERS = {"write_meta", "dumps_meta", "yml_dumps", "writestr"}
HASHERS = {"log_artifact_hashes", "log_artifact_hashes_sync"}
# (file, scope) -> why no rehash is needed there. Every entry must still match
# a real hit (test_allowlist_has_no_stale_entries).
ALLOW = {
    (
        "helao/core/drivers/data/analysis_layout.py",
        "write_model_json",
    ): "hashed at the end of publish_outputs, which every analysis publish calls",
    (
        "helao/helpers/meta_io.py",
        "dumps_meta",
    ): "the serializer itself; each caller rehashes or is listed here",
    (
        "helao/helpers/meta_io.py",
        "write_meta",
    ): "the writer itself; each caller rehashes or is listed here",
    (
        "helao/core/runners/micro_orch.py",
        "zip_runs",
    ): "builds a new export archive from already-hashed records; writestr adds only MANIFEST.txt",
    (
        "helao/hexagon/adapters/native/data_file.py",
        "init_datafile",
    ): "builds the YAML preamble of the data file body; hashed at action finalization",
    (
        "helao/hexagon/adapters/native/data_file.py",
        "log_data_set_output_file",
    ): "data .meta.json header, rewritten on every write; hashed at action finalization",
    (
        "helao/hexagon/adapters/native/data_file.py",
        "write_file",
    ): "data .meta.json header, rewritten on every write; hashed at action finalization",
    (
        "helao/hexagon/adapters/native/data_file.py",
        "write_file_nowait",
    ): "data .meta.json header, rewritten on every write; hashed at action finalization",
    (
        "helao/hexagon/adapters/native/posthoc_writer.py",
        "write_file",
    ): "data .meta.json header; hashed at action finalization",
    (
        "helao/hexagon/adapters/native/sync_driver.py",
        "write_meta",
    ): "dead method, no callers",
    (
        "helao/hexagon/adapters/native/sync_driver.py",
        "write_dict",
    ): "the .prg progress sidecar, not a record",
}

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _aliases(tree) -> dict:
    """Local name -> imported name, for ``from m import x as y``."""
    return {
        a.asname: a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
        for a in n.names
        if a.asname
    }


def _own_nodes(scope):
    """Nodes of ``scope`` without descending into nested function definitions."""
    stack = list(
        ast.iter_child_nodes(scope) if not isinstance(scope, _SCOPES) else scope.body
    )
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, _SCOPES):
            stack.extend(ast.iter_child_nodes(n))


def _called(scope, aliases=None) -> set:
    """Names referenced in ``scope`` (calls and bare references), aliases resolved."""
    aliases = aliases or {}
    names = set()
    for n in _own_nodes(scope):
        name = (
            n.id
            if isinstance(n, ast.Name)
            else n.attr if isinstance(n, ast.Attribute) else None
        )
        if name:
            names.add(aliases.get(name, name))
    return names


def scan_source(src: str) -> list:
    """``(scope name, lineno)`` of every scope with a writer and no hasher."""
    tree = ast.parse(src)
    aliases = _aliases(tree)
    out = []
    scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, _SCOPES)]
    for scope in scopes:
        called = _called(scope, aliases)
        if called & WRITERS and not called & HASHERS:
            out.append(("<module>", 1) if scope is tree else (scope.name, scope.lineno))
    return out


def _files():
    root = Path(__file__).resolve().parents[3]
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "*.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [
        (root, p)
        for p in out.split()
        if not Path(p).name.startswith(("test_", "unit_test_"))
        and not Path(p).name.endswith("_fixtures.py")
        and not p.startswith("harness/")
        and "/smoke/" not in p
    ]


def _all_hits():
    return {
        (path, name): lineno
        for root, path in _files()
        for name, lineno in scan_source((root / path).read_text(encoding="utf-8"))
    }


def test_record_writes_rehash_or_are_allowlisted():
    bad = [f"{p}:{ln} {n}" for (p, n), ln in _all_hits().items() if (p, n) not in ALLOW]
    assert not bad, "record write without log_artifact_hashes:\n" + "\n".join(bad)


def test_allowlist_has_no_stale_entries():
    stale = sorted(set(ALLOW) - set(_all_hits()))
    assert not stale, f"ALLOW entries no longer matched by a real hit: {stale}"


def test_gate_catches_planted_sites():
    planted = {
        "plain": "def f(p, d):\n    write_meta(p, d)\n",
        "attr": "def f(p, d):\n    meta_io.write_meta(p, d)\n",
        "alias": "from m import write_meta as wm\ndef f(p, d):\n    wm(p, d)\n",
        "module level": "write_meta('x-act.json', {})\n",
        "main block": "if __name__ == '__main__':\n    write_meta('x', {})\n",
        "class body": "class C:\n    write_meta('x', {})\n",
        "partial": "def f(p):\n    return functools.partial(write_meta, p)\n",
        "to_thread": "async def f(p, d):\n    await asyncio.to_thread(write_meta, p, d)\n",
        "yml_dumps": "def f(p, d):\n    open(p, 'w').write(yml_dumps(d))\n",
        "dumps_meta": "def f(p, d):\n    open(p, 'w').write(dumps_meta(d, p))\n",
        "writestr": "def f(z, n, b):\n    z.writestr(n, b)\n",
        "nested write, outer hash": (
            "def f(p, d):\n    def g():\n        write_meta(p, d)\n    g()\n"
            "    log_artifact_hashes_sync([p], kind='a', owner_uuid=None)\n"
        ),
    }
    for label, src in planted.items():
        assert scan_source(src), label
    hashed = "def f(p, d):\n    write_meta(p, d)\n    log_artifact_hashes_sync([p])\n"
    assert scan_source(hashed) == []
