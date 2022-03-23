""" A device class for the Gamry USB potentiostat, used by a FastAPI server instance.

The 'gamry' device class exposes potentiostat measurement functions provided by the
GamryCOM comtypes Win32 module. Class methods are specific to Gamry devices. Device 
configuration is read from config/config.py. 

"""

__all__ = ["gamry",
           "Gamry_modes",
          ]

import comtypes
import comtypes.client as client
import asyncio
import time
from enum import Enum
import psutil
import numpy as np

from helaocore.schema import Action
from helaocore.server.base import Base
from helaocore.error import ErrorCodes
from helaocore.model.sample import SampleInheritance, SampleStatus
from helaocore.model.data import DataModel
from helaocore.model.file import FileConnParams, HloHeaderModel
from helaocore.model.active import ActiveParams
from helaocore.model.hlostatus import HloStatus
from helaocore.data.sample import UnifiedSampleDataAPI
from helaocore.model.hlostatus import HloStatus

class Gamry_modes(str, Enum):
    CA = "CA"
    CP = "CP"
    CV = "CV"
    LSV = "LSV"
    EIS = "EIS"
    OCV = "OCV"

# https://www.gamry.com/support/technical-support/frequently-asked-questions/fixed-vs-autoranging/
# class Gamry_IErange(str, Enum):
#     #NOTE: The ranges listed below are for 300 mA or 30 mA models. For 750 mA models, multiply the ranges by 2.5. For 600 mA models, multiply the ranges by 2.0.
#     auto = "auto"
#     mode0 = "3pA"
#     mode1 = "30pA"
#     mode2 = "300pA"
#     mode3 = "3nA"
#     mode4 = "30nA"
#     mode5 = "300nA"
#     mode6 = "3uA"
#     mode7 = "30uA"
#     mode8 = "300uA"
#     mode9 = "3mA"
#     mode10 = "30mA"
#     mode11 = "300mA"
#     mode12 = "3A"
#     mode13 = "30A"
#     mode14 = "300A"
#     mode15 = "3kA"


# for IFC1010
class Gamry_IErange_IFC1010(str, Enum):
    # NOTE: The ranges listed below are for 300 mA or 30 mA models. For 750 mA models, multiply the ranges by 2.5. For 600 mA models, multiply the ranges by 2.0.
    auto = "auto"
    # mode0 = "N/A"
    # mode1 = "N/A"
    # mode2 = "N/A"
    # mode3 = "N/A"
    mode4 = "10nA"
    mode5 = "100nA"
    mode6 = "1uA"
    mode7 = "10uA"
    mode8 = "100uA"
    mode9 = "1mA"
    mode10 = "10mA"
    mode11 = "100mA"
    mode12 = "1A"
    # mode13 = "N/A"
    # mode14 = "N/A"
    # mode15 = "N/A"


class Gamry_IErange_REF600(str, Enum):
    auto = "auto"
    # mode0 = "N/A"
    mode1 = "60pA"
    mode2 = "600pA"
    mode3 = "6nA"
    mode4 = "60nA"
    mode5 = "600nA"
    mode6 = "6uA"
    mode7 = "60uA"
    mode8 = "600uA"
    mode9 = "6mA"
    mode10 = "60mA"
    mode11 = "600mA"
    # mode12 = "N/A"
    # mode13 = "N/A"
    # mode14 = "N/A"
    # mode15 = "N/A"


# G750 is 7.5nA to 750mA
class Gamry_IErange_PCI4G300(str, Enum):
    auto = "auto"
    # mode0 = "N/A"
    # mode1 = "N/A"
    # mode2 = "N/A"
    mode3 = "3nA"
    mode4 = "30nA"
    mode5 = "300nA"
    mode6 = "3uA"
    mode7 = "30uA"
    mode8 = "300uA"
    mode9 = "3mA"
    mode10 = "30mA"
    mode11 = "300mA"
    # mode12 = "N/A"
    # mode13 = "N/A"
    # mode14 = "N/A"
    # mode15 = "N/A"


class Gamry_IErange_PCI4G750(str, Enum):
    auto = "auto"
    # mode0 = "N/A"
    # mode1 = "N/A"
    # mode2 = "N/A"
    mode3 = "7.5nA"
    mode4 = "75nA"
    mode5 = "750nA"
    mode6 = "7.5uA"
    mode7 = "75uA"
    mode8 = "750uA"
    mode9 = "7.5mA"
    mode10 = "75mA"
    mode11 = "750mA"
    # mode12 = "N/A"
    # mode13 = "N/A"
    # mode14 = "N/A"
    # mode15 = "N/A"


class Gamry_IErange_dflt(str, Enum):
    auto = "auto"
    mode0 = "mode0"
    mode1 = "mode1"
    mode2 = "mode2"
    mode3 = "mode3"
    mode4 = "mode4"
    mode5 = "mode5"
    mode6 = "mode6"
    mode7 = "mode7"
    mode8 = "mode8"
    mode9 = "mode9"
    mode10 = "mode10"
    mode11 = "mode11"
    mode12 = "mode12"
    mode13 = "mode13"
    mode14 = "mode14"
    mode15 = "mode15"


def gamry_error_decoder(e):
    if isinstance(e, comtypes.COMError):
        hresult = 2 ** 32 + e.args[0]
        if hresult & 0x20000000:
            return GamryCOMError(
                "0x{0:08x}: {1}".format(2 ** 32 + e.args[0], e.args[1])
            )
    return e


class GamryCOMError(Exception):
    """definition of error handling things from gamry"""

    pass


