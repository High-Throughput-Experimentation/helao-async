"""The private motion endpoints the engineering control panel drives.

These exist so a panel move is *not* an action: it must not write a row into
the run record and must not queue behind whatever the orchestrator is running
on that server. That is a property of how the route is registered, not of what
it returns, so the registration is asserted too -- a route that slipped back
under ``tags=["action"]``, or under the ``/{server_key}/`` prefix, would still
work and would still be wrong.

Three risks carry the weight here.

**The commanded value.** A ``units="counts"`` move must reach the controller
as the integer that was typed. The galil half drives the *real* driver through
a fake command channel and asserts the emitted command strings, because
``_motor_move`` funnels every fault into a plausible-looking ``ErrorCodes``
value -- a return-code assertion would pass over a broken branch.

**The discriminators.** ``units`` and ``mode`` are enums so that ``"count"``,
the plausible misspelling, cannot fall through to the millimetre branch and
execute a 10 000-*count* move as 10 000 *millimetres*. FastAPI must answer
422. Asserting that needs real request validation, so the private routes are
mirrored onto a real ``FastAPI`` app and exercised over ``TestClient``.

**Panel-vs-orchestrator concurrency.** A move issued while an action is
running must be *refused* with ``ErrorCodes.in_progress`` and reach no device,
while a stop must halt regardless -- and must halt without de-energizing,
since a de-energized vertical axis drops.

**Dispatch, not completion.** ``/move_axis`` answers as soon as the move is
launched: ``_motor_move`` settle-polls to a 30-minute cap while the panel
dispatches with a 5 s timeout, so a blocking route reported every move longer
than about five seconds as failed while it was succeeding -- and an operator
shown that retries, issuing a second move. Two consequences are asserted here:
a move must return without waiting for the stage, and a failure *after*
dispatch must reach the log, since the return value can no longer carry it.
Tests that assert what reached the controller therefore await the dispatched
task (``_galil_move``) instead of the endpoint alone.

Neither server's hardware is present (``gclib`` is Windows-only and no
Thorlabs stage is attached), but neither is needed: the galil vendor seam is
``GalilCommandChannel`` and the Kinesis one is ``Thorlabs.KinesisMotor``, and
both are replaced with recorders.

Run directly (``python -m pytest`` on this file) -- the hte suite is not part
of ``run_unit_tests.py``.
"""

import asyncio
import time
import types
from typing import Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from helao.core.error import ErrorCodes
from helao.core.servers.motion_control import Units
from helao.deploy.hte.drivers.motion import kinesis_driver as kd
from helao.deploy.hte.drivers.motion.kinesis_driver import KinesisMotor
from helao.hexagon.adapters.native.galil_motion_native import NativeGalilMotion

#: adss MOTOR's B-axis scale, copied from the tracked hte config and kept as a
#: literal so a station recalibration cannot retune the regression witness: at
#: this scale seven counts expressed in mm and converted back floor to six.
ADSS_B_COUNT_TO_MM = 0.00015627999999717445

#: MLJ150/M as shipped: 61 440 000 counts over 50 mm. Counts *per mm* -- the
#: reciprocal orientation of ``count_to_mm`` above.
POS_SCALE = 1228800.0


# --------------------------------------------------------------------------
# app / base doubles
# --------------------------------------------------------------------------


class _FakeRoute:
    def __init__(self, path, tags, fn):
        self.path = path
        self.tags = tags
        self.fn = fn


class _EndpointModel:
    """The one field the busy check reads off an endpoint."""

    def __init__(self, active_dict=None):
        self.active_dict = active_dict or {}


class _FakeApp:
    """Captures what ``*_dyn_endpoints`` registers, instead of a real BaseAPI.

    Private routes are additionally mirrored onto a real ``FastAPI`` so the
    422 assertions exercise genuine request validation rather than a
    hand-rolled imitation of it. Only the private ones: the action routes on
    these servers take parameters shaped for the orchestrator, and dragging
    them into a live app would make an unrelated registration failure look
    like a failure of these endpoints.
    """

    def __init__(self, driver, server_params=None, server_name="MOTOR"):
        self.driver = driver
        self.server_params = server_params or {}
        self.routes = {}
        self.api = FastAPI()
        self.base = types.SimpleNamespace(
            server=types.SimpleNamespace(server_name=server_name),
            server_params=self.server_params,
            # No ``helaodirs``: the galil driver's ``connect()`` reads plate
            # and instrument calibration off disk when one is present, and
            # this feature has nothing to do with calibration.
            helaodirs=None,
            actionservermodel=types.SimpleNamespace(endpoints={}, estop=False),
        )

    def post(self, path, tags=None, **kwargs):
        def _register(fn):
            self.routes[path] = _FakeRoute(path, tags or [], fn)
            if tags and "private" in tags:
                self.api.post(path, tags=tags)(fn)
            return fn

        return _register

    def on_event(self, name):
        def _register(fn):
            return fn

        return _register

    def set_busy(self, *endpoint_names):
        """Make the server report a running action on each named endpoint."""
        self.base.actionservermodel.endpoints = {
            name: _EndpointModel({"uuid": object()}) for name in endpoint_names
        }

    def set_idle(self, *endpoint_names):
        self.base.actionservermodel.endpoints = {
            name: _EndpointModel() for name in endpoint_names
        }


