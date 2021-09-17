""" A device class for the Gamry USB potentiostat, used by a FastAPI server instance.

The 'gamry' device class exposes potentiostat measurement functions provided by the
GamryCOM comtypes Win32 module. Class methods are specific to Gamry devices. Device 
configuration is read from config/config.py. 

"""
from helao.core.schema import Action
from helao.core.server import Base
import sys
import comtypes
import comtypes.client as client
import asyncio
import time
from enum import Enum
import psutil
import os
import pyaml

from helao.core.error import error_codes
from helao.core.model import liquid_sample_no, gas_sample_no, solid_sample_no, samples_inout


class Gamry_modes(str, Enum):
    CA = "CA"
    CP = "CP"
    CV = "CV"
    LSV = "LSV"
    EIS = "EIS"
    OCV = "OCV"


# class Gamry_IErange(str, Enum):
#     #NOTE: The ranges listed below are for 300 mA or 30 mA models. For 750 mA models, multiply the ranges by 2.5. For 600 mA models, multiply the ranges by 2.0.
#     auto = 'auto'
#     mode0 = '3pA'
#     mode1 = '30pA'
#     mode2 = '300pA'
#     mode3 = '3nA'
#     mode4 = '30nA'
#     mode5 = '300nA'
#     mode6 = '3μA'
#     mode7 = '30μA'
#     mode8 = '300μA'
#     mode9 = '3mA'
#     mode10 = '30mA'
#     mode11 = '300mA'
#     mode12 = '3A'
#     mode13 = '30A'
#     mode14 = '300A'
#     mode15 = '3kA'

