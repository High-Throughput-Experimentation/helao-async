
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
from helao.core.server import import_actualizers, async_private_dispatcher
# from helao.core.data import liquid_sample_no_API
from helao.core.data import HTE_legacy_API
from helao.core.schema import Action, Decision


class return_actlib(BaseModel):
    """Return class for queried actualizer objects."""
    index: int
    action: str
    doc: str
    args: list
    defaults: list
    #annotations: dict()
    # defaults: list
    #argcount: int
    #params: list


class C_async_operator:
    def __init__(self, app):
        self.app = app

        self.dataAPI = HTE_legacy_API()


        self.orch_name = self.app.srv_config["orch"]
        
        self.pmdata = []
        

        # holds the page layout
        self.layout = []
        self.param_layout = []
        self.param_input = []

        self.decision_list = dict()
        self.action_list = dict()

        self.act_select_list = []
        self.actualizers = []
        self.action_lib = import_actualizers(world_config_dict = self.app.world_cfg, library_path = None)



        # FastAPI calls
        self.get_actualizers()
        self.app.doc.add_next_tick_callback(partial(self.get_decisions))
        self.app.doc.add_next_tick_callback(partial(self.get_actions))

        #print([key for key in self.decision_list.keys()])
        self.decision_source = ColumnDataSource(data=self.decision_list)
        self.columns_dec = [TableColumn(field=key, title=key) for key in self.decision_list.keys()]
        self.decision_table = DataTable(source=self.decision_source, columns=self.columns_dec, width=620, height=200)

        self.action_source = ColumnDataSource(data=self.action_list)
        self.columns_act = [TableColumn(field=key, title=key) for key in self.action_list.keys()]
        self.action_table = DataTable(source=self.action_source, columns=self.columns_act, width=620, height=200)




        self.actions_dropdown = Select(title="Select actualizer:", value = None, options=self.act_select_list)
        self.actions_dropdown.on_change('value', self.callback_act_select)

        self.button_load_sample_list = FileInput(accept=".csv,.txt", width = 300)
        self.button_load_sample_list.on_change('value', self.get_sample_list)


        # buttons to control orch
        self.button_start = Button(label="Start", button_type="default", width=70)
        self.button_start.on_event(ButtonClick, self.callback_start)
        self.button_stop = Button(label="Stop", button_type="default", width=70)
        self.button_stop.on_event(ButtonClick, self.callback_stop)
        self.button_skip = Button(label="Skip", button_type="danger", width=70)
        self.button_skip.on_event(ButtonClick, self.callback_skip_dec)

        self.button_clear_dec = Button(label="clear decisions", button_type="danger", width=100)
        self.button_clear_dec.on_event(ButtonClick, self.callback_clear_decisions)
        self.button_clear_act = Button(label="clear actions", button_type="danger", width=100)
        self.button_clear_act.on_event(ButtonClick, self.callback_clear_actions)

        self.button_prepend = Button(label="prepend", button_type="default", width=150)
        self.button_prepend.on_event(ButtonClick, self.callback_prepend)
        self.button_append = Button(label="append", button_type="default", width=150)
        self.button_append.on_event(ButtonClick, self.callback_append)




        self.act_descr_txt = Paragraph(text="""select item""", width=600, height=30)


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



        self.layout0 = layout([
            layout(
                [Spacer(width=20), Div(text=f"<b>{self.app.srv_config['doc_name']}</b>", width=200+50, height=15, style={'font-size': '200%', 'color': 'red'})],
                background="#C0C0C0",width=640),
            layout([
                [self.actions_dropdown],
                [Spacer(width=10), Div(text="<b>Actualizer description:</b>", width=200+50, height=15)],
                [self.act_descr_txt],
                Spacer(height=10),
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
                [Spacer(width=20), Div(text="<b>Decisions:</b>", width=200+50, height=15)],
                [self.decision_table],
                [Spacer(width=20), Div(text="<b>Actions:</b>", width=200+50, height=15)],
                [self.action_table],
                Spacer(height=10),
                [self.button_skip, Spacer(width=5), self.button_clear_dec, Spacer(width=5), self.button_clear_act],
                Spacer(height=10),
                ],background="#7fdbff",width=640),
            ])


        self.dynamic_col = column(self.layout0, self.layout2)
        self.app.doc.add_root(self.dynamic_col)


        # select the first item to force an update of the layout
        if self.act_select_list:
            self.actions_dropdown.value = self.act_select_list[0]



    def get_actualizers(self):
        """Return the current list of ACTUALIZERS."""
        self.actualizers = []
        print('##############', self.action_lib)
        for i, act in enumerate(self.action_lib):
            print('full',inspect.getfullargspec(self.action_lib[act]))
            #print('anno',inspect.getfullargspec(self.action_lib[act]).annotations)
            #print('def',inspect.getfullargspec(self.action_lib[act]).defaults)
            tmpdoc = self.action_lib[act].__doc__ 
            print("... doc:", tmpdoc)
            if tmpdoc == None:
                tmpdoc = ""
            tmpargs = inspect.getfullargspec(self.action_lib[act]).args
            tmpdef = inspect.getfullargspec(self.action_lib[act]).defaults
            if tmpdef == None:
                tmpdef = []
            # if not tmpargs:
            #     tmpargs = ['']
            
            
            self.actualizers.append(return_actlib(
                index=i,
                action = act,
                doc = tmpdoc,#self.action_lib[act].__doc__ if self.action_lib[act].__doc__ not None else "",
                args = tmpargs,#{},
                defaults = tmpdef,
                #annotations = inspect.getfullargspec(self.action_lib[act]).annotations,
                # defaults = inspect.getfullargspec(self.action_lib[act]).defaults,
               #params = '',
            ).dict()
                )

        for item in self.actualizers:
            self.act_select_list.append(item['action'])


    async def get_decisions(self):
        '''get decision list from orch'''
        response = await self.do_orch_request(action_name = "list_decisions")
        response = response["decisions"]
        self.decision_list = dict()
        if len(response):
            for key in response[0].keys():
                self.decision_list[key] = []
            for line in response:
                for key, value in line.items():
                    self.decision_list[key].append(value)
        print(' ... current active decisions:',self.decision_list)


    async def get_actions(self):
        '''get action list from orch'''
        response = await self.do_orch_request(action_name = "list_actions")
        response = response["actions"]
        self.action_list = dict()
        if len(response):
            for key in response[0].keys():
                self.action_list[key] = []
        print(' ... current active actions:',self.action_list)


    async def do_orch_request(self,action_name, 
                              params_dict: dict = {},
                              json_dict: dict = {}
                              ):
        """submit a FastAPI request to orch"""
    

        response = await async_private_dispatcher(
            world_config_dict = self.app.world_cfg, 
            server = self.orch_name,
            private_action = action_name,
            params_dict = params_dict,
            json_dict = json_dict
            )
            
        return response



    def callback_act_select(self, attr, old, new):
        idx = self.act_select_list.index(new)
        act_doc = self.actualizers[idx]['doc']
        # for arg in self.actualizers[idx]['args']:
        #     print(arg)
        self.update_param_layout(self.actualizers[idx]['args'], self.actualizers[idx]['defaults'])
        self.app.doc.add_next_tick_callback(partial(self.update_doc,act_doc))


    def callback_clicked_pmplot(self, event):
        """double click/tap on PM plot to add/move marker"""
        print("DOUBLE TAP PMplot")
        print(event.x, event.y)
        # get coordinates of doubleclick
        platex = event.x
        platey = event.y
        # transform to nearest sample point
        PMnum = self.get_samples([platex], [platey])
        self.get_sample_infos(PMnum)


    def callback_changed_plateid(self, attr, old, new):
        self.get_pm(new)
        self.get_elements_plateid(new)


    def callback_changed_sampleno(self, attr, old, new):
        def to_int(val):
            try:
                return int(val)
            except Exception:
                return None

        sample_no = to_int(new)
        if sample_no is not None:
            self.get_sample_infos([sample_no])
        else:
            self.app.doc.add_next_tick_callback(partial(self.update_samples,""))


    def callback_start(self, event):
        print(' ... starting orch')
        self.app.doc.add_next_tick_callback(partial(self.do_orch_request,"start"))


    def callback_stop(self, event):
        print(' ... stopping operator orch')
        self.app.doc.add_next_tick_callback(partial(self.do_orch_request,"stop"))


    def callback_skip_dec(self, event):
        print(' ... skipping decision')
        self.app.doc.add_next_tick_callback(partial(self.do_orch_request,"skip"))


    def callback_clear_decisions(self, event):
        print(' ... clearing decisions')
        self.app.doc.add_next_tick_callback(partial(self.do_orch_request,"clear_decisions"))


    def callback_clear_actions(self, event):
        print(' ... clearing actions')
        self.app.doc.add_next_tick_callback(partial(self.do_orch_request,"clear_actions"))


    def callback_prepend(self, event):
        self.prepend_action()
        self.app.doc.add_next_tick_callback(partial(self.update_tables))



    def callback_append(self, event):
        self.append_action()
        self.app.doc.add_next_tick_callback(partial(self.update_tables))


    def append_action(self):
        params_dict, json_dict = self.populate_action()
        # print("pop acction##############################################################")
        # print(params)
        # print("##############################################################")
        # submit decission to orchestrator
        self.app.doc.add_next_tick_callback(partial(self.do_orch_request,"append_decision", params_dict, json_dict))


    def prepend_action(self):
        params_dict, json_dict = self.populate_action()
        # submit decission to orchestrator
        self.app.doc.add_next_tick_callback(partial(self.do_orch_request,"prepend_decision", params_dict, json_dict))


    def populate_action(self):
        selaction = self.actions_dropdown.value
        selplateid = self.input_plateid.value
        selsample = self.input_sampleno.value
        sellabel = self.input_label.value
        elements = self.input_elements.value
        code  = self.input_code.value
        composition = self.input_composition.value

        print(' ... selected action from list:', selaction)
        print(' ... selected plateid:', selplateid)
        print(' ... selected sample:', selsample)
        print(' ... selected label:', sellabel)


        actparams = {paraminput.title: paraminput.value for paraminput in self.param_input}

        D = Decision(inputdict={
            # "orch_name":orch_name,
            "decision_label":sellabel,
            "actualizer":selaction,
            "actualizer_pars":actparams,
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
            print(' ... action parameter:',args[idx])
            # skip the decisionObj parameter
            if args[idx] == 'decisionObj':
                continue

            self.param_input.append(TextInput(value=buf, title=args[idx], disabled=False, width=400, height=40))
            self.param_layout.append(layout([
                        [self.param_input[item]],
                        Spacer(height=10),
                        ]))
            item = item + 1

        self.dynamic_col.children.insert(-1, layout(self.param_layout))


    def update_doc(self, value):
        self.act_descr_txt.text = value


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
        print(samplelist)
        samplestr = ''
        for sample in samplelist:
            samplestr += str(int(sample)) + ','
        if samplestr.endswith(','):
            samplestr = samplestr[:-1]
        print(samplestr)
        self.app.doc.add_next_tick_callback(partial(self.update_samples,samplestr))


    def get_pm(self, plateid):
        """"gets plate map from aligner server"""
        #simple one for tests is plateid = '4534'
        self.pmdata = json.loads(self.dataAPI.get_platemap_plateid(plateid))
        self.app.doc.add_next_tick_callback(partial(self.update_pm_plot))

    
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
        self.app.doc.add_next_tick_callback(partial(self.update_elements, elements))


    def get_sample_infos(self, PMnum: List = None):
        print(" ... updating samples")
        buf = ""
        if PMnum is not None and self.pmdata:
            if PMnum[0] is not None: # need to check as this can also happen
                print(' ... selected sampleid:', PMnum[0])
                if PMnum[0] > len(self.pmdata):
                    print(" ... invalid sample no")
                    self.app.doc.add_next_tick_callback(partial(self.update_samples,""))
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
                self.app.doc.add_next_tick_callback(partial(self.update_samples,str(PMnum[0])))
                self.app.doc.add_next_tick_callback(partial(self.update_xysamples,str(platex), str(platey)))
                self.app.doc.add_next_tick_callback(partial(self.update_composition,buf))
                self.app.doc.add_next_tick_callback(partial(self.update_code,str(code)))

                # remove old Marker point
                old_point = self.plot_mpmap.select(name='selsample')
                if len(old_point)>0:
                    self.plot_mpmap.renderers.remove(old_point[0])
                # plot new Marker point
                self.plot_mpmap.square(platex, platey, size=7,line_width=2, color=None, alpha=1.0, line_color=(255,0,0), name='selsample')
                return True

        return False



    def update_tables(self):
        pass
    #     self.get_decisions()
    #     self.columns_dec = [TableColumn(field=key, title=key) for key in self.decision_list.keys()]
    #     self.decision_table.source.data = self.decision_list
    #     self.decision_table.columns=self.columns_dec

    #     self.get_actions()
    #     self.columns_act = [TableColumn(field=key, title=key) for key in self.action_list.keys()]
    #     self.action_table.source.data=self.action_list
    #     self.action_table.columns=self.columns_act


    # async def IOloop_visualizer(self):
    #     # should maybe update it do ws later instead of polling once orch2 is ready
    #     # itr seems when orch is in dispatch loop this here is not updating
    #     self.update_tables()





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


    operator = C_async_operator(app)
    # get the event loop
    operatorloop = asyncio.get_event_loop()



# # select the first item to force an update of the layout
# if operator.act_select_list:
#     operator.actions_dropdown.value = operator.act_select_list[0]

# # self.operator.app.doc.add_periodic_callback(operator.IOloop_visualizer,2000) # time in ms


    return doc
