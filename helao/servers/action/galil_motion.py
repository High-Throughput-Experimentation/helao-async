# shell: uvicorn motion_server:app --reload
""" A FastAPI service definition for a motion/IO server, e.g. Galil.

The motion/IO service defines RESTful methods for sending commmands and retrieving data
from a motion controller driver class such as 'galil_driver' using
FastAPI. The methods provided by this service are not device-specific. Appropriate code
must be written in the driver class to ensure that the service methods are generic, i.e.
calls to 'motion.*' are not device-specific. Currently inherits configuration from
driver code, and hard-coded to use 'galil' class (see "__main__").

Motor calibration procedure for new instrument alignment:
Place alignment plate onto stage. 
In c:\inst_hlo\database\plate_calib, delete the instrument_calib.json 
---
Open the MOTOR bokeh
----
In MOTOR swagger:
After performing setmotionref, verify/edit the x-y offsets in the config file.
Execute run_aligner.
----
In MOTOR bokeh, click on green "go" button.
On the map click on the samples, move to the corresponding positions and "Add Pt"
After 3 points, click "Calc" and then "Sub"mit
---
Exit helao, in the plat_calib directory, rename the plate_6353_calib.json to instrument_calib.json.

Back in helao, redo the alignment for 6353 plate or any 4x6 plate or round.

For rounds, type any map 57 plate number and align to the sample numbers on the round alignment plate.

Exit helao and restart.

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
from helao.servers.base_api import BaseAPI
from helao.helpers.make_str_enum import make_str_enum
from helao.helpers.premodels import Action
from helao.core.error import ErrorCodes
from helao.helpers.config_loader import config_loader


async def galil_dyn_endpoints(app=None):
    server_key = app.base.server.server_name

    if app.driver.galil_enabled is True:

        dev_axis = app.server_params.get("axis_id", {})
        dev_axisitems = make_str_enum("axis_id", {key: key for key in dev_axis})

        if dev_axis:

            @app.post(f"/{server_key}/setmotionref", tags=["action"])
            async def setmotionref(action: Action = Body({}, embed=True)):
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

        @app.post(f"/{server_key}/reset_plate_alignment", tags=["action"])
        async def reset_plate_alignment(
            action: Action = Body({}, embed=True)
        ):
            active = await app.base.setup_and_contain_action()
            app.driver.reset_plate_transfermatrix()
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/load_plate_alignment", tags=["action"])
        async def load_plate_alignment(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            matrix: List = [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        ):
            active = await app.base.setup_and_contain_action()
            newmatrix = app.driver.update_plate_transfermatrix(
                newtransfermatrix=np.matrix(active.action.action_params["matrix"])
            )
            await active.enqueue_data_dflt(datadict={"matrix": newmatrix.tolist()})
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/run_aligner", tags=["action"])
        async def run_aligner(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            plateid: int = 6353,  # None
        ):
            """starts the plate aligning process, matrix is return when fully done"""
            A =  app.base.setup_action()
            active_dict = await app.driver.run_aligner(A)
            return active_dict

        @app.post(f"/{server_key}/stop_aligner", tags=["action"])
        async def stop_aligner(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
        ):
            """starts the plate aligning process, matrix is return when fully done"""
            active = await app.base.setup_and_contain_action()
            active.action.error_code = await app.driver.stop_aligner()
            finished_action = await active.finish()
            return finished_action.as_dict()

        # parse as {'M':json.dumps(np.matrix(M).tolist()),'platexy':json.dumps(np.array(platexy).tolist())}
        @app.post(f"/{server_key}/toMotorXY", tags=["action"])
        async def toMotorXY(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            platexy: Optional[str] = None,
        ):
            """Converts plate to motor xy"""
            active = await app.base.setup_and_contain_action(action_abbr="tomotorxy")
            await active.enqueue_data_dflt(
                datadict={
                    "motorxy": app.driver.transform.transform_platexy_to_motorxy(
                        **active.action.action_params
                    ).tolist()
                }
            )
            finished_action = await active.finish()
            return finished_action.as_dict()

        # parse as {'M':json.dumps(np.matrix(M).tolist()),'platexy':json.dumps(np.array(motorxy).tolist())}
        @app.post(f"/{server_key}/toPlateXY", tags=["action"])
        async def toPlateXY(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            motorxy: Optional[str] = None,
        ):
            """Converts motor to plate xy"""
            active = await app.base.setup_and_contain_action(action_abbr="toplatexy")
            await active.enqueue_data_dflt(
                datadict={
                    "platexy": app.driver.transform.transform_motorxy_to_platexy(
                        **active.action.action_params
                    ).tolist()
                }
            )
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/MxytoMPlate", tags=["action"])
        async def MxytoMPlate(
            action: Action = Body({}, embed=True),
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

            @app.post(f"/{server_key}/move", tags=["action"])
            async def move(
                action: Action = Body({}, embed=True),
                action_version: int = 1,
                d_mm: List[float] = [0, 0],
                axis: List[str] = ["x", "y"],
                speed: Optional[int] = None,
                mode: MoveModes = MoveModes.relative,
                transformation: TransformationModes = TransformationModes.motorxy,  # default, nothing to do
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

            @app.post(f"/{server_key}/easymove", tags=["action"])
            async def easymove(
                action: Action = Body({}, embed=True),
                action_version: int = 1,
                axis: dev_axisitems = None,
                d_mm: float = 0,
                speed: Optional[int] = None,
                mode: MoveModes = MoveModes.relative,
                transformation: TransformationModes = TransformationModes.motorxy,  # default, nothing to do
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

        @app.post(f"/{server_key}/disconnect", tags=["action"])
        async def disconnect(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
        ):
            active = await app.base.setup_and_contain_action(action_abbr="disconnect")
            await active.enqueue_data_dflt(datadict=await app.driver.motor_disconnect())
            finished_action = await active.finish()
            return finished_action.as_dict()

        if dev_axis:

            @app.post(f"/{server_key}/query_positions", tags=["action"])
            async def query_positions(
                action: Action = Body({}, embed=True),
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

            @app.post(f"/{server_key}/query_position", tags=["action"])
            async def query_position(
                action: Action = Body({}, embed=True),
                action_version: int = 1,
                # axis: Union[List[str], str] = None
                axis: dev_axisitems = None,
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

            @app.post(f"/{server_key}/query_moving", tags=["action"])
            async def query_moving(
                action: Action = Body({}, embed=True),
                action_version: int = 1,
                axis: Union[List[str], str] = None,
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

            @app.post(f"/{server_key}/axis_off", tags=["action"])
            async def axis_off(
                action: Action = Body({}, embed=True),
                action_version: int = 1,
                # axis: Union[List[str], str] = None
                axis: dev_axisitems = None,
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

            @app.post(f"/{server_key}/axis_on", tags=["action"])
            async def axis_on(
                action: Action = Body({}, embed=True),
                action_version: int = 1,
                axis: dev_axisitems = None,
            ):
                active = await app.base.setup_and_contain_action(action_abbr="axis_on")
                datadict = await app.driver.motor_on(**active.action.action_params)
                active.action.error_code = app.base.get_main_error(
                    datadict.get("err_code", ErrorCodes.unspecified)
                )
                await active.enqueue_data_dflt(datadict=datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

        @app.post(f"/{server_key}/solid_get_platemap", tags=["action"])
        async def solid_get_platemap(
            action: Action = Body({}, embed=True),
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

        @app.post(f"/{server_key}/solid_get_samples_xy", tags=["action"])
        async def solid_get_samples_xy(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            plate_id: Optional[int] = None,
            sample_no: Optional[int] = None,
        ):
            active = await app.base.setup_and_contain_action()
            datadict = await app.driver.solid_get_samples_xy(
                **active.action.action_params
            )
            platexy = datadict.get("platexy", [[None, None]])[0]
            if platexy[0] is None or platexy[1] is None:
                active.action.error_code = ErrorCodes.not_available
            active.action.action_params.update({"_platexy": platexy})
            await active.enqueue_data_dflt(datadict=datadict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/solid_get_builtin_specref", tags=["action"])
        async def solid_get_builtin_specref(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            specref_code: int = 1,
            ref_position_name: str = "builtin_ref_motorxy"
        ):
            active = await app.base.setup_and_contain_action()
            refxy = app.base.world_cfg[active.action.action_params["ref_position_name"]]
            active.action.action_params.update({"_refxy": refxy})
            await active.enqueue_data_dflt(datadict={"_refxy": refxy})
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/solid_get_nearest_specref", tags=["action"])
        async def solid_get_nearest_specref(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            plate_id: Optional[int] = None,
            sample_no: Optional[int] = None,
            specref_code: int = 1,
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

        @app.post(f"/{server_key}/stop", tags=["action"])
        async def stop(
            action: Action = Body({}, embed=True),
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

        @app.post(f"/{server_key}/reset", tags=["action"])
        async def reset(
            action: Action = Body({}, embed=True),
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

            @app.post(f"/{server_key}/z_move", tags=["action"])
            async def z_move(
                action: Action = Body({}, embed=True),
                action_version: int = 1,
                z_position: Zpos = "NA",
            ):
                """Move the z-axis motor to cell positions predefined in the config."""
                active = await app.base.setup_and_contain_action(action_abbr="z_move")
                z_arg = active.action.action_params["z_position"]
                if isinstance(z_arg, Zpos):
                    z_key = z_arg.value
                else:
                    z_key = z_arg
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
                else:
                    active.action.error_code = ErrorCodes.not_available
                finished_action = await active.finish()
                return finished_action.as_dict()


def makeApp(confPrefix, server_key, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Galil motion server",
        version=2.0,
        driver_class=Galil,
        dyn_endpoints=galil_dyn_endpoints,
    )

    return app
