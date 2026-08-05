"""Backend-agnostic logic for the motion-axis control panels.

The engineering control panel exists in both UI stacks -- a Bokeh document and
a Reflex page -- and, as with the digital outputs beside them, the behaviour
lives here so the two cannot drift. Nothing in this module imports ``bokeh`` or
``reflex``; it knows only the config and the private endpoints. That is also
what leaves a later ``ControlSurface`` port free to wrap this module and its
digital-output sibling as one thing rather than two.

Three things are shared:

* **Which axes a station has, and how its scale is declared.** Three shipped
  config schemas differ in where the axes are listed and how the scale is keyed
  and oriented, so :func:`discover_axes` takes the schema name from the caller
  exactly as :func:`~helao.core.servers.io_control.discover_do_items` takes its
  group names. The panel module contributes only *which*, never *how*.
* **When a move is large enough to ask about.** One threshold rule, evaluated
  once, so the two stacks cannot disagree about when to confirm -- a UI that
  quietly stopped asking would look identical to one that never needed to.
* **How a command reaches the hardware.** Through the *private* ``move_axis`` /
  ``stop_motion`` / ``get_axis_positions`` endpoints, never the action twins:
  an action would write a row into the run record for every click and would
  queue behind whatever the orchestrator is running on that server.

**Unknown is a third state, never zero.** This is the digital-output panel's
tri-state invariant carried from booleans to floats, and it matters *more*
here, not less: ``False`` at least looks like a state, whereas ``0.0`` is a
perfectly legitimate motor coordinate. A failed read rendered as zero is
indistinguishable from an axis sitting at its origin, on a panel whose whole
job is telling an engineer where the instrument is. So a coordinate that was
not read renders ``"?"``, and a scale that is not configured yields ``None``
rather than a confident zero.

**The scale is computed in exactly one place.** :func:`mm_per_count` is the
only function here permitted to compute or invert a scale, because two of the
three schemas state it in opposite directions and the error is silent (see its
docstring). The drivers necessarily touch scales too; this rule is about *this*
layer, where a mistake would reach a confirmation dialog and make it stop
appearing.
"""

__all__ = [
    "UNKNOWN",
    "MmPerCount",
    "DEFAULT_WARN_ABOVE_MM",
    "ARM_TIMEOUT_S",
    "CALL_TIMEOUT",
    "READ_RETRIES",
    "WRITE_RETRIES",
    "AXIS_SOURCES",
    "REFUSED_STATUS",
    "FAILED_STATUS",
    "Units",
    "AxisItem",
    "discover_axes",
    "mm_per_count",
    "warn_threshold_mm",
    "exceeds_warn_threshold",
    "read_axis_positions",
    "move_axis",
    "stop_motion",
    "position_label",
    "outcome_status",
    "FOLLOWUP_INTERVAL_S",
    "FOLLOWUP_GRACE_S",
    "FOLLOWUP_CEILING_S",
    "should_follow_up",
]

import math
from enum import Enum
from typing import NamedTuple, NewType, Optional

from helao.core.error import ErrorCodes
from helao.helpers import helao_logging as logging
from helao.helpers.dispatcher import async_private_dispatcher

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: A coordinate that has not been read, or whose read failed. A distinct value
#: rather than ``0.0`` -- see the module docstring.
UNKNOWN = None

#: Millimetres travelled per encoder count.
#:
#: A ``NewType`` rather than a bare ``float`` so that the one function allowed
#: to compute it is the only source pyright will accept. A second computation
#: site elsewhere would have to launder its result through here to typecheck,
#: which is the point: the two orientations below are indistinguishable at a
#: glance and wrong by scale-squared.
MmPerCount = NewType("MmPerCount", float)

#: Displacement above which a move asks for a second click, when the config
#: names no threshold of its own. Chosen to clear the tightest shipped
#: ``move_limit_mm`` (measured: 3.0 and 5.0 at the two stations that declare
#: one), so the driver's own hard reject still fires first where it exists,
#: while sitting well below a full-plate traverse.
DEFAULT_WARN_ABOVE_MM = 10.0

#: Seconds a granted confirmation stays valid. An arm that outlived the
#: attention it was granted under is a confirmation for a move nobody is
#: watching.
ARM_TIMEOUT_S = 30

