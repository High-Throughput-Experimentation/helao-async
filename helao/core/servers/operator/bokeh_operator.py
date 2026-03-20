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

import time
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
import builtins

from helao.helpers import helao_logging as logging

from helao.helpers.to_json import parse_bokeh_input
from helao.helpers.unpack_samples import unpack_samples_helper
from helao.helpers.gen_uuid import md5_string
from helao.core.servers.vis import Vis
from helao.helpers.plate_api import HTEPlateAPI

from helao.core.models.orchstatus import LoopStatus
from helao.helpers.premodels import Sequence, Experiment

from bokeh.layouts import column
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource
from bokeh.models import DataTable, TableColumn
from bokeh.models import Select
from bokeh.models import Button
from bokeh.models import CheckboxGroup
from bokeh.models import TabPanel, Tabs
from bokeh.models import CustomJS
from bokeh.models.widgets import Div
from bokeh.models.widgets.inputs import TextInput, TextAreaInput
from bokeh.plotting import figure
from bokeh.events import ButtonClick, DoubleTap
from bokeh.models.widgets import FileInput

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

BUILTIN_TYPES = [
    getattr(builtins, d)
    for d in dir(builtins)
    if isinstance(getattr(builtins, d), type)
]


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
    sequence: Sequence

    def __init__(self, vis_serv: Vis, orch):
        self.vis = vis_serv
        self.orch = orch
        self.dataAPI = HTEPlateAPI()

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
        self.seq_param_input_types = []
        self.seq_private_input = []
        self.exp_param_layout = []
        self.exp_param_input = []
        self.exp_param_input_types = []
        self.exp_private_input = []

        self.seqspec_param_layout = []
        self.seqspec_param_input = []
        self.seqspec_param_input_types = []
        self.seqspec_private_input = []

        self.sequence = None
        self.experiment_plan_lists = {
            k: [] for k in ["sequence_name", "sequence_label", "experiment_name"]
        }

        self.sequence_lists = {
            k: []
            for k in [
                "sequence_name",
                "sequence_label",
                "sequence_uuid",
                "campaign_name",
                "campaign_uuid",
            ]
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

        self.experiment_plan_source, self.experiment_plan_table = self._make_table(
            self.experiment_plan_lists
        )
        self.sequence_source, self.sequence_table = self._make_table(
            self.sequence_lists
        )
        self.experiment_source, self.experiment_table = self._make_table(
            self.experiment_lists
        )
        self.action_source, self.action_table = self._make_table(self.action_lists)
        self.action_server_source, self.action_server_table = self._make_table(
            self.action_server_lists
        )

        self.sequence_tab = TabPanel(child=self.sequence_table, title="Sequences")
        self.experiment_tab = TabPanel(child=self.experiment_table, title="Experiments")
        self.action_tab = TabPanel(child=self.action_table, title="Actions")
        self.action_server_tab = TabPanel(
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

        self.active_action_source, self.active_action_table = self._make_table(
            self.active_action_lists, fit_columns=False
        )

        self.planner_tab = TabPanel(
            child=self.experiment_plan_table,
            title="Planned Experiments",
        )
        self.active_tab = TabPanel(
            child=self.active_action_table,
            title="Active Actions",
        )
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
        self.button_start_orch = self._make_button(
            "Start Orch", "default", 70, self.callback_start_orch
        )
        self.button_estop_orch = self._make_button(
            "ESTOP", "danger", 400, self.callback_estop_orch, height=100
        )
        self.button_add_expplan = self._make_button(
            "Add plan", "default", 100, self.callback_add_expplan
        )
        self.button_add_smpseqs = self._make_button(
            "Split plan", "default", 100, self.callback_add_split_sequences
        )
        self.button_stop_orch = self._make_button(
            "Stop Orch", "default", 70, self.callback_stop_orch
        )
        self.button_skip_exp = self._make_button(
            "Skip exp", "danger", 70, self.callback_skip_exp
        )
        self.button_update = self._make_button(
            "Update tables", "default", 120, self.callback_update_tables
        )
        self.button_clear_expplan = self._make_button(
            "Clear expplan", "default", 100, self.callback_clear_expplan
        )
        self.orch_status_button = Button(
            label="Disabled", disabled=False, button_type="danger", width=470
        )  # success: green, danger: red

        self.orch_stepact_button = self._make_stepwise_button(
            "step_thru_actions", "actions", self.callback_toggle_stepact
        )
        self.orch_stepexp_button = self._make_stepwise_button(
            "step_thru_experiments", "experiments", self.callback_toggle_stepexp
        )
        # note: intentionally uses step_thru_experiments to match original behaviour
        self.orch_stepseq_button = self._make_stepwise_button(
            "step_thru_experiments", "sequences", self.callback_toggle_stepseq
        )

        self.button_clear_seqs = self._make_button(
            "Clear seqs", "danger", 100, self.callback_clear_sequences
        )
        self.button_clear_exps = self._make_button(
            "Clear exp", "danger", 100, self.callback_clear_experiments
        )
        self.button_clear_action = self._make_button(
            "Clear act", "danger", 100, self.callback_clear_actions
        )

        self.button_prepend_exp = self._make_button(
            "Prepend exp to exp plan", "default", 150, self.callback_prepend_exp
        )
        self.button_append_exp = self._make_button(
            "Append exp to exp plan", "default", 150, self.callback_append_exp
        )
        self.button_prepend_seq = self._make_button(
            "Prepend seq to exp plan", "default", 150, self.callback_prepend_seq
        )
        self.button_append_seq = self._make_button(
            "Append seq to exp plan", "default", 150, self.callback_append_seq
        )

        self.button_last_seq_pars = self._make_button(
            "Load last seq params", "default", 150, self.get_last_seq_pars
        )
        self.button_last_exp_pars = self._make_button(
            "Load last exp params", "default", 150, self.get_last_exp_pars
        )

        self.save_last_exp_pars = CheckboxGroup(labels=["save exp params"], active=[0])
        self.save_last_seq_pars = CheckboxGroup(labels=["save seq params"], active=[0])

        self.button_enqueue_seqspec = self._make_button(
            "Enqueue specs sequence", "default", 150, self.callback_enqueue_seqspec
        )
        self.button_reload_seqspec = self._make_button(
            "Reload specs folder", "default", 150, self.callback_reload_seqspec
        )
        self.button_to_seqtab = self._make_button(
            "To sequence selection", "default", 150, self.callback_to_seqtab
        )

        self.sequence_descr_txt = Div(
            text="""select a sequence item""", width=600, height_policy="min"
        )
        self.experiment_descr_txt = Div(
            text="""select a experiment item""", width=600, height_policy="min"
        )
        self.seqspec_descr_txt = Div(
            text="""select a sequence specification""", width=600, height_policy="min"
        )

        self.error_txt = Div(
            text="""no error""",
            width=600,
            height=30,
            styles={"font-size": "100%", "color": "black"},
        )

        self.input_sequence_label = TextInput(
            value="nolabel",
            title="sequence label",
            disabled=False,
            width=150,
            height=40,
        )
        self.input_sequence_label2 = TextInput(
            value="nolabel",
            title="sequence label",
            disabled=False,
            width=150,
            height=40,
        )
        self.input_campaign_name = TextInput(
            value="",
            title="campaign name",
            disabled=False,
            width=150,
            height=40,
        )
        self.input_campaign_name2 = TextInput(
            value="",
            title="campaign name",
            disabled=False,
            width=150,
            height=40,
        )
        self.input_campaign_uuid = TextInput(
            value="",
            title="campaign uuid",
            disabled=False,
            width=150,
            height=40,
        )
        self.input_campaign_uuid2 = TextInput(
            value="",
            title="campaign uuid",
            disabled=False,
            width=150,
            height=40,
        )
        self.input_sequence_comment = TextAreaInput(
            value="",
            title="sequence comment",
            disabled=False,
            width=470,
            height=90,
            rows=3,
        )
        self.input_sequence_comment2 = TextAreaInput(
            value="",
            title="sequence comment",
            disabled=False,
            width=470,
            height=90,
            rows=3,
        )

        # Wire mirrored inputs — each member of a pair keeps the other in sync.
        self.input_sequence_label.on_change(
            "value",
            self._make_copy_callback("input_sequence_label", "input_sequence_label2"),
        )
        self.input_sequence_label2.on_change(
            "value",
            self._make_copy_callback("input_sequence_label2", "input_sequence_label"),
        )
        self.input_campaign_name.on_change(
            "value",
            self._make_copy_callback("input_campaign_name", "input_campaign_name2"),
        )
        self.input_campaign_name2.on_change(
            "value",
            self._make_copy_callback("input_campaign_name2", "input_campaign_name"),
        )
        self.input_campaign_uuid.on_change(
            "value",
            self._make_copy_callback("input_campaign_uuid", "input_campaign_uuid2"),
        )
        self.input_campaign_uuid2.on_change(
            "value",
            self._make_copy_callback("input_campaign_uuid2", "input_campaign_uuid"),
        )
        self.input_sequence_comment.on_change(
            "value",
            self._make_copy_callback(
                "input_sequence_comment", "input_sequence_comment2"
            ),
        )
        self.input_sequence_comment2.on_change(
            "value",
            self._make_copy_callback(
                "input_sequence_comment2", "input_sequence_comment"
            ),
        )

        self.orch_section = Div(
            text="<b>Orchestrator</b>",
            width=self.max_width - 20,
            height=32,
            styles={"font-size": "150%", "color": "#CB4335"},
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
                            styles={"font-size": "200%", "color": "#CB4335"},
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
                            Spacer(width=20),
                            self.input_campaign_name,
                            Spacer(width=20),
                            self.input_campaign_uuid,
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
                            Spacer(width=20),
                            self.input_campaign_name2,
                            Spacer(width=20),
                            self.input_campaign_uuid2,
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
                            self.button_add_smpseqs,
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
                                styles={"font-size": "100%", "color": "black"},
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
                            self.button_add_smpseqs,
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

        self.sequence_select_tab = TabPanel(
            child=self.layout1, title="Sequence Selection"
        )
        self.experiment_select_tab = TabPanel(
            child=self.layout2, title="Experiment Selection"
        )
        self.seqspec_select_tab = TabPanel(
            child=self.layout3, title="Specification Files"
        )
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

    # ------------------------------------------------------------------
    # Private helpers — used to reduce repetition in __init__ and below
    # ------------------------------------------------------------------

    def _make_table(self, data_dict: dict, **extra_kwargs) -> tuple:
        """Create a (ColumnDataSource, DataTable) pair from a dict of lists."""
        source = ColumnDataSource(data=data_dict)
        columns = [TableColumn(field=k, title=k) for k in data_dict]
        table = DataTable(
            source=source,
            columns=columns,
            width=self.max_width - 20,
            height=200,
            autosize_mode="force_fit",
            **extra_kwargs,
        )
        return source, table

    def _make_button(
        self, label: str, btn_type: str, width: int, callback, **kwargs
    ) -> Button:
        """Create a Button and register a ButtonClick event handler in one call."""
        btn = Button(label=label, button_type=btn_type, width=width, **kwargs)
        btn.on_event(ButtonClick, callback)
        return btn

    def _make_stepwise_button(self, flag_attr: str, kind: str, callback) -> Button:
        """Create a STEP-THRU / RUN-THRU toggle button from an orch flag attribute."""
        is_step = getattr(self.orch, flag_attr)
        label = f"{'STEP' if is_step else 'RUN'}-THRU {kind}"
        btn = Button(
            label=label, button_type="danger" if is_step else "success", width=170
        )
        btn.on_event(ButtonClick, callback)
        return btn

    def _make_copy_callback(self, source_attr: str, target_attr: str):
        """Return an on_change callback that mirrors source to target via update_q."""

        def _cb(attr, old, new):
            self.vis.doc.add_next_tick_callback(
                partial(
                    self.update_input_value,
                    getattr(self, target_attr),
                    getattr(self, source_attr).value,
                )
            )

        return _cb

    def _build_lib(
        self, lib: dict, filter_type, config_key: str, model_class, name_field: str
    ):
        """Shared logic for get_sequence_lib / get_experiment_lib.

        Returns (items, select_list) where items is a list of model dicts and
        select_list is the ordered list of names for the dropdown.
        """
        items = []
        select_list = []
        LOGGER.info(f"found {name_field.replace('_name', '')}s: {list(lib)}")
        for i, name in enumerate(lib):
            func = lib[name]
            tmpdoc = func.__doc__ or ""
            argspec = inspect.getfullargspec(func)
            tmpargs = list(argspec.args)
            tmpdefs = list(argspec.defaults or [])
            tmptypes = [argspec.annotations.get(k, "unspecified") for k in tmpargs]

            if filter_type is not None:
                idxlist = [
                    idx
                    for idx, arg in enumerate(tmpargs)
                    if argspec.annotations.get(arg) == filter_type
                ]
                for j, idx in enumerate(idxlist):
                    if len(tmpargs) == len(tmpdefs):
                        tmpargs.pop(idx - j)
                        tmpdefs.pop(idx - j)
                        tmptypes.pop(idx - j)
                    else:
                        tmpargs.pop(idx - j)
                        tmptypes.pop(idx - j)

            cfg_defs = self.orch.world_cfg.get(config_key, {})
            tmpdefs = [cfg_defs.get(ta, td) for ta, td in zip(tmpargs, tmpdefs)]
            for t in tmpdefs:
                try:
                    t = json.dumps(t)
                except Exception:
                    t = ""
            items.append(
                model_class(
                    index=i,
                    **{name_field: name},
                    doc=tmpdoc,
                    args=tuple(tmpargs),
                    defaults=tuple(tmpdefs),
                    argtypes=tuple(tmptypes),
                ).model_dump()
            )
            select_list.append(name)
        return items, select_list

    def _apply_sequence_to_orch(self, orch_method):
        """Shared body for callback_add_expplan / callback_add_split_sequences."""
        if self.sequence is None:
            return
        self.sequence.sequence_label = self.input_sequence_label.value
        if self.input_sequence_comment.value != "":
            self.sequence.sequence_comment = self.input_sequence_comment.value
        campaign_name = self.input_campaign_name.value
        if campaign_name != "":
            self.sequence.campaign_name = campaign_name
            if self.input_campaign_uuid.value.strip() == "":
                self.sequence.campaign_uuid = md5_string(campaign_name)
            else:
                self.sequence.campaign_uuid = self.input_campaign_uuid.value.strip()
        self.vis.doc.add_next_tick_callback(partial(orch_method, self.sequence))
        self.sequence = None
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def _update_param_layout(
        self, mode: str, idx: int, args=None, defaults=None, argtypes=None
    ):
        """Shared body for update_seq/exp/seqspec_param_layout."""
        _cfg = {
            "seq": {
                "items_attr": "sequences",
                "input_attr": "seq_param_input",
                "types_attr": "seq_param_input_types",
                "private_attr": "seq_private_input",
                "layout_attr": "seq_param_layout",
                "header": "<b>Optional sequence parameters:</b>",
                "refresh": True,
            },
            "exp": {
                "items_attr": "experiments",
                "input_attr": "exp_param_input",
                "types_attr": "exp_param_input_types",
                "private_attr": "exp_private_input",
                "layout_attr": "exp_param_layout",
                "header": "<b>Optional experiment parameters:</b>",
                "refresh": True,
            },
            "seqspec": {
                "items_attr": None,
                "input_attr": "seqspec_param_input",
                "types_attr": "seqspec_param_input_types",
                "private_attr": "seqspec_private_input",
                "layout_attr": "seqspec_param_layout",
                "header": "<b>Required sequence parameters:</b>",
                "refresh": False,
            },
        }
        cfg = _cfg[mode]

        if args is None and cfg["items_attr"] is not None:
            item = getattr(self, cfg["items_attr"])[idx]
            args = list(item["args"])
            defaults = list(item["defaults"])
            argtypes = list(item["argtypes"])

        self.dynamic_col.children.pop(3)

        for _ in range(len(args) - len(defaults)):
            defaults.insert(0, "")

        setattr(self, cfg["input_attr"], [])
        setattr(self, cfg["types_attr"], [])
        setattr(self, cfg["private_attr"], [])
        param_layout = [
            Spacer(height=10),
            layout(
                [
                    [
                        Div(
                            text=cfg["header"],
                            width=200 + 50,
                            height=15,
                            styles={"font-size": "100%", "color": "black"},
                        ),
                    ],
                ],
                background=self.color_sq_param_inputs,
                width=self.max_width,
                height_policy="min",
            ),
        ]
        setattr(self, cfg["layout_attr"], param_layout)

        param_input = getattr(self, cfg["input_attr"])
        private_input = getattr(self, cfg["private_attr"])
        argtype_list = getattr(self, cfg["types_attr"])

        self.add_dynamic_inputs(
            param_input,
            private_input,
            param_layout,
            args,
            defaults,
            argtypes,
            argtype_list,
        )

        if not param_input:
            param_layout.append(
                layout(
                    [
                        [
                            Spacer(width=10),
                            Div(
                                text="-- none --",
                                width=200 + 50,
                                height=15,
                                styles={"font-size": "100%", "color": "black"},
                            ),
                        ],
                    ],
                    background=self.color_sq_param_inputs,
                    width=self.max_width,
                ),
            )

        self.dynamic_col.children.insert(3, layout(param_layout, height_policy="min"))

        if cfg["refresh"]:
            self.refresh_inputs(param_input, private_input)

    def get_sequence_lib(self):
        """Populates sequences (library) and sequence_list (dropdown selector)."""
        self.sequences, self.sequence_select_list = self._build_lib(
            self.sequence_lib,
            None,
            "sequence_params",
            return_sequence_lib,
            "sequence_name",
        )

    def get_experiment_lib(self):
        """Populates experiments (library) and experiment_list (dropdown selector)."""
        self.experiments, self.experiment_select_list = self._build_lib(
            self.experiment_lib,
            Experiment,
            "experiment_params",
            return_experiment_lib,
            "experiment_name",
        )

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
            self.sequence_lists["campaign_name"].append(
                seqdict.get("campaign_name", None)
            )
            self.sequence_lists["campaign_uuid"].append(
                seqdict.get("campaign_uuid", None)
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
            self.action_server_source.stream(
                self.action_server_lists, rollover=self.num_actserv
            )

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
        campaign_name = self.input_campaign_name.value
        if campaign_name != "":
            seq.campaign_name = campaign_name
            if self.input_campaign_uuid.value.strip() == "":
                seq.campaign_uuid = md5_string(campaign_name)
            else:
                seq.campaign_uuid = self.input_campaign_uuid.value.strip()
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
            self.get_pm(plateid, sender)
            self.get_elements_plateid(plateid, sender)

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
        self._apply_sequence_to_orch(self.orch.add_sequence)

    def callback_add_split_sequences(self, event):
        """add experiment plan as sequences split by sample to orch sequence_dq"""
        self._apply_sequence_to_orch(self.orch.add_split_sequences)

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
        self.populate_sequence(prepend=True)
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_append_seq(self, event):
        self.populate_sequence(prepend=False)
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
        self.sequence.planned_experiments.append(experimentmodel)

    def prepend_experiment(self):
        experimentmodel = self.populate_experimentmodel()
        self.sequence.planned_experiments.insert(0, experimentmodel)

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

    def populate_sequence(self, prepend: bool = False):
        selected_sequence = self.sequence_dropdown.value
        LOGGER.info(f"selected sequence from list: {selected_sequence}")

        sequence_params = {
            paraminput.title: (
                input_type(parse_bokeh_input(paraminput.value))
                if input_type in BUILTIN_TYPES
                else parse_bokeh_input(paraminput.value)
            )
            for paraminput, input_type in zip(
                self.seq_param_input, self.seq_param_input_types
            )
        }
        for k, v in sequence_params.items():
            LOGGER.info(
                f"added sequence param '{k}' with value {v} and type {type(v)} "
            )

        self.write_params("seq", selected_sequence, sequence_params)
        start_time = time.time()
        expplan_list = self.orch.unpack_sequence(
            sequence_name=selected_sequence, sequence_params=sequence_params
        )
        end_time = time.time()
        LOGGER.debug(f"Unpacking sequence took {end_time - start_time} seconds")

        if self.sequence is None:
            self.sequence = Sequence()
            self.sequence.planned_experiments = []
        self.sequence.sequence_name = selected_sequence
        self.sequence.sequence_label = self.input_sequence_label.value
        self.sequence.sequence_params = sequence_params
        start_time = time.time()
        if prepend:
            self.sequence.planned_experiments = (
                expplan_list + self.sequence.planned_experiments
            )
        else:
            self.sequence.planned_experiments += expplan_list
        end_time = time.time()
        LOGGER.debug(
            f"Adding experiments to sequence took {end_time - start_time} seconds"
        )

    def populate_experimentmodel(self) -> Experiment:
        selected_experiment = self.experiment_dropdown.value
        LOGGER.info(f"selected experiment from list: {selected_experiment}")
        experiment_params = {
            paraminput.title: (
                input_type(parse_bokeh_input(paraminput.value))
                if input_type in BUILTIN_TYPES
                else parse_bokeh_input(paraminput.value)
            )
            for paraminput, input_type in zip(
                self.exp_param_input, self.exp_param_input_types
            )
        }
        for k, v in experiment_params.items():
            LOGGER.info(
                f"added experiment param '{k}' with value {v} and type {type(v)} "
            )
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
        self._update_param_layout("seq", idx)

    def update_exp_param_layout(self, idx):
        self._update_param_layout("exp", idx)

    def update_seqspec_param_layout(self, idx):
        args = []
        argtypes = []
        defaults = []
        seqspec_path = self.seqspecs[idx]
        try:
            seqfunc_params = self.seqspec_parser.list_params(seqspec_path, self.orch)
        except Exception:
            LOGGER.error(f"error parsing specfile {seqspec_path}", exc_info=True)
            seqfunc_params = {}
        for arg, argtype in self.seqspec_parser.PARAM_TYPES.items():
            if arg in seqfunc_params:
                args.append(arg)
                argtypes.append(argtype)
        self._update_param_layout(
            "seqspec", idx, args=args, defaults=defaults, argtypes=argtypes
        )

    def add_dynamic_inputs(
        self,
        param_input,
        private_input,
        param_layout,
        args,
        defaults,
        argtypes,
        argtype_list,
    ):
        item = 0

        for idx in range(len(args)):
            def_val = f"{defaults[idx]}"
            # if args[idx] == "experiment":
            #     continue
            # disabled = False

            initial_stylesheet = [".bk-input { color: black; }"]
            text_input = TextInput(
                value=def_val,
                title=args[idx],
                disabled=True if args[idx].endswith("_version") else False,
                width=400,
                height=40,
                stylesheets=initial_stylesheet,
            )
            color_callback_js = CustomJS(
                args=dict(input=text_input),
                code=f"""
var value = input.value;
var new_color = "black";
if (value !== '{def_val}') {{
    new_color = "red";
}}
input.stylesheets = [`.bk-input {{ color: ${{new_color}} !important; }}`]
""",
            )
            # text_input.js_on_change("value", color_callback_js)
            text_input.js_on_change("value_input", color_callback_js)
            param_input.append(text_input)
            argtype_list.append(argtypes[idx])
            param_layout.append(
                layout(
                    [
                        [
                            param_input[item],
                            Div(
                                text=str(argtypes[idx])
                                .split()[-1]
                                .strip("'<>]")
                                .split(".")[-1]
                                .replace("[", " of "),
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

    def get_pm(self, plateid: int, sender):
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
            pmdata = self.dataAPI.get_platemap_plateid(int(input_plate_id.value))

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
            if isinstance(inp, figure):
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
            pmdata = self.dataAPI.get_platemap_plateid(int(input_plate_id.value))
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
        start_time = time.time()
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
            for D in self.sequence.planned_experiments:
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
            if (
                self.orch.active_sequence is not None
                and self.orch.active_experiment is not None
            ):
                self.orch_status_button.label = f"running {str(self.orch.active_sequence.sequence_name)} / {str(self.orch.active_experiment.experiment_name)}"
            else:
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
        self.button_add_expplan.label = f"Add plan [{plan_count}]"
        end_time = time.time()
        LOGGER.debug(f"Updating tables took {end_time - start_time} seconds")

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
