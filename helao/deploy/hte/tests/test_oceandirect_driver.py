"""Driver-level tests for the OceanDirect spectrometer.

The vendor ``oceandirect`` wheel ships inside the Ocean Insight SDK installer
and is absent from the ``helao`` environment, so every test here runs against
``oceandirect_sim``, which reproduces the vendor's *failure* behaviour (raised
``OceanDirectError``, ids invalidated by close, unsupported features raising)
rather than just its happy path.

The most load-bearing test in this file is the HLO round-trip. The driver packs
each spectrum as five parallel arrays on one line, betting that both HLO
readers concatenate list-valued columns and therefore reconstruct the
one-row-per-pixel long format. That bet is checked against the real readers
here, not argued in a comment -- if ``read_hlo`` ever stops flattening, this
file fails rather than a station discovering it.

Run directly (``python -m pytest`` on this file) -- the hte suite is not part
of ``run_unit_tests.py``.
"""

import json

import pytest

from helao.core.drivers.helao_driver import DriverResponseType, DriverStatus
from helao.deploy.hte.drivers.spec import oceandirect_sim as sim
from helao.deploy.hte.drivers.spec.oceandirect_driver import OceanDirectSpec
from helao.deploy.hte.drivers.spec.oceandirect_enum import (
    LONG_FORMAT_KEYS,
    MAX_METADATA_BUFFER_SIZE,
)
from helao.helpers.hlo_data import read_hlo, read_hlo_data_chunks, read_hlo_header
from helao.helpers.to_json import hlo_json_dumps


@pytest.fixture(autouse=True)
def _clean_sim():
    """Restore the default simulated device population around every test."""
    sim.reset_sim()
    yield
    sim.reset_sim()


def _driver(**config) -> OceanDirectSpec:
    """Build a simulated driver with ``config`` merged over the defaults."""
    cfg = {"simulate": True}
    cfg.update(config)
    return OceanDirectSpec(config=cfg)


def _connected(**config) -> OceanDirectSpec:
    """Build a simulated driver and assert it connected."""
    drv = _driver(**config)
    resp = drv.connect()
    assert resp.response == DriverResponseType.success, resp.message
    return drv


# ----------------------------------------------------------------------
# Construction and lifecycle
# ----------------------------------------------------------------------
def test_construction_performs_no_device_io():
    """The ABC forbids device I/O in ``__init__``; nothing may be open yet."""
    drv = _driver()
    assert drv.api is None
    assert drv.dev is None
    assert drv.device_id is None
    assert drv.ready is False
    assert drv.n_pixels == 0
    assert drv.pxwl == []
    # And the status call must be answerable before connect().
    assert drv.get_status().status == DriverStatus.uninitialized


def test_connect_interrogates_the_device():
    drv = _connected(int_time_us=50_000)
    assert drv.model == "SR2"
    assert drv.serial == "SIM-SR2-0001"
    assert drv.n_pixels == 2048
    assert len(drv.pxwl) == 2048
    assert drv.int_time_min_us == 1000
    assert drv.int_time_max_us == 10_000_000
    assert drv.int_time_increment_us == 1000
    assert drv.get_status().status == DriverStatus.ok


def test_connect_reports_failure_when_no_device_is_found():
    sim.set_sim_config(sim.SimConfig(find_returns_nothing=True))
    drv = _driver()
    resp = drv.connect()
    assert resp.response == DriverResponseType.failed
    assert resp.status == DriverStatus.error
    assert drv.ready is False
    # A failed connect must not leave a half-open device behind.
    assert drv.dev is None
    assert drv.device_id is None


def test_connect_reports_failure_when_open_raises():
    sim.set_sim_config(sim.SimConfig(open_raises=True))
    resp = _driver().connect()
    assert resp.response == DriverResponseType.failed
    assert "simulated open failure" in resp.message