#: Seconds a panel will wait on one call, and how many times it will try.
#:
#: Far below the dispatcher's defaults (60s, 5 retries), and that is the point.
#: These calls run on the Bokeh document's callback, so a server that is down
#: or answering 404 does not merely delay the read -- it holds the document
#: while it retries, and the page renders *blank* until it gives up. One short
#: attempt fails fast into the honest "could not read" state instead.
#:
#: A command is worth one extra retry because a dropped write is worse than a
#: slow one, but the ceiling stays low for the same reason.
CALL_TIMEOUT = 5
READ_RETRIES = 1
WRITE_RETRIES = 2

#: The config schemas :func:`discover_axes` and :func:`mm_per_count` know how
#: to read. Named for the shape of the config rather than for a driver or a
#: vendor: two of the three are the same vendor, so the vendor does not
#: discriminate and the schema does.
AXIS_SOURCES = ("letter_scale", "name_scale", "inverse_scale")

#: What a panel says when the server refused the command because a sequence is
#: running. Refused is a *fourth* outcome, not a flavour of failed: a generic
#: red failure on a panel whose purpose is reporting what the instrument is
#: doing leads an engineer to conclude the panel is broken. The wording names
#: the remedy, not just the cause.
REFUSED_STATUS = "a sequence is running -- press Stop first"

#: What a panel says when the command did not land for any other reason. The
#: axis's readout goes unknown alongside it: the move may or may not have
#: started, and guessing either way would misreport the instrument.
FAILED_STATUS = "command failed"


class Units(str, Enum):
    """The unit a typed move value is expressed in.

    Defined here rather than beside any one driver so that this layer, both UI
    stacks and all three endpoints share one enum. A plain ``str`` would let
    ``"count"`` -- the plausible misspelling -- fall through to the millimetre
    branch, executing a 10 000-*count* move as 10 000 *millimetres*. As an enum
    the endpoint answers 422 instead.

    Attributes:
        mm: Millimetres. The default everywhere.
        counts: Raw encoder counts, dispatched to the driver undivided.
    """

    mm = "mm"
    counts = "counts"


class AxisItem(NamedTuple):
    """One movable axis, as the config declares it.

    Attributes:
        server_key: Config key of the action server that owns the axis.
        axis: The axis name, and the ``axis`` the private endpoints take.
        family: The config schema this axis was discovered from -- one of
            :data:`AXIS_SOURCES`. Named for the family rather than the schema
            because the schema is what stands in for a family at this layer:
            the vendor does not discriminate (two schemas are one vendor) while
            the schema does.
        mm_per_count: Millimetres per encoder count, or ``None`` when the
            config declares no scale for this axis. ``None`` is what disables
            the move control -- see :attr:`move_enabled`.
        warn_above_mm: Displacement above which a move asks for confirmation.
        has_counts: Whether the axis can report raw counts. True for all three
            shipped schemas; the field exists so a family that can only report
            millimetres could say so without the readout inventing an integer.
    """

    server_key: str
    axis: str
    family: str
    mm_per_count: Optional[MmPerCount]
    warn_above_mm: float
    has_counts: bool

    @property
    def move_enabled(self) -> bool:
        """Whether this axis gets a working move control.

        An axis with no configured scale has no millimetre/count relation, and
        the warn threshold is a millimetre quantity, so there is nothing to
        evaluate a large move against. Saying so **once**, statically, beside a
        disabled control is the honest answer. The alternative -- leaving the
        control live and warning on every move because the threshold cannot be
        evaluated -- trains an operator to dismiss the dialog, and they then
        dismiss it on the axes where it matters.

        No shipped config reaches this state; it is a robustness path.
        """
        return self.mm_per_count is not None