class _Recorder:
    """Stands in for a module LOGGER; keeps the message per level."""

    def __init__(self):
        self.messages = {"info": [], "warning": [], "error": []}

    def info(self, msg, *a, **kw):
        self.messages["info"].append(str(msg))

    def warning(self, msg, *a, **kw):
        self.messages["warning"].append(str(msg))

    def error(self, msg, *a, **kw):
        self.messages["error"].append(str(msg))

    def debug(self, msg, *a, **kw):
        pass


# --------------------------------------------------------------------------
# galil: the real driver behind a fake command channel
# --------------------------------------------------------------------------


class FakeChannel:
    """Records commands; returns programmed responses (default ``'0'``)."""

    def __init__(self, responses: Optional[dict] = None):
        self.commands: list = []
        self.opened: Optional[str] = None
        self.closed = False
        self._responses = responses or {}

    def open(self, connection_string: str) -> None:
        self.opened = connection_string

    def command(self, cmd: str) -> str:
        self.commands.append(cmd)
        r = self._responses.get(cmd, "0")
        if isinstance(r, list):
            return r.pop(0)
        return r

    def info(self) -> str:
        return "fake-info"

    def version(self) -> str:
        return "fake-1.0"

    def close(self) -> None:
        self.closed = True


# x is deliberately mapped to "C" rather than "A": if the axis->letter map
# were applied twice, or not at all, the emitted letter would differ, so the
# letter itself is part of every move assertion.
GALIL_CFG = {
    "axis_id": {"x": "C", "y": "B"},
    "galil_ip_str": "10.0.0.1",
    "count_to_mm": {"C": ADSS_B_COUNT_TO_MM, "B": 6.315e-05},
    "def_speed_count_sec": 10000,
    "max_speed_count_sec": 25000,
}

# The controller answers with every axis it has, so a three-axis controller
# with two configured is what exercises the axis->letter map.
PA_QUERY = "PA ?,?,?"


def _galil_responses(extra=None):
    # SC "1" per axis == stopped, so the settle-poll breaks on its first read.
    base = {
        "MG _MOC": "0",
        "TP": "1000, 2000, 3000",
        PA_QUERY: "1000, 2000, 3000",
        "SC": "1, 1, 1",
    }
    base.update(extra or {})
    return base


def _galil_app(config=None, responses=None, busy_on=()):
    """Register the galil endpoints against a driver with no gclib behind it."""
    from helao.deploy.hte.servers.action import galil_motion

    channel = FakeChannel(responses=responses or _galil_responses())
    driver = NativeGalilMotion(dict(config or GALIL_CFG), channel=channel)
    app = _FakeApp(driver, server_params=dict(config or GALIL_CFG))

    # The sample DB is server state this feature never touches, and building a
    # real one would need a database on disk.
    original = galil_motion.UnifiedSampleDataAPI
    galil_motion.UnifiedSampleDataAPI = lambda base: object()
    try:
        # `_FakeApp` is a test double, not a `BaseAPI` subclass -- it carries
        # only the attributes `galil_dyn_endpoints` actually reaches for.
        asyncio.run(galil_motion.galil_dyn_endpoints(app))  # type: ignore[arg-type]
    finally:
        galil_motion.UnifiedSampleDataAPI = original

    if busy_on:
        app.set_busy(*busy_on)
    else:
        app.set_idle("move", "easymove")
    channel.commands.clear()
    return app, channel


def _emitted(channel, prefix):
    return [c for c in channel.commands if c.startswith(prefix)]


async def _settle_galil_moves():
    """Wait for every panel move the galil endpoint dispatched.

    ``/move_axis`` returns as soon as the move is *dispatched*, so a test that
    asserts what reached the controller has to await the background task the
    endpoint launched -- and inside the same event loop, since ``asyncio.run``
    closes the loop, and cancels anything still pending on it, on return.
    """
    from helao.deploy.hte.servers.action import galil_motion

    while galil_motion.PANEL_MOVE_TASKS:
        await asyncio.gather(
            *list(galil_motion.PANEL_MOVE_TASKS), return_exceptions=True
        )


