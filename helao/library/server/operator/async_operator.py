
__all__ = ["makeBokehApp"]


# import os
# import sys
# import websockets
# import asyncio
import json
# import collections
from functools import partial
from importlib import import_module
from socket import gethostname
# import aiohttp
# from collections import deque

# from munch import munchify


# from bokeh.io import show
from bokeh.layouts import column
from bokeh.layouts import layout, Spacer
from bokeh.models import FileInput
from bokeh.models import ColumnDataSource, CheckboxButtonGroup, RadioButtonGroup
from bokeh.models import Title, DataTable, TableColumn
from bokeh.models.widgets import Paragraph
from bokeh.models import CustomJS, Dropdown
from bokeh.models import Select
# from bokeh.models import Range1d
from bokeh.models import Arrow, NormalHead, OpenHead, VeeHead
from bokeh.models import Button, TextAreaInput, TextInput
from bokeh.models import TextInput
from bokeh.models.widgets import Div
from bokeh.plotting import figure, curdoc
from bokeh.palettes import Spectral6, small_palettes
# from bokeh.transform import linear_cmap
# from bokeh.events import MenuItemClick
from bokeh.events import ButtonClick, DoubleTap


# import pathlib
# import copy
# import math
import io
from pybase64 import b64decode
import numpy as np


# import requests
# from functools import partial

import inspect
from pydantic import BaseModel

from typing import Optional, List, Union



import helaocore.server as hcs
from helaocore.data import HTELegacyAPI
from helaocore.schema import Process