def discover_axes(server_config: dict, axis_source, *, server_key: str = "") -> list:
    """Enumerate a server's movable axes from its config.

    Positionally this mirrors
    :func:`~helao.core.servers.io_control.discover_do_items` exactly --
    ``(server_config, selector)`` -- so the two discovery functions are one
    contract and a later port wraps one pattern rather than two. The schema is
    passed in, **not** sniffed from the config: two of the three schemas key
    their scale by name and could be told apart only by guessing, and a wrong
    guess is silent.

    Args:
        server_config: The server's entry in the world config (the block with
            ``host``, ``port`` and ``params``).
        axis_source: One of :data:`AXIS_SOURCES`, from the panel module's
            ``AXIS_SOURCE``.

            * ``"letter_scale"`` -- ``params.axis_id`` maps axis name to a
              controller letter; ``count_to_mm`` is keyed by that letter.
            * ``"name_scale"`` -- ``params.axis_id`` maps axis name to a serial
              number; ``count_to_mm`` is keyed by the axis name.
            * ``"inverse_scale"`` -- ``params.axes`` maps axis name to a block
              carrying ``pos_scale``, which is the *reciprocal*.
        server_key: Config key of the owning server, for the returned items.
            Keyword-only and defaulted so that the positional shape stays
            identical to ``discover_do_items``; the config block does not carry
            its own key, so only the caller iterating ``servers`` knows it.

    Returns:
        list[AxisItem]: Every configured axis, in config order. Empty when the
        server declares none -- which a panel should render as an explicit "no
        axes configured" rather than as a blank box -- and empty for an
        unrecognised ``axis_source``, which is logged rather than guessed at.
    """
    params = server_config.get("params") or {}
    if axis_source in ("letter_scale", "name_scale"):
        names = list(params.get("axis_id") or {})
    elif axis_source == "inverse_scale":
        names = list(params.get("axes") or {})
    else:
        # Say why and skip, rather than falling back to a schema that might be
        # the right shape by coincidence and the wrong one by a factor of the
        # scale squared.
        LOGGER.error(
            f"unknown axis_source '{axis_source}' for '{server_key}'; expected "
            f"one of {AXIS_SOURCES}. No motion controls for this server."
        )
        return []
    return [
        AxisItem(
            server_key=server_key,
            axis=name,
            family=axis_source,
            mm_per_count=mm_per_count(server_config, name, axis_source),
            warn_above_mm=warn_threshold_mm(server_config, name, axis_source),
            has_counts=True,
        )
        for name in names
    ]


def mm_per_count(server_config: dict, axis: str, axis_source) -> Optional[MmPerCount]:
    """Return millimetres per encoder count for one axis.

    **The only scale accessor in this layer, deliberately.** The three schemas
    state the scale in two opposite orientations:

    * ``count_to_mm`` is **millimetres per count** -- e.g. ``1.5628e-04``.
    * ``pos_scale`` is **counts per millimetre** -- e.g. ``1228800.0``.

    They are reciprocals, and both are plain positive floats, so an inversion
    dropped or wrongly added produces a number that looks entirely ordinary and
    is wrong by the square of the scale. Every caller therefore goes through
    here rather than reading either key.

    ``count_to_mm`` is a **misnomer** -- it is a multiplier, not a converter,
    and it reads as though it went the other way. It is the key thirty shipped
    station configs and two drivers already use, so it must **not** be renamed;
    this docstring exists in place of the rename.

    Args:
        server_config: The server's entry in the world config.
        axis: The axis name as the config declares it.
        axis_source: One of :data:`AXIS_SOURCES`. See :func:`discover_axes`.

    Returns:
        Optional[MmPerCount]: The scale, or ``None`` when the config declares
        none for this axis, when the schema is unrecognised, or when the value
        is zero, negative or non-finite. ``None``, never ``0.0``: a zero scale
        would render every coordinate as ``0.000 mm`` with total confidence.
    """
    params = server_config.get("params") or {}
    if axis_source == "letter_scale":
        letter = (params.get("axis_id") or {}).get(axis)
        if letter is None:
            return None
        raw = (params.get("count_to_mm") or {}).get(letter)
    elif axis_source == "name_scale":
        raw = (params.get("count_to_mm") or {}).get(axis)
    elif axis_source == "inverse_scale":
        block = (params.get("axes") or {}).get(axis) or {}
        counts_per_mm = block.get("pos_scale")
        try:
            counts_per_mm = float(counts_per_mm)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        if not math.isfinite(counts_per_mm) or counts_per_mm == 0.0:
            # Guarded rather than divided: a missing or zero pos_scale is a
            # config that does not state a scale, not one that states an
            # infinite one.
            return None
        raw = 1.0 / counts_per_mm
    else:
        LOGGER.error(
            f"unknown axis_source '{axis_source}'; expected one of {AXIS_SOURCES}"
        )
        return None
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0.0:
        return None
    return MmPerCount(value)


