
__all__ = ["makeBokehApp"]

from importlib import import_module




import websockets
import asyncio
import json
from functools import partial
from socket import gethostname
from uuid import UUID
from copy import deepcopy

from bokeh.models import (
                          ColumnDataSource,
                          CheckboxButtonGroup,
                          RadioButtonGroup,
                          TextInput
                         )
from bokeh.models.widgets import Paragraph
from bokeh.plotting import figure
from bokeh.palettes import small_palettes
from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer


from helaocore.model.data import DataPackageModel
from helaocore.server.make_vis_serv import makeVisServ
from helaocore.server.vis import Vis

# ##############################################################################
# # motor module class
# ##############################################################################
# class C_motorvis:
#     def __init__(self, config):
#         self.config = config
#         self.data_url = config["wsdata_url"]
#         self.stat_url = config["wsstat_url"]
#         self.IOloop_data_run = False
#         self.axis_id = config["axis_id"]
#         self.params = config["params"]

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
#             self.axisvaldisp.append(TextInput(value="", title=axkey+"(mm)", disabled=True, width=100, height=40, css_classes=["custom_input2"]))
#             self.motorlayout_axis.append(layout([[self.axisvaldisp[tmpidx],Spacer(width=40)]]))
#             self.axisstatdisp.append(TextInput(value="", title=axkey+" status", disabled=True, width=100, height=40, css_classes=["custom_input2"]))
#             self.motorlayout_stat.append(layout([[self.axisstatdisp[tmpidx],Spacer(width=40)]]))
#             self.axiserrdisp.append(TextInput(value="", title=axkey+" Error code", disabled=True, width=100, height=40, css_classes=["custom_input2"]))
#             self.motorlayout_err.append(layout([[self.axiserrdisp[tmpidx],Spacer(width=40)]]))
#             tmpidx = tmpidx+1

#         # add a 2D map for xy
#         ratio = (self.params["xmax"]-self.params["xmin"])/(self.params["ymax"]-self.params["ymin"])
#         self.plot_motor = figure(title="xy MotorPlot", height=300,x_axis_label="plate X (mm)", y_axis_label="plate Y (mm)",width = 800, aspect_ratio=ratio)
#         self.plot_motor.x_range=Range1d(self.params["xmin"], self.params["xmax"])
#         self.plot_motor.y_range=Range1d(self.params["ymin"], self.params["ymax"])

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
#                     self.vis.print_message(" ... VisulizerWSrcv:",self.data)
#                 except Exception:
#                     self.IOloop_data_run = False


