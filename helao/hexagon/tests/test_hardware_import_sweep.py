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
    "robot.pal_driver",
    "io.nidaqmx_driver",
    "spec.andor.driver",
]
SLICE2_MODULES = [
    "pstat.biologic.driver",
]


@pytest.mark.parametrize("mod", SLICE1_MODULES)
def test_slice1_driver_imports_on_linux(mod):
    importlib.import_module(BASE + mod)


@pytest.mark.parametrize("mod", SLICE2_MODULES)
def test_slice2_driver_imports_on_linux(mod):
    # P3a-2 DONE (2026-07-22): biologic/technique.py no longer references
    # blp.OCV/... at module scope. The registry stores technique-name strings
    # (`easy_class_name`) and resolves the vendor class lazily via
    # `resolve_easy_class` at setup() time, so the driver now imports on Linux
    # without the Windows-only easy_biologic runtime.
    importlib.import_module(BASE + mod)


@pytest.mark.xfail(
    reason="P3a-2 status (2026-07-22): KinesisMotor.__init__ still calls "
    "self.connect(). Unlike the other §10.4 offenders it is CONTESTED, not a "
    "clean TODO: kinesis_server.py wires poller_class=KinesisPoller, and a "
    "DriverPoller auto-starts in __init__ needing an open device (see the "
    "poller-connect-in-__init__ rule), so relocating connect() is not a plain "
    "behavior-preserving move. The sibling offenders are resolved otherwise: "
    "AndorDriver fixed (disconnected-construct), GamryDriver deferred (shared "
    "across private deployments), MeerstetterTEC dropped (no hte driver).",
    strict=False,
)
def test_kinesis_constructs_without_connecting(monkeypatch):
    """§10.4: KinesisMotor(config) must not open devices in __init__.

    Currently xfails by design — kinesis is poller-backed, so connect-in-
    __init__ may be correct rather than a violation (contested; see reason)."""
    import pylablib.devices.Thorlabs as Thorlabs

    from helao.deploy.hte.drivers.motion import kinesis_driver

    calls = []
    monkeypatch.setattr(
        Thorlabs,
        "KinesisMotor",
        lambda *a, **k: calls.append((a, k)) or object(),
    )
    drv = kinesis_driver.KinesisMotor(
        config={
            "axes": {
                "x": {
                    "serial_no": "0",
                    "pos_scale": 1,
                    "vel_scale": 1,
                    "acc_scale": 1,
                }
            }
        }
    )
    assert calls == [], "KinesisMotor.__init__ must not connect to hardware"
    assert isinstance(LegacyDriverHardwareAdapter(drv), HardwarePort)


DISCONNECTED_CONSTRUCT = [
    ("io.galil_io_driver", "Galil"),
    ("motion.galil_motion_driver", "Galil"),
    ("sensor.cm0134_driver", "CM0134"),
    ("sensor.sprintir_driver", "SprintIR"),
    ("io.synaccess.driver", "NetbooterDriver"),
    ("pump.simdos_driver", "SIMDOS"),
    # NOT disconnected-construct (excluded, not weakened - recorded as findings):
    # - pstat.gamry.driver.GamryDriver: __init__ calls self.connect()
    #   unconditionally (same §10.4 constructor-connect pattern as
    #   KinesisMotor); out of scope for this plan.
    # - temperature_control.mecom_driver.MeerstetterTEC: __init__ requires
    #   config["channel"]/config["port"] with no default, raising a plain
    #   KeyError on config={}; unrelated to vendor imports.
]


@pytest.mark.parametrize("mod,cls", DISCONNECTED_CONSTRUCT)
def test_adapter_is_hardware_port(mod, cls):
    klass = getattr(importlib.import_module(BASE + mod), cls)
    drv = klass(config={})
    assert isinstance(LegacyDriverHardwareAdapter(drv), HardwarePort)
