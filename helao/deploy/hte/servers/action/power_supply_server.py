
__all__ = ["makeApp"]


import time
import asyncio
from tracemalloc import start
from fastapi import Body

from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.core.models.file import HloHeaderModel

from helao.core.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from helao.helpers.executor import Executor
from helao.helpers import helao_logging as logging  # get LOGGER from BaseAPI instance
from ...drivers.power_supply.power_supply_driver import PowerSupplyDriver, DriverStatus, DriverResponseType

global LOGGER
LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

from enum import Enum


class ConstantCurrentSquareWaveExecutor(Executor):
    driver: PowerSupplyDriver

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.poll_rate = 0.2  # pump events every 100 millisecond
            self.start_time = time.time()

            class PollFlag(Enum):
                PRE = "pre"
                OFF_0 = "off_0"
                ON = "on"
                OFF_1 = "off1"
            self.PollFlag=PollFlag
            self.poll_flag = PollFlag.PRE
            # link attrs for convenience
            self.action_params = self.active.action.action_params
            self.driver = self.active.driver

            # no external timer, event sink signals end of measurement
            self.duration = -1
        except Exception:
            LOGGER.error(f"Failed to initialize apply_voltage executor:", exc_info=True)
          # init should never return for any python class!

    async def _pre_exec(self):
        " connect to the power supply and set the output to on"
        resp = self.driver.connect()

        if resp.response != DriverResponseType.success:
            LOGGER.error(f"ConstantCurrentSquareWaveExecutor connect failed:", exc_info=True)
            return {"error": ErrorCodes.critical_error}
        resp = self.driver.set_output(True)
        if resp.response != DriverResponseType.success:
            LOGGER.error(f"ConstantCurrentSquareWaveExecutor set_output(True) failed:", exc_info=True)
            return {"error": ErrorCodes.critical_error}
        else:
            LOGGER.info(f"power supply is connected")
        return {"error": ErrorCodes.none}

    async def _exec(self):
        self.start_time = time.time()
        " apply the voltage to the power supply"
        
        resp = await self.driver.apply_current_async(current=0, sleep_time=0.1)
        resp = self.driver.set_output(output_on=False)
        if resp.response != DriverResponseType.success:
            LOGGER.warning("failed to set current to 0")

        self.poll_flag = self.PollFlag.OFF_0
        return {"error": ErrorCodes.none, }

    async def _poll(self):
        current_a = self.action_params['current']
        # to do  - speed up the polling and add an exit condition. make errored reads ok
        sleep_time = self.action_params["sleep_time"]
        sleep_time1 = self.action_params["sleep_time1"]
        sleep_time2 = self.action_params["sleep_time2"]
        
        time_now = time.time()- self.start_time

        if time_now >sleep_time2:

            resp = await self.driver.apply_current_async(current=0, sleep_time=0.1)
            resp = self.driver.set_output(output_on=False)
            LOGGER.warning('poll completed')
            return {"status": HloStatus.finished}
            
        elif time_now > sleep_time1:
            if self.poll_flag == self.PollFlag.ON:
                LOGGER.warning('changing poll flag from ON to OFF_1')
                resp = await self.driver.apply_current_async(current=0, sleep_time=0.1)
                time.sleep(0.1)
                resp = self.driver.set_output(output_on=False)
                if resp.response != DriverResponseType.success:
                    LOGGER.warning("failed to set current to 0")

                self.poll_flag = self.PollFlag.OFF_1
                time.sleep(0.1)
                if resp.response != DriverResponseType.success:
                        LOGGER.error(f"set output failed in poll:", exc_info=True) 
                LOGGER.info(f'poll, at time {time_now}, which is after the second time of {sleep_time1}')
            
            
                    
        
        elif time_now > sleep_time:
            if self.poll_flag == self.PollFlag.OFF_0:
                resp = self.driver.set_output(output_on=True)
                LOGGER.warning(f'output set for ON time, response is {resp.response}')
                time.sleep(0.1)
                if resp.response != DriverResponseType.success:
                        LOGGER.error(f"set output failed in poll:", exc_info=True) 
                resp = await self.driver.apply_current_async(current=current_a, sleep_time=0.1)   
                LOGGER.warning(f'Current for ON applied, response is {resp.response}')
                            
                self.poll_flag = self.PollFlag.ON
            LOGGER.info(f'poll, at time {time_now}, which is after {sleep_time}')

        else:

            LOGGER.info(f'poll, at time {time_now}, which is before {sleep_time}')

       
        resp=await self.driver.get_voltage_async(sleep_time=0.05)
        LOGGER.info(f'polled voltage is {resp.data['voltage_v']}')
        resp.data['t_s']=time_now
        return {'data': resp.data, "status": HloStatus.active}


        
            

                
            
        
            

        

        
    async def _post_exec(self):
        " disconnect from the power supply"
        resp = self.driver.disconnect()
        if resp.response != DriverResponseType.success:
            return {"error": ErrorCodes.critical_error}
        return {"error": ErrorCodes.none}
