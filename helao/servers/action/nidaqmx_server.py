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
import time

from importlib import import_module

from fastapi import Body, Query
from typing import Optional, List, Union
from socket import gethostname


from helao.servers.base_api import BaseAPI
from helao.drivers.io.nidaqmx_driver import cNIMAX, DevMonExec
from helao.core.models.sample import AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample
from helao.helpers.make_str_enum import make_str_enum
from helao.helpers.premodels import Action
from helao.core.error import ErrorCodes
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, server_key, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="NIdaqmx server",
        version=2.0,
        driver_class=cNIMAX,
    )
    dev_monitor = app.server_params.get("dev_monitor", {})
    dev_monitoritems = make_str_enum("dev_monitor", {key: key for key in dev_monitor})

    dev_heat = app.server_params.get("dev_heat", {})
    dev_heatitems = make_str_enum("dev_heat", {key: key for key in dev_heat})

    dev_pump = app.server_params.get("dev_pump", {})
    dev_pumpitems = make_str_enum("dev_pump", {key: key for key in dev_pump})

    dev_gasvalve = app.server_params.get("dev_gasvalve", {})
    dev_gasvalveitems = make_str_enum(
        "dev_gasvalve", {key: key for key in dev_gasvalve}
    )

    dev_liquidvalve = app.server_params.get("dev_liquidvalve", {})
    dev_liquidvalveitems = make_str_enum(
        "dev_liquidvalve", {key: key for key in dev_liquidvalve}
    )

    dev_multivalve = app.server_params.get("dev_multivalve", {})
    dev_multivalveitems = make_str_enum(
        "dev_multivalve", {key: key for key in dev_multivalve}
    )

    dev_led = app.server_params.get("dev_led", {})
    dev_leditems = make_str_enum("dev_led", {key: key for key in dev_led})

    dev_fswbcd = app.server_params.get("dev_fswbcd", {})
    dev_fswbcditems = make_str_enum("dev_fswbcd", {key: key for key in dev_fswbcd})
    dev_cellcurrent = app.server_params.get("dev_cellcurrent", {})
    # dev_cellcurrentitems = make_str_enum("dev_cellcurrent",{key:key for key in dev_cellcurrent})
    dev_cellvoltage = app.server_params.get("dev_cellvoltage", {})
    # dev_cellvoltageitems = make_str_enum("dev_cellvoltage",{key:key for key in dev_cellvoltage})
    dev_activecell = app.server_params.get("dev_activecell", {})
    dev_activecellitems = make_str_enum(
        "dev_activecell", {key: key for key in dev_activecell}
    )
    dev_mastercell = app.server_params.get("dev_mastercell", {})
    dev_mastercellitems = make_str_enum(
        "dev_mastercell", {key: key for key in dev_mastercell}
    )
    dev_fsw = app.server_params.get("dev_fsw", {})
    dev_fswitems = make_str_enum("dev_fsw", {key: key for key in dev_fsw})
    # dev_RSHTTLhandshake = app.server_params.get("dev_RSHTTLhandshake",dict())

    if dev_mastercell:

        @app.post(f"/{server_key}/mastercell", tags=["action"])
        async def mastercell(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            cell: dev_mastercellitems = None,
            on: bool = True,
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

        @app.post(f"/{server_key}/activecell", tags=["action"])
        async def activecell(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            cell: dev_activecellitems = None,
            on: bool = True,
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

        @app.post(f"/{server_key}/pump", tags=["action"])
        async def pump(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            pump: dev_pumpitems = None,
            on: bool = True,
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

        @app.post(f"/{server_key}/gasvalve", tags=["action"])
        async def gasvalve(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            gasvalve: dev_gasvalveitems = None,
            on: bool = True,
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

        @app.post(f"/{server_key}/liquidvalve", tags=["action"])
        async def liquidvalve(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            liquidvalve: dev_liquidvalveitems = None,
            on: bool = True,
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


    if dev_multivalve:

        @app.post(f"/{server_key}/multivalve", tags=["action"])
        async def multivalve(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            multivalve: dev_multivalveitems = None,
            on: bool = True,
        ):
            active = await app.base.setup_and_contain_action(action_abbr="lfv")
            # some additional params in order to call the same driver functions
            # for all DO actions
            active.action.action_params["do_port"] = dev_multivalve[
                active.action.action_params["multivalve"]
            ]
            active.action.action_params["do_name"] = active.action.action_params[
                "multivalve"
            ]
            datadict = await app.driver.set_digital_out(**active.action.action_params)
            active.action.error_code = datadict.get(
                "error_code", ErrorCodes.unspecified
            )
            await active.enqueue_data_dflt(datadict=datadict)
            finished_act = await active.finish()
            return finished_act.as_dict()

    if dev_led:

        @app.post(f"/{server_key}/led", tags=["action"])
        async def led(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            led: dev_leditems = None,
            on: bool = True,
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

        @app.post(f"/{server_key}/fswbcd", tags=["action"])
        async def fswbcd(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            fswbcd: dev_fswbcditems = None,
            on: bool = True,
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

        @app.post(f"/{server_key}/fsw", tags=["action"])
        async def fsw(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            fsw: dev_fswitems = None,
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

        @app.post(f"/{server_key}/cellIV", tags=["action"])
        async def cellIV(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            fast_samples_in: List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
] = Body([], embed=True),
            Tval: float = 10.0,
            SampleRate: int = Query(1.0, ge=1),
            TTLwait: int = -1,  # -1 disables, else select TTL channel
        ):
            """Runs multi cell IV measurement.
            Args:
                 SampleRate: samples per second
                 Tval: time of measurement in seconds
                 TTLwait: trigger channel, -1 disables, else select TTL channel"""
            A =  app.base.setup_action()
            A.action_abbr = "multiCV"
            active_dict = await app.driver.run_cell_IV(A)
            return active_dict

    if dev_monitor:

        @app.post(f"/{server_key}/acquire_monitors", tags=["action"])
        async def acquire_monitors(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            duration: float = -1,
            acquisition_rate: float = 0.2,
            fast_samples_in: List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
] = Body([], embed=True),
        ):
            """Record NIMax monitor device channels."""
            active = await app.base.setup_and_contain_action()
            active.action.action_abbr = "ni_monitor"
            executor = DevMonExec(
                active=active,
                oneoff=False,
                poll_rate=active.action.action_params["acquisition_rate"],
            )
            active_action_dict = active.start_executor(executor)
            return active_action_dict

        @app.post(f"/{server_key}/cancel_acquire_monitors", tags=["action"])
        async def cancel_acquire_monitors(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
        ):
            """Stop NIMax monitor acquisition."""
            active = await app.base.setup_and_contain_action()
            for exec_id, executor in app.base.executors.items():
                if exec_id.split()[0] == "acquire_monitors":
                    executor.stop_action_task()
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post("/readtemp", tags=["private"])
        async def readtemp():
            """Runs temp measurement.  T and S thermocouples"""
            tempread = {}
            tempread = await app.driver.read_T()
            print(tempread)
            return tempread

    if dev_heat:

        @app.post(f"/{server_key}/heater", tags=["action"])
        async def heater(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            heater: dev_heatitems = None,
            on: bool = True,
        ):
            active = await app.base.setup_and_contain_action(action_abbr="heat")
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

    if dev_monitor:

        @app.post("/monloop", tags=["private"])
        async def monloop():
            # A =  app.base.setup_action()
            A = await app.driver.monitorloop()

        @app.post(f"/{server_key}/heatloop", tags=["action"])
        async def heatloop(
            # action: Action = Body({}, embed=True),
            # action_version: int = 1,
            duration_hrs: float = 2,
            celltemp_min_C: float = 74.5,
            celltemp_max_C: float = 75.5,
            reservoir2_min_C: float = 84.5,
            reservoir2_max_C: float = 85.5,
        ):
            # A =  app.base.setup_action()
            A = await app.driver.Heatloop(
                duration_h=duration_hrs,
                celltemp_min=celltemp_min_C,
                celltemp_max=celltemp_max_C,
                reservoir2_min=reservoir2_min_C,
                reservoir2_max=reservoir2_max_C,
            )

        #        temp_dict = {}
        #        #app.driver.create_Ttask()
        #        starttime=time.time()
        #        duration = duration_hrs * 60 * 60
        #        heatloop_run = True
        #        while heatloop_run and ( time.time() - starttime < duration):
        #            #need to insert pause. also verify if values are actually being evaluated
        #            time.sleep(1)
        #            temp_dict = await readtemp()
        #            for k,v in temp_dict.items():
        #                temp_dict[k] = float(v)
        #            print(type(temp_dict['Ktc_in_cell']))
        #            print(type(temp_dict['Ttc_in_reservoir']))
        #            if temp_dict['Ktc_in_cell'] < celltemp_min_C:
        #                print("heat1on")
        #                heater(heater="cellheater", on = True)
        #            if temp_dict['Ktc_in_cell'] > celltemp_max_C:
        #                print("heat1off")
        #                heater(heater="cellheater", on = False)
        #            if temp_dict['Ttc_in_reservoir'] < reservoir2_min_C:
        #                print("heat2on")
        #                heater(heater="res_heater", on = True)
        #            if temp_dict['Ttc_in_reservoir'] > reservoir2_max_C:
        #                print("heat2off")
        #                heater(heater="res_heater", on = False)
        # need way to monitor and break loop
        # ie, heatloop_run = False

        #        await stop_temp()
        #        heater(heater="cellheater", on = False)
        #        heater(heater="res_heater", on = False)

        # @app.post(f"/stoptemp", tags=["action"])
        # async def stop_temp():
        #     app.driver.stop_Ttask()

        # @app.post(f"/starttemp", tags=["action"])
        # async def start_temp():
        #     app.driver.create_Ttask()

        @app.post("/stopmonloop", tags=["private"])
        async def monloopstop():
            app.driver.stop_monitor()

        @app.post("/stopheatloop", tags=["private"])
        async def heatloopstop():
            app.driver.stop_heatloop()

    @app.post(f"/{server_key}/stop", tags=["action"])
    async def stop(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Stops measurement in a controlled way."""
        active = await app.base.setup_and_contain_action(action_abbr="stop")
        await active.enqueue_data_dflt(datadict={"stop": await app.driver.stop()})
        finished_act = await active.finish()
        return finished_act.as_dict()

    return app
