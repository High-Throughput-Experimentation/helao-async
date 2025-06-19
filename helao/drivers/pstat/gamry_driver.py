""" A device class for the Gamry USB potentiostat, used by a FastAPI server instance.

The 'gamry' device class exposes potentiostat measurement functions provided by the
GamryCOM comtypes Win32 module. Class methods are specific to Gamry devices. Device 
configuration is read from config/config.py. 

"""

__all__ = [
    "gamry",
    "Gamry_modes",
]

import comtypes
import comtypes.client as client
import asyncio
import time
import psutil
import traceback
from collections import defaultdict

import numpy as np

from helao.helpers import helao_logging as logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

from helao.helpers.premodels import Action
from helao.servers.base import Base
from helao.core.error import ErrorCodes
from helao.core.models.sample import SampleInheritance, SampleStatus
from helao.core.models.data import DataModel
from helao.core.models.file import FileConnParams, HloHeaderModel
from helao.helpers.active_params import ActiveParams
from helao.core.models.hlostatus import HloStatus
from helao.helpers.sample_api import UnifiedSampleDataAPI

from helao.drivers.pstat.enum import (
    Gamry_modes,
    Gamry_IErange_IFC1010,
    Gamry_IErange_REF600,
    Gamry_IErange_PCI4G300,
    Gamry_IErange_PCI4G750,
    Gamry_IErange_dflt,
)


def gamry_error_decoder(e):
    if isinstance(e, comtypes.COMError):
        hresult = 2**32 + e.args[0]
        if hresult & 0x20000000:
            return GamryCOMError("0x{0:08x}: {1}".format(2**32 + e.args[0], e.args[1]))
    return e


class GamryCOMError(Exception):
    """definition of error handling things from gamry"""



