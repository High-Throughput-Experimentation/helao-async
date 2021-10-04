
# import os
# import sys
# import websockets
import asyncio
import json
# import collections
from functools import partial
from importlib import import_module

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


from helao.core.server import makeVisServ
from helao.core.server import import_sequences, async_private_dispatcher
# from helao.core.data import liquid_sample_no_API
from helao.core.data import HTE_legacy_API
from helao.core.schema import cProcess_group
from helao.core.server import Vis


class return_sequence_lib(BaseModel):
    """Return class for queried sequence objects."""
    index: int
    sequence: str
    doc: str
    args: list
    defaults: list
    #annotations: dict()
    # defaults: list
    #argcount: int
    #params: list


class C_async_operator:
    def __init__(self, visServ: Vis):
        self.vis = visServ

        self.dataAPI = HTE_legacy_API(self.vis)

        self.config_dict = self.vis.server_cfg["params"]
        self.orch_name = self.config_dict["orch"]
        
        self.pmdata = []
        

        # holds the page layout
        self.layout = []
        self.param_layout = []
        self.param_input = []

        self.process_group_list = dict()
        self.process_list = dict()
        self.active_process_list = dict()

        self.sequence_select_list = []
        self.sequences = []
        self.sequence_lib = import_sequences(world_config_dict = self.vis.world_cfg, library_path = None, server_name=self.vis.server_name)



        # FastAPI calls
        self.get_sequences()
        self.vis.doc.add_next_tick_callback(partial(self.get_process_groups))
        self.vis.doc.add_next_tick_callback(partial(self.get_processes))
        self.vis.doc.add_next_tick_callback(partial(self.get_active_processes))

        #self.vis.print_message([key for key in self.process_group_list.keys()])
        self.process_group_source = ColumnDataSource(data=self.process_group_list)
        self.columns_dec = [TableColumn(field=key, title=key) for key in self.process_group_list.keys()]
        self.process_group_table = DataTable(source=self.process_group_source, columns=self.columns_dec, width=620, height=200)

        self.process_source = ColumnDataSource(data=self.process_list)
        self.columns_process = [TableColumn(field=key, title=key) for key in self.process_list.keys()]
        self.process_table = DataTable(source=self.process_source, columns=self.columns_process, width=620, height=200)

        self.active_process_source = ColumnDataSource(data=self.active_process_list)
        self.columns_active_process = [TableColumn(field=key, title=key) for key in self.active_process_list.keys()]
        self.active_process_table = DataTable(source=self.active_process_source, columns=self.columns_active_process, width=620, height=200)



        self.sequence_dropdown = Select(title="Select sequence:", value = None, options=self.sequence_select_list)
        self.sequence_dropdown.on_change('value', self.callback_process_select)

        self.button_load_sample_list = FileInput(accept=".csv,.txt", width = 300)
        self.button_load_sample_list.on_change('value', self.get_sample_list)


        # buttons to control orch
        self.button_start = Button(label="Start", button_type="default", width=70)
        self.button_start.on_event(ButtonClick, self.callback_start)
        self.button_stop = Button(label="Stop", button_type="default", width=70)
        self.button_stop.on_event(ButtonClick, self.callback_stop)
        self.button_skip = Button(label="Skip", button_type="danger", width=70)
        self.button_skip.on_event(ButtonClick, self.callback_skip_dec)
        self.button_update = Button(label="update tables", button_type="default", width=120)
        self.button_update.on_event(ButtonClick, self.callback_update_tables)

        self.button_clear_dec = Button(label="clear process_groups", button_type="danger", width=100)
        self.button_clear_dec.on_event(ButtonClick, self.callback_clear_process_groups)
        self.button_clear_process = Button(label="clear processes", button_type="danger", width=100)
        self.button_clear_process.on_event(ButtonClick, self.callback_clear_processes)

        self.button_prepend = Button(label="prepend", button_type="default", width=150)
        self.button_prepend.on_event(ButtonClick, self.callback_prepend)
        self.button_append = Button(label="append", button_type="default", width=150)
        self.button_append.on_event(ButtonClick, self.callback_append)




