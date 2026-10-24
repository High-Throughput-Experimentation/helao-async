"""`spectrograph.py` is the only module that IMPORTS pyAndorSpectrograph.

This is the property the whole split exists for, and it is the one that
would rot silently: an import added to driver.py or calibrated.py breaks a
spectrograph-free station at connect() and nothing else would notice on
Linux, because the package is absent here either way.

Checked by parsing imports, not by grepping source text. A grep for the
bare package name also matches the docstrings that explain the rule --
calibrated.py says "pyAndorSpectrograph need not be installed", which is
documentation, not a dependency. Import statements are the actual hazard.
"""

import ast
from pathlib import Path

ANDOR = Path("helao/deploy/hte/drivers/spec/andor")
ALLOWED = {"spectrograph.py"}


def _imported_modules(path: Path) -> set[str]:
    """Every module name this file imports, however it spells the import."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            # level>0 is a relative import; node.module is None for `from . import x`
            prefix = "." * node.level + (node.module or "")
            names.add(prefix)
            names.update(f"{prefix}.{a.name}".lstrip(".") for a in node.names)
    return names


def test_only_spectrograph_py_imports_the_vendor_package():
    offenders = []
    for path in sorted(ANDOR.glob("*.py")):
        if path.name in ALLOWED:
            continue
        if any(n.startswith("pyAndorSpectrograph") for n in _imported_modules(path)):
            offenders.append(path.name)
    assert offenders == [], f"{offenders} must not import pyAndorSpectrograph"


def test_spectrograph_py_actually_imports_it():
    """A guard that passes because the target moved is not a guard."""
    names = _imported_modules(ANDOR / "spectrograph.py")
    assert any(n.startswith("pyAndorSpectrograph") for n in names), names


def test_the_calibrated_driver_does_not_import_the_spectrograph_module():
    names = _imported_modules(ANDOR / "calibrated.py")
    assert not any("spectrograph" in n for n in names), names


def test_the_base_does_not_import_either_subclass():
    """A base importing its subclasses would defeat the whole split."""
    names = _imported_modules(ANDOR / "driver.py")
    assert not any("spectrograph" in n or "calibrated" in n for n in names), names
