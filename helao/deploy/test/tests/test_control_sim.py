"""The control simulator: the five private routes, and why they write nothing.

This server exists so artifact row 15 -- *a ``/control`` toggle drives hardware
and writes nothing* -- can be asserted on Linux. That claim rests on **how the
routes are registered**, not on what they return: a route under
``tags=["action"]``, or under the ``/{server_key}/`` prefix, would behave
identically from a panel's point of view and would write a record for every
click. So the registration is asserted first and hardest.

No ``BaseAPI`` is stood up here. ``register_control_routes`` takes anything
with a ``post`` decorator, which is what lets the paths and tags be inspected
directly instead of inferred from a running server's openapi.
"""

import asyncio

import pytest

from helao.core.error import ErrorCodes
from helao.ui.shared.motion_control import Units
from helao.deploy.test.servers.action.control_sim import (
    ControlSim,
    MoveModes,
    register_control_routes,
)

IO_PARAMS = {
    "dev_do": {"gamry_aux": 1, "led": 7, "unreadable_line": None},
}
MOTION_PARAMS = {
    "axis_id": {"x": "A", "y": "B"},
    "count_to_mm": {"A": 1.5628e-04, "B": 1.5628e-04},
}


class _FakeServ:
    """The two attributes :class:`ControlSim` reads off its action server.

    Not a ``Base``: standing one up would need a config, a clock, and a bound
    port, none of which the driver touches. The ``type: ignore`` at the
    construction below says exactly that -- the annotation is right for
    production and the stub is right here.
    """

    def __init__(self, params):
        self.server_cfg = {"params": params}
        self.world_cfg = {}


class _FakeApp:
    """Records what ``register_control_routes`` registers."""

    def __init__(self, params):
        self.driver = ControlSim(_FakeServ(params))  # type: ignore[arg-type]
        self.routes = {}
        self.tags = {}

    def post(self, path, tags=None, **kwargs):
        def _register(fn):
            self.routes[path] = fn
            self.tags[path] = tags or []
            return fn

        return _register


def io_app():
    app = _FakeApp(IO_PARAMS)
    register_control_routes(app, "IOSIM")
    return app


def motion_app():
    app = _FakeApp(MOTION_PARAMS)
    register_control_routes(app, "MOTORSIM")
    return app


def call(app, path, **kwargs):
    return asyncio.run(app.routes[path](**kwargs))


# --------------------------------------------------------------------------
# registration -- the substance of row 15
# --------------------------------------------------------------------------


def test_every_control_route_is_private_and_bare_pathed():
    app = _FakeApp({**IO_PARAMS, **MOTION_PARAMS})
    register_control_routes(app, "BOTH")

    assert set(app.routes) == {
        "/get_digital_outs",
        "/set_digital_out",
        "/get_axis_positions",
        "/move_axis",
        "/stop_motion",
    }
    for path, tags in app.tags.items():
        # ``private``, never ``action``: the action namespace is what puts a
        # row in the run record and queues the click behind the orchestrator.
        assert tags == ["private"], (path, tags)
        assert not path.startswith("/IOSIM"), path
        assert path.count("/") == 1, path
    print("test_every_control_route_is_private_and_bare_pathed PASS")


def test_the_io_routes_appear_only_with_dev_do():
    app = _FakeApp({})
    register_control_routes(app, "EMPTY")
    assert app.routes == {}

    # Mirrors galil_io's ``if app.driver.dev_do:`` gate, so a config shape that
    # yields no controls here yields none there either.
    assert set(io_app().routes) == {"/get_digital_outs", "/set_digital_out"}
    print("test_the_io_routes_appear_only_with_dev_do PASS")


def test_the_motion_routes_appear_only_with_axis_id():
    assert set(motion_app().routes) == {
        "/get_axis_positions",
        "/move_axis",
        "/stop_motion",
    }
    print("test_the_motion_routes_appear_only_with_axis_id PASS")


# --------------------------------------------------------------------------
# digital outputs -- the tri-state
# --------------------------------------------------------------------------


def test_every_line_starts_unknown_not_off():
    code, states = call(io_app(), "/get_digital_outs")

    assert code == ErrorCodes.none
    assert states == {"gamry_aux": None, "led": None, "unreadable_line": None}
    # A server that has not written a line since startup does not know its
    # state: it may be energised from a previous run.
    assert states["led"] is not False
    print("test_every_line_starts_unknown_not_off PASS")


