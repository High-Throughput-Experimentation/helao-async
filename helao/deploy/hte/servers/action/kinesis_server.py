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
from helao.helpers.executor import Executor

from ...drivers.motion.kinesis_driver import (
    MOTION_STATES,
    KinesisMotor,
    KinesisPoller,
    MoveModes,
)


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