def test_device_selected_by_serial_number():
    sim.set_sim_config(sim.SimConfig(serial_numbers=("SIM-A", "SIM-B", "SIM-C")))
    drv = _connected(serial_number="SIM-B")
    assert drv.serial == "SIM-B"


def test_unknown_serial_number_is_a_failure_not_a_silent_fallback():
    """Falling back to device 0 would measure the wrong instrument."""
    sim.set_sim_config(sim.SimConfig(serial_numbers=("SIM-A", "SIM-B")))
    drv = _driver(serial_number="SIM-NOPE")
    resp = drv.connect()
    assert resp.response == DriverResponseType.failed
    assert "SIM-NOPE" in resp.message
    assert drv.dev is None


def test_dev_index_selects_positionally_and_bounds_check():
    sim.set_sim_config(sim.SimConfig(serial_numbers=("SIM-A", "SIM-B")))
    assert _connected(dev_index=1).serial == "SIM-B"
    resp = _driver(dev_index=7).connect()
    assert resp.response == DriverResponseType.failed
    assert "dev_index 7" in resp.message


def test_reset_rediscovers_because_close_invalidates_the_id():
    """A cached id is dead after close; ``reset`` must re-run discovery."""
    drv = _connected()
    first_id = drv.device_id
    resp = drv.reset()
    assert resp.response == DriverResponseType.success
    assert drv.device_id is not None
    assert drv.device_id != first_id
    assert drv.ready is True
    # The device is usable after the reset, not merely re-registered.
    spectrum, _ = drv.acquire_spectrum()
    assert len(spectrum) == 2048


def test_disconnect_is_idempotent_and_clears_state():
    drv = _connected()
    assert drv.disconnect().response == DriverResponseType.success
    assert drv.ready is False
    assert drv.dev is None
    # A second disconnect must not raise.
    assert drv.disconnect().response == DriverResponseType.success


def test_methods_fail_cleanly_when_no_device_is_open():
    """Every public method answers with a response; none raise."""
    drv = _driver()
    for resp in (
        drv.get_device_info(),
        drv.set_integration_time_us(1000),
        drv.set_processing(scans_to_average=2),
        drv.set_trigger_mode(0),
        drv.set_corrections(electric_dark=True),
        drv.store_dark_spectrum(),
        drv.start_buffered(n_scans=1),
        drv.stop_buffered(),
        drv.set_tec(enable=True),
        drv.get_tec_status(),
        drv.set_shutter_open(True),
        drv.set_lamp_enable(True),
        drv.set_light_source_enable(0, True),
        drv.set_single_strobe(enable=True),
        drv.set_continuous_strobe(enable=True),
    ):
        assert resp.response == DriverResponseType.failed
    assert drv.stop().status == DriverStatus.uninitialized


# ----------------------------------------------------------------------
# Integration time
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "requested,expected",
    [
        (0, 1000),  # below minimum -> minimum
        (-5, 1000),  # negative -> minimum
        (1000, 1000),  # exactly minimum
        (50_500, 50_000),  # off-grid -> snapped down
        (50_000, 50_000),  # on-grid -> unchanged
        (10**12, 10_000_000),  # above maximum -> maximum
    ],
)
def test_integration_time_is_clamped_and_snapped(requested, expected):
    drv = _connected()
    assert drv.clamp_integration_time_us(requested) == expected
    resp = drv.set_integration_time_us(requested)
    assert resp.response == DriverResponseType.success
    assert resp.data["int_time_us"] == expected
    assert resp.data["requested_us"] == int(requested)
    # And the value actually reached the device.
    assert drv.dev.get_integration_time() == expected


def test_snapped_value_is_always_accepted_by_the_device():
    """The device raises on an off-grid write; snapping is what prevents it."""
    drv = _connected()
    with pytest.raises(sim.OceanDirectError):
        drv.dev.set_integration_time(999)  # below the device minimum
    assert drv.set_integration_time_us(999).data["int_time_us"] == 1000


