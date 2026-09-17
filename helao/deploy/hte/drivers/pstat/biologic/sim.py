"""A fake EClib1 DLL, not a fake client.

This fakes the ``ctypes.WinDLL`` surface that ``vendor.load_dll`` returns, so
`eclib_client` cannot tell it apart from the real thing. That is deliberate:
the real structs, the real `EccParams` packing, and the real `BL_GetData`
buffer decode all stay inside the code under test -- a simulator bolted on one
layer up (faking the client instead) would exercise none of them.

Three fidelity commitments, each because the real DLL is like this and a
simulator that cheats here would let a client bug pass:

- Every fake export returns an ``int`` error code and never raises. The real
  exports return codes; the client is what raises them as `EclibError`.
- A channel reports `PROG_STATE.RUN` for at least one poll before it ever
  reports `PROG_STATE.STOP` -- the real start race (a channel polled between
  `BL_StartChannel` and the firmware actually running reads STOP) is real,
  and a simulator that jumped straight to STOP would hide a client that
  can't handle it.
- The per-technique column count table (`_COLS`) is transcribed from the PDF
  independently of `data.py`. `data.py`'s tables are what is under test
  elsewhere; if this module asked `data.py` how many columns to emit, the two
  could be wrong together and every decode test would pass vacuously.
"""

import ctypes
import os
from dataclasses import dataclass, field
from typing import Callable

from helao.deploy.hte.drivers.pstat.biologic import vendor

__all__ = [
    "NO_KERNEL_FIRMWARE_CODE",
    "SimConfig",
    "decode_single",
    "encode_single",
    "firmware_loads",
    "load_dll",
    "loaded_ecc_files",
    "push_message",
    "rows_emitted",
    "set_sim_config",
]

NO_KERNEL_FIRMWARE_CODE = 0
_LOADED_FIRMWARE_CODE = 4

_MULTI_PROCESS = {
    vendor.TECH_ID.PEIS,
    vendor.TECH_ID.GEIS,
    vendor.TECH_ID.SPEIS,
    vendor.TECH_ID.SGEIS,
}

#: (technique, board family, process index) -> column count. PDF §7, one row
#: per data-format table. Process 0 is common to a technique's two families
#: unless a separate VMP3/VMP300 row is listed below.
_COLS: dict[tuple[int, vendor.BoardFamily, int], int] = {
    (vendor.TECH_ID.OCV, vendor.BoardFamily.VMP3, 0): 4,
    (vendor.TECH_ID.OCV, vendor.BoardFamily.VMP300, 0): 3,
    (vendor.TECH_ID.CA, vendor.BoardFamily.VMP3, 0): 5,
    (vendor.TECH_ID.CA, vendor.BoardFamily.VMP300, 0): 5,
    (vendor.TECH_ID.CP, vendor.BoardFamily.VMP3, 0): 5,
    (vendor.TECH_ID.CP, vendor.BoardFamily.VMP300, 0): 5,
    (vendor.TECH_ID.CALIMIT, vendor.BoardFamily.VMP3, 0): 5,
    (vendor.TECH_ID.CALIMIT, vendor.BoardFamily.VMP300, 0): 5,
    (vendor.TECH_ID.CPLIMIT, vendor.BoardFamily.VMP3, 0): 5,
    (vendor.TECH_ID.CPLIMIT, vendor.BoardFamily.VMP300, 0): 5,
    (vendor.TECH_ID.CV, vendor.BoardFamily.VMP3, 0): 6,
    (vendor.TECH_ID.CV, vendor.BoardFamily.VMP300, 0): 5,
    (vendor.TECH_ID.PEIS, vendor.BoardFamily.VMP3, 0): 4,
    (vendor.TECH_ID.PEIS, vendor.BoardFamily.VMP300, 0): 4,
    (vendor.TECH_ID.PEIS, vendor.BoardFamily.VMP3, 1): 15,
    (vendor.TECH_ID.PEIS, vendor.BoardFamily.VMP300, 1): 14,
    (vendor.TECH_ID.GEIS, vendor.BoardFamily.VMP3, 0): 4,
    (vendor.TECH_ID.GEIS, vendor.BoardFamily.VMP300, 0): 4,
    (vendor.TECH_ID.GEIS, vendor.BoardFamily.VMP3, 1): 15,
    (vendor.TECH_ID.GEIS, vendor.BoardFamily.VMP300, 1): 14,
    (vendor.TECH_ID.SPEIS, vendor.BoardFamily.VMP3, 0): 5,
    (vendor.TECH_ID.SPEIS, vendor.BoardFamily.VMP300, 0): 5,
    (vendor.TECH_ID.SPEIS, vendor.BoardFamily.VMP3, 1): 16,
    (vendor.TECH_ID.SPEIS, vendor.BoardFamily.VMP300, 1): 15,
    (vendor.TECH_ID.SGEIS, vendor.BoardFamily.VMP3, 0): 5,
    (vendor.TECH_ID.SGEIS, vendor.BoardFamily.VMP300, 0): 5,
    (vendor.TECH_ID.SGEIS, vendor.BoardFamily.VMP3, 1): 16,
    (vendor.TECH_ID.SGEIS, vendor.BoardFamily.VMP300, 1): 15,
}

