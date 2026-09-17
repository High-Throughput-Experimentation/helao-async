"""The EClib1 ABI, transcribed rather than imported.

The EC-Lab Development Package ships BioLogic's own ctypes layer under
``Examples/Python/kbio/``, and it is a good one -- but every file in it carries
the OEM Package licence header ("may only be used for non-commercial purposes"),
and this repository is a public remote. So the struct layouts, the export
signatures and the constant tables are transcribed here from the package's PDF
and its export table, and nothing is copied.

Two transcription traps, both of which produce a working-looking driver that
talks to the wrong thing:

**The DLL's channel index is 0-based.** Every ``kbio`` wrapper passes ``ch - 1``,
which is that layer's own 1-based sugar, not the DLL's convention --
``easy_biologic`` passes ``ch`` straight through as ``c_uint8(ch)``, and HELAO's
``channel`` action param defaults to ``0``. Nothing here subtracts.

**``BL_GetChannelInfos`` is plural.** ``BL_GetChannelInfo`` does not exist, and a
missing export raises only when the name is first bound.
"""

import ctypes
import os
from ctypes import (
    POINTER,
    c_bool,
    c_byte,
    c_char_p,
    c_double,
    c_float,
    c_int8,
    c_int32,
    c_uint8,
    c_uint32,
)
from enum import Enum, IntEnum
from typing import Any

__all__ = [
    "BANDWIDTH",
    "BOARD_TYPE",
    "BoardFamily",
    "ChannelInfo",
    "ChannelsArray",
    "CurrentValues",
    "DataBuffer",
    "DataInfo",
    "DeviceInfo",
    "ECL_API",
    "ERROR_NAMES",
    "EccParam",
    "EccParams",
    "E_RANGE",
    "I_RANGE",
    "PARAM_BOOLEAN",
    "PARAM_INT",
    "PARAM_SINGLE",
    "PROG_STATE",
    "ResultsArray",
    "TECH_ID",
    "TechniqueInfos",
    "VendorError",
    "board_family",
    "ecc_file",
    "firmware_assets",
    "load_dll",
]

#: Where a station's EC-Lab Development Package install lives by default.
DEFAULT_SDK_PATH = r"C:\EC-Lab Development Package\lib"

DLL_NAME = "EClib64.dll"

MAX_SLOT_NB = 16

ChannelsArray = c_bool * MAX_SLOT_NB
ResultsArray = c_int32 * MAX_SLOT_NB
DataBuffer = c_uint32 * 1000

c_double_p = POINTER(c_double)
c_float_p = POINTER(c_float)
c_int32_p = POINTER(c_int32)
c_uint32_p = POINTER(c_uint32)


class VendorError(RuntimeError):
    """A problem with the SDK install or with an ABI argument, not with a call."""


class DeviceInfo(ctypes.Structure):
    _fields_ = [
        ("DeviceCode", c_int32),
        ("RAMSize", c_int32),
        ("CPU", c_int32),
        ("NumberOfChannels", c_int32),
        ("NumberOfSlots", c_int32),
        ("FirmwareVersion", c_int32),
        ("FirmwareDate_yyyy", c_int32),
        ("FirmwareDate_mm", c_int32),
        ("FirmwareDate_dd", c_int32),
        ("HTdisplayOn", c_int32),
        ("NbOfConnectedPC", c_int32),
    ]


class ChannelInfo(ctypes.Structure):
    _fields_ = [
        ("Channel", c_int32),
        ("BoardVersion", c_int32),
        ("BoardSerialNumber", c_int32),
        ("FirmwareCode", c_int32),
        ("FirmwareVersion", c_int32),
        ("XilinxVersion", c_int32),
        ("AmpCode", c_int32),
        ("NbAmps", c_int32),
        ("Lcboard", c_int32),
        ("Zboard", c_int32),
        ("MUXboard", c_int32),
        ("GPRAboard", c_int32),
        ("MemSize", c_int32),
        ("MemFilled", c_int32),
        ("State", c_int32),
        ("MaxIRange", c_int32),
        ("MinIRange", c_int32),
        ("MaxBandwidth", c_int32),
        ("NbOfTechniques", c_int32),
    ]


class CurrentValues(ctypes.Structure):
    _fields_ = [
        ("State", c_int32),
        ("MemFilled", c_int32),
        ("TimeBase", c_float),
        ("Ewe", c_float),
        ("EweRangeMin", c_float),
        ("EweRangeMax", c_float),
        ("Ece", c_float),
        ("EceRangeMin", c_float),
        ("EceRangeMax", c_float),
        ("Eoverflow", c_int32),
        ("I", c_float),
        ("IRange", c_int32),
        ("Ioverflow", c_int32),
        ("ElapsedTime", c_float),
        ("Freq", c_float),
        ("Rcomp", c_float),
        ("Saturation", c_int32),
        ("OptErr", c_int32),
        ("OptPos", c_int32),
    ]