def test_integration_time_parameter_is_microseconds_not_milliseconds():
    """Guards against inheriting the SM303's millisecond assumption."""
    drv = _connected(int_time_us=250_000)
    assert drv.dev.get_integration_time() == 250_000


# ----------------------------------------------------------------------
# Feature gating
# ----------------------------------------------------------------------
def test_capability_matrix_covers_every_feature_id():
    drv = _connected()
    assert set(drv.features) == {f.name for f in sim.FeatureID}
    assert drv.features["DATA_BUFFER"] is True
    assert drv.features["SHUTTER"] is False


def test_unsupported_feature_returns_failed_and_does_not_raise():
    """An unsupported feature must not raise out of an action handler."""
    drv = _connected()
    resp = drv.set_shutter_open(True)
    assert resp.response == DriverResponseType.failed
    assert "SHUTTER" in resp.message


def test_supported_feature_round_trips():
    drv = _connected()
    resp = drv.set_tec(enable=True, setpoint_degrees_c=5.0)
    assert resp.response == DriverResponseType.success
    assert resp.data["tec_enabled"] is True
    assert resp.data["setpoint_degrees_c"] == 5.0
    assert resp.data["temperature_degrees_c"] == 5.5


def test_partially_supported_corrections_apply_what_they_can():
    """One unavailable toggle must not block the others."""
    features = set(sim.SR_SERIES_FEATURES) - {sim.FeatureID.NONLINEARITY_CAL}
    sim.set_sim_config(sim.SimConfig(features=frozenset(features)))
    drv = _connected()
    resp = drv.set_corrections(
        electric_dark=True, nonlinearity=True, saturation_check=True
    )
    assert resp.response == DriverResponseType.failed  # something was unavailable
    assert resp.data["electric_dark"] is True  # ...but this one applied
    assert resp.data["saturation_check"] is True
    assert isinstance(resp.data["nonlinearity"], str)  # error detail
    assert "NONLINEARITY_CAL" in resp.data["nonlinearity"]


def test_strobe_values_are_clamped_to_device_limits():
    drv = _connected()
    resp = drv.set_single_strobe(enable=True, delay_us=10**9, width_us=0)
    assert resp.response == DriverResponseType.success
    assert resp.data["delay_us"] == 1_000_000  # device maximum
    assert resp.data["width_us"] == 1  # device minimum
    assert resp.data["enabled"] is True


def test_light_source_index_is_bounds_checked():
    drv = _connected()
    ok = drv.set_light_source_enable(0, True)
    assert ok.response == DriverResponseType.success
    assert ok.data["enabled"] is True
    bad = drv.set_light_source_enable(5, True)
    assert bad.response == DriverResponseType.failed
    assert "out of range" in bad.message


# ----------------------------------------------------------------------
# Acquisition and peak detection
# ----------------------------------------------------------------------
def test_acquire_spectrum_returns_pixel_count_and_epoch():
    drv = _connected()
    spectrum, epoch_s = drv.acquire_spectrum()
    assert len(spectrum) == drv.n_pixels
    assert all(isinstance(x, float) for x in spectrum[:8])
    assert epoch_s > 0


def test_intensity_scales_with_integration_time():
    """A calibration loop needs a monotonic response to converge."""
    drv = _connected(int_time_us=1000)
    low, _ = drv.acquire_spectrum()
    drv.set_integration_time_us(10_000)
    high, _ = drv.acquire_spectrum()
    assert max(high) > max(low)


def test_peak_intensity_window_and_empty_window():
    drv = _connected(int_time_us=1000)
    spectrum, _ = drv.acquire_spectrum()
    # The synthetic spectrum peaks near 450 nm.
    in_window = drv.peak_intensity(spectrum, 440, 460)
    off_peak = drv.peak_intensity(spectrum, 700, 750)
    assert in_window is not None and off_peak is not None
    assert in_window > off_peak
    # A window outside the device's range selects nothing.
    assert drv.peak_intensity(spectrum, 1000, 1100) is None
    # No bounds at all is the whole spectrum.
    assert drv.peak_intensity(spectrum) == max(spectrum)


