"""
This module defines the BokehOperator class, which is responsible for managing
the Bokeh-based user interface for the HTE (High Throughput Experimentation) 
orchestrator. The BokehOperator class provides methods for interacting with 
the orchestrator, including adding sequences and experiments, updating tables, 
and handling user input.

Classes:
    return_sequence_lib: A Pydantic BaseModel class representing a sequence 
        object with attributes such as index, sequence_name, doc, args, 
        defaults, and argtypes.
    return_experiment_lib: A Pydantic BaseModel class representing an 
        experiment object with attributes such as index, experiment_name, 
        doc, args, defaults, and argtypes.
    BokehOperator: A class that manages the Bokeh-based user interface for 
        the HTE orchestrator. It provides methods for interacting with the 
        orchestrator, updating tables, handling user input, and managing 
        sequences and experiments.

"""
import traceback
import asyncio
import io
import json
import os
import sys
import importlib
from typing import List, Optional
from pybase64 import b64decode
from socket import gethostname
import inspect
from pydantic import BaseModel
import numpy as np
from functools import partial

from helao.helpers import logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

from helao.helpers.to_json import parse_bokeh_input
from helao.helpers.unpack_samples import unpack_samples_helper
from helao.servers.vis import Vis
from helao.helpers.legacy_api import HTELegacyAPI

from helao.helpers.premodels import Experiment
from helao.core.models.orchstatus import LoopStatus
from helao.helpers.premodels import Sequence, Experiment

from bokeh.layouts import column
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource
from bokeh.models import DataTable, TableColumn
from bokeh.models.widgets import Paragraph
from bokeh.models import Select
from bokeh.models import Button
from bokeh.models import CheckboxGroup
from bokeh.models import Panel, Tabs
from bokeh.models.widgets import Div
from bokeh.models.widgets.inputs import TextInput, TextAreaInput
from bokeh.plotting import figure, Figure
from bokeh.events import ButtonClick, DoubleTap
from bokeh.models.widgets import FileInput, Toggle


class return_sequence_lib(BaseModel):
    """Return class for queried sequence objects."""

    index: int
    sequence_name: str
    doc: str
    args: list
    defaults: list
    argtypes: list


class return_experiment_lib(BaseModel):
    """Return class for queried experiment objects."""

    index: int
    experiment_name: str
    doc: str
    args: list
    defaults: list
    argtypes: list