def warn_threshold_mm(server_config: dict, axis: str, axis_source) -> float:
    """Return the displacement in millimetres above which a move is confirmed.

    Resolved in order, first match wins:

    1. ``params.warn_above_mm[axis]`` -- a per-axis override a station can add
       without touching code.
    2. ``params.axes[axis].move_limit_mm`` -- the limit the reciprocal schema
       already declares. Reused rather than duplicated, so a station that has
       already stated how far that axis may travel does not state it twice.
    3. :data:`DEFAULT_WARN_ABOVE_MM`.

    Args:
        server_config: The server's entry in the world config.
        axis: The axis name as the config declares it.
        axis_source: One of :data:`AXIS_SOURCES`; an unrecognised value is
            logged and falls through to the default rather than silently
            reading keys from a schema this server does not use.

    Returns:
        float: The threshold. Always positive and finite -- a config value that
        is neither is ignored in favour of the default, since a threshold of
        zero would confirm every move and one of infinity would confirm none.
    """
    if axis_source not in AXIS_SOURCES:
        LOGGER.error(
            f"unknown axis_source '{axis_source}'; expected one of {AXIS_SOURCES}"
        )
        return DEFAULT_WARN_ABOVE_MM
    params = server_config.get("params") or {}
    override = (params.get("warn_above_mm") or {}).get(axis)
    limit = ((params.get("axes") or {}).get(axis) or {}).get("move_limit_mm")
    for candidate in (override, limit):
        try:
            value = float(candidate)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0.0:
            return value
    return DEFAULT_WARN_ABOVE_MM


def exceeds_warn_threshold(
    item: AxisItem,
    value: float,
    units: Units,
    current_mm: Optional[float] = UNKNOWN,
    mode=None,
) -> bool:
    """Whether this move is large enough to require a second click.

    In **relative** mode the entered value *is* the displacement. In
    **absolute** mode it is not: an absolute 25.0 from a current 24.9 is a
    0.1 mm move, so the comparison is against ``abs(target - current)``.
    Comparing the entered coordinate there would confirm nearly every absolute
    move and teach an operator to click through the dialog.

    **Fail closed when the answer is unevaluable *and the condition will
    pass*.** An absolute move whose current coordinate has not been read, and a
    non-finite entry, both warn -- each clears on the next read or the next
    keystroke, so a dialog is proportionate and cannot become permanent noise.
    The one *permanent* unevaluable case, an axis with no configured scale, is
    resolved at discovery instead (:attr:`AxisItem.move_enabled`) precisely so
    that it raises no recurring dialog.

    Args:
        item: The axis, carrying its scale and threshold. Typed rather than
            taking a bare ``float`` scale so that pyright rejects a scale
            computed anywhere but :func:`mm_per_count`.
        value: The value as typed.
        units: The unit ``value`` is in.
        current_mm: The axis's last-read coordinate in millimetres, or
            :data:`UNKNOWN`. Only consulted in absolute mode.
        mode: The move mode. Compared by value against ``"absolute"``, so the
            existing ``MoveModes`` string-enum satisfies it without this layer
            importing a deployment's module; anything else is treated as a
            relative displacement.

    Returns:
        bool: True when a confirmation should be required. Never a rejection --
        confirming is the only consequence, and a confirmed move executes.
    """
    try:
        entered = float(value)
    except (TypeError, ValueError):
        entered = math.nan
    if not math.isfinite(entered):
        # Transient: the next keystroke resolves it.
        return True

    if units == Units.counts:
        if item.mm_per_count is None:
            # Unreachable through a correctly built panel: an axis with no
            # scale has no enabled move control (P3). Reaching here means a
            # caller bypassed that, so a move is about to go out unguarded --
            # report the bug and require the click.
            LOGGER.error(
                f"'{item.server_key}' axis '{item.axis}' has no configured "
                f"scale but a counts move reached the threshold check; the "
                f"control for it should be disabled"
            )
            return True
        entered_mm = entered * float(item.mm_per_count)
    else:
        entered_mm = entered

    if mode is not None and str(getattr(mode, "value", mode)) == "absolute":
        if current_mm is UNKNOWN:
            # Transient: the next read resolves it.
            return True
        try:
            current = float(current_mm)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return True
        if not math.isfinite(current):
            return True
        displacement = abs(entered_mm - current)
    else:
        displacement = abs(entered_mm)

    if displacement > item.warn_above_mm:
        # Logged so a station's log records that a large move was consciously
        # confirmed, rather than only that a move happened.
        LOGGER.warning(
            f"'{item.server_key}' axis '{item.axis}': {displacement:.3f} mm "
            f"exceeds the {item.warn_above_mm:.3f} mm warn threshold"
        )
        return True
    return False


