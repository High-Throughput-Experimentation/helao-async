"""Server-layer tests for the OceanDirect spectrometer action server.

No hardware and no vendor wheel are present, so the driver runs against
``oceandirect_sim`` and the FastAPI host is replaced by ``_FakeApp``, which
captures what ``oceandirect_dyn_endpoints`` registers. What is under test is
the server layer: route registration and tagging, that handlers read their
parameters from ``action_params`` rather than their own function arguments,
the long-format data contract reaching the data sink, and the buffered
executor's lifecycle.

Route registration is asserted, not just handler behaviour: an acquisition
route that slipped out from under the ``/{server_key}/`` prefix, or a private
endpoint that acquired an ``action`` tag, would still work and would still be
wrong.

Run directly (``python -m pytest`` on this file) -- the hte suite is not part
of ``run_unit_tests.py``.
"""

import asyncio
import inspect
import threading
import time
from typing import Optional
from uuid import uuid4

import pytest

from helao.core.drivers.helao_driver import DriverResponseType
from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.deploy.hte.drivers.spec import oceandirect_sim as sim
from helao.deploy.hte.drivers.spec.oceandirect_driver import OceanDirectSpec
from helao.deploy.hte.drivers.spec.oceandirect_enum import (
    LONG_FORMAT_KEYS,
    SINGLE_SHOT_KEYS,
    SRTrigMode,
)
from helao.deploy.hte.servers.action import oceandirect_server as srv
from helao.hexagon.app.action_context import collect_default_params


# ----------------------------------------------------------------------
# Fakes
# ----------------------------------------------------------------------
class _FakeRoute:
    def __init__(self, path, tags, fn):
        self.path = path
        self.tags = tags
        self.fn = fn


class _FakeAction:
    """Stands in for ``helao.helpers.premodels.Action``."""

    def __init__(self, action_name="test_action", action_params=None):
        self.action_name = action_name
        self.action_uuid = uuid4()
        self.action_params = action_params if action_params is not None else {}
        self.action_abbr = None
        self.error_code = ErrorCodes.none
        self.samples_in = []
        self.file_conn_keys = [uuid4()]
        self.exec_id = None
        self.finished = False

    def as_dict(self):
        return {
            "action_name": self.action_name,
            "action_params": self.action_params,
            "error_code": self.error_code,
            "samples_in": self.samples_in,
            "finished": self.finished,
        }


class _FakeSession:
    """Stands in for the ``ActionSession`` returned by ``ctx.begin``."""

    def __init__(self, action, driver, begin_kwargs):
        self.action = action
        self.driver = driver
        self.begin_kwargs = begin_kwargs
        self.enqueued: list[dict] = []
        self.appended_samples: list = []
        self.hlo_header_finished = False
        self.started_executor = None

    async def enqueue_data_dflt(self, datadict):
        self.enqueued.append(datadict)

    async def append_sample(self, samples, IO):
        self.appended_samples.append((IO, list(samples)))

    def get_realtime_nowait(self, epoch_ns=None, offset=None):
        return 0

    def finish_hlo_header(self, realtime=None, file_conn_keys=None):
        self.hlo_header_finished = True

    def start_executor(self, executor):
        self.started_executor = executor
        return {"started": executor.exec_id}

    async def finish(self):
        self.action.finished = True
        return self.action


class _FakeContext:
    """Stands in for ``ActionContext``: carries the Action, opens a session."""

    def __init__(self, action, driver):
        self.action = action
        self.driver = driver
        self.session: Optional[_FakeSession] = None

    async def begin(self, **kwargs):
        self.session = _FakeSession(self.action, self.driver, kwargs)
        return self.session


class _FakeUnifiedDB:
    """Sample API stub: returns whatever it was seeded with."""

    def __init__(self, base=None, samples=None):
        self.base = base
        self._samples = samples if samples is not None else []

    async def init_db(self):
        return None

    async def get_samples(self, samples_in):
        return list(self._samples)


class _FakeSample:
    def __init__(self, label="sim__solid__1_1"):
        self.label = label
        self.inheritance = None
        self.status_reset_to = None

    def get_global_label(self):
        return self.label

    def reset_sample_status(self, status):
        self.status_reset_to = status


class _FakeApp:
    """Captures what ``oceandirect_dyn_endpoints`` registers."""

    def __init__(self, driver, server_name="SPEC_OD"):
        self.driver = driver
        self.server_params = {}
        self.routes: dict[str, _FakeRoute] = {}
        self.executors: dict = {}
        self.unified_db = None

        class _Server:
            pass

        self.server = _Server()
        self.server.server_name = server_name

    @property
    def base(self):
        return self

    def post(self, path, tags=None, **kwargs):
        def _register(fn):
            self.routes[path] = _FakeRoute(path, tags or [], fn)
            return fn

        return _register

    def action(self, **route_kwargs):
        def _decorate(fn):
            path = route_kwargs.pop("path", f"/{self.server.server_name}/{fn.__name__}")
            tags = route_kwargs.pop("tags", ["action"])
            return self.post(path, tags=tags, **route_kwargs)(fn)

        return _decorate


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_sim():
    sim.reset_sim()
    yield
    sim.reset_sim()