class DataInfo(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("IRQskipped", c_int32),
        ("NbRows", c_int32),
        ("NbCols", c_int32),
        ("TechniqueIndex", c_int32),
        ("TechniqueID", c_int32),
        ("ProcessIndex", c_int32),
        ("loop", c_int32),
        ("StartTime", c_double),
        ("MuxPad", c_int32),
    ]


#: PDF: TEccParam.ParamType.
PARAM_INT = 0
PARAM_BOOLEAN = 1
PARAM_SINGLE = 2


class EccParam(ctypes.Structure):
    _fields_ = [
        ("ParamStr", 64 * c_byte),
        ("ParamType", c_int32),
        ("ParamVal", c_uint32),
        ("ParamIndex", c_int32),
    ]


ECC_PARM = POINTER(EccParam)


class EccParams(ctypes.Structure):
    _pack_ = 4
    _fields_ = [("len", c_int32), ("pParams", ECC_PARM)]


ECC_PARMS = POINTER(EccParams)


class TechniqueInfos(ctypes.Structure):
    _fields_ = [
        ("Id", c_int32),
        ("indx", c_int32),
        ("nbParams", c_int32),
        ("nbSettings", c_int32),
        ("Params", ECC_PARM),
        ("HardSettings", ECC_PARM),
    ]


DEVICE_INFO = POINTER(DeviceInfo)
CH_INFO = POINTER(ChannelInfo)
CURRENT_VALUES = POINTER(CurrentValues)
DATA_INFO = POINTER(DataInfo)
TECHNIQUE_INFOS = POINTER(TechniqueInfos)


class BOARD_TYPE(IntEnum):
    UNKNOWN = 0
    ESSENTIAL = 1
    PREMIUM = 2
    DIGICORE = 3


class PROG_STATE(IntEnum):
    STOP = 0
    RUN = 1
    PAUSE = 2
    SYNC = 3


class I_RANGE(IntEnum):
    I_RANGE_KEEP = -1
    I_RANGE_100pA = 0
    I_RANGE_1nA = 1
    I_RANGE_10nA = 2
    I_RANGE_100nA = 3
    I_RANGE_1uA = 4
    I_RANGE_10uA = 5
    I_RANGE_100uA = 6
    I_RANGE_1mA = 7
    I_RANGE_10mA = 8
    I_RANGE_100mA = 9
    I_RANGE_1A = 10
    I_RANGE_BOOSTER = 11
    I_RANGE_AUTO = 12


class E_RANGE(IntEnum):
    E_RANGE_2_5V = 0
    E_RANGE_5V = 1
    E_RANGE_10V = 2
    E_RANGE_AUTO = 3


class BANDWIDTH(IntEnum):
    BW_1 = 1
    BW_2 = 2
    BW_3 = 3
    BW_4 = 4
    BW_5 = 5
    BW_6 = 6
    BW_7 = 7
    BW_8 = 8
    BW_9 = 9


class TECH_ID(IntEnum):
    """Only the identifiers this driver loads or decodes. PDF §5."""

    NONE = 0
    OCV = 100
    CA = 101
    CP = 102
    CV = 103
    PEIS = 104
    GEIS = 107
    SPEIS = 113
    SGEIS = 114
    LOOP = 150
    TO = 151
    TI = 152
    TOS = 153
    CPLIMIT = 155
    CALIMIT = 157


class BoardFamily(Enum):
    """Which record layout a channel's board uses. PDF §7 splits every data
    format table into "VMP3 series" and "VMP-300 series"."""

    VMP3 = "VMP3"
    VMP300 = "VMP-300"


#: Board type -> (`.ecc` filename suffix, record layout family).
#:
#: One mapping, because the two must never disagree: the suffix decides which
#: technique encoding the firmware is handed, and the family decides how its
#: records are decoded. easy-biologic keys the layout off the *chassis* device
#: code while the encoding follows the channel board, which in a mixed-board
#: chassis decodes a record against the wrong column count.
_BOARD: dict[BOARD_TYPE, tuple[str, BoardFamily]] = {
    BOARD_TYPE.ESSENTIAL: ("", BoardFamily.VMP3),
    BOARD_TYPE.PREMIUM: ("4", BoardFamily.VMP300),
    BOARD_TYPE.DIGICORE: ("5", BoardFamily.VMP300),
}