class C_nidaqmxvis:
    """NImax visualizer module class"""
    def __init__(self, visServ: Vis, nidaqmx_key: str):
        self.vis = visServ
        self.config_dict = self.vis.server_cfg["params"]
        self.show = False

        nidaqmxserv_config = self.vis.world_cfg["servers"].get(nidaqmx_key, None)
        if nidaqmxserv_config is None:
            return
        nidaqmxserv_host = nidaqmxserv_config.get("host", None)
        nidaqmxserv_port = nidaqmxserv_config.get("port", None)
        
        self.show = True

        
        self.data_url = f"ws://{nidaqmxserv_config['host']}:{nidaqmxserv_config['port']}/ws_data"
        # self.stat_url = f"ws://{nidaqmxserv_config["host"]}:{nidaqmxserv_config["port"]}/ws_status"



        self.IOloop_data_run = False

        self.activeCell = [True for _ in range(9)]

        self.datakeys = ["t_s",
                    "Icell1_A",
                    "Icell2_A",
                    "Icell3_A",
                    "Icell4_A",
                    "Icell5_A",
                    "Icell6_A",
                    "Icell7_A",
                    "Icell8_A",
                    "Icell9_A",
                    "Ecell1_V",
                    "Ecell2_V",
                    "Ecell3_V",
                    "Ecell4_V",
                    "Ecell5_V",
                    "Ecell6_V",
                    "Ecell7_V",
                    "Ecell8_V",
                    "Ecell9_V"]


        datadict = {key:[] for key in self.datakeys}

        self.sourceIV = ColumnDataSource(data=datadict)
        self.sourceIV_prev = ColumnDataSource(data=datadict)

        self.cur_action_uuid = ""
        self.prev_action_uuid = ""

        # create visual elements
        self.layout = []
        
        self.paragraph1 = Paragraph(text="""cells:""", width=50, height=15)
        self.yaxis_selector_group = CheckboxButtonGroup(
                                    labels=[f"{i+1}" for i in range(9)], 
                                    active=[i for i in range(9)]
                                    )
        # to check if selection changed during ploting
        self.yselect = self.yaxis_selector_group.active
        
        
        self.plot_VOLT = figure(title="CELL VOLTs", height=300, width=500)
        self.plot_CURRENT = figure(title="CELL CURRENTs", height=300, width=500)

        self.plot_VOLT_prev = figure(title="prev. CELL VOLTs", height=300, width=500)
        self.plot_CURRENT_prev = figure(title="prev. CELL CURRENTs", height=300, width=500)

        self.reset_plot(self.cur_action_uuid, forceupdate= True)

        # combine all sublayouts into a single one
        self.layout = layout([
            [Spacer(width=20), Div(text=f'<b>NImax Visualizer module for server <a href="http://{nidaqmxserv_host}:{nidaqmxserv_port}/docs#/" target="_blank">\'{nidaqmx_key}\'</a></b>', width=1004, height=15)],
            [self.paragraph1],
            [self.yaxis_selector_group],
            Spacer(height=10),
            [self.plot_VOLT, self.plot_VOLT_prev],
            Spacer(height=10),
            [self.plot_CURRENT, self.plot_CURRENT_prev],
            Spacer(height=10)
            ],background="#C0C0C0",width=1024)

        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))


    def add_points(self, datapackage: DataPackageModel):
        self.reset_plot(str(datapackage.action_uuid))

        tmpdata = {key:[] for key in self.datakeys}
        # they are all in sequence of cell1 to cell9 in the dict
        cellnum = 1

        for fileconnkey, data_dict in datapackage.datamodel.data.items():

            for key, val in data_dict.items():
                if key == "t_s":
                    tmpdata[key] = val
                elif key == "Icell_A":
                    tmpdata[f"Icell{cellnum}_A"] = val
                elif key == "Ecell_V":
                    tmpdata[f"Ecell{cellnum}_V"] = val
            cellnum += 1
        self.sourceIV.stream(tmpdata)


    async def IOloop_data(self): # non-blocking coroutine, updates data source
        self.vis.print_message(f" ... NI visualizer subscribing to: {self.data_url}")
        retry_limit = 5
        for _ in range(retry_limit):
            try:
                async with websockets.connect(self.data_url) as ws:
                    self.IOloop_data_run = True
                    while self.IOloop_data_run:
                        try:
                            datapackage = DataPackageModel(**json.loads(await ws.recv()))
                            if datapackage.action_name in ("cellIV"):
                                self.vis.doc.add_next_tick_callback(partial(self.add_points, datapackage))
                        except Exception:
                            self.IOloop_data_run = False
            except Exception:
                self.vis.print_message(f"failed to subscribe to "
                                   f"{self.data_url}"
                                   "trying again in 1sec",
                                   error = True)
                await asyncio.sleep(1) 


    def _add_plots(self):
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
        

        self.plot_VOLT.title.text = (f"action_uuid: {self.cur_action_uuid}")
        self.plot_CURRENT.title.text = (f"action_uuid: {self.cur_action_uuid}")
        # self.plot_VOLT_prev.title.text = ("action_uuid: "+self.prev_action_uuid)
        # self.plot_VOLT_prev.title.text = ("action_uuid: "+self.prev_action_uuid)


        colors = small_palettes["Category10"][9]
        for i in self.yaxis_selector_group.active:
            _ = self.plot_VOLT.line(x="t_s", y=f"Ecell{i+1}_V", source=self.sourceIV, name=f"Ecell{i+1}_V", line_color=colors[i], legend_label=f"Ecell{i+1}_V")
            _ = self.plot_CURRENT.line(x="t_s", y=f"Icell{i+1}_A", source=self.sourceIV, name=f"Icell{i+1}_A", line_color=colors[i], legend_label=f"Icell{i+1}_A")
            _ = self.plot_VOLT_prev.line(x="t_s", y=f"Ecell{i+1}_V", source=self.sourceIV_prev, name=f"Ecell{i+1}_V", line_color=colors[i], legend_label=f"Ecell{i+1}_V")
            _ = self.plot_CURRENT_prev.line(x="t_s", y=f"Icell{i+1}_A", source=self.sourceIV_prev, name=f"Icell{i+1}_A", line_color=colors[i], legend_label=f"Icell{i+1}_A")
        


    def reset_plot(self, new_action_uuid: UUID, forceupdate: bool = False):
        if (new_action_uuid != self.cur_action_uuid) or forceupdate:
            self.vis.print_message(" ... reseting NImax graph")
            self.prev_action_uuid = self.cur_action_uuid
            self.cur_action_uuid = new_action_uuid

            # copy old data to "prev" plot
            self.sourceIV_prev.data = {deepcopy(key): deepcopy(val) for key, val in self.sourceIV.data.items()}        
            self.sourceIV.data = {k: [] for k in self.sourceIV.data}
            self._add_plots()

        elif (self.yselect != self.yaxis_selector_group.active):
            self.yselect = self.yaxis_selector_group.active
            self._add_plots()