@pytest.fixture
def built(monkeypatch):
    """Build the fake app with endpoints registered against a simulated device."""
    samples: list = []
    monkeypatch.setattr(
        srv,
        "UnifiedSampleDataAPI",
        lambda base: _FakeUnifiedDB(base=base, samples=samples),
    )
    driver = OceanDirectSpec(config={"simulate": True, "int_time_us": 50_000})
    app = _FakeApp(driver)
    asyncio.run(srv.oceandirect_dyn_endpoints(app))
    # Expose the sample list so a test can decide what get_samples returns.
    app._samples = samples  # type: ignore[attr-defined]
    return app


def _call(app, action_name, **overrides):
    """Invoke a registered action handler the way the host would.

    ``action_params`` is seeded from the handler's own declared defaults using
    the real ``collect_default_params``, then overridden -- so a handler that
    reads its function argument instead of ``action_params`` is caught, because
    the two disagree.
    """
    route = app.routes[f"/{app.server.server_name}/{action_name}"]
    fn = route.fn
    params = collect_default_params(inspect.signature(fn))
    params.pop("fast_samples_in", None)
    params.update(overrides)
    action = _FakeAction(action_name=action_name, action_params=dict(params))
    ctx = _FakeContext(action, app.driver)
    result = asyncio.run(fn(ctx))
    return ctx, result


# ----------------------------------------------------------------------
# Registration
# ----------------------------------------------------------------------
def test_private_endpoints_are_bare_paths_tagged_private(built):
    for name in (
        "get_device_info",
        "get_wl",
        "get_tec_status",
        "get_buffered_count",
        "get_acquisition_delay",
    ):
        route = built.routes[f"/{name}"]
        assert route.tags == ["private"]
        # A private endpoint must not sit under the action prefix.
        assert f"/{built.server.server_name}/" not in route.path


def test_action_endpoints_are_prefixed_and_tagged_action(built):
    expected = {
        "acquire_spec",
        "acquire_spec_adv",
        "acquire_spec_corrected",
        "acquire_spec_buffered",
        "acquire_spec_extrig",
        "calibrate_intensity",
        "store_dark_spectrum",
        "set_corrections",
        "stop_buffered_after",
        "stop_extrig_after",
        "set_trigger_mode",
        "set_acquisition_delay",
        "set_tec",
        "set_shutter",
        "set_lamp",
        "set_light_source",
        "set_single_strobe",
        "set_continuous_strobe",
    }
    for name in expected:
        route = built.routes[f"/{built.server.server_name}/{name}"]
        assert route.tags == ["action"]
    # And nothing else was registered under the action prefix.
    prefixed = {
        p.rsplit("/", 1)[-1]
        for p in built.routes
        if p.startswith(f"/{built.server.server_name}/")
    }
    assert prefixed == expected


def test_concurrent_actions_are_disabled(built):
    """One spectrometer cannot serve two acquisitions, and the vendor
    requires discovery/open to be serialized."""
    assert built.server_params["allow_concurrent_actions"] is False


def test_driver_is_connected_during_endpoint_registration(built):
    assert built.driver.ready is True
    assert built.driver.n_pixels == 2048


def test_every_acquisition_handler_declares_microsecond_integration_time(built):
    """A parameter named ``int_time_ms`` here would silently mean 1000x less."""
    for name in (
        "acquire_spec",
        "acquire_spec_adv",
        "acquire_spec_corrected",
        "acquire_spec_buffered",
        "acquire_spec_extrig",
    ):
        route = built.routes[f"/{built.server.server_name}/{name}"]
        params = inspect.signature(route.fn).parameters
        assert "int_time_us" in params
        assert "int_time_ms" not in params


# ----------------------------------------------------------------------
# Private endpoint behaviour
# ----------------------------------------------------------------------
def test_get_device_info_returns_the_capability_matrix(built):
    info = built.routes["/get_device_info"].fn()
    assert info["model"] == "SIM-SR2"
    assert info["n_pixels"] == 2048
    assert set(info["features"]) == {f.name for f in sim.FeatureID}
    assert info["features"]["DATA_BUFFER"] is True
    assert info["features"]["SHUTTER"] is False


def test_get_wl_returns_the_wavelength_axis(built):
    wl = built.routes["/get_wl"].fn()
    assert len(wl) == 2048
    assert wl == sorted(wl)


def test_get_buffered_count_is_zero_when_idle(built):
    assert built.routes["/get_buffered_count"].fn() == {"buffered_spectra": 0}


# ----------------------------------------------------------------------
# Acquisition
# ----------------------------------------------------------------------
def test_acquire_spec_emits_one_long_format_payload(built):
    ctx, result = _call(built, "acquire_spec", int_time_us=50_000, duration_sec=-1)
    session = ctx.session
    assert len(session.enqueued) == 1
    payload = session.enqueued[0]
    assert list(payload) == SINGLE_SHOT_KEYS
    assert "dev_ts_ns" not in payload  # get_spectrum() carries no metadata
    assert {len(v) for v in payload.values()} == {2048}
    assert set(payload["spec_idx"]) == {0}
    assert result["finished"] is True
    assert result["error_code"] == ErrorCodes.none


def test_begin_pins_the_column_order_and_ships_the_wavelength_header(built):
    """Inferring json_data_keys from the first message would be order-dependent."""
    ctx, _ = _call(built, "acquire_spec")
    kwargs = ctx.session.begin_kwargs
    # The single-shot session declares only what it can fill.
    assert kwargs["json_data_keys"] == SINGLE_SHOT_KEYS
    assert kwargs["action_abbr"] == "OPT"
    optional = kwargs["hloheader"].optional
    assert len(optional["wl"]) == 2048
    assert optional["model"] == "SIM-SR2"
    assert optional["serial_number"] == "SIM-SR2-0001"
    assert optional["n_pixels"] == 2048


