""" A device class for the Galil motion controller, used by a FastAPI server instance.

The 'galil' device class exposes motion and I/O functions from the underlying 'gclib'
library. Class methods are specific to Galil devices. Device configuration is read from
config/config.py. 
"""

__all__ = ["Galil",
           "MoveModes",
           "TransformationModes"]

import numpy as np
import time
import asyncio
from enum import Enum
from functools import partial
import json
import os
from socket import gethostname
import base64

from bokeh.server.server import Server
from bokeh.models import ColumnDataSource
from bokeh.models.widgets import Paragraph
from bokeh.plotting import figure
from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer
from bokeh.models import (
                          Button, 
                          TextAreaInput, 
                          TextInput, 
                          Select, 
                          CheckboxGroup, 
                          Toggle, 
                         )
from bokeh.events import ButtonClick, DoubleTap, MouseWheel, Pan
# from bokeh.models import TapTool, PanTool
from bokeh.layouts import gridplot
from bokeh.models.widgets import FileInput

from helaocore.server.base import Base
from helaocore.error import ErrorCodes
from helaocore.schema import Action
from helaocore.server.vis import Vis
from helaocore.server.make_vis_serv import makeVisServ
from helaocore.data.legacy import HTELegacyAPI
from helaocore.model.active import ActiveParams
from helaocore.model.file import FileConnParams
from helaocore.model.data import DataModel

# install galil driver first
# (helao) c:\Program Files (x86)\Galil\gclib\source\wrappers\python>python setup.py install
import gclib


class cmd_exception(ValueError):
    def __init__(self, arg):
        self.args = arg