#: `.ecc` stem (suffix and extension stripped) -> TECH_ID.
_ECC_TO_TECH: dict[str, int] = {
    "ocv": vendor.TECH_ID.OCV,
    "ca": vendor.TECH_ID.CA,
    "cp": vendor.TECH_ID.CP,
    "cv": vendor.TECH_ID.CV,
    "peis": vendor.TECH_ID.PEIS,
    "geis": vendor.TECH_ID.GEIS,
    "seisp": vendor.TECH_ID.SPEIS,
    "seisg": vendor.TECH_ID.SGEIS,
    "calimit": vendor.TECH_ID.CALIMIT,
    "cplimit": vendor.TECH_ID.CPLIMIT,
    "loop": vendor.TECH_ID.LOOP,
    "TI": vendor.TECH_ID.TI,
    "TO": vendor.TECH_ID.TO,
    "TOS": vendor.TECH_ID.TOS,
}

#: Export name -> argtypes, derived from the real ABI table so a call shaped
#: for the real DLL is shaped identically here. Two exceptions: `c_char_p`
#: reconstructs to an immutable `bytes` snapshot inside a ctypes *callback*
#: (there is no address left to write through), so the OUT text-buffer slots
#: use `POINTER(c_char)` instead, which reconstructs to a real pointer.
_ARGSPEC: dict[str, list] = {
    name: list(argtypes) for name, argtypes, *_ in vendor.ECL_API
}
_ARGSPEC["BL_GetLibVersion"][0] = ctypes.POINTER(ctypes.c_char)
_ARGSPEC["BL_GetErrorMsg"][1] = ctypes.POINTER(ctypes.c_char)
_ARGSPEC["BL_GetMessage"][2] = ctypes.POINTER(ctypes.c_char)


def encode_single(value: float) -> int:
    """Reinterpret a float's bits as the `c_uint32` EClib1 hands back."""
    return ctypes.c_uint32.from_buffer(ctypes.c_float(value)).value


def decode_single(word: int) -> float:
    """The inverse of `encode_single`."""
    return ctypes.c_float.from_buffer(ctypes.c_uint32(word)).value


def _tech_for_ecc(filename: bytes) -> int:
    """Recognize a technique from a `.ecc` name -- bare or with a directory.

    The real driver passes a full path (`BL_LoadTechnique` needs one to find
    a file `EClib64.dll` may not be co-located with); the basename is what
    carries the technique identity.
    """
    basename = os.path.basename(filename.decode())
    stem = basename.removesuffix(".ecc").rstrip("0123456789")
    return _ECC_TO_TECH[stem]


def _pack_str64(label: bytes):
    # EccParam.ParamStr is `64 * c_byte`, not `c_char * 64` -- a byte array
    # field only accepts a `bytes` assignment when its element type is
    # `c_char`, so this builds the array element-wise instead.
    padded = label[:63].ljust(64, b"\x00")
    return (ctypes.c_byte * 64)(*padded)


