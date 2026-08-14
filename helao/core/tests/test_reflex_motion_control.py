"""The Reflex motion controls on ``/control``: discovery, arming, and unknown.

The page is the thin half of this feature by design -- every behavioural rule
lives in :mod:`helao.ui.shared.motion_control`, which
``test_motion_control.py`` gates -- so what is asserted here is that the page
*routes through* those rules rather than reimplementing them, and that its two
row storages stay independent.

Four of these tests exist because their failure mode is silent:

* a panel module with no ``DO_GROUPS`` used to raise into a handler that
  **drops the panel**, so a station's motion controls would simply never have
  appeared;
* a confirmation granted for one value must not authorise another, and a stale
  arm looks exactly like a working one;
* a bare ``list`` annotation on a var ``rx.foreach`` iterates fails the
  *frontend build*, not the import -- at a station with no Node to rebuild it;
* a follow-up that stops on the first ``moving: False`` leaves the *pre-move*
  coordinate on screen, which is indistinguishable from a move that has not
  gone anywhere. That one was found on a live instrument rather than here.

Event handlers are exercised directly rather than through a browser, as in
``test_reflex_control.py``: they are coroutines whose job is to fold a
transport result into rows, and that is what can be wrong.
"""

import ast
import asyncio
import inspect
import json
import types
from pathlib import Path

import pytest

from helao.core.error import ErrorCodes
from helao.ui.shared import palette
from helao.ui.shared.motion_control import (
    ARM_TIMEOUT_S,
    FAILED_STATUS,
    FOLLOWUP_CEILING_S,
    FOLLOWUP_GRACE_S,
    FOLLOWUP_INTERVAL_S,
    REFUSED_STATUS,
    Units,
)
from helao.ui.shared.palette import TW
from helao.ui.reflex import control as control_mod
from helao.ui.reflex.control import (
    MOTION_ARM,
    MOTION_AXIS,
    MOTION_ENABLED,
    MOTION_LABEL,
    MOTION_MM,
    MOTION_MODE,
    MOTION_MOVING,
    MOTION_SERVER,
    MOTION_UNITS,
    MOTION_VALUE,
    ControlState,
    control_targets,
)