class Galil:
    def __init__(self, action_serv: Base):

        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]

        self.dflt_matrix = np.matrix(
                                     [
                                      [1,0,0],
                                      [0,1,0],
                                      [0,0,1]
                                     ]
                                    )


        self.file_backup_transfermatrix = None
        if self.base.states_root is not None:
            self.file_backup_transfermatrix = \
                os.path.join(self.base.states_root, 
                             f"{gethostname()}_motor_calib.json")
 
        self.transfermatrix = \
        self.load_transfermatrix(file = self.file_backup_transfermatrix)
        self.save_transfermatrix(file = self.file_backup_transfermatrix)

        self.motor_timeout = self.config_dict.get("timeout", 60)

        # need to check if config settings exist
        # else need to create empty ones
        self.axis_id = self.config_dict.get("axis_id", dict())

        self.M_instr = self.config_dict.get("M_instr", [
                [1, 0, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ])

        self.xyTransfermatrix = np.matrix([
                                           [1, 0, 0],
                                           [0, 1, 0],
                                           [0, 0, 1]
                                          ])


        # Mplatexy is identity matrix by default
        self.transform = TransformXY(self.base,
            self.M_instr, self.axis_id
        )
        # only here for testing: will overwrite the default identity matrix
        self.transform.update_Mplatexy(Mxy = self.transfermatrix)

        # if this is the main instance let us make a galil connection
        self.g = gclib.py()
        self.base.print_message(f"gclib version: {self.g.GVersion()}")
        # TODO: error checking here: Galil can crash an dcarsh program
        galil_ip = self.config_dict.get("galil_ip_str", None)
        self.galil_enabled = None
        try:
            if galil_ip:
                self.g.GOpen("%s --direct -s ALL" % (galil_ip))
                self.base.print_message(self.g.GInfo())
                self.c = self.g.GCommand  # alias the command callable
                # The SH commands tells the controller to use the current 
                # motor position as the command position and to enable servo control here.
                # The SH command changes the coordinate system.
                # Therefore, all position commands given prior to SH, 
                # must be repeated. Otherwise, the controller produces incorrect motion.
                self.c("SH; PF 10.4")
                axis_init = [
                            ("MT", 2), # Specifies Step motor with active low step pulses
                            ("CE", 4), # Configure Encoder: Normal pulse and direction
                            ("TW", 32000),  # Timeout for IN Position (MC) in ms
                            ("SD", 256000), # sets the linear deceleration rate of the motors when a limit switch has been reached.
                            ]
                for axl in self.config_dict['axis_id'].values():
                    for ac, av in axis_init:
                        self.c(f"{ac}{axl}={av}")
                self.galil_enabled = True
            else:
                self.base.print_message(
                    "no Galil IP configured",
                    error = True
                )
                self.galil_enabled = False
        except Exception:
            self.base.print_message(
                "severe Galil error ... "
                "please power cycle Galil and try again",
                error = True
            )
            self.galil_enabled = False

        self.cycle_lights = False

        # block gamry
        self.blocked = False
        # is motor move busy?
        self.motor_busy = False
        self.bokehapp = None
        self.aligner = None
        self.aligner_enabled = self.base.server_params.get("enable_aligner", False)
        if self.aligner_enabled and self.galil_enabled:
            self.start_aligner()


    def start_aligner(self):
        servHost = self.base.server_cfg["host"]
        servPort = self.base.server_params.get(
            "bokeh_port",
            self.base.server_cfg["port"]+1000
        )
        servPy = "Aligner"


        self.bokehapp = Server(
                          {f"/{servPy}": partial(self.makeBokehApp, motor=self)},
                          port=servPort, 
                          address=servHost, 
                          allow_websocket_origin=[f"{servHost}:{servPort}"]
                          )
        self.bokehapp.start()
        self.bokehapp.io_loop.add_callback(self.bokehapp.show, f"/{servPy}")


    def makeBokehApp(self, doc, motor):
        app = makeVisServ(
            config = self.base.world_cfg,
            server_key = self.base.server.server_name,
            doc = doc,
            server_title = self.base.server.server_name,
            description = f"{self.base.technique_name} Aligner",
            version=2.0,
            driver_class=None,
        )
    
        doc.aligner = Aligner(app.vis, motor)
        return doc



    async def setaxisref(self):
        # home all axis first
        axis = self.get_all_axis()
        self.base.print_message(f"axis: {axis}")
        if "Rx" in axis:
            axis.remove("Rx")
        if "Ry" in axis:
            axis.remove("Ry")
        if "Rz" in axis:
            axis.remove("Rz")
        #            axis.pop(axis.index('Rz'))
        self.base.print_message(f"axis: {axis}")


        if axis is not None:
            # go slow to find the same position every time
            # first a fast move to find the switch
            retc1 = await self._motor_move(
                d_mm = [0 for ax in axis],
                axis = axis,
                speed = None,
                mode = MoveModes.homing,
                transformation = TransformationModes.motorxy
            )

            # move back 2mm
            retc1 = await self._motor_move(
                d_mm = [2 for ax in axis],
                axis = axis,
                speed = None,
                mode = MoveModes.relative,
                transformation = TransformationModes.motorxy
            )

            # approach switch again very slow to get better zero position
            retc1 = await self._motor_move(
                d_mm = [0 for ax in axis],
                axis = axis,
                speed = 1000,
                mode = MoveModes.homing,
                transformation = TransformationModes.motorxy
            )

            # move back to configured center coordinates
            retc2 = await self._motor_move(
                d_mm = [
                    self.config_dict["axis_zero"][self.axis_id[ax]]
                    for ax in axis
                ],
                axis = axis,
                speed = None,
                mode = MoveModes.relative,
                transformation = TransformationModes.motorxy
            )


            # set absolute zero to current position
            q = self.c("TP")  # query position of all axis
            self.base.print_message(f"q1: {q}")
            cmd = "DP "
            for i in range(len(q.split(","))):
                if i == 0:
                    cmd += "0"
                else:
                    cmd += ",0"
            self.base.print_message(f"cmd: {cmd}")

            # sets abs zero here
            _ = self.c(cmd)

            return retc2
        else:
            return "error"


    async def run_aligner(self, A: Action):
        if not self.blocked:
            if not self.aligner_enabled \
            or not self.aligner:
                A.error_code = ErrorCodes.not_available
                activeDict = A.as_dict()
            else:
                self.blocked = True
                self.aligner.plateid = A.action_params["plateid"]
                self.aligner.active = await self.base.contain_action(
                    ActiveParams(
                                 action = A,
                                 file_conn_params_dict = {self.base.dflt_file_conn_key():
                                     FileConnParams(
                                         # use dflt file conn key for first
                                         # init
                                                   file_conn_key = \
                                                       self.base.dflt_file_conn_key(),
                                                    sample_global_labels=[],
                                                    json_data_keys = [
                                                        "Transfermatrix",
                                                        "oldTransfermatrix",
                                                        "errorcode"
                                                    ],
                                                    file_type="aligner_helao__file",
                                                    # hloheader = HloHeaderModel(
                                                    #     optional = None
                                                    # ),
                                                   )
                                     }
                    )
                )
                self.aligner.g_aligning = True
                activeDict = self.aligner.active.action.as_dict()
        else:
            A.error_code = ErrorCodes.in_progress
            activeDict = A.as_dict()
        return activeDict


    async def motor_move(self, active):
        d_mm = active.action.action_params.get("d_mm",[])
        axis = active.action.action_params.get("axis",[])
        speed = active.action.action_params.get("speed", None)
        mode = active.action.action_params.get("mode",MoveModes.absolute)
        transformation = active.action.action_params.get("transformation",TransformationModes.motorxy)
        if not self.blocked:
            self.blocked = True
            retval = await self._motor_move(
                d_mm = d_mm,
                axis = axis,
                speed = speed,
                mode = mode,
                transformation = transformation
            ) 
            self.blocked = False
            return retval
        else:
            return {
                "moved_axis": None,
                "speed": None,
                "accepted_rel_dist": None,
                "supplied_rel_dist": None,
                "err_dist": None,
                "err_code": ErrorCodes.in_progress,
                "counts": None,
            }


    async def _motor_move(
                          self, 
                          d_mm,
                          axis,
                          speed,
                          mode,
                          transformation
                         ):
        if self.motor_busy:
            return {
                "moved_axis": None,
                "speed": None,
                "accepted_rel_dist": None,
                "supplied_rel_dist": None,
                "err_dist": None,
                "err_code": ErrorCodes.in_progress,
                "counts": None,
            }
            
        self.motor_busy = True

        # in order to enable easy mode for swagger:
        if type(axis) is not list:
            axis = [axis]
        if type(d_mm) is not list:
            d_mm = [d_mm]
        
        error =  ErrorCodes.none

        stopping = False  # no stopping of any movement by other actions
        mode = MoveModes(mode)
        transformation = TransformationModes(transformation)

        # need to get absolute motor position first
        tmpmotorpos = await self.query_axis_position(
            self.get_all_axis()
        )
        self.base.print_message(f"current absolute motor positions: "
                                f"{tmpmotorpos}")
        # don't use dicts as we do math on these vectors
         # x, y, z, Rx, Ry, Rz
        current_positionvec = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        # map the request to this
        # x, y, z, Rx, Ry, Rz
        req_positionvec = [None, None, None, None, None, None]

        reqdict = dict(zip(axis, d_mm))
        self.base.print_message(f"requested position ({mode}): {reqdict}")

        for idx, ax in enumerate(["x", "y", "z", "Rx", "Ry", "Rz"]):
            if ax in tmpmotorpos["ax"]:
                # for current_positionvec
                current_positionvec[idx] = tmpmotorpos["position"][
                    tmpmotorpos["ax"].index(ax)
                ]
                # for req_positionvec
                if ax in reqdict:
                    req_positionvec[idx] = reqdict[ax]

        self.base.print_message(f"motor position vector: {current_positionvec[0:3]}")
        self.base.print_message(f"requested position vector ({mode}) {req_positionvec}")

        if transformation == TransformationModes.motorxy:
            # nothing to do
            self.base.print_message(f"motion: got motorxy ({mode}), no transformation necessary")
        elif transformation == TransformationModes.platexy:
            self.base.print_message(f"motion: got platexy ({mode}), converting to motorxy")
            motorxy = [0, 0, 1]
            motorxy[0] = current_positionvec[0]
            motorxy[1] = current_positionvec[1]
            current_platexy = self.transform.transform_motorxy_to_platexy(motorxy)
            # transform.transform_motorxyz_to_instrxyz(current_positionvec[0:3])
            self.base.print_message(f"current plate position (calc from motor): {current_platexy}")
            if mode == MoveModes.relative:
                new_platexy = [0, 0, 1]

                if req_positionvec[0] is not None:
                    new_platexy[0] = current_platexy[0] + req_positionvec[0]
                else:
                    new_platexy[0] = current_platexy[0]

                if req_positionvec[1] is not None:
                    new_platexy[1] = current_platexy[1] + req_positionvec[1]
                else:
                    new_platexy[1] = current_platexy[1]

                self.base.print_message(f"new platexy (abs): {new_platexy}")
                new_motorxy = self.transform.transform_platexy_to_motorxy(
                    new_platexy
                )
                self.base.print_message(f"new motorxy (abs): {new_motorxy}")
                axis = ["x", "y"]
                d_mm = [d for d in new_motorxy[0:2]]
                mode = MoveModes.absolute
            elif mode == MoveModes.absolute:
                new_platexy = [0, 0, 1]

                if req_positionvec[0] is not None:
                    new_platexy[0] = req_positionvec[0]
                else:
                    new_platexy[0] = current_platexy[0]

                if req_positionvec[1] is not None:
                    new_platexy[1] = req_positionvec[1]
                else:
                    new_platexy[1] = current_platexy[1]

                self.base.print_message(f"new platexy (abs): {new_platexy}")
                new_motorxy = self.transform.transform_platexy_to_motorxy(
                    new_platexy
                )
                self.base.print_message(f"new motorxy (abs): {new_motorxy}")
                axis = ["x", "y"]
                d_mm = [d for d in new_motorxy[0:2]]

            elif mode == MoveModes.homing:
                # not coordinate conversoion needed as these are not used (but length is still checked)
                pass

            xyvec = [0, 0, 1]
            for i, ax in enumerate(axis):
                if ax == "x":
                    xyvec[0] = d_mm[0]
                if ax == "y":
                    xyvec[1] = d_mm[1]
        elif transformation == TransformationModes.instrxy:
            self.base.print_message(f"mode: {mode}")
            self.base.print_message(f"motion: got instrxyz ({mode}), converting to motorxy")
            current_instrxyz = self.transform.transform_motorxyz_to_instrxyz(
                current_positionvec[0:3]
            )
            self.base.print_message(
                f"current instrument position (calc from motor): {current_instrxyz}"
            )
            if mode == MoveModes.relative:
                new_instrxyz = current_instrxyz
                for i in range(3):
                    if req_positionvec[i] is not None:
                        new_instrxyz[i] = new_instrxyz[i] + req_positionvec[i]
                    else:
                        new_instrxyz[i] = new_instrxyz[i]
                self.base.print_message(f"new instrument position (abs): {new_instrxyz}")
                # transform from instrxyz to motorxyz
                new_motorxyz = self.transform.transform_instrxyz_to_motorxyz(
                    new_instrxyz[0:3]
                )
                self.base.print_messagef(f"new motor position (abs): {new_motorxyz}")
                axis = ["x", "y", "z"]
                d_mm = [d for d in new_motorxyz[0:3]]
                mode = MoveModes.absolute
            elif mode == MoveModes.absolute:
                new_instrxyz = current_instrxyz
                for i in range(3):
                    if req_positionvec[i] is not None:
                        new_instrxyz[i] = req_positionvec[i]
                    else:
                        new_instrxyz[i] = new_instrxyz[i]
                self.base.print_message(f"new instrument position (abs): {new_instrxyz}")
                new_motorxyz = self.transform.transform_instrxyz_to_motorxyz(
                    new_instrxyz[0:3]
                )
                self.base.print_message(f"new motor position (abs): {new_motorxyz}")
                axis = ["x", "y", "z"]
                d_mm = [d for d in new_motorxyz[0:3]]
            elif mode == MoveModes.homing:
                # not coordinate conversoion needed as these are not used (but length is still checked)
                pass

        self.base.print_message(f"final axis requested: {axis}")
        self.base.print_message(f"final d ({mode}) requested: {d_mm}")

        # return value arrays for multi axis movement
        ret_moved_axis = []
        ret_speed = []
        ret_accepted_rel_dist = []
        ret_supplied_rel_dist = []
        ret_err_dist = []
        ret_err_code = []
        ret_counts = []

        # expected time for each move, used for axis stop check
        timeofmove = []

        if self.base.actionserver.estop:
            self.motor_busy = False
            return {
                "moved_axis": None,
                "speed": None,
                "accepted_rel_dist": None,
                "supplied_rel_dist": None,
                "err_dist": None,
                "err_code": ErrorCodes.estop,
                "counts": None,
            }

        # TODO: if same axis is moved twice
        for d, ax in zip(d_mm, axis):
            # need to remove stopping for multi-axis move
            if len(ret_moved_axis) > 0:
                stopping = False

            # first we check if we have the right axis specified
            # if 1:
            if ax in self.axis_id:
                axl = self.axis_id[ax]
            else:
                self.base.print_message("motor setup error",
                                        error = True)
                ret_moved_axis.append(None)
                ret_speed.append(None)
                ret_accepted_rel_dist.append(None)
                ret_supplied_rel_dist.append(d)
                ret_err_dist.append(None)
                ret_err_code.append(ErrorCodes.setup)
                ret_counts.append(None)
                continue

            # check if the motors are moving if so return an error message
            # recalculate the distance in mm into distance in counts
            # if 1:
            try:
                self.base.print_message(f"count_to_mm: {axl}, {self.config_dict['count_to_mm'][axl]}")
                float_counts = (
                    d / self.config_dict["count_to_mm"][axl]
                )  # calculate float dist from steupd

                counts = int(np.floor(float_counts))  # we can only mode full counts
                # save and report the error distance
                error_distance = self.config_dict["count_to_mm"][axl] * (
                    float_counts - counts
                )

                # check if a speed was upplied otherwise set it to standart
                if speed == None:
                    speed = self.config_dict["def_speed_count_sec"]
                else:
                    speed = int(np.floor(speed))

                if speed > self.config_dict["max_speed_count_sec"]:
                    speed = self.config_dict["max_speed_count_sec"]
                self._speed = speed
            except Exception:
                self.base.print_message("motor numerical error",
                                        error = True)
                # something went wrong in the numerical part so we give that as feedback
                ret_moved_axis.append(None)
                ret_speed.append(None)
                ret_accepted_rel_dist.append(None)
                ret_supplied_rel_dist.append(d)
                ret_err_dist.append(None)
                ret_err_code.append(ErrorCodes.numerical)
                ret_counts.append(None)
                continue

            try:
                # the logic here is that we assemble a command experiment
                # here we decide if we move relative, home, or move absolute
                if stopping:
                    cmd_seq = [
                        f"ST{axl}",
                        f"MO{axl}",
                        f"SH{axl}",
                        f"SP{axl}={speed}",
                    ]
                else:
                    cmd_seq = [f"SP{axl}={speed}"]
                if mode == MoveModes.relative:
                    cmd_seq.append(f"PR{axl}={counts}")
                elif mode == MoveModes.homing:
                    cmd_seq.append(f"HM{axl}")
                elif mode == MoveModes.absolute:
                    # now we want an abolute position
                    cmd_seq.append(f"PA{axl}={counts}")
                else:
                    raise cmd_exception
                cmd_seq.append(f"BG{axl}")
                # todo: fix this for absolute or relative move
                timeofmove.append(abs(counts / speed))

                # ret = ""
                self.base.print_message(f"BUGCHECK: {cmd_seq}")
                # BUG
                # TODO
                # it can happen that it crashes below for some reasons
                # when more then two axis move are requested
                for cmd in cmd_seq:
                    _ = self.c(cmd)
                    # ret.join(_)
                self.base.print_message(f"Galil cmd: {cmd_seq}")
                ret_moved_axis.append(axl)
                ret_speed.append(speed)
                ret_accepted_rel_dist.append(None)
                ret_supplied_rel_dist.append(d)
                ret_err_dist.append(error_distance)
                ret_err_code.append(ErrorCodes.none)
                ret_counts.append(counts)
                # time = counts/ counts_per_second

                # continue
            except Exception as e:
                self.base.print_message("motor error: '{e}'",
                                        error = True)
                ret_moved_axis.append(None)
                ret_speed.append(None)
                ret_accepted_rel_dist.append(None)
                ret_supplied_rel_dist.append(d)
                ret_err_dist.append(None)
                ret_err_code.append(ErrorCodes.motor)
                ret_counts.append(None)
                continue

        # get max time until all axis are expected to have stopped
        self.base.print_message(f"timeofmove: {timeofmove}")
        if len(timeofmove) > 0:
            tmax = max(timeofmove)
            if tmax > 30 * 60:
                tmax > 30 * 60  # 30min hard limit
        else:
            tmax = 0

        # wait for expected axis move time before checking if axis stoppped
        self.base.print_message(f"axis expected to stop in {tmax} sec")

        if not self.base.actionserver.estop:

            # check if all axis stopped
            tstart = time.time()

            while (time.time() - tstart < self.motor_timeout) \
            and not self.base.actionserver.estop:
                qmove = await self.query_axis_moving(axis)
                # test = await self.query_axis_position(self.get_all_axis())
                await asyncio.sleep(0.5)
                if all(status == "stopped" for status in qmove["motor_status"]):
                    break

            if not self.base.actionserver.estop:
                # stop of motor movement (motor still on)
                if time.time() - tstart > self.motor_timeout:
                    await self.stop_axis(axis)
                # check which axis had the timeout
                newret_err_code = []
                for erridx, err_code in enumerate(ret_err_code):
                    if qmove["err_code"][erridx] != ErrorCodes.none:
                        newret_err_code.append(ErrorCodes.timeout)
                        self.base.print_message("motor timeout error",
                                                error = True)
                    else:
                        newret_err_code.append(err_code)

                ret_err_code = newret_err_code
            else:
                # estop occured while checking axis end position
                ret_err_code = [ErrorCodes.estop for _ in ret_err_code]

        else:
            # estop was triggered while waiting for axis to stop
            ret_err_code = [ErrorCodes.estop for _ in ret_err_code]

        # read final position
        # updates ws buffer
        _ = await self.query_axis_position(axis)


        # one return for all axis
        self.motor_busy = False
        return {
            "moved_axis": ret_moved_axis,
            "speed": ret_speed,
            "accepted_rel_dist": ret_accepted_rel_dist,
            "supplied_rel_dist": ret_supplied_rel_dist,
            "err_dist": ret_err_dist,
            "err_code": ret_err_code,
            "counts": ret_counts,
        }


    async def motor_disconnect(self):
        try:
            self.g.GClose()  # don't forget to close connections!
        except gclib.GclibError as e:
            return {"connection": {"Unexpected GclibError:", e}}
        return {"connection": "motor_offline"}


    async def query_axis_position(self, axis,*args,**kwargs):
        # this only queries the position of a single axis
        # server example:
        # http://127.0.0.1:8000/motor/query/position?axis=x

        # convert single axis move to list
        if type(axis) is not list:
            axis = [axis]

        # first get the relative position (actual only the current position of the encoders)
        # to get how many axis are present
        qTP = self.c("TP")  # query position of all axis
        self.base.print_message(f"q (TP): {qTP}")
        cmd = "PA "
        for i in range(len(qTP.split(","))):
            if i == 0:
                cmd += "?"
            else:
                cmd += ",?"
        q = self.c(cmd)  # query position of all axis
        # _ = self.c("PF 10.4")  # set format
        # q = self.c("TP")  # query position of all axis
        self.base.print_message(f"q (PA): {q}")
        # now we need to map these outputs to the ABCDEFG... channels
        # and then map that to xyz so it is humanly readable
        axlett = "ABCDEFGH"
        axlett = axlett[0 : len(q.split(","))]
        inv_axis_id = {d: v for v, d in self.axis_id.items()}
        ax_abc_to_xyz = {l: inv_axis_id[l] for i, l in enumerate(axlett) if l in inv_axis_id}
        # this puts the counts back to motor mm
        pos = {
            axl: float(r) * self.config_dict["count_to_mm"].get(axl,0)
            for axl, r in zip(axlett, q.split(", "))
        }
        # return the results through calculating things into mm
        axpos = {ax_abc_to_xyz.get(k,None): p for k, p in pos.items()}
        ret_ax = []
        ret_position = []
        for ax in axis:
            if ax in axpos:
                # self.update_wsmotorbuffersingle("position", ax, axpos[ax])
                ret_ax.append(ax)
                ret_position.append(axpos[ax])
            else:
                ret_ax.append(None)
                ret_position.append(None)

        msg_ret_ax = []
        msg_ret_position = []
        for ax, pos in axpos.items():
            msg_ret_ax.append(ax)
            msg_ret_position.append(pos)
        await self.update_aligner(msg = \
                        {"ax": msg_ret_ax, "position": msg_ret_position})
        return {"ax": ret_ax, "position": ret_position}


    async def query_axis_moving(self, axis,*args,**kwargs):
        # this functions queries the status of the axis
        q = self.c("SC")
        axlett = "ABCDEFGH"
        axlett = axlett[0 : len(q.split(","))]
        # convert single axis move to list
        if type(axis) is not list:
            axis = [axis]
        ret_status = []
        ret_err_code = []
        qdict = dict(zip(axlett, q.split(", ")))
        for ax in axis:
            if ax in self.axis_id:
                axl = self.axis_id.get(ax, None)
                if axl in qdict:
                    r = qdict[axl]
                    if int(r) == 0:
                        # self.update_wsmotorbuffersingle("motor_status", ax, "moving")
                        # self.update_wsmotorbuffersingle("err_code", ax, int(r))
                        ret_status.append("moving")
                        ret_err_code.append(ErrorCodes.none)
                    elif int(r) == 1:
                        # self.update_wsmotorbuffersingle("motor_status", ax, "stopped")
                        # self.update_wsmotorbuffersingle("err_code", ax, int(r))
                        ret_status.append("stopped")
                        ret_err_code.append(ErrorCodes.none)
                    else:
                        # self.update_wsmotorbuffersingle("motor_status", ax, "stopped")
                        # self.update_wsmotorbuffersingle("err_code", ax, int(r))
                        # stopped due to error/issue
                        ret_status.append("stopped")
                        ret_err_code.append(ErrorCodes.none)
                else:
                    ret_status.append("invalid")
                    ret_err_code.append(ErrorCodes.unspecified)

            else:
                ret_status.append("invalid")
                ret_err_code.append(ErrorCodes.not_available)
                pass


        msg = {"motor_status": ret_status, "err_code": ret_err_code}
        await self.update_aligner(msg = msg)
        return msg


    async def reset(self):
        # The RS command resets the state of the actionor to its power-on condition.
        # The previously saved state of the controller,
        # along with parameter values, and saved experiments are restored.
        return self.c("RS")


    async def estop(self, switch:bool, *args, **kwargs):
        # this will estop the axis
        # set estop: switch=true
        # release estop: switch=false
        self.base.print_message("Axis Estop")
        if switch == True:
            await self.stop_axis(self.get_all_axis())
            await self.motor_off(self.get_all_axis())
            # set flag (move command need to check for it)
            self.base.actionserver.estop = True
        else:
            # need only to set the flag
            self.base.actionserver.estop = False
        return switch


    async def stop_axis(self, axis):
        # this will stop the current motion of the axis
        # but not turn off the motor
        # for stopping and turnuing off use moto_off

        # convert single axis move to list
        if type(axis) is not list:
            axis = [axis]
        for ax in axis:
            if ax in self.axis_id:
                axl = self.axis_id[ax]
                self.c(f"ST{axl}")

        ret = await self.query_axis_moving(axis)
        ret.update(await self.query_axis_position(axis))
        return ret

    async def motor_off(self, axis,*args,**kwargs):

        # sometimes it is useful to turn the motors off for manual alignment
        # this function does exactly that
        # It then returns the status
        # and the current position of all motors

        # an example would be:
        # http://127.0.0.1:8000/motor/stop
        # convert single axis move to list
        if type(axis) is not list:
            axis = [axis]

        for ax in axis:

            if ax in self.axis_id:
                axl = self.axis_id[ax]
            else:
                continue
                # ret = self.query_axis_moving(axis)
                # ret.update(self.query_axis_position(axis))
                # return ret

            cmd_seq = [f"ST{axl}", f"MO{axl}"]

            for cmd in cmd_seq:
                _ = self.c(cmd)

        ret = await self.query_axis_moving(axis)
        ret.update(await self.query_axis_position(axis))
        return ret

    async def motor_on(self, axis,*args,**kwargs):
        # sometimes it is useful to turn the motors back on for manual alignment
        # this function does exactly that
        # It then returns the status
        # and the current position of all motors
        # server example
        # http://127.0.0.1:8000/motor/on?axis=x

        # convert single axis move to list
        if type(axis) is not list:
            axis = [axis]

        for ax in axis:

            if ax in self.axis_id:
                axl = self.axis_id[ax]
            else:
                continue
                # ret = self.query_axis_moving(axis)
                # ret.update(self.query_axis_position(axis))
                # return ret
            cmd_seq = [f"ST{axl}", f"SH{axl}"]

            for cmd in cmd_seq:
                _ = self.c(cmd)

        ret = await self.query_axis_moving(axis)
        ret.update(await self.query_axis_position(axis))
        return ret


    async def upload_DMC(self, DMC_prog):
        self.c("UL;")  # begin upload
        # upload line by line from DMC_prog
        for DMC_prog_line in DMC_prog.split("\n"):
            self.c(DMC_prog_line)
        self.c("\x1a")  # terminator "<cntrl>Z"


    def get_all_axis(self):
        return [ax for ax in self.axis_id]

    async def get_all_digital_out(self):
        return [port for port in self.config_dict["Dout_id"]]

    async def get_all_digital_in(self):
        return [port for port in self.config_dict["Din_id"]]

    async def get_all_analog_out(self):
        return [port for port in self.config_dict["Aout_id"]]

    async def get_all_analog_in(self):
        return [port for port in self.config_dict["Ain_id"]]

    def shutdown_event(self):
        # this gets called when the server is shut down or reloaded to ensure a clean
        # disconnect ... just restart or terminate the server
        # self.stop_axis(self.get_all_axis())
        if self.aligner_enabled and self.aligner:
            self.aligner.IOtask.cancel()
        self.base.print_message("shutting down galil motion")
        # asyncio.gather(self.motor_off(asyncio.gather(self.get_all_axis()))) # already contains stop command
        self.g.GClose()
        return {"shutdown"}


    async def update_aligner(self, msg):
        if self.aligner_enabled and self.aligner:
            await self.aligner.motorpos_q.put(msg)


    def save_transfermatrix(self, file):
        if file is not None:
            filedir, filename = os.path.split(file)
            self.base.print_message(f"saving calib '{filename}' "
                                    f"to '{filedir}'", info = True)
            if not os.path.exists(filedir):
                os.makedirs(filedir, exist_ok=True)

            with open(file, "w") as f:
                f.write(json.dumps(self.transfermatrix.tolist()))


    def load_transfermatrix(self, file):
        if os.path.exists(file):
            with open(file, "r") as f:
                try:
                    data = f.readline()
                    new_matrix = np.matrix(json.loads(data))
                    if new_matrix.shape != self.dflt_matrix.shape:
                        self.base.print_message(f"matrix '{new_matrix}' "
                                               "has wrong shape",
                                               error = True)
                        return self.dflt_matrix
                    else:
                        self.base.print_message(f"loaded matrix '{new_matrix}'")
                        return new_matrix
                    
                except Exception:
                    self.base.print_message(f"error loading matrix for '{file}'",
                                           error = True)
                    return self.dflt_matrix
        else:
            self.base.print_message(f"matrix file '{file}' not found",
                                   error = True)
            return self.dflt_matrix


    def update_transfermatrix(self, newtransfermatrix):
        if newtransfermatrix.shape != self.dflt_matrix.shape:
            self.base.print_message(f"matrix '{newtransfermatrix}' "
                                   "has wrong shape, using dflt.",
                                   error = True)
            matrix = self.dflt_matrix
        else:
            matrix = newtransfermatrix
        self.transfermatrix = matrix
        self.transform.update_Mplatexy(Mxy = self.transfermatrix)
        return self.transfermatrix


    def reset_transfermatrix(self):
        self.update_transfermatrix(
            newtransfermatrix = self.dflt_matrix)


class MoveModes(str, Enum):
    homing = "homing"
    relative = "relative"
    absolute = "absolute"


class TransformationModes(str, Enum):
    motorxy = "motorxy"
    platexy = "platexy"
    instrxy = "instrxy"


class TransformXY:
    # Updating plate calibration will automatically update the system transformation
    # matrix. When angles are changed updated them also here and run update_Msystem
    def __init__(self, action_serv: Base, Minstr, seq=None):
        self.base = action_serv
        # instrument specific matrix
        # motor to instrument
        self.Minstrxyz = np.asmatrix(Minstr)  # np.asmatrix(np.identity(4))
        self.Minstr = np.asmatrix(np.identity(4))
        self.Minstrinv = np.asmatrix(np.identity(4))
        # plate Matrix
        # instrument to plate
        self.Mplate = np.asmatrix(np.identity(4))
        self.Mplatexy = np.asmatrix(np.identity(3))
        # system Matrix
        # motor to plate
        self.M = np.asmatrix(np.identity(4))
        self.Minv = np.asmatrix(np.identity(4))
        # need to update the angles here each time the axis is rotated
        self.alpha = 0
        self.beta = 0
        self.gamma = 0
        self.seq = seq

        # pre calculates the system Matrix M
        self.update_Msystem()


    def transform_platexy_to_motorxy(self, platexy,*args,**kwargs):
        """simply calculates motorxy based on platexy
        plate warping (z) will be a different call"""
        platexy = np.asarray(platexy)
        if len(platexy) == 3:
            platexy = np.insert(platexy, 2, 0)
        # for _ in range(4-len(platexy)):
        #     platexy = np.append(platexy,1)
        # self.base.print_message(" ... M:\n", self.M)
        # self.base.print_message(" ... xy:", platexy)
        motorxy = np.dot(self.M, platexy)
        motorxy = np.delete(motorxy, 2)
        motorxy = np.array(motorxy)[0]
        return motorxy


    def transform_motorxy_to_platexy(self, motorxy,*args,**kwargs):
        """simply calculates platexy from current motorxy"""
        motorxy = np.asarray(motorxy)
        if len(motorxy) == 3:
            motorxy = np.insert(motorxy, 2, 0)
        # self.base.print_message(" ... Minv:\n", self.Minv)
        # self.base.print_message(" ... xy:", motorxy)
        platexy = np.dot(self.Minv, motorxy)
        platexy = np.delete(platexy, 2)
        platexy = np.array(platexy)[0]
        return platexy


    def transform_motorxyz_to_instrxyz(self, motorxyz,*args,**kwargs):
        """simply calculatesinstrxyz from current motorxyz"""
        motorxyz = np.asarray(motorxyz)
        if len(motorxyz) == 3:
            # append 1 at end
            motorxyz = np.append(motorxyz, 1)
        # self.base.print_message(" ... Minstrinv:\n", self.Minstrinv)
        # self.base.print_message(" ... xyz:", motorxyz)
        instrxyz = np.dot(self.Minstrinv, motorxyz)
        return np.array(instrxyz)[0]


    def transform_instrxyz_to_motorxyz(self, instrxyz,*args,**kwargs):
        """simply calculates motorxyz from current instrxyz"""
        instrxyz = np.asarray(instrxyz)
        if len(instrxyz) == 3:
            instrxyz = np.append(instrxyz, 1)
        # self.base.print_message(" ... Minstr:\n", self.Minstr)
        # self.base.print_message(" ... xyz:", instrxyz)

        motorxyz = np.dot(self.Minstr, instrxyz)
        return np.array(motorxyz)[0]


    def Rx(self):
        """returns rotation matrix around x-axis"""
        alphatmp = np.mod(self.alpha, 360)  # this actually takes care of neg. values
        # precalculate some common angles for better accuracy and speed
        if alphatmp == 0:  # or alphatmp == -0.0:
            return np.asmatrix(np.identity(4))
        elif alphatmp == 90:  # or alphatmp == -270:
            return np.matrix(
                             [
                              [1, 0, 0, 0],
                              [0, 0, -1, 0],
                              [0, 1, 0, 0],
                              [0, 0, 0, 1]
                             ]
                            )
        elif alphatmp == 180:  # or alphatmp == -180:
            return np.matrix(
                             [
                              [1, 0, 0, 0],
                              [0, -1, 0, 0],
                              [0, 0, -1, 0],
                              [0, 0, 0, 1]
                             ]
                            )
        elif alphatmp == 270:  # or alphatmp == -90:
            return np.matrix(
                             [
                              [1, 0, 0, 0],
                              [0, 0, 1, 0],
                              [0, -1, 0, 0],
                              [0, 0, 0, 1]
                             ]
                            )
        else:
            return np.matrix(
                [
                    [1, 0, 0, 0],
                    [
                        0,
                        np.cos(np.pi / 180 * alphatmp),
                        -1.0 * np.sin(np.pi / 180 * alphatmp),
                        0,
                    ],
                    [
                        0,
                        np.sin(np.pi / 180 * alphatmp),
                        np.cos(np.pi / 180 * alphatmp),
                        0,
                    ],
                    [0, 0, 0, 1],
                ]
            )


    def Ry(self):
        """returns rotation matrix around y-axis"""
        betatmp = np.mod(self.beta, 360)  # this actually takes care of neg. values
        # precalculate some common angles for better accuracy and speed
        if betatmp == 0:  # or betatmp == -0.0:
            return np.asmatrix(np.identity(4))
        elif betatmp == 90:  # or betatmp == -270:
            return np.matrix(
                             [
                              [0, 0, 1, 0],
                              [0, 1, 0, 0],
                              [-1, 0, 0, 0],
                              [0, 0, 0, 1]
                             ]
                            )
        elif betatmp == 180:  # or betatmp == -180:
            return np.matrix(
                             [
                              [-1, 0, 0, 0],
                              [0, 1, 0, 0],
                              [0, 0, -1, 0],
                              [0, 0, 0, 1]
                             ]
                            )
        elif betatmp == 270:  # or betatmp == -90:
            return np.matrix(
                             [
                              [0, 0, -1, 0],
                              [0, 1, 0, 0],
                              [1, 0, 0, 0],
                              [0, 0, 0, 1]
                             ]
                            )
        else:
            return np.matrix(
                [
                    [
                        np.cos(np.pi / 180 * self.beta),
                        0,
                        np.sin(np.pi / 180 * self.beta),
                        0,
                    ],
                    [0, 1, 0, 0],
                    [
                        -1.0 * np.sin(np.pi / 180 * self.beta),
                        0,
                        np.cos(np.pi / 180 * self.beta),
                        0,
                    ],
                    [0, 0, 0, 1],
                ]
            )


    def Rz(self):
        """returns rotation matrix around z-axis"""
        gammatmp = np.mod(self.gamma, 360)  # this actually takes care of neg. values
        # precalculate some common angles for better accuracy and speed
        if gammatmp == 0:  # or gammatmp == -0.0:
            return np.asmatrix(np.identity(4))
        elif gammatmp == 90:  # or gammatmp == -270:
            return np.matrix(
                             [
                              [0, -1, 0, 0],
                              [1, 0, 0, 0],
                              [0, 0, 1, 0],
                              [0, 0, 0, 1]
                             ]
                            )
        elif gammatmp == 180:  # or gammatmp == -180:
            return np.matrix(
                             [
                              [-1, 0, 0, 0],
                              [0, -1, 0, 0],
                              [0, 0, 1, 0],
                              [0, 0, 0, 1]
                             ]
                            )
        elif gammatmp == 270:  # or gammatmp == -90:
            return np.matrix(
                             [
                              [0, 1, 0, 0],
                              [-1, 0, 0, 0],
                              [0, 0, 1, 0],
                              [0, 0, 0, 1]
                             ]
                            )
        else:
            return np.matrix(
                [
                    [
                        np.cos(np.pi / 180 * gammatmp),
                        -1.0 * np.sin(np.pi / 180 * gammatmp),
                        0,
                        0,
                    ],
                    [
                        np.sin(np.pi / 180 * gammatmp),
                        np.cos(np.pi / 180 * gammatmp),
                        0,
                        0,
                    ],
                    [0, 0, 1, 0],
                    [0, 0, 0, 1],
                ]
            )


    def Mx(self):
        """returns Mx part of Minstr"""
        Mx = np.asmatrix(np.identity(4))
        Mx[0, 0:4] = self.Minstrxyz[0, 0:4]
        # self.base.print_message(" ... Mx", Mx)
        return Mx


    def My(self):
        """returns My part of Minstr"""
        My = np.asmatrix(np.identity(4))
        My[1, 0:4] = self.Minstrxyz[1, 0:4]
        # self.base.print_message(" ... My", My)
        return My


    def Mz(self):
        """returns Mz part of Minstr"""
        Mz = np.asmatrix(np.identity(4))
        Mz[2, 0:4] = self.Minstrxyz[2, 0:4]
        # self.base.print_message(" ... Mz", Mz)
        return Mz


    def Mplatewarp(self, platexy):
        """returns plate warp correction matrix (Z-correction. 
        Only valid for a single platexy coordinate"""
        return np.asmatrix(np.identity(4))  # TODO, just returns identity matrix for now


    def update_Msystem(self):
        """updates the transformation matrix for new plate calibration or
        when angles are changed.
        Follows stacking experiment from bottom to top (plate)"""

        self.base.print_message("updating M")

        if self.seq == None:
            self.base.print_message("seq is empty, using default transformation")
            # default case, we simply have xy calibration
            self.M = np.dot(self.Minstrxyz, self.Mplate)
        else:
            self.Minstr = np.asmatrix(np.identity(4))
            # more complicated
            # check for some common experiments:
            Mcommon1 = (
                False  # to check against when common combinations are already found
            )
            axstr = ""
            for ax in self.seq:
                axstr += ax
            # check for xyz or xy (with no z)
            # experiment does not matter so should define it like this in the config
            # if we want to use this
            if axstr.find("xy") == 0 and axstr.find("z") <= 2:
                self.base.print_message("got xyz seq")
                self.Minstr = self.Minstrxyz
                Mcommon1 = True

            for ax in self.seq:
                if ax == "x" and not Mcommon1:
                    self.base.print_message("got x seq")
                    self.Minstr = np.dot(self.Minstr, self.Mx())
                elif ax == "y" and not Mcommon1:
                    self.base.print_message("got y seq")
                    self.Minstr = np.dot(self.Minstr, self.My())
                elif ax == "z" and not Mcommon1:
                    self.base.print_message("got z seq")
                    self.Minstr = np.dot(self.Minstr, self.Mz())
                elif ax == "Rx":
                    self.base.print_message("got Rx seq")
                    self.Minstr = np.dot(self.Minstr, self.Rx())
                elif ax == "Ry":
                    self.base.print_message("got Ry seq")
                    self.Minstr = np.dot(self.Minstr, self.Ry())
                elif ax == "Rz":
                    self.base.print_message("got Rz seq")
                    self.Minstr = np.dot(self.Minstr, self.Rz())

            self.M = np.dot(self.Minstr, self.Mplate)

            # precalculate the inverse as we also need it a lot
            try:
                self.Minv = self.M.I
            except Exception:
                self.base.print_message(
                    "System Matrix singular",
                    error = True
                )
                # use the -1 to signal inverse later --> platexy will then be [x,y,-1]
                self.Minv = np.matrix(
                    [
                     [0, 0, 0, 0],
                     [0, 0, 0, 0],
                     [0, 0, 0, 0],
                     [0, 0, 0, -1]
                    ]
                )

            try:
                self.Minstrinv = self.Minstr.I
            except Exception:
                self.base.print_message(
                    "Instrument Matrix singular",
                    error = True
                )
                # use the -1 to signal inverse later --> platexy will then be [x,y,-1]
                self.Minstrinv = np.matrix(
                    [
                     [0, 0, 0, 0],
                     [0, 0, 0, 0],
                     [0, 0, 0, 0],
                     [0, 0, 0, -1]
                    ]
                )


    def update_Mplatexy(self, Mxy,*args,**kwargs):
        """updates the xy part of the plate calibration"""
        Mxy = np.matrix(Mxy)
        # assign the xy part
        self.Mplate[0:2, 0:2] = Mxy[0:2, 0:2]
        # assign the last row (offsets), notice the difference in col (3x3 vs 4x4)
        #        self.Mplate[0:2,3] = Mxy[0:2,2] # something does not work with this one is a 1x2 the other 2x1 for some reason
        self.Mplate[0, 3] = Mxy[0, 2]
        self.Mplate[1, 3] = Mxy[1, 2]
        # self.Mplate[3,0:4] should always be 0,0,0,1 and should never change

        # update the system matrix so we save calculation time later
        self.update_Msystem()
        return True


    def get_Mplatexy(self):
        """returns the xy part of the platecalibration"""
        self.Mplatexy = np.asmatrix(np.identity(3))
        self.Mplatexy[0:2, 0:2] = self.Mplate[0:2, 0:2]
        self.Mplatexy[0, 2] = self.Mplate[0, 3]
        self.Mplatexy[1, 2] = self.Mplate[1, 3]
        return self.Mplatexy


    def get_Mplate_Msystem(self, Mxy,*args,**kwargs):
        """removes Minstr from Msystem to obtain Mplate for alignment"""
        Mxy = np.asarray(Mxy)
        Mglobal = np.asmatrix(np.identity(4))
        Mglobal[0:2, 0:2] = Mxy[0:2, 0:2]
        Mglobal[0, 3] = Mxy[0, 2]
        Mglobal[1, 3] = Mxy[1, 2]

        try:
            Minstrinv = self.Minstr.I
            Mtmp = np.dot(Minstrinv, Mglobal)
            self.Mplatexy = np.asmatrix(np.identity(3))
            self.Mplatexy[0:2, 0:2] = Mtmp[0:2, 0:2]
            self.Mplatexy[0, 2] = Mtmp[0, 3]
            self.Mplatexy[1, 2] = Mtmp[1, 3]

            return self.Mplatexy
        except Exception:
            self.base.print_message(
                "Instrument Matrix singular",
                error = True
            )
            # use the -1 to signal inverse later --> platexy will then be [x,y,-1]
            self.Minv = np.matrix([[0, 0, 0], [0, 0, 0], [0, 0, -1]])




class Aligner:
    def __init__(self, visServ: Vis, motor):
        self.vis = visServ
        self.motor = motor
        self.config_dict = self.vis.server_cfg["params"]
        self.dataAPI = HTELegacyAPI(self.vis)
        self.motorpos_q = asyncio.Queue()

        # flag to check if we actual should align
        self.g_aligning = False
        self.active = None
        self.plateid = None

        # dummy value, will be updated during init
        self.g_motor_position = [0,0,1]
        # to force drawing of marker
        self.gbuf_motor_position = -1*self.g_motor_position
        # dummy value, will be updated during init
        self.g_plate_position = [0,0,1]
        # to force drawing of marker
        self.gbuf_plate_position = -1*self.g_plate_position

        # will be updated during init
        self.g_motor_ismoving = False
        
        self.manual_step = 1 # mm
        self.mouse_control = False
        # initial instrument specific TransferMatrix
        self.initialTransferMatrix = self.motor.transfermatrix
        # self.initialTransferMatrix = np.matrix(
        #                                        [
        #                                         [1,0,0],
        #                                         [0,1,0],
        #                                         [0,0,1]
        #                                        ]
        #                                       )
        self.cutoff = np.array(self.config_dict.get("cutoff",6))
        
        # this is now used for plate to motor transformation and will be refined
        self.TransferMatrix = self.initialTransferMatrix
        
        self.markerdata = ColumnDataSource({"x0": [0], "y0": [0]})
        self.create_layout()
        self.motor.aligner = self
        self.IOtask = asyncio.create_task(self.IOloop_aligner())
        self.vis.doc.on_session_destroyed(self.cleanup_session)


    def cleanup_session(self, session_context):
        self.vis.print_message("Bokeh session closed",
                                error = True)
        self.IOtask.cancel()


    def create_layout(self):
        
        self.MarkerColors = [
                             (255,0,0),
                             (0,0,255),
                             (0,255,0),
                             (255,165,0),
                             (255,105,180)
                            ]

        self.MarkerNames = ["Cell", "Blue", "Green", "Orange", "Pink"]
        self.MarkerSample = [None, None, None, None, None]
        self.MarkerIndex = [None, None, None, None, None]
        self.MarkerCode = [None, None, None, None, None]
        self.MarkerFraction = [None, None, None, None, None]

        # for 2D transformation, the vectors (and Matrix) need to be 3D
        self.MarkerXYplate = [
                              (None, None,1),
                              (None, None,1),
                              (None, None,1),
                              (None, None,1),
                              (None, None,1)
                             ]
        # 3dim vector because of transformation matrix
        self.calib_ptsplate = [
                               (None, None,1),
                               (None, None,1),
                               (None, None,1)
                              ]

        self.calib_ptsmotor = [
                               (None, None,1),
                               (None, None,1),
                               (None, None,1)
                              ]
        
        
        # PM data given as parameter or empty and needs to be loaded
        self.pmdata = []
        
        self.totalwidth = 800
        
        
        ######################################################################
        #### getPM group elements ###
        ######################################################################
        
        self.button_goalign = Button(
                                     label="Go", 
                                     button_type="default", 
                                     width=150
                                    )
        self.button_skipalign = Button(
                                       label="Skip this step", 
                                       button_type="default", 
                                       width=150
                                      )
        self.button_goalign.on_event(ButtonClick, self.clicked_go_align)
        self.button_skipalign.on_event(ButtonClick, self.clicked_skipstep)
        self.status_align = \
            TextAreaInput(
                          value="", 
                          rows=8, 
                          title="Alignment Status:", 
                          disabled=True, 
                          width=150
                         )
        
        
        self.layout_getPM = layout(
                                    self.button_goalign,
                                    self.button_skipalign,
                                    self.status_align
                                  )
        
        
        
        ######################################################################
        #### Calibration group elements ###
        ######################################################################
        
        self.calib_sel_motor_loc_marker = \
            Select(
                   title="Active Marker", 
                   value=self.MarkerNames[1], 
                   options=self.MarkerNames[1:], 
                   width=110-50
                  )
        
        self.calib_button_addpt = \
            Button(
                   label="Add Pt", 
                   button_type="default", 
                   width=110-50
                  )
        self.calib_button_addpt.on_event(ButtonClick, self.clicked_addpoint)
        
        #Calc. Motor-Plate Coord. Transform
        self.calib_button_calc = \
            Button(
                   label="Calc", 
                   button_type="primary", 
                   width=110-50
                  )
        self.calib_button_calc.on_event(ButtonClick, self.clicked_calc)
        
        self.calib_button_reset = \
            Button(
                   label="Reset", 
                   button_type="default", 
                   width=110-50
                  )
        self.calib_button_reset.on_event(ButtonClick, self.clicked_reset)
        
        self.calib_button_done = \
            Button(
                   label="Sub.", 
                   button_type="danger", 
                   width=110-50
                  )
        self.calib_button_done.on_event(ButtonClick, self.clicked_submit)
        
        
        self.calib_xplate = []
        self.calib_yplate = []
        self.calib_xmotor = []
        self.calib_ymotor = []
        self.calib_pt_del_button = []
        for i in range(0,3):
            buf = "x%d plate" % (i+1)
            self.calib_xplate.append(
                                     TextInput(
                                               value="", 
                                               title=buf, 
                                               disabled=True, 
                                               width=60, 
                                               height=40
                                              )
                                    )
            buf = "y%d plate" % (i+1)
            self.calib_yplate.append(
                                     TextInput(
                                               value="", 
                                               title=buf, 
                                               disabled=True, 
                                               width=60, 
                                               height=40
                                              )
                                    )
            buf = "x%d motor" % (i+1)
            self.calib_xmotor.append(
                                     TextInput(
                                               value="", 
                                               title=buf, 
                                               disabled=True, 
                                               width=60, 
                                               height=40
                                              )
                                    )
            buf = "y%d motor" % (i+1)
            self.calib_ymotor.append(
                                     TextInput(
                                               value="", 
                                               title=buf, 
                                               disabled=True, 
                                               width=60, 
                                               height=40
                                              )
                                    )
            self.calib_pt_del_button.append(
                                            Button(
                                                   label="Del", 
                                                   button_type="primary", 
                                                   width=(int)(30), 
                                                   height=25
                                                  )
                                           )
            self.calib_pt_del_button[i].on_click(
                partial(self.clicked_calib_del_pt, idx=i)
            )


        self.calib_xscale_text = TextInput(
                                           value="", 
                                           title="xscale", 
                                           disabled=True, 
                                           width=50, 
                                           height=40, 
                                           css_classes=["custom_input1"]
                                          )
        self.calib_yscale_text = TextInput(
                                           value="", 
                                           title="yscale", 
                                           disabled=True, 
                                           width=50, 
                                           height=40, 
                                           css_classes=["custom_input1"]
                                          )
        self.calib_xtrans_text = TextInput(
                                           value="", 
                                           title="x trans", 
                                           disabled=True, 
                                           width=50, 
                                           height=40, 
                                           css_classes=["custom_input1"]
                                          )
        self.calib_ytrans_text = TextInput(
                                           value="", 
                                           title="y trans", 
                                           disabled=True, 
                                           width=50, 
                                           height=40, 
                                           css_classes=["custom_input1"]
                                          )
        self.calib_rotx_text = TextInput(
                                         value="", 
                                         title="rotx (deg)", 
                                         disabled=True, 
                                         width=50, 
                                         height=40, 
                                         css_classes=["custom_input1"]
                                        )
        self.calib_roty_text = TextInput(
                                         value="", 
                                         title="roty (deg)", 
                                         disabled=True, 
                                         width=50, 
                                         height=40, 
                                         css_classes=["custom_input1"]
                                        )
        
        #calib_plotsmp_check = CheckboxGroup(labels=["don't plot smp 0"], active=[0], width = 50)
        
        self.layout_calib = layout([
            [
             layout(
                    self.calib_sel_motor_loc_marker,
                    self.calib_button_addpt,
                    self.calib_button_calc,
                    self.calib_button_reset,
                    self.calib_button_done,
                    ),
             layout([
                    [
                     Spacer(width=20), 
                     Div(
                         text="<b>Calibration Coordinates</b>",
                         width=200+50,
                         height=15
                        )
                    ],
                    layout(
                        [
                         [Spacer(height=20),self.calib_pt_del_button[0]],
                         Spacer(width=10),
                         self.calib_xplate[0],
                         self.calib_yplate[0],
                         self.calib_xmotor[0],
                         self.calib_ymotor[0]
                        ],
                        Spacer(height=10),
                        Spacer(height=5, background=(0,0,0)),
                        [
                          [Spacer(height=20),self.calib_pt_del_button[1]],
                          Spacer(width=10),
                          self.calib_xplate[1],
                          self.calib_yplate[1],
                          self.calib_xmotor[1],
                          self.calib_ymotor[1]
                        ],
                        Spacer(height=10),
                        Spacer(height=5, background=(0,0,0)),
                        [
                          [Spacer(height=20),self.calib_pt_del_button[2]],
                          Spacer(width=10),
                          self.calib_xplate[2], 
                          self.calib_yplate[2],
                          self.calib_xmotor[2],
                          self.calib_ymotor[2]
                        ],
                        Spacer(height=10),
                        background="#C0C0C0"),
                   ]),
            ],
            [
              layout([[
                      self.calib_xscale_text,
                      self.calib_xtrans_text,
                      self.calib_rotx_text,
                      Spacer(width=10),
                      self.calib_yscale_text,
                      self.calib_ytrans_text,
                      self.calib_roty_text
                    ]]),
            ],
        ])

        
        ######################################################################
        #### Motor group elements ####
        ######################################################################
        self.motor_movexabs_text = TextInput(
                                             value="0", 
                                             title="abs x (mm)", 
                                             disabled=False, 
                                             width=60, 
                                             height=40
                                            )
        self.motor_moveyabs_text = TextInput(
                                             value="0", 
                                             title="abs y (mm)", 
                                             disabled=False, 
                                             width=60, 
                                             height=40
                                            )
        self.motor_moveabs_button = Button(
                                           label="Move", 
                                           button_type="primary", 
                                           width=60
                                          )
        self.motor_moveabs_button.on_event(ButtonClick, self.clicked_moveabs)
        
        self.motor_movexrel_text = TextInput(
                                             value="0", 
                                             title="rel x (mm)", 
                                             disabled=False, 
                                             width=60, 
                                             height=40
                                            )
        self.motor_moveyrel_text = TextInput(
                                             value="0", 
                                             title="rel y (mm)", 
                                             disabled=False, 
                                             width=60, 
                                             height=40
                                            )
        self.motor_moverel_button = Button(
                                           label="Move", 
                                           button_type="primary", 
                                           width=60
                                          )
        self.motor_moverel_button.on_event(ButtonClick, self.clicked_moverel)
        
        self.motor_readxmotor_text = TextInput(
                                               value="0", 
                                               title="motor x (mm)", 
                                               disabled=True, 
                                               width=60, 
                                               height=40
                                              )
        self.motor_readymotor_text = TextInput(
                                               value="0", 
                                               title="motor y (mm)", 
                                               disabled=True, 
                                               width=60, 
                                               height=40
                                              )
        
        
        self.motor_read_button = Button(
                                        label="Read", 
                                        button_type="primary", 
                                        width=60
                                       )
        self.motor_read_button.on_event(
                                        ButtonClick, 
                                        self.clicked_readmotorpos
                                       )
        
        
        self.motor_move_indicator = Toggle(
                                           label="Stage Moving", 
                                           disabled=True, 
                                           button_type="danger", 
                                           width=50
                                          ) #success: green, danger: red
        
        self.motor_movedist_text = TextInput(
                                             value="0", 
                                             title="move (mm)", 
                                             disabled=False, 
                                             width=40, 
                                             height=40
                                            )
        self.motor_move_check = CheckboxGroup(
                                              labels=["Arrows control motor"], 
                                              width=40
                                             )
        
        self.layout_motor = layout([
            layout(
                [
                 [Spacer(height=20),self.motor_moveabs_button],
                 self.motor_movexabs_text,
                 Spacer(width=10),
                 self.motor_moveyabs_text
                ],
                [
                 [Spacer(height=20),self.motor_moverel_button],
                 self.motor_movexrel_text,
                 Spacer(width=10),
                 self.motor_moveyrel_text
                ],
                [
                 [Spacer(height=20),self.motor_read_button],
                  self.motor_readxmotor_text,
                  Spacer(width=10),
                  self.motor_readymotor_text
                ],
                self.motor_move_indicator,
                Spacer(height=15,width=240),
                background="#008080"
            ),
            layout(
                [
                 self.motor_movedist_text,Spacer(width=10),
                 [Spacer(height=25),self.motor_move_check]
                ],
                Spacer(height=10,width=240),
                background="#808000"
            ),
        ])


        dimarrow = 20
        self.motor_buttonup = \
                        Button(
                               label="\u2191", 
                               button_type="danger", 
                               disabled=False, 
                               width=dimarrow, 
                               height=dimarrow,
                               # css_classes=[buf]
                              )
        self.motor_buttondown = \
                        Button(
                               label="\u2193", 
                               button_type="danger", 
                               disabled=False, 
                               width=dimarrow,
                               height=dimarrow,
                               # css_classes=[buf]
                              )
        self.motor_buttonleft = \
                        Button(
                               label="\u2190", 
                               button_type="danger", 
                               disabled=False, 
                               width=dimarrow,
                               height=dimarrow,
                               # css_classes=[buf]
                              )
        self.motor_buttonright = \
                        Button(
                               label="\u2192", 
                               button_type="danger", 
                               disabled=False, 
                               width=dimarrow,
                               height=dimarrow,
                               # css_classes=[buf]
                              )

        self.motor_buttonupleft = \
                        Button(
                               label="\u2196", 
                               button_type="warning", 
                               disabled=False, 
                               width=dimarrow, 
                               height=dimarrow,
                               # css_classes=[buf]
                              )
        self.motor_buttondownleft = \
                        Button(
                               label="\u2199", 
                               button_type="warning", 
                               disabled=False, 
                               width=dimarrow,
                               height=dimarrow,
                               # css_classes=[buf]
                              )
        self.motor_buttonupright = \
                        Button(
                               label="\u2197", 
                               button_type="warning", 
                               disabled=False, 
                               width=dimarrow,
                               height=dimarrow,
                               # css_classes=[buf]
                              )
        self.motor_buttondownright = \
                        Button(
                               label="\u2198", 
                               button_type="warning", 
                               disabled=False, 
                               width=dimarrow,
                               height=dimarrow,
                               # css_classes=[buf]
                              )

        self.motor_step = TextInput(
                                    value=f"{self.manual_step}", 
                                    title="step (mm)", 
                                    disabled=False, 
                                    width=150, 
                                    height=40, 
                                    # css_classes=["custom_input1"]
                                   )


        self.motor_buttonup.on_click(
            partial(self.clicked_move_up)
        )
        self.motor_buttondown.on_click(
            partial(self.clicked_move_down)
        )
        self.motor_buttonleft.on_click(
            partial(self.clicked_move_left)
        )
        self.motor_buttonright.on_click(
            partial(self.clicked_move_right)
        )

        self.motor_buttonupleft.on_click(
            partial(self.clicked_move_upleft)
        )
        self.motor_buttondownleft.on_click(
            partial(self.clicked_move_downleft)
        )
        self.motor_buttonupright.on_click(
            partial(self.clicked_move_upright)
        )
        self.motor_buttondownright.on_click(
            partial(self.clicked_move_downright)
        )

        self.motor_step.on_change(
            "value", 
            partial(self.callback_changed_motorstep, sender=self.motor_step)
        )

        self.motor_mousemove_check = CheckboxGroup(
                                              labels=["Mouse control motor"], 
                                              width=40,
                                              active=[]
                                             )
        self.motor_mousemove_check.on_click(
            partial(self.clicked_motor_mousemove_check)
        )


        self.calib_file_input = FileInput(
                                          width=150,
                                          accept=".json"
                                         )
        self.calib_file_input.on_change('value', self.callback_calib_file_input)



        self.layout_manualmotor = \
             layout([
                        [
                         Spacer(width=20), 
                         Div(
                             text="<b>Manual Motor Control</b>",
                             width=200+50,
                             height=15
                            )
                        ],
                        [gridplot(
                                    [[
                                     self.motor_buttonupleft,
                                     self.motor_buttonup,
                                     self.motor_buttonupright
                                    ],
                                    [
                                     self.motor_buttonleft,
                                     None,
                                     self.motor_buttonright,
                                    ],
                                    [
                                     self.motor_buttondownleft,
                                     self.motor_buttondown,
                                     self.motor_buttondownright,
                                    ]],
                                    width=50,
                                    height=50
                        )],
                        [self.motor_step],
                        [self.motor_mousemove_check],
                        [[
                         Spacer(width=20), 
                         Div(
                             text="<b>calib file:</b>",
                             width=200+50,
                             height=15
                            ),
                         self.calib_file_input
                        ]]
                   ])


        
        ######################################################################
        #### Marker group elements ####
        ######################################################################
        self.marker_type_text = []
        self.marker_move_button = []
        self.marker_buttonsel = []
        self.marker_index = []
        self.marker_sample = []
        self.marker_x = []
        self.marker_y = []
        self.marker_code = []
        self.marker_fraction = []
        self.marker_layout = []
        
        
        for idx in range(len(self.MarkerNames)):
            self.marker_type_text.append(
                                         Paragraph(
                                                   text=f"{self.MarkerNames[idx]} Marker", 
                                                   width=120, 
                                                   height=15
                                                  )
                                        )
            self.marker_move_button.append(
                                           Button(
                                                  label="Move", 
                                                  button_type="primary", 
                                                  width=(int)(self.totalwidth/5-40), 
                                                  height=25
                                                 )
                                          )
            self.marker_index.append(
                                     TextInput(
                                               value="", 
                                               title="Index", 
                                               disabled=True,
                                               width=40, 
                                               height=40, 
                                               css_classes=["custom_input2"]
                                              )
                                    )
            self.marker_sample.append(
                                      TextInput(
                                                value="", 
                                                title="Sample", 
                                                disabled=True, 
                                                width=40, 
                                                height=40, 
                                                css_classes=["custom_input2"]
                                               )
                                     )
            self.marker_x.append(
                                 TextInput(
                                           value="", 
                                           title="x(mm)", 
                                           disabled=True, 
                                           width=40, 
                                           height=40, 
                                           css_classes=["custom_input2"]
                                          )
                                )
            self.marker_y.append(
                                 TextInput(
                                           value="", 
                                           title="y(mm)", 
                                           disabled=True, width=40, 
                                           height=40, 
                                           css_classes=["custom_input2"]
                                          )
                                )
            self.marker_code.append(
                                    TextInput(
                                              value="", 
                                              title="code", 
                                              disabled=True, 
                                              width=40, 
                                              height=40, 
                                              css_classes=["custom_input2"]
                                             )
                                   )
            self.marker_fraction.append(
                                        TextInput(
                                                  value="", 
                                                  title="fraction", 
                                                  disabled=True, 
                                                  width=120, 
                                                  height=40, 
                                                  css_classes=["custom_input2"]
                                                 )
                                       )
            buf = f"custom_button_Marker{(idx+1)}"
            self.marker_buttonsel.append(
                                         Button(
                                                label="", 
                                                button_type="default", 
                                                disabled=False, 
                                                width=40, 
                                                height=40,
                                                css_classes=[buf]
                                               )
                                        )
            self.marker_buttonsel[idx].on_click(
                partial(self.clicked_buttonsel, idx=idx)
            )
            
            self.marker_move_button[idx].on_click(
                partial(self.clicked_button_marker_move, idx=idx)
            )
            
            self.marker_layout.append(
                layout(
                       self.marker_type_text[idx],
                       [
                        self.marker_buttonsel[idx],
                        self.marker_index[idx], 
                        self.marker_sample[idx]
                       ],
                       [
                        self.marker_x[idx],
                        self.marker_y[idx],
                        self.marker_code[idx]
                       ],
                       self.marker_fraction[idx],
                       Spacer(height=5),
                       self.marker_move_button[idx]
                       , width=(int)((self.totalwidth-4*5)/5)
                )
            )
        
        
        # disbale cell marker
        self.marker_move_button[0].disabled=True
        self.marker_buttonsel[0].disabled=True
        
        # combine marker group layouts
        self.layout_markers = layout(
            [[
             self.marker_layout[0], 
             Spacer(width=5, background=(0,0,0)),
             self.marker_layout[1], 
             Spacer(width=5, background=(0,0,0)),
             self.marker_layout[2], 
             Spacer(width=5, background=(0,0,0)),
             self.marker_layout[3], 
             Spacer(width=5, background=(0,0,0)),
             self.marker_layout[4]
            ]],
            background="#C0C0C0"
        )

        ######################################################################
        ## pm plot
        ######################################################################
        self.plot_mpmap = figure(
                                 title="PlateMap", 
                                 height=300,
                                 x_axis_label="X (mm)",
                                 y_axis_label="Y (mm)",
                                 width = self.totalwidth
                                )

        self.plot_mpmap.square(
                               source=self.markerdata,
                               x="x0",
                               y="y0",
                               size=7,
                               line_width=2, 
                               color=None, 
                               alpha=1.0, 
                               line_color=self.MarkerColors[0], 
                               name=self.MarkerNames[0]
                              )

        self.plot_mpmap.rect(
                              6.0*25.4/2,
                              4.0*25.4/2.0,
                              width = 6.0*25.4,
                              height = 4.0*25.4,
                              angle = 0.0,
                              angle_units="rad",
                              fill_alpha=0.0,
                              fill_color="gray",
                              line_width=2,
                              alpha=1.0,
                              line_color=(0,0,0),
                              name="plate_boundary")

        # self.taptool = self.plot_mpmap.select(type=TapTool)
        # self.pantool = self.plot_mpmap.select(type=PanTool)
        self.plot_mpmap.on_event(DoubleTap, self.clicked_pmplot)
        self.plot_mpmap.on_event(MouseWheel, self.clicked_pmplot_mousewheel)
        self.plot_mpmap.on_event(Pan, self.clicked_pmplot_mousepan)
        
        ######################################################################
        # add all to alignerwebdoc
        ######################################################################
        
        self.divmanual = Div(text="""<b>Hotkeys:</b> Not supported by bokeh. Will be added later.<svg width="20" height="20">
        <rect width="20" height="20" style="fill:{{supplied_color_str}};stroke-width:3;stroke:rgb(0,0,0)" />
        </svg>""",
        width=self.totalwidth, height=200)
        self.css_styles = Div(text=
            """<style>
            .custom_button_Marker1 button.bk.bk-btn.bk-btn-default {
                color: black;
                background-color: #ff0000;
            }
            
            .custom_button_Marker2 button.bk.bk-btn.bk-btn-default {
                color: black;
                background-color: #0000ff;
            }
            
            .custom_button_Marker3 button.bk.bk-btn.bk-btn-default {
                color: black;
                background-color: #00ff00;
            }
            
            .custom_button_Marker4 button.bk.bk-btn.bk-btn-default {
                color: black;
                background-color: #FFA500;
            }
            
            .custom_button_Marker5 button.bk.bk-btn.bk-btn-default {
                color: black;
                background-color: #FF69B4;
            }
            </style>""")

        self.vis.doc.add_root(self.css_styles)
        self.vis.doc.add_root(
                              layout(
                                  [[
                                    self.layout_getPM,
                                    self.layout_calib, 
                                    self.layout_motor,
                                    self.layout_manualmotor
                                  ]]
                              )
        )
        self.vis.doc.add_root(
            Spacer(height = 5,width = self.totalwidth, background=(0,0,0))
        )
        self.vis.doc.add_root(self.layout_markers)
        self.vis.doc.add_root(
            Spacer(height = 5, width = self.totalwidth, background=(0,0,0))
        )
        self.vis.doc.add_root(self.plot_mpmap)
        self.vis.doc.add_root(self.divmanual)
        
        # init all controls
        self.init_mapaligner()


    def clicked_move_up(self):
        asyncio.gather(
            self.motor_move(
                mode = MoveModes.relative,
                x = 0,
                y = self.manual_step
            )
        )

    def clicked_move_down(self):
        asyncio.gather(
            self.motor_move(
                mode = MoveModes.relative,
                x = 0,
                y = -self.manual_step
            )
        )


    def clicked_move_left(self):
        asyncio.gather(
            self.motor_move(
                mode = MoveModes.relative,
                x = -self.manual_step,
                y = 0
            )
        )


    def clicked_move_right(self):
        asyncio.gather(
            self.motor_move(
                mode = MoveModes.relative,
                x = self.manual_step,
                y = 0
            )
        )


    def clicked_move_upright(self):
        asyncio.gather(
            self.motor_move(
                mode = MoveModes.relative,
                x = self.manual_step,
                y = self.manual_step
            )
        )

    def clicked_move_downright(self):
        asyncio.gather(
            self.motor_move(
                mode = MoveModes.relative,
                x = self.manual_step,
                y = -self.manual_step
            )
        )


    def clicked_move_upleft(self):
        asyncio.gather(
            self.motor_move(
                mode = MoveModes.relative,
                x = -self.manual_step,
                y = self.manual_step
            )
        )


    def clicked_move_downleft(self):
        asyncio.gather(
            self.motor_move(
                mode = MoveModes.relative,
                x = -self.manual_step,
                y = -self.manual_step
            )
        )

    def clicked_motor_mousemove_check(self, new):
        if new:
            self.mouse_control = True
        else:
            self.mouse_control = False


    def callback_calib_file_input(self, attr, old, new):
        filecontent = base64.b64decode(new.encode('ascii')).decode('ascii')
        try:
            new_matrix = np.matrix(json.loads(filecontent))
        except Exception:
            self.vis.print_message("error loading matrix",
                                   error = True)
            new_matrix = self.motor.dflt_matrix

        self.vis.print_message(f"loaded matrix '{new_matrix}'")
        self.motor.update_transfermatrix(newtransfermatrix = new_matrix)


    def callback_changed_motorstep(self, attr, old, new, sender):
        """callback for plateid text input"""
        def to_float(val):
            try:
                return float(val)
            except ValueError:
                return None

        newstep = to_float(new)
        oldstep =  to_float(old)

        if newstep is not None:
            self.manual_step = newstep
        else:
            if oldstep is not None:
                self.manual_step = oldstep
            else:
                self.manual_step = 1
        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value,sender,f"{self.manual_step}")
        )


    def update_input_value(self, sender, value):
        sender.value = value


    def clicked_reset(self):
        """resets aligner to initial params"""
        self.init_mapaligner()
        
    
    def clicked_addpoint(self, event):
        """Add new point to calibration point list and removing last point"""
        # (1) get selected marker
        selMarker = \
            self.MarkerNames.index(self.calib_sel_motor_loc_marker.value)
        # (2) add new platexy point to end of plate point list
        self.calib_ptsplate.append(self.MarkerXYplate[selMarker])
        # (3) get current motor position
        motorxy = self.g_motor_position # gets the displayed position    
        # (4) add new motorxy to motor point list
        self.calib_ptsmotor.append(motorxy)
        self.vis.print_message(f"motorxy: {motorxy}")
        self.vis.print_message(f"platexy: {self.MarkerXYplate[selMarker]}")
        self.vis.doc.add_next_tick_callback(
            partial(
                    self.update_status,
                    f"added Point:\nMotorxy:\n"
                    f"{motorxy}\nPlatexy:\n"+
                    f"{self.MarkerXYplate[selMarker]}"
                   )
        )
    
        # remove first point from calib list
        self.calib_ptsplate.pop(0)
        self.calib_ptsmotor.pop(0)
        # display points
        for i in range(0,3):
            self.vis.doc.add_next_tick_callback(
                partial(self.update_calpointdisplay,i)
            )
    
    
    def clicked_submit(self):
        """submit final results back to aligner server"""
        asyncio.gather(self.finish_alignment(self.TransferMatrix,0))
    
    
    def clicked_go_align(self):
        """start a new alignment procedure"""
        # init the aligner
        self.init_mapaligner()
        
        if self.g_aligning:
            asyncio.gather(self.get_pm())
        else:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status,"Error!\nAlign is invalid!")
            )
    
    
    def clicked_moveabs(self):
        """move motor to abs position"""
        asyncio.gather(
            self.motor_move(
                mode = MoveModes.absolute,
                x = (float)(self.motor_movexabs_text.value), 
                y = (float)(self.motor_moveyabs_text.value)
            )
        )
    
    
    def clicked_moverel(self):
        """move motor by relative amount"""
        asyncio.gather(
            self.motor_move(
                mode = MoveModes.relative,
                x = (float)(self.motor_movexrel_text.value), 
                y = (float)(self.motor_moveyrel_text.value)
            )
        )
    
    
    def clicked_readmotorpos(self):
        """gets current motor position"""
        asyncio.gather(self.motor_getxy()) # updates g_motor_position
    
    
    def clicked_calc(self):
        """wrapper for async calc call"""
        asyncio.gather(self.align_calc())
    
    
    def clicked_skipstep(self):
        """Calculate Transformation Matrix from given points"""
        asyncio.gather(self.finish_alignment(self.initialTransferMatrix,0))
    
    
    def clicked_buttonsel(self, idx):
        """Selects the Marker by clicking on colored buttons"""
        self.calib_sel_motor_loc_marker.value = self.MarkerNames[idx]
    
    
    def clicked_calib_del_pt(self, idx):
        """remove cal point"""
        # remove first point from calib list
        self.calib_ptsplate.pop(idx)
        self.calib_ptsmotor.pop(idx)
        self.calib_ptsplate.insert(0,(None, None, 1))
        self.calib_ptsmotor.insert(0,(None, None, 1))
        # display points
        for i in range(0,3):
            self.vis.doc.add_next_tick_callback(
                partial(self.update_calpointdisplay,i)
            )
    
    
    def clicked_button_marker_move(self, idx):
        """move motor to maker position"""
        if not self.marker_x[idx].value == "None" \
        and not self.marker_y[idx].value == "None":
            asyncio.gather(
                self.motor_move(
                    mode = MoveModes.absolute,
                    x = (float)(self.marker_x[idx].value),
                    y = (float)(self.marker_y[idx].value)
                )
            )


    def clicked_pmplot_mousepan(self, event):
        if self.mouse_control:
            asyncio.gather(
                self.motor_move(
                    mode = MoveModes.relative,
                    x = -self.manual_step*event.delta_x/100,
                    y = -self.manual_step*event.delta_y/100
                )
            )


    def clicked_pmplot_mousewheel(self, event):
        if self.mouse_control:
            if event.delta > 0:
                new_manual_step = self.manual_step*(2*abs(event.delta)/1000)
            else:
                new_manual_step = self.manual_step/(2*abs(event.delta)/1000)

            if new_manual_step < 0.01:
                new_manual_step = 0.01                
            if new_manual_step > 10:
                new_manual_step = 10
                
            self.callback_changed_motorstep(
                attr = "value",
                old = f"{self.manual_step}",
                new = f"{new_manual_step}",
                sender = self.motor_step
            )


    def clicked_pmplot(self, event):
        """double click/tap on PM plot to add/move marker"""
        # get selected Marker
        selMarker = \
            self.MarkerNames.index(self.calib_sel_motor_loc_marker.value)
        # get coordinates of doubleclick
        platex = event.x
        platey = event.y
        # transform to nearest sample point
        PMnum = self.get_samples([platex], [platey])
        buf = ""
        if PMnum is not None:
            if PMnum[0] is not None: # need to check as this can also happen
                platex = self.pmdata[PMnum[0]]['x']
                platey = self.pmdata[PMnum[0]]['y']
                self.MarkerXYplate[selMarker] = (platex,platey,1)
                self.MarkerSample[selMarker] = self.pmdata[PMnum[0]]["Sample"]
                self.MarkerIndex[selMarker] = PMnum[0]
                self.MarkerCode[selMarker] = self.pmdata[PMnum[0]]["code"]
        
                # only display non zero fractions
                buf = ""
                # TODO: test on other platemap
                for fraclet in ("A", "B", "C", "D", "E", "F", "G", "H"):
                    if self.pmdata[PMnum[0]][fraclet] > 0:
                        buf = f"{buf}{fraclet}{self.pmdata[PMnum[0]][fraclet]*100} "
                if len(buf) == 0:
                    buf = "-"
                self.MarkerFraction[selMarker] = buf
            # remove old Marker point
            old_point = self.plot_mpmap.select(name=self.MarkerNames[selMarker])
            if len(old_point)>0:
                self.plot_mpmap.renderers.remove(old_point[0])
            # plot new Marker point
            self.plot_mpmap.square(
                                   platex, 
                                   platey, 
                                   size=7,
                                   line_width=2, 
                                   color=None, 
                                   alpha=1.0, 
                                   line_color=self.MarkerColors[selMarker], 
                                   name=self.MarkerNames[selMarker]
                                  )
            # add Marker positions to list
            self.update_Markerdisplay(selMarker)


    async def finish_alignment(self, newTransfermatrix, errorcode):
        """sends finished alignment back to FastAPI server"""
        if self.active:
            self.motor.update_transfermatrix(newtransfermatrix = newTransfermatrix)
            self.motor.save_transfermatrix(file = self.motor.file_backup_transfermatrix)
            self.motor.save_transfermatrix(file = os.path.join(self.motor.base.db_root, "plate_calib",
                             f"{gethostname()}_plate_{self.plateid}_calib.json")
            )
            await self.active.write_file(
                file_type = "plate_calib",
                filename = f"{gethostname()}_plate_{self.plateid}_calib.json",
                output_str = json.dumps(self.motor.transfermatrix.tolist()),
                # header = ";".join(["global_sample_label", "Survey Runs", "Main Runs", "Rack", "Vial", "Dilution Factor"]),
                # sample_str = None
                )


            await self.active.enqueue_data(datamodel = \
                   DataModel(
                             data = {self.active.action.file_conn_keys[0]:\
                                        {
                                            "Transfermatrix":self.motor.transfermatrix.tolist(),
                                            "oldTransfermatrix":self.initialTransferMatrix.tolist(),
                                            "errorcode":f"{errorcode}"
                                        }
                                     },
                             errors = []
                       
                            )
            )
            _ = await self.active.finish()
            self.active = None
            self.plateid = None
            self.g_aligning = False
            self.motor.blocked = False
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status,"Submitted!")
            )
        else:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status,"Error!\nAlign is invalid!")
            )


    async def motor_move(self, mode, x, y):
        """moves the motor by submitting a request to aligner server"""
        if self.g_aligning \
        and not self.motor.motor_busy:
            _ = await self.motor._motor_move(
                d_mm = [x, y],
                axis = ["x", "y"],
                speed = None,
                mode = mode,#MoveModes.absolute,
                transformation = TransformationModes.platexy
            )
        elif self.motor.motor_busy:
            self.vis.print_message("motor is busy", error = True)


    async def motor_getxy(self):
        """gets current motor position from alignment server"""
        if self.g_aligning:
            _ = await self.motor.query_axis_position(axis = ["x", "y"])
        else:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status,"Error!\nAlign is invalid!")
            )
        
    
    async def get_pm(self):
        """gets plate map"""
        if self.g_aligning:
            self.pmdata = self.dataAPI.get_platemap_plateid(self.plateid)
            if self.pmdata:
                self.vis.doc.add_next_tick_callback(
                    partial(self.update_pm_plot_title, self.plateid)
                )
                self.vis.doc.add_next_tick_callback(
                   partial(self.update_status,f"Got plateID:\n {self.plateid}")
                )
                self.vis.doc.add_next_tick_callback(
                    partial(self.update_status,"PM loaded")
                )
                self.vis.doc.add_next_tick_callback(
                    partial(self.update_pm_plot)
                )
            else:
                self.vis.doc.add_next_tick_callback(
                    partial(self.update_status,"Error!\nInvalid plateid!")
                )
                self.g_aligning = False
        else:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status,"Error!\nAlign is invalid!")
            )
        
    
    def xy_to_sample(self, xy, pmapxy):
        """get point from pmap closest to xy"""
        if len(pmapxy):
            diff = pmapxy - xy
            sumdiff = (diff ** 2).sum(axis=1)
            return np.int(np.argmin(sumdiff))
        else:
            return None
    
    
    def get_samples(self, X, Y):
        """get list of samples row number closest to xy"""
        # X and Y are vectors
        xyarr = np.array((X, Y)).T
        pmxy = np.array([[col['x'], col['y']] for col in self.pmdata])
        samples = list(np.apply_along_axis(self.xy_to_sample, 1, xyarr, pmxy))
        return samples
    
    
    def remove_allMarkerpoints(self):
        """Removes all Markers from plot"""
        for idx in range(len(self.MarkerNames)-1):
            # remove old Marker point
            old_point = self.plot_mpmap.select(name=self.MarkerNames[idx+1])
            if len(old_point)>0:
                self.plot_mpmap.renderers.remove(old_point[0])


    def align_1p(self, xyplate, xymotor):
        """One point alignment"""
        # can only calculate the xy offset
        xoff = xymotor[0][0]-xyplate[0][0]
        yoff = xymotor[0][1]-xyplate[0][1]
        M = np.matrix([[1,0,xoff],
                       [0,1,yoff],
                       [0,0,1]])
        return M
    
    
    async def align_calc(self):
        """Calculate Transformation Matrix from given points"""
        global calib_ptsplate, calib_ptsmotor
        global TransferMatrix
        global cutoff
        validpts = []
    
        # check for duplicate points
        platepts, motorpts = self.align_uniquepts(self.calib_ptsplate,self.calib_ptsmotor)
    
        # check if points are not None
        for idx in range(len(platepts)):
            if not self.align_test_point(platepts[idx]) and not self.align_test_point(motorpts[idx]):
                validpts.append(idx)
    
        # select the correct alignment procedure
        if len(validpts) == 3:
            # Three point alignment
            self.vis.print_message("3P alignment")
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status,"3P alignment")
            )
            M = self.align_3p(platepts, motorpts)
        elif len(validpts) == 2:
            # Two point alignment
            self.vis.print_message("2P alignment")
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status,"2P alignment")
            )
    #        # only scale and offsets, no rotation
    #        M = align_2p([platepts[validpts[0]],platepts[validpts[1]]],
    #                     [motorpts[validpts[0]],motorpts[validpts[1]]])
            # only scale and rotation, offsets == 0
            M = self.align_3p([platepts[validpts[0]],platepts[validpts[1]],(0,0,1)],
                         [motorpts[validpts[0]],motorpts[validpts[1]],(0,0,1)])
        elif len(validpts) == 1:
            # One point alignment
            self.vis.print_message("1P alignment")
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status,"1P alignment")
            )
            M = self.align_1p([platepts[validpts[0]]],
                         [motorpts[validpts[0]]])
        else:
            # No alignment
            self.vis.print_message("0P alignment")
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status,"0P alignment")
            )
            M = self.TransferMatrix
            
        M = self.motor.transform.get_Mplate_Msystem(Mxy = M)
        
        self.TransferMatrix = self.cutoffdigits(M, self.cutoff)
        self.vis.print_message("new TransferMatrix:")
        self.vis.print_message(M)
    
    
        self.vis.doc.add_next_tick_callback(partial(self.update_TranferMatrixdisplay))
        self.vis.doc.add_next_tick_callback(partial(self.update_status,'New Matrix:\n'+(str)(M)))
    
    
    ################################################################################
    # Two point alignment
    ################################################################################
    #def align_2p(xyplate,xymotor):
    #    # A = M*B --> M = A*B-1
    #    # A .. xymotor
    #    # B .. xyplate
    #    A = np.matrix([[xymotor[0][0],xymotor[1][0]],
    #                   [xymotor[0][1],xymotor[1][1]]])
    #    B = np.matrix([[xyplate[0][0],xyplate[1][0]],
    #                   [xyplate[0][1],xyplate[1][1]]])
    
    
    #    M = np.matrix([[1,0,xoff],
    #                   [0,1,yoff],
    #                   [0,0,1]])
    #    return M
    
    
    def align_3p(self, xyplate, xymotor):
        """Three point alignment"""
        
        self.vis.print_message("Solving: xyMotor = M * xyPlate")
        # can calculate the full transfer matrix
        # A = M*B --> M = A*B-1
        # A .. xymotor
        # B .. xyplate
        A = np.matrix([[xymotor[0][0],xymotor[1][0],xymotor[2][0]],
                       [xymotor[0][1],xymotor[1][1],xymotor[2][1]],
                       [xymotor[0][2],xymotor[1][2],xymotor[2][2]]])
        B = np.matrix([[xyplate[0][0],xyplate[1][0],xyplate[2][0]],
                       [xyplate[0][1],xyplate[1][1],xyplate[2][1]],
                       [xyplate[0][2],xyplate[1][2],xyplate[2][2]]])
        # solve linear system of equations
        self.vis.print_message(f"xyMotor:\n {A}")
        self.vis.print_message(f"xyPlate:\n {B}")
    
        try:
            M = np.dot(A,B.I)
        except Exception:
            # should not happen when all xyplate coordinates are unique
            # (previous function removes all duplicate xyplate points)
            # but can still produce a not valid Matrix
            # as xymotor plates might not be unique/faulty
            self.vis.print_message("Matrix singular")
            M = TransferMatrix
        return M
    
    
    def align_test_point(self, test_list):
        """Test if point is valid for aligning procedure"""
        return [i for i in range(len(test_list)) if test_list[i] == None] 
    
    
    def align_uniquepts(self, x, y): 
        unique_x = []
        unique_y = []
        for i in range(len(x)):
            if x[i] not in unique_x:
                unique_x.append(x[i])
                unique_y.append(y[i])
        return unique_x, unique_y

    
    def cutoffdigits(self, M, digits):
        for i in range(len(M)):
            for j in range(len(M)):
                M[i,j] = round(M[i,j],digits)
        return M
    
    
    ################################################################################
    # 
    ################################################################################
    def update_calpointdisplay(self, ptid):
        """Updates the calibration point display"""
        self.calib_xplate[ptid].value = (str)(self.calib_ptsplate[ptid][0])
        self.calib_yplate[ptid].value = (str)(self.calib_ptsplate[ptid][1]) 
        self.calib_xmotor[ptid].value = (str)(self.calib_ptsmotor[ptid][0])
        self.calib_ymotor[ptid].value = (str)(self.calib_ptsmotor[ptid][1])
    
    
    def update_status(self, updatestr, reset = 0):
        """updates the web interface status field"""
        if reset:
            self.status_align.value = updatestr
        else:
            oldstatus = self.status_align.value
            self.status_align.value = updatestr+'\n######\n'+oldstatus
    
    
    def update_pm_plot(self):
        """plots the plate map"""
        x = [col['x'] for col in self.pmdata]
        y = [col['y'] for col in self.pmdata]
        # remove old Pmplot
        old_point = self.plot_mpmap.select(name="PMplot")
        if len(old_point)>0:
            self.plot_mpmap.renderers.remove(old_point[0])
        self.plot_mpmap.square(
                               x, 
                               y, 
                               size=5, 
                               color=None, 
                               alpha=0.5, 
                               line_color="black",
                               name="PMplot"
                              )
    
    
    
    def update_Markerdisplay(self, selMarker):
        """updates the Marker display elements"""
        self.marker_x[selMarker].value = (str)(self.MarkerXYplate[selMarker][0])
        self.marker_y[selMarker].value = (str)(self.MarkerXYplate[selMarker][1])
        self.marker_index[selMarker].value = (str)((self.MarkerIndex[selMarker]))
        self.marker_sample[selMarker].value = (str)((self.MarkerSample[selMarker]))
        self.marker_code[selMarker].value = (str)((self.MarkerCode[selMarker]))
        self.marker_fraction[selMarker].value = (str)(self.MarkerFraction[selMarker])
    
    
    def update_TranferMatrixdisplay(self):
        self.calib_xscale_text.value = f"{self.TransferMatrix[0, 0]:.1E}"
        self.calib_yscale_text.value = f"{self.TransferMatrix[1, 1]:.1E}"
        self.calib_xtrans_text.value = f"{self.TransferMatrix[0, 2]:.1E}"
        self.calib_ytrans_text.value = f"{self.TransferMatrix[1, 2]:.1E}"
        self.calib_rotx_text.value = f"{self.TransferMatrix[0, 1]:.1E}"
        self.calib_roty_text.value = f"{self.TransferMatrix[1, 0]:.1E}"


    def update_pm_plot_title(self, plateid):
        self.plot_mpmap.title.text = (f"PlateMap: {plateid}")


    def init_mapaligner(self):
        """resets all parameters"""
        self.initialTransferMatrix = self.motor.transfermatrix
        self.TransferMatrix = self.initialTransferMatrix
        self.calib_ptsplate = [
                               (None, None,1),
                               (None, None,1),
                               (None, None,1)
                              ]
        self.calib_ptsmotor = [
                               (None, None,1),
                               (None, None,1),
                               (None, None,1)
                              ]
        self.MarkerSample = [None, None, None, None, None]
        self.MarkerIndex = [None, None, None, None, None]
        self.MarkerCode = [None, None, None, None, None]
        self.MarkerXYplate = [
                              (None, None,1),
                              (None, None,1),
                              (None, None,1),
                              (None, None,1),
                              (None, None,1)
                             ]
        self.MarkerFraction = [None, None, None, None, None]
        for idx in range(len(self.MarkerNames)):
            self.vis.doc.add_next_tick_callback(
                partial(self.update_Markerdisplay,idx)
            )
        for i in range(0,3):
            self.vis.doc.add_next_tick_callback(
                partial(self.update_calpointdisplay,i)
            )

        self.remove_allMarkerpoints()
        self.vis.doc.add_next_tick_callback(
            partial(self.update_TranferMatrixdisplay)
        )
        self.vis.doc.add_next_tick_callback(
            partial(
                    self.update_status,
                    "Press ""Go"" to start alignment procedure.",
                    reset = 1
            )
        )
        
        # initialize motor position variables
        # by simply moving relative 0
        asyncio.gather(
            self.motor_move(
                mode = MoveModes.relative,
                x = 0,
                y = 0
            )
        )
        
        # force redraw of cell marker
        self.gbuf_motor_position = -1*self.gbuf_motor_position
        self.gbuf_plate_position = -1*self.gbuf_plate_position
        
    
    async def IOloop_aligner(self): # non-blocking coroutine, updates data source
        """IOloop for updating web interface"""
        while True:
            try:
                await asyncio.sleep(0.1)
                self.vis.doc.add_next_tick_callback(partial(self.IOloop_helper))

                msg = await self.motorpos_q.get()
                self.vis.print_message(f"Aligner IO got new pos {msg}",
                                        info = True)
                if "ax" in msg:
                    if 'x' in msg['ax']:
                        idx = msg['ax'].index('x')
                        xmotor = msg['position'][idx]
                    else:
                        xmotor = None
                
                    if 'y' in msg['ax']:
                        idx = msg['ax'].index('y')
                        ymotor = msg['position'][idx]
                    else:
                        ymotor = None
                    self.g_motor_position = [xmotor, ymotor, 1] # dim needs to be always + 1 for later transformations
    
                    self.vis.print_message(f"Motor :{self.g_motor_position}",
                                            info = True)
                elif "motor_status" in msg:
                    if all(status == "stopped" for status in msg["motor_status"]):
                        self.g_motor_ismoving = False
                    else:
                        self.g_motor_ismoving = True

                    
                self.motorpos_q.task_done()
            except Exception as e:
                print(e)


    def IOloop_helper(self):
        self.motor_readxmotor_text.value = (str)(self.g_motor_position[0])
        self.motor_readymotor_text.value = (str)(self.g_motor_position[1])
        if self.g_motor_ismoving:
            self.motor_move_indicator.label = "Stage Moving"
            self.motor_move_indicator.button_type = "danger"
        else:
            self.motor_move_indicator.label = "Stage Stopped"
            self.motor_move_indicator.button_type = "success"
    
        # only update marker when positions differ
        # to remove flicker
        if not self.gbuf_motor_position == self.g_motor_position:
            # convert motorxy to platexy # todo, replace with wsdatapositionbuffer
            tmpplate = self.motor.transform.transform_motorxy_to_platexy(motorxy = self.g_motor_position)
            self.vis.print_message(f"Plate: {tmpplate}", info = True)
            
            # update cell marker position in plot
            self.markerdata.data = {"x0": [tmpplate[0]], "y0": [tmpplate[1]]}    
            self.MarkerXYplate[0] = (tmpplate[0],tmpplate[1],1)
            # get rest of values from nearest point 
            PMnum = self.get_samples([tmpplate[0]], [tmpplate[1]])
            buf = ""
            if PMnum is not None:
                if PMnum[0] is not None: # need to check as this can also happen
                    self.MarkerSample[0] = self.pmdata[PMnum[0]]["Sample"]
                    self.MarkerIndex[0] = PMnum[0]
                    self.MarkerCode[0] = self.pmdata[PMnum[0]]["code"]
            
                    # only display non zero fractions
                    buf = ""
                    # TODO: test on other platemap
                    for fraclet in ("A", "B", "C", "D", "E", "F", "G", "H"):
                        if self.pmdata[PMnum[0]][fraclet] > 0:
                            buf = f"{buf}{fraclet}{self.pmdata[PMnum[0]][fraclet]*100} "
                    if len(buf) == 0:
                        buf = "-"
                    self.MarkerFraction[0] = buf
    
            self.update_Markerdisplay(0)
    
        # buffer position
        self.gbuf_motor_position = self.g_motor_position