class BokehOperator:
    def __init__(self, vis_serv: Vis, orch):
        self.vis = vis_serv
        self.orch = orch
        self.dataAPI = HTELegacyAPI(self.vis)

        self.config_dict = self.vis.server_cfg.get("params", {})
        self.loaded_config_path = self.vis.world_cfg.get("loaded_config_path", "")
        self.pal_name = None
        self.update_q = asyncio.Queue()
        self.num_actserv = len(
            [
                k
                for k, v in self.vis.world_cfg["servers"].items()
                if "bokeh" not in v and "demovis" not in v
            ]
        )
        # find pal server if configured in world config
        for server_name, server_config in self.vis.world_cfg["servers"].items():
            if server_config.get("fast", "") == "pal_server":
                self.pal_name = server_name
                LOGGER.info(f"found PAL server: '{self.pal_name}'")
                break

        self.dev_customitems = []
        if self.pal_name is not None:
            pal_server_params = self.vis.world_cfg["servers"][self.pal_name]["params"]
            if "positions" in pal_server_params:
                dev_custom = pal_server_params["positions"].get("custom", {})
            else:
                dev_custom = {}
            self.dev_customitems = [key for key in dev_custom.keys()]

        self.color_sq_param_inputs = "#F9E79F"
        self.max_width = 1024
        # holds the page layout
        self.layout = []
        self.seq_param_layout = []
        self.seq_param_input = []
        self.seq_private_input = []
        self.exp_param_layout = []
        self.exp_param_input = []
        self.exp_private_input = []

        self.seqspec_param_layout = []
        self.seqspec_param_input = []
        self.seqspec_private_input = []

        self.sequence = None
        self.experiment_plan_lists = {
            k: [] for k in ["sequence_name", "sequence_label", "experiment_name"]
        }

        self.sequence_lists = {
            k: [] for k in ["sequence_name", "sequence_label", "sequence_uuid"]
        }

        self.experiment_lists = {k: [] for k in ["experiment_name", "experiment_uuid"]}

        self.action_lists = {
            k: [] for k in ["action_name", "action_server", "action_uuid"]
        }

        self.active_action_lists = {
            k: [] for k in ["action_name", "action_server", "action_uuid"]
        }

        self.action_server_lists = {
            k: [] for k in ["action_server", "server_status", "driver_status"]
        }

        self.sequence_select_list = []
        self.sequences = []
        self.sequence_lib = self.orch.sequence_lib

        self.experiment_select_list = []
        self.experiments = []
        self.experiment_lib = self.orch.experiment_lib

        self.seqspec_select_list = []
        self.seqspecs = []
        self.seqspec_parser_module = None
        self.seqspec_parser = None
        self.seqspec_folder = None
        self.parser_path = self.config_dict.get("seqspec_parser_path", None)
        specs_folder = self.config_dict.get("seqspec_folder_path", None)
        if self.parser_path is not None:
            if os.path.exists(self.parser_path) and os.path.isfile(self.parser_path):
                module_name = os.path.basename(self.parser_path).replace(".py", "")
                spec = importlib.util.spec_from_file_location(
                    module_name, self.parser_path
                )
                self.seqspec_parser_module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = self.seqspec_parser_module
                spec.loader.exec_module(self.seqspec_parser_module)
                self.seqspec_parser = self.seqspec_parser_module.SpecParser()
        if specs_folder is not None:
            if os.path.exists(specs_folder) and os.path.isdir(specs_folder):
                self.seqspec_folder = specs_folder

        # FastAPI calls
        self.get_sequence_lib()
        self.get_experiment_lib()

        self.vis.doc.add_next_tick_callback(partial(self.get_sequences))
        self.vis.doc.add_next_tick_callback(partial(self.get_experiments))
        self.vis.doc.add_next_tick_callback(partial(self.get_actions))
        self.vis.doc.add_next_tick_callback(partial(self.get_active_actions))
        self.vis.doc.add_next_tick_callback(partial(self.get_orch_status_summary))

        self.experiment_plan_source = ColumnDataSource(data=self.experiment_plan_lists)
        self.columns_expplan = [
            TableColumn(field=key, title=key) for key in self.experiment_plan_lists
        ]
        self.experiment_plan_table = DataTable(
            source=self.experiment_plan_source,
            columns=self.columns_expplan,
            width=self.max_width - 20,
            height=200,
            autosize_mode="fit_columns",
        )

        self.sequence_source = ColumnDataSource(data=self.sequence_lists)
        self.columns_seq = [
            TableColumn(field=key, title=key) for key in self.sequence_lists
        ]
        self.sequence_table = DataTable(
            source=self.sequence_source,
            columns=self.columns_seq,
            width=self.max_width - 20,
            height=200,
            autosize_mode="fit_columns",
        )

        self.experiment_source = ColumnDataSource(data=self.experiment_lists)
        self.columns_exp = [
            TableColumn(field=key, title=key) for key in self.experiment_lists
        ]
        self.experiment_table = DataTable(
            source=self.experiment_source,
            columns=self.columns_exp,
            width=self.max_width - 20,
            height=200,
            autosize_mode="fit_columns",
        )

        self.action_source = ColumnDataSource(data=self.action_lists)
        self.columns_act = [
            TableColumn(field=key, title=key) for key in self.action_lists
        ]
        self.action_table = DataTable(
            source=self.action_source,
            columns=self.columns_act,
            width=self.max_width - 20,
            height=200,
            autosize_mode="fit_columns",
        )
        self.action_server_source = ColumnDataSource(data=self.action_server_lists)
        self.columns_actserv = [
            TableColumn(field=key, title=key) for key in self.action_server_lists
        ]
        self.action_server_table = DataTable(
            source=self.action_server_source,
            columns=self.columns_actserv,
            width=self.max_width - 20,
            height=200,
            autosize_mode="fit_columns",
        )

        self.sequence_tab = Panel(child=self.sequence_table, title="Sequences")
        self.experiment_tab = Panel(child=self.experiment_table, title="Experiments")
        self.action_tab = Panel(child=self.action_table, title="Actions")
        self.action_server_tab = Panel(
            child=self.action_server_table, title="Action Servers"
        )
        self.queue_tabs = Tabs(
            tabs=[
                self.sequence_tab,
                self.experiment_tab,
                self.action_tab,
                self.action_server_tab,
            ],
            height_policy="min",
        )

        self.active_action_source = ColumnDataSource(data=self.active_action_lists)
        self.columns_active_action = [
            TableColumn(field=key, title=key) for key in self.active_action_lists
        ]
        self.active_action_table = DataTable(
            source=self.active_action_source,
            columns=self.columns_active_action,
            width=self.max_width - 20,
            height=200,
            autosize_mode="fit_columns",
            fit_columns=False,
        )

        self.planner_tab = Panel(
            child=self.experiment_plan_table, title="Sequence Planner"
        )
        self.active_tab = Panel(child=self.active_action_table, title="Active Actions")
        self.planactive_tabs = Tabs(
            tabs=[self.planner_tab, self.active_tab], height_policy="min"
        )

        self.sequence_dropdown = Select(
            title="Select sequence:",
            value=None,
            options=self.sequence_select_list,
        )
        self.sequence_dropdown.on_change("value", self.callback_sequence_select)

        self.experiment_dropdown = Select(
            title="Select experiment:", value=None, options=self.experiment_select_list
        )
        self.experiment_dropdown.on_change("value", self.callback_experiment_select)

        # specification file loader
        self.seqspec_dropdown = Select(
            title="Select spec file:", value=None, options=self.seqspec_select_list
        )
        self.seqspec_dropdown.on_change("value", self.callback_seqspec_select)

        if self.seqspec_parser is not None and self.seqspec_folder is not None:
            self.get_seqspec_lib()

        # buttons to control orch
        self.button_start_orch = Button(
            label="Start Orch", button_type="default", width=70
        )
        self.button_start_orch.on_event(ButtonClick, self.callback_start_orch)
        self.button_estop_orch = Button(
            label="ESTOP", button_type="danger", width=400, height=100
        )
        self.button_estop_orch.on_event(ButtonClick, self.callback_estop_orch)
        self.button_add_expplan = Button(
            label="Add exp plan", button_type="default", width=100
        )
        self.button_add_expplan.on_event(ButtonClick, self.callback_add_expplan)
        self.button_stop_orch = Button(
            label="Stop Orch", button_type="default", width=70
        )
        self.button_stop_orch.on_event(ButtonClick, self.callback_stop_orch)
        self.button_skip_exp = Button(label="Skip exp", button_type="danger", width=70)
        self.button_skip_exp.on_event(ButtonClick, self.callback_skip_exp)
        self.button_update = Button(
            label="Update tables", button_type="default", width=120
        )
        self.button_update.on_event(ButtonClick, self.callback_update_tables)
        self.button_clear_expplan = Button(
            label="Clear expplan", button_type="default", width=100
        )
        self.button_clear_expplan.on_event(ButtonClick, self.callback_clear_expplan)
        self.orch_status_button = Button(
            label="Disabled", disabled=False, button_type="danger", width=400
        )  # success: green, danger: red

        if self.orch.step_thru_actions:
            self.orch_stepact_button = Button(
                label="STEP-THRU actions", button_type="danger", width=170
            )
        else:
            self.orch_stepact_button = Button(
                label="RUN-THRU actions", button_type="success", width=170
            )
        self.orch_stepact_button.on_event(ButtonClick, self.callback_toggle_stepact)

        if self.orch.step_thru_experiments:
            self.orch_stepexp_button = Button(
                label="STEP-THRU experiments", button_type="danger", width=170
            )
        else:
            self.orch_stepexp_button = Button(
                label="RUN-THRU experiments", button_type="success", width=170
            )
        self.orch_stepexp_button.on_event(ButtonClick, self.callback_toggle_stepexp)

        if self.orch.step_thru_experiments:
            self.orch_stepseq_button = Button(
                label="STEP-THRU sequences", button_type="danger", width=170
            )
        else:
            self.orch_stepseq_button = Button(
                label="RUN-THRU sequences", button_type="success", width=170
            )
        self.orch_stepseq_button.on_event(ButtonClick, self.callback_toggle_stepseq)

        self.button_clear_seqs = Button(
            label="Clear seqs", button_type="danger", width=100
        )
        self.button_clear_seqs.on_event(ButtonClick, self.callback_clear_sequences)
        self.button_clear_exps = Button(
            label="Clear exp", button_type="danger", width=100
        )
        self.button_clear_exps.on_event(ButtonClick, self.callback_clear_experiments)
        self.button_clear_action = Button(
            label="Clear act", button_type="danger", width=100
        )
        self.button_clear_action.on_event(ButtonClick, self.callback_clear_actions)

        self.button_prepend_exp = Button(
            label="Prepend exp to exp plan", button_type="default", width=150
        )
        self.button_prepend_exp.on_event(ButtonClick, self.callback_prepend_exp)
        self.button_append_exp = Button(
            label="Append exp to exp plan", button_type="default", width=150
        )
        self.button_append_exp.on_event(ButtonClick, self.callback_append_exp)

        self.button_prepend_seq = Button(
            label="Prepend seq to exp plan",
            button_type="default",
            width=150,
        )
        self.button_prepend_seq.on_event(ButtonClick, self.callback_prepend_seq)
        self.button_append_seq = Button(
            label="Append seq to exp plan", button_type="default", width=150
        )
        self.button_append_seq.on_event(ButtonClick, self.callback_append_seq)

        self.button_last_seq_pars = Button(
            label="Load last seq params", button_type="default", width=150
        )
        self.button_last_seq_pars.on_event(ButtonClick, self.get_last_seq_pars)
        self.button_last_exp_pars = Button(
            label="Load last exp params", button_type="default", width=150
        )
        self.button_last_exp_pars.on_event(ButtonClick, self.get_last_exp_pars)

        self.save_last_exp_pars = CheckboxGroup(labels=["save exp params"], active=[0])
        self.save_last_seq_pars = CheckboxGroup(labels=["save seq params"], active=[0])

        self.button_enqueue_seqspec = Button(
            label="Enqueue specs sequence", button_type="default", width=150
        )
        self.button_enqueue_seqspec.on_event(ButtonClick, self.callback_enqueue_seqspec)

        self.button_reload_seqspec = Button(
            label="Reload specs folder", button_type="default", width=150
        )
        self.button_reload_seqspec.on_event(ButtonClick, self.callback_reload_seqspec)

        self.button_to_seqtab = Button(
            label="To sequence selection", button_type="default", width=150
        )
        self.button_to_seqtab.on_event(ButtonClick, self.callback_to_seqtab)

        self.sequence_descr_txt = Div(
            text="""select a sequence item""", width=600, height_policy="min"
        )
        self.experiment_descr_txt = Div(
            text="""select a experiment item""", width=600, height_policy="min"
        )
        self.seqspec_descr_txt = Div(
            text="""select a sequence specification""", width=600, height_policy="min"
        )

        self.error_txt = Paragraph(
            text="""no error""",
            width=600,
            height=30,
            style={"font-size": "100%", "color": "black"},
        )

        self.input_sequence_label = TextInput(
            value="nolabel",
            title="sequence label",
            disabled=False,
            width=150,
            height=40,
        )
        self.input_sequence_label.on_change("value", self.callback_copy_sequence_label)

        self.input_sequence_label2 = TextInput(
            value="nolabel",
            title="sequence label",
            disabled=False,
            width=150,
            height=40,
        )
        self.input_sequence_label2.on_change(
            "value", self.callback_copy_sequence_label2
        )

        self.input_sequence_comment = TextAreaInput(
            value="",
            title="sequence comment",
            disabled=False,
            width=470,
            height=90,
            rows=3,
        )
        self.input_sequence_comment.on_change(
            "value", self.callback_copy_sequence_comment
        )

        self.input_sequence_comment2 = TextAreaInput(
            value="",
            title="sequence comment",
            disabled=False,
            width=470,
            height=90,
            rows=3,
        )
        self.input_sequence_comment2.on_change(
            "value", self.callback_copy_sequence_comment2
        )

        self.orch_section = Div(
            text="<b>Orchestrator</b>",
            width=self.max_width - 20,
            height=32,
            style={"font-size": "150%", "color": "#CB4335"},
        )

        self.layout0 = layout(
            [
                layout(
                    [
                        Spacer(width=20),
                        Div(
                            text=f"<b>{self.config_dict.get('doc_name', 'BokehOperator')} on {gethostname().lower()} -- config: {os.path.basename(self.loaded_config_path)}</b>",
                            width=self.max_width - 20,
                            height=32,
                            style={"font-size": "200%", "color": "#CB4335"},
                        ),
                    ],
                    # background="#D6DBDF",
                    width=self.max_width,
                ),
                Spacer(height=10),
            ],
            height_policy="min",
        )
        self.layout1 = layout(
            [
                layout(
                    [
                        [
                            self.sequence_dropdown,
                            Spacer(width=20),
                            self.input_sequence_label,
                        ],
                        [self.input_sequence_comment],
                        [
                            Div(
                                text="<b>sequence description:</b>",
                                width=200 + 50,
                                height=15,
                            ),
                        ],
                        [self.sequence_descr_txt],
                        Spacer(height=10),
                    ],
                    background="#D6DBDF",
                    width=self.max_width,
                    height_policy="min",
                ),
                layout(
                    [
                        [
                            self.button_append_seq,
                            self.button_prepend_seq,
                            self.button_last_seq_pars,
                            self.save_last_seq_pars,
                        ]
                    ],
                    background="#D6DBDF",
                    width=self.max_width,
                    height_policy="min",
                ),
            ],
            height_policy="min",
        )

        self.layout2 = layout(
            [
                layout(
                    [
                        [
                            self.experiment_dropdown,
                            Spacer(width=20),
                            self.input_sequence_label2,
                        ],
                        [self.input_sequence_comment2],
                        [
                            Div(
                                text="<b>experiment description:</b>",
                                width=200 + 50,
                                height=15,
                            ),
                        ],
                        [self.experiment_descr_txt],
                        Spacer(height=10),
                    ],
                    background="#D6DBDF",
                    width=self.max_width,
                    height_policy="min",
                ),
                layout(
                    [
                        [
                            self.button_append_exp,
                            self.button_prepend_exp,
                            self.button_last_exp_pars,
                            self.save_last_exp_pars,
                        ],
                    ],
                    background="#D6DBDF",
                    width=self.max_width,
                    height_policy="min",
                ),
            ],
            height_policy="min",
        )

        self.layout3 = layout(
            [
                layout(
                    [
                        [
                            self.seqspec_dropdown,
                            Spacer(width=20),
                            self.input_sequence_label2,
                        ],
                        [self.input_sequence_comment2],
                        [
                            Div(
                                text="<b>sequence spec description:</b>",
                                width=200 + 50,
                                height=15,
                            ),
                        ],
                        [self.seqspec_descr_txt],
                        Spacer(height=10),
                    ],
                    background="#D6DBDF",
                    width=self.max_width,
                    height_policy="min",
                ),
                layout(
                    [
                        [
                            self.button_enqueue_seqspec,
                            Spacer(width=10),
                            self.button_reload_seqspec,
                            Spacer(width=10),
                            self.button_to_seqtab,
                        ],
                    ],
                    background="#D6DBDF",
                    width=self.max_width,
                    height_policy="min",
                ),
            ],
            height_policy="min",
        )

        self.layout4 = layout(
            [
                Spacer(height=10),
                layout(
                    [
                        Spacer(width=20),
                        self.orch_section,
                    ],
                    # background="#D6DBDF",
                    width=self.max_width,
                    height_policy="min",
                ),
                layout(
                    [
                        [
                            self.button_add_expplan,
                            Spacer(width=10),
                            self.button_start_orch,
                            Spacer(width=10),
                            self.button_stop_orch,
                            Spacer(width=10),
                            self.button_clear_expplan,
                            Spacer(width=10),
                            self.orch_status_button,
                        ],
                        Spacer(height=4),
                        [
                            self.orch_stepact_button,
                            Spacer(width=10),
                            self.orch_stepexp_button,
                            Spacer(width=10),
                            self.orch_stepseq_button,
                        ],
                        Spacer(height=10),
                        [
                            Div(
                                text="<b>Error message:</b>",
                                width=200 + 50,
                                height=15,
                                style={"font-size": "100%", "color": "black"},
                            ),
                        ],
                        [Spacer(width=10), self.error_txt],
                        Spacer(height=10),
                    ],
                    background="#D6DBDF",
                    width=self.max_width,
                    height_policy="min",
                ),
                layout(
                    [
                        [
                            Div(
                                text="<b>Non-queued:</b>",
                                width=200 + 50,
                                height=15,
                            ),
                        ],
                        [self.planactive_tabs],
                        [
                            Div(
                                text="<b>Queues:</b>",
                                width=200 + 50,
                                height=15,
                            ),
                        ],
                        [self.queue_tabs],
                        [
                            self.button_add_expplan,
                            Spacer(width=10),
                            self.button_start_orch,
                            Spacer(width=10),
                            self.button_stop_orch,
                            Spacer(width=10),
                            self.button_clear_expplan,
                            Spacer(width=10),
                            self.orch_status_button,
                        ],
                        Spacer(height=10),
                        [
                            self.button_skip_exp,
                            Spacer(width=5),
                            self.button_clear_seqs,
                            Spacer(width=5),
                            self.button_clear_exps,
                            Spacer(width=5),
                            self.button_clear_action,
                            self.button_update,
                        ],
                        Spacer(height=10),
                        self.button_estop_orch,
                        Spacer(height=10),
                    ],
                    background="#AED6F1",
                    width=self.max_width,
                    height_policy="min",
                ),
            ],
            height_policy="min",
        )

        self.sequence_select_tab = Panel(child=self.layout1, title="Sequence Selection")
        self.experiment_select_tab = Panel(
            child=self.layout2, title="Experiment Selection"
        )
        self.seqspec_select_tab = Panel(child=self.layout3, title="Specification Files")
        if self.seqspec_folder is not None and self.seqspec_parser is not None:
            self.select_tabs = Tabs(
                tabs=[
                    self.sequence_select_tab,
                    self.experiment_select_tab,
                    self.seqspec_select_tab,
                ]
            )
        else:
            self.select_tabs = Tabs(
                tabs=[
                    self.sequence_select_tab,
                    self.experiment_select_tab,
                ],
                height_policy="min",
            )
        self.select_tabs.on_change("active", self.update_selector_layout)
        self.dynamic_col = column(
            self.layout0,
            layout(height_policy="min"),
            self.select_tabs,
            layout(height_policy="min"),
            layout(height_policy="min"),
            self.layout4,  # placeholder  # placeholder
        )
        self.vis.doc.add_root(self.dynamic_col)

        # select the first item to force an update of the layout
        if self.experiment_select_list and self.select_tabs.active == 1:
            self.experiment_dropdown.value = self.experiment_select_list[0]

        if self.sequence_select_list and self.select_tabs.active == 0:
            self.sequence_dropdown.value = self.sequence_select_list[0]

        if self.seqspec_select_list and self.select_tabs.active == 2:
            self.seqspec_dropdown.value = self.seqspec_select_list[0]

        self.IOloop_run = False
        self.IOtask = asyncio.create_task(self.IOloop())
        self.vis.doc.on_session_destroyed(self.cleanup_session)
        self.orch.orch_op = self

    def cleanup_session(self, session_context):
        LOGGER.info("BokehOperator session closed")
        self.IOloop_run = False
        self.IOtask.cancel()

    def get_sequence_lib(self):
        """Populates sequences (library) and sequence_list (dropdown selector)."""
        self.sequences = []
        LOGGER.info(f"found sequences: {list(self.sequence_lib)}")
        for i, sequence in enumerate(self.sequence_lib):
            tmpdoc = self.sequence_lib[sequence].__doc__
            if tmpdoc is None:
                tmpdoc = ""

            argspec = inspect.getfullargspec(self.sequence_lib[sequence])
            tmpargs = argspec.args
            tmpdefs = argspec.defaults
            tmptypes = [
                argspec.annotations.get(k, "unspecified") for k in list(tmpargs)
            ]

            if tmpdefs is None:
                tmpdefs = []

            # filter the Sequence BaseModel
            idxlist = []
            # for idx, tmparg in enumerate(argspec.args):
            #     if tmparg=="sequence_version":
            #         idxlist.append(idx)

            tmpargs = list(tmpargs)
            tmpdefs = list(tmpdefs)
            for j, idx in enumerate(idxlist):
                if len(tmpargs) == len(tmpdefs):
                    tmpargs.pop(idx - j)
                    tmpdefs.pop(idx - j)
                    tmptypes.pop(idx - j)
                else:
                    tmpargs.pop(idx - j)
                    tmptypes.pop(idx - j)
            # use defaults specified in config
            seq_defs = self.orch.world_cfg.get("sequence_params", {})
            tmpdefs = [seq_defs.get(ta, td) for ta, td in zip(tmpargs, tmpdefs)]
            tmpargs = tuple(tmpargs)
            tmpdefs = tuple(tmpdefs)
            tmptypes = tuple(tmptypes)

            for t in tmpdefs:
                t = json.dumps(t)

            self.sequences.append(
                return_sequence_lib(
                    index=i,
                    sequence_name=sequence,
                    doc=tmpdoc,
                    args=tmpargs,
                    defaults=tmpdefs,
                    argtypes=tmptypes,
                ).model_dump()
            )
        for item in self.sequences:
            self.sequence_select_list.append(item["sequence_name"])

    def get_experiment_lib(self):
        """Populates experiments (library) and experiment_list (dropdown selector)."""
        self.experiments = []
        LOGGER.info(f"found experiment: {list(self.experiment_lib)}")
        for i, experiment in enumerate(self.experiment_lib):
            tmpdoc = self.experiment_lib[experiment].__doc__
            if tmpdoc is None:
                tmpdoc = ""

            argspec = inspect.getfullargspec(self.experiment_lib[experiment])
            tmpargs = argspec.args
            tmpdefs = argspec.defaults
            tmptypes = [
                argspec.annotations.get(k, "unspecified") for k in list(tmpargs)
            ]
            if tmpdefs is None:
                tmpdefs = []

            # filter the Experiment BaseModel
            idxlist = []
            for idx, tmparg in enumerate(argspec.args):
                # if argspec.annotations.get(tmparg, None) == Experiment or tmparg=="experiment_version":
                if argspec.annotations.get(tmparg, None) == Experiment:
                    idxlist.append(idx)

            tmpargs = list(tmpargs)
            tmpdefs = list(tmpdefs)
            for j, idx in enumerate(idxlist):
                if len(tmpargs) == len(tmpdefs):
                    tmpargs.pop(idx - j)
                    tmpdefs.pop(idx - j)
                    tmptypes.pop(idx - j)
                else:
                    tmpargs.pop(idx - j)
                    tmptypes.pop(idx - j)
            # use defaults specified in config
            exp_defs = self.orch.world_cfg.get("experiment_params", {})
            tmpdefs = [exp_defs.get(ta, td) for ta, td in zip(tmpargs, tmpdefs)]
            tmpargs = tuple(tmpargs)
            tmpdefs = tuple(tmpdefs)
            tmptypes = tuple(tmptypes)

            for t in tmpdefs:
                t = json.dumps(t)

            self.experiments.append(
                return_experiment_lib(
                    index=i,
                    experiment_name=experiment,
                    doc=tmpdoc,
                    args=tmpargs,
                    defaults=tmpdefs,
                    argtypes=tmptypes,
                ).model_dump()
            )
        for item in self.experiments:
            self.experiment_select_list.append(item["experiment_name"])

    def get_seqspec_lib(self):
        """Populates sequence specification library (preset params) and dropdown."""
        self.seqspec_select_list = []
        self.seqspecs = []
        specfiles = self.seqspec_parser.lister(self.seqspec_folder)
        LOGGER.info(f"found specs: {specfiles}")
        for fp in specfiles:
            self.seqspecs.append(fp)
            self.seqspec_select_list.append(os.path.basename(fp))
        self.seqspec_dropdown.options = self.seqspec_select_list

    async def get_sequences(self):
        """get experiment list from orch"""
        sequences = self.orch.list_sequences()
        for key in self.sequence_lists:
            self.sequence_lists[key] = []

        sequence_count = 0
        for seq in sequences:
            seqdict = seq.as_dict()
            self.sequence_lists["sequence_name"].append(
                seqdict.get("sequence_name", None)
            )
            self.sequence_lists["sequence_label"].append(
                seqdict.get("sequence_label", None)
            )
            self.sequence_lists["sequence_uuid"].append(
                seqdict.get("sequence_uuid", None)
            )
            sequence_count += 1

        # self.sequence_source.stream(self.sequence_lists, rollover=sequence_count)
        self.sequence_source.data = self.sequence_lists
        # self.vis.print_message(
        #     f"current queued sequences: ({len(self.orch.sequence_dq)})"
        # )

    async def get_experiments(self):
        """get experiment list from orch"""
        experiments = self.orch.list_experiments()
        for key in self.experiment_lists:
            self.experiment_lists[key] = []

        experiment_count = 0
        for exp in experiments:
            expdict = exp.as_dict()
            self.experiment_lists["experiment_name"].append(
                expdict.get("experiment_name", None)
            )
            self.experiment_lists["experiment_uuid"].append(
                expdict.get("experiment_uuid", None)
            )
            experiment_count += 1

        # self.experiment_source.stream(self.experiment_lists, rollover=experiment_count)
        self.experiment_source.data = self.experiment_lists
        # self.vis.print_message(
        #     f"current queued experiments: ({len(self.orch.experiment_dq)})"
        # )

    async def get_actions(self):
        """get action list from orch"""
        actions = self.orch.list_actions()
        for key in self.action_lists:
            self.action_lists[key] = []

        action_count = 0
        for act in actions:
            actdict = act.as_dict()
            self.action_lists["action_name"].append(actdict.get("action_name", None))
            self.action_lists["action_server"].append(act.action_server.disp_name())
            self.action_lists["action_uuid"].append(actdict.get("action_uuid", None))
            action_count += 1

        # self.action_source.stream(self.action_lists, rollover=action_count)
        self.action_source.data = self.action_lists
        # LOGGER.info(f"current queued actions: ({len(self.orch.action_dq)})")

    async def get_active_actions(self):
        """get action list from orch"""
        actions = self.orch.list_active_actions()
        for key in self.active_action_lists:
            self.active_action_lists[key] = []
        action_count = 0
        for act in actions:
            actdict = act.as_dict()
            liquid_list, solid_list, gas_list = unpack_samples_helper(
                samples=act.samples_in
            )
            # self.vis.print_message(
            #     f"solids_in: {[s.get_global_label() for s in solid_list]}", sample=True
            # )
            self.active_action_lists["action_name"].append(
                actdict.get("action_name", None)
            )
            self.active_action_lists["action_server"].append(
                act.action_server.disp_name()
            )
            self.active_action_lists["action_uuid"].append(
                actdict.get("action_uuid", None)
            )
            action_count += 1

        # self.active_action_source.stream(self.active_action_lists, rollover=action_count)
        self.active_action_source.data = self.active_action_lists
        # LOGGER.info(f"current active actions: {self.active_action_lists}")

    async def get_orch_status_summary(self):
        for key in self.action_server_lists:
            self.action_server_lists[key] = []

        for server_name, (status_str, driver_str) in self.orch.status_summary.items():
            self.action_server_lists["action_server"].append(server_name)
            self.action_server_lists["server_status"].append(status_str)
            self.action_server_lists["driver_status"].append(driver_str)
            self.action_server_source.stream(self.action_server_lists, rollover=self.num_actserv)

    def update_selector_layout(self, attr, old, new):
        if new == 2:
            self.seqspec_dropdown.value = self.seqspec_select_list[0]
            first_spec = self.seqspec_select_list[0]
            self.callback_seqspec_select("value", first_spec, first_spec)
        if new == 1:
            self.experiment_dropdown.value = self.experiment_select_list[0]
            first_exp = self.experiment_select_list[0]
            self.callback_experiment_select("value", first_exp, first_exp)
        if new == 0:
            self.sequence_dropdown.value = self.sequence_select_list[0]
            first_seq = self.sequence_select_list[0]
            self.callback_sequence_select("value", first_seq, first_seq)

    def callback_sequence_select(self, attr, old, new):
        idx = self.sequence_select_list.index(new)
        self.update_seq_param_layout(idx)
        self.vis.doc.add_next_tick_callback(
            partial(self.update_seq_doc, self.sequences[idx]["doc"])
        )

    def callback_experiment_select(self, attr, old, new):
        idx = self.experiment_select_list.index(new)
        self.update_exp_param_layout(idx)
        self.vis.doc.add_next_tick_callback(
            partial(self.update_exp_doc, self.experiments[idx]["doc"])
        )

    def callback_seqspec_select(self, attr, old, new):
        idx = self.seqspec_select_list.index(new)
        self.update_seqspec_param_layout(idx)
        self.vis.doc.add_next_tick_callback(
            partial(self.update_seqspec_doc, self.seqspecs[idx])
        )

    def callback_enqueue_seqspec(self, event):
        idx = self.seqspec_select_list.index(self.seqspec_dropdown.value)
        specfile = self.seqspecs[idx]
        parser_kwargs = self.config_dict.get("parser_kwargs", {})
        input_params = {
            paraminput.title: parse_bokeh_input(paraminput.value)
            for paraminput in self.seqspec_param_input
        }
        seq = self.seqspec_parser.parser(
            specfile, self.orch, params=input_params, **parser_kwargs
        )
        seq.sequence_label = self.input_sequence_label.value
        if self.input_sequence_comment.value != "":
            seq.sequence_comment = self.input_sequence_comment.value
        self.vis.doc.add_next_tick_callback(partial(self.orch.add_sequence, seq))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_reload_seqspec(self, event):
        if self.seqspec_parser is not None and self.seqspec_folder is not None:
            self.vis.doc.add_next_tick_callback(self.get_seqspec_lib)

    def callback_to_seqtab(self, event):
        idx = self.seqspec_select_list.index(self.seqspec_dropdown.value)
        specfile = self.seqspecs[idx]
        parser_kwargs = self.config_dict.get("parser_kwargs", {})
        seqspec_input_params = {
            paraminput.title: parse_bokeh_input(paraminput.value)
            for paraminput in self.seqspec_param_input
        }
        seq = self.seqspec_parser.parser(
            specfile, self.orch, params=seqspec_input_params, **parser_kwargs
        )
        seqname = seq.sequence_name
        loaded_params = seq.sequence_params
        # switch tabs and update layout
        self.select_tabs.active = 0
        self.callback_sequence_select("value", seqname, seqname)
        self.sequence_dropdown.value = seqname
        # replace defaults with loaded params
        for i, x in enumerate(self.seq_param_input):
            if x.title in loaded_params:
                self.seq_param_input[i].value = str(loaded_params[x.title])

    def callback_clicked_pmplot(self, event, sender):
        """double click/tap on PM plot to add/move marker"""
        LOGGER.info(f"DOUBLE TAP PMplot: {event.x}, {event.y}")
        # get coordinates of doubleclick
        platex = event.x
        platey = event.y
        # transform to nearest sample point
        PMnum = self.get_samples([platex], [platey], sender)
        self.get_sample_infos(PMnum, sender)

    def callback_changed_plateid(self, attr, old, new, sender):
        """callback for plateid text input"""

        def to_int(val):
            try:
                return int(val)
            except ValueError:
                return None

        plateid = to_int(new)
        if plateid is not None:
            self.get_pm(new, sender)
            self.get_elements_plateid(new, sender)

            private_input, param_input = self.find_param_private_input(sender)
            if private_input is None or param_input is None:
                return

            # after selecting a new plate, we reset the sample_no
            input_sample_no = self.find_input(param_input, "solid_sample_no")
            if input_sample_no is not None:
                self.vis.doc.add_next_tick_callback(
                    partial(
                        self.callback_changed_sampleno,
                        attr="value",
                        old=input_sample_no.value,
                        new="1",
                        sender=input_sample_no,
                    )
                )

        else:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_input_value, sender, "")
            )

    def callback_plate_sample_no_list_file(self, attr, old, new, sender, inputfield):
        f = io.BytesIO(b64decode(sender.value))
        sample_nos = json.dumps(np.loadtxt(f).astype(int).tolist())
        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, inputfield, sample_nos)
        )

    def callback_changed_sampleno(self, attr, old, new, sender):
        """callback for sampleno text input"""

        def to_int(val):
            try:
                return int(val)
            except ValueError:
                return None

        sample_no = to_int(new)
        if sample_no is not None:
            self.get_sample_infos([sample_no - 1], sender)
        else:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_input_value, sender, "")
            )

    def callback_estop_orch(self, event):
        LOGGER.info("estop orch")
        self.vis.doc.add_next_tick_callback(partial(self.orch.estop_loop))

    def callback_start_orch(self, event):
        if self.orch.globalstatusmodel.loop_state == LoopStatus.stopped:
            LOGGER.info("starting orch")
            self.vis.doc.add_next_tick_callback(partial(self.orch.start))
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))
        elif self.orch.globalstatusmodel.loop_state == LoopStatus.estopped:
            LOGGER.error("orch is in estop")
        else:
            LOGGER.info("Cannot start orch when not in a stopped state.")

    def callback_add_expplan(self, event):
        """add experiment plan as new sequence to orch sequence_dq"""
        if self.sequence is not None:
            sellabel = self.input_sequence_label.value
            self.sequence.sequence_label = sellabel
            if self.input_sequence_comment.value != "":
                self.sequence.sequence_comment = self.input_sequence_comment.value
            self.vis.doc.add_next_tick_callback(
                partial(self.orch.add_sequence, self.sequence)
            )
            # clear current experiment_plan (sequence in operator)
            self.sequence = None
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_toggle_stepact(self, event):
        self.vis.doc.add_next_tick_callback(
            partial(self.update_stepwise_toggle, self.orch_stepact_button)
        )

    def callback_toggle_stepexp(self, event):
        self.vis.doc.add_next_tick_callback(
            partial(self.update_stepwise_toggle, self.orch_stepexp_button)
        )

    def callback_toggle_stepseq(self, event):
        self.vis.doc.add_next_tick_callback(
            partial(self.update_stepwise_toggle, self.orch_stepseq_button)
        )

    def callback_stop_orch(self, event):
        LOGGER.info("stopping operator orch")
        self.vis.doc.add_next_tick_callback(partial(self.orch.stop))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_skip_exp(self, event):
        LOGGER.info("skipping experiment")
        self.vis.doc.add_next_tick_callback(partial(self.orch.skip))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_clear_expplan(self, event):
        LOGGER.info("clearing exp plan table")
        self.sequence = None
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_clear_sequences(self, event):
        LOGGER.info("clearing experiments")
        self.vis.doc.add_next_tick_callback(partial(self.orch.clear_sequences))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_clear_experiments(self, event):
        LOGGER.info("clearing experiments")
        self.vis.doc.add_next_tick_callback(partial(self.orch.clear_experiments))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_clear_actions(self, event):
        LOGGER.info("clearing actions")
        self.vis.doc.add_next_tick_callback(partial(self.orch.clear_actions))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_prepend_seq(self, event):
        sequence = self.populate_sequence()
        for i, D in enumerate(sequence.experiment_plan_list):
            self.sequence.experiment_plan_list.insert(i, D)
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_append_seq(self, event):
        sequence = self.populate_sequence()
        for D in sequence.experiment_plan_list:
            self.sequence.experiment_plan_list.append(D)
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_prepend_exp(self, event):
        self.prepend_experiment()
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_append_exp(self, event):
        self.append_experiment()
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_update_tables(self, event):
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def append_experiment(self):
        experimentmodel = self.populate_experimentmodel()
        self.sequence.experiment_plan_list.append(experimentmodel)

    def prepend_experiment(self):
        experimentmodel = self.populate_experimentmodel()
        self.sequence.experiment_plan_list.insert(0, experimentmodel)

    def write_params(self, ptype: str, name: str, pars: dict):
        param_file_path = os.path.join(
            self.orch.world_cfg["root"], "STATES", "previous_params.json"
        )
        if not os.path.exists(param_file_path):
            os.makedirs(os.path.dirname(param_file_path), exist_ok=True)
            pdict = {"seq": {}, "exp": {}}
        else:
            with open(param_file_path, "r", encoding="utf8") as f:
                pdict = json.load(f)
        if (ptype == "seq" and self.save_last_seq_pars.active == [0]) or (
            ptype == "exp" and self.save_last_exp_pars.active == [0]
        ):
            pdict[ptype].update({name: pars})
            with open(param_file_path, "w", encoding="utf8") as f:
                json.dump(pdict, f)

    def read_params(self, ptype: str, name: str):
        param_file_path = os.path.join(
            self.orch.world_cfg["root"], "STATES", "previous_params.json"
        )
        if not os.path.exists(param_file_path):
            os.makedirs(os.path.dirname(param_file_path), exist_ok=True)
            pdict = {"seq": {}, "exp": {}}
        else:
            with open(param_file_path, "r", encoding="utf8") as f:
                pdict = json.load(f)
        return pdict.get(ptype, {}).get(name, {})

    def populate_sequence(self):
        selected_sequence = self.sequence_dropdown.value
        LOGGER.info(f"selected sequence from list: {selected_sequence}")

        sequence_params = {
            paraminput.title: parse_bokeh_input(paraminput.value)
            for paraminput in self.seq_param_input
        }
        for k, v in sequence_params.items():
            LOGGER.info(f"added sequence param '{k}' with value {v} and type {type(v)} ")

        self.write_params("seq", selected_sequence, sequence_params)
        expplan_list = self.orch.unpack_sequence(
            sequence_name=selected_sequence, sequence_params=sequence_params
        )

        sequence = Sequence()
        sequence.sequence_name = selected_sequence
        sequence.sequence_label = self.input_sequence_label.value
        sequence.sequence_params = sequence_params
        for expplan in expplan_list:
            sequence.experiment_plan_list.append(expplan)

        if self.sequence is None:
            self.sequence = Sequence()
        self.sequence.sequence_name = sequence.sequence_name
        self.sequence.sequence_label = sequence.sequence_label
        self.sequence.sequence_params = sequence.sequence_params
        self.sequence.sequence_codehash = self.orch.get_sequence_codehash(
            selected_sequence
        )

        return sequence

    def populate_experimentmodel(self) -> Experiment:
        selected_experiment = self.experiment_dropdown.value
        LOGGER.info(f"selected experiment from list: {selected_experiment}")
        experiment_params = {
            paraminput.title: parse_bokeh_input(paraminput.value)
            for paraminput in self.exp_param_input
        }
        for k, v in experiment_params.items():
            LOGGER.info(f"added experiment param '{k}' with value {v} and type {type(v)} ")
        self.write_params("exp", selected_experiment, experiment_params)
        experimentmodel = Experiment(
            experiment_name=selected_experiment, experiment_params=experiment_params
        )
        if self.sequence is None:
            self.sequence = Sequence()
        self.sequence.sequence_name = "manual_orch_seq"
        self.sequence.sequence_label = self.input_sequence_label.value
        return experimentmodel

    def refresh_inputs(self, param_input, private_input):
        input_plate_id = self.find_input(param_input, "solid_plate_id")
        input_sample_no = self.find_input(param_input, "solid_sample_no")
        if input_plate_id is not None:
            self.vis.doc.add_next_tick_callback(
                partial(
                    self.callback_changed_plateid,
                    attr="value",
                    old=input_plate_id.value,
                    new=input_plate_id.value,
                    sender=input_plate_id,
                )
            )
        if input_sample_no is not None:
            self.vis.doc.add_next_tick_callback(
                partial(
                    self.callback_changed_sampleno,
                    attr="value",
                    old=input_sample_no.value,
                    new=input_sample_no.value,
                    sender=input_sample_no,
                )
            )

    def update_input_value(self, sender, value):
        sender.value = value

    def flip_stepwise_flag(self, sender_type):
        if sender_type == "actions":
            self.orch.step_thru_actions = not self.orch.step_thru_actions
        elif sender_type == "experiments":
            self.orch.step_thru_experiments = not self.orch.step_thru_experiments
        elif sender_type == "sequences":
            self.orch.step_thru_sequences = not self.orch.step_thru_sequences

    def update_stepwise_toggle(self, sender):
        sender_type = sender.label.split("[")[0].strip().split()[-1].strip()
        sender_map = {
            "actions": (self.orch_stepact_button, len(self.orch.action_dq)),
            "experiments": (self.orch_stepexp_button, len(self.orch.experiment_dq)),
            "sequences": (self.orch_stepseq_button, len(self.orch.sequence_dq)),
        }
        sbutton, numq = sender_map[sender_type]
        self.flip_stepwise_flag(sender_type)
        if sbutton.button_type == "danger":
            sbutton.label = f"RUN-THRU {sender_type} [{numq}]"
            sbutton.button_type = "success"
        else:
            sbutton.label = f"STEP-THRU {sender_type} [{numq}]"
            sbutton.button_type = "danger"

    def update_queuecount_labels(self):
        stepwisebuttons = [
            (self.orch_stepseq_button, len(self.orch.sequence_dq)),
            (self.orch_stepexp_button, len(self.orch.experiment_dq)),
            (self.orch_stepact_button, len(self.orch.action_dq)),
        ]
        for sbutton, numq in stepwisebuttons:
            sbutton.label = sbutton.label.split("[")[0].strip() + f" [{numq}]"

    def update_seq_param_layout(self, idx):
        args = self.sequences[idx]["args"]
        defaults = self.sequences[idx]["defaults"]
        argtypes = self.sequences[idx]["argtypes"]
        self.dynamic_col.children.pop(4)

        for _ in range(len(args) - len(defaults)):
            defaults.insert(0, "")

        self.seq_param_input = []
        self.seq_private_input = []
        self.seq_param_layout = [
            Spacer(height=10),
            layout(
                [
                    [
                        Div(
                            text="<b>Optional sequence parameters:</b>",
                            width=200 + 50,
                            height=15,
                            style={"font-size": "100%", "color": "black"},
                        ),
                    ],
                ],
                background=self.color_sq_param_inputs,
                width=self.max_width,
                height_policy="min",
            ),
        ]

        self.add_dynamic_inputs(
            self.seq_param_input,
            self.seq_private_input,
            self.seq_param_layout,
            args,
            defaults,
            argtypes,
        )

        if not self.seq_param_input:
            self.seq_param_layout.append(
                layout(
                    [
                        [
                            Spacer(width=10),
                            Div(
                                text="-- none --",
                                width=200 + 50,
                                height=15,
                                style={"font-size": "100%", "color": "black"},
                            ),
                        ],
                    ],
                    background=self.color_sq_param_inputs,
                    width=self.max_width,
                ),
            )

        self.dynamic_col.children.insert(
            4, layout(self.seq_param_layout, height_policy="min")
        )

        self.refresh_inputs(self.seq_param_input, self.seq_private_input)

    def update_exp_param_layout(self, idx):
        args = self.experiments[idx]["args"]
        defaults = self.experiments[idx]["defaults"]
        argtypes = self.experiments[idx]["argtypes"]
        self.dynamic_col.children.pop(4)

        for _ in range(len(args) - len(defaults)):
            defaults.insert(0, "")

        self.exp_param_input = []
        self.exp_private_input = []
        self.exp_param_layout = [
            Spacer(height=10),
            layout(
                [
                    [
                        Div(
                            text="<b>Optional experiment parameters:</b>",
                            width=200 + 50,
                            height=15,
                            style={"font-size": "100%", "color": "black"},
                        ),
                    ],
                ],
                background=self.color_sq_param_inputs,
                width=self.max_width,
                height_policy="min",
            ),
        ]
        self.add_dynamic_inputs(
            self.exp_param_input,
            self.exp_private_input,
            self.exp_param_layout,
            args,
            defaults,
            argtypes,
        )

        if not self.exp_param_input:
            self.exp_param_layout.append(
                layout(
                    [
                        [
                            Spacer(width=10),
                            Div(
                                text="-- none --",
                                width=200 + 50,
                                height=15,
                                style={"font-size": "100%", "color": "black"},
                            ),
                        ],
                    ],
                    background=self.color_sq_param_inputs,
                    width=self.max_width,
                    height_policy="min",
                ),
            )

        self.dynamic_col.children.insert(
            4, layout(self.exp_param_layout, height_policy="min")
        )

        self.refresh_inputs(self.exp_param_input, self.exp_private_input)

    def update_seqspec_param_layout(self, idx):
        args = []
        argtypes = []
        defaults = []

        seqspec_path = self.seqspecs[idx]
        seqfunc_params = self.seqspec_parser.list_params(seqspec_path, self.orch)

        for arg, argtype in self.seqspec_parser.PARAM_TYPES.items():
            if arg in seqfunc_params:
                args.append(arg)
                argtypes.append(argtype)

        self.dynamic_col.children.pop(4)

        for _ in range(len(args) - len(defaults)):
            defaults.insert(0, "")

        self.seqspec_param_input = []
        self.seqspec_private_input = []
        self.seqspec_param_layout = [
            Spacer(height=10),
            layout(
                [
                    [
                        Div(
                            text="<b>Required sequence parameters:</b>",
                            width=200 + 50,
                            height=15,
                            style={"font-size": "100%", "color": "black"},
                        ),
                    ],
                ],
                background=self.color_sq_param_inputs,
                width=self.max_width,
                height_policy="min",
            ),
        ]

        self.add_dynamic_inputs(
            self.seqspec_param_input,
            self.seqspec_private_input,
            self.seqspec_param_layout,
            args,
            defaults,
            argtypes,
        )

        if not self.seqspec_param_input:
            self.seqspec_param_layout.append(
                layout(
                    [
                        [
                            Spacer(width=10),
                            Div(
                                text="-- none --",
                                width=200 + 50,
                                height=15,
                                style={"font-size": "100%", "color": "black"},
                            ),
                        ],
                    ],
                    background=self.color_sq_param_inputs,
                    width=self.max_width,
                    height_policy="min",
                ),
            )

        self.dynamic_col.children.insert(
            4, layout(self.seqspec_param_layout, height_policy="min")
        )

    def add_dynamic_inputs(
        self, param_input, private_input, param_layout, args, defaults, argtypes
    ):
        item = 0
        for idx in range(len(args)):
            def_val = f"{defaults[idx]}"
            # if args[idx] == "experiment":
            #     continue
            # disabled = False

            param_input.append(
                TextInput(
                    value=def_val,
                    title=args[idx],
                    disabled=True if args[idx].endswith("_version") else False,
                    width=400,
                    height=40,
                )
            )
            param_layout.append(
                layout(
                    [
                        [
                            param_input[item],
                            Paragraph(
                                text=str(argtypes[idx])
                                .split()[-1]
                                .strip("'<>]")
                                .split(".")[-1]
                                .replace("[", " of "),
                                align=("start", "end"),
                            ),
                        ],
                        Spacer(height=10),
                    ],
                    background=self.color_sq_param_inputs,
                    width=self.max_width,
                )
            )
            item = item + 1

            # special key params
            if args[idx] == "solid_plate_id":
                param_input[-1].on_change(
                    "value",
                    partial(self.callback_changed_plateid, sender=param_input[-1]),
                )
                private_input.append(
                    figure(
                        title="PlateMap",
                        # height=300,
                        x_axis_label="X (mm)",
                        y_axis_label="Y (mm)",
                        width=self.max_width,
                        aspect_ratio=6 / 4,
                        aspect_scale=1,
                    )
                )
                private_input[-1].border_fill_color = self.color_sq_param_inputs
                private_input[-1].border_fill_alpha = 0.5
                private_input[-1].background_fill_color = self.color_sq_param_inputs
                private_input[-1].background_fill_alpha = 0.5
                private_input[-1].on_event(
                    DoubleTap,
                    partial(self.callback_clicked_pmplot, sender=param_input[-1]),
                )
                self.update_pm_plot(private_input[-1], [])
                param_layout.append(
                    layout(
                        [
                            [private_input[-1]],
                            Spacer(height=10),
                        ],
                        background=self.color_sq_param_inputs,
                        width=self.max_width,
                    )
                )

                private_input.append(
                    TextInput(
                        value="", title="elements", disabled=True, width=120, height=40
                    )
                )
                private_input.append(
                    TextInput(
                        value="", title="code", disabled=True, width=60, height=40
                    )
                )
                private_input.append(
                    TextInput(
                        value="",
                        title="composition",
                        disabled=True,
                        width=220,
                        height=40,
                    )
                )
                param_layout.append(
                    layout(
                        [
                            [private_input[-3], private_input[-2], private_input[-1]],
                            Spacer(height=10),
                        ],
                        background=self.color_sq_param_inputs,
                        width=self.max_width,
                    )
                )

            elif args[idx] == "solid_sample_no":
                param_input[-1].on_change(
                    "value",
                    partial(self.callback_changed_sampleno, sender=param_input[-1]),
                )

            elif args[idx] == "x_mm":
                param_input[-1].disabled = True

            elif args[idx] == "y_mm":
                param_input[-1].disabled = True

            elif args[idx] == "solid_custom_position":
                param_input[-1] = Select(
                    title=args[idx], value=None, options=self.dev_customitems
                )
                if self.dev_customitems:
                    if def_val in self.dev_customitems:
                        param_input[-1].value = def_val
                    else:
                        param_input[-1].value = self.dev_customitems[0]
                param_layout[-1] = layout(
                    [
                        [param_input[-1]],
                        Spacer(height=10),
                    ],
                    background=self.color_sq_param_inputs,
                    width=self.max_width,
                )

            elif args[idx] == "liquid_custom_position":
                param_input[-1] = Select(
                    title=args[idx], value=None, options=self.dev_customitems
                )
                if self.dev_customitems:
                    if def_val in self.dev_customitems:
                        param_input[-1].value = def_val
                    else:
                        param_input[-1].value = self.dev_customitems[0]
                param_layout[-1] = layout(
                    [
                        [param_input[-1]],
                        Spacer(height=10),
                    ],
                    background=self.color_sq_param_inputs,
                    width=self.max_width,
                )

            elif args[idx] == "plate_sample_no_list":
                private_input.append(FileInput(width=200, accept=".txt"))
                param_layout.append(
                    layout(
                        [
                            [private_input[-1]],
                            Spacer(height=10),
                        ],
                        background=self.color_sq_param_inputs,
                        width=self.max_width,
                    )
                )
                private_input[-1].on_change(
                    "value",
                    partial(
                        self.callback_plate_sample_no_list_file,
                        sender=private_input[-1],
                        inputfield=param_input[-1],
                    ),
                )

    def update_seq_doc(self, value):
        self.sequence_descr_txt.text = value.replace("\n", "<br>")

    def update_exp_doc(self, value):
        self.experiment_descr_txt.text = value.replace("\n", "<br>")

    def update_seqspec_doc(self, value):
        fp = value.replace("\n", "<br>")
        self.seqspec_descr_txt.text = f"Enqueue a sequence using parser:<br>{self.parser_path}<br><br>on specification file:<br>{fp}"

    def update_error(self, value):
        self.error_txt.text = value

    def update_xysamples(self, xval, yval, sender):
        private_input, param_input = self.find_param_private_input(sender)
        if private_input is None or param_input is None:
            return False

        for paraminput in param_input:
            if paraminput.title == "x_mm":
                paraminput.value = xval
            if paraminput.title == "y_mm":
                paraminput.value = yval

    def update_pm_plot(self, plot_mpmap, pmdata):
        """plots the plate map"""
        x = [col["x"] for col in pmdata]
        y = [col["y"] for col in pmdata]
        # remove old Pmplot
        old_point = plot_mpmap.select(name="PMplot")
        if len(old_point) > 0:
            plot_mpmap.renderers.remove(old_point[0])
        plot_mpmap.square(
            x, y, size=5, color=None, alpha=0.5, line_color="black", name="PMplot"
        )

    def get_pm(self, plateid, sender):
        """gets plate map"""
        private_input, param_input = self.find_param_private_input(sender)
        if private_input is None or param_input is None:
            return False

        # pmdata = json.loads(self.dataAPI.get_platemap_plateid(plateid))
        pmdata = self.dataAPI.get_platemap_plateid(plateid)
        if len(pmdata) == 0:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_error, "no pm found")
            )

        plot_mpmap = self.find_plot(private_input, "PlateMap")
        if plot_mpmap is not None:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_pm_plot, plot_mpmap, pmdata)
            )

    def xy_to_sample(self, xy, pmapxy):
        """get point from pmap closest to xy"""
        if len(pmapxy):
            diff = pmapxy - xy
            sumdiff = (diff**2).sum(axis=1)
            return int(np.argmin(sumdiff))
        else:
            return None

    def get_samples(self, X, Y, sender):
        """get list of samples row number closest to xy"""
        # X and Y are vectors

        private_input, param_input = self.find_param_private_input(sender)
        if private_input is None or param_input is None:
            return False

        input_plate_id = self.find_input(param_input, "solid_plate_id")

        if input_plate_id is not None:
            # pmdata = json.loads(self.dataAPI.get_platemap_plateid(input_plate_id.value))
            pmdata = self.dataAPI.get_platemap_plateid(input_plate_id.value)

            xyarr = np.array((X, Y)).T
            pmxy = np.array([[col["x"], col["y"]] for col in pmdata])
            samples = list(np.apply_along_axis(self.xy_to_sample, 1, xyarr, pmxy))
            return samples
        else:
            return [None]

    def get_elements_plateid(self, plateid: int, sender):
        """gets plate elements from aligner server"""

        private_input, param_input = self.find_param_private_input(sender)
        if private_input is None or param_input is None:
            return False

        input_elements = self.find_input(private_input, "elements")

        if input_elements is not None:
            elements = self.dataAPI.get_elements_plateid(
                plateid,
                multielementink_concentrationinfo_bool=False,
                print_key_or_keyword="screening_print_id",
                exclude_elements_list=[""],
                return_defaults_if_none=False,
            )
            if elements is not None:
                self.vis.doc.add_next_tick_callback(
                    partial(self.update_input_value, input_elements, ",".join(elements))
                )

    def find_plot(self, inputs, name):
        for inp in inputs:
            if isinstance(inp, Figure):
                if inp.title.text == name:
                    return inp
        return None

    def find_input(self, inputs, name):
        for inp in inputs:
            if isinstance(inp, TextInput):
                if inp.title == name:
                    return inp
        return None

    def find_param_private_input(self, sender):
        private_input = None
        param_input = None

        if sender in self.exp_param_input or sender in self.exp_private_input:
            private_input = self.exp_private_input
            param_input = self.exp_param_input

        elif sender in self.seq_param_input or sender in self.seq_private_input:
            private_input = self.seq_private_input
            param_input = self.seq_param_input

        return private_input, param_input

    def get_sample_infos(self, PMnum: Optional[List] = None, sender=None):
        LOGGER.info("updating samples")

        private_input, param_input = self.find_param_private_input(sender)
        if private_input is None or param_input is None:
            return False

        plot_mpmap = self.find_plot(private_input, "PlateMap")
        input_plate_id = self.find_input(param_input, "solid_plate_id")
        input_sample_no = self.find_input(param_input, "solid_sample_no")
        input_code = self.find_input(private_input, "code")
        input_composition = self.find_input(private_input, "composition")
        if (
            plot_mpmap is not None
            and input_plate_id is not None
            and input_sample_no is not None
        ):
            # pmdata = json.loads(self.dataAPI.get_platemap_plateid(input_plate_id.value))
            pmdata = self.dataAPI.get_platemap_plateid(input_plate_id.value)
            buf = ""
            if PMnum is not None and pmdata:
                if PMnum[0] is not None:  # need to check as this can also happen
                    LOGGER.info(f"selected sample_no: {PMnum[0]+1}")
                    if PMnum[0] > len(pmdata) or PMnum[0] < 0:
                        LOGGER.info("invalid sample no")
                        self.vis.doc.add_next_tick_callback(
                            partial(self.update_input_value, input_sample_no, "")
                        )
                        return False

                    platex = pmdata[PMnum[0]]["x"]
                    platey = pmdata[PMnum[0]]["y"]
                    code = pmdata[PMnum[0]]["code"]

                    buf = ""
                    for fraclet in ("A", "B", "C", "D", "E", "F", "G", "H"):
                        buf = "%s%s_%s " % (buf, fraclet, pmdata[PMnum[0]][fraclet])
                    if len(buf) == 0:
                        buf = "-"
                    if input_sample_no != str(PMnum[0] + 1):
                        self.vis.doc.add_next_tick_callback(
                            partial(
                                self.update_input_value,
                                input_sample_no,
                                str(PMnum[0] + 1),
                            )
                        )
                    self.vis.doc.add_next_tick_callback(
                        partial(self.update_xysamples, str(platex), str(platey), sender)
                    )
                    if input_composition is not None:
                        self.vis.doc.add_next_tick_callback(
                            partial(self.update_input_value, input_composition, buf)
                        )
                    if input_code is not None:
                        self.vis.doc.add_next_tick_callback(
                            partial(self.update_input_value, input_code, str(code))
                        )

                    # remove old Marker point
                    old_point = plot_mpmap.select(name="selsample")
                    if len(old_point) > 0:
                        plot_mpmap.renderers.remove(old_point[0])
                    # plot new Marker point
                    plot_mpmap.square(
                        platex,
                        platey,
                        size=7,
                        line_width=2,
                        color=None,
                        alpha=1.0,
                        line_color=(255, 0, 0),
                        name="selsample",
                    )

                    return True
            else:
                return False

        return False

    async def add_experiment_to_sequence(self):
        pass

    async def update_tables(self):
        await self.get_sequences()
        await self.get_experiments()
        await self.get_actions()
        await self.get_active_actions()
        await self.get_orch_status_summary()
        self.update_queuecount_labels()
        for key in self.experiment_plan_lists:
            self.experiment_plan_lists[key] = []
        
        plan_count = 0
        if self.sequence is not None:
            for D in self.sequence.experiment_plan_list:
                self.experiment_plan_lists["sequence_name"].append(
                    self.sequence.sequence_name
                )
                self.experiment_plan_lists["sequence_label"].append(
                    self.sequence.sequence_label
                )
                self.experiment_plan_lists["experiment_name"].append(D.experiment_name)
                plan_count += 1

        # self.experiment_plan_source.stream(self.experiment_plan_lists, rollover=plan_count)
        self.experiment_plan_source.data = self.experiment_plan_lists

        if self.orch.globalstatusmodel.loop_state == LoopStatus.started:
            self.orch_status_button.label = "running"
            self.orch_status_button.button_type = "success"
        elif self.orch.globalstatusmodel.loop_state == LoopStatus.stopped:
            stop_msg = (
                ": " + self.orch.current_stop_message
                if self.orch.current_stop_message != ""
                else ""
            )
            self.orch_status_button.label = f"stopped{stop_msg}"
            if stop_msg:
                self.orch_status_button.button_type = "warning"
            else:
                self.orch_status_button.button_type = "primary"
        else:
            self.orch_status_button.label = (
                f"{self.orch.globalstatusmodel.loop_state.value}"
            )
            self.orch_status_button.button_type = "danger"

    async def IOloop(self):
        self.IOloop_run = True
        while self.IOloop_run:
            try:
                _ = await self.update_q.get()
                self.vis.doc.add_next_tick_callback(partial(self.update_tables))
            except Exception as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                LOGGER.error(f"BokehOperator IOloop error: {repr(e), tb,}")

    def get_last_seq_pars(self):
        loaded_pars = self.read_params("seq", self.sequence_dropdown.value)
        for k, v in loaded_pars.items():
            seq_input = self.find_input(self.seq_param_input, k)
            self.vis.doc.add_next_tick_callback(
                partial(self.update_input_value, seq_input, str(v))
            )

    def get_last_exp_pars(self):
        loaded_pars = self.read_params("exp", self.experiment_dropdown.value)
        for k, v in loaded_pars.items():
            exp_input = self.find_input(self.exp_param_input, k)
            self.vis.doc.add_next_tick_callback(
                partial(self.update_input_value, exp_input, str(v))
            )

    def callback_copy_sequence_label(self, attr, old, new):
        self.vis.doc.add_next_tick_callback(
            partial(
                self.update_input_value,
                self.input_sequence_label2,
                self.input_sequence_label.value,
            )
        )

    def callback_copy_sequence_label2(self, attr, old, new):
        self.vis.doc.add_next_tick_callback(
            partial(
                self.update_input_value,
                self.input_sequence_label,
                self.input_sequence_label2.value,
            )
        )

    def callback_copy_sequence_comment(self, attr, old, new):
        self.vis.doc.add_next_tick_callback(
            partial(
                self.update_input_value,
                self.input_sequence_comment2,
                self.input_sequence_comment.value,
            )
        )

    def callback_copy_sequence_comment2(self, attr, old, new):
        self.vis.doc.add_next_tick_callback(
            partial(
                self.update_input_value,
                self.input_sequence_comment,
                self.input_sequence_comment2.value,
            )
        )