def test_peak_intensity_of_empty_spectrum_is_none():
    assert _connected().peak_intensity([]) is None


def test_dark_corrected_acquisition_requires_a_stored_dark():
    drv = _connected()
    with pytest.raises(sim.OceanDirectError):
        drv.acquire_spectrum(dark_corrected=True)
    resp = drv.store_dark_spectrum()
    assert resp.response == DriverResponseType.success
    assert resp.data["n_pixels"] == drv.n_pixels
    assert resp.data["dark_max"] >= resp.data["dark_min"]
    corrected, _ = drv.acquire_spectrum(dark_corrected=True)
    # Same light level as the dark, so the correction cancels out.
    assert max(abs(x) for x in corrected) == pytest.approx(0.0, abs=1e-9)


# ----------------------------------------------------------------------
# Long-format rows
# ----------------------------------------------------------------------
def test_build_rows_emits_five_equal_length_columns():
    drv = _connected()
    spectrum, epoch_s = drv.acquire_spectrum()
    rows = drv.build_rows([spectrum], [epoch_s])
    assert list(rows) == LONG_FORMAT_KEYS
    lengths = {len(v) for v in rows.values()}
    assert lengths == {drv.n_pixels}
    assert rows["wl"] == drv.pxwl
    assert rows["i"] == spectrum
    assert set(rows["spec_idx"]) == {0}
    assert set(rows["dev_ts_ns"]) == {None}


def test_build_rows_advances_and_resets_the_frame_counter():
    drv = _connected()
    spectrum, epoch_s = drv.acquire_spectrum()
    first = drv.build_rows([spectrum], [epoch_s])
    second = drv.build_rows([spectrum], [epoch_s])
    assert set(first["spec_idx"]) == {0}
    assert set(second["spec_idx"]) == {1}
    drv.reset_spec_idx()
    third = drv.build_rows([spectrum], [epoch_s])
    assert set(third["spec_idx"]) == {0}


def test_build_rows_frames_a_multi_spectrum_batch():
    drv = _connected()
    spectra = [drv.acquire_spectrum()[0] for _ in range(3)]
    rows = drv.build_rows(spectra, [1.0, 2.0, 3.0], dev_timestamps=[10, 20, 30])
    n = drv.n_pixels
    assert len(rows["spec_idx"]) == 3 * n
    assert rows["spec_idx"][:n] == [0] * n
    assert rows["spec_idx"][n : 2 * n] == [1] * n
    assert rows["spec_idx"][2 * n :] == [2] * n
    assert rows["dev_ts_ns"][0] == 10
    assert rows["dev_ts_ns"][-1] == 30
    assert rows["epoch_s"][0] == 1.0
    assert rows["epoch_s"][-1] == 3.0


def test_build_rows_of_nothing_is_empty():
    drv = _connected()
    assert drv.build_rows([], []) == {}
    # A spectrum with no pixels must not emit a ragged frame either.
    assert drv.build_rows([[]], [1.0]) == {}


def test_build_rows_trims_a_spectrum_longer_than_the_wavelength_axis():
    """Ragged columns would corrupt every downstream reader."""
    drv = _connected()
    spectrum, epoch_s = drv.acquire_spectrum()
    rows = drv.build_rows([spectrum + [1.0, 2.0, 3.0]], [epoch_s])
    assert {len(v) for v in rows.values()} == {drv.n_pixels}


# ----------------------------------------------------------------------
# HLO round-trip: the flattening bet
# ----------------------------------------------------------------------
def _write_hlo(path, header_lines, payloads):
    """Write an ``.hlo`` file the same way the data logger does."""
    with open(path, "w") as f:
        for line in header_lines:
            f.write(line + "\n")
        f.write("%%\n")
        for payload in payloads:
            f.write(hlo_json_dumps(payload) + "\n")


