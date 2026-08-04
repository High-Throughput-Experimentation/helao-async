"""The private digital-out endpoints the engineering control panel drives.

These exist so a panel toggle is *not* an action: it must not write a row into
the run record and must not queue behind whatever the orchestrator is running
on that server. That is a property of how the endpoint is registered, not of
what it returns, so these tests assert the registration too — a route that
slipped back under ``tags=["action"]``, or under the ``/{server_key}/`` prefix,
would still work and would still be wrong.

Neither server's hardware is present here (gclib and NI-DAQmx are both
Windows-only vendor SDKs), so the drivers are stubbed at the two methods the
endpoints call. What is under test is the server layer: name resolution, the
bool coercion, and the shape of the ``(error_code, {name: state})`` pair.

Run directly (``python -m pytest`` on this file) — the hte suite is not part of
``run_unit_tests.py``.
"""

import asyncio

import pytest

from helao.core.error import ErrorCodes
from helao.deploy.hte.servers.action.galil_io import do_value_to_bool


class _FakeRoute:
    def __init__(self, path, tags, fn):
        self.path = path
        self.tags = tags
        self.fn = fn


class _FakeApp:
    """Captures what ``*_dyn_endpoints`` registers, instead of a real FastAPI."""

    def __init__(self, driver, server_params=None, server_name="IO"):
        self.driver = driver
        self.server_params = server_params or {}
        self.routes = {}

        class _Server:
            server_name = None

        class _Base:
            pass

        self.base = _Base()
        self.base.server = _Server()
        self.base.server.server_name = server_name

    def post(self, path, tags=None, **kwargs):
        def _register(fn):
            self.routes[path] = _FakeRoute(path, tags or [], fn)
            return fn

        return _register


# --------------------------------------------------------------------------
# do_value_to_bool
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (" 1.0000", True),  # what gclib actually hands back
        (" 0.0000", False),
        ("1", True),
        ("0", False),
        (1.0, True),
        (True, True),
        (False, False),
        (None, None),  # not read -> unknown, NOT off
        ("", None),
        ("nonsense", None),
    ],
)
def test_do_value_to_bool(raw, expected):
    assert do_value_to_bool(raw) is expected


def test_unreadable_line_is_unknown_not_off():
    # The distinction the control panel depends on: a line whose readback
    # failed must not render identically to a line that is off.
    assert do_value_to_bool(None) is not False
    assert do_value_to_bool("nonsense") is not False


# --------------------------------------------------------------------------
# galil_io
# --------------------------------------------------------------------------


class _FakeGalil:
    """The four attributes/methods galil_dyn_endpoints touches for DO."""

    def __init__(self, dev_do, readback=" 1.0000"):
        self.dev_do = dev_do
        self.dev_ai = {}
        self.dev_ao = {}
        self.dev_di = {}
        self.dev_doitems = None
        self.dev_diitems = None
        self.galil_enabled = True
        self.writes = []
        self._readback = readback

    def connect(self):
        class _Resp:
            status = "ok"

        return _Resp()

    async def get_digital_out(self, do_name="", **kwargs):
        if do_name not in self.dev_do:
            return {"error_code": ErrorCodes.not_available, "value": None}
        return {"error_code": ErrorCodes.none, "value": self._readback}

    async def set_digital_out(self, on=False, do_name="", **kwargs):
        self.writes.append((do_name, on))
        return {
            "error_code": ErrorCodes.none,
            "value": " 1.0000" if on else " 0.0000",
        }


def _galil_app(dev_do, readback=" 1.0000"):
    from helao.deploy.hte.servers.action.galil_io import galil_dyn_endpoints

    app = _FakeApp(_FakeGalil(dev_do, readback))
    asyncio.run(galil_dyn_endpoints(app))
    return app


def test_galil_private_routes_are_private_and_unprefixed():
    app = _galil_app({"gamry_aux": 1, "Thorlab_led": 7})

    for path in ("/get_digital_outs", "/set_digital_out"):
        assert path in app.routes, sorted(app.routes)
        route = app.routes[path]
        # Private, so no action is created...
        assert route.tags == ["private"], route.tags
        # ...and unprefixed, because /{server_key}/ is the action namespace.
        assert not route.path.startswith("/IO/"), route.path

    # The action twins are still there and still actions.
    assert app.routes["/IO/set_digital_out"].tags == ["action"]
    print("test_galil_private_routes_are_private_and_unprefixed PASS")


def test_galil_get_digital_outs_covers_every_configured_line():
    app = _galil_app({"gamry_aux": 1, "Thorlab_led": 7}, readback=" 0.0000")
    error_code, states = asyncio.run(app.routes["/get_digital_outs"].fn())

    assert error_code == ErrorCodes.none
    assert states == {"gamry_aux": False, "Thorlab_led": False}
    print("test_galil_get_digital_outs_covers_every_configured_line PASS")


def test_galil_set_digital_out_writes_and_reports_readback():
    app = _galil_app({"gamry_aux": 1})
    error_code, states = asyncio.run(
        app.routes["/set_digital_out"].fn(do_name="gamry_aux", on=True)
    )

    assert error_code == ErrorCodes.none
    assert app.driver.writes == [("gamry_aux", True)]
    # The post-write state comes back, so a panel needs no second round trip.
    assert states == {"gamry_aux": True}

    _, states = asyncio.run(
        app.routes["/set_digital_out"].fn(do_name="gamry_aux", on=False)
    )
    assert states == {"gamry_aux": False}
    print("test_galil_set_digital_out_writes_and_reports_readback PASS")