#: Board type -> (kernel blob, FPGA blob). DIGICORE takes no FPGA file.
_FIRMWARE: dict[BOARD_TYPE, tuple[str, str]] = {
    BOARD_TYPE.ESSENTIAL: ("kernel.bin", "Vmp_ii_0437_a6.xlx"),
    BOARD_TYPE.PREMIUM: ("kernel4.bin", "vmp_iv_0395_aa.xlx"),
    BOARD_TYPE.DIGICORE: ("kernel.bin", ""),
}

#: Vendor error code -> name. The *name* is what a log line needs: -9 meaning
#: "EC-Lab is running and holding the instrument" is a different action from -1
#: meaning "not connected", and a bare negative number distinguishes neither.
#:
#: Transcribed from PDF §5.4. The families are NOT contiguous hundreds blocks
#: in the order you'd guess: general is -1..-15, instrument is -101..-105,
#: and only then do communication (-200..-207), firmware (-300..-309) and
#: technique (-400..-405) start. ``ERR_GEN_NOCHANNELELECTED`` (missing the S)
#: is the vendor's own typo, reproduced as printed.
ERROR_NAMES: dict[int, str] = {
    0: "ERR_NOERROR",
    -1: "ERR_GEN_NOTCONNECTED",
    -2: "ERR_GEN_CONNECTIONINPROGRESS",
    -3: "ERR_GEN_CHANNELNOTPLUGGED",
    -4: "ERR_GEN_INVALIDPARAMETERS",
    -5: "ERR_GEN_FILENOTEXISTS",
    -6: "ERR_GEN_FUNCTIONFAILED",
    -7: "ERR_GEN_NOCHANNELELECTED",
    -8: "ERR_GEN_INVALIDCONF",
    -9: "ERR_GEN_ECLAB_LOADED",
    -10: "ERR_GEN_LIBNOTCORRECTLYLOADED",
    -11: "ERR_GEN_USBLIBRARYERROR",
    -12: "ERR_GEN_FUNCTIONINPROGRESS",
    -13: "ERR_GEN_CHANNEL_RUNNING",
    -14: "ERR_GEN_DEVICE_NOTALLOWED",
    -15: "ERR_GEN_UPDATEPARAMETERS",
    -101: "ERR_INSTR_VMEERROR",
    -102: "ERR_INSTR_TOOMANYDATA",
    -103: "ERR_INSTR_RESPNOTPOSSIBLE",
    -104: "ERR_INSTR_RESPERROR",
    -105: "ERR_INSTR_MSGSIZEERROR",
    -200: "ERR_COMM_COMMFAILED",
    -201: "ERR_COMM_CONNECTIONFAILED",
    -202: "ERR_COMM_WAITINGACK",
    -203: "ERR_COMM_INVALIDIPADDRESS",
    -204: "ERR_COMM_ALLOCMEMFAILED",
    -205: "ERR_COMM_LOADFIRMWAREFAILED",
    -206: "ERR_COMM_INCOMPATIBLESERVER",
    -207: "ERR_COMM_MAXCONNREACHED",
    -300: "ERR_FIRM_FIRMFILENOTEXISTS",
    -301: "ERR_FIRM_FIRMFILEACCESSFAILED",
    -302: "ERR_FIRM_FIRMINVALIDFILE",
    -303: "ERR_FIRM_FIRMLOADINGFAILED",
    -304: "ERR_FIRM_XILFILENOTEXISTS",
    -305: "ERR_FIRM_XILFILEACCESSFAILED",
    -306: "ERR_FIRM_XILINVALIDFILE",
    -307: "ERR_FIRM_XILLOADINGFAILED",
    -308: "ERR_FIRM_FIRMWARENOTLOADED",
    -309: "ERR_FIRM_FIRMWAREINCOMPATIBLE",
    -400: "ERR_TECH_ECCFILENOTEXISTS",
    -401: "ERR_TECH_INCOMPATIBLEECC",
    -402: "ERR_TECH_ECCFILECORRUPTED",
    -403: "ERR_TECH_LOADTECHNIQUEFAILED",
    -404: "ERR_TECH_DATACORRUPTED",
    -405: "ERR_TECH_MEMFULL",
}

