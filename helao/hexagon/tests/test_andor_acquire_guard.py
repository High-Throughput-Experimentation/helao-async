"""The two runtime refusals in ``andor_server``, and the calibrate_wl executor.

``acquire`` refuses when the driver has no wavelength axis; ``adjust_nd``
refuses when the driver is not the spectrograph variant, because that station
has no software-controlled ND filter wheel. Both routes are registered
unconditionally -- the frozen route checklist is an AST extraction of source,
so a decorator wrapped in a config test would keep the source surface uniform
while the live OpenAPI silently differed per station.

Worth its own tier of test rather than trusting inspection: ``app.driver`` is
UNTYPED throughout ``andor_server``. The module writes ``app.driver:
AndorDriver`` as a bare annotation on an attribute expression, which pyright
rejects (``reportInvalidTypeForm``) and never applies, so nothing in that file
type-checks against the driver contract.

The registrar is exercised against a synthetic ``ActionHost``-shaped app -- the
same pattern ``test_endpoint_overlay`` uses -- because the point is what the
handler does before ``ctx.begin``, not how the real host wires it up.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from helao.core.error import ErrorCodes
from helao.deploy.hte.drivers.spec.andor.calibrated import AndorCalibratedDriver
from helao.deploy.hte.drivers.spec.andor.spectrograph import (
    AndorSpectrographDriver,
)
from helao.deploy.hte.servers.action.andor_server import (
    AndorCalibrateWavelength,
    andor_dyn_endpoints,
)

SERVER_KEY = "ANDOR"


class _ReachedBegin(Exception):
    """Raised by the fake ``begin`` on the non-refusing path."""


class _FakeApp:
    """The subset of ``ActionHost`` ``andor_dyn_endpoints`` actually reads."""

    def __init__(self, wl_arr, driver=None):
        if driver is None:
            driver = SimpleNamespace(wl_arr=wl_arr)
        driver.wl_arr = wl_arr
        driver.connect = lambda: SimpleNamespace(status="ok")
        self.driver = driver
        self.server = SimpleNamespace(server_name=SERVER_KEY)
        self.server_params: dict = {}
        self.executors: dict = {}
        self.handlers: dict = {}

    def action(self, *args, **kwargs):
        def decorate(func):
            self.handlers[func.__name__] = func
            return func

        return decorate


class _FakeActive:
    def __init__(self):
        self.action = SimpleNamespace(error_code=ErrorCodes.none, action_abbr=None)
        self.finished = False

    async def finish(self):
        self.finished = True
        return SimpleNamespace(as_dict=lambda: {"error_code": self.action.error_code})


class _FakeCtx:
    def __init__(self, *, raise_on_begin=False):
        self.begin_kwargs = None
        self.active = _FakeActive()
        self._raise_on_begin = raise_on_begin

    async def begin(self, **kwargs):
        self.begin_kwargs = kwargs
        if self._raise_on_begin:
            raise _ReachedBegin
        return self.active


async def _registered_acquire(wl_arr):
    app = _FakeApp(wl_arr)
    await andor_dyn_endpoints(app)  # type: ignore[arg-type]
    return app, app.handlers["acquire"]


@pytest.mark.asyncio
async def test_acquire_refuses_without_a_wavelength_axis():
    """A fallback pixel index would record a run against a fabricated axis."""
    _app, acquire = await _registered_acquire(None)
    ctx = _FakeCtx()

    result = await acquire(ctx)

    assert ctx.begin_kwargs == {}, "the refusal opens a bare action, no data keys"
    assert ctx.active.action.error_code == ErrorCodes.critical_error
    assert ctx.active.finished, "the refused action is finished, not left active"
    assert result == {"error_code": ErrorCodes.critical_error}


@pytest.mark.asyncio
async def test_acquire_proceeds_when_a_wavelength_axis_exists():
    """The guard must not fire on a calibrated station."""
    _app, acquire = await _registered_acquire(np.linspace(400.0, 900.0, 4))
    ctx = _FakeCtx(raise_on_begin=True)

    with pytest.raises(_ReachedBegin):
        await acquire(ctx)

    assert ctx.begin_kwargs is not None
    assert ctx.begin_kwargs["json_data_keys"] == [
        "elapsed_time_s",
        "ch_0000",
        "ch_0001",
        "ch_0002",
        "ch_0003",
    ]
    assert ctx.begin_kwargs["hloheader"].optional["wl"] == [
        pytest.approx(v) for v in np.linspace(400.0, 900.0, 4)
    ]


# --- adjust_nd refuses on a station with no ND wheel -----------------------
#
# The route is registered on both variants, so the guard is the only thing
# standing between a calibrated station and `AndorSpectrographDriver.adjust_ND`
# being called on a driver that does not define it. pyright cannot check the
# isinstance below for the reason in the module docstring, so it is checked
# here instead.


async def _registered_adjust_nd(driver):
    app = _FakeApp(wl_arr=None, driver=driver)
    await andor_dyn_endpoints(app)  # type: ignore[arg-type]
    return app, app.handlers["adjust_nd"]


@pytest.mark.asyncio
async def test_adjust_nd_refuses_on_the_calibrated_variant():
    """That station's ND filter is set by hand; there is no wheel to drive."""
    driver = AndorCalibratedDriver(config={"dev_id": 0})
    _app, adjust_nd = await _registered_adjust_nd(driver)
    ctx = _FakeCtx()

    result = await adjust_nd(ctx)

    assert ctx.begin_kwargs == {}
    assert ctx.active.action.error_code == ErrorCodes.critical_error
    assert ctx.active.finished, "the refused action is finished, not left active"
    assert result == {"error_code": ErrorCodes.critical_error}