# The pinned contrast arithmetic, reused rather than reimplemented: two
# implementations of the same luminance formula eventually disagree, and the
# one in the palette gate is the authoritative one.
from helao.core.tests.test_palette import (
    FLOOR_BODY_TEXT,
    FLOOR_CONTROL,
    contrast_ratio,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
WHITE = "#ffffff"

# A synthetic station, not a copy of any shipped config: representative scale
# magnitudes for a letter-keyed controller (roughly 1e-4 mm per count), an axis
# deliberately left with no scale to exercise the disabled path, and a digital
# server alongside so the two row storages are always both populated.
WORLD = {
    "servers": {
        "IO": {
            "host": "127.0.0.1",
            "port": 8005,
            "control_vis": "digital_out_control",
            "params": {"dev_do": {"gamry_aux": 1, "Thorlab_led": 7}},
        },
        "MOTOR": {
            "host": "127.0.0.1",
            "port": 8003,
            "control_vis": "motion_control_letter_scale",
            "params": {
                "axis_id": {"x": "C", "y": "B", "w": "D"},
                # No entry for "D": that axis has no mm/count relation at all.
                "count_to_mm": {"B": 1.5628e-04, "C": 1.5628e-04},
            },
        },
    }
}

#: mm per count for x and y above; 100000 counts is 15.6 mm, over the 10.0 mm
#: default threshold, and 1000 counts is 0.16 mm, well under it.
SCALE = 1.5628e-04


@pytest.fixture(autouse=True)
def panel_modules(monkeypatch):
    """Stand in for the panel modules Phase 6 ships.

    ``resolve_panel_module`` is patched where ``control`` imported it, not in
    ``discovery``: the real one is ``lru_cache``d, so patching it there would
    leak a resolution into every later test in the process.
    """

    def _resolve(module_name):
        if module_name == "motion_control_letter_scale":
            # A motion module: an axis schema and a title, and pointedly no
            # DO_GROUPS.
            return types.SimpleNamespace(
                AXIS_SOURCE="letter_scale", TITLE="Motion controls"
            )
        if module_name == "digital_out_control":
            # The legacy three-line shape, verbatim: groups and nothing else.
            return types.SimpleNamespace(DO_GROUPS=("dev_do",))
        raise ModuleNotFoundError(module_name)

    monkeypatch.setattr(control_mod, "resolve_panel_module", _resolve)


class _FakeState:
    """A stand-in carrying the vars and helpers the handlers touch.

    Deliberately not a ``ControlState`` subclass, for the reason
    ``test_reflex_control.py`` records: Reflex intercepts attribute assignment
    on a real state and forwards it to a parent that does not exist outside a
    session. Every non-event method the handlers reach through ``self`` has to
    be listed, so a missing one fails loudly rather than quietly passing.
    """

    def __init__(self):
        self.rows = []
        self.motion_rows = []
        self.status = ""
        self.loaded = False
        self.tick_ms = control_mod.IDLE_TICK_MS
        self.followup_server = ""
        self.followup_since = 0.0
        self.followup_busy = False

    _state_of = ControlState._state_of
    _apply = ControlState._apply
    _read_into_rows = ControlState._read_into_rows
    _motion_from = ControlState._motion_from
    _motion_row_of = ControlState._motion_row_of
    _rewrite_motion = ControlState._rewrite_motion
    _blank_position = ControlState._blank_position
    _refresh_positions = ControlState._refresh_positions
    _begin_followup = ControlState._begin_followup
    _end_followup = ControlState._end_followup

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def page(monkeypatch):
    """Configure the page and script what the endpoints reply."""
    sent: list = []
    script: dict = {
        "read": {},
        "positions": {},
        "move": (ErrorCodes.none, {}),
        "stop": (ErrorCodes.none, {"stopped": ["x", "y", "w"]}),
        "write": {},
        # Every position read this test provoked, in order. Kept apart from
        # ``sent`` on purpose: the follow-up reads *after* a command, so
        # appending reads there would move what ``sent[-1]`` means in every
        # test that asserts on the last command dispatched.
        "position_reads": [],
    }

    async def _read(server_key, host, port):
        return dict(script["read"].get(server_key, {}))

    async def _write(server_key, host, port, do_name, on):
        sent.append(("set", server_key, do_name, on))
        return dict(script["write"])

    async def _positions(server_key, host, port):
        script["position_reads"].append(server_key)
        return {
            axis: dict(values)
            for axis, values in (script["positions"].get(server_key) or {}).items()
        }

    async def _move(server_key, host, port, axis, value, mode=None, units=None, **kw):
        sent.append(("move", server_key, axis, value, mode, units))
        return script["move"]

    async def _stop(server_key, host, port):
        sent.append(("stop", server_key))
        return script["stop"]

    monkeypatch.setattr(control_mod, "read_digital_outs", _read)
    monkeypatch.setattr(control_mod, "set_digital_out", _write)
    monkeypatch.setattr(control_mod, "read_axis_positions", _positions)
    monkeypatch.setattr(control_mod, "move_axis", _move)
    monkeypatch.setattr(control_mod, "stop_motion", _stop)
    control_mod.configure_control(WORLD, "REFLEX")
    return sent, script


def _load(state):
    asyncio.run(ControlState.load.fn(state))


def _move(state, server_key, axis):
    asyncio.run(ControlState.move.fn(state, server_key, axis))


def _stop(state, server_key):
    asyncio.run(ControlState.stop.fn(state, server_key))


def _toggle(state, server_key, do_name):
    asyncio.run(ControlState.toggle.fn(state, server_key, do_name))


def _tick(state):
    """Fire one interval tick, as the page's ticking component would."""
    asyncio.run(ControlState.follow_up.fn(state))


def _motion(state, axis):
    """Return the row currently rendered for one MOTOR axis."""
    return next(row for row in state.motion_rows if row[MOTION_AXIS] == axis)


def _positioned(x_mm=1.0, x_counts=6398, moving=False):
    """A reply describing all three axes, x at a known coordinate."""
    return {
        "MOTOR": {
            "x": {"mm": x_mm, "counts": x_counts, "moving": moving},
            "y": {"mm": 2.0, "counts": 12797, "moving": False},
            "w": {"mm": None, "counts": 4096, "moving": False},
        }
    }


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------


def test_a_motion_server_yields_a_target_with_its_axes():
    targets = {t.server_key: t for t in control_targets(WORLD)}

    assert [a.axis for a in targets["MOTOR"].axes] == ["x", "y", "w"]
    assert targets["MOTOR"].title == "Motion controls"
    # The digital server is untouched by any of this.
    assert [i.name for i in targets["IO"].items] == ["gamry_aux", "Thorlab_led"]
    print("test_a_motion_server_yields_a_target_with_its_axes PASS")


def test_axis_source_is_passed_through_to_discover_axes(monkeypatch):
    """Read *and used*, which is the whole of P10.

    A module's ``AXIS_SOURCE`` names which of three config schemas the axes are
    declared in, and the schemas cannot be told apart by inspection -- two of
    them key their scale by axis name and differ only in orientation. A page
    that read the value and then sniffed the config would be right by
    coincidence and wrong by the square of the scale.
    """
    seen: list = []

    def _spy(server_config, axis_source, *, server_key=""):
        seen.append((server_key, axis_source))
        return []

    monkeypatch.setattr(control_mod, "discover_axes", _spy)
    control_targets(WORLD)

    assert seen == [("MOTOR", "letter_scale")], seen
    print("test_axis_source_is_passed_through_to_discover_axes PASS")


def test_a_panel_module_without_do_groups_is_not_dropped():
    """The hard read used to raise into a handler that skips the panel.

    Not a crash -- a *silence*. The page rendered, every other server appeared,
    and the motion controls were simply absent, indistinguishable from a
    mistyped module name in the config.
    """
    targets = control_targets(WORLD)

    assert "MOTOR" in [t.server_key for t in targets]
    assert next(t for t in targets if t.server_key == "MOTOR").items == ()
    print("test_a_panel_module_without_do_groups_is_not_dropped PASS")


def test_a_legacy_digital_panel_module_still_yields_a_target_with_no_axes():
    """AC6: a deployment's existing three-line module keeps working unedited."""
    target = next(t for t in control_targets(WORLD) if t.server_key == "IO")

    assert target.axes == ()
    assert target.axis_source == ""
    assert [i.name for i in target.items] == ["gamry_aux", "Thorlab_led"]
    assert target.title == "Digital output controls"
    print("test_a_legacy_digital_panel_module_still_yields_a_target_with_no_axes PASS")


def test_an_axis_with_no_configured_scale_is_discovered_but_disabled():
    """P3: said once, statically, rather than warned about on every move.

    The alternative -- leaving the control live and confirming every move
    because the threshold cannot be evaluated -- trains an operator to dismiss
    the dialog, and they then dismiss it on the axes where it matters.
    """
    axes = {a.axis: a for a in control_targets(WORLD)[1].axes}

    assert axes["w"].mm_per_count is None
    assert axes["w"].move_enabled is False
    assert axes["x"].move_enabled is True
    print("test_an_axis_with_no_configured_scale_is_discovered_but_disabled PASS")


def test_an_unresolvable_motion_module_is_skipped_not_raised():
    world = {
        "servers": {
            "MOTOR": {
                "host": "h",
                "port": 1,
                "control_vis": "no_such_motion_module",
                "params": {"axis_id": {"x": "C"}},
            }
        }
    }
    assert control_targets(world) == []
    print("test_an_unresolvable_motion_module_is_skipped_not_raised PASS")


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------


def test_the_mount_read_covers_motion_through_the_one_handler(page):
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    assert [row[MOTION_AXIS] for row in state.motion_rows] == ["x", "y", "w"]
    assert _motion(state, "x")[MOTION_LABEL] == "1.000 mm / 6398 counts"
    print("test_the_mount_read_covers_motion_through_the_one_handler PASS")


def test_an_unread_coordinate_renders_unknown_never_zero(page):
    """Zero is a legitimate motor coordinate.

    A failed read shown as ``0.000 mm`` is indistinguishable from an axis
    sitting at its origin, on a panel whose whole job is telling an engineer
    where the instrument is.
    """
    _, script = page
    script["positions"] = {}  # the server did not answer
    state = _FakeState()
    _load(state)

    for row in state.motion_rows:
        assert row[MOTION_LABEL] == "? mm / ? counts", row
        assert "0.000" not in row[MOTION_LABEL]
    unreachable = state.status.split(";")[0]
    assert unreachable.startswith("could not read:"), state.status
    assert "MOTOR" in unreachable, state.status
    print("test_an_unread_coordinate_renders_unknown_never_zero PASS")


def test_a_half_known_axis_reports_the_half_it_has(page):
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    # The scale-less axis can report counts and honestly cannot report mm.
    assert _motion(state, "w")[MOTION_LABEL] == "? mm / 4096 counts"
    print("test_a_half_known_axis_reports_the_half_it_has PASS")


def test_an_answering_server_with_a_silent_axis_says_which(page):
    _, script = page
    script["read"] = {"IO": {"gamry_aux": True, "Thorlab_led": False}}
    script["positions"] = {"MOTOR": {"x": {"mm": 1.0, "counts": 6398, "moving": False}}}
    state = _FakeState()
    _load(state)

    assert "position unknown: MOTOR y, MOTOR w" in state.status, state.status
    # A server that answered is not one that could not be reached, and the two
    # call for different things.
    assert "could not read" not in state.status, state.status
    print("test_an_answering_server_with_a_silent_axis_says_which PASS")


def test_a_moving_axis_is_flagged_so_a_stale_coordinate_looks_stale(page):
    _, script = page
    script["positions"] = _positioned(moving=True)
    state = _FakeState()
    _load(state)

    assert _motion(state, "x")[MOTION_MOVING] == "moving"
    assert _motion(state, "y")[MOTION_MOVING] == "stopped"
    print("test_a_moving_axis_is_flagged_so_a_stale_coordinate_looks_stale PASS")


def test_load_stays_idempotent_with_motion_rows(page):
    _, script = page
    script["positions"] = _positioned(x_mm=1.0)
    state = _FakeState()
    _load(state)

    script["positions"] = _positioned(x_mm=9.0)
    _load(state)

    # Reflex can fire on_mount more than once; a second read would stamp over
    # what the panel has since commanded.
    assert _motion(state, "x")[MOTION_LABEL] == "1.000 mm / 6398 counts"
    print("test_load_stays_idempotent_with_motion_rows PASS")


def test_a_read_keeps_what_has_been_typed(page):
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)
    ControlState.set_move_value.fn(state, "MOTOR", "x", "5")
    ControlState.set_move_mode.fn(state, "MOTOR", "x", "absolute")

    asyncio.run(ControlState.reread.fn(state))

    row = _motion(state, "x")
    assert row[MOTION_MODE] == "absolute", "a position read discarded the mode"
    print("test_a_read_keeps_what_has_been_typed PASS")