def test_handler_reads_integration_time_from_action_params(built):
    """The override reaches the device only if action_params is the source."""
    ctx, _ = _call(built, "acquire_spec", int_time_us=250_000)
    assert built.driver.dev.get_integration_time() == 250_000
    assert ctx.session.action.action_params["applied_int_time_us"] == 250_000


def test_out_of_range_integration_time_is_clamped_and_recorded(built):
    ctx, _ = _call(built, "acquire_spec", int_time_us=10**12)
    assert ctx.session.action.action_params["applied_int_time_us"] == 10_000_000


def test_duration_loop_emits_multiple_framed_spectra(built):
    ctx, _ = _call(built, "acquire_spec", int_time_us=1000, duration_sec=0.05)
    session = ctx.session
    assert len(session.enqueued) >= 2
    # Frames are consecutive and distinct across the whole action.
    seen = [sorted(set(p["spec_idx"]))[0] for p in session.enqueued]
    assert seen == list(range(len(session.enqueued)))
    assert session.action.action_params["spectra_emitted"] == len(session.enqueued)


def test_acquire_spec_adv_applies_on_device_processing(built):
    ctx, _ = _call(
        built,
        "acquire_spec_adv",
        int_time_us=1000,
        scans_to_average=4,
        boxcar_width=3,
        peak_lower_wl=440,
        peak_upper_wl=460,
    )
    p = ctx.session.action.action_params
    assert p["applied_processing"] == {"scans_to_average": 4, "boxcar_width": 3}
    assert built.driver.dev.get_scans_to_average() == 4
    assert built.driver.dev.get_boxcar_width() == 3
    assert p["peak_intensity"] is not None


def test_acquire_spec_adv_records_but_survives_unsupported_processing(built):
    """Losing the measurement over an unavailable refinement would be worse."""
    features = set(sim.SR_SERIES_FEATURES)
    sim.set_sim_config(sim.SimConfig(features=frozenset(features)))

    def _boom(*args, **kwargs):
        raise sim.OceanDirectError(-99, "scans_to_average unavailable")

    built.driver.dev.set_scans_to_average = _boom  # type: ignore[method-assign]
    ctx, result = _call(built, "acquire_spec_adv", int_time_us=1000, scans_to_average=4)
    assert result["error_code"] == ErrorCodes.critical_error
    # ...and a spectrum was still acquired and emitted.
    assert len(ctx.session.enqueued) == 1
    assert list(ctx.session.enqueued[0]) == SINGLE_SHOT_KEYS


def test_acquire_spec_aborts_when_integration_time_cannot_be_set(built):
    def _boom(*args, **kwargs):
        raise sim.OceanDirectError(-98, "integration time unavailable")

    built.driver.dev.set_integration_time = _boom  # type: ignore[method-assign]
    ctx, result = _call(built, "acquire_spec", int_time_us=1000)
    assert result["error_code"] == ErrorCodes.critical_error
    # Acquiring at an unknown integration time would produce uncomparable data.
    assert ctx.session.enqueued == []


# ----------------------------------------------------------------------
# Intensity calibration
# ----------------------------------------------------------------------
def test_calibrate_intensity_converges_into_the_target_window(built):
    ctx, _ = _call(
        built,
        "calibrate_intensity",
        int_time_us=1000,
        target_peak_min=30000,
        target_peak_max=32000,
        max_iters=8,
        max_int_time_us=10_000_000,
    )
    p = ctx.session.action.action_params
    assert p["in_target_window"] is True
    assert 30000 <= p["peak_intensity"] <= 32000
    assert p["calibrated_int_time_us"] > 1000
    # Every iteration's spectrum was recorded, not just the final one.
    assert len(ctx.session.enqueued) == p["calibration_iters"] + 1


def test_calibration_respects_the_device_maximum_over_the_caller_ceiling(built):
    """A ceiling above the hardware limit must not loop forever at the cap."""
    ctx, _ = _call(
        built,
        "calibrate_intensity",
        int_time_us=1000,
        target_peak_min=10**9,  # unreachable
        target_peak_max=10**10,
        max_iters=20,
        max_int_time_us=10**15,
    )
    p = ctx.session.action.action_params
    assert p["in_target_window"] is False
    assert p["calibrated_int_time_us"] <= built.driver.int_time_max_us
    assert p["max_int_time_reached"] is True


def test_calibration_stops_when_the_integration_time_stops_moving(built):
    """Otherwise it would repeat an identical measurement to max_iters."""
    ctx, _ = _call(
        built,
        "calibrate_intensity",
        int_time_us=10_000_000,  # already at the device maximum
        target_peak_min=10**9,
        target_peak_max=10**10,
        max_iters=50,
    )
    p = ctx.session.action.action_params
    assert p["calibration_iters"] <= 1
    assert len(ctx.session.enqueued) <= 2


