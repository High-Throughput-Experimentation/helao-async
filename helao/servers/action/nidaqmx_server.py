__all__ = ["makeApp"]

# NIdaqmx server
# https://nidaqmx-python.readthedocs.io/en/latest/task.html
# http://127.0.0.1:8006/docs#/default
# https://readthedocs.org/projects/nidaqmx-python/downloads/pdf/stable/


# TODO:
# done - add wsdata with buffering for visualizers
# - add wsstatus
# - test what happens if NImax broswer has nothing configured and only lists the device
# - create tasks for action library
# - handshake as stream with interrupt

from importlib import import_module

from fastapi import Body, Query
from typing import Optional, List
from socket import gethostname


from helao.servers.base import makeActionServ
from helao.drivers.io.nidaqmx_driver import cNIMAX
from helaocore.models.sample import LiquidSample, SampleUnion
from helao.helpers.make_str_enum import make_str_enum
from helao.helpers.premodels import Action
from helaocore.error import ErrorCodes
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, servKey, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = makeActionServ(
        config=config,
        server_key=servKey,
        server_title=servKey,
        description="NIdaqmx server",
        version=2.0,
        driver_class=cNIMAX,
    )
    dev_temperature = app.server_params.get("dev_temperature", dict())
    dev_tempitems = make_str_enum("dev_temperature", {key: key for key in dev_temperature})

    dev_heat = app.server_params.get("dev_heat", dict())
    dev_heatitems = make_str_enum("dev_heat", {key: key for key in dev_heat})


    dev_pump = app.server_params.get("dev_pump", dict())
    dev_pumpitems = make_str_enum("dev_pump", {key: key for key in dev_pump})

    dev_gasvalve = app.server_params.get("dev_gasvalve", dict())
    dev_gasvalveitems = make_str_enum(
        "dev_gasvalve", {key: key for key in dev_gasvalve}
    )

    dev_liquidvalve = app.server_params.get("dev_liquidvalve", dict())
    dev_liquidvalveitems = make_str_enum(
        "dev_liquidvalve", {key: key for key in dev_liquidvalve}
    )

    dev_led = app.server_params.get("dev_led", dict())
    dev_leditems = make_str_enum("dev_led", {key: key for key in dev_led})

    dev_fswbcd = app.server_params.get("dev_fswbcd", dict())
    dev_fswbcditems = make_str_enum("dev_fswbcd", {key: key for key in dev_fswbcd})
    dev_cellcurrent = app.server_params.get("dev_cellcurrent", dict())
    # dev_cellcurrentitems = make_str_enum("dev_cellcurrent",{key:key for key in dev_cellcurrent})
    dev_cellvoltage = app.server_params.get("dev_cellvoltage", dict())
    # dev_cellvoltageitems = make_str_enum("dev_cellvoltage",{key:key for key in dev_cellvoltage})
    dev_activecell = app.server_params.get("dev_activecell", dict())
    dev_activecellitems = make_str_enum(
        "dev_activecell", {key: key for key in dev_activecell}
    )
    dev_mastercell = app.server_params.get("dev_mastercell", dict())
    dev_mastercellitems = make_str_enum(
        "dev_mastercell", {key: key for key in dev_mastercell}
    )
    dev_fsw = app.server_params.get("dev_fsw", dict())
    dev_fswitems = make_str_enum("dev_fsw", {key: key for key in dev_fsw})
    # dev_RSHTTLhandshake = app.server_params.get("dev_RSHTTLhandshake",dict())

    if dev_mastercell:

        @app.post(f"/{servKey}/mastercell", tags=["public"])
        async def mastercell(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            cell: Optional[dev_mastercellitems] = None,
            on: Optional[bool] = True,
        ):
            active = await app.base.setup_and_contain_action(action_abbr="mcell")
            # some additional params in order to call the same driver functions
            # for all DO actions
            active.action.action_params["do_port"] = dev_mastercell[
                active.action.action_params["cell"]
            ]
            active.action.action_params["do_name"] = active.action.action_params["cell"]
            datadict = await app.driver.set_digital_out(**active.action.action_params)
            active.action.error_code = datadict.get(
                "error_code", ErrorCodes.unspecified
            )
            await active.enqueue_data_dflt(datadict=datadict)
            finished_act = await active.finish()
            return finished_act.as_dict()

    if dev_activecell:

        @app.post(f"/{servKey}/activecell", tags=["public"])
        async def activecell(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            cell: Optional[dev_activecellitems] = None,
            on: Optional[bool] = True,
        ):
            active = await app.base.setup_and_contain_action(action_abbr="acell")
            # some additional params in order to call the same driver functions
            # for all DO actions
            active.action.action_params["do_port"] = dev_activecell[
                active.action.action_params["cell"]
            ]
            active.action.action_params["do_name"] = active.action.action_params["cell"]
            datadict = await app.driver.set_digital_out(**active.action.action_params)
            active.action.error_code = datadict.get(
                "error_code", ErrorCodes.unspecified
            )
            await active.enqueue_data_dflt(datadict=datadict)
            finished_act = await active.finish()
            return finished_act.as_dict()

    if dev_pump:

        @app.post(f"/{servKey}/pump", tags=["public"])
        async def pump(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            pump: Optional[dev_pumpitems] = None,
            on: Optional[bool] = True,
        ):
            active = await app.base.setup_and_contain_action(action_abbr="pump")
            # some additional params in order to call the same driver functions
            # for all DO actions
            active.action.action_params["do_port"] = dev_pump[
                active.action.action_params["pump"]
            ]
            active.action.action_params["do_name"] = active.action.action_params["pump"]
            datadict = await app.driver.set_digital_out(**active.action.action_params)
            active.action.error_code = datadict.get(
                "error_code", ErrorCodes.unspecified
            )
            await active.enqueue_data_dflt(datadict=datadict)
            finished_act = await active.finish()
            return finished_act.as_dict()

    if dev_gasvalve:

        @app.post(f"/{servKey}/gasvalve", tags=["public"])
        async def gasvalve(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            gasvalve: Optional[dev_gasvalveitems] = None,
            on: Optional[bool] = True,
        ):
            active = await app.base.setup_and_contain_action(action_abbr="gfv")
            # some additional params in order to call the same driver functions
            # for all DO actions
            active.action.action_params["do_port"] = dev_gasvalve[
                active.action.action_params["gasvalve"]
            ]
            active.action.action_params["do_name"] = active.action.action_params[
                "gasvalve"
            ]
            datadict = await app.driver.set_digital_out(**active.action.action_params)
            active.action.error_code = datadict.get(
                "error_code", ErrorCodes.unspecified
            )
            await active.enqueue_data_dflt(datadict=datadict)
            finished_act = await active.finish()
            return finished_act.as_dict()

    if dev_liquidvalve:

        @app.post(f"/{servKey}/liquidvalve", tags=["public"])
        async def liquidvalve(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            liquidvalve: Optional[dev_liquidvalveitems] = None,
            on: Optional[bool] = True,
        ):
            active = await app.base.setup_and_contain_action(action_abbr="lfv")
            # some additional params in order to call the same driver functions
            # for all DO actions
            active.action.action_params["do_port"] = dev_liquidvalve[
                active.action.action_params["liquidvalve"]
            ]
            active.action.action_params["do_name"] = active.action.action_params[
                "liquidvalve"
            ]
            datadict = await app.driver.set_digital_out(**active.action.action_params)
            active.action.error_code = datadict.get(
                "error_code", ErrorCodes.unspecified
            )
            await active.enqueue_data_dflt(datadict=datadict)
            finished_act = await active.finish()
            return finished_act.as_dict()

    if dev_led:

        @app.post(f"/{servKey}/led", tags=["public"])
        async def led(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            led: Optional[dev_leditems] = None,
            on: Optional[bool] = True,
        ):
            active = await app.base.setup_and_contain_action(action_abbr="led")
            # some additional params in order to call the same driver functions
            # for all DO actions
            active.action.action_params["do_port"] = dev_led[
                active.action.action_params["led"]
            ]
            active.action.action_params["do_name"] = active.action.action_params["led"]
            datadict = await app.driver.set_digital_out(**active.action.action_params)
            active.action.error_code = datadict.get(
                "error_code", ErrorCodes.unspecified
            )
            await active.enqueue_data_dflt(datadict=datadict)
            finished_act = await active.finish()
            return finished_act.as_dict()

    if dev_fswbcd:

        @app.post(f"/{servKey}/fswbcd", tags=["public"])
        async def fswbcd(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            fswbcd: Optional[dev_fswbcditems] = None,
            on: Optional[bool] = True,
        ):
            active = await app.base.setup_and_contain_action(action_abbr="fswbcd")
            # some additional params in order to call the same driver functions
            # for all DO actions
            active.action.action_params["do_port"] = dev_fswbcd[
                active.action.action_params["fswbcd"]
            ]
            active.action.action_params["do_name"] = active.action.action_params[
                "fswbcd"
            ]
            datadict = await app.driver.set_digital_out(**active.action.action_params)
            active.action.error_code = datadict.get(
                "error_code", ErrorCodes.unspecified
            )
            await active.enqueue_data_dflt(datadict=datadict)
            finished_act = await active.finish()
            return finished_act.as_dict()

    if dev_fsw:

        @app.post(f"/{servKey}/fsw", tags=["public"])
        async def fsw(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            fsw: Optional[dev_fswitems] = None,
        ):
            active = await app.base.setup_and_contain_action(action_abbr="fsw")
            # some additional params in order to call the same driver functions
            # for all DI actions
            active.action.action_params["di_port"] = dev_fsw[
                active.action.action_params["fsw"]
            ]
            active.action.action_params["di_name"] = active.action.action_params["fsw"]
            datadict = await app.driver.get_digital_in(**active.action.action_params)
            active.action.error_code = datadict.get(
                "error_code", ErrorCodes.unspecified
            )
            await active.enqueue_data_dflt(datadict=datadict)
            finished_act = await active.finish()
            return finished_act.as_dict()

    if dev_cellcurrent and dev_cellvoltage:

        @app.post(f"/{servKey}/cellIV", tags=["public"])
        async def cellIV(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            fast_samples_in: Optional[List[SampleUnion]] = Body([], embed=True),
            Tval: Optional[float] = 10.0,
            SampleRate: Optional[int] = Query(1.0, ge=1),
            TTLwait: Optional[int] = -1,  # -1 disables, else select TTL channel
        ):
            """Runs multi cell IV measurement.
            Args:
                 SampleRate: samples per second
                 Tval: time of measurement in seconds
                 TTLwait: trigger channel, -1 disables, else select TTL channel"""
            A = await app.base.setup_action()
            A.action_abbr = "multiCV"
            active_dict = await app.driver.run_cell_IV(A)
            return active_dict

    if dev_temperature:

        @app.post(f"/{servKey}/readtemp", tags=["public"])
        async def readtemp(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            TC: Optional[str]= "type-S",  #some sort of selection
            Tval: Optional[float] = 10.0,
            SampleRate: Optional[int] = Query(1.0, ge=1),
            TTLwait: Optional[int] = -1,  # -1 disables, else select TTL channel
        ):
            """Runs temp measurement.
            Args:
                 SampleRate: samples per second
                 TC: which thermocouple to read
                 Tval: time of measurement in seconds
                 TTLwait: trigger channel, -1 disables, else select TTL channel"""
            A = await app.base.setup_action()
            A.action_abbr = "multiCV"  #need to replace with a temp measurement
            active_dict = await app.driver.run_cell_IV(A)
            return active_dict


    if dev_heat:

        @app.post(f"/{servKey}/heater", tags=["public"])
        async def heater(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            heater: Optional[dev_heatitems] = None,
            on: Optional[bool] = True,
        ):
            active = await app.base.setup_and_contain_action(action_abbr="heatf")
            # some additional params in order to call the same driver functions
            # for all DO actions
            active.action.action_params["do_port"] = dev_heat[
                active.action.action_params["heater"]
            ]
            active.action.action_params["do_name"] = active.action.action_params[
                "heater"
            ]
            datadict = await app.driver.set_digital_out(**active.action.action_params)
            active.action.error_code = datadict.get(
                "error_code", ErrorCodes.unspecified
            )
            await active.enqueue_data_dflt(datadict=datadict)
            finished_act = await active.finish()
            return finished_act.as_dict()


    @app.post(f"/{servKey}/stop", tags=["public"])
    async def stop(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Stops measurement in a controlled way."""
        active = await app.base.setup_and_contain_action(action_abbr="stop")
        await active.enqueue_data_dflt(datadict={"stop": await app.driver.stop()})
        finished_act = await active.finish()
        return finished_act.as_dict()

    return app
