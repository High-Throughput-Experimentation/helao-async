import asyncio
import base64
import json
import os
from socket import gethostname
from functools import partial
import traceback

import numpy as np

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

from helao.helpers import helao_logging as logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER
from helao.servers.vis import Vis
from helao.helpers.legacy_api import HTELegacyAPI
from helao.core.models.data import DataModel
from helao.core.error import ErrorCodes

from helao.drivers.motion.enum import MoveModes, TransformationModes


class Aligner:
    def __init__(self, vis_serv: Vis, motor):
        self.vis = vis_serv
        self.motor = motor
        self.config_dict = self.vis.server_cfg.get("params", {})
        self.dataAPI = HTELegacyAPI(self.vis)
        self.motorpos_q = asyncio.Queue()

        # flag to check if we actual should align

        # dummy value, will be updated during init
        self.g_motor_position = [0, 0, 1]
        # to force drawing of marker
        self.gbuf_motor_position = -1 * self.g_motor_position
        # dummy value, will be updated during init
        self.g_plate_position = [0, 0, 1]
        # to force drawing of marker
        self.gbuf_plate_position = -1 * self.g_plate_position

        # will be updated during init
        self.g_motor_ismoving = False

        self.manual_step = 1  # mm
        self.mouse_control = False
        # initial instrument specific TransferMatrix
        self.initial_plate_transfermatrix = self.motor.plate_transfermatrix
        # self.initial_plate_transfermatrix = np.matrix(
        #                                        [
        #                                         [1,0,0],
        #                                         [0,1,0],
        #                                         [0,0,1]
        #                                        ]
        #                                       )
        self.cutoff = np.array(self.config_dict.get("cutoff", 6))

        # this is now used for plate to motor transformation and will be refined
        self.plate_transfermatrix = self.initial_plate_transfermatrix

        self.markerdata = ColumnDataSource({"x0": [0], "y0": [0]})
        self.create_layout()
        self.motor.aligner = self
        self.IOloop_run = False
        self.IOtask = asyncio.create_task(self.IOloop_aligner())
        self.vis.doc.on_session_destroyed(self.cleanup_session)

    def cleanup_session(self, session_context):
        LOGGER.info("Aligner Bokeh session closed")
        self.IOloop_run = False
        self.IOtask.cancel()

    def create_layout(self):

        self.MarkerColors = [
            (255, 0, 0),
            (0, 0, 255),
            (0, 255, 0),
            (255, 165, 0),
            (255, 105, 180),
        ]

        self.MarkerNames = ["Cell", "Blue", "Green", "Orange", "Pink"]
        self.MarkerSample = [None, None, None, None, None]
        self.MarkerIndex = [None, None, None, None, None]
        self.MarkerCode = [None, None, None, None, None]
        self.MarkerFraction = [None, None, None, None, None]

        # for 2D transformation, the vectors (and Matrix) need to be 3D
        self.MarkerXYplate = [
            (None, None, 1),
            (None, None, 1),
            (None, None, 1),
            (None, None, 1),
            (None, None, 1),
        ]
        # 3dim vector because of transformation matrix
        self.calib_ptsplate = [(None, None, 1), (None, None, 1), (None, None, 1)]

        self.calib_ptsmotor = [(None, None, 1), (None, None, 1), (None, None, 1)]

        # PM data given as parameter or empty and needs to be loaded
        self.pmdata = []

        self.totalwidth = 800

        ######################################################################
        #### getPM group elements ###
        ######################################################################

        self.button_goalign = Button(label="Go", button_type="danger", width=150)
        self.button_skipalign = Button(
            label="Skip this step", button_type="default", width=150
        )
        self.button_goalign.on_event(ButtonClick, self.clicked_go_align)
        self.button_skipalign.on_event(ButtonClick, self.clicked_skipstep)
        self.status_align = TextAreaInput(
            value="", rows=8, title="Alignment Status:", disabled=True, width=150
        )

        self.aligner_enabled_status = Toggle(
            label="Disabled", disabled=True, button_type="danger", width=50
        )  # success: green, danger: red

        self.layout_getPM = layout(
            self.button_goalign,
            self.button_skipalign,
            self.status_align,
            self.aligner_enabled_status,
        )

        ######################################################################
        #### Calibration group elements ###
        ######################################################################

        self.calib_sel_motor_loc_marker = Select(
            title="Active Marker",
            value=self.MarkerNames[1],
            options=self.MarkerNames[1:],
            width=110 - 50,
        )

        self.calib_button_addpt = Button(
            label="Add Pt", button_type="default", width=110 - 50
        )
        self.calib_button_addpt.on_event(ButtonClick, self.clicked_addpoint)

        # Calc. Motor-Plate Coord. Transform
        self.calib_button_calc = Button(
            label="Calc", button_type="primary", width=110 - 50
        )
        self.calib_button_calc.on_event(ButtonClick, self.clicked_calc)

        self.calib_button_reset = Button(
            label="Reset", button_type="default", width=110 - 50
        )
        self.calib_button_reset.on_event(ButtonClick, self.clicked_reset)

        self.calib_button_done = Button(
            label="Sub.", button_type="danger", width=110 - 50
        )
        self.calib_button_done.on_event(ButtonClick, self.clicked_submit)

        self.calib_xplate = []
        self.calib_yplate = []
        self.calib_xmotor = []
        self.calib_ymotor = []
        self.calib_pt_del_button = []
        for i in range(0, 3):
            buf = "x%d plate" % (i + 1)
            self.calib_xplate.append(
                TextInput(value="", title=buf, disabled=True, width=60, height=40)
            )
            buf = "y%d plate" % (i + 1)
            self.calib_yplate.append(
                TextInput(value="", title=buf, disabled=True, width=60, height=40)
            )
            buf = "x%d motor" % (i + 1)
            self.calib_xmotor.append(
                TextInput(value="", title=buf, disabled=True, width=60, height=40)
            )
            buf = "y%d motor" % (i + 1)
            self.calib_ymotor.append(
                TextInput(value="", title=buf, disabled=True, width=60, height=40)
            )
            self.calib_pt_del_button.append(
                Button(label="Del", button_type="primary", width=(int)(30), height=25)
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
            css_classes=["custom_input1"],
        )
        self.calib_yscale_text = TextInput(
            value="",
            title="yscale",
            disabled=True,
            width=50,
            height=40,
            css_classes=["custom_input1"],
        )
        self.calib_xtrans_text = TextInput(
            value="",
            title="x trans",
            disabled=True,
            width=50,
            height=40,
            css_classes=["custom_input1"],
        )
        self.calib_ytrans_text = TextInput(
            value="",
            title="y trans",
            disabled=True,
            width=50,
            height=40,
            css_classes=["custom_input1"],
        )
        self.calib_rotx_text = TextInput(
            value="",
            title="rotx (deg)",
            disabled=True,
            width=50,
            height=40,
            css_classes=["custom_input1"],
        )
        self.calib_roty_text = TextInput(
            value="",
            title="roty (deg)",
            disabled=True,
            width=50,
            height=40,
            css_classes=["custom_input1"],
        )

        # calib_plotsmp_check = CheckboxGroup(labels=["don't plot smp 0"], active=[0], width = 50)

        self.layout_calib = layout(
            [
                [
                    layout(
                        self.calib_sel_motor_loc_marker,
                        self.calib_button_addpt,
                        self.calib_button_calc,
                        self.calib_button_reset,
                        self.calib_button_done,
                    ),
                    layout(
                        [
                            [
                                Spacer(width=20),
                                Div(
                                    text="<b>Calibration Coordinates</b>",
                                    width=200 + 50,
                                    height=15,
                                ),
                            ],
                            layout(
                                [
                                    [Spacer(height=20), self.calib_pt_del_button[0]],
                                    Spacer(width=10),
                                    self.calib_xplate[0],
                                    self.calib_yplate[0],
                                    self.calib_xmotor[0],
                                    self.calib_ymotor[0],
                                ],
                                Spacer(height=10),
                                Spacer(height=5, background=(0, 0, 0)),
                                [
                                    [Spacer(height=20), self.calib_pt_del_button[1]],
                                    Spacer(width=10),
                                    self.calib_xplate[1],
                                    self.calib_yplate[1],
                                    self.calib_xmotor[1],
                                    self.calib_ymotor[1],
                                ],
                                Spacer(height=10),
                                Spacer(height=5, background=(0, 0, 0)),
                                [
                                    [Spacer(height=20), self.calib_pt_del_button[2]],
                                    Spacer(width=10),
                                    self.calib_xplate[2],
                                    self.calib_yplate[2],
                                    self.calib_xmotor[2],
                                    self.calib_ymotor[2],
                                ],
                                Spacer(height=10),
                                background="#C0C0C0",
                            ),
                        ]
                    ),
                ],
                [
                    layout(
                        [
                            [
                                self.calib_xscale_text,
                                self.calib_xtrans_text,
                                self.calib_rotx_text,
                                Spacer(width=10),
                                self.calib_yscale_text,
                                self.calib_ytrans_text,
                                self.calib_roty_text,
                            ]
                        ]
                    ),
                ],
            ]
        )

        ######################################################################
        #### Motor group elements ####
        ######################################################################
        self.motor_movexabs_text = TextInput(
            value="0", title="abs x (mm)", disabled=False, width=60, height=40
        )
        self.motor_moveyabs_text = TextInput(
            value="0", title="abs y (mm)", disabled=False, width=60, height=40
        )
        self.motor_moveabs_button = Button(
            label="Move", button_type="primary", width=60
        )
        self.motor_moveabs_button.on_event(ButtonClick, self.clicked_moveabs)

        self.motor_movexrel_text = TextInput(
            value="0", title="rel x (mm)", disabled=False, width=60, height=40
        )
        self.motor_moveyrel_text = TextInput(
            value="0", title="rel y (mm)", disabled=False, width=60, height=40
        )
        self.motor_moverel_button = Button(
            label="Move", button_type="primary", width=60
        )
        self.motor_moverel_button.on_event(ButtonClick, self.clicked_moverel)

        self.motor_readxmotor_text = TextInput(
            value="0", title="motor x (mm)", disabled=True, width=60, height=40
        )
        self.motor_readymotor_text = TextInput(
            value="0", title="motor y (mm)", disabled=True, width=60, height=40
        )

        self.motor_read_button = Button(label="Read", button_type="primary", width=60)
        self.motor_read_button.on_event(ButtonClick, self.clicked_readmotorpos)

        self.motor_move_indicator = Toggle(
            label="Stage Moving", disabled=True, button_type="danger", width=50
        )  # success: green, danger: red

        self.motor_movedist_text = TextInput(
            value="0", title="move (mm)", disabled=False, width=40, height=40
        )
        self.motor_move_check = CheckboxGroup(labels=["Arrows control motor"], width=40)

        self.layout_motor = layout(
            [
                layout(
                    [
                        [Spacer(height=20), self.motor_moveabs_button],
                        self.motor_movexabs_text,
                        Spacer(width=10),
                        self.motor_moveyabs_text,
                    ],
                    [
                        [Spacer(height=20), self.motor_moverel_button],
                        self.motor_movexrel_text,
                        Spacer(width=10),
                        self.motor_moveyrel_text,
                    ],
                    [
                        [Spacer(height=20), self.motor_read_button],
                        self.motor_readxmotor_text,
                        Spacer(width=10),
                        self.motor_readymotor_text,
                    ],
                    self.motor_move_indicator,
                    Spacer(height=15, width=240),
                    background="#008080",
                ),
                layout(
                    [
                        self.motor_movedist_text,
                        Spacer(width=10),
                        [Spacer(height=25), self.motor_move_check],
                    ],
                    Spacer(height=10, width=240),
                    background="#808000",
                ),
            ]
        )

        dimarrow = 20
        self.motor_buttonup = Button(
            label="\u2191",
            button_type="danger",
            disabled=False,
            width=dimarrow,
            height=dimarrow,
            # css_classes=[buf]
        )
        self.motor_buttondown = Button(
            label="\u2193",
            button_type="danger",
            disabled=False,
            width=dimarrow,
            height=dimarrow,
            # css_classes=[buf]
        )
        self.motor_buttonleft = Button(
            label="\u2190",
            button_type="danger",
            disabled=False,
            width=dimarrow,
            height=dimarrow,
            # css_classes=[buf]
        )
        self.motor_buttonright = Button(
            label="\u2192",
            button_type="danger",
            disabled=False,
            width=dimarrow,
            height=dimarrow,
            # css_classes=[buf]
        )

        self.motor_buttonupleft = Button(
            label="\u2196",
            button_type="warning",
            disabled=False,
            width=dimarrow,
            height=dimarrow,
            # css_classes=[buf]
        )
        self.motor_buttondownleft = Button(
            label="\u2199",
            button_type="warning",
            disabled=False,
            width=dimarrow,
            height=dimarrow,
            # css_classes=[buf]
        )
        self.motor_buttonupright = Button(
            label="\u2197",
            button_type="warning",
            disabled=False,
            width=dimarrow,
            height=dimarrow,
            # css_classes=[buf]
        )
        self.motor_buttondownright = Button(
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

        self.motor_buttonup.on_click(partial(self.clicked_move_up))
        self.motor_buttondown.on_click(partial(self.clicked_move_down))
        self.motor_buttonleft.on_click(partial(self.clicked_move_left))
        self.motor_buttonright.on_click(partial(self.clicked_move_right))

        self.motor_buttonupleft.on_click(partial(self.clicked_move_upleft))
        self.motor_buttondownleft.on_click(partial(self.clicked_move_downleft))
        self.motor_buttonupright.on_click(partial(self.clicked_move_upright))
        self.motor_buttondownright.on_click(partial(self.clicked_move_downright))

        self.motor_step.on_change(
            "value", partial(self.callback_changed_motorstep, sender=self.motor_step)
        )

        self.motor_mousemove_check = CheckboxGroup(
            labels=["Mouse control motor"], width=40, active=[]
        )
        self.motor_mousemove_check.on_click(partial(self.clicked_motor_mousemove_check))

        self.calib_file_input = FileInput(width=150, accept=".json")
        self.calib_file_input.on_change("value", self.callback_calib_file_input)

        self.layout_manualmotor = layout(
            [
                [
                    Spacer(width=20),
                    Div(text="<b>Manual Motor Control</b>", width=200 + 50, height=15),
                ],
                [
                    gridplot(
                        [
                            [
                                self.motor_buttonupleft,
                                self.motor_buttonup,
                                self.motor_buttonupright,
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
                            ],
                        ],
                        width=50,
                        height=50,
                    )
                ],
                [self.motor_step],
                [self.motor_mousemove_check],
                [
                    [
                        Spacer(width=20),
                        Div(
                            text="<b>load plate calib file:</b>",
                            width=200 + 50,
                            height=15,
                        ),
                        self.calib_file_input,
                    ]
                ],
            ]
        )

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
                Paragraph(text=f"{self.MarkerNames[idx]} Marker", width=120, height=15)
            )
            self.marker_move_button.append(
                Button(
                    label="Move",
                    button_type="primary",
                    width=(int)(self.totalwidth / 5 - 40),
                    height=25,
                )
            )
            self.marker_index.append(
                TextInput(
                    value="",
                    title="Index",
                    disabled=True,
                    width=40,
                    height=40,
                    css_classes=["custom_input2"],
                )
            )
            self.marker_sample.append(
                TextInput(
                    value="",
                    title="Sample",
                    disabled=True,
                    width=40,
                    height=40,
                    css_classes=["custom_input2"],
                )
            )
            self.marker_x.append(
                TextInput(
                    value="",
                    title="x(mm)",
                    disabled=True,
                    width=140,
                    height=40,
                    css_classes=["custom_input2"],
                )
            )
            self.marker_y.append(
                TextInput(
                    value="",
                    title="y(mm)",
                    disabled=True,
                    width=140,
                    height=40,
                    css_classes=["custom_input2"],
                )
            )
            self.marker_code.append(
                TextInput(
                    value="",
                    title="code",
                    disabled=True,
                    width=40,
                    height=40,
                    css_classes=["custom_input2"],
                )
            )
            self.marker_fraction.append(
                TextInput(
                    value="",
                    title="fraction",
                    disabled=True,
                    width=90,
                    height=40,
                    css_classes=["custom_input2"],
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
                    css_classes=[buf],
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
                        self.marker_sample[idx],
                    ],
                    self.marker_x[idx],
                    self.marker_y[idx],
                    [
                        self.marker_code[idx],
                        self.marker_fraction[idx],
                    ],
                    Spacer(height=5),
                    self.marker_move_button[idx],
                    width=(int)((self.totalwidth - 4 * 5) / 5),
                )
            )

        # disbale cell marker
        self.marker_move_button[0].disabled = True
        self.marker_buttonsel[0].disabled = True

        # combine marker group layouts
        self.layout_markers = layout(
            [
                [
                    self.marker_layout[0],
                    Spacer(width=5, background=(0, 0, 0)),
                    self.marker_layout[1],
                    Spacer(width=5, background=(0, 0, 0)),
                    self.marker_layout[2],
                    Spacer(width=5, background=(0, 0, 0)),
                    self.marker_layout[3],
                    Spacer(width=5, background=(0, 0, 0)),
                    self.marker_layout[4],
                ]
            ],
            background="#C0C0C0",
        )

        ######################################################################
        ## pm plot
        ######################################################################
        self.plot_mpmap = figure(
            title="PlateID",
            # height=300,
            x_axis_label="X (mm)",
            y_axis_label="Y (mm)",
            width=self.totalwidth,
            aspect_ratio=6 / 4,  # 1,
            aspect_scale=1,
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
            name=self.MarkerNames[0],
        )

        self.plot_mpmap.rect(
            6.0 * 25.4 / 2,
            4.0 * 25.4 / 2.0,
            width=6.0 * 25.4,
            height=4.0 * 25.4,
            angle=0.0,
            angle_units="rad",
            fill_alpha=0.0,
            fill_color="gray",
            line_width=2,
            alpha=1.0,
            line_color=(0, 0, 0),
            name="plate_boundary",
        )

        # self.taptool = self.plot_mpmap.select(type=TapTool)
        # self.pantool = self.plot_mpmap.select(type=PanTool)
        self.plot_mpmap.on_event(DoubleTap, self.clicked_pmplot)
        self.plot_mpmap.on_event(MouseWheel, self.clicked_pmplot_mousewheel)
        self.plot_mpmap.on_event(Pan, self.clicked_pmplot_mousepan)

        ######################################################################
        # add all to alignerwebdoc
        ######################################################################

        self.divmanual = Div(
            text="""<b>Hotkeys:</b> Not supported by bokeh. Will be added later.<svg width="20" height="20">
        <rect width="20" height="20" style="fill:{{supplied_color_str}};stroke-width:3;stroke:rgb(0,0,0)" />
        </svg>""",
            width=self.totalwidth,
            height=200,
        )
        self.css_styles = Div(
            text="""<style>
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
            </style>"""
        )

        self.vis.doc.add_root(self.css_styles)
        self.vis.doc.add_root(
            layout(
                [
                    [
                        self.layout_getPM,
                        self.layout_calib,
                        self.layout_motor,
                        self.layout_manualmotor,
                    ]
                ]
            )
        )
        self.vis.doc.add_root(
            Spacer(height=5, width=self.totalwidth, background=(0, 0, 0))
        )
        self.vis.doc.add_root(self.layout_markers)
        self.vis.doc.add_root(
            Spacer(height=5, width=self.totalwidth, background=(0, 0, 0))
        )
        self.vis.doc.add_root(self.plot_mpmap)
        self.vis.doc.add_root(self.divmanual)

        # init all controls
        self.init_mapaligner()

    def clicked_move_up(self):
        asyncio.gather(
            self.motor_move(mode=MoveModes.relative, x=0, y=self.manual_step)
        )

    def clicked_move_down(self):
        asyncio.gather(
            self.motor_move(mode=MoveModes.relative, x=0, y=-self.manual_step)
        )

    def clicked_move_left(self):
        asyncio.gather(
            self.motor_move(mode=MoveModes.relative, x=-self.manual_step, y=0)
        )

    def clicked_move_right(self):
        asyncio.gather(
            self.motor_move(mode=MoveModes.relative, x=self.manual_step, y=0)
        )

    def clicked_move_upright(self):
        asyncio.gather(
            self.motor_move(
                mode=MoveModes.relative, x=self.manual_step, y=self.manual_step
            )
        )

    def clicked_move_downright(self):
        asyncio.gather(
            self.motor_move(
                mode=MoveModes.relative, x=self.manual_step, y=-self.manual_step
            )
        )

    def clicked_move_upleft(self):
        asyncio.gather(
            self.motor_move(
                mode=MoveModes.relative, x=-self.manual_step, y=self.manual_step
            )
        )

    def clicked_move_downleft(self):
        asyncio.gather(
            self.motor_move(
                mode=MoveModes.relative, x=-self.manual_step, y=-self.manual_step
            )
        )

    def clicked_motor_mousemove_check(self, new):
        if new:
            self.mouse_control = True
        else:
            self.mouse_control = False

    def callback_calib_file_input(self, attr, old, new):
        if self.motor.aligning_enabled:
            filecontent = base64.b64decode(new.encode("ascii")).decode("ascii")
            try:
                new_matrix = np.matrix(json.loads(filecontent))
            except Exception as e:
                tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                LOGGER.error(f"error loading matrix ", exc_info=True)
                new_matrix = self.motor.dflt_matrix

            LOGGER.info(f"loaded matrix \n'{new_matrix}'")
            self.motor.update_plate_transfermatrix(newtransfermatrix=new_matrix)
        else:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status, "Error!\nAlign is invalid!")
            )

    def callback_changed_motorstep(self, attr, old, new, sender):
        """callback for motor_step input"""

        def to_float(val):
            try:
                return float(val)
            except ValueError:
                return None

        newstep = to_float(new)
        oldstep = to_float(old)

        if newstep is None:
            if oldstep is not None:
                newstep = oldstep
            else:
                newstep = 1

        if newstep < 0.01:
            newstep = 0.01
        if newstep > 10:
            newstep = 10

        self.manual_step = newstep

        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.manual_step}")
        )

    def update_input_value(self, sender, value):
        sender.value = value

    def clicked_reset(self):
        """resets aligner to initial params"""
        self.init_mapaligner()

    def clicked_addpoint(self, event):
        """Add new point to calibration point list and removing last point"""
        # (1) get selected marker
        selMarker = self.MarkerNames.index(self.calib_sel_motor_loc_marker.value)
        # (2) add new platexy point to end of plate point list
        self.calib_ptsplate.append(self.MarkerXYplate[selMarker])
        # (3) get current motor position
        motorxy = self.g_motor_position  # gets the displayed position
        # (4) add new motorxy to motor point list
        self.calib_ptsmotor.append(motorxy)
        LOGGER.info(f"motorxy: {motorxy}")
        LOGGER.info(f"platexy: {self.MarkerXYplate[selMarker]}")
        self.vis.doc.add_next_tick_callback(
            partial(
                self.update_status,
                f"added Point:\nMotorxy:\n"
                f"{motorxy}\nPlatexy:\n" + f"{self.MarkerXYplate[selMarker]}",
            )
        )

        # remove first point from calib list
        self.calib_ptsplate.pop(0)
        self.calib_ptsmotor.pop(0)
        # display points
        for i in range(0, 3):
            self.vis.doc.add_next_tick_callback(partial(self.update_calpointdisplay, i))

    def clicked_submit(self):
        """submit final results back to aligner server"""
        asyncio.gather(
            self.finish_alignment(self.plate_transfermatrix, ErrorCodes.none)
        )

    def clicked_go_align(self):
        """start a new alignment procedure"""
        # init the aligner
        self.init_mapaligner()

        if self.motor.aligning_enabled:
            asyncio.gather(self.get_pm())
        else:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status, "Error!\nAlign is invalid!")
            )

    def clicked_moveabs(self):
        """move motor to abs position"""
        asyncio.gather(
            self.motor_move(
                mode=MoveModes.absolute,
                x=(float)(self.motor_movexabs_text.value),
                y=(float)(self.motor_moveyabs_text.value),
            )
        )

    def clicked_moverel(self):
        """move motor by relative amount"""
        asyncio.gather(
            self.motor_move(
                mode=MoveModes.relative,
                x=(float)(self.motor_movexrel_text.value),
                y=(float)(self.motor_moveyrel_text.value),
            )
        )

    def clicked_readmotorpos(self):
        """gets current motor position"""
        asyncio.gather(self.motor_getxy())  # updates g_motor_position

    def clicked_calc(self):
        """wrapper for async calc call"""
        asyncio.gather(self.align_calc())

    def clicked_skipstep(self):
        """Calculate Transformation Matrix from given points"""
        asyncio.gather(
            self.finish_alignment(self.initial_plate_transfermatrix, ErrorCodes.none)
        )

    def stop_align(self):
        asyncio.gather(
            self.finish_alignment(self.motor.plate_transfermatrix, ErrorCodes.stop)
        )

    def clicked_buttonsel(self, idx):
        """Selects the Marker by clicking on colored buttons"""
        self.calib_sel_motor_loc_marker.value = self.MarkerNames[idx]

    def clicked_calib_del_pt(self, idx):
        """remove cal point"""
        # remove first point from calib list
        self.calib_ptsplate.pop(idx)
        self.calib_ptsmotor.pop(idx)
        self.calib_ptsplate.insert(0, (None, None, 1))
        self.calib_ptsmotor.insert(0, (None, None, 1))
        # display points
        for i in range(0, 3):
            self.vis.doc.add_next_tick_callback(partial(self.update_calpointdisplay, i))

    def clicked_button_marker_move(self, idx):
        """move motor to maker position"""
        if (
            not self.marker_x[idx].value == "None"
            and not self.marker_y[idx].value == "None"
        ):
            asyncio.gather(
                self.motor_move(
                    mode=MoveModes.absolute,
                    x=(float)(self.marker_x[idx].value),
                    y=(float)(self.marker_y[idx].value),
                )
            )

    def clicked_pmplot_mousepan(self, event):
        if self.mouse_control:
            asyncio.gather(
                self.motor_move(
                    mode=MoveModes.relative,
                    x=-self.manual_step * event.delta_x / 100,
                    y=-self.manual_step * event.delta_y / 100,
                )
            )

    def clicked_pmplot_mousewheel(self, event):
        if self.mouse_control:
            if event.delta > 0:
                new_manual_step = self.manual_step * (2 * abs(event.delta) / 1000)
            else:
                new_manual_step = self.manual_step / (2 * abs(event.delta) / 1000)

            if new_manual_step < 0.01:
                new_manual_step = 0.01
            if new_manual_step > 10:
                new_manual_step = 10

            self.callback_changed_motorstep(
                attr="value",
                old=f"{self.manual_step}",
                new=f"{new_manual_step}",
                sender=self.motor_step,
            )

    def clicked_pmplot(self, event):
        """double click/tap on PM plot to add/move marker"""
        # get selected Marker
        selMarker = self.MarkerNames.index(self.calib_sel_motor_loc_marker.value)
        # get coordinates of doubleclick
        platex = event.x
        platey = event.y
        # transform to nearest sample point
        PMnum = self.get_samples([platex], [platey])
        buf = ""
        if PMnum is not None:
            if PMnum[0] is not None:  # need to check as this can also happen
                platex = self.pmdata[PMnum[0]]["x"]
                platey = self.pmdata[PMnum[0]]["y"]
                self.MarkerXYplate[selMarker] = (platex, platey, 1)
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
            if len(old_point) > 0:
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
                name=self.MarkerNames[selMarker],
            )
            # add Marker positions to list
            self.update_Markerdisplay(selMarker)

    async def finish_alignment(self, newTransfermatrix, errorcode):
        """sends finished alignment back to FastAPI server"""
        if self.motor.aligner_active:
            self.motor.update_plate_transfermatrix(newtransfermatrix=newTransfermatrix)
            # state is now saved within update
            # self.motor.save_transfermatrix(file = self.motor.file_backup_transfermatrix)
            self.motor.save_transfermatrix(
                file=os.path.join(
                    self.motor.base.helaodirs.db_root,
                    "plate_calib",
                    f"{gethostname().lower()}_plate_{self.motor.aligner_plateid}_calib.json",
                )
            )
            self.motor.aligner_active.action.error_code = (
                self.motor.base.get_main_error(errorcode)
            )
            await self.motor.aligner_active.write_file(
                file_type="plate_calib",
                filename=f"{gethostname().lower()}_plate_{self.motor.aligner_plateid}_calib.json",
                output_str=json.dumps(self.motor.plate_transfermatrix.tolist()),
                # header = ";".join(["global_sample_label", "Survey Runs", "Main Runs", "Rack", "Vial", "Dilution Factor"]),
                # sample_str = None
            )

            await self.motor.aligner_active.enqueue_data(
                datamodel=DataModel(
                    data={
                        self.motor.aligner_active.action.file_conn_keys[0]: {
                            "Transfermatrix": self.motor.plate_transfermatrix.tolist(),
                            "oldTransfermatrix": self.initial_plate_transfermatrix.tolist(),
                            "err_code": f"{errorcode}",
                        }
                    },
                    errors=[],
                )
            )
            _ = await self.motor.aligner_active.finish()
            self.motor.aligner_active = None
            self.motor.aligner_plateid = None
            self.motor.aligning_enabled = False
            self.motor.blocked = False
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status, "Submitted!")
            )
            self.vis.doc.add_next_tick_callback(partial(self.IOloop_helper))
        else:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status, "Error!\nAlign is invalid!")
            )

    async def motor_move(self, mode, x, y):
        """moves the motor by submitting a request to aligner server"""
        if self.motor.aligning_enabled and not self.motor.motor_busy:
            _ = await self.motor._motor_move(
                d_mm=[x, y],
                axis=["x", "y"],
                speed=None,
                mode=mode,  # MoveModes.absolute,
                transformation=TransformationModes.platexy,
            )
        elif self.motor.motor_busy:
            LOGGER.error("motor is busy")

    async def motor_getxy(self):
        """gets current motor position from alignment server"""
        if self.motor.aligning_enabled:
            _ = await self.motor.query_axis_position(axis=["x", "y"])
        else:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status, "Error!\nAlign is invalid!")
            )

    async def get_pm(self):
        """gets plate map"""
        if self.motor.aligning_enabled:
            self.pmdata = self.dataAPI.get_platemap_plateid(self.motor.aligner_plateid)
            if self.pmdata:
                self.vis.doc.add_next_tick_callback(
                    partial(self.update_pm_plot_title, self.motor.aligner_plateid)
                )
                self.vis.doc.add_next_tick_callback(
                    partial(
                        self.update_status,
                        f"Got plateID:\n {self.motor.aligner_plateid}",
                    )
                )
                self.vis.doc.add_next_tick_callback(
                    partial(self.update_status, "PM loaded")
                )
                self.vis.doc.add_next_tick_callback(partial(self.update_pm_plot))
            else:
                self.vis.doc.add_next_tick_callback(
                    partial(self.update_status, "Error!\nInvalid plateid!")
                )
                self.motor.aligning_enabled = False
        else:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status, "Error!\nAlign is invalid!")
            )

    def xy_to_sample(self, xy, pmapxy):
        """get point from pmap closest to xy"""
        if len(pmapxy):
            diff = pmapxy - xy
            sumdiff = (diff**2).sum(axis=1)
            return int(np.argmin(sumdiff))
        else:
            return None

    def get_samples(self, X, Y):
        """get list of samples row number closest to xy"""
        # X and Y are vectors
        xyarr = np.array((X, Y)).T
        pmxy = np.array([[col["x"], col["y"]] for col in self.pmdata])
        samples = list(np.apply_along_axis(self.xy_to_sample, 1, xyarr, pmxy))
        return samples

    def remove_allMarkerpoints(self):
        """Removes all Markers from plot"""
        for idx in range(len(self.MarkerNames) - 1):
            # remove old Marker point
            old_point = self.plot_mpmap.select(name=self.MarkerNames[idx + 1])
            if len(old_point) > 0:
                self.plot_mpmap.renderers.remove(old_point[0])

    def align_1p(self, xyplate, xymotor):
        """One point alignment"""
        # can only calculate the xy offset
        xoff = xymotor[0][0] - xyplate[0][0]
        yoff = xymotor[0][1] - xyplate[0][1]
        M = np.matrix([[1, 0, xoff], [0, 1, yoff], [0, 0, 1]])
        return M

    async def align_calc(self):
        """Calculate Transformation Matrix from given points"""
        global calib_ptsplate, calib_ptsmotor
        global TransferMatrix
        global cutoff
        validpts = []

        # check for duplicate points
        platepts, motorpts = self.align_uniquepts(
            self.calib_ptsplate, self.calib_ptsmotor
        )

        # check if points are not None
        for idx in range(len(platepts)):
            if not self.align_test_point(platepts[idx]) and not self.align_test_point(
                motorpts[idx]
            ):
                validpts.append(idx)

        # select the correct alignment procedure
        if len(validpts) == 3:
            # Three point alignment
            LOGGER.info("3P alignment")
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status, "3P alignment")
            )
            M = self.align_3p(platepts, motorpts)
        elif len(validpts) == 2:
            # Two point alignment
            LOGGER.info("2P alignment")
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status, "2P alignment")
            )
            #        # only scale and offsets, no rotation
            #        M = align_2p([platepts[validpts[0]],platepts[validpts[1]]],
            #                     [motorpts[validpts[0]],motorpts[validpts[1]]])
            # only scale and rotation, offsets == 0
            M = self.align_3p(
                [platepts[validpts[0]], platepts[validpts[1]], (0, 0, 1)],
                [motorpts[validpts[0]], motorpts[validpts[1]], (0, 0, 1)],
            )
        elif len(validpts) == 1:
            # One point alignment
            LOGGER.info("1P alignment")
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status, "1P alignment")
            )
            M = self.align_1p([platepts[validpts[0]]], [motorpts[validpts[0]]])
        else:
            # No alignment
            LOGGER.info("0P alignment")
            self.vis.doc.add_next_tick_callback(
                partial(self.update_status, "0P alignment")
            )
            M = self.plate_transfermatrix

        M = self.motor.transform.get_Mplate_Msystem(Mxy=M)

        self.plate_transfermatrix = self.cutoffdigits(M, self.cutoff)
        LOGGER.info("new TransferMatrix:")
        self.vis.print_message(M)

        self.vis.doc.add_next_tick_callback(partial(self.update_TranferMatrixdisplay))
        self.vis.doc.add_next_tick_callback(
            partial(self.update_status, "New Matrix:\n" + (str)(M))
        )

    ################################################################################
    # Two point alignment
    ################################################################################
    # def align_2p(xyplate,xymotor):
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

        LOGGER.info("Solving: xyMotor = M * xyPlate")
        # can calculate the full transfer matrix
        # A = M*B --> M = A*B-1
        # A .. xymotor
        # B .. xyplate
        A = np.matrix(
            [
                [xymotor[0][0], xymotor[1][0], xymotor[2][0]],
                [xymotor[0][1], xymotor[1][1], xymotor[2][1]],
                [xymotor[0][2], xymotor[1][2], xymotor[2][2]],
            ]
        )
        B = np.matrix(
            [
                [xyplate[0][0], xyplate[1][0], xyplate[2][0]],
                [xyplate[0][1], xyplate[1][1], xyplate[2][1]],
                [xyplate[0][2], xyplate[1][2], xyplate[2][2]],
            ]
        )
        # solve linear system of equations
        LOGGER.info(f"xyMotor:\n {A}")
        LOGGER.info(f"xyPlate:\n {B}")

        try:
            M = np.dot(A, B.I)
        except Exception as e:
            tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            # should not happen when all xyplate coordinates are unique
            # (previous function removes all duplicate xyplate points)
            # but can still produce a not valid Matrix
            # as xymotor plates might not be unique/faulty
            LOGGER.error(f"Matrix singular ", exc_info=True)
            M = TransferMatrix
        return M

    def align_test_point(self, test_list):
        """Test if point is valid for aligning procedure"""
        return [i for i in range(len(test_list)) if test_list[i] is None]

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
                M[i, j] = round(M[i, j], digits)
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

    def update_status(self, updatestr, reset=0):
        """updates the web interface status field"""
        if reset:
            self.status_align.value = updatestr
        else:
            oldstatus = self.status_align.value
            self.status_align.value = updatestr + "\n######\n" + oldstatus

    def update_pm_plot(self):
        """plots the plate map"""
        x = [col["x"] for col in self.pmdata]
        y = [col["y"] for col in self.pmdata]
        # remove old Pmplot
        old_point = self.plot_mpmap.select(name="PMplot")
        if len(old_point) > 0:
            self.plot_mpmap.renderers.remove(old_point[0])
        self.plot_mpmap.square(
            x, y, size=5, color=None, alpha=0.5, line_color="black", name="PMplot"
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
        self.calib_xscale_text.value = f"{self.plate_transfermatrix[0, 0]:.1E}"
        self.calib_yscale_text.value = f"{self.plate_transfermatrix[1, 1]:.1E}"
        self.calib_xtrans_text.value = f"{self.plate_transfermatrix[0, 2]:.1E}"
        self.calib_ytrans_text.value = f"{self.plate_transfermatrix[1, 2]:.1E}"
        self.calib_rotx_text.value = f"{self.plate_transfermatrix[0, 1]:.1E}"
        self.calib_roty_text.value = f"{self.plate_transfermatrix[1, 0]:.1E}"

    def update_pm_plot_title(self, plateid):
        self.plot_mpmap.title.text = f"PlateMap: {plateid}"

    def init_mapaligner(self):
        """resets all parameters"""
        self.initial_plate_transfermatrix = self.motor.plate_transfermatrix
        self.plate_transfermatrix = self.initial_plate_transfermatrix
        self.calib_ptsplate = [(None, None, 1), (None, None, 1), (None, None, 1)]
        self.calib_ptsmotor = [(None, None, 1), (None, None, 1), (None, None, 1)]
        self.MarkerSample = [None, None, None, None, None]
        self.MarkerIndex = [None, None, None, None, None]
        self.MarkerCode = [None, None, None, None, None]
        self.MarkerXYplate = [
            (None, None, 1),
            (None, None, 1),
            (None, None, 1),
            (None, None, 1),
            (None, None, 1),
        ]
        self.MarkerFraction = [None, None, None, None, None]
        for idx in range(len(self.MarkerNames)):
            self.vis.doc.add_next_tick_callback(partial(self.update_Markerdisplay, idx))
        for i in range(0, 3):
            self.vis.doc.add_next_tick_callback(partial(self.update_calpointdisplay, i))

        self.remove_allMarkerpoints()
        self.vis.doc.add_next_tick_callback(partial(self.update_TranferMatrixdisplay))
        self.vis.doc.add_next_tick_callback(
            partial(
                self.update_status,
                "Press Go to start alignment procedure.",
                reset=1,
            )
        )

        # initialize motor position variables
        # by simply moving relative 0
        asyncio.gather(self.motor_move(mode=MoveModes.relative, x=0, y=0))

        # force redraw of cell marker
        self.gbuf_motor_position = -1 * self.gbuf_motor_position
        self.gbuf_plate_position = -1 * self.gbuf_plate_position

    async def IOloop_aligner(self):  # non-blocking coroutine, updates data source
        """IOloop for updating web interface"""
        self.IOloop_run = True
        while self.IOloop_run:
            try:
                await asyncio.sleep(0.1)
                self.vis.doc.add_next_tick_callback(partial(self.IOloop_helper))

                msg = await self.motorpos_q.get()
                # self.vis.print_message(f"Aligner IO got new pos {msg}",
                #                         info = True)
                if "ax" in msg:
                    if "x" in msg["ax"]:
                        idx = msg["ax"].index("x")
                        xmotor = msg["position"][idx]
                    else:
                        xmotor = None

                    if "y" in msg["ax"]:
                        idx = msg["ax"].index("y")
                        ymotor = msg["position"][idx]
                    else:
                        ymotor = None
                    self.g_motor_position = [
                        xmotor,
                        ymotor,
                        1,
                    ]  # dim needs to be always + 1 for later transformations

                    LOGGER.info(f"Motor :{self.g_motor_position}")
                elif "motor_status" in msg:
                    if all(status == "stopped" for status in msg["motor_status"]):
                        self.g_motor_ismoving = False
                    else:
                        self.g_motor_ismoving = True

                self.motorpos_q.task_done()
            except Exception as e:
                tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                LOGGER.error(f"aligner IOloop error: ", exc_info=True)

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
            tmpplate = self.motor.transform.transform_motorxy_to_platexy(
                motorxy=self.g_motor_position
            )
            LOGGER.info(f"Plate: {tmpplate}")

            # update cell marker position in plot
            self.markerdata.data = {"x0": [tmpplate[0]], "y0": [tmpplate[1]]}
            self.MarkerXYplate[0] = (tmpplate[0], tmpplate[1], 1)
            # get rest of values from nearest point
            PMnum = self.get_samples([tmpplate[0]], [tmpplate[1]])
            buf = ""
            if PMnum is not None:
                if PMnum[0] is not None:  # need to check as this can also happen
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

        if self.motor.aligning_enabled:
            self.aligner_enabled_status.label = "Enabled"
            self.aligner_enabled_status.button_type = "success"
            self.button_goalign.button_type = "success"

        else:
            self.aligner_enabled_status.label = "Disabled"
            self.aligner_enabled_status.button_type = "danger"
            self.button_goalign.button_type = "danger"

        # buffer position
        self.gbuf_motor_position = self.g_motor_position
