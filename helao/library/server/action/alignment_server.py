
__all__ = ["makeApp"]


# Instrument Alignment server
# talks with specified motor server and 
# provides input to separate user interface server

# TODO: add checks against align.aligning

from typing import Optional, List, Union
from importlib import import_module
from fastapi import Request
from helaocore.server import makeActionServ, setup_action
from helao.library.driver.alignment_driver import aligner
from helao.library.driver.galil_driver import move_modes


def makeApp(confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config
    C = config["servers"]
    S = C[servKey]

    app = makeActionServ(
        config,
        servKey,
        servKey,
        "Instrument alignment server",
        version=2.0,
        driver_class=aligner,
    )

    # only for alignment bokeh server
    @app.post(f"/{servKey}/private/align_get_position")
    async def private_align_get_position(request: Request):
        """Return the current motor position"""
        # gets position of all axis, but use only axis 
        # defined in aligner server params
        # can also easily be 3d axis 
        # (but not implemented yet so only 2d for now)
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["data"],
        )
        await active.enqueue_data_dflt(datadict = \
           {"data": await app.driver.setaxisref()})
        finished_action = await active.finish()
        return finished_action.as_dict()


    # only for alignment bokeh server
    @app.post(f"/{servKey}/private/align_move")
    async def private_align_move(
        request: Request,
        multi_d_mm: Optional[Union[List[float], float]] = None,
        multi_axis: Optional[Union[List[str], str]] = None,
        speed: Optional[int] = None,
        mode: Optional[move_modes] = "relative"
    ):
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["data"],
        )
        await active.enqueue_data_dflt(datadict = \
           {"data": await app.driver.move(active)})
        finished_action = await active.finish()
        return finished_action.as_dict()
        

    # only for alignment bokeh server
    @app.post(f"/{servKey}/private/MxytoMPlate")
    async def private_MxytoMPlate(
                                  request: Request, 
                                  Mxy: Optional[List[List[float]]]
                                 ):
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["data"],
        )
        await active.enqueue_data_dflt(datadict = \
           {"data": \
            await app.driver.MxytoMPlate(active.action.action_params["Mxy"])})
        finished_action = await active.finish()
        return finished_action.as_dict()
        

    # only for alignment bokeh server
    @app.post(f"/{servKey}/private/toPlateXY")
    async def private_toPlateXY(
                                request: Request, 
                                motorxy: Optional[List[List[float]]]
                               ):
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["data"],
        )
        await active.enqueue_data_dflt(datadict = \
           {"data": \
            await app.driver.motor_to_platexy(**active.action.action_params)})
        finished_action = await active.finish()
        return finished_action.as_dict()

    # only for alignment bokeh server
    @app.post(f"/{servKey}/private/toMotorXY")
    async def private_toMotorXY(
                                request: Request, 
                                platexy: Optional[List[List[float]]]
                               ):
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["data"],
        )
        await active.enqueue_data_dflt(datadict = \
           {"data": \
            await app.driver.plate_to_motorxy(**active.action.action_params)})
        finished_action = await active.finish()
        return finished_action.as_dict()

    # only for alignment bokeh server
    @app.post(f"/{servKey}/private/align_get_PM")
    async def private_align_get_PM(request: Request):
        """Returns the PM for the alignment Visualizer"""
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["data"],
        )
        await active.enqueue_data_dflt(datadict = \
           {"data": await app.driver.get_PM()})
        finished_action = await active.finish()
        return finished_action.as_dict()

    # only for alignment bokeh server
    @app.post(f"/{servKey}/private/ismoving")
    async def private_align_ismoving(request: Request, axis: str="xy"):
        """check if motor is moving"""
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = ["data"],
        )
        await active.enqueue_data_dflt(datadict = \
           {"data": await app.driver.ismoving(**active.action.action_params)})
        finished_action = await active.finish()
        return finished_action.as_dict()

    # only for alignment bokeh server
    @app.post(f"/{servKey}/private/send_alignment")
    async def private_align_send_alignment(
        request: Request, 
        Transfermatrix: Optional[List[List[int]]]=None, 
        errorcode: Optional[str]=None, 
    ):
        """the bokeh server will send its Transfermatrix back with this"""
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = [],
        )
        # saving params from bokehserver so we can send them back
        app.driver.newTransfermatrix = Transfermatrix
        app.driver.errorcode = errorcode
        # signal to other function that we are done
        app.driver.aligning = False
        # await active.enqueue_data_dflt(datadict = \
        #    {"data": "received new alignment"})
        finished_action = await active.finish()
        return finished_action.as_dict()

    # TODO: alignment FastAPI and bokeh server are linked
    # should motor server and data server be parameters?
    # TODO: add mode to get Transfermatrix from Database?
    @app.post(f"/{servKey}/get_alignment")
    async def get_alignment(
        request: Request,
        plateid: Optional[str],
        # default motor server in config
        # align.config_dict['motor_server'],
        motor: Optional[str] = "motor",
        # default data server in config
        # align.config_dict['data_server']
        data: Optional[str] = "data"
    ):
        """Starts alignment action and returns TransferMatrix"""

        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = [
                                                            "err_code",
                                                            "plateid",
                                                            "motor_server",
                                                            "data_server"
                                                            ],
        )
        await active.enqueue_data_dflt(datadict = \
           await app.driver.get_alignment(**active.action.action_params))
        finished_action = await active.finish()
        return finished_action.as_dict()

    # gets status and Transfermatrix
    # for new Matrix, a new alignment action needs to be started via
    # get_alignment
    # when align_status is then true the Matrix is valid, 
    # else it will return the initial one
    @app.post(f"/{servKey}/align_status")
    async def align_status(request: Request):
        """Return status of current alignment"""
        active = await app.base.setup_and_contain_action(
                                          request = request,
                                          json_data_keys = [
                                                            "aligning",
                                                            "transfermatrix",
                                                            "plateid",
                                                            "err_code",
                                                            "motor_server",
                                                            "data_server"
                                                            ],
        )
        align_status={
            # true when in progress, false otherwise
            "aligning": await app.driver.is_aligning(),
            "transfermatrix": app.driver.newTransfermatrix,
            "plateid": app.driver.plateid,
            "err_code": app.driver.errorcode,
            "motor_server": app.driver.motorserv,
            "data_server": app.driver.dataserv,
        }
        await active.enqueue_data_dflt(datadict = \
           align_status)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post("/shutdown")
    def post_shutdown():
        shutdown_event()

    @app.on_event("shutdown")
    def shutdown_event():
        return ""

    return app