# --------------------------------------------------------------------------
# the two storages
# --------------------------------------------------------------------------


def test_a_toggle_does_not_perturb_motion_state(page):
    _, script = page
    script["read"] = {"IO": {"gamry_aux": True, "Thorlab_led": False}}
    script["positions"] = _positioned()
    script["write"] = {"gamry_aux": False}
    state = _FakeState()
    _load(state)
    before = [list(row) for row in state.motion_rows]

    _toggle(state, "IO", "gamry_aux")

    assert state.motion_rows == before
    print("test_a_toggle_does_not_perturb_motion_state PASS")


def test_a_move_does_not_perturb_digital_output_state(page):
    _, script = page
    script["read"] = {"IO": {"gamry_aux": True, "Thorlab_led": False}}
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)
    before = [list(row) for row in state.rows]

    ControlState.set_move_value.fn(state, "MOTOR", "x", "0.5")
    _move(state, "MOTOR", "x")

    assert state.rows == before
    print("test_a_move_does_not_perturb_digital_output_state PASS")


# --------------------------------------------------------------------------
# moving, and the confirmation
# --------------------------------------------------------------------------


def test_a_small_move_goes_on_the_first_click(page):
    sent, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    ControlState.set_move_value.fn(state, "MOTOR", "x", "0.5")
    _move(state, "MOTOR", "x")

    assert sent[-1] == ("move", "MOTOR", "x", 0.5, "relative", Units.mm), sent
    print("test_a_small_move_goes_on_the_first_click PASS")


def test_a_large_move_arms_first_and_dispatches_nothing(page):
    sent, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    ControlState.set_move_value.fn(state, "MOTOR", "x", "25")
    _move(state, "MOTOR", "x")

    assert [s for s in sent if s[0] == "move"] == [], sent
    assert _motion(state, "x")[MOTION_ARM] == "armed"
    assert "large move" in state.status, state.status

    _move(state, "MOTOR", "x")
    assert sent[-1] == ("move", "MOTOR", "x", 25.0, "relative", Units.mm), sent
    assert _motion(state, "x")[MOTION_ARM] == "ready", "the arm must be spent"
    print("test_a_large_move_arms_first_and_dispatches_nothing PASS")


@pytest.mark.parametrize(
    "start_units, start_value, field, changed",
    [
        ("mm", "100", "value", "200"),
        ("mm", "100", "mode", "absolute"),
        # The units case runs counts -> mm rather than the other way, so that
        # *both* sides of the change are a large move. Going mm -> counts turns
        # 100 mm into 100 counts, which is 0.016 mm and correctly needs no
        # confirmation at all -- a pass that would prove nothing about the arm.
        ("counts", "100000", "units", "mm"),
    ],
)
def test_changing_what_was_confirmed_disarms(
    page, start_units, start_value, field, changed
):
    """The arm is bound to the ``(value, mode, units)`` it was granted for.

    Without this: type 100, click (arms), change to 200, click -- and a 200 mm
    move executes under a confirmation granted for 100.
    """
    sent, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)
    ControlState.set_move_units.fn(state, "MOTOR", "x", start_units)
    ControlState.set_move_value.fn(state, "MOTOR", "x", start_value)
    _move(state, "MOTOR", "x")
    assert _motion(state, "x")[MOTION_ARM] == "armed"

    {
        "value": ControlState.set_move_value.fn,
        "mode": ControlState.set_move_mode.fn,
        "units": ControlState.set_move_units.fn,
    }[field](state, "MOTOR", "x", changed)

    assert _motion(state, "x")[MOTION_ARM] == "ready"
    _move(state, "MOTOR", "x")
    assert [s for s in sent if s[0] == "move"] == [], sent
    assert _motion(state, "x")[MOTION_ARM] == "armed", "the click must re-arm"
    print(f"test_changing_what_was_confirmed_disarms[{field}] PASS")