class C_potvis:
    """potentiostat visualizer module class"""
    def __init__(self, visServ: Vis, potentiostat_key: str):
        self.vis = visServ
        # self.vis = app
        self.config_dict = self.vis.server_cfg["params"]
        self.show = False
        # todo add input field for this
        self.max_points = 500

        potserv_config = self.vis.world_cfg["servers"].get(potentiostat_key, None)
        if potserv_config is None:
            return
        potserv_host = potserv_config.get("host", None)
        potserv_port = potserv_config.get("port", None)
        self.show = True

        self.data_url = f"ws://{potserv_config['host']}:{potserv_config['port']}/ws_data"
        # self.stat_url = f"ws://{potserv_config["host"]}:{potserv_config["port"]}/ws_status"



        self.IOloop_data_run = False
        self.IOloop_stat_run = False

        self.data_dict_keys = ["t_s", "Ewe_V", "Ach_V", "I_A"]
        self.data_dict = {key:[] for key in self.data_dict_keys}

        self.datasource = ColumnDataSource(data=self.data_dict)
        self.datasource_prev = ColumnDataSource(data=deepcopy(self.data_dict))
        self.cur_action_uuid = ""
        self.prev_action_uuid = ""
 
        # create visual elements
        self.layout = []


        self.input_max_points = TextInput(
                                          value=f"{self.max_points}", 
                                          title="max datapoints", 
                                          disabled=False, 
                                          width=150, 
                                          height=40, 
                                   )
        self.input_max_points.on_change(
            "value", 
            partial(self.callback_input_max_points, sender=self.input_max_points)
        )



        self.xaxis_selector_group = RadioButtonGroup(labels=self.data_dict_keys, active=0, width = 500)
        self.yaxis_selector_group = CheckboxButtonGroup(labels=self.data_dict_keys, active=[1,3], width = 500)
        
        
        self.plot = figure(title="Title", height=300, width=500)


        self.plot_prev = figure(title="Title", height=300, width=500)
        # combine all sublayouts into a single one
        self.layout = layout([
            [Spacer(width=20), Div(text=f'<b>Potentiostat Visualizer module for server <a href="http://{potserv_host}:{potserv_port}/docs#/" target="_blank">\'{potentiostat_key}\'</a></b>', width=1004, height=15)],
            [self.input_max_points],
            [Paragraph(text="""x-axis:""", width=500, height=15), Paragraph(text="""y-axis:""", width=500, height=15)],
            [self.xaxis_selector_group, self.yaxis_selector_group],
            Spacer(height=10),
            [self.plot, Spacer(width=20), self.plot_prev],
            Spacer(height=10)
            ],background="#C0C0C0",width=1024)

        # to check if selection changed during ploting
        self.xselect = self.xaxis_selector_group.active
        self.yselect = self.yaxis_selector_group.active

        self.reset_plot(self.cur_action_uuid, forceupdate= True)

        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))


    def callback_input_max_points(self, attr, old, new, sender):
        """callback for input_max_points"""
        def to_int(val):
            try:
                return int(val)
            except ValueError:
                return None

        newpts = to_int(new)
        oldpts =  to_int(old)

        if newpts is None:
            if oldpts is not None:
                newpts = oldpts
            else:
                newpts = 500

        if newpts < 2:
            newpts = 2
        if newpts > 10000:
            newpts = 10000

        self.max_points = newpts

        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value,sender,f"{self.max_points}")
        )


    def update_input_value(self, sender, value):
        sender.value = value


    def add_points(self, datapackage: DataPackageModel):
        def _add_helper(datadict, pointlist):
            for pt in pointlist:
                datadict.append(pt)

        self.reset_plot(str(datapackage.action_uuid))
        if len(self.data_dict[self.data_dict_keys[0]]) > self.max_points:
            delpts = len(self.data_dict[self.data_dict_keys[0]]) - self.max_points
            for key in self.data_dict_keys:
                del self.data_dict[key][:delpts]
        
        for fileconnkey, data_dict in datapackage.datamodel.data.items():
            for key in self.data_dict_keys:
                _add_helper(datadict = self.data_dict[key],
                            pointlist = data_dict.get(key, [0])
                )

        self.datasource.data = self.data_dict


    async def IOloop_data(self): # non-blocking coroutine, updates data source
        self.vis.print_message(f" ... potentiostat visualizer subscribing to: {self.data_url}")
        retry_limit = 5
        for _ in range(retry_limit):
            try:
                async with websockets.connect(self.data_url) as ws:
                    self.IOloop_data_run = True
                    while self.IOloop_data_run:
                        try:
                            datapackage = DataPackageModel(**json.loads(await ws.recv()))
                            if datapackage.action_name in (
                                    "run_LSV",
                                    "run_CA",
                                    "run_CP",
                                    "run_CV",
                                    "run_EIS",
                                    "run_OCV"
                                        ):
                                self.vis.doc.add_next_tick_callback(partial(self.add_points, datapackage))
                        except Exception:
                            self.IOloop_data_run = False
            except Exception:
                self.vis.print_message(f"failed to subscribe to "
                                   f"{self.data_url}"
                                   "trying again in 1sec",
                                   error = True)
                await asyncio.sleep(1) 
    

    def _add_plots(self):
        # clear legend
        if self.plot.renderers:
            self.plot.legend.items = []

        if self.plot_prev.renderers:
            self.plot_prev.legend.items = []


        # remove all old lines
        self.plot.renderers = []
        self.plot_prev.renderers = []

        
        self.plot.title.text = (f"active action_uuid: {self.cur_action_uuid}")
        self.plot_prev.title.text = (f"previous action_uuid: {self.prev_action_uuid}")
        xstr = ""
        if(self.xaxis_selector_group.active == 0):
            xstr = "t_s"
        elif(self.xaxis_selector_group.active == 1):
            xstr = "Ewe_V"
        elif(self.xaxis_selector_group.active == 2):
            xstr = "Ach_V"
        else:
            xstr = "I_A"
        colors = ["red", "blue", "yellow", "green"]
        color_count = 0
        for i in self.yaxis_selector_group.active:
            if i == 0:
                self.plot.line(x=xstr, y="t_s", line_color=colors[color_count], source=self.datasource, name=self.cur_action_uuid, legend_label="t_s")
                self.plot_prev.line(x=xstr, y="t_s", line_color=colors[color_count], source=self.datasource_prev, name=self.prev_action_uuid, legend_label="t_s")
            elif i == 1:
                self.plot.line(x=xstr, y="Ewe_V", line_color=colors[color_count], source=self.datasource, name=self.cur_action_uuid, legend_label="Ewe_V")
                self.plot_prev.line(x=xstr, y="Ewe_V", line_color=colors[color_count], source=self.datasource_prev, name=self.prev_action_uuid, legend_label="Ewe_V")
            elif i == 2:
                self.plot.line(x=xstr, y="Ach_V", line_color=colors[color_count], source=self.datasource, name=self.cur_action_uuid, legend_label="Ach_V")
                self.plot_prev.line(x=xstr, y="Ach_V", line_color=colors[color_count], source=self.datasource_prev, name=self.prev_action_uuid, legend_label="Ach_V")
            else:
                self.plot.line(x=xstr, y="I_A", line_color=colors[color_count], source=self.datasource, name=self.cur_action_uuid, legend_label="I_A")
                self.plot_prev.line(x=xstr, y="I_A", line_color=colors[color_count], source=self.datasource_prev, name=self.prev_action_uuid, legend_label="I_A")
            color_count += 1


    def reset_plot(self, new_action_uuid: UUID, forceupdate: bool = False):
        if (new_action_uuid != self.cur_action_uuid) or forceupdate:
            self.vis.print_message(" ... reseting Gamry graph")
            self.prev_action_uuid = self.cur_action_uuid
            self.cur_action_uuid = new_action_uuid
        
            # copy old data to "prev" plot
            self.datasource_prev.data = {deepcopy(key): deepcopy(val) for key, val in self.datasource.data.items()}
            self.data_dict = {key:[] for key in self.data_dict_keys}
            self.datasource.data = self.data_dict
            self._add_plots()

        elif  (self.xselect != self.xaxis_selector_group.active) or (self.yselect != self.yaxis_selector_group.active):
            self.xselect = self.xaxis_selector_group.active
            self.yselect = self.yaxis_selector_group.active
            self._add_plots()


