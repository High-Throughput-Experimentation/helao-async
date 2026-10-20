"""Low-severity latent-crash fixes in the hte deployment (fakes only)."""

import asyncio
import json
import logging as pylogging
import sys
import tempfile
import types
from types import SimpleNamespace

import numpy as np
import pytest

from helao.core.error import ErrorCodes
from helao.core.models.file import FileInfo


class _StrictHandler(pylogging.Handler):
    """Formats each record, so a bad %-format raises where the call is made."""

    def emit(self, record):
        record.getMessage()


@pytest.fixture()
def strict_log():
    """Attach a strict handler at DEBUG to a logger; undo afterwards."""
    undo = []

    def _attach(logger):
        h = _StrictHandler()
        old = logger.level
        logger.addHandler(h)
        logger.setLevel(pylogging.DEBUG)
        undo.append((logger, h, old))

    yield _attach
    for logger, h, old in undo:
        logger.removeHandler(h)
        logger.setLevel(old)


# --- echeuvis_stability: missing presitu spectrum --------------------------


def test_echeuvis_missing_presitu_spectrum_returns_false(monkeypatch):
    from helao.deploy.hte.drivers.data.analyses import echeuvis_stability as es

    good = (np.linspace(400, 800, 5), [0.0], np.ones((1, 5)))
    monkeypatch.setattr(
        es, "parse_spechlo", lambda spec: False if spec == "bad" else good
    )
    ana = object.__new__(es.EcheUvisAnalysis)
    ana.analysis_params = dict(es.ANALYSIS_DEFAULTS)
    ana.inputs = SimpleNamespace(
        baseline_spec="ok", insitu_spec="ok", presitu_spec="bad"
    )
    assert ana.calc_output() is False


# --- archive_driver ---------------------------------------------------------


def test_tray_load_logs_the_sample_without_a_format_error(strict_log):
    from helao.deploy.hte.drivers.data import archive_driver as ad

    strict_log(ad.LOGGER)

    class _DB:
        async def get_samples(self, samples):
            return []

    archive = object.__new__(ad.Archive)
    archive.unified_db = _DB()  # type: ignore
    err, _ = asyncio.run(archive.tray_load(tray=1, slot=1, vial=1, load_sample_in={}))
    assert err == ErrorCodes.not_available


def test_tray_export_csv_with_empty_slot_writes_header_only():
    from helao.deploy.hte.drivers.data.archive_driver import Archive

    written = []

    class _Active:
        async def write_file(self, **kw):
            written.append(kw)

    archive = object.__new__(Archive)
    archive.write_config = lambda: None  # type: ignore
    archive.positions = SimpleNamespace(trays_dict={1: {1: None}})  # type: ignore
    asyncio.run(archive.tray_export_csv(tray=1, slot=1, myactive=_Active()))
    assert written and written[0]["output_str"] == ""


# --- power supply -----------------------------------------------------------


def test_get_voltage_async_success_is_reported_as_success():
    from helao.deploy.hte.drivers.power_supply.power_supply_driver import (
        PowerSupplyDriver,
    )
    from helao.core.drivers.helao_driver import DriverResponseType

    drv = PowerSupplyDriver(config={"resource_name": "fake"})
    drv.instrument = SimpleNamespace(query=lambda cmd: "3.3")  # type: ignore
    resp = asyncio.run(drv.get_voltage_async(sleep_time=0))
    assert resp.response == DriverResponseType.success
    assert resp.data == {"voltage_v": 3.3}


# --- galil_motion_driver ----------------------------------------------------


def test_galil_motor_disconnect_failure_is_json_serialisable(monkeypatch):
    class GclibError(Exception):
        pass

    monkeypatch.setitem(sys.modules, "gclib", SimpleNamespace(GclibError=GclibError))
    from helao.deploy.hte.drivers.motion.galil_motion_driver import Galil

    def _close():
        raise GclibError("link down")

    drv = object.__new__(Galil)
    drv.g = SimpleNamespace(GClose=_close)
    out = asyncio.run(drv.motor_disconnect())
    assert "link down" in json.loads(json.dumps(out))["connection"]


# --- kinesis ----------------------------------------------------------------


def test_kinesis_dev_enum_exists_when_an_axis_fails_to_open(monkeypatch):
    from helao.deploy.hte.drivers.motion import kinesis_driver as kd

    def _motor(conn=None, scale=None):
        if conn == "bad":
            raise OSError("no device")
        return object()

    monkeypatch.setattr(kd.Thorlabs, "KinesisMotor", _motor)
    axis = {"pos_scale": 1.0, "vel_scale": 1.0, "acc_scale": 1.0}
    drv = kd.KinesisMotor(
        config={
            "axes": {
                "x": {"serial_no": "bad", **axis},
                "y": {"serial_no": "ok", **axis},
            }
        }
    )
    drv.connect()  # the host connects after construction; "bad" fails to open
    assert sorted(e.value for e in drv.dev_kinesis) == ["x", "y"]


# --- simdos -----------------------------------------------------------------