@dataclass
class SimConfig:
    rows_per_poll: int = 4
    polls_until_stop: int = 3
    board_type: int = vendor.BOARD_TYPE.PREMIUM
    kernel_loaded: bool = True
    fail_on: dict[str, int] | None = None
    #: Number of `BL_GetData` polls after `BL_StartChannel` that report zero
    #: rows and `PROG_STATE.STOP` -- the real start race where a channel
    #: polled before the firmware actually runs reads STOP, not RUN.
    idle_polls_before_run: int = 0
    #: Keep emitting `rows_per_poll` rows (with `PROG_STATE.STOP`) forever
    #: past `polls_until_stop` instead of dropping to zero. Exercises the
    #: `RunTracker`/`MAX_DRAINS_PER_CALL` bound on a channel whose tail never
    #: actually ends.
    endless_tail: bool = False
    #: `DataInfo.IRQskipped` to report on the first row-bearing poll after
    #: `BL_StartChannel`. Reported once per run, not accumulated per poll --
    #: real dropped-point counts are a single event, not a running total.
    irq_skipped: int = 0
    #: When set, `BL_GetTechniqueInfos` answers from this list instead of the
    #: channel's actually-loaded technique list -- simulates a firmware that
    #: reports back something other than what was requested.
    technique_ids_override: list[int] | None = None


_CONFIG = SimConfig()


def set_sim_config(cfg: SimConfig) -> None:
    global _CONFIG
    _CONFIG = cfg


@dataclass
class _Channel:
    techniques: list[int] = field(default_factory=list)
    state: int = vendor.PROG_STATE.STOP
    polls: int = 0
    messages: list[str] = field(default_factory=list)
    #: Remaining `BL_GetData` polls to withhold rows for, set fresh by
    #: `BL_StartChannel` from `SimConfig.idle_polls_before_run`.
    idle_remaining: int = 0
    #: Whether `IRQskipped` has already been reported once this run.
    irq_reported: bool = False


class _Sim:
    """One simulated device connection, fresh per `load_dll()` call.

    `cfg` is a property reading the live module-level `_CONFIG`, not a value
    snapshotted at construction. Every field is meant to be perturbed on an
    already-connected, already-loaded simulator: a test connects, loads a
    technique, then calls `set_sim_config` to inject a failure or change how
    many rows a poll yields, the same way a station operator might change an
    instrument setting without power-cycling it. A snapshot taken once at
    `load_dll()` would make every such change silently a no-op.
    """

    def __init__(self):
        self.idn = 1
        self.connected = False
        self._channels: dict[int, _Channel] = {}
        #: The current load episode's `.ecc` filenames, in order. Reset
        #: whenever `BL_LoadTechnique(first=True)` starts a new one -- same
        #: boundary `_Channel.techniques` resets on -- so a re-load with a
        #: trigger prepended does not carry over an earlier setup's load.
        self.loaded_ecc: list[str] = []

    @property
    def cfg(self) -> SimConfig:
        return _CONFIG

    def channel(self, ch: int) -> _Channel:
        return self._channels.setdefault(ch, _Channel())

    def check(self, idn: int, ch: int | None = None) -> int:
        if not self.connected or idn != self.idn:
            return -1  # ERR_GEN_NOTCONNECTED
        if ch is not None and not (0 <= ch < vendor.MAX_SLOT_NB):
            return -3  # ERR_GEN_CHANNELNOTPLUGGED
        return 0


#: The most recently `load_dll()`-created simulator, so `push_message` (which
#: has no dll handle of its own) reaches the same state a just-created
#: `FakeDll` will answer from.
_STATE: _Sim | None = None

#: Count of successful `BL_LoadFirmware` calls. Reset in `load_dll()` --
#: per-run state, scoped to the same lifetime as `_STATE` -- and NOT in
#: `set_sim_config()`, which deliberately resets nothing so a mid-run
#: reconfigure doesn't zero a counter a test is about to assert on.
_FIRMWARE_LOADS = 0

#: Total rows handed back across every `BL_GetData` call. Same reset rule as
#: `_FIRMWARE_LOADS`: `load_dll()` only.
_ROWS_EMITTED = 0


def push_message(channel: int, text: str) -> None:
    if _STATE is not None:
        _STATE.channel(channel).messages.append(text)


def firmware_loads() -> int:
    """Number of `BL_LoadFirmware` calls since the last `load_dll()`."""
    return _FIRMWARE_LOADS


def rows_emitted() -> int:
    """Total rows returned by `BL_GetData` since the last `load_dll()`."""
    return _ROWS_EMITTED


def loaded_ecc_files() -> list[str]:
    """The `.ecc` filenames loaded in the current load episode, in order.

    Resets whenever a `BL_LoadTechnique(first=True)` starts a new episode --
    the same boundary the channel's own technique list resets on -- so a
    re-load with a trigger prepended reports only that reload, not whatever
    an earlier `setup()` already loaded.
    """
    return list(_STATE.loaded_ecc) if _STATE is not None else []


