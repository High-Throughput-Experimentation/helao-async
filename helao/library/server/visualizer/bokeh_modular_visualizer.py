from importlib import import_module

from helao.core.server import makeVisServ
# from helao.core.server import Action, setupAct





import os
# import sys
import websockets
import asyncio
import json
import collections
from functools import partial
# from importlib import import_module
# from functools import partial


from bokeh.models import ColumnDataSource, CheckboxButtonGroup, RadioButtonGroup
# from bokeh.models import Title, DataTable, TableColumn
from bokeh.models.widgets import Paragraph
from bokeh.plotting import figure, curdoc
# from bokeh.models import Range1d
# from bokeh.models import Arrow, NormalHead, OpenHead, VeeHead
# #from tornado.ioloop import IOLoop
# from munch import munchify
from bokeh.palettes import Spectral6, small_palettes
# from bokeh.transform import linear_cmap

# from bokeh.models import TextInput
from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer
# import pathlib
# import copy
# import math


# ##############################################################################
# # motor module class
# ##############################################################################
# class C_motorvis:
#     def __init__(self, config):
#         self.config = config
#         self.data_url = config['wsdata_url']
#         self.stat_url = config['wsstat_url']
#         self.IOloop_data_run = False
#         self.axis_id = config['axis_id']
#         self.params = config['params']

#         self.data = dict()
#         # buffered version
#         self.dataold = copy.deepcopy(self.data)

#         # create visual elements
#         self.layout = []
#         self.motorlayout_axis = []
#         self.motorlayout_stat = []
#         self.motorlayout_err = []
#         # display of axis positions and status
#         self.axisvaldisp = []
#         self.axisstatdisp = []
#         self.axiserrdisp = []
#         tmpidx = 0
#         for axkey, axitem in self.axis_id.items():
#             self.axisvaldisp.append(TextInput(value="", title=axkey+"(mm)", disabled=True, width=100, height=40, css_classes=['custom_input2']))
#             self.motorlayout_axis.append(layout([[self.axisvaldisp[tmpidx],Spacer(width=40)]]))
#             self.axisstatdisp.append(TextInput(value="", title=axkey+" status", disabled=True, width=100, height=40, css_classes=['custom_input2']))
#             self.motorlayout_stat.append(layout([[self.axisstatdisp[tmpidx],Spacer(width=40)]]))
#             self.axiserrdisp.append(TextInput(value="", title=axkey+" Error code", disabled=True, width=100, height=40, css_classes=['custom_input2']))
#             self.motorlayout_err.append(layout([[self.axiserrdisp[tmpidx],Spacer(width=40)]]))
#             tmpidx = tmpidx+1

#         # add a 2D map for xy
#         ratio = (self.params['xmax']-self.params['xmin'])/(self.params['ymax']-self.params['ymin'])
#         self.plot_motor = figure(title="xy MotorPlot", height=300,x_axis_label='plate X (mm)', y_axis_label='plate Y (mm)',width = 800, aspect_ratio=ratio)
#         self.plot_motor.x_range=Range1d(self.params['xmin'], self.params['xmax'])
#         self.plot_motor.y_range=Range1d(self.params['ymin'], self.params['ymax'])

#         # combine all sublayouts into a single one
#         self.layout = layout([
#             [Spacer(width=20), Div(text="<b>Motor Visualizer module</b>", width=200+50, height=15)],
#             layout([self.motorlayout_axis]),
#             Spacer(height=10),
#             layout([self.motorlayout_stat]),
#             Spacer(height=10),
#             layout([self.motorlayout_err]),
#             Spacer(height=10),
#             layout([self.plot_motor]),
#             Spacer(height=10)
#             ],background="#C0C0C0")


#     async def IOloop_data(self): # non-blocking coroutine, updates data source
#         async with websockets.connect(self.data_url) as ws:
#             self.IOloop_data_run = True
#             while self.IOloop_data_run:
#                 try:
#                     self.data =  await ws.recv()
#                     print(" ... VisulizerWSrcv:",self.data)
#                 except Exception:
#                     self.IOloop_data_run = False


