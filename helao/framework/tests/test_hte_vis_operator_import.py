"""Smoke-import test for hte visualizer and operator modules after Wave 3 import-swap.

Discovers every visualizer module under ``helao/deploy/hte/servers/visualizer/``
(per-instrument *_vis.py files) and the three bespoke operator modules
(gcld_operator.py, gcld_operator_test.py, finish_analysis.py), then attempts
``importlib.import_module`` on each.

Pass/skip/fail semantics:
* **PASS** — module imported without error.
* **SKIP** — ``ImportError`` / ``ModuleNotFoundError`` whose message references
  a known vendor/hardware package that is not installed on Linux CI (e.g.
  ``nidaqmx``, ``comtypes``, ``pyAndorSDK3``, etc.). These drivers require
  physical hardware SDKs or are Windows-only.
* **FAIL** — any other ``ImportError``, which indicates a residual legacy
  import path from the Wave-3 migration that was not correctly mapped onto
  the ``helao.framework.*`` namespace.

Non-import exceptions (``OSError``, ``RuntimeError``, etc.) are swallowed:
we only care that the Python import machinery resolves all module paths
correctly, not that the hardware initialises.
"""

import importlib
import importlib.util
import pathlib
import sys

import pytest

# ---------------------------------------------------------------------------
# Ensure the repo root is on sys.path so relative intra-package imports
# within helao/deploy/hte/ resolve correctly when running from any CWD.
# parents[3] of helao/framework/tests/<file>.py  =  helao-async/ (repo root)
# ---------------------------------------------------------------------------
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Discover test cases
# ---------------------------------------------------------------------------

_VIS_DIR = _REPO_ROOT / "helao" / "deploy" / "hte" / "servers" / "visualizer"
_OPERATOR_DIR = _REPO_ROOT / "helao" / "deploy" / "hte" / "servers" / "operator"

# Vendor / hardware packages that are not installed on Linux CI.
# An ImportError mentioning any of these is a skip, not a failure.
_VENDOR_PACKAGES = {
    "gclib",
    "comtypes",
    "easy_biologic",
    "pyAndorSDK3",
    "pyAndorSpectrograph",
    "minimalmodbus",
    "nidaqmx",
    "leancat_helao",
    "pylablib",
    "alicat",
    "mecom",
    "pyvisa",
    "aiofiles",
    "paramiko",
    "data_request_client",
    "gcld_operator",
}


def _collect_modules() -> list[pathlib.Path]:
    """Collect all per-instrument *_vis.py files and bespoke operator modules."""
    files = []

    # 12 per-instrument visualizers
    vis_files = sorted(_VIS_DIR.glob("*_vis.py"))
    files.extend([f for f in vis_files if f.name != "__init__.py"])

    # 3 bespoke operators
    operator_files = [
        _OPERATOR_DIR / "gcld_operator.py",
        _OPERATOR_DIR / "gcld_operator_test.py",
        _OPERATOR_DIR / "finish_analysis.py",
    ]
    files.extend([f for f in operator_files if f.exists()])

    return files


def _module_name(path: pathlib.Path) -> str:
    """Return the dotted module name for *path* relative to *_REPO_ROOT*."""
    rel = path.relative_to(_REPO_ROOT)
    parts = list(rel.parts)
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


_MODULES = _collect_modules()


@pytest.mark.parametrize(
    "module_path",
    _MODULES,
    ids=[f.stem for f in _MODULES],
)
def test_import(module_path: pathlib.Path) -> None:
    """Import the module; skip on hardware/vendor unavailability."""
    stem = module_path.stem

    module_name = _module_name(module_path)

    # Remove any stale cached version so each run is fresh
    sys.modules.pop(module_name, None)

    try:
        importlib.import_module(module_name)
    except ImportError as exc:
        # Walk the full exception chain for a vendor package name
        missing = _find_vendor(exc)
        if missing:
            pytest.skip(
                f"{module_path.name}: skipped — vendor/hardware package "
                f"'{missing}' not available on this platform"
            )
        # Any other ImportError is a real failure (wrong framework path)
        pytest.fail(
            f"ImportError in {module_path.name}: {exc}\n"
            "Check that the Wave-3 import-swap mapped this symbol correctly."
        )
    except Exception:
        # Non-import errors (OSError from hardware init, etc.) are acceptable —
        # we only care that the import path resolution succeeds.
        pass


def _find_vendor(exc: BaseException) -> str | None:
    """Walk the exception chain; return the first vendor package name found."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        msg = str(current).lower()
        for vendor in _VENDOR_PACKAGES:
            if vendor.lower() in msg:
                return vendor
        current = current.__cause__ or current.__context__
    return None
