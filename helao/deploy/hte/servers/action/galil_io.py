"""Galil IO action server.

Wraps the :class:`Galil` IO driver and exposes endpoints for analog and
digital I/O (``get_analog_in``, ``set_analog_out``, ``get_digital_in``,
``get_digital_out``, ``set_digital_out``), gated digital cycling
(``set_digital_cycle`` / ``stop_digital_cycle``), monitored analog
acquisition (``acquire_analog_in`` via :class:`AiMonExec`) and an emergency
``reset``. Endpoints are registered dynamically depending on which of
``dev_ai``/``dev_ao``/``dev_di``/``dev_do`` the driver provides.

Alongside the digital-out *actions* it also registers two **private** twins,
``get_digital_outs`` and ``set_digital_out``, which the engineering control
panel uses. They call the same driver methods without the action wrapper, so a
manual toggle neither writes a row into the run record nor queues behind an
orchestrated action on this server.
"""

__all__ = ["makeApp", "do_value_to_bool"]

from typing import Optional, Union

from fastapi import Body

from helao.core.drivers.helao_driver import DriverResponseType
from helao.core.error import ErrorCodes
from helao.core.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    SolidSample,
)
from helao.hexagon.app.action_context import ActionContext, action_version
from helao.hexagon.app.action_host import ActionHost
from helao.helpers import helao_logging as logging

