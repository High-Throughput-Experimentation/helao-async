"""P3b: import-only checks for the hexagon hte action-server shims.

Each shim under helao.deploy.hexagon.servers.action must import cleanly,
expose a callable makeApp, and declare a LEGACY_MODULE string pointing at
the matching module under helao.deploy.hte.servers.action. makeApp() is
NOT called here — that needs a loaded CONFIG (deferred to P3e preflight).
"""

from importlib import import_module

import pytest

HTE_ACTION_SHIM_MODULES = [
    "HTEdata_server",
    "andor_server",
    "biologic_server",
    "calc_server",
    "cam_server",
    "co2sensor_server",
    "diapump_server",
    "galil_io",
    "galil_motion",
    "gamry_server2",
    "kinesis_server",
    "mfc_server",
    "nidaqmx_server",
    "o2sensor_server",
    "pal_server",
    "pdu_server",
    "power_supply_server",
    "sample_server",
    "spec_server",
    "syringe_server",
    "tec_server",
    # P3b-2: dbpack (HelaoSyncer; legacy syncer kept — native-sync cut-over is a
    # separate P2e-style step) + analysis (config-driven analyze_ endpoints).
    "dbpack_server",
    "analysis_server",
]


@pytest.mark.parametrize("module_name", HTE_ACTION_SHIM_MODULES)
def test_shim_imports_and_wires_legacy_module(module_name):
    module = import_module(f"helao.deploy.hexagon.servers.action.{module_name}")

    assert hasattr(module, "makeApp")
    assert callable(module.makeApp)

    expected_legacy = f"helao.deploy.hte.servers.action.{module_name}"
    assert module.LEGACY_MODULE == expected_legacy