#        self.process_descr_txt = Paragraph(text="""select item""", width=600, height=30)
        self.process_descr_txt = Div(text="""select item""", width=600, height=30)
        self.error_txt = Paragraph(text="""no error""", width=600, height=30, style={'font-size': '100%', 'color': 'black'})


        self.input_sampleno = TextInput(value="", title="sample no", disabled=False, width=330, height=40)
        self.input_sampleno.on_change('value', self.callback_changed_sampleno)
        self.input_plateid = TextInput(value="", title="plate id", disabled=False, width=60, height=40)
        self.input_plateid.on_change('value', self.callback_changed_plateid)
        
        self.input_label = TextInput(value="nolabel", title="label", disabled=False, width=120, height=40)
        self.input_elements = TextInput(value="", title="elements", disabled=False, width=120, height=40)
        self.input_code = TextInput(value="", title="code", disabled=False, width=60, height=40)
        self.input_composition = TextInput(value="", title="composition", disabled=False, width=220, height=40)




        self.plot_mpmap = figure(title="PlateMap", height=300,x_axis_label='X (mm)', y_axis_label='Y (mm)',width = 640)
        self.plot_mpmap.on_event(DoubleTap, self.callback_clicked_pmplot)
        self.update_pm_plot()


        self.layout0 = layout([
            layout(
                [Spacer(width=20), Div(text=f"<b>{self.config_dict['doc_name']}</b>", width=200+50, height=32, style={'font-size': '200%', 'color': 'red'})],
                background="#C0C0C0",width=640),
            layout([
                [self.sequence_dropdown],
                [Spacer(width=10), Div(text="<b>sequence description:</b>", width=200+50, height=15)],
                [self.process_descr_txt],
                Spacer(height=10),
                [Spacer(width=10), Div(text="<b>Error message:</b>", width=200+50, height=15, style={'font-size': '100%', 'color': 'black'})],
                [Spacer(width=10), self.error_txt],
                Spacer(height=10),
                ],background="#808080",width=640),
            layout([
                # [Paragraph(text="""Load sample list from file:""", width=600, height=30)],
                # [self.button_load_sample_list],
                [self.input_plateid, self.input_sampleno],
                [self.input_elements, self.input_code, self.input_composition],
                [self.input_label],
                Spacer(height=10),
                [self.plot_mpmap],
                Spacer(height=10),
                ]),
            ])



        self.layout2 = layout([
                layout([
                    [self.button_append, self.button_prepend, self.button_start, self.button_stop],
                    ]),
                layout([
                [Spacer(width=20), Div(text="<b>queued process_groups:</b>", width=200+50, height=15)],
                [self.process_group_table],
                [Spacer(width=20), Div(text="<b>queued processes:</b>", width=200+50, height=15)],
                [self.process_table],
                [Spacer(width=20), Div(text="<b>Active processes:</b>", width=200+50, height=15)],
                [self.active_process_table],
                Spacer(height=10),
                [self.button_skip, Spacer(width=5), self.button_clear_dec, Spacer(width=5), self.button_clear_process, self.button_update],
                Spacer(height=10),
                ],background="#7fdbff",width=640),
            ])


        self.dynamic_col = column(self.layout0, self.layout2)
        self.vis.doc.add_root(self.dynamic_col)


        # select the first item to force an update of the layout
        if self.sequence_select_list:
            self.sequence_dropdown.value = self.sequence_select_list[0]



    def get_sequences(self):
        """Return the current list of sequences."""
        self.sequences = []
        self.vis.print_message(f" ... found sequence: {[sequence for sequence in self.sequence_lib.keys()]}")
        for i, sequence in enumerate(self.sequence_lib):
            # self.vis.print_message('full',inspect.getfullargspec(self.sequence_lib[sequence]))
            #self.vis.print_message('anno',inspect.getfullargspec(self.sequence_lib[sequence]).annotations)
            #self.vis.print_message('def',inspect.getfullargspec(self.sequence_lib[sequence]).defaults)
            tmpdoc = self.sequence_lib[sequence].__doc__ 
            # self.vis.print_message("... doc:", tmpdoc)
            if tmpdoc == None:
                tmpdoc = ""
            tmpargs = inspect.getfullargspec(self.sequence_lib[sequence]).args
            tmpdef = inspect.getfullargspec(self.sequence_lib[sequence]).defaults
            if tmpdef == None:
                tmpdef = []
            # if not tmpargs:
            #     tmpargs = ['']
            
            
            self.sequences.append(return_sequence_lib(
                index=i,
                sequence = sequence,
                doc = tmpdoc,#self.sequence_lib[sequence].__doc__ if self.sequence_lib[sequence].__doc__ not None else "",
                args = tmpargs,#{},
                defaults = tmpdef,
                #annotations = inspect.getfullargspec(self.sequence_lib[sequence]).annotations,
                # defaults = inspect.getfullargspec(self.sequence_lib[sequence]).defaults,
               #params = '',
            ).dict()
                )

        for item in self.sequences:
            self.sequence_select_list.append(item['sequence'])


    async def get_process_groups(self):
        '''get process_group list from orch'''
        response = await self.do_orch_request(process_name = "list_process_groups")
        response = response["process_groups"]
        self.process_group_list = dict()
        if len(response):
            for key in response[0].keys():
                self.process_group_list[key] = []
            for line in response:
                for key, value in line.items():
                    self.process_group_list[key].append(value)
        self.vis.print_message(' ... current queued process_groups:',self.process_group_list)


    async def get_processes(self):
        '''get process list from orch'''
        response = await self.do_orch_request(process_name = "list_processes")
        response = response["processes"]
        self.process_list = dict()
        if len(response):
            for key in response[0].keys():
                self.process_list[key] = []
            for line in response:
                for key, value in line.items():
                    self.process_list[key].append(value)
        self.vis.print_message(' ... current queued processes:',self.process_list)


    async def get_active_processes(self):
        '''get process list from orch'''
        response = await self.do_orch_request(process_name = "list_active_processes")
        response = response["processes"]
        self.active_process_list = dict()
        if len(response):
            for key in response[0].keys():
                self.active_process_list[key] = []
            for line in response:
                for key, value in line.items():
                    self.active_process_list[key].append(value)
        self.vis.print_message(' ... current active processes:',self.active_process_list)


    async def do_orch_request(self,process_name, 
                              params_dict: dict = {},
                              json_dict: dict = {}
                              ):
        """submit a FastAPI request to orch"""
    

        response = await async_private_dispatcher(
            world_config_dict = self.vis.world_cfg, 
            server = self.orch_name,
            private_process = process_name,
            params_dict = params_dict,
            json_dict = json_dict
            )
            
        return response



    def callback_process_select(self, attr, old, new):
        idx = self.sequence_select_list.index(new)
        process_doc = self.sequences[idx]['doc']
        # for arg in self.sequences[idx]['args']:
        #     self.vis.print_message(arg)
        self.update_param_layout(self.sequences[idx]['args'], self.sequences[idx]['defaults'])
        self.vis.doc.add_next_tick_callback(partial(self.update_doc,process_doc))


    def callback_clicked_pmplot(self, event):
        """double click/tap on PM plot to add/move marker"""
        self.vis.print_message("DOUBLE TAP PMplot")
        self.vis.print_message(event.x, event.y)
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
        self.vis.print_message(" ... starting orch")
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"start"))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_stop(self, event):
        self.vis.print_message(" ... stopping operator orch")
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"stop"))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_skip_dec(self, event):
        self.vis.print_message(" ... skipping process_group")
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"skip"))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_clear_process_groups(self, event):
        self.vis.print_message(" ... clearing process_groups")
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"clear_process_groups"))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_clear_processes(self, event):
        self.vis.print_message(" ... clearing processes")
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"clear_processes"))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_prepend(self, event):
        self.prepend_process_group()
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))



    def callback_append(self, event):
        self.append_process_group()
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def callback_update_tables(self, event):
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))


    def append_process_group(self):
        params_dict, json_dict = self.populate_process()
        # submit decission to orchestrator
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"append_process_group", params_dict, json_dict))


    def prepend_process_group(self):
        params_dict, json_dict = self.populate_process()
        # submit decission to orchestrator
        self.vis.doc.add_next_tick_callback(partial(self.do_orch_request,"prepend_process_group", params_dict, json_dict))


    def populate_process(self):
        def to_json(v):
            try:
                val = json.loads(v)
            except ValueError:
                val = v
            return val
        
        selected_sequence = self.sequence_dropdown.value
        selplateid = self.input_plateid.value
        selsample = self.input_sampleno.value
        sellabel = self.input_label.value
        # elements = self.input_elements.value
        # code  = self.input_code.value
        # composition = self.input_composition.value

        self.vis.print_message(f" ... selected process from list: {selected_sequence}")
        self.vis.print_message(f" ... selected plateid: {selplateid}")
        self.vis.print_message(f" ... selected sample: {selsample}")
        self.vis.print_message(f" ... selected label: {sellabel}")


        sequence_params = {paraminput.title: to_json(paraminput.value) for paraminput in self.param_input}
        sequence_params["plate_id"] = selplateid
        sequence_params["plate_sample_no"] = selsample

        D = cProcess_group(inputdict={
            # "orch_name":orch_name,
            "process_group_label":sellabel,
            "sequence":selected_sequence,
            "sequence_pars":sequence_params,
            # "result_dict":result_dict,
            # "access":access,
        })

        return D.fastdict()


    def update_param_layout(self, args, defaults):
        if len(self.dynamic_col.children)>2:
            self.dynamic_col.children.pop(1)

        for _ in range(len(args)-len(defaults)):
            defaults.insert(0,"")

        self.param_input = []
        self.param_layout = []
        
        item = 0
        for idx in range(len(args)):
            buf = f'{defaults[idx]}'
            # self.vis.print_message(' ... process parameter:',args[idx])
            # skip the process_group_Obj parameter
            if args[idx] == 'process_group_Obj':
                continue

            disabled = False
            if args[idx] == 'x_mm':
                disabled = True
            if args[idx] == 'y_mm':
                disabled = True

            self.param_input.append(TextInput(value=buf, title=args[idx], disabled=disabled, width=400, height=40))
            self.param_layout.append(layout([
                        [self.param_input[item]],
                        Spacer(height=10),
                        ]))
            item = item + 1

        self.dynamic_col.children.insert(-1, layout(self.param_layout))


    def update_doc(self, value):
        self.process_descr_txt.text = value.replace("\n", "<br>")


    def update_error(self, value):
        self.error_txt.text = value


    def update_plateid(self, value):
        """updates plateid text input"""
        self.input_plateid.value = value


    def update_samples(self, value):
        self.input_sampleno.value = value


    def update_xysamples(self, xval, yval):
        for paraminput in self.param_input:
            if paraminput.title == 'x_mm':
                paraminput.value = xval
            if paraminput.title == 'y_mm':
                paraminput.value = yval


    def update_elements(self, elements):
        self.input_elements.value = ','.join(elements) 

        
    def update_composition(self, composition):
        self.input_composition.value = composition

        
    def update_code(self, code):
        self.input_code.value = code


    def update_pm_plot(self):
        '''plots the plate map'''
        x = [col['x'] for col in self.pmdata]
        y = [col['y'] for col in self.pmdata]
        # remove old Pmplot
        old_point = self.plot_mpmap.select(name="PMplot")
        if len(old_point)>0:
            self.plot_mpmap.renderers.remove(old_point[0])
        self.plot_mpmap.square(x, y, size=5, color=None, alpha=0.5, line_color='black',name="PMplot")


    def get_sample_list(self, attr, old_file, new_file):
        f = io.BytesIO(b64decode(new_file))
        samplelist = np.loadtxt(f, skiprows=2, delimiter=",")
        self.vis.print_message(samplelist)
        samplestr = ''
        for sample in samplelist:
            samplestr += str(int(sample)) + ','
        if samplestr.endswith(','):
            samplestr = samplestr[:-1]
        self.vis.print_message(samplestr)
        self.vis.doc.add_next_tick_callback(partial(self.update_samples,samplestr))


    def get_pm(self, plateid):
        """"gets plate map from aligner server"""
        #simple one for tests is plateid = '4534'
        self.pmdata = json.loads(self.dataAPI.get_platemap_plateid(plateid))
        if len(self.pmdata) == 0:
            self.vis.doc.add_next_tick_callback(partial(self.update_error,"no pm found"))
        self.vis.doc.add_next_tick_callback(partial(self.update_pm_plot))

    
    def xy_to_sample(self, xy, pmapxy):
        '''get point from pmap closest to xy'''
        if len(pmapxy):
            diff = pmapxy - xy
            sumdiff = (diff ** 2).sum(axis=1)
            return np.int(np.argmin(sumdiff))
        else:
            return None
    
    
    def get_samples(self, X, Y):
        '''get list of samples row number closest to xy'''
        # X and Y are vectors
        xyarr = np.array((X, Y)).T
        pmxy = np.array([[col['x'], col['y']] for col in self.pmdata])
        samples = list(np.apply_along_axis(self.xy_to_sample, 1, xyarr, pmxy))
        return samples             


    def get_elements_plateid(self, plateid: int):
        '''gets plate elements from aligner server'''
        elements =  self.dataAPI.get_elements_plateid(
            plateid,
            multielementink_concentrationinfo_bool=False,
            print_key_or_keyword="screening_print_id",
            exclude_elements_list=[""],
            return_defaults_if_none=False)
        if elements is not None:
            self.vis.doc.add_next_tick_callback(partial(self.update_elements, elements))


    def get_sample_infos(self, PMnum: List = None):
        self.vis.print_message(" ... updating samples")
        buf = ""
        if PMnum is not None and self.pmdata:
            if PMnum[0] is not None: # need to check as this can also happen
                self.vis.print_message(f" ... selected sampleid: {PMnum[0]}")
                if PMnum[0] > len(self.pmdata):
                    self.vis.print_message(" ... invalid sample no")
                    self.vis.doc.add_next_tick_callback(partial(self.update_samples,""))
                    return False
                
                platex = self.pmdata[PMnum[0]]['x']
                platey = self.pmdata[PMnum[0]]['y']
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
                old_point = self.plot_mpmap.select(name='selsample')
                if len(old_point)>0:
                    self.plot_mpmap.renderers.remove(old_point[0])
                # plot new Marker point
                self.plot_mpmap.square(platex, platey, size=7,line_width=2, color=None, alpha=1.0, line_color=(255,0,0), name='selsample')
                return True

        return False



    async def update_tables(self):
        await self.get_process_groups()
        await self.get_processes()
        await self.get_active_processes()



        self.columns_dec = [TableColumn(field=key, title=key) for key in self.process_group_list.keys()]
        self.process_group_table.source.data = self.process_group_list
        self.process_group_table.columns=self.columns_dec

        self.columns_process = [TableColumn(field=key, title=key) for key in self.process_list.keys()]
        self.process_table.source.data=self.process_list
        self.process_table.columns=self.columns_process

        self.columns_active_process = [TableColumn(field=key, title=key) for key in self.active_process_list.keys()]
        self.active_process_table.source.data=self.active_process_list
        self.active_process_table.columns=self.columns_active_process



    async def IOloop(self):
        # should maybe update it do ws later instead of polling once orch2 is ready
        # itr seems when orch is in dispatch loop this here is not updating
        await self.update_tables()





def makeBokehApp(doc, confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config

    app = makeVisServ(
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

    # this periodically updates the GUI (process and process_group tables)
    # operator.vis.doc.add_periodic_callback(operator.IOloop,2000) # time in ms

    return doc