@pytest.mark.asyncio
async def test_adjust_nd_proceeds_on_the_spectrograph_variant():
    """The guard must not fire on the station that does have a wheel."""
    driver = AndorSpectrographDriver(config={"dev_id": 0})
    _app, adjust_nd = await _registered_adjust_nd(driver)
    ctx = _FakeCtx(raise_on_begin=True)

    with pytest.raises(_ReachedBegin):
        await adjust_nd(ctx)


@pytest.mark.asyncio
async def test_adjust_nd_refuses_a_driver_that_is_neither_variant():
    """`isinstance`, not a `wl_source` string: a stub app must not drive ND."""
    _app, adjust_nd = await _registered_adjust_nd(None)
    ctx = _FakeCtx()

    assert (await adjust_nd(ctx)) == {"error_code": ErrorCodes.critical_error}


@pytest.mark.asyncio
async def test_calibrate_wl_is_registered_on_both_variants():
    """Registration is unconditional; only the handler bodies differ."""
    for driver in (
        AndorCalibratedDriver(config={"dev_id": 0}),
        AndorSpectrographDriver(config={"dev_id": 0}),
    ):
        app = _FakeApp(wl_arr=None, driver=driver)
        await andor_dyn_endpoints(app)  # type: ignore[arg-type]
        assert "calibrate_wl" in app.handlers


# --- the calibrate_wl executor ---------------------------------------------


class _FakeCalibActive:
    """Just enough ``Active`` for ``Executor.__init__`` and ``_exec``."""

    def __init__(self, driver, action_params):
        self.driver = driver
        self.action = SimpleNamespace(
            action_name="calibrate_wl",
            action_uuid="0000-uuid",
            action_params=action_params,
            exec_id=None,
        )


def _fake_lamp_frame(n_pixels, line_pixels):
    pixels = np.arange(n_pixels, dtype=float)
    counts = np.full(n_pixels, 100.0)
    for p in line_pixels:
        counts += 5000.0 * np.exp(-0.5 * ((pixels - p) / 2.0) ** 2)
    return counts


@pytest.mark.asyncio
async def test_the_executor_forwards_a_successful_calibration(tmp_path, monkeypatch):
    driver = AndorCalibratedDriver(
        config={"dev_id": 0, "states_root": str(tmp_path), "host": "teststation"}
    )
    line_pixels = [200, 700, 1300, 1900, 2400]
    monkeypatch.setattr(
        driver,
        "_capture_lamp_frame",
        lambda n_frames, exp_time: _fake_lamp_frame(2560, line_pixels),
    )
    active = _FakeCalibActive(
        driver,
        {
            "lamp_lines_nm": [400.0 + 0.2 * p for p in line_pixels],
            "lamp": "Hg-Ar",
            "degree": 1,
        },
    )
    executor = AndorCalibrateWavelength(active=active, oneoff=True)

    result = await executor._exec()

    assert result["error"] == ErrorCodes.none
    assert result["data"]["n_lines"] == 5
    assert result["data"]["applied"] is True
    assert result["data"]["lamp"] == "Hg-Ar"


@pytest.mark.asyncio
async def test_the_executor_reports_a_failed_calibration_without_raising(
    tmp_path, monkeypatch
):
    """The failed DriverResponse carries no `data`; reading a field would raise.

    An operator whose lamp was off, or whose lines did not resolve, must get a
    reported failure. Indexing `resp.data` unguarded would instead raise out of
    `_exec` and turn every failure into a crash -- the one case where the
    action's own error report is the only diagnostic there is.
    """
    driver = AndorCalibratedDriver(
        config={"dev_id": 0, "states_root": str(tmp_path), "host": "teststation"}
    )
    monkeypatch.setattr(
        driver,
        "_capture_lamp_frame",
        lambda n_frames, exp_time: _fake_lamp_frame(2560, [200]),
    )
    active = _FakeCalibActive(
        driver, {"lamp_lines_nm": [400.0, 500.0, 600.0, 700.0, 800.0], "degree": 3}
    )
    executor = AndorCalibrateWavelength(active=active, oneoff=True)

    result = await executor._exec()

    assert result["error"] == ErrorCodes.critical_error
    assert result["data"] == {}


@pytest.mark.asyncio
async def test_the_executor_defaults_an_empty_lamp_line_list_to_none(tmp_path):
    """`lamp_lines_nm: list = []` is the route default; [] must mean "use the
    reference table", not "fit against no lines"."""
    driver = AndorCalibratedDriver(config={"dev_id": 0, "states_root": str(tmp_path)})
    executor = AndorCalibrateWavelength(
        active=_FakeCalibActive(driver, {"lamp_lines_nm": []}), oneoff=True
    )
    assert executor.lamp_lines_nm is None
    assert executor.lamp == "Hg-Ar"
    assert executor.n_frames == 1
    assert executor.degree == 3
    assert executor.driver is driver