class ApplyVoltageExecutor(Executor):
    driver: PowerSupplyDriver

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.poll_rate = 5  # pump events every 100 millisecond
            self.start_time = time.time()

            # link attrs for convenience
            self.action_params = self.active.action.action_params
            self.driver = self.active.driver

            # no external timer, event sink signals end of measurement
            self.duration = -1
        except Exception:
            LOGGER.error(f"Failed to initialize apply_voltage executor:", exc_info=True)
          # init should never return for any python class!

    async def _pre_exec(self):
        " connect to the power supply and set the output to on"
        resp = self.driver.connect()
        if resp.response != DriverResponseType.success:
            return {"error": ErrorCodes.critical_error}
        resp = self.driver.set_output(True)
        if resp.response != DriverResponseType.success:
            return {"error": ErrorCodes.critical_error}
        return {"error": ErrorCodes.none}

    async def _exec(self):
        " apply the voltage to the power supply"
        voltage = self.action_params["voltage"]
        sleep_time = self.action_params["sleep_time"]
        resp = await self.driver.apply_voltage_async(voltage=voltage, sleep_time=sleep_time)
        resp = self.driver.set_output(output_on=True)
        if resp.response != DriverResponseType.success:
            return {"error": ErrorCodes.critical_error}
        return {"error": ErrorCodes.none}

    async def _poll(self):
        " poll the voltage of the power supply"
        resp = await self.driver.get_current_async(sleep_time=self.poll_rate)
        LOGGER.info(f"_poll response is {resp}")
        status = HloStatus.active
        if resp.response != DriverResponseType.success:
            status = HloStatus.errored
            return {"error": ErrorCodes.critical_error, "status": status}
        return {"error": ErrorCodes.none, "data": resp.data, "status": status}

    async def _post_exec(self):
        " disconnect from the power supply"
        resp = self.driver.disconnect()
        if resp.response != DriverResponseType.success:
            return {"error": ErrorCodes.critical_error}
        return {"error": ErrorCodes.none}


class SquareWaveExecutor(Executor):
    driver: PowerSupplyDriver

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.poll_rate = 5  # pump events every 100 millisecond
            self.start_time = time.time()

            # link attrs for convenience
            self.action_params = self.active.action.action_params
            self.driver = self.active.driver

            # no external timer, event sink signals end of measurement
            self.duration = -1
        except Exception:
            LOGGER.error(f"Failed to initialize apply_voltage executor:", exc_info=True)
          # init should never return for any python class!

    async def _pre_exec(self):
        " connect to the power supply and set the output to on"
        resp = self.driver.connect()
        if resp.response != DriverResponseType.success:
            return {"error": ErrorCodes.critical_error}
        resp = self.driver.set_output(True)
        if resp.response != DriverResponseType.success:
            return {"error": ErrorCodes.critical_error}
        return {"error": ErrorCodes.none}

    async def _exec(self):
        " apply the voltage to the power supply"
        voltage = self.action_params["voltage"]
        sleep_time = self.action_params["sleep_time"]
        try:
            resp = self.driver.set_output(output_on=False)
            time.sleep(sleep_time)
            if resp.response != DriverResponseType.success:
                LOGGER.error(f"SquareWaveExecutor set_output(output_on=False) failed:", exc_info=True)
                return {"error": ErrorCodes.critical_error}
            resp = self.driver.set_output(output_on=True)
            if resp.response != DriverResponseType.success:
                LOGGER.error(f"SquareWaveExecutor set_output(output_on=True) failed:", exc_info=True)
                return {"error": ErrorCodes.critical_error}
            resp = await self.driver.apply_voltage_async(voltage=voltage, sleep_time=sleep_time)
            if resp.response != DriverResponseType.success:
                LOGGER.error(f"SquareWaveExecutor apply_voltage_async failed:", exc_info=True)
                return {"error": ErrorCodes.critical_error}
            resp = self.driver.set_output(output_on=False)
            time.sleep(sleep_time)
            if resp.response != DriverResponseType.success:
                LOGGER.error(f"SquareWaveExecutor set_output(output_on=False) failed:", exc_info=True)
                return {"error": ErrorCodes.critical_error}
            
            return {"error": ErrorCodes.none}
        except Exception:
            LOGGER.error(f"SquareWaveExecutor failed:", exc_info=True)
            return {"error": ErrorCodes.critical_error}

    async def _poll(self):
        " poll the voltage of the power supply"
        try:
            resp = await self.driver.get_current_async(sleep_time=0.1)
            LOGGER.info(f"SquareWaveExecutor poll response: {resp}")
            if resp.response != DriverResponseType.success:
                LOGGER.error(f"SquareWaveExecutor poll response not success:", exc_info=True)
                return {"error": ErrorCodes.critical_error}
            
            return {"error": ErrorCodes.none, "data": resp.data}
        except Exception:
            LOGGER.error(f"SquareWaveExecutor poll failed:", exc_info=True)
            return {"error": ErrorCodes.critical_error}

    async def _post_exec(self):
        " disconnect from the power supply"
        resp = self.driver.disconnect()
        if resp.response != DriverResponseType.success:
            return {"error": ErrorCodes.critical_error}
        return {"error": ErrorCodes.none}