# ----------------------------------------------------------------------
# Corrections
# ----------------------------------------------------------------------
def test_store_dark_then_corrected_acquisition(built):
    _ctx, dark = _call(built, "store_dark_spectrum", int_time_us=50_000)
    assert dark["error_code"] == ErrorCodes.none
    assert dark["action_params"]["n_pixels"] == 2048
    assert dark["action_params"]["dark_mean"] is not None

    ctx, result = _call(built, "acquire_spec_corrected", int_time_us=50_000)
    assert result["error_code"] == ErrorCodes.none
    payload = ctx.session.enqueued[0]
    assert list(payload) == SINGLE_SHOT_KEYS
    # Same light level as the dark, so the correction cancels out.
    assert max(abs(x) for x in payload["i"]) == pytest.approx(0.0, abs=1e-9)


def test_corrected_acquisition_without_a_dark_is_an_error_not_raw_data(built):
    """Emitting uncorrected data that claims to be corrected is the failure
    mode worth preventing."""
    ctx, result = _call(built, "acquire_spec_corrected", int_time_us=50_000)
    assert result["error_code"] == ErrorCodes.critical_error
    assert ctx.session.enqueued == []
    assert "no dark stored" in ctx.session.action.action_params["error_detail"]


def test_set_corrections_reports_partial_support(built):
    features = set(sim.SR_SERIES_FEATURES) - {sim.FeatureID.NONLINEARITY_CAL}
    sim.set_sim_config(sim.SimConfig(features=frozenset(features)))
    driver = OceanDirectSpec(config={"simulate": True})
    driver.connect()
    built.driver = driver
    ctx, result = _call(built, "set_corrections", electric_dark=True, nonlinearity=True)
    applied = ctx.session.action.action_params["applied_corrections"]
    assert applied["electric_dark"] is True
    assert isinstance(applied["nonlinearity"], str)
    assert result["error_code"] == ErrorCodes.critical_error


# ----------------------------------------------------------------------
# Device control
# ----------------------------------------------------------------------
def test_set_tec_round_trips_and_records(built):
    ctx, result = _call(built, "set_tec", enable=True, setpoint_degrees_c=7.5)
    assert result["error_code"] == ErrorCodes.none
    applied = ctx.session.action.action_params["applied_tec"]
    assert applied["tec_enabled"] is True
    assert applied["setpoint_degrees_c"] == 7.5


def test_unsupported_shutter_finishes_with_an_error_and_does_not_raise(built):
    ctx, result = _call(built, "set_shutter", open_shutter=True)
    assert result["error_code"] == ErrorCodes.critical_error
    assert result["finished"] is True
    assert ctx.session.enqueued[0]["message"].find("SHUTTER") != -1


def test_trigger_mode_is_read_back(built):
    ctx, result = _call(built, "set_trigger_mode", mode=int(SRTrigMode.ext_edge))
    assert result["error_code"] == ErrorCodes.none
    applied = ctx.session.action.action_params["applied_trigger_mode"]
    assert applied["requested"] == 1
    assert applied["mode_name"] == "ext_edge"
    assert applied["trigger_mode"] == 1
    assert applied["int_time_from_pulse_width"] is False


def test_a_non_sr_trigger_mode_is_refused_with_the_real_options(built):
    """Mode 3 is the FX/HDX convention this enum used to carry; an SR device
    rejects it, and the refusal should say what the options are."""
    ctx, result = _call(built, "set_trigger_mode", mode=3)

    assert result["error_code"] == ErrorCodes.critical_error
    message = ctx.session.enqueued[0]["message"]
    assert "not an SR-series trigger mode" in message
    assert "0=software" in message and "2=ext_level" in message


def test_level_mode_reports_that_the_pulse_owns_the_integration_time(built):
    ctx, _result = _call(built, "set_trigger_mode", mode=int(SRTrigMode.ext_level))
    applied = ctx.session.action.action_params["applied_trigger_mode"]
    assert applied["int_time_from_pulse_width"] is True


def test_lamp_and_light_source_and_strobes(built):
    _c1, r1 = _call(built, "set_lamp", enable=True)
    assert r1["error_code"] == ErrorCodes.none
    _c2, r2 = _call(built, "set_light_source", index=0, enable=True)
    assert r2["error_code"] == ErrorCodes.none
    c3, r3 = _call(built, "set_single_strobe", enable=True, delay_us=50, width_us=10)
    assert r3["error_code"] == ErrorCodes.none
    assert c3.session.action.action_params["applied_single_strobe"]["delay_us"] == 50
    c4, r4 = _call(
        built, "set_continuous_strobe", enable=True, period_us=2000, width_us=100
    )
    assert r4["error_code"] == ErrorCodes.none
    assert (
        c4.session.action.action_params["applied_continuous_strobe"]["period_us"]
        == 2000
    )


def test_bad_light_source_index_is_rejected(built):
    _ctx, result = _call(built, "set_light_source", index=9, enable=True)
    assert result["error_code"] == ErrorCodes.critical_error


# ----------------------------------------------------------------------
# Buffered capture endpoint and executor
# ----------------------------------------------------------------------
def _buffered_call(app, **overrides):
    """Invoke ``acquire_spec_buffered``, which validates before ``begin``."""
    route = app.routes[f"/{app.server.server_name}/acquire_spec_buffered"]
    fn = route.fn
    params = collect_default_params(inspect.signature(fn))
    params.pop("fast_samples_in", None)
    params.update(overrides)
    action = _FakeAction(
        action_name="acquire_spec_buffered", action_params=dict(params)
    )
    ctx = _FakeContext(action, app.driver)
    return ctx, asyncio.run(fn(ctx))


