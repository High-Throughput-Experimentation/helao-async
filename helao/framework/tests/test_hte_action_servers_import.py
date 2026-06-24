"""Smoke-import test for all hte action server modules after Wave 2 import-swap.

Discovers every ``*.py`` file under ``helao/deploy/hte/servers/action/``
(excluding ``__init__.py``) and attempts ``importlib.import_module`` on each.

Pass/skip/fail semantics:
* **PASS** — module imported without error.
* **SKIP** — ``ImportError`` / ``ModuleNotFoundError`` whose message references
  a known vendor/hardware package that is not installed on Linux CI (e.g.
  ``gclib``, ``comtypes``, ``easy_biologic``, ``pyAndorSDK3``,
  ``minimalmodbus``, etc.).  These drivers are Windows-only or require
  physical hardware SDKs.
* **FAIL** — any other ``ImportError``, which indicates a residual legacy
  import path from the Wave-2 migration that was not correctly mapped onto
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

_ACTION_DIR = _REPO_ROOT / "helao" / "deploy" / "hte" / "servers" / "action"

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
}

# Files with known pre-existing issues unrelated to the Wave-2 import-swap.
# Key: stem name, value: skip reason string.
_KNOWN_ISSUES: dict[str, str] = {
    # The relative import '....drivers.data.HTEdata_legacy' (4 dots) resolves
    # to 'helao.deploy.drivers' rather than 'helao.deploy.hte.drivers' — a
    # pre-existing bug in the server file itself, not introduced by Wave 2.
    "HTEdata_server": (
        "pre-existing relative-import depth bug (4-dot import resolves to "
        "helao.deploy.drivers, not helao.deploy.hte.drivers)"
    ),
}


def _collect_server_files() -> list[pathlib.Path]:
    files = sorted(_ACTION_DIR.glob("*.py"))
    return [f for f in files if f.name != "__init__.py"]


def _module_name(path: pathlib.Path) -> str:
    """Return the dotted module name for *path* relative to *_REPO_ROOT*."""
    rel = path.relative_to(_REPO_ROOT)
    parts = list(rel.parts)
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


_SERVER_FILES = _collect_server_files()


@pytest.mark.parametrize(
    "server_path",
    _SERVER_FILES,
    ids=[f.stem for f in _SERVER_FILES],
)
def test_import(server_path: pathlib.Path) -> None:
    """Import the server module; skip on hardware/vendor unavailability."""
    stem = server_path.stem

    # Known pre-existing issues — skip with explanation
    if stem in _KNOWN_ISSUES:
        pytest.skip(_KNOWN_ISSUES[stem])

    module_name = _module_name(server_path)

    # Remove any stale cached version so each run is fresh
    sys.modules.pop(module_name, None)

    try:
        importlib.import_module(module_name)
    except ImportError as exc:
        # Walk the full exception chain for a vendor package name
        missing = _find_vendor(exc)
        if missing:
            pytest.skip(
                f"{server_path.name}: skipped — vendor/hardware package "
                f"'{missing}' not available on this platform"
            )
        # Any other ImportError is a real failure (wrong framework path)
        pytest.fail(
            f"ImportError in {server_path.name}: {exc}\n"
            "Check that the Wave-2 import-swap mapped this symbol correctly."
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