class GamryDtaqEvents:
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
        self.config_dict = action_serv.server_cfg.get("params", {})
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
        self.action = (
            None  # for passing action object from technique method to measure loop
        )
        self.active = (
            None  # for holding active action object, clear this at end of measurement
        )
        self.pstat_connection = None
        self.samples_in = []
        # status is handled through active, call active.finish()
        self.gamry_range_enum = Gamry_IErange_dflt
        self.allow_no_sample = self.config_dict.get("allow_no_sample", False)
        self.Gamry_devid = self.config_dict.get("dev_id", 0)
        self.filterfreq_hz = 1.0 * self.config_dict.get("filterfreq_hz", 1000.0)
        self.grounded = int(self.config_dict.get("grounded", True))
        self.data_buffer_size = 100
        self.data_buffer = defaultdict(list)

        asyncio.gather(self.init_Gamry(self.Gamry_devid))

        # for Dtaq
        self.dtaqsink = dummy_sink()
        self.dtaq = None
        self.sample_rate = 0.1

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
        self.FIFO_gamryheader = {}  # measuement specific, reset after each measurement
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
                    if not self.base.actionservermodel.estop:
                        LOGGER.info("Gamry got measurement request")
                        await self.measure()
                        if self.base.actionservermodel.estop:
                            self.IO_do_meas = False
                            LOGGER.error("Gamry is in estop after measurement.")
                        else:
                            LOGGER.info("setting Gamry to idle")
                            # await self.stat.set_idle()
                        LOGGER.info("Gamry measurement is done")
                    else:
                        self.active.action.action_status.append(HloStatus.estopped)
                        self.IO_do_meas = False
                        LOGGER.error("Gamry is in estop.")

                # endpoint can return even we got errors
                self.IO_continue = True

                if self.active:
                    LOGGER.info("gamry finishes active action")
                    _ = await self.active.finish()
                    self.active = None
                    self.action = None
                    self.samples_in = []

        except asyncio.CancelledError:
            # endpoint can return even we got errors
            self.IO_continue = True
            LOGGER.info("IOloop task was cancelled")

    def kill_GamryCom(self):
        """script can be blocked or crash if GamryCom is still open and busy"""
        pyPids = {
            p.pid: p
            for p in psutil.process_iter(["name"])
            if p.info["name"].startswith("GamryCom")
        }

        for pid in pyPids:
            LOGGER.info(f"killing GamryCom on PID: {pid}")
            p = psutil.Process(pid)
            for _ in range(3):
                # os.kill(p.pid, signal.SIGTERM)
                p.terminate()
                time.sleep(0.5)
                if not psutil.pid_exists(p.pid):
                    LOGGER.info("Successfully terminated GamryCom.")
                    return True
            if psutil.pid_exists(p.pid):
                LOGGER.info("Failed to terminate server GamryCom after 3 retries.")
                return False

    async def init_Gamry(self, devid):
        """connect to a Gamry"""
        try:
            self.devices = client.CreateObject("GamryCOM.GamryDeviceList")
            LOGGER.info(f"GamryDeviceList: {self.devices.EnumSections()}")
            # LOGGER.info(f"{len(self.devices.EnumSections())}")
            if len(self.devices.EnumSections()) >= devid + 1:
                self.FIFO_Gamryname = self.devices.EnumSections()[devid]

                if self.FIFO_Gamryname.find("IFC") == 0:
                    self.pstat = client.CreateObject("GamryCOM.GamryPC6Pstat")
                    LOGGER.info(f"Gamry, using Interface {self.pstat}")
                elif self.FIFO_Gamryname.find("REF") == 0:
                    self.pstat = client.CreateObject("GamryCOM.GamryPC5Pstat")
                    LOGGER.info(f"Gamry, using Reference {self.pstat}")
                elif self.FIFO_Gamryname.find("PCI") == 0:
                    self.pstat = client.CreateObject("GamryCOM.GamryPstat")
                    LOGGER.info(f"Gamry, using PCI {self.pstat}")
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
                # LOGGER.info("")
                LOGGER.info(f"Connected to Gamry on DevID {devid}!")

            else:
                self.pstat = None
                LOGGER.error(f"No potentiostat is connected on DevID {devid}! Have you turned it on?")

        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            # this will lock up the potentiostat server
            # happens when a not activated Gamry is connected and turned on
            # TODO: find a way to avoid it
            LOGGER.error(f"fatal error initializing Gamry: {repr(e), tb,}")
        self.ready = True

    async def open_connection(self):
        """Open connection to Gamry"""
        # this just tries to open a connection with try/catch
        await asyncio.sleep(0.01)
        if not self.pstat:
            await self.init_Gamry(self.Gamry_devid)
        try:
            if self.pstat:
                self.pstat.Open()
                return ErrorCodes.none
            else:
                LOGGER.error("open_connection: Gamry not initialized!")
                return ErrorCodes.not_initialized

        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            # self.pstat = None
            LOGGER.error(f"Gamry error init", exc_info=True)
            return ErrorCodes.critical_error

    def close_connection(self):
        """Close connection to Gamry"""
        # this just tries to close a connection with try/catch
        try:
            if self.pstat:
                self.pstat.Close()
                return ErrorCodes.none
            else:
                LOGGER.error("close_connection: Gamry not initialized!")
                return ErrorCodes.not_initialized
        except Exception:
            # self.pstat = None
            return ErrorCodes.critical_error

    def close_pstat_connection(self):
        if self.IO_measuring:
            self.IO_do_meas = False  # will stop meas loop
            self.IO_measuring = False
            self.dtaq.Run(False)
            self.pstat.SetCell(self.GamryCOM.CellOff)
            LOGGER.info("signaling IOloop to stop")
            self.set_IO_signalq_nowait(False)

            # delete this at the very last step
            self.close_connection()
            self.pstat_connection = None
            self.dtaqsink = dummy_sink()
            self.dtaq = None

        else:
            pass

    async def measurement_setup(self, act_params, mode: Gamry_modes = None, *argv):
        """setting up the measurement parameters
        need to initialize and open connection to gamry first"""
        await asyncio.sleep(0.01)
        error = ErrorCodes.none
        self.data_buffer = defaultdict(list) 
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
                # pstat.InstrumentSpecificInitialize ()
                self.pstat.SetPosFeedEnable(False)  # False

                # pstat.SetStability (StabilityFast)
                self.pstat.SetIEStability(self.GamryCOM.StabilityFast)
                # Fast (0), Medium (1), Slow (2)
                # StabilityFast (0), StabilityNorm (1), StabilityMed (1), StabilitySlow (2)
                # pstat.SetCASpeed(1)#GamryCOM.CASpeedNorm)
                # CASpeedFast (0), CASpeedNorm (1), CASpeedMed (2), CASpeedSlow (3)
                if not self.FIFO_Gamryname.startswith("IFC1010"):
                    self.pstat.SetSenseSpeedMode(True)
                # pstat.SetConvention (PHE200_IConvention)
                # anodic currents are positive
                self.pstat.SetIConvention(self.GamryCOM.Anodic)

                self.pstat.SetGround(self.grounded)  # 0=Float, 1=Earth

                # Set current channel range.
                # Setting the IchRange using a voltage is preferred. The measured current is converted into a voltage on the I channel using the I/E converter.
                # 0 0.03 V range, 1 0.30 V range, 2 3.00 V range, 3 30.00 V (PCI4) 12V (PC5)
                # The floating point number is the maximum anticipated voltage (in Volts).
                ichrangeval = self.pstat.TestIchRange(3.0)
                self.pstat.SetIchRange(ichrangeval)
                self.pstat.SetIchRangeMode(True)  # auto-set
                self.pstat.SetIchOffsetEnable(False)
                # per framework manual, first call TestIchFilter before setting SetIchFilter
                ichfilterval = self.pstat.TestIchFilter(self.filterfreq_hz)
                self.pstat.SetIchFilter(ichfilterval)

                # Set voltage channel range.
                vchrangeval = self.pstat.TestVchRange(12.0)
                self.pstat.SetVchRange(vchrangeval)
                self.pstat.SetVchRangeMode(True)
                self.pstat.SetVchOffsetEnable(False)
                # per framework manual, first call TestVchFilter before setting SetVchFilter
                vchfilterval = self.pstat.TestVchFilter(self.filterfreq_hz)
                self.pstat.SetVchFilter(vchfilterval)

                # Sets the range of the Auxiliary A/D input.
                self.pstat.SetAchRange(3.0)

                # pstat.SetIERangeLowerLimit(None)

                # Sets the I/E Range of the potentiostat.
                self.pstat.SetIERange(0.03)
                # Enable or disable current measurement auto-ranging.
                if not self.FIFO_Gamryname.startswith("IFC1010"):
                    self.pstat.SetIERangeMode(True)

                if self.IO_IErange == self.gamry_range_enum.auto:
                    LOGGER.info("auto I range selected")
                    self.pstat.SetIERange(0.03)
                    if not self.FIFO_Gamryname.startswith("IFC1010"):
                        self.pstat.SetIERangeMode(True)
                else:
                    LOGGER.info(f"I-range: {self.IO_IErange.value}, mode{IErangesdict[self.IO_IErange.name]} selected")
                    self.pstat.SetIERange(IErangesdict[self.IO_IErange.name])
                    if not self.FIFO_Gamryname.startswith("IFC1010"):
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

                dtaq_lims = []

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
                    self.pstat.SetVchRangeMode(False)
                    setpointv = np.abs(act_params["Vval__V"])
                    vchrangeval = self.pstat.TestVchRange(setpointv * 1.1)
                    self.pstat.SetVchRange(vchrangeval)
                    # subset of stop conditions
                    if act_params.get("stop_imin", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopXMin(True, act_params["stop_imin"])
                        )
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetThreshIMin(
                                True, act_params["stop_imin"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopXMin(False, 0.0))
                        dtaq_lims.append(lambda dtaq: dtaq.SetThreshIMin(False, 0.0))
                    if act_params.get("stop_imax", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopXMax(True, act_params["stop_imax"])
                        )
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetThreshIMax(
                                True, act_params["stop_imax"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopXMax(False, 0.0))
                        dtaq_lims.append(lambda dtaq: dtaq.SetThreshIMax(False, 0.0))
                    if act_params.get("stopdelay_imin", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopAtDelayXMin(
                                act_params["stopdelay_imin"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopAtDelayXMin(1))
                    if act_params.get("stopdelay_imax", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopAtDelayXMax(
                                act_params["stopdelay_imax"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopAtDelayXMax(1))
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
                    self.pstat.SetIERangeMode(False)
                    setpointie = np.abs(act_params["Ival__A"])
                    ierangeval = self.pstat.TestIERange(setpointie)
                    self.pstat.SetIERange(ierangeval)
                    # subset of stop conditions

                    LOGGER.info(f"Using vmin threshold = {act_params['stop_vmin']}, {type(act_params['stop_vmin'])}")
                    if act_params.get("stop_vmin", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopXMin(True, act_params["stop_vmin"])
                        )
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetThreshVMin(
                                True, act_params["stop_vmin"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopXMin(False, 0.0))
                        dtaq_lims.append(lambda dtaq: dtaq.SetThreshVMin(False, 0.0))
                    if act_params.get("stop_vmax", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopXMax(True, act_params["stop_vmax"])
                        )
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetThreshVMax(
                                True, act_params["stop_vmax"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopXMax(False, 0.0))
                        dtaq_lims.append(lambda dtaq: dtaq.SetThreshVMax(False, 0.0))
                    if act_params.get("stopdelay_vmin", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopAtDelayXMin(
                                act_params["stopdelay_vmin"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopAtDelayXMin(1))
                    if act_params.get("stopdelay_vmax", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopAtDelayXMax(
                                act_params["stopdelay_vmax"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopAtDelayXMax(1))
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
                    self.pstat.SetVchRangeMode(False)
                    vkeys = ["Vinit", "Vapex1", "Vapex2", "Vfinal"]
                    setpointvs = [act_params[f"{x}__V"] for x in vkeys]
                    setpointv = np.max(np.abs(setpointvs))
                    vchrangeval = self.pstat.TestVchRange(setpointv * 1.1)
                    self.pstat.SetVchRange(vchrangeval)
                    # subset of stop conditions
                    if act_params.get("stop_imin", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopIMin(True, act_params["stop_imin"])
                        )
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetThreshIMin(
                                True, act_params["stop_imin"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopIMin(False, 0.0))
                        dtaq_lims.append(lambda dtaq: dtaq.SetThreshIMin(False, 0.0))
                    if act_params.get("stop_imax", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopIMax(True, act_params["stop_imax"])
                        )
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetThreshIMax(
                                True, act_params["stop_imax"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopIMax(False, 0.0))
                        dtaq_lims.append(lambda dtaq: dtaq.SetThreshIMax(False, 0.0))
                    if act_params.get("stopdelay_imin", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopAtDelayIMin(
                                act_params["stopdelay_imin"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopAtDelayIMin(1))
                    if act_params.get("stopdelay_imax", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopAtDelayIMax(
                                act_params["stopdelay_imax"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopAtDelayIMax(1))
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
                    self.pstat.SetVchRangeMode(False)
                    vkeys = ["Vinit", "Vfinal"]
                    setpointvs = [act_params[f"{x}__V"] for x in vkeys]
                    setpointv = np.max(np.abs(setpointvs))
                    vchrangeval = self.pstat.TestVchRange(setpointv * 1.1)
                    self.pstat.SetVchRange(vchrangeval)
                    if act_params.get("stop_imin", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopIMin(True, act_params["stop_imin"])
                        )
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetThreshIMin(
                                True, act_params["stop_imin"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopIMin(False, 0.0))
                        dtaq_lims.append(lambda dtaq: dtaq.SetThreshIMin(False, 0.0))
                    if act_params.get("stop_imax", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopIMax(True, act_params["stop_imax"])
                        )
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetThreshIMax(
                                True, act_params["stop_imax"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopIMax(False, 0.0))
                        dtaq_lims.append(lambda dtaq: dtaq.SetThreshIMax(False, 0.0))
                    if act_params.get("stop_dimin", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopDIMin(
                                True, act_params["stop_dimin"]
                            )
                        )
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetThreshDIMin(
                                True, act_params["stop_dimin"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopDIMin(False, 0.0))
                        dtaq_lims.append(lambda dtaq: dtaq.SetThreshDIMin(False, 0.0))
                    if act_params.get("stop_dimax", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopDIMax(
                                True, act_params["stop_dimax"]
                            )
                        )
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetThreshDIMax(
                                True, act_params["stop_dimax"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopDIMax(False, 0.0))
                        dtaq_lims.append(lambda dtaq: dtaq.SetThreshDIMax(False, 0.0))
                    if act_params.get("stop_adimin", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopADIMin(
                                True, act_params["stop_adimin"]
                            )
                        )
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetThreshADIMin(
                                True, act_params["stop_adimin"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopADIMin(False, 0.0))
                        dtaq_lims.append(lambda dtaq: dtaq.SetThreshADIMin(False, 0.0))
                    if act_params.get("stop_adimax", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopADIMax(
                                True, act_params["stop_adimax"]
                            )
                        )
                        dtaq_lims.append(lambda dtaq: dtaq.SetThreshADIMax(True, 0.0))
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopADIMax(False, 0.0))
                        dtaq_lims.append(lambda dtaq: dtaq.SetThreshADIMax(False, 0.0))
                    if act_params.get("stopdelay_imin", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopAtDelayIMin(
                                act_params["stopdelay_imin"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopAtDelayIMin(1))
                    if act_params.get("stopdelay_imax", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopAtDelayIMax(
                                act_params["stopdelay_imax"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopAtDelayIMax(1))
                    if act_params.get("stopdelay_dimin", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopAtDelayDIMin(
                                act_params["stopdelay_dimin"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopAtDelayDIMin(1))
                    if act_params.get("stopdelay_dimax", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopAtDelayDIMax(
                                act_params["stopdelay_dimax"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopAtDelayDIMax(1))
                    if act_params.get("stopdelay_adimin", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopAtDelayADIMin(
                                act_params["stopdelay_adimin"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopAtDelayADIMin(1))
                    if act_params.get("stopdelay_adimax", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopAtDelayADIMax(
                                act_params["stopdelay_adimax"]
                            )
                        )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopAtDelayADIMax(1))
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
                    self.pstat.SetVchRangeMode(False)
                    setpointv = np.abs(act_params["Vval__V"])
                    vchrangeval = self.pstat.TestVchRange(setpointv * 1.1)
                    self.pstat.SetVchRange(vchrangeval)
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
                    self.pstat.SetVchRangeMode(True)
                    # subset of stop conditions
                    if act_params.get("stop_advmin", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopADVMin(
                                True, act_params["stop_advmin"]
                            )
                        )
                        # dtaq_lims.append(
                        #     lambda dtaq: dtaq.SetThreshADVMin(
                        #         True, act_params["stop_advmin"]
                        #     )
                        # )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopADVMin(False, 0.0))
                        # dtaq_lims.append(lambda dtaq: dtaq.SetThreshADVMin(False, 0.0))
                    if act_params.get("stop_advmax", None) is not None:
                        dtaq_lims.append(
                            lambda dtaq: dtaq.SetStopADVMax(
                                True, act_params["stop_advmax"]
                            )
                        )
                        # dtaq_lims.append(
                        #     lambda dtaq: dtaq.SetThreshADVMax(
                        #         True, act_params["stop_advmax"]
                        #     )
                        # )
                    else:
                        dtaq_lims.append(lambda dtaq: dtaq.SetStopADVMax(False, 0.0))
                        # dtaq_lims.append(lambda dtaq: dtaq.SetThreshADVMax(False, 0.0))
                elif mode == Gamry_modes.RCA:
                    Dtaqmode = "GamryCOM.GamryDtaqUniv"
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
                        "unknown1",
                    ]
                    self.pstat.SetCtrlMode(self.GamryCOM.PstatMode)
                    self.pstat.SetVchRangeMode(True)

                # Gamry Signal not available
                else:
                    LOGGER.error(f"'mode {mode} not supported'")
                    error = ErrorCodes.not_available

                if error is ErrorCodes.none:
                    try:
                        LOGGER.info(f"creating dtaq '{Dtaqmode}'")
                        self.dtaq = client.CreateObject(Dtaqmode)
                        if Dtaqtype:
                            self.dtaq.Init(self.pstat, Dtaqtype, *argv)
                        else:
                            self.dtaq.Init(self.pstat, *argv)
                        LOGGER.info(f"applying {len(dtaq_lims)} limits")
                        for limfn in dtaq_lims:
                            limfn(self.dtaq)

                    except Exception as e:
                        tb = "".join(
                            traceback.format_exception(type(e), e, e.__traceback__)
                        )
                        LOGGER.error(f"Gamry Error during setup: {gamry_error_decoder(e)} {tb}")

                    # This method, when enabled,
                    # allows for longer experiments with fewer points,
                    # but still acquires data quickly around each step.
                    if mode == Gamry_modes.CA:
                        self.dtaq.SetDecimation(False)
                    elif mode == Gamry_modes.CP:
                        self.dtaq.SetDecimation(False)

                    self.dtaqsink = GamryDtaqEvents(self.dtaq)
                    LOGGER.info(f"initialized dtaqsink with status {self.dtaqsink.status} in mode setup_{mode}")

            except comtypes.COMError as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                LOGGER.error(f"Gamry error during measurement setup: {repr(e)} {tb}")
                error = ErrorCodes.critical_error
        else:
            LOGGER.error("measurement_setup: Gamry not initialized!")
            error = ErrorCodes.not_initialized

        return error

    async def measure(self):
        """performing a measurement with the Gamry
        this is the main function for the instrument"""
        await asyncio.sleep(0.01)

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
                LOGGER.info("signal ramp set")
            except Exception as e:
                LOGGER.error(gamry_error_decoder(e), exc_info=True)
                self.pstat.SetCell(self.GamryCOM.CellOff)
                return {"measure": "signal_error"}

            # TODO:
            # send or wait for trigger
            # Sets the voltage of the auxiliary DAC output.
            # self.pstat.SetAnalogOut
            # Sets the digital output setting.
            # self.pstat.SetDigitalOut
            # self.pstat.DigitalIn

            LOGGER.info(f"Gamry DigiOut state: {self.pstat.DigitalOut()}")
            LOGGER.info(f"Gamry DigiIn state: {self.pstat.DigitalIn()}")
            # first, wait for trigger
            if self.IO_TTLwait >= 0:
                bits = self.pstat.DigitalIn()
                LOGGER.info(f"Gamry DIbits: {bits}, waiting for trigger.")
                while self.IO_do_meas:
                    bits = self.pstat.DigitalIn()
                    if self.IO_TTLwait & bits:
                        break
                    # break  # for testing, we don't want to wait forever
                    await asyncio.sleep(0.01)

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
                    # 0001
                    self.pstat.SetDigitalOut(1, 1)
                elif self.IO_TTLsend == 1:
                    # 0010
                    self.pstat.SetDigitalOut(2, 2)
                elif self.IO_TTLsend == 2:
                    # 0100
                    self.pstat.SetDigitalOut(4, 4)
                elif self.IO_TTLsend == 3:
                    # 1000
                    self.pstat.SetDigitalOut(8, 8)

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
                LOGGER.info("running dtaq")
                self.IO_measuring = True
            except Exception as e:
                LOGGER.error(gamry_error_decoder(e), exc_info=True)
                self.close_pstat_connection()
                return {"measure": "run_error"}

            realtime = await self.active.get_realtime()

            if self.active:
                self.active.finish_hlo_header(
                    realtime=realtime,
                    # use firt of currently
                    # active file_conn_keys
                    # split action will update it
                    file_conn_keys=self.active.action.file_conn_keys,
                )

            # dtaqsink.status might still be 'idle' if sleep is too short
            await asyncio.sleep(0.1)
            client.PumpEvents(0.001)
            sink_status = self.dtaqsink.status
            counter = 0
            last_update = time.time()

            while (
                # counter < len(self.dtaqsink.acquired_points)
                self.IO_do_meas
                and (
                    sink_status != "done"
                    or counter < len(self.dtaqsink.acquired_points)
                )
            ):
                # need some await points
                await asyncio.sleep(0.01)
                client.PumpEvents(0.001)
                tmpc = len(self.dtaqsink.acquired_points)
                if counter < tmpc:
                    tmp_datapoints = self.dtaqsink.acquired_points[counter:tmpc]
                    for tup in tmp_datapoints:
                        for k, v in zip(self.FIFO_column_headings, tup):
                            if len(self.data_buffer[k])>self.data_buffer_size:
                                self.data_buffer[k].pop(0)
                            self.data_buffer[k].append(v)
                    
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
                            data = {
                                self.active.action.file_conn_keys[0]: {
                                    k: v
                                    for k, v in zip(
                                        self.FIFO_column_headings,
                                        np.matrix(tmp_datapoints).T.tolist(),
                                    )
                                }
                            }
                            await self.active.enqueue_data(
                                datamodel=DataModel(
                                    data=data, errors=[], status=HloStatus.active
                                )
                            )
                    last_update = time.time()

                if time.time() - last_update > 5 * self.sample_rate:
                    LOGGER.info(f"Pstat did not send additional data after 5 d_t intervals, ending measurement.")
                    await self.active.enqueue_data(
                        datamodel=DataModel(
                            data={}, errors=[], status=HloStatus.finished
                        )
                    )
                    sink_status = "done"
                else:
                    # LOGGER.info(f"counter: {counter}, tmpc: {tmpc}")
                    counter = tmpc
                    sink_status = self.dtaqsink.status

            # check if we have Ewe_V or I_A in data_buffer, add means to action params
            for k in ["Ewe_V", "I_A"]:
                if k in self.data_buffer:
                    meanv = np.mean(self.data_buffer[k][-5:])
                    self.active.action.action_params[f"{k}__mean_final"] = meanv

            self.close_pstat_connection()
            return {"measure": f"done_{self.IO_meas_mode}"}

    async def status(self):
        """return status of data structure"""
        await asyncio.sleep(0.01)
        return self.dtaqsink.status

    async def stop(self):
        """stops measurement, writes all data and returns from meas loop"""
        # turn off cell and run before stopping meas loop
        if self.IO_measuring:
            # file and Gamry connection will be closed with the meas loop
            self.IO_do_meas = False  # will stop meas loop
            self.dtaq.Stop()
            await self.set_IO_signalq(False)

    async def estop(self, switch: bool, *args, **kwargs):
        """same as stop, set or clear estop flag with switch parameter"""
        # should be the same as stop()
        switch = bool(switch)
        self.base.actionservermodel.estop = switch
        if self.IO_measuring:
            if switch:
                self.IO_do_meas = False  # will stop meas loop
                self.dtaq.Stop()
                await self.set_IO_signalq(False)
                if self.active:
                    # add estop status to active.status
                    self.active.set_estop()
        return switch

    def shutdown(self):
        # close all connection and objects to gamry
        LOGGER.info("shutting down gamry")
        if self.IO_measuring:
            # file and Gamry connection will be closed with the meas loop
            self.IO_do_meas = False  # will stop meas loop
            self.set_IO_signalq_nowait(False)

        # give some time to finish all data
        retries = 0
        while self.active is not None and retries < 10:
            LOGGER.info(f"Got shutdown, but Active is not yet done!, retry {retries}")
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

            unit = s.lstrip("0123456789. ")
            number = s[: -len(unit)]
            return to_float(number), unit

        def to_amps(number: float, unit: str):
            unit = unit.lower()
            exp = None
            if unit == "aa":
                exp = 1e-18
            elif unit == "fa":
                exp = 1e-15
            elif unit == "pa":
                exp = 1e-12
            elif unit == "na":
                exp = 1e-9
            elif unit == "ua":
                exp = 1e-6
            elif unit == "ma":
                exp = 1e-3
            elif unit == "a":
                exp = 1
            elif unit == "ka":
                exp = 1000

            if exp is None:
                return None
            else:
                return number * exp

        if requested_range is None:
            LOGGER.warning("could not detect IErange, using 'auto'")
            return self.gamry_range_enum.auto

        LOGGER.info(f"got IErange request for {requested_range}")

        names = [e.name.lower() for e in self.gamry_range_enum]
        vals = [e.value.lower() for e in self.gamry_range_enum]
        lookupvals = [e.value for e in self.gamry_range_enum]

        idx = None
        if isinstance(requested_range, str):
            requested_range = requested_range.lower()

        if requested_range in vals:
            idx = vals.index(requested_range)

        elif requested_range in names:
            idx = names.index(requested_range)

        else:
            # auto should have been detected already above
            # try auto detect range based on value and unit pair

            if isinstance(requested_range, float):
                req_num = requested_range
            else:
                req_num, req_unit = mysplit(
                    requested_range.replace(" ", "").replace("_", "")
                )
                req_num = to_amps(number=req_num, unit=req_unit)
            if req_num is None:
                return self.gamry_range_enum.auto
            for ret_idx, val in enumerate(vals):
                val_num, val_unit = mysplit(val)
                val_num = to_amps(number=val_num, unit=val_unit)
                if val_num is None:
                    # skip auto
                    continue
                if req_num <= val_num:
                    # self.gamry_range_enum is already sort min to max
                    idx = ret_idx
                    break

            if idx is None:
                LOGGER.error("could not detect IErange, using 'auto'")
                return self.gamry_range_enum.auto

        ret_range = self.gamry_range_enum(lookupvals[idx])
        LOGGER.info(f"detected IErange: {ret_range}")
        return ret_range

    async def technique_wrapper(
        self, act, measmode, sigfunc, sigfunc_params, samplerate, eta=0.0, setupargs=[]
    ):
        self.sample_rate = samplerate
        act.action_etc = eta
        act.error_code = ErrorCodes.none
        samples_in = await self.unified_db.get_samples(act.samples_in)
        if not samples_in and not self.allow_no_sample:
            LOGGER.error("Gamry got no valid sample, cannot start measurement!")
            act.samples_in = []
            act.error_code = ErrorCodes.no_sample

        if (
            self.pstat
            and not self.IO_do_meas
            and not self.IO_measuring
            and not self.base.actionservermodel.estop
            and act.error_code is ErrorCodes.none
        ):
            # open connection, will be closed after measurement in IOloop
            act.error_code = await self.open_connection()

        elif not self.pstat:
            act.error_code = ErrorCodes.not_initialized

        elif not self.IO_do_meas:
            act.error_code = ErrorCodes.in_progress

        elif self.base.actionservermodel.estop:
            act.error_code = ErrorCodes.estop

        elif self.IO_measuring:
            act.error_code = ErrorCodes.in_progress

        else:
            if act.error_code is ErrorCodes.none:
                act.error_code = ErrorCodes.not_initialized

        activeDict = act.as_dict()

        if act.error_code is ErrorCodes.none:
            # set parameters for IOloop meas
            self.IO_meas_mode = measmode
            act.error_code = await self.measurement_setup(
                act.action_params, self.IO_meas_mode, *setupargs
            )
            if act.error_code is ErrorCodes.none:
                # setup the experiment specific signal ramp
                self.IO_sigramp = client.CreateObject(sigfunc)
                try:
                    self.IO_sigramp.Init(*sigfunc_params)
                    act.error_code = ErrorCodes.none
                except comtypes.COMError as _:
                    LOGGER.info("COMError, reinstantiating connection.")
                    # remake connection
                    self.kill_GamryCom()
                    self.GamryCOM = client.GetModule(
                        ["{BD962F0D-A990-4823-9CF5-284D1CDD9C6D}", 1, 0]
                    )
                    await self.init_Gamry(self.Gamry_devid)
                    self.IO_sigramp.Init(*sigfunc_params)
                    act.error_code = ErrorCodes.none
                except Exception as e:
                    tb = "".join(
                        traceback.format_exception(type(e), e, e.__traceback__)
                    )
                    act.error_code = gamry_error_decoder(e)
                    LOGGER.error(f"IO_sigramp.Init error: {act.error_code} {tb}")

                self.samples_in = samples_in
                self.action = act

                # write header lines with one function call
                self.FIFO_gamryheader.update(
                    {
                        "gamry": self.FIFO_Gamryname,
                        "ierangemode": self.IO_IErange.name,
                    }
                )

                self.active = await self.base.contain_action(
                    ActiveParams(
                        action=self.action,
                        file_conn_params_dict={
                            self.base.dflt_file_conn_key(): FileConnParams(
                                # use dflt file conn key for first
                                # init
                                file_conn_key=self.base.dflt_file_conn_key(),
                                sample_global_labels=[
                                    sample.get_global_label()
                                    for sample in self.samples_in
                                ],
                                file_type="pstat_helao__file",
                                # only add optional keys to header
                                # rest will be added later
                                hloheader=HloHeaderModel(
                                    optional=self.FIFO_gamryheader
                                ),
                            )
                        },
                    )
                )

                for sample in self.samples_in:
                    sample.status = [SampleStatus.preserved]
                    sample.inheritance = SampleInheritance.allow_both

                # clear old samples_in first
                self.active.action.samples_in = []
                # now add updated samples to sample_in again
                if self.samples_in:
                    await self.active.append_sample(
                        samples=[sample_in for sample_in in self.samples_in], IO="in"
                    )

                # signal the IOloop to start the measrurement
                await self.set_IO_signalq(True)

                # need to wait now for the activation of the meas routine
                # and that the active object is activated and sets action status
                while not self.IO_continue:
                    await asyncio.sleep(0.1)

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
        self,
        A: Action,
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
            "Vinit__V": Vinit,
            "Vfinal__V": Vfinal,
            "ScanRate__V_s": ScanRate,
            "AcqInterval__s": SampleRate,
            "ETA__s": eta,
        }

        # common
        self.IO_IErange = self.ierangefinder(requested_range=IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend
        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta,
        )

        return activeDict

    async def technique_CA(
        self,
        A: Action,
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
            "Vval__V": Vval,
            "Tval__s": Tval,
            "AcqInterval__s": SampleRate,
            "ETA__s": eta,
        }

        # common
        self.IO_IErange = self.ierangefinder(requested_range=IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend
        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta,
        )
        return activeDict

    async def technique_CP(
        self,
        A: Action,
    ):
        """CP definition"""
        Ival = A.action_params["Ival__A"]
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
            "Ival__A": Ival,
            "Tval__s": Tval,
            "AcqInterval__s": SampleRate,
            "ETA__s": eta,
        }

        # common
        self.IO_IErange = self.ierangefinder(requested_range=IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend
        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta,
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
            "Vinit__V": Vinit,
            "Vapex1__V": Vapex1,
            "Vapex2__V": Vapex2,
            "Vfinal__V": Vfinal,
            "ScanInit__V_s": ScanInit,
            "ScanApex__V_s": ScanApex,
            "ScanFinal__V_s": ScanFinal,
            "holdtime0__s": HoldTime0,
            "holdtime1__s": HoldTime1,
            "holdtime2__s": HoldTime2,
            "AcqInterval__s": SampleRate,
            "cycles": Cycles,
            "ETA__s": eta,
        }

        # common
        self.IO_IErange = self.ierangefinder(requested_range=IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend
        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta,
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
            "Vval__V": Vval,
            "Tval__s": Tval,
            "freq": Freq,
            "rms": RMS,
            "precision": Precision,
            "AcqInterval__s": SampleRate,
            "ETA__s": eta,
        }

        # common
        self.IO_IErange = self.ierangefinder(requested_range=IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend
        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta,
            setupargs=argv,
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
            "Tval__s": Tval,
            "AcqInterval__s": SampleRate,
            "ETA__s": eta,
        }

        # common
        self.IO_IErange = self.ierangefinder(requested_range=IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend

        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=SampleRate,
            eta=eta,
        )
        return activeDict

    async def technique_RCA(self, A: Action):
        """Repeating CA definition"""
        Vinit = A.action_params["Vinit__V"]
        Tinit = A.action_params["Tinit__s"]
        Vstep = A.action_params["Vstep__V"]
        Tstep = A.action_params["Tstep__s"]
        Cycles = A.action_params["Cycles"]
        AcqInt = A.action_params["AcqInterval__s"]

        TTLwait = A.action_params["TTLwait"]
        TTLsend = A.action_params["TTLsend"]
        IErange = A.action_params["IErange"]
        """This technique is used to run pulse voltammetry experiments such as Normal 
        Pulse or Differential Pulse voltammetry. It is normally combined with the PV 
        dtaq for data acquisition. The values passed in for Vinit and Vpv, Vpulse, will 
        be interpreted as volts for potentiostat mode or amps for galvanostat mode."""

        # calculate signal array
        cycle_time = Tinit + Tstep
        points_per_cycle = round(cycle_time / AcqInt)
        signal_array = [Vinit if i*AcqInt <= Tinit else Vstep for i in range(points_per_cycle)]

        eta = cycle_time * Cycles

        sigfunc_params = [
            self.pstat,
            Cycles,
            AcqInt,
            points_per_cycle,
            signal_array,
            self.GamryCOM.PstatMode,
        ]
        sigfunc = "GamryCOM.GamrySignalArray"
        measmode = Gamry_modes.RCA

        # setup partial header which will be completed in measure loop
        self.FIFO_gamryheader = {
            "Vinit__V": Vinit,
            "Tinit__s": Tinit,
            "Vstep__V": Vstep,
            "Tstep__s": Tstep,
            "Cycles": Cycles,
            "AcqInterval__s": AcqInt,
        }

        # common
        self.IO_IErange = self.ierangefinder(requested_range=IErange)
        self.IO_TTLwait = TTLwait
        self.IO_TTLsend = TTLsend

        activeDict = await self.technique_wrapper(
            act=A,
            measmode=measmode,
            sigfunc=sigfunc,
            sigfunc_params=sigfunc_params,
            samplerate=AcqInt,
            eta=eta,
        )
        return activeDict
