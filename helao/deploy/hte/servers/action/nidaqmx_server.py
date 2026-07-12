"""FastAPI action server for an NI DAQmx instrument.

Wraps :class:`cNIMAX` and its :class:`CellIVExec` (multi-cell IV) and
:class:`DevMonExec` (monitor acquisition) executors, and dynamically exposes
digital-output endpoints for each populated device group declared in
``server_params`` (mastercell, activecell, pump, gasvalve, liquidvalve,
multivalve, led, fswbcd, heater) plus digital-input endpoints for foot
switches, multi-cell IV measurement, monitor acquisition, and a
temperature-controlled heat loop. Thermocouple monitor channels are
always-on, polled by :class:`cNIMAXPoller`.
"""

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


from fastapi import Body, Query
from typing import List, Union


from helao.core.servers.base_api import BaseAPI
from ...drivers.io.nidaqmx_driver import cNIMAX, cNIMAXPoller, CellIVExec, DevMonExec
from helao.core.models.sample import (
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
)
from helao.core.models.file import FileConnParams, HloHeaderModel
from helao.helpers.make_str_enum import make_str_enum
from helao.helpers.active_params import ActiveParams
from helao.helpers.sample_api import UnifiedSampleDataAPI
from helao.core.error import ErrorCodes

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


async def nidaqmx_dyn_endpoints(app: BaseAPI):
    """Open the NI-DAQ connection and wire the seams the driver needs from the server.

    Called once at startup (after the driver is constructed): opens the
    thermocouple monitor task and NEGATE3 scale via `connect()` (not in
    `__init__`, per the HelaoDriver ABC's no-device-I/O-at-construction
    rule), wires `_base_hook` so the NI-DAQmx hardware callback can do its
    synchronous estop/live-buffer reads, and constructs the single shared
    `UnifiedSampleDataAPI` instance the `cellIV` endpoint validates samples
    against (mirrors the pre-migration one-instance-per-server pattern).
    """
    app.driver: cNIMAX
    connect_resp = app.driver.connect()
    LOGGER.info(f"NI-MAX connect() returned status={connect_resp.status}")
    app.driver._base_hook = app.base

    app.unified_db = UnifiedSampleDataAPI(app.base)
    await app.unified_db.init_db()