def test_a_write_reads_back_and_persists():
    app = io_app()
    code, reported = call(app, "/set_digital_out", do_name="led", on=True)
    assert (code, reported) == (ErrorCodes.none, {"led": True})

    _, states = call(app, "/get_digital_outs")
    assert states["led"] is True
    # The other lines are untouched -- still unknown, not defaulted to off by
    # a write to a neighbour.
    assert states["gamry_aux"] is None
    print("test_a_write_reads_back_and_persists PASS")


def test_an_unreadable_line_accepts_writes_and_still_reads_unknown():
    app = io_app()
    code, reported = call(app, "/set_digital_out", do_name="unreadable_line", on=True)

    assert code == ErrorCodes.none
    assert reported == {"unreadable_line": None}
    _, states = call(app, "/get_digital_outs")
    assert states["unreadable_line"] is None
    # This is the NI server's real behaviour (one-shot tasks, no readback) and
    # the reason unknown is a value rather than a placeholder for off.
    assert states["unreadable_line"] is not False
    print("test_an_unreadable_line_accepts_writes_and_still_reads_unknown PASS")


def test_an_unknown_line_is_refused_with_an_empty_payload():
    code, reported = call(io_app(), "/set_digital_out", do_name="nonesuch", on=True)

    assert code == ErrorCodes.not_available
    # Empty, not ``{"nonesuch": ...}``: a phantom control is worse than a
    # missing one, and the client wrappers discard the body on a non-none code
    # precisely so an error payload cannot become one.
    assert reported == {}
    print("test_an_unknown_line_is_refused_with_an_empty_payload PASS")


# --------------------------------------------------------------------------
# motion
# --------------------------------------------------------------------------


def test_positions_report_both_units_from_one_sample():
    code, positions = call(motion_app(), "/get_axis_positions")

    assert code == ErrorCodes.none
    assert set(positions) == {"x", "y"}
    assert positions["x"] == {"mm": 0.0, "counts": 0, "moving": False}
    print("test_positions_report_both_units_from_one_sample PASS")


def test_a_counts_move_reaches_the_encoder_undivided():
    app = motion_app()
    code, payload = call(
        app,
        "/move_axis",
        axis="x",
        value=1000.0,
        units=Units.counts,
        mode=MoveModes.relative,
    )

    assert code == ErrorCodes.none
    # Dispatched exactly as typed: 1000 counts is 1000 counts, and the
    # endpoint reports the integer it knows will be commanded.
    assert payload["counts"] == 1000
    assert payload["units"] == "counts"
    _, positions = call(app, "/get_axis_positions")
    assert positions["x"]["counts"] == 1000
    print("test_a_counts_move_reaches_the_encoder_undivided PASS")


def test_an_mm_move_reports_no_counts():
    app = motion_app()
    _, payload = call(
        app,
        "/move_axis",
        axis="x",
        value=1.0,
        units=Units.mm,
        mode=MoveModes.relative,
    )

    # ``None`` rather than a plausible-looking figure: the conversion belongs
    # to the driver and has not run at the point this returns.
    assert payload["counts"] is None
    _, positions = call(app, "/get_axis_positions")
    assert positions["x"]["counts"] == int(1.0 / 1.5628e-04)
    print("test_an_mm_move_reports_no_counts PASS")


def test_absolute_and_relative_differ():
    app = motion_app()
    call(
        app,
        "/move_axis",
        axis="x",
        value=500.0,
        units=Units.counts,
        mode=MoveModes.relative,
    )
    call(
        app,
        "/move_axis",
        axis="x",
        value=500.0,
        units=Units.counts,
        mode=MoveModes.relative,
    )
    _, positions = call(app, "/get_axis_positions")
    assert positions["x"]["counts"] == 1000

    call(
        app,
        "/move_axis",
        axis="x",
        value=500.0,
        units=Units.counts,
        mode=MoveModes.absolute,
    )
    _, positions = call(app, "/get_axis_positions")
    assert positions["x"]["counts"] == 500
    print("test_absolute_and_relative_differ PASS")


