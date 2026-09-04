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
import warnings
from pathlib import Path

ANDOR = Path("helao/deploy/hte/drivers/spec/andor")
ALLOWED = {"spectrograph.py"}

# Standalone exploratory scripts that predate the split and are not part of
# any station's import graph: each constructs `AndorSDK3()` at module scope,
# so importing one drives hardware. Nothing imports them, which is what makes
# their vendor imports harmless -- a spectrograph-free connect() never reaches
# them -- and `test_the_exempt_scripts_are_imported_by_nothing` pins that.
# Exempted by exact name rather than by a `test_*` pattern, so a real module
# can only join this list deliberately.
STANDALONE_SCRIPTS = {"test_funcs.py", "test_read_loop.py"}


def _imported_modules(path: Path) -> set[str]:
    """Every module name this file imports, however it spells the import."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
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
        if path.name in ALLOWED or path.name in STANDALONE_SCRIPTS:
            continue
        if any(n.startswith("pyAndorSpectrograph") for n in _imported_modules(path)):
            offenders.append(path.name)
    assert offenders == [], f"{offenders} must not import pyAndorSpectrograph"


def test_the_exempt_scripts_are_imported_by_nothing():
    """The exemption holds only while nothing pulls those scripts into a process."""
    stems = {name.removesuffix(".py") for name in STANDALONE_SCRIPTS}
    importers, examined = [], 0
    for path in Path("helao").rglob("*.py"):
        if path.name in STANDALONE_SCRIPTS:
            continue
        try:
            # Parsing the whole tree surfaces pre-existing invalid-escape
            # warnings from unrelated modules; they are not this guard's news.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                names = _imported_modules(path)
        except (SyntaxError, UnicodeDecodeError):
            continue
        examined += 1
        if any(n.rsplit(".", 1)[-1] in stems for n in names):
            importers.append(str(path))
    # A sweep that examined nothing (wrong cwd) would pass vacuously.
    assert examined > 100, examined
    assert importers == [], f"{importers} import an exempted vendor script"


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