def test_a_disarmed_move_is_re_judged_not_merely_re_confirmed(page):
    """Changing the unit changes how big the move is, not just its label.

    100 mm is a traverse; 100 *counts* on this axis is 0.016 mm. Disarming and
    then re-running the threshold is what makes the second click on the smaller
    move go straight through instead of demanding a confirmation for a move
    nobody needs to think about.
    """
    sent, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    ControlState.set_move_value.fn(state, "MOTOR", "x", "100")
    _move(state, "MOTOR", "x")
    assert _motion(state, "x")[MOTION_ARM] == "armed"

    ControlState.set_move_units.fn(state, "MOTOR", "x", "counts")
    _move(state, "MOTOR", "x")

    assert sent[-1] == ("move", "MOTOR", "x", 100.0, "relative", Units.counts), sent
    print("test_a_disarmed_move_is_re_judged_not_merely_re_confirmed PASS")


def test_an_arm_expires(page, monkeypatch):
    """A confirmation that outlived the attention it was granted under."""
    sent, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)
    clock = {"t": 1000.0}
    monkeypatch.setattr(control_mod, "_now", lambda: clock["t"])

    ControlState.set_move_value.fn(state, "MOTOR", "x", "25")
    _move(state, "MOTOR", "x")
    assert _motion(state, "x")[MOTION_ARM] == "armed"

    clock["t"] += ARM_TIMEOUT_S + 1
    _move(state, "MOTOR", "x")

    assert [s for s in sent if s[0] == "move"] == [], sent
    assert _motion(state, "x")[MOTION_ARM] == "armed", "it must re-arm, not move"
    print("test_an_arm_expires PASS")


def test_an_absolute_move_is_judged_on_the_displacement(page):
    """Absolute 25.0 from 24.9 is a 0.1 mm move.

    Comparing the entered coordinate instead would confirm nearly every
    absolute move and teach an operator to click through the dialog -- and the
    page can only get this right by handing the shared rule the coordinate it
    last read, which is what this asserts.
    """
    sent, script = page
    script["positions"] = _positioned(x_mm=24.9)
    state = _FakeState()
    _load(state)

    ControlState.set_move_mode.fn(state, "MOTOR", "x", "absolute")
    ControlState.set_move_value.fn(state, "MOTOR", "x", "25.0")
    _move(state, "MOTOR", "x")

    assert sent[-1] == ("move", "MOTOR", "x", 25.0, "absolute", Units.mm), sent
    print("test_an_absolute_move_is_judged_on_the_displacement PASS")


def test_an_absolute_move_from_an_unread_coordinate_asks_first(page):
    """Fail closed while the state is *transient*: the next read clears it."""
    sent, script = page
    script["positions"] = {}
    state = _FakeState()
    _load(state)

    ControlState.set_move_mode.fn(state, "MOTOR", "x", "absolute")
    ControlState.set_move_value.fn(state, "MOTOR", "x", "0.1")
    _move(state, "MOTOR", "x")

    assert [s for s in sent if s[0] == "move"] == [], sent
    assert _motion(state, "x")[MOTION_ARM] == "armed"
    print("test_an_absolute_move_from_an_unread_coordinate_asks_first PASS")


def test_a_counts_move_is_dispatched_exactly_as_typed(page):
    """Nothing on this page converts a commanded value.

    The unit travels alongside as a discriminator and the conversion -- or the
    deliberate absence of one -- happens in the driver. A page that divided by
    the scale here would send a number the driver then divided again.
    """
    sent, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    ControlState.set_move_units.fn(state, "MOTOR", "x", "counts")
    ControlState.set_move_value.fn(state, "MOTOR", "x", "1000")
    _move(state, "MOTOR", "x")

    assert sent[-1] == ("move", "MOTOR", "x", 1000.0, "relative", Units.counts), sent
    print("test_a_counts_move_is_dispatched_exactly_as_typed PASS")


def test_a_large_counts_move_still_asks(page):
    """The one place the scale reaches a decision, so the one to get wrong."""
    sent, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    ControlState.set_move_units.fn(state, "MOTOR", "x", "counts")
    ControlState.set_move_value.fn(state, "MOTOR", "x", "100000")  # 15.6 mm
    assert 100000 * SCALE > 10.0
    _move(state, "MOTOR", "x")

    assert [s for s in sent if s[0] == "move"] == [], sent
    assert _motion(state, "x")[MOTION_ARM] == "armed"
    print("test_a_large_counts_move_still_asks PASS")


def test_an_unrecognised_unit_falls_back_to_millimetres(page):
    """A dropdown value is a string, and ``"count"`` is the plausible typo.

    Falling through to the millimetre branch is what would execute a ten
    thousand *count* move as ten thousand *millimetres*.
    """
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    ControlState.set_move_units.fn(state, "MOTOR", "x", "count")
    assert _motion(state, "x")[MOTION_UNITS] == Units.mm.value
    ControlState.set_move_mode.fn(state, "MOTOR", "x", "Absolute")
    assert _motion(state, "x")[MOTION_MODE] == "relative"
    print("test_an_unrecognised_unit_falls_back_to_millimetres PASS")


def test_a_move_on_a_scale_less_axis_dispatches_nothing(page):
    sent, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    assert _motion(state, "w")[MOTION_ENABLED] == "disabled"
    # Its unit dropdown is the only one it can honestly offer.
    assert _motion(state, "w")[MOTION_UNITS] == Units.counts.value

    ControlState.set_move_value.fn(state, "MOTOR", "w", "10")
    _move(state, "MOTOR", "w")

    assert [s for s in sent if s[0] == "move"] == [], sent
    assert "no scale configured" in state.status, state.status
    print("test_a_move_on_a_scale_less_axis_dispatches_nothing PASS")


def test_an_empty_value_is_not_a_move_to_zero(page):
    sent, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    _move(state, "MOTOR", "x")

    assert [s for s in sent if s[0] == "move"] == [], sent
    assert "type a move value" in state.status, state.status
    print("test_an_empty_value_is_not_a_move_to_zero PASS")