class FakeDll:
    def __init__(self, state: _Sim):
        self._state = state
        self._impls: dict[str, Callable[..., int]] = {
            "BL_GetLibVersion": self._get_lib_version,
            "BL_Connect": self._connect,
            "BL_Disconnect": self._disconnect,
            "BL_TestConnection": self._test_connection,
            "BL_GetChannelsPlugged": self._get_channels_plugged,
            "BL_LoadFirmware": self._load_firmware,
            "BL_GetChannelInfos": self._get_channel_infos,
            "BL_GetChannelBoardType": self._get_channel_board_type,
            "BL_GetErrorMsg": self._get_error_msg,
            "BL_GetMessage": self._get_message,
            "BL_LoadTechnique": self._load_technique,
            "BL_DefineBoolParameter": self._define_bool_parameter,
            "BL_DefineSglParameter": self._define_sgl_parameter,
            "BL_DefineIntParameter": self._define_int_parameter,
            "BL_UpdateParameters": self._update_parameters,
            "BL_GetTechniqueInfos": self._get_technique_infos,
            "BL_GetParamInfos": self._get_technique_infos,
            "BL_StartChannel": self._start_channel,
            "BL_StopChannel": self._stop_channel,
            "BL_GetCurrentValues": self._get_current_values,
            "BL_GetData": self._get_data,
            "BL_ConvertNumericIntoSingle": self._convert_numeric_into_single,
            "BL_ConvertChannelNumericIntoSingle": self._convert_channel_numeric_into_single,
            "BL_ConvertTimeChannelNumericIntoSeconds": self._convert_time_channel,
        }
        self._bound: dict[str, Callable[..., int]] = {}

    def __getitem__(self, name: str) -> Callable[..., int]:
        if name not in self._impls:
            raise KeyError(name)
        if name not in self._bound:
            impl = self._impls[name]

            # `fail_on` (like every other `SimConfig` field, via `_Sim.cfg`)
            # is resolved here, on every call -- never captured once at bind
            # time. `set_sim_config` rebinds the module-level `_CONFIG` name
            # to a new `SimConfig` instance rather than mutating the one an
            # already-connected `_Sim` was built with, so a value read once
            # and cached in this closure would never see a config change
            # made after the name was first looked up.
            def dispatch(*args, _name=name, _impl=impl):
                forced = (self._state.cfg.fail_on or {}).get(_name)
                return _impl(*args) if forced is None else forced

            self._bound[name] = ctypes.CFUNCTYPE(ctypes.c_int32, *_ARGSPEC[name])(
                dispatch
            )
        return self._bound[name]

    # -- connection --------------------------------------------------

    def _get_lib_version(self, buf, size) -> int:
        return 0

    def _connect(self, address, timeout, idn_ptr, info_ptr) -> int:
        self._state.connected = True
        idn_ptr.contents.value = self._state.idn
        info = info_ptr.contents
        info.DeviceCode = 0
        info.RAMSize = 0
        info.CPU = 0
        info.NumberOfChannels = vendor.MAX_SLOT_NB
        info.NumberOfSlots = vendor.MAX_SLOT_NB
        info.FirmwareVersion = 1090
        info.FirmwareDate_yyyy = 2020
        info.FirmwareDate_mm = 1
        info.FirmwareDate_dd = 1
        info.HTdisplayOn = 0
        info.NbOfConnectedPC = 1
        return 0

    def _disconnect(self, idn) -> int:
        err = self._state.check(idn)
        if err:
            return err
        self._state.connected = False
        return 0

    def _test_connection(self, idn) -> int:
        return self._state.check(idn)

    def _get_channels_plugged(self, idn, arr, size) -> int:
        err = self._state.check(idn)
        if err:
            return err
        for i in range(min(size, vendor.MAX_SLOT_NB)):
            arr[i] = True
        return 0

    def _load_firmware(
        self, idn, channels, results, length, showgauge, forceload, binfile, xlxfile
    ) -> int:
        global _FIRMWARE_LOADS
        err = self._state.check(idn)
        if err:
            return err
        for i in range(min(length, vendor.MAX_SLOT_NB)):
            results[i] = 0
        _FIRMWARE_LOADS += 1
        return 0

    # -- channel/board info -------------------------------------------

    def _get_channel_infos(self, idn, ch, info_ptr) -> int:
        err = self._state.check(idn, ch)
        if err:
            return err
        channel = self._state.channel(ch)
        cfg = self._state.cfg
        info = info_ptr.contents
        info.Channel = ch
        info.BoardVersion = 0
        info.BoardSerialNumber = 0
        info.FirmwareCode = (
            _LOADED_FIRMWARE_CODE if cfg.kernel_loaded else NO_KERNEL_FIRMWARE_CODE
        )
        info.FirmwareVersion = 1090
        info.XilinxVersion = 0
        info.AmpCode = 0
        info.NbAmps = 1
        info.Lcboard = 0
        info.Zboard = 0
        info.MUXboard = 0
        info.GPRAboard = 0
        info.MemSize = 0
        info.MemFilled = 0
        info.State = channel.state
        info.MaxIRange = 0
        info.MinIRange = 0
        info.MaxBandwidth = 0
        info.NbOfTechniques = len(channel.techniques)
        return 0

    def _get_channel_board_type(self, idn, ch, board_ptr) -> int:
        err = self._state.check(idn, ch)
        if err:
            return err
        board_ptr.contents.value = self._state.cfg.board_type
        return 0

    def _get_error_msg(self, idn, buf, size) -> int:
        return 0

    def _get_message(self, idn, ch, buf, size_ptr) -> int:
        err = self._state.check(idn, ch)
        if err:
            return err
        channel = self._state.channel(ch)
        text = channel.messages.pop(0).encode() if channel.messages else b""
        cap = max(size_ptr.contents.value - 1, 0)
        data = text[:cap] + b"\x00"
        ctypes.memmove(buf, data, len(data))
        size_ptr.contents.value = len(data) - 1
        return 0

    # -- techniques -----------------------------------------------------

    def _load_technique(self, idn, ch, filename, parms, first, last, display) -> int:
        err = self._state.check(idn, ch)
        if err:
            return err
        try:
            tech = _tech_for_ecc(filename)
        except KeyError:
            return -400  # ERR_TECH_ECCFILENOTEXISTS
        channel = self._state.channel(ch)
        if first:
            channel.techniques = []
            self._state.loaded_ecc = []
        channel.techniques.append(tech)
        # Recorded as a basename: the real driver passes a full path, but
        # `loaded_ecc_files()` exists to check *which technique* loaded, not
        # to check path construction -- that would make every ecc-tracking
        # test depend on `sdk_path`, which is arbitrary in the fixtures.
        self._state.loaded_ecc.append(os.path.basename(filename.decode()))
        return 0

    def _define_bool_parameter(self, label, value, index, parm_ptr) -> int:
        parm = parm_ptr.contents
        parm.ParamStr = _pack_str64(label)
        parm.ParamType = vendor.PARAM_BOOLEAN
        parm.ParamVal = int(bool(value))
        parm.ParamIndex = index
        return 0

    def _define_sgl_parameter(self, label, value, index, parm_ptr) -> int:
        parm = parm_ptr.contents
        parm.ParamStr = _pack_str64(label)
        parm.ParamType = vendor.PARAM_SINGLE
        parm.ParamVal = encode_single(value)
        parm.ParamIndex = index
        return 0

    def _define_int_parameter(self, label, value, index, parm_ptr) -> int:
        parm = parm_ptr.contents
        parm.ParamStr = _pack_str64(label)
        parm.ParamType = vendor.PARAM_INT
        parm.ParamVal = value & 0xFFFFFFFF
        parm.ParamIndex = index
        return 0

    def _update_parameters(self, idn, ch, tech_index, parms_ptr, filename) -> int:
        return self._state.check(idn, ch)

    def _get_technique_infos(self, idn, ch, index, info_ptr) -> int:
        err = self._state.check(idn, ch)
        if err:
            return err
        channel = self._state.channel(ch)
        override = self._state.cfg.technique_ids_override
        source = override if override is not None else channel.techniques
        if not (0 <= index < len(source)):
            return -4  # ERR_GEN_INVALIDPARAMETERS
        info = info_ptr.contents
        info.Id = source[index]
        info.indx = index
        info.nbParams = 0
        info.nbSettings = 0
        return 0

    # -- run control and data --------------------------------------------

    def _start_channel(self, idn, ch) -> int:
        err = self._state.check(idn, ch)
        if err:
            return err
        channel = self._state.channel(ch)
        if not channel.techniques:
            return -403  # ERR_TECH_LOADTECHNIQUEFAILED
        channel.state = vendor.PROG_STATE.RUN
        channel.polls = 0
        channel.idle_remaining = self._state.cfg.idle_polls_before_run
        channel.irq_reported = False
        return 0

    def _stop_channel(self, idn, ch) -> int:
        err = self._state.check(idn, ch)
        if err:
            return err
        channel = self._state.channel(ch)
        channel.state = vendor.PROG_STATE.STOP
        channel.polls = max(channel.polls, self._state.cfg.polls_until_stop + 1)
        return 0

    def _get_current_values(self, idn, ch, cv_ptr) -> int:
        err = self._state.check(idn, ch)
        if err:
            return err
        channel = self._state.channel(ch)
        cv = cv_ptr.contents
        cv.State = channel.state
        cv.TimeBase = 1e-3
        return 0

    def _get_data(self, idn, ch, buf, di_ptr, cv_ptr) -> int:
        global _ROWS_EMITTED
        err = self._state.check(idn, ch)
        if err:
            return err
        channel = self._state.channel(ch)
        cfg = self._state.cfg
        di = di_ptr.contents
        cv = cv_ptr.contents
        cv.TimeBase = 1e-3

        if channel.idle_remaining > 0:
            # The real start race: a channel polled before the firmware has
            # actually begun running reads STOP with nothing recorded yet.
            channel.idle_remaining -= 1
            di.NbRows = 0
            di.NbCols = 0
            di.IRQskipped = 0
            cv.State = channel.state
            return 0

        finished = channel.polls > cfg.polls_until_stop
        if not channel.techniques or (finished and not cfg.endless_tail):
            di.NbRows = 0
            di.NbCols = 0
            di.IRQskipped = 0
            cv.State = channel.state
            return 0

        tech_id = channel.techniques[0]
        family = vendor.board_family(cfg.board_type)
        multi = tech_id in _MULTI_PROCESS
        process_index = channel.polls % 2 if multi else 0
        rows = cfg.rows_per_poll
        cols = _COLS[(tech_id, family, process_index)]
        channel.state = (
            vendor.PROG_STATE.STOP
            if channel.polls >= cfg.polls_until_stop
            else vendor.PROG_STATE.RUN
        )

        tick = channel.polls * rows
        for r in range(rows):
            base = r * cols
            buf[base] = tick + r  # t_high: monotonic whole-tick count
            buf[base + 1] = 0  # t_low
            for c in range(2, cols):
                buf[base + c] = encode_single(float(tick + r + c))

        di.NbRows = rows
        di.NbCols = cols
        di.TechniqueID = tech_id
        di.TechniqueIndex = 0
        di.ProcessIndex = process_index
        di.StartTime = 0.0
        # A dropped-point count is a single event, not a running total --
        # reported once per run, on the first row-bearing poll.
        if not channel.irq_reported:
            di.IRQskipped = cfg.irq_skipped
            channel.irq_reported = True
        else:
            di.IRQskipped = 0
        channel.polls += 1
        cv.State = channel.state
        _ROWS_EMITTED += rows
        return 0

    # -- unit conversions -------------------------------------------------

    def _convert_numeric_into_single(self, word, out_ptr) -> int:
        out_ptr.contents.value = decode_single(word)
        return 0

    def _convert_channel_numeric_into_single(self, word, out_ptr, channel_flag) -> int:
        out_ptr.contents.value = decode_single(word)
        return 0

    def _convert_time_channel(self, words_ptr, out_ptr, timebase, channel_flag) -> int:
        # The two words are the high and low 32 bits of one 64-bit tick
        # count, composed before scaling -- not a raw tick plus a
        # separately-scaled one.
        ticks = (words_ptr[0] << 32) + words_ptr[1]
        out_ptr.contents.value = ticks * timebase
        return 0


def load_dll(sdk_path: str | None = None) -> FakeDll:
    """Ignore `sdk_path` entirely -- there is no file to find."""
    global _STATE, _FIRMWARE_LOADS, _ROWS_EMITTED
    _STATE = _Sim()
    _FIRMWARE_LOADS = 0
    _ROWS_EMITTED = 0
    return FakeDll(_STATE)