def test_simdos_get_mode_retries_a_missed_reply(monkeypatch):
    import helao.deploy.hte.drivers.pump.simdos_driver as simdos

    monkeypatch.setattr(simdos.serial, "Serial", lambda **kw: kw)
    drv = simdos.SIMDOS(config={"port": "COM7", "address": 1})
    replies = iter([None, None, "1"])
    drv.send = lambda cmd: next(replies)  # type: ignore
    assert drv.get_mode() == simdos.PumpMode(1)


# --- gamry readz ------------------------------------------------------------


def test_readz_get_data_debug_log_formats(monkeypatch, strict_log):
    from helao.core.drivers.helao_driver import DriverResponseType
    from helao.deploy.hte.drivers.pstat.gamry import readz

    strict_log(readz.LOGGER)
    fake_client = SimpleNamespace(PumpEvents=lambda rate: None)
    monkeypatch.setitem(sys.modules, "comtypes", SimpleNamespace(client=fake_client))
    monkeypatch.setitem(sys.modules, "comtypes.client", fake_client)
    rz = object.__new__(readz.ReadZ)
    rz.counter = 0
    rz.dtaqsink = SimpleNamespace(acquired_points=[1, 2], status="measuring")
    assert rz.get_data(0.0).response == DriverResponseType.success


# --- spectral products ------------------------------------------------------


def _sm303(pxwl, data):
    from helao.deploy.hte.drivers.spec import spectral_products_driver as sp

    drv = object.__new__(sp.SM303)
    drv.set_trigger_mode = lambda t: True  # type: ignore
    drv.set_integration_time = lambda t: True  # type: ignore
    drv.spec = SimpleNamespace(spSetIntMode=lambda *a: 1)
    drv.dev_num = 0
    drv.read_data = lambda: 1  # type: ignore
    drv.pxwl = pxwl
    drv.data = data
    return drv


def test_peak_window_outside_detector_is_an_error_and_upper_pixel_is_included():
    drv = _sm303([float(i) for i in range(10)], [0, 0, 0, 0, 0, 7, 0, 0, 0, 3])
    out = drv.acquire_spec_adv(10, peak_lower_wl=50, peak_upper_wl=60)
    assert out == {"error_code": ErrorCodes.not_available}
    # upper bound pixel (wl 5) is inside the window
    assert (
        drv.acquire_spec_adv(10, peak_lower_wl=2, peak_upper_wl=5)["peak_intensity"]
        == 7
    )
    # descending wavelength table works too
    rev = _sm303([float(9 - i) for i in range(10)], [3, 0, 0, 0, 7, 0, 0, 0, 0, 0])
    assert (
        rev.acquire_spec_adv(10, peak_lower_wl=4, peak_upper_wl=6)["peak_intensity"]
        == 7
    )


# --- processors -------------------------------------------------------------


def test_spec_melt_keeps_the_original_file_when_conversion_fails(monkeypatch, tmp_path):
    from helao.deploy.hte.processors import spec_melt_wls

    def boom(path):
        raise OSError("unreadable")

    monkeypatch.setattr(spec_melt_wls, "read_hlo", boom)
    f = FileInfo(file_type="spec_r_helao__file", file_name="a.hlo")
    pp = object.__new__(spec_melt_wls.PostProcess)
    pp.files = [f]
    pp.output_dir = str(tmp_path)
    pp.action = SimpleNamespace(action_params={})
    assert pp.process() == [f]


def test_hispec_temp_csv_is_removed_even_when_calibration_fails(monkeypatch, tmp_path):
    from helao.deploy.hte.processors import hispec_process_all as hp

    class _HD:
        name = "HISPEC_sub_SpEC"
        act = [None, None, None, SimpleNamespace(data=[None, {"a": [1]}])]

        def __init__(self, path):
            pass

    def boom(**kw):
        raise RuntimeError("calibration failed")

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(hp, "HelaoData", _HD)
    monkeypatch.setattr(hp, "hlo_to_parquet", lambda *a, **k: None)
    monkeypatch.setattr(hp, "fully_read_and_calibrate_parquet", boom)
    pp = object.__new__(hp.PostProcess)
    pp.files = [FileInfo(file_type="andor_helao__file", file_name="a.hlo")]
    pp.output_dir = str(tmp_path)
    pp.exp_yml_path = "x-exp.yml"
    pp.action = SimpleNamespace(action_params={})
    pp.process()
    assert list(tmp_path.glob("*.csv")) == []


# --- servers (route-capturing fake ActionHost) ------------------------------


class _FakeHost:
    server_params: dict = {}

    def __init__(self, *a, **kw):
        self.server_params = dict(type(self).server_params)
        self.driver = SimpleNamespace()
        self.executors = {}
        self.routes = {}
        self.stopped = []

    def action(self, **kw):
        def deco(fn):
            self.routes[fn.__name__] = fn
            return fn

        return deco

    def post(self, path, **kw):
        def deco(fn):
            self.routes[path] = fn
            return fn

        return deco

    def stop_executor(self, executor_id):
        self.stopped.append(executor_id)
        return {"success": False, "executor_id": executor_id}