async def power_supply_dyn_endpoints(app: BaseAPI):
    server_key = app.base.server.server_name
    app.base.server_params["allow_concurrent_actions"] = False

    @app.post(f"/{server_key}/apply_voltage", tags=["action"])
    async def apply_voltage(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        voltage: float = 1.0,
        sleep_time: float = 0.05,
    ):
        """Apply voltage to the power supply asynchronously."""

        # Prepare json_data_keys for logging/serialization (for example: ["elapsed_time_s", "voltage_v", "current_a"])
        data_keys = ["elapsed_time_s", "voltage_v", "current_a"]  # Adjust as needed

        active = await app.base.setup_and_contain_action(
            json_data_keys=data_keys,
            file_type="power_supply_helao__file",
            hloheader=HloHeaderModel(
                action_name=action.action_name,
                column_headings=data_keys,
                optional={},
            ),
        )

        # Abbreviate action for clarity
        active.action.action_abbr = "APPLYVOLT"
        # Save parameters to action_params
        active.action.action_params["voltage"] = voltage
        active.action.action_params["sleep_time"] = sleep_time

        # Start executor
        executor = ApplyVoltageExecutor(active=active, oneoff=False)
        active_action_dict = active.start_executor(executor)
        

        return active_action_dict

    @app.post(f"/{server_key}/square_wave", tags=["action"])
    async def square_wave(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        voltage: float = 1.0,
        sleep_time: float = 0.05,
    ):
        """Apply voltage to the power supply asynchronously."""

        # Prepare json_data_keys for logging/serialization (for example: ["elapsed_time_s", "voltage_v", "current_a"])
        data_keys = ["elapsed_time_s", "voltage_v", "current_a"]  # Adjust as needed

        active = await app.base.setup_and_contain_action(
            json_data_keys=data_keys,
            file_type="power_supply_helao__file",
            hloheader=HloHeaderModel(
                action_name=action.action_name,
                column_headings=data_keys,
                optional={},
            ),
        )

        # Abbreviate action for clarity
        active.action.action_abbr = "SQUAREWAVE"
        # Save parameters to action_params
        active.action.action_params["voltage"] = voltage
        active.action.action_params["sleep_time"] = sleep_time

        # Start executor
        executor = SquareWaveExecutor(active=active, oneoff=False)
        active_action_dict = active.start_executor(executor)
        

        return active_action_dict


    @app.post(f"/{server_key}/constant_current_square_wave", tags=["action"])
    async def constant_current_square_wave(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        current: float = 0.01,
        sleep_time: float = 0.05,
        sleep_time1: float = 1,
        sleep_time2: float = 1,
    ):
        """Apply constant current square wave to the power supply asynchronously."""

        # Prepare json_data_keys for logging/serialization (for example: ["elapsed_time_s", "voltage_v", "current_a"])
        data_keys = ["elapsed_time_s", "voltage_v", "current_a"]  # Adjust as needed

        active = await app.base.setup_and_contain_action(
            json_data_keys=data_keys,
            file_type="power_supply_helao__file",
            hloheader=HloHeaderModel(
                action_name=action.action_name,
                column_headings=data_keys,
                optional={},
            ),
        )

        # Abbreviate action for clarity
        active.action.action_abbr = "SQUAREWAVE"
        # Save parameters to action_params
        active.action.action_params["current"] = current
        active.action.action_params["sleep_time"] = sleep_time
        active.action.action_params["sleep_time1"] = sleep_time1
        active.action.action_params["sleep_time2"] = sleep_time2

        # Start executor
        executor = ConstantCurrentSquareWaveExecutor(active=active, oneoff=False)
        active_action_dict = active.start_executor(executor)
        

        return active_action_dict


def makeApp(server_key):

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Power supply action server",
        version=0.1,
        driver_classes=[PowerSupplyDriver],
        dyn_endpoints=power_supply_dyn_endpoints,
    )

    @app.post("/stop_private", tags=["private"])
    def stop_private():
        """Calls driver stop method."""
        app.driver.disconnect()

    return app




