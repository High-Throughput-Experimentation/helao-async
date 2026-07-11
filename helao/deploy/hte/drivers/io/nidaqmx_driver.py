"""NI DAQmx driver for HTE cell IV measurements and ancillary IO.

Manages two PXI cards (a 6289 for cell current and a 6284 for cell voltage)
plus a third task for thermocouple monitors. The driver streams per-cell I/V
samples via a buffer callback, and exposes simple coroutines for setting
digital outputs and reading digital inputs (used to drive pumps, gas/liquid
valves, heaters, and LEDs).

Multi-cell IV measurements are driven by :class:`CellIVExec`, which owns the
``Active`` action; the NI-DAQmx buffer callback (:meth:`cNIMAX.streamIV_callback`)
fires on a nidaqmx-internal thread, outside the asyncio poll loop, so it
cannot report data through ``Executor._poll``'s return value like a normal
K6a data source. Instead, :class:`CellIVExec` hands the driver a handful of
plain callables (``active.enqueue_data_nowait``, ``active.get_realtime_nowait``,
``active.finish_hlo_header``) in ``arm_cell_iv`` -- the driver never holds a
reference to ``Active``/``Base`` themselves. Thermocouple monitor channels are
always-on and are handled by the paired :class:`cNIMAXPoller`.
"""

__all__ = ["cNIMAX", "cNIMAXPoller", "CellIVExec", "DevMonExec"]

import time
import asyncio
import traceback
from typing import Optional, Callable, List

import nidaqmx
from nidaqmx.constants import LineGrouping
from nidaqmx.constants import Edge
from nidaqmx.constants import AcquisitionType
from nidaqmx.constants import TerminalConfiguration
from nidaqmx.constants import VoltageUnits
from nidaqmx.constants import TemperatureUnits
from nidaqmx.constants import ThermocoupleType
from nidaqmx.constants import CurrentShuntResistorLocation
from nidaqmx.constants import UnitsPreScaled
from nidaqmx.constants import TriggerType