def find_server_names(vis:Vis, fast_key:str) -> list:
    """finds server name for a given fast driver"""
    server_names = []
    for server_name, server_config \
    in vis.world_cfg["servers"].items():
        if server_config.get("fast", "") == fast_key:
            vis.print_message(f"found server: '{fast_key}' "
                                   f"under '{server_name}'",
                                   info = True)
            server_names.append(server_name)

    return server_names


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

    visoloop = asyncio.get_event_loop()
                
    app.vis.doc.add_root(layout(
        [Spacer(width=20), Div(text=f"<b>Visualizer on {gethostname()}</b>", width=1004, height=32, style={'font-size': '200%', 'color': 'red'})],
        background="#C0C0C0",width=1024))
    app.vis.doc.add_root(Spacer(height=10))

    # create visualizer objects for defined instruments

    # find all configured gamry servers
    potservnames = find_server_names(vis = app.vis,
                      fast_key = "gamry_server")
    potvis = []
    for potservname in potservnames:
        potvis.append(
            C_potvis(visServ = app.vis, potentiostat_key = potservname)
        )
        if potvis[-1].show:
            visoloop.create_task(potvis[-1].IOloop_data())


    # find all configured NI servers
    niservnames = find_server_names(vis = app.vis,
                      fast_key = "nidaqmx_server")

    NImaxvis = []
    for niservname in niservnames:
        NImaxvis.append(
            C_nidaqmxvis(visServ = app.vis, nidaqmx_key = niservname))
        if NImaxvis[-1].show:
            visoloop.create_task(NImaxvis[-1].IOloop_data())


    return doc
