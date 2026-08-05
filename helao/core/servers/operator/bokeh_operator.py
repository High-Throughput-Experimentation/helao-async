"""Bokeh operator UI for the HELAO orchestrator.

Defines the :class:`BokehOperator` Bokeh application that displays sequence,
experiment and action queues, drives the orchestrator's start/stop/skip
controls, and lets a human pick sequences/experiments and edit their
parameters before enqueueing them.

Also exposes two small pydantic models (:class:`return_sequence_lib`,
:class:`return_experiment_lib`) used to describe entries from the loaded
sequence and experiment libraries.
"""

import html as _html
import inspect
import io
import json
import os
import re
import time
from enum import Enum
from functools import partial
from socket import gethostname
from typing import Optional

import numpy as np
from bokeh.events import ButtonClick, DoubleTap
from bokeh.layouts import Spacer, column, layout, row
from bokeh.models import (
    Button,
    CheckboxGroup,
    ColumnDataSource,
    CustomJS,
    DataTable,
    InlineStyleSheet,
    RadioButtonGroup,
    Select,
    TableColumn,
    TabPanel,
    Tabs,
)
from bokeh.models.widgets import Div, FileInput
from bokeh.models.widgets.inputs import TextAreaInput, TextInput
from bokeh.plotting import figure
from pybase64 import b64decode
from pydantic import BaseModel

from helao.core.models.orchstatus import LoopStatus
from helao.core.servers.bokeh_theme import (
    SECTION_MARGIN,
    color_rule,
    estop_button_stylesheet,
    file_load_button_stylesheet,
    semantic_button_stylesheet,
    stretch_section,
)
from helao.core.servers.operator import param_store, spec_parser
from helao.core.servers.operator.object_tree import (
    doc_to_html,
    open_keys_for,
    object_to_html,
    render_node,
    server_header_text,
    tree_header_text,
    truncate_uuid,
)
from helao.core.servers.operator.param_forms import (
    BUILTIN_TYPES,
    build_lib,
    parse_arg_docs,
    resolve_campaign_uuid,
    version_hint_parts,
)
from helao.core.servers.palette import (
    BODY_TEXT,
    ESTOP_BG,
    ESTOP_HOVER_BG,
    HEADING_TEXT,
    MODIFIED_PARAM_TEXT,
    MUTED_TEXT_ON_PANEL,
    PANEL_BG,
    PANEL_BORDER,
    PANEL_BORDER_WIDTH,
    PARAM_INPUT_BG,
    PLAN_PANEL_NONQUEUED_BG,
    SELECTED_MARKER_OUTLINE,
    SURFACE_WHITE,
    panel_styles,
)
from helao.core.servers.vis import Vis
from helao.helpers.config_loader import is_ui_only_server
from helao.helpers import helao_logging as logging
from helao.helpers.premodels import Experiment, Sequence
from helao.helpers.to_json import parse_bokeh_input

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


# Bokeh re-runs makeBokehApp (and thus BokehOperator.__init__) on every client
# connection. The following process-level cache holds the session-invariant
# results of expensive per-config work so only the first connection pays for it:
#   * _PLATE_API_CACHE: shared read-only plate-data API instances (keyed by class
#     name) whose construction loads static plate data.
# The spec-parser module cache moved to spec_parser alongside the loader, and
# the introspected sequence/experiment dropdown table to param_forms, both
# because the Reflex operator shares them.
_PLATE_API_CACHE: dict = {}


# The collapsible-HTML renderers moved to object_tree alongside param_forms and
# spec_parser, because the Reflex operator shows the same trees and docstrings.
# Re-exported under their original private names: this module's own call sites
# use them, and so does test_standalone_operator.
_render_node = render_node
_object_to_html = object_to_html
_truncate_uuid = truncate_uuid
_tree_header_text = tree_header_text
_server_header_text = server_header_text


#: Margin on the blocks that make up the parameter form. They are the one place
#: a section margin is *wrong*: the tinted blocks are not separate sections but
#: consecutive rows of one form, and a 4px gutter around each drew a white
#: outline around every parameter. Zero vertically so the rows abut into a
#: single tinted field, and the same 4px horizontally as everything else so the
#: field's outer edges still line up with the sections above and below it.
PARAM_FIELD_MARGIN = (0, 4, 0, 4)

#: Margin on the "Optional/Required … parameters:" caption that opens the
#: field. Top only — its bottom edge is the field's first row.
PARAM_HEADING_MARGIN = (4, 4, 0, 4)

#: ``LayoutDOM.name`` carried by exactly the parameter cells that may share a
#: row with a neighbour. ``_pair_param_cells`` groups consecutive blocks
#: carrying it into two-column rows and passes everything else through at full
#: width, which is what keeps the plate map, the file input and the
#: custom-position selector — all of which a special-cased parameter appends or
#: substitutes *after* its cell — out of the grid without the pairing pass
#: needing to know they exist.
PARAM_CELL_NAME = "helao_param_cell"

#: Labels of the two-way radio group a ``bool`` parameter renders as. They are
#: the *values* as well as the labels: ``param_widget_value`` returns the active
#: one verbatim, and ``parse_bokeh_input`` maps exactly these two strings to
#: Python booleans, so nothing downstream has to learn about the widget.
BOOL_LABELS = ["True", "False"]

#: Styles on the two metadata tree views. They are white ``Div``s sitting on a
#: white-ish panel, so without an outline the scroll box has no edge and its
#: content reads as loose text in the panel rather than as a pane of its own —
#: the same argument :func:`panel_styles` makes for a section, on a control that
#: is not a section and so cannot use it. The padding is what keeps the tree's
#: first character off the line now drawn beside it.
TREE_VIEW_STYLES = {
    "overflow": "auto",
    "max-height": "200px",
    "background-color": SURFACE_WHITE,
    "border": f"{PANEL_BORDER_WIDTH} solid {PANEL_BORDER}",
    "padding": "4px",
}


def param_widget_value(widget) -> str:
    """Return the current value of a parameter widget as a string.

    Parameter widgets are mostly ``TextInput``/``Select``, which carry a
    ``value``, but a ``bool`` parameter renders as a ``RadioButtonGroup``, whose
    state is an index into ``labels`` and which raises on ``.value`` — Bokeh
    models reject attributes they do not declare, so a missed call site fails
    loudly rather than silently reading a stale default.

    Args:
        widget: A widget from one of the ``*_param_input`` lists.

    Returns:
        str: The value, as the string the parameter coercion expects.
    """
    if isinstance(widget, RadioButtonGroup):
        active = widget.active
        if active is None or not (0 <= active < len(widget.labels)):
            return ""
        return widget.labels[active]
    return widget.value


def set_param_widget_value(widget, value) -> None:
    """Write ``value`` into a parameter widget, whatever kind it is.

    The inverse of :func:`param_widget_value`. A value that is not one of
    :data:`BOOL_LABELS` clears a radio group's selection rather than guessing,
    so a bad restore reads as "nothing chosen" instead of silently as ``False``.

    Args:
        widget: A widget from one of the ``*_param_input`` lists.
        value: The new value; stringified for a radio group's comparison.
    """
    if isinstance(widget, RadioButtonGroup):
        text = str(value)
        widget.active = widget.labels.index(text) if text in widget.labels else None
        return
    widget.value = value


class return_sequence_lib(BaseModel):
    """Summary record for one entry in the loaded sequence library."""

    index: int
    sequence_name: str
    doc: str
    args: list
    defaults: list
    argtypes: list
    version: Optional[int] = None
    codehash: Optional[str] = None


class return_experiment_lib(BaseModel):
    """Summary record for one entry in the loaded experiment library."""

    index: int
    experiment_name: str
    doc: str
    args: list
    defaults: list
    argtypes: list
    version: Optional[int] = None
    codehash: Optional[str] = None