def test_a_failed_move_leaves_the_coordinate_unknown(page):
    """The same contract a failed digital write keeps.

    The command may or may not have landed, so the honest coordinate is
    unknown -- not the one the panel happened to be showing.
    """
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    script["move"] = (ErrorCodes.unspecified, {})
    ControlState.set_move_value.fn(state, "MOTOR", "x", "0.5")
    _move(state, "MOTOR", "x")

    row = _motion(state, "x")
    assert row[MOTION_LABEL] == "? mm / ? counts"
    assert row[MOTION_MM] == ""
    assert FAILED_STATUS in state.status, state.status
    # And only that axis.
    assert _motion(state, "y")[MOTION_LABEL] == "2.000 mm / 12797 counts"
    print("test_a_failed_move_leaves_the_coordinate_unknown PASS")


def test_a_refused_move_names_the_remedy_and_keeps_the_readout(page):
    """Refused is a fourth outcome, not a flavour of failed.

    A generic red failure on a panel whose purpose is reporting what the
    instrument is doing leads an engineer to conclude the panel is broken. The
    endpoint declined because a sequence is running; nothing is unknown, and
    the remedy is specific.
    """
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    script["move"] = (ErrorCodes.in_progress, {})
    ControlState.set_move_value.fn(state, "MOTOR", "x", "0.5")
    _move(state, "MOTOR", "x")

    assert REFUSED_STATUS in state.status, state.status
    assert "Stop first" in state.status, state.status
    assert _motion(state, "x")[MOTION_LABEL] == "1.000 mm / 6398 counts"
    print("test_a_refused_move_names_the_remedy_and_keeps_the_readout PASS")


def test_a_refused_move_does_not_stay_armed(page):
    """Or it would go the moment the sequence ended, with no second click."""
    sent, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    script["move"] = (ErrorCodes.in_progress, {})
    ControlState.set_move_value.fn(state, "MOTOR", "x", "25")
    _move(state, "MOTOR", "x")  # arms
    _move(state, "MOTOR", "x")  # dispatched, refused

    assert _motion(state, "x")[MOTION_ARM] == "ready"
    print("test_a_refused_move_does_not_stay_armed PASS")


def test_a_completed_move_re_reads_that_server(page):
    sent, script = page
    script["positions"] = _positioned(x_mm=1.0)
    state = _FakeState()
    _load(state)

    script["positions"] = _positioned(x_mm=1.5, x_counts=9597)
    ControlState.set_move_value.fn(state, "MOTOR", "x", "0.5")
    _move(state, "MOTOR", "x")

    assert _motion(state, "x")[MOTION_LABEL] == "1.500 mm / 9597 counts"
    print("test_a_completed_move_re_reads_that_server PASS")


# --------------------------------------------------------------------------
# stopping
# --------------------------------------------------------------------------


def test_stop_halts_the_server_and_re_reads(page):
    sent, script = page
    script["positions"] = _positioned(x_mm=1.0, moving=True)
    state = _FakeState()
    _load(state)

    script["positions"] = _positioned(x_mm=1.2, x_counts=7678, moving=False)
    _stop(state, "MOTOR")

    assert ("stop", "MOTOR") in sent
    assert _motion(state, "x")[MOTION_LABEL] == "1.200 mm / 7678 counts"
    assert _motion(state, "x")[MOTION_MOVING] == "stopped"
    assert "stopped x, y, w" in state.status, state.status
    print("test_stop_halts_the_server_and_re_reads PASS")


def test_stop_spends_every_arm_on_the_server(page):
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)
    ControlState.set_move_value.fn(state, "MOTOR", "x", "25")
    _move(state, "MOTOR", "x")
    assert _motion(state, "x")[MOTION_ARM] == "armed"

    _stop(state, "MOTOR")

    assert all(row[MOTION_ARM] == "ready" for row in state.motion_rows)
    print("test_stop_spends_every_arm_on_the_server PASS")


def test_a_failed_stop_says_so(page):
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    script["stop"] = (ErrorCodes.unspecified, {})
    _stop(state, "MOTOR")

    assert FAILED_STATUS in state.status, state.status
    print("test_a_failed_stop_says_so PASS")


def test_stopping_an_unknown_server_is_a_no_op(page):
    sent, _ = page
    state = _FakeState()
    _load(state)

    _stop(state, "NOT_A_SERVER")
    _move(state, "NOT_A_SERVER", "x")

    assert [s for s in sent if s[0] in ("stop", "move")] == []
    print("test_stopping_an_unknown_server_is_a_no_op PASS")


# --------------------------------------------------------------------------
# the follow-up refresh
# --------------------------------------------------------------------------
#
# Reported from a live instrument: after a move the readout did not update
# when the motion ended, and the operator had to press Read. Both stacks
# already re-read after dispatching, but a fire-and-forget driver answers
# before the stage has moved, so that read captures the *pre-move* coordinate
# and nothing re-reads afterwards.


@pytest.fixture
def clock(monkeypatch):
    """Hold the page's monotonic clock still, and let a test advance it.

    The same clock the arm timeout counts in, patched where the page reads it.
    Advancing it by hand is what makes the grace window and the ceiling
    testable at all -- the alternative is a test that sleeps for two minutes.
    """
    held = {"t": 1000.0}
    monkeypatch.setattr(control_mod, "_now", lambda: held["t"])
    return held


def _commanded_move(state, page, *, moving):
    """Dispatch a small move on x, the server answering with *moving*."""
    _, script = page
    script["positions"] = _positioned(x_mm=1.0, x_counts=6398, moving=moving)
    ControlState.set_move_value.fn(state, "MOTOR", "x", "0.5")
    _move(state, "MOTOR", "x")


def test_a_commanded_move_starts_a_follow_up(page, clock):
    """The defect itself: one read after dispatch is not enough."""
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    _commanded_move(state, page, moving=True)

    assert state.followup_server == "MOTOR"
    assert state.followup_since == clock["t"]
    # The tick has to speed up as well as be armed: a follow-up nothing ever
    # fires is the stale readout with extra state.
    assert state.tick_ms == control_mod.FOLLOWUP_TICK_MS
    print("test_a_commanded_move_starts_a_follow_up PASS")