#: Export name -> (argtypes, [restype]). Absent restype means the call returns
#: an int error code that the client checks.
#:
#: `blfind64.dll` is deliberately absent: device discovery is the module that
#: makes the vendor layer unimportable off-Windows, and every station config
#: names an explicit IP.
ECL_API: list[tuple[str, list[Any], ...]] = [
    ("BL_GetLibVersion", [c_char_p, c_uint32_p]),
    ("BL_Connect", [c_char_p, c_uint8, c_int32_p, DEVICE_INFO]),
    ("BL_Disconnect", [c_int32]),
    ("BL_TestConnection", [c_int32]),
    ("BL_GetChannelsPlugged", [c_int32, ChannelsArray, c_uint8]),
    (
        "BL_LoadFirmware",
        [
            c_int32,
            ChannelsArray,
            ResultsArray,
            c_uint8,
            c_bool,
            c_bool,
            c_char_p,
            c_char_p,
        ],
    ),
    ("BL_GetChannelInfos", [c_int32, c_uint8, CH_INFO]),
    ("BL_GetChannelBoardType", [c_int32, c_uint8, c_uint32_p]),
    ("BL_GetErrorMsg", [c_int32, c_char_p, c_uint32_p]),
    ("BL_GetMessage", [c_int32, c_uint8, c_char_p, c_uint32_p]),
    (
        "BL_LoadTechnique",
        [c_int32, c_uint8, c_char_p, EccParams, c_bool, c_bool, c_bool],
    ),
    ("BL_DefineBoolParameter", [c_char_p, c_bool, c_int32, ECC_PARM]),
    ("BL_DefineSglParameter", [c_char_p, c_float, c_int32, ECC_PARM]),
    ("BL_DefineIntParameter", [c_char_p, c_int32, c_int32, ECC_PARM]),
    ("BL_UpdateParameters", [c_int32, c_int8, c_int32, ECC_PARMS, c_char_p]),
    ("BL_GetTechniqueInfos", [c_int32, c_int8, c_int32, TECHNIQUE_INFOS]),
    ("BL_GetParamInfos", [c_int32, c_int8, c_int32, TECHNIQUE_INFOS]),
    ("BL_StartChannel", [c_int32, c_int8]),
    ("BL_StopChannel", [c_int32, c_int8]),
    ("BL_GetCurrentValues", [c_int32, c_int8, CURRENT_VALUES]),
    ("BL_GetData", [c_int32, c_int8, DataBuffer, DATA_INFO, CURRENT_VALUES]),
    ("BL_ConvertNumericIntoSingle", [c_uint32, c_float_p]),
    ("BL_ConvertChannelNumericIntoSingle", [c_uint32, c_float_p, c_uint32]),
    (
        "BL_ConvertTimeChannelNumericIntoSeconds",
        [c_uint32_p, c_double_p, c_float, c_uint32],
    ),
]


def ecc_file(stem: str, board_type: int) -> str:
    """The `.ecc` filename for a technique on a given board.

    ``ca`` becomes ``ca.ecc`` / ``ca4.ecc`` / ``ca5.ecc``. The suffix is the
    board's, never a pinned SDK version -- easy-biologic instead selects from a
    vendored `techniques-6.08` set regardless of what the channel reports.
    """
    try:
        suffix, _ = _BOARD[BOARD_TYPE(board_type)]
    except (KeyError, ValueError):
        raise VendorError(f"unsupported board type {board_type!r} for .ecc selection")
    return f"{stem}{suffix}.ecc"


def firmware_assets(board_type: int) -> tuple[str, str]:
    """``(kernel blob, FPGA blob)`` for a board. The FPGA name is ``""`` on
    DIGICORE, which takes none."""
    try:
        return _FIRMWARE[BOARD_TYPE(board_type)]
    except (KeyError, ValueError):
        raise VendorError(f"unsupported board type {board_type!r} for firmware")


def board_family(board_type: int) -> BoardFamily:
    """Which record-layout family a board's data must be decoded against."""
    try:
        _, family = _BOARD[BOARD_TYPE(board_type)]
    except (KeyError, ValueError):
        raise VendorError(f"unsupported board type {board_type!r} for record layout")
    return family


def load_dll(sdk_path: str = DEFAULT_SDK_PATH) -> Any:
    """Load ``EClib64.dll`` from an SDK install and bind every export.

    Raises `VendorError` naming the path, because "the DLL is not where the
    config says" and "the DLL is there but is 32-bit" need different fixes and
    ctypes distinguishes them only by `winerror`.
    """
    dll_path = os.path.join(sdk_path, DLL_NAME)
    if not os.path.isfile(dll_path):
        raise VendorError(f"{DLL_NAME} not found under sdk_path {sdk_path!r}")
    try:
        dll = ctypes.WinDLL(dll_path)  # type: ignore[attr-defined]
    except OSError as exc:
        if getattr(exc, "winerror", None) == 193:
            raise VendorError(f"{dll_path} is 32-bit; this Python is 64-bit")
        raise VendorError(f"could not load {dll_path}: {exc}")
    for name, argtypes, *rest in ECL_API:
        try:
            function = dll[name]
        except AttributeError:
            raise VendorError(f"{DLL_NAME} at {sdk_path!r} has no export {name}")
        function.argtypes = argtypes
        function.restype = rest[0] if rest else c_int32
    return dll