# for IFC1010
class Gamry_IErange(str, Enum):
    # NOTE: The ranges listed below are for 300 mA or 30 mA models. For 750 mA models, multiply the ranges by 2.5. For 600 mA models, multiply the ranges by 2.0.
    auto = "auto"
    mode0 = "1pA"  # doesnt go that low
    mode1 = "10pA"  # doesnt go that low
    mode2 = "100pA"  # doesnt go that low
    mode3 = "1nA"
    mode4 = "10nA"
    mode5 = "100nA"
    mode6 = "1μA"
    mode7 = "10μA"
    mode8 = "100μA"
    mode9 = "1mA"
    mode10 = "10mA"
    mode11 = "100mA"
    mode12 = "1A"
    mode13 = "10A"
    mode14 = "100A"
    mode15 = "1kA"


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
            count, points = self.dtaq.Cook(1000)
            # The columns exposed by GamryDtaq.Cook vary by dtaq and are
            # documented in the Toolkit Reference Manual.
            self.acquired_points.extend(zip(*points))
            # self.buffer[time.time()] = self.acquired_points[-1]
            # self.buffer_size += sys.getsizeof(self.acquired_points[-1]

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
    def __init__(self, actServ: Base):

        self.base = actServ
        self.config_dict = actServ.server_cfg["params"]

        # get Gamry object (Garmry.com)
        # a busy gamrycom can lock up the server
        self.kill_GamryCom()
        self.GamryCOM = client.GetModule(
            ["{BD962F0D-A990-4823-9CF5-284D1CDD9C6D}", 1, 0]
        )
        # self.GamryCOM = client.GetModule(self.config_dict["path_to_gamrycom"])

        self.pstat = None
        self.action = None  # for passing action object from technique method to measure loop
        self.active =None  # for holding active action object, clear this at end of measurement
        self.samples_in=[]
        # status is handled through active, call active.finish()

        if not "dev_id" in self.config_dict:
            self.config_dict["dev_id"] = 0
        # if not 'dev_family' in self.config_dict:
        #     self.config_dict['dev_family'] = 'Reference'

        # if not 'local_data_dump' in self.config_dict:
        #     self.config_dict['local_data_dump'] = 'C:\\INST\\RUNS'

        # self.local_data_dump = self.config_dict['local_data_dump']

        self.Gamry_devid = self.config_dict["dev_id"]
        # self.Gamry_family = self.config_dict['dev_family']

        asyncio.gather(self.init_Gamry(self.Gamry_devid))

        # for Dtaq
        self.dtaqsink = dummy_sink()
        self.dtaq = None
        # empty the data before new one is collected
        # self.data = collections.defaultdict(list)

        # for global IOloop
        # replaces while loop w/async trigger
        self.IO_signalq = asyncio.Queue(1)
        self.IO_do_meas = False  # signal flag for intent (start/stop)
        self.IO_measuring = False  # status flag of measurement
        self.IO_meas_mode = None
        self.IO_sigramp = None
        self.IO_TTLwait = -1
        self.IO_TTLsend = -1
        self.IO_estop = False
        self.IO_IErange = Gamry_IErange("auto")

        myloop = asyncio.get_event_loop()
        # add meas IOloop
        myloop.create_task(self.IOloop())

        # for saving data localy
        self.FIFO_epoch = None
        # self.FIFO_header = ''
        self.FIFO_gamryheader = dict() # measuement specific, will be reset each measurement
        # self.FIFO_name = ''
        # self.FIFO_dir = ''
        self.FIFO_column_headings = []
        self.FIFO_Gamryname = ""
        # holds all sample information
        # self.FIFO_sample = sample_class()
        
        # signals return to endpoint after active was created
        self.IO_continue = False


        ### passing Action dict will contain all UID and action paramter information ###
        # self.runparams = action_runparams
        # self.def_action_params = Action_params()
        # self.action_params = self.def_action_params.as_dict()

    async def IOloop(self):
        """This is main Gamry measurement loop which always needs to run
        else if measurement is done in FastAPI calls we will get timeouts"""
        try:
            while True:
                self.IO_do_meas = await self.IO_signalq.get()
                if self.IO_do_meas and not self.IO_measuring:
                    # are we in estop?
                    if not self.IO_estop:
                        self.base.print_message(" ... Gamry got measurement request")
                        await self.measure()
                        if self.IO_estop:
                            self.base.print_message(" ... Gamry is in estop.")
                            # await self.stat.set_estop()
                        else:
                            self.base.print_message(" ... setting Gamry to idle")
                            # await self.stat.set_idle()
                        self.base.print_message(" ... Gamry measurement is done")
                    else:
                        self.IO_do_meas = False
                        self.base.print_message(" ... Gamry is in estop.")
                        # await self.stat.set_estop()
                elif self.IO_do_meas and self.IO_measuring:
                    self.base.print_message(" ... got measurement request but Gamry is busy")
                elif not self.IO_do_meas and self.IO_measuring:
                    self.base.print_message(" ... got stop request, measurement will stop next cycle")
                else:
                    self.base.print_message(" ... got stop request but Gamry is idle")
        except asyncio.CancelledError:
            self.base.print_message("IOloop task was cancelled")

    def kill_GamryCom(self):
        """script can be blocked or crash if GamryCom is still open and busy"""
        pyPids = {
            p.pid: p
            for p in psutil.process_iter(["name", "connections"])
            if p.info["name"].startswith("GamryCom")
        }

        for pid in pyPids.keys():
            self.base.print_message(f" ... killing GamryCom on PID: {pid}")
            p = psutil.Process(pid)
            for _ in range(3):
                # os.kill(p.pid, signal.SIGTERM)
                p.terminate()
                time.sleep(0.5)
                if not psutil.pid_exists(p.pid):
                    self.base.print_message(" ... Successfully terminated GamryCom.")
                    return True
            if psutil.pid_exists(p.pid):
                self.base.print_message(" ... Failed to terminate server GamryCom after 3 retries.")
                return False

    async def init_Gamry(self, devid):
        """connect to a Gamry"""
        try:
            self.devices = client.CreateObject("GamryCOM.GamryDeviceList")
            self.base.print_message(f" ... GamryDeviceList: {self.devices.EnumSections()}")
            # self.base.print_message(f" ... {len(self.devices.EnumSections())}")
            if len(self.devices.EnumSections()) >= devid + 1:
                self.FIFO_Gamryname = self.devices.EnumSections()[devid]

                if self.FIFO_Gamryname.find("IFC") == 0:
                    self.pstat = client.CreateObject("GamryCOM.GamryPC6Pstat")
                    self.base.print_message(f" ... Gamry, using Interface {self.pstat}")
                elif self.FIFO_Gamryname.find("REF") == 0:
                    self.pstat = client.CreateObject("GamryCOM.GamryPC5Pstat")
                    self.base.print_message(f" ... Gamry, using Reference {self.pstat}")
                # else: # old version before Framework 7.06
                #     self.pstat = client.CreateObject('GamryCOM.GamryPstat')
                #     self.base.print_message(' ... Gamry, using Farmework , 7.06?', self.pstat)

                self.pstat.Init(self.devices.EnumSections()[devid])
                # self.base.print_message(" ... ", self.pstat)

            else:
                self.pstat = None
                self.base.print_message(
                    f" ... No potentiostat is connected on DevID {devid}! Have you turned it on?"
                )

        except Exception as e:
            # this will lock up the potentiostat server
            # happens when a not activated Gamry is connected and turned on
            # TODO: find a way to avoid it
            self.base.print_message(" ... fatal error initializing Gamry:", e)

    async def open_connection(self):
        """Open connection to Gamry"""
        # this just tries to open a connection with try/catch
        await asyncio.sleep(0.001)
        if not self.pstat:
            await self.init_Gamry(self.Gamry_devid)
        try:
            if self.pstat:
                self.pstat.Open()
                return {"potentiostat_connection": "connected"}
            else:
                return {"potentiostat_connection": "not initialized"}

        except Exception:
            # self.pstat = None
            return {"potentiostat_connection": "error"}

    async def close_connection(self):
        """Close connection to Gamry"""
        # this just tries to close a connection with try/catch
        await asyncio.sleep(0.001)
        try:
            if self.pstat:
                self.pstat.Close()
                return {"potentiostat_connection": "closed"}
            else:
                return {"potentiostat_connection": "not initialized"}
        except Exception:
            # self.pstat = None
            return {"potentiostat_connection": "error"}

    async def measurement_setup(self, AcqFreq, mode: Gamry_modes = None, *argv):
        """setting up the measurement parameters
        need to initialize and open connection to gamry first"""
        await asyncio.sleep(0.001)
        if self.pstat:
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

            if self.IO_IErange == Gamry_IErange.auto:
                self.base.print_message(" ... auto I range selected")
                self.pstat.SetIERange(0.03)
                self.pstat.SetIERangeMode(True)
            else:
                self.base.print_message(f" ... {self.IO_IErange.value} I range selected")
                self.base.print_message(f" ... {IErangesdict[self.IO_IErange.name]} I range selected")
                self.pstat.SetIERange(IErangesdict[self.IO_IErange.name])
                self.pstat.SetIERangeMode(False)
            # elif self.IO_IErange == Gamry_IErange.mode0:
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
                return {"measurement_setup": f"mode_{mode}_not_supported"}

            try:
                self.dtaq = client.CreateObject(Dtaqmode)
                if Dtaqtype:
                    self.dtaq.Init(self.pstat, Dtaqtype, *argv)
                else:
                    self.dtaq.Init(self.pstat, *argv)
            except Exception as e:
                self.base.print_message(" ... Gamry Error:", gamry_error_decoder(e))

            # This method, when enabled,
            # allows for longer experiments with fewer points,
            # but still acquires data quickly around each step.
            if mode == Gamry_modes.CA:
                self.dtaq.SetDecimation(False)
            elif mode == Gamry_modes.CP:
                self.dtaq.SetDecimation(False)

            self.dtaqsink = GamryDtaqEvents(self.dtaq)
            self.base.print_message(f"!!! initialized dtaqsink with status {self.dtaqsink.status}")
            return {"measurement_setup": f"setup_{mode}"}
        else:
            return {"measurement_setup": "not initialized"}


    async def measure(self):
        """performing a measurement with the Gamry
        this is the main function for the instrument"""
        await asyncio.sleep(0.001)
        if self.pstat:

            # write header lines with one function call
            self.FIFO_gamryheader.update(
                    {
                    "gamry":self.FIFO_Gamryname,
                    "ierangemode":self.IO_IErange.name,
                    "techniqueparamsname":"",
                    "techniquename":self.IO_meas_mode.name,
                    "version":0.2,
                    "column_headings":self.FIFO_column_headings,
                    }
            )


            file_sample_label={}
            for samples_in in self.samples_in:
                label = None
                if samples_in.sample_type == "liquid":
                    if samples_in.liquid is not None:
                        label = f"{samples_in.machine}__{samples_in.liquid.id}"
                    
                elif samples_in.sample_type == "gas":
                    if samples_in.gas is not None:
                        label = f"{samples_in.machine}__{samples_in.gas.id}"
                elif samples_in.sample_type == "solid":
                    if samples_in.solid is not None:
                        label = f"{samples_in.solid.plate_id}__{samples_in.solid.sample_no}"

                elif samples_in.sample_type == "sample_assembly":
                    label = samples_in.label
                
                if label is not None:
                    if samples_in.sample_type in file_sample_label:
                        file_sample_label[samples_in.sample_type].append(label)
                    else:
                        file_sample_label[samples_in.sample_type]=[label]

            if len(file_sample_label) == 0:
                file_sample_label = None

            self.active = await self.base.contain_action(
                self.action,
                file_type="pstat_helao__file",
                file_group="helao_files",
                file_data_keys=self.FIFO_column_headings,
                file_sample_label=file_sample_label,
                header=self.FIFO_gamryheader,
            )
            self.base.print_message(f"!!! Active action uuid is {self.active.action.action_uuid}")
            # active object is set so we can set the continue flag
            self.IO_continue = True
            await self.update_action_sampleinout()


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
                self.base.print_message("!!! signal ramp set")
            except Exception as e:
                self.base.print_message(" ... gamry error in signal")
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

            self.base.print_message(".... DigiOut:", self.pstat.DigitalOut())
            self.base.print_message(".... DigiIn:", self.pstat.DigitalIn())
            # first, wait for trigger
            if self.IO_TTLwait >= 0:
                while self.IO_do_meas:
                    bits = self.pstat.DigitalIn()
                    self.base.print_message(" ... Gamry DIbits", bits)
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
                #                self.pstat.SetDigitalOut(self.IO_TTLsend,self.IO_TTLsend)
                self.base.print_message(
                    self.pstat.SetDigitalOut(self.IO_TTLsend, self.IO_TTLsend)
                )  # bitmask on
            #                self.base.print_message(self.pstat.SetDigitalOut(0,self.IO_TTLsend)) # bitmask off
            # if self.IO_TTLsend == 0:
            #     #0001
            #     self.pstat.SetDigitalOut(1,1)
            # elif self.IO_TTLsend == 1:
            #     #0010
            #     self.pstat.SetDigitalOut(2,2)
            # elif self.IO_TTLsend == 2:
            #     #0100
            #     self.pstat.SetDigitalOut(4,4)
            # elif self.IO_TTLsend == 3:
            #     #1000
            #     self.pstat.SetDigitalOut(8,8)

            # turn on the potentiostat output
            if self.IO_meas_mode == Gamry_modes.OCV:
                self.pstat.SetCell(self.GamryCOM.CellMon)
            else:
                self.pstat.SetCell(self.GamryCOM.CellOn)

            # Use the following code to discover events:
            # client.ShowEvents(dtaqcpiv)
            connection = client.GetEvents(self.dtaq, self.dtaqsink)

            try:
                # get current time and start measurement
                self.dtaq.Run(True)
                self.base.print_message("!!! running dtaq")
                self.IO_measuring = True
            except Exception as e:
                self.base.print_message(" ... gamry error run")
                self.base.print_message(gamry_error_decoder(e))
                self.pstat.SetCell(self.GamryCOM.CellOff)
                del connection
                return {"measure": "run_error"}



            realtime = await self.active.set_realtime()
            if self.active:
                self.active.enqueue_data_nowait(pyaml.dump({"epoch_ns":realtime}))
                self.active.enqueue_data_nowait("%%")
                    
                    
            # dtaqsink.status might still be 'idle' if sleep is too short
            await asyncio.sleep(0.04)
            client.PumpEvents(0.001)
            sink_status = self.dtaqsink.status
            counter = 0

            # self.base.print_message(f"!!! sink_status is {sink_status}, loop flag is {self.IO_do_meas}")

            while (
                # counter < len(self.dtaqsink.acquired_points)
                self.IO_do_meas
                and (sink_status != "done" or counter < len(self.dtaqsink.acquired_points))
            ):
                # need some await points
                await asyncio.sleep(0.001)
                client.PumpEvents(0.001)
                if counter < len(self.dtaqsink.acquired_points):
                    tmp_datapoints = self.dtaqsink.acquired_points[counter]
                    # Need to get additional data for EIS
                    if self.IO_meas_mode == Gamry_modes.EIS:
                        test = list(tmp_datapoints)
                        test.append(self.dtaqsink.dtaq.Zreal())
                        test.append(self.dtaqsink.dtaq.Zimag())
                        test.append(self.dtaqsink.dtaq.Zsig())
                        test.append(self.dtaqsink.dtaq.Zphz())
                        test.append(self.dtaqsink.dtaq.Zfreq())
                        test.append(self.dtaqsink.dtaq.Zmod())
                        tmp_datapoints = tuple(test)
    
                    if self.active:
                        if self.active.action.save_data:
                            # self.base.print_message(' ... gamry pushing data:', {k: [v] for k, v in zip(self.FIFO_column_headings, tmp_datapoints)})
                            await self.active.enqueue_data(
                                {
                                    k: [v]
                                    for k, v in zip(
                                        self.FIFO_column_headings, tmp_datapoints
                                    )
                                }
                            )
                        # else:
                        # self.base.print_message(' ... gamry not pushing data:', {k: [v] for k, v in zip(self.FIFO_column_headings, tmp_datapoints)})
                    # else:
                    # self.base.print_message(' ... gamry not pushing data:', {k: [v] for k, v in zip(self.FIFO_column_headings, tmp_datapoints)})    
                    counter += 1

                sink_status = self.dtaqsink.status
                # self.base.print_message(sink_status, self.IO_do_meas)



            self.IO_measuring = False
            self.dtaq.Run(False)
            self.pstat.SetCell(self.GamryCOM.CellOff)
            self.base.print_message("!!! signaling IOloop to stop")
            await self.close_connection()
            await self.IO_signalq.put(False)
            # # delete this at the very last step
            del connection
            # connection will be closed in IOloop
            self.dtaqsink = dummy_sink()

            self.base.print_message(" ... gamry finishes active action")
            _ = await self.active.finish()
            self.active = None
            self.action = None
            self.samples_in=[]

            return {"measure": f"done_{self.IO_meas_mode}"}
        else:
            self.IO_measuring = False
            return {"measure": "not initialized"}

    async def status(self):
        """return status of data structure"""
        await asyncio.sleep(0.001)
        return self.dtaqsink.status

    async def stop(self):
        """stops measurement, writes all data and returns from meas loop"""
        # turn off cell and run before stopping meas loop
        if self.IO_measuring:
            # file and Gamry connection will be closed with the meas loop
            await self.IO_signalq.put(False)

    async def estop(self, A: Action):
        """same as stop, set or clear estop flag with switch parameter"""
        # should be the same as stop()
        switch = A.action_params["switch"]
        
        self.IO_estop = switch
        if self.IO_measuring:
            if switch:
                await self.IO_signalq.put(False)
                await self.base.set_estop(
                    self.active.active.action_name, self.active.active.action_uuid
                )
                # can only set action server estop on a running uuid

    async def technique_wrapper(
        self, 
        act, 
        measmode, 
        sigfunc, 
        sigfunc_params, 
        samplerate, 
        eta=0.0,
        samples_in=[],
        setupargs=[]
    ):
        # open connection, will be closed after measurement in IOloop
        retval = await self.open_connection()
        activeDict = dict()
        if retval["potentiostat_connection"] == "connected":
            if self.pstat and not self.IO_do_meas:
                # set parameters for IOloop meas
                self.IO_meas_mode = measmode
                await self.measurement_setup(
                    1.0 / samplerate, self.IO_meas_mode, *setupargs
                )
                # setup the experiment specific signal ramp
                self.IO_sigramp = client.CreateObject(sigfunc)
                try:
                    self.IO_sigramp.Init(*sigfunc_params)
                    err_code = "0"
                except Exception as e:
                    err_code = gamry_error_decoder(e)
                    self.base.print_message(err_code)

                self.action = act
                self.samples_in=samples_in
                # signal the IOloop to start the measrurement
                await self.IO_signalq.put(True)
                # wait for data to appear in multisubscriber queue before returning active dict
                # async for data_msg in self.base.data_q.subscribe():
                #     for act_uuid, _ in data_msg.items():
                #         if act.action_uuid == act_uuid:
                #             activeDict = self.active.action.as_dict()
                #     if activeDict:
                #         break

                # need to wait now for the activation of the meas routine
                # and that the active object is activated and sets action status

                while not self.IO_continue:
                    await asyncio.sleep(1)

                # reset continue flag
                self.IO_continue = False

                err_code = "none"

                if self.active:
                    activeDict = self.active.action.as_dict()
                else:
                    activeDict = act.as_dict()                

            elif self.IO_measuring:
                activeDict = act.as_dict()                
                err_code = "meas already in progress"
            else:
                activeDict = act.as_dict()                
                err_code = "not initialized"
        else:
            activeDict = act.as_dict()                
            err_code = retval["potentiostat_connection"]

        
        activeDict["data"] = {"err_code": err_code, "eta": eta}
        return activeDict

    async def technique_LSV(
        self, A: Action,
    ):
        """LSV definition"""
        samples_in = A.action_params.get("samples_in",None)
        if samples_in is not None:
            samples_in = self.to_samples_inout(samples_in, A)
        Vinit = A.action_params["Vinit"]
        Vfinal = A.action_params["Vfinal"]
        ScanRate = A.action_params["ScanRate"]
        SampleRate = A.action_params["SampleRate"]
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
                "Vinit":Vinit,
                "Vfinal":Vfinal,
                "scanrate":ScanRate,
                "samplerate":SampleRate,
                "eta":eta,
        }

        # common
        self.IO_IErange = Gamry_IErange(IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend
        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta,
            samples_in=samples_in
        )



        return activeDict

    async def technique_CA(
        self, A: Action,
    ):
        """CA definition"""
        samples_in = A.action_params.get("samples_in",None)
        if samples_in is not None:
            samples_in = self.to_samples_inout(samples_in, A)
        Vval = A.action_params["Vval"]
        Tval = A.action_params["Tval"]
        SampleRate = A.action_params["SampleRate"]
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
                "Vval":Vval,
                "Tval":Tval,
                "samplerate":SampleRate,
                "eta":eta,
        }

        # common
        self.IO_IErange = Gamry_IErange(IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend
        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta,
            samples_in=samples_in
        )
        return activeDict

    async def technique_CP(
        self, A: Action,
    ):
        """CP definition"""
        samples_in = A.action_params.get("samples_in",None)
        if samples_in is not None:
            samples_in = self.to_samples_inout(samples_in, A)
        Ival = A.action_params["Ival"]
        Tval = A.action_params["Tval"]
        SampleRate = A.action_params["SampleRate"]
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
                "Tval":Tval,
                "samplerate":SampleRate,
                "eta":eta,
        }

        # common
        self.IO_IErange = Gamry_IErange(IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend
        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta,
            samples_in=samples_in
        )
        return activeDict

    async def technique_CV(self, A: Action):
        samples_in = A.action_params.get("samples_in",None)
        if samples_in is not None:
            samples_in = self.to_samples_inout(samples_in, A)
        Vinit = A.action_params["Vinit"]
        Vapex1 = A.action_params["Vapex1"]
        Vapex2 = A.action_params["Vapex2"]
        Vfinal = A.action_params["Vfinal"]
        ScanInit = A.action_params["ScanInit"]
        ScanApex = A.action_params["ScanApex"]
        ScanFinal = A.action_params["ScanFinal"]
        HoldTime0 = A.action_params["HoldTime0"]
        HoldTime1 = A.action_params["HoldTime1"]
        HoldTime2 = A.action_params["HoldTime2"]
        SampleRate = A.action_params["SampleRate"]
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
                "Vinit":Vinit,
                "Vapex1":Vapex1,
                "Vapex2":Vapex2,
                "Vfinal":Vfinal,
                "scaninit":ScanInit,
                "scanapex":ScanApex,
                "scanfinal":ScanFinal,
                "holdtime0":HoldTime0,
                "holdtime1":HoldTime1,
                "holdtime2":HoldTime2,
                "samplerate":SampleRate,
                "cycles":Cycles,
                "eta":eta,
        }

        # common
        self.IO_IErange = Gamry_IErange(IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend
        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta,
            samples_in=samples_in
        )
        return activeDict

    async def technique_EIS(self, A: Action):
        """EIS definition"""
        samples_in = A.action_params.get("samples_in",None)
        if samples_in is not None:
            samples_in = self.to_samples_inout(samples_in, A)
        Vval = A.action_params["Vval"]
        Tval = A.action_params["Tval"]
        Freq = A.action_params["Freq"]
        RMS = A.action_params["RMS"]
        Precision = A.action_params["Precision"]
        SampleRate = A.action_params["SampleRate"]
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
                "Vval":Vval,
                "Tval":Tval,
                "freq":Freq,
                "rms":RMS,
                "precision":Precision,
                "samplerate":SampleRate,
                "eta":eta,
        }

        # common
        self.IO_IErange = Gamry_IErange(IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend
        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta,
            samples_in=samples_in,
            setupargs=argv
        )
        return activeDict

    async def technique_OCV(self, A: Action):
        """OCV definition"""
        samples_in = A.action_params.get("samples_in",None)
        if samples_in is not None:
            samples_in = self.to_samples_inout(samples_in, A)
        Tval = A.action_params["Tval"]
        SampleRate = A.action_params["SampleRate"]
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
            "Tval":Tval,
            "samplerate":SampleRate,
            "eta":eta,
        }

        # common
        self.IO_IErange = Gamry_IErange(IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend

        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta,
            samples_in=samples_in
        )
        return activeDict


    def to_samples_inout(self, samples_in_dictlist, A):
        if type(samples_in_dictlist) is not list:
            samples_in_dictlist = [samples_in_dictlist]
        samples_in_retlist = []

        for samples_in_dict in samples_in_dictlist:
            solid = samples_in_dict.get("solid",None)
            if solid is not None:
                # print(solid)
                solid = solid_sample_no(**solid)
            liquid = samples_in_dict.get("liquid",None)
            if liquid is not None:
                # print(liquid)
                liquid = liquid_sample_no(**liquid)
            gas = samples_in_dict.get("gas",None)
            if gas is not None:
                # print(gas)
                gas = gas_sample_no(**gas)
            machine = samples_in_dict.get("machine",None)
            if machine is None:
                machine = A.machine_name
    
            samples_in_retlist.append(samples_inout(
                       sample_type = samples_in_dict.get("sample_type",""),
                       in_out = samples_in_dict.get("in_out",""),
                       label = samples_in_dict.get("label",None),
                       solid = solid,
                       liquid = liquid,
                       gas = gas,
                       status = samples_in_dict.get("status",None),
                       inheritance = samples_in_dict.get("inheritance",None),
                       machine = machine
                )
            )
        return samples_in_retlist


    async def update_action_sampleinout(self):
        """Updates action sample_in and sample_out"""
        if self.active:
            for samples_in in self.samples_in:
                await self.active.append_sample(samples_in)
            