def test_an_unknown_axis_is_refused():
    code, payload = call(
        motion_app(),
        "/move_axis",
        axis="z",
        value=1.0,
        units=Units.counts,
        mode=MoveModes.relative,
    )
    assert code == ErrorCodes.not_available
    assert payload == {}
    print("test_an_unknown_axis_is_refused PASS")


def test_an_axis_with_no_scale_reports_no_millimetres():
    app = _FakeApp({"axis_id": {"w": "C"}, "count_to_mm": {}})
    register_control_routes(app, "NOSCALE")
    _, positions = call(app, "/get_axis_positions")

    # ``None``, not zero: an unscaled axis has counts and no millimetres, and
    # zero millimetres is a real coordinate.
    assert positions["w"]["mm"] is None
    assert positions["w"]["counts"] == 0
    print("test_an_axis_with_no_scale_reports_no_millimetres PASS")


def test_an_mm_move_on_an_unscaled_axis_is_refused_not_guessed():
    app = _FakeApp({"axis_id": {"w": "C"}, "count_to_mm": {}})
    register_control_routes(app, "NOSCALE")
    code, payload = call(
        app,
        "/move_axis",
        axis="w",
        value=1.0,
        units=Units.mm,
        mode=MoveModes.relative,
    )

    # Refusing beats inventing a scale: a wrong scale is silent and wrong by
    # a factor, where a refusal names itself.
    assert code == ErrorCodes.not_available
    assert payload == {}
    print("test_an_mm_move_on_an_unscaled_axis_is_refused_not_guessed PASS")


def test_stop_motion_lists_every_axis_it_halted():
    app = motion_app()
    call(
        app,
        "/move_axis",
        axis="x",
        value=1000.0,
        units=Units.counts,
        mode=MoveModes.relative,
    )
    _, positions = call(app, "/get_axis_positions")
    assert positions["x"]["moving"] is True

    code, payload = call(app, "/stop_motion")
    assert code == ErrorCodes.none
    assert payload == {"stopped": ["x", "y"]}
    _, positions = call(app, "/get_axis_positions")
    assert positions["x"]["moving"] is False
    # A stop halts motion; it does not rewind the stage.
    assert positions["x"]["counts"] == 1000
    print("test_stop_motion_lists_every_axis_it_halted PASS")


def test_the_move_mode_vocabulary_matches_the_station_enum():
    # A simulator answering a different vocabulary than the thing it stands in
    # for would prove nothing about the panel that drives both.
    assert [m.value for m in MoveModes] == ["homing", "relative", "absolute"]
    print("test_the_move_mode_vocabulary_matches_the_station_enum PASS")


# --------------------------------------------------------------------------
# the sim answers the shared client layer
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "params, source, expected",
    [
        (IO_PARAMS, ("dev_do",), ["gamry_aux", "led", "unreadable_line"]),
        (MOTION_PARAMS, "letter_scale", ["x", "y"]),
    ],
)
def test_the_config_shape_is_the_one_the_panels_discover(params, source, expected):
    """The sim's config must take the same discovery branch a station does.

    A simulator whose config the shared discovery functions cannot read would
    let the negative gate pass over routes no panel could ever reach.
    """
    from helao.ui.shared.io_control import discover_do_items
    from helao.ui.shared.motion_control import discover_axes

    cfg = {"host": "127.0.0.1", "port": 8002, "params": params}
    if isinstance(source, tuple):
        found = [i.name for i in discover_do_items(cfg, source)]
    else:
        found = [a.axis for a in discover_axes(cfg, source, server_key="MOTORSIM")]
    assert found == expected
    print("test_the_config_shape_is_the_one_the_panels_discover PASS")


def test_the_shipped_scale_orientation_is_read_correctly():
    from helao.ui.shared.motion_control import discover_axes

    cfg = {"host": "127.0.0.1", "port": 8003, "params": MOTION_PARAMS}
    axes = {a.axis: a for a in discover_axes(cfg, "letter_scale", server_key="M")}

    # count_to_mm is millimetres per count; pos_scale (the other schema) is its
    # reciprocal. Getting this backwards is wrong by the square of the scale
    # and looks entirely ordinary.
    assert axes["x"].mm_per_count == pytest.approx(1.5628e-04)
    print("test_the_shipped_scale_orientation_is_read_correctly PASS")
