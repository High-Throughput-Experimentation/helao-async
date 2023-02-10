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
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        device_name: str = dev_name,
        flowrate_sccm: Optional[float] = None,
        ramp_sccm_sec: Optional[float] = 0,
        duration: Optional[float] = -1,
        acquisition_rate: Optional[float] = 0.2,
        fast_samples_in: Optional[List[SampleUnion]] = Body([], embed=True),
    ):
        """Set flow rate and record."""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "acq_flow"
        executor = MfcExec(
            active=active,
            oneoff=False,
            poll_rate=active.action.action_params["acquisition_rate"],
        )
        active_action_dict = await active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/acquire_pressure", tags=["action"])
    async def acquire_pressure(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        device_name: str = dev_name,
        pressure_psia: Optional[float] = None,
        ramp_psi_sec: Optional[float] = 0,
        duration: Optional[float] = -1,
        acquisition_rate: Optional[float] = 0.2,
        fast_samples_in: Optional[List[SampleUnion]] = Body([], embed=True),
    ):
        """Set pressure and record."""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "acq_pres"
        executor = PfcExec(
            active=active,
            oneoff=False,
            poll_rate=active.action.action_params["acquisition_rate"],
        )
        active_action_dict = await active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/cancel_acquire", tags=["action"])
    async def cancel_acquire_flowrate(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        device_name: Optional[str] = dev_name,
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
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        device_name: str = dev_name,
        flowrate_sccm: Optional[float] = None,
        ramp_sccm_sec: Optional[float] = 0,
    ):
        active = await app.base.setup_and_contain_action(action_abbr="set_flow")
        app.driver.set_flowrate(**active.action.action_params)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/set_pressure", tags=["action"])
    async def set_pressure(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        device_name: str = dev_name,
        pressure_psia: Optional[float] = None,
        ramp_psi_sec: Optional[float] = 0,
    ):
        active = await app.base.setup_and_contain_action(action_abbr="set_flow")
        app.driver.set_pressure(**active.action.action_params)
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
    def set_gas(device_name: str = dev_name, gas: Union[int, str] = "N2"):
        return app.driver.set_gas(device_name, gas)

    @app.post("/set_gas_mixture", tags=["private"])
    def set_gas_mixture(device_name: str = dev_name, gas_dict: dict = {"N2": 100}):
        return app.driver.set_gas_mixture(device_name, gas_dict)

    @app.post("/lock_display", tags=["private"])
    def lock_display(device_name: str = dev_name):
        return app.driver.lock_display(device_name)

    @app.post("/unlock_display", tags=["private"])
    def unlock_display(device_name: str = dev_name):
        return app.driver.unlock_display(device_name)

    @app.post("/hold_valve", tags=["private"])
    def hold_valve(device_name: str = dev_name):
        return app.driver.hold_valve(device_name)

    @app.post("/hold_valve_closed", tags=["private"])
    def hold_valve_closed(device_name: str = dev_name):
        return app.driver.hold_valve_closed(device_name)

    @app.post("/hold_cancel", tags=["private"])
    def hold_cancel(device_name: str = dev_name):
        return app.driver.hold_cancel(device_name)

    @app.post("/tare_volume", tags=["private"])
    def tare_volume(device_name: str = dev_name):
        return app.driver.tare_volume(device_name)

    @app.post("/tare_pressure", tags=["private"])
    def tare_pressure(device_name: str = dev_name):
        return app.driver.tare_pressure(device_name)

    # @app.post("/reset_totalizer", tags=["private"])
    # def reset_totalizer(device_name: str = dev_name):
    #     return app.driver.reset_totalizer(device_name)

    @app.post("/manual_query_state", tags=["private"])
    def manual_query_state(device_name: str = dev_name):
        return app.driver.manual_query_status(device_name)

    return app