from ...drivers.io.galil_io_driver import AiMonExec, Galil, GalilPoller, TriggerType

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def do_value_to_bool(value):
    """Coerce a Galil digital-out readback to a bool, or ``None`` if unreadable.

    ``get_digital_out`` returns whatever ``MG @OUT[port]`` gave back, which
    gclib renders as a string like ``" 1.0000"`` rather than as a number. Going
    through ``float`` covers that, the bare ``"1"`` form, and a driver that has
    already coerced. ``None`` rather than ``False`` on failure, because on a
    control panel "we could not read this line" and "this line is off" must not
    look the same.

    Args:
        value: The ``value`` field of a driver digital-out result.

    Returns:
        bool | None: The line state, or ``None`` when it did not parse.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    try:
        return bool(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


async def galil_dyn_endpoints(app: ActionHost):
    """Register Galil IO action endpoints conditional on driver capabilities.

    Only registers each route if the corresponding device family is present on
    the driver (``dev_ai`` -> analog-in endpoints, ``dev_ao`` -> analog-out,
    ``dev_di``/``dev_do`` -> digital-in/out and cycle endpoints).

    Args:
        app: The :class:`ActionHost` instance being constructed by ``makeApp``.
    """
    server_key = app.server.server_name
    app.driver: Galil

    # gclib connection is opened here (not in the driver's __init__, per the
    # HelaoDriver ABC's no-device-I/O-at-construction rule) so that
    # `galil_enabled` reflects a real connection attempt before endpoint
    # registration below decides which routes to expose -- matching the
    # pre-migration timing where __init__ itself opened the connection
    # before this hook ran.
    connect_resp = app.driver.connect()
    LOGGER.info(f"Galil connect() returned status={connect_resp.status}")

    if app.driver.galil_enabled is True:

        if app.driver.dev_ai:

            @app.action()
            @action_version(2)
            async def get_analog_in(
                ctx: ActionContext,
                ai_item: Optional[app.driver.dev_aiitems] = None,
            ):
                """Read a single analog input channel identified by ``ai_item``."""
                active = await ctx.begin(action_abbr="get_ai")

                active.action.action_params["ai_name"] = active.action.action_params[
                    "ai_item"
                ]
                datadict = await app.driver.get_analog_in(**active.action.action_params)
                active.action.error_code = datadict.get(
                    "error_code", ErrorCodes.unspecified
                )
                await active.enqueue_data_dflt(datadict=datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

            @app.action()
            async def acquire_analog_in(
                ctx: ActionContext,
                duration: float = -1,
                acquisition_rate: float = 0.2,
                fast_samples_in: list[
                    Union[
                        AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample
                    ]
                ] = Body([], embed=True),
            ):
                """Start a monitored analog-in acquisition via :class:`AiMonExec`."""
                active = await ctx.begin()
                active.action.action_abbr = "galil_ai"
                executor = AiMonExec(
                    active=active,
                    oneoff=False,
                    poll_rate=active.action.action_params["acquisition_rate"],
                )
                LOGGER.info("Starting executor task.")
                active_action_dict = active.start_executor(executor)
                LOGGER.info("Returning active dict.")
                return active_action_dict

            @app.action()
            async def cancel_acquire_analog_in(ctx: ActionContext):
                """Stop any running ``acquire_analog_in`` executors on this server."""
                active = await ctx.begin()
                for exec_id, executor in app.executors.items():
                    if exec_id.split()[0] == "acquire_analog_in":
                        executor.stop_action_task()
                finished_action = await active.finish()
                return finished_action.as_dict()

        if app.driver.dev_ao:

            @app.action()
            @action_version(2)
            async def set_analog_out(
                ctx: ActionContext,
                ao_item: Optional[app.driver.dev_aoitems] = None,
                value: Optional[float] = None,
            ):
                """Drive an analog output channel ``ao_item`` to ``value``."""
                active = await ctx.begin(action_abbr="set_ao")

                active.action.action_params["ao_name"] = active.action.action_params[
                    "ao_item"
                ]
                datadict = await app.driver.set_analog_out(
                    **active.action.action_params
                )
                active.action.error_code = datadict.get(
                    "error_code", ErrorCodes.unspecified
                )
                await active.enqueue_data_dflt(datadict=datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

        if app.driver.dev_di:

            @app.action()
            @action_version(2)
            async def get_digital_in(
                ctx: ActionContext,
                di_item: Optional[app.driver.dev_diitems] = None,
            ):
                """Read the state of a digital input ``di_item``."""
                active = await ctx.begin(action_abbr="get_di")

                active.action.action_params["di_name"] = active.action.action_params[
                    "di_item"
                ]
                datadict = await app.driver.get_digital_in(
                    **active.action.action_params
                )
                active.action.error_code = datadict.get(
                    "error_code", ErrorCodes.unspecified
                )
                await active.enqueue_data_dflt(datadict=datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

        if app.driver.dev_do:

            @app.action()
            @action_version(2)
            async def get_digital_out(
                ctx: ActionContext,
                do_item: Optional[app.driver.dev_doitems] = None,
            ):
                """Read the current setpoint of a digital output ``do_item``."""
                active = await ctx.begin(action_abbr="get_do")

                active.action.action_params["do_name"] = active.action.action_params[
                    "do_item"
                ]
                datadict = await app.driver.get_digital_out(
                    **active.action.action_params
                )
                active.action.error_code = datadict.get(
                    "error_code", ErrorCodes.unspecified
                )
                await active.enqueue_data_dflt(datadict=datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

        if app.driver.dev_do:

            @app.action()
            @action_version(2)
            async def set_digital_out(
                ctx: ActionContext,
                do_item: Optional[app.driver.dev_doitems] = None,
                on: bool = False,
            ):
                """Set the digital output ``do_item`` on or off."""
                active = await ctx.begin(action_abbr="set_do")

                active.action.action_params["do_name"] = active.action.action_params[
                    "do_item"
                ]
                datadict = await app.driver.set_digital_out(
                    **active.action.action_params
                )
                active.action.error_code = datadict.get(
                    "error_code", ErrorCodes.unspecified
                )
                await active.enqueue_data_dflt(datadict=datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

            # Private twins of the two digital-out endpoints above, for the
            # engineering control panel. Same driver calls, no action wrapper:
            # a panel toggle is a manual intervention, not a step of an
            # experiment, and routing it through the action machinery would put
            # a row in the run record for every click and queue that click
            # behind whatever the orchestrator is running on this server.
            #
            # Bare paths, not ``/{server_key}/...``: that prefix is the action
            # namespace. Reached with ``async_private_dispatcher``.

            @app.post("/get_digital_outs", tags=["private"])
            async def get_digital_outs():
                """Return the state of every configured digital output.

                Read from the controller (``MG @OUT[port]`` per line) rather
                than from anything this server remembers, so a line a sequence
                changed still reads back correctly.

                Returns:
                    ``(error_code, {do_name: bool | None})``. A name maps to
                    ``None`` when its readback did not parse, which a panel
                    should show as unknown rather than as off.
                """
                states = {}
                error_code = ErrorCodes.none
                for do_name in app.driver.dev_do:
                    datadict = await app.driver.get_digital_out(do_name=do_name)
                    item_code = datadict.get("error_code", ErrorCodes.unspecified)
                    if item_code != ErrorCodes.none:
                        error_code = item_code
                    states[do_name] = do_value_to_bool(datadict.get("value"))
                return error_code, states

            @app.post("/set_digital_out", tags=["private"])
            async def set_digital_out_direct(do_name: str = "", on: bool = False):
                """Drive one digital output without creating an action.

                Args:
                    do_name: Key in the server's ``dev_do`` config block.
                    on: ``True`` to set the bit, ``False`` to clear it.

                Returns:
                    ``(error_code, {do_name: bool | None})`` carrying the
                    post-write readback, so a caller does not need a second
                    round trip to learn what the line ended up at.
                """
                if do_name not in app.driver.dev_do:
                    return ErrorCodes.not_available, {}
                datadict = await app.driver.set_digital_out(on=on, do_name=do_name)
                return (
                    datadict.get("error_code", ErrorCodes.unspecified),
                    {do_name: do_value_to_bool(datadict.get("value"))},
                )

        if app.driver.dev_di and app.driver.dev_do:

            @app.action()
            @action_version(2)
            async def set_digital_cycle(
                ctx: ActionContext,
                trigger_name: app.driver.dev_diitems = "gamry_ttl0",
                triggertype: TriggerType = TriggerType.fallingedge,
                out_name: Optional[
                    Union[app.driver.dev_doitems, list[app.driver.dev_doitems]]
                ] = "led",
                out_name_gamry: app.driver.dev_doitems = "gamry_aux",
                toggle_init_delay: Union[float, list[float]] = 0,
                toggle_duty: Union[float, list[float]] = 0.5,
                toggle_period: Union[float, list[float]] = 2.0,
                toggle_duration: Union[float, list[float]] = -1,
                req_out_name: Optional[
                    Union[app.driver.dev_doitems, list[app.driver.dev_doitems]]
                ] = None,
            ):
                """Toggle a digital output on a trigger-driven cycle.

                The toggle starts on the configured edge of ``trigger_name`` and
                drives ``out_name`` ON/OFF with the requested duty cycle until
                ``toggle_duration`` elapses (negative values run as long as the
                trigger is active). ``out_name_gamry`` is the DO line wired to
                the Gamry aux input.

                Args:
                    trigger_name: Digital input that arms/starts the toggle.
                    triggertype: Edge polarity recognised on ``trigger_name``.
                    out_name: Digital output(s) to be toggled.
                    out_name_gamry: Digital output connected to the Gamry aux.
                    toggle_init_delay: Seconds to wait after the trigger before
                        beginning the first ON pulse.
                    toggle_duty: Fraction of the period in the ON state
                        (``0..1``).
                    toggle_period: Full ON+OFF period in seconds.
                    toggle_duration: Total seconds to keep cycling; negative
                        values follow the trigger duration.
                    req_out_name: Optional digital output(s) required to remain
                        asserted while cycling.
                """
                active = await ctx.begin()

                datadict = await app.driver.set_digital_cycle(
                    **active.action.action_params
                )
                active.action.error_code = datadict.get(
                    "error_code", ErrorCodes.unspecified
                )
                await active.enqueue_data_dflt(datadict=datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

        if app.driver.dev_di and app.driver.dev_do:

            @app.action()
            @action_version(2)
            async def stop_digital_cycle(ctx: ActionContext):
                """Stop the currently running digital toggle cycle."""
                active = await ctx.begin()

                datadict = await app.driver.stop_digital_cycle()
                active.action.error_code = datadict.get(
                    "error_code", ErrorCodes.unspecified
                )
                # await active.enqueue_data_dflt(datadict = datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

        @app.action()
        async def reset(ctx: ActionContext):
            """Reset the Galil controller. Emergency use only."""
            active = await ctx.begin(action_abbr="reset")
            reset_resp = app.driver.reset()
            active.action.error_code = (
                ErrorCodes.none
                if reset_resp.response == DriverResponseType.success
                else ErrorCodes.unspecified
            )
            await active.enqueue_data_dflt(
                datadict={
                    "reset": reset_resp.response.value,
                    "status": reset_resp.status.value,
                }
            )
            finished_action = await active.finish()
            return finished_action.as_dict()


def makeApp(server_key) -> ActionHost:
    """Build the Galil IO FastAPI app.

    Constructs a :class:`ActionHost` backed by the :class:`Galil` IO driver and
    defers endpoint registration to :func:`galil_dyn_endpoints`.

    Args:
        server_key: Key identifying this server in the orchestration group.

    Returns:
        The configured :class:`ActionHost` application.
    """

    app = ActionHost(
        server_key=server_key,
        server_title=server_key,
        description="Galil IO server",
        version=2.0,
        driver_classes=[Galil],
        poller_class=GalilPoller,
        dyn_endpoints=galil_dyn_endpoints,
    )

    return app
