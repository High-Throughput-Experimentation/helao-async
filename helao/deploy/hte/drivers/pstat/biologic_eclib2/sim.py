"""A fake EC-Lib 2.0 SDK, so the backend runs with no DLL and no instrument.

Selected by ``simulate: true`` on the action server's params, the same way
``oceandirect_sim.py`` stands in for OceanDirect. Two things it is deliberately
faithful about, because they are what the code above it gets wrong:

- **It raises like the vendor layer does.** Every real ``BL_*`` wrapper raises
  ``EC_SDK_Runtime_Error`` on a non-zero return rather than returning a code, so
  a simulator that returned codes would let error handling pass here and fail at
  the station.
- **It ends an acquisition the way the vendor examples detect the end**: by
  eventually reporting zero rows with ``channel_state`` IDLE, per technique, in
  the order the techniques were added.

It does *not* simulate electrochemistry. Rows are synthetic ramps -- enough to
prove the plan was applied, the right ``BL_ProcessRawTo*`` was chosen for each
technique, and the columns come out right.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Mirrors of the shipped enums, by name. Values match
# Python/Constants/bl_constants.py where anything downstream compares them;
# `vendor.member` resolves by name, so the names are what matter.
ChannelState = Enum(
    "ChannelState",
    {"EC_SDK_CHANNEL_STATE_IDLE": 0, "EC_SDK_CHANNEL_STATE_RUNNING": 1},
)

ErrorCode = Enum(
    "ErrorCode",
    {
        "EC_SDK_ERROR_NOERROR": 0,
        "EC_SDK_ERROR_LICENSE_NOT_VALID": -99900,
        "EC_SDK_ERROR_LICENSE_NOT_AUTHORISED": -99901,
        "EC_SDK_ERROR_LICENSE_TECHNIQUE_EIS_NOT_AUTHORISED": -99902,
    },
)

TechniqueIdentifier = Enum(
    "TechniqueIdentifier",
    {
        "EC_SDK_TECHNIQUE_NONE": 0,
        "EC_SDK_TECHNIQUE_OCV": 100,
        "EC_SDK_TECHNIQUE_CA": 101,
        "EC_SDK_TECHNIQUE_CP": 102,
        "EC_SDK_TECHNIQUE_CV": 103,
        "EC_SDK_TECHNIQUE_PEIS": 104,
        "EC_SDK_TECHNIQUE_GEIS": 107,
    },
)

IRangeValue = Enum(
    "IRangeValue",
    {
        "EC_SDK_IRANGE_NONE": 0,
        "EC_SDK_IRANGE_100pA": 1,
        "EC_SDK_IRANGE_1nA": 2,
        "EC_SDK_IRANGE_10nA": 3,
        "EC_SDK_IRANGE_100nA": 4,
        "EC_SDK_IRANGE_1uA": 5,
        "EC_SDK_IRANGE_10uA": 6,
        "EC_SDK_IRANGE_100uA": 7,
        "EC_SDK_IRANGE_1mA": 8,
        "EC_SDK_IRANGE_10mA": 9,
        "EC_SDK_IRANGE_100mA": 10,
        "EC_SDK_IRANGE_1A": 11,
        "EC_SDK_IRANGE_BOOSTER": 12,
    },
)

IRangeMode = Enum(
    "IRangeMode",
    {"I_RANGE_MODE_FIXED": 0, "I_RANGE_MODE_AUTO": 1, "I_RANGE_MODE_KEEP": 2},
)

ERangeValue = Enum(
    "ERangeValue",
    {
        "EC_SDK_ERANGE_2_5": 0,
        "EC_SDK_ERANGE_5": 1,
        "EC_SDK_ERANGE_10": 2,
        "EC_SDK_ERANGE_AUTO": 3,
    },
)

# 1..9 and no KEEP, matching the shipped enum rather than the docs' table.
BandwidthValue = Enum(
    "BandwidthValue", {f"EC_SDK_BANDWIDTH_{n}": n for n in range(1, 10)}
)

SweepMode = Enum("SweepMode", {"EC_SDK_SWEEP_LOG": 0, "EC_SDK_SWEEP_LINEAR": 1})

# The shipped VsInitial aliases the current-control names onto the
# voltage-control ones (both start at 0); reproduced so name lookup behaves the
# same here.
VsInitial = Enum(
    "VsInitial",
    {
        "EC_SDK_VS_EREF": 0,
        "EC_SDK_VS_EINIT": 1,
        "EC_SDK_VS_EOC": 2,
        "EC_SDK_VS_IREF": 0,
        "EC_SDK_VS_IINIT": 1,
        "EC_SDK_VS_IPREV": 2,
    },
)

FloatingMode = Enum(
    "FloatingMode",
    {"EC_SDK_FLOATING_MODE_GROUNDED": 0, "EC_SDK_FLOATING_MODE_FLOATING": 1},
)

ConnectionMode = Enum(
    "ConnectionMode",
    {
        "EC_SDK_CONNECTION_MODE_STANDARD": 0,
        "EC_SDK_CONNECTION_MODE_CETOGRND": 1,
        "EC_SDK_CONNECTION_MODE_WETOGRND": 2,
        "EC_SDK_CONNECTION_MODE_HIGHVOLTAGE": 3,
    },
)

FloatParameter = Enum(
    "FloatParameter",
    {
        name: i
        for i, name in enumerate(
            [
                "EC_SDK_AMPLITUDE_CURRENT_IN_AMP",
                "EC_SDK_AMPLITUDE_VOLTAGE_IN_V",
                "EC_SDK_BEGIN_MEASURING_I",
                "EC_SDK_END_MEASURING_I",
                "EC_SDK_FINAL_FREQUENCY_IN_HZ",
                "EC_SDK_INITIAL_FREQUENCY_IN_HZ",
                "EC_SDK_REST_TIME_IN_S",
                "EC_SDK_WAIT_FOR_STEADY_IN_SINE_PERIOD",
            ]
        )
    },
)

FloatArrayParameter = Enum(
    "FloatArrayParameter",
    {
        name: i
        for i, name in enumerate(
            [
                "EC_SDK_CURRENT_STEP_IN_A",
                "EC_SDK_DURATION_STEP_IN_S",
                "EC_SDK_RECORD_EVERY_DE",
                "EC_SDK_RECORD_EVERY_DI",
                "EC_SDK_RECORD_EVERY_DT",
                "EC_SDK_SCAN_RATE_IN_V_PER_S",
                "EC_SDK_VOLTAGE_STEP_IN_V",
            ]
        )
    },
)

IntParameter = Enum(
    "IntParameter",
    {
        name: i
        for i, name in enumerate(
            [
                "EC_SDK_AVERAGE_N_TIMES",
                "EC_SDK_FREQUENCY_NUMBER",
                "EC_SDK_N_CYCLES",
                "EC_SDK_SCAN_NUMBER",
                "EC_SDK_STEP_NUMBER",
            ]
        )
    },
)

BoolParameter = Enum(
    "BoolParameter",
    {
        name: i
        for i, name in enumerate(
            [
                "EC_SDK_ENABLE_AVERAGE_EVERY_DE",
                "EC_SDK_ENABLE_DRIFT_CORRECTION",
                "EC_SDK_RECORD_EVERY_DT_ARRAY_MODE",
                "EC_SDK_RECORD_EVERY_DE_ARRAY_MODE",
                "EC_SDK_RECORD_EVERY_DI_ARRAY_MODE",
            ]
        )
    },
)

EnumParameter = Enum("EnumParameter", {"EC_SDK_SWEEP_MODE": 0})
EnumArrayParameter = Enum("EnumArrayParameter", {"EC_SDK_VS_INITIAL": 0})


class EC_SDK_Runtime_Error(Exception):
    """Stand-in for the vendor exception, which carries an ``ErrorCode``."""

    def __init__(self, message: str, code: Any = None):
        super().__init__(message)
        self.code = code


@dataclass
class DeviceInfo:
    device_code: int = 16  # EC_SDK_DEVICE_SP300
    channels_plugged: list = field(default_factory=lambda: [True] + [False] * 15)
    number_of_slots: int = 16
    serial_number: int = 1234


@dataclass
class DataInfo:
    channel_state: Any
    number_of_rows: int
    number_of_cols: int
    technique_index: int
    technique_identifier: Any
    timebase_in_second: float = 20e-6
    start_time_in_second: float = 0.0
    extra_data_flags: int = 0
    loop_counters: list = field(default_factory=lambda: [0] * 10)


@dataclass
class LiveValues:
    channel_state: Any
    memory_used_in_percent: float = 0.0
    current_technique_index: int = 0
    current_technique_identifier: Any = None
    Ewe_in_volt: float = 0.0
    Ece_in_volt: float = 0.0
    I_measured_in_ampere: float = 0.0
    I_range: Any = None
    elapsed_time_in_second: float = 0.0
    frequency_in_hertz: float = 0.0
    loop_counters: list = field(default_factory=lambda: [0] * 10)


@dataclass
class OcvData:
    time: float
    ewe: float


@dataclass
class StepData:
    """Stands in for CaData / CpData / CvData, which share these field names."""

    time: float
    ewe_average: float
    i_average: float
    cycle: int
    step_index: int = 0


@dataclass
class EisData:
    frequency: float
    mod_ewe: float
    mod_iwe: float
    phase_we: float
    ewe_dc: float
    iwe_dc: float
    e_range_we: float
    mod_ece: float
    mod_ice: float
    phase_ce: float
    ece_dc: float
    ice_dc: float
    e_range_ce: float
    time_in_s: float


CaData = CpData = CvData = StepData


class Constants:
    """Namespace mirroring the vendor ``Constants`` module for :func:`vendor.member`."""

    ChannelState = ChannelState
    ErrorCode = ErrorCode
    TechniqueIdentifier = TechniqueIdentifier
    IRangeValue = IRangeValue
    IRangeMode = IRangeMode
    ERangeValue = ERangeValue
    BandwidthValue = BandwidthValue
    SweepMode = SweepMode
    VsInitial = VsInitial
    FloatingMode = FloatingMode
    ConnectionMode = ConnectionMode
    FloatParameter = FloatParameter
    FloatArrayParameter = FloatArrayParameter
    IntParameter = IntParameter
    BoolParameter = BoolParameter
    EnumParameter = EnumParameter
    EnumArrayParameter = EnumArrayParameter
    OcvData = OcvData
    CaData = CaData
    CpData = CpData
    CvData = CvData
    EisData = EisData
    DataInfo = DataInfo
    LiveValues = LiveValues
    DeviceInfo = DeviceInfo


@dataclass
class _Technique:
    identifier: Any
    index: int
    params: dict = field(default_factory=dict)
    irange: tuple | None = None
    erange: Any = None
    bandwidth: Any = None


@dataclass
class _Experiment:
    handle: int
    techniques: list = field(default_factory=list)


@dataclass
class _Channel:
    experiment: Any = None
    running: bool = False
    #: Index into ``experiment.techniques`` of the technique now producing rows.
    cursor: int = 0
    #: Downloads served for the current technique.
    served: int = 0


#: Rows the simulator emits per technique, split across this many downloads.
ROWS_PER_TECHNIQUE = 4
DOWNLOADS_PER_TECHNIQUE = 2


class SimECLibAPI:
    """Fake ``ECLibAPI``, matching the vendor class's call signatures.

    Args:
        path: Ignored; accepted so construction matches the real class.
        fail_on: Optional map of method name -> ``ErrorCode`` to raise, for
            exercising error handling (e.g. a missing license).
    """

    MAX_NUMBER_OF_CHANNELS = 16

    def __init__(self, path: str = "<simulated>", fail_on: dict | None = None):
        self.path = path
        self.fail_on = dict(fail_on or {})
        self.connected = False
        self.address: str | None = None
        self.channels: dict[int, _Channel] = {}
        self.experiments: dict[int, _Experiment] = {}
        self.techniques: dict[int, _Technique] = {}
        self.firmware_loaded: list[int] = []
        self._next_handle = 1
        #: Every call made, in order, for tests to assert against.
        self.calls: list[tuple] = []

    # -- plumbing ---------------------------------------------------------

    def _record(self, name: str, *args) -> None:
        self.calls.append((name, *args))
        if name in self.fail_on:
            code = self.fail_on[name]
            raise EC_SDK_Runtime_Error(f"simulated failure in {name}", code)

    def _handle(self) -> int:
        handle = self._next_handle
        self._next_handle += 1
        return handle

    def _channel(self, channel: int) -> _Channel:
        if not self.connected:
            raise EC_SDK_Runtime_Error("not connected", ErrorCode.EC_SDK_ERROR_NOERROR)
        if channel not in self.channels:
            raise EC_SDK_Runtime_Error(
                f"channel {channel} not plugged", ErrorCode.EC_SDK_ERROR_NOERROR
            )
        return self.channels[channel]

    # -- generic / connection --------------------------------------------

    def BL_GetLibVersion(self) -> str:
        self._record("BL_GetLibVersion")
        return "2.0.2-simulated"

    def BL_Connect(self, address: str, timeout: int = 5):
        self._record("BL_Connect", address, timeout)
        self.connected = True
        self.address = address
        info = DeviceInfo()
        self.channels = {
            i: _Channel() for i, on in enumerate(info.channels_plugged) if on
        }
        return self._handle(), info

    def BL_TestConnection(self, connection_handle: int) -> None:
        self._record("BL_TestConnection", connection_handle)
        if not self.connected:
            raise EC_SDK_Runtime_Error("not connected", ErrorCode.EC_SDK_ERROR_NOERROR)

    def BL_Disconnect(self, connection_handle: int) -> None:
        self._record("BL_Disconnect", connection_handle)
        self.connected = False
        self.channels = {}

    def BL_LoadFirmware(
        self, connection_handle: int, channel_list: list, force_reload: bool
    ) -> list:
        self._record(
            "BL_LoadFirmware", connection_handle, list(channel_list), force_reload
        )
        # Accumulated, not replaced: the driver loads one channel per call, so
        # replacing would hide every load but the last.
        self.firmware_loaded = sorted(
            set(self.firmware_loaded) | {i for i, on in enumerate(channel_list) if on}
        )
        return [ErrorCode.EC_SDK_ERROR_NOERROR] * len(channel_list)

    # -- experiment -------------------------------------------------------

    def BL_CreateExperiment(self, device_info, floating_mode, connection_mode) -> int:
        self._record("BL_CreateExperiment", floating_mode, connection_mode)
        handle = self._handle()
        self.experiments[handle] = _Experiment(handle=handle)
        return handle

    def BL_DeleteExperiment(self, experiment_handle: int) -> None:
        self._record("BL_DeleteExperiment", experiment_handle)
        experiment = self.experiments.pop(experiment_handle, None)
        if experiment is not None:
            for tech in experiment.techniques:
                self.techniques.pop(id(tech), None)

    def BL_AddTechnique(self, experiment_handle: int, technique_identifier) -> int:
        self._record("BL_AddTechnique", experiment_handle, technique_identifier)
        experiment = self.experiments[experiment_handle]
        handle = self._handle()
        tech = _Technique(
            identifier=technique_identifier, index=len(experiment.techniques)
        )
        experiment.techniques.append(tech)
        self.techniques[handle] = tech
        return handle

    def BL_LoadExperiment(
        self, connection_handle: int, channel: int, experiment_handle: int
    ) -> None:
        self._record("BL_LoadExperiment", connection_handle, channel, experiment_handle)
        chan = self._channel(channel)
        chan.experiment = self.experiments[experiment_handle]
        chan.cursor = 0
        chan.served = 0

    def BL_UpdateExperiment(
        self, connection_handle: int, channel: int, experiment_handle: int
    ) -> None:
        self._record(
            "BL_UpdateExperiment", connection_handle, channel, experiment_handle
        )
        self._channel(channel)

    def BL_SetSafetyLimit(self, experiment_handle: int, limit) -> None:
        self._record("BL_SetSafetyLimit", experiment_handle, limit)

    def BL_SetTechniqueLimit(self, technique_handle: int, limit) -> None:
        self._record("BL_SetTechniqueLimit", technique_handle, limit)

    # -- technique parameters --------------------------------------------

    def _set(self, method: str, technique_handle: int, parameter, value) -> None:
        self._record(method, technique_handle, parameter, value)
        self.techniques[technique_handle].params[parameter.name] = value

    def BL_SetFloatParameter(self, technique_handle, parameter, value) -> None:
        self._set("BL_SetFloatParameter", technique_handle, parameter, value)

    def BL_SetFloatArrayParameter(self, technique_handle, parameter, value) -> None:
        self._set("BL_SetFloatArrayParameter", technique_handle, parameter, list(value))

    def BL_SetIntParameter(self, technique_handle, parameter, value) -> None:
        self._set("BL_SetIntParameter", technique_handle, parameter, value)

    def BL_SetIntArrayParameter(self, technique_handle, parameter, value) -> None:
        self._set("BL_SetIntArrayParameter", technique_handle, parameter, list(value))

    def BL_SetBoolParameter(self, technique_handle, parameter, value) -> None:
        self._set("BL_SetBoolParameter", technique_handle, parameter, value)

    def BL_SetBoolArrayParameter(self, technique_handle, parameter, value) -> None:
        self._set("BL_SetBoolArrayParameter", technique_handle, parameter, list(value))

    def BL_SetEnumParameter(self, technique_handle, parameter, value) -> None:
        self._set("BL_SetEnumParameter", technique_handle, parameter, value)

    def BL_SetEnumArrayParameter(self, technique_handle, parameter, value) -> None:
        self._set("BL_SetEnumArrayParameter", technique_handle, parameter, list(value))

    def BL_UpdateFloatParameter(self, technique_handle, parameter, value) -> None:
        self._set("BL_UpdateFloatParameter", technique_handle, parameter, value)

    def BL_UpdateFloatArrayParameter(self, technique_handle, parameter, value) -> None:
        self._set(
            "BL_UpdateFloatArrayParameter", technique_handle, parameter, list(value)
        )

    def BL_UpdateIntParameters(self, technique_handle, parameter, value) -> None:
        self._set("BL_UpdateIntParameters", technique_handle, parameter, value)

    def BL_SetIRange(self, technique_handle, i_range_mode, i_range_value) -> None:
        self._record("BL_SetIRange", technique_handle, i_range_mode, i_range_value)
        self.techniques[technique_handle].irange = (i_range_mode, i_range_value)

    def BL_SetERange(self, technique_handle, e_range_value) -> None:
        self._record("BL_SetERange", technique_handle, e_range_value)
        self.techniques[technique_handle].erange = e_range_value

    def BL_SetBandwidth(self, technique_handle, bandwidth_value) -> None:
        self._record("BL_SetBandwidth", technique_handle, bandwidth_value)
        self.techniques[technique_handle].bandwidth = bandwidth_value

    # -- run / read -------------------------------------------------------

    def BL_StartChannel(self, connection_handle: int, channel: int) -> None:
        self._record("BL_StartChannel", connection_handle, channel)
        chan = self._channel(channel)
        if chan.experiment is None:
            raise EC_SDK_Runtime_Error(
                "no experiment loaded", ErrorCode.EC_SDK_ERROR_NOERROR
            )
        chan.running = True
        chan.cursor = 0
        chan.served = 0

    def BL_StopChannel(self, connection_handle: int, channel: int) -> None:
        self._record("BL_StopChannel", connection_handle, channel)
        chan = self._channel(channel)
        chan.running = False
        # A stopped channel has nothing further to hand over.
        chan.cursor = len(chan.experiment.techniques) if chan.experiment else 0

    def BL_GetLiveValues(self, connection_handle: int, channel: int) -> LiveValues:
        self._record("BL_GetLiveValues", connection_handle, channel)
        chan = self._channel(channel)
        running = chan.running and self._has_more(chan)
        identifier = None
        if running and chan.experiment is not None:
            identifier = chan.experiment.techniques[chan.cursor].identifier
        return LiveValues(
            channel_state=(
                ChannelState.EC_SDK_CHANNEL_STATE_RUNNING
                if running
                else ChannelState.EC_SDK_CHANNEL_STATE_IDLE
            ),
            current_technique_index=chan.cursor,
            current_technique_identifier=identifier,
            Ewe_in_volt=0.5,
            I_measured_in_ampere=1e-4,
            I_range=IRangeValue.EC_SDK_IRANGE_1mA,
        )

    def _has_more(self, chan: _Channel) -> bool:
        return chan.experiment is not None and chan.cursor < len(
            chan.experiment.techniques
        )

    def BL_DownloadRawData(self, connection_handle: int, channel: int):
        self._record("BL_DownloadRawData", connection_handle, channel)
        chan = self._channel(channel)
        if not self._has_more(chan):
            chan.running = False
            return (
                DataInfo(
                    channel_state=ChannelState.EC_SDK_CHANNEL_STATE_IDLE,
                    number_of_rows=0,
                    number_of_cols=0,
                    technique_index=0,
                    technique_identifier=TechniqueIdentifier.EC_SDK_TECHNIQUE_NONE,
                ),
                [],
            )

        tech = chan.experiment.techniques[chan.cursor]
        batch = ROWS_PER_TECHNIQUE // DOWNLOADS_PER_TECHNIQUE
        offset = chan.served * batch
        rows = _synthesize(tech.identifier, offset, batch)

        chan.served += 1
        last_batch = chan.served >= DOWNLOADS_PER_TECHNIQUE
        if last_batch:
            chan.cursor += 1
            chan.served = 0

        still_running = self._has_more(chan)
        if not still_running:
            chan.running = False
        return (
            DataInfo(
                channel_state=(
                    ChannelState.EC_SDK_CHANNEL_STATE_RUNNING
                    if still_running
                    else ChannelState.EC_SDK_CHANNEL_STATE_IDLE
                ),
                number_of_rows=len(rows),
                number_of_cols=1,
                technique_index=tech.index,
                technique_identifier=tech.identifier,
            ),
            rows,
        )

    # The raw buffer here already holds typed rows, so each ProcessRawTo*
    # merely checks that the caller picked the reader matching the technique
    # the DataInfo named -- which is the mistake worth catching.
    def _process(self, data_buffer, data_info, expected: set, kind: str) -> list:
        self._record(f"BL_ProcessRawTo{kind}Data", data_info.technique_identifier)
        if data_info.technique_identifier.name not in expected:
            raise EC_SDK_Runtime_Error(
                f"BL_ProcessRawTo{kind}Data called for "
                f"{data_info.technique_identifier.name}",
                ErrorCode.EC_SDK_ERROR_NOERROR,
            )
        return list(data_buffer)[: data_info.number_of_rows]

    def BL_ProcessRawToOcvData(self, data_buffer, data_info) -> list:
        return self._process(data_buffer, data_info, {"EC_SDK_TECHNIQUE_OCV"}, "Ocv")

    def BL_ProcessRawToCaData(self, data_buffer, data_info) -> list:
        return self._process(data_buffer, data_info, {"EC_SDK_TECHNIQUE_CA"}, "Ca")

    def BL_ProcessRawToCpData(self, data_buffer, data_info) -> list:
        return self._process(data_buffer, data_info, {"EC_SDK_TECHNIQUE_CP"}, "Cp")

    def BL_ProcessRawToCvData(self, data_buffer, data_info) -> list:
        return self._process(data_buffer, data_info, {"EC_SDK_TECHNIQUE_CV"}, "Cv")

    def BL_ProcessRawToEisData(self, data_buffer, data_info) -> list:
        return self._process(
            data_buffer,
            data_info,
            {"EC_SDK_TECHNIQUE_PEIS", "EC_SDK_TECHNIQUE_GEIS"},
            "Eis",
        )


def _synthesize(identifier, offset: int, count: int) -> list:
    """Synthetic rows for a technique. Ramps, not electrochemistry."""
    name = identifier.name
    if name == "EC_SDK_TECHNIQUE_OCV":
        return [
            OcvData(time=0.1 * (offset + i), ewe=1.5 + 0.01 * i) for i in range(count)
        ]
    if name in ("EC_SDK_TECHNIQUE_CA", "EC_SDK_TECHNIQUE_CP", "EC_SDK_TECHNIQUE_CV"):
        return [
            StepData(
                time=0.1 * (offset + i),
                ewe_average=0.5 + 0.01 * i,
                i_average=1e-4 * (i + 1),
                cycle=0,
            )
            for i in range(count)
        ]
    if name in ("EC_SDK_TECHNIQUE_PEIS", "EC_SDK_TECHNIQUE_GEIS"):
        return [
            EisData(
                frequency=10.0 ** (3 - (offset + i)),
                mod_ewe=0.02,
                mod_iwe=0.004,
                phase_we=0.5,
                ewe_dc=0.3,
                iwe_dc=1e-3,
                e_range_we=5.0,
                mod_ece=0.04,
                mod_ice=0.008,
                phase_ce=-0.25,
                ece_dc=0.6,
                ice_dc=2e-3,
                e_range_ce=5.0,
                time_in_s=0.1 * (offset + i),
            )
            for i in range(count)
        ]
    raise EC_SDK_Runtime_Error(
        f"simulator has no rows for {name}", ErrorCode.EC_SDK_ERROR_NOERROR
    )


def sim_modules(fail_on: dict | None = None):
    """An :class:`~.vendor.SdkModules`-shaped stand-in for the vendor package.

    Lets :mod:`sdk_client` be constructed identically whether it is driving the
    real SDK or this one.
    """
    from pathlib import Path

    from helao.deploy.hte.drivers.pstat.biologic_eclib2.vendor import SdkModules

    def api_class(path: str):
        return SimECLibAPI(path, fail_on=fail_on)

    return SdkModules(
        api_class=api_class,  # type: ignore[arg-type]
        constants=Constants,
        error_class=EC_SDK_Runtime_Error,
        sdk_root=Path("<simulated>"),
    )