def _galil_move(app, **kwargs):
    """Call ``/move_axis`` and wait for the move it dispatched to finish."""

    async def _run():
        result = await app.routes["/move_axis"].fn(**kwargs)
        await _settle_galil_moves()
        return result

    return asyncio.run(_run())


def _wait_until(predicate, timeout=10.0):
    """Poll ``predicate`` from a non-async test thread.

    Needed by the ``TestClient`` cases only: those drive the endpoint from
    another thread, so the dispatched move cannot be awaited directly, and the
    response now arrives *before* the move has reached the device.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


# --------------------------------------------------------------------------
# galil: registration
# --------------------------------------------------------------------------


def test_galil_motion_routes_are_private_and_unprefixed():
    app, _ = _galil_app()

    for path in ("/move_axis", "/stop_motion", "/get_axis_positions"):
        assert path in app.routes, sorted(app.routes)
        route = app.routes[path]
        # Private, so no action is created and no run-record row is written...
        assert route.tags == ["private"], route.tags
        # ...and unprefixed, because /{server_key}/ is the action namespace:
        # a prefixed path would be intercepted by the queueing middleware and
        # every panel click would wait on the orchestrator.
        assert not route.path.startswith("/MOTOR/"), route.path

    # The action twins are still there and still actions.
    assert app.routes["/MOTOR/move"].tags == ["action"]
    print("test_galil_motion_routes_are_private_and_unprefixed PASS")


def test_galil_halt_route_is_not_named_for_an_estop():
    """``/stop_private`` is a reserved estop role, and this route is not one.

    An estop must de-energize; this halts and deliberately leaves the motors
    holding. A halt-only route wearing the estop name would be adopted into a
    cascade that then under-stops.
    """
    app, _ = _galil_app()
    assert "/stop_private" not in app.routes
    assert "/estop" not in app.routes
    assert "/stop_motion" in app.routes
    print("test_galil_halt_route_is_not_named_for_an_estop PASS")


# --------------------------------------------------------------------------
# galil: the commanded value
# --------------------------------------------------------------------------


def test_galil_counts_move_reaches_the_controller_undivided():
    app, ch = _galil_app()
    error_code, payload = _galil_move(app, axis="x", value=7, units=Units.counts)

    assert "PRC=7" in ch.commands, ch.commands
    assert error_code == ErrorCodes.none
    assert payload["counts"] == 7
    assert payload == {"axis": "x", "requested": 7, "units": "counts", "counts": 7}
    print("test_galil_counts_move_reaches_the_controller_undivided PASS")


def test_galil_mm_move_of_the_same_distance_loses_a_count():
    """The witness for why counts is a separate domain, not a convenience.

    Seven counts expressed in millimetres and converted back by the mm path
    floors to six. That single lost count is the whole reason the panel can
    ask for counts at all, and it is asserted through the endpoint so a future
    "helpful" conversion added at this layer would fail here.
    """
    app, ch = _galil_app()
    _galil_move(app, axis="x", value=7 * ADSS_B_COUNT_TO_MM, units=Units.mm)
    assert "PRC=6" in ch.commands, ch.commands
    assert "PRC=7" not in ch.commands
    print("test_galil_mm_move_of_the_same_distance_loses_a_count PASS")


def test_galil_absolute_counts_move_emits_pa_not_pr():
    app, ch = _galil_app()
    from helao.deploy.hte.drivers.motion.galil_motion_driver import MoveModes

    _galil_move(app, axis="y", value=4321, mode=MoveModes.absolute, units=Units.counts)
    assert "PAB=4321" in ch.commands, ch.commands
    assert not _emitted(ch, "PRB"), ch.commands
    print("test_galil_absolute_counts_move_emits_pa_not_pr PASS")


def test_galil_move_never_de_energizes_a_motor():
    app, ch = _galil_app()
    _galil_move(app, axis="x", value=25, units=Units.counts)
    assert not _emitted(ch, "MO"), ch.commands
    print("test_galil_move_never_de_energizes_a_motor PASS")


def test_galil_move_uses_the_motor_frame_only():
    """A counts move is only defined in the raw motor frame.

    The plate and instrument transforms are millimetre arithmetic; a count fed
    through one comes out as a plausible-looking and entirely wrong target,
    which the driver refuses. The endpoint must therefore never hand it
    anything but ``motorxy``.

    The proof is the emitted command, not the return code: since the endpoint
    dispatches rather than completes, it returns ``none`` before the driver
    has had a chance to refuse anything. The refusal would land in the log, so
    that is asserted empty too.
    """
    from helao.deploy.hte.servers.action import galil_motion

    app, ch = _galil_app()
    recorder = _Recorder()
    original = galil_motion.LOGGER
    galil_motion.LOGGER = recorder
    try:
        _galil_move(app, axis="x", value=11, units=Units.counts)
    finally:
        galil_motion.LOGGER = original

    assert "PRC=11" in ch.commands, ch.commands
    assert recorder.messages["error"] == [], recorder.messages
    print("test_galil_move_uses_the_motor_frame_only PASS")


# --------------------------------------------------------------------------
# galil: panel vs orchestrator
# --------------------------------------------------------------------------


def test_galil_move_is_refused_while_an_action_is_running():
    """The busy refusal survives the move becoming a background dispatch.

    It has to happen *before* the task is launched, or the refusal turns into
    a move that is accepted, dispatched, and only then declined by the
    driver's own guard -- reported nowhere the panel can see.
    """
    from helao.deploy.hte.servers.action import galil_motion

    app, ch = _galil_app(busy_on=("move",))
    error_code, payload = asyncio.run(
        app.routes["/move_axis"].fn(axis="x", value=7, units=Units.counts)
    )

    # Refused, not failed: the panel renders those differently, and a generic
    # failure on a panel whose purpose is reporting the instrument's state
    # leads an engineer to conclude the panel is broken.
    assert error_code == ErrorCodes.in_progress
    assert payload == {}
    # And no device call at all -- not a call that the driver then declined.
    assert ch.commands == [], ch.commands
    # Nor a task: the refusal is decided before anything is dispatched.
    assert galil_motion.PANEL_MOVE_TASKS == set()
    print("test_galil_move_is_refused_while_an_action_is_running PASS")


def test_galil_move_is_allowed_when_every_endpoint_is_idle():
    """The refusal must key on a *running* action, not on a known endpoint.

    An endpoint that has run before still has an entry in the model, with an
    empty ``active_dict``. Keying on the entry rather than on its contents
    would disable the panel permanently after the first sequence.
    """
    app, ch = _galil_app()
    app.set_idle("move", "easymove", "query_positions")
    error_code, _ = _galil_move(app, axis="x", value=3, units=Units.counts)
    assert error_code == ErrorCodes.none
    assert "PRC=3" in ch.commands, ch.commands
    print("test_galil_move_is_allowed_when_every_endpoint_is_idle PASS")


def test_galil_stop_halts_even_while_an_action_is_running():
    app, ch = _galil_app(busy_on=("move",))
    error_code, payload = asyncio.run(app.routes["/stop_motion"].fn())

    assert error_code == ErrorCodes.none
    assert set(payload["stopped"]) == {"x", "y"}
    # Halted...
    assert "STC" in ch.commands and "STB" in ch.commands, ch.commands
    # ...and still energized. A de-energized vertical axis drops under
    # gravity, so a stop that cut the holding current would be more dangerous
    # than the motion it interrupted.
    assert not _emitted(ch, "MO"), ch.commands
    print("test_galil_stop_halts_even_while_an_action_is_running PASS")


def test_galil_stop_during_an_action_logs_the_data_integrity_consequence():
    """The accepted consequence must leave a trace, not just a docstring.

    The running action is not notified: it observes that motion ceased and
    completes normally, reporting a position it never reached. The run record
    can therefore describe a move that did not happen, and the only evidence
    it was a panel stop is this log line.
    """
    from helao.deploy.hte.servers.action import galil_motion

    app, _ = _galil_app(busy_on=("move",))
    recorder = _Recorder()
    original = galil_motion.LOGGER
    galil_motion.LOGGER = recorder
    try:
        asyncio.run(app.routes["/stop_motion"].fn())
    finally:
        galil_motion.LOGGER = original

    assert recorder.messages["warning"], recorder.messages
    logged = recorder.messages["warning"][0]
    assert "move" in logged
    assert "stop_motion" in logged
    print("test_galil_stop_during_an_action_logs_the_data_integrity_consequence PASS")


def test_galil_stop_when_idle_logs_no_warning():
    from helao.deploy.hte.servers.action import galil_motion

    app, _ = _galil_app()
    recorder = _Recorder()
    original = galil_motion.LOGGER
    galil_motion.LOGGER = recorder
    try:
        asyncio.run(app.routes["/stop_motion"].fn())
    finally:
        galil_motion.LOGGER = original

    assert recorder.messages["warning"] == []
    print("test_galil_stop_when_idle_logs_no_warning PASS")


# --------------------------------------------------------------------------
# galil: the dual-unit read
# --------------------------------------------------------------------------


def test_galil_get_axis_positions_renders_one_sample_in_both_units():
    app, _ = _galil_app()
    error_code, state = asyncio.run(app.routes["/get_axis_positions"].fn())

    assert error_code == ErrorCodes.none
    assert set(state) == {"x", "y"}
    # TP reports A=1000, B=2000, C=3000; x is C and y is B.
    assert state["x"]["counts"] == 3000
    assert state["y"]["counts"] == 2000
    # mm is derived from that same integer, not sampled again.
    assert state["x"]["mm"] == pytest.approx(3000 * ADSS_B_COUNT_TO_MM)
    assert state["y"]["mm"] == pytest.approx(2000 * 6.315e-05)
    # SC "1" is stopped.
    assert state["x"]["moving"] is False
    print("test_galil_get_axis_positions_renders_one_sample_in_both_units PASS")


def test_galil_get_axis_positions_reports_unknown_rather_than_zero():
    """A disabled controller must not report every axis sitting at the origin.

    Zero is a legitimate motor coordinate, so an unread axis rendered as zero
    is indistinguishable from one at its home position -- on a panel whose
    only job is telling an engineer where the instrument is.
    """
    app, _ = _galil_app()
    app.driver.galil_enabled = False
    _, state = asyncio.run(app.routes["/get_axis_positions"].fn())

    for axis, values in state.items():
        assert values["mm"] is None, axis
        assert values["counts"] is None, axis
        assert values["moving"] is None, axis
    print("test_galil_get_axis_positions_reports_unknown_rather_than_zero PASS")


# --------------------------------------------------------------------------
# galil: the discriminators (422, never a silent fall-through)
# --------------------------------------------------------------------------


@pytest.fixture
def galil_client():
    app, channel = _galil_app()
    with TestClient(app.api) as client:
        yield client, channel


def test_galil_misspelled_units_is_rejected_not_defaulted(galil_client):
    """The most dangerous single defect this feature could ship.

    ``"count"`` is the plausible misspelling of ``"counts"``. Routed through a
    free-text parameter it falls through to the millimetre branch, and a
    10 000-*count* move executes as 10 000 *millimetres*.
    """
    client, channel = galil_client
    resp = client.post(
        "/move_axis", params={"axis": "x", "value": 10000, "units": "count"}
    )

    assert resp.status_code == 422, resp.text
    assert channel.commands == [], "a rejected request must reach no device"
    print("test_galil_misspelled_units_is_rejected_not_defaulted PASS")


def test_galil_misspelled_mode_is_rejected_not_defaulted(galil_client):
    client, channel = galil_client
    resp = client.post(
        "/move_axis", params={"axis": "x", "value": 1, "mode": "abolute"}
    )

    assert resp.status_code == 422, resp.text
    assert channel.commands == []
    print("test_galil_misspelled_mode_is_rejected_not_defaulted PASS")


def test_galil_move_requires_an_axis_and_a_value(galil_client):
    """Neither may be defaulted: an empty axis moves something nobody named.

    A ``value`` defaulted to zero is the milder half of the same mistake -- it
    turns a malformed request into a silent no-op the panel reports as a
    successful move.
    """
    client, channel = galil_client

    assert client.post("/move_axis", params={"value": 1}).status_code == 422
    assert client.post("/move_axis", params={"axis": "x"}).status_code == 422
    assert client.post("/move_axis").status_code == 422
    assert channel.commands == []
    print("test_galil_move_requires_an_axis_and_a_value PASS")


def test_galil_move_rejects_an_unconfigured_axis(galil_client):
    client, channel = galil_client
    resp = client.post("/move_axis", params={"axis": "z", "value": 1})

    assert resp.status_code == 422, resp.text
    assert channel.commands == []
    print("test_galil_move_rejects_an_unconfigured_axis PASS")


def test_galil_move_accepts_both_spelled_units(galil_client):
    from helao.deploy.hte.servers.action import galil_motion

    client, channel = galil_client
    for units in ("mm", "counts"):
        resp = client.post(
            "/move_axis", params={"axis": "x", "value": 1, "units": units}
        )
        assert resp.status_code == 200, (units, resp.text)
    # Polled, not asserted outright: the response now arrives before the
    # dispatched move has reached the device, and this test drives the app
    # from another thread, so there is no task here to await.
    assert _wait_until(lambda: _emitted(channel, "PRC")), channel.commands
    # Drained before the client tears the loop down, so a pending move is not
    # cancelled out from under the done-callback.
    _wait_until(lambda: not galil_motion.PANEL_MOVE_TASKS)
    print("test_galil_move_accepts_both_spelled_units PASS")


# --------------------------------------------------------------------------
# galil: dispatch, not completion
# --------------------------------------------------------------------------


def test_galil_panel_move_returns_before_the_stage_arrives():
    """The defect this endpoint's asynchrony exists to fix.

    ``_motor_move`` settle-polls until motion stops, to a 30-minute cap, and
    the panel dispatches with a 5 s timeout -- so while this route blocked,
    every move longer than about five seconds was reported to the operator as
    a failure while the stage was in fact moving to where it was asked.

    Asserted without a clock: the stand-in driver call parks on an event this
    test only sets *after* the endpoint has answered, so the call can complete
    at all only if the endpoint did not wait for it. ``wait_for`` turns the
    regression into a failure instead of a hang.
    """
    app, _ = _galil_app()
    started = asyncio.Event()
    released = asyncio.Event()

    async def _slow_move(**kwargs):
        started.set()
        await released.wait()
        return {"err_code": [ErrorCodes.none], "counts": [7]}

    async def _run():
        app.driver._motor_move = _slow_move
        error_code, payload = await asyncio.wait_for(
            app.routes["/move_axis"].fn(axis="x", value=7, units=Units.counts),
            timeout=10,
        )
        # Answered while the move has not even begun -- the strongest form of
        # "did not wait for it".
        assert not started.is_set()
        assert error_code == ErrorCodes.none
        assert payload == {"axis": "x", "requested": 7, "units": "counts", "counts": 7}

        released.set()
        await _settle_galil_moves()
        # ...and the move did run, rather than being dropped on the floor.
        assert started.is_set()

    asyncio.run(_run())
    print("test_galil_panel_move_returns_before_the_stage_arrives PASS")


def test_galil_panel_move_holds_a_reference_to_its_task():
    """A bare ``create_task`` can be garbage-collected mid-move.

    The loop keeps only a weak reference to a running task, so the dispatcher
    has to hold a strong one until the move finishes -- and drop it after, or
    the set grows for the life of the server.
    """
    from helao.deploy.hte.servers.action import galil_motion

    app, _ = _galil_app()
    released = asyncio.Event()

    async def _slow_move(**kwargs):
        await released.wait()
        return {"err_code": [ErrorCodes.none], "counts": [7]}

    async def _run():
        app.driver._motor_move = _slow_move
        await app.routes["/move_axis"].fn(axis="x", value=7, units=Units.counts)
        assert len(galil_motion.PANEL_MOVE_TASKS) == 1, galil_motion.PANEL_MOVE_TASKS
        released.set()
        await _settle_galil_moves()
        assert galil_motion.PANEL_MOVE_TASKS == set()

    asyncio.run(_run())
    print("test_galil_panel_move_holds_a_reference_to_its_task PASS")


def test_galil_background_move_that_raises_is_logged_not_swallowed():
    """The cost of answering early, and the only thing that pays it back.

    Once the endpoint has returned, a raising move produces nothing but
    "Task exception was never retrieved" at collection time -- which is to say
    nothing an operator or a log reader ever sees. The done-callback is what
    turns it back into a record, and it has to name the axis and the value,
    since the panel is by then reporting a move it believes succeeded.
    """
    from helao.deploy.hte.servers.action import galil_motion

    app, _ = _galil_app()

    async def _exploding_move(**kwargs):
        raise RuntimeError("gclib went away")

    recorder = _Recorder()
    original = galil_motion.LOGGER
    galil_motion.LOGGER = recorder
    try:
        app.driver._motor_move = _exploding_move
        error_code, _ = _galil_move(app, axis="x", value=7, units=Units.counts)
    finally:
        galil_motion.LOGGER = original

    # The panel was told the move was accepted -- which it was.
    assert error_code == ErrorCodes.none
    assert recorder.messages["error"], recorder.messages
    logged = recorder.messages["error"][0]
    assert "gclib went away" in logged
    assert "'x'" in logged, logged
    assert "7" in logged, logged
    print("test_galil_background_move_that_raises_is_logged_not_swallowed PASS")


def test_galil_background_move_that_returns_an_error_code_is_logged():
    """The common failure shape, which an exception-only callback would miss.

    ``_motor_move`` funnels nearly every real fault into an ``ErrorCodes``
    value rather than raising -- the busy guard, a rejected command, a
    timeout. Those used to be the endpoint's return value and now have nowhere
    else to go.
    """
    from helao.deploy.hte.servers.action import galil_motion

    app, _ = _galil_app()

    async def _failing_move(**kwargs):
        return {"err_code": [ErrorCodes.motor], "counts": [None]}

    recorder = _Recorder()
    original = galil_motion.LOGGER
    galil_motion.LOGGER = recorder
    try:
        app.driver._motor_move = _failing_move
        _galil_move(app, axis="x", value=7, units=Units.counts)
    finally:
        galil_motion.LOGGER = original

    assert recorder.messages["error"], recorder.messages
    # Formatted the same way the dispatcher formats it, so the assertion
    # cannot pass or fail on an enum-repr difference.
    assert f"{ErrorCodes.motor}" in recorder.messages["error"][0]
    print("test_galil_background_move_that_returns_an_error_code_is_logged PASS")


# --------------------------------------------------------------------------
# kinesis
# --------------------------------------------------------------------------


class FakeKinesisMotor:
    """Recorder standing in for ``pylablib.devices.Thorlabs.KinesisMotor``."""

    def __init__(self, conn=None, scale=None, position: int = 0, status=()):
        self.conn = conn
        self.scale = scale
        self.position = position
        self._status = list(status)
        self.calls: list = []

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    def get_position(self, *args, **kwargs):
        self._record("get_position", *args, **kwargs)
        return self.position

    def get_status(self, *args, **kwargs):
        self._record("get_status", *args, **kwargs)
        return list(self._status)

    def move_by(self, *args, **kwargs):
        self._record("move_by", *args, **kwargs)

    def move_to(self, *args, **kwargs):
        self._record("move_to", *args, **kwargs)

    def stop(self, *args, **kwargs):
        self._record("stop", *args, **kwargs)

    def close(self, *args, **kwargs):
        self._record("close", *args, **kwargs)

    def method_names(self) -> set:
        return {name for name, _, _ in self.calls}


def _kinesis_cfg(**axis_overrides) -> dict:
    axis = {
        "serial_no": "45470574",
        "pos_scale": POS_SCALE,
        "vel_scale": 65970697.6,
        "acc_scale": 13518.2,
    }
    axis.update(axis_overrides)
    return {"axes": {"z": dict(axis)}}


@pytest.fixture
def make_kinesis_app(monkeypatch):
    """Register the Kinesis endpoints against recorders, not hardware."""
    from helao.deploy.hte.servers.action import kinesis_server

    def _factory(conn=None, scale=None, **kw):
        return FakeKinesisMotor(conn=conn, scale=scale)

    monkeypatch.setattr(kd.Thorlabs, "KinesisMotor", _factory)

    def _make(config=None, busy_on=(), position=0, status=()):
        config = config or _kinesis_cfg()
        driver = KinesisMotor(config=config)
        for motor in driver.motors.values():
            motor.position = position
            motor._status = list(status)
            motor.calls.clear()
        app = _FakeApp(driver, server_params=config, server_name="KMOTOR")
        # `_FakeApp` is a test double, not a `BaseAPI` subclass.
        asyncio.run(kinesis_server.kinesis_dyn_endpoints(app))  # type: ignore[arg-type]
        if busy_on:
            app.set_busy(*busy_on)
        else:
            app.set_idle("kmove")
        return app

    return _make


def test_kinesis_motion_routes_are_private_and_unprefixed(make_kinesis_app):
    app = make_kinesis_app()

    for path in ("/move_axis", "/stop_motion", "/get_axis_positions"):
        assert path in app.routes, sorted(app.routes)
        assert app.routes[path].tags == ["private"]
        assert not app.routes[path].path.startswith("/KMOTOR/")

    assert "/stop_private" not in app.routes
    assert app.routes["/KMOTOR/kmove"].tags == ["action"]
    print("test_kinesis_motion_routes_are_private_and_unprefixed PASS")


def test_kinesis_existing_polling_routes_are_untouched(make_kinesis_app):
    """The two bare-``str`` polling routes are a conflicting precedent.

    They must keep their shape (nothing else may depend on the new tuple
    convention being universal) and the new routes must not copy it: the
    panel's shared layer unwraps ``(error_code, payload)``, and a bare string
    normalises to an empty dict, leaving every readout permanently unknown.
    """
    app = make_kinesis_app()
    for path in ("/start_polling", "/stop_polling"):
        assert app.routes[path].tags == ["private"]
        assert app.routes[path].fn.__annotations__.get("return") is str

    _, payload = asyncio.run(app.routes["/get_axis_positions"].fn())
    assert isinstance(payload, dict)
    print("test_kinesis_existing_polling_routes_are_untouched PASS")


def test_kinesis_counts_move_is_handed_over_unscaled(make_kinesis_app):
    app = make_kinesis_app()
    error_code, payload = asyncio.run(
        app.routes["/move_axis"].fn(axis="z", value=61440, units=Units.counts)
    )

    assert error_code == ErrorCodes.none
    assert app.driver.motors["z"].calls == [("move_by", (61440,), {"scale": False})]
    assert payload == {
        "axis": "z",
        "requested": 61440,
        "units": "counts",
        "counts": 61440,
    }
    print("test_kinesis_counts_move_is_handed_over_unscaled PASS")


def test_kinesis_mm_move_keeps_the_vendor_scaling(make_kinesis_app):
    app = make_kinesis_app()
    _, payload = asyncio.run(
        app.routes["/move_axis"].fn(axis="z", value=1.5, units=Units.mm)
    )

    assert app.driver.motors["z"].calls == [("move_by", (1.5,), {})]
    # No conversion happens at this layer, so there is no count to report --
    # and reporting zero would claim the stage was told not to move.
    assert payload["counts"] is None
    print("test_kinesis_mm_move_keeps_the_vendor_scaling PASS")


def test_kinesis_absolute_move_uses_move_to(make_kinesis_app):
    from helao.deploy.hte.drivers.motion.kinesis_driver import MoveModes

    app = make_kinesis_app()
    asyncio.run(
        app.routes["/move_axis"].fn(
            axis="z", value=61440, mode=MoveModes.absolute, units=Units.counts
        )
    )
    assert app.driver.motors["z"].calls == [("move_to", (61440,), {"scale": False})]
    print("test_kinesis_absolute_move_uses_move_to PASS")


def test_kinesis_move_is_refused_while_an_action_is_running(make_kinesis_app):
    app = make_kinesis_app(busy_on=("kmove",))
    error_code, payload = asyncio.run(
        app.routes["/move_axis"].fn(axis="z", value=61440, units=Units.counts)
    )

    assert error_code == ErrorCodes.in_progress
    assert payload == {}
    assert app.driver.motors["z"].calls == [], "a refusal must reach no device"
    print("test_kinesis_move_is_refused_while_an_action_is_running PASS")


def test_kinesis_stop_halts_every_axis_without_de_energizing(make_kinesis_app):
    app = make_kinesis_app(busy_on=("kmove",))
    error_code, payload = asyncio.run(app.routes["/stop_motion"].fn())

    assert error_code == ErrorCodes.none
    assert payload == {"stopped": ["z"]}
    assert app.driver.motors["z"].calls == [
        ("stop", (), {"immediate": True, "sync": True})
    ]
    # There is no de-energize call on this driver, and the stop must not
    # acquire one by way of a "make it safer" edit.
    assert "close" not in app.driver.motors["z"].method_names()
    print("test_kinesis_stop_halts_every_axis_without_de_energizing PASS")


def test_kinesis_get_axis_positions_reads_each_axis_once_unscaled(make_kinesis_app):
    app = make_kinesis_app(position=61440)
    error_code, state = asyncio.run(app.routes["/get_axis_positions"].fn())

    assert error_code == ErrorCodes.none
    reads = [c for c in app.driver.motors["z"].calls if c[0] == "get_position"]
    # Exactly one sample...
    assert len(reads) == 1, reads
    # ...and it is the raw one. A single scaled read satisfies the count while
    # throwing away the integer the read exists to keep.
    assert reads[0] == ("get_position", (), {"scale": False})
    assert state["z"]["counts"] == 61440
    assert state["z"]["mm"] == pytest.approx(61440 / POS_SCALE)
    print("test_kinesis_get_axis_positions_reads_each_axis_once_unscaled PASS")


def test_kinesis_get_axis_positions_reports_no_scale_as_unknown(make_kinesis_app):
    app = make_kinesis_app(config=_kinesis_cfg(pos_scale=0), position=61440)
    _, state = asyncio.run(app.routes["/get_axis_positions"].fn())

    assert state["z"]["counts"] == 61440
    assert state["z"]["mm"] is None, "a missing scale is unknown, never 0.0 mm"
    print("test_kinesis_get_axis_positions_reports_no_scale_as_unknown PASS")


@pytest.fixture
def kinesis_client(make_kinesis_app):
    app = make_kinesis_app()
    with TestClient(app.api) as client:
        yield client, app


def test_kinesis_misspelled_units_is_rejected_not_defaulted(kinesis_client):
    client, app = kinesis_client
    resp = client.post(
        "/move_axis", params={"axis": "z", "value": 10000, "units": "count"}
    )

    assert resp.status_code == 422, resp.text
    assert app.driver.motors["z"].calls == []
    print("test_kinesis_misspelled_units_is_rejected_not_defaulted PASS")


def test_kinesis_misspelled_mode_is_rejected_not_defaulted(kinesis_client):
    client, app = kinesis_client
    resp = client.post(
        "/move_axis", params={"axis": "z", "value": 1, "mode": "abolute"}
    )

    assert resp.status_code == 422, resp.text
    assert app.driver.motors["z"].calls == []
    print("test_kinesis_misspelled_mode_is_rejected_not_defaulted PASS")


def test_kinesis_move_requires_an_axis_and_a_value(kinesis_client):
    client, app = kinesis_client

    assert client.post("/move_axis", params={"value": 1}).status_code == 422
    assert client.post("/move_axis", params={"axis": "z"}).status_code == 422
    assert (
        client.post("/move_axis", params={"axis": "q", "value": 1}).status_code == 422
    )
    assert app.driver.motors["z"].calls == []
    print("test_kinesis_move_requires_an_axis_and_a_value PASS")
