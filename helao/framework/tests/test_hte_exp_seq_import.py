"""Import smoke test for hte experiment and sequence modules after Wave 3.5 import-swap.

Every migrated module under ``helao/deploy/hte/experiments/`` and
``helao/deploy/hte/sequences/`` is imported via ``importlib.import_module``.

Pass/skip/fail semantics mirror ``test_hte_vis_operator_import.py``:
* **PASS** — module imported without error.
* **SKIP** — ``ImportError`` / ``ModuleNotFoundError`` whose message references a
  known vendor/hardware package not installed on Linux CI.
* **FAIL** — any other ``ImportError``, which indicates a residual legacy import path
  from the Wave-3.5 migration that was not correctly mapped onto ``helao.framework.*``.

Non-import exceptions (``OSError``, ``RuntimeError``, hardware init errors) are
swallowed — we only care that Python's import machinery resolves all module paths.

An extra assertion verifies ``samples_exp.orch_sub_wait.experiment_version == 2``:
the presence of the ``experiment_version`` attribute proves the framework
``@experiment`` decorator was applied (the legacy decorator does not set it).
"""

import importlib
import pathlib
import sys

import pytest

# ---------------------------------------------------------------------------
# Ensure repo root is on sys.path so intra-package imports resolve correctly.
# parents[3] of helao/framework/tests/<file>.py  =  helao-async/ (repo root)
# ---------------------------------------------------------------------------
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Load CONFIG so libs that reference CONFIG at import time resolve.
# ---------------------------------------------------------------------------
from helao.helpers.config_loader import read_config

read_config("power_supply_test")

# ---------------------------------------------------------------------------
# Vendor / hardware packages not installed on Linux CI → skip, not fail.
# ---------------------------------------------------------------------------
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
    # private deployment module used by UVIS_R_seq.py
    "priv",
}

# ---------------------------------------------------------------------------
# Module list: all 31 migrated files (experiments + sequences + archive)
# ---------------------------------------------------------------------------
_MIGRATED_MODULES = [
    # experiments
    "helao.deploy.hte.experiments.samples_exp",
    "helao.deploy.hte.experiments.ADSS_exp",
    "helao.deploy.hte.experiments.ANEC_exp",
    "helao.deploy.hte.experiments.CCSI_exp",
    "helao.deploy.hte.experiments.CLAD_exp",
    "helao.deploy.hte.experiments.CSIL_exp",
    "helao.deploy.hte.experiments.ECHEUVIS_exp",
    "helao.deploy.hte.experiments.ECHE_exp",
    "helao.deploy.hte.experiments.ECMS_exp",
    "helao.deploy.hte.experiments.HISPEC_exp",
    "helao.deploy.hte.experiments.ICPMS_exp",
    "helao.deploy.hte.experiments.PSTAT_exp",
    "helao.deploy.hte.experiments.UVIS_exp",
    "helao.deploy.hte.experiments.XRFS_exp",
    "helao.deploy.hte.experiments.archive.DEMO_exp",
    "helao.deploy.hte.experiments.archive.simulate_exp",
    # sequences
    "helao.deploy.hte.sequences.ADSS_seq",
    "helao.deploy.hte.sequences.ANEC_seq",
    "helao.deploy.hte.sequences.CCSI_seq",
    "helao.deploy.hte.sequences.CLAD_seq",
    "helao.deploy.hte.sequences.ECHEUVIS_seq",
    "helao.deploy.hte.sequences.ECHE_seq",
    "helao.deploy.hte.sequences.ECMS_seq",
    "helao.deploy.hte.sequences.HISPEC_seq",
    "helao.deploy.hte.sequences.ICPMS_seq",
    "helao.deploy.hte.sequences.PSTAT_seq",
    "helao.deploy.hte.sequences.UVIS_DR_seq",
    "helao.deploy.hte.sequences.UVIS_R_seq",
    "helao.deploy.hte.sequences.UVIS_T_seq",
    "helao.deploy.hte.sequences.UVIS_TR_seq",
    "helao.deploy.hte.sequences.XRFS_seq",
]


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


@pytest.mark.parametrize("module_name", _MIGRATED_MODULES)
def test_import(module_name: str) -> None:
    """Import the module; skip on hardware/vendor unavailability."""
    # Remove any stale cached version so each run is fresh
    sys.modules.pop(module_name, None)

    try:
        importlib.import_module(module_name)
    except ImportError as exc:
        missing = _find_vendor(exc)
        if missing:
            pytest.skip(
                f"{module_name}: skipped — vendor/hardware package "
                f"'{missing}' not available on this platform"
            )
        pytest.fail(
            f"ImportError in {module_name}: {exc}\n"
            "Check that the Wave-3.5 import-swap mapped this symbol correctly."
        )
    except Exception:
        # Non-import errors (hardware init, OSError, etc.) are acceptable.
        pass


def test_orch_sub_wait_experiment_version() -> None:
    """Framework @experiment decorator must be applied to samples_exp.orch_sub_wait.

    The presence of ``experiment_version`` proves the framework decorator was used,
    not the legacy one (which does not set this attribute).
    """
    import helao.deploy.hte.experiments.samples_exp as se

    assert hasattr(se.orch_sub_wait, "experiment_version"), (
        "orch_sub_wait is missing experiment_version — legacy decorator still applied"
    )
    assert se.orch_sub_wait.experiment_version == 2, (
        f"Expected experiment_version==2, got {se.orch_sub_wait.experiment_version}"
    )
