"""Engineering-control simulator: the five private control routes, no hardware.

The ``/control`` page's whole surface is five **private** endpoints --
``get_digital_outs`` / ``set_digital_out`` on an IO server and
``get_axis_positions`` / ``move_axis`` / ``stop_motion`` on a motion server --
and until now every one of them lived only in a deployment whose drivers are
Windows-only. That left artifact row 15 ("a ``/control`` toggle drives
hardware and writes nothing") assertable only at a station, which is the same
as not assertable: a negative -- *nothing was written* -- passes trivially
against a server that was never reached.

This server exists so that claim can be **earned on Linux**. It answers all
five routes from an in-memory device, so the negative harness
(``harness/control_negative.py``) can require a *success precondition* --
error code ``none`` and an observed readback change -- before it asserts the
run tree is unchanged. A 404 or a dead server then fails the test rather than
satisfying it.

**Which routes register is decided by config, exactly as in production.** The
IO pair appears only when the server declares ``dev_do``; the motion trio only
when it declares ``axis_id``. That is not a convenience: it mirrors
``galil_io``'s ``if app.driver.dev_do:`` and ``galil_motion``'s axis gate, so a
config shape that yields no controls here yields none there either.

**Bare paths, not ``/{server_key}/...``.** That prefix is the action
namespace, and it is the entire substance of row 15: an action wrapper would
put a row in the run record for every click and queue that click behind
whatever the orchestrator is running. These routes carry ``tags=["private"]``
and are reached with ``async_private_dispatcher``, so they enter neither the
action namespace nor the queueing middleware -- and therefore write nothing.

The simulated device is deliberately *honest* rather than lenient:

* An unknown ``do_name`` is refused with ``not_available`` and an empty
  payload, as ``galil_io`` refuses it -- a control for a line the server does
  not have is a button that cannot work.
* A line configured as unreadable (scale value ``None``) reads back ``None``
  forever. Unknown is a third state and some real hardware genuinely has it:
  the NI server cannot read its outputs back at all.
* ``move_axis`` returns as soon as the move is *dispatched*, and reports
  ``counts`` only for a counts move -- an mm move reports ``None`` rather than
  a plausible-looking figure, because the conversion belongs to the driver.
"""

__all__ = ["ControlSim", "MoveModes", "makeApp", "register_control_routes"]

import time
from enum import Enum
from typing import Optional

from helao.core.error import ErrorCodes
from helao.hexagon.app.action_context import ActionContext
from helao.hexagon.app.action_host import ActionHost
from helao.ui.shared.motion_control import Units
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class MoveModes(str, Enum):
    """How ``value`` is interpreted by :func:`move_axis`.

    Declared here rather than imported: the enum a station's Galil server uses
    lives in that deployment's drivers, and the test deployment must not import
    it. The *values* match, because a simulator answering a different
    vocabulary than the thing it stands in for would prove nothing.

    Attributes:
        homing: Move toward and zero against a limit switch.
        relative: Move by an offset from the current position.
        absolute: Move to an absolute coordinate.
    """

    homing = "homing"
    relative = "relative"
    absolute = "absolute"


class ControlSim:
    """In-memory digital outputs and motion axes.

    Attributes:
        base: Hosting action server.
        dev_do: ``{do_name: port}`` from config; the keys are the lines this
            server admits. A line whose configured value is ``None`` is
            *unreadable* -- it accepts writes and always reads back unknown.
        axis_id: ``{axis: controller_letter}`` from config, the
            ``letter_scale`` schema.
        count_to_mm: ``{controller_letter: mm_per_count}`` from config.
        counts: Current coordinate per axis, in encoder counts.
        moving_until: Epoch after which an axis is no longer reported moving.
    """

    def __init__(self, action_serv: ActionHost):
        """Initialise the simulated device from the server's config block."""
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg

        self.dev_do: dict = dict(self.config_dict.get("dev_do") or {})
        self.axis_id: dict = dict(self.config_dict.get("axis_id") or {})
        self.count_to_mm: dict = dict(self.config_dict.get("count_to_mm") or {})

        # Every line starts unknown, not off. A server that has not written a
        # line since startup does not know its state -- it may be energised
        # from a previous run -- and starting the simulation at False would
        # make the tri-state untestable from the very first read.
        self.states: dict = {name: None for name in self.dev_do}
        self.counts: dict = {axis: 0 for axis in self.axis_id}
        self.moving_until: dict = {axis: 0.0 for axis in self.axis_id}

    def readable(self, do_name: str) -> bool:
        """Whether ``do_name``'s state can be read back at all."""
        return self.dev_do.get(do_name) is not None

    def get_digital_out(self, do_name: str):
        """Return one line's state, or ``None`` when it is unreadable."""
        if not self.readable(do_name):
            return None
        return self.states.get(do_name)

    def set_digital_out(self, do_name: str, on: bool):
        """Drive one line and return what it reads back afterwards."""
        self.states[do_name] = bool(on)
        return self.get_digital_out(do_name)

    def mm_of(self, axis: str) -> Optional[float]:
        """Convert an axis's counts to millimetres, or ``None`` with no scale."""
        scale = self.count_to_mm.get(self.axis_id.get(axis))
        if scale is None:
            return None
        return float(self.counts[axis]) * float(scale)

    def is_moving(self, axis: str) -> bool:
        """Whether the simulated axis is still within its move window."""
        return time.time() < self.moving_until.get(axis, 0.0)

    def start_move(self, axis: str, counts: int, mode: MoveModes) -> None:
        """Apply a move immediately and open a short 'moving' window.

        Applied at once rather than ramped: the readback contract is what is
        under test, not a motion profile. The window exists only so that
        ``moving`` is a real tri-state value and not a constant ``False``.
        """
        if mode is MoveModes.absolute:
            self.counts[axis] = int(counts)
        elif mode is MoveModes.homing:
            self.counts[axis] = 0
        else:
            self.counts[axis] = int(self.counts[axis]) + int(counts)
        self.moving_until[axis] = time.time() + 0.25

    def stop_all(self) -> list:
        """Halt every axis; return the axes the stop was issued to."""
        for axis in self.axis_id:
            self.moving_until[axis] = 0.0
        return list(self.axis_id)

    def shutdown(self):
        """No-op shutdown hook."""
        pass