def _app(monkeypatch, module, server_params=None):
    _FakeHost.server_params = server_params or {}
    monkeypatch.setattr(module, "ActionHost", _FakeHost)
    return module.makeApp("K")


def test_cancel_acquire_image_with_nothing_running_still_finishes(monkeypatch):
    from helao.deploy.hte.servers.action import cam_server

    app = _app(monkeypatch, cam_server)
    finished = SimpleNamespace(as_dict=lambda: {"done": True})

    async def finish():
        return finished

    async def begin(**kw):
        return SimpleNamespace(finish=finish)

    out = asyncio.run(app.routes["cancel_acquire_image"](SimpleNamespace(begin=begin)))
    assert out == {"done": True} and app.stopped == ["axis"]


def test_pal_anec_aliquot_needs_archive_and_a_gas_method(monkeypatch):
    from helao.deploy.hte.servers.action import pal_server

    liquid_only = _app(
        monkeypatch, pal_server, {"cams": {"injection_custom_GC_liquid_start": {}}}
    )
    gas_no_archive = _app(
        monkeypatch, pal_server, {"cams": {"injection_custom_GC_gas_wait": {}}}
    )
    full = _app(
        monkeypatch,
        pal_server,
        {
            "cams": {
                "injection_custom_GC_gas_wait": {},
                "injection_custom_GC_gas_start": {},
                "archive": {},
            }
        },
    )
    assert "PAL_ANEC_aliquot" not in liquid_only.routes
    assert "PAL_ANEC_aliquot" not in gas_no_archive.routes
    one_gas = _app(
        monkeypatch,
        pal_server,
        {"cams": {"injection_custom_GC_gas_wait": {}, "archive": {}}},
    )
    assert "PAL_ANEC_aliquot" not in one_gas.routes
    assert "PAL_ANEC_aliquot" in full.routes


@pytest.mark.parametrize("name", ["PAL_dilute", "PAL_autodilute"])
def test_pal_dilute_endpoints_return_a_clear_error(monkeypatch, name):
    from helao.deploy.hte.servers.action import pal_server

    cam = name.split("_")[1]
    app = _app(monkeypatch, pal_server, {"cams": {cam: {}}})
    action = SimpleNamespace(error_code=ErrorCodes.none)
    action.as_dict = lambda: {"error_code": action.error_code}
    out = asyncio.run(app.routes[name](SimpleNamespace(action=action)))
    assert out == {"error_code": ErrorCodes.not_available}


def test_db_new_samples_with_no_reference_samples_does_not_raise(monkeypatch):
    from helao.deploy.hte.servers.action import sample_server

    app = _app(monkeypatch, sample_server)

    async def create_samples(**kw):
        return []

    app.driver = SimpleNamespace(create_samples=create_samples)
    finished = SimpleNamespace(as_dict=lambda: {"done": True})

    async def anoop(*a, **k):
        return None

    async def finish():
        return finished

    active = SimpleNamespace(
        action=SimpleNamespace(samples_in=[], samples_out=[], action_params={}),
        append_sample=anoop,
        base=SimpleNamespace(
            dflt_file_conn_key=lambda: "00000000-0000-0000-0000-000000000001"
        ),
        enqueue_data_nowait=lambda *a, **k: None,
        finish=finish,
    )

    async def begin(**kw):
        return active

    out = asyncio.run(app.routes["db_new_samples"](SimpleNamespace(begin=begin)))
    assert out == {"done": True}
    assert "_fast_sample_out" not in active.action.action_params


# --- gcld_operator ----------------------------------------------------------


def test_insitu_potential_list_rejects_an_unknown_z_start(monkeypatch):
    fake = types.ModuleType("data_request_client.client")
    fake.CreateDataRequestModel = fake.DataRequestsClient = object  # type: ignore
    monkeypatch.setitem(sys.modules, "data_request_client", types.ModuleType("x"))
    monkeypatch.setitem(sys.modules, "data_request_client.client", fake)
    from helao.deploy.hte.servers.operator import gcld_operator as g

    assert g.insitu_potential_list(0.5, scan_down=False) is None
    pots = g.insitu_potential_list(0.4, scan_down=False)
    assert pots is not None and pots[:3] == [0.4, 0.6, 0.8]
    assert sorted(pots) == sorted(g.ECHEUVIS_multiCA_led_defaults["CA_potential_vsRHE"])


# --- sample_vis -------------------------------------------------------------


def test_sample_vis_bad_max_smps_input_keeps_the_previous_value():
    from helao.deploy.hte.servers.visualizer import sample_vis

    vis = object.__new__(sample_vis.C_vis)
    vis.max_smps = 10
    vis.vis = SimpleNamespace(
        doc=SimpleNamespace(add_next_tick_callback=lambda cb: None)
    )
    vis.reset_plot = lambda: None  # type: ignore
    vis.callback_input_max_smps("value", "10", "abc", sender=None)
    assert vis.max_smps == 10
    vis.callback_input_max_smps("value", "10", "25", sender=None)
    assert vis.max_smps == 25
