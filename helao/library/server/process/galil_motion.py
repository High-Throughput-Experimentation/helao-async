# shell: uvicorn motion_server:app --reload
""" A FastAPI service definition for a motion/IO server, e.g. Galil.

The motion/IO service defines RESTful methods for sending commmands and retrieving data
from a motion controller driver class such as 'galil_driver' or 'galil_simulate' using
FastAPI. The methods provided by this service are not device-specific. Appropriate code
must be written in the driver class to ensure that the service methods are generic, i.e.
calls to 'motion.*' are not device-specific. Currently inherits configuration from
driver code, and hard-coded to use 'galil' class (see "__main__").
"""

import json
from importlib import import_module
from typing import Optional, List, Union
from fastapi import Request
from helao.library.driver.galil_driver import move_modes, transformation_mode
from helao.core.server import make_process_serv, setup_process
from helao.library.driver.galil_driver import galil


def makeApp(confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config

    app = make_process_serv(
        config, 
        servKey, 
        servKey, 
        "Galil motion server", 
        version=2.0, 
        driver_class=galil
    )


    @app.post(f"/{servKey}/setmotionref")
    async def setmotionref(request: Request):
        """Set the reference position for xyz by 
        (1) homing xyz, 
        (2) set abs zero, 
        (3) moving by center counts back, 
        (4) set abs zero"""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data({"setref": await app.driver.setaxisref()})
        finished_act = await active.finish()
        return finished_act.as_dict()


    # parse as {'M':json.dumps(np.matrix(M).tolist()),'platexy':json.dumps(np.array(platexy).tolist())}
    @app.post(f"/{servKey}/toMotorXY")
    async def transform_platexy_to_motorxy(request: Request, 
        platexy: Optional[str] = None
    ):
        """Converts plate to motor xy"""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        motorxy = app.driver.transform.transform_platexy_to_motorxy(**A.process_params)
        await active.enqueue_data(motorxy)
        finished_act = await active.finish()
        return finished_act.as_dict()


    # parse as {'M':json.dumps(np.matrix(M).tolist()),'platexy':json.dumps(np.array(motorxy).tolist())}
    @app.post(f"/{servKey}/toPlateXY")
    async def transform_motorxy_to_platexy(request: Request, 
        motorxy: Optional[str] = None
    ):
        """Converts motor to plate xy"""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        platexy = app.driver.transform.transform_motorxy_to_platexy(**A.process_params)
        await active.enqueue_data(platexy)
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/MxytoMPlate")
    async def MxytoMPlate(request: Request, 
        Mxy: Optional[str] = None
    ):
        """removes Minstr from Msystem to obtain Mplate for alignment"""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        Mplate = app.driver.transform.get_Mplate_Msystem(**A.process_params)
        await active.enqueue_data(Mplate)
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/download_alignmentmatrix")
    async def download_alignmentmatrix(request: Request, 
        Mxy: Optional[str] = None
    ):
        """Get current in use Alignment from motion server"""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        updsys = app.driver.transform.update_Mplatexy(**A.process_params)
        await active.enqueue_data(updsys)
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/upload_alignmentmatrix")
    async def upload_alignmentmatrix(request: Request):
        """Send new Alignment to motion server"""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        alignmentmatrix = app.driver.transform.get_Mplatexy().tolist()
        await active.enqueue_data(alignmentmatrix)
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/move")
    async def move(
        request: Request, 
        d_mm: Optional[List[float]] = [],
        axis: Optional[List[str]] = [],
        speed: Optional[int] = None,
        mode: Optional[move_modes] = "relative",
        transformation: Optional[transformation_mode] = "motorxy"  # default, nothing to do
    ):
        """Move a apecified {axis} by {d_mm} distance at {speed} using {mode} i.e. relative.
        Use Rx, Ry, Rz and not in combination with x,y,z only in motorxy.
        No z, Rx, Ry, Rz when platexy selected."""
        A = await setup_process(request)
        app.base.print_message(A.as_dict())
        active = await app.base.contain_process(A)
        move_response = await app.driver.motor_move(A)
        await active.enqueue_data(move_response)
        # if move_response.get("err_code", [])!=[0]:
        #     app.base.print_message(move_response)
        #     await active.set_error(f"{move_response['err_code']}")
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{servKey}/disconnect")
    async def disconnect(request: Request):
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(await app.driver.motor_disconnect())
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/query_positions")
    async def query_positions(request: Request):
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(await app.driver.query_axis_position(await app.driver.get_all_axis()))
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/query_position")
    async def query_position(request: Request, 
        axis: Optional[Union[List[str], str]] = None
    ):
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(await app.driver.query_axis_position(**A.process_params))
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/query_moving")
    async def query_moving(request: Request, 
        axis: Optional[Union[List[str], str]] = None
    ):
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(await app.driver.query_axis_moving(**A.process_params))
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/axis_off")
    async def axis_off(request: Request, axis: Optional[Union[List[str], str]] = None):
        # http://127.0.0.1:8001/motor/set/off?axis=x
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(await app.driver.motor_off(**A.process_params))
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/axis_on")
    async def axis_on(request: Request, axis: Optional[Union[List[str], str]] = None):
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(await app.driver.motor_on(**A.process_params))
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/stop")
    async def stop(request: Request):
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(
            await app.driver.motor_off(await app.driver.get_all_axis())
        )
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/reset")
    async def reset(request: Request):
        """resets galil device. only for emergency use!"""
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(
            await app.driver.motor_off(await app.driver.reset())
        )
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post(f"/{servKey}/estop")
    async def estop(request: Request, switch: Optional[bool] = True):
        # http://127.0.0.1:8001/motor/set/stop
        A = await setup_process(request)
        active = await app.base.contain_process(A)
        await active.enqueue_data(await app.driver.estop_axis(**A.process_params))
        finished_act = await active.finish()
        return finished_act.as_dict()


    @app.post("/shutdown")
    def post_shutdown():
        app.base.print_message(" ... motion shutdown")
        app.driver.shutdown_event()
    #    shutdown_event()


    @app.on_event("shutdown")
    def shutdown_event():
        global galil_motion_running
        galil_motion_running = False
        app.driver.shutdown_event()

    return app
