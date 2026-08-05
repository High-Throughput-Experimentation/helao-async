"""FastAPI action server for Thorlabs Kinesis motorised stages.

Defines :class:`KinesisMotorExec` to drive a single axis from a HELAO action
and registers move / cancel / velocity endpoints for every axis declared
under ``server_params['axes']``.
"""

__all__ = ["makeApp"]

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
import asyncio
import time
from typing import Optional

from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.core.servers.base_api import BaseAPI
from helao.core.servers.motion_control import Units
from helao.helpers.executor import Executor

from ...drivers.motion.kinesis_driver import (
    MOTION_STATES,
    KinesisMotor,
    KinesisPoller,
    MoveModes,
)


def _running_actions(app: BaseAPI) -> list:
    """Names of this server's endpoints that currently have a running action.

    Whether an action is running is knowable only server-side, from the
    ``Base`` object no shared module holds, so this check cannot live beside
    the rest of the panel logic in ``motion_control.py`` -- only the
    *rendering* of a refusal does. Same sweep the queueing middleware performs
    in ``base_api.py``, without its single-endpoint narrowing: a panel command
    for the stage cares that the server is moving something, not which route
    was asked to move it.
    """
    return [
        ep for ep, em in app.base.actionservermodel.endpoints.items() if em.active_dict
    ]


class KinesisMotorExec(Executor):
    """Executor that drives a single Kinesis axis for a move action.

    Reads the target axis and movement parameters from the action and
    delegates motion to :class:`KinesisMotor` via the configured driver.

    Attributes:
        base: The server's :class:`Base` instance.
        driver: The :class:`KinesisMotor` driver bound to this server.
        live_dict: Reference to the poller's shared live-data dict.
        action_params: Action parameters dict shortcut.
        axis_name: Resolved axis identifier.
        axis_params: Per-axis configuration entry from ``server_params``.
    """

    def __init__(self, *args, **kwargs):
        """Resolve axis configuration and cache driver/buffer shortcuts.

        Args:
            *args: Forwarded to :class:`Executor`.
            **kwargs: Forwarded to :class:`Executor`.
        """
        super().__init__(*args, **kwargs)
        # shortcut attribs
        self.base = self.active.base
        self.driver = self.base.app.driver
        self.live_dict = self.base.app.poller.live_dict

        # action params and axis config
        self.action_params = self.active.action.action_params
        self.axis_name = self.action_params["axis"]
        if not isinstance(self.axis_name, str):
            self.axis_name = self.axis_name.value
        self.axis_params = self.base.server_params["axes"][self.axis_name]
        LOGGER.info("KinesisMotorExec initialized.")

    async def _pre_exec(self) -> dict:
        """Configure velocity and acceleration on the axis before motion.

        Returns:
            Dict containing ``error`` set to :attr:`ErrorCodes.none` on a
            successful driver setup or :attr:`ErrorCodes.setup` otherwise.
        """
        LOGGER.info("KinesisMotorExec running setup methods.")
        velocity = self.action_params.get("velocity_mm_s", None)
        acceleration = self.action_params.get("acceleration_mm_s2", None)
        LOGGER.info("KinesisMotorExec checking velocity and accel.")
        resp = self.driver.setup(
            axis=self.axis_name, velocity=velocity, acceleration=acceleration
        )
        error = ErrorCodes.none if resp.response == "success" else ErrorCodes.setup
        LOGGER.info("KinesisMotorExec setup complete.")
        return {"error": error}

    async def _exec(self) -> dict:
        """Compute the target position and start the move.

        Resolves an absolute target using the relative/absolute move mode,
        compares against the per-axis ``move_limit_mm`` from configuration,
        and dispatches the move through the driver when within limits.

        Returns:
            Dict with ``error`` indicating success, motor-limit refusal, or
            a critical motor error.
        """
        LOGGER.info("KinesisMotorExec validating move mode & limit.")
        move_mode = self.action_params.get("move_mode", "relative")
        move_value = self.action_params.get("value_mm", 0.0)
        current_position = self.live_dict[self.axis_name].get("position_mm", 9999)
        target_position = move_value
        if move_mode == MoveModes.relative:
            target_position += current_position

        self.start_time = time.time()
        if target_position < self.axis_params.get("move_limit_mm", 3.0):
            LOGGER.info("KinesisMotorExec starting motion.")
            resp = self.driver.move(self.axis_name, move_mode, move_value)
            error = (
                ErrorCodes.none
                if resp.response == "success"
                else ErrorCodes.critical_error
            )
            return {"error": error}
        else:
            LOGGER.info(
                f"final position {target_position} is greater than motion limit, ignoring motion request."
            )
            return {"error": ErrorCodes.motor}

    async def _poll(self) -> dict:
        """Sample position and motion status from the poller live buffer.

        Returns:
            Dict containing the current ``position_mm`` and an :class:`HloStatus`
            of ``active`` while motion states are present, ``finished`` otherwise.
        """
        live_dict, epoch_s = self.base.get_lbuf(self.axis_name)
        live_dict["epoch_s"] = epoch_s
        if any([x in MOTION_STATES for x in live_dict["status"]]):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.01)
        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": {"position_mm": live_dict["position_mm"]},
        }

    async def _manual_stop(self) -> dict:
        """Immediately stop the axis on a user-issued cancel.

        Returns:
            Dict containing ``error`` set to :attr:`ErrorCodes.none`.
        """
        self.driver.stop(self.axis_name)
        return {"error": ErrorCodes.none}