class BokehOperator:
    """Bokeh application that visualises an :class:`Orch` and lets a user drive it.

    Builds the queue/history tables, sequence/experiment/spec selectors,
    parameter inputs, and orchestrator control buttons, and wires them to the
    orchestrator's APIs via the bound :class:`Vis` instance.
    """

    plan: list[Sequence]

    def __init__(self, vis_serv: Vis, backend):
        """Build the Bokeh layout and bind the operator UI to ``backend``.

        Args:
            vis_serv: ``Vis`` helper providing access to the Bokeh document and config.
            backend: An ``OrchBackend`` (Local or Remote) the UI drives.
        """
        self.vis = vis_serv
        self.backend = backend

        self.config_dict = self.vis.server_cfg.get("params", {})
        self.dataAPI = None
        plate_api_name = self.config_dict.get("plate_api")
        if plate_api_name == "HTEPlateAPI":
            cached_api = _PLATE_API_CACHE.get(plate_api_name)
            if cached_api is None:
                from helao.helpers.plate_api import HTEPlateAPI

                cached_api = HTEPlateAPI()
                _PLATE_API_CACHE[plate_api_name] = cached_api
            self.dataAPI = cached_api
        self.loaded_config_path = self.vis.world_cfg.get("loaded_config_path", "")
        self.pal_name = None
        self.num_actserv = len(
            [
                k
                for k, v in self.vis.world_cfg["servers"].items()
                if not is_ui_only_server(v)
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

        self.color_sq_param_inputs = PARAM_INPUT_BG
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

        self.plan = []
        self._hist_objs = {"action": [], "experiment": [], "sequence": []}
        self.experiment_plan_lists = {
            k: [] for k in ["sequence_name", "sequence_label", "num_experiments"]
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

        self.action_history_lists = {
            k: []
            for k in [
                "action_endpoint",
                "action_status",
                "action_uuid",
                "experiment_name",
                "sequence_label",
                "start",
                "finish",
            ]
        }
        self.experiment_history_lists = {
            k: []
            for k in [
                "experiment_name",
                "experiment_uuid",
                "experiment_status",
                "sequence_label",
                "campaign_name",
                "start",
                "finish",
            ]
        }
        self.sequence_history_lists = {
            k: []
            for k in [
                "sequence_name",
                "sequence_uuid",
                "sequence_status",
                "sequence_label",
                "campaign_name",
                "start",
                "finish",
            ]
        }

        self.action_server_lists = {
            k: [] for k in ["action_server", "server_status", "driver_status"]
        }

        self.sequence_select_list = []
        self.sequences = []
        self.sequence_lib = self.backend.sequence_lib

        self.experiment_select_list = []
        self.experiments = []
        self.experiment_lib = self.backend.experiment_lib

        self.seqspec_select_list = []
        self.seqspecs = []
        self.seqspec_parser = None
        self.seqspec_folder = None
        self.parser_path = self.config_dict.get("seqspec_parser_path", None)
        specs_folder = self.config_dict.get("seqspec_folder_path", None)
        # Loading goes through the shared layer so the Reflex operator reads
        # the same parser, from the same cache, with the same failure
        # behaviour: a broken parser disables the tab rather than taking down
        # the page.
        self.seqspec_parser = spec_parser.load_parser(self.parser_path)
        if specs_folder is not None:
            if os.path.exists(specs_folder) and os.path.isdir(specs_folder):
                self.seqspec_folder = specs_folder
        self.skip_default_highlights = set(
            self.config_dict.get("skip_default_highlights", [])
        )

        # FastAPI calls
        self.get_sequence_lib()
        self.get_experiment_lib()

        self.vis.doc.add_next_tick_callback(partial(self.get_sequences))
        self.vis.doc.add_next_tick_callback(partial(self.get_experiments))
        self.vis.doc.add_next_tick_callback(partial(self.get_actions))
        self.vis.doc.add_next_tick_callback(partial(self.get_history))
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
            sizing_mode="stretch_width",
        )

        self.action_history_source, self.action_history_table = self._make_table(
            self.action_history_lists, fit_columns=True
        )
        self.experiment_history_source, self.experiment_history_table = (
            self._make_table(self.experiment_history_lists, fit_columns=True)
        )
        self.sequence_history_source, self.sequence_history_table = self._make_table(
            self.sequence_history_lists, fit_columns=True
        )

        self.planner_tab = TabPanel(
            child=self.experiment_plan_table,
            title="Plan",
        )
        self.action_history_tab = TabPanel(
            child=self.action_history_table,
            title="Action History",
        )
        self.experiment_history_tab = TabPanel(
            child=self.experiment_history_table,
            title="Experiment History",
        )
        self.sequence_history_tab = TabPanel(
            child=self.sequence_history_table,
            title="Sequence History",
        )
        self.planhistory_tabs = Tabs(
            tabs=[
                self.planner_tab,
                self.sequence_history_tab,
                self.experiment_history_tab,
                self.action_history_tab,
            ],
            height_policy="min",
            sizing_mode="stretch_width",
        )

        self.sequence_dropdown = Select(
            title="Select sequence:",
            value=None,
            options=self.sequence_select_list,
        )
        self.sequence_dropdown.on_change("value", self.callback_sequence_select)
        self.sequence_version_div = Div(
            text="",
            width=300,
            height=31,
            margin=(22, 5, 0, 5),
            styles={"line-height": "31px", "color": MUTED_TEXT_ON_PANEL},
        )

        self.experiment_dropdown = Select(
            title="Select experiment:", value=None, options=self.experiment_select_list
        )
        self.experiment_dropdown.on_change("value", self.callback_experiment_select)
        self.experiment_version_div = Div(
            text="",
            width=300,
            height=31,
            margin=(22, 5, 0, 5),
            styles={"line-height": "31px", "color": MUTED_TEXT_ON_PANEL},
        )

        # specification file loader
        self.seqspec_dropdown = Select(
            title="Select spec file:", value=None, options=self.seqspec_select_list
        )
        self.seqspec_dropdown.on_change("value", self.callback_seqspec_select)

        if self.seqspec_parser is not None and self.seqspec_folder is not None:
            self.get_seqspec_lib()

        # buttons to control orch
        self.button_start_orch = self._make_button(
            "Start Orch", "success", 70, self.callback_start_orch
        )
        self.button_estop_orch = self._make_button(
            "ESTOP",
            "danger",
            int(self.max_width * 0.25),
            self.callback_estop_orch,
            height=100,
            sizing_mode="fixed",
            # ESTOP's own sheet, and *only* it: both this and
            # semantic_button_stylesheet() target .bk-btn.bk-btn-danger at equal
            # specificity, so whichever came later in the list would win and the
            # ESTOP would silently render as an ordinary red-700 danger button.
            # _make_button skips the shared sheet whenever a caller supplies its
            # own, which is what keeps this the only sheet here.
            stylesheets=[estop_button_stylesheet()],
        )
        self.button_add_expplan = self._make_button(
            "Add plan", "default", 100, self.callback_add_expplan
        )
        self.button_add_smpseqs = self._make_button(
            "Split plan", "default", 100, self.callback_add_split_sequences
        )
        self.button_prepend_plan = self._make_button(
            "Prepend plan", "default", 100, self.callback_prepend_plan
        )
        self.button_plan_move_up = self._make_button(
            "Plan ↑", "default", 70, self.callback_plan_move_up, width_policy="min"
        )
        self.button_plan_move_down = self._make_button(
            "Plan ↓", "default", 70, self.callback_plan_move_down, width_policy="min"
        )
        self.button_plan_remove = self._make_button(
            "Plan ✕", "default", 70, self.callback_plan_remove, width_policy="min"
        )
        # One set of queue-reorder buttons that acts on whichever queue tab is
        # active (Sequence / Experiment / Action). See callback_queue_* and
        # _active_queue_target.
        self.button_queue_move_up = self._make_button(
            "Queue ↑", "default", 70, self.callback_queue_move_up, width_policy="min"
        )
        self.button_queue_move_down = self._make_button(
            "Queue ↓", "default", 70, self.callback_queue_move_down, width_policy="min"
        )
        self.button_queue_remove = self._make_button(
            "Queue ✕", "default", 70, self.callback_queue_remove, width_policy="min"
        )
        self.button_stop_orch = self._make_button(
            "Stop Orch", "danger", 70, self.callback_stop_orch
        )
        # align="center" cross-centers the checkbox vertically against the
        # adjacent Stop Orch button in their shared row.
        self.reset_run_id_on_stop = CheckboxGroup(
            labels=["reset run_id"], active=[], align="center"
        )
        self.button_skip_exp = self._make_button(
            "Skip exp", "danger", 70, self.callback_skip_exp
        )
        self.button_update = self._make_button(
            "Update tables", "default", 120, self.callback_update_tables
        )
        self.button_clear_expplan = self._make_button(
            "Clear plan", "default", 100, self.callback_clear_expplan
        )
        self.orch_status_button = Button(
            label="Disabled",
            disabled=False,
            button_type="danger",
            sizing_mode="stretch_width",
            # update_tables drives this through all four types (success while
            # running, warning/primary when stopped, danger otherwise), so it
            # needs the sheet that carries all four.
            stylesheets=[semantic_button_stylesheet()],
        )  # fills width left by the other buttons

        self.orch_stepact_button = self._make_stepwise_button(
            "actions", self.callback_toggle_stepact
        )
        self.orch_stepexp_button = self._make_stepwise_button(
            "experiments", self.callback_toggle_stepexp
        )
        self.orch_stepseq_button = self._make_stepwise_button(
            "sequences", self.callback_toggle_stepseq
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

        self.planhistory_tree_header = Div(
            text="<b>select a row</b>", height=20, sizing_mode="stretch_width"
        )
        self.planhistory_tree_div = Div(
            text="",
            sizing_mode="stretch_width",
            styles=dict(TREE_VIEW_STYLES),
        )
        self.queue_tree_header = Div(
            text="<b>select a row</b>", height=20, sizing_mode="stretch_width"
        )
        self.queue_tree_div = Div(
            text="",
            sizing_mode="stretch_width",
            styles=dict(TREE_VIEW_STYLES),
        )

        self.error_txt = Div(
            text="""no error""",
            sizing_mode="stretch_width",
            height=60,
            styles={"font-size": "100%", "color": BODY_TEXT},
        )

        self.input_sequence_label = TextInput(
            value="nolabel",
            title="sequence label",
            disabled=False,
            sizing_mode="stretch_width",
            height=31,
        )
        self.input_sequence_label2 = TextInput(
            value="nolabel",
            title="sequence label",
            disabled=False,
            sizing_mode="stretch_width",
            height=31,
        )
        self.input_campaign_name = TextInput(
            value="",
            title="campaign name",
            disabled=False,
            sizing_mode="stretch_width",
            height=31,
        )
        self.input_campaign_name2 = TextInput(
            value="",
            title="campaign name",
            disabled=False,
            sizing_mode="stretch_width",
            height=31,
        )
        self.input_campaign_uuid = TextInput(
            value="",
            title="campaign uuid",
            disabled=False,
            sizing_mode="stretch_width",
            height=31,
        )
        self.input_campaign_uuid2 = TextInput(
            value="",
            title="campaign uuid",
            disabled=False,
            sizing_mode="stretch_width",
            height=31,
        )
        self.input_sequence_comment = TextAreaInput(
            value="",
            title="sequence comment",
            disabled=False,
            sizing_mode="stretch_width",
            height=90,
            rows=3,
        )
        self.input_sequence_comment2 = TextAreaInput(
            value="",
            title="sequence comment",
            disabled=False,
            sizing_mode="stretch_width",
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
        self.input_sequence_label.on_change(
            "value",
            partial(self._sanitize_label_callback, self.input_sequence_label),
        )
        self.input_sequence_label2.on_change(
            "value",
            partial(self._sanitize_label_callback, self.input_sequence_label2),
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
            sizing_mode="stretch_width",
            height=32,
            styles={"font-size": "150%", "color": HEADING_TEXT},
        )

        self.layout0 = layout(
            [
                stretch_section(
                    layout(
                        [
                            Spacer(width=20),
                            Div(
                                text=f"<b>{self.config_dict.get('doc_name', 'BokehOperator')} on {gethostname().lower()} -- config: {os.path.basename(self.loaded_config_path)}</b>",
                                sizing_mode="stretch_width",
                                height=32,
                                styles={"font-size": "200%", "color": HEADING_TEXT},
                            ),
                        ],
                        height_policy="min",
                        margin=SECTION_MARGIN,
                    )
                ),
                Spacer(height=10),
            ],
            sizing_mode="stretch_width",
            height_policy="min",
        )
        # Selector tabs hold only the dropdown + description. The sequence
        # label/campaign/comment fields and the append/prepend button rows are
        # moved into a footer block rendered *below* the dynamic parameter
        # layout (see ``_build_param_footer`` / ``_update_param_layout``).
        # The selector tabs hold ONLY the dropdown so every tab panel has the
        # same (minimal) height. Bokeh's ``Tabs`` sizes its content area to the
        # tallest panel and stacks all panels, so any per-selection height
        # variation inside a panel (e.g. the item description) would leave a
        # variable whitespace gap above the dynamic parameter block below. The
        # item description is therefore rendered inside the dynamic parameter
        # block instead (see ``_update_param_layout``).
        self.layout1 = layout(
            [
                stretch_section(
                    layout(
                        [
                            [self.sequence_dropdown, self.sequence_version_div],
                        ],
                        styles=panel_styles(PANEL_BG),
                        height_policy="min",
                        margin=SECTION_MARGIN,
                    )
                ),
            ],
            sizing_mode="stretch_width",
            height_policy="min",
        )

        self.layout2 = layout(
            [
                stretch_section(
                    layout(
                        [
                            [self.experiment_dropdown, self.experiment_version_div],
                        ],
                        styles=panel_styles(PANEL_BG),
                        height_policy="min",
                        margin=SECTION_MARGIN,
                    )
                ),
            ],
            sizing_mode="stretch_width",
            height_policy="min",
        )

        self.layout3 = layout(
            [
                stretch_section(
                    layout(
                        [
                            [self.seqspec_dropdown],
                        ],
                        styles=panel_styles(PANEL_BG),
                        height_policy="min",
                        margin=SECTION_MARGIN,
                    )
                ),
            ],
            sizing_mode="stretch_width",
            height_policy="min",
        )

        self.layout4 = layout(
            [
                Spacer(height=10),
                stretch_section(
                    layout(
                        [
                            Spacer(width=20),
                            self.orch_section,
                        ],
                        height_policy="min",
                        margin=SECTION_MARGIN,
                    )
                ),
                stretch_section(
                    layout(
                        [
                            row(
                                self.button_add_expplan,
                                self.button_add_smpseqs,
                                self.button_prepend_plan,
                                self.button_clear_expplan,
                                self.button_start_orch,
                                self.button_stop_orch,
                                self.reset_run_id_on_stop,
                                spacing=4,
                                sizing_mode="stretch_width",
                            ),
                            Spacer(height=10),
                        ],
                        styles=panel_styles(PANEL_BG),
                        height_policy="min",
                        margin=SECTION_MARGIN,
                    )
                ),
                stretch_section(
                    layout(
                        [
                            [
                                Div(
                                    text="<b>Non-queued:</b>",
                                    width=200 + 50,
                                    height=15,
                                ),
                            ],
                            [
                                row(
                                    column(
                                        self.planhistory_tabs,
                                        sizing_mode="stretch_width",
                                        stylesheets=[
                                            InlineStyleSheet(
                                                css=":host { flex: 7 1 0% !important; }"
                                            )
                                        ],
                                    ),
                                    column(
                                        self.planhistory_tree_header,
                                        self.planhistory_tree_div,
                                        sizing_mode="stretch_width",
                                        stylesheets=[
                                            InlineStyleSheet(
                                                css=":host { flex: 3 1 0% !important; }"
                                            )
                                        ],
                                    ),
                                    sizing_mode="stretch_width",
                                ),
                            ],
                            row(
                                self.button_plan_move_up,
                                self.button_plan_move_down,
                                self.button_plan_remove,
                                spacing=4,
                            ),
                        ],
                        styles=panel_styles(PLAN_PANEL_NONQUEUED_BG),
                        height_policy="min",
                        margin=SECTION_MARGIN,
                    )
                ),
                stretch_section(
                    layout(
                        [
                            [
                                Div(
                                    text="<b>Queues:</b>",
                                    width=200 + 50,
                                    height=15,
                                ),
                            ],
                            row(
                                self.orch_stepact_button,
                                self.orch_stepexp_button,
                                self.orch_stepseq_button,
                                self.orch_status_button,
                                spacing=4,
                                sizing_mode="stretch_width",
                            ),
                            [
                                row(
                                    column(
                                        self.queue_tabs,
                                        sizing_mode="stretch_width",
                                        stylesheets=[
                                            InlineStyleSheet(
                                                css=":host { flex: 7 1 0% !important; }"
                                            )
                                        ],
                                    ),
                                    column(
                                        self.queue_tree_header,
                                        self.queue_tree_div,
                                        sizing_mode="stretch_width",
                                        stylesheets=[
                                            InlineStyleSheet(
                                                css=":host { flex: 3 1 0% !important; }"
                                            )
                                        ],
                                    ),
                                    sizing_mode="stretch_width",
                                ),
                            ],
                            row(
                                self.button_queue_move_up,
                                self.button_queue_move_down,
                                self.button_queue_remove,
                                spacing=4,
                            ),
                            Spacer(height=10),
                            row(
                                self.button_skip_exp,
                                self.button_clear_seqs,
                                self.button_clear_exps,
                                self.button_clear_action,
                                self.button_update,
                                spacing=4,
                            ),
                            Spacer(height=10),
                            row(
                                column(self.button_estop_orch),
                                column(
                                    Div(
                                        text="<b>Error message:</b>",
                                        height=15,
                                        sizing_mode="stretch_width",
                                        styles={
                                            "font-size": "100%",
                                            "color": BODY_TEXT,
                                        },
                                    ),
                                    self.error_txt,
                                    sizing_mode="stretch_width",
                                ),
                                spacing=10,
                                sizing_mode="stretch_width",
                            ),
                            Spacer(height=10),
                        ],
                        styles=panel_styles(PANEL_BG),
                        height_policy="min",
                        margin=SECTION_MARGIN,
                    )
                ),
            ],
            sizing_mode="stretch_width",
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
        # The Tabs container needs the stretch itself: its panels' contents are
        # already stretch_width, but a Tabs sizes to its widest panel and then
        # clips them to that, so the selection block sat at the dropdown's
        # width while every section below it filled the page.
        if self.seqspec_folder is not None and self.seqspec_parser is not None:
            self.select_tabs = Tabs(
                tabs=[
                    self.sequence_select_tab,
                    self.experiment_select_tab,
                    self.seqspec_select_tab,
                ],
                sizing_mode="stretch_width",
            )
        else:
            self.select_tabs = Tabs(
                tabs=[
                    self.sequence_select_tab,
                    self.experiment_select_tab,
                ],
                sizing_mode="stretch_width",
                height_policy="min",
            )
        self.select_tabs.on_change("active", self.update_selector_layout)
        self.dynamic_col = column(
            self.layout0,
            layout(height_policy="min"),
            self.select_tabs,
            layout(height_policy="min"),
            self.layout4,  # placeholder  # placeholder
            sizing_mode="stretch_width",
        )
        self.vis.doc.add_root(self.dynamic_col)

        # Tree views react to row-selection in the active tab + tab switches.
        for _src in (
            self.experiment_plan_source,
            self.action_history_source,
            self.experiment_history_source,
            self.sequence_history_source,
        ):
            _src.selected.on_change(
                "indices", lambda a, o, n: self._render_planhistory_tree()
            )
        self.planhistory_tabs.on_change(
            "active", lambda a, o, n: self._render_planhistory_tree()
        )
        for _src in (
            self.sequence_source,
            self.experiment_source,
            self.action_source,
            self.action_server_source,
        ):
            _src.selected.on_change(
                "indices", lambda a, o, n: self._render_queue_tree()
            )
        self.queue_tabs.on_change(
            "active",
            lambda a, o, n: (
                self._render_queue_tree(),
                self._refresh_queue_button_state(),
            ),
        )

        # select the first item to force an update of the layout
        if self.experiment_select_list and self.select_tabs.active == 1:
            self.experiment_dropdown.value = self.experiment_select_list[0]

        if self.sequence_select_list and self.select_tabs.active == 0:
            self.sequence_dropdown.value = self.sequence_select_list[0]

        if self.seqspec_select_list and self.select_tabs.active == 2:
            self.seqspec_dropdown.value = self.seqspec_select_list[0]

        self._queue_counts = {"n_sequences": 0, "n_experiments": 0, "n_actions": 0}
        self._current_stop_message = ""
        # Last orch state the unified queue buttons gate on (set by update_tables).
        self._loop_state = None
        self._manual_seq = False
        # queue_tabs index -> (source, move_fn, remove_fn, name_col) for the
        # unified reorder buttons. The Action Servers tab (3) has no entry.
        self._queue_targets = {
            0: (
                self.sequence_source,
                self.backend.move_sequence,
                self.backend.remove_sequence,
                "sequence_name",
            ),
            1: (
                self.experiment_source,
                self.backend.move_experiment,
                self.backend.remove_experiment,
                "experiment_name",
            ),
            2: (
                self.action_source,
                self.backend.move_action,
                self.backend.remove_action,
                "action_name",
            ),
        }
        self.backend.subscribe(self._on_backend_change)
        self.vis.doc.on_session_destroyed(self.cleanup_session)

    def _on_backend_change(self):
        """Backend notified a state change: schedule a table refresh on the doc thread."""
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def cleanup_session(self, session_context):
        """Tear down the backend subscription when the Bokeh session ends."""
        LOGGER.info("BokehOperator session closed")
        self.backend.close()

    # ------------------------------------------------------------------
    # Private helpers — used to reduce repetition in __init__ and below
    # ------------------------------------------------------------------

    def _make_table(self, data_dict: dict, **extra_kwargs) -> tuple:
        """Build a ``(ColumnDataSource, DataTable)`` pair backed by ``data_dict``."""
        source = ColumnDataSource(data=data_dict)
        columns = [TableColumn(field=k, title=k) for k in data_dict]
        table = DataTable(
            source=source,
            columns=columns,
            sizing_mode="stretch_width",
            height=200,
            autosize_mode="force_fit" if "fit_columns" not in extra_kwargs else "none",
            **extra_kwargs,
        )
        return source, table

    def _make_button(
        self, label: str, btn_type: str, width: int, callback, **kwargs
    ) -> Button:
        """Create a Bokeh ``Button`` already wired to ``callback`` on click.

        A semantic ``btn_type`` also gets the palette's per-widget override,
        which is the only mechanism that can recolour a Bokeh widget: Bokeh
        supplies its semantic colours from inside each widget's own shadow root,
        where no document-level stylesheet reaches. ``"default"`` is left alone —
        it is Bokeh's neutral, and the aligner's marker chips are default buttons
        carrying their own override.

        A caller passing its own ``stylesheets`` (the ESTOP button) is not
        given the shared sheet: its override already covers the one type it uses.
        """
        if btn_type != "default" and "stylesheets" not in kwargs:
            kwargs["stylesheets"] = [semantic_button_stylesheet()]
        btn = Button(label=label, button_type=btn_type, width=width, **kwargs)
        btn.on_event(ButtonClick, callback)
        return btn

    def _make_stepwise_button(self, kind: str, callback) -> Button:
        """Build a STEP/RUN toggle button reflecting the backend step flag for ``kind``."""
        is_step = self.backend.get_step_flags()[kind]
        label = f"{'STEP' if is_step else 'RUN'}-THRU {kind}"
        btn = Button(
            label=label,
            button_type="danger" if is_step else "success",
            width=170,
            # One sheet carries all four types, so update_stepwise_toggle's
            # danger<->success flip keeps its palette colours.
            stylesheets=[semantic_button_stylesheet()],
        )
        btn.on_event(ButtonClick, callback)
        return btn

    def _make_copy_callback(self, source_attr: str, target_attr: str):
        """Return an ``on_change`` callback that mirrors the value of one input into another."""

        def _cb(attr, old, new):
            self.vis.doc.add_next_tick_callback(
                partial(
                    self.update_input_value,
                    getattr(self, target_attr),
                    getattr(self, source_attr).value,
                )
            )

        return _cb

    def _clean_label(self, value):
        """Collapse whitespace/underscore runs to single underscores (None-safe)."""
        if not value:
            return value
        return re.sub(r"[\s_]+", "_", value)

    def _sanitize_label_callback(self, sender, attr, old, new):
        """Rewrite a label input's value to its sanitized form when they differ."""
        cleaned = self._clean_label(new)
        if cleaned != new:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_input_value, sender, cleaned)
            )

    def _build_lib(
        self,
        lib: dict,
        filter_type,
        config_key: str,
        model_class,
        name_field: str,
        codehash_map: dict = None,
    ) -> tuple:
        """Inspect ``lib`` and return ``(items, select_list)`` for the dropdowns.

        Thin wrapper: the logic lives in
        :func:`~helao.core.servers.operator.param_forms.build_lib`, shared with
        the Reflex operator.
        """
        return build_lib(
            lib,
            filter_type,
            config_key,
            self.vis.world_cfg,
            self.loaded_config_path,
            model_class,
            name_field,
            codehash_map,
        )

    _parse_arg_docs = staticmethod(parse_arg_docs)

    @staticmethod
    def _version_hint(item: dict) -> str:
        """Format the 'version \u00b7 codehash' hint shown beside a selector dropdown."""
        # Every part is escaped now, not just the codehash: the version part is
        # "v" plus a number, so escaping it is a no-op and the output is
        # identical -- while removing the question of which part was safe.
        parts = [_html.escape(p) for p in version_hint_parts(item)]
        return f"<i>{' \u00b7 '.join(parts)}</i>" if parts else ""

    def _resolve_campaign_uuid(self, campaign_name: str):
        """Resolve the campaign UUID from operator input.

        The rule is shared with the Reflex operator through ``param_forms``;
        only reading the widget belongs here.
        """
        return resolve_campaign_uuid(campaign_name, self.input_campaign_uuid.value)

    def _capture_metadata(self, seq: Sequence) -> None:
        """Stamp label / campaign / comment from the current inputs onto ``seq``."""
        seq.sequence_label = self.input_sequence_label.value
        if self.input_sequence_comment.value != "":
            seq.sequence_comment = self.input_sequence_comment.value
        campaign_name = self.input_campaign_name.value
        if campaign_name != "":
            seq.campaign_name = campaign_name
            seq.campaign_uuid = self._resolve_campaign_uuid(campaign_name)

    def _build_param_header(self, mode: str):
        """Load-last-params button + save-params checkbox row for ``mode``
        (seq/exp only). Rendered just below the description block."""
        if mode == "seq":
            button, checkbox = self.button_last_seq_pars, self.save_last_seq_pars
        elif mode == "exp":
            button, checkbox = self.button_last_exp_pars, self.save_last_exp_pars
        else:  # seqspec has no saved-params controls
            return []
        checkbox.align = "center"
        return [
            stretch_section(
                layout(
                    [row(button, checkbox)],
                    styles=panel_styles(PANEL_BG),
                    height_policy="min",
                    margin=SECTION_MARGIN,
                )
            ),
        ]

    def _build_param_footer(self, mode: str):
        """Footer rendered below the dynamic parameter layout: the label/
        campaign/comment fields and the append/prepend button row for ``mode``."""
        if mode == "seq":
            field_row = [
                self.input_sequence_label,
                Spacer(width=20),
                self.input_campaign_name,
                Spacer(width=20),
                self.input_campaign_uuid,
            ]
            comment = self.input_sequence_comment
            button_row = [
                self.button_append_seq,
                self.button_prepend_seq,
            ]
        elif mode == "exp":
            field_row = [
                self.input_sequence_label2,
                Spacer(width=20),
                self.input_campaign_name2,
                Spacer(width=20),
                self.input_campaign_uuid2,
            ]
            comment = self.input_sequence_comment2
            button_row = [
                self.button_append_exp,
                self.button_prepend_exp,
            ]
        else:  # seqspec
            field_row = [self.input_sequence_label2]
            comment = self.input_sequence_comment2
            button_row = [
                self.button_enqueue_seqspec,
                Spacer(width=10),
                self.button_reload_seqspec,
                Spacer(width=10),
                self.button_to_seqtab,
            ]
        # Explicit stretch_width rows so the (stretch_width) label/campaign/uuid
        # and comment widgets actually fill the app width — a plain ``layout([...])``
        # auto-row stays fixed-width and the children never expand.
        comment.sizing_mode = "stretch_width"
        return [
            stretch_section(
                layout(
                    [
                        row(*field_row, sizing_mode="stretch_width"),
                        Spacer(height=16),
                        row(comment, sizing_mode="stretch_width"),
                    ],
                    styles=panel_styles(PANEL_BG),
                    height_policy="min",
                    margin=SECTION_MARGIN,
                )
            ),
            stretch_section(
                layout(
                    [button_row],
                    styles=panel_styles(PANEL_BG),
                    height_policy="min",
                    margin=SECTION_MARGIN,
                )
            ),
        ]

    def _param_cell(self, children: list):
        """Wrap ``children`` as one cell of the two-column parameter grid.

        Carries :data:`PARAM_CELL_NAME` so ``_pair_param_cells`` picks it up,
        and an explicit ``flex: 1 1 0%`` rather than a plain ``stretch_width``:
        two ``stretch_width`` siblings in a row size from their content first,
        so an over-long parameter name in one cell would steal width from the
        other and the two inputs would not line up down the page.

        ``align-self: stretch`` is the height half of the same argument.
        ``height_policy="min"`` gives each cell an explicit height, which
        overrides the flex default and leaves the shorter of two paired cells
        ending part-way up the row — the tinted blocks then read as ragged
        rather than as a grid. It has to be ``!important``: Bokeh writes the
        computed height onto the host's inline style.

        No margin at all: the inset belongs to the row (see
        :data:`PARAM_FIELD_MARGIN`), so paired cells meet with no white line
        between them and the whole form reads as one tinted field.

        Args:
            children: Rows for the cell, in ``layout()`` form.

        Returns:
            The cell's layout container.
        """
        return stretch_section(
            layout(
                children,
                background=self.color_sq_param_inputs,
                height_policy="min",
                margin=0,
                name=PARAM_CELL_NAME,
                stylesheets=[
                    InlineStyleSheet(
                        css=":host { flex: 1 1 0% !important;"
                        " align-self: stretch !important; }"
                    )
                ],
            )
        )

    def _param_extra_block(self, children: list):
        """Wrap ``children`` as a full-width block beneath a parameter cell.

        Used for the widgets a special-cased parameter adds *besides* its input
        — the plate map, its element/code/composition readouts, and the
        sample-list file picker. Deliberately without :data:`PARAM_CELL_NAME`:
        these are too wide for half a row, and staying out of the grid is also
        what keeps them directly beneath the parameter they belong to.

        Args:
            children: Rows for the block, in ``layout()`` form.

        Returns:
            The block's layout container.
        """
        return stretch_section(
            layout(
                children,
                background=self.color_sq_param_inputs,
                height_policy="min",
                margin=PARAM_FIELD_MARGIN,
            )
        )

    @staticmethod
    def _pair_param_cells(blocks: list) -> list:
        """Group consecutive parameter cells into two-column rows.

        Only blocks carrying :data:`PARAM_CELL_NAME` are paired; anything else
        (the plate map, the sample-list file input, the substituted
        custom-position selector) passes through at full width and also breaks
        a pair, so a parameter's own extra widgets stay directly beneath it
        rather than being separated from it by the next parameter.

        A cell left over at the end of a run is paired with a spacer instead of
        being widened, so the last input in an odd-length form has the same
        width as every other one.

        Args:
            blocks: The dynamic-parameter section of a param layout, in order.

        Returns:
            list: The same blocks, with parameter cells wrapped in two-up rows.
        """

        def _pair(first, second):
            return row(
                first,
                second if second is not None else Spacer(sizing_mode="stretch_width"),
                spacing=0,
                sizing_mode="stretch_width",
                # The cells inside carry no horizontal margin of their own, so
                # the two columns meet with no white line between them and the
                # inset lives on the row.
                margin=PARAM_FIELD_MARGIN,
            )

        paired: list = []
        pending = None
        for block in blocks:
            if getattr(block, "name", None) == PARAM_CELL_NAME:
                if pending is None:
                    pending = block
                else:
                    paired.append(_pair(pending, block))
                    pending = None
                continue
            if pending is not None:
                paired.append(_pair(pending, None))
                pending = None
            paired.append(block)
        if pending is not None:
            paired.append(_pair(pending, None))
        return paired

    def _update_param_layout(
        self, mode: str, idx: int, args=None, defaults=None, argtypes=None
    ):
        """Rebuild the parameter input panel for one of ``seq``/``exp``/``seqspec`` selections."""
        _cfg = {
            "seq": {
                "items_attr": "sequences",
                "input_attr": "seq_param_input",
                "types_attr": "seq_param_input_types",
                "private_attr": "seq_private_input",
                "layout_attr": "seq_param_layout",
                "header": "<b>Optional sequence parameters:</b>",
                "descr_attr": "sequence_descr_txt",
                "descr_label": "<b>sequence description:</b>",
                "refresh": True,
            },
            "exp": {
                "items_attr": "experiments",
                "input_attr": "exp_param_input",
                "types_attr": "exp_param_input_types",
                "private_attr": "exp_private_input",
                "layout_attr": "exp_param_layout",
                "header": "<b>Optional experiment parameters:</b>",
                "descr_attr": "experiment_descr_txt",
                "descr_label": "<b>experiment description:</b>",
                "refresh": True,
            },
            "seqspec": {
                "items_attr": None,
                "input_attr": "seqspec_param_input",
                "types_attr": "seqspec_param_input_types",
                "private_attr": "seqspec_private_input",
                "layout_attr": "seqspec_param_layout",
                "header": "<b>Required sequence parameters:</b>",
                "descr_attr": "seqspec_descr_txt",
                "descr_label": "<b>sequence spec description:</b>",
                "refresh": False,
            },
        }
        cfg = _cfg[mode]

        arg_descs = {}
        if cfg["items_attr"] is not None:
            item = getattr(self, cfg["items_attr"])[idx]
            arg_descs = self._parse_arg_docs(item.get("doc", ""))
            if args is None:
                args = list(item["args"])
                defaults = list(item["defaults"])
                argtypes = list(item["argtypes"])

        self.dynamic_col.children.pop(3)

        for _ in range(len(args) - len(defaults)):
            defaults.insert(0, "")

        setattr(self, cfg["input_attr"], [])
        setattr(self, cfg["types_attr"], [])
        setattr(self, cfg["private_attr"], [])
        # The item description is rendered here (rather than inside the selector
        # tab panel) so the tab panels stay a uniform, minimal height and no
        # variable whitespace appears above this block. See ``layout1``/``2``/``3``.
        # The load-last-params button + save-params checkbox row is rendered just
        # below the description block (see ``_build_param_header``).
        param_layout = (
            [
                stretch_section(
                    layout(
                        [
                            [
                                Div(
                                    text=cfg["descr_label"],
                                    width=200 + 50,
                                    height=15,
                                ),
                            ],
                            [getattr(self, cfg["descr_attr"])],
                            Spacer(height=10),
                        ],
                        styles=panel_styles(PANEL_BG),
                        height_policy="min",
                        margin=SECTION_MARGIN,
                    )
                ),
            ]
            + self._build_param_header(mode)
            + [
                Spacer(height=10),
                stretch_section(
                    layout(
                        [
                            [
                                Div(
                                    text=cfg["header"],
                                    width=200 + 50,
                                    height=15,
                                    styles={"font-size": "100%", "color": BODY_TEXT},
                                ),
                            ],
                        ],
                        background=self.color_sq_param_inputs,
                        height_policy="min",
                        margin=PARAM_HEADING_MARGIN,
                    )
                ),
            ]
        )
        setattr(self, cfg["layout_attr"], param_layout)

        param_input = getattr(self, cfg["input_attr"])
        private_input = getattr(self, cfg["private_attr"])
        argtype_list = getattr(self, cfg["types_attr"])

        # Everything appended from here down is the dynamic parameter section,
        # and only that section is paired into two columns — the description,
        # header and footer blocks stay full width.
        dyn_start = len(param_layout)

        self.add_dynamic_inputs(
            param_input,
            private_input,
            param_layout,
            args,
            defaults,
            argtypes,
            argtype_list,
            arg_descs,
        )

        if not param_input:
            param_layout.append(
                stretch_section(
                    layout(
                        [
                            [
                                Spacer(width=10),
                                Div(
                                    text="-- none --",
                                    width=200 + 50,
                                    height=15,
                                    styles={"font-size": "100%", "color": BODY_TEXT},
                                ),
                            ],
                        ],
                        background=self.color_sq_param_inputs,
                        height_policy="min",
                        margin=PARAM_FIELD_MARGIN,
                    )
                ),
            )

        param_layout[dyn_start:] = self._pair_param_cells(param_layout[dyn_start:])

        param_layout.extend(self._build_param_footer(mode))

        self.dynamic_col.children.insert(
            3,
            layout(param_layout, sizing_mode="stretch_width", height_policy="min"),
        )

        if cfg["refresh"]:
            self.refresh_inputs(param_input, private_input)

    def get_sequence_lib(self):
        """Populate the sequence library list and the sequence-selector dropdown."""
        self.sequences, self.sequence_select_list = self._build_lib(
            self.sequence_lib,
            None,
            "sequence_params",
            return_sequence_lib,
            "sequence_name",
            codehash_map=getattr(self.backend, "sequence_codehash", {}),
        )

    def get_experiment_lib(self):
        """Populate the experiment library list and the experiment-selector dropdown."""
        self.experiments, self.experiment_select_list = self._build_lib(
            self.experiment_lib,
            Experiment,
            "experiment_params",
            return_experiment_lib,
            "experiment_name",
            codehash_map=getattr(self.backend, "experiment_codehash", {}),
        )

    def get_seqspec_lib(self):
        """Refresh the sequence-specification dropdown from the configured spec folder."""
        self.seqspec_select_list = []
        self.seqspecs = []
        specfiles = self.seqspec_parser.lister(self.seqspec_folder)
        LOGGER.info(f"found specs: {specfiles}")
        for fp in specfiles:
            self.seqspecs.append(fp)
            self.seqspec_select_list.append(os.path.basename(fp))
        self.seqspec_dropdown.options = self.seqspec_select_list

    async def get_sequences(self):
        """Refresh the queued-sequences table from the backend."""
        rows = await self.backend.list_sequences()
        for key in self.sequence_lists:
            vals = [r.get(key) for r in rows]
            if key.endswith("_uuid"):
                vals = [str(v)[-8:] if v else v for v in vals]
            self.sequence_lists[key] = vals
        self._assign(self.sequence_source, "data", self.sequence_lists)

    async def get_experiments(self):
        """Refresh the queued-experiments table from the backend."""
        rows = await self.backend.list_experiments()
        for key in self.experiment_lists:
            vals = [r.get(key) for r in rows]
            if key.endswith("_uuid"):
                vals = [str(v)[-8:] if v else v for v in vals]
            self.experiment_lists[key] = vals
        self._assign(self.experiment_source, "data", self.experiment_lists)

    async def get_actions(self):
        """Refresh the queued-actions table from the backend."""
        rows = await self.backend.list_actions()
        for key in self.action_lists:
            vals = [r.get(key) for r in rows]
            if key.endswith("_uuid"):
                vals = [str(v)[-8:] if v else v for v in vals]
            self.action_lists[key] = vals
        self._assign(self.action_source, "data", self.action_lists)

    async def get_history(self):
        """Refresh the action/experiment/sequence history tables from the backend."""
        hist = await self.backend.get_histories()
        self._hist_objs = {"action": [], "experiment": [], "sequence": []}
        for key in self.action_history_lists:
            self.action_history_lists[key] = []
        for actuuid, actdict in sorted(hist["action"], key=lambda x: x[0])[::-1]:
            self._hist_objs["action"].append(actdict)
            self.action_history_lists["action_uuid"].append(str(actuuid)[-8:])
            self.action_history_lists["action_endpoint"].append(
                f"{actdict['action_server']}/{actdict['action_name']}"
            )
            self.action_history_lists["start"].append(
                actdict.get("action_timestamp", None)
            )
            self.action_history_lists["finish"].append(
                actdict.get("action_finished_timestamp", None)
            )
            # Append to EVERY column once per row (default "" when the key is
            # missing) so all ColumnDataSource columns stay equal length —
            # otherwise Bokeh refuses to render the table ("columns must be of
            # the same length") and the history tab appears empty.
            for k in ["action_status", "experiment_name", "sequence_label"]:
                val = actdict.get(k)
                if isinstance(val, list):
                    val = val[-1] if val else ""
                self.action_history_lists[k].append("" if val is None else val)
        for key in self.experiment_history_lists:
            self.experiment_history_lists[key] = []
        for expuuid, expdict in sorted(hist["experiment"], key=lambda x: x[0])[::-1]:
            self._hist_objs["experiment"].append(expdict)
            self.experiment_history_lists["experiment_uuid"].append(str(expuuid)[-8:])
            self.experiment_history_lists["experiment_name"].append(
                expdict["experiment_name"]
            )
            self.experiment_history_lists["start"].append(
                expdict.get("experiment_timestamp", None)
            )
            self.experiment_history_lists["finish"].append(
                expdict.get("experiment_finished_timestamp", None)
            )
            for k in ["experiment_status", "sequence_label", "campaign_name"]:
                val = expdict.get(k)
                if isinstance(val, list):
                    val = val[-1] if val else ""
                self.experiment_history_lists[k].append("" if val is None else val)
        for key in self.sequence_history_lists:
            self.sequence_history_lists[key] = []
        for sequuid, seqdict in sorted(hist["sequence"], key=lambda x: x[0])[::-1]:
            self._hist_objs["sequence"].append(seqdict)
            self.sequence_history_lists["sequence_uuid"].append(str(sequuid)[-8:])
            self.sequence_history_lists["sequence_name"].append(
                seqdict["sequence_name"]
            )
            self.sequence_history_lists["start"].append(
                seqdict.get("sequence_timestamp", None)
            )
            self.sequence_history_lists["finish"].append(
                seqdict.get("sequence_finished_timestamp", None)
            )
            for k in ["sequence_status", "sequence_label", "campaign_name"]:
                val = seqdict.get(k)
                if isinstance(val, list):
                    val = val[-1] if val else ""
                self.sequence_history_lists[k].append("" if val is None else val)
        self._assign(self.action_history_source, "data", self.action_history_lists)
        self._assign(
            self.experiment_history_source, "data", self.experiment_history_lists
        )
        self._assign(self.sequence_history_source, "data", self.sequence_history_lists)

    async def get_orch_status_summary(self):
        """Refresh the action-server status table from the backend's status summary."""
        summary = await self.backend.get_status_summary()
        for key in self.action_server_lists:
            self.action_server_lists[key] = []
        # Sort by server name so the table keeps a fixed row order regardless of
        # the (unordered) dict order the backend status summary arrives in.
        for server_name, (status_str, driver_str) in sorted(summary.items()):
            self.action_server_lists["action_server"].append(server_name)
            self.action_server_lists["server_status"].append(status_str)
            self.action_server_lists["driver_status"].append(driver_str)
        # Replace the data wholesale (like the history tables) instead of
        # streaming per row, so rows render exactly once in the sorted order.
        self._assign(self.action_server_source, "data", self.action_server_lists)

    def update_selector_layout(self, attr, old, new):
        """Switch the parameter panel to match the currently active selector tab."""
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
        """Rebuild the sequence parameter panel and docstring for the newly selected sequence."""
        idx = self.sequence_select_list.index(new)
        self.sequence_version_div.text = self._version_hint(self.sequences[idx])
        self.update_seq_param_layout(idx)
        self.vis.doc.add_next_tick_callback(
            partial(self.update_seq_doc, self.sequences[idx]["doc"])
        )

    def callback_experiment_select(self, attr, old, new):
        """Rebuild the experiment parameter panel and docstring for the newly selected experiment."""
        idx = self.experiment_select_list.index(new)
        self.experiment_version_div.text = self._version_hint(self.experiments[idx])
        self.update_exp_param_layout(idx)
        self.vis.doc.add_next_tick_callback(
            partial(self.update_exp_doc, self.experiments[idx]["doc"])
        )

    def callback_seqspec_select(self, attr, old, new):
        """Rebuild the spec-file parameter panel and description for the newly selected spec."""
        idx = self.seqspec_select_list.index(new)
        self.update_seqspec_param_layout(idx)
        self.vis.doc.add_next_tick_callback(
            partial(self.update_seqspec_doc, self.seqspecs[idx])
        )

    def callback_enqueue_seqspec(self, event):
        """Parse the selected spec file and enqueue the resulting sequence on the orchestrator."""
        idx = self.seqspec_select_list.index(self.seqspec_dropdown.value)
        specfile = self.seqspecs[idx]
        parser_kwargs = self.config_dict.get("parser_kwargs", {})
        input_params = {
            paraminput.name: parse_bokeh_input(param_widget_value(paraminput))
            for paraminput in self.seqspec_param_input
        }
        seq = self.seqspec_parser.parser(
            specfile, self.backend, params=input_params, **parser_kwargs
        )
        seq.sequence_label = self.input_sequence_label.value
        if self.input_sequence_comment.value != "":
            seq.sequence_comment = self.input_sequence_comment.value
        campaign_name = self.input_campaign_name.value
        if campaign_name != "":
            seq.campaign_name = campaign_name
            seq.campaign_uuid = self._resolve_campaign_uuid(campaign_name)
        self.vis.doc.add_next_tick_callback(partial(self.backend.add_sequence, seq))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_reload_seqspec(self, event):
        """Re-read the spec folder to pick up newly added specification files."""
        if self.seqspec_parser is not None and self.seqspec_folder is not None:
            self.vis.doc.add_next_tick_callback(self.get_seqspec_lib)

    def callback_to_seqtab(self, event):
        """Switch to the Sequence tab pre-populated with the selected spec's parameters."""
        idx = self.seqspec_select_list.index(self.seqspec_dropdown.value)
        specfile = self.seqspecs[idx]
        parser_kwargs = self.config_dict.get("parser_kwargs", {})
        seqspec_input_params = {
            paraminput.name: parse_bokeh_input(param_widget_value(paraminput))
            for paraminput in self.seqspec_param_input
        }
        seq = self.seqspec_parser.parser(
            specfile, self.backend, params=seqspec_input_params, **parser_kwargs
        )
        seqname = seq.sequence_name
        loaded_params = seq.sequence_params
        # switch tabs and update layout
        self.select_tabs.active = 0
        self.callback_sequence_select("value", seqname, seqname)
        self.sequence_dropdown.value = seqname
        # replace defaults with loaded params
        for i, x in enumerate(self.seq_param_input):
            if x.name in loaded_params:
                set_param_widget_value(
                    self.seq_param_input[i], str(loaded_params[x.name])
                )

    def callback_clicked_pmplot(self, event, sender):
        """On a double-tap on the plate map, snap the marker to the nearest sample."""
        LOGGER.info(f"DOUBLE TAP PMplot: {event.x}, {event.y}")
        # get coordinates of doubleclick
        platex = event.x
        platey = event.y
        # transform to nearest sample point
        PMnum = self.get_samples([platex], [platey], sender)
        self.get_sample_infos(PMnum, sender)

    def callback_changed_plateid(self, attr, old, new, sender):
        """Refresh plate map and elements when the ``plate_id`` text input changes."""

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
        """Load a text file of integer sample numbers and write them as JSON into ``inputfield``."""
        f = io.BytesIO(b64decode(sender.value))
        sample_nos = json.dumps(np.loadtxt(f).astype(int).tolist())
        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, inputfield, sample_nos)
        )

    def callback_changed_sampleno(self, attr, old, new, sender):
        """When the ``sample_no`` input changes, refresh the highlighted sample info on the plate map."""

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
        self.vis.doc.add_next_tick_callback(partial(self.backend.estop))

    def callback_start_orch(self, event):
        LOGGER.info("starting orch")
        self.vis.doc.add_next_tick_callback(partial(self.backend.start))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    async def _flush_plan(self, plan, method):
        """Dispatch each buffered sequence through ``method`` (add_sequence / add_split_sequences)."""
        for seq in plan:
            await method(seq)

    def callback_add_expplan(self, event):
        """Enqueue every buffered sequence on the orchestrator (append)."""
        plan = self.plan
        self.plan = []
        self.vis.doc.add_next_tick_callback(
            partial(self._flush_plan, plan, self.backend.add_sequence)
        )
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_add_split_sequences(self, event):
        """Enqueue every buffered sequence via the split-by-sample helper."""
        plan = self.plan
        self.plan = []
        self.vis.doc.add_next_tick_callback(
            partial(self._flush_plan, plan, self.backend.add_split_sequences)
        )
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_prepend_plan(self, event):
        """Prepend the whole plan buffer to the front of the orch sequence queue."""
        plan = self.plan
        self.plan = []
        self.vis.doc.add_next_tick_callback(
            partial(self.backend.prepend_sequences, plan)
        )
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def _selected_plan_idx(self):
        """Return the first selected plan-table row index, or ``None``."""
        idxs = list(self.experiment_plan_source.selected.indices)
        return idxs[0] if idxs else None

    def callback_plan_move_up(self, event):
        """Move the selected buffered sequence one row up."""
        i = self._selected_plan_idx()
        if i is not None and i > 0:
            self.plan[i - 1], self.plan[i] = self.plan[i], self.plan[i - 1]
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_plan_move_down(self, event):
        """Move the selected buffered sequence one row down."""
        i = self._selected_plan_idx()
        if i is not None and i < len(self.plan) - 1:
            self.plan[i + 1], self.plan[i] = self.plan[i], self.plan[i + 1]
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_plan_remove(self, event):
        """Remove the selected buffered sequence from the plan."""
        i = self._selected_plan_idx()
        if i is not None and 0 <= i < len(self.plan):
            del self.plan[i]
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def _active_queue_target(self):
        """Resolve the queue-reorder target for the active ``queue_tabs`` tab.

        Returns ``(source, move_fn, remove_fn, name_col)`` for the Sequence (0),
        Experiment (1), or Action (2) tab, or ``None`` for the read-only Action
        Servers tab (3) where reordering is not possible.
        """
        return self._queue_targets.get(self.queue_tabs.active)

    def callback_queue_move_up(self, event):
        """Move the selected item of the active queue one position toward the front."""
        tgt = self._active_queue_target()
        if tgt is None:
            return
        source, move_fn, _remove_fn, _col = tgt
        idxs = list(source.selected.indices)
        if idxs and idxs[0] > 0:
            i = idxs[0]
            self.vis.doc.add_next_tick_callback(partial(move_fn, i, i - 1))
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_queue_move_down(self, event):
        """Move the selected item of the active queue one position toward the back."""
        tgt = self._active_queue_target()
        if tgt is None:
            return
        source, move_fn, _remove_fn, col = tgt
        idxs = list(source.selected.indices)
        n = len(source.data.get(col, []))
        if idxs and idxs[0] < n - 1:
            i = idxs[0]
            self.vis.doc.add_next_tick_callback(partial(move_fn, i, i + 1))
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_queue_remove(self, event):
        """Remove the selected item of the active queue from the orch queue."""
        tgt = self._active_queue_target()
        if tgt is None:
            return
        source, _move_fn, remove_fn, _col = tgt
        idxs = list(source.selected.indices)
        if idxs:
            i = idxs[0]
            self.vis.doc.add_next_tick_callback(partial(remove_fn, i))
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def _refresh_queue_button_state(self):
        """Enable/disable the unified queue-reorder buttons for the active tab.

        Uses the last orch state seen by :meth:`update_tables` (``_loop_state`` /
        ``_manual_seq``) so it can run on a tab switch without a backend round
        trip. Sequence tab (0): enabled only when the orch is stopped.
        Experiment/Action tabs (1, 2): enabled only when stopped AND the active
        sequence is a manual sequence. Action Servers tab (3): always disabled.
        """
        idx = self.queue_tabs.active
        stopped = self._loop_state == LoopStatus.stopped.value
        if idx == 0:
            disabled = not stopped
        elif idx in (1, 2):
            disabled = not stopped or not self._manual_seq
        else:
            disabled = True
        self._assign(self.button_queue_move_up, "disabled", disabled)
        self._assign(self.button_queue_move_down, "disabled", disabled)
        self._assign(self.button_queue_remove, "disabled", disabled)

    def callback_toggle_stepact(self, event):
        """Flip the step-through-actions toggle."""
        self.vis.doc.add_next_tick_callback(
            partial(self.update_stepwise_toggle, self.orch_stepact_button)
        )

    def callback_toggle_stepexp(self, event):
        """Flip the step-through-experiments toggle."""
        self.vis.doc.add_next_tick_callback(
            partial(self.update_stepwise_toggle, self.orch_stepexp_button)
        )

    def callback_toggle_stepseq(self, event):
        """Flip the step-through-sequences toggle."""
        self.vis.doc.add_next_tick_callback(
            partial(self.update_stepwise_toggle, self.orch_stepseq_button)
        )

    def callback_stop_orch(self, event):
        LOGGER.info("stopping operator orch")
        reset = 0 in self.reset_run_id_on_stop.active
        self.vis.doc.add_next_tick_callback(
            partial(self.backend.stop, reset_run_id=reset)
        )
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_skip_exp(self, event):
        LOGGER.info("skipping experiment")
        self.vis.doc.add_next_tick_callback(partial(self.backend.skip))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_clear_expplan(self, event):
        """Discard the staged plan buffer and refresh the tables."""
        LOGGER.info("clearing plan buffer")
        self.plan = []
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_clear_sequences(self, event):
        LOGGER.info("clearing sequences")
        self.vis.doc.add_next_tick_callback(partial(self.backend.clear_sequences))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_clear_experiments(self, event):
        LOGGER.info("clearing experiments")
        self.vis.doc.add_next_tick_callback(partial(self.backend.clear_experiments))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_clear_actions(self, event):
        LOGGER.info("clearing actions")
        self.vis.doc.add_next_tick_callback(partial(self.backend.clear_actions))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_prepend_seq(self, event):
        """Prepend the current sequence selection to the staged plan."""
        self.populate_sequence(prepend=True)
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_append_seq(self, event):
        """Append the current sequence selection to the staged plan."""
        self.populate_sequence(prepend=False)
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_prepend_exp(self, event):
        """Prepend the current experiment selection to the staged plan."""
        self.prepend_experiment()
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_append_exp(self, event):
        """Append the current experiment selection to the staged plan."""
        self.append_experiment()
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_update_tables(self, event):
        """Force a manual refresh of every queue/history table."""
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def append_experiment(self):
        """Wrap the current experiment selection as a manual sequence appended to the buffer."""
        experimentmodel = self.populate_experimentmodel()
        seq = Sequence(
            sequence_name="manual_orch_seq",
            planned_experiments=[experimentmodel],
            manual_action=True,
        )
        self._capture_metadata(seq)
        self.plan.append(seq)

    def prepend_experiment(self):
        """Wrap the current experiment selection as a manual sequence prepended to the buffer."""
        experimentmodel = self.populate_experimentmodel()
        seq = Sequence(
            sequence_name="manual_orch_seq",
            planned_experiments=[experimentmodel],
            manual_action=True,
        )
        self._capture_metadata(seq)
        self.plan.insert(0, seq)

    def write_params(self, ptype: str, name: str, pars: dict):
        """Persist the most recent sequence/experiment parameters, if enabled.

        The checkbox gate stays here because it reads a widget; the file is
        shared with the Reflex operator through ``param_store``.
        """
        if not (
            (ptype == "seq" and self.save_last_seq_pars.active == [0])
            or (ptype == "exp" and self.save_last_exp_pars.active == [0])
        ):
            return
        param_store.write_params(
            self.vis.world_cfg.get("root", ""),
            ptype,
            name,
            pars,
            meta={
                "sequence_label": self.input_sequence_label.value,
                "campaign_name": self.input_campaign_name.value,
                "campaign_uuid": self.input_campaign_uuid.value,
            },
        )

    def read_params(self, ptype: str, name: str) -> dict:
        """Return the most recently saved parameters for ``name`` of type ``ptype``."""
        return param_store.read_params(self.vis.world_cfg.get("root", ""), ptype, name)

    def read_last_meta(self) -> dict:
        """Return the saved global label/campaign block, or ``{}`` if none."""
        return param_store.read_last_meta(self.vis.world_cfg.get("root", ""))

    def populate_sequence(self, prepend: bool = False):
        """Unpack the selected sequence with current params and add it to the plan buffer."""
        selected_sequence = self.sequence_dropdown.value
        LOGGER.info(f"selected sequence from list: {selected_sequence}")

        sequence_params = {
            paraminput.name: (
                input_type(parse_bokeh_input(param_widget_value(paraminput)))
                if input_type in BUILTIN_TYPES
                else parse_bokeh_input(param_widget_value(paraminput))
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
        expplan_list = self.backend.unpack_sequence(
            sequence_name=selected_sequence, sequence_params=sequence_params
        )
        seq = Sequence(
            sequence_name=selected_sequence,
            sequence_params=sequence_params,
            planned_experiments=expplan_list,
        )
        self._capture_metadata(seq)
        if prepend:
            self.plan.insert(0, seq)
        else:
            self.plan.append(seq)

    def populate_experimentmodel(self) -> Experiment:
        """Build an ``Experiment`` from the experiment dropdown and current parameter inputs."""
        selected_experiment = self.experiment_dropdown.value
        LOGGER.info(f"selected experiment from list: {selected_experiment}")
        experiment_params = {
            paraminput.name: (
                input_type(parse_bokeh_input(param_widget_value(paraminput)))
                if input_type in BUILTIN_TYPES
                else parse_bokeh_input(param_widget_value(paraminput))
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
        return Experiment(
            experiment_name=selected_experiment, experiment_params=experiment_params
        )

    def refresh_inputs(self, param_input, private_input):
        """Re-fire ``solid_plate_id`` / ``solid_sample_no`` callbacks to refresh dependent widgets."""
        if self.dataAPI is None:
            # plate-map hook disabled (no 'plate_api' in server params), so the
            # plateid/sampleno callbacks were never registered on these inputs
            return
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
        """Assign ``value`` to ``sender`` (Bokeh next-tick safe setter).

        Routed through :func:`set_param_widget_value` because this is the setter
        every restore path uses — loading last-used parameters, and the
        spec-file hand-off — and any of those may land on a ``bool``
        parameter's radio group rather than on a text field.
        """
        if sender is not None:
            set_param_widget_value(sender, value)
        else:
            LOGGER.warning("tried to update value of nonexistant sender")

    def flip_stepwise_flag(self, sender_type):
        """Toggle the backend's step-through flag for actions/experiments/sequences."""
        new_val = not self.backend.get_step_flags()[sender_type]
        self.vis.doc.add_next_tick_callback(
            partial(self.backend.set_step_flag, sender_type, new_val)
        )

    def update_stepwise_toggle(self, sender):
        """Update a step-through button's label and colour after its flag flips."""
        sender_type = sender.label.split("[")[0].strip().split()[-1].strip()
        count_key = {
            "actions": "n_actions",
            "experiments": "n_experiments",
            "sequences": "n_sequences",
        }[sender_type]
        numq = self._queue_counts.get(count_key, 0)
        self.flip_stepwise_flag(sender_type)
        if sender.button_type == "danger":
            sender.label = f"RUN-THRU {sender_type} [{numq}]"
            sender.button_type = "success"
        else:
            sender.label = f"STEP-THRU {sender_type} [{numq}]"
            sender.button_type = "danger"

    def update_queuecount_labels(self):
        """Refresh the queue-size counters shown on the step-through buttons."""
        for sbutton, count_key in [
            (self.orch_stepseq_button, "n_sequences"),
            (self.orch_stepexp_button, "n_experiments"),
            (self.orch_stepact_button, "n_actions"),
        ]:
            numq = self._queue_counts.get(count_key, 0)
            self._assign(
                sbutton, "label", sbutton.label.split("[")[0].strip() + f" [{numq}]"
            )

    def update_seq_param_layout(self, idx):
        """Rebuild the sequence-parameter panel for entry ``idx`` of the sequence library."""
        self._update_param_layout("seq", idx)

    def update_exp_param_layout(self, idx):
        """Rebuild the experiment-parameter panel for entry ``idx`` of the experiment library."""
        self._update_param_layout("exp", idx)

    def update_seqspec_param_layout(self, idx):
        """Rebuild the spec-parameter panel for entry ``idx`` using the spec parser's schema."""
        args = []
        argtypes = []
        defaults = []
        seqspec_path = self.seqspecs[idx]
        try:
            seqfunc_params = self.seqspec_parser.list_params(seqspec_path, self.backend)
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
        arg_descs=None,
    ):
        """Generate Bokeh widgets for the given parameter ``args`` and append them to ``param_layout``.

        Each param row is split into two columns: the input field on the left
        (fixed width) and, on the right, the parsed ``Args:`` description for
        that field (from ``arg_descs``), shown persistently regardless of input
        focus.

        Special-cases plate-related parameters (``solid_plate_id``,
        ``solid_sample_no``, ``x_mm``/``y_mm``, custom positions, file
        upload) by attaching the appropriate callbacks and extra inputs.
        """
        arg_descs = arg_descs or {}
        item = 0

        for idx in range(len(args)):
            def_val = f"{defaults[idx]}"
            # if args[idx] == "experiment":
            #     continue
            # disabled = False

            type_hint = (
                str(argtypes[idx])
                .split()[-1]
                .strip(chr(39) + "<>]")
                .split(".")[-1]
                .replace("[", " of ")
            )
            # A plain ``bool`` renders as a two-way radio group rather than a
            # free-text field. Restricted to a default that is already one of
            # BOOL_LABELS: an ``Optional[bool]`` reads back as "Optional of
            # bool" here and never matches, but a bare ``bool`` annotation with
            # a ``None`` default would, and a radio group has no third position
            # to put it in — such a parameter keeps its text field, where
            # ``None`` still round-trips.
            is_bool = type_hint == "bool" and def_val in BOOL_LABELS
            # The parsed ``Args:`` description is the input's tooltip. A native
            # ``title`` attribute rather than Bokeh's ``description``: that
            # renders a "?" icon beside the widget's *title*, which is empty
            # here, and RadioButtonGroup does not accept it at all — it is an
            # InputWidget property, and a group is not an InputWidget. Hovering
            # the control itself is also the behaviour being asked for.
            # ``html_attributes`` is on UIElement, so one mechanism covers both
            # widget kinds. Omitted entirely when there is no description, so a
            # widget never carries an empty tooltip.
            arg_desc = arg_descs.get(args[idx], "")
            tooltip = {"title": arg_desc} if arg_desc else {}
            if is_bool:
                param_widget = RadioButtonGroup(
                    labels=list(BOOL_LABELS),
                    active=BOOL_LABELS.index(def_val),
                    name=args[idx],
                    disabled=args[idx].endswith("_version"),
                    height=31,
                    margin=(0, 5, 0, 5),
                    sizing_mode="stretch_width",
                    html_attributes=tooltip,
                )
            else:
                initial_stylesheet = [color_rule(".bk-input", BODY_TEXT)]
                param_widget = TextInput(
                    value=def_val,
                    title="",
                    name=args[idx],
                    disabled=True if args[idx].endswith("_version") else False,
                    height=31,
                    margin=(0, 5, 0, 5),
                    sizing_mode="stretch_width",
                    stylesheets=initial_stylesheet,
                    html_attributes=tooltip,
                )
                if args[idx] not in self.skip_default_highlights:
                    # Both rules are built in Python and the JS only picks
                    # between them, so no CSS is assembled in the browser and
                    # neither declaration appears as a literal at this call
                    # site. A radio group needs no equivalent: which position is
                    # selected is the whole widget, so a changed value is
                    # already visible without recolouring anything.
                    default_rule = color_rule(".bk-input", BODY_TEXT, important=True)
                    modified_rule = color_rule(
                        ".bk-input", MODIFIED_PARAM_TEXT, important=True
                    )
                    color_callback_js = CustomJS(
                        args=dict(input=param_widget),
                        code=f"""
cb_obj.stylesheets = [
    cb_obj.value_input === '{def_val}' ? `{default_rule}` : `{modified_rule}`
]
""",
                    )
                    param_widget.js_on_change("value", color_callback_js)
                    param_widget.js_on_change("value_input", color_callback_js)
            param_input.append(param_widget)
            argtype_list.append(argtypes[idx])
            idx_col_w = 35
            # The label row is name … type. The description is no longer in it —
            # it is the input's tooltip — so the name takes the slack and the
            # row is a fixed one line high again, which is what lets paired
            # cells stay the same height without a description forcing a wrap.
            name_div = Div(
                text=f"{args[idx]}",
                sizing_mode="stretch_width",
                height=14,
                margin=(0, 5, 0, 5),
            )
            # Right-aligned, and last in the row, so the annotation lands on the
            # cell's right edge.
            type_div = Div(
                text=f"<i>[{type_hint}]</i>",
                width=140,
                height=14,
                margin=(0, 5, 0, 5),
                styles={"text-align": "right"},
            )
            index_div = Div(
                text=f"[{idx}]",
                width=idx_col_w,
                height=param_widget.height,
                margin=(0, 5, 0, 5),
                styles={
                    "text-align": "right",
                    "line-height": f"{param_widget.height}px",
                },
            )
            # Named rather than inlined so a special-cased parameter can put a
            # widget beside its input — see `plate_sample_no_list` below — without
            # reaching into `input_col.children` by index.
            input_row = row(
                index_div,
                param_input[item],
                spacing=0,
                sizing_mode="stretch_width",
            )
            input_col = column(
                row(
                    Spacer(width=idx_col_w),
                    name_div,
                    type_div,
                    spacing=0,
                    sizing_mode="stretch_width",
                ),
                input_row,
                spacing=5,
                sizing_mode="stretch_width",
            )
            param_layout.append(
                self._param_cell(
                    [
                        input_col,
                        Spacer(height=10),
                    ]
                )
            )
            item = item + 1

            # special key params
            if self.dataAPI is not None and args[idx] == "solid_plate_id":
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
                    self._param_extra_block(
                        [
                            [private_input[-1]],
                            Spacer(height=10),
                        ]
                    )
                )

                private_input.append(
                    TextInput(
                        value="",
                        title="elements",
                        name="elements",
                        disabled=True,
                        width=120,
                        height=40,
                    )
                )
                private_input.append(
                    TextInput(
                        value="",
                        title="code",
                        name="code",
                        disabled=True,
                        width=60,
                        height=40,
                    )
                )
                private_input.append(
                    TextInput(
                        value="",
                        title="composition",
                        name="composition",
                        disabled=True,
                        width=220,
                        height=40,
                    )
                )
                param_layout.append(
                    self._param_extra_block(
                        [
                            [private_input[-3], private_input[-2], private_input[-1]],
                            Spacer(height=10),
                        ]
                    )
                )

            elif self.dataAPI is not None and args[idx] == "solid_sample_no":
                param_input[-1].on_change(
                    "value",
                    partial(self.callback_changed_sampleno, sender=param_input[-1]),
                )

            elif self.dataAPI is not None and args[idx] == "x_mm":
                param_input[-1].disabled = True

            elif self.dataAPI is not None and args[idx] == "y_mm":
                param_input[-1].disabled = True

            elif args[idx] == "solid_custom_position":
                param_input[-1] = Select(
                    title=args[idx],
                    value=None,
                    options=self.dev_customitems,
                    name=args[idx],
                )
                if self.dev_customitems:
                    if def_val in self.dev_customitems:
                        param_input[-1].value = def_val
                    else:
                        param_input[-1].value = self.dev_customitems[0]
                # Substituted for the text cell, and stays a grid cell: the
                # selector is no wider than the input it replaces, so dropping
                # it out of the two-column flow would leave a full-width row in
                # the middle of the form.
                param_layout[-1] = self._param_cell(
                    [
                        [param_input[-1]],
                        Spacer(height=10),
                    ]
                )

            elif args[idx] == "liquid_custom_position":
                param_input[-1] = Select(
                    title=args[idx],
                    value=None,
                    options=self.dev_customitems,
                    name=args[idx],
                )
                if self.dev_customitems:
                    if def_val in self.dev_customitems:
                        param_input[-1].value = def_val
                    else:
                        param_input[-1].value = self.dev_customitems[0]
                # Substituted for the text cell, and stays a grid cell: the
                # selector is no wider than the input it replaces, so dropping
                # it out of the two-column flow would leave a full-width row in
                # the middle of the form.
                param_layout[-1] = self._param_cell(
                    [
                        [param_input[-1]],
                        Spacer(height=10),
                    ]
                )

            elif self.dataAPI is not None and args[idx] == "plate_sample_no_list":
                # Sizing and label come from the stylesheet, not from `width=`:
                # the widget renders a native file input, so a Python width
                # sets the host box while the control inside keeps its own.
                private_input.append(
                    FileInput(
                        accept=".txt",
                        # Matches the text input it sits beside. Bokeh's default
                        # widget margin has a 5px top, which would drop the
                        # button that far below the field's top edge.
                        margin=(0, 5, 0, 5),
                        stylesheets=[file_load_button_stylesheet()],
                    )
                )
                # Into this parameter's own input row, immediately right of the
                # text input it fills. `input_col` is already the cell's child,
                # so appending here places the button without rebuilding the
                # cell.
                #
                # It was previously a full-width block appended as its own
                # entry, which read correctly while the form was one column
                # wide; under the two-column grid that block took the next slot
                # and drew beneath the *previous* parameter instead.
                input_row.children.append(private_input[-1])
                private_input[-1].on_change(
                    "value",
                    partial(
                        self.callback_plate_sample_no_list_file,
                        sender=private_input[-1],
                        inputfield=param_input[-1],
                    ),
                )

    # Shared with the Reflex operator; see object_tree.
    _doc_to_html = staticmethod(doc_to_html)

    def update_seq_doc(self, value):
        """Render the selected sequence's docstring into the sequence description widget."""
        self.sequence_descr_txt.text = self._doc_to_html(value)

    def update_exp_doc(self, value):
        """Render the selected experiment's docstring into the experiment description widget."""
        self.experiment_descr_txt.text = self._doc_to_html(value)

    def update_seqspec_doc(self, value):
        """Show the parser path and spec file path in the seqspec description widget."""
        fp = value.replace("\n", "<br>")
        self.seqspec_descr_txt.text = f"Enqueue a sequence using parser:<br>{self.parser_path}<br><br>on specification file:<br>{fp}"

    def update_error(self, value):
        """Set the error banner text."""
        self.error_txt.text = value

    def update_xysamples(self, xval, yval, sender):
        """Write ``xval``/``yval`` into the ``x_mm``/``y_mm`` inputs associated with ``sender``."""
        private_input, param_input = self.find_param_private_input(sender)
        if private_input is None or param_input is None:
            return False

        for paraminput in param_input:
            if paraminput.name == "x_mm":
                paraminput.value = xval
            if paraminput.name == "y_mm":
                paraminput.value = yval

    def update_pm_plot(self, plot_mpmap, pmdata):
        """Re-render the plate map markers on ``plot_mpmap`` from ``pmdata``."""
        x = [col["x"] for col in pmdata]
        y = [col["y"] for col in pmdata]
        # remove old Pmplot
        old_point = plot_mpmap.select(name="PMplot")
        if len(old_point) > 0:
            plot_mpmap.renderers.remove(old_point[0])
        plot_mpmap.square(
            x, y, size=5, color=None, alpha=0.5, line_color=BODY_TEXT, name="PMplot"
        )

    def get_pm(self, plateid: int, sender):
        """Look up the plate map for ``plateid`` and trigger a plate-map redraw."""
        if self.dataAPI is None:
            return False

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
        """Return the index of the entry in ``pmapxy`` closest to ``xy``, or ``None`` if empty."""
        if len(pmapxy):
            diff = pmapxy - xy
            sumdiff = (diff**2).sum(axis=1)
            return int(np.argmin(sumdiff))
        else:
            return None

    def get_samples(self, X, Y, sender):
        """Return the indices of plate-map entries closest to each ``(X[i], Y[i])`` pair."""
        # X and Y are vectors
        if self.dataAPI is None:
            return [None]

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
        """Populate the ``elements`` widget with the element list for ``plateid``."""
        if self.dataAPI is None:
            return False

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
        """Return the Bokeh ``figure`` in ``inputs`` whose title equals ``name``, or ``None``."""
        for inp in inputs:
            if isinstance(inp, figure):
                if inp.title.text == name:
                    return inp
        return None

    def find_input(self, inputs, name):
        """Return the ``TextInput`` in ``inputs`` whose ``name`` equals ``name``, or ``None``."""
        for inp in inputs:
            if isinstance(inp, TextInput):
                if inp.name == name:
                    return inp
        return None

    def find_param_private_input(self, sender):
        """Return the ``(private_input, param_input)`` lists that contain ``sender``, or ``(None, None)``."""
        private_input = None
        param_input = None

        if sender in self.exp_param_input or sender in self.exp_private_input:
            private_input = self.exp_private_input
            param_input = self.exp_param_input

        elif sender in self.seq_param_input or sender in self.seq_private_input:
            private_input = self.seq_private_input
            param_input = self.seq_param_input

        return private_input, param_input

    def get_sample_infos(self, PMnum: Optional[list] = None, sender=None):
        """Update sample-related widgets and the highlighted marker on the plate map for ``PMnum``."""
        if self.dataAPI is None:
            return False

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
                        line_color=SELECTED_MARKER_OUTLINE,
                        name="selsample",
                    )

                    return True
            else:
                return False

        return False

    async def add_experiment_to_sequence(self):
        """Placeholder hook for future experiment-to-sequence integration."""
        pass

    @staticmethod
    def _assign(model, attr, value):
        """Set ``model.attr`` only when the value actually changed.

        The operator refreshes on a 5 s poll (and on every status-WS message).
        Re-assigning a Bokeh model property to an identical value still emits a
        document patch to the browser, which triggers a layout reflow and blurs
        whatever input the user is currently typing into. Skipping no-op writes
        keeps an idle/stopped UI from pushing any patch, so focus is preserved.
        Returns True if a write happened.
        """
        if getattr(model, attr) != value:
            setattr(model, attr, value)
            return True
        return False

    async def update_tables(self):
        """Refresh every queue/history table and update the orchestrator status banner/buttons."""
        start_time = time.time()
        await self.get_sequences()
        await self.get_experiments()
        await self.get_actions()
        await self.get_history()
        await self.get_orch_status_summary()
        for key in self.experiment_plan_lists:
            self.experiment_plan_lists[key] = []
        for seq in self.plan:
            self.experiment_plan_lists["sequence_name"].append(seq.sequence_name)
            self.experiment_plan_lists["sequence_label"].append(seq.sequence_label)
            self.experiment_plan_lists["num_experiments"].append(
                len(seq.planned_experiments)
            )
        self._assign(self.experiment_plan_source, "data", self.experiment_plan_lists)

        state = await self.backend.get_orch_state()
        self._queue_counts = {
            "n_sequences": state.get("n_sequences", 0),
            "n_experiments": state.get("n_experiments", 0),
            "n_actions": state.get("n_actions", 0),
        }
        # Refresh the step-button counters AFTER _queue_counts is updated from the
        # current orch state, so the labels reflect this poll (not the previous
        # one) and don't flip a poll late.
        self.update_queuecount_labels()
        loop_state = state.get("loop_state")
        loop_state = getattr(loop_state, "value", loop_state)  # normalize enum->str
        self._current_stop_message = state.get("current_stop_message", "") or ""
        aseq = (state.get("active_sequence") or {}).get("sequence_name")
        aexp = (state.get("active_experiment") or {}).get("experiment_name")
        if loop_state == LoopStatus.started.value:
            if aseq is not None and aexp is not None:
                status_label = f"running {aseq} / {aexp}"
            else:
                status_label = "running"
            status_type = "success"
        elif loop_state == LoopStatus.stopped.value:
            stop_msg = (
                f": {self._current_stop_message}" if self._current_stop_message else ""
            )
            status_label = f"stopped{stop_msg}"
            status_type = "warning" if stop_msg else "primary"
        else:
            status_label = f"{loop_state}"
            status_type = "danger"
        self._assign(self.orch_status_button, "label", status_label)
        self._assign(self.orch_status_button, "button_type", status_type)
        queue_disabled = loop_state != LoopStatus.stopped.value
        self._assign(self.button_prepend_plan, "disabled", queue_disabled)
        # Cache the state the unified queue buttons gate on, then refresh them.
        # _refresh_queue_button_state also runs on tab switch (queue_tabs
        # on_change) so the single button set matches whichever queue is shown.
        self._loop_state = loop_state
        self._manual_seq = bool(
            (state.get("active_sequence") or {}).get("manual_action")
        )
        self._refresh_queue_button_state()
        self._assign(self.button_add_expplan, "label", f"Add plan [{len(self.plan)}]")
        end_time = time.time()
        LOGGER.debug(f"Updating tables took {end_time - start_time} seconds")

    # ------------------------------------------------------------------
    # Tree-view helpers — render an object as a <details> tree beside the
    # active planhistory or queue tab when the user selects a row.
    # ------------------------------------------------------------------

    _open_keys = staticmethod(open_keys_for)

    def _set_tree(self, header_div, tree_div, header_text, obj, open_keys):
        header_div.text = f"<b>{header_text}</b>" if header_text.strip() else "<b>—</b>"
        tree_div.text = _object_to_html(obj, open_keys=open_keys)

    def _clear_tree(self, header_div, tree_div):
        header_div.text = "<b>select a row</b>"
        tree_div.text = ""

    def _render_planhistory_tree(self):
        """Render the tree beside the non-queued (plan/history) tabs."""
        active = self.planhistory_tabs.active
        if active == 0:  # Plan
            src, kind, getter = (
                self.experiment_plan_source,
                "sequence",
                lambda i: self.plan[i].as_dict(),
            )
        elif active == 1:  # Action History
            src, kind, getter = (
                self.action_history_source,
                "action",
                lambda i: self._hist_objs["action"][i],
            )
        elif active == 2:  # Experiment History
            src, kind, getter = (
                self.experiment_history_source,
                "experiment",
                lambda i: self._hist_objs["experiment"][i],
            )
        else:  # Sequence History
            src, kind, getter = (
                self.sequence_history_source,
                "sequence",
                lambda i: self._hist_objs["sequence"][i],
            )
        idxs = src.selected.indices
        if not idxs:
            self._clear_tree(self.planhistory_tree_header, self.planhistory_tree_div)
            return
        try:
            obj = getter(idxs[0])
        except (IndexError, KeyError, AttributeError):
            LOGGER.exception("planhistory tree render failed")
            self._clear_tree(self.planhistory_tree_header, self.planhistory_tree_div)
            return
        self._set_tree(
            self.planhistory_tree_header,
            self.planhistory_tree_div,
            _tree_header_text(kind, obj),
            obj,
            self._open_keys(obj),
        )

    def _render_queue_tree(self):
        """Render the tree beside the queue tabs."""
        active = self.queue_tabs.active
        if active == 3:  # Action Servers -> config dict (local)
            idxs = self.action_server_source.selected.indices
            if not idxs:
                self._clear_tree(self.queue_tree_header, self.queue_tree_div)
                return
            names = self.action_server_source.data.get("action_server", [])
            try:
                name = names[idxs[0]]
            except IndexError:
                self._clear_tree(self.queue_tree_header, self.queue_tree_div)
                return
            cfg = self.vis.world_cfg["servers"].get(name, {})
            self._set_tree(
                self.queue_tree_header,
                self.queue_tree_div,
                _server_header_text(name, cfg),
                cfg,
                ["params"],
            )
            return
        kind = {0: "sequence", 1: "experiment", 2: "action"}[active]
        src = {
            0: self.sequence_source,
            1: self.experiment_source,
            2: self.action_source,
        }[active]
        idxs = src.selected.indices
        if not idxs:
            self._clear_tree(self.queue_tree_header, self.queue_tree_div)
            return
        # Rapid row clicks race; last fetch to complete wins. Acceptable for a single-operator UI.
        self.vis.doc.add_next_tick_callback(
            partial(self._async_render_queue_obj, kind, idxs[0])
        )

    async def _async_render_queue_obj(self, kind, idx):
        obj = await self.backend.get_queue_object(kind, idx)
        if not obj:
            LOGGER.debug("queue object %s[%s] empty; clearing tree", kind, idx)
            self._clear_tree(self.queue_tree_header, self.queue_tree_div)
            return
        self._set_tree(
            self.queue_tree_header,
            self.queue_tree_div,
            _tree_header_text(kind, obj),
            obj,
            self._open_keys(obj),
        )

    def _restore_last_meta(self):
        """Schedule label/campaign fields to be filled from the saved global meta block.

        Both the primary and mirror widgets are updated together so the mirror
        callbacks do not race and overwrite the restored values.
        """
        meta = self.read_last_meta()
        # Each entry is (primary_widget, mirror_widget) so both sides are set
        # atomically (via next-tick) before their mutual mirror callbacks fire.
        field_pairs = [
            ("sequence_label", self.input_sequence_label, self.input_sequence_label2),
            ("campaign_name", self.input_campaign_name, self.input_campaign_name2),
            ("campaign_uuid", self.input_campaign_uuid, self.input_campaign_uuid2),
        ]
        for key, primary, mirror in field_pairs:
            if key in meta and meta[key] is not None:
                val = str(meta[key])
                self.vis.doc.add_next_tick_callback(
                    partial(self.update_input_value, primary, val)
                )
                self.vis.doc.add_next_tick_callback(
                    partial(self.update_input_value, mirror, val)
                )

    def get_last_seq_pars(self):
        """Pre-fill the sequence parameter inputs and label/campaign from saved values."""
        loaded_pars = self.read_params("seq", self.sequence_dropdown.value)
        for k, v in loaded_pars.items():
            seq_input = self.find_input(self.seq_param_input, k)
            self.vis.doc.add_next_tick_callback(
                partial(self.update_input_value, seq_input, str(v))
            )
        self._restore_last_meta()

    def get_last_exp_pars(self):
        """Pre-fill the experiment parameter inputs and label/campaign from saved values."""
        loaded_pars = self.read_params("exp", self.experiment_dropdown.value)
        for k, v in loaded_pars.items():
            exp_input = self.find_input(self.exp_param_input, k)
            self.vis.doc.add_next_tick_callback(
                partial(self.update_input_value, exp_input, str(v))
            )
        self._restore_last_meta()
