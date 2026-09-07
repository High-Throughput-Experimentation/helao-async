"""`olecom_client.py` is the only module that imports comtypes, and only lazily.

Everything else in the OLE package must import and construct on Linux, where
comtypes does not exist -- which is where every test in the package runs. An
import added to driver.py or sim.py would not fail loudly; it would make the
whole package uncollectable, and the failure would read as "the tests are
broken" rather than "the isolation broke".

Checked by parsing imports, not by grepping source: several modules carry
docstrings explaining this rule, and a text search would flag the
documentation that exists to prevent the problem.
"""

import ast
from pathlib import Path

OLE = Path("helao/deploy/hte/drivers/pstat/biologic_ole")
ALLOWED = {"olecom_client.py"}
VENDOR_PREFIXES = ("comtypes", "win32com", "pythoncom", "pywintypes")


def _imports(path: Path) -> set[str]:
    """Every module name this file imports, however it spells the import."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level + (node.module or "")
            names.add(prefix)
            names.update(f"{prefix}.{a.name}".lstrip(".") for a in node.names)
    return names


def _module_scope_imports(path: Path) -> set[str]:
    """Only the imports at module scope -- the ones that run on import."""
    names: set[str] = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add("." * node.level + (node.module or ""))
    return names


def test_only_the_client_imports_a_com_package():
    offenders = []
    for path in sorted(OLE.glob("*.py")):
        if path.name in ALLOWED:
            continue
        if any(name.startswith(VENDOR_PREFIXES) for name in _imports(path)):
            offenders.append(path.name)
    assert offenders == [], f"{offenders} must not import a COM package"


def test_the_client_imports_comtypes_but_not_at_module_scope():
    """A guard that passes because the target moved is not a guard.

    And a module-scope import in the client itself would defeat the whole
    thing: the package imports the client.
    """
    path = OLE / "olecom_client.py"
    assert any(name.startswith("comtypes") for name in _imports(path))
    assert not any(
        name.startswith(VENDOR_PREFIXES) for name in _module_scope_imports(path)
    )


def test_nothing_in_the_package_imports_easy_biologic():
    """The two backends must not acquire a dependency on each other."""
    offenders = [
        path.name
        for path in sorted(OLE.glob("*.py"))
        if any(name.startswith("easy_biologic") for name in _imports(path))
    ]
    assert offenders == [], offenders


def test_the_pure_modules_import_no_sibling_that_touches_com():
    """mps_template, technique, status and mps_assemble stay COM-free."""
    for name in ("mps_template.py", "technique.py", "status.py", "mps_assemble.py"):
        imports = _imports(OLE / name)
        assert not any("olecom_client" in imported for imported in imports), name
        assert not any("sim" == imported for imported in imports), name


def test_the_package_was_actually_scanned():
    """A sweep of an empty directory passes vacuously."""
    assert len(list(OLE.glob("*.py"))) >= 8, sorted(p.name for p in OLE.glob("*.py"))
