"""`wl_source` picks the driver class, and its default keeps hispec.yml valid.

The default matters more than the key does. `test_hte_builds_on_linux.py`
loads every station config and calls makeApp; hispec.yml declares no
`wl_source`, and it must not need editing for this change to land.

Also covers a Critical wiring debt paid off in this task: `BaseAPI`
constructs a driver as `driver_class(config=self.server_params)`, with no
`server_key=` and nothing that knows the station's STATES directory.
`makeApp` now sets both directly on `app.driver` after construction, so a
second andor server on the same host does not collide on one calibration
filename and the calibration file is not written cwd-relative.
"""

from pathlib import Path

import pytest

from helao.deploy.hte.drivers.spec.andor.calibrated import AndorCalibratedDriver
from helao.deploy.hte.drivers.spec.andor.spectrograph import AndorSpectrographDriver
from helao.deploy.hte.servers.action import andor_server
from helao.helpers import config_loader


@pytest.fixture
def with_config(monkeypatch):
    def _set(params):
        monkeypatch.setattr(
            config_loader,
            "CONFIG",
            {"servers": {"ANDOR": {"group": "action", "params": params}}},
        )

    return _set


def test_an_absent_key_yields_the_spectrograph_driver(with_config):
    """hispec.yml has no wl_source and must keep working untouched."""
    with_config({"dev_id": 0})
    assert andor_server._driver_class("ANDOR") is AndorSpectrographDriver


def test_spectrograph_is_selectable_explicitly(with_config):
    with_config({"dev_id": 0, "wl_source": "spectrograph"})
    assert andor_server._driver_class("ANDOR") is AndorSpectrographDriver


def test_calibration_selects_the_calibrated_driver(with_config):
    with_config({"dev_id": 0, "wl_source": "calibration"})
    assert andor_server._driver_class("ANDOR") is AndorCalibratedDriver


def test_an_unknown_value_is_refused_loudly(with_config):
    """A typo must not silently fall through to the default."""
    with_config({"dev_id": 0, "wl_source": "spectograph"})
    with pytest.raises(ValueError, match="spectograph"):
        andor_server._driver_class("ANDOR")


def test_no_config_at_all_still_yields_the_default(monkeypatch):
    """makeApp is called outside the launcher by tests and capture scripts."""
    monkeypatch.setattr(config_loader, "CONFIG", None)
    assert andor_server._driver_class("ANDOR") is AndorSpectrographDriver


def test_a_server_key_absent_from_config_yields_the_default(with_config):
    with_config({"dev_id": 0, "wl_source": "calibration"})
    assert andor_server._driver_class("SOME_OTHER_KEY") is AndorSpectrographDriver


# --- Wiring: app.driver.server_key / app.driver._base_hook -----------------
#
# Building a real ActionHost needs a real config (build_wiring KeyErrors on a
# server_key/host/port it can't find), so these use the actual hispec.yml
# config via load_global_config rather than the bare-dict fixture above --
# the same seam test_hte_builds_on_linux.py uses to build hte servers on
# Linux with no hardware attached.
#
# The wiring itself only exists once app.driver does, and ActionHost builds
# the driver inside its FastAPI startup handler (action_host.py), not
# synchronously in __init__ -- makeApp() alone leaves app.driver None. So
# these run the startup handlers over ASGI, the same seam
# test_action_writes_artifacts.py uses for the same reason.


@pytest.fixture
def hispec_andor_alt_key(monkeypatch):
    """A second andor server key cloned from hispec's ANDOR entry.

    Deliberately NOT "ANDOR": server_key defaults to "ANDOR" on the driver
    (driver.py's __init__ signature), so asserting against "ANDOR" would pass
    on the broken default and prove nothing about the wiring fix. Cloning
    hispec's real entry (rather than hand-rolling one) keeps `host`/`port`
    valid for `build_wiring`.
    """
    from helao.helpers.config_loader import load_global_config

    load_global_config("hispec", set_global=True)
    servers = config_loader.CONFIG["servers"]
    servers["ANDOR_ALT"] = dict(servers["ANDOR"])
    monkeypatch.setattr(config_loader, "CONFIG", config_loader.CONFIG)
    return "ANDOR_ALT"