def register_control_routes(app, server_key):
    """Register whichever of the five private routes ``app.driver`` supports.

    Split out of :func:`makeApp` so the registration -- which routes exist,
    under which paths, with which tags -- is testable without standing up a
    real ``BaseAPI``. That property is the one row 15 rests on and it is a
    property of *registration*, not of what a route returns: a route that
    slipped back under ``tags=["action"]``, or under the ``/{server_key}/``
    prefix, would still work and would still be wrong.

    Args:
        app: Anything with a ``post(path, tags=...)`` decorator and a
            ``driver`` attribute -- a ``BaseAPI`` in production, a recording
            stub in the tests.
        server_key: Server name in the launched config, for log lines.
    """
    if app.driver.dev_do:

        @app.post("/get_digital_outs", tags=["private"])
        async def get_digital_outs():
            """Return the state of every configured digital output.

            Returns:
                ``(error_code, {do_name: bool | None})``.
            """
            return ErrorCodes.none, {
                name: app.driver.get_digital_out(name) for name in app.driver.dev_do
            }

        @app.post("/set_digital_out", tags=["private"])
        async def set_digital_out(do_name: str = "", on: bool = False):
            """Drive one digital output without creating an action.

            Returns:
                ``(error_code, {do_name: bool | None})`` carrying the
                post-write readback, so a caller does not need a second round
                trip to learn what the line ended up at. An unknown name is
                refused with an **empty** payload -- a phantom control is worse
                than a missing one.
            """
            if do_name not in app.driver.dev_do:
                LOGGER.error(f"'{server_key}' has no digital output '{do_name}'")
                return ErrorCodes.not_available, {}
            return ErrorCodes.none, {do_name: app.driver.set_digital_out(do_name, on)}

    if app.driver.axis_id:

        @app.post("/get_axis_positions", tags=["private"])
        async def get_axis_positions():
            """Return every axis's coordinate in both millimetres and counts.

            Both halves come from one sample of the same integer, so they
            always describe the same instant.

            Returns:
                ``(error_code, {axis: {"mm": float|None, "counts": int|None,
                "moving": bool|None}})``.
            """
            return ErrorCodes.none, {
                axis: {
                    "mm": app.driver.mm_of(axis),
                    "counts": int(app.driver.counts[axis]),
                    "moving": app.driver.is_moving(axis),
                }
                for axis in app.driver.axis_id
            }

        @app.post("/move_axis", tags=["private"])
        async def move_axis(
            axis: str,
            value: float,
            mode: MoveModes = MoveModes.relative,
            units: Units = Units.mm,
            speed: Optional[int] = None,
        ):
            """Start a move on one axis without creating an action.

            ``mode`` and ``units`` are enums, not strings, for the reason the
            Galil endpoint states: a free-text ``units`` would let ``"count"``
            -- the plausible misspelling -- fall through to the millimetre
            branch and execute a 10 000-*count* move as 10 000 *millimetres*.
            FastAPI answers 422 instead.

            Returns:
                ``(error_code, {"axis", "requested", "units", "counts"})``. The
                code means **accepted and dispatched**, never "completed".
                ``counts`` is ``None`` for an mm move: the conversion happens
                in the driver and has not run yet.
            """
            if axis not in app.driver.axis_id:
                LOGGER.error(f"'{server_key}' has no axis '{axis}'")
                return ErrorCodes.not_available, {}
            if units is Units.counts:
                app.driver.start_move(axis, int(value), mode)
                counts = int(value)
            else:
                scale = app.driver.count_to_mm.get(app.driver.axis_id.get(axis))
                if scale in (None, 0):
                    LOGGER.error(f"'{server_key}' axis '{axis}' has no scale")
                    return ErrorCodes.not_available, {}
                app.driver.start_move(axis, int(value / float(scale)), mode)
                counts = None
            return ErrorCodes.none, {
                "axis": axis,
                "requested": value,
                "units": units.value,
                "counts": counts,
            }

        @app.post("/stop_motion", tags=["private"])
        async def stop_motion():
            """Halt every axis, leaving the (simulated) motors energized.

            Returns:
                ``(error_code, {"stopped": [axis, ...]})``.
            """
            return ErrorCodes.none, {"stopped": app.driver.stop_all()}


def makeApp(server_key):
    """Build the control-simulator FastAPI app.

    Args:
        server_key: Server name in the launched config.

    Returns:
        Configured :class:`HelaoFastAPI` app carrying whichever of the five
        private control routes the config asked for.
    """

    def dyn_endpoints(app=None):
        register_control_routes(app, server_key)

    # Through ``dyn_endpoints``, not inline after the constructor: ``BaseAPI``
    # builds its drivers in the *startup* event, so ``app.driver`` is still
    # ``None`` when ``makeApp`` returns. Registering inline raises
    # ``AttributeError: 'NoneType' object has no attribute 'dev_do'`` before
    # the server ever binds -- and the launcher reports that as a server that
    # simply never became ready. Same seam the shipped IO and motion servers
    # use, for the same reason.
    app = ActionHost(
        server_key=server_key,
        server_title=server_key,
        description="Engineering-control simulator",
        version=1.0,
        driver_classes=[ControlSim],
        dyn_endpoints=dyn_endpoints,
    )
    return app
