"""Static validation of the experiment/sequence library export contract.

``import_autolibs`` publishes a library module's callables by reading a
module-level list named after the library type::

    for func in tempd.get(f"{lib_type.upper()}S", []):   # import_autolibs.py

That ``.get(..., [])`` is the reason this module exists. A library file whose
list is **missing or misnamed** yields an empty sequence, so the loop body never
runs and the module contributes **zero** experiments -- with no exception and no
log line, because the only error branch fires for a name that is listed but not
defined. The failure surfaces at the bench as an experiment quietly absent from
the operator's dropdown, which is a miserable thing to debug.

Checks are AST-only and never import the module under test. That is a hard
requirement, not an optimization: library modules legitimately fail to import
away from their station (vendor SDKs such as ``pyAndorSDK3``, and at least one
private-deployment sequence that reaches for AWS credentials at import time),
so an import-based check would report those environments as broken.

Deployment-agnostic by design -- callers pass their own root, so each
deployment (including private ones, which this repo must not name) opts itself
in from its own test suite.
"""

import ast
from pathlib import Path

__all__ = ["EXPECTED_LIST", "check_library_exports", "iter_library_files"]

#: filename suffix -> the module-level list name ``import_autolibs`` will read
EXPECTED_LIST = {"_exp.py": "EXPERIMENTS", "_seq.py": "SEQUENCES"}


def iter_library_files(root: Path):
    """Yield ``(path, expected_list_name)`` for every library module under ``root``.

    Recurses, so archived subdirectories are covered. Any path with a ``notes``
    component is skipped: those are scratch/reference trees, not libraries the
    orchestrator loads.
    """
    for subdir, suffix in (("experiments", "_exp.py"), ("sequences", "_seq.py")):
        base = Path(root) / subdir
        if not base.is_dir():
            continue
        for path in sorted(base.rglob(f"*{suffix}")):
            if "notes" in path.parts:
                continue
            yield path, EXPECTED_LIST[suffix]


def check_library_exports(root: Path) -> list[str]:
    """Return a list of human-readable problems for library modules under ``root``.

    Empty list means every library module under ``root`` exposes a list
    ``import_autolibs`` can actually read. Checked per file:

    - the correctly-named list exists at module level;
    - its value is a **list literal**, not a reference -- this is what rejects
      the old ``EXPERIMENTS = __all__`` indirection, and any other alias that
      would put the real names somewhere a reader does not expect;
    - it is non-empty (an empty library is almost always an accident, and is
      indistinguishable from a missing one at load time);
    - every element is a plain string;
    - every listed name is defined in the module, mirroring the one condition
      ``import_autolibs`` does report -- but at test time rather than at launch;
    - no module-level ``__all__`` remains, since the export list is now the
      single source of truth and a stale ``__all__`` invites the two drifting.
    """
    problems: list[str] = []
    for path, expected in iter_library_files(root):
        rel = path.name
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError as exc:
            problems.append(f"{rel}: SyntaxError: {exc}")
            continue

        assigns = {
            node.targets[0].id: node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        }

        if "__all__" in assigns:
            problems.append(
                f"{rel}: still defines __all__; {expected} is the single source "
                "of truth for what the orchestrator publishes"
            )

        node = assigns.get(expected)
        if node is None:
            other = next((n for n in EXPECTED_LIST.values() if n in assigns), None)
            hint = f" (found {other} instead)" if other else ""
            problems.append(
                f"{rel}: no module-level {expected}{hint} -- import_autolibs "
                "would publish nothing from this module, silently"
            )
            continue

        if not isinstance(node.value, ast.List):
            kind = type(node.value).__name__
            problems.append(
                f"{rel}: {expected} is a {kind}, not a list literal -- the names "
                "must be written where a reader (and this check) can see them"
            )
            continue

        if not node.value.elts:
            problems.append(f"{rel}: {expected} is empty")
            continue

        names, bad = [], []
        for elt in node.value.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                names.append(elt.value)
            else:
                bad.append(ast.unparse(elt))
        if bad:
            problems.append(f"{rel}: {expected} has non-string entries: {bad}")

        defined = {
            n.name
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        missing = [n for n in names if n not in defined]
        if missing:
            problems.append(
                f"{rel}: {expected} lists names the module does not define: {missing}"
            )
    return problems
