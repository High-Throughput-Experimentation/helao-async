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


from helao.library.driver.galil_motion_driver import (
                                                      move_modes, 
                                                      transformation_mode,
                                                      galil
                                                     )
from helaocore.server.base import makeActionServ
from helaocore.helper.make_str_enum import make_str_enum
from helaocore.schema import Action
from helaocore.error import ErrorCodes

def makeApp(confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config

    app = makeActionServ(
        config=config, 
        server_key=servKey, 
        server_title=servKey, 
        description="Galil motion server", 
        version=2.0, 
        driver_class=galil
    )
    
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
                                              json_data_keys = ["setref"],
                                              action_abbr = "setmotionref"
            )
            await active.enqueue_data_dflt(datadict = \
               {"setref": await app.driver.setaxisref()})
            finished_action = await active.finish()
            return finished_action.as_dict()


    # parse as {'M':json.dumps(np.matrix(M).tolist()),'platexy':json.dumps(np.array(platexy).tolist())}
    @app.post(f"/{servKey}/toMotorXY")
    async def transform_platexy_to_motorxy(
                                           action: Optional[Action] = \
                                                   Body({}, embed=True),
                                           platexy: Optional[str] = None
                                          ):
        """Converts plate to motor xy"""
        active = await app.base.setup_and_contain_action(
                                          json_data_keys = ["motorxy"],
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
                                          json_data_keys = ["platexy"],
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
                                          json_data_keys = ["mplate"],
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
                                          json_data_keys = ["mplatexy"],
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
                                          json_data_keys = ["uploaded"],
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
                       mode: Optional[move_modes] = "relative",
                       transformation: Optional[transformation_mode] = "motorxy"  # default, nothing to do
                      ):
            """Move a apecified {axis} by {d_mm} distance at {speed} using {mode} i.e. relative.
            Use Rx, Ry, Rz and not in combination with x,y,z only in motorxy.
            No z, Rx, Ry, Rz when platexy selected."""
            active = await app.base.setup_and_contain_action(
                                              json_data_keys = [
                                                                "moved_axis",
                                                                "speed",
                                                                "accepted_rel_dist",
                                                                "supplied_rel_dist",
                                                                "err_dist",
                                                                "err_code",
                                                                "counts"
                                                               ],
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
                           mode: Optional[move_modes] = "relative",
                           transformation: Optional[transformation_mode] = "motorxy"  # default, nothing to do
                          ):
            """Move a apecified {axis} by {d_mm} distance at {speed} using {mode} i.e. relative.
            Use Rx, Ry, Rz and not in combination with x,y,z only in motorxy.
            No z, Rx, Ry, Rz when platexy selected."""
            active = await app.base.setup_and_contain_action(
                                              json_data_keys = [
                                                                "moved_axis",
                                                                "speed",
                                                                "accepted_rel_dist",
                                                                "supplied_rel_dist",
                                                                "err_dist",
                                                                "err_code",
                                                                "counts"
                                                               ],
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
                                          json_data_keys = ["connection"],
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
                                              json_data_keys = [
                                                                "ax",
                                                                "position"
                                                               ],
                                              action_abbr = "query_position"
            )
            await active.enqueue_data_dflt(datadict = \
               await app.driver.query_axis_position(await app.driver.get_all_axis()))
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
                                              json_data_keys = [
                                                                "ax",
                                                                "position"
                                                               ],
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
                                              json_data_keys = [
                                                                "motor_status",
                                                                "err_code"
                                                               ],
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
                                              json_data_keys = [
                                                                "motor_status",
                                                                "ax",
                                                                "position",
                                                                "err_code"
                                                               ],
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
                                              json_data_keys = [
                                                                "motor_status",
                                                                "ax",
                                                                "position",
                                                                "err_code"
                                                               ],
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
                                          json_data_keys = [
                                                            "motor_status",
                                                            "ax",
                                                            "position",
                                                            "err_code"
                                                           ],
                                          action_abbr = "stop"
        )
        datadict = \
            await app.driver.motor_off(axis = await app.driver.get_all_axis())
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
                                          json_data_keys = [
                                                            "reset",
                                                           ],
                                          action_abbr = "reset"
        )
        await active.enqueue_data_dflt(datadict = \
                                       {"reset":await app.driver.reset()})
        finished_action = await active.finish()
        return finished_action.as_dict()


    @app.post("/shutdown")
    def post_shutdown():
        app.base.print_message("motion shutdown")
        app.driver.shutdown_event()
    #    shutdown_event()


    @app.on_event("shutdown")
    def shutdown_event():
        global galil_motion_running
        galil_motion_running = False
        app.driver.shutdown_event()

    return app