async def read_axis_positions(server_key: str, host: str, port: int) -> dict:
    """Read every axis's coordinate on a server, once.

    Called at panel open, after every command, and on demand -- never on a
    timer. These are engineering controls, not a data stream, and polling every
    station's motion servers forever to catch a move almost nobody makes is not
    worth the traffic. A panel therefore shows truth at open plus whatever it
    has commanded since.

    Args:
        server_key: Config key of the action server, for logging.
        host: Its host.
        port: Its HTTP port.

    Returns:
        dict: ``{axis: {"mm": float|None, "counts": int|None,
        "moving": bool|None}}``. Empty on a failed call, which leaves every
        readout unknown rather than inventing coordinates.
    """
    try:
        response, error_code = await async_private_dispatcher(
            server_key=server_key,
            host=host,
            port=port,
            private_action="get_axis_positions",
            timeout=CALL_TIMEOUT,
            retries=READ_RETRIES,
        )
    except Exception:
        LOGGER.error(f"'{server_key}' get_axis_positions failed", exc_info=True)
        return {}
    if error_code != ErrorCodes.none:
        # Discard the body, do not parse it. An HTTP error still carries a
        # JSON dict -- a 404 from a server without the endpoint replies
        # ``{"detail": "Not Found"}`` -- and parsing that yields a phantom
        # control named "detail" reading ON. Measured, not hypothetical.
        LOGGER.error(f"'{server_key}' get_axis_positions -> {error_code}")
        return {}
    return _as_axis_dict(response)


async def move_axis(
    server_key: str,
    host: str,
    port: int,
    axis: str,
    value: float,
    mode=None,
    units: Units = Units.mm,
    speed: Optional[int] = None,
) -> tuple:
    """Command one axis and report how the server answered.

    The value is dispatched **exactly as typed**. Nothing here converts it: the
    unit is carried alongside as a discriminator and the conversion -- or the
    deliberate absence of one -- happens inside the driver, where the encoder
    lives. That is what keeps this module's blast radius the confirmation
    dialog rather than the stage.

    Args:
        server_key: Config key of the action server, for logging.
        host: Its host.
        port: Its HTTP port.
        axis: The axis to move.
        value: The move value, as typed, in ``units``.
        mode: The move mode; passed through by value.
        units: The unit ``value`` is in.
        speed: Optional speed override; omitted from the call when ``None`` so
            the server keeps its configured default.

    Returns:
        tuple[ErrorCodes, dict]: The server's code and payload. The code is
        returned rather than swallowed because *refused* and *failed* are
        different outcomes a panel must show differently -- see
        :func:`outcome_status`.
    """
    params_dict = {
        "axis": str(getattr(axis, "value", axis)),
        "value": float(value),
        "units": str(getattr(units, "value", units)),
    }
    if mode is not None:
        params_dict["mode"] = str(getattr(mode, "value", mode))
    if speed is not None:
        params_dict["speed"] = int(speed)
    try:
        response, error_code = await async_private_dispatcher(
            server_key=server_key,
            host=host,
            port=port,
            private_action="move_axis",
            params_dict=params_dict,
            timeout=CALL_TIMEOUT,
            retries=WRITE_RETRIES,
        )
    except Exception:
        LOGGER.error(f"'{server_key}' move_axis({axis}) failed", exc_info=True)
        return ErrorCodes.unspecified, {}
    if error_code != ErrorCodes.none:
        LOGGER.error(f"'{server_key}' move_axis({axis}) -> {error_code}")
        return error_code, {}
    return error_code, _as_payload(response)


async def stop_motion(server_key: str, host: str, port: int) -> tuple:
    """Halt every axis on a server, leaving the motors energized.

    Stopping is deliberately unconditional: an escape hatch for a stage heading
    somewhere it should not go must not depend on the orchestrator being
    responsive. The consequence is stated rather than hidden -- a sequence
    mid-move is **not** notified, so it observes motion has ceased and
    completes normally, and the run record then describes a move that did not
    go where it says it did.

    Args:
        server_key: Config key of the action server, for logging.
        host: Its host.
        port: Its HTTP port.

    Returns:
        tuple[ErrorCodes, dict]: The server's code and payload, typically
        ``{"stopped": [axis, ...]}``.
    """
    try:
        response, error_code = await async_private_dispatcher(
            server_key=server_key,
            host=host,
            port=port,
            private_action="stop_motion",
            timeout=CALL_TIMEOUT,
            retries=WRITE_RETRIES,
        )
    except Exception:
        LOGGER.error(f"'{server_key}' stop_motion failed", exc_info=True)
        return ErrorCodes.unspecified, {}
    if error_code != ErrorCodes.none:
        LOGGER.error(f"'{server_key}' stop_motion -> {error_code}")
        return error_code, {}
    return error_code, _as_payload(response)


