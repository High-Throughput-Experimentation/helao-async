__all__ = ["makeApp"]

from typing import Optional, Union, List
from fastapi import Body, Query
from helao.servers.base_api import BaseAPI
from helao.drivers.io.galil_io_driver import Galil, TriggerType, AiMonExec
from helao.helpers.premodels import Action
from helao.core.models.sample import LiquidSample, SampleUnion
from helao.core.error import ErrorCodes
from helao.helpers.config_loader import config_loader

from helao.helpers import logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

async def galil_dyn_endpoints(app=None):
    server_key = app.base.server.server_name

    if app.driver.galil_enabled is True:

        if app.driver.dev_ai:

            @app.post(f"/{server_key}/get_analog_in", tags=["action"])
            async def get_analog_in(
                action: Action = Body({}, embed=True),
                action_version: int = 2,
                ai_item: app.driver.dev_aiitems = None,
            ):
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
                fast_samples_in: List[SampleUnion] = Body([], embed=True),
            ):
                """Record galil analog inputs (monitor_ai)."""
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
                """Stop galil analog input acquisition."""
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
                value: float = None,
            ):
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

                """Toggles output.
                Args:
                    trigger_name: di on which the toggle starts
                    out_name: do_item for toggle output
                    out_name_gamry: do which is connected to gamry aux input
                    toggle_init_delay: offset time in seconds after which toggle starts
                    toggle_duty: fraction duty cycle of toggle ON state
                    toggle_period: period (seconds) of full toggle ON+OFF cycle
                    toggle_duration: time (seconds) for total  toggle time (max is duration of trigger_item)
                                negative value will run as long trigger_item is applied
                    !!! toggle cycle is ON/OFF !!!"""
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
            """FOR EMERGENCY USE ONLY!
            resets galil device.
            """
            active = await app.base.setup_and_contain_action(action_abbr="reset")
            await active.enqueue_data_dflt(datadict={"reset": await app.driver.reset()})
            finished_action = await active.finish()
            return finished_action.as_dict()


def makeApp(confPrefix, server_key, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Galil IO server",
        version=2.0,
        driver_class=Galil,
        dyn_endpoints=galil_dyn_endpoints,
    )

    return app
