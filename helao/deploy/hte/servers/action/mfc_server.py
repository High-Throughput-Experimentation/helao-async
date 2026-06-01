# shell: uvicorn motion_server:app --reload
"""FastAPI action server for Alicat mass-flow and pressure controllers.

Wraps :class:`AliCatMFC` and the flow/pressure executors
(:class:`MfcExec`, :class:`PfcExec`, :class:`MfcConstConcExec`,
:class:`MfcConstPresExec`) and exposes action endpoints for streamed
acquisition, setpoint changes, valve hold operations, and constant
concentration/pressure dosing loops, along with private endpoints for
direct device control.
"""

__all__ = ["makeApp"]

from typing import Optional, List, Union
from fastapi import Body
from helao.helpers.premodels import Action
from helao.core.servers.base_api import BaseAPI, action_version
from helao.core.models.sample import (
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
)
from ...drivers.mfc.alicat_driver import (
    AliCatMFC,
    MfcExec,
    PfcExec,
    MfcConstConcExec,
    MfcConstPresExec,
)

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


async def mfc_dyn_endpoints(app: BaseAPI):
    """Register MFC endpoints once the driver is online.

    The ``maintain_concentration`` endpoints are only registered when a CO2
    sensor server named by ``co2_server_name`` is present in the overall
    config. All other endpoints are registered when at least one device is
    declared under ``server_params['devices']``.

    Args:
        app: The :class:`BaseAPI` instance being configured.
    """
    server_key = app.base.server.server_name
    co2_sensor_key = app.base.server_params.get("co2_server_name", None)
    devices = list(app.base.server_params["devices"].keys())

    if co2_sensor_key in app.helao_cfg["servers"] and devices:

        @app.post(f"/{server_key}/maintain_concentration", tags=["action"])
        async def maintain_concentration(
            device_name: app.driver.dev_mfcs = devices[0],
            target_co2_ppm: float = 1e5,
            headspace_scc: float = 7.5,
            refill_freq_sec: float = 10.0,
            flowrate_sccm: Optional[float] = None,
            ramp_sccm_sec: float = 0,
            stay_open: bool = False,
            duration: float = -1,
            exec_id: Optional[str] = None,
        ):
            """Maintain a target CO2 concentration via a :class:`MfcConstConcExec`.

            The executor doses gas at the chosen refill frequency to hold the
            specified ppm setpoint in the configured headspace volume.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                device_name: MFC device identifier.
                target_co2_ppm: Concentration setpoint in ppm.
                headspace_scc: Headspace volume in standard cc.
                refill_freq_sec: Interval between refill checks in seconds.
                flowrate_sccm: Optional explicit refill flow rate.
                ramp_sccm_sec: Optional ramp rate when changing setpoint.
                stay_open: If true, keep the valve open between refills.
                duration: Run duration in seconds; negative runs until cancelled.
                exec_id: Optional executor id (used by the cancel endpoint).

            Returns:
                The active action dictionary from ``start_executor``.
            """
            active = await app.base.setup_and_contain_action()
            active.action.action_abbr = "hold_conc"
            executor = MfcConstConcExec(
                active=active,
                oneoff=False,
                poll_rate=0.1,
            )
            active_action_dict = active.start_executor(executor)
            return active_action_dict

        @app.post(f"/{server_key}/cancel_maintain_concentration", tags=["action"])
        async def cancel_maintain_concentration(
            device_name: Optional[str] = None,
            exec_id: Optional[str] = None,
        ):
            """Cancel a running ``maintain_concentration`` executor.

            Stops by ``exec_id`` if provided, otherwise stops all matching
            executors filtered by ``device_name``.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                device_name: Optional device filter.
                exec_id: Optional executor identifier to stop directly.

            Returns:
                The finished action dictionary.
            """
            active = await app.base.setup_and_contain_action()
            if active.action.action_params["exec_id"] is not None:
                app.base.stop_executor(active.action.action_params["exec_id"])
            else:
                if active.action.action_params["device_name"] is None:
                    dev_dict = {}
                else:
                    dev_dict = {
                        "device_name": active.action.action_params["device_name"]
                    }
                app.base.stop_all_executor_prefix("maintain_concentration", dev_dict)
            finished_action = await active.finish()
            return finished_action.as_dict()

    else:
        LOGGER.info(f"server_name {co2_sensor_key} was not found in config.")
        LOGGER.info(app.helao_cfg["servers"])

    if devices:

        @app.post(f"/{server_key}/acquire_flowrate", tags=["action"])
        @action_version(2)
        async def acquire_flowrate(
            device_name: app.driver.dev_mfcs = devices[0],
            flowrate_sccm: Optional[float] = None,
            ramp_sccm_sec: float = 0,
            stay_open: bool = False,
            duration: float = -1,
            acquisition_rate: float = 0.2,
            fast_samples_in: List[
                Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
            ] = Body([], embed=True),
            exec_id: Optional[str] = None,
        ):
            """Apply a flow rate and stream MFC telemetry via :class:`MfcExec`.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                device_name: MFC device identifier.
                flowrate_sccm: Optional new flow setpoint in sccm.
                ramp_sccm_sec: Optional ramp rate in sccm/s.
                stay_open: Whether to leave the valve open after acquisition.
                duration: Recording duration in seconds; negative runs until
                    cancelled.
                acquisition_rate: Polling period in seconds passed to the
                    executor.
                fast_samples_in: Sample references associated with this action.
                exec_id: Optional executor id (used by the cancel endpoint).

            Returns:
                The active action dictionary from ``start_executor``.
            """
            active = await app.base.setup_and_contain_action()
            active.action.action_abbr = "acq_flow"
            executor = MfcExec(
                active=active,
                oneoff=False,
                poll_rate=active.action.action_params["acquisition_rate"],
            )
            active_action_dict = active.start_executor(executor)
            return active_action_dict

        @app.post(f"/{server_key}/cancel_acquire_flowrate", tags=["action"])
        async def cancel_acquire_flowrate(
            device_name: Optional[str] = None,
            exec_id: Optional[str] = None,
        ):
            """Cancel a running ``acquire_flowrate`` executor.

            Stops by ``exec_id`` if provided, otherwise stops all matching
            executors filtered by ``device_name``.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                device_name: Optional device filter.
                exec_id: Optional executor identifier to stop directly.

            Returns:
                The finished action dictionary.
            """
            active = await app.base.setup_and_contain_action()
            if active.action.action_params["exec_id"] is not None:
                app.base.stop_executor(active.action.action_params["exec_id"])
            else:
                if active.action.action_params["device_name"] is None:
                    dev_dict = {}
                else:
                    dev_dict = {
                        "device_name": active.action.action_params["device_name"]
                    }
                app.base.stop_all_executor_prefix("acquire_flowrate", dev_dict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/acquire_pressure", tags=["action"])
        @action_version(2)
        async def acquire_pressure(
            device_name: app.driver.dev_mfcs = devices[0],
            pressure_psia: Optional[float] = None,
            ramp_psi_sec: float = 0,
            stay_open: bool = False,
            duration: float = -1,
            acquisition_rate: float = 0.2,
            fast_samples_in: List[
                Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
            ] = Body([], embed=True),
            exec_id: Optional[str] = None,
        ):
            """Apply a pressure setpoint and stream telemetry via :class:`PfcExec`.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                device_name: Pressure controller identifier.
                pressure_psia: Optional new pressure setpoint in psia.
                ramp_psi_sec: Optional ramp rate in psi/s.
                stay_open: Whether to leave the valve open after acquisition.
                duration: Recording duration in seconds; negative runs until
                    cancelled.
                acquisition_rate: Polling period in seconds passed to the
                    executor.
                fast_samples_in: Sample references associated with this action.
                exec_id: Optional executor id (used by the cancel endpoint).

            Returns:
                The active action dictionary from ``start_executor``.
            """
            active = await app.base.setup_and_contain_action()
            active.action.action_abbr = "acq_pres"
            executor = PfcExec(
                active=active,
                oneoff=False,
                poll_rate=active.action.action_params["acquisition_rate"],
            )
            active_action_dict = active.start_executor(executor)
            return active_action_dict

        @app.post(f"/{server_key}/cancel_acquire_pressure", tags=["action"])
        async def cancel_acquire_pressure(
            device_name: Optional[str] = None,
            exec_id: Optional[str] = None,
        ):
            """Cancel a running ``acquire_pressure`` executor.

            Stops by ``exec_id`` if provided, otherwise stops all matching
            executors filtered by ``device_name``.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                device_name: Optional device filter.
                exec_id: Optional executor identifier to stop directly.

            Returns:
                The finished action dictionary.
            """
            active = await app.base.setup_and_contain_action()
            if active.action.action_params["exec_id"] is not None:
                app.base.stop_executor(active.action.action_params["exec_id"])
            else:
                if active.action.action_params["device_name"] is None:
                    dev_dict = {}
                else:
                    dev_dict = {
                        "device_name": active.action.action_params["device_name"]
                    }
                app.base.stop_all_executor_prefix("acquire_pressure", dev_dict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/set_flowrate", tags=["action"])
        async def set_flowrate(
            device_name: app.driver.dev_mfcs = devices[0],
            flowrate_sccm: Optional[float] = None,
            ramp_sccm_sec: float = 0,
        ):
            """Write a new flow rate to the chosen MFC.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                device_name: MFC device identifier.
                flowrate_sccm: Optional new flow setpoint in sccm.
                ramp_sccm_sec: Optional ramp rate in sccm/s.

            Returns:
                The finished action dictionary.
            """
            active = await app.base.setup_and_contain_action(action_abbr="set_flow")
            await app.driver.set_flowrate(**active.action.action_params)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/set_pressure", tags=["action"])
        async def set_pressure(
            device_name: app.driver.dev_mfcs = devices[0],
            pressure_psia: Optional[float] = None,
            ramp_psi_sec: float = 0,
        ):
            """Write a new pressure setpoint to the chosen controller.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                device_name: Pressure controller identifier.
                pressure_psia: Optional pressure setpoint in psia.
                ramp_psi_sec: Optional ramp rate in psi/s.

            Returns:
                The finished action dictionary.
            """
            active = await app.base.setup_and_contain_action(action_abbr="set_pressure")
            await app.driver.set_pressure(**active.action.action_params)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/hold_valve_action", tags=["action"])
        async def hold_valve_action(
            device_name: app.driver.dev_mfcs = devices[0],
        ):
            """Hold the valve open at its current position on the selected device.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                device_name: MFC device identifier.

            Returns:
                The finished action dictionary.
            """
            active = await app.base.setup_and_contain_action(action_abbr="hold_valve")
            await app.driver.hold_valve(
                active.action.action_params.get("device_name", None)
            )
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/cancel_hold_valve_action", tags=["action"])
        async def cancel_hold_valve_action(
            device_name: app.driver.dev_mfcs = devices[0],
        ):
            """Release a previously held valve on the selected device.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                device_name: MFC device identifier.

            Returns:
                The finished action dictionary.
            """
            active = await app.base.setup_and_contain_action(action_abbr="cancel_hold")
            await app.driver.hold_cancel(
                active.action.action_params.get("device_name", None)
            )
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/hold_valve_closed_action", tags=["action"])
        async def hold_valve_closed_action(
            device_name: app.driver.dev_mfcs = devices[0],
        ):
            """Hold the valve fully closed on the selected device.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                device_name: MFC device identifier.

            Returns:
                The finished action dictionary.
            """
            active = await app.base.setup_and_contain_action(action_abbr="close_valve")
            await app.driver.hold_valve_closed(
                active.action.action_params.get("device_name", None)
            )
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/maintain_pressure", tags=["action"])
        @action_version(2)
        async def maintain_pressure(
            device_name: app.driver.dev_mfcs = devices[0],
            target_pressure: float = 14.7,
            total_gas_scc: float = 7.0,
            refill_freq_sec: float = 10.0,
            flowrate_sccm: Optional[float] = None,
            ramp_sccm_sec: float = 0,
            stay_open: bool = False,
            duration: float = -1,
            exec_id: Optional[str] = None,
        ):
            """Maintain a target pressure via a :class:`MfcConstPresExec`.

            The executor evaluates pressure at ``refill_freq_sec`` cadence and
            doses gas to keep the headspace at the requested setpoint.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                device_name: MFC device identifier.
                target_pressure: Pressure setpoint in psia.
                total_gas_scc: Headspace volume in standard cc.
                refill_freq_sec: Interval between refill checks in seconds.
                flowrate_sccm: Optional explicit refill flow rate.
                ramp_sccm_sec: Optional ramp rate when changing setpoint.
                stay_open: If true, keep the valve open between refills.
                duration: Run duration in seconds; negative runs until cancelled.
                exec_id: Optional executor id (used by the cancel endpoint).

            Returns:
                The active action dictionary from ``start_executor``.
            """
            active = await app.base.setup_and_contain_action()
            active.action.action_abbr = "hold_pres"
            executor = MfcConstPresExec(
                active=active,
                oneoff=False,
                poll_rate=0.05,
            )
            active_action_dict = active.start_executor(executor)
            return active_action_dict

        @app.post(f"/{server_key}/cancel_maintain_pressure", tags=["action"])
        async def cancel_maintain_pressure(
            device_name: Optional[str] = None,
            exec_id: Optional[str] = None,
        ):
            """Cancel a running ``maintain_pressure`` executor.

            Stops by ``exec_id`` if provided, otherwise stops all matching
            executors filtered by ``device_name``.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                device_name: Optional device filter.
                exec_id: Optional executor identifier to stop directly.

            Returns:
                The finished action dictionary.
            """
            active = await app.base.setup_and_contain_action()
            if active.action.action_params["exec_id"] is not None:
                app.base.stop_executor(active.action.action_params["exec_id"])
            else:
                if active.action.action_params["device_name"] is None:
                    dev_dict = {}
                else:
                    dev_dict = {
                        "device_name": active.action.action_params["device_name"]
                    }
                app.base.stop_all_executor_prefix("maintain_pressure", dev_dict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post("/start_polling", tags=["private"])
        async def start_polling() -> str:
            """Start the driver's background polling loop."""
            await app.driver.start_polling()
            return "start_polling: ok"

        @app.post("/stop_polling", tags=["private"])
        async def stop_polling() -> str:
            """Stop the driver's background polling loop."""
            await app.driver.stop_polling()
            return "stop_polling: ok"

        @app.post("/list_devices", tags=["private"])
        def list_devices():
            """Return the driver's discovered flow controller metadata."""
            return app.driver.fcinfo

        @app.post("/list_gases", tags=["private"])
        def list_gases(
            device_name: app.driver.dev_mfcs = devices[0],
        ):
            """Return the available gas list for the chosen device."""
            return app.driver.list_gases(device_name)

        @app.post("/set_gas", tags=["private"])
        async def set_gas(
            device_name: app.driver.dev_mfcs = devices[0], gas: Union[int, str] = "N2"
        ):
            """Select a single gas on the chosen device."""
            return await app.driver.set_gas(device_name, gas)

        @app.post("/set_gas_mixture", tags=["private"])
        async def set_gas_mixture(
            device_name: app.driver.dev_mfcs = devices[0], gas_dict: dict = {"N2": 100}
        ):
            """Program a multi-gas blend on the chosen device.

            Args:
                device_name: MFC device identifier.
                gas_dict: Mapping of gas name to percentage composition.
            """
            return await app.driver.set_gas_mixture(device_name, gas_dict)

        @app.post("/lock_display", tags=["private"])
        async def lock_display(device_name: app.driver.dev_mfcs = devices[0]):
            """Lock the front-panel display on the chosen device."""
            return await app.driver.lock_display(device_name)

        @app.post("/unlock_display", tags=["private"])
        async def unlock_display(device_name: app.driver.dev_mfcs = devices[0]):
            """Unlock the front-panel display on the chosen device."""
            return await app.driver.unlock_display(device_name)

        @app.post("/hold_valve", tags=["private"])
        async def hold_valve(device_name: app.driver.dev_mfcs = devices[0]):
            """Latch the valve at its present position on the chosen device."""
            return await app.driver.hold_valve(device_name)

        @app.post("/hold_valve_closed", tags=["private"])
        async def hold_valve_closed(device_name: app.driver.dev_mfcs = devices[0]):
            """Latch the valve fully closed on the chosen device."""
            return await app.driver.hold_valve_closed(device_name)

        @app.post("/hold_cancel", tags=["private"])
        async def hold_cancel(device_name: app.driver.dev_mfcs = devices[0]):
            """Release any active valve hold on the chosen device."""
            return await app.driver.hold_cancel(device_name)

        @app.post("/tare_volume", tags=["private"])
        async def tare_volume(device_name: app.driver.dev_mfcs = devices[0]):
            """Tare the volume totaliser on the chosen device."""
            return await app.driver.tare_volume(device_name)

        @app.post("/tare_pressure", tags=["private"])
        async def tare_pressure(device_name: app.driver.dev_mfcs = devices[0]):
            """Tare the pressure transducer on the chosen device."""
            return await app.driver.tare_pressure(device_name)

        # @app.post("/reset_totalizer", tags=["private"])
        # def reset_totalizer(device_name: app.driver.dev_mfcs = devices[0]):
        #     return app.driver.reset_totalizer(device_name)

        @app.post("/manual_query_state", tags=["private"])
        def manual_query_state(device_name: app.driver.dev_mfcs = devices[0]):
            """Force a single status read from the chosen device."""
            return app.driver.manual_query_status(device_name)

        @app.post("/read_valve_register", tags=["private"])
        def read_valve_register(device_name: app.driver.dev_mfcs = devices[0]):
            """Read the device's valve drive register (R53)."""
            return app.driver._send(device_name, "R53")

        @app.post("/write_valve_register", tags=["private"])
        def write_valve_register(
            device_name: app.driver.dev_mfcs = devices[0], value: int = 20000
        ):
            """Write ``value`` into the device's valve drive register (W53)."""
            return app.driver._send(device_name, f"W53={value}")

        @app.post("/send_command", tags=["private"])
        def send_command(
            device_name: app.driver.dev_mfcs = devices[0], command: str = ""
        ):
            """Send an arbitrary raw command string to the chosen device."""
            return app.driver._send(device_name, command)


def makeApp(server_key) -> BaseAPI:
    """Build the BaseAPI app for Alicat MFC/PFC devices.

    Args:
        server_key: Unique key identifying this server in the orchestration
            group.

    Returns:
        The configured BaseAPI instance. Device-specific endpoints are
        registered via :func:`mfc_dyn_endpoints` once the driver is up.
    """

    # current plan is 1 mfc per COM

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="MFC server",
        version=0.1,
        driver_classes=[AliCatMFC],
        dyn_endpoints=mfc_dyn_endpoints,
    )

    return app
