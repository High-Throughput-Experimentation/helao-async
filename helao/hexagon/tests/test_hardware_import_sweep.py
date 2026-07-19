import importlib
import pytest
from helao.hexagon.adapters.legacy.hardware import LegacyDriverHardwareAdapter
from helao.hexagon.ports.hardware import HardwarePort

BASE = "helao.deploy.hte.drivers."

SLICE1_MODULES = [
    "pstat.gamry.driver",
    "spec.spectral_products_driver",  # already lazy
    "io.galil_io_driver",
    "motion.galil_motion_driver",
    "sensor.cm0134_driver",
    "sensor.sprintir_driver",  # already imports (serial only)
    "temperature_control.mecom_driver",
    "io.synaccess.driver",
    "motion.kinesis_driver",
    "pump.simdos_driver",
]
SLICE2_MODULES = [
    "spec.andor.driver",
    "pstat.biologic.driver",
    "io.nidaqmx_driver",
    "robot.pal_driver",
]


@pytest.mark.parametrize("mod", SLICE1_MODULES)
def test_slice1_driver_imports_on_linux(mod):
    importlib.import_module(BASE + mod)


@pytest.mark.parametrize("mod", SLICE2_MODULES)
@pytest.mark.xfail(
    reason="P3a-2: deeper lazy-import/constructor refactor pending", strict=False
)
def test_slice2_driver_imports_on_linux(mod):
    importlib.import_module(BASE + mod)
