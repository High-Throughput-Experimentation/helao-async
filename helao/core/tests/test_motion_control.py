"""The shared logic under both motion-axis control panels.

Backend-agnostic, so these tests need neither Bokeh nor Reflex. What they pin
is the part that would fail silently: the scale, whose two config orientations
are reciprocals of each other and both perfectly ordinary-looking floats, and
the tri-state readout, where the failure mode is worse than the digital
outputs' because ``0.0`` is a legitimate motor coordinate.

**Fixture rule.** Live-config sweeps over hte configs live in
helao/deploy/hte/tests/test_motion_control_hte.py.
"""

import asyncio
import math
import os
import re

from typing import Optional

import pytest

from helao.core.error import ErrorCodes
from helao.ui.shared import motion_control
from helao.ui.shared.motion_control import (
    ARM_TIMEOUT_S,
    AXIS_SOURCES,
    DEFAULT_WARN_ABOVE_MM,
    FAILED_STATUS,
    REFUSED_STATUS,
    UNKNOWN,
    AxisItem,
    MmPerCount,
    Units,
    discover_axes,
    exceeds_warn_threshold,
    mm_per_count,
    move_axis,
    outcome_status,
    position_label,
    read_axis_positions,
    stop_motion,
    warn_threshold_mm,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
#: The name-keyed schema ships in no tracked config, so its fixture is written
#: out here rather than globbed from a deployment this repository does not
#: contain. Representative values only: what the code branches on is the shape
#: -- axis_id mapping to a serial number, count_to_mm keyed by the axis *name*
#: rather than by a controller letter.
NAME_SCALE_CFG = {
    "host": "127.0.0.1",
    "port": 8003,
    "params": {
        "axis_id": {"x": "45470574", "y": "45470575"},
        "count_to_mm": {
            # 2.44140625e-06 -- a 150 mm linear stage, name-keyed schema.
            "x": 2.44140625e-06,
            "y": 2.44140625e-06,
        },
    },
}

#: Deliberately synthetic: no shipped config is sparse (every axis a station
#: declares has a scale entry), so a real-config fixture would pass this test
#: without ever entering the branch it exists to cover.
SYNTHETIC_SPARSE_CFG = {
    "params": {
        "axis_id": {"x": "C", "y": "B"},
        "count_to_mm": {"C": 0.00015634},  # no entry for B
    },
}


# --------------------------------------------------------------------------
# T-U1 -- discovery
# --------------------------------------------------------------------------


def test_discovery_reads_the_name_keyed_schema():
    items = discover_axes(NAME_SCALE_CFG, "name_scale", server_key="MOTION")

    assert [i.axis for i in items] == ["x", "y"]
    # Keyed by the axis name, not by the serial number axis_id maps it to.
    assert items[0].mm_per_count == pytest.approx(2.44140625e-06, rel=1e-12)
    print("test_discovery_reads_the_name_keyed_schema PASS")


def test_discovery_refuses_an_unknown_source_rather_than_guessing(caplog):
    # Two of the three schemas key their scale by axis name, so a config shape
    # cannot be told apart from another by inspection -- guessing would be
    # wrong by the square of the scale.
    with caplog.at_level("ERROR"):
        items = discover_axes(NAME_SCALE_CFG, "letter_map", server_key="MOTION")

    assert items == []
    assert "letter_map" in caplog.text
    print("test_discovery_refuses_an_unknown_source_rather_than_guessing PASS")


def test_discovery_is_empty_when_nothing_is_configured():
    # A panel renders this as an explicit "none configured", not a blank box.
    assert discover_axes({"params": {}}, "letter_scale") == []
    assert discover_axes({}, "inverse_scale") == []
    print("test_discovery_is_empty_when_nothing_is_configured PASS")


def test_discovery_keeps_the_same_positional_shape_as_the_digital_out_twin():
    """Both discovery functions are ``(server_config, selector)``.

    Asserted so the two cannot drift apart: a later port wrapping both control
    kinds should find one contract, not two.
    """
    import inspect

    from helao.ui.shared.io_control import discover_do_items

    do_positional = [
        p.name
        for p in inspect.signature(discover_do_items).parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    axis_positional = [
        p.name
        for p in inspect.signature(discover_axes).parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    assert do_positional == ["server_config", "groups"]
    assert axis_positional == ["server_config", "axis_source"]
    print("test_discovery_keeps_the_same_positional_shape_as_the_digital_out_twin PASS")


# --------------------------------------------------------------------------
# T-U2 -- counts are not millimetres, and no shipped scale round-trips
# --------------------------------------------------------------------------


def test_the_counts_round_trip_loses_a_count_at_seven():
    """The fixed regression witness for why a counts move must not be divided.

    A literal rather than a config read, so it stays a stable statement of the
    hazard even after a station recalibrates the axis it came from.
    """
    c = 0.00015627999999717445
    assert math.floor(7 * c / c) == 6
    print("test_the_counts_round_trip_loses_a_count_at_seven PASS")


# --------------------------------------------------------------------------
# T-U3 -- the scale accessor, and the inversion it must not drop or add
# --------------------------------------------------------------------------


def test_a_zero_or_missing_reciprocal_yields_none_not_a_division_error():
    # A zero pos_scale is a config that does not state a scale, not one that
    # states an infinite one.
    assert (
        mm_per_count(
            {"params": {"axes": {"z": {"pos_scale": 0}}}}, "z", "inverse_scale"
        )
        is None
    )
    assert mm_per_count({"params": {"axes": {"z": {}}}}, "z", "inverse_scale") is None
    assert mm_per_count({"params": {}}, "z", "inverse_scale") is None
    print("test_a_zero_or_missing_reciprocal_yields_none_not_a_division_error PASS")


def test_an_unknown_source_yields_no_scale_and_logs(caplog):
    with caplog.at_level("ERROR"):
        assert mm_per_count(NAME_SCALE_CFG, "x", "scaled_axes") is None
    assert "scaled_axes" in caplog.text
    print("test_an_unknown_source_yields_no_scale_and_logs PASS")


# --------------------------------------------------------------------------
# T-U4 -- the scale keys are read in exactly one function
# --------------------------------------------------------------------------


def test_only_the_accessor_subscripts_the_scale_keys():
    """No second scale site in this layer.

    Scoped to this layer on purpose: the drivers legitimately subscript these
    keys today and always will, so a repository-wide sweep could not pass. What
    must hold is that *here* -- where a mistake reaches a confirmation dialog
    and makes it stop appearing -- there is one accessor and no other reader.
    """
    path = os.path.join(REPO_ROOT, "helao", "ui", "shared", "motion_control.py")
    with open(path, encoding="utf-8") as handle:
        source = handle.read()

    # Split on the accessor's own definition; everything after it up to the
    # next top-level def is allowed to name the keys.
    lines = source.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("def mm_per_count")]
    assert len(starts) == 1, "mm_per_count must be defined exactly once"
    start = starts[0]
    end = next(
        i
        for i in range(start + 1, len(lines))
        if lines[i].startswith(("def ", "async def ", "class "))
    )

    offenders = [
        (i + 1, line)
        for i, line in enumerate(lines)
        if not start <= i < end
        and re.search(r"""\bget\(\s*['"](count_to_mm|pos_scale)['"]""", line)
    ]
    assert offenders == [], f"scale key read outside mm_per_count: {offenders}"
    print("test_only_the_accessor_subscripts_the_scale_keys PASS")


# --------------------------------------------------------------------------
# T-U5 -- the axis with no configured scale
# --------------------------------------------------------------------------


def test_a_synthetic_sparse_config_disables_the_move_control_rather_than_raising():
    """Explicitly synthetic -- no shipped config is sparse.

    Every axis a station declares has a scale entry today, so a real-config
    fixture would pass this test without ever entering the branch. This is a
    robustness path, and it must degrade rather than raise: a KeyError inside a
    panel build takes the whole document down.
    """
    items = discover_axes(SYNTHETIC_SPARSE_CFG, "letter_scale", server_key="MOTOR")

    by_axis = {i.axis: i for i in items}
    assert set(by_axis) == {"x", "y"}
    assert by_axis["x"].mm_per_count is not None
    assert by_axis["y"].mm_per_count is None
    # Counts still render -- the axis is readable, it just has no millimetre
    # relation -- but the move control is off, so no dialog can become noise.
    assert by_axis["y"].has_counts is True
    assert by_axis["y"].move_enabled is False
    assert by_axis["x"].move_enabled is True
    print(
        "test_a_synthetic_sparse_config_disables_the_move_control_rather_than_raising"
        " PASS"
    )


# --------------------------------------------------------------------------
# T-U7 -- the accessor is one consistent scalar
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# T-U8..T-U11 -- the warn threshold
# --------------------------------------------------------------------------


def _item(
    mm_per_count_value: Optional[float] = 1e-4, warn: float = 10.0, axis: str = "x"
) -> AxisItem:
    """Build an axis fixture directly.

    The scale is laundered through ``MmPerCount`` explicitly, which is the
    escape hatch the ``NewType`` is supposed to have: a test may state a scale
    out loud, while production code cannot compute one anywhere but the
    accessor without pyright saying so.
    """
    return AxisItem(
        server_key="MOTOR",
        axis=axis,
        family="letter_scale",
        mm_per_count=(
            None if mm_per_count_value is None else MmPerCount(mm_per_count_value)
        ),
        warn_above_mm=warn,
        has_counts=True,
    )


def test_relative_mode_compares_the_entered_displacement():
    item = _item(warn=10.0)

    assert exceeds_warn_threshold(item, 11.0, Units.mm, mode="relative") is True
    assert exceeds_warn_threshold(item, 9.0, Units.mm, mode="relative") is False
    # Direction is irrelevant to size.
    assert exceeds_warn_threshold(item, -11.0, Units.mm, mode="relative") is True
    print("test_relative_mode_compares_the_entered_displacement PASS")


def test_absolute_mode_compares_the_displacement_not_the_coordinate():
    item = _item(warn=10.0)

    # Absolute 25.0 from 24.9 is a 0.1 mm move. Comparing the coordinate would
    # confirm nearly every absolute move and train the operator to click
    # through the dialog.
    assert (
        exceeds_warn_threshold(item, 25.0, Units.mm, current_mm=24.9, mode="absolute")
        is False
    )
    assert (
        exceeds_warn_threshold(item, 25.0, Units.mm, current_mm=1.0, mode="absolute")
        is True
    )
    print("test_absolute_mode_compares_the_displacement_not_the_coordinate PASS")


def test_a_counts_entry_is_converted_before_it_is_compared():
    item = _item(mm_per_count_value=1e-4, warn=10.0)

    # 200 000 counts is 20 mm: over. 50 000 counts is 5 mm: under. Comparing
    # the raw counts against a millimetre threshold would warn on both.
    assert exceeds_warn_threshold(item, 200000, Units.counts, mode="relative") is True
    assert exceeds_warn_threshold(item, 50000, Units.counts, mode="relative") is False
    print("test_a_counts_entry_is_converted_before_it_is_compared PASS")


def test_an_unread_coordinate_in_absolute_mode_fails_closed():
    # Transient, and it clears on the next read -- so a dialog is proportionate
    # and cannot become permanent noise. The fail-open alternative is a large
    # move with no confirmation at all.
    item = _item(warn=10.0)
    assert (
        exceeds_warn_threshold(item, 0.1, Units.mm, current_mm=UNKNOWN, mode="absolute")
        is True
    )
    # ... and the same entry evaluates normally once a coordinate is known.
    assert (
        exceeds_warn_threshold(item, 0.1, Units.mm, current_mm=0.0, mode="absolute")
        is False
    )
    print("test_an_unread_coordinate_in_absolute_mode_fails_closed PASS")


def test_a_non_finite_entry_fails_closed():
    item = _item(warn=10.0)
    for value in (float("nan"), float("inf")):
        assert exceeds_warn_threshold(item, value, Units.mm, mode="relative") is True
    # A widget can hand back a string the user was mid-way through typing;
    # that is unevaluable, not zero.
    assert (
        exceeds_warn_threshold(item, "not a number", Units.mm, mode="relative")  # type: ignore[arg-type]
        is True
    )
    print("test_a_non_finite_entry_fails_closed PASS")


def test_a_scale_less_axis_is_never_evaluated_because_its_control_is_disabled(caplog):
    """The permanent unevaluable case is resolved at discovery, not at click.

    What this pins is the *structural* resolution: the axis with no scale has
    no enabled move control, so no dialog exists for it to raise on every move
    forever. Reaching the threshold check anyway means a caller bypassed the
    disable, which is a bug -- so it is reported at ERROR, and the click is
    still required rather than a large move going out unguarded.
    """
    items = discover_axes(SYNTHETIC_SPARSE_CFG, "letter_scale", server_key="MOTOR")
    scale_less = next(i for i in items if i.axis == "y")
    assert scale_less.move_enabled is False

    with caplog.at_level("ERROR"):
        exceeds_warn_threshold(scale_less, 5.0, Units.counts, mode="relative")
    assert "no configured scale" in caplog.text
    print(
        "test_a_scale_less_axis_is_never_evaluated_because_its_control_is_disabled PASS"
    )


def test_a_millimetre_entry_needs_no_scale_at_all():
    # The scale is only needed to express a counts entry in millimetres, so a
    # millimetre entry on a scale-less axis is perfectly evaluable.
    item = _item(mm_per_count_value=None, warn=10.0)
    assert exceeds_warn_threshold(item, 11.0, Units.mm, mode="relative") is True
    assert exceeds_warn_threshold(item, 1.0, Units.mm, mode="relative") is False
    print("test_a_millimetre_entry_needs_no_scale_at_all PASS")


def test_a_nonsense_threshold_in_the_config_falls_through_to_the_default():
    # Zero would confirm every move; infinity would confirm none. Both are
    # ignored rather than obeyed.
    for bad in (0, -1, float("inf"), "soon"):
        cfg = {"params": {"warn_above_mm": {"z": bad}}}
        assert warn_threshold_mm(cfg, "z", "inverse_scale") == DEFAULT_WARN_ABOVE_MM
    print("test_a_nonsense_threshold_in_the_config_falls_through_to_the_default PASS")


# --------------------------------------------------------------------------
# T-U12 -- the threshold confirms, it never rejects
# --------------------------------------------------------------------------


def test_an_over_threshold_move_still_reaches_the_dispatcher(dispatched):
    calls, reply = dispatched
    reply["value"] = ((ErrorCodes.none, {"axis": "x"}), ErrorCodes.none)
    item = _item(warn=10.0)

    # Ten times over the threshold, and the threshold's only consequence is the
    # confirmation. A confirmed move executes; nothing here may reject it.
    assert exceeds_warn_threshold(item, 100.0, Units.mm, mode="relative") is True
    error_code, _ = asyncio.run(
        move_axis("MOTOR", "127.0.0.1", 8003, axis="x", value=100.0, mode="relative")
    )

    assert error_code == ErrorCodes.none
    assert calls[0]["params_dict"]["value"] == 100.0
    print("test_an_over_threshold_move_still_reaches_the_dispatcher PASS")


# --------------------------------------------------------------------------
# T-U13..T-U14 -- the dual-unit readout
# --------------------------------------------------------------------------


def test_the_readout_renders_both_units():
    assert position_label(12.345, 78321) == "12.345 mm / 78321 counts"
    print("test_the_readout_renders_both_units PASS")


def test_unknown_never_renders_as_the_origin():
    assert position_label(UNKNOWN, UNKNOWN) == "? mm / ? counts"
    # The load-bearing one. Zero is a legitimate motor coordinate, so a failed
    # read shown as zero is indistinguishable from an axis at its origin.
    assert position_label(0.0, 0) == "0.000 mm / 0 counts"
    assert position_label(UNKNOWN, UNKNOWN) != position_label(0.0, 0)
    print("test_unknown_never_renders_as_the_origin PASS")


def test_the_two_halves_are_unknown_independently():
    # A configured axis with no scale reports counts and no millimetres.
    assert position_label(UNKNOWN, 78321) == "? mm / 78321 counts"
    assert position_label(12.345, UNKNOWN) == "12.345 mm / ? counts"
    print("test_the_two_halves_are_unknown_independently PASS")


def test_a_non_finite_coordinate_renders_unknown():
    assert position_label(float("nan"), 1) == "? mm / 1 counts"
    assert position_label(float("inf"), 1) == "? mm / 1 counts"
    print("test_a_non_finite_coordinate_renders_unknown PASS")


# --------------------------------------------------------------------------
# T-U15..T-U16 -- transport
# --------------------------------------------------------------------------


@pytest.fixture
def dispatched(monkeypatch):
    """Capture private-dispatcher calls and script their replies."""
    calls = []
    reply = {"value": ({}, ErrorCodes.none)}

    async def _fake(**kwargs):
        calls.append(kwargs)
        result = reply["value"]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(motion_control, "async_private_dispatcher", _fake)
    return calls, reply


def test_read_normalises_the_rpc_tuple_shape(dispatched):
    calls, reply = dispatched
    reply["value"] = (
        (ErrorCodes.none, {"x": {"mm": 12.5, "counts": 79981, "moving": False}}),
        ErrorCodes.none,
    )

    positions = asyncio.run(read_axis_positions("MOTOR", "127.0.0.1", 8003))

    assert positions == {"x": {"mm": 12.5, "counts": 79981, "moving": False}}
    assert calls[0]["private_action"] == "get_axis_positions"
    print("test_read_normalises_the_rpc_tuple_shape PASS")


def test_motion_calls_use_the_panel_timeout_and_the_read_write_retry_counts(
    dispatched,
):
    calls, _ = dispatched
    asyncio.run(read_axis_positions("MOTOR", "127.0.0.1", 8003))
    asyncio.run(move_axis("MOTOR", "127.0.0.1", 8003, axis="x", value=0.0))
    asyncio.run(stop_motion("MOTOR", "127.0.0.1", 8003))

    # 5 s, not the dispatcher's 60: these run on a UI callback.
    assert [c["timeout"] for c in calls] == [motion_control.CALL_TIMEOUT] * 3
    assert motion_control.CALL_TIMEOUT == 5
    assert [c["retries"] for c in calls] == [
        motion_control.READ_RETRIES,
        motion_control.WRITE_RETRIES,
        motion_control.WRITE_RETRIES,
    ]
    print(
        "test_motion_calls_use_the_panel_timeout_and_the_read_write_retry_counts PASS"
    )


def test_a_non_finite_coordinate_degrades_to_unknown(dispatched):
    _, reply = dispatched
    reply["value"] = ({"x": {"mm": float("nan"), "counts": "?"}}, ErrorCodes.none)

    positions = asyncio.run(read_axis_positions("MOTOR", "127.0.0.1", 8003))

    assert positions["x"] == {"mm": None, "counts": None, "moving": None}
    print("test_a_non_finite_coordinate_degrades_to_unknown PASS")


def test_read_normalises_the_http_list_shape(dispatched):
    # The HTTP fallback JSON-decodes the endpoint's tuple to a two-element
    # list, so both shapes reach this layer and both must unwrap.
    _, reply = dispatched
    reply["value"] = (
        [0, {"z": {"mm": None, "counts": 4096, "moving": None}}],
        ErrorCodes.none,
    )

    positions = asyncio.run(read_axis_positions("KMOTOR", "127.0.0.1", 8015))

    assert positions == {"z": {"mm": None, "counts": 4096, "moving": None}}
    print("test_read_normalises_the_http_list_shape PASS")


def test_read_preserves_unknown_rather_than_coercing_it(dispatched):
    _, reply = dispatched
    reply["value"] = (
        (ErrorCodes.none, {"x": {"mm": None, "counts": None, "moving": None}}),
        ErrorCodes.none,
    )

    positions = asyncio.run(read_axis_positions("MOTOR", "127.0.0.1", 8003))

    assert positions["x"] == {"mm": None, "counts": None, "moving": None}
    # Not zero, and not False: an axis that did not report is not an axis at
    # its origin holding still.
    assert positions["x"]["mm"] is None
    assert positions["x"]["counts"] is None
    assert positions["x"]["moving"] is None
    print("test_read_preserves_unknown_rather_than_coercing_it PASS")


def test_read_discards_an_error_body_rather_than_parsing_it(dispatched, caplog):
    _, reply = dispatched
    reply["value"] = ({"detail": "Not Found"}, ErrorCodes.http)

    with caplog.at_level("ERROR"):
        positions = asyncio.run(read_axis_positions("MOTOR", "127.0.0.1", 8003))

    # A 404 from a server without the endpoint still replies with a JSON dict;
    # parsing it would yield a phantom axis named "detail".
    assert positions == {}
    assert "detail" not in positions
    assert len([r for r in caplog.records if r.levelname == "ERROR"]) == 1
    print("test_read_discards_an_error_body_rather_than_parsing_it PASS")


def test_a_stray_error_body_still_yields_no_phantom_axis(dispatched):
    # Second line of defence: even were the code clean, an axis whose value is
    # a bare string is not an axis and is dropped.
    _, reply = dispatched
    reply["value"] = ((ErrorCodes.none, {"detail": "Not Found"}), ErrorCodes.none)

    assert asyncio.run(read_axis_positions("MOTOR", "127.0.0.1", 8003)) == {}
    print("test_a_stray_error_body_still_yields_no_phantom_axis PASS")


def test_read_returns_empty_when_the_server_is_unreachable(dispatched, caplog):
    _, reply = dispatched
    reply["value"] = RuntimeError("connection refused")

    with caplog.at_level("ERROR"):
        positions = asyncio.run(read_axis_positions("MOTOR", "127.0.0.1", 8003))

    # Empty, not a dict of zeros: every readout stays unknown rather than the
    # panel inventing coordinates for an instrument it could not reach. And one
    # ERROR line, not a retry wall.
    assert positions == {}
    assert len([r for r in caplog.records if r.levelname == "ERROR"]) == 1
    print("test_read_returns_empty_when_the_server_is_unreachable PASS")


def test_a_bare_string_reply_yields_no_readings(dispatched):
    # One motion server's existing polling routes return a bare string. Copying
    # that convention here would give an always-unknown panel rather than a
    # crash, which is the honest degradation but worth pinning.
    _, reply = dispatched
    reply["value"] = ("started", ErrorCodes.none)

    assert asyncio.run(read_axis_positions("KMOTOR", "127.0.0.1", 8015)) == {}
    print("test_a_bare_string_reply_yields_no_readings PASS")


def test_move_sends_the_value_untouched_and_names_its_unit(dispatched):
    calls, reply = dispatched
    reply["value"] = ((ErrorCodes.none, {"axis": "x", "counts": 7}), ErrorCodes.none)

    error_code, payload = asyncio.run(
        move_axis(
            "MOTOR",
            "127.0.0.1",
            8003,
            axis="x",
            value=7,
            mode="relative",
            units=Units.counts,
        )
    )

    assert error_code == ErrorCodes.none
    assert payload == {"axis": "x", "counts": 7}
    assert calls[0]["private_action"] == "move_axis"
    # The commanded value is never converted here: the unit travels alongside
    # it and the driver decides. Seven counts must arrive as seven.
    assert calls[0]["params_dict"]["value"] == 7
    assert calls[0]["params_dict"]["units"] == "counts"
    assert calls[0]["params_dict"]["mode"] == "relative"
    # Omitted rather than sent as null, so the server keeps its own default.
    assert "speed" not in calls[0]["params_dict"]
    print("test_move_sends_the_value_untouched_and_names_its_unit PASS")


def test_move_passes_an_enum_by_value(dispatched):
    calls, reply = dispatched
    reply["value"] = ((ErrorCodes.none, {}), ErrorCodes.none)

    asyncio.run(
        move_axis(
            "MOTOR", "127.0.0.1", 8003, axis="x", value=1.0, units=Units.mm, speed=5
        )
    )

    assert calls[0]["params_dict"]["units"] == "mm"
    assert calls[0]["params_dict"]["speed"] == 5
    print("test_move_passes_an_enum_by_value PASS")


def test_stop_takes_no_axis_and_reports_what_it_halted(dispatched):
    calls, reply = dispatched
    reply["value"] = ((ErrorCodes.none, {"stopped": ["x", "y"]}), ErrorCodes.none)

    error_code, payload = asyncio.run(stop_motion("MOTOR", "127.0.0.1", 8003))

    assert error_code == ErrorCodes.none
    assert payload == {"stopped": ["x", "y"]}
    assert calls[0]["private_action"] == "stop_motion"
    assert calls[0].get("params_dict") in (None, {})
    print("test_stop_takes_no_axis_and_reports_what_it_halted PASS")


def test_a_failed_command_reports_its_code_rather_than_swallowing_it(dispatched):
    _, reply = dispatched
    reply["value"] = ((ErrorCodes.motor, {}), ErrorCodes.motor)

    error_code, payload = asyncio.run(
        move_axis("MOTOR", "127.0.0.1", 8003, axis="x", value=1.0)
    )

    assert error_code == ErrorCodes.motor
    assert payload == {}
    print("test_a_failed_command_reports_its_code_rather_than_swallowing_it PASS")


def test_an_unreachable_server_reports_a_code_not_an_exception(dispatched):
    _, reply = dispatched
    reply["value"] = RuntimeError("connection refused")

    assert asyncio.run(move_axis("MOTOR", "127.0.0.1", 8003, axis="x", value=1.0)) == (
        ErrorCodes.unspecified,
        {},
    )
    assert asyncio.run(stop_motion("MOTOR", "127.0.0.1", 8003)) == (
        ErrorCodes.unspecified,
        {},
    )
    print("test_an_unreachable_server_reports_a_code_not_an_exception PASS")


# --------------------------------------------------------------------------
# refused is not failed
# --------------------------------------------------------------------------


def test_refused_is_a_distinct_outcome_from_failed():
    assert outcome_status(ErrorCodes.none) == ""
    assert outcome_status(ErrorCodes.in_progress) == REFUSED_STATUS
    assert outcome_status(ErrorCodes.motor) == FAILED_STATUS
    # The load-bearing one, and the float analogue of unknown-is-not-off:
    # nothing is broken when a sequence is running, so a generic red failure
    # would lead an engineer to conclude the panel itself is broken.
    assert outcome_status(ErrorCodes.in_progress) != outcome_status(ErrorCodes.motor)
    print("test_refused_is_a_distinct_outcome_from_failed PASS")


def test_the_refusal_names_the_remedy_not_just_the_cause():
    assert "sequence is running" in REFUSED_STATUS
    assert "Stop" in REFUSED_STATUS
    print("test_the_refusal_names_the_remedy_not_just_the_cause PASS")


def test_a_refused_move_is_reported_as_refused(dispatched):
    _, reply = dispatched
    reply["value"] = ((ErrorCodes.in_progress, {}), ErrorCodes.in_progress)

    error_code, _ = asyncio.run(
        move_axis("MOTOR", "127.0.0.1", 8003, axis="x", value=1.0)
    )

    assert outcome_status(error_code) == REFUSED_STATUS
    print("test_a_refused_move_is_reported_as_refused PASS")


# --------------------------------------------------------------------------
# T-U17 -- the layer stays backend-agnostic
# --------------------------------------------------------------------------


def test_the_shared_layer_imports_neither_ui_stack():
    """Neither ``bokeh`` nor ``reflex``, asserted against the source.

    This is what lets both stacks -- and a later port over both control kinds
    -- consume one module. An import of either would make the module a member
    of one stack and force the other to fork the rules.
    """
    path = os.path.join(REPO_ROOT, "helao", "ui", "shared", "motion_control.py")
    with open(path, encoding="utf-8") as handle:
        source = handle.read()

    offenders = [
        line
        for line in source.splitlines()
        if re.match(r"^\s*(import|from)\s+(bokeh|reflex)\b", line)
    ]
    assert offenders == [], f"UI stack imported in the shared layer: {offenders}"
    print("test_the_shared_layer_imports_neither_ui_stack PASS")


def test_importing_the_module_pulls_in_neither_ui_stack():
    # The source check above would miss an indirect import, so also assert that
    # importing this module in a clean interpreter does not drag either stack
    # in. Run out-of-process: pytest's own session may have imported them.
    import subprocess
    import sys

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import helao.ui.shared.motion_control; "
            "print(sorted(m for m in sys.modules if m in ('bokeh', 'reflex')))",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "[]", proc.stdout
    print("test_importing_the_module_pulls_in_neither_ui_stack PASS")


# --------------------------------------------------------------------------
# constants the two stacks share
# --------------------------------------------------------------------------


def test_the_unit_enum_is_defined_here_and_carries_both_units():
    # One enum for this layer, both stacks and all three endpoints. A plain
    # string would let "count" fall through to the millimetre branch and
    # execute a 10 000-count move as 10 000 millimetres.
    assert [u.value for u in Units] == ["mm", "counts"]
    assert Units("mm") is Units.mm
    with pytest.raises(ValueError):
        Units("count")
    print("test_the_unit_enum_is_defined_here_and_carries_both_units PASS")


def test_the_shared_constants_are_present_and_sane():
    assert AXIS_SOURCES == ("letter_scale", "name_scale", "inverse_scale")
    assert DEFAULT_WARN_ABOVE_MM == 10.0
    assert ARM_TIMEOUT_S == 30
    # Far below the dispatcher's 60s/5-retry defaults: these run on the Bokeh
    # document callback, where a slow retry renders the page blank.
    assert motion_control.CALL_TIMEOUT < 60
    assert motion_control.READ_RETRIES < 5
    assert motion_control.WRITE_RETRIES < 5
    print("test_the_shared_constants_are_present_and_sane PASS")


# ---------------------------------------------------------------------------
# Follow-up refresh policy.
#
# Added after a live-instrument test: the readout did not update when motion
# ended on the fire-and-forget driver family, because a move command returns
# once the motion is *dispatched*. These pin the two rules that make a shared
# refresh policy work across drivers with opposite blocking semantics.
# ---------------------------------------------------------------------------


def test_the_grace_window_survives_an_immediate_not_moving():
    # THE bug this policy exists to fix. A read taken straight after dispatch
    # can answer moving=False because the stage has not started yet, not
    # because it finished. A naive "poll while moving" believes that first
    # answer and leaves the pre-move coordinate on screen forever.
    assert motion_control.should_follow_up({"x": {"moving": False}}, 0.0) is True
    assert (
        motion_control.should_follow_up(
            {"x": {"moving": False}}, motion_control.FOLLOWUP_GRACE_S - 0.01
        )
        is True
    )
    print("test_the_grace_window_survives_an_immediate_not_moving PASS")


def test_it_stops_once_motion_has_genuinely_ceased():
    assert (
        motion_control.should_follow_up(
            {"x": {"moving": False}}, motion_control.FOLLOWUP_GRACE_S + 0.01
        )
        is False
    )
    print("test_it_stops_once_motion_has_genuinely_ceased PASS")


def test_it_keeps_reading_while_an_axis_reports_motion():
    assert motion_control.should_follow_up({"x": {"moving": True}}, 30.0) is True
    # One moving axis is enough; the panel reads every axis in one call.
    assert (
        motion_control.should_follow_up(
            {"x": {"moving": False}, "y": {"moving": True}}, 30.0
        )
        is True
    )
    print("test_it_keeps_reading_while_an_axis_reports_motion PASS")


def test_unknown_motion_does_not_sustain_the_follow_up():
    # `moving` is tri-state. None means the driver could not say -- treating
    # "don't know" as "still moving" would poll a silent server all the way to
    # the ceiling on every single move.
    assert motion_control.should_follow_up({"x": {"moving": None}}, 30.0) is False
    print("test_unknown_motion_does_not_sustain_the_follow_up PASS")


def test_the_ceiling_terminates_a_permanently_moving_axis():
    # An axis whose flag never clears must not be followed forever: on the
    # Reflex side an unbounded refresh outlives the browser tab.
    assert (
        motion_control.should_follow_up(
            {"x": {"moving": True}}, motion_control.FOLLOWUP_CEILING_S
        )
        is False
    )
    assert motion_control.FOLLOWUP_CEILING_S > motion_control.FOLLOWUP_GRACE_S
    assert motion_control.FOLLOWUP_INTERVAL_S < motion_control.FOLLOWUP_GRACE_S
    print("test_the_ceiling_terminates_a_permanently_moving_axis PASS")


def test_a_malformed_or_empty_payload_ends_the_follow_up_quietly():
    # An unreachable server yields {}; a garbled reply may not hold dicts.
    assert motion_control.should_follow_up({}, 30.0) is False
    assert motion_control.should_follow_up(None, 30.0) is False
    assert motion_control.should_follow_up({"x": None}, 30.0) is False
    assert motion_control.should_follow_up({"x": "moving"}, 30.0) is False
    print("test_a_malformed_or_empty_payload_ends_the_follow_up_quietly PASS")


def test_abandoning_live_motion_is_logged_not_silent():
    # The only symptom of the 120s bug was a stale number on a panel, which is
    # not something a station can report usefully. If the follow-up ever again
    # gives up on an axis that is still moving, the log says so.
    records = []

    class _Capture:
        def warning(self, msg, *args):
            records.append(msg % args if args else msg)

        def __getattr__(self, _name):
            return lambda *a, **k: None

    original = motion_control.LOGGER
    motion_control.LOGGER = _Capture()
    try:
        # Still moving at the ceiling -> abandoned, and said out loud.
        assert (
            motion_control.should_follow_up(
                {"x": {"moving": True}}, motion_control.FOLLOWUP_CEILING_S
            )
            is False
        )
        assert len(records) == 1
        assert "ceiling" in records[0]

        # Stopped at the ceiling is an ordinary ending, not a warning.
        records.clear()
        assert (
            motion_control.should_follow_up(
                {"x": {"moving": False}}, motion_control.FOLLOWUP_CEILING_S
            )
            is False
        )
        assert records == []
    finally:
        motion_control.LOGGER = original
    print("test_abandoning_live_motion_is_logged_not_silent PASS")


def test_the_followup_ceiling_covers_the_drivers_move_wait_cap():
    # The driver waits for its own moves up to its cap; the follow-up must not be
    # shorter than that cap (equal is fine), or it abandons live motion. The
    # hte configs' slowest axis is swept in hte's test_motion_control_hte.py.
    MOVE_WAIT_CAP_S = 30 * 60  # NativeGalilMotion's per-move wait cap

    assert motion_control.FOLLOWUP_CEILING_S >= MOVE_WAIT_CAP_S