def test_the_follow_up_re_reads_while_moving_and_stops_once_it_clears(page, clock):
    """The whole feature, end to end.

    Each tick renders what it read, so when the follow-up does stop, the
    coordinate on screen is the last one the instrument reported rather than
    the one from the tick before.
    """
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)
    _commanded_move(state, page, moving=True)

    # Past the grace window, still travelling: keep going.
    clock["t"] += FOLLOWUP_GRACE_S + FOLLOWUP_INTERVAL_S
    script["positions"] = _positioned(x_mm=2.0, x_counts=12796, moving=True)
    _tick(state)

    assert state.followup_server == "MOTOR", "it stopped while the axis was moving"
    assert _motion(state, "x")[MOTION_LABEL] == "2.000 mm / 12796 counts"

    # Arrived.
    clock["t"] += FOLLOWUP_INTERVAL_S
    script["positions"] = _positioned(x_mm=3.0, x_counts=19194, moving=False)
    _tick(state)

    assert state.followup_server == ""
    assert state.tick_ms == control_mod.IDLE_TICK_MS
    assert _motion(state, "x")[MOTION_LABEL] == "3.000 mm / 19194 counts"
    assert _motion(state, "x")[MOTION_MOVING] == "stopped"
    print("test_the_follow_up_re_reads_while_moving_and_stops_once_it_clears PASS")


def test_the_grace_window_survives_an_immediate_not_moving(page, clock):
    """The exact bug being fixed, as a test.

    A read taken immediately after dispatch can answer ``moving: False`` --
    not because the move finished, but because it had not started. A policy of
    "re-read while moving" sees that first answer, concludes the move is over,
    and leaves the pre-move coordinate on screen.
    """
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)
    # The driver has not started the stage yet, so it reports stationary at the
    # coordinate it was already at.
    _commanded_move(state, page, moving=False)
    assert state.followup_server == "MOTOR"

    clock["t"] += FOLLOWUP_INTERVAL_S
    assert FOLLOWUP_INTERVAL_S < FOLLOWUP_GRACE_S, "the grace window is the point"
    script["positions"] = _positioned(x_mm=1.0, x_counts=6398, moving=False)
    reads = len(script["position_reads"])
    _tick(state)

    assert len(script["position_reads"]) == reads + 1, "it did not read at all"
    assert state.followup_server == "MOTOR", "it gave up inside the grace window"

    # Now the stage is genuinely moving, which is what the window was there to
    # catch, and the follow-up carries on past it.
    clock["t"] += FOLLOWUP_GRACE_S
    script["positions"] = _positioned(x_mm=1.4, x_counts=8957, moving=True)
    _tick(state)

    assert state.followup_server == "MOTOR"
    assert _motion(state, "x")[MOTION_LABEL] == "1.400 mm / 8957 counts"
    print("test_the_grace_window_survives_an_immediate_not_moving PASS")


def test_a_silent_moving_flag_ends_the_follow_up_at_the_grace_window(page, clock):
    """``moving`` is tri-state, and only an explicit ``True`` sustains it.

    Treating "the driver could not say" as "still moving" would poll a silent
    server all the way to the ceiling after every single move.
    """
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)
    _commanded_move(state, page, moving=None)

    clock["t"] += FOLLOWUP_GRACE_S
    _tick(state)

    assert state.followup_server == ""
    assert _motion(state, "x")[MOTION_MOVING] == "unknown"
    print("test_a_silent_moving_flag_ends_the_follow_up_at_the_grace_window PASS")


def test_the_tick_issues_no_request_once_the_follow_up_is_over(page, clock):
    """A page-level interval fires forever; this is what makes that acceptable.

    An idle ``/control`` tab must not put traffic on a station's motion
    servers, and it must not overwrite whatever the status line last said.
    """
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)
    _commanded_move(state, page, moving=False)
    clock["t"] += FOLLOWUP_GRACE_S
    _tick(state)
    assert state.followup_server == "", "the follow-up should be over by now"

    state.status = "something the engineer is reading"
    reads = len(script["position_reads"])
    for _ in range(10):
        clock["t"] += FOLLOWUP_INTERVAL_S
        _tick(state)

    assert len(script["position_reads"]) == reads, script["position_reads"]
    assert state.status == "something the engineer is reading"
    assert state.tick_ms == control_mod.IDLE_TICK_MS
    print("test_the_tick_issues_no_request_once_the_follow_up_is_over PASS")


def test_the_ceiling_terminates_a_permanently_moving_axis(page, clock):
    """A stuck axis, or a driver whose flag never clears.

    Unbounded is the failure this page's no-server-side-loop rule exists to
    prevent, and a tick that never gives up is the same thing wearing a
    component. The bound is computed from the policy's own constants rather
    than pinned to a number here, so a change to either is not silently
    absorbed.
    """
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)
    _commanded_move(state, page, moving=True)
    started = clock["t"]
    reads = len(script["position_reads"])

    # Deliberately more iterations than the ceiling allows: the loop must be
    # ended by the policy, not by running out of range.
    ticks = int(FOLLOWUP_CEILING_S / FOLLOWUP_INTERVAL_S) + 10
    for _ in range(ticks):
        clock["t"] += FOLLOWUP_INTERVAL_S
        _tick(state)
        if not state.followup_server:
            break
    else:
        raise AssertionError(f"the follow-up was still running after {ticks} ticks")

    assert clock["t"] - started <= FOLLOWUP_CEILING_S + FOLLOWUP_INTERVAL_S
    assert (
        len(script["position_reads"]) - reads
        <= FOLLOWUP_CEILING_S / FOLLOWUP_INTERVAL_S + 1
    )
    assert state.tick_ms == control_mod.IDLE_TICK_MS
    # And it says which of the two endings this was: the coordinate on screen
    # is the last one read, not a settled one, and Read is what is left.
    assert "still moving" in state.status, state.status
    assert "Read" in state.status, state.status
    print("test_the_ceiling_terminates_a_permanently_moving_axis PASS")


def test_a_settled_follow_up_does_not_claim_the_move_finished(page, clock):
    """It reports what it did -- read a position -- not what it cannot know."""
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)
    _commanded_move(state, page, moving=False)

    clock["t"] += FOLLOWUP_GRACE_S
    _tick(state)

    assert state.status == "MOTOR: position updated", state.status
    assert "still moving" not in state.status
    print("test_a_settled_follow_up_does_not_claim_the_move_finished PASS")