def test_array_packed_lines_read_back_as_one_row_per_pixel(tmp_path):
    """The whole data contract in one test.

    Three spectra are written as three array-packed lines. ``read_hlo``
    concatenates list-valued columns, so the result must be a flat
    ``3 * n_pixels`` long-format table whose per-spectrum framing is
    recoverable from ``spec_idx`` alone.
    """
    drv = _connected()
    spectra = [drv.acquire_spectrum()[0] for _ in range(3)]
    rows = drv.build_rows(spectra, [1.0, 2.0, 3.0], dev_timestamps=[100, 200, 300])
    # One line per spectrum on the wire...
    payloads = []
    n = drv.n_pixels
    for k in range(3):
        payloads.append({key: rows[key][k * n : (k + 1) * n] for key in rows})
    path = tmp_path / "spec.hlo"
    _write_hlo(path, ["optional:", f"  n_pixels: {n}"], payloads)
    assert sum(1 for _ in open(path)) == 3 + 3  # 2 header + separator + 3 data

    meta, data = read_hlo(str(path))
    # ...but 3 * n rows on read.
    assert set(data) == set(LONG_FORMAT_KEYS)
    assert {len(v) for v in data.values()} == {3 * n}

    # Framing survives: grouping on spec_idx recovers each spectrum exactly.
    for k, original in enumerate(spectra):
        idxs = [i for i, s in enumerate(data["spec_idx"]) if s == k]
        assert len(idxs) == n
        assert [data["i"][i] for i in idxs] == original
        assert [data["wl"][i] for i in idxs] == drv.pxwl
        assert {data["dev_ts_ns"][i] for i in idxs} == {(k + 1) * 100}
        assert {data["epoch_s"][i] for i in idxs} == {float(k + 1)}


def test_the_parquet_chunk_reader_flattens_identically(tmp_path):
    """``hlo_to_parquet`` reads through a different function; same contract."""
    drv = _connected()
    spectrum, _ = drv.acquire_spectrum()
    rows = drv.build_rows([spectrum], [1.0])
    path = tmp_path / "spec.hlo"
    _write_hlo(path, ["optional:", "  n_pixels: 2048"], [rows])

    _header, data_start = read_hlo_header(str(path))
    chunks = list(read_hlo_data_chunks(str(path), data_start, chunk_size=100))
    assert len(chunks) == 1
    chunk, chunk_len = chunks[0]
    assert set(chunk) == set(LONG_FORMAT_KEYS)
    assert {len(v) for v in chunk.values()} == {drv.n_pixels}
    assert chunk_len == drv.n_pixels


def test_every_emitted_value_is_json_serializable():
    """A non-serializable value is written as an error row, silently."""
    drv = _connected()
    spectrum, epoch_s = drv.acquire_spectrum()
    rows = drv.build_rows([spectrum], [epoch_s])
    decoded = json.loads(hlo_json_dumps(rows))
    assert set(decoded) == set(LONG_FORMAT_KEYS)
    assert decoded["dev_ts_ns"][0] is None  # None becomes JSON null, not "None"


# ----------------------------------------------------------------------
# Buffered capture
# ----------------------------------------------------------------------
def test_buffered_run_drains_more_than_one_batch_without_loss():
    """37 spectra cannot come back in one read: the vendor caps a read at 15."""
    drv = _connected()
    resp = drv.start_buffered(n_scans=37)
    assert resp.response == DriverResponseType.success
    assert drv.buffering is True
    assert resp.data["backtoback_scans"] == 37

    batches, total, timestamps = 0, 0, []
    while True:
        spectra, ts = drv.drain_buffered()
        if not spectra:
            break
        assert len(spectra) <= MAX_METADATA_BUFFER_SIZE
        batches += 1
        total += len(spectra)
        timestamps += ts
    assert total == 37
    assert batches == 3  # 15 + 15 + 7
    assert len(timestamps) == 37
    assert timestamps == sorted(timestamps)
    assert len(set(timestamps)) == 37  # no duplicated device timestamps

    assert drv.stop_buffered().response == DriverResponseType.success
    assert drv.buffering is False