def position_label(mm: Optional[float], counts: Optional[int]) -> str:
    """Return the dual-unit readout for one axis.

    Both halves always render, and either may be unknown independently: a
    configured axis with no scale reports counts and no millimetres, while a
    server that could not be reached reports neither.

    Shared so the two stacks cannot disagree about what unknown looks like, and
    formatted so that unknown can never be mistaken for the origin.

    Args:
        mm: The coordinate in millimetres, or :data:`UNKNOWN`.
        counts: The coordinate in encoder counts, or :data:`UNKNOWN`.

    Returns:
        str: e.g. ``"12.345 mm / 78321 counts"``, ``"? mm / 78321 counts"``, or
        ``"? mm / ? counts"``. Never ``"0.000 mm"`` for an unknown value --
        zero is a real coordinate, so a failed read shown as zero would be
        indistinguishable from an axis at its origin.
    """
    return f"{_mm_text(mm)} mm / {_counts_text(counts)} counts"


def outcome_status(error_code) -> str:
    """Return the status line for how a command was answered.

    Three outcomes, not two. A command refused because a sequence is running is
    **not** a failure: nothing is broken, the panel is working, and the remedy
    is specific. Collapsing it into a generic failure leads an engineer to
    conclude the panel itself is broken -- the same reasoning that makes an
    unread digital output render as unknown rather than off.

    Args:
        error_code: The code returned by :func:`move_axis` or
            :func:`stop_motion`.

    Returns:
        str: Empty on success, :data:`REFUSED_STATUS` when the server refused
        because it is busy, :data:`FAILED_STATUS` otherwise.
    """
    if error_code == ErrorCodes.none:
        return ""
    if error_code == ErrorCodes.in_progress:
        return REFUSED_STATUS
    return FAILED_STATUS


def _mm_text(mm: Optional[float]) -> str:
    """Render the millimetre half of a readout, or ``"?"``."""
    if mm is UNKNOWN:
        return "?"
    try:
        value = float(mm)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "?"
    if not math.isfinite(value):
        return "?"
    return f"{value:.3f}"


#: How often to re-read while an axis is still moving.
#:
#: One second, not a fraction of one: the follow-up shares the controller's
#: command channel with the move it is watching -- the Galil driver's own wait
#: loop polls the same connection -- so a tighter cadence buys nothing but
#: contention. A readout that settles within a second of the stage stopping is
#: indistinguishable from instant to an operator.
FOLLOWUP_INTERVAL_S = 1.0

#: How long to keep re-reading *regardless* of what ``moving`` says.
#:
#: A move command returns once the motion has been *dispatched*, which for a
#: fire-and-forget driver is before the stage has begun to move. Reading
#: immediately afterwards can therefore answer ``moving: False`` -- not because
#: the move finished, but because it had not started. A policy of "re-read
#: while moving" would see that first answer, conclude the move was over, and
#: leave the pre-move coordinate on screen: exactly the stale readout this
#: follow-up exists to fix. The grace window covers the gap between dispatch
#: and motion.
FOLLOWUP_GRACE_S = 2.0

#: When to give up, whatever ``moving`` still says.
#:
#: An axis that reports ``moving`` forever -- stuck, or a driver whose flag
#: never clears -- must not be followed forever. On the Reflex side especially:
#: an unbounded refresh is the failure mode the "never drive a refresh from a
#: server-side loop" rule exists to prevent, because ``on_unmount`` does not
#: fire on tab close. Bounded means it always stops on its own, and the Read
#: button remains for anything past the ceiling.
#:
#: **Derived from the driver, not chosen.** The Galil driver waits for its own
#: moves up to a hard 30-minute cap (``tmax`` in ``_motor_move``), so a move it
#: has itself given up on cannot still be running: 30 minutes is the longest a
#: legitimate move can last, and therefore the earliest this may stop without
#: abandoning real motion.
#:
#: An earlier value of 120 s was reasoned about rather than derived, and was
#: **wrong at a real station**: eche10's x-axis travels 1.562 mm/s at its
#: configured default speed, so any move past ~187 mm outlives 120 s. The
#: follow-up quit mid-travel and the readout never settled -- the exact bug the
#: follow-up exists to fix, reintroduced by an invented number. Derive limits
#: like this from the hardware's own bounds.
FOLLOWUP_CEILING_S = 30.0 * 60.0