def test_buffered_endpoint_rejects_no_sample_without_creating_a_session(built):
    """The no-sample branch must produce an error code and no artifacts."""
    built.driver.allow_no_sample = False
    ctx, result = _buffered_call(built, n_scans=5)
    assert result["error_code"] == ErrorCodes.no_sample
    assert ctx.session is None  # no session, therefore no files


def test_buffered_endpoint_allows_no_sample_when_configured(built):
    built.driver.allow_no_sample = True
    ctx, result = _buffered_call(built, n_scans=5)
    assert ctx.session is not None
    assert result == {"started": ctx.session.started_executor.exec_id}
    assert isinstance(ctx.session.started_executor, srv.OceanDirectBufferExec)
    assert ctx.session.started_executor.oneoff is False


def test_buffered_endpoint_registers_samples_and_finishes_the_header(built):
    built._samples.append(_FakeSample())
    built.driver.allow_no_sample = False
    ctx, _ = _buffered_call(built, n_scans=5)
    session = ctx.session
    assert session.hlo_header_finished is True
    assert session.begin_kwargs["sample_global_labels"] == ["sim__solid__1_1"]
    assert session.begin_kwargs["json_data_keys"] == LONG_FORMAT_KEYS
    assert session.begin_kwargs["file_type"] == "spec_helao__file"
    assert session.appended_samples[0][0] == "in"


def test_buffered_endpoint_aborts_on_bad_integration_time(built):
    def _boom(*args, **kwargs):
        raise sim.OceanDirectError(-97, "nope")

    built.driver.dev.set_integration_time = _boom  # type: ignore[method-assign]
    ctx, result = _buffered_call(built, n_scans=5)
    assert result["error_code"] == ErrorCodes.critical_error
    assert ctx.session is None


def _executor(driver, **params):
    """Build the buffered executor over a fake session."""
    defaults = {
        "n_scans": 40,
        "n_spectra": None,
        "buffer_capacity": None,
        "duration": -1,
        "dry_polls_to_finish": 2,
        "poll_rate": 0.0,
    }
    defaults.update(params)
    action = _FakeAction(action_name="acquire_spec_buffered", action_params=defaults)
    session = _FakeSession(action, driver, {})
    return srv.OceanDirectBufferExec(active=session, oneoff=False, poll_rate=0.0)


def test_executor_drains_the_whole_burst_across_batches(built):
    """40 spectra cannot arrive in one read; the vendor caps a read at 15."""
    ex = _executor(built.driver, n_scans=40, dry_polls_to_finish=1)
    assert asyncio.run(ex._pre_exec())["error"] == ErrorCodes.none
    assert built.driver.buffering is True

    payloads, statuses = [], []
    for _ in range(20):
        result = asyncio.run(ex._poll())
        statuses.append(result["status"])
        if result["data"]:
            payloads.append(result["data"])
        if result["status"] == HloStatus.finished:
            break
    assert statuses[-1] == HloStatus.finished
    assert ex.emitted == 40

    # Frames are consecutive with no gaps or repeats across the whole run.
    frames = []
    for payload in payloads:
        # Five keys here, unlike the single-shot path: the buffered drain is
        # the only source of a device timestamp.
        assert list(payload) == LONG_FORMAT_KEYS
        assert {len(v) for v in payload.values()} == {len(payload["spec_idx"])}
        frames += sorted(set(payload["spec_idx"]))
    assert frames == list(range(40))
    # Device timestamps came through, unlike on the single-shot path.
    assert all(t is not None for t in payloads[0]["dev_ts_ns"])

    asyncio.run(ex._post_exec())
    assert built.driver.buffering is False
    assert ex.active.action.action_params["spectra_emitted"] == 40


def test_executor_stops_at_the_requested_spectrum_count(built):
    """A full batch must not overshoot n_spectra."""
    ex = _executor(built.driver, n_scans=40, n_spectra=17)
    asyncio.run(ex._pre_exec())
    total = 0
    for _ in range(20):
        result = asyncio.run(ex._poll())
        total += len(set(result["data"].get("spec_idx", [])))
        if result["status"] == HloStatus.finished:
            break
    assert ex.emitted == 17
    assert total == 17
    asyncio.run(ex._post_exec())


def test_executor_finishes_when_the_buffer_runs_dry(built):
    ex = _executor(built.driver, n_scans=3, dry_polls_to_finish=2)
    asyncio.run(ex._pre_exec())
    statuses = [asyncio.run(ex._poll())["status"] for _ in range(6)]
    assert HloStatus.finished in statuses
    assert ex.emitted == 3


def test_executor_does_not_finish_on_a_dry_first_poll(built):
    """An early poll can arrive before the device filled its first scan."""
    ex = _executor(built.driver, n_scans=5, dry_polls_to_finish=1)
    asyncio.run(ex._pre_exec())
    built.driver.dev.Advanced.clear_data_buffer()  # buffer empty, nothing emitted yet
    result = asyncio.run(ex._poll())
    assert result["status"] == HloStatus.active
    assert ex.emitted == 0
    assert ex.dry_polls == 1


def test_executor_finishes_on_duration(built):
    ex = _executor(built.driver, n_scans=10_000, duration=0.01)
    asyncio.run(ex._pre_exec())
    ex.start_time -= 1.0  # duration already elapsed
    result = asyncio.run(ex._poll())
    assert result["status"] == HloStatus.finished
    asyncio.run(ex._post_exec())