class C_nidaqmxvis:
    """NImax visualizer module class"""
    def __init__(self, app):
        self.app = app

        nidaqmx_key = self.app.srv_config["ws_nidaqmx"]
        potserv_config = self.app.helao_cfg["servers"][nidaqmx_key]
        self.data_url = f"ws://{potserv_config['host']}:{potserv_config['port']}/ws_data"
        # self.stat_url = f"ws://{potserv_config['host']}:{potserv_config['port']}/ws_status"



        # self.dataset_url = config['wsdataset_url']
        self.IOloop_data_run = False
        self.IOloop_dataset_run = False

        self.time_stamp = 0
        self.IVlist = {}
        self.activeCell = [True for _ in range(9)]


        datadict = dict(
                       t_s=[],
                       ICell1_A=[],
                       ICell2_A=[],
                       ICell3_A=[],
                       ICell4_A=[],
                       ICell5_A=[],
                       ICell6_A=[],
                       ICell7_A=[],
                       ICell8_A=[],
                       ICell9_A=[],
                       ECell1_V=[],
                       ECell2_V=[],
                       ECell3_V=[],
                       ECell4_V=[],
                       ECell5_V=[],
                       ECell6_V=[],
                       ECell7_V=[],
                       ECell8_V=[],
                       ECell9_V=[]
                       )

        self.sourceIV = ColumnDataSource(data=datadict)
        self.sourceIV_prev = ColumnDataSource(data=datadict)

        self.cur_action_id = ""
        self.prev_action_id = ""

        # create visual elements
        self.layout = []
        
        self.paragraph1 = Paragraph(text="""cells:""", width=50, height=15)
        self.checkbox_button_group = CheckboxButtonGroup(
                                    labels=[f"{i+1}" for i in range(9)], 
                                    active=[i for i in range(9)]
                                    )
        
        
        self.plot_VOLT = figure(title="CELL VOLTs", height=300)
        self.plot_CURRENT = figure(title="CELL CURRENTs", height=300)

        self.plot_VOLT_prev = figure(title="prev. CELL VOLTs", height=300)
        self.plot_CURRENT_prev = figure(title="prev. CELL CURRENTs", height=300)

        self.reset_plot()

        # combine all sublayouts into a single one
        self.layout = layout([
            [Spacer(width=20), Div(text="<b>NImax Visualizer module</b>", width=200+50, height=15)],
            [self.paragraph1],
            [self.checkbox_button_group],
            Spacer(height=10),
            [self.plot_VOLT, self.plot_VOLT_prev],
            Spacer(height=10),
            [self.plot_CURRENT, self.plot_CURRENT_prev],
            Spacer(height=10)
            ],background="#C0C0C0")

        self.app.doc.add_root(self.layout)
        self.app.doc.add_root(Spacer(height=10))


    def add_points(self, new_data):
        new_action_id = list(new_data)[0]

        if (new_action_id != self.cur_action_id):
            self.prev_action_id = self.cur_action_id
            self.cur_action_id = new_action_id
            self.reset_plot()

        data_dict = new_data[new_action_id]["data"]
        self.sourceIV_prev.data = {key: val for key, val in self.sourceIV.data.items()}        
        self.sourceIV.data = {k: [] for k in self.sourceIV.data}
        self.sourceIV.stream(data_dict)


    async def IOloop_data(self): # non-blocking coroutine, updates data source
        async with websockets.connect(self.data_url) as ws:
            self.IOloop_data_run = True
            while self.IOloop_data_run:
                try:
                    new_data = json.loads(await ws.recv())
                    self.app.doc.add_next_tick_callback(partial(self.add_points, new_data))
                except Exception:
                    self.IOloop_data_run = False


    def reset_plot(self):
        # remove all old lines and clear legend
        if self.plot_VOLT.renderers:
            self.plot_VOLT.legend.items = []

        if self.plot_CURRENT.renderers:
            self.plot_CURRENT.legend.items = []


        if self.plot_VOLT_prev.renderers:
            self.plot_VOLT_prev.legend.items = []

        if self.plot_CURRENT_prev.renderers:
            self.plot_CURRENT_prev.legend.items = []
            
        self.plot_VOLT.renderers = []
        self.plot_CURRENT.renderers = []

        self.plot_VOLT_prev.renderers = []
        self.plot_CURRENT_prev.renderers = []
        

        self.plot_VOLT.title.text = ("Action_ID: "+self.cur_action_id)
        self.plot_VOLT.title.text = ("Action_ID: "+self.cur_action_id)
        # self.plot_VOLT_prev.title.text = ("Action_ID: "+self.prev_action_id)
        # self.plot_VOLT_prev.title.text = ("Action_ID: "+self.prev_action_id)


        colors = small_palettes['Category10'][9]
        for i in self.checkbox_button_group.active:
            _ = self.plot_VOLT.line(x='t_s', y=f'ECell{i+1}_V', source=self.sourceIV, name=f'ECell{i+1}_V', line_color=colors[i], legend_label=f'ECell{i+1}_V')
            _ = self.plot_CURRENT.line(x='t_s', y=f'ICell{i+1}_A', source=self.sourceIV, name=f'ICell{i+1}_A', line_color=colors[i], legend_label=f'ICell{i+1}_A')
            _ = self.plot_VOLT_prev.line(x='t_s', y=f'ECell{i+1}_V', source=self.sourceIV_prev, name=f'ECell{i+1}_V', line_color=colors[i], legend_label=f'ECell{i+1}_V')
            _ = self.plot_CURRENT_prev.line(x='t_s', y=f'ICell{i+1}_A', source=self.sourceIV_prev, name=f'ICell{i+1}_A', line_color=colors[i], legend_label=f'ICell{i+1}_A')


