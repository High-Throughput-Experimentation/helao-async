# shell: uvicorn motion_server:app --reload
"""Thermoelectric cooler server

"""

__all__ = ["makeApp"]

from typing import Optional, List, Union
from fastapi import Body
from helao.helpers.premodels import Action
from helao.servers.base_api import BaseAPI
from helao.core.models.sample import AssemblySample, LiquidSample, GasSample,SolidSample, NoneSample
from helao.drivers.temperature_control.mecom_driver import MeerstetterTEC, TECMonExec, TECWaitExec
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, server_key, helao_root):
    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Sensor server",
        version=0.1,
        driver_class=MeerstetterTEC,
    )

    @app.post(f"/{server_key}/record_tec", tags=["action"])
    async def record_tec(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        duration: float = -1,
        acquisition_rate: float = 0.2,
        fast_samples_in: List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]] = Body([], embed=True),
    ):
        """Record TEC values (does not affect setpoint or control)."""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "TEC"
        executor = TECMonExec(
            active=active,
            oneoff=False,
            poll_rate=active.action.action_params["acquisition_rate"],
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/cancel_record_tec", tags=["action"])
    async def cancel_record_tec(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Stop recording TEC values (does not affect setpoint or control)."""
        active = await app.base.setup_and_contain_action()
        for exec_id, executor in app.base.executors.items():
            if exec_id.split()[0] == "record_tec":
                executor.stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/set_temperature", tags=["action"])
    async def set_temperature(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        target_temperature_degc: float = 25.0,
    ):
        """Set target temperature without enabling/disabling control."""
        active = await app.base.setup_and_contain_action(action_abbr="setTEC")
        app.driver.set_temp(active.action.action_params["target_temperature_degc"])
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/enable_tec", tags=["action"])
    async def enable_tec(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        "Enable TEC control."""
        active = await app.base.setup_and_contain_action(action_abbr="enableTEC")
        app.driver.enable()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/disable_tec", tags=["action"])
    async def disable_tec(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Disable TEC control."""
        active = await app.base.setup_and_contain_action(action_abbr="disableTEC")
        app.driver.disable()
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/wait_till_stable", tags=["action"])
    async def wait_till_stable(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        acquisition_rate: float = 0.2,
    ):
        """Wait until temperature_is_stable returns int 2 (stable)."""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "waitTEC"
        executor = TECWaitExec(
            active=active,
            oneoff=False,
            poll_rate=active.action.action_params["acquisition_rate"],
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/cancel_wait_till_stable", tags=["action"])
    async def cancel_wait_till_stable(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Stop waiting for temperature_is_stable."""
        active = await app.base.setup_and_contain_action()
        for exec_id, executor in app.base.executors.items():
            if exec_id.split()[0] == "wait_till_stable":
                executor.stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()
    
    return app
