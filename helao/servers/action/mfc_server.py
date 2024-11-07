# shell: uvicorn motion_server:app --reload
""" Serial MFC server

"""

__all__ = ["makeApp"]

from typing import Optional, List, Union
from fastapi import Body
from helao.helpers.premodels import Action
from helao.servers.base_api import BaseAPI
from helao.core.models.sample import SampleUnion
from helao.drivers.mfc.alicat_driver import (
    AliCatMFC,
    MfcExec,
    PfcExec,
    MfcConstConcExec,
    MfcConstPresExec,
)
from helao.helpers.config_loader import config_loader


async def mfc_dyn_endpoints(app=None):
    server_key = app.base.server.server_name
    co2_sensor_key = app.base.server_params.get("co2_server_name", None)
    devices = list(app.base.server_params["devices"].keys())

    if co2_sensor_key in app.helao_cfg["servers"] and devices:

        @app.post(f"/{server_key}/maintain_concentration", tags=["action"])
        async def maintain_concentration(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            device_name: app.driver.dev_mfcs = devices[0],
            target_co2_ppm: float = 1e5,
            headspace_scc: float = 7.5,
            refill_freq_sec: float = 10.0,
            flowrate_sccm: float = None,
            ramp_sccm_sec: float = 0,
            stay_open: bool = False,
            duration: float = -1,
            exec_id: Optional[str] = None,
        ):
            """Check pressure at refill freq and dose to target pressure."""
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
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            device_name: Optional[str] = None,
            exec_id: Optional[str] = None,
        ):
            """Stop flowrate & acquisition for given device_name."""
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
        app.base.print_message(f"server_name {co2_sensor_key} was not found in config.")
        app.base.print_message(app.helao_cfg["servers"])

    if devices:

        @app.post(f"/{server_key}/acquire_flowrate", tags=["action"])
        async def acquire_flowrate(
            action: Action = Body({}, embed=True),
            action_version: int = 2,
            device_name: app.driver.dev_mfcs = devices[0],
            flowrate_sccm: float = None,
            ramp_sccm_sec: float = 0,
            stay_open: bool = False,
            duration: float = -1,
            acquisition_rate: float = 0.2,
            fast_samples_in: List[SampleUnion] = Body([], embed=True),
            exec_id: Optional[str] = None,
        ):
            """Set flow rate and record."""
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
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            device_name: Optional[str] = None,
            exec_id: Optional[str] = None,
        ):
            """Stop flowrate & acquisition for given device_name."""
            active = await app.base.setup_and_contain_action()
            if active.action.action_params["exec_id"] is not None:
                app.base.stop_executor(active.action.action_params["exec_id"])
            else:
                if active.action.action_params["device_name"] is None:
                    dev_dict = {}
                else:
                    dev_dict = {"device_name": active.action.action_params["device_name"]}
                app.base.stop_all_executor_prefix("acquire_flowrate", dev_dict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/acquire_pressure", tags=["action"])
        async def acquire_pressure(
            action: Action = Body({}, embed=True),
            action_version: int = 2,
            device_name: app.driver.dev_mfcs = devices[0],
            pressure_psia: float = None,
            ramp_psi_sec: float = 0,
            stay_open: bool = False,
            duration: float = -1,
            acquisition_rate: float = 0.2,
            fast_samples_in: List[SampleUnion] = Body([], embed=True),
            exec_id: Optional[str] = None,
        ):
            """Set pressure and record."""
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
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            device_name: Optional[str] = None,
            exec_id: Optional[str] = None,
        ):
            """Stop flowrate & acquisition for given device_name."""
            active = await app.base.setup_and_contain_action()
            if active.action.action_params["exec_id"] is not None:
                app.base.stop_executor(active.action.action_params["exec_id"])
            else:
                if active.action.action_params["device_name"] is None:
                    dev_dict = {}
                else:
                    dev_dict = {"device_name": active.action.action_params["device_name"]}
                app.base.stop_all_executor_prefix("acquire_pressure", dev_dict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/set_flowrate", tags=["action"])
        async def set_flowrate(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            device_name: app.driver.dev_mfcs = devices[0],
            flowrate_sccm: float = None,
            ramp_sccm_sec: float = 0,
        ):
            active = await app.base.setup_and_contain_action(action_abbr="set_flow")
            await app.driver.set_flowrate(**active.action.action_params)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/set_pressure", tags=["action"])
        async def set_pressure(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            device_name: app.driver.dev_mfcs = devices[0],
            pressure_psia: float = None,
            ramp_psi_sec: float = 0,
        ):
            active = await app.base.setup_and_contain_action(action_abbr="set_pressure")
            await app.driver.set_pressure(**active.action.action_params)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/hold_valve_action", tags=["action"])
        async def hold_valve_action(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            device_name: app.driver.dev_mfcs = devices[0],
        ):
            active = await app.base.setup_and_contain_action(action_abbr="hold_valve")
            await app.driver.hold_valve(active.action.action_params.get("device_name", None))
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/cancel_hold_valve_action", tags=["action"])
        async def cancel_hold_valve_action(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            device_name: app.driver.dev_mfcs = devices[0],
        ):
            active = await app.base.setup_and_contain_action(action_abbr="cancel_hold")
            await app.driver.hold_cancel(active.action.action_params.get("device_name", None))
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/hold_valve_closed_action", tags=["action"])
        async def hold_valve_closed_action(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            device_name: app.driver.dev_mfcs = devices[0],
        ):
            active = await app.base.setup_and_contain_action(action_abbr="close_valve")
            await app.driver.hold_valve_closed(
                active.action.action_params.get("device_name", None)
            )
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/maintain_pressure", tags=["action"])
        async def maintain_pressure(
            action: Action = Body({}, embed=True),
            action_version: int = 2,
            device_name: app.driver.dev_mfcs = devices[0],
            target_pressure: float = 14.7,
            total_gas_scc: float = 7.0,
            refill_freq_sec: float = 10.0,
            flowrate_sccm: float = None,
            ramp_sccm_sec: float = 0,
            stay_open: bool = False,
            duration: float = -1,
            exec_id: Optional[str] = None,
        ):
            """Check pressure at refill freq and dose to target pressure."""
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
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            device_name: Optional[str] = None,
            exec_id: Optional[str] = None,
        ):
            """Stop flowrate & acquisition for given device_name."""
            active = await app.base.setup_and_contain_action()
            if active.action.action_params["exec_id"] is not None:
                app.base.stop_executor(active.action.action_params["exec_id"])
            else:
                if active.action.action_params["device_name"] is None:
                    dev_dict = {}
                else:
                    dev_dict = {"device_name": active.action.action_params["device_name"]}
                app.base.stop_all_executor_prefix("maintain_pressure", dev_dict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post("/start_polling", tags=["private"])
        async def start_polling():
            await app.driver.start_polling()
            return "start_polling: ok"

        @app.post("/stop_polling", tags=["private"])
        async def stop_polling():
            await app.driver.stop_polling()
            return "stop_polling: ok"

        @app.post("/list_devices", tags=["private"])
        def list_devices():
            return app.driver.fcinfo

        @app.post("/list_gases", tags=["private"])
        def list_gases(
            device_name: app.driver.dev_mfcs = devices[0],
        ):
            return app.driver.list_gases(device_name)

        @app.post("/set_gas", tags=["private"])
        async def set_gas(
            device_name: app.driver.dev_mfcs = devices[0], gas: Union[int, str] = "N2"
        ):
            return await app.driver.set_gas(device_name, gas)

        @app.post("/set_gas_mixture", tags=["private"])
        async def set_gas_mixture(
            device_name: app.driver.dev_mfcs = devices[0], gas_dict: dict = {"N2": 100}
        ):
            return await app.driver.set_gas_mixture(device_name, gas_dict)

        @app.post("/lock_display", tags=["private"])
        async def lock_display(device_name: app.driver.dev_mfcs = devices[0]):
            return await app.driver.lock_display(device_name)

        @app.post("/unlock_display", tags=["private"])
        async def unlock_display(device_name: app.driver.dev_mfcs = devices[0]):
            return await app.driver.unlock_display(device_name)

        @app.post("/hold_valve", tags=["private"])
        async def hold_valve(device_name: app.driver.dev_mfcs = devices[0]):
            return await app.driver.hold_valve(device_name)

        @app.post("/hold_valve_closed", tags=["private"])
        async def hold_valve_closed(device_name: app.driver.dev_mfcs = devices[0]):
            return await app.driver.hold_valve_closed(device_name)

        @app.post("/hold_cancel", tags=["private"])
        async def hold_cancel(device_name: app.driver.dev_mfcs = devices[0]):
            return await app.driver.hold_cancel(device_name)

        @app.post("/tare_volume", tags=["private"])
        async def tare_volume(device_name: app.driver.dev_mfcs = devices[0]):
            return await app.driver.tare_volume(device_name)

        @app.post("/tare_pressure", tags=["private"])
        async def tare_pressure(device_name: app.driver.dev_mfcs = devices[0]):
            return await app.driver.tare_pressure(device_name)

        # @app.post("/reset_totalizer", tags=["private"])
        # def reset_totalizer(device_name: app.driver.dev_mfcs = devices[0]):
        #     return app.driver.reset_totalizer(device_name)

        @app.post("/manual_query_state", tags=["private"])
        def manual_query_state(device_name: app.driver.dev_mfcs = devices[0]):
            return app.driver.manual_query_status(device_name)

        @app.post("/read_valve_register", tags=["private"])
        def read_valve_register(device_name: app.driver.dev_mfcs = devices[0]):
            return app.driver._send(device_name, "R53")

        @app.post("/write_valve_register", tags=["private"])
        def write_valve_register(
            device_name: app.driver.dev_mfcs = devices[0], value: int = 20000
        ):
            return app.driver._send(device_name, f"W53={value}")

        @app.post("/send_command", tags=["private"])
        def send_command(
            device_name: app.driver.dev_mfcs = devices[0], command: str = ""
        ):
            return app.driver._send(device_name, command)

def makeApp(confPrefix, server_key, helao_root):
    config = config_loader(confPrefix, helao_root)

    # current plan is 1 mfc per COM

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="MFC server",
        version=0.1,
        driver_class=AliCatMFC,
        dyn_endpoints=mfc_dyn_endpoints,
    )

    return app