class C_potvis:
    """potentiostat visualizer module class"""
    def __init__(self, app):
        self.app = app

        potentiostat_key = self.app.srv_config["ws_potentiostat"]
        potserv_config = self.app.helao_cfg["servers"][potentiostat_key]
        self.data_url = f"ws://{potserv_config['host']}:{potserv_config['port']}/ws_data"
        # self.stat_url = f"ws://{potserv_config['host']}:{potserv_config['port']}/ws_status"



        self.IOloop_data_run = False
        self.IOloop_stat_run = False

        self.datasource = ColumnDataSource(data=dict(pt=[], t_s=[], Ewe_V=[], Ach_V=[], I_A=[]))
        self.datasource_prev = ColumnDataSource(data=dict(pt=[], t_s=[], Ewe_V=[], Ach_V=[], I_A=[]))
        self.cur_action_id = ""
        self.prev_action_id = ""
 
        # create visual elements
        self.layout = []


        self.paragraph1 = Paragraph(text="""x-axis:""", width=50, height=15)
        self.radio_button_group = RadioButtonGroup(labels=["t_s", "Ewe_V", "Ach_V", "I_A"], active=0)
        self.paragraph2 = Paragraph(text="""y-axis:""", width=50, height=15)
        self.checkbox_button_group = CheckboxButtonGroup(labels=["t_s", "Ewe_V", "Ach_V", "I_A"], active=[1,3])
        
        
        self.plot = figure(title="Title", height=300)


        self.plot_prev = figure(title="Title", height=300)

        # combine all sublayouts into a single one
        self.layout = layout([
            [Spacer(width=20), Div(text="<b>Potentiostat Visualizer module</b>", width=200+50, height=15)],
            [self.paragraph1],
            [self.radio_button_group],
            [self.paragraph2],
            [self.checkbox_button_group],
            Spacer(height=10),
            [self.plot, self.plot_prev],
            Spacer(height=10)
            ],background="#C0C0C0")

        # to check if selection changed during ploting
        self.xselect = self.radio_button_group.active
        self.yselect = self.checkbox_button_group.active


        self.app.doc.add_root(self.layout)
        self.app.doc.add_root(Spacer(height=10))


    def add_points(self, new_data):
        # if len(new_data):
        new_action_id = list(new_data)[0]

        # detect if plot selection changed
        if  (self.xselect != self.radio_button_group.active) or (self.yselect != self.checkbox_button_group.active):
            self.xselect = self.radio_button_group.active
            self.yselect = self.checkbox_button_group.active
            # use current(old) timestamp but force update via optional
            # second parameter
            self.reset_plot(new_action_id,True)
        else:
            self.reset_plot(new_action_id)
        
        
        tmpdata = {'pt':[0]}
        # for some techniques not all data is present
        # we should only get one data point at the time
        data_dict = new_data[new_action_id]["data"]
        tmpdata["t_s"] = data_dict.get("t_s", [0])
        tmpdata["Ewe_V"] = data_dict.get("Ewe_V", [0])
        tmpdata["Ach_V"] = data_dict.get("Ach_V", [0])
        tmpdata["I_A"] = data_dict.get("I_A", [0])

        # print(tmpdata)

        self.datasource.stream(tmpdata)


    async def IOloop_data(self): # non-blocking coroutine, updates data source
        # global doc
        print(" ... potentiostat visualizer subscribing to:", self.data_url)
        async with websockets.connect(self.data_url) as ws:
            self.IOloop_data_run = True
            while self.IOloop_data_run:
                try:
                    new_data = json.loads(await ws.recv())
                    # print(' ... new data for potentiostat visualizer module:')
                    # print(new_data)
                    if new_data is not None:
                        self.app.doc.add_next_tick_callback(partial(self.add_points, new_data))
                except Exception:
                    self.IOloop_data_run = False

    
    def reset_plot(self, new_action_id, forceupdate: bool = False):
        if (new_action_id != self.cur_action_id) or forceupdate:
            print(' ... reseting Gamry graph')
            # copy old data to 'prev' plot
            self.prev_action_id = self.cur_action_id
            self.datasource_prev.data = {key: val for key, val in self.datasource.data.items()}
            self.cur_action_id = new_action_id
        
            self.datasource.data = {k: [] for k in self.datasource.data}
            # remove all old lines
            self.plot.renderers = []
            self.plot_prev.renderers = []
    
            
            self.plot.title.text = ("Action_ID: "+self.cur_action_id)
            self.plot_prev.title.text = ("Action_ID: "+self.prev_action_id)
            xstr = ''
            if(self.radio_button_group.active == 0):
                xstr = 't_s'
            elif(self.radio_button_group.active == 1):
                xstr = 'Ewe_V'
            elif(self.radio_button_group.active == 2):
                xstr = 'Ach_V'
            else:
                xstr = 'I_A'
            colors = ['red', 'blue', 'yellow', 'green']
            color_count = 0
            for i in self.checkbox_button_group.active:
                if i == 0:
                    self.plot.line(x=xstr, y='t_s', line_color=colors[color_count], source=self.datasource, name=self.cur_action_id)
                    self.plot_prev.line(x=xstr, y='t_s', line_color=colors[color_count], source=self.datasource_prev, name=self.prev_action_id)
                elif i == 1:
                    self.plot.line(x=xstr, y='Ewe_V', line_color=colors[color_count], source=self.datasource, name=self.cur_action_id)
                    self.plot_prev.line(x=xstr, y='Ewe_V', line_color=colors[color_count], source=self.datasource_prev, name=self.prev_action_id)
                elif i == 2:
                    self.plot.line(x=xstr, y='Ach_V', line_color=colors[color_count], source=self.datasource, name=self.cur_action_id)
                    self.plot_prev.line(x=xstr, y='Ach_V', line_color=colors[color_count], source=self.datasource_prev, name=self.prev_action_id)
                else:
                    self.plot.line(x=xstr, y='I_A', line_color=colors[color_count], source=self.datasource, name=self.cur_action_id)
                    self.plot_prev.line(x=xstr, y='I_A', line_color=colors[color_count], source=self.datasource_prev, name=self.prev_action_id)
                color_count += 1
   