class GamryDtaqEvents(object):
    def __init__(self, dtaq):
        self.dtaq = dtaq
        self.acquired_points = []
        self.status = "idle"
        # self.buffer = buff
        self.buffer_size = 0

    def cook(self):
        count = 1
        while count > 0:
            try:
                # TODO: how to know from self.dtaq that the 
                # connection to Gamry was closed?
                count, points = self.dtaq.Cook(1000)
                # The columns exposed by GamryDtaq.Cook vary by dtaq and are
                # documented in the Toolkit Reference Manual.
                self.acquired_points.extend(zip(*points))
            except Exception:
                count = 0

    def _IGamryDtaqEvents_OnDataAvailable(self):
        self.cook()
        self.status = "measuring"

    def _IGamryDtaqEvents_OnDataDone(self):
        self.cook()  # a final cook
        self.status = "done"


class dummy_sink:
    """Dummy class for when the Gamry is not used"""

    def __init__(self):
        self.status = "idle"


# due to async status handling and delayed result paradigm, this gamry class requires an
# action server to operate
class gamry:
    def __init__(self, action_serv: Base):

        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        # signals the dynamic endpoints that init was done
        self.ready = False

        self.unified_db = UnifiedSampleDataAPI(self.base)
        asyncio.gather(self.unified_db.init_db())

        # get Gamry object (Garmry.com)
        # a busy gamrycom can lock up the server
        self.kill_GamryCom()
        self.GamryCOM = client.GetModule(
            ["{BD962F0D-A990-4823-9CF5-284D1CDD9C6D}", 1, 0]
        )
        # self.GamryCOM = client.GetModule(self.config_dict["path_to_gamrycom"])

        self.pstat = None
        self.action = None  # for passing action object from technique method to measure loop
        self.active = None  # for holding active action object, clear this at end of measurement
        self.pstat_connection = None
        self.samples_in = []
        # status is handled through active, call active.finish()
        self.gamry_range_enum = Gamry_IErange_dflt
        self.allow_no_sample = self.config_dict.get("allow_no_sample", False)
        self.Gamry_devid = self.config_dict.get("dev_id", 0)

        asyncio.gather(self.init_Gamry(self.Gamry_devid))

        # for Dtaq
        self.dtaqsink = dummy_sink()
        self.dtaq = None

        # for global IOloop
        # replaces while loop w/async trigger
        self.IO_signalq = asyncio.Queue(1)
        self.IO_do_meas = False  # signal flag for intent (start/stop)
        self.IO_measuring = False  # status flag of measurement
        self.IO_meas_mode = None
        self.IO_sigramp = None
        self.IO_TTLwait = -1
        self.IO_TTLsend = -1
        self.IO_IErange = self.gamry_range_enum("auto")

        myloop = asyncio.get_event_loop()
        # add meas IOloop
        myloop.create_task(self.IOloop())

        # for saving data localy
        self.FIFO_epoch = None
        self.FIFO_gamryheader = dict() # measuement specific, will be reset each measurement
        self.FIFO_column_headings = []
        self.FIFO_Gamryname = ""
        
        # signals return to endpoint after active was created
        self.IO_continue = False
        self.IOloop_run = False


    def set_IO_signalq_nowait(self, val: bool) -> None:
        if self.IO_signalq.full():
            _ = self.IO_signalq.get_nowait()
        self.IO_signalq.put_nowait(val)


    async def set_IO_signalq(self, val: bool) -> None:
        if self.IO_signalq.full():
            _ = await self.IO_signalq.get()
        await self.IO_signalq.put(val)


    async def IOloop(self):
        """This is main Gamry measurement loop which always needs to run
        else if measurement is done in FastAPI calls we will get timeouts"""
        self.IOloop_run = True
        try:
            while self.IOloop_run:
                self.IO_do_meas = await self.IO_signalq.get()
                if self.IO_do_meas:
                    # are we in estop?
                    if not self.base.actionserver.estop:
                        self.base.print_message("Gamry got measurement request")
                        await self.measure()
                        if self.base.actionserver.estop:
                            self.IO_do_meas = False
                            self.base.print_message("Gamry is in estop after measurement.",
                                                    error=True)
                        else:
                            self.base.print_message("setting Gamry to idle")
                            # await self.stat.set_idle()
                        self.base.print_message("Gamry measurement is done")
                    else:
                        self.active.action.action_status.append(HloStatus.estopped)
                        self.IO_do_meas = False
                        self.base.print_message("Gamry is in estop.",
                                                error=True)

                # endpoint can return even we got errors
                self.IO_continue = True


                if self.active:
                    self.base.print_message("gamry finishes active action")
                    _ = await self.active.finish()
                    self.active = None
                    self.action = None
                    self.samples_in = []


        except asyncio.CancelledError:
            # endpoint can return even we got errors
            self.IO_continue = True
            self.base.print_message("IOloop task was cancelled")


    def kill_GamryCom(self):
        """script can be blocked or crash if GamryCom is still open and busy"""
        pyPids = {
            p.pid: p
            for p in psutil.process_iter(["name", "connections"])
            if p.info["name"].startswith("GamryCom")
        }

        for pid in pyPids:
            self.base.print_message(f"killing GamryCom on PID: {pid}")
            p = psutil.Process(pid)
            for _ in range(3):
                # os.kill(p.pid, signal.SIGTERM)
                p.terminate()
                time.sleep(0.5)
                if not psutil.pid_exists(p.pid):
                    self.base.print_message("Successfully terminated GamryCom.")
                    return True
            if psutil.pid_exists(p.pid):
                self.base.print_message("Failed to terminate server GamryCom after 3 retries.")
                return False


    async def init_Gamry(self, devid):
        """connect to a Gamry"""
        try:
            self.devices = client.CreateObject("GamryCOM.GamryDeviceList")
            self.base.print_message(f"GamryDeviceList: "
                                    f"{self.devices.EnumSections()}")
            # self.base.print_message(f"{len(self.devices.EnumSections())}")
            if len(self.devices.EnumSections()) >= devid + 1:
                self.FIFO_Gamryname = self.devices.EnumSections()[devid]

                if self.FIFO_Gamryname.find("IFC") == 0:
                    self.pstat = client.CreateObject("GamryCOM.GamryPC6Pstat")
                    self.base.print_message(f"Gamry, using Interface {self.pstat}",
                                            info = True)
                elif self.FIFO_Gamryname.find("REF") == 0:
                    self.pstat = client.CreateObject("GamryCOM.GamryPC5Pstat")
                    self.base.print_message(f"Gamry, using Reference {self.pstat}",
                                            info = True)
                elif self.FIFO_Gamryname.find("PCI") == 0:
                    self.pstat = client.CreateObject('GamryCOM.GamryPstat')
                    self.base.print_message(f"Gamry, using PCI {self.pstat}",
                                            info = True)
                # else: # old version before Framework 7.06
                #     self.pstat = client.CreateObject('GamryCOM.GamryPstat')
                #     self.base.print_message('Gamry, using Farmework , 7.06?', self.pstat)

                if self.FIFO_Gamryname.find("IFC1010") == 0:
                    self.gamry_range_enum = Gamry_IErange_IFC1010
                elif self.FIFO_Gamryname.find("REF600") == 0:
                    self.gamry_range_enum = Gamry_IErange_REF600
                elif self.FIFO_Gamryname.find("PCI4G300") == 0:
                    self.gamry_range_enum = Gamry_IErange_PCI4G300
                elif self.FIFO_Gamryname.find("PCI4G750") == 0:
                    self.gamry_range_enum = Gamry_IErange_PCI4G750
                else:
                    self.gamry_range_enum = Gamry_IErange_dflt

                self.pstat.Init(self.devices.EnumSections()[devid])
                # self.base.print_message("", self.pstat)
                self.base.print_message(
                    f"Connected to Gamry on DevID {devid}!",
                    info = True
                )

            else:
                self.pstat = None
                self.base.print_message(
                    f"No potentiostat is connected on DevID {devid}! Have you turned it on?",
                    error = True
                )

        except Exception as e:
            # this will lock up the potentiostat server
            # happens when a not activated Gamry is connected and turned on
            # TODO: find a way to avoid it
            self.base.print_message(f"fatal error initializing Gamry: {e}", error=True)
        self.ready = True

    async def open_connection(self):
        """Open connection to Gamry"""
        # this just tries to open a connection with try/catch
        await asyncio.sleep(0.001)
        if not self.pstat:
            await self.init_Gamry(self.Gamry_devid)
        try:
            if self.pstat:
                self.pstat.Open()
                return ErrorCodes.none
            else:
                self.base.print_message("open_connection: Gamry not initialized!", error=True)
                return ErrorCodes.not_initialized

        except Exception as e:
            # self.pstat = None
            self.base.print_message(f"Gamry error init: {e}", error=True)
            return ErrorCodes.critical


    def close_connection(self):
        """Close connection to Gamry"""
        # this just tries to close a connection with try/catch
        try:
            if self.pstat:
                self.pstat.Close()
                return ErrorCodes.none
            else:
                self.base.print_message("close_connection: Gamry not initialized!", error=True)
                return ErrorCodes.not_initialized
        except Exception:
            # self.pstat = None
            return ErrorCodes.critical


    def close_pstat_connection(self):
        if self.IO_measuring:
            self.IO_do_meas = False # will stop meas loop
            self.IO_measuring = False
            self.dtaq.Run(False)
            self.pstat.SetCell(self.GamryCOM.CellOff)
            self.base.print_message("signaling IOloop to stop")
            self.set_IO_signalq_nowait(False)

            # delete this at the very last step
            self.close_connection()
            self.pstat_connection = None
            self.dtaqsink = dummy_sink()    
            self.dtaq = None
            
        else:
            pass


    async def measurement_setup(self, AcqFreq, mode: Gamry_modes = None, *argv):
        """setting up the measurement parameters
        need to initialize and open connection to gamry first"""
        await asyncio.sleep(0.001)
        error =  ErrorCodes.none
        if self.pstat:
            try:
                IErangesdict = dict(
                    mode0=0,
                    mode1=1,
                    mode2=2,
                    mode3=3,
                    mode4=4,
                    mode5=5,
                    mode6=6,
                    mode7=7,
                    mode8=8,
                    mode9=9,
                    mode10=10,
                    mode11=11,
                    mode12=12,
                    mode13=13,
                    mode14=14,
                    mode15=15,
                )
    
                # InitializePstat (from exp script)
                # https://www.gamry.com/application-notes/instrumentation/changing-potentiostat-speed-settings/
                self.pstat.SetCell(self.GamryCOM.CellOff)
                #####pstat.InstrumentSpecificInitialize ()
                self.pstat.SetPosFeedEnable(False)  # False
    
                # pstat.SetStability (StabilityFast)
                self.pstat.SetIEStability(self.GamryCOM.StabilityFast)
                # Fast (0), Medium (1), Slow (2)
                # StabilityFast (0), StabilityNorm (1), StabilityMed (1), StabilitySlow (2)
                # pstat.SetCASpeed(1)#GamryCOM.CASpeedNorm)
                # CASpeedFast (0), CASpeedNorm (1), CASpeedMed (2), CASpeedSlow (3)
                self.pstat.SetSenseSpeedMode(True)
                # pstat.SetConvention (PHE200_IConvention)
                # anodic currents are positive
                self.pstat.SetIConvention(self.GamryCOM.Anodic)
    
                self.pstat.SetGround(self.GamryCOM.Float)
    
                # Set current channel range.
                # Setting the IchRange using a voltage is preferred. The measured current is converted into a voltage on the I channel using the I/E converter.
                # 0 0.03 V range, 1 0.30 V range, 2 3.00 V range, 3 30.00 V (PCI4) 12V (PC5)
                # The floating point number is the maximum anticipated voltage (in Volts).
                self.pstat.SetIchRange(12.0)
                self.pstat.SetIchRangeMode(True)  # auto-set
                self.pstat.SetIchOffsetEnable(False)
                self.pstat.SetIchFilter(AcqFreq)
    
                # Set voltage channel range.
                self.pstat.SetVchRange(12.0)
                self.pstat.SetVchRangeMode(True)
                self.pstat.SetVchOffsetEnable(False)
                self.pstat.SetVchFilter(AcqFreq)
    
                # Sets the range of the Auxiliary A/D input.
                self.pstat.SetAchRange(3.0)
    
                # pstat.SetIERangeLowerLimit(None)
    
                # Sets the I/E Range of the potentiostat.
                self.pstat.SetIERange(0.03)
                # Enable or disable current measurement auto-ranging.
                self.pstat.SetIERangeMode(True)
    
                if self.IO_IErange == self.gamry_range_enum.auto:
                    self.base.print_message("auto I range selected")
                    self.pstat.SetIERange(0.03)
                    self.pstat.SetIERangeMode(True)
                else:
                    self.base.print_message(f"{self.IO_IErange.value} I range selected")
                    self.base.print_message(f"{IErangesdict[self.IO_IErange.name]} I range selected")
                    self.pstat.SetIERange(IErangesdict[self.IO_IErange.name])
                    self.pstat.SetIERangeMode(False)
                # elif self.IO_IErange == self.gamry_range_enum.mode0:
                #     self.pstat.SetIERangeMode(False)
                #     self.pstat.SetIERange(0)
    
                # Sets the voltage of the auxiliary DAC output.
                self.pstat.SetAnalogOut(0.0)
    
                # Set the cell voltage of the Pstat.
                # self.pstat.SetVoltage(0.0)
    
                # Set the current interrupt IR compensation mode.
                self.pstat.SetIruptMode(self.GamryCOM.IruptOff)
    
                # the format of the data array is dependent upon the specific Dtaq
                # e.g. which subheader to use
    
                if mode == Gamry_modes.CA:
                    Dtaqmode = "GamryCOM.GamryDtaqChrono"
                    Dtaqtype = self.GamryCOM.ChronoAmp
                    self.FIFO_column_headings = [
                        "t_s",
                        "Ewe_V",
                        "Vu",
                        "I_A",
                        "Q",
                        "Vsig",
                        "Ach_V",
                        "IERange",
                        "Overload_HEX",
                        "StopTest",
                    ]
                    self.pstat.SetCtrlMode(self.GamryCOM.PstatMode)
                elif mode == Gamry_modes.CP:
                    Dtaqmode = "GamryCOM.GamryDtaqChrono"
                    Dtaqtype = self.GamryCOM.ChronoPot
                    self.FIFO_column_headings = [
                        "t_s",
                        "Ewe_V",
                        "Vu",
                        "I_A",
                        "Q",
                        "Vsig",
                        "Ach_V",
                        "IERange",
                        "Overload_HEX",
                        "StopTest",
                    ]
                    self.pstat.SetCtrlMode(self.GamryCOM.GstatMode)
                elif mode == Gamry_modes.CV:
                    Dtaqmode = "GamryCOM.GamryDtaqRcv"
                    Dtaqtype = None
                    self.FIFO_column_headings = [
                        "t_s",
                        "Ewe_V",
                        "Vu",
                        "I_A",
                        "Vsig",
                        "Ach_V",
                        "IERange",
                        "Overload_HEX",
                        "StopTest",
                        "Cycle",
                        "unknown1",
                    ]
                    self.pstat.SetCtrlMode(self.GamryCOM.PstatMode)
                elif mode == Gamry_modes.LSV:
                    Dtaqmode = "GamryCOM.GamryDtaqCpiv"
                    Dtaqtype = None
                    self.FIFO_column_headings = [
                        "t_s",
                        "Ewe_V",
                        "Vu",
                        "I_A",
                        "Vsig",
                        "Ach_V",
                        "IERange",
                        "Overload_HEX",
                        "StopTest",
                        "unknown1",
                    ]
                    self.pstat.SetCtrlMode(self.GamryCOM.PstatMode)
                elif mode == Gamry_modes.EIS:
                    #                Dtaqmode = "GamryCOM.GamryReadZ"
                    Dtaqmode = "GamryCOM.GamryDtaqEis"
                    Dtaqtype = None
                    # this needs to be manualy extended, default are only I and V (I hope that this is Ewe_V)
                    self.FIFO_column_headings = [
                        "I_A",
                        "Ewe_V",
                        "Zreal",
                        "Zimag",
                        "Zsig",
                        "Zphz",
                        "Zfreq",
                        "Zmod",
                    ]
                    self.pstat.SetCtrlMode(self.GamryCOM.PstatMode)
                elif mode == Gamry_modes.OCV:
                    Dtaqmode = "GamryCOM.GamryDtaqOcv"
                    Dtaqtype = None
                    self.FIFO_column_headings = [
                        "t_s",
                        "Ewe_V",
                        "Vm",
                        "Vsig",
                        "Ach_V",
                        "Overload_HEX",
                        "StopTest",
                        "unknown1",
                        "unknown2",
                        "unknown3",
                    ]
                    self.pstat.SetCtrlMode(self.GamryCOM.PstatMode)
                else:
                    self.base.print_message(f"'mode {mode} not supported'", error=True)
                    error = ErrorCodes.not_available


                if error is ErrorCodes.none:  
                    try:
                        self.base.print_message(f"creating dtaq '{Dtaqmode}'", info = True)
                        self.dtaq = client.CreateObject(Dtaqmode)
                        if Dtaqtype:
                            self.dtaq.Init(self.pstat, Dtaqtype, *argv)
                        else:
                            self.dtaq.Init(self.pstat, *argv)
                    except Exception as e:
                        self.base.print_message(f"Gamry Error during setup: "
                                                f"{gamry_error_decoder(e)}", error=True)
        
                    # This method, when enabled,
                    # allows for longer experiments with fewer points,
                    # but still acquires data quickly around each step.
                    if mode == Gamry_modes.CA:
                        self.dtaq.SetDecimation(False)
                    elif mode == Gamry_modes.CP:
                        self.dtaq.SetDecimation(False)
        
                    self.dtaqsink = GamryDtaqEvents(self.dtaq)
                    self.base.print_message(f"initialized dtaqsink with status {self.dtaqsink.status} in mode setup_{mode}")
                    

            except comtypes.COMError as e:
                self.base.print_message(f"Gamry error during measurement setup: {e}", error=True)
                error = ErrorCodes.critical
        else:
            self.base.print_message("measurement_setup: Gamry not initialized!", error=True)
            error = ErrorCodes.not_initialized

        return error


    async def measure(self):
        """performing a measurement with the Gamry
        this is the main function for the instrument"""
        await asyncio.sleep(0.001)

        if not self.pstat:
            self.IO_measuring = False
            return {"measure": "not initialized"}

        else:

            # active object is set so we can set the continue flag
            self.IO_continue = True
            
            
            

            # TODO:
            # - I/E range: auto, fixed
            # - IRcomp: None, PF, CI
            # - max current/voltage
            # - eq time
            # - init time delay
            # - conditioning
            # - sampling mode: fast, noise reject, surface

            # push the signal ramp over
            try:
                self.pstat.SetSignal(self.IO_sigramp)
                self.base.print_message("signal ramp set")
            except Exception as e:
                self.base.print_message("gamry error in signal")
                self.base.print_message(gamry_error_decoder(e))
                self.pstat.SetCell(self.GamryCOM.CellOff)
                return {"measure": "signal_error"}

            # TODO:
            # send or wait for trigger
            # Sets the voltage of the auxiliary DAC output.
            # self.pstat.SetAnalogOut
            # Sets the digital output setting.
            # self.pstat.SetDigitalOut
            # self.pstat.DigitalIn

            self.base.print_message(f"Gamry DigiOut state: {self.pstat.DigitalOut()}")
            self.base.print_message(f"Gamry DigiIn state: {self.pstat.DigitalIn()}")
            # first, wait for trigger
            if self.IO_TTLwait >= 0:
                while self.IO_do_meas:
                    bits = self.pstat.DigitalIn()
                    self.base.print_message(f"Gamry DIbits: {bits}")
                    if self.IO_TTLwait & bits:
                        break
                    # if self.IO_TTLwait == 0:
                    #     #0001
                    #     if (bits & 0x01):
                    #         break
                    # elif self.IO_TTLwait == 1:
                    #     #0010
                    #     if (bits & 0x02):
                    #         break
                    # elif self.IO_TTLwait == 2:
                    #     #0100
                    #     if (bits & 0x04):
                    #         break
                    # elif self.IO_TTLwait == 3:
                    #     #1000
                    #     if (bits & 0x08):
                    #         break
                    break  # for testing, we don't want to wait forever
                    await asyncio.sleep(0.001)

            # second, send a trigger
            # TODO: need to reset trigger first during init to high/low
            # if its in different state
            # and reset it after meas
            if self.IO_TTLsend >= 0:
                # SetDigitalOut([in] short Out, # New output setting in the lowest 4 bits
                #               [in] short Mask, # Identify the bits to be changed
                #              )	
                # returns [out]	OutSet	Output setting as set
                # The Out parameter is used to show the desired bit pattern 
                # and to show the range of bits to be changed. 
                # Each of the lowest 4 bits of the Out argument corresponds 
                # to one of the output bits. A bit will only be changed if 
                # the mask argument has a one in that bit's bit position. 
                # A mask argument of 0x0003 would allow changes in Output0 
                # and Output1. With this mask value, Output 2 and Output 3 
                # will not be changed regardless of the bit pattern argument.
                if self.IO_TTLsend == 0:
                    #0001
                    self.pstat.SetDigitalOut(1,1)
                elif self.IO_TTLsend == 1:
                    #0010
                    self.pstat.SetDigitalOut(2,2)
                elif self.IO_TTLsend == 2:
                    #0100
                    self.pstat.SetDigitalOut(4,4)
                elif self.IO_TTLsend == 3:
                    #1000
                    self.pstat.SetDigitalOut(8,8)

            # turn on the potentiostat output
            if self.IO_meas_mode == Gamry_modes.OCV:
                self.pstat.SetCell(self.GamryCOM.CellMon)
            else:
                self.pstat.SetCell(self.GamryCOM.CellOn)

            # Use the following code to discover events:
            # client.ShowEvents(dtaqcpiv)
            self.pstat_connection = client.GetEvents(self.dtaq, self.dtaqsink)

            try:
                # get current time and start measurement
                self.dtaq.Run(True)
                self.base.print_message("running dtaq")
                self.IO_measuring = True
            except Exception as e:
                self.base.print_message("gamry error run")
                self.base.print_message(gamry_error_decoder(e))
                self.close_pstat_connection()
                return {"measure": "run_error"}


            realtime = await self.active.set_realtime()
            if self.active:
                self.active.finish_hlo_header(
                                              realtime=realtime,
                                              # use firt of currently
                                              # active file_conn_keys
                                              # split action will update it
                                              file_conn_keys = \
                                               self.active.action.file_conn_keys
                                              )
                    
                    
            # dtaqsink.status might still be 'idle' if sleep is too short
            await asyncio.sleep(0.04)
            client.PumpEvents(0.001)
            sink_status = self.dtaqsink.status
            counter = 0


            while (
                # counter < len(self.dtaqsink.acquired_points)
                self.IO_do_meas
                and (sink_status != "done" or counter < len(self.dtaqsink.acquired_points))
            ):
                # need some await points
                await asyncio.sleep(0.001)
                client.PumpEvents(0.001)
                tmpc = len(self.dtaqsink.acquired_points)
                if counter < tmpc:
                    tmp_datapoints = self.dtaqsink.acquired_points[counter:tmpc]
                    # print(counter, tmpc, len(tmp_datapoints))
                    # EIS needs to be tested and fixed 
                    # # Need to get additional data for EIS
                    # if self.IO_meas_mode == Gamry_modes.EIS:
                    #     test = list(tmp_datapoints)
                    #     test.append(self.dtaqsink.dtaq.Zreal())
                    #     test.append(self.dtaqsink.dtaq.Zimag())
                    #     test.append(self.dtaqsink.dtaq.Zsig())
                    #     test.append(self.dtaqsink.dtaq.Zphz())
                    #     test.append(self.dtaqsink.dtaq.Zfreq())
                    #     test.append(self.dtaqsink.dtaq.Zmod())
                    #     tmp_datapoints = tuple(test)
    
                    if self.active:
                        if self.active.action.save_data:
                            data = {self.active.action.file_conn_keys[0]:\
                                       {
                                           k: v
                                           for k, v in zip(
                                               self.FIFO_column_headings, 
                                               np.matrix(tmp_datapoints).T.tolist()
                                           )
                                       }
                                    }
                            await self.active.enqueue_data(datamodel = \
                                   DataModel(
                                             data = data,
                                             errors = [],
                                             status = HloStatus.active
                                            )
                                )
                    counter = tmpc

                sink_status = self.dtaqsink.status

            self.close_pstat_connection()
            return {"measure": f"done_{self.IO_meas_mode}"}


    async def status(self):
        """return status of data structure"""
        await asyncio.sleep(0.001)
        return self.dtaqsink.status


    async def stop(self):
        """stops measurement, writes all data and returns from meas loop"""
        # turn off cell and run before stopping meas loop
        if self.IO_measuring:
            # file and Gamry connection will be closed with the meas loop
            self.IO_do_meas = False # will stop meas loop
            await self.set_IO_signalq(False)


    async def estop(self, switch:bool, *args, **kwargs):
        """same as stop, set or clear estop flag with switch parameter"""
        # should be the same as stop()
        switch = bool(switch)
        self.base.actionserver.estop = switch
        if self.IO_measuring:
            if switch:
                self.IO_do_meas = False # will stop meas loop
                await self.set_IO_signalq(False)
                if self.active:
                    # add estop status to active.status
                    await self.active.set_estop()
        return switch


    def shutdown(self):
        # close all connection and objects to gamry
        self.base.print_message("shutting down gamry")
        if self.IO_measuring:
            # file and Gamry connection will be closed with the meas loop
            self.IO_do_meas = False # will stop meas loop
            self.set_IO_signalq_nowait(False)

        # give some time to finish all data
        retries = 0
        while self.active is not None \
        and retries < 10:
            self.base.print_message(f"Got shutdown, "
                                    f"but Active is not yet done!, "
                                    f"retry {retries}",
                                    info = True)
            self.set_IO_signalq_nowait(False)
            time.sleep(1)
            retries += 1
        # stop IOloop
        self.IOloop_run = False
        self.kill_GamryCom()



    def ierangefinder(self, requested_range=None):
    
        def mysplit(s):
            def to_float(val):
                try:
                    return float(val)
                except ValueError:
                    return None
            
            unit = s.lstrip('0123456789. ')
            number = s[:-len(unit)]
            return to_float(number), unit
        
        def to_amps(number: float, unit: str):
            unit = unit.lower()
            exp = None
            if unit == "aa":
                exp = 1E-18
            elif unit == "fa":
                exp = 1E-15
            elif unit == "pa":
                exp = 1E-12
            elif unit == "na":
                exp = 1E-9
            elif unit == "ua":
                exp = 1E-6
            elif unit == "ma":
                exp = 1E-3
            elif unit == "a":
                exp = 1
            elif unit == "ka":
                exp = 1000
            
            if exp is None:
                return None
            else:
                return number*exp

        
        if requested_range is None:
            self.base.print_message("could not detect IErange, using 'auto'", 
                                    error=True)
            return self.gamry_range_enum.auto
        requested_range = f"{requested_range.lower()}"

        self.base.print_message(f"got IErange request for {requested_range}", 
                                info=True)
        
        names = [e.name.lower() for e in self.gamry_range_enum]
        vals = [e.value.lower() for e in self.gamry_range_enum]
        lookupvals = [e.value for e in self.gamry_range_enum]
    
            
        idx = None
        if requested_range in vals:
            idx = vals.index(requested_range)

        elif requested_range in names:
            idx = names.index(requested_range)

        else:
            # auto should have been detected already above
            # try auto detect range based on value and unit pair
            req_num, req_unit =  mysplit(requested_range)
            req_num = to_amps(number = req_num, unit = req_unit)
            if req_num is None:
                return self.gamry_range_enum.auto
            for ret_idx, val in enumerate(vals):
                val_num, val_unit = mysplit(val)
                val_num = to_amps(number = val_num, unit = val_unit)
                if val_num is None:
                    # skip auto
                    continue
                if req_num <= val_num:
                    # self.gamry_range_enum is already sort min to max
                    idx = ret_idx
                    break


            if idx is None:
                self.base.print_message("could not detect IErange, using 'auto'", 
                                        error=True)
                return self.gamry_range_enum.auto
        
        
        ret_range = self.gamry_range_enum(lookupvals[idx])
        self.base.print_message(f"detected IErange: {ret_range}", 
                                info=True)
        return ret_range
    


    async def technique_wrapper(
        self, 
        act, 
        measmode, 
        sigfunc, 
        sigfunc_params, 
        samplerate, 
        eta=0.0,
        setupargs=[]
    ):
        activeDict = dict()
        act.action_etc = eta
        act.error_code = ErrorCodes.none
        samples_in = await self.unified_db.get_samples(act.samples_in)
        if not samples_in and not self.allow_no_sample:
            self.base.print_message("Gamry got no valid sample, "
                                    "cannot start measurement!",
                                    error = True)
            act.samples_in = []
            act.error_code = ErrorCodes.no_sample
            activeDict = act.as_dict()
 

        if self.pstat \
        and not self.IO_do_meas \
        and not self.IO_measuring \
        and not self.base.actionserver.estop \
        and act.error_code is ErrorCodes.none:
            # open connection, will be closed after measurement in IOloop
            act.error_code = await self.open_connection()

        elif not self.pstat:
            activeDict = act.as_dict()
            act.error_code = ErrorCodes.not_initialized

        elif not self.IO_do_meas:
            activeDict = act.as_dict()
            act.error_code = ErrorCodes.in_progress

        elif self.base.actionserver.estop:
            activeDict = act.as_dict()
            act.error_code = ErrorCodes.estop

        elif self.IO_measuring:
            activeDict = act.as_dict()
            act.error_code = ErrorCodes.in_progress

        else:
            if act.error_code is ErrorCodes.none:
                act.error_code = ErrorCodes.not_initialized
            activeDict = act.as_dict()


        if act.error_code is ErrorCodes.none:
            # set parameters for IOloop meas
            self.IO_meas_mode = measmode
            act.error_code = await self.measurement_setup(
                1.0 / samplerate, self.IO_meas_mode, *setupargs
            )
            if act.error_code is ErrorCodes.none:
                # setup the experiment specific signal ramp
                self.IO_sigramp = client.CreateObject(sigfunc)
                try:
                    self.IO_sigramp.Init(*sigfunc_params)
                    act.error_code = ErrorCodes.none
                except Exception as e:
                    act.error_code = gamry_error_decoder(e)
                    self.base.print_message(f"IO_sigramp.Init error: "
                                            f"{act.error_code}", error = True)
                
                self.samples_in = samples_in
                self.action = act
                self.action.samples_in = []


                # write header lines with one function call
                self.FIFO_gamryheader.update(
                        {
                        "gamry":self.FIFO_Gamryname,
                        "ierangemode":self.IO_IErange.name,
                        }
                )

                self.active =  await self.base.contain_action(
                    ActiveParams(
                                 action = self.action,
                                 file_conn_params_dict = {self.base.dflt_file_conn_key():
                                     FileConnParams(
                                         # use dflt file conn key for first
                                         # init
                                                   file_conn_key = \
                                                       self.base.dflt_file_conn_key(),
                                                    sample_global_labels=[sample.get_global_label() for sample in self.samples_in],
                                                    file_type="pstat_helao__file",
                                                    # only add optional keys to header
                                                    # rest will be added later
                                                    hloheader = HloHeaderModel(
                                                        optional = self.FIFO_gamryheader
                                                    ),
                                                   )
                                     }
    
                ))

                for sample in self.samples_in:
                    sample.status = [SampleStatus.preserved]
                    sample.inheritance = SampleInheritance.allow_both

                # clear old samples_in first
                self.active.action.samples_in = []
                # now add updated samples to sample_in again
                await self.active.append_sample(samples = [sample_in for sample_in in self.samples_in],
                                                IO="in"
                                                )

                # signal the IOloop to start the measrurement
                await self.set_IO_signalq(True)

                # need to wait now for the activation of the meas routine
                # and that the active object is activated and sets action status
                while not self.IO_continue:
                    await asyncio.sleep(1)

                # reset continue flag
                self.IO_continue = False

                if self.active:
                    activeDict = self.active.action.as_dict()
                else:
                    activeDict = act.as_dict()
            else:
                self.close_connection()
                activeDict = act.as_dict()

        else:
            # could not open connection
            # open_connection already set the error_code
            activeDict = act.as_dict()                


        return activeDict


    async def technique_LSV(
        self, A: Action,
    ):
        """LSV definition"""
        Vinit = A.action_params["Vinit__V"]
        Vfinal = A.action_params["Vfinal__V"]
        ScanRate = A.action_params["ScanRate__V_s"]
        SampleRate = A.action_params["AcqInterval__s"]
        TTLwait = A.action_params["TTLwait"]
        TTLsend = A.action_params["TTLsend"]
        IErange = A.action_params["IErange"]

        # time expected for measurement to be completed
        eta = abs(Vfinal - Vinit) / ScanRate  # +delay
        sigfunc_params = [
            self.pstat,
            Vinit,
            Vfinal,
            ScanRate,
            SampleRate,
            self.GamryCOM.PstatMode,
        ]
        sigfunc = "GamryCOM.GamrySignalRamp"
        measmode = Gamry_modes.LSV

        # setup partial header which will be completed in measure loop
        self.FIFO_gamryheader = {
                "Vinit__V":Vinit,
                "Vfinal__V":Vfinal,
                "ScanRate__V_s":ScanRate,
                "AcqInterval__s":SampleRate,
                "eta":eta,
        }

        # common
        self.IO_IErange = self.ierangefinder(requested_range = IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend
        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta
        )



        return activeDict

    async def technique_CA(
        self, A: Action,
    ):
        """CA definition"""
        Vval = A.action_params["Vval__V"]
        Tval = A.action_params["Tval__s"]
        SampleRate = A.action_params["AcqInterval__s"]
        TTLwait = A.action_params["TTLwait"]
        TTLsend = A.action_params["TTLsend"]
        IErange = A.action_params["IErange"]

        # time expected for measurement to be completed
        eta = Tval  # +delay
        sigfunc_params = [self.pstat, Vval, Tval, SampleRate, self.GamryCOM.PstatMode]
        sigfunc = "GamryCOM.GamrySignalConst"
        measmode = Gamry_modes.CA

        # setup partial header which will be completed in measure loop
        self.FIFO_gamryheader = {
                "Vval__V":Vval,
                "Tval__s":Tval,
                "AcqInterval__s":SampleRate,
                "eta":eta,
        }

        # common
        self.IO_IErange = self.ierangefinder(requested_range = IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend
        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta
        )
        return activeDict

    async def technique_CP(
        self, A: Action,
    ):
        """CP definition"""
        Ival = A.action_params["Ival"]
        Tval = A.action_params["Tval__s"]
        SampleRate = A.action_params["AcqInterval__s"]
        TTLwait = A.action_params["TTLwait"]
        TTLsend = A.action_params["TTLsend"]
        IErange = A.action_params["IErange"]

        # time expected for measurement to be completed
        eta = Tval  # +delay
        sigfunc_params = [self.pstat, Ival, Tval, SampleRate, self.GamryCOM.GstatMode]
        sigfunc = "GamryCOM.GamrySignalConst"
        measmode = Gamry_modes.CP

        # setup partial header which will be completed in measure loop
        self.FIFO_gamryheader = {
                "Ival":Ival,
                "Tval__s":Tval,
                "AcqInterval__s":SampleRate,
                "eta":eta,
        }

        # common
        self.IO_IErange = self.ierangefinder(requested_range = IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend
        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta
        )
        return activeDict

    async def technique_CV(self, A: Action):
        # Initial value in volts or amps.
        Vinit = A.action_params["Vinit__V"]
        # Apex 1 value in volts or amps.
        Vapex1 = A.action_params["Vapex1__V"]
        # Apex 2 value in volts or amps.
        Vapex2 = A.action_params["Vapex2__V"]
        # Final value in volts or amps.
        Vfinal = A.action_params["Vfinal__V"]
        # Initial scan rate in volts/second or amps/second.
        ScanInit = A.action_params["ScanRate__V_s"]
        # Apex scan rate in volts/second or amps/second.
        ScanApex = A.action_params["ScanRate__V_s"]
        # Final scan rate in volts/second or amps/second.
        ScanFinal = A.action_params["ScanRate__V_s"]
        # Time to hold at Apex 1 in seconds
        HoldTime0 = 0.0
        # Time to hold at Apex 2 in seconds
        HoldTime1 = 0.0
        # Time to hold at Sfinal in seconds
        HoldTime2 = 0.0
        # Time between data acquisition steps.
        SampleRate = A.action_params["AcqInterval__s"]
        # The number of cycles the signal is to be run
        Cycles = A.action_params["Cycles"]
        TTLwait = A.action_params["TTLwait"]
        TTLsend = A.action_params["TTLsend"]
        IErange = A.action_params["IErange"]

        # time expected for measurement to be completed
        eta = abs(Vapex1 - Vinit) / ScanInit
        eta += abs(Vfinal - Vapex2) / ScanFinal
        eta += abs(Vapex2 - Vapex1) / ScanApex * Cycles
        eta += abs(Vapex2 - Vapex1) / ScanApex * 2.0 * (Cycles - 1)  # +delay
        sigfunc_params = [
            self.pstat,
            Vinit,
            Vapex1,
            Vapex2,
            Vfinal,
            ScanInit,
            ScanApex,
            ScanFinal,
            HoldTime0,
            HoldTime1,
            HoldTime2,
            SampleRate,
            Cycles,
            self.GamryCOM.PstatMode,
        ]
        sigfunc = "GamryCOM.GamrySignalRupdn"
        measmode = Gamry_modes.CV

        # setup partial header which will be completed in measure loop
        self.FIFO_gamryheader = {
                "Vinit__V":Vinit,
                "Vapex1__V":Vapex1,
                "Vapex2__V":Vapex2,
                "Vfinal__V":Vfinal,
                "scaninit":ScanInit,
                "scanapex":ScanApex,
                "scanfinal":ScanFinal,
                "holdtime0":HoldTime0,
                "holdtime1":HoldTime1,
                "holdtime2":HoldTime2,
                "AcqInterval__s":SampleRate,
                "cycles":Cycles,
                "eta":eta,
        }

        # common
        self.IO_IErange = self.ierangefinder(requested_range = IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend
        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta
        )
        return activeDict

    async def technique_EIS(self, A: Action):
        """EIS definition"""
        Vval = A.action_params["Vval__V"]
        Tval = A.action_params["Tval__s"]
        Freq = A.action_params["Freq"]
        RMS = A.action_params["RMS"]
        Precision = A.action_params["Precision"]
        SampleRate = A.action_params["AcqInterval__s"]
        TTLwait = A.action_params["TTLwait"]
        TTLsend = A.action_params["TTLsend"]
        IErange = A.action_params["IErange"]

        # time expected for measurement to be completed
        eta = Tval  # +delay
        sigfunc_params = [self.pstat, Vval, Tval, SampleRate, self.GamryCOM.PstatMode]
        sigfunc = "GamryCOM.GamrySignalConst"
        measmode = Gamry_modes.CP
        argv = (Freq, RMS, Precision)

        # setup partial header which will be completed in measure loop
        self.FIFO_gamryheader = {
                "Vval__V":Vval,
                "Tval__s":Tval,
                "freq":Freq,
                "rms":RMS,
                "precision":Precision,
                "AcqInterval__s":SampleRate,
                "eta":eta,
        }

        # common
        self.IO_IErange = self.ierangefinder(requested_range = IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend
        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta,
            setupargs=argv
        )
        return activeDict

    async def technique_OCV(self, A: Action):
        """OCV definition"""
        Tval = A.action_params["Tval__s"]
        SampleRate = A.action_params["AcqInterval__s"]
        # runparams = A.action_params['runparams']
        TTLwait = A.action_params["TTLwait"]
        TTLsend = A.action_params["TTLsend"]
        IErange = A.action_params["IErange"]
        """The OCV class manages data acquisition for a Controlled Voltage I-V curve. However, it is a special purpose curve
        designed for measuring the open circuit voltage over time. The measurement is made in the Potentiostatic mode but with the Cell
        Switch open. The operator may set a voltage stability limit. When this limit is met the Ocv terminates."""
        # time expected for measurement to be completed
        eta = Tval  # +delay
        sigfunc_params = [self.pstat, 0.0, Tval, SampleRate, self.GamryCOM.PstatMode]
        sigfunc = "GamryCOM.GamrySignalConst"
        measmode = Gamry_modes.OCV

        # setup partial header which will be completed in measure loop
        self.FIFO_gamryheader = {
            "Tval__s":Tval,
            "AcqInterval__s":SampleRate,
            "eta":eta,
        }

        # common
        self.IO_IErange = self.ierangefinder(requested_range = IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend

        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta
        )
        return activeDict