from helao.helpers.executor import Executor
from helao.core.error import ErrorCodes
from helao.helpers.make_str_enum import make_str_enum
from helao.core.models.sample import SampleInheritance, SampleStatus
from helao.core.models.file import FileConnParams, HloHeaderModel
from helao.core.models.data import DataModel
from helao.core.models.hlostatus import HloStatus
from helao.core.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
    DriverPoller,
)

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class cNIMAX(HelaoDriver):
    """NI DAQmx wrapper used by the HTE action server.

    Reads device maps (`dev_pump`, `dev_gasvalve`, `dev_liquidvalve`,
    `dev_heat`, `dev_led`, `dev_monitor`, `dev_cellcurrent`,
    `dev_cellvoltage`) from `config`. NI resources (the custom current scale
    and the thermocouple monitor task) are opened in :meth:`connect`, not at
    construction. Always-on thermocouple polling is handled by the paired
    :class:`cNIMAXPoller`, wired in as the server's ``poller_class``.
    Multi-cell IV measurements are armed via :meth:`arm_cell_iv` (called from
    :class:`CellIVExec`, which owns the ``Active`` action).

    Server config parameters:
        ``dev_pump``/``dev_gasvalve``/``dev_liquidvalve``/``dev_heat``/
        ``dev_led``: digital-out port maps.
        ``dev_monitor``: thermocouple channel map (K-type by default,
            T-type when the name contains ``"Ttc_"``).
        ``dev_cellcurrent``/``dev_cellvoltage``: analog-in port maps for the
            multi-cell IV task; ``dev_cellcurrent_trigger``/
            ``dev_cellvoltage_trigger``: optional shared start-trigger line.
        ``allow_no_sample``: permit a cell-IV measurement with no validated
            samples.
    """

    def __init__(self, config: dict = {}):
        """Store config and build the dynamic IO enums; no device I/O here.

        Args:
            config: Driver configuration (the server's ``params`` dict).
        """
        super().__init__(config=config)
        self.config_dict = self.config

        # set by the server's dyn_endpoints startup hook (mirrors the
        # DriverPoller._base_hook wiring in base_api.py); used only for the
        # synchronous estop/live-buffer reads the NI-DAQmx hardware callback
        # needs (that callback fires on a nidaqmx-internal thread, so it
        # cannot await anything -- see streamIV_callback). Always accessed
        # via safe getattr so construction/unit tests work without a server.
        self._base_hook = None

        self.dev_pump = self.config_dict.get("dev_pump", {})
        self.dev_pumpitems = make_str_enum(
            "dev_pump", {key: key for key in self.dev_pump}
        )

        self.dev_gasvalve = self.config_dict.get("dev_gasvalve", {})
        self.dev_gasvalveitems = make_str_enum(
            "dev_gasvalve", {key: key for key in self.dev_gasvalve}
        )

        self.dev_liquidvalve = self.config_dict.get("dev_liquidvalve", {})
        self.dev_liquidvalveitems = make_str_enum(
            "dev_liquidvalve", {key: key for key in self.dev_liquidvalve}
        )
        self.dev_heat = self.config_dict.get("dev_heat", {})
        self.dev_heatitems = make_str_enum(
            "dev_heat", {key: key for key in self.dev_heat}
        )

        self.dev_led = self.config_dict.get("dev_led", {})
        self.dev_leditems = make_str_enum("dev_led", {key: key for key in self.dev_led})

        self.allow_no_sample = self.config_dict.get("allow_no_sample", False)

        LOGGER.info("init NI-MAX")

        # connection/device state -- populated by connect()/arm_cell_iv(), not here
        self._connected = False
        self.Iscale = None
        self.time_stamp = time.time()

        # this defines the time axis, need to calculate our own
        self.samplingrate = 10  # samples per second
        # used to keep track of time during data readout
        self.IVtimeoffset = 0.0
        self.buffersize = 1000  # finite samples or size of buffer depending on mode
        self.duration = 10  # sec
        self.ttlwait = -1
        self.buffersizeread = int(self.samplingrate)

        self.task_6289cellcurrent = None
        self.task_6284cellvoltage = None
        self.task_monitors = None
        self.task_monitor_keys: List[str] = []
        self.IO_do_meas = False  # signal flag for intent (start/stop)
        self.IO_measuring = False  # status flag of measurement
        self.activeCell = [False for _ in range(9)]

        self.FIFO_epoch = None
        self.FIFO_NImaxheader = {}
        self.FIFO_name = ""
        self.FIFO_dir = ""
        self.FIFO_cell_keys = [
            "cell1",
            "cell2",
            "cell3",
            "cell4",
            "cell5",
            "cell6",
            "cell7",
            "cell8",  # removed from cell list due to use of NI lines   ---- restored 8/14/2022
            "cell9",  # can add back in if rewiring added to box for heaters
        ]
        self.file_conn_keys = []
        self.FIFO_column_headings = [
            "t_s",
            "Icell_A",
            "Ecell_V",
            "Ttemp_Ktc_in_cell_C",
            "Ttemp_Ttc_in_reservoir_C",
            "Ttemp_Ktc_out_cell_C",
            "Ttemp_Ktc_out_reservoir_C",
        ]

        # per-run hooks into the Active action that owns the current cell-IV
        # measurement, injected by CellIVExec._pre_exec via arm_cell_iv() and
        # cleared by stop_cell_iv(); the streamIV_callback (NI-DAQmx hardware
        # callback, not asyncio) calls these directly instead of returning
        # data through _poll (see module docstring).
        self._save_data = True
        self._get_realtime_nowait: Optional[Callable] = None
        self._finish_hlo_header: Optional[Callable] = None
        self._data_sink: Optional[Callable] = None

        self.Heatloop_run = False

    def connect(self) -> DriverResponse:
        """Register the current-negate scale and start the thermocouple monitor task.

        Returns:
            ``DriverResponse`` reporting connection success or failure.
        """
        try:
            # seems to work by just defining the scale and then only using its name
            self.Iscale = nidaqmx.scale.Scale.create_lin_scale(
                "NEGATE3", -1.0, 0.0, UnitsPreScaled.AMPS, "AMPS"
            )
            self.create_monitortask()
            if self.task_monitor_keys:
                self.task_monitors.start()
            self._connected = True
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("NImax connect failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )

    def get_status(self) -> DriverResponse:
        """Return whether :meth:`connect` has completed successfully.

        Returns:
            ``DriverResponse`` with ``status=ok`` if connected, else
            ``status=uninitialized``.
        """
        if self._connected:
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.uninitialized
        )

    async def stop(self) -> DriverResponse:
        """Request the in-progress cell-IV measurement (if any) to stop.

        Kept async (unlike the ABC's plain signature) so the existing
        ``await app.driver.stop()`` call site in the action server is
        unaffected; other migrated drivers in this repo mix sync/async ABC
        overrides the same way (e.g. ``galil_motion``'s ``reset``).
        """
        if self.IO_measuring:
            self.IO_do_meas = False
        return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok)

    def reset(self) -> DriverResponse:
        """Force-close and reopen the monitor connection."""
        self.disconnect()
        return self.connect()

    def disconnect(self) -> DriverResponse:
        """Close the thermocouple monitor task.

        Returns:
            ``DriverResponse`` reporting close success or failure.
        """
        try:
            if self.task_monitors is not None:
                self.task_monitors.close()
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("NImax disconnect failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        finally:
            self.task_monitors = None
            self._connected = False
        return response

    async def async_shutdown(self) -> DriverResponse:
        """Close the monitor task on server shutdown (sync ``shutdown`` is omitted)."""
        return self.disconnect()

    def _get_lbuf(self, key: str):
        """Safely read ``key`` from the action server's live buffer via ``_base_hook``.

        Returns ``(None, None)`` if no ``_base_hook`` has been wired yet
        (e.g. during construction-only unit tests).
        """
        if self._base_hook is not None:
            return self._base_hook.get_lbuf(key)
        return None, None

    def _is_estopped(self) -> bool:
        """Safely read the action server's estop flag via ``_base_hook``."""
        actionservermodel = getattr(self._base_hook, "actionservermodel", None)
        return bool(getattr(actionservermodel, "estop", False))

    def create_IVtask(self):
        """Configure the dual NI-DAQ tasks used for multi-cell IV measurements.

        Sets up the 6289 current task (master) with the negate custom scale
        and the 6284 voltage task (slave), wires up the buffer callback, and
        configures the digital-edge start triggers when TTL wait is enabled.
        """
        # Voltage reading is MASTER
        self.task_6289cellcurrent = nidaqmx.Task()
        for myname, mydev in self.config_dict["dev_cellcurrent"].items():
            self.task_6289cellcurrent.ai_channels.add_ai_current_chan(
                mydev,
                name_to_assign_to_channel="Cell_" + myname,
                terminal_config=TerminalConfiguration.DIFFERENTIAL,
                min_val=-0.02,
                max_val=+0.02,
                units=VoltageUnits.FROM_CUSTOM_SCALE,
                shunt_resistor_loc=CurrentShuntResistorLocation.EXTERNAL,
                ext_shunt_resistor_val=5.0,
                custom_scale_name="NEGATE3",  # TODO: this can be a per channel calibration
            )
        self.task_6289cellcurrent.ai_channels.all.ai_lowpass_enable = True
        self.task_6289cellcurrent.timing.cfg_samp_clk_timing(
            self.samplingrate,
            source="",
            active_edge=Edge.RISING,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=self.buffersize,
        )
        # TODO can increase the callbackbuffersize if needed
        self.task_6289cellcurrent.register_every_n_samples_acquired_into_buffer_event(
            self.buffersizeread, self.streamIV_callback
        )

        # Voltage reading is SLAVE
        # we cannot combine both tasks into one as they run on different DAQs
        # define the VOLT and CURRENT task as they need to stay in memory
        self.task_6284cellvoltage = nidaqmx.Task()
        for myname, mydev in self.config_dict["dev_cellvoltage"].items():
            self.task_6284cellvoltage.ai_channels.add_ai_voltage_chan(
                mydev,
                name_to_assign_to_channel="Cell_" + myname,
                terminal_config=TerminalConfiguration.DIFFERENTIAL,
                min_val=-10.0,
                max_val=+10.0,
                units=VoltageUnits.VOLTS,
            )

        # does this globally enable lowpass or only for channels in task?
        self.task_6284cellvoltage.ai_channels.all.ai_lowpass_enable = True
        self.task_6284cellvoltage.timing.cfg_samp_clk_timing(
            self.samplingrate,
            source="",
            active_edge=Edge.RISING,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=self.buffersize,
        )

        # each card need its own physical trigger input
        if (
            self.config_dict["dev_cellvoltage_trigger"] != ""
            and self.config_dict["dev_cellcurrent_trigger"] != ""
            and self.ttlwait != -1
        ):
            self.task_6284cellvoltage.triggers.start_trigger.trig_type = (
                TriggerType.DIGITAL_EDGE
            )
            self.task_6284cellvoltage.triggers.start_trigger.cfg_dig_edge_start_trig(
                trigger_source=self.config_dict["dev_cellvoltage_trigger"],
                trigger_edge=Edge.RISING,
            )

            self.task_6289cellcurrent.triggers.start_trigger.trig_type = (
                TriggerType.DIGITAL_EDGE
            )
            self.task_6289cellcurrent.triggers.start_trigger.cfg_dig_edge_start_trig(
                trigger_source=self.config_dict["dev_cellcurrent_trigger"],
                trigger_edge=Edge.RISING,
            )

    def create_monitortask(self):
        """Configure the background NI-DAQ thermocouple monitoring task.

        Adds one analog-input thermocouple channel per `dev_monitor` entry
        (K-type by default, T-type when the name contains "Ttc_") and enables
        the lowpass filter. Called from :meth:`connect`.
        """
        self.task_monitors = nidaqmx.Task()
        self.task_monitor_keys = list(self.config_dict.get("dev_monitor", {}).keys())
        if self.task_monitor_keys:
            for myname in self.task_monitor_keys:
                mydev = self.config_dict["dev_monitor"][myname]
                # can add if filter for different types of monitors (other than Temp)
                if "Ttc_" in myname:
                    TCtype = ThermocoupleType.T
                else:
                    TCtype = ThermocoupleType.K
                self.task_monitors.ai_channels.add_ai_thrmcpl_chan(
                    mydev,
                    name_to_assign_to_channel=myname,
                    min_val=0,
                    max_val=150,
                    units=TemperatureUnits.DEG_C,
                    thermocouple_type=TCtype,
                )
            self.task_monitors.ai_channels.all.ai_lowpass_enable = True
            self.task_monitors.timing.cfg_samp_clk_timing(
                rate=1,
                source="",
                active_edge=Edge.RISING,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=self.buffersize,
            )

    def streamIV_callback(
        self, task_handle, every_n_samples_event_type, number_of_samples, callback_data
    ) -> int:
        """NI-DAQ buffer callback that drains the I/V tasks and enqueues per-cell data.

        When a measurement is active, reads `number_of_samples` from the
        current and voltage tasks, augments each cell record with the latest
        monitor readings, and pushes the result to the active action's data
        queue (via the `_data_sink` hook installed by `arm_cell_iv`). In
        estop or post-stop conditions the buffer is drained and tasks are
        closed without enqueuing data.

        This callback fires on a nidaqmx-internal thread outside the asyncio
        event loop, so estop/live-buffer/active access must go through the
        synchronous `_base_hook`/injected-callable seams rather than
        `await`-ing anything.

        Returns:
            0 (required by the NI-DAQmx callback protocol).
        """
        is_estopped = self._is_estopped()
        if self.IO_do_meas and not is_estopped:
            try:
                self.IO_measuring = True

                if self.FIFO_epoch is None and self._get_realtime_nowait is not None:
                    self.FIFO_epoch = self._get_realtime_nowait()
                    # need to correct for the first datapoints
                    self.FIFO_epoch -= number_of_samples / self.samplingrate
                    if self._save_data and self._finish_hlo_header is not None:
                        self._finish_hlo_header(realtime=self.FIFO_epoch)

                # start seq: V then current, so read current first then Volt
                # put callback only on current (Volt should the always have enough points)
                # readout is requested-1 when callback is on requested
                dataI = self.task_6289cellcurrent.read(
                    number_of_samples_per_channel=number_of_samples
                )
                dataV = self.task_6284cellvoltage.read(
                    number_of_samples_per_channel=number_of_samples
                )
                mdata = {}
                for myname in self.task_monitor_keys:
                    mdata[myname], _ = self._get_lbuf(myname)

                # this is also what NImax seems to do
                time_ = [
                    self.IVtimeoffset + i / self.samplingrate
                    for i in range(len(dataI[0]))
                ]
                # update timeoffset
                self.IVtimeoffset += number_of_samples / self.samplingrate

                data_dict = {}
                for i, _ in enumerate(self.FIFO_cell_keys):
                    cell_data_dict = {
                        f"{self.FIFO_column_headings[0]}": time_,
                        f"{self.FIFO_column_headings[1]}": dataI[i],
                        f"{self.FIFO_column_headings[2]}": dataV[i],
                    }
                    for k in self.task_monitor_keys:
                        cell_data_dict[k] = mdata[k]
                    data_dict[self.file_conn_keys[i]] = cell_data_dict

                # push data to datalogger queue
                if self._data_sink is not None:
                    self._data_sink(datamodel=DataModel(data=data_dict, errors=[]))

            except Exception as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                LOGGER.error(f"canceling NImax IV stream: {repr(e), tb,}")

        elif is_estopped and self.IO_do_meas:
            _ = self.task_6289cellcurrent.read(
                number_of_samples_per_channel=number_of_samples
            )
            _ = self.task_6284cellvoltage.read(
                number_of_samples_per_channel=number_of_samples
            )
            self.IO_measuring = False
            self.task_6289cellcurrent.close()
            self.task_6284cellvoltage.close()

        else:
            # NImax has data but measurement was already turned off
            # just pull data from buffer and turn task off
            _ = self.task_6289cellcurrent.read(
                number_of_samples_per_channel=number_of_samples
            )
            _ = self.task_6284cellvoltage.read(
                number_of_samples_per_channel=number_of_samples
            )
            # task should be already off or should be closed soon
            LOGGER.info("meas was turned off but NImax IV task is still running ...")

        return 0

    def arm_cell_iv(
        self,
        samplerate: int,
        duration: float,
        ttlwait: int,
        file_conn_keys: list,
        save_data: bool,
        get_realtime_nowait: Callable,
        finish_hlo_header: Callable,
        enqueue_data_nowait: Callable,
    ) -> DriverResponse:
        """Configure and start the buffered multi-cell IV NI-DAQ tasks.

        Called once from `CellIVExec._pre_exec`, after the caller has
        created the `Active` action and its 9 per-cell file connections.
        Plain params + callables only (K7): the driver never sees `Active`.

        Args:
            samplerate: Samples per second per channel.
            duration: Total measurement duration in seconds.
            ttlwait: -1 disables trigger wait, else the TTL channel index.
            file_conn_keys: One file-connection key per `FIFO_cell_keys`
                entry, supplied by the caller that owns `active`.
            save_data: Mirrors `active.action.save_data`; gates the one-time
                `finish_hlo_header` call.
            get_realtime_nowait: `active.get_realtime_nowait` (no args).
            finish_hlo_header: `active.finish_hlo_header` (kwarg `realtime`).
            enqueue_data_nowait: `active.enqueue_data_nowait` (kwarg `datamodel`).

        Returns:
            `DriverResponse` reporting the tasks were armed and started.
        """
        self.IVtimeoffset = 0.0
        self.samplingrate = samplerate
        self.duration = duration
        self.ttlwait = ttlwait
        self.buffersizeread = int(self.samplingrate)
        self.file_conn_keys = file_conn_keys
        self.FIFO_epoch = None

        self._save_data = save_data
        self._get_realtime_nowait = get_realtime_nowait
        self._finish_hlo_header = finish_hlo_header
        self._data_sink = enqueue_data_nowait

        self.create_IVtask()
        self.IO_do_meas = True
        # start slave first, then master to trigger slave (matches prior IOloop order)
        self.task_6284cellvoltage.start()
        self.task_6289cellcurrent.start()

        return DriverResponse(response=DriverResponseType.success, status=DriverStatus.busy)

    def stop_cell_iv(self) -> DriverResponse:
        """Stop an in-progress multi-cell IV measurement and close its NI tasks."""
        self.IO_do_meas = False
        self.IO_measuring = False
        try:
            if self.task_6289cellcurrent is not None:
                self.task_6289cellcurrent.close()
            if self.task_6284cellvoltage is not None:
                self.task_6284cellvoltage.close()
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("error closing NImax IV tasks", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        finally:
            self.task_6289cellcurrent = None
            self.task_6284cellvoltage = None
            self._data_sink = None
            self._get_realtime_nowait = None
            self._finish_hlo_header = None
        return response

    async def Heatloop(
        self,
        duration_h,
        celltemp_min,
        celltemp_max,
        reservoir2_min,
        reservoir2_max,
    ) -> bool:
        """Bang-bang temperature control for cell and reservoir heaters.

        For `duration_h` hours, polls the cached monitor temperatures from
        the live buffer once per second and toggles the `cellheater` and
        `res_heater` digital outputs to keep cell temperature within
        `celltemp_min`..`celltemp_max` and reservoir temperature within
        `reservoir2_min`..`reservoir2_max`. Exits early if `Heatloop_run`
        is cleared, and turns the heaters off on exit.

        Returns:
            The final `Heatloop_run` flag, indicating whether the loop
            completed via timeout (True) or was stopped (False).
        """
        duration = duration_h * 3600
        heatloopstarttime = time.time()

        self.Heatloop_run = True
        mdata = {}

        while (time.time() - heatloopstarttime < duration) and self.Heatloop_run:
            readtempdict = {}
            for i, myname in enumerate(self.config_dict["dev_monitor"]):
                mdata[i], _ = self._get_lbuf(myname)
                readtempdict[myname] = mdata[i]
            cell_temp = float(readtempdict["Ttemp_Ktc_in_cell_C"])
            reservoir_temp = float(readtempdict["Ttemp_Ttc_in_reservoir_C"])
            for myheat, myport in self.dev_heat.items():
                if myheat == "cellheater":
                    if cell_temp < celltemp_min:
                        await self.set_digital_out(
                            do_port=myport, do_name=myheat, on=True
                        )
                    if cell_temp > celltemp_max:
                        await self.set_digital_out(
                            do_port=myport, do_name=myheat, on=False
                        )
                if myheat == "res_heater":
                    if reservoir_temp < reservoir2_min:
                        await self.set_digital_out(
                            do_port=myport, do_name=myheat, on=True
                        )
                    if reservoir_temp > reservoir2_max:
                        await self.set_digital_out(
                            do_port=myport, do_name=myheat, on=False
                        )
            await asyncio.sleep(1)
        await self.set_digital_out(do_port=myport, do_name=myheat, on=False)
        await self.set_digital_out(do_port=myport, do_name=myheat, on=False)
        return (
            self.Heatloop_run
        )  # indicates whether heatloop terminated via time duration or stop

    async def set_digital_out(
        self, do_port=None, do_name: str = "", on: bool = False, *args, **kwargs
    ) -> dict:
        """Drive a single digital output line via a one-shot NI-DAQ task.

        Args:
            do_port: NI-DAQ channel string (e.g. "PXI-6284/port0/line0").
            do_name: Friendly name for the channel.
            on: True for high, False for low.

        Returns:
            Dict with `error_code`, `port`, `name`, `type` ("digital_out"),
            and the applied `value`.
        """
        LOGGER.info(f"do_port '{do_name}': {do_port} is {on}")
        on = bool(on)
        cmds = []
        err_code = ErrorCodes.none
        if do_port is not None:
            with nidaqmx.Task() as task_do_port:
                task_do_port.do_channels.add_do_chan(
                    do_port,
                    line_grouping=LineGrouping.CHAN_PER_LINE,
                )
                cmds.append(on)
                if cmds:
                    task_do_port.write(cmds)
                    err_code = ErrorCodes.none
                else:
                    err_code = ErrorCodes.not_available
        else:
            err_code = ErrorCodes.not_available

        return {
            "error_code": err_code,
            "port": do_port,
            "name": do_name,
            "type": "digital_out",
            "value": on,
        }

    async def get_digital_in(
        self, di_port=None, di_name: str = "", on: bool = False, *args, **kwargs
    ) -> dict:
        """Read a single digital input line via a one-shot NI-DAQ task.

        Args:
            di_port: NI-DAQ channel string for the digital input.
            di_name: Friendly name for the channel.
            on: Unused; placeholder for API symmetry with `set_digital_out`.

        Returns:
            Dict with `error_code`, `port`, `name`, `type` ("digital_in"),
            and `value`.
        """
        LOGGER.info(f"di_port '{di_name}': {di_port}")
        on = None
        err_code = ErrorCodes.none
        if di_port is not None:
            with nidaqmx.Task() as task_di_port:

                task_di_port.di_channels.add_di_chan(
                    di_port,
                    line_grouping=LineGrouping.CHAN_PER_LINE,
                )
                on = task_di_port.read(number_of_samples_per_channel=1)
        else:
            err_code = ErrorCodes.not_available

        return {
            "error_code": err_code,
            "port": di_port,
            "name": di_name,
            "type": "digital_in",
            "value": on,
        }

    async def read_T(self) -> dict:
        """Return the latest cached value for each monitor channel from the live buffer."""
        mdata = {}
        for myname in self.task_monitor_keys:
            mdata[myname], _ = self._get_lbuf(myname)
        print(mdata)
        return mdata

    def stop_heatloop(self):
        """Signal the heater control loop to exit."""
        self.Heatloop_run = False

    async def estop(self, switch: bool, *args, **kwargs) -> bool:
        """Engage or release the IO emergency stop.

        Drives every configured LED, pump, gas valve, liquid valve, and
        heater output low (matching the pre-migration behavior, this runs
        whether `switch` asserts or releases estop). If a cell-IV
        measurement is in progress and `switch` is True, it is also
        signalled to stop.

        Server-side estop-flag bookkeeping (`actionservermodel.estop`) and
        marking in-flight actions as estopped are owned by the action-server
        framework (`base_api.py`'s `/estop` endpoint and `estop_actives()`),
        not the driver.

        Args:
            switch: True to assert estop, False to release.

        Returns:
            The boolean coerced `switch` value.
        """
        switch = bool(switch)

        for do_name, do_port in self.dev_led.items():
            await self.set_digital_out(do_port=do_port, do_name=do_name, on=False)

        for do_name, do_port in self.dev_pump.items():
            await self.set_digital_out(do_port=do_port, do_name=do_name, on=False)

        for do_name, do_port in self.dev_gasvalve.items():
            await self.set_digital_out(do_port=do_port, do_name=do_name, on=False)

        for do_name, do_port in self.dev_liquidvalve.items():
            await self.set_digital_out(do_port=do_port, do_name=do_name, on=False)

        for do_name, do_port in self.dev_heat.items():
            await self.set_digital_out(do_port=do_port, do_name=do_name, on=False)

        if switch and self.IO_measuring:
            self.IO_do_meas = False

        return switch


class cNIMAXPoller(DriverPoller):
    """Background poller that reads the NI-DAQ thermocouple monitor task."""

    driver: cNIMAX

    def get_data(self) -> DriverResponse:
        """Read one sample from every configured thermocouple monitor channel.

        Mirrors the pre-migration `monitorloop` body: a single synchronous
        `task_monitors.read()`, zipped against `task_monitor_keys`.

        Returns:
            `DriverResponse` with `data={monitor_name: value, ...}`, or an
            empty `DriverResponse` if no monitor channels are configured.
        """
        if not self.driver.task_monitor_keys or self.driver.task_monitors is None:
            return DriverResponse()
        try:
            mvalues = self.driver.task_monitors.read()
        except Exception:
            LOGGER.error("NImax monitor task read failed", exc_info=True)
            return DriverResponse()
        if not isinstance(mvalues, list):
            mvalues = [mvalues]
        datastore = {
            myname: mvalue
            for myname, mvalue in zip(self.driver.task_monitor_keys, mvalues)
        }
        return DriverResponse(
            response=DriverResponseType.success,
            status=DriverStatus.ok,
            data=datastore,
        )


class CellIVExec(Executor):
    """Executor that drives a synchronized multi-cell current/voltage measurement.

    Owns the `Active` action created by the `/cellIV` endpoint (K7b: the
    endpoint validates samples and calls `contain_action` for the first
    cell's file connection; `_pre_exec` here does the remaining sample
    bookkeeping/file-conn splitting for the other 8 cells, then arms the NI
    tasks via `driver.arm_cell_iv`, handing it plain callables instead of
    `Active` itself). The NI-DAQmx buffer callback pushes data directly via
    those callables (see module docstring), so `_poll` only tracks
    active/finished status; it does not return `data`.
    """

    def __init__(self, samples_in: list, file_sample_list: list, *args, **kwargs):
        """Capture the pre-validated samples and per-cell sample split.

        Args:
            samples_in: Samples returned by `UnifiedSampleDataAPI.get_samples`.
            file_sample_list: Per-`FIFO_cell_keys`-index list of samples,
                computed by the endpoint before `contain_action`.
            *args: Positional args forwarded to :class:`Executor`.
            **kwargs: Keyword args forwarded to :class:`Executor` (must
                include `active`).
        """
        super().__init__(*args, **kwargs)
        LOGGER.info("CellIVExec initialized.")
        p = self.active.action.action_params
        # K7 CRITICAL: read from action_params (subscript), never endpoint fn-args
        self.samplerate = p["SampleRate"]
        self.duration = p["Tval"]
        self.ttlwait = p["TTLwait"]
        self.samples_in = samples_in
        self.file_sample_list = file_sample_list
        self.iv_start_time: Optional[float] = None

    async def _pre_exec(self) -> dict:
        """Split the container action into 9 per-cell file connections and arm the NI tasks."""
        driver = self.active.driver

        for sample in self.samples_in:
            sample.reset_sample_status(SampleStatus.preserved)
            sample.inheritance = SampleInheritance.allow_both

        # cell 0's file_conn was already created by contain_action(); attach its samples
        self.active.action.samples_in = []
        await self.active.append_sample(samples=self.file_sample_list[0], IO="in")

        file_conn_keys = list(self.active.action.file_conn_keys)

        # split into the remaining 8 per-cell file connections
        for i, cell_key in enumerate(driver.FIFO_cell_keys[1:], start=1):
            sample_label = (
                [s.get_global_label() for s in self.file_sample_list[i]]
                if self.file_sample_list[i]
                else None
            )
            new_file_conn_keys = await self.active.split(
                new_fileconnparams=FileConnParams(
                    file_conn_key=self.active.base.dflt_file_conn_key(),
                    sample_global_labels=sample_label,
                    file_type="ni_helao__file",
                    hloheader=HloHeaderModel(optional={"cell": cell_key}),
                )
            )
            if new_file_conn_keys:
                file_conn_keys.append(new_file_conn_keys[0])

            self.active.action.samples_in = []
            await self.active.append_sample(samples=self.file_sample_list[i], IO="in")

        driver.arm_cell_iv(
            samplerate=self.samplerate,
            duration=self.duration,
            ttlwait=self.ttlwait,
            file_conn_keys=file_conn_keys,
            save_data=self.active.action.save_data,
            get_realtime_nowait=self.active.get_realtime_nowait,
            finish_hlo_header=self.active.finish_hlo_header,
            enqueue_data_nowait=self.active.enqueue_data_nowait,
        )
        return {"error": ErrorCodes.none}

    async def _poll(self) -> dict:
        """Wait for the first NI-DAQ callback, then track elapsed time against `duration`.

        Data is pushed directly to `active.enqueue_data_nowait` from the NI
        hardware callback (see `arm_cell_iv`/`streamIV_callback`), so this
        never returns `data` itself.
        """
        driver = self.active.driver
        if not driver.IO_measuring:
            return {"error": ErrorCodes.none, "status": HloStatus.active, "data": {}}
        if self.iv_start_time is None:
            self.iv_start_time = time.time()
        elapsed = time.time() - self.iv_start_time
        if elapsed < self.duration and driver.IO_do_meas:
            status = HloStatus.active
        else:
            status = HloStatus.finished
        return {"error": ErrorCodes.none, "status": status, "data": {}}

    async def _post_exec(self) -> dict:
        """Close the NI IV tasks and clear the driver's per-run hooks."""
        self.active.driver.stop_cell_iv()
        return {"error": ErrorCodes.none, "data": {}}

    async def _manual_stop(self) -> dict:
        """Close the NI IV tasks on abort (estop/manual stop)."""
        self.active.driver.stop_cell_iv()
        return {"error": ErrorCodes.none}


class DevMonExec(Executor):
    """Executor that streams NI-DAQ monitor (thermocouple) channels.

    Reads each `task_monitor_keys` value from the live buffer and finishes
    when `duration` (seconds; -1 for unlimited) elapses.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the executor and capture start time/duration."""
        super().__init__(*args, **kwargs)
        LOGGER.info("DevMonExec initialized.")
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)

    async def _poll(self) -> dict:
        """Read each monitor channel from the live buffer.

        Returns:
            Dict with `error`, `status`, and `data` (per-channel values plus
            `epoch_s`).
        """
        data_dict = {}
        times = []
        for monitor_name in self.active.driver.task_monitor_keys:
            val, epoch_s = self.active.base.get_lbuf(monitor_name)
            data_dict[monitor_name] = val
            times.append(epoch_s)
        data_dict["epoch_s"] = max(times)
        iter_time = time.time()
        elapsed_time = iter_time - self.start_time
        if (self.duration < 0) or (elapsed_time < self.duration):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.01)
        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": data_dict,
        }