# ##############################################################################
# # job queue module class
# # for visualizing the content of the orch queue (with params), just a simple table
# # TODO: work in progress
# ##############################################################################
# class C_jobvis:
#     def __init__(self, config):
#         self.config = config
#         self.data_url = config['wsdata_url']
#         self.stat_url = config['wsstat_url']


# ##############################################################################
# # data module class
# ##############################################################################
# class C_datavis:
#     def __init__(self, config):
#         self.config = config
#         self.data_url = config['wsdata_url']
#         self.stat_url = config['wsstat_url']
#         self.data = dict()
#         # buffered version
#         self.dataold = copy.deepcopy(self.data)
        
        
#     async def IOloop_data(self): # non-blocking coroutine, updates data source
#         async with websockets.connect(self.data_url) as ws:
#             self.IOloop_data_run = True
#             while self.IOloop_data_run:
#                 try:
#                     self.data =  await ws.recv()
#                     print(" ... VisulizerWSrcv: pm data")
#                 except Exception:
#                     self.IOloop_data_run = False


# ##############################################################################
# # update loop for visualizer document
# ##############################################################################
# async def IOloop_visualizer():
#     pass
#     # update if motor is present
#     if datavis:
#         if datavis.data:
#             # update only if changed
#             if not datavis.data == datavis.dataold:
#                 datavis.dataold = copy.deepcopy(datavis.data)
#                 pmdata = json.loads(datavis.data)['map']
#                 # plot only if motorvis is active
#                 if motorvis:
#                     x = [col['x'] for col in pmdata]
#                     y = [col['y'] for col in pmdata]
#                     # remove old Pmplot
#                     old_point = motorvis.plot_motor.select(name="PMplot")
#                     if len(old_point)>0:
#                         motorvis.plot_motor.renderers.remove(old_point[0])
#                     motorvis.plot_motor.square(x, y, size=5, color=None, alpha=0.5, line_color='black',name="PMplot")

            
#     if motorvis:
#         MarkerColors = [(255,0,0),(0,0,255),(0,255,0),(255,165,0),(255,105,180)]
#         if motorvis.data:
#             # update only if changed
#             if not motorvis.data == motorvis.dataold:
#                 motorvis.dataold = copy.deepcopy(motorvis.data)
#                 tmpmotordata = json.loads(motorvis.data)                
#                 for idx in range(len(motorvis.axisvaldisp)):
#                     motorvis.axisvaldisp[idx].value = (str)(tmpmotordata['position'][idx])
#                     motorvis.axisstatdisp[idx].value = (str)(tmpmotordata['motor_status'][idx])
#                     motorvis.axiserrdisp[idx].value = (str)(tmpmotordata['err_code'][idx])
#                 # check if x and y motor is present and plot it
#                 pangle = 0.0
#                 if 'Rz' in tmpmotordata['axis']:
#                     pangle = tmpmotordata['position'][tmpmotordata['axis'].index('Rz')]
#                     pangle = math.pi/180.0*pangle # TODO
# #                if 'x' in tmpmotordata['axis'] and 'y' in tmpmotordata['axis']:
# #                    ptx = tmpmotordata['position'][tmpmotordata['axis'].index('x')]
# #                    pty = tmpmotordata['position'][tmpmotordata['axis'].index('y')]
#                 if 'platexy' in tmpmotordata:
#                     ptx = tmpmotordata['platexy'][0]
#                     pty = tmpmotordata['platexy'][1]
                    
