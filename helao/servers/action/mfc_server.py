# shell: uvicorn motion_server:app --reload
""" Serial MFC server

"""

__all__ = ["makeApp"]

from typing import Optional, List, Union
from fastapi import Body
from helao.helpers.premodels import Action
from helao.servers.base import makeActionServ
from helaocore.models.sample import SampleUnion
from helao.drivers.mfc.alicat_driver import AliCatMFC, MfcExec
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, servKey, helao_root):

    config = config_loader(confPrefix, helao_root)

    # current plan is 1 mfc per COM
    dev_name = list(config["servers"][servKey]["params"]["devices"].keys())[0]

    app = makeActionServ(
        config=config,
        server_key=servKey,
        server_title=servKey,
        description="MFC server",
        version=0.1,
        driver_class=AliCatMFC,
    )

    @app.post(f"/{servKey}/acquire_flowrate")
    async def acquire_flowrate(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        device_name: str = dev_name,
        flowrate_sccm: Optional[float] = None,
        duration: Optional[float] = -1,
        acquisition_rate: Optional[float] = 0.2,
        fast_samples_in: Optional[List[SampleUnion]] = Body([], embed=True),
    ):
        """Acquire spectra based on external trigger."""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "acq_flow"
        executor = MfcExec(
            active=active,
            oneoff=False,
            poll_rate=active.action.action_params["acquisition_rate"],
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{servKey}/set_flowrate")
    async def set_flowrate(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        device_name: str = dev_name,
        flowrate_sccm: Optional[float] = None,
    ):
        active = await app.base.setup_and_contain_action(action_abbr="set_flow")
        app.driver.set_flowrate(**active.action.action_params)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{servKey}/cancel_acquire_flowrate")
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

    @app.post("/start_polling")
    async def start_polling():
        await app.driver.start_polling()
        return "start_polling: ok"

    @app.post("/stop_polling")
    async def stop_polling():
        await app.driver.stop_polling()
        return "stop_polling: ok"

    @app.post("/list_devices")
    def list_devices():
        return app.driver.list_devices()

    @app.post("/list_gases")
    def list_gases(device_name: str = dev_name):
        return app.driver.list_gases(device_name)

    @app.post("/set_pressure")
    def set_pressure(device_name: str = dev_name, pressure_psia: float = 15.00):
        return app.driver.set_pressure(device_name, pressure_psia)

    @app.post("/set_gas")
    def set_gas(device_name: str = dev_name, gas: Union[int, str] = "N2"):
        return app.driver.set_gas(device_name, gas)

    @app.post("/set_gas_mixture")
    def set_gas_mixture(device_name: str = dev_name, gas_dict: dict = {"N2": 100}):
        return app.driver.set_gas_mixture(device_name, gas_dict)

    @app.post("/lock_display")
    def lock_display(device_name: str = dev_name):
        return app.driver.lock_display(device_name)

    @app.post("/unlock_display")
    def unlock_display(device_name: str = dev_name):
        return app.driver.unlock_display(device_name)

    @app.post("/hold_valve")
    def hold_valve(device_name: str = dev_name):
        return app.driver.hold_valve(device_name)

    @app.post("/hold_valve_closed")
    def hold_valve_closed(device_name: str = dev_name):
        return app.driver.hold_valve_closed(device_name)

    @app.post("/hold_cancel")
    def hold_cancel(device_name: str = dev_name):
        return app.driver.hold_cancel(device_name)

    @app.post("/tare_volume")
    def tare_volume(device_name: str = dev_name):
        return app.driver.tare_volume(device_name)

    @app.post("/tare_pressure")
    def tare_pressure(device_name: str = dev_name):
        return app.driver.tare_pressure(device_name)

    @app.post("/reset_totalizer")
    def reset_totalizer(device_name: str = dev_name):
        return app.driver.reset_totalizer(device_name)

    return app
