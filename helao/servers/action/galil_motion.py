# shell: uvicorn motion_server:app --reload
""" A FastAPI service definition for a motion/IO server, e.g. Galil.

The motion/IO service defines RESTful methods for sending commmands and retrieving data
from a motion controller driver class such as 'galil_driver' using
FastAPI. The methods provided by this service are not device-specific. Appropriate code
must be written in the driver class to ensure that the service methods are generic, i.e.
calls to 'motion.*' are not device-specific. Currently inherits configuration from
driver code, and hard-coded to use 'galil' class (see "__main__").
"""

__all__ = ["makeApp"]

from enum import Enum
from typing import Optional, List, Union
from fastapi import Body
import numpy as np


from helao.drivers.motion.galil_motion_driver import (
    MoveModes,
    TransformationModes,
    Galil,
)
from helao.servers.base import makeActionServ
from helao.helpers.make_str_enum import make_str_enum
from helao.helpers.premodels import Action
from helaocore.error import ErrorCodes
from helao.helpers.config_loader import config_loader


async def galil_dyn_endpoints(app=None):
    servKey = app.base.server.server_name

    if app.driver.galil_enabled is True:

        dev_axis = app.server_params.get("axis_id", {})
        dev_axisitems = make_str_enum("axis_id", {key: key for key in dev_axis})

        if dev_axis:

            @app.post(f"/{servKey}/setmotionref")
            async def setmotionref(action: Optional[Action] = Body({}, embed=True)):
                """Set the reference position for xyz by
                (1) homing xyz,
                (2) set abs zero,
                (3) moving by center counts back,
                (4) set abs zero"""
                active = await app.base.setup_and_contain_action(
                    action_abbr="setmotionref"
                )
                await active.enqueue_data_dflt(
                    datadict={"setref": await app.driver.setaxisref()}
                )
                finished_action = await active.finish()
                return finished_action.as_dict()

        @app.post(f"/{servKey}/reset_plate_alignment", tags=["public_aligner"])
        async def reset_plate_alignment(
            action: Optional[Action] = Body({}, embed=True)
        ):
            active = await app.base.setup_and_contain_action()
            app.driver.reset_plate_transfermatrix()
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{servKey}/load_plate_alignment", tags=["public_aligner"])
        async def load_plater_alignment(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            matrix: Optional[List] = [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        ):
            active = await app.base.setup_and_contain_action()
            newmatrix = app.driver.update_plate_transfermatrix(
                newtransfermatrix=np.matrix(active.action.action_params["matrix"])
            )
            await active.enqueue_data_dflt(datadict={"matrix": newmatrix.tolist()})
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{servKey}/run_aligner", tags=["public_aligner"])
        async def run_aligner(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            plateid: Optional[int] = 6353,  # None
        ):
            """starts the plate aligning process, matrix is return when fully done"""
            A = await app.base.setup_action()
            active_dict = await app.driver.run_aligner(A)
            return active_dict

        @app.post(f"/{servKey}/stop_aligner", tags=["public_aligner"])
        async def stop_aligner(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
        ):
            """starts the plate aligning process, matrix is return when fully done"""
            active = await app.base.setup_and_contain_action()
            active.action.error_code = await app.driver.stop_aligner()
            finished_action = await active.finish()
            return finished_action.as_dict()

        # parse as {'M':json.dumps(np.matrix(M).tolist()),'platexy':json.dumps(np.array(platexy).tolist())}
        @app.post(f"/{servKey}/toMotorXY")
        async def transform_platexy_to_motorxy(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            platexy: Optional[str] = None,
        ):
            """Converts plate to motor xy"""
            active = await app.base.setup_and_contain_action(action_abbr="tomotorxy")
            await active.enqueue_data_dflt(
                datadict={
                    "motorxy": app.driver.transform.transform_platexy_to_motorxy(
                        **active.action.action_params
                    )
                }
            )
            finished_action = await active.finish()
            return finished_action.as_dict()

        # parse as {'M':json.dumps(np.matrix(M).tolist()),'platexy':json.dumps(np.array(motorxy).tolist())}
        @app.post(f"/{servKey}/toPlateXY")
        async def transform_motorxy_to_platexy(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            motorxy: Optional[str] = None,
        ):
            """Converts motor to plate xy"""
            active = await app.base.setup_and_contain_action(action_abbr="toplatexy")
            await active.enqueue_data_dflt(
                datadict={
                    "platexy": app.driver.transform.transform_motorxy_to_platexy(
                        **active.action.action_params
                    )
                }
            )
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{servKey}/MxytoMPlate")
        async def MxytoMPlate(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            Mxy: Optional[str] = None,
        ):
            """removes Minstr from Msystem to obtain Mplate for alignment"""
            active = await app.base.setup_and_contain_action(action_abbr="mxytomplate")
            await active.enqueue_data_dflt(
                datadict={
                    "mplate": app.driver.transform.get_Mplate_Msystem(
                        **active.action.action_params
                    )
                }
            )
            finished_action = await active.finish()
            return finished_action.as_dict()

        if dev_axis:

            @app.post(f"/{servKey}/move")
            async def move(
                action: Optional[Action] = Body({}, embed=True),
                action_version: int = 1,
                d_mm: Optional[List[float]] = [0, 0],
                axis: Optional[List[str]] = ["x", "y"],
                speed: Optional[int] = None,
                mode: Optional[MoveModes] = "relative",
                transformation: Optional[
                    TransformationModes
                ] = "motorxy",  # default, nothing to do
            ):
                """Move a specified {axis} by {d_mm} distance at {speed} using {mode} i.e. relative.
                Use Rx, Ry, Rz and not in combination with x,y,z only in motorxy.
                No z, Rx, Ry, Rz when platexy selected."""
                active = await app.base.setup_and_contain_action(action_abbr="move")
                datadict = await app.driver.motor_move(active)
                active.action.error_code = app.base.get_main_error(
                    datadict.get("err_code", ErrorCodes.unspecified)
                )
                await active.enqueue_data_dflt(datadict=datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

        if dev_axis:

            @app.post(f"/{servKey}/easymove")
            async def easymove(
                action: Optional[Action] = Body({}, embed=True),
                action_version: int = 1,
                axis: Optional[dev_axisitems] = None,
                d_mm: Optional[float] = 0,
                speed: Optional[int] = None,
                mode: Optional[MoveModes] = "relative",
                transformation: Optional[
                    TransformationModes
                ] = "motorxy",  # default, nothing to do
            ):
                """Move a specified {axis} by {d_mm} distance at {speed} using {mode} i.e. relative.
                Use Rx, Ry, Rz and not in combination with x,y,z only in motorxy.
                No z, Rx, Ry, Rz when platexy selected."""
                active = await app.base.setup_and_contain_action(action_abbr="move")
                datadict = await app.driver.motor_move(active)
                active.action.error_code = app.base.get_main_error(
                    datadict.get("err_code", ErrorCodes.unspecified)
                )
                await active.enqueue_data_dflt(datadict=datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

        @app.post(f"/{servKey}/disconnect")
        async def disconnect(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
        ):
            active = await app.base.setup_and_contain_action(action_abbr="disconnect")
            await active.enqueue_data_dflt(datadict=await app.driver.motor_disconnect())
            finished_action = await active.finish()
            return finished_action.as_dict()

        if dev_axis:

            @app.post(f"/{servKey}/query_positions")
            async def query_positions(
                action: Optional[Action] = Body({}, embed=True),
                action_version: int = 1,
            ):
                active = await app.base.setup_and_contain_action(
                    action_abbr="query_position"
                )
                await active.enqueue_data_dflt(
                    datadict=await app.driver.query_axis_position(
                        axis=app.driver.get_all_axis()
                    )
                )
                finished_action = await active.finish()
                return finished_action.as_dict()

        if dev_axis:

            @app.post(f"/{servKey}/query_position")
            async def query_position(
                action: Optional[Action] = Body({}, embed=True),
                action_version: int = 1,
                # axis: Optional[Union[List[str], str]] = None
                axis: Optional[dev_axisitems] = None,
            ):
                active = await app.base.setup_and_contain_action(
                    action_abbr="query_position"
                )
                await active.enqueue_data_dflt(
                    datadict=await app.driver.query_axis_position(
                        **active.action.action_params
                    )
                )
                finished_action = await active.finish()
                return finished_action.as_dict()

        if dev_axis:

            @app.post(f"/{servKey}/query_moving")
            async def query_moving(
                action: Optional[Action] = Body({}, embed=True),
                action_version: int = 1,
                axis: Optional[Union[List[str], str]] = None,
            ):
                active = await app.base.setup_and_contain_action(
                    action_abbr="query_moving"
                )
                datadict = await app.driver.query_axis_moving(
                    **active.action.action_params
                )
                active.action.error_code = app.base.get_main_error(
                    datadict.get("err_code", ErrorCodes.unspecified)
                )
                await active.enqueue_data_dflt(datadict=datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

        if dev_axis:

            @app.post(f"/{servKey}/axis_off")
            async def axis_off(
                action: Optional[Action] = Body({}, embed=True),
                action_version: int = 1,
                # axis: Optional[Union[List[str], str]] = None
                axis: Optional[dev_axisitems] = None,
            ):
                # http://127.0.0.1:8001/motor/set/off?axis=x
                active = await app.base.setup_and_contain_action(action_abbr="axis_off")
                datadict = await app.driver.motor_off(**active.action.action_params)
                active.action.error_code = app.base.get_main_error(
                    datadict.get("err_code", ErrorCodes.unspecified)
                )
                await active.enqueue_data_dflt(datadict=datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

        if dev_axis:

            @app.post(f"/{servKey}/axis_on")
            async def axis_on(
                action: Optional[Action] = Body({}, embed=True),
                action_version: int = 1,
                axis: Optional[dev_axisitems] = None,
            ):
                active = await app.base.setup_and_contain_action(action_abbr="axis_on")
                datadict = await app.driver.motor_on(**active.action.action_params)
                active.action.error_code = app.base.get_main_error(
                    datadict.get("err_code", ErrorCodes.unspecified)
                )
                await active.enqueue_data_dflt(datadict=datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

        @app.post(f"/{servKey}/solid_get_platemap")
        async def solid_get_platemap(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            plate_id: Optional[int] = None,
        ):
            active = await app.base.setup_and_contain_action()
            datadict = await app.driver.solid_get_platemap(
                **active.action.action_params
            )
            await active.enqueue_data_dflt(datadict=datadict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{servKey}/solid_get_samples_xy")
        async def solid_get_samples_xy(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            plate_id: Optional[int] = None,
            sample_no: Optional[int] = None,
        ):
            active = await app.base.setup_and_contain_action()
            datadict = await app.driver.solid_get_samples_xy(
                **active.action.action_params
            )
            platexy = list(datadict.get("platexy", [(None, None)])[0])
            active.action.action_params.update({"_platexy": platexy})
            await active.enqueue_data_dflt(datadict=datadict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{servKey}/solid_get_builtin_specref")
        async def solid_get_builtin_specref(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            specref_code: Optional[int] = 1,
        ):
            active = await app.base.setup_and_contain_action()
            refxy = app.base.world_cfg["builtin_ref_motorxy"]
            active.action.action_params.update({"_refxy": refxy})
            await active.enqueue_data_dflt(datadict={"_refxy": refxy})
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{servKey}/solid_get_nearest_specref")
        async def solid_get_nearest_specref(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
            plate_id: Optional[int] = None,
            sample_no: Optional[int] = None,
            specref_code: Optional[int] = 1,
        ):
            active = await app.base.setup_and_contain_action()
            datadict = await app.driver.solid_get_platemap(
                active.action.action_params["plate_id"]
            )
            pmdlist = datadict["platemap"][0]
            pmkeys = ["sample_no", "x", "y"]

            smpd = [
                d
                for d in pmdlist
                if d["sample_no"] == active.action.action_params["sample_no"]
            ][0]
            refarr = np.array(
                [
                    [d[k] for k in pmkeys]
                    for d in pmdlist
                    if d["code"] == active.action.action_params["specref_code"]
                ]
            )
            print(refarr.shape)
            print(refarr[:2])
            refnos, refxys = refarr[:, 0], refarr[:, 1:]
            nearest = np.argmin(
                ((refxys - np.array([smpd["x"], smpd["y"]]).reshape(1, 2)) ** 2).sum(
                    axis=1
                )
            )
            refno = refnos[nearest]
            refxy = list(refxys[nearest])
            active.action.action_params.update({"_refno": refno, "_refxy": refxy})
            await active.enqueue_data_dflt(datadict={"_refno": refno, "_refxy": refxy})
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{servKey}/stop")
        async def stop(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
        ):
            active = await app.base.setup_and_contain_action(action_abbr="stop")
            datadict = await app.driver.motor_off(axis=app.driver.get_all_axis())
            active.action.error_code = app.base.get_main_error(
                datadict.get("err_code", ErrorCodes.unspecified)
            )
            await active.enqueue_data_dflt(datadict=datadict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{servKey}/reset")
        async def reset(
            action: Optional[Action] = Body({}, embed=True),
            action_version: int = 1,
        ):
            """FOR EMERGENCY USE ONLY!
            resets galil device.
            """
            active = await app.base.setup_and_contain_action(action_abbr="reset")
            await active.enqueue_data_dflt(datadict={"reset": await app.driver.reset()})
            finished_action = await active.finish()
            return finished_action.as_dict()

        if dev_axis:

            zpos_dict = app.base.server_params.get("z_height_mm", {})
            zpos_dict["NA"] = None
            Zpos = Enum("Zpos", {k: k for k in zpos_dict.keys()})

            @app.post(f"/{servKey}/z_move")
            async def z_move(
                action: Optional[Action] = Body({}, embed=True),
                action_version: int = 1,
                z_position: Zpos = Zpos.NA,
            ):
                """Move the z-axis motor to cell positions predefined in the config."""
                active = await app.base.setup_and_contain_action(action_abbr="z_move")
                z_key = active.action.action_params["z_position"].value
                z_value = zpos_dict.get(z_key, "NA")
                if z_key != "NA":
                    active.action.action_params.update(
                        {
                            "d_mm": [z_value],
                            "axis": ["z"],
                            "mode": MoveModes.absolute,
                            "transofmration": TransformationModes.instrxy,
                        }
                    )
                    datadict = await app.driver.motor_move(active)
                    active.action.error_code = app.base.get_main_error(
                        datadict.get("err_code", ErrorCodes.unspecified)
                    )
                    await active.enqueue_data_dflt(datadict=datadict)
                    finished_action = await active.finish()
                    return finished_action.as_dict()
                else:
                    active.action.action_error_code = ErrorCodes.not_available
                    return active.action.clean_dict()


def makeApp(confPrefix, servKey, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = makeActionServ(
        config=config,
        server_key=servKey,
        server_title=servKey,
        description="Galil motion server",
        version=2.0,
        driver_class=Galil,
        dyn_endpoints=galil_dyn_endpoints,
    )

    return app