#                     # update plot
#                     old_point = motorvis.plot_motor.select(name='motor_xy')
#                     if len(old_point)>0:
#                         for oldpoint in old_point:
#                             motorvis.plot_motor.renderers.remove(oldpoint)

#                     motorvis.plot_motor.rect(6.0*25.4/2,  4.0*25.4/2.0, width = 6.0*25.4, height = 4.0*25.4, angle = 0.0, angle_units='rad', fill_alpha=0.0, fill_color='gray', line_width=2, alpha=1.0, line_color=(0,0,0), name='motor_xy')
#                     # plot new Marker point
#                     if S.params.ws_motor_params.sample_marker_type == 0:
#                         # standard square marker
#                         motorvis.plot_motor.square(ptx, pty, size=7,line_width=2, color=None, alpha=1.0, line_color=MarkerColors[0], name='motor_xy')

#                     elif S.params.ws_motor_params.sample_marker_type == 1: # RSHS
#                         # marker symbold for ANEC2, need exact dimensions for final marker
#                         sample_size = 5
#                         sample_spacing = 0.425*25.4
#                         sample_count = 9;
#                         # the square box
#                         motorvis.plot_motor.rect(ptx, pty, width = sample_size+10, height = (sample_count-1)*sample_spacing+10, angle = -1.0*pangle, angle_units='rad', fill_alpha=0.0, fill_color='gray', line_width=2, alpha=1.0, line_color=(255,0,0), name='motor_xy')
#                         # and the different sample circles
#                         motorvis.plot_motor.ellipse(ptx, pty, width = sample_size, height = sample_size, fill_alpha=0.0, fill_color=None, line_width=2, alpha=1.0, line_color=(0,0,255), name='motor_xy')
#                         for i in range(1,(int)((sample_count-1)/2)+1):
#                             motorvis.plot_motor.ellipse(ptx+i*sample_spacing*math.sin(pangle), pty+i*sample_spacing*math.cos(pangle), width = sample_size, height = sample_size, fill_alpha=0.0, fill_color='gray', line_width=2, alpha=1.0, line_color=(255,0,0), name='motor_xy')
#                             motorvis.plot_motor.ellipse(ptx-i*sample_spacing*math.sin(pangle), pty-i*sample_spacing*math.cos(pangle), width = sample_size, height = sample_size, fill_alpha=0.0, fill_color='gray', line_width=2, alpha=1.0, line_color=(255,0,0), name='motor_xy')



