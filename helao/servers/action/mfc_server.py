# shell: uvicorn motion_server:app --reload
""" Serial MFC server

"""

__all__ = ["makeApp"]

from typing import Optional, List, Union
from fastapi import Body
from helao.helpers.premodels import Action
from helao.servers.base import HelaoBase
from helaocore.models.sample import SampleUnion
from helao.drivers.mfc.alicat_driver import AliCatMFC, MfcExec, PfcExec
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, server_key, helao_root):

    config = config_loader(confPrefix, helao_root)

    # current plan is 1 mfc per COM
    dev_name = list(config["servers"][server_key]["params"]["devices"].keys())[0]

    app = HelaoBase(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="MFC server",
        version=0.1,
        driver_class=AliCatMFC,
    )

    @app.post(f"/{server_key}/acquire_flowrate", tags=["action"])
    async def acquire_flowrate(
        action: Action = Body({}, embed=True),
        action_version: int = 2,
        device_name: str = dev_name,
        flowrate_sccm: float = None,
        ramp_sccm_sec: float = 0,
        stay_open: bool = False,
        duration: float = -1,
        acquisition_rate: float = 0.2,
        fast_samples_in: List[SampleUnion] = Body([], embed=True),
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

    @app.post(f"/{server_key}/acquire_pressure", tags=["action"])
    async def acquire_pressure(
        action: Action = Body({}, embed=True),
        action_version: int = 2,
        device_name: str = dev_name,
        pressure_psia: float = None,
        ramp_psi_sec: float = 0,
        stay_open: bool = False,
        duration: float = -1,
        acquisition_rate: float = 0.2,
        fast_samples_in: List[SampleUnion] = Body([], embed=True),
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

    @app.post(f"/{server_key}/cancel_acquire_flowrate", tags=["action"])
    async def cancel_acquire_flowrate(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        device_name: str = dev_name,
    ):
        """Stop flowrate & acquisition for given device_name."""
        active = await app.base.setup_and_contain_action()
        await app.base.executors[
            active.action.action_params["device_name"]
        ].stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/cancel_acquire_pressure", tags=["action"])
    async def cancel_acquire_pressure(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        device_name: str = dev_name,
    ):
        """Stop flowrate & acquisition for given device_name."""
        active = await app.base.setup_and_contain_action()
        await app.base.executors[
            active.action.action_params["device_name"]
        ].stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/set_flowrate", tags=["action"])
    async def set_flowrate(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        device_name: str = dev_name,
        flowrate_sccm: float = None,
        ramp_sccm_sec: float = 0,
    ):
        active = await app.base.setup_and_contain_action(action_abbr="set_flow")
        app.driver.set_flowrate(**active.action.action_params)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/set_pressure", tags=["action"])
    async def set_pressure(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        device_name: str = dev_name,
        pressure_psia: float = None,
        ramp_psi_sec: float = 0,
    ):
        active = await app.base.setup_and_contain_action(action_abbr="set_pressure")
        app.driver.set_pressure(**active.action.action_params)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/hold_valve", tags=["action"])
    async def hold_valve_action(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        device_name: str = dev_name,
    ):
        active = await app.base.setup_and_contain_action(action_abbr="hold_valve")
        app.driver.hold_valve(active.action.action_params.get("device_name", None))
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/cancel_hold", tags=["action"])
    async def cancel_hold_action(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        device_name: str = dev_name,
    ):
        active = await app.base.setup_and_contain_action(action_abbr="cancel_hold")
        app.driver.cancel_hold(active.action.action_params.get("device_name", None))
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/hold_valve_closed", tags=["action"])
    async def hold_valve_closed_action(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        device_name: str = dev_name,
    ):
        active = await app.base.setup_and_contain_action(action_abbr="close_valve")
        app.driver.hold_valve_closed(active.action.action_params.get("device_name", None))
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
    def list_gases(device_name: str = dev_name):
        return app.driver.list_gases(device_name)

    @app.post("/set_gas", tags=["private"])
    async def set_gas(device_name: str = dev_name, gas: Union[int, str] = "N2"):
        return await app.driver.set_gas(device_name, gas)

    @app.post("/set_gas_mixture", tags=["private"])
    async def set_gas_mixture(device_name: str = dev_name, gas_dict: dict = {"N2": 100}):
        return await app.driver.set_gas_mixture(device_name, gas_dict)

    @app.post("/lock_display", tags=["private"])
    async def lock_display(device_name: str = dev_name):
        return await app.driver.lock_display(device_name)

    @app.post("/unlock_display", tags=["private"])
    async def unlock_display(device_name: str = dev_name):
        return await app.driver.unlock_display(device_name)

    @app.post("/hold_valve", tags=["private"])
    async def hold_valve(device_name: str = dev_name):
        return await app.driver.hold_valve(device_name)

    @app.post("/hold_valve_closed", tags=["private"])
    async def hold_valve_closed(device_name: str = dev_name):
        return await app.driver.hold_valve_closed(device_name)

    @app.post("/hold_cancel", tags=["private"])
    async def hold_cancel(device_name: str = dev_name):
        return await app.driver.hold_cancel(device_name)

    @app.post("/tare_volume", tags=["private"])
    async def tare_volume(device_name: str = dev_name):
        return await app.driver.tare_volume(device_name)

    @app.post("/tare_pressure", tags=["private"])
    async def tare_pressure(device_name: str = dev_name):
        return await app.driver.tare_pressure(device_name)

    # @app.post("/reset_totalizer", tags=["private"])
    # def reset_totalizer(device_name: str = dev_name):
    #     return app.driver.reset_totalizer(device_name)

    @app.post("/manual_query_state", tags=["private"])
    def manual_query_state(device_name: str = dev_name):
        return app.driver.manual_query_status(device_name)

    @app.post("/read_valve_register", tags=["private"])
    def read_valve_register(device_name: str = dev_name):
        return app.driver._send(device_name, "R53")

    @app.post("/write_valve_register", tags=["private"])
    def write_valve_register(device_name: str = dev_name, value: int = 20000):
        return app.driver._send(device_name, f"W53={value}")

    @app.post("/send_command", tags=["private"])
    def send_command(device_name: str = dev_name, command: str = ''):
        return app.driver._send(device_name, command)

    return app