def should_follow_up(positions: dict, elapsed_s: float) -> bool:
    """Whether to re-read positions again after ``elapsed_s`` of following up.

    Shared by both UI stacks so the refresh cadence cannot drift between them.

    Args:
        positions: The most recent :func:`read_axis_positions` payload.
        elapsed_s: Seconds since the follow-up began (i.e. since dispatch).

    Returns:
        bool: ``True`` while the grace window is open or some axis still
        reports motion, ``False`` once the ceiling is reached.

    Note:
        ``moving`` is tri-state. Only an explicit ``True`` sustains the
        follow-up past the grace window -- ``None`` means the driver could not
        say, and treating "don't know" as "still moving" would poll a silent
        server until the ceiling on every move.
    """
    still_moving = any(
        (axis or {}).get("moving") is True
        for axis in (positions or {}).values()
        if isinstance(axis, dict)
    )
    if elapsed_s >= FOLLOWUP_CEILING_S:
        if still_moving:
            # Abandoning motion that is still running, so the readout will not
            # settle on its own and the operator must press Read. Says so out
            # loud: the previous ceiling was too low for a real move and the
            # only symptom was a stale number, which is not a diagnosable
            # report. If this line appears, the ceiling is wrong again -- or an
            # axis is genuinely stuck, which is worth a look either way.
            LOGGER.warning(
                "motion follow-up hit its %.0fs ceiling while an axis still "
                "reported motion; the readout will not settle on its own",
                FOLLOWUP_CEILING_S,
            )
        return False
    if elapsed_s < FOLLOWUP_GRACE_S:
        return True
    return still_moving


def _counts_text(counts: Optional[int]) -> str:
    """Render the counts half of a readout, or ``"?"``."""
    if counts is UNKNOWN:
        return "?"
    try:
        return str(int(counts))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return "?"


def _as_payload(response):
    """Unwrap a private-endpoint reply to its payload.

    The dispatcher hands back whatever the endpoint returned, and the two
    transports it can use do not agree on shape: the RPC fast path preserves
    the ``(error_code, payload)`` tuple, while the HTTP fallback JSON-decodes
    it to a two-element list. Both arrive here, so both are unwrapped.

    Args:
        response: The dispatcher's first return value.

    Returns:
        The payload half, or ``{}`` when nothing dict-shaped was found.
    """
    if isinstance(response, (list, tuple)) and len(response) == 2:
        response = response[1]
    return response if isinstance(response, dict) else {}


def _as_axis_dict(response) -> dict:
    """Normalise a position reply to ``{axis: {mm, counts, moving}}``.

    Every field is coerced independently and to ``None`` on anything
    unexpected, so a partial or malformed reply degrades to unknown rather than
    to a plausible-looking number. An axis whose value is not a dict at all is
    dropped entirely -- which is the second line of defence against an error
    body such as ``{"detail": "Not Found"}`` reaching the readout as an axis
    named "detail".

    Args:
        response: The dispatcher's first return value.

    Returns:
        dict: Positions keyed by axis; empty if nothing dict-shaped was found.
    """
    payload = _as_payload(response)
    normalised = {}
    for axis, values in payload.items():
        if not isinstance(values, dict):
            continue
        normalised[str(axis)] = {
            "mm": _as_float_or_none(values.get("mm")),
            "counts": _as_int_or_none(values.get("counts")),
            "moving": _as_bool_or_none(values.get("moving")),
        }
    return normalised


def _as_float_or_none(value) -> Optional[float]:
    """Coerce a reported millimetre coordinate, or ``None``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_int_or_none(value) -> Optional[int]:
    """Coerce a reported count, or ``None``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _as_bool_or_none(value) -> Optional[bool]:
    """Coerce a reported moving flag, or ``None``.

    ``None`` survives as unknown: a server that does not report whether an axis
    is moving has not reported that it is stationary.
    """
    return None if value is None else bool(value)