def makeBokehApp(doc, confPrefix, servKey):

    config = import_module(f"helao.config.{confPrefix}").config

    app = makeVisServ(
        config,
        servKey,
        doc,
        servKey,
        "Modular Visualizer",
        version=2.0,
        driver_class=None,
    )




    # is there any better way to inlcude external CSS? 
    # css_styles = Div(text="""<style>%s</style>""" % pathlib.Path(os.path.join(helao_root, 'visualizer\styles.css')).read_text())
    # doc.add_root(css_styles)

    visoloop = asyncio.get_event_loop()
    


    # create visualizer objects for defined instruments

    if 'ws_potentiostat' in app.srv_config:
        potvis = C_potvis(app)
        visoloop.create_task(potvis.IOloop_data())
        # visoloop.create_task(potvis.IOloop_stat())
    else:
        print('No potentiostat visualizer configured')
        potvis = []


    if 'ws_nidaqmx' in app.srv_config:
        NImaxvis = C_nidaqmxvis(app)
        visoloop.create_task(NImaxvis.IOloop_data())
    else:
        print('No NImax visualizer configured')
        NImaxvis = []


# if 'ws_data' in S.params:
#     tmpserv = S.params.ws_data
#     dataserv['serv'] = tmpserv
#     dataserv['wsdata_url'] = f"ws://{C[tmpserv].host}:{C[tmpserv].port}/{tmpserv}/ws_data"
#     dataserv['wsstat_url'] = f"ws://{C[tmpserv].host}:{C[tmpserv].port}/{tmpserv}/ws_status"
#     print(f"Create Visualizer for {dataserv['serv']}")
#     datavis = C_datavis(dataserv)
#     visoloop.create_task(datavis.IOloop_data())
# else:
#     print('No data visualizer configured')
#     datavis = []

# if 'ws_motor' in S.params:    
#     tmpserv = S.params.ws_motor
#     motorserv['serv'] = tmpserv
#     motorserv['params']  = S.params.ws_motor_params
#     motorserv['axis_id'] = C[tmpserv].params.axis_id
#     motorserv['wsdata_url'] = f"ws://{C[tmpserv].host}:{C[tmpserv].port}/{tmpserv}/ws_motordata"
#     motorserv['wsstat_url'] = f"ws://{C[tmpserv].host}:{C[tmpserv].port}/{tmpserv}/ws_status"
#     if not 'sample_marker_type' in S.params.ws_motor_params:
#         S.params.ws_motor_params.sample_marker_type = 0
#     print(f"Create Visualizer for {motorserv['serv']}")
#     motorvis = C_motorvis(motorserv)
#     doc.add_root(layout([motorvis.layout]))
#     doc.add_root(layout(Spacer(height=10)))
#     visoloop.create_task(motorvis.IOloop_data())
# else:
#     print('No motor visualizer configured')
#     motorvis = []



    # web interface update loop
    # todo put his in the respective classes?
    # app.doc.add_periodic_callback(IOloop_visualizer,500) # time in ms

    return doc