def test_drain_request_is_capped_at_the_vendor_maximum():
    """Asking for more than 15 raises on the device; the driver must not."""
    drv = _connected()
    with pytest.raises(sim.OceanDirectError):
        drv.dev.Advanced.get_spectrum_with_metadata([], [], 16)
    drv.start_buffered(n_scans=20)
    spectra, _ = drv.drain_buffered(buffer_size=999)
    assert len(spectra) == MAX_METADATA_BUFFER_SIZE


def test_buffered_capture_requires_the_features():
    features = set(sim.SR_SERIES_FEATURES) - {sim.FeatureID.DATA_BUFFER}
    sim.set_sim_config(sim.SimConfig(features=frozenset(features)))
    drv = _connected()
    resp = drv.start_buffered(n_scans=5)
    assert resp.response == DriverResponseType.failed
    assert "DATA_BUFFER" in resp.message
    assert drv.buffering is False


def test_buffer_capacity_is_clamped_to_the_device_range():
    drv = _connected()
    resp = drv.start_buffered(n_scans=2, capacity=10**9)
    assert resp.response == DriverResponseType.success
    assert resp.data["buffer_capacity"] == 50_000


def test_disconnect_stops_a_running_buffered_capture():
    """Leaving the buffer armed would keep the device acquiring."""
    drv = _connected()
    drv.start_buffered(n_scans=10)
    assert drv.buffering is True
    assert drv.disconnect().response == DriverResponseType.success
    assert drv.buffering is False


def test_stop_reports_busy_status_while_buffering():
    drv = _connected()
    drv.start_buffered(n_scans=10)
    assert drv.get_status().status == DriverStatus.busy
    assert drv.stop().response == DriverResponseType.success
    assert drv.buffering is False
    assert drv.get_status().status == DriverStatus.ok


# ----------------------------------------------------------------------
# E-stop
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_estop_darkens_the_device_and_each_leg_is_independent():
    """A device lacking one leg must still get the others."""
    drv = _connected()
    drv.set_lamp_enable(True)
    drv.set_single_strobe(enable=True)
    drv.set_continuous_strobe(enable=True)
    drv.start_buffered(n_scans=5)

    assert await drv.estop(True) is True
    assert drv.buffering is False
    assert drv.dev.Advanced.get_enable_lamp() is False
    assert drv.dev.Advanced.get_single_strobe_enable() is False
    assert drv.dev.Advanced.get_continuous_strobe_enable() is False


@pytest.mark.asyncio
async def test_estop_survives_a_device_missing_every_leg():
    """No feature supported at all: estop still answers, and does not raise."""
    sim.set_sim_config(sim.SimConfig(features=frozenset({sim.FeatureID.SPECTROMETER})))
    drv = _connected()
    assert await drv.estop(True) is True
    assert await drv.estop(False) is False


@pytest.mark.asyncio
async def test_async_shutdown_closes_the_device():
    drv = _connected()
    resp = await drv.async_shutdown()
    assert resp.response == DriverResponseType.success
    assert drv.dev is None


# ----------------------------------------------------------------------
# Vendor-import behaviour
# ----------------------------------------------------------------------
def test_missing_vendor_package_is_a_clean_failure_not_an_import_error():
    """The module must import on Linux; connect() reports the missing wheel."""
    drv = OceanDirectSpec(config={"simulate": False})
    resp = drv.connect()
    # No oceandirect wheel in this environment, so this is the real path.
    assert resp.response == DriverResponseType.failed
    assert resp.status == DriverStatus.uninitialized
    assert "oceandirect not installed" in resp.message
