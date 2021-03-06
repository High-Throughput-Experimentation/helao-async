__all__ = ["makeApp"]

from typing import Optional, Union, List
from fastapi import Body, Query
from helao.servers.base import makeActionServ
from helao.drivers.io.galil_io_driver import Galil, TriggerType
from helao.helpers.premodels import Action
from helaocore.error import ErrorCodes
from helao.helpers.config_loader import config_loader


async def galil_dyn_endpoints(app=None):
    servKey = app.base.server.server_name

    if app.driver.galil_enabled is True:

        if app.driver.dev_ai:

            @app.post(f"/{servKey}/get_analog_in")
            async def get_analog_in(
                action: Optional[Action] = Body({}, embed=True),
                action_version: int = 1,
                ai_item: Optional[app.driver.dev_aiitems] = None,
            ):
                active = await app.base.setup_and_contain_action(action_abbr="get_ai")
                active.action.action_params["ai_port"] = app.driver.dev_do[
                    active.action.action_params["ai_item"]
                ]
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

        if app.driver.dev_ao:

            @app.post(f"/{servKey}/set_analog_out")
            async def set_analog_out(
                action: Optional[Action] = Body({}, embed=True),
                action_version: int = 1,
                ao_item: Optional[app.driver.dev_aoitems] = None,
                value: Optional[float] = None,
            ):
                active = await app.base.setup_and_contain_action(action_abbr="set_ao")
                active.action.action_params["ao_port"] = app.driver.dev_do[
                    active.action.action_params["ao_item"]
                ]
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

            @app.post(f"/{servKey}/get_digital_in")
            async def get_digital_in(
                action: Optional[Action] = Body({}, embed=True),
                action_version: int = 1,
                di_item: Optional[app.driver.dev_diitems] = None,
            ):
                active = await app.base.setup_and_contain_action(action_abbr="get_di")
                active.action.action_params["di_port"] = app.driver.dev_do[
                    active.action.action_params["di_item"]
                ]
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

            @app.post(f"/{servKey}/get_digital_out")
            async def get_digital_out(
                action: Optional[Action] = Body({}, embed=True),
                action_version: int = 1,
                do_item: Optional[app.driver.dev_doitems] = None,
            ):
                active = await app.base.setup_and_contain_action(action_abbr="get_do")
                active.action.action_params["do_port"] = app.driver.dev_do[
                    active.action.action_params["do_item"]
                ]
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

            @app.post(f"/{servKey}/set_digital_out")
            async def set_digital_out(
                action: Optional[Action] = Body({}, embed=True),
                action_version: int = 1,
                do_item: Optional[app.driver.dev_doitems] = None,
                on: Optional[bool] = False,
            ):
                active = await app.base.setup_and_contain_action(action_abbr="set_do")
                active.action.action_params["do_port"] = app.driver.dev_do[
                    active.action.action_params["do_item"]
                ]
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

            @app.post(f"/{servKey}/set_digital_cycle")
            async def set_digital_cycle(
                action: Optional[Action] = Body({}, embed=True),
                action_version: int = 2,
                trigger_name: Optional[app.driver.dev_diitems] = "gamry_ttl0",
                triggertype: Optional[TriggerType] = TriggerType.fallingedge,
                out_name: Optional[
                    Union[app.driver.dev_doitems, List[app.driver.dev_doitems]]
                ] = "led",
                out_name_gamry: Optional[app.driver.dev_doitems] = "gamry_aux",
                toggle_init_delay: Optional[Union[float, List[float]]] = 0,
                toggle_duty: Optional[Union[float, List[float]]] = 0.5,
                toggle_period: Optional[Union[float, List[float]]] = 2.0,
                toggle_duration: Optional[Union[float, List[float]]] = -1,
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

            @app.post(f"/{servKey}/stop_digital_cycle")
            async def stop_digital_cycle(
                action: Optional[Action] = Body({}, embed=True),
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

        @app.post(f"/{servKey}/reset")
        async def reset(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
        ):
            """FOR EMERGENCY USE ONLY!
            resets galil device.
            """
            active = await app.base.setup_and_contain_action(action_abbr="reset")
            await active.enqueue_data_dflt(datadict={"reset": await app.driver.reset()})
            finished_action = await active.finish()
            return finished_action.as_dict()


def makeApp(confPrefix, servKey, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = makeActionServ(
        config=config,
        server_key=servKey,
        server_title=servKey,
        description="Galil IO server",
        version=2.0,
        driver_class=Galil,
        dyn_endpoints=galil_dyn_endpoints,
    )

    return app