async def kinesis_dyn_endpoints(app: BaseAPI):
    """Register Kinesis motion endpoints after driver initialisation.

    Reads the configured axes from ``server_params['axes']`` and, if any are
    present, attaches ``kmove``, ``cancel_kmove``, ``set_velocity``, and the
    private polling control endpoints.

    Args:
        app: The :class:`BaseAPI` instance being configured.
    """
    server_key = app.base.server.server_name
    motors = list(app.base.server_params["axes"].keys())

    if motors:

        @app.post(f"/{server_key}/kmove", tags=["action"])
        async def kmove(
            axis: app.driver.dev_kinesis = motors[0],
            move_mode: MoveModes = "relative",
            value_mm: float = 0.0,
            velocity_mm_s: Optional[float] = None,
            acceleration_mm_s2: Optional[float] = None,
            poll_rate_s: float = 0.1,
            exec_id: Optional[str] = None,
        ):
            """Start a :class:`KinesisMotorExec` to move the selected axis.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                axis: Axis identifier from the driver's enumerated devices.
                move_mode: Relative or absolute interpretation of ``value_mm``.
                value_mm: Move magnitude or absolute target in millimetres.
                velocity_mm_s: Optional override for axis velocity.
                acceleration_mm_s2: Optional override for axis acceleration.
                poll_rate_s: Executor polling period in seconds.
                exec_id: Optional executor id (used by the cancel endpoint).

            Returns:
                The active action dictionary from ``start_executor``.
            """
            active = await app.base.setup_and_contain_action()
            active.action.action_abbr = "kmove"
            executor = KinesisMotorExec(
                active=active,
                oneoff=False,
                poll_rate=active.action.action_params["poll_rate_s"],
            )
            active_action_dict = active.start_executor(executor)
            return active_action_dict

        @app.post(f"/{server_key}/cancel_kmove", tags=["action"])
        async def cancel_kmove(
            axis: app.driver.dev_kinesis = motors[0],
            exec_id: Optional[str] = None,
        ):
            """Cancel a running ``kmove`` executor by id or by axis.

            If ``exec_id`` is provided the matching executor is stopped;
            otherwise every ``kmove`` executor matching the optional axis
            filter is stopped.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                axis: Optional axis filter when ``exec_id`` is not given.
                exec_id: Optional executor identifier to stop directly.

            Returns:
                The finished action dictionary.
            """
            active = await app.base.setup_and_contain_action()
            if active.action.action_params["exec_id"] is not None:
                app.base.stop_executor(active.action.action_params["exec_id"])
            else:
                if active.action.action_params["axis"] is None:
                    dev_dict = {}
                else:
                    dev_dict = {"axis": active.action.action_params["axis"]}
                app.base.stop_all_executor_prefix("kmove", dev_dict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/set_velocity", tags=["action"])
        async def set_velocity(
            axis: app.driver.dev_kinesis = motors[0],
            velocity_mm_s: Optional[float] = None,
            acceleration_mm_s2: Optional[float] = None,
        ):
            """Apply velocity and acceleration parameters to the chosen axis.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                axis: Axis identifier from the driver's enumerated devices.
                velocity_mm_s: Maximum velocity in mm/s.
                acceleration_mm_s2: Acceleration in mm/s^2.

            Returns:
                The finished action dictionary.
            """
            active = await app.base.setup_and_contain_action(action_abbr="set_velocity")
            app.driver.motors[
                active.action.action_params["axis"]
            ].set_velocity_parameters(
                acceleration=active.action.action_params["acceleration_mm_s2"],
                max_velocity=active.action.action_params["velocity_mm_s"],
            )
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post("/start_polling", tags=["private"])
        async def start_polling() -> str:
            """Start the Kinesis poller background loop."""
            await app.poller.start_polling()
            return "start_polling: ok"

        @app.post("/stop_polling", tags=["private"])
        async def stop_polling() -> str:
            """Stop the Kinesis poller background loop."""
            await app.poller.stop_polling()
            return "stop_polling: ok"

        # Private motion controls for the engineering control panel. Same
        # driver calls as the action routes above, no action wrapper: a panel
        # click is a manual intervention, not a step of an experiment, and
        # routing it through the action machinery would put a row in the run
        # record for every click and queue that click behind whatever the
        # orchestrator is running on this server.
        #
        # Bare paths, not ``/{server_key}/...``: that prefix is the action
        # namespace. Reached with ``async_private_dispatcher``.
        #
        # These three return ``(error_code, payload)`` tuples, unlike the two
        # polling routes directly above, which return a bare string. The tuple
        # is the convention the panel's shared layer unwraps; a copied bare
        # string would leave every readout permanently unknown.
        #
        # ``mode`` and ``units`` are enums rather than strings on purpose. A
        # free-text ``units`` would let ``"count"`` -- the plausible
        # misspelling -- fall through to the millimetre branch and execute a
        # 10 000-*count* move as 10 000 *millimetres*. FastAPI answers 422
        # instead. ``axis`` and ``value`` are required for the same reason: a
        # defaulted axis moves something nobody named.

        @app.post("/move_axis", tags=["private"])
        async def move_axis(
            axis: app.driver.dev_kinesis,
            value: float,
            mode: MoveModes = MoveModes.relative,
            units: Units = Units.mm,
            speed: Optional[int] = None,
        ):
            """Move one axis without creating an action.

            Refused outright while an action is running on this server: unlike
            a stop, a concurrent move has no safety justification, and the
            refusal is reported as its own outcome rather than as a failure so
            the panel can name the remedy. No device call is made in that case.

            The value is dispatched in the domain ``units`` names. Under
            ``counts`` the driver passes ``scale=False``, so the integer
            reaches the controller as the count it already is; the conversion
            (or its deliberate absence) happens there, never here.

            Args:
                axis: Axis name from the server's ``axes`` config.
                value: Move magnitude or absolute target, in ``units``.
                mode: Relative or absolute interpretation of ``value``.
                units: ``mm`` or ``counts``.
                speed: Accepted for signature parity with the other motion
                    servers and ignored -- velocity on a Kinesis axis is set
                    through ``set_velocity``, not per move.

            Returns:
                ``(error_code, {"axis", "requested", "units", "counts"})``.
                ``counts`` carries the commanded integer for a counts move and
                is ``None`` for a millimetre one: the endpoint performs no
                conversion, so it has no count to report and will not invent
                a plausible-looking one.
            """
            running = _running_actions(app)
            if running:
                LOGGER.info(
                    f"refusing panel move on axis '{axis}': actions running "
                    f"on {running}"
                )
                return ErrorCodes.in_progress, {}

            # TOCTOU residual, stated rather than discovered at a station: an
            # action can start between the check above and the driver call
            # below. Unlike Galil, this driver has no downstream busy guard --
            # ``move_by``/``move_to`` during motion is a re-target, not a
            # fault -- so the race degrades to "the panel's move wins". It is
            # a residual, not a closed hole.
            axis_name = getattr(axis, "value", axis)
            resp = app.driver.move(axis_name, mode, value, units=units.value)
            error_code = (
                ErrorCodes.none
                if resp.response == "success"
                else ErrorCodes.critical_error
            )
            return error_code, {
                "axis": axis_name,
                "requested": value,
                "units": units.value,
                "counts": int(value) if units == Units.counts else None,
            }

        @app.post("/stop_motion", tags=["private"])
        async def stop_motion():
            """Halt every axis, leaving the motors energized.

            ``KinesisMotor.stop`` only, never a de-energize: a vertical axis
            that lost its holding current would drop under gravity, so a panel
            stop that cut it would be more dangerous than the motion it
            interrupted. That is also why this route is **not** named for an
            estop -- an estop must de-energize, and a halt-only route wearing
            that name would under-stop whatever cascade adopted it.

            **Unconditional, including mid-sequence, and the consequence is
            accepted rather than hidden.** A running action is not cancelled,
            failed, or notified: its executor keeps polling, observes that
            motion has ceased, and completes normally -- reporting a position
            that is not the one it commanded. So the run record can end up
            describing a move that did not go where it says it went. That is
            the correct trade for an engineering escape hatch (halting a
            crashing stage must not depend on the orchestrator being
            responsive), but it is a data-integrity hazard, which is why the
            case is logged at WARNING here.

            Returns:
                ``(error_code, {"stopped": [axis, ...]})`` listing the axes
                the stop was issued to.
            """
            axes = list(app.driver.motors)
            running = _running_actions(app)
            if running:
                LOGGER.warning(
                    f"panel stop_motion issued while actions are running on "
                    f"{running}; motion will halt without notifying them, so "
                    f"their recorded end position will not be the commanded one"
                )
            resp = app.driver.stop()
            error_code = (
                ErrorCodes.none
                if resp.response == "success"
                else ErrorCodes.critical_error
            )
            return error_code, {"stopped": axes}

        @app.post("/get_axis_positions", tags=["private"])
        async def get_axis_positions():
            """Return every axis's coordinate in both millimetres and counts.

            One position sample per axis, rendered twice: the driver reads the
            raw device count once and derives millimetres from that same
            integer, so the two halves always describe the same instant.
            Taking a second, scaled reading would be two round trips at two
            instants, which cannot describe one coordinate on a moving axis.

            Returns:
                ``(error_code, {axis: {"mm": float|None, "counts": int|None,
                "moving": bool|None}})``. ``None`` rather than ``0``
                throughout -- including for an axis whose ``pos_scale`` is
                missing -- because zero is a legitimate motor coordinate, so a
                value shown as zero must mean zero.
            """
            return ErrorCodes.none, app.driver.query_axis_positions()


def makeApp(server_key) -> BaseAPI:
    """Build the BaseAPI app for Kinesis motorised stages.

    Args:
        server_key: Unique key identifying this server in the orchestration
            group.

    Returns:
        The configured BaseAPI instance. Axis-specific endpoints are added
        lazily via :func:`kinesis_dyn_endpoints`.
    """

    # current plan is 1 mfc per COM

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Kinesis motor server",
        version=0.2,
        driver_classes=[KinesisMotor],
        poller_class=KinesisPoller,
        dyn_endpoints=kinesis_dyn_endpoints,
    )

    return app
