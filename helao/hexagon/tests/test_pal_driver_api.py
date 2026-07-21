"""Public-API drift guard for `pal_driver.py` (P3a-PAL 4-way split, slice 0).

Baseline freeze: the internal 4-way split (DataSinkPort/SampleStatePort/
PalTransportPort/PalTriggerPort ports + a PalReconciliation domain service)
must not change any name or signature that `pal_server.py` / `PALJobExec`
depend on. This test is the Linux-runnable proof of that surface -- no
hardware, no connect(), just import + attribute/signature presence.

Covers:
- the six model/enum names `pal_server.py:24-33` imports from `pal_driver`
  (PAL, Spacingmethod, PALtools, PalMicroCam, PALposition, GCsampletype);
- every `build_palcam_*` helper `pal_server.py` calls;
- `submit_job`, `stop`, `kill_PAL`, `is_busy`, and the `sshhost` attribute
  that `PALJobExec` / the server's `_pal_reject_busy`/`_pal_start` depend on.
"""

import inspect

from helao.deploy.hte.drivers.robot import pal_driver
from helao.deploy.hte.drivers.robot.pal_driver import (
    PAL,
    GCsampletype,
    PALposition,
    PALtools,
    Spacingmethod,
)

# pal_server.py:24-33 imports these six names directly from pal_driver.
IMPORTED_MODEL_NAMES = [
    "PAL",
    "Spacingmethod",
    "PALtools",
    "PalMicroCam",
    "PALposition",
    "GCsampletype",
]

# build_palcam_* helpers pal_server.py calls (grepped from the endpoint bodies).
BUILD_PALCAM_METHODS = [
    "build_palcam_arbitrary",
    "build_palcam_ANEC_aliquot",
    "build_palcam_ANEC_GC",
    "build_palcam_injection_tray_GC",
    "build_palcam_injection_custom_GC",
    "build_palcam_injection_custom_HPLC",
    "build_palcam_injection_tray_HPLC",
    "build_palcam_transfer_tray_tray",
    "build_palcam_transfer_tray_custom",
    "build_palcam_transfer_custom_tray",
    "build_palcam_transfer_custom_custom",
    "build_palcam_archive",
    "build_palcam_deepclean",
]


def test_six_model_enum_names_still_import_from_pal_driver():
    missing = [n for n in IMPORTED_MODEL_NAMES if not hasattr(pal_driver, n)]
    assert not missing, f"pal_server.py-imported names missing: {missing}"


def test_build_palcam_methods_present_with_expected_signature():
    for name in BUILD_PALCAM_METHODS:
        assert hasattr(PAL, name), f"PAL.{name} missing"
        sig = inspect.signature(getattr(PAL, name))
        params = list(sig.parameters)
        # self, params, samples_in (all build_palcam_* helpers share this shape)
        assert params == [
            "self",
            "params",
            "samples_in",
        ], f"PAL.{name} signature drifted: {params}"


def test_submit_job_present_with_expected_signature():
    assert hasattr(PAL, "submit_job")
    sig = inspect.signature(PAL.submit_job)
    assert list(sig.parameters) == ["self", "palcam", "active"]


def test_stop_kill_pal_is_busy_present():
    assert hasattr(PAL, "stop")
    assert list(inspect.signature(PAL.stop).parameters) == ["self"]

    assert hasattr(PAL, "kill_PAL")
    assert list(inspect.signature(PAL.kill_PAL).parameters) == ["self"]

    assert hasattr(PAL, "is_busy")
    assert list(inspect.signature(PAL.is_busy).parameters) == ["self"]


def test_sshhost_attribute_present_after_construction():
    # No connect(): just construct with an empty config, mirroring the
    # server's `driver_classes=[PAL]` composition without any hardware I/O.
    driver = PAL(config={})
    assert hasattr(driver, "sshhost")
    assert driver.sshhost is None
    assert driver.is_busy() is False