def test_a_second_move_restarts_the_follow_up_clock(page, clock):
    """Or the second move inherits the first's elapsed time.

    A move commanded two minutes after the last one would then be past the
    ceiling before its first tick and would never follow up at all.
    """
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)
    _commanded_move(state, page, moving=True)

    clock["t"] += FOLLOWUP_CEILING_S * 2
    _commanded_move(state, page, moving=True)

    assert state.followup_since == clock["t"]
    clock["t"] += FOLLOWUP_INTERVAL_S
    _tick(state)
    assert state.followup_server == "MOTOR"
    print("test_a_second_move_restarts_the_follow_up_clock PASS")


def test_an_overlapping_tick_is_dropped_rather_than_queued(page, clock):
    """A motion server slower than the interval must not stack up reads.

    Interleaved reads can land out of order and leave an older coordinate on
    top of a newer one -- a stale readout produced by the mechanism that exists
    to prevent stale readouts.
    """
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)
    _commanded_move(state, page, moving=True)

    state.followup_busy = True
    reads = len(script["position_reads"])
    _tick(state)

    assert len(script["position_reads"]) == reads
    assert state.followup_server == "MOTOR", "and it must not end the follow-up"
    print("test_an_overlapping_tick_is_dropped_rather_than_queued PASS")


def test_a_refused_move_starts_no_follow_up(page, clock):
    """Nothing moved, so there is nothing to settle.

    And a follow-up would end by overwriting the status that names the remedy
    with its own, which is the one line the engineer needs.
    """
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    script["move"] = (ErrorCodes.in_progress, {})
    ControlState.set_move_value.fn(state, "MOTOR", "x", "0.5")
    _move(state, "MOTOR", "x")

    assert state.followup_server == ""
    assert state.tick_ms == control_mod.IDLE_TICK_MS
    assert REFUSED_STATUS in state.status, state.status
    print("test_a_refused_move_starts_no_follow_up PASS")


def test_a_failed_move_starts_no_follow_up(page, clock):
    """The command may not have landed, and the coordinate is already unknown.

    Polling a server that just failed to answer would only overwrite the
    failure with a cheerier line.
    """
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    script["move"] = (ErrorCodes.unspecified, {})
    ControlState.set_move_value.fn(state, "MOTOR", "x", "0.5")
    _move(state, "MOTOR", "x")

    assert state.followup_server == ""
    assert FAILED_STATUS in state.status, state.status
    print("test_a_failed_move_starts_no_follow_up PASS")


def test_stop_settles_the_readout_too(page, clock):
    """A stop is a deceleration, not an instant halt.

    And it is the moment an engineer most needs the coordinate the stage
    actually came to rest at.
    """
    _, script = page
    script["positions"] = _positioned(moving=True)
    state = _FakeState()
    _load(state)

    _stop(state, "MOTOR")
    assert state.followup_server == "MOTOR"
    assert state.tick_ms == control_mod.FOLLOWUP_TICK_MS

    clock["t"] += FOLLOWUP_GRACE_S
    script["positions"] = _positioned(x_mm=1.2, x_counts=7678, moving=False)
    _tick(state)

    assert state.followup_server == ""
    assert _motion(state, "x")[MOTION_LABEL] == "1.200 mm / 7678 counts"
    print("test_stop_settles_the_readout_too PASS")


def test_a_failed_stop_starts_no_follow_up(page, clock):
    _, script = page
    script["positions"] = _positioned()
    state = _FakeState()
    _load(state)

    script["stop"] = (ErrorCodes.unspecified, {})
    _stop(state, "MOTOR")

    assert state.followup_server == ""
    assert FAILED_STATUS in state.status, state.status
    print("test_a_failed_stop_starts_no_follow_up PASS")


def test_a_digital_only_server_never_starts_a_follow_up(page, clock):
    """There are no coordinates to settle, so there is nothing to re-read."""
    _, script = page
    script["read"] = {"IO": {"gamry_aux": True, "Thorlab_led": False}}
    script["write"] = {"gamry_aux": False}
    state = _FakeState()
    _load(state)
    reads = len(script["position_reads"])

    _toggle(state, "IO", "gamry_aux")
    _tick(state)

    assert state.followup_server == ""
    assert state.tick_ms == control_mod.IDLE_TICK_MS
    assert len(script["position_reads"]) == reads
    print("test_a_digital_only_server_never_starts_a_follow_up PASS")


def test_the_cadence_is_the_shared_layer_s_and_not_the_page_s():
    """Two UI stacks that pick their own cadence drift, and that is the point.

    The page may convert the shared interval to the milliseconds its component
    takes; it may not choose a number.
    """
    assert control_mod.FOLLOWUP_TICK_MS == int(FOLLOWUP_INTERVAL_S * 1000)
    source = (
        REPO_ROOT / "helao" / "ui" / "reflex" / "control.py"
    ).read_text(encoding="utf-8")
    assert "should_follow_up" in source, "the page must ask the shared policy"
    # The three policy constants are imported, never restated.
    for name in ("FOLLOWUP_INTERVAL_S", "FOLLOWUP_GRACE_S", "FOLLOWUP_CEILING_S"):
        assert f"{name} =" not in source, f"{name} is redefined in the page"
    print("test_the_cadence_is_the_shared_layer_s_and_not_the_page_s PASS")


# --------------------------------------------------------------------------
# the page itself
# --------------------------------------------------------------------------


def _rendered(component) -> str:
    """Flatten a Reflex component to the text a build would compile."""
    return json.dumps(component.render(), default=str)


def test_the_page_renders_a_motion_block_per_server(page):
    text = _rendered(control_mod.control_page())

    assert "Stop" in text
    assert "Confirm move" in text, "the armed label must exist at build time"
    assert palette.REFLEX_MOTION_STOP_CLASS in text
    assert palette.REFLEX_MOTION_INPUT_CLASS in text
    print("test_the_page_renders_a_motion_block_per_server PASS")


def test_a_motion_server_with_no_axes_says_so(page):
    world = {
        "servers": {
            "MOTOR": {
                "host": "127.0.0.1",
                "port": 8003,
                "control_vis": "motion_control_letter_scale",
                "params": {},
            }
        }
    }
    control_mod.configure_control(world, "REFLEX")
    try:
        text = _rendered(control_mod.control_page())
        assert "no axes configured" in text, text
        assert "no digital outputs configured" not in text, text
    finally:
        control_mod.configure_control(WORLD, "REFLEX")
    print("test_a_motion_server_with_no_axes_says_so PASS")