def test_executor_reports_a_failed_arming_instead_of_polling(built):
    features = set(sim.SR_SERIES_FEATURES) - {sim.FeatureID.DATA_BUFFER}
    sim.set_sim_config(sim.SimConfig(features=frozenset(features)))
    driver = OceanDirectSpec(config={"simulate": True})
    driver.connect()
    ex = _executor(driver, n_scans=5)
    assert asyncio.run(ex._pre_exec())["error"] == ErrorCodes.critical_error
    assert ex.armed is False
    # A poll after a failed arming must terminate, not spin.
    assert asyncio.run(ex._poll())["status"] == HloStatus.finished


def test_manual_stop_disarms_the_device(built):
    ex = _executor(built.driver, n_scans=100)
    asyncio.run(ex._pre_exec())
    assert built.driver.buffering is True
    assert asyncio.run(ex._manual_stop())["error"] == ErrorCodes.none
    assert built.driver.buffering is False
    assert ex.armed is False


def test_executor_resets_the_frame_counter_per_run(built):
    """spec_idx is per-action; a second run must start at 0."""
    ex1 = _executor(built.driver, n_scans=3, dry_polls_to_finish=1)
    asyncio.run(ex1._pre_exec())
    for _ in range(5):
        if asyncio.run(ex1._poll())["status"] == HloStatus.finished:
            break
    asyncio.run(ex1._post_exec())

    ex2 = _executor(built.driver, n_scans=3, dry_polls_to_finish=1)
    asyncio.run(ex2._pre_exec())
    first = asyncio.run(ex2._poll())
    assert min(first["data"]["spec_idx"]) == 0


def test_stop_buffered_after_signals_only_matching_executors(built):
    class _StubExec:
        def __init__(self):
            self.stopped = False

        def stop_action_task(self):
            self.stopped = True

    matching = _StubExec()
    other = _StubExec()
    built.executors = {
        f"acquire_spec_buffered {uuid4()}": matching,
        f"acquire_spec {uuid4()}": other,
    }
    ctx, result = _call(built, "stop_buffered_after", delay=0)
    assert matching.stopped is True
    assert other.stopped is False
    assert len(ctx.session.action.action_params["stopped_executors"]) == 1
    assert result["finished"] is True


# ----------------------------------------------------------------------
# Externally-triggered capture: the path for a device with no buffer
# ----------------------------------------------------------------------
def _bufferless_driver() -> OceanDirectSpec:
    """A connected driver for a device with no DATA_BUFFER/BACK_TO_BACK.

    This is the real OCEANSR4's shape, and the reason the triggered path
    exists: OceanDirectBufferExec cannot arm on it at all.
    """
    features = set(sim.SR_SERIES_FEATURES) - {
        sim.FeatureID.DATA_BUFFER,
        sim.FeatureID.BACK_TO_BACK,
    }
    sim.set_sim_config(sim.SimConfig(model="OCEANSR4", features=frozenset(features)))
    driver = OceanDirectSpec(config={"simulate": True})
    driver.connect()
    return driver


def test_a_bufferless_device_is_told_where_to_go_instead():
    """The refusal must name the alternative, or a station finds a dead
    endpoint and no way forward."""
    resp = _bufferless_driver().start_buffered(n_scans=10)

    assert resp.response == DriverResponseType.failed
    assert "DATA_BUFFER" in resp.message
    assert "acquire_spec_extrig" in resp.message


def _extrig_exec(driver, **params):
    """Build the triggered executor over a fake session."""
    defaults = {
        # 1 = external edge. Mode 3 was used here before and is not an
        # SR-series mode at all.
        "trigger_mode": 1,
        "acquisition_delay_us": None,
        "n_spectra": None,
        "duration": -1,
        "read_timeout_s": 0.2,
        "poll_rate": 0.0,
    }
    defaults.update(params)
    action = _FakeAction(action_name="acquire_spec_extrig", action_params=defaults)
    session = _FakeSession(action, driver, {})
    return srv.OceanDirectExtrigExec(active=session, oneoff=False, poll_rate=0.0)


def test_the_triggered_path_works_without_a_buffer():
    """The whole point: an OCEANSR4 can still run a long acquisition."""
    driver = _bufferless_driver()
    ex = _extrig_exec(driver, n_spectra=3)

    assert asyncio.run(ex._pre_exec())["error"] == ErrorCodes.none
    assert driver.armed_trigger_mode == int(SRTrigMode.ext_edge)

    payloads = []
    for _ in range(10):
        result = asyncio.run(ex._poll())
        if result["data"]:
            payloads.append(result["data"])
        if result["status"] == HloStatus.finished:
            break
    assert ex.emitted == 3
    # No dev_ts_ns: get_spectrum() carries no metadata on this path.
    assert all(list(pl) == SINGLE_SHOT_KEYS for pl in payloads)
    assert [sorted(set(pl["spec_idx"]))[0] for pl in payloads] == [0, 1, 2]

    asyncio.run(ex._post_exec())
    # Disarmed, or the next unrelated read on this server would block forever.
    assert driver.armed_trigger_mode is None
    assert ex.active.action.action_params["spectra_emitted"] == 3


