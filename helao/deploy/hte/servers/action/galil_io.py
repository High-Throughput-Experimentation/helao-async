"""Galil IO action server.

Wraps the :class:`Galil` IO driver and exposes endpoints for analog and
digital I/O (``get_analog_in``, ``set_analog_out``, ``get_digital_in``,
``get_digital_out``, ``set_digital_out``), gated digital cycling
(``set_digital_cycle`` / ``stop_digital_cycle``), monitored analog
acquisition (``acquire_analog_in`` via :class:`AiMonExec`) and an emergency
``reset``. Endpoints are registered dynamically depending on which of
``dev_ai``/``dev_ao``/``dev_di``/``dev_do`` the driver provides.
"""

__all__ = ["makeApp"]

from typing import Optional, Union, List
from fastapi import Body
from helao.core.servers.base_api import BaseAPI
from ...drivers.io.galil_io_driver import Galil, TriggerType, AiMonExec
from helao.helpers.premodels import Action
from helao.core.models.sample import (
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
)
from helao.core.error import ErrorCodes

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


async def galil_dyn_endpoints(app: BaseAPI):
    """Register Galil IO action endpoints conditional on driver capabilities.

    Only registers each route if the corresponding device family is present on
    the driver (``dev_ai`` -> analog-in endpoints, ``dev_ao`` -> analog-out,
    ``dev_di``/``dev_do`` -> digital-in/out and cycle endpoints).

    Args:
        app: The :class:`BaseAPI` instance being constructed by ``makeApp``.
    """
    server_key = app.base.server.server_name

    if app.driver.galil_enabled is True:

        if app.driver.dev_ai:

            @app.post(f"/{server_key}/get_analog_in", tags=["action"])
            async def get_analog_in(
                action: Action = Body({}, embed=True),
                action_version: int = 2,
                ai_item: app.driver.dev_aiitems = None,
            ):
                """Read a single analog input channel identified by ``ai_item``."""
                active = await app.base.setup_and_contain_action(action_abbr="get_ai")

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

            @app.post(f"/{server_key}/acquire_analog_in", tags=["action"])
            async def acquire_analog_in(
                action: Action = Body({}, embed=True),
                action_version: int = 1,
                duration: float = -1,
                acquisition_rate: float = 0.2,
                fast_samples_in: List[
                    Union[
                        AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample
                    ]
                ] = Body([], embed=True),
            ):
                """Start a monitored analog-in acquisition via :class:`AiMonExec`."""
                active = await app.base.setup_and_contain_action()
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

            @app.post(f"/{server_key}/cancel_acquire_analog_in", tags=["action"])
            async def cancel_acquire_analog_in(
                action: Action = Body({}, embed=True),
                action_version: int = 1,
            ):
                """Stop any running ``acquire_analog_in`` executors on this server."""
                active = await app.base.setup_and_contain_action()
                for exec_id, executor in app.base.executors.items():
                    if exec_id.split()[0] == "acquire_analog_in":
                        executor.stop_action_task()
                finished_action = await active.finish()
                return finished_action.as_dict()

        if app.driver.dev_ao:

            @app.post(f"/{server_key}/set_analog_out", tags=["action"])
            async def set_analog_out(
                action: Action = Body({}, embed=True),
                action_version: int = 2,
                ao_item: app.driver.dev_aoitems = None,
                value: Optional[float] = None,
            ):
                """Drive an analog output channel ``ao_item`` to ``value``."""
                active = await app.base.setup_and_contain_action(action_abbr="set_ao")

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

            @app.post(f"/{server_key}/get_digital_in", tags=["action"])
            async def get_digital_in(
                action: Action = Body({}, embed=True),
                action_version: int = 2,
                di_item: app.driver.dev_diitems = None,
            ):
                """Read the state of a digital input ``di_item``."""
                active = await app.base.setup_and_contain_action(action_abbr="get_di")

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

            @app.post(f"/{server_key}/get_digital_out", tags=["action"])
            async def get_digital_out(
                action: Action = Body({}, embed=True),
                action_version: int = 2,
                do_item: app.driver.dev_doitems = None,
            ):
                """Read the current setpoint of a digital output ``do_item``."""
                active = await app.base.setup_and_contain_action(action_abbr="get_do")

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

            @app.post(f"/{server_key}/set_digital_out", tags=["action"])
            async def set_digital_out(
                action: Action = Body({}, embed=True),
                action_version: int = 2,
                do_item: app.driver.dev_doitems = None,
                on: bool = False,
            ):
                """Set the digital output ``do_item`` on or off."""
                active = await app.base.setup_and_contain_action(action_abbr="set_do")

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

        if app.driver.dev_di and app.driver.dev_do:

            @app.post(f"/{server_key}/set_digital_cycle", tags=["action"])
            async def set_digital_cycle(
                action: Action = Body({}, embed=True),
                action_version: int = 2,
                trigger_name: app.driver.dev_diitems = "gamry_ttl0",
                triggertype: TriggerType = TriggerType.fallingedge,
                out_name: Optional[
                    Union[app.driver.dev_doitems, List[app.driver.dev_doitems]]
                ] = "led",
                out_name_gamry: app.driver.dev_doitems = "gamry_aux",
                toggle_init_delay: Union[float, List[float]] = 0,
                toggle_duty: Union[float, List[float]] = 0.5,
                toggle_period: Union[float, List[float]] = 2.0,
                toggle_duration: Union[float, List[float]] = -1,
                req_out_name: Optional[
                    Union[app.driver.dev_doitems, List[app.driver.dev_doitems]]
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
                active = await app.base.setup_and_contain_action()

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

            @app.post(f"/{server_key}/stop_digital_cycle", tags=["action"])
            async def stop_digital_cycle(
                action: Action = Body({}, embed=True),
                action_version: int = 2,
            ):
                """Stop the currently running digital toggle cycle."""
                active = await app.base.setup_and_contain_action()

                datadict = await app.driver.stop_digital_cycle()
                active.action.error_code = datadict.get(
                    "error_code", ErrorCodes.unspecified
                )
                # await active.enqueue_data_dflt(datadict = datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

        @app.post(f"/{server_key}/reset", tags=["action"])
        async def reset(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
        ):
            """Reset the Galil controller. Emergency use only."""
            active = await app.base.setup_and_contain_action(action_abbr="reset")
            await active.enqueue_data_dflt(datadict={"reset": await app.driver.reset()})
            finished_action = await active.finish()
            return finished_action.as_dict()


def makeApp(server_key) -> BaseAPI:
    """Build the Galil IO FastAPI app.

    Constructs a :class:`BaseAPI` backed by the :class:`Galil` IO driver and
    defers endpoint registration to :func:`galil_dyn_endpoints`.

    Args:
        server_key: Key identifying this server in the orchestration group.

    Returns:
        The configured :class:`BaseAPI` application.
    """

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Galil IO server",
        version=2.0,
        driver_classes=[Galil],
        dyn_endpoints=galil_dyn_endpoints,
    )

    return app