def test_galil_set_digital_out_refuses_an_unconfigured_name():
    app = _galil_app({"gamry_aux": 1})
    error_code, states = asyncio.run(
        app.routes["/set_digital_out"].fn(do_name="not_a_line", on=True)
    )

    assert error_code == ErrorCodes.not_available
    assert states == {}
    assert app.driver.writes == [], "an unconfigured name must not reach the driver"
    print("test_galil_set_digital_out_refuses_an_unconfigured_name PASS")


# --------------------------------------------------------------------------
# nidaqmx
# --------------------------------------------------------------------------


#: The shape of a real station's NI block (anec.yml), trimmed.
NI_PARAMS = {
    "dev_pump": {"PeriPump1": "cDAQ1Mod1/port0/line9"},
    "dev_gasvalve": {"CO2": "cDAQ1Mod1/port0/line0", "Ar": "cDAQ1Mod1/port0/line2"},
    "dev_led": {"led": "cDAQ1Mod1/port0/line11"},
}


def test_nidaqmx_groups_flatten_into_one_namespace():
    from helao.deploy.hte.servers.action.nidaqmx_server import build_do_port_map

    do_ports, do_owners = build_do_port_map(NI_PARAMS)

    # Every configured line across every group — a panel needs a control for
    # each one, and this server has no single dev_do block to read them from.
    assert set(do_ports) == {"PeriPump1", "CO2", "Ar", "led"}
    # The port comes from the group that declared the name.
    assert do_ports["PeriPump1"] == "cDAQ1Mod1/port0/line9"
    assert do_ports["CO2"] == "cDAQ1Mod1/port0/line0"
    assert do_owners["led"] == ["dev_led"]
    print("test_nidaqmx_groups_flatten_into_one_namespace PASS")


def test_nidaqmx_flags_a_name_two_groups_claim():
    # No config in this repo does this, but nothing forbids it either, and
    # picking either group would drive the wrong physical line — so the map
    # records both owners and the endpoint refuses the name.
    from helao.deploy.hte.servers.action.nidaqmx_server import build_do_port_map

    _, do_owners = build_do_port_map(
        {
            "dev_gasvalve": {"shared": "cDAQ1Mod1/port0/line0"},
            "dev_liquidvalve": {"shared": "cDAQ1Mod1/port0/line1"},
        }
    )
    assert do_owners["shared"] == ["dev_gasvalve", "dev_liquidvalve"]
    assert len(do_owners["shared"]) > 1, "the endpoint's refusal condition"
    print("test_nidaqmx_flags_a_name_two_groups_claim PASS")


def test_nidaqmx_map_is_empty_when_no_group_is_configured():
    # The endpoints are registered only when this is non-empty, so a server
    # with no digital outputs gains no private routes.
    from helao.deploy.hte.servers.action.nidaqmx_server import build_do_port_map

    assert build_do_port_map({}) == ({}, {})
    assert build_do_port_map({"dev_monitor": {"T1": "ai0"}}) == ({}, {})
    print("test_nidaqmx_map_is_empty_when_no_group_is_configured PASS")


def test_nidaqmx_do_groups_match_the_endpoints_that_take_on_bool():
    """The map must cover exactly the groups with a togglable endpoint.

    A group added to the server without being added to ``DO_GROUPS`` would be
    invisible to the control panel, with nothing raised — so this reads the
    server's own source rather than restating the list.
    """
    import re
    from pathlib import Path

    from helao.deploy.hte.servers.action import nidaqmx_server
    from helao.deploy.hte.servers.action.nidaqmx_server import DO_GROUPS

    src = Path(nidaqmx_server.__file__).read_text()
    # Each toggle endpoint is registered under `if dev_<group>:` and takes a
    # `<x>items` enum built from that group.
    togglable = set()
    for m in re.finditer(
        r"async def \w+\(\n\s+\w+: (dev_\w+)items = None,\n\s+on: bool", src
    ):
        togglable.add(m.group(1))

    assert togglable, "found no on:bool endpoints — did the signatures change?"
    assert togglable == set(DO_GROUPS), (
        f"DO_GROUPS and the on:bool endpoints disagree: "
        f"only in endpoints={togglable - set(DO_GROUPS)}, "
        f"only in DO_GROUPS={set(DO_GROUPS) - togglable}"
    )
    print("test_nidaqmx_do_groups_match_the_endpoints_that_take_on_bool PASS")


def test_nidaqmx_driver_mirror_starts_unknown_and_records_writes():
    """``cNIMAX.do_state`` is the only DO state this server can report.

    NI-DAQmx gives no readback for a line held by a one-shot task, so an
    unwritten name must be absent (rendered unknown) rather than present as
    ``False`` — the line may be energised from a previous run.
    """
    from helao.deploy.hte.drivers.io.nidaqmx_driver import cNIMAX

    driver = cNIMAX.__new__(cNIMAX)  # no connect(), no NI-DAQmx import
    driver.do_state = {}

    assert driver.do_state.get("CO2") is None, "unwritten must not read as off"

    # What the endpoint reports is `state.get(name)` over the configured names.
    driver.do_state["CO2"] = True
    reported = {name: driver.do_state.get(name) for name in ("CO2", "Ar")}
    assert reported == {"CO2": True, "Ar": None}
    print("test_nidaqmx_driver_mirror_starts_unknown_and_records_writes PASS")
