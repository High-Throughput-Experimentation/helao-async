# shell: uvicorn motion_server:app --reload
""" A FastAPI service definition for a motion/IO server, e.g. Galil.

The motion/IO service defines RESTful methods for sending commmands and retrieving data
from a motion controller driver class such as 'galil_driver' or 'galil_simulate' using
FastAPI. The methods provided by this service are not device-specific. Appropriate code
must be written in the driver class to ensure that the service methods are generic, i.e.
calls to 'motion.*' are not device-specific. Currently inherits configuration from
driver code, and hard-coded to use 'galil' class (see "__main__").
"""

__all__ = ["makeApp"]


from importlib import import_module
from typing import Optional, List, Union
from fastapi import Body
import numpy as np


from helao.library.driver.galil_motion_driver import (
                                                      MoveModes, 
                                                      TransformationModes,
                                                      Galil
                                                     )
from helaocore.server.base import makeActionServ
from helaocore.helper.make_str_enum import make_str_enum
from helaocore.schema import Action
from helaocore.error import ErrorCodes



async def galil_dyn_endpoints(app = None):
    servKey = app.base.server.server_name

    if app.driver.galil_enabled is True:

        dev_axis = app.server_params.get("axis_id",dict())
        dev_axisitems = make_str_enum("axis_id",{key:key for key in dev_axis})
    
        if dev_axis:
            @app.post(f"/{servKey}/setmotionref")
            async def setmotionref(
                                   action: Optional[Action] = \
                                           Body({}, embed=True)
                                  ):
                """Set the reference position for xyz by 
                (1) homing xyz, 
                (2) set abs zero, 
                (3) moving by center counts back, 
                (4) set abs zero"""
                active = await app.base.setup_and_contain_action(
                                                  action_abbr = "setmotionref"
                )
                await active.enqueue_data_dflt(datadict = \
                   {"setref": await app.driver.setaxisref()})
                finished_action = await active.finish()
                return finished_action.as_dict()
    
    
        @app.post(f"/{servKey}/reset_alignment", tags=["public_aligner"])
        async def reset_alignment(
                                  action: Optional[Action] = \
                                          Body({}, embed=True)
                                 ):
                active = await app.base.setup_and_contain_action()
                app.driver.reset_transfermatrix()
                finished_action = await active.finish()
                return finished_action.as_dict()
    
    
        @app.post(f"/{servKey}/load_alignment", tags=["public_aligner"])
        async def load_alignment(
                                  action: Optional[Action] = \
                                          Body({}, embed=True),
                                  matrix: Optional[List] = [
                                                            [1,0,0],
                                                            [0,1,0],
                                                            [0,0,1]
                                                           ]
                                 ):
                active = await app.base.setup_and_contain_action()
                newmatrix = app.driver.update_transfermatrix(newtransfermatrix = \
                                         np.matrix(active.action.action_params["matrix"])
                )
                await active.enqueue_data_dflt(datadict = \
                   {"matrix": newmatrix.tolist()})
                finished_action = await active.finish()
                return finished_action.as_dict()
    
    
        @app.post(f"/{servKey}/run_aligner", tags=["public_aligner"])
        async def run_aligner(
                                               action: Optional[Action] = \
                                                       Body({}, embed=True),
                                               plateid: Optional[int] = None
                                              ):
            """starts the plate aligning process, matrix is return when fully done"""
            A = await app.base.setup_action()
            active_dict = await app.driver.run_aligner(A)
            return active_dict
    
    
        # parse as {'M':json.dumps(np.matrix(M).tolist()),'platexy':json.dumps(np.array(platexy).tolist())}
        @app.post(f"/{servKey}/toMotorXY")
        async def transform_platexy_to_motorxy(
                                               action: Optional[Action] = \
                                                       Body({}, embed=True),
                                               platexy: Optional[str] = None
                                              ):
            """Converts plate to motor xy"""
            active = await app.base.setup_and_contain_action(
                                              action_abbr = "tomotorxy"
            )
            await active.enqueue_data_dflt(datadict = \
               {"motorxy": app.driver.transform.transform_platexy_to_motorxy(**active.action.action_params)})
            finished_action = await active.finish()
            return finished_action.as_dict()
    
    
        # parse as {'M':json.dumps(np.matrix(M).tolist()),'platexy':json.dumps(np.array(motorxy).tolist())}
        @app.post(f"/{servKey}/toPlateXY")
        async def transform_motorxy_to_platexy(
                                               action: Optional[Action] = \
                                                       Body({}, embed=True),
                                               motorxy: Optional[str] = None
                                              ):
            """Converts motor to plate xy"""
            active = await app.base.setup_and_contain_action(
                                              action_abbr = "toplatexy"
            )
            await active.enqueue_data_dflt(datadict = \
               {"platexy": app.driver.transform.transform_motorxy_to_platexy(**active.action.action_params)})
            finished_action = await active.finish()
            return finished_action.as_dict()
    
    
        @app.post(f"/{servKey}/MxytoMPlate")
        async def MxytoMPlate(
                              action: Optional[Action] = \
                                      Body({}, embed=True),
                              Mxy: Optional[str] = None
                             ):
            """removes Minstr from Msystem to obtain Mplate for alignment"""
            active = await app.base.setup_and_contain_action(
                                              action_abbr = "mxytomplate"
            )
            await active.enqueue_data_dflt(datadict = \
               {"mplate": app.driver.transform.get_Mplate_Msystem(**active.action.action_params)})
            finished_action = await active.finish()
            return finished_action.as_dict()
    
    
        @app.post(f"/{servKey}/download_alignmentmatrix")
        async def download_alignmentmatrix(
                                           action: Optional[Action] = \
                                                   Body({}, embed=True),
                                          ):
            """Get current in use Alignment from motion server
               returns the xy part of the platecalibration.
            """
            active = await app.base.setup_and_contain_action(
                                              action_abbr = "get_mplatexy"
            )
            await active.enqueue_data_dflt(datadict = \
               {"mplatexy": app.driver.transform.get_Mplatexy()})
            finished_action = await active.finish()
            return finished_action.as_dict()
    
    
        @app.post(f"/{servKey}/upload_alignmentmatrix")
        async def upload_alignmentmatrix(
                                         action: Optional[Action] = \
                                                 Body({}, embed=True),
                                         Mxy: Optional[str] = None
                                        ):
            """Send new Alignment to motion server.
               Updates the xy part of the plate calibration.
            """
            active = await app.base.setup_and_contain_action(
                                              action_abbr = "upload_mplatexy"
            )
            await active.enqueue_data_dflt(datadict = \
               {"uploaded": app.driver.transform.update_Mplatexy(**active.action.action_params)})
            finished_action = await active.finish()
            return finished_action.as_dict()
    
    
        if dev_axis:
            @app.post(f"/{servKey}/move")
            async def move(
                           action: Optional[Action] = \
                                   Body({}, embed=True),
                           d_mm: Optional[List[float]] = [0,0],
                           axis: Optional[List[str]] = ["x","y"],
                           speed: Optional[int] = None,
                           mode: Optional[MoveModes] = "relative",
                           transformation: Optional[TransformationModes] = "motorxy"  # default, nothing to do
                          ):
                """Move a apecified {axis} by {d_mm} distance at {speed} using {mode} i.e. relative.
                Use Rx, Ry, Rz and not in combination with x,y,z only in motorxy.
                No z, Rx, Ry, Rz when platexy selected."""
                active = await app.base.setup_and_contain_action(
                                                  action_abbr = "move"
                )
                datadict = await app.driver.motor_move(active)
                active.action.error_code = \
                    app.base.get_main_error(
                        datadict.get("err_code", ErrorCodes.unspecified)
                    )
                await active.enqueue_data_dflt(datadict = datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()
    
    
        if dev_axis:
            @app.post(f"/{servKey}/easymove")
            async def easymove(
                               action: Optional[Action] = \
                                       Body({}, embed=True),
                               axis: Optional[dev_axisitems] = None,
                               d_mm: Optional[float] = 0,
                               speed: Optional[int] = None,
                               mode: Optional[MoveModes] = "relative",
                               transformation: Optional[TransformationModes] = "motorxy"  # default, nothing to do
                              ):
                """Move a apecified {axis} by {d_mm} distance at {speed} using {mode} i.e. relative.
                Use Rx, Ry, Rz and not in combination with x,y,z only in motorxy.
                No z, Rx, Ry, Rz when platexy selected."""
                active = await app.base.setup_and_contain_action(
                                                  action_abbr = "move"
                )
                datadict = await app.driver.motor_move(active)
                active.action.error_code = \
                    app.base.get_main_error(
                        datadict.get("err_code", ErrorCodes.unspecified)
                    )
                await active.enqueue_data_dflt(datadict = datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()
    
    
        @app.post(f"/{servKey}/disconnect")
        async def disconnect(
                             action: Optional[Action] = \
                                     Body({}, embed=True),
                            ):
            active = await app.base.setup_and_contain_action(
                                              action_abbr = "disconnect"
            )
            await active.enqueue_data_dflt(datadict = \
               await app.driver.motor_disconnect())
            finished_action = await active.finish()
            return finished_action.as_dict()
    
    
        if dev_axis:
            @app.post(f"/{servKey}/query_positions")
            async def query_positions(
                                      action: Optional[Action] = \
                                              Body({}, embed=True),
                                     ):
                active = await app.base.setup_and_contain_action(
                                                  action_abbr = "query_position"
                )
                await active.enqueue_data_dflt(datadict = \
                   await app.driver.query_axis_position(app.driver.get_all_axis()))
                finished_action = await active.finish()
                return finished_action.as_dict()
    
    
        if dev_axis:
            @app.post(f"/{servKey}/query_position")
            async def query_position(
                                     action: Optional[Action] = \
                                             Body({}, embed=True),
                                     # axis: Optional[Union[List[str], str]] = None
                                     axis: Optional[dev_axisitems] = None
            ):
                active = await app.base.setup_and_contain_action(
                                                  action_abbr = "query_position"
                )
                await active.enqueue_data_dflt(datadict = \
                   await app.driver.query_axis_position(**active.action.action_params))
                finished_action = await active.finish()
                return finished_action.as_dict()
    
    
        if dev_axis:
            @app.post(f"/{servKey}/query_moving")
            async def query_moving(
                                   action: Optional[Action] = \
                                           Body({}, embed=True),
                                   axis: Optional[Union[List[str], str]] = None
                                  ):
                active = await app.base.setup_and_contain_action(
                                                  action_abbr = "query_moving"
                )
                datadict = await app.driver.query_axis_moving(**active.action.action_params)
                active.action.error_code = \
                    app.base.get_main_error(
                        datadict.get("err_code", ErrorCodes.unspecified)
                    )
                await active.enqueue_data_dflt(datadict = datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()
    
    
        if dev_axis:
            @app.post(f"/{servKey}/axis_off")
            async def axis_off(
                               action: Optional[Action] = \
                                       Body({}, embed=True),
                               # axis: Optional[Union[List[str], str]] = None
                               axis: Optional[dev_axisitems] = None
                              ):
                # http://127.0.0.1:8001/motor/set/off?axis=x
                active = await app.base.setup_and_contain_action(
                                                  action_abbr = "axis_off"
                )
                datadict = \
                    await app.driver.motor_off(**active.action.action_params)
                active.action.error_code = \
                    app.base.get_main_error(
                        datadict.get("err_code", ErrorCodes.unspecified)
                    )
                await active.enqueue_data_dflt(datadict = datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()
    
    
        if dev_axis:
            @app.post(f"/{servKey}/axis_on")
            async def axis_on(
                              action: Optional[Action] = \
                                      Body({}, embed=True),
                              # axis: Optional[Union[List[str], str]] = None
                              axis: Optional[dev_axisitems] = None
                             ):
                active = await app.base.setup_and_contain_action(
                                                  action_abbr = "axis_on"
                )
                datadict = \
                    await app.driver.motor_on(**active.action.action_params)
                active.action.error_code = \
                    app.base.get_main_error(
                        datadict.get("err_code", ErrorCodes.unspecified)
                    )
                await active.enqueue_data_dflt(datadict = datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()
    
    
    
        @app.post(f"/{servKey}/stop")
        async def stop(
                       action: Optional[Action] = \
                               Body({}, embed=True),
                      ):
            active = await app.base.setup_and_contain_action(
                                              action_abbr = "stop"
            )
            datadict = \
                await app.driver.motor_off(axis = app.driver.get_all_axis())
            active.action.error_code = \
                app.base.get_main_error(
                    datadict.get("err_code", ErrorCodes.unspecified)
                )
            await active.enqueue_data_dflt(datadict = datadict)
            finished_action = await active.finish()
            return finished_action.as_dict()
    
    
        @app.post(f"/{servKey}/reset")
        async def reset(
                        action: Optional[Action] = \
                                Body({}, embed=True),
                       ):
            """FOR EMERGENCY USE ONLY!
               resets galil device. 
            """
            active = await app.base.setup_and_contain_action(
                                              action_abbr = "reset"
            )
            await active.enqueue_data_dflt(datadict = \
                                           {"reset":await app.driver.reset()})
            finished_action = await active.finish()
            return finished_action.as_dict()


def makeApp(confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config

    app = makeActionServ(
        config=config, 
        server_key=servKey, 
        server_title=servKey, 
        description="Galil motion server", 
        version=2.0, 
        driver_class=Galil,
        dyn_endpoints=galil_dyn_endpoints
    )
    

    @app.post("/shutdown")
    def post_shutdown():
        app.base.print_message("motion shutdown")
        app.driver.shutdown_event()
    #    shutdown_event()


    @app.on_event("shutdown")
    def shutdown_event():
        app.driver.shutdown_event()

    return app