async def _started_app(server_key: str):
    """Build the andor host and run its startup handlers.

    ``httpx.ASGITransport`` does not run lifespan events, and the startup
    handler is what constructs ``app.driver`` and calls ``connect()`` (via
    ``andor_dyn_endpoints``) -- without it the wiring under test has not
    happened yet. ``connect()`` fails harmlessly with no vendor SDK on Linux
    (caught broadly in ``AndorDriver.connect``); it is the wiring beforehand,
    not the connect outcome, that these tests check.

    ``startup_event`` (the sync handler below) fires ``dyn_endpoints_init``
    via a bare ``asyncio.gather(...)`` -- fire-and-forget, not awaited -- so
    that Task's completion relative to anything after ``handler()`` returns
    is not guaranteed. Awaiting ``init_endpoint_status`` directly here, with
    ``app._dyn_endpoints`` passed explicitly, makes the wiring + connect()
    complete deterministically before this returns (the abandoned gather
    Task then runs ``andor_dyn_endpoints`` a harmless second time, or not at
    all if the loop closes first).
    """
    app = andor_server.makeApp(server_key)
    for handler in app.router.on_startup:
        # _rpc_startup binds a co-located ZMQ ROUTER port; no part of this
        # wiring check needs it, and it can collide with a running rig.
        if handler.__name__ == "_rpc_startup":
            continue
        result = handler()
        if hasattr(result, "__await__"):
            await result
    await app.init_endpoint_status(app._dyn_endpoints)
    return app


@pytest.mark.asyncio
async def test_the_driver_carries_the_real_server_key(hispec_andor_alt_key):
    app = await _started_app(hispec_andor_alt_key)
    assert app.driver.server_key == hispec_andor_alt_key
    assert app.driver.server_key != "ANDOR"  # the class default; must be overridden


@pytest.mark.asyncio
async def test_the_driver_is_base_hooked_to_its_app(hispec_andor_alt_key):
    app = await _started_app(hispec_andor_alt_key)
    assert app.driver._base_hook is app


@pytest.mark.asyncio
async def test_calibration_file_resolves_under_the_configured_states_root(
    hispec_andor_alt_key,
):
    app = await _started_app(hispec_andor_alt_key)
    calib_path = app.driver.calibration_file()
    # Not the cwd-relative fallback ("STATES", resolved against the process
    # cwd) that calibration_file() falls back to when nothing sets
    # _base_hook -- the very bug this task fixes.
    assert calib_path.parent == Path(app.helaodirs.states_root)
    assert calib_path.parent != Path("STATES").resolve()
    assert hispec_andor_alt_key in calib_path.name


# --- Route surface: the frozen record is untouched, the addition is listed --


def test_adjust_nd_is_still_frozen_and_calibrate_wl_is_listed():
    """adjust_nd survives this work; only calibrate_wl is added."""
    import json

    frozen = json.loads(
        Path("helao/hexagon/tests/checklists/hte/andor_server.json").read_text()
    )
    paths = {r["path"] for r in frozen}
    assert "/ANDOR/adjust_nd" in paths, "the frozen record must not have been edited"
    assert "/ANDOR/calibrate_wl" not in paths, "additions go in _additions.json"

    additions = json.loads(
        Path("helao/hexagon/tests/checklists/hte/_additions.json").read_text()
    )
    entry = [a for a in additions if a["path"] == "/ANDOR/calibrate_wl"]
    assert len(entry) == 1, "calibrate_wl must be listed exactly once"
    assert entry[0]["module"] == "andor_server.py"
    assert entry[0]["method"] == "post"
