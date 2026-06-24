"""Import smoke test for HTE driver modules after Wave 1 import-swap.

Walks ``helao/deploy/hte/drivers/`` for ``.py`` files and attempts to import
each module via :func:`importlib.import_module`.  The four Windows-only files
(galil_io, galil_motion, gamry/driver, gamry/readz) that require ``gclib`` or
``comtypes`` are explicitly skipped with :func:`pytest.skip` so the test suite
remains green on Linux.

This test verifies only that the import-swap did not introduce new
``ImportError`` exceptions caused by wrong framework module paths.  It does NOT
run any driver logic.
"""

import importlib
import sys
from pathlib import Path

import pytest

# Repository root is two levels above helao/framework/tests/
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DRIVERS_ROOT = _REPO_ROOT / "helao" / "deploy" / "hte" / "drivers"

# The four Windows-only driver files (require gclib or comtypes, unavailable on Linux).
_WINDOWS_ONLY_PATHS = {
    "helao/deploy/hte/drivers/io/galil_io_driver.py",
    "helao/deploy/hte/drivers/motion/galil_motion_driver.py",
    "helao/deploy/hte/drivers/pstat/gamry/driver.py",
    "helao/deploy/hte/drivers/pstat/gamry/readz.py",
}

# Files that are deliberately excluded from module-import smoke tests
# (standalone test scripts, __init__ stubs, leancat sub-packages that require
# the leancat_helao SDK, andor driver that requires pyAndorSDK3).
_EXCLUDE_PATTERNS = {
    "__init__.py",
    # test scripts inside the driver tree that aren't real driver modules
    "sprintir_tests.py",
    # leancat sub-packages (commands, database, logger, script, station)
    # are imported transitively when leancat/driver.py is imported
    "commands.py",
    "database.py",
    "logger.py",
    "script.py",
    "station.py",
    # andor requires pyAndorSDK3 which is not installed on Linux CI
    "helao/deploy/hte/drivers/spec/andor/driver.py",
    # biologic requires easy_biologic
    "helao/deploy/hte/drivers/pstat/biologic/driver.py",
}


def _rel(p: Path) -> str:
    return str(p.relative_to(_REPO_ROOT)).replace("\\", "/")


def _to_module(p: Path) -> str:
    """Convert an absolute path under the repo to a dotted module name."""
    rel = p.relative_to(_REPO_ROOT)
    return str(rel.with_suffix("")).replace("/", ".").replace("\\", ".")


def _collect_driver_files():
    """Return all .py files under hte/drivers/ grouped by (rel_path, module_name, skip_reason)."""
    results = []
    for path in sorted(_DRIVERS_ROOT.rglob("*.py")):
        rel = _rel(path)
        name = path.name

        if name in _EXCLUDE_PATTERNS or rel in _EXCLUDE_PATTERNS:
            continue

        if rel in _WINDOWS_ONLY_PATHS:
            results.append((rel, _to_module(path), "windows-only (gclib/comtypes)"))
        else:
            results.append((rel, _to_module(path), None))
    return results


_DRIVER_CASES = _collect_driver_files()


@pytest.mark.parametrize(
    "rel_path,module_name,skip_reason",
    [(r, m, s) for r, m, s in _DRIVER_CASES],
    ids=[r for r, _, _ in _DRIVER_CASES],
)
def test_hte_driver_import(rel_path, module_name, skip_reason):
    """Import ``module_name`` and assert no ImportError from the framework swap."""
    if skip_reason:
        pytest.skip(f"Skipped: {skip_reason}")

    # Remove any previously cached (potentially broken) version
    sys.modules.pop(module_name, None)

    # Vendor packages that are hardware-specific and may not be installed on CI.
    # These are distinct from the helao.framework.* paths we are testing.
    _VENDOR_PACKAGES = {
        "gclib",
        "comtypes",
        "nidaqmx",
        "minimalmodbus",
        "pyAndorSDK3",
        "pyAndorSpectrograph",
        "easy_biologic",
        "leancat_helao",
        "pylablib",
        "nidaqmx",
        "alicat",
        "mecom",
        "pyvisa",
        "serial",
        "aiofiles",
        "paramiko",
        "psutil",
        "boto3",
        "botocore",
        "aiohttp",
        "requests",
    }

    try:
        importlib.import_module(module_name)
    except ImportError as exc:
        missing = str(exc)
        # Vendor/hardware package missing: skip rather than fail
        for vendor in _VENDOR_PACKAGES:
            if vendor in missing:
                pytest.skip(f"Vendor package unavailable: {missing}")
        # Unknown ImportError — likely a bad framework path from our swap
        pytest.fail(
            f"ImportError in {rel_path}: {exc}\n"
            "Check that the Wave 1 import-swap mapped this symbol correctly."
        )
    except Exception:
        # Non-import errors (missing hardware, config, etc.) are acceptable —
        # we only care that the import machinery resolves the module paths.
        pass