def makeApp(server_key) -> BaseAPI:
    """Build the BaseAPI app for the NI DAQmx server.

    Reads device group dictionaries from ``server_params`` and only registers
    endpoint families whose corresponding mapping is non-empty.

    Args:
        server_key: Unique key identifying this server in the orchestration
            group.

    Returns:
        The configured BaseAPI instance.
    """

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="NIdaqmx server",
        version=2.0,
        driver_classes=[cNIMAX],
        poller_class=cNIMAXPoller,
        dyn_endpoints=nidaqmx_dyn_endpoints,
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
            cell: dev_mastercellitems = None,
            on: bool = True,
        ):
            """Toggle the digital line wired to the chosen master cell.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                cell: Master cell identifier from ``dev_mastercell``.
                on: Output level to apply.

            Returns:
                The finished action dictionary.
            """
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
            cell: dev_activecellitems = None,
            on: bool = True,
        ):
            """Toggle the digital line wired to the chosen active cell.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                cell: Active cell identifier from ``dev_activecell``.
                on: Output level to apply.

            Returns:
                The finished action dictionary.
            """
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
            pump: dev_pumpitems = None,
            on: bool = True,
        ):
            """Toggle the digital line wired to the chosen pump.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                pump: Pump identifier from ``dev_pump``.
                on: Output level to apply.

            Returns:
                The finished action dictionary.
            """
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
            gasvalve: dev_gasvalveitems = None,
            on: bool = True,
        ):
            """Toggle the digital line wired to the chosen gas valve.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                gasvalve: Gas valve identifier from ``dev_gasvalve``.
                on: Output level to apply.

            Returns:
                The finished action dictionary.
            """
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
            liquidvalve: dev_liquidvalveitems = None,
            on: bool = True,
        ):
            """Toggle the digital line wired to the chosen liquid valve.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                liquidvalve: Liquid valve identifier from ``dev_liquidvalve``.
                on: Output level to apply.

            Returns:
                The finished action dictionary.
            """
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
            multivalve: dev_multivalveitems = None,
            on: bool = True,
        ):
            """Toggle the digital line wired to the chosen multi-port valve.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                multivalve: Valve identifier from ``dev_multivalve``.
                on: Output level to apply.

            Returns:
                The finished action dictionary.
            """
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
            led: dev_leditems = None,
            on: bool = True,
        ):
            """Toggle the digital line wired to the chosen LED.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                led: LED identifier from ``dev_led``.
                on: Output level to apply.

            Returns:
                The finished action dictionary.
            """
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
            fswbcd: dev_fswbcditems = None,
            on: bool = True,
        ):
            """Toggle the digital line wired to a foot-switch BCD output.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                fswbcd: Output identifier from ``dev_fswbcd``.
                on: Output level to apply.

            Returns:
                The finished action dictionary.
            """
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
            fsw: dev_fswitems = None,
        ):
            """Read the digital input wired to the chosen foot switch.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                fsw: Foot switch identifier from ``dev_fsw``.

            Returns:
                The finished action dictionary.
            """
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
            fast_samples_in: List[
                Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
            ] = Body([], embed=True),
            Tval: float = 10.0,
            SampleRate: int = Query(1.0, ge=1),
            TTLwait: int = -1,  # -1 disables, else select TTL channel
        ):
            """Run a synchronised multi-cell current/voltage measurement.

            Validates the inbound samples against the unified sample DB,
            creates one file-conn per cell (via :class:`CellIVExec`, which
            splits the active action so each cell has its own output
            stream), configures the IV NI-DAQ task, and starts the executor.
            Returns an "already in progress" error if a measurement is
            already running, or a "no sample" error if sample validation
            fails (matching the pre-migration ``run_cell_IV`` behavior:
            neither case creates an ``Active`` action).

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                fast_samples_in: Sample references associated with this action.
                Tval: Total measurement duration in seconds.
                SampleRate: Samples per second per channel; must be >= 1.
                TTLwait: Trigger channel to wait on; ``-1`` disables waiting.

            Returns:
                The active action dictionary from ``start_executor``, or a
                finished-with-error action dict if validation failed.
            """
            A = app.base.setup_action()
            A.action_abbr = "multiCV"
            A.error_code = ErrorCodes.none

            if app.driver.IO_do_meas:
                A.error_code = ErrorCodes.in_progress
                return A.as_dict()

            samples_in = await app.unified_db.get_samples(A.samples_in)
            if not samples_in and not app.driver.allow_no_sample:
                LOGGER.error("NI got no valid sample, cannot start measurement!")
                A.error_code = ErrorCodes.no_sample
                return A.as_dict()

            cell_keys = app.driver.FIFO_cell_keys
            file_sample_label = {}
            file_sample_list = []
            for i, cell_key in enumerate(cell_keys):
                if samples_in is not None:
                    if len(samples_in) == 9:  # number of cells ---- restored to 9
                        file_sample_list.append([samples_in[i]])
                        sample_label = [samples_in[i].get_global_label()]
                    else:
                        file_sample_list.append(samples_in)
                        sample_label = [
                            sample.get_global_label() for sample in samples_in
                        ]
                else:
                    file_sample_list.append([])
                    sample_label = None
                file_sample_label[cell_key] = sample_label

            active = await app.base.contain_action(
                ActiveParams(
                    action=A,
                    file_conn_params_dict={
                        app.base.dflt_file_conn_key(): FileConnParams(
                            file_conn_key=app.base.dflt_file_conn_key(),
                            sample_global_labels=file_sample_label[cell_keys[0]],
                            file_type="ni_helao__file",
                            # only add optional keys to header
                            # rest will be added later
                            hloheader=HloHeaderModel(optional={"cell": cell_keys[0]}),
                        )
                    },
                )
            )
            executor = CellIVExec(
                samples_in=samples_in,
                file_sample_list=file_sample_list,
                active=active,
                oneoff=False,
                poll_rate=0.1,
            )
            active_action_dict = active.start_executor(executor)
            return active_action_dict

    if dev_monitor:

        @app.post(f"/{server_key}/acquire_monitors", tags=["action"])
        async def acquire_monitors(
            duration: float = -1,
            acquisition_rate: float = 0.2,
            fast_samples_in: List[
                Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
            ] = Body([], embed=True),
        ):
            """Start a :class:`DevMonExec` to stream NI monitor channels.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                duration: Acquisition duration in seconds; negative runs until
                    cancelled.
                acquisition_rate: Polling period in seconds passed to the
                    executor.
                fast_samples_in: Sample references associated with this action.

            Returns:
                The active action dictionary from ``start_executor``.
            """
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
        ):
            """Stop any running ``acquire_monitors`` executor.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.

            Returns:
                The finished action dictionary.
            """
            active = await app.base.setup_and_contain_action()
            for exec_id, executor in app.base.executors.items():
                if exec_id.split()[0] == "acquire_monitors":
                    executor.stop_action_task()
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post("/readtemp", tags=["private"])
        async def readtemp():
            """Read configured T-type and S-type thermocouple channels.

            Returns:
                The thermocouple dictionary produced by ``driver.read_T``.
            """
            tempread = {}
            tempread = await app.driver.read_T()
            print(tempread)
            return tempread

    if dev_heat:

        @app.post(f"/{server_key}/heater", tags=["action"])
        async def heater(
            heater: dev_heatitems = None,
            on: bool = True,
        ):
            """Toggle the digital line wired to the chosen heater.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                heater: Heater identifier from ``dev_heat``.
                on: Output level to apply.

            Returns:
                The finished action dictionary.
            """
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
            """(Re)start the always-on thermocouple monitor poller.

            The monitor task is now polled continuously by ``cNIMAXPoller``
            (wired as this server's ``poller_class``) rather than a
            driver-owned background loop; this endpoint is kept for
            compatibility and simply un-pauses that poller.
            """
            await app.poller._start_polling()

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
            """Drive heater channels to keep cell and reservoir in temperature.

            Delegates to ``driver.Heatloop`` which toggles configured heater
            outputs based on thermocouple readings until ``duration_hrs``
            elapses or :func:`heatloopstop` is invoked.

            Args:
                duration_hrs: Run duration in hours.
                celltemp_min_C: Lower bound for the cell thermocouple.
                celltemp_max_C: Upper bound for the cell thermocouple.
                reservoir2_min_C: Lower bound for the reservoir thermocouple.
                reservoir2_max_C: Upper bound for the reservoir thermocouple.
            """
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
            """Pause the always-on thermocouple monitor poller."""
            await app.poller._stop_polling()

        @app.post("/stopheatloop", tags=["private"])
        async def heatloopstop():
            """Signal the driver's heat loop to exit."""
            app.driver.stop_heatloop()

    @app.post(f"/{server_key}/stop", tags=["action"])
    async def stop(
    ):
        """Stop driver activity in a controlled way and record the result.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action(action_abbr="stop")
        await active.enqueue_data_dflt(datadict={"stop": await app.driver.stop()})
        finished_act = await active.finish()
        return finished_act.as_dict()

    return app
