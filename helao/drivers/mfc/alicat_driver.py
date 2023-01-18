""" A device class for the AliCat mass flow controller.

This device class uses the python implementation from https://github.com/numat/alicat
which has been added to the 'helao' conda environment. The default gas list included in
the module code differs from our MFC at G16 (i-C4H10), G25 (He-25), and G26 (He-75).
Update the gas list registers in case any of the 3 gases are used.

"""

__all__ = []

import time
import asyncio


from helaocore.error import ErrorCodes
from helao.servers.base import Base
from helaocore.models.data import DataModel
from helaocore.models.file import FileConnParams, HloHeaderModel
from helaocore.models.sample import SampleInheritance, SampleStatus
from helaocore.models.hlostatus import HloStatus
from helao.helpers.premodels import Action
from helao.helpers.active_params import ActiveParams
from helao.helpers.sample_api import UnifiedSampleDataAPI
from helao.servers.base import Base

from functools import partial
from bokeh.server.server import Server

from alicat import FlowController


class AliCatMFC:
    def __init__(self, action_serv: Base):

        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.unified_db = UnifiedSampleDataAPI(self.base)

        self.mfc = FlowContoller(port=self.config_dict["port"])
        # query status with self.mfc.get()
        # query pid settings with self.mfc.get_pid()

        self.aloop = asyncio.get_running_loop()
        self.polling = True
        self.poll_signalq = asyncio.Queue(1)
        self.poll_signal_task = self.aloop.create_task(self.poll_signal_loop())
        self.polling_task = self.aloop.create_task(self.poll_sensor_loop())
        self.last_state = "unknown"

    async def start_polling(self):
        self.base.print_message("got 'start_polling' request, raising signal")
        await self.poll_signalq.put(True)

    async def stop_polling(self):
        self.base.print_message("got 'stop_polling' request, raising signal")
        await self.poll_signalq.put(False)

    async def poll_signal_loop(self):
        while True:
            self.polling = await self.poll_signalq.get()
            self.base.print_message("polling signal received")

    async def poll_sensor_loop(self, waittime: float = 0.05):
        self.base.print_message("MFC background task has started")
        lastupdate = 0
        while True:
            if self.polling:
                checktime = time.time()
                if checktime - lastupdate < waittime:
                    # self.base.print_message("waiting for minimum update interval.")
                    await asyncio.sleep(waittime - (checktime - lastupdate))
                status_dict = self.mfc.get()
                lastupdate = time.time()
                await self.base.put_lbuf(status_dict)
                # self.base.print_message("status sent to live buffer")
            await asyncio.sleep(0.01)

    def shutdown(self):
        # this gets called when the server is shut down or reloaded to ensure a clean
        # disconnect ... just restart or terminate the server
        self.base.print_message("closing MFC connection")
        self.mfc.close()


"""Notes:

Register diffs at G16,25,26
(returned by b"A??g*\r"):       (coded into alicat/serial.py):
A G00      Air                  Air
A G01       Ar                  Ar
A G02      CH4                  CH4
A G03       CO                  CO
A G04      CO2                  CO2
A G05     C2H6                  C2H6
A G06       H2                  H2
A G07       He                  He
A G08       N2                  N2
A G09      N2O                  N2O
A G10       Ne                  Ne
A G11       O2                  O2
A G12     C3H8                  C3H8
A G13   nC4H10                  n-C4H10
A G14     C2H2                  C2H2
A G15     C2H4                  C2H4
A G16   iC4H10                  i-C2H10
A G17       Kr                  K
A G18       Xe                  Xe
A G19      SF6                  SF6
A G20     C-25                  C-25
A G21     C-10                  C-10
A G22      C-8                  C-8
A G23      C-2                  C-2
A G24     C-75                  C-75
A G25    He-25                  A-75
A G26    He-75                  A-25
A G27    A1025                  A1025
A G28   Star29                  Star29
A G29      P-5                  P-5
A G140     C-15
A G141     C-20
A G142     C-50
A G143    He-50
A G144    He-90
A G145    Bio5M
A G146   Bio10M
A G147   Bio15M
A G148   Bio20M
A G149   Bio25M
A G150   Bio30M
A G151   Bio35M
A G152   Bio40M
A G153   Bio45M
A G154   Bio50M
A G155   Bio55M
A G156   Bio60M
A G157   Bio65M
A G158   Bio70M
A G159   Bio75M
A G160   Bio80M
A G161   Bio85M
A G162   Bio90M
A G163   Bio95M
A G164   EAN-32
A G165   EAN-36
A G166   EAN-40
A G167   HeOx20
A G168   HeOx21
A G169   HeOx30
A G170   HeOx40
A G171   HeOx50
A G172   HeOx60
A G173   HeOx80
A G174   HeOx99
A G175    EA-40
A G176    EA-60
A G177    EA-80
A G178    Metab
A G179   LG-4.5
A G180     LG-6
A G181     LG-7
A G182     LG-9
A G183   HeNe-9
A G184   LG-9.4
A G185   SynG-1
A G186   SynG-2
A G187   SynG-3
A G188   SynG-4
A G189   NatG-1
A G190   NatG-2
A G191   NatG-3
A G192    CoalG
A G193     Endo
A G194      HHO
A G195     HD-5
A G196    HD-10
A G197   OCG-89
A G198   OCG-93
A G199   OCG-95
A G200     FG-1
A G201     FG-2
A G202     FG-3
A G203     FG-4
A G204     FG-5
A G205     FG-6
A G206     P-10
A G210       D2
"""