def test_no_var_the_page_iterates_is_a_bare_container():
    """A bare ``list`` fails ``reflex export``, not the import.

    So it looks fine in every test until the bundle is built -- and a station
    has no Node to build it. This converts that into a pytest failure.
    """
    annotations = inspect.get_annotations(ControlState)
    assert "motion_rows" in annotations, "the motion var must be annotated at all"
    for name, annotation in annotations.items():
        assert annotation not in (list, dict, tuple, set), f"{name} is a bare container"
    assert annotations["motion_rows"] == list[list[str]]
    assert annotations["rows"] == list[list[str]]
    print("test_no_var_the_page_iterates_is_a_bare_container PASS")


def test_the_page_never_drives_itself_from_a_loop():
    """``on_unmount`` does not fire when a tab is closed.

    A ``while True`` in a background handler would go on polling a station's
    motion servers forever after the browser is gone, logging a delta to a
    disconnected client on every pass. The follow-up refresh is driven by a
    component in the page instead -- see the test below -- which is a
    *narrower* allowance than "no loops", so this stays as it was minus the
    one line that forbade the component.
    """
    source = (
        REPO_ROOT / "helao" / "ui" / "reflex" / "control.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    # The AST, not a substring sweep: the prose in this module has to be free
    # to say "while the axis is moving", and a grep for "while" cannot tell
    # that from a loop. Any ``while`` at all, not only ``while True`` -- a loop
    # over a flag the browser cannot clear is the same leak.
    loops = [node for node in ast.walk(tree) if isinstance(node, ast.While)]
    assert not loops, f"control.py has a while loop at line {loops and loops[0].lineno}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            assert not name.endswith(
                ("asyncio.sleep", "create_task", "ensure_future")
            ), f"control.py:{node.lineno} drives itself with {name}"
    print("test_the_page_never_drives_itself_from_a_loop PASS")


def test_the_refresh_is_driven_by_a_component_in_the_page():
    """A component stops existing when its tab does; a loop does not.

    Asserted on the rendered page rather than on the source, because what has
    to be true is that the tick is *in the tree* -- a handler defined and never
    mounted is the stale readout with extra state.
    """
    control_mod.configure_control(WORLD, "REFLEX")
    text = _rendered(control_mod.control_page())

    assert "Moment" in text, "no ticking component in the page"
    assert "tick_ms" in text, "the tick is not bound to the page's interval var"
    assert "follow_up" in text, "the tick drives nothing"
    print("test_the_refresh_is_driven_by_a_component_in_the_page PASS")


# --------------------------------------------------------------------------
# palette
# --------------------------------------------------------------------------


def test_the_motion_classes_exist_and_raise_on_an_unknown_key():
    assert set(palette.REFLEX_MOTION_MOVE_CLASSES) == {"ready", "armed"}
    assert palette.reflex_motion_move_class("armed") == "bg-amber-700 text-white"
    with pytest.raises(KeyError):
        palette.reflex_motion_move_class("maybe")
    print("test_the_motion_classes_exist_and_raise_on_an_unknown_key PASS")


@pytest.mark.parametrize("shade", ["sky-700", "amber-700", "red-700"])
def test_every_motion_button_clears_both_floors_on_the_control_canvas(shade):
    """Measured against ``rose-50``, not white.

    ``REFLEX_PAGE_TINTS["/control"]`` is the canvas these sit on, and a button
    that clears 3:1 against white can sit under it on a tint.
    """
    canvas = TW[palette.REFLEX_PAGE_TINTS["/control"]]
    assert contrast_ratio(WHITE, TW[shade]) >= FLOOR_BODY_TEXT
    assert contrast_ratio(TW[shade], canvas) >= FLOOR_CONTROL
    print(f"test_every_motion_button_clears_both_floors[{shade}] PASS")


def test_the_move_input_edge_holds_the_control_floor_on_both_sides():
    """It separates a white field from a tinted canvas, so it faces both."""
    canvas = TW[palette.REFLEX_PAGE_TINTS["/control"]]
    assert "border-slate-500" in palette.REFLEX_MOTION_INPUT_CLASS
    assert contrast_ratio(TW["slate-500"], WHITE) >= FLOOR_CONTROL
    assert contrast_ratio(TW["slate-500"], canvas) >= FLOOR_CONTROL
    print("test_the_move_input_edge_holds_the_control_floor_on_both_sides PASS")


def test_the_readout_is_body_text_on_both_surfaces():
    canvas = TW[palette.REFLEX_PAGE_TINTS["/control"]]
    assert "text-slate-900" in palette.REFLEX_MOTION_READOUT_CLASS
    assert contrast_ratio(TW["slate-900"], canvas) >= FLOOR_BODY_TEXT
    assert contrast_ratio(TW["slate-900"], WHITE) >= FLOOR_BODY_TEXT
    print("test_the_readout_is_body_text_on_both_surfaces PASS")


def test_the_motion_constants_carry_no_muted_slate_500():
    """``text-slate-500`` measures 4.33 on this page's canvas, under the floor.

    ``border-slate-500`` is a different role with a different floor, and is
    deliberately not caught by this.
    """
    strings = [
        palette.REFLEX_MOTION_STOP_CLASS,
        palette.REFLEX_MOTION_INPUT_CLASS,
        palette.REFLEX_MOTION_READOUT_CLASS,
        *palette.REFLEX_MOTION_MOVE_CLASSES.values(),
    ]
    assert not [s for s in strings if "text-slate-500" in s]
    print("test_the_motion_constants_carry_no_muted_slate_500 PASS")


def test_the_page_holds_no_colour_of_its_own():
    """Every colour on this page comes from ``palette``.

    The sweeper in ``test_palette.py`` enforces this across the tree; asserted
    here too because a Tailwind utility written inline is the specific way this
    page would acquire one, and it renders perfectly while being unmeasurable.
    """
    source = (
        REPO_ROOT / "helao" / "ui" / "reflex" / "control.py"
    ).read_text(encoding="utf-8")
    for offender in ("bg-", "text-slate", "text-white", "border-slate", "rgb("):
        for lineno, line in enumerate(source.splitlines(), 1):
            if offender in line:
                raise AssertionError(
                    f"control.py:{lineno} carries {offender!r}: {line}"
                )
    print("test_the_page_holds_no_colour_of_its_own PASS")
