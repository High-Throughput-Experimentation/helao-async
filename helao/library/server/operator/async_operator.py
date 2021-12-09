
__all__ = ["makeBokehApp"]

import json
from functools import partial
from importlib import import_module
from socket import gethostname
import numpy as np
import inspect
from pydantic import BaseModel
from typing import List

from bokeh.layouts import column
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource
from bokeh.models import DataTable, TableColumn
from bokeh.models.widgets import Paragraph
from bokeh.models import Select
from bokeh.models import Button, TextInput
import bokeh.models.widgets as bmw
import bokeh.plotting as bpl
from bokeh.events import ButtonClick, DoubleTap

import helaocore.server as hcs
from helaocore.data import HTELegacyAPI
from helaocore.schema import Process, Sequence
from helaocore.helper import to_json


class return_sequence_lib(BaseModel):
    """Return class for queried sequence objects."""
    index: int
    sequence_name: str
    doc: str
    args: list
    defaults: list


class return_process_lib(BaseModel):
    """Return class for queried process objects."""
    index: int
    process_name: str
    doc: str
    args: list
    defaults: list


class C_async_operator:
    def __init__(self, visServ: hcs.Vis):
        self.vis = visServ

        self.dataAPI = HTELegacyAPI(self.vis)

        self.config_dict = self.vis.server_cfg["params"]
        self.orch_name = self.config_dict["orch"]
        self.pal_name = self.config_dict.get("pal", None)
        self.dev_customitems = []
        if self.pal_name is not None:
            pal_server_params = self.vis.world_cfg["servers"][self.pal_name]["params"]
            if "positions" in pal_server_params:
                dev_custom = pal_server_params["positions"].get("custom",dict())
            else:
                dev_custom = dict()
            self.dev_customitems = [key for key in dev_custom.keys()]

        self.color_sq_param_inputs = "#BDB76B"

        # holds the page layout
        self.layout = []
        self.seq_param_layout = []
        self.seq_param_input = []
        self.seq_private_input = []
        self.prc_param_layout = []
        self.prc_param_input = []
        self.prc_private_input = []

        self.sequence = None
        self.sequence_list = dict()
        self.process_list = dict()
        self.action_list = dict()
        self.active_action_list = dict()

        self.sequence_select_list = []
        self.sequences = []
        self.sequence_lib = hcs.import_sequences(world_config_dict = self.vis.world_cfg, sequence_path = None, server_name=self.vis.server_name)

        self.process_select_list = []
        self.processes = []
        self.process_lib = hcs.import_processes(world_config_dict = self.vis.world_cfg, process_path = None, server_name=self.vis.server_name)

        # FastAPI calls
        self.get_sequence_lib()
        self.get_process_lib()
        self.vis.doc.add_next_tick_callback(partial(self.get_processes))
        self.vis.doc.add_next_tick_callback(partial(self.get_actions))
        self.vis.doc.add_next_tick_callback(partial(self.get_active_actions))

        self.sequence_source = ColumnDataSource(data=self.sequence_list)
        self.columns_seq = [TableColumn(field=key, title=key) for key in self.sequence_list]
        self.sequence_table = DataTable(
                                        source=self.sequence_source, 
                                        columns=self.columns_seq, 
                                        width=620, 
                                        height=200,
                                        autosize_mode = "fit_columns"
                                        )

        self.process_source = ColumnDataSource(data=self.process_list)
        self.columns_prc = [TableColumn(field=key, title=key) for key in self.process_list]
        self.process_table = DataTable(
                                       source=self.process_source, 
                                       columns=self.columns_prc, 
                                       width=620, 
                                       height=200,
                                       autosize_mode = "fit_columns"
                                      )

        self.action_source = ColumnDataSource(data=self.action_list)
        self.columns_act = [TableColumn(field=key, title=key) for key in self.action_list]
        self.action_table = DataTable(
                                      source=self.action_source, 
                                      columns=self.columns_act, 
                                      width=620, 
                                      height=200,
                                      autosize_mode = "fit_columns"
                                     )

        self.active_action_source = ColumnDataSource(data=self.active_action_list)
        self.columns_active_action = [TableColumn(field=key, title=key) for key in self.active_action_list]
        self.active_action_table = DataTable(
                                             source=self.active_action_source, 
                                             columns=self.columns_active_action, 
                                             width=620, 
                                             height=200,
                                             autosize_mode = "fit_columns"
                                            )

        self.sequence_dropdown = Select(
                                        title="Select sequence:",
                                        value = None,
                                        options=self.sequence_select_list,
                                       )
        self.sequence_dropdown.on_change("value", self.callback_sequence_select)

        self.process_dropdown = Select(
                                       title="Select process:",
                                       value = None,
                                       options=self.process_select_list
                                      )
        self.process_dropdown.on_change("value", self.callback_process_select)


        # buttons to control orch
        self.button_start = Button(label="Start Orch", button_type="default", width=70)
        self.button_start.on_event(ButtonClick, self.callback_start)
        self.button_stop = Button(label="Stop Orch", button_type="default", width=70)
        self.button_stop.on_event(ButtonClick, self.callback_stop)
        self.button_skip = Button(label="Skip prc", button_type="danger", width=70)
        self.button_skip.on_event(ButtonClick, self.callback_skip_dec)
        self.button_update = Button(label="update tables", button_type="default", width=120)
        self.button_update.on_event(ButtonClick, self.callback_update_tables)
        self.button_clear_seqg = Button(label="clear seqg", button_type="default", width=70)
        self.button_clear_seqg.on_event(ButtonClick, self.callback_clear_seqg)

        self.button_clear_prg = Button(label="clear prc", button_type="danger", width=100)
        self.button_clear_prg.on_event(ButtonClick, self.callback_clear_processes)
        self.button_clear_action = Button(label="clear act", button_type="danger", width=100)
        self.button_clear_action.on_event(ButtonClick, self.callback_clear_actions)

        self.button_prepend_prc = Button(label="prepend prc", button_type="default", width=150)
        self.button_prepend_prc.on_event(ButtonClick, self.callback_prepend_prc)
        self.button_append_prc = Button(label="append prc", button_type="default", width=150)
        self.button_append_prc.on_event(ButtonClick, self.callback_append_prc)

        self.button_prepend_seqg = Button(label="prepend seqg", button_type="default", width=150)
        self.button_prepend_seqg.on_event(ButtonClick, self.callback_prepend_seqg)
        self.button_append_seqg = Button(label="append seqg", button_type="default", width=150)
        self.button_append_seqg.on_event(ButtonClick, self.callback_append_seqg)


        self.sequence_descr_txt = bmw.Div(text="""select a sequence item""", width=600)
        self.process_descr_txt = bmw.Div(text="""select a process item""", width=600)
        self.error_txt = Paragraph(text="""no error""", width=600, height=30, style={"font-size": "100%", "color": "black"})

        self.input_sequence_label = TextInput(value="nolabel", title="sequence label", disabled=False, width=120, height=40)

        self.layout0 = layout([
            layout(
                [Spacer(width=20), bmw.Div(text=f"<b>{self.config_dict.get('doc_name', 'Operator')} on {gethostname()}</b>", width=620, height=32, style={"font-size": "200%", "color": "red"})],
                background="#C0C0C0",width=640),
            Spacer(height=10),
            layout(
                [Spacer(width=20), bmw.Div(text="<b>Sequences:</b>", width=620, height=32, style={"font-size": "150%", "color": "red"})],
                background="#C0C0C0",width=640),
            layout([
                [self.sequence_dropdown],
                [Spacer(width=10), bmw.Div(text="<b>sequence description:</b>", width=200+50, height=15)],
                [self.sequence_descr_txt],
                Spacer(height=10),
                ],background="#808080",width=640),
            layout([
                [self.button_append_seqg, self.button_prepend_seqg],
                ],background="#808080",width=640)
            ])

        self.layout2 = layout([
            Spacer(height=10),
            layout(
                [Spacer(width=20), bmw.Div(text="<b>Processes:</b>", width=620, height=32, style={"font-size": "150%", "color": "red"})],
                background="#C0C0C0",width=640),
            Spacer(height=10),
            layout([
                [self.process_dropdown],
                [Spacer(width=10), bmw.Div(text="<b>process description:</b>", width=200+50, height=15)],
                [self.process_descr_txt],
                Spacer(height=20),
                ],background="#808080",width=640),
                layout([
                    [self.button_append_prc, self.button_prepend_prc],
                ],background="#808080",width=640)
            ])


        self.layout4 = layout([
                Spacer(height=10),
                layout(
                    [Spacer(width=20), bmw.Div(text="<b>Orch:</b>", width=620, height=32, style={"font-size": "150%", "color": "red"})],
                    background="#C0C0C0",width=640),
                layout([
                    [self.input_sequence_label, self.button_start, Spacer(width=10), self.button_stop,  Spacer(width=10), self.button_clear_seqg],
                    Spacer(height=10),
                    [Spacer(width=10), bmw.Div(text="<b>Error message:</b>", width=200+50, height=15, style={"font-size": "100%", "color": "black"})],
                    [Spacer(width=10), self.error_txt],
                    Spacer(height=10),
                    ],background="#808080",width=640),
                layout([
                [Spacer(width=20), bmw.Div(text="<b>Process Group content:</b>", width=200+50, height=15)],
                [self.sequence_table],
                [Spacer(width=20), bmw.Div(text="<b>queued processes:</b>", width=200+50, height=15)],
                [self.process_table],
                [Spacer(width=20), bmw.Div(text="<b>queued actions:</b>", width=200+50, height=15)],
                [self.action_table],
                [Spacer(width=20), bmw.Div(text="<b>Active actions:</b>", width=200+50, height=15)],
                [self.active_action_table],
                Spacer(height=10),
                [self.button_skip, Spacer(width=5), self.button_clear_prg, Spacer(width=5), self.button_clear_action, self.button_update],
                Spacer(height=10),
                ],background="#7fdbff",width=640),
            ])


        self.dynamic_col = column(
                                  self.layout0, 
                                  layout(), # placeholder
                                  self.layout2, 
                                  layout(),  # placeholder
                                  self.layout4
                                  )
        self.vis.doc.add_root(self.dynamic_col)


        # select the first item to force an update of the layout
        if self.process_select_list:
            self.process_dropdown.value = self.process_select_list[0]

        if self.sequence_select_list:
            self.sequence_dropdown.value = self.sequence_select_list[0]


    def get_sequence_lib(self):
        """Return the current list of sequences."""
        self.sequences = []
        self.vis.print_message(f"found sequences: {[sequence for sequence in self.sequence_lib]}")
        for i, sequence in enumerate(self.sequence_lib):
            tmpdoc = self.sequence_lib[sequence].__doc__ 
            if tmpdoc == None:
                tmpdoc = ""
            tmpargs = inspect.getfullargspec(self.sequence_lib[sequence]).args
            tmpdef = inspect.getfullargspec(self.sequence_lib[sequence]).defaults
            if tmpdef == None:
                tmpdef = []
            
            
            self.sequences.append(return_sequence_lib(
                index=i,
                sequence_name = sequence,
                doc = tmpdoc,
                args = tmpargs,
                defaults = tmpdef,
                ).dict()
            )
        for item in self.sequences:
            self.sequence_select_list.append(item["sequence_name"])


    def get_process_lib(self):
        """Return the current list of processes."""
        self.processes = []
        self.vis.print_message(f"found process: {[process for process in self.process_lib]}")
        for i, process in enumerate(self.process_lib):
            tmpdoc = self.process_lib[process].__doc__ 
            if tmpdoc == None:
                tmpdoc = ""
            tmpargs = inspect.getfullargspec(self.process_lib[process]).args
            tmpdef = inspect.getfullargspec(self.process_lib[process]).defaults
            if tmpdef == None:
                tmpdef = []
            
            self.processes.append(return_process_lib(
                index=i,
                process_name = process,
                doc = tmpdoc,
                args = tmpargs,
                defaults = tmpdef,
               ).dict()
            )
        for item in self.processes:
            self.process_select_list.append(item["process_name"])


    async def get_processes(self):
        """get process list from orch"""
        response = await self.do_orch_request(action_name = "list_processes")
        self.process_list = dict()
        if len(response):
            for key in response[0]:
                self.process_list[key] = []
            for line in response:
                for key, value in line.items():
                    self.process_list[key].append(value)
        self.vis.print_message(f"current queued processes: {self.process_list}")


    async def get_actions(self):
        """get action list from orch"""
        response = await self.do_orch_request(action_name = "list_actions")
        self.action_list = dict()
        if len(response):
            for key in response[0]:
                self.action_list[key] = []
            for line in response:
                for key, value in line.items():
                    self.action_list[key].append(value)
        self.vis.print_message(f"current queued actions: {self.action_list}")


    async def get_active_actions(self):
        """get action list from orch"""
        response = await self.do_orch_request(action_name = "list_active_actions")
        self.active_action_list = dict()
        if len(response):
            for key in response[0]:
                self.active_action_list[key] = []
            for line in response:
                for key, value in line.items():
                    self.active_action_list[key].append(value)
        self.vis.print_message(f"current active actions: {self.active_action_list}")


    async def do_orch_request(self,action_name, 
                              params_dict: dict = {},
                              json_dict: dict = {}
                              ):
        """submit a FastAPI request to orch"""
    

        response = await hcs.async_private_dispatcher(
            world_config_dict = self.vis.world_cfg, 
            server = self.orch_name,
            private_action = action_name,
            params_dict = params_dict,
            json_dict = json_dict
            )
            
        return response

    def callback_sequence_select(self, attr, old, new):
        idx = self.sequence_select_list.index(new)
        self.update_seq_param_layout(idx)
        self.vis.doc.add_next_tick_callback(
            partial(self.update_seq_doc,self.sequences[idx]["doc"])
        )


    def callback_process_select(self, attr, old, new):
        idx = self.process_select_list.index(new)
        self.update_prc_param_layout(idx)
        self.vis.doc.add_next_tick_callback(
            partial(self.update_prc_doc,self.processes[idx]["doc"])
        )


    def callback_clicked_pmplot(self, event, sender):
        """double click/tap on PM plot to add/move marker"""
        self.vis.print_message(f"DOUBLE TAP PMplot: {event.x}, {event.y}")
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
                self.vis.doc.add_next_tick_callback(partial(
                                                            self.callback_changed_sampleno,
                                                            attr = "value",
                                                            old = input_sample_no.value,
                                                            new = "1",
                                                            sender=input_sample_no
                                                           ))

        else:
            self.vis.doc.add_next_tick_callback(partial(self.update_input_value,sender,""))


    def callback_changed_sampleno(self, attr, old, new, sender):
        """callback for sampleno text input"""
        def to_int(val):
            try:
                return int(val)
            except ValueError:
                return None

        sample_no = to_int(new)
        if sample_no is not None:
            self.get_sample_infos([sample_no-1], sender)
        else:
            self.vis.doc.add_next_tick_callback(partial(self.update_input_value,sender,""))


    def callback_start(self, event):
        if self.sequence is not None:
            sellabel = self.input_sequence_label.value
            self.sequence.sequence_label = sellabel
            self.vis.print_message("starting orch")
            params_dict, json_dict =  self.sequence.fastdict()
            self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"append_sequence", params_dict, json_dict))
            self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"start"))
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))
        else:
            self.vis.print_message("Cannot start orch. Sequence is empty.")


    def callback_stop(self, event):
        self.vis.print_message("stopping operator orch")
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"stop"))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_skip_dec(self, event):
        self.vis.print_message("skipping process")
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"skip"))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_clear_seqg(self, event):
        self.vis.print_message("clearing seqg table")
        self.sequence = None
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_clear_processes(self, event):
        self.vis.print_message("clearing processes")
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"clear_processes"))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_clear_actions(self, event):
        self.vis.print_message("clearing actions")
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"clear_actions"))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_prepend_seqg(self, event):
        sequence = self.populate_sequence()
        for i, D in enumerate(sequence.process_list):
            self.sequence.process_list.insert(i,D)
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_append_seqg(self, event):
        sequence = self.populate_sequence()
        for D in sequence.process_list:
            self.sequence.process_list.append(D)
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))        


    def callback_prepend_prc(self, event):
        self.prepend_process()
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_append_prc(self, event):
        self.append_process()
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_update_tables(self, event):
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def append_process(self):
        D = self.populate_process()
        self.sequence.process_list.append(D)


    def prepend_process(self):
        D = self.populate_process()
        self.sequence.process_list.insert(0,D)


    def unpack_sequence(self, sequence_name, sequence_params):
        if sequence_name in self.sequence_lib:
            return self.sequence_lib[sequence_name](**sequence_params)
        else:
            return []


    def populate_sequence(self):
        selected_sequence = self.sequence_dropdown.value
        self.vis.print_message(f"selected sequence from list: {selected_sequence}")

        sequence_params = {paraminput.title: to_json(paraminput.value) for paraminput in self.seq_param_input}
        prc_list = self.unpack_sequence(
                        sequence_name = selected_sequence,
                        sequence_params = sequence_params
                       )

        sequence = Sequence()
        sequence.sequence_name = selected_sequence
        sequence.sequence_label = self.input_sequence_label.value
        sequence.sequence_params = sequence_params
        for prc in prc_list:
            D = Process(inputdict=prc)
            sequence.process_list.append(D)

        if self.sequence is None:
            self.sequence = Sequence()
        self.sequence.sequence_name = sequence.sequence_name
        self.sequence.sequence_label = sequence.sequence_label
        self.sequence.sequence_params = sequence.sequence_params

        return sequence


    def populate_process(self):
        selected_process = self.process_dropdown.value
        self.vis.print_message(f"selected process from list: {selected_process}")
        process_params = {paraminput.title: to_json(paraminput.value) for paraminput in self.prc_param_input}
        D = Process(inputdict={
            # "orch_name":orch_name,
            "process_label":selected_process,
            # "process_label":sellabel,
            "process_name":selected_process,
            "process_params":process_params,
        })
        if self.sequence is None:
            self.sequence = Sequence()
        self.sequence.sequence_name = "manual_orch_seq"
        self.sequence.sequence_label = self.input_sequence_label.value
        return D


    def refresh_inputs(self, param_input, private_input):
        input_plate_id = self.find_input(param_input, "solid_plate_id")
        input_sample_no = self.find_input(param_input, "solid_sample_no")
        if input_plate_id is not None:
            self.vis.doc.add_next_tick_callback(partial(
                                                        self.callback_changed_plateid,
                                                        attr = "value",
                                                        old = input_plate_id.value,
                                                        new = input_plate_id.value,
                                                        sender=input_plate_id
                                                       ))
        if input_sample_no is not None:
            self.vis.doc.add_next_tick_callback(partial(
                                                        self.callback_changed_sampleno,
                                                        attr = "value",
                                                        old = input_sample_no.value,
                                                        new = input_sample_no.value,
                                                        sender=input_sample_no
                                                       ))


    def update_input_value(self, sender, value):
        sender.value = value


    def update_seq_param_layout(self, idx):
        args = self.sequences[idx]["args"]
        defaults = self.sequences[idx]["defaults"]
        self.dynamic_col.children.pop(1)

        for _ in range(len(args)-len(defaults)):
            defaults.insert(0,"")

        self.seq_param_input = []
        self.seq_private_input = []
        self.seq_param_layout = [
            layout([
                [Spacer(width=10), bmw.Div(text="<b>Optional sequence parameters:</b>", width=200+50, height=15, style={"font-size": "100%", "color": "black"})],
                ],background=self.color_sq_param_inputs,width=640),
            ]


        self.add_dynamic_inputs(
                                self.seq_param_input,
                                self.seq_private_input,
                                self.seq_param_layout,
                                args,
                                defaults
                               )


        if not self.seq_param_input:
            self.seq_param_layout.append(
                    layout([
                    [Spacer(width=10), bmw.Div(text="-- none --", width=200+50, height=15, style={"font-size": "100%", "color": "black"})],
                    ],background=self.color_sq_param_inputs,width=640),
                )

        self.dynamic_col.children.insert(1, layout(self.seq_param_layout))

        self.refresh_inputs(self.seq_param_input, self.seq_private_input)


    def update_prc_param_layout(self, idx):
        args = self.processes[idx]["args"]
        defaults = self.processes[idx]["defaults"]
        self.dynamic_col.children.pop(3)

        for _ in range(len(args)-len(defaults)):
            defaults.insert(0,"")

        self.prc_param_input = []
        self.prc_private_input = []
        self.prc_param_layout = [
            layout([
                [Spacer(width=10), bmw.Div(text="<b>Optional process parameters:</b>", width=200+50, height=15, style={"font-size": "100%", "color": "black"})],
                ],background=self.color_sq_param_inputs,width=640),
            ]
        self.add_dynamic_inputs(
                                self.prc_param_input,
                                self.prc_private_input,
                                self.prc_param_layout,
                                args,
                                defaults
                               )


        if not self.prc_param_input:
            self.prc_param_layout.append(
                    layout([
                    [Spacer(width=10), bmw.Div(text="-- none --", width=200+50, height=15, style={"font-size": "100%", "color": "black"})],
                    ],background=self.color_sq_param_inputs,width=640),
                )

        self.dynamic_col.children.insert(3, layout(self.prc_param_layout))

        self.refresh_inputs(self.prc_param_input, self.prc_private_input)



    def add_dynamic_inputs(
                           self,
                           param_input,
                           private_input,
                           param_layout,
                           args,
                           defaults
                          ):
        item = 0
        for idx in range(len(args)):
            def_val = f"{defaults[idx]}"
            if args[idx] == "pg_Obj":
                continue
            disabled = False

            param_input.append(TextInput(value=def_val, title=args[idx], disabled=disabled, width=400, height=40))
            param_layout.append(layout([
                        [param_input[item]],
                        Spacer(height=10),
                        ],background=self.color_sq_param_inputs,width=640))
            item = item + 1

            # special key params
            if args[idx] == "solid_plate_id":
                param_input[-1].on_change("value", partial(self.callback_changed_plateid, sender=param_input[-1]))
                private_input.append(bpl.figure(title="PlateMap", height=300,x_axis_label="X (mm)", y_axis_label="Y (mm)",width = 640))
                private_input[-1].border_fill_color = self.color_sq_param_inputs
                private_input[-1].border_fill_alpha = 0.5
                private_input[-1].background_fill_color = self.color_sq_param_inputs
                private_input[-1].background_fill_alpha = 0.5
                private_input[-1].on_event(DoubleTap, partial(self.callback_clicked_pmplot, sender=param_input[-1]))
                self.update_pm_plot(private_input[-1], [])
                param_layout.append(layout([
                            [private_input[-1]],
                            Spacer(height=10),
                            ],background=self.color_sq_param_inputs,width=640))

                private_input.append(TextInput(value="", title="elements", disabled=True, width=120, height=40))
                private_input.append(TextInput(value="", title="code", disabled=True, width=60, height=40))
                private_input.append(TextInput(value="", title="composition", disabled=True, width=220, height=40))
                param_layout.append(layout([
                            [private_input[-3], private_input[-2], private_input[-1]],
                            Spacer(height=10),
                            ],background=self.color_sq_param_inputs,width=640))

            elif args[idx] == "solid_sample_no":
                param_input[-1].on_change("value", partial(self.callback_changed_sampleno, sender=param_input[-1]))

            elif args[idx] == "x_mm":
                param_input[-1].disabled = True

            elif args[idx] == "y_mm":
                param_input[-1].disabled = True

            elif args[idx] == "solid_custom_position":
                param_input[-1] = Select(title=args[idx], value = None, options=self.dev_customitems)
                if self.dev_customitems:
                    if def_val in self.dev_customitems:
                        param_input[-1].value = def_val
                    else:
                        param_input[-1].value = self.dev_customitems[0]
                param_layout[-1] = layout([
                            [param_input[-1]],
                            Spacer(height=10),
                            ],background=self.color_sq_param_inputs,width=640)

            elif args[idx] == "liquid_custom_position":
                param_input[-1] = Select(title=args[idx], value = None, options=self.dev_customitems)
                if self.dev_customitems:
                    if def_val in self.dev_customitems:
                        param_input[-1].value = def_val
                    else:
                        param_input[-1].value = self.dev_customitems[0]
                param_layout[-1] = layout([
                            [param_input[-1]],
                            Spacer(height=10),
                            ],background=self.color_sq_param_inputs,width=640)


    def update_seq_doc(self, value):
        self.sequence_descr_txt.text = value.replace("\n", "<br>")


    def update_prc_doc(self, value):
        self.process_descr_txt.text = value.replace("\n", "<br>")


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
        if len(old_point)>0:
            plot_mpmap.renderers.remove(old_point[0])
        plot_mpmap.square(x, y, size=5, color=None, alpha=0.5, line_color="black",name="PMplot")


    def get_pm(self, plateid, sender):
        """"gets plate map from aligner server, sender is the input which did the request"""
        private_input, param_input = self.find_param_private_input(sender)
        if private_input is None or param_input is None:
            return False

        pmdata = json.loads(self.dataAPI.get_platemap_plateid(plateid))
        if len(pmdata) == 0:
            self.vis.doc.add_next_tick_callback(partial(self.update_error,"no pm found"))

        plot_mpmap = self.find_plot(private_input, "PlateMap")
        if plot_mpmap is not None:
            self.vis.doc.add_next_tick_callback(partial(self.update_pm_plot, plot_mpmap, pmdata))


    def xy_to_sample(self, xy, pmapxy):
        """get point from pmap closest to xy"""
        if len(pmapxy):
            diff = pmapxy - xy
            sumdiff = (diff ** 2).sum(axis=1)
            return np.int(np.argmin(sumdiff))
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
            pmdata = json.loads(self.dataAPI.get_platemap_plateid(input_plate_id.value))
    
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

            elements =  self.dataAPI.get_elements_plateid(
                plateid,
                multielementink_concentrationinfo_bool=False,
                print_key_or_keyword="screening_print_id",
                exclude_elements_list=[""],
                return_defaults_if_none=False)
            if elements is not None:
                self.vis.doc.add_next_tick_callback(partial(self.update_input_value, input_elements, ",".join(elements)))


    def find_plot(self, inputs, name):
        for inp in inputs:
            if isinstance(inp, bpl.Figure):
                if inp.title.text == name:
                    return inp
        return None

    def find_input(self, inputs, name):
        for inp in inputs:
            if isinstance(inp, bmw.inputs.TextInput):
                if inp.title == name:
                    return inp
        return None
    
    
    def find_param_private_input(self, sender):
        private_input = None
        param_input = None

        if sender in self.prc_param_input \
        or sender in self.prc_private_input:
            private_input = self.prc_private_input
            param_input = self.prc_param_input

        elif sender in self.seq_param_input \
        or sender in self.seq_private_input:
            private_input = self.seq_private_input
            param_input = self.seq_param_input
        
        return  private_input, param_input

 
    def get_sample_infos(self, PMnum: List = None, sender = None):
        self.vis.print_message("updating samples")

        private_input, param_input = self.find_param_private_input(sender)
        if private_input is None or param_input is None:
            return False

        plot_mpmap = self.find_plot(private_input, "PlateMap")
        input_plate_id = self.find_input(param_input, "solid_plate_id")
        input_sample_no = self.find_input(param_input, "solid_sample_no")
        input_code = self.find_input(private_input, "code")
        input_composition = self.find_input(private_input, "composition")
        if plot_mpmap is not None \
        and input_plate_id is not None \
        and input_sample_no is not None:
            pmdata = json.loads(self.dataAPI.get_platemap_plateid(input_plate_id.value))
            buf = ""
            if PMnum is not None and pmdata:
                if PMnum[0] is not None: # need to check as this can also happen
                    self.vis.print_message(f"selected sampleid: {PMnum[0]+1}")
                    if PMnum[0] > len(pmdata) or PMnum[0] < 0:
                        self.vis.print_message("invalid sample no")
                        self.vis.doc.add_next_tick_callback(partial(self.update_input_value,input_sample_no,""))
                        return False
                    
                    platex = pmdata[PMnum[0]]["x"]
                    platey = pmdata[PMnum[0]]["y"]
                    code = pmdata[PMnum[0]]["code"]
    
                    buf = ""
                    for fraclet in ("A", "B", "C", "D", "E", "F", "G", "H"):
                        buf = "%s%s_%s " % (buf,fraclet, pmdata[PMnum[0]][fraclet])
                    if len(buf) == 0:
                        buf = "-"
                    if input_sample_no != str(PMnum[0]+1):
                        self.vis.doc.add_next_tick_callback(partial(self.update_input_value, input_sample_no,str(PMnum[0]+1)))
                    self.vis.doc.add_next_tick_callback(partial(self.update_xysamples,str(platex), str(platey), sender))
                    if input_composition is not None:
                        self.vis.doc.add_next_tick_callback(partial(self.update_input_value,input_composition,buf))
                    if input_code is not None:
                        self.vis.doc.add_next_tick_callback(partial(self.update_input_value,input_code,str(code)))
    
                    # remove old Marker point
                    old_point = plot_mpmap.select(name="selsample")
                    if len(old_point)>0:
                        plot_mpmap.renderers.remove(old_point[0])
                    # plot new Marker point
                    plot_mpmap.square(platex, platey, size=7,line_width=2, color=None, alpha=1.0, line_color=(255,0,0), name="selsample")

                    return True
            else:
                return False

        return False


    async def add_process_to_sequence(self):
        pass
        

    async def update_tables(self):
        await self.get_processes()
        await self.get_actions()
        await self.get_active_actions()

        self.sequence_list = dict()

        self.sequence_list["sequence_name"] = []
        self.sequence_list["sequence_label"] = []
        self.sequence_list["process_name"] = []
        if self.sequence is not None:
            for D in self.sequence.process_list:
                self.sequence_list["sequence_name"].append(self.sequence.sequence_name)
                self.sequence_list["sequence_label"].append(self.sequence.sequence_label)
                self.sequence_list["process_name"].append(D.process_name)


        self.columns_seq = [TableColumn(field=key, title=key) for key in self.sequence_list]
        self.sequence_table.source.data = self.sequence_list
        self.sequence_table.columns=self.columns_seq


        self.columns_prc = [TableColumn(field=key, title=key) for key in self.process_list]
        self.process_table.source.data = self.process_list
        self.process_table.columns=self.columns_prc

        self.columns_act = [TableColumn(field=key, title=key) for key in self.action_list]
        self.action_table.source.data=self.action_list
        self.action_table.columns=self.columns_act

        self.columns_active_action = [TableColumn(field=key, title=key) for key in self.active_action_list]
        self.active_action_table.source.data=self.active_action_list
        self.active_action_table.columns=self.columns_active_action


    async def IOloop(self):
        # todo: update to ws
        await self.update_tables()


def makeBokehApp(doc, confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config

    app = hcs.makeVisServ(
        config,
        servKey,
        doc,
        servKey,
        "Operator",
        version=2.0,
        driver_class=None,
    )


    _ = C_async_operator(app.vis)
    # operator = C_async_operator(app.vis)
    # get the event loop
    # operatorloop = asyncio.get_event_loop()

    # this periodically updates the GUI (action and process tables)
    # operator.vis.doc.add_periodic_callback(operator.IOloop,2000) # time in ms

    return doc