class return_process_lib(BaseModel):
    """Return class for queried process objects."""
    index: int
    process_name: str
    doc: str
    args: list
    defaults: list
    #annotations: dict()
    # defaults: list
    #argcount: int
    #params: list


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

        self.pmdata = []
        
        self.color_sq_param_inputs = "#BDB76B"


        # holds the page layout
        self.layout = []
        self.param_layout = []
        self.param_input = []

        self.process_list = dict()
        self.action_list = dict()
        self.active_action_list = dict()

        self.process_select_list = []
        self.processes = []
        self.process_lib = hcs.import_processes(world_config_dict = self.vis.world_cfg, process_path = None, server_name=self.vis.server_name)



        # FastAPI calls
        self.get_process_lib()
        self.vis.doc.add_next_tick_callback(partial(self.get_processes))
        self.vis.doc.add_next_tick_callback(partial(self.get_actions))
        self.vis.doc.add_next_tick_callback(partial(self.get_active_actions))

        #self.vis.print_message([key for key in self.process_list])
        self.process_source = ColumnDataSource(data=self.process_list)
        self.columns_dec = [TableColumn(field=key, title=key) for key in self.process_list]
        self.process_table = DataTable(source=self.process_source, columns=self.columns_dec, width=620, height=200)

        self.action_source = ColumnDataSource(data=self.action_list)
        self.columns_action = [TableColumn(field=key, title=key) for key in self.action_list]
        self.action_table = DataTable(source=self.action_source, columns=self.columns_action, width=620, height=200)

        self.active_action_source = ColumnDataSource(data=self.active_action_list)
        self.columns_active_action = [TableColumn(field=key, title=key) for key in self.active_action_list]
        self.active_action_table = DataTable(source=self.active_action_source, columns=self.columns_active_action, width=620, height=200)



        self.process_dropdown = Select(title="Select process:", value = None, options=self.process_select_list)
        self.process_dropdown.on_change("value", self.callback_action_select)

        self.button_load_sample_list = FileInput(accept=".csv,.txt", width = 300)
        self.button_load_sample_list.on_change("value", self.get_sample_list)


        # buttons to control orch
        self.button_start = Button(label="Start Orch", button_type="default", width=70)
        self.button_start.on_event(ButtonClick, self.callback_start)
        self.button_stop = Button(label="Stop Orch", button_type="default", width=70)
        self.button_stop.on_event(ButtonClick, self.callback_stop)
        self.button_skip = Button(label="Skip prc", button_type="danger", width=70)
        self.button_skip.on_event(ButtonClick, self.callback_skip_dec)
        self.button_update = Button(label="update tables", button_type="default", width=120)
        self.button_update.on_event(ButtonClick, self.callback_update_tables)

        self.button_clear_dec = Button(label="clear prg", button_type="danger", width=100)
        self.button_clear_dec.on_event(ButtonClick, self.callback_clear_processes)
        self.button_clear_action = Button(label="clear prc", button_type="danger", width=100)
        self.button_clear_action.on_event(ButtonClick, self.callback_clear_actions)

        self.button_prepend = Button(label="prepend sq", button_type="default", width=150)
        self.button_prepend.on_event(ButtonClick, self.callback_prepend)
        self.button_append = Button(label="append sq", button_type="default", width=150)
        self.button_append.on_event(ButtonClick, self.callback_append)

        self.action_descr_txt = Div(text="""select item""", width=600)
        self.error_txt = Paragraph(text="""no error""", width=600, height=30, style={"font-size": "100%", "color": "black"})

        self.input_solid_sample_no = TextInput(value="", title="sample no", disabled=False, width=330, height=40)
        self.input_solid_sample_no.on_change("value", self.callback_changed_sampleno)
        self.input_solid_plate_id = TextInput(value="", title="plate id", disabled=False, width=60, height=40)
        self.input_solid_plate_id.on_change("value", self.callback_changed_plateid)
        
        self.input_process_label = TextInput(value="nolabel", title="process label", disabled=False, width=120, height=40)
        self.input_elements = TextInput(value="", title="elements", disabled=True, width=120, height=40)
        self.input_code = TextInput(value="", title="code", disabled=True, width=60, height=40)
        self.input_composition = TextInput(value="", title="composition", disabled=True, width=220, height=40)

        self.plot_mpmap = figure(title="PlateMap", height=300,x_axis_label="X (mm)", y_axis_label="Y (mm)",width = 640)
        self.plot_mpmap.border_fill_color = self.color_sq_param_inputs
        self.plot_mpmap.border_fill_alpha = 0.5
        self.plot_mpmap.background_fill_color = self.color_sq_param_inputs
        self.plot_mpmap.background_fill_alpha = 0.5
        self.plot_mpmap.on_event(DoubleTap, self.callback_clicked_pmplot)
        self.update_pm_plot()

        self.layout0 = layout([
            layout(
                [Spacer(width=20), Div(text=f"<b>{self.config_dict.get('doc_name', 'Operator')} on {gethostname()}</b>", width=620, height=32, style={"font-size": "200%", "color": "red"})],
                background="#C0C0C0",width=640),
            layout([
                [self.process_dropdown],
                [Spacer(width=10), Div(text="<b>process description:</b>", width=200+50, height=15)],
                [self.action_descr_txt],
                Spacer(height=20),
                [Spacer(width=10), Div(text="<b>Error message:</b>", width=200+50, height=15, style={"font-size": "100%", "color": "black"})],
                [Spacer(width=10), self.error_txt],
                Spacer(height=10),
                ],background="#808080",width=640),
            layout([
                [self.input_process_label],
                Spacer(height=10),
                ]),
            ])



        self.layout2 = layout([
                layout([
                    [self.button_append, self.button_prepend, self.button_start, self.button_stop],
                    ]),
                layout([
                [Spacer(width=20), Div(text="<b>queued processes:</b>", width=200+50, height=15)],
                [self.process_table],
                [Spacer(width=20), Div(text="<b>queued actions:</b>", width=200+50, height=15)],
                [self.action_table],
                [Spacer(width=20), Div(text="<b>Active actions:</b>", width=200+50, height=15)],
                [self.active_action_table],
                Spacer(height=10),
                [self.button_skip, Spacer(width=5), self.button_clear_dec, Spacer(width=5), self.button_clear_action, self.button_update],
                Spacer(height=10),
                ],background="#7fdbff",width=640),
            ])


        self.dynamic_col = column(self.layout0, self.layout2)
        self.vis.doc.add_root(self.dynamic_col)


        # select the first item to force an update of the layout
        if self.process_select_list:
            self.process_dropdown.value = self.process_select_list[0]



    def get_process_lib(self):
        """Return the current list of processes."""
        self.processes = []
        self.vis.print_message(f"found process: {[process for process in self.process_lib]}")
        for i, process in enumerate(self.process_lib):
            # self.vis.print_message("full",inspect.getfullargspec(self.process_lib[process]))
            #self.vis.print_message("anno",inspect.getfullargspec(self.process_lib[process]).annotations)
            #self.vis.print_message("def",inspect.getfullargspec(self.process_lib[process]).defaults)
            tmpdoc = self.process_lib[process].__doc__ 
            # self.vis.print_message("... doc:", tmpdoc)
            if tmpdoc == None:
                tmpdoc = ""
            tmpargs = inspect.getfullargspec(self.process_lib[process]).args
            tmpdef = inspect.getfullargspec(self.process_lib[process]).defaults
            if tmpdef == None:
                tmpdef = []
            # if not tmpargs:
            #     tmpargs = [""]
            
            
            self.processes.append(return_process_lib(
                index=i,
                process_name = process,
                doc = tmpdoc,#self.process_lib[process].__doc__ if self.process_lib[process].__doc__ not None else "",
                args = tmpargs,#{},
                defaults = tmpdef,
                #annotations = inspect.getfullargspec(self.process_lib[process]).annotations,
                # defaults = inspect.getfullargspec(self.process_lib[process]).defaults,
               #params = "",
            ).dict()
                )
        for item in self.processes:
            self.process_select_list.append(item["process_name"])


    async def get_processes(self):
        """get process list from orch"""
        response = await self.do_orch_request(action_name = "list_processes")
        response = response["processes"]
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
        response = response["actions"]
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
        response = response["actions"]
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



    def callback_action_select(self, attr, old, new):
        idx = self.process_select_list.index(new)
        action_doc = self.processes[idx]["doc"]
        # for arg in self.processes[idx]["args"]:
        #     self.vis.print_message(arg)
        self.update_param_layout(self.processes[idx]["args"], self.processes[idx]["defaults"])
        self.vis.doc.add_next_tick_callback(partial(self.update_doc,action_doc))


    def callback_clicked_pmplot(self, event):
        """double click/tap on PM plot to add/move marker"""
        self.vis.print_message(f"DOUBLE TAP PMplot: {event.x}, {event.y}")
        # get coordinates of doubleclick
        platex = event.x
        platey = event.y
        # transform to nearest sample point
        PMnum = self.get_samples([platex], [platey])
        self.get_sample_infos(PMnum)


    def callback_changed_plateid(self, attr, old, new):
        """callback for plateid text input"""
        def to_int(val):
            try:
                return int(val)
            except ValueError:
                return None

        plateid = to_int(new)
        if plateid is not None:
            self.get_pm(new)
            self.get_elements_plateid(new)
        else:
            self.vis.doc.add_next_tick_callback(partial(self.update_plateid,""))


    def callback_changed_sampleno(self, attr, old, new):
        """callback for sampleno text input"""
        def to_int(val):
            try:
                return int(val)
            except ValueError:
                return None

        sample_no = to_int(new)
        if sample_no is not None:
            self.get_sample_infos([sample_no])
        else:
            self.vis.doc.add_next_tick_callback(partial(self.update_samples,""))


    def callback_start(self, event):
        self.vis.print_message("starting orch")
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"start"))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_stop(self, event):
        self.vis.print_message("stopping operator orch")
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"stop"))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_skip_dec(self, event):
        self.vis.print_message("skipping process")
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"skip"))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_clear_processes(self, event):
        self.vis.print_message("clearing processes")
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"clear_processes"))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_clear_actions(self, event):
        self.vis.print_message("clearing actions")
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"clear_actions"))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_prepend(self, event):
        self.prepend_process()
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))



    def callback_append(self, event):
        self.append_process()
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_update_tables(self, event):
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def append_process(self):
        params_dict, json_dict = self.populate_action()
        # submit decission to orchestrator
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"append_process", params_dict, json_dict))


    def prepend_process(self):
        params_dict, json_dict = self.populate_action()
        # submit decission to orchestrator
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"prepend_process", params_dict, json_dict))


    def populate_action(self):
        def to_json(v):
            try:
                val = json.loads(v)
            except ValueError:
                val = v
            return val
        
        selected_process = self.process_dropdown.value
        sellabel = self.input_process_label.value

        self.vis.print_message(f"selected action from list: {selected_process}")
        self.vis.print_message(f"selected label: {sellabel}")

        process_params = {paraminput.title: to_json(paraminput.value) for paraminput in self.param_input}
        D = Process(inputdict={
            # "orch_name":orch_name,
            "process_label":sellabel,
            "process_name":selected_process,
            "process_params":process_params,
        })

        return D.fastdict()


    def update_param_layout(self, args, defaults):
        if len(self.dynamic_col.children)>2:
            self.dynamic_col.children.pop(1)

        for _ in range(len(args)-len(defaults)):
            defaults.insert(0,"")

        self.param_input = []
        # self.param_layout = []
        self.param_layout = [
            layout([
                [Spacer(width=10), Div(text="<b>Optional process parameters:</b>", width=200+50, height=15, style={"font-size": "100%", "color": "black"})],
                ],background=self.color_sq_param_inputs,width=640),
            ]

        item = 0
        for idx in range(len(args)):
            buf = f"{defaults[idx]}"
            # self.vis.print_message("action parameter:",args[idx])
            # skip the process_Obj parameter
            if args[idx] == "pg_Obj":
                continue
            disabled = False

            self.param_input.append(TextInput(value=buf, title=args[idx], disabled=disabled, width=400, height=40))
            self.param_layout.append(layout([
                        [self.param_input[item]],
                        Spacer(height=10),
                        ],background=self.color_sq_param_inputs,width=640))
            item = item + 1

            # special key params
            if args[idx] == "solid_plate_id":
                self.input_solid_plate_id = self.param_input[-1]
                self.input_solid_plate_id.on_change("value", self.callback_changed_plateid)
                self.param_layout.append(layout([
                            [self.plot_mpmap],
                            Spacer(height=10),
                            ],background=self.color_sq_param_inputs,width=640))
                self.param_layout.append(layout([
                            [self.input_elements, self.input_code, self.input_composition],
                            Spacer(height=10),
                            ],background=self.color_sq_param_inputs,width=640))
            elif args[idx] == "solid_sample_no":
                self.input_solid_sample_no = self.param_input[-1]
                self.input_solid_sample_no.on_change("value", self.callback_changed_sampleno)
            elif args[idx] == "x_mm":
                self.param_input[-1].disabled = True
            elif args[idx] == "y_mm":
                self.param_input[-1].disabled = True
            elif args[idx] == "solid_custom_position":
                self.param_input[-1] = Select(title=args[idx], value = None, options=self.dev_customitems)
                if self.dev_customitems:
                    self.param_input[-1].value = self.dev_customitems[0]
                self.param_layout[-1] = layout([
                            [self.param_input[-1]],
                            Spacer(height=10),
                            ],background=self.color_sq_param_inputs,width=640)
            elif args[idx] == "liquid_custom_position":
                self.param_input[-1] = Select(title=args[idx], value = None, options=self.dev_customitems)
                if self.dev_customitems:
                    self.param_input[-1].value = self.dev_customitems[0]
                self.param_layout[-1] = layout([
                            [self.param_input[-1]],
                            Spacer(height=10),
                            ],background=self.color_sq_param_inputs,width=640)

        self.dynamic_col.children.insert(-1, layout(self.param_layout))


    def update_doc(self, value):
        self.action_descr_txt.text = value.replace("\n", "<br>")


    def update_error(self, value):
        self.error_txt.text = value


    def update_plateid(self, value):
        """updates plateid text input"""
        self.input_solid_plate_id.value = value


    def update_samples(self, value):
        self.input_solid_sample_no.value = value


    def update_xysamples(self, xval, yval):
        for paraminput in self.param_input:
            if paraminput.title == "x_mm":
                paraminput.value = xval
            if paraminput.title == "y_mm":
                paraminput.value = yval


    def update_elements(self, elements):
        self.input_elements.value = ",".join(elements) 

        
    def update_composition(self, composition):
        self.input_composition.value = composition

        
    def update_code(self, code):
        self.input_code.value = code


    def update_pm_plot(self):
        """plots the plate map"""
        x = [col["x"] for col in self.pmdata]
        y = [col["y"] for col in self.pmdata]
        # remove old Pmplot
        old_point = self.plot_mpmap.select(name="PMplot")
        if len(old_point)>0:
            self.plot_mpmap.renderers.remove(old_point[0])
        self.plot_mpmap.square(x, y, size=5, color=None, alpha=0.5, line_color="black",name="PMplot")


    def get_sample_list(self, attr, old_file, new_file):
        f = io.BytesIO(b64decode(new_file))
        samplelist = np.loadtxt(f, skiprows=2, delimiter=",")
        self.vis.print_message(samplelist)
        samplestr = ""
        for sample in samplelist:
            samplestr += str(int(sample)) + ","
        if samplestr.endswith(","):
            samplestr = samplestr[:-1]
        self.vis.print_message(samplestr)
        self.vis.doc.add_next_tick_callback(partial(self.update_samples,samplestr))


    def get_pm(self, plateid):
        """"gets plate map from aligner server"""
        #simple one for tests is plateid = "4534"
        self.pmdata = json.loads(self.dataAPI.get_platemap_plateid(plateid))
        if len(self.pmdata) == 0:
            self.vis.doc.add_next_tick_callback(partial(self.update_error,"no pm found"))
        self.vis.doc.add_next_tick_callback(partial(self.update_pm_plot))

    
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
        pmxy = np.array([[col["x"], col["y"]] for col in self.pmdata])
        samples = list(np.apply_along_axis(self.xy_to_sample, 1, xyarr, pmxy))
        return samples             


    def get_elements_plateid(self, plateid: int):
        """gets plate elements from aligner server"""
        elements =  self.dataAPI.get_elements_plateid(
            plateid,
            multielementink_concentrationinfo_bool=False,
            print_key_or_keyword="screening_print_id",
            exclude_elements_list=[""],
            return_defaults_if_none=False)
        if elements is not None:
            self.vis.doc.add_next_tick_callback(partial(self.update_elements, elements))


    def get_sample_infos(self, PMnum: List = None):
        self.vis.print_message("updating samples")
        buf = ""
        if PMnum is not None and self.pmdata:
            if PMnum[0] is not None: # need to check as this can also happen
                self.vis.print_message(f"selected sampleid: {PMnum[0]}")
                if PMnum[0] > len(self.pmdata):
                    self.vis.print_message("invalid sample no")
                    self.vis.doc.add_next_tick_callback(partial(self.update_samples,""))
                    return False
                
                platex = self.pmdata[PMnum[0]]["x"]
                platey = self.pmdata[PMnum[0]]["y"]
                code = self.pmdata[PMnum[0]]["code"]

                # only display non zero fractions
                buf = ""
                # TODO: test on other platemap
                for fraclet in ("A", "B", "C", "D", "E", "F", "G", "H"):
                    # if self.pmdata[PMnum[0]][fraclet] > 0:
                    #     buf = "%s%s%d " % (buf,fraclet, self.pmdata[PMnum[0]][fraclet]*100)
                    buf = "%s%s_%s " % (buf,fraclet, self.pmdata[PMnum[0]][fraclet])
                if len(buf) == 0:
                    buf = "-"
                self.vis.doc.add_next_tick_callback(partial(self.update_samples,str(PMnum[0])))
                self.vis.doc.add_next_tick_callback(partial(self.update_xysamples,str(platex), str(platey)))
                self.vis.doc.add_next_tick_callback(partial(self.update_composition,buf))
                self.vis.doc.add_next_tick_callback(partial(self.update_code,str(code)))

                # remove old Marker point
                old_point = self.plot_mpmap.select(name="selsample")
                if len(old_point)>0:
                    self.plot_mpmap.renderers.remove(old_point[0])
                # plot new Marker point
                self.plot_mpmap.square(platex, platey, size=7,line_width=2, color=None, alpha=1.0, line_color=(255,0,0), name="selsample")
                return True

        return False



    async def update_tables(self):
        await self.get_processes()
        await self.get_actions()
        await self.get_active_actions()



        self.columns_dec = [TableColumn(field=key, title=key) for key in self.process_list]
        self.process_table.source.data = self.process_list
        self.process_table.columns=self.columns_dec

        self.columns_action = [TableColumn(field=key, title=key) for key in self.action_list]
        self.action_table.source.data=self.action_list
        self.action_table.columns=self.columns_action

        self.columns_active_action = [TableColumn(field=key, title=key) for key in self.active_action_list]
        self.active_action_table.source.data=self.active_action_list
        self.active_action_table.columns=self.columns_active_action



    async def IOloop(self):
        # should maybe update it do ws later instead of polling once orch2 is ready
        # itr seems when orch is in dispatch loop this here is not updating
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


    operator = C_async_operator(app.vis)
    # get the event loop
    # operatorloop = asyncio.get_event_loop()

    # this periodically updates the GUI (action and process tables)
    # operator.vis.doc.add_periodic_callback(operator.IOloop,2000) # time in ms

    return doc