def test_a_trigger_that_never_comes_keeps_waiting_rather_than_failing(built):
    """A timed-out read is the normal "still waiting" state. Treating it as an
    error would end a run whose trigger was merely late."""
    driver = built.driver
    ex = _extrig_exec(driver, read_timeout_s=0.02)
    asyncio.run(ex._pre_exec())

    def _slow(*args, **kwargs):
        time.sleep(0.4)  # outlives read_timeout_s, but bounded for the suite
        return [0.0] * driver.n_pixels

    driver.dev.get_spectrum = _slow  # type: ignore[method-assign]
    result = asyncio.run(ex._poll())

    assert result["status"] == HloStatus.active
    assert result["error"] == ErrorCodes.none
    assert result["data"] == {}
    assert ex.waits == 1
    assert ex.emitted == 0


def test_the_triggered_run_finishes_on_duration(built):
    ex = _extrig_exec(built.driver, duration=0.01)
    asyncio.run(ex._pre_exec())
    ex.start_time -= 1.0

    assert asyncio.run(ex._poll())["status"] == HloStatus.finished
    asyncio.run(ex._post_exec())
    assert built.driver.armed_trigger_mode is None


def test_a_failed_arming_does_not_poll(built):
    driver = built.driver

    def _boom(*args, **kwargs):
        raise sim.OceanDirectError(-11, "trigger mode unsupported")

    driver.dev.set_trigger_mode = _boom  # type: ignore[method-assign]
    ex = _extrig_exec(driver)

    assert asyncio.run(ex._pre_exec())["error"] == ErrorCodes.critical_error
    assert ex.armed is False
    assert asyncio.run(ex._poll())["status"] == HloStatus.finished


def test_manual_stop_disarms_the_trigger(built):
    """Leaving the device armed would hang the next read on this server."""
    ex = _extrig_exec(built.driver)
    asyncio.run(ex._pre_exec())
    assert built.driver.armed_trigger_mode is not None

    assert asyncio.run(ex._manual_stop())["error"] == ErrorCodes.none

    assert built.driver.armed_trigger_mode is None
    assert ex.armed is False


def test_the_triggered_read_does_not_hold_the_driver_lock(built):
    """A minutes-long wait must not serialize disconnect() behind it, or
    server shutdown hangs until someone fires a trigger."""
    driver = built.driver
    entered = threading.Event()
    release = threading.Event()

    def _blocking():
        entered.set()
        release.wait(timeout=5)
        return [0.0] * driver.n_pixels

    driver.dev.get_spectrum = _blocking  # type: ignore[method-assign]
    worker = threading.Thread(
        target=lambda: driver.acquire_spectrum(serialize=False), daemon=True
    )
    worker.start()
    assert entered.wait(timeout=5)

    # The lock must be free while that read is in flight.
    assert driver._lock.acquire(blocking=False) is True
    driver._lock.release()
    release.set()
    worker.join(timeout=5)


def test_a_serialized_read_does_hold_the_lock(built):
    """The unserialized path is an opt-in for the triggered case only."""
    driver = built.driver
    entered = threading.Event()
    release = threading.Event()

    def _blocking():
        entered.set()
        release.wait(timeout=5)
        return [0.0] * driver.n_pixels

    driver.dev.get_spectrum = _blocking  # type: ignore[method-assign]
    worker = threading.Thread(target=driver.acquire_spectrum, daemon=True)
    worker.start()
    assert entered.wait(timeout=5)

    assert driver._lock.acquire(blocking=False) is False
    release.set()
    worker.join(timeout=5)


def test_stop_extrig_after_disarms_and_signals_only_its_own_executors(built):
    class _StubExec:
        def __init__(self):
            self.stopped = False

        def stop_action_task(self):
            self.stopped = True

    matching = _StubExec()
    other = _StubExec()
    built.executors = {
        f"acquire_spec_extrig {uuid4()}": matching,
        f"acquire_spec_buffered {uuid4()}": other,
    }
    built.driver.arm_trigger(int(SRTrigMode.ext_edge))

    ctx, result = _call(built, "stop_extrig_after", delay=0)

    assert matching.stopped is True
    assert other.stopped is False
    assert built.driver.armed_trigger_mode is None
    assert len(ctx.session.action.action_params["stopped_executors"]) == 1
    assert result["finished"] is True


def _extrig_call(app):
    """Invoke the acquire_spec_extrig endpoint the way the host would."""
    route = app.routes[f"/{app.server.server_name}/acquire_spec_extrig"]
    params = collect_default_params(inspect.signature(route.fn))
    params.pop("fast_samples_in", None)
    action = _FakeAction(action_name="acquire_spec_extrig", action_params=dict(params))
    ctx = _FakeContext(action, app.driver)
    return ctx, asyncio.run(route.fn(ctx))


def test_the_extrig_endpoint_rejects_no_sample_without_a_session(built):
    built.driver.allow_no_sample = False
    ctx, result = _extrig_call(built)

    assert result["error_code"] == ErrorCodes.no_sample
    assert ctx.session is None  # no session, therefore no artifacts


def test_the_extrig_endpoint_declares_the_timestamp_free_column_set(built):
    built.driver.allow_no_sample = True
    ctx, _result = _extrig_call(built)

    assert ctx.session.begin_kwargs["json_data_keys"] == SINGLE_SHOT_KEYS
    assert isinstance(ctx.session.started_executor, srv.OceanDirectExtrigExec)
    assert ctx.session.started_executor.oneoff is False


# ----------------------------------------------------------------------
# The extrig endpoint against the manual's trigger semantics
# ----------------------------------------------------------------------
def _extrig_call_with(app, **overrides):
    route = app.routes[f"/{app.server.server_name}/acquire_spec_extrig"]
    params = collect_default_params(inspect.signature(route.fn))
    params.pop("fast_samples_in", None)
    params.update(overrides)
    action = _FakeAction(action_name="acquire_spec_extrig", action_params=dict(params))
    ctx = _FakeContext(action, app.driver)
    return ctx, asyncio.run(route.fn(ctx))


def test_the_extrig_default_is_the_external_edge_mode(built):
    """It defaulted to 3 -- the FX/HDX edge value -- which no SR device
    accepts, so the endpoint's own default could never have worked."""
    route = built.routes[f"/{built.server.server_name}/acquire_spec_extrig"]
    defaults = collect_default_params(inspect.signature(route.fn))
    assert defaults["trigger_mode"] == int(SRTrigMode.ext_edge) == 1


def test_a_non_sr_mode_is_refused_without_opening_a_session(built):
    built.driver.allow_no_sample = True
    ctx, result = _extrig_call_with(built, trigger_mode=3)

    assert result["error_code"] == ErrorCodes.not_available
    assert ctx.session is None  # nothing armed, no artifacts


def test_level_mode_skips_the_integration_time_and_records_that(built):
    """The pulse width owns integration in mode 2, so writing int_time_us
    would imply control the caller does not have."""
    built.driver.allow_no_sample = True
    before = built.driver.dev.get_integration_time()

    ctx, _result = _extrig_call_with(
        built, trigger_mode=int(SRTrigMode.ext_level), int_time_us=987_000
    )

    p = ctx.session.action.action_params
    assert p["int_time_ignored"] is True
    assert "applied_int_time_us" not in p
    assert built.driver.dev.get_integration_time() == before


def test_edge_mode_does_apply_the_integration_time(built):
    built.driver.allow_no_sample = True
    ctx, _result = _extrig_call_with(
        built, trigger_mode=int(SRTrigMode.ext_edge), int_time_us=50_000
    )

    p = ctx.session.action.action_params
    assert p["int_time_ignored"] is False
    assert p["applied_int_time_us"] == 50_000


def test_the_acquisition_delay_is_applied_before_arming(built):
    ex = _extrig_exec(built.driver, acquisition_delay_us=2500)

    assert asyncio.run(ex._pre_exec())["error"] == ErrorCodes.none

    p = ex.active.action.action_params
    assert p["applied_acquisition_delay"]["acquisition_delay_us"] == 2500
    assert built.driver.dev.get_acquisition_delay() == 2500
    assert built.driver.armed_trigger_mode == int(SRTrigMode.ext_edge)


def test_an_unavailable_acquisition_delay_does_not_abort_the_run(built):
    """The delay is a refinement; a device that cannot offer it can still be
    triggered, so this warns and continues."""

    def _boom(*args, **kwargs):
        raise sim.OceanDirectError(-13, "acquisition delay unsupported")

    built.driver.dev.set_acquisition_delay = _boom  # type: ignore[method-assign]
    ex = _extrig_exec(built.driver, acquisition_delay_us=1000)

    assert asyncio.run(ex._pre_exec())["error"] == ErrorCodes.none
    assert ex.armed is True


def test_an_all_zero_frame_is_counted_and_still_recorded(built):
    """An under-width level pulse yields all zeros with no error. The frame is
    real data as far as the device is concerned, so it is recorded -- but
    counted, because a run of them means the pulse is too short."""
    driver = built.driver
    driver.dev.get_spectrum = lambda: [0.0] * driver.n_pixels  # type: ignore[method-assign]
    ex = _extrig_exec(driver, trigger_mode=int(SRTrigMode.ext_level), n_spectra=2)
    asyncio.run(ex._pre_exec())

    for _ in range(6):
        if asyncio.run(ex._poll())["status"] == HloStatus.finished:
            break

    assert ex.emitted == 2
    assert ex.zero_frames == 2
    asyncio.run(ex._post_exec())
    assert ex.active.action.action_params["zero_frames"] == 2


def test_a_normal_frame_is_not_counted_as_zero(built):
    ex = _extrig_exec(built.driver, n_spectra=1)
    asyncio.run(ex._pre_exec())
    for _ in range(4):
        if asyncio.run(ex._poll())["status"] == HloStatus.finished:
            break
    assert ex.emitted == 1
    assert ex.zero_frames == 0


def test_the_delay_action_and_getter_agree(built):
    ctx, result = _call(built, "set_acquisition_delay", delay_us=4321)

    assert result["error_code"] == ErrorCodes.none
    applied = ctx.session.action.action_params["applied_acquisition_delay"]
    assert applied["acquisition_delay_us"] == 4321
    assert built.routes["/get_acquisition_delay"].fn()["acquisition_delay_us"] == 4321


# ----------------------------------------------------------------------
# makeApp
# ----------------------------------------------------------------------
def test_make_app_wires_the_driver_and_dyn_endpoints():
    """Asserted without constructing an ActionHost, which would bind ports."""
    src = inspect.getsource(srv.makeApp)
    assert "driver_classes=[OceanDirectSpec]" in src
    assert "dyn_endpoints=oceandirect_dyn_endpoints" in src
    assert srv.makeApp.__annotations__["return"].__name__ == "ActionHost"
