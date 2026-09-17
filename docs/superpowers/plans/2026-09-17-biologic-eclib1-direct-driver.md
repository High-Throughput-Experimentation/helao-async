# BioLogic EClib1 Direct Driver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `eclib` BioLogic backend's easy-biologic dependency with a driver that calls the EC-Lab Development Package (EClib1) DLL directly, in place, adding four techniques and a linked-technique plan endpoint.

**Architecture:** Seven modules under the existing `helao/deploy/hte/drivers/pstat/biologic/`, mirroring the proven `biologic_eclib2/` split: `vendor.py` (ctypes ABI + structs + enums + asset resolution), `enum.py` (string aliases → vendor ints), `sim.py` (fake DLL), `eclib_client.py` (serialized gateway), `data.py` (record unpacking), `technique.py` (ECC parameter tables + plans), `driver.py` (single-channel `HelaoDriver`). The package path, the `BiologicDriver` class name and the `pstat_backend: eclib` key are all preserved, so no station config changes.

**Tech Stack:** Python 3.14, `ctypes` (`WinDLL`), pytest, `numpy`/`pandas` (already used by the driver), the `helao` conda env.

**Spec:** `docs/superpowers/specs/2026-09-17-biologic-eclib1-direct-driver-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- **Run Python through the `helao` conda env**, not OS python. For single test files: `conda run -n helao python -m pytest <file> -v`. For the whole hexagon suite, run **per file** with `timeout` and **without** `conda run` (it buffers output and the suite hangs as one session).
- **`black` (line length 88, default settings) on every changed file immediately before `git add`.**
- **pyright (`pyrightconfig.json`, basic) is authoritative.** Baseline on `biologic_server.py` plus the driver files is **40 errors** today, all pre-existing Optional-narrowing and dynamic `ActionHost` attributes. Measure against 40, not 0. Do not remove `# type: ignore` directives.
- **No vendor assets enter the repo.** No `.ecc`, no `kernel*.bin`, no `*.xlx`, no `EClib64.dll`, and no file copied from `Examples/Python/kbio/` — every one carries the BioLogic OEM Package licence header and this repo is a public remote. Write the binding from the ABI table and the PDF.
- **`sdk_path`** is a server config param; default `C:\EC-Lab Development Package\lib`.
- **The DLL's channel index is 0-based.** BioLogic's own `kbio` wrappers pass `ch - 1`, which is *kbio's* 1-based sugar, not the DLL's convention. `easy_biologic` passes `ch` straight through as `c_uint8(ch)`, and HELAO's `channel` action param defaults to `0`. Pass `channel` through unmodified. Copying kbio's `- 1` drives the wrong channel and nothing reports a fault.
- **Emitted columns are frozen** for OCV, CA, CP, CV, PEIS, GEIS, CAOCV: DC is `{t_s, Ewe_V, I_A, P_W, cycle}`, EIS is the 16-name set in `test_biologic_column_contract.py`. The `_`-prefixed `CurrentValues` columns keep today's membership.
- **Never name the private deployments** in tracked files; say "private deployments".
- **Do not commit while a sibling agent is running**, and re-check `git status --short --branch` immediately before every `git add` — `/mnt/STORAGE/repos/helao/helao-async` and `/home/dan/repos/helao-async` are the same checkout.

---

## Prerequisites — station work, not executor work

These cannot be done by an implementing agent and **must** be complete before Task 16 lands.

- [ ] **P1: Capture the runtime golden with the CURRENT driver, at the station.** Run `helao/hexagon/tests/smoke/biologic_diff.bat` against a dummy cell or calibration resistor on a BioLogic station, with that station's real `address`/`num_channels`. Archive the capture. Once easy-biologic is deleted this reference is unobtainable, and the rewrite would then have only its own assertions to agree with.
- [ ] **P2: Record which board family the gate station reports.** `BL_GetChannelBoardType` → `ESSENTIAL` (VMP3-series layouts) or `PREMIUM`/`DIGICORE` (VMP-300-series layouts). The other family's tables will be asserted against the PDF and `BL_GetParamInfos` but not against a record; note which one that is.
- [ ] **P3: Cut a freeze branch from `unstable`** before the merge. Rollback is a revert of the merge commit; there is no config key to flip back.

---

## File Structure

| file | responsibility | task |
|---|---|---|
| `helao/deploy/hte/drivers/pstat/biologic/vendor.py` | `WinDLL` load from `sdk_path`; ctypes structs, ABI signature table, vendor int enums, error-code names, board-type → `.ecc`/firmware asset resolution | 1 |
| `helao/deploy/hte/drivers/pstat/biologic/enum.py` | `EC_IRange`/`EC_ERange`/`EC_Bandwidth` string aliases → vendor ints (rewritten, hermetic) | 2 |
| `helao/deploy/hte/drivers/pstat/biologic/sim.py` | Fake DLL at the `vendor` boundary | 3 |
| `helao/deploy/hte/drivers/pstat/biologic/eclib_client.py` | Single-worker-thread serialized gateway; `EclibError` carrying the vendor code's name | 4 |
| `helao/deploy/hte/drivers/pstat/biologic/data.py` | Layout tables per `(technique, board_family, process_index)`; conversions; derived columns; done-detection | 5, 6 |
| `helao/deploy/hte/drivers/pstat/biologic/technique.py` | `BiologicTechnique`, ECC parameter tables, column plans, `BIOTECHS`, TTL bracketing, plan/LOOP assembly | 7–12 |
| `helao/deploy/hte/drivers/pstat/biologic/driver.py` | `BiologicDriver(HelaoDriver)`, single channel | 13, 14 |
| `helao/deploy/hte/servers/action/biologic_server.py` | 4 new endpoints, `run_plan` guard widening | 15 |
| `helao_dev_{win,linux}-64.yml` | easy-biologic dependency removal | 16 |

Deleted in Task 16: nothing — `driver.py`, `technique.py` and `enum.py` are rewritten in place, so their paths and importers are unchanged.

---

### Task 1: `vendor.py` — ctypes ABI, structs, vendor enums, asset resolution

**Files:**
- Create: `helao/deploy/hte/drivers/pstat/biologic/vendor.py`
- Test: `helao/hexagon/tests/test_biologic_vendor.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `DeviceInfo`, `ChannelInfo`, `CurrentValues`, `DataInfo`, `EccParam`, `EccParams`, `TechniqueInfos`, `DataBuffer`, `ChannelsArray`, `ResultsArray` (ctypes); `ECL_API: list[tuple[str, list, ...]]`; `I_RANGE`, `E_RANGE`, `BANDWIDTH`, `BOARD_TYPE`, `PROG_STATE`, `TECH_ID` (`IntEnum`); `ERROR_NAMES: dict[int, str]`; `load_dll(sdk_path) -> ctypes.WinDLL`; `ecc_file(stem, board_type) -> str`; `firmware_assets(board_type) -> tuple[str, str]`; `BoardFamily` with `.VMP3`/`.VMP300` and `board_family(board_type) -> BoardFamily`.

- [ ] **Step 1: Write the failing test**

```python
"""`vendor` is the ABI, transcribed from the PDF and the DLL's export table.

Nothing here is copied from the OEM package's own Python examples; the
licence header on every one of those files forbids it in a public repo.
"""

import ctypes

import pytest

from helao.deploy.hte.drivers.pstat.biologic import vendor


def test_ecc_param_is_76_bytes_with_a_64_byte_label():
    assert ctypes.sizeof(vendor.EccParam) == 76
    assert dict(vendor.EccParam._fields_)["ParamStr"]._length_ == 64


def test_data_info_is_packed_to_4_and_carries_the_fields_unpacking_needs():
    assert vendor.DataInfo._pack_ == 4
    names = [name for name, _ in vendor.DataInfo._fields_]
    assert names == [
        "IRQskipped",
        "NbRows",
        "NbCols",
        "TechniqueIndex",
        "TechniqueID",
        "ProcessIndex",
        "loop",
        "StartTime",
        "MuxPad",
    ]


def test_data_buffer_is_1000_words():
    assert ctypes.sizeof(vendor.DataBuffer) == 1000 * 4


def test_current_values_carries_timebase_and_state():
    names = [name for name, _ in vendor.CurrentValues._fields_]
    assert names[:3] == ["State", "MemFilled", "TimeBase"]
    assert "IRange" in names


def test_prog_state_values_are_the_documented_ones():
    assert (vendor.PROG_STATE.STOP, vendor.PROG_STATE.RUN) == (0, 1)
    assert (vendor.PROG_STATE.PAUSE, vendor.PROG_STATE.SYNC) == (2, 3)


def test_i_range_keep_is_negative_one_and_auto_is_twelve():
    assert vendor.I_RANGE.I_RANGE_KEEP == -1
    assert vendor.I_RANGE.I_RANGE_100pA == 0
    assert vendor.I_RANGE.I_RANGE_1A == 10
    assert vendor.I_RANGE.I_RANGE_BOOSTER == 11
    assert vendor.I_RANGE.I_RANGE_AUTO == 12


def test_e_range_and_bandwidth_values():
    assert vendor.E_RANGE.E_RANGE_2_5V == 0
    assert vendor.E_RANGE.E_RANGE_AUTO == 3
    assert vendor.BANDWIDTH.BW_1 == 1
    assert vendor.BANDWIDTH.BW_9 == 9


def test_technique_ids_match_the_pdf():
    assert vendor.TECH_ID.OCV == 100
    assert vendor.TECH_ID.CA == 101
    assert vendor.TECH_ID.CP == 102
    assert vendor.TECH_ID.CV == 103
    assert vendor.TECH_ID.PEIS == 104
    assert vendor.TECH_ID.GEIS == 107
    assert vendor.TECH_ID.SPEIS == 113
    assert vendor.TECH_ID.SGEIS == 114
    assert vendor.TECH_ID.LOOP == 150
    assert vendor.TECH_ID.TO == 151
    assert vendor.TECH_ID.TI == 152
    assert vendor.TECH_ID.CPLIMIT == 155
    assert vendor.TECH_ID.CALIMIT == 157


@pytest.mark.parametrize(
    "board_type,stem,expected",
    [
        (vendor.BOARD_TYPE.ESSENTIAL, "ca", "ca.ecc"),
        (vendor.BOARD_TYPE.PREMIUM, "ca", "ca4.ecc"),
        (vendor.BOARD_TYPE.DIGICORE, "ca", "ca5.ecc"),
        (vendor.BOARD_TYPE.ESSENTIAL, "peis", "peis.ecc"),
        (vendor.BOARD_TYPE.PREMIUM, "seisp", "seisp4.ecc"),
        (vendor.BOARD_TYPE.DIGICORE, "TI", "TI5.ecc"),
    ],
)
def test_ecc_file_suffix_follows_board_type(board_type, stem, expected):
    assert vendor.ecc_file(stem, board_type) == expected


def test_ecc_file_refuses_an_unknown_board_type():
    with pytest.raises(vendor.VendorError, match="board type"):
        vendor.ecc_file("ca", vendor.BOARD_TYPE.UNKNOWN)


def test_firmware_assets_are_per_board_type():
    assert vendor.firmware_assets(vendor.BOARD_TYPE.ESSENTIAL) == (
        "kernel.bin",
        "Vmp_ii_0437_a6.xlx",
    )
    assert vendor.firmware_assets(vendor.BOARD_TYPE.PREMIUM) == (
        "kernel4.bin",
        "vmp_iv_0395_aa.xlx",
    )
    assert vendor.firmware_assets(vendor.BOARD_TYPE.DIGICORE) == ("kernel.bin", "")


def test_board_family_groups_premium_and_digicore_together():
    assert vendor.board_family(vendor.BOARD_TYPE.ESSENTIAL) is vendor.BoardFamily.VMP3
    assert vendor.board_family(vendor.BOARD_TYPE.PREMIUM) is vendor.BoardFamily.VMP300
    assert vendor.board_family(vendor.BOARD_TYPE.DIGICORE) is vendor.BoardFamily.VMP300


def test_the_api_table_covers_every_call_the_client_makes():
    names = {name for name, *_ in vendor.ECL_API}
    assert {
        "BL_Connect",
        "BL_Disconnect",
        "BL_TestConnection",
        "BL_GetChannelInfos",
        "BL_GetChannelBoardType",
        "BL_LoadFirmware",
        "BL_LoadTechnique",
        "BL_DefineBoolParameter",
        "BL_DefineSglParameter",
        "BL_DefineIntParameter",
        "BL_UpdateParameters",
        "BL_GetTechniqueInfos",
        "BL_GetParamInfos",
        "BL_StartChannel",
        "BL_StopChannel",
        "BL_GetData",
        "BL_GetCurrentValues",
        "BL_GetMessage",
        "BL_GetErrorMsg",
        "BL_ConvertChannelNumericIntoSingle",
        "BL_ConvertTimeChannelNumericIntoSeconds",
    } <= names


def test_blfind_is_not_in_the_api_table():
    """Discovery is what makes the vendor layer unimportable off-Windows, and
    every station config names an explicit IP."""
    names = {name for name, *_ in vendor.ECL_API}
    assert not any(name.startswith("BL_FindEChem") for name in names)


def test_error_names_cover_the_codes_the_driver_branches_on():
    assert vendor.ERROR_NAMES[0] == "ERR_NOERROR"
    assert vendor.ERROR_NAMES[-1] == "ERR_GEN_NOTCONNECTED"
    assert vendor.ERROR_NAMES[-2] == "ERR_GEN_CONNECTIONINPROGRESS"
    assert vendor.ERROR_NAMES[-9] == "ERR_GEN_ECLAB_LOADED"


def test_import_loads_no_dll():
    """`biologic_server.py` imports this module on Linux."""
    import sys

    assert "helao.deploy.hte.drivers.pstat.biologic.vendor" in sys.modules
    assert vendor.load_dll.__module__ == vendor.__name__


def test_load_dll_reports_the_path_it_could_not_find(tmp_path):
    with pytest.raises(vendor.VendorError, match=str(tmp_path)):
        vendor.load_dll(str(tmp_path))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_vendor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.deploy.hte.drivers.pstat.biologic.vendor'`

- [ ] **Step 3: Write minimal implementation**

```python
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
ERROR_NAMES: dict[int, str] = {
    0: "ERR_NOERROR",
    -1: "ERR_GEN_NOTCONNECTED",
    -2: "ERR_GEN_CONNECTIONINPROGRESS",
    -3: "ERR_GEN_CHANNELNOTPLUGGED",
    -4: "ERR_GEN_INVALIDPARAMETERS",
    -5: "ERR_GEN_FILENOTEXISTS",
    -6: "ERR_GEN_FUNCTIONFAILED",
    -7: "ERR_GEN_NOCHANNELSELECTED",
    -8: "ERR_GEN_INVALIDCONF",
    -9: "ERR_GEN_ECLAB_LOADED",
    -10: "ERR_GEN_LIBNOTCORRECTLYLOADED",
    -11: "ERR_GEN_USBLIBRARYERROR",
    -12: "ERR_GEN_FUNCTIONINPROGRESS",
    -13: "ERR_GEN_CHANNEL_RUNNING",
    -14: "ERR_GEN_TOO_FAST_FOR_HARDWARE",
    -15: "ERR_GEN_CHANNEL_NOT_PLUGGED",
    -101: "ERR_COMM_COMMFAILED",
    -102: "ERR_COMM_CONNECTIONFAILED",
    -103: "ERR_COMM_WAITINGACK",
    -104: "ERR_COMM_INVALIDIPADDRESS",
    -105: "ERR_COMM_ALLOCMEMFAILED",
    -106: "ERR_COMM_LOADFIRMWAREFAILED",
    -107: "ERR_COMM_INCOMPATIBLESERVER",
    -108: "ERR_COMM_MAXCONNREACHED",
    -200: "ERR_FIRM_FIRMFILENOTEXISTS",
    -201: "ERR_FIRM_FIRMFILEACCESSFAILED",
    -202: "ERR_FIRM_FIRMINVALIDFILE",
    -203: "ERR_FIRM_FIRMLOADINGFAILED",
    -204: "ERR_FIRM_XILFILENOTEXISTS",
    -205: "ERR_FIRM_XILFILEACCESSFAILED",
    -206: "ERR_FIRM_XILINVALIDFILE",
    -207: "ERR_FIRM_XILLOADINGFAILED",
    -208: "ERR_FIRM_FIRMWARENOTCOMPATIBLE",
    -300: "ERR_TECH_ECCFILENOTEXISTS",
    -301: "ERR_TECH_INCOMPATIBLEECC",
    -302: "ERR_TECH_ECCFILECORRUPTED",
    -303: "ERR_TECH_LOADTECHNIQUEFAILED",
    -304: "ERR_TECH_DATACORRUPTED",
    -305: "ERR_TECH_MEMFULL",
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
    ("BL_LoadTechnique", [c_int32, c_uint8, c_char_p, EccParams, c_bool, c_bool, c_bool]),
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_vendor.py -v`
Expected: PASS (24 tests). `test_load_dll_reports_the_path_it_could_not_find` passes on Linux because the `isfile` check fires before `WinDLL` is touched.

- [ ] **Step 5: Verify the error-code table against the PDF**

Run: `pdftotext -layout "/mnt/k/experiments/eche/Installation packages/EC-Lab Development Package/EC-Lab Development Package.pdf" - | grep -n "ERR_GEN\|ERR_COMM\|ERR_FIRM\|ERR_TECH"`
Expected: every name/value pair in `ERROR_NAMES` appears with the same number. Fix any mismatch in `vendor.py` and add the corrected pair to `test_error_names_cover_the_codes_the_driver_branches_on`. The PDF is the only source here — a wrong code name misdirects the next person reading a log.

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/pstat/biologic/vendor.py helao/hexagon/tests/test_biologic_vendor.py
git status --short --branch
git add helao/deploy/hte/drivers/pstat/biologic/vendor.py helao/hexagon/tests/test_biologic_vendor.py
git commit -m "feat(biologic): transcribe the EClib1 ABI, structs and asset tables

Board type drives both the .ecc suffix and the record layout from one
mapping, so the encoding handed to the firmware and the decoding applied to
its records cannot disagree.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `enum.py` — string aliases to vendor ints, hermetically

**Files:**
- Modify (rewrite): `helao/deploy/hte/drivers/pstat/biologic/enum.py`
- Test: `helao/hexagon/tests/test_biologic_enum.py`

**Interfaces:**
- Consumes: `vendor.I_RANGE`, `vendor.E_RANGE`, `vendor.BANDWIDTH` from Task 1.
- Produces: `EC_IRange`, `EC_ERange`, `EC_Bandwidth` (`StrEnum`, members unchanged from today); `ec_irange(value) -> int`, `ec_erange(value) -> int`, `ec_bandwidth(value) -> int`.

The three `StrEnum` classes are annotations on `biologic_server.py`'s endpoint signatures, so **their member names and string values must not change** — an edit there changes the recorded `action_params` and the OpenAPI surface. Only the resolvers change: they returned an `easy_biologic.lib.ec_lib` enum *member* and now return a plain `int`.

The values are identical numbers. `easy_biologic.lib.ec_lib.IRange` is `p100=0 … a1=10, KEEP=-1, BOOSTER=11, AUTO=12`, matching `vendor.I_RANGE`; `ERange` is `v2_5=0 … AUTO=3`; `Bandwidth` is `BW1..BW9 = 1..9`. So this is behaviour-preserving, and the test pins that by number rather than by round-trip.

- [ ] **Step 1: Write the failing test**

```python
"""The string aliases keep their spelling; only what they resolve to changes.

`EC_IRange`/`EC_ERange`/`EC_Bandwidth` are FastAPI annotations on the
`run_*` endpoints, so a renamed member changes the recorded action params and
the OpenAPI surface that `test_hte_route_checklist.py` freezes.
"""

import sys

import pytest

from helao.deploy.hte.drivers.pstat.biologic import vendor
from helao.deploy.hte.drivers.pstat.biologic.enum import (
    EC_Bandwidth,
    EC_ERange,
    EC_IRange,
    ec_bandwidth,
    ec_erange,
    ec_irange,
)


def test_the_irange_members_are_exactly_the_ones_the_endpoints_annotate():
    assert [m.value for m in EC_IRange] == [
        "p100", "n1", "n10", "n100", "u1", "u10", "u100",
        "m1", "m10", "m100", "a1", "KEEP", "BOOSTER", "AUTO",
    ]


def test_the_erange_and_bandwidth_members_are_unchanged():
    assert [m.value for m in EC_ERange] == ["v2_5", "v5", "v10", "AUTO"]
    assert [m.value for m in EC_Bandwidth] == [f"BW{i}" for i in range(1, 10)]


@pytest.mark.parametrize(
    "alias,expected",
    [
        ("p100", 0), ("n1", 1), ("n10", 2), ("n100", 3),
        ("u1", 4), ("u10", 5), ("u100", 6), ("m1", 7),
        ("m10", 8), ("m100", 9), ("a1", 10),
        ("KEEP", -1), ("BOOSTER", 11), ("AUTO", 12),
    ],
)
def test_irange_resolves_to_the_same_int_easy_biologic_sent(alias, expected):
    """Pinned by number, not by round-trip: these are the values four stations'
    recorded data was produced with."""
    assert ec_irange(alias) == expected
    assert ec_irange(EC_IRange(alias)) == expected


@pytest.mark.parametrize(
    "alias,expected", [("v2_5", 0), ("v5", 1), ("v10", 2), ("AUTO", 3)]
)
def test_erange_resolves_to_the_same_int(alias, expected):
    assert ec_erange(alias) == expected


@pytest.mark.parametrize("n", range(1, 10))
def test_bandwidth_resolves_to_its_own_number(n):
    assert ec_bandwidth(f"BW{n}") == n


def test_resolvers_return_plain_ints_not_enum_members():
    """`technique.py` puts these straight into an int ECC parameter."""
    assert type(ec_irange("AUTO")) is int
    assert type(ec_erange("AUTO")) is int
    assert type(ec_bandwidth("BW4")) is int


def test_every_resolved_value_is_a_real_vendor_enum_member():
    for member in EC_IRange:
        assert vendor.I_RANGE(ec_irange(member)) is not None
    for member in EC_ERange:
        assert vendor.E_RANGE(ec_erange(member)) is not None
    for member in EC_Bandwidth:
        assert vendor.BANDWIDTH(ec_bandwidth(member)) is not None


def test_an_unknown_alias_raises_rather_than_defaulting():
    with pytest.raises(ValueError):
        ec_irange("m1000")


def test_the_module_no_longer_touches_easy_biologic():
    assert "easy_biologic" not in sys.modules
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_enum.py -v`
Expected: FAIL — `ImportError: cannot import name 'ec_irange'` resolves, but `test_resolvers_return_plain_ints_not_enum_members` fails with `ModuleNotFoundError: No module named 'easy_biologic'` raised from the old `_ec_lib()`.

- [ ] **Step 3: Write minimal implementation**

Keep the three `StrEnum` classes and their docstrings exactly as they are today. Replace everything from `def _ec_lib():` to the end of the file with:

```python
#: Alias -> vendor int. Spelled out rather than derived by `getattr` on a
#: vendor enum, because these numbers are the contract: they are what four
#: stations' recorded data was produced with, and a table can be diffed
#: against the PDF while a `getattr` cannot.
_IRANGE: dict[str, int] = {
    "p100": vendor.I_RANGE.I_RANGE_100pA,
    "n1": vendor.I_RANGE.I_RANGE_1nA,
    "n10": vendor.I_RANGE.I_RANGE_10nA,
    "n100": vendor.I_RANGE.I_RANGE_100nA,
    "u1": vendor.I_RANGE.I_RANGE_1uA,
    "u10": vendor.I_RANGE.I_RANGE_10uA,
    "u100": vendor.I_RANGE.I_RANGE_100uA,
    "m1": vendor.I_RANGE.I_RANGE_1mA,
    "m10": vendor.I_RANGE.I_RANGE_10mA,
    "m100": vendor.I_RANGE.I_RANGE_100mA,
    "a1": vendor.I_RANGE.I_RANGE_1A,
    "KEEP": vendor.I_RANGE.I_RANGE_KEEP,
    "BOOSTER": vendor.I_RANGE.I_RANGE_BOOSTER,
    "AUTO": vendor.I_RANGE.I_RANGE_AUTO,
}

_ERANGE: dict[str, int] = {
    "v2_5": vendor.E_RANGE.E_RANGE_2_5V,
    "v5": vendor.E_RANGE.E_RANGE_5V,
    "v10": vendor.E_RANGE.E_RANGE_10V,
    "AUTO": vendor.E_RANGE.E_RANGE_AUTO,
}

_BANDWIDTH: dict[str, int] = {
    f"BW{n}": vendor.BANDWIDTH(n) for n in range(1, 10)
}


def ec_irange(value) -> int:
    """The vendor current-range int for a string alias or ``EC_IRange``."""
    return int(_IRANGE[EC_IRange(value).value])


def ec_erange(value) -> int:
    """The vendor voltage-range int for a string alias or ``EC_ERange``."""
    return int(_ERANGE[EC_ERange(value).value])


def ec_bandwidth(value) -> int:
    """The vendor bandwidth int for a string alias or ``EC_Bandwidth``."""
    return int(_BANDWIDTH[EC_Bandwidth(value).value])
```

Replace the module docstring's second paragraph — the one explaining the lazy vendor import — with:

```python
"""String enums for Biologic IRange / ERange / Bandwidth, and their integer
values.

The aliases are what an action records and what the ``run_*`` endpoints
annotate, so their spellings are a contract; the integers are what
``BL_DefineIntParameter`` receives. Both live here so a reader can check one
against the other, and so nothing else in the driver has to know that
``"m1"`` means 7.

This module is hermetic. It used to lazy-import ``easy_biologic.lib.ec_lib``
just to map each alias onto a vendor member spelled identically, with the
import deferred because ``biologic_server.py`` imports this module on stations
that have EC-Lab but not easy-biologic. With the numbers held here there is
nothing to defer.
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_enum.py -v`
Expected: PASS (26 tests).

- [ ] **Step 5: Confirm nothing else imported the old resolvers' return type**

Run: `grep -rn "ec_irange\|ec_erange\|ec_bandwidth" helao/ | grep -v "drivers/pstat/biologic/enum.py" | grep -v tests`
Expected: only `helao/deploy/hte/drivers/pstat/biologic/driver.py` (its `coercers` dict), which Task 14 rewrites. If anything else appears, it was relying on an `easy_biologic` enum member and needs the same int treatment — add it to this task.

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/pstat/biologic/enum.py helao/hexagon/tests/test_biologic_enum.py
git status --short --branch
git add helao/deploy/hte/drivers/pstat/biologic/enum.py helao/hexagon/tests/test_biologic_enum.py
git commit -m "refactor(biologic): resolve range aliases to ints, not vendor enum members

Same numbers, so recorded data is unaffected; the module stops importing
easy_biologic at all, which is what the lazy import existed to defer.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `sim.py` — a fake DLL at the vendor boundary

**Files:**
- Create: `helao/deploy/hte/drivers/pstat/biologic/sim.py`
- Test: `helao/hexagon/tests/test_biologic_sim.py`

**Interfaces:**
- Consumes: every struct and enum from `vendor` (Task 1).
- Produces: `FakeDll` with `__getitem__(name) -> Callable`, matching what `vendor.load_dll` returns so `eclib_client` cannot tell them apart; `SimConfig(rows_per_poll: int = 4, polls_until_stop: int = 3, board_type: int = vendor.BOARD_TYPE.PREMIUM, kernel_loaded: bool = True, fail_on: dict[str, int] | None = None)`; `set_sim_config(cfg)`; `load_dll(sdk_path=None) -> FakeDll`.

**It fakes the DLL, not the client.** That keeps the real structs, the real `EccParams` packing and the real `BL_GetData` buffer decode inside the code under test — a simulator one layer up would prove none of them.

**It carries its own column-count table, transcribed independently from PDF §7.** This is deliberate duplication: `data.py`'s layout tables are what is being tested, so if the simulator asked `data.py` how many columns to emit, the two could be wrong together and every decode test would pass. Row *values* are deterministic ramps; the test computes the expected decode itself.

- [ ] **Step 1: Write the failing test**

```python
"""The simulated DLL is faithful about the three things the code above it
gets wrong: it returns error *codes* (it does not raise), it reports
`PROG_STATE.STOP` only after having reported `RUN`, and its per-technique
column count is transcribed from the PDF independently of `data.py`.
"""

import ctypes

import pytest

from helao.deploy.hte.drivers.pstat.biologic import sim, vendor


@pytest.fixture(autouse=True)
def fresh():
    sim.set_sim_config(sim.SimConfig())
    yield
    sim.set_sim_config(sim.SimConfig())


def connect(dll):
    idn = ctypes.c_int32()
    info = vendor.DeviceInfo()
    rc = dll["BL_Connect"](b"192.168.200.100", 5, ctypes.byref(idn), ctypes.byref(info))
    assert rc == 0
    return idn.value, info


def test_load_dll_ignores_sdk_path_and_needs_no_file():
    assert sim.load_dll("/nonexistent") is not None


def test_connect_reports_channels_and_a_firmware_version():
    dll = sim.load_dll()
    _, info = connect(dll)
    assert info.NumberOfChannels >= 1
    assert info.FirmwareVersion > 0


def test_calls_return_error_codes_and_never_raise():
    """The real exports return an int; the client is what raises."""
    dll = sim.load_dll()
    rc = dll["BL_StartChannel"](999, 0)
    assert isinstance(rc, int)
    assert rc != 0


def test_fail_on_forces_a_named_call_to_return_a_chosen_code():
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_LoadTechnique": -300}))
    dll = sim.load_dll()
    idn, _ = connect(dll)
    parms = vendor.EccParams(0, None)
    rc = dll["BL_LoadTechnique"](idn, 0, b"ca4.ecc", parms, True, True, False)
    assert rc == -300


def test_channel_info_reports_the_configured_board_and_kernel_state():
    sim.set_sim_config(
        sim.SimConfig(board_type=vendor.BOARD_TYPE.ESSENTIAL, kernel_loaded=False)
    )
    dll = sim.load_dll()
    idn, _ = connect(dll)
    info = vendor.ChannelInfo()
    assert dll["BL_GetChannelInfos"](idn, 0, ctypes.byref(info)) == 0
    assert info.FirmwareCode == sim.NO_KERNEL_FIRMWARE_CODE
    board = ctypes.c_uint32()
    assert dll["BL_GetChannelBoardType"](idn, 0, ctypes.byref(board)) == 0
    assert board.value == vendor.BOARD_TYPE.ESSENTIAL


def test_a_run_reports_RUN_before_it_reports_STOP():
    """The start race is real: a channel polled between StartChannel and the
    firmware running reads STOP. The simulator must not skip RUN."""
    sim.set_sim_config(sim.SimConfig(polls_until_stop=2))
    dll = sim.load_dll()
    idn, _ = connect(dll)
    parms = vendor.EccParams(0, None)
    assert dll["BL_LoadTechnique"](idn, 0, b"ca4.ecc", parms, True, True, False) == 0
    assert dll["BL_StartChannel"](idn, 0) == 0

    states = []
    for _ in range(5):
        buf, di, cv = vendor.DataBuffer(), vendor.DataInfo(), vendor.CurrentValues()
        assert dll["BL_GetData"](idn, 0, buf, ctypes.byref(di), ctypes.byref(cv)) == 0
        states.append(cv.State)
    assert states[0] == vendor.PROG_STATE.RUN
    assert vendor.PROG_STATE.STOP in states
    assert states.index(vendor.PROG_STATE.STOP) >= 2


def test_get_data_emits_the_pdf_column_count_for_the_loaded_technique():
    sim.set_sim_config(
        sim.SimConfig(board_type=vendor.BOARD_TYPE.PREMIUM, rows_per_poll=3)
    )
    dll = sim.load_dll()
    idn, _ = connect(dll)
    parms = vendor.EccParams(0, None)
    dll["BL_LoadTechnique"](idn, 0, b"ca4.ecc", parms, True, True, False)
    dll["BL_StartChannel"](idn, 0)

    buf, di, cv = vendor.DataBuffer(), vendor.DataInfo(), vendor.CurrentValues()
    dll["BL_GetData"](idn, 0, buf, ctypes.byref(di), ctypes.byref(cv))
    assert di.TechniqueID == vendor.TECH_ID.CA
    assert di.NbRows == 3
    assert di.NbCols == 5  # t_high t_low Ewe I Cycle
    assert di.ProcessIndex == 0


def test_an_eis_run_emits_both_processes_with_their_own_widths():
    sim.set_sim_config(sim.SimConfig(board_type=vendor.BOARD_TYPE.ESSENTIAL))
    dll = sim.load_dll()
    idn, _ = connect(dll)
    parms = vendor.EccParams(0, None)
    dll["BL_LoadTechnique"](idn, 0, b"peis.ecc", parms, True, True, False)
    dll["BL_StartChannel"](idn, 0)

    seen = {}
    for _ in range(6):
        buf, di, cv = vendor.DataBuffer(), vendor.DataInfo(), vendor.CurrentValues()
        dll["BL_GetData"](idn, 0, buf, ctypes.byref(di), ctypes.byref(cv))
        if di.NbRows:
            seen[di.ProcessIndex] = di.NbCols
    assert seen[0] == 4  # t_high t_low Ewe I
    assert seen[1] == 15  # VMP3 carries the trailing Irange


def test_the_buffer_drains_to_zero_rows_after_stop():
    sim.set_sim_config(sim.SimConfig(polls_until_stop=1))
    dll = sim.load_dll()
    idn, _ = connect(dll)
    parms = vendor.EccParams(0, None)
    dll["BL_LoadTechnique"](idn, 0, b"ca4.ecc", parms, True, True, False)
    dll["BL_StartChannel"](idn, 0)

    widths = []
    for _ in range(12):
        buf, di, cv = vendor.DataBuffer(), vendor.DataInfo(), vendor.CurrentValues()
        dll["BL_GetData"](idn, 0, buf, ctypes.byref(di), ctypes.byref(cv))
        widths.append(di.NbRows)
    assert widths[-1] == 0


def test_define_parameter_writes_the_label_and_value_into_the_struct():
    dll = sim.load_dll()
    parm = vendor.EccParam()
    assert dll["BL_DefineSglParameter"](b"Duration_step", 2.5, 0, ctypes.byref(parm)) == 0
    assert bytes(parm.ParamStr).split(b"\x00")[0] == b"Duration_step"
    assert parm.ParamIndex == 0


def test_technique_infos_reports_what_was_loaded_in_order():
    dll = sim.load_dll()
    idn, _ = connect(dll)
    parms = vendor.EccParams(0, None)
    dll["BL_LoadTechnique"](idn, 0, b"TI4.ecc", parms, True, False, False)
    dll["BL_LoadTechnique"](idn, 0, b"ca4.ecc", parms, False, True, False)

    first, second = vendor.TechniqueInfos(), vendor.TechniqueInfos()
    assert dll["BL_GetTechniqueInfos"](idn, 0, 0, ctypes.byref(first)) == 0
    assert dll["BL_GetTechniqueInfos"](idn, 0, 1, ctypes.byref(second)) == 0
    assert first.Id == vendor.TECH_ID.TI
    assert second.Id == vendor.TECH_ID.CA


def test_loading_with_first_true_replaces_the_previous_list():
    """EClib1 has no unload; `first=True` is what clears the channel."""
    dll = sim.load_dll()
    idn, _ = connect(dll)
    parms = vendor.EccParams(0, None)
    dll["BL_LoadTechnique"](idn, 0, b"TI4.ecc", parms, True, False, False)
    dll["BL_LoadTechnique"](idn, 0, b"ocv4.ecc", parms, True, True, False)
    info = vendor.TechniqueInfos()
    dll["BL_GetTechniqueInfos"](idn, 0, 0, ctypes.byref(info))
    assert info.Id == vendor.TECH_ID.OCV


def test_convert_helpers_round_trip_the_ramp_encoding():
    dll = sim.load_dll()
    out = ctypes.c_float()
    word = sim.encode_single(1.25)
    assert dll["BL_ConvertChannelNumericIntoSingle"](word, ctypes.byref(out), 2) == 0
    assert out.value == pytest.approx(1.25, abs=1e-6)


def test_convert_time_uses_the_timebase_and_the_two_words():
    dll = sim.load_dll()
    words = (ctypes.c_uint32 * 2)(0, 1000)
    out = ctypes.c_double()
    assert dll["BL_ConvertTimeChannelNumericIntoSeconds"](
        words, ctypes.byref(out), ctypes.c_float(1e-3), 2
    ) == 0
    assert out.value == pytest.approx(1.0)


def test_get_message_drains_once_then_returns_empty():
    dll = sim.load_dll()
    idn, _ = connect(dll)
    sim.push_message(0, "I_Range out of range, clamped")
    buf = ctypes.create_string_buffer(4096)
    size = ctypes.c_uint32(4096)
    dll["BL_GetMessage"](idn, 0, buf, ctypes.byref(size))
    assert b"clamped" in buf.value
    buf2 = ctypes.create_string_buffer(4096)
    size2 = ctypes.c_uint32(4096)
    dll["BL_GetMessage"](idn, 0, buf2, ctypes.byref(size2))
    assert buf2.value == b""


def test_stop_channel_ends_the_run_immediately():
    dll = sim.load_dll()
    idn, _ = connect(dll)
    parms = vendor.EccParams(0, None)
    dll["BL_LoadTechnique"](idn, 0, b"ca4.ecc", parms, True, True, False)
    dll["BL_StartChannel"](idn, 0)
    assert dll["BL_StopChannel"](idn, 0) == 0
    cv = vendor.CurrentValues()
    dll["BL_GetCurrentValues"](idn, 0, ctypes.byref(cv))
    assert cv.State == vendor.PROG_STATE.STOP


def test_channel_indices_are_zero_based_here_too():
    """If the client ever grew a `- 1`, channel 0 would become -1 and this
    would stop answering."""
    dll = sim.load_dll()
    idn, _ = connect(dll)
    info = vendor.ChannelInfo()
    assert dll["BL_GetChannelInfos"](idn, 0, ctypes.byref(info)) == 0
    assert info.Channel == 0
    assert dll["BL_GetChannelInfos"](idn, -1, ctypes.byref(info)) != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_sim.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.deploy.hte.drivers.pstat.biologic.sim'`

- [ ] **Step 3: Write minimal implementation**

Write `sim.py` with:

- Module docstring stating the three fidelity commitments asserted above (returns codes rather than raising; reports `RUN` before `STOP`; carries its own PDF-transcribed column table so it is an independent witness to `data.py`).
- `encode_single(value: float) -> int` / `decode_single(word: int) -> float`: reinterpret a `c_float` as a `c_uint32` via `ctypes.cast`, so the ramp values the simulator writes are decoded by the *real* conversion path.
- `_COLS: dict[tuple[int, vendor.BoardFamily, int], int]` — transcribed from PDF §7, process index included:
  `(OCV, VMP3, 0): 4`, `(OCV, VMP300, 0): 3`,
  `(CA, *, 0): 5`, `(CP, *, 0): 5`, `(CALIMIT, *, 0): 5`, `(CPLIMIT, *, 0): 5`,
  `(CV, VMP3, 0): 6`, `(CV, VMP300, 0): 5`,
  `(PEIS, *, 0): 4`, `(PEIS, VMP3, 1): 15`, `(PEIS, VMP300, 1): 14`,
  `(GEIS, ...)` same as PEIS,
  `(SPEIS, *, 0): 5`, `(SPEIS, VMP3, 1): 16`, `(SPEIS, VMP300, 1): 15`,
  `(SGEIS, ...)` same as SPEIS.
- `_ECC_TO_TECH: dict[str, int]` mapping an `.ecc` stem (suffix stripped) to a `vendor.TECH_ID`, so `BL_LoadTechnique` can report the right `TechniqueID` back: `ocv→OCV, ca→CA, cp→CP, cv→CV, peis→PEIS, geis→GEIS, seisp→SPEIS, seisg→SGEIS, calimit→CALIMIT, cplimit→CPLIMIT, loop→LOOP, TI→TI, TO→TO, TOS→TOS`.
- `SimConfig` dataclass and a module-level `_CONFIG`, with `set_sim_config`.
- `_Channel` state: `techniques: list[int]`, `state: int`, `polls: int`, `messages: list[str]`, `pending: list[tuple[int, int]]` (process index, rows).
- `FakeDll.__getitem__(name)` returning a bound method per export, raising `KeyError(name)` for an unbound one so a client calling something the ABI table lacks fails loudly.
- Each export: validate the id and channel (return `-1` / `-3` as appropriate), honour `fail_on`, mutate the passed ctypes object, return `0`.
- `BL_GetData`: emit `rows_per_poll` rows for the current technique and process, filling `t_high`/`t_low` as a monotonic tick count and every `SINGLE` column as `encode_single(ramp)`; set `di.NbRows`, `di.NbCols`, `di.TechniqueID`, `di.TechniqueIndex`, `di.ProcessIndex`, `di.StartTime = 0.0`, `di.IRQskipped = 0`; set `cv.TimeBase = 1e-3` and `cv.State`. After `polls_until_stop` polls set `state = STOP` and emit one more non-empty segment, then zero rows — the tail the driver has to drain. For PEIS/GEIS/SPEIS/SGEIS alternate `ProcessIndex` 0 and 1.
- `push_message(channel, text)` and `load_dll(sdk_path=None)`.
- `NO_KERNEL_FIRMWARE_CODE = 0` plus a loaded value (e.g. `4`), so `driver.connect` can branch on kernel presence.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_sim.py -v`
Expected: PASS (17 tests).

- [ ] **Step 5: Format and commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/pstat/biologic/sim.py helao/hexagon/tests/test_biologic_sim.py
git status --short --branch
git add helao/deploy/hte/drivers/pstat/biologic/sim.py helao/hexagon/tests/test_biologic_sim.py
git commit -m "test(biologic): simulate the EClib1 DLL, not the client

Fakes the WinDLL surface so the real structs, EccParams packing and GetData
buffer decode stay inside the code under test. Its column-count table is
transcribed from the PDF independently of data.py, so the two cannot be wrong
together.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `eclib_client.py` — serialized gateway and error mapping

**Files:**
- Create: `helao/deploy/hte/drivers/pstat/biologic/eclib_client.py`
- Test: `helao/hexagon/tests/test_biologic_eclib_client.py`

**Interfaces:**
- Consumes: `vendor` (Task 1), `sim` (Task 3).
- Produces: `EclibError(RuntimeError)` with `.code: int` and `.name: str`; `EclibClient(sdk_path: str, simulate: bool = False)` with `connect(address: str, timeout: int = 5) -> vendor.DeviceInfo`, `disconnect()`, `test_connection() -> bool`, `channel_info(channel: int) -> vendor.ChannelInfo`, `board_type(channel: int) -> int`, `load_firmware(channel: int, kernel: str, fpga: str, force: bool = False)`, `load_technique(channel: int, ecc_path: str, params: vendor.EccParams, first: bool, last: bool)`, `define_params(entries: list[tuple[str, object, int]]) -> vendor.EccParams`, `technique_ids(channel: int, count: int) -> list[int]`, `start_channel(channel: int)`, `stop_channel(channel: int)`, `get_data(channel: int) -> tuple[vendor.CurrentValues, vendor.DataInfo, list[int]]`, `current_values(channel: int) -> vendor.CurrentValues`, `drain_messages(channel: int) -> list[str]`, `to_single(word: int, board_type: int) -> float`, `to_seconds(t_high: int, t_low: int, timebase: float, board_type: int) -> float`, `close()`; and `idn: int | None`.

Two reasons this layer exists, both worth keeping in the module docstring:

**Serialization.** Every vendor call is marshalled onto one dedicated worker thread owned by the client. `easy_biologic`'s `*_async` functions are `async def` wrappers around the blocking sync calls — generated in a loop at `lib/ec_lib.py:660` — so today every `BL_GetData` blocks the action server's event loop at the executor's 10 ms poll rate, in a process also serving HTTP and two WebSockets. Serializing here also settles DLL re-entrancy without the manual having to answer it.

**Interpretation.** Exports return an int code; this raises `EclibError` carrying the code's *name*, because `ERR_GEN_ECLAB_LOADED` (EC-Lab has the instrument) and `ERR_GEN_NOTCONNECTED` call for different operator actions and a bare `-9` distinguishes neither.

`define_params` keeps the returned `EccParam` array alive on the `EccParams` object it hands back (`params._keepalive = array`). The struct holds a bare pointer; if the array is garbage-collected before `BL_LoadTechnique` reads it, the DLL reads freed memory and the failure is a wrong parameter value or a crash, not an exception.

- [ ] **Step 1: Write the failing test**

```python
"""The client is the only thing that touches the DLL, and the only thing that
turns a vendor code into an exception."""

import threading

import pytest

from helao.deploy.hte.drivers.pstat.biologic import sim, vendor
from helao.deploy.hte.drivers.pstat.biologic.eclib_client import (
    EclibClient,
    EclibError,
)

ADDRESS = "192.168.200.100"


@pytest.fixture
def client():
    sim.set_sim_config(sim.SimConfig())
    c = EclibClient(sdk_path="/unused", simulate=True)
    try:
        yield c
    finally:
        c.close()
        sim.set_sim_config(sim.SimConfig())


@pytest.fixture
def connected(client):
    client.connect(ADDRESS)
    return client


def test_connect_returns_device_info_and_records_the_id(client):
    info = client.connect(ADDRESS)
    assert info.NumberOfChannels >= 1
    assert client.idn is not None


def test_a_vendor_failure_raises_with_the_code_name(connected):
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_LoadTechnique": -300}))
    parms = connected.define_params([("Duration_step", 1.0, 0)])
    with pytest.raises(EclibError) as exc:
        connected.load_technique(0, "ca4.ecc", parms, first=True, last=True)
    assert exc.value.code == -300
    assert exc.value.name == "ERR_TECH_ECCFILENOTEXISTS"
    assert "ERR_TECH_ECCFILENOTEXISTS" in str(exc.value)


def test_an_unknown_code_still_raises_and_says_so(connected):
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_StartChannel": -9999}))
    with pytest.raises(EclibError) as exc:
        connected.start_channel(0)
    assert exc.value.code == -9999
    assert "unknown" in exc.value.name.lower() or "-9999" in str(exc.value)


def test_every_vendor_call_runs_on_one_thread_that_is_not_the_caller(connected):
    seen = set()
    original = connected._call

    def spy(name, *args):
        seen.add(threading.current_thread().name)
        return original(name, *args)

    connected._call = spy
    connected.channel_info(0)
    connected.board_type(0)
    connected.current_values(0)
    assert len(seen) == 1
    assert threading.current_thread().name not in seen


def test_calls_from_two_threads_still_land_on_the_one_worker(connected):
    threads_seen = []

    def work():
        threads_seen.append(connected.channel_info(0).Channel)

    ts = [threading.Thread(target=work) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert threads_seen == [0, 0, 0, 0]


def test_define_params_keeps_the_array_alive(connected):
    """The EccParams struct holds a bare pointer. If the array it points at is
    collected before LoadTechnique reads it, the DLL reads freed memory."""
    parms = connected.define_params(
        [("Voltage_step", 0.5, 0), ("Step_number", 0, 0), ("vs_initial", False, 0)]
    )
    assert parms.len == 3
    assert getattr(parms, "_keepalive", None) is not None


def test_define_params_dispatches_by_python_type(connected):
    parms = connected.define_params(
        [("Duration_step", 2.5, 0), ("N_Cycles", 3, 0), ("sweep", True, 0)]
    )
    labels = [
        bytes(parms._keepalive[i].ParamStr).split(b"\x00")[0].decode()
        for i in range(parms.len)
    ]
    assert labels == ["Duration_step", "N_Cycles", "sweep"]


def test_define_params_refuses_a_type_the_dll_has_no_setter_for(connected):
    with pytest.raises(EclibError, match="Duration_step"):
        connected.define_params([("Duration_step", "2.5", 0)])


def test_bools_are_not_treated_as_ints(connected):
    """`isinstance(True, int)` is True, so a naive dispatch sends a bool to
    BL_DefineIntParameter and the DLL records 1 where it wanted a flag."""
    parms = connected.define_params([("vs_initial", True, 0)])
    assert parms._keepalive[0].ParamType == vendor.PARAM_BOOLEAN


def test_get_data_returns_only_the_rows_the_info_claims(connected):
    sim.set_sim_config(sim.SimConfig(rows_per_poll=3))
    parms = connected.define_params([("Duration_step", 1.0, 0)])
    connected.load_technique(0, "ca4.ecc", parms, first=True, last=True)
    connected.start_channel(0)
    values, info, records = connected.get_data(0)
    assert info.NbRows == 3
    assert len(records) == info.NbRows * info.NbCols
    assert values.TimeBase > 0


def test_technique_ids_reads_back_the_loaded_list_in_order(connected):
    parms = connected.define_params([("Trigger_Logic", 1, 0)])
    connected.load_technique(0, "TI4.ecc", parms, first=True, last=False)
    connected.load_technique(0, "ca4.ecc", parms, first=False, last=True)
    assert connected.technique_ids(0, 2) == [vendor.TECH_ID.TI, vendor.TECH_ID.CA]


def test_drain_messages_returns_everything_then_empties(connected):
    sim.push_message(0, "first")
    sim.push_message(0, "second")
    assert connected.drain_messages(0) == ["first", "second"]
    assert connected.drain_messages(0) == []


def test_drain_messages_is_bounded_so_a_chatty_channel_cannot_hang_a_poll(connected):
    for i in range(10_000):
        sim.push_message(0, f"m{i}")
    drained = connected.drain_messages(0)
    assert len(drained) <= 100


def test_to_single_uses_the_channel_aware_conversion(connected):
    word = sim.encode_single(-0.125)
    assert connected.to_single(word, vendor.BOARD_TYPE.PREMIUM) == pytest.approx(
        -0.125, abs=1e-6
    )


def test_to_seconds_uses_the_vendor_call_not_a_hand_rolled_shift(connected):
    """PDF §7.x.4 prescribes BL_ConvertTimeChannelNumericIntoSeconds;
    easy-biologic computes TimeBase * ((t_high << 32) + t_low) itself."""
    assert connected.to_seconds(0, 1000, 1e-3, vendor.BOARD_TYPE.PREMIUM) == (
        pytest.approx(1.0)
    )


def test_channel_index_is_passed_through_unmodified(connected):
    """kbio's wrappers subtract 1; that is kbio's convention, not the DLL's."""
    calls = []
    original = connected._call
    connected._call = lambda name, *args: (calls.append((name, args)), original(name, *args))[1]
    connected.board_type(0)
    name, args = calls[-1]
    assert name == "BL_GetChannelBoardType"
    assert args[1] == 0


def test_close_is_idempotent_and_joins_the_worker(client):
    client.connect(ADDRESS)
    client.close()
    client.close()
    assert client.idn is None


def test_a_call_after_close_raises_rather_than_hanging(client):
    client.connect(ADDRESS)
    client.close()
    with pytest.raises(EclibError, match="closed"):
        client.channel_info(0)


def test_test_connection_reports_false_when_not_connected(client):
    assert client.test_connection() is False
```

- [ ] **Step 2: Add the two parameter-type constants `vendor.py` still lacks**

The bool-vs-int test needs the DLL's `ParamType` values. Append to `vendor.py` and to `test_biologic_vendor.py`:

```python
# vendor.py -- PDF: TEccParam.ParamType
PARAM_INT = 0
PARAM_BOOLEAN = 1
PARAM_SINGLE = 2
```

```python
# test_biologic_vendor.py
def test_param_type_values_match_the_pdf():
    assert (vendor.PARAM_INT, vendor.PARAM_BOOLEAN, vendor.PARAM_SINGLE) == (0, 1, 2)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_eclib_client.py helao/hexagon/tests/test_biologic_vendor.py -v`
Expected: the client file fails with `ModuleNotFoundError: ... .eclib_client`; the vendor file fails one test with `AttributeError: module ... has no attribute 'PARAM_INT'`.

- [ ] **Step 4: Write minimal implementation**

`eclib_client.py`:

```python
import ctypes
import queue
import threading
from typing import Any, Optional

from helao.deploy.hte.drivers.pstat.biologic import vendor
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: A channel that keeps producing messages must not keep a poll in this loop.
MAX_MESSAGES_PER_DRAIN = 100


class EclibError(RuntimeError):
    def __init__(self, code: int, context: str = ""):
        self.code = int(code)
        self.name = vendor.ERROR_NAMES.get(self.code, f"unknown code {self.code}")
        super().__init__(f"{context}: {self.name} ({self.code})" if context else self.name)


class EclibClient:
    def __init__(self, sdk_path: str, simulate: bool = False):
        self.sdk_path = sdk_path
        self.simulate = simulate
        self.idn: Optional[int] = None
        self._closed = False
        self._requests: "queue.Queue[Any]" = queue.Queue()
        self._worker = threading.Thread(
            target=self._serve, name="eclib-worker", daemon=True
        )
        self._worker.start()
        if simulate:
            from helao.deploy.hte.drivers.pstat.biologic import sim

            self._dll = self._submit(sim.load_dll, sdk_path)
        else:
            self._dll = self._submit(vendor.load_dll, sdk_path)

    # -- the one thread ----------------------------------------------------

    def _serve(self) -> None:
        while True:
            item = self._requests.get()
            if item is None:
                return
            fn, args, result = item
            try:
                result.put((fn(*args), None))
            except BaseException as exc:  # returned to the caller's thread
                result.put((None, exc))

    def _submit(self, fn, *args):
        if self._closed:
            raise EclibError(-1, "client is closed")
        result: "queue.Queue[Any]" = queue.Queue(maxsize=1)
        self._requests.put((fn, args, result))
        value, exc = result.get()
        if exc is not None:
            raise exc
        return value

    def _call(self, name: str, *args) -> int:
        """Invoke a vendor export on the worker thread, returning its code."""
        return self._submit(self._dll[name], *args)

    def _checked(self, name: str, *args) -> None:
        code = self._call(name, *args)
        if code != 0:
            raise EclibError(code, name)
    ...
```

Then the public methods, each `_checked`-wrapping one export and unpacking its out-params:

- `connect`: `c_int32` id + `DeviceInfo`, `BL_Connect(address.encode(), timeout, byref(idn), byref(info))`, store `self.idn`.
- `disconnect`: `BL_Disconnect(self.idn)`, clear `self.idn`.
- `test_connection`: returns `False` when `self.idn is None`, else `self._call("BL_TestConnection", self.idn) == 0` — a predicate, never an exception, because `driver.connect` branches on it.
- `channel_info`, `board_type`, `current_values`: allocate the struct, `byref`, return it.
- `load_firmware`: build `ChannelsArray` with only `channel` true, `ResultsArray`, call with `(idn, chans, results, len(results), force, True, kernel.encode(), fpga.encode())`, then raise `EclibError(results[channel], "BL_LoadFirmware")` if that slot is non-zero — the per-channel result, not just the call's code, is where a firmware failure is reported.
- `load_technique`: `BL_LoadTechnique(idn, channel, ecc_path.encode(), params, first, last, False)`.
- `define_params`: dispatch **`bool` before `int`** (`isinstance(True, int)` is `True`), `float` → `BL_DefineSglParameter`, `int` → `BL_DefineIntParameter`, `bool` → `BL_DefineBoolParameter`; anything else raises `EclibError(-4, f"{label}: no DLL setter for {type(value).__name__}")`. Build `array = (vendor.EccParam * n)()`, define into `byref(array[i])`, then `params = vendor.EccParams(n, ctypes.cast(array, vendor.ECC_PARM))` and `params._keepalive = array`.
- `technique_ids`: `BL_GetTechniqueInfos(idn, channel, i, byref(info))` for `i in range(count)`, collect `info.Id`.
- `start_channel` / `stop_channel`.
- `get_data`: allocate `DataBuffer`, `DataInfo`, `CurrentValues`; call; return `(values, info, list(buf[: info.NbRows * info.NbCols]))` — slice by the claimed size, never the whole 1000 words.
- `drain_messages`: loop `BL_GetMessage` into a 4096 buffer until empty or `MAX_MESSAGES_PER_DRAIN`, decode `errors="replace"`.
- `to_single`, `to_seconds`: `BL_ConvertChannelNumericIntoSingle` / `BL_ConvertTimeChannelNumericIntoSeconds` with a `(c_uint32 * 2)(t_high, t_low)`.
- `close`: idempotent — disconnect if `self.idn`, set `_closed`, `self._requests.put(None)`, `self._worker.join(timeout=5)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_eclib_client.py helao/hexagon/tests/test_biologic_vendor.py -v`
Expected: PASS (20 + 25 tests).

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/pstat/biologic/ helao/hexagon/tests/test_biologic_eclib_client.py helao/hexagon/tests/test_biologic_vendor.py
git status --short --branch
git add helao/deploy/hte/drivers/pstat/biologic/eclib_client.py helao/deploy/hte/drivers/pstat/biologic/vendor.py helao/hexagon/tests/test_biologic_eclib_client.py helao/hexagon/tests/test_biologic_vendor.py
git commit -m "feat(biologic): serialize every EClib1 call onto one worker thread

easy-biologic's *_async functions are async def wrappers around blocking sync
calls, so BL_GetData ran on the action server's event loop at the 10ms poll
rate. Vendor codes now raise EclibError carrying the code's name.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `data.py` — layout tables, conversions, canonical columns

**Files:**
- Create: `helao/deploy/hte/drivers/pstat/biologic/data.py`
- Test: `helao/hexagon/tests/test_biologic_data.py`

**Interfaces:**
- Consumes: `vendor` (Task 1), and two callables the client supplies (`to_single(word, board_type)`, `to_seconds(t_high, t_low, timebase, board_type)`), injected rather than imported so this module stays free of the DLL.
- Produces: `Field = NamedTuple("Field", name: str, kind: str)` where `kind` is `"single"` or `"int"`; `layout(tech_id: int, family: vendor.BoardFamily, process: int) -> tuple[Field, ...]`; `COLUMNS: dict[str, tuple[str, ...]]` keyed by technique name; `decode(name: str, info, values, records, to_single, to_seconds, board_type) -> dict[str, list]`; `LayoutError(RuntimeError)`.

**`COLUMNS` is the single declaration of the emitted column set.** Task 7's `BiologicTechnique.column_plan` is populated from it at import, so the registry and the decoder cannot drift; `test_biologic_column_contract.py` reads the registry and therefore transitively pins this table.

- [ ] **Step 1: Write the failing test**

```python
"""Layout tables against PDF §7, and the canonical columns they project onto.

Every expected value here is computed in the test from the ramp the fake
records carry, so a wrong layout misaligns the decode and fails rather than
producing plausible numbers.
"""

import math

import pytest

from helao.deploy.hte.drivers.pstat.biologic import data, vendor
from helao.deploy.hte.drivers.pstat.biologic import sim

VMP3 = vendor.BoardFamily.VMP3
VMP300 = vendor.BoardFamily.VMP300
BOARD = vendor.BOARD_TYPE.PREMIUM


def to_single(word, board_type):
    return sim.decode_single(word)


def to_seconds(t_high, t_low, timebase, board_type):
    return timebase * ((t_high << 32) + t_low)


class Info:
    """Stand-in for vendor.DataInfo; decode() only reads these fields."""

    def __init__(self, tech_id, rows, cols, process=0, start=0.0, skipped=0):
        self.TechniqueID = tech_id
        self.NbRows = rows
        self.NbCols = cols
        self.ProcessIndex = process
        self.StartTime = start
        self.IRQskipped = skipped
        self.TechniqueIndex = 0
        self.loop = 0


class Values:
    def __init__(self, timebase=1e-3, state=vendor.PROG_STATE.RUN):
        self.TimeBase = timebase
        self.State = state


def names(tech_id, family, process=0):
    return [f.name for f in data.layout(tech_id, family, process)]


# --- layouts, PDF section 7 -------------------------------------------------


def test_ocv_carries_ece_on_vmp3_and_not_on_vmp300():
    assert names(vendor.TECH_ID.OCV, VMP3) == ["t_high", "t_low", "voltage", "voltage_ce"]
    assert names(vendor.TECH_ID.OCV, VMP300) == ["t_high", "t_low", "voltage"]


def test_ocv_fourth_vmp3_column_is_ece_not_control():
    """easy-biologic names it `control`; PDF section 7.2.3 says Ece."""
    assert names(vendor.TECH_ID.OCV, VMP3)[3] == "voltage_ce"


def test_cv_has_a_leading_control_column_on_vmp3_only():
    assert names(vendor.TECH_ID.CV, VMP3) == [
        "t_high", "t_low", "control", "current", "voltage", "cycle",
    ]
    assert names(vendor.TECH_ID.CV, VMP300) == [
        "t_high", "t_low", "current", "voltage", "cycle",
    ]


@pytest.mark.parametrize(
    "tech_id",
    [
        vendor.TECH_ID.CA,
        vendor.TECH_ID.CP,
        vendor.TECH_ID.CALIMIT,
        vendor.TECH_ID.CPLIMIT,
    ],
)
@pytest.mark.parametrize("family", [VMP3, VMP300])
def test_the_dc_step_techniques_share_one_five_column_layout(tech_id, family):
    assert names(tech_id, family) == [
        "t_high", "t_low", "voltage", "current", "cycle",
    ]


@pytest.mark.parametrize("tech_id", [vendor.TECH_ID.PEIS, vendor.TECH_ID.GEIS])
@pytest.mark.parametrize("family", [VMP3, VMP300])
def test_eis_process_zero_is_four_columns_on_both_families(tech_id, family):
    assert names(tech_id, family, 0) == ["t_high", "t_low", "voltage", "current"]


@pytest.mark.parametrize("tech_id", [vendor.TECH_ID.PEIS, vendor.TECH_ID.GEIS])
def test_eis_process_one_carries_a_trailing_irange_on_vmp3_only(tech_id):
    vmp3 = names(tech_id, VMP3, 1)
    vmp300 = names(tech_id, VMP300, 1)
    assert len(vmp3) == 15
    assert len(vmp300) == 14
    assert vmp3[-1] == "current_range"
    assert vmp3[:-1] == vmp300


@pytest.mark.parametrize("tech_id", [vendor.TECH_ID.PEIS, vendor.TECH_ID.GEIS])
def test_eis_process_one_field_order_matches_the_pdf(tech_id):
    assert names(tech_id, VMP300, 1) == [
        "frequency",
        "abs_voltage",
        "abs_current",
        "impedance_phase",
        "voltage",
        "current",
        "_pad1",
        "abs_voltage_ce",
        "abs_current_ce",
        "impedance_ce_phase",
        "voltage_ce",
        "_pad2",
        "_pad3",
        "time",
    ]


@pytest.mark.parametrize("tech_id", [vendor.TECH_ID.SPEIS, vendor.TECH_ID.SGEIS])
def test_staircase_eis_adds_step_to_both_processes(tech_id):
    assert names(tech_id, VMP3, 0) == [
        "t_high", "t_low", "voltage", "current", "step",
    ]
    assert names(tech_id, VMP3, 1)[-1] == "step"
    assert len(names(tech_id, VMP3, 1)) == 16
    assert len(names(tech_id, VMP300, 1)) == 15


def test_time_words_are_ints_and_measurements_are_singles():
    kinds = {f.name: f.kind for f in data.layout(vendor.TECH_ID.CA, VMP300, 0)}
    assert kinds["t_high"] == "int"
    assert kinds["t_low"] == "int"
    assert kinds["cycle"] == "int"
    assert kinds["voltage"] == "single"
    assert kinds["current"] == "single"


def test_an_unknown_technique_id_raises_rather_than_guessing():
    with pytest.raises(data.LayoutError, match="139"):
        data.layout(139, VMP3, 0)  # ZRA -- shipped .ecc, not implemented here


def test_an_unknown_process_index_raises():
    with pytest.raises(data.LayoutError, match="process"):
        data.layout(vendor.TECH_ID.PEIS, VMP3, 2)


def test_a_column_count_mismatch_is_refused_not_silently_realigned():
    """NbCols disagreeing with the table means the layout is wrong for this
    firmware; decoding anyway produces plausible, shifted numbers."""
    info = Info(vendor.TECH_ID.CA, rows=1, cols=4)
    with pytest.raises(data.LayoutError, match="NbCols"):
        data.decode("CA", info, Values(), [0, 0, 0, 0], to_single, to_seconds, BOARD)


# --- canonical columns ------------------------------------------------------


def test_the_dc_column_plan_is_the_frozen_one():
    assert set(data.COLUMNS["CA"]) == {"t_s", "Ewe_V", "I_A", "P_W", "cycle"}
    assert set(data.COLUMNS["CP"]) == {"t_s", "Ewe_V", "I_A", "P_W", "cycle"}
    assert set(data.COLUMNS["CV"]) == {"t_s", "Ewe_V", "I_A", "P_W", "cycle"}
    assert set(data.COLUMNS["CAOCV"]) == {"t_s", "Ewe_V", "I_A", "P_W", "cycle"}


def test_ocv_emits_only_time_and_potential():
    assert set(data.COLUMNS["OCV"]) == {"t_s", "Ewe_V"}


def test_the_eis_column_plan_is_the_frozen_sixteen():
    assert set(data.COLUMNS["PEIS"]) == {
        "process", "t_s", "Ewe_V", "I_A", "AbsEwe_V", "AbsI_A", "phase",
        "modulus", "Ece_V", "AbsEce_V", "AbsIce_A", "phase_ce", "modulus_ce",
        "f_Hz", "X_ohm", "R_ohm",
    }
    assert set(data.COLUMNS["GEIS"]) == set(data.COLUMNS["PEIS"])


def test_the_limit_variants_reuse_cp_columns():
    assert set(data.COLUMNS["CALIMIT"]) == set(data.COLUMNS["CP"])
    assert set(data.COLUMNS["CPLIMIT"]) == set(data.COLUMNS["CP"])


def test_staircase_eis_adds_step_to_the_eis_columns():
    assert set(data.COLUMNS["SPEIS"]) == set(data.COLUMNS["PEIS"]) | {"step"}
    assert set(data.COLUMNS["SGEIS"]) == set(data.COLUMNS["SPEIS"])


# --- decoding ---------------------------------------------------------------


def dc_record(t_ticks, ewe, i, cycle):
    return [0, t_ticks, sim.encode_single(ewe), sim.encode_single(i), cycle]


def test_a_ca_segment_decodes_to_the_values_the_ramp_encoded():
    records = dc_record(1000, 0.5, 1e-3, 2) + dc_record(2000, 0.6, 2e-3, 2)
    info = Info(vendor.TECH_ID.CA, rows=2, cols=5)
    out = data.decode("CA", info, Values(1e-3), records, to_single, to_seconds, BOARD)
    assert out["t_s"] == pytest.approx([1.0, 2.0])
    assert out["Ewe_V"] == pytest.approx([0.5, 0.6])
    assert out["I_A"] == pytest.approx([1e-3, 2e-3])
    assert out["cycle"] == [2, 2]


def test_power_is_signed_ewe_times_i():
    """The OLE backend derives |Ewe*I|; eclib records the signed product and
    four stations' data was produced that way."""
    records = dc_record(1000, -0.5, 2e-3, 0)
    info = Info(vendor.TECH_ID.CA, rows=1, cols=5)
    out = data.decode("CA", info, Values(), records, to_single, to_seconds, BOARD)
    assert out["P_W"] == pytest.approx([-1e-3])


def test_start_time_offsets_the_decoded_time():
    records = dc_record(1000, 0.0, 0.0, 0)
    info = Info(vendor.TECH_ID.CA, rows=1, cols=5, start=10.0)
    out = data.decode("CA", info, Values(1e-3), records, to_single, to_seconds, BOARD)
    assert out["t_s"] == pytest.approx([11.0])


def test_a_nan_start_time_is_treated_as_zero():
    records = dc_record(1000, 0.0, 0.0, 0)
    info = Info(vendor.TECH_ID.CA, rows=1, cols=5, start=float("nan"))
    out = data.decode("CA", info, Values(1e-3), records, to_single, to_seconds, BOARD)
    assert out["t_s"] == pytest.approx([1.0])


def test_cv_reads_voltage_and_current_from_the_right_slots_on_vmp3():
    """On VMP3 the leading `control` column shifts everything; reading VMP300
    order would swap Ewe and I and both would look like plausible numbers."""
    records = [
        0, 1000,
        sim.encode_single(9.9),   # control / Ec
        sim.encode_single(3e-3),  # <I>
        sim.encode_single(0.7),   # <Ewe>
        4,
    ]
    info = Info(vendor.TECH_ID.CV, rows=1, cols=6)
    out = data.decode(
        "CV", info, Values(), records, to_single, to_seconds,
        vendor.BOARD_TYPE.ESSENTIAL,
    )
    assert out["Ewe_V"] == pytest.approx([0.7])
    assert out["I_A"] == pytest.approx([3e-3])
    assert out["cycle"] == [4]


def test_control_is_decoded_but_not_emitted():
    """It has no frozen column; emitting it would change the recorded set."""
    assert "control" not in data.COLUMNS["CV"]


def eis_p1_record(freq, abs_ewe, abs_i, phase, ewe, i, abs_ece, abs_ice,
                  phase_ce, ece, t):
    return [
        sim.encode_single(freq),
        sim.encode_single(abs_ewe),
        sim.encode_single(abs_i),
        sim.encode_single(phase),
        sim.encode_single(ewe),
        sim.encode_single(i),
        0,
        sim.encode_single(abs_ece),
        sim.encode_single(abs_ice),
        sim.encode_single(phase_ce),
        sim.encode_single(ece),
        0,
        0,
        sim.encode_single(t),
    ]


def test_eis_process_one_derives_modulus_and_the_cartesian_impedance():
    phase = 0.5
    records = eis_p1_record(1000.0, 0.02, 0.004, phase, 0.3, 0.004, 0.01, 0.004, 0.1, 0.2, 7.5)
    info = Info(vendor.TECH_ID.PEIS, rows=1, cols=14, process=1)
    out = data.decode("PEIS", info, Values(), records, to_single, to_seconds, BOARD)
    modulus = 0.02 / 0.004
    assert out["modulus"] == pytest.approx([modulus])
    assert out["modulus_ce"] == pytest.approx([0.01 / 0.004])
    assert out["X_ohm"] == pytest.approx([-modulus * math.sin(phase)])
    assert out["R_ohm"] == pytest.approx([modulus * math.cos(phase)])
    assert out["f_Hz"] == pytest.approx([1000.0])
    assert out["t_s"] == pytest.approx([7.5])
    assert out["process"] == [1]


def test_eis_process_zero_fills_the_ac_columns_with_nan():
    """Both processes must emit the same keys or the appended buffer goes
    ragged and the chart silently drops a trace."""
    records = [0, 1000, sim.encode_single(0.3), sim.encode_single(1e-3)]
    info = Info(vendor.TECH_ID.PEIS, rows=1, cols=4, process=0)
    out = data.decode("PEIS", info, Values(1e-3), records, to_single, to_seconds, BOARD)
    assert set(out) == set(data.COLUMNS["PEIS"])
    assert out["process"] == [0]
    assert out["t_s"] == pytest.approx([1.0])
    assert out["Ewe_V"] == pytest.approx([0.3])
    assert math.isnan(out["f_Hz"][0])
    assert math.isnan(out["modulus"][0])


def test_a_zero_abs_current_yields_nan_modulus_rather_than_raising():
    records = eis_p1_record(1000.0, 0.02, 0.0, 0.5, 0.3, 0.0, 0.01, 0.0, 0.1, 0.2, 1.0)
    info = Info(vendor.TECH_ID.PEIS, rows=1, cols=14, process=1)
    out = data.decode("PEIS", info, Values(), records, to_single, to_seconds, BOARD)
    assert math.isnan(out["modulus"][0])
    assert math.isnan(out["X_ohm"][0])


def test_zero_rows_yields_empty_lists_for_every_declared_column():
    info = Info(vendor.TECH_ID.CA, rows=0, cols=5)
    out = data.decode("CA", info, Values(), [], to_single, to_seconds, BOARD)
    assert set(out) == set(data.COLUMNS["CA"])
    assert all(v == [] for v in out.values())


def test_a_technique_id_of_none_yields_no_rows():
    """BL_GetData reports TechniqueID 0 before anything is loaded."""
    info = Info(vendor.TECH_ID.NONE, rows=0, cols=0)
    out = data.decode("CA", info, Values(), [], to_single, to_seconds, BOARD)
    assert all(v == [] for v in out.values())


def test_staircase_step_is_emitted_as_an_integer_column():
    records = [0, 1000, sim.encode_single(0.3), sim.encode_single(1e-3), 3]
    info = Info(vendor.TECH_ID.SPEIS, rows=1, cols=5, process=0)
    out = data.decode("SPEIS", info, Values(1e-3), records, to_single, to_seconds, BOARD)
    assert out["step"] == [3]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.deploy.hte.drivers.pstat.biologic.data'`

- [ ] **Step 3: Add `decode_single` to `sim.py`**

The test decodes the ramp with the simulator's own inverse. Confirm `sim.decode_single(sim.encode_single(x)) == x` is already covered by Task 3's `test_convert_helpers_round_trip_the_ramp_encoding`; if `decode_single` was not exported, add it and its `__all__` entry now.

- [ ] **Step 4: Write minimal implementation**

`data.py` holds four tables and one function.

```python
"""Record layouts, conversions, and the canonical HELAO columns.

Layouts are keyed `(technique id, board family, process index)` and
transcribed from PDF section 7's data-format tables. Two rules the tables
encode, both of which produce plausible wrong numbers if broken:

**The family is the channel board's, not the chassis'.** easy-biologic selects
layouts from `device.kind`; the technique encoding follows the board, so in a
mixed-board chassis the two disagree and a record is decoded against the wrong
column count.

**A `NbCols` that disagrees with the table is an error, not a hint.** Realigning
to whatever arrived would emit shifted values that look like data.

`COLUMNS` is the one declaration of what each technique emits. `technique.py`
reads it for `column_plan`, so the registry the column-contract test inspects
and the decoder that fills the buffer cannot drift apart.
"""
```

- `Field = NamedTuple("Field", [("name", str), ("kind", str)])`, plus `_i(name)`/`_s(name)` helpers.
- `_EIS_P1_COMMON` = the 14 fields listed in `test_eis_process_one_field_order_matches_the_pdf`; VMP3 appends `_s("current_range")`; SPEIS/SGEIS append `_i("step")` after that.
- `_LAYOUTS: dict[tuple[int, BoardFamily, int], tuple[Field, ...]]` built from those pieces, with CA/CP/CALIMIT/CPLIMIT sharing one tuple and GEIS sharing PEIS's.
- `layout()` raises `LayoutError` naming the id or the process index rather than returning a default.
- `COLUMNS: dict[str, tuple[str, ...]]`: `OCV = ("t_s", "Ewe_V")`; `_DC = ("t_s", "Ewe_V", "I_A", "P_W", "cycle")` for CA/CP/CV/CAOCV/CALIMIT/CPLIMIT; `_EIS` = the 16 names for PEIS/GEIS; `_EIS + ("step",)` for SPEIS/SGEIS.
- `decode(name, info, values, records, to_single, to_seconds, board_type)`:
  1. `if info.TechniqueID == vendor.TECH_ID.NONE or info.NbRows == 0: return {c: [] for c in COLUMNS[name]}`.
  2. `fields = layout(info.TechniqueID, vendor.board_family(board_type), info.ProcessIndex)`; raise `LayoutError` if `len(fields) != info.NbCols`, quoting both.
  3. Slice `records` into `info.NbRows` rows of `info.NbCols`, converting each word by `f.kind` (`to_single(word, board_type)` or `int(word)` — note a `c_uint32` `cycle` must be read as unsigned, which it already is).
  4. `start = 0.0 if math.isnan(info.StartTime) else info.StartTime`.
  5. Project per technique into `COLUMNS[name]`, with `float("nan")` for any column this process does not carry. Time is `start + to_seconds(row["t_high"], row["t_low"], values.TimeBase, board_type)` for process 0 and the decoded `time` float for EIS process 1.
  6. `modulus = abs_voltage / abs_current` guarded — `nan` when the divisor is 0 or either side is `nan`; `X_ohm`/`R_ohm` from `modulus` and `impedance_phase` with the same guard, matching today's `NaN`-fill fallback.

- [ ] **Step 5: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_data.py -v`
Expected: PASS (34 tests).

- [ ] **Step 6: Cross-check every layout against the PDF before committing**

Run: `pdftotext -layout "/mnt/k/experiments/eche/Installation packages/EC-Lab Development Package/EC-Lab Development Package.pdf" - | sed -n '/7.2.3. Data format/,/7.3.4/p;/7.5.2. Data format/,/7.6.4/p;/7.11.3. Data format/,/7.14.4/p'`
Expected: each table read column-by-column against `_LAYOUTS`. Record in the commit message which PDF sections were checked. This is the step that catches the case the tests cannot: a table that is self-consistently wrong.

- [ ] **Step 7: Format and commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/pstat/biologic/data.py helao/deploy/hte/drivers/pstat/biologic/sim.py helao/hexagon/tests/test_biologic_data.py
git status --short --branch
git add helao/deploy/hte/drivers/pstat/biologic/data.py helao/deploy/hte/drivers/pstat/biologic/sim.py helao/hexagon/tests/test_biologic_data.py
git commit -m "feat(biologic): decode EClib1 records from PDF-transcribed layout tables

Layouts keyed (technique, board family, process); the family is the channel
board's, not the chassis'. A NbCols mismatch raises instead of realigning.
COLUMNS is the single declaration technique.py and the contract test share.

Checked against PDF sections 7.2.3, 7.3.3, 7.5.2, 7.6.3, 7.11.3, 7.12.3,
7.13.3, 7.14.3.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `data.py` — done-detection, tail drain, dropped-point reporting

**Files:**
- Modify: `helao/deploy/hte/drivers/pstat/biologic/data.py` (append `RunTracker`)
- Test: `helao/hexagon/tests/test_biologic_done_detection.py`

**Interfaces:**
- Consumes: `vendor.PROG_STATE` (Task 1).
- Produces: `RunTracker(max_drains: int = 20)` with `observe(values, info) -> str` returning `"starting"` / `"measuring"` / `"done"`, `.seen_run: bool`, `.skipped: int`, `.drains: int`, `.should_drain(info) -> bool`; and `MAX_DRAINS_PER_CALL = 20`.

Three behaviours, each replacing something in today's `get_data`:

- **`State > 0` is not "running".** `PROG_STATE` is `STOP=0, RUN=1, PAUSE=2, SYNC=3`; `PAUSE` and `SYNC` are busy and are named as such rather than caught by a `> 0` that also swallows anything a future firmware adds.
- **A channel polled between `StartChannel` and the firmware actually running reads `STOP`.** Today's first `get_data` can therefore end an action before it began. `STOP` is terminal only after one `RUN` has been seen; before that it is `"starting"`.
- **The tail must be drained.** Today's `while len(latest_segment.data) > 0` loop is unbounded and carries a stray `print("!!! retrieving last segment")`. `should_drain` bounds it by a drain count and by `TechniqueIndex` not advancing — an advancing index means the channel moved to the next linked technique and is not finishing.

`IRQskipped` is dropped points. It accumulates on `.skipped` for the driver to log and count; it does **not** become a column (the emitted set is frozen).

- [ ] **Step 1: Write the failing test**

```python
"""Done-detection, the start race, and the bounded tail drain."""

import pytest

from helao.deploy.hte.drivers.pstat.biologic import vendor
from helao.deploy.hte.drivers.pstat.biologic.data import MAX_DRAINS_PER_CALL, RunTracker


class V:
    def __init__(self, state):
        self.State = state
        self.TimeBase = 1e-3


class I:
    def __init__(self, rows=1, index=0, skipped=0):
        self.NbRows = rows
        self.TechniqueIndex = index
        self.IRQskipped = skipped


RUN = vendor.PROG_STATE.RUN
STOP = vendor.PROG_STATE.STOP
PAUSE = vendor.PROG_STATE.PAUSE
SYNC = vendor.PROG_STATE.SYNC


def test_stop_before_any_run_reads_as_starting_not_done():
    """The whole point: StartChannel returns before the firmware is running,
    so the first poll can legitimately see STOP."""
    t = RunTracker()
    assert t.observe(V(STOP), I(rows=0)) == "starting"
    assert t.observe(V(STOP), I(rows=0)) == "starting"
    assert t.seen_run is False


def test_run_then_stop_reads_as_done():
    t = RunTracker()
    assert t.observe(V(RUN), I()) == "measuring"
    assert t.observe(V(STOP), I()) == "done"


def test_pause_is_busy_not_done():
    t = RunTracker()
    t.observe(V(RUN), I())
    assert t.observe(V(PAUSE), I()) == "measuring"


def test_sync_is_busy_not_done():
    t = RunTracker()
    t.observe(V(RUN), I())
    assert t.observe(V(SYNC), I()) == "measuring"


def test_an_unknown_state_is_treated_as_busy():
    """A firmware that adds a state must not read as a finished action."""
    t = RunTracker()
    t.observe(V(RUN), I())
    assert t.observe(V(99), I()) == "measuring"


def test_rows_arriving_count_as_having_run():
    """A short technique can complete between two polls; the rows are proof it
    ran even though RUN was never observed."""
    t = RunTracker()
    assert t.observe(V(STOP), I(rows=4)) == "done"
    assert t.seen_run is True


def test_done_is_sticky():
    t = RunTracker()
    t.observe(V(RUN), I())
    assert t.observe(V(STOP), I()) == "done"
    assert t.observe(V(RUN), I()) == "done"


def test_should_drain_while_rows_keep_arriving():
    t = RunTracker()
    assert t.should_drain(I(rows=3)) is True


def test_should_not_drain_once_a_segment_is_empty():
    t = RunTracker()
    assert t.should_drain(I(rows=0)) is False


def test_drain_is_bounded():
    t = RunTracker()
    for _ in range(MAX_DRAINS_PER_CALL):
        assert t.should_drain(I(rows=1)) is True
    assert t.should_drain(I(rows=1)) is False


def test_drain_stops_when_the_technique_index_advances():
    """An advancing index means the channel moved to the next linked
    technique, so it is not finishing and draining would never end."""
    t = RunTracker()
    assert t.should_drain(I(rows=1, index=0)) is True
    assert t.should_drain(I(rows=1, index=1)) is False


def test_max_drains_is_configurable_for_a_long_plan():
    t = RunTracker(max_drains=2)
    assert t.should_drain(I(rows=1)) is True
    assert t.should_drain(I(rows=1)) is True
    assert t.should_drain(I(rows=1)) is False


def test_skipped_irqs_accumulate():
    t = RunTracker()
    t.observe(V(RUN), I(skipped=3))
    t.observe(V(RUN), I(skipped=2))
    assert t.skipped == 5


def test_skipped_irqs_are_not_a_column():
    """Dropped points are a log line and a counter; the emitted set is frozen."""
    from helao.deploy.hte.drivers.pstat.biologic import data

    for columns in data.COLUMNS.values():
        assert "IRQskipped" not in columns
        assert "_IRQskipped" not in columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_done_detection.py -v`
Expected: FAIL — `ImportError: cannot import name 'RunTracker' from ... data`

- [ ] **Step 3: Write minimal implementation**

Append to `data.py`:

```python
#: How many extra `BL_GetData` calls one `get_data` will make while draining
#: the tail. Bounded because the loop it replaces was not: `to_s3`-style
#: "retry until it works" on a call that can keep returning rows is how a
#: worker wedges.
MAX_DRAINS_PER_CALL = 20

#: States that mean the channel is not finished. Named rather than tested with
#: `State > 0`, which also swallows whatever a future firmware adds.
_BUSY_STATES = frozenset(
    {vendor.PROG_STATE.RUN, vendor.PROG_STATE.PAUSE, vendor.PROG_STATE.SYNC}
)


class RunTracker:
    """Decides when a technique has finished, and how far to drain after.

    One per started channel; the driver keeps it from `start_channel` to
    `cleanup`.
    """

    def __init__(self, max_drains: int = MAX_DRAINS_PER_CALL):
        self.max_drains = max_drains
        self.seen_run = False
        self.skipped = 0
        self.drains = 0
        self._done = False
        self._drain_index: Optional[int] = None

    def observe(self, values, info) -> str:
        self.skipped += int(getattr(info, "IRQskipped", 0) or 0)
        if self._done:
            return "done"
        state = int(values.State)
        if state in _BUSY_STATES or state not in {int(vendor.PROG_STATE.STOP)}:
            # Busy, or a state this build does not know -- either way not done.
            self.seen_run = True
            return "measuring"
        if int(getattr(info, "NbRows", 0) or 0) > 0:
            # Rows are proof it ran, even if RUN was never sampled.
            self.seen_run = True
        if not self.seen_run:
            return "starting"
        self._done = True
        return "done"

    def should_drain(self, info) -> bool:
        if int(getattr(info, "NbRows", 0) or 0) <= 0:
            return False
        index = int(getattr(info, "TechniqueIndex", 0) or 0)
        if self._drain_index is None:
            self._drain_index = index
        elif index != self._drain_index:
            return False
        if self.drains >= self.max_drains:
            return False
        self.drains += 1
        return True
```

Add `Optional` to the module's `typing` import.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_done_detection.py -v`
Expected: PASS (15 tests).

- [ ] **Step 5: Run the whole data module's tests together**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_data.py helao/hexagon/tests/test_biologic_done_detection.py -v`
Expected: PASS (49 tests).

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/pstat/biologic/data.py helao/hexagon/tests/test_biologic_done_detection.py
git status --short --branch
git add helao/deploy/hte/drivers/pstat/biologic/data.py helao/hexagon/tests/test_biologic_done_detection.py
git commit -m "fix(biologic): require an observed RUN before STOP ends an action

StartChannel returns before the firmware runs, so the first poll can read
STOP and the action ended before it began. PAUSE and SYNC are now named busy
rather than caught by State > 0, the tail drain is bounded by a count and by
TechniqueIndex, and IRQskipped is counted instead of ignored.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: `technique.py` — core, plus OCV / CA / CP / CV

**Files:**
- Modify (rewrite): `helao/deploy/hte/drivers/pstat/biologic/technique.py`
- Test: `helao/hexagon/tests/test_biologic_technique.py`

**Interfaces:**
- Consumes: `data.COLUMNS` (Task 5), `enum.ec_irange`/`ec_erange`/`ec_bandwidth` (Task 2), `vendor.TECH_ID` (Task 1).
- Produces: `Param = NamedTuple("Param", label: str, kind: str, arity: int)` (`kind` in `{"float", "int", "bool"}`, `arity` 1 for scalar or the fixed array width); `BiologicTechnique` dataclass with `technique_name`, `ecc_stem`, `param_table: dict[str, Param]`, `defaults: dict[str, object]`, `build: Callable[[dict], dict[str, object]]`, and properties `column_plan` (from `data.COLUMNS`) and `tech_id`; `entries(technique, action_params) -> list[tuple[str, object, int]]`; `TechniqueError(RuntimeError)`; `BIOTECHS: dict[str, BiologicTechnique]`; `SweepMode` (`StrEnum`, unchanged: `LINEAR = "lin"`, `LOG = "log"`).

`BIOTECHS` keeps its name and its role — `TECHNIQUE_REGISTRIES["eclib"]` is `lambda name: BIOTECHS[name]` and does not change.

**`column_plan` reads `data.COLUMNS`, it does not restate it.** One declaration; `test_biologic_column_contract.py` inspects the registry and so pins the decoder transitively.

**`build` is a callable per technique, not a flat dict.** CA needs `Step_number = len(steps) - 1`, CV needs a 5-point voltage profile from four scalars, and PEIS duplicates one action value into `Initial_` and `Final_` parameters. A dict-only mapping cannot express any of those, and the previous driver expressed them by leaning on easy-biologic's per-program `run()`.

**`defaults` is keyed by *action* key and is load-bearing.** Today these come from easy-biologic's per-program `defaults` dicts, applied when the endpoint does not supply a value, and they are what four stations' data was produced with:

| technique | action key absent from the endpoint | value easy-biologic supplied |
|---|---|---|
| OCV | `AcqInterval__V` | `0.01` |
| CA | `N_Cycles`, `vs_initial` | `0`, `False` |
| CP | `AcqInterval__V` is supplied; `vs_initial` | `False` |
| CV | `AcqInterval__V` | `0.01` |
| CV | `Average_over_dE`, `Begin_measuring_I`, `End_measuring_I` | `False`, `0.5`, `1.0` |

`run_CA` sets `AcqInterval__A = 10.0` in the endpoint body before dispatch, so `Record_every_dI` is effectively "never"; that stays the endpoint's job and is not duplicated here.

Note while working here: `run_CV`'s docstring claims it "Subtracts one from `Cycles`" and "derives `AcqInterval__V` from the time interval and scan rate". The body at `biologic_server.py:491` does neither. Task 15 corrects that docstring; do not implement what it describes.

- [ ] **Step 1: Write the failing test**

```python
"""Parameter tables and per-technique builds, against PDF section 7 and
against what easy-biologic actually sent."""

import pytest

from helao.deploy.hte.drivers.pstat.biologic import data, vendor
from helao.deploy.hte.drivers.pstat.biologic.technique import (
    BIOTECHS,
    BiologicTechnique,
    Param,
    TechniqueError,
    entries,
)


def built(name, **action_params):
    """ECC label -> value(s) for a technique, defaults applied."""
    tech = BIOTECHS[name]
    merged = {**tech.defaults, **action_params}
    return tech.build(merged)


def flat(name, **action_params):
    """(label, value, index) triples, as the client receives them."""
    return entries(BIOTECHS[name], {**BIOTECHS[name].defaults, **action_params})


# --- registry ---------------------------------------------------------------


def test_the_registry_keys_are_the_names_the_endpoints_resolve():
    assert set(BIOTECHS) >= {"OCV", "CA", "CP", "CV", "PEIS", "GEIS", "CAOCV"}


def test_every_technique_declares_the_ecc_stem_and_id_that_match():
    expected = {
        "OCV": ("ocv", vendor.TECH_ID.OCV),
        "CA": ("ca", vendor.TECH_ID.CA),
        "CP": ("cp", vendor.TECH_ID.CP),
        "CV": ("cv", vendor.TECH_ID.CV),
    }
    for name, (stem, tech_id) in expected.items():
        assert BIOTECHS[name].ecc_stem == stem
        assert BIOTECHS[name].tech_id == tech_id


def test_column_plan_is_read_from_data_not_restated():
    for name, tech in BIOTECHS.items():
        assert tuple(tech.column_plan) == tuple(data.COLUMNS[name])


# --- entry expansion --------------------------------------------------------


def test_a_scalar_becomes_one_entry_at_index_zero():
    assert ("Rest_time_T", 5.0, 0) in flat("OCV", Tval__s=5.0)


def test_a_list_becomes_one_entry_per_index():
    got = flat("CA", Vval__V=0.5, Tval__s=2.0)
    steps = [(label, value, index) for label, value, index in got if label == "Voltage_step"]
    assert steps == [("Voltage_step", 0.5, 0)]


def test_entry_values_are_coerced_to_the_declared_ecc_kind():
    """The DLL has a setter per type; an int where a single is declared calls
    BL_DefineIntParameter and the firmware reads a different parameter."""
    got = dict(((label, value) for label, value, _ in flat("CA", Vval__V=1, Tval__s=2)))
    assert isinstance(got["Voltage_step"], float)
    assert isinstance(got["Step_number"], int)
    assert isinstance(got["vs_initial"], bool)


def test_an_unknown_label_from_a_build_is_refused():
    tech = BiologicTechnique(
        technique_name="CA",
        ecc_stem="ca",
        tech_id=vendor.TECH_ID.CA,
        param_table={"Voltage_step": Param("Voltage_step", "float", 20)},
        defaults={},
        build=lambda p: {"Voltage_step": [0.1], "Nonsense": 1},
    )
    with pytest.raises(TechniqueError, match="Nonsense"):
        entries(tech, {})


def test_exceeding_a_declared_array_width_is_refused():
    with pytest.raises(TechniqueError, match="20"):
        flat("CA", Vval__V=[0.1] * 21, Tval__s=[1.0] * 21)


# --- OCV --------------------------------------------------------------------


def test_ocv_sends_the_three_pdf_parameters():
    got = built("OCV", Tval__s=12.0, AcqInterval__s=0.25)
    assert got == {
        "Rest_time_T": 12.0,
        "Record_every_dT": 0.25,
        "Record_every_dE": 0.01,
    }


def test_ocv_voltage_interval_default_is_the_one_easy_biologic_supplied():
    assert BIOTECHS["OCV"].defaults["AcqInterval__V"] == 0.01


def test_ocv_sends_no_hardware_range_parameters():
    """The endpoint exposes none, and OCV never drives the cell."""
    labels = {label for label, _, _ in flat("OCV", Tval__s=1.0)}
    assert not labels & {"I_Range", "E_Range", "Bandwidth"}


# --- CA ---------------------------------------------------------------------


def test_ca_wraps_the_scalar_step_and_sets_step_number_to_len_minus_one():
    got = built("CA", Vval__V=0.7, Tval__s=3.0, AcqInterval__s=0.01, AcqInterval__A=10.0)
    assert got["Voltage_step"] == [0.7]
    assert got["Duration_step"] == [3.0]
    assert got["vs_initial"] == [False]
    assert got["Step_number"] == 0
    assert got["N_Cycles"] == 0
    assert got["Record_every_dT"] == 0.01
    assert got["Record_every_dI"] == 10.0


def test_ca_maps_the_three_range_enums_to_vendor_ints():
    got = built(
        "CA", Vval__V=0.0, Tval__s=1.0, AcqInterval__s=0.01, AcqInterval__A=10.0,
        IRange="m10", ERange="v5", Bandwidth="BW7",
    )
    assert got["I_Range"] == vendor.I_RANGE.I_RANGE_10mA
    assert got["E_Range"] == vendor.E_RANGE.E_RANGE_5V
    assert got["Bandwidth"] == vendor.BANDWIDTH.BW_7


def test_ca_accepts_a_list_of_steps_and_keeps_the_arrays_aligned():
    got = built(
        "CA", Vval__V=[0.1, 0.2, 0.3], Tval__s=[1.0, 2.0, 3.0],
        AcqInterval__s=0.01, AcqInterval__A=10.0,
    )
    assert got["Voltage_step"] == [0.1, 0.2, 0.3]
    assert got["Duration_step"] == [1.0, 2.0, 3.0]
    assert got["vs_initial"] == [False, False, False]
    assert got["Step_number"] == 2


def test_ca_refuses_mismatched_step_and_duration_lists():
    """The DLL would run the steps it has durations for and stop, silently."""
    with pytest.raises(TechniqueError, match="Duration_step"):
        built("CA", Vval__V=[0.1, 0.2], Tval__s=[1.0], AcqInterval__s=0.01, AcqInterval__A=10.0)


# --- CP ---------------------------------------------------------------------


def test_cp_sends_current_steps_and_records_on_potential():
    got = built("CP", Ival__A=1e-3, Tval__s=4.0, AcqInterval__s=0.01, AcqInterval__V=0.001)
    assert got["Current_step"] == [1e-3]
    assert got["Duration_step"] == [4.0]
    assert got["Step_number"] == 0
    assert got["Record_every_dE"] == 0.001
    assert "Record_every_dI" not in got


def test_cp_does_not_derive_the_current_range_from_the_step():
    """easy-biologic's set_current_range() only warns when a range is given,
    and the endpoint always gives one -- so this path was already dead."""
    got = built(
        "CP", Ival__A=5.0, Tval__s=1.0, AcqInterval__s=0.01, AcqInterval__V=0.001,
        IRange="u10",
    )
    assert got["I_Range"] == vendor.I_RANGE.I_RANGE_10uA


# --- CV ---------------------------------------------------------------------


def test_cv_builds_the_five_point_profile_in_pdf_order():
    """PDF section 7.3.2: Voltage_step is [Ei, E1, E2, Ei, Ef]."""
    got = built(
        "CV", Vinit__V=0.0, Vapex1__V=1.0, Vapex2__V=-1.0, Vfinal__V=0.2,
        ScanRate__V_s=0.05, AcqInterval__s=0.1, Cycles=3,
    )
    assert got["Voltage_step"] == [0.0, 1.0, -1.0, 0.0, 0.2]
    assert got["Scan_Rate"] == [0.05] * 5
    assert got["vs_initial"] == [False] * 5


def test_cv_scan_number_is_the_fixed_two_the_pdf_requires():
    got = built(
        "CV", Vinit__V=0.0, Vapex1__V=1.0, Vapex2__V=-1.0, Vfinal__V=0.0,
        ScanRate__V_s=1.0, AcqInterval__s=0.1, Cycles=1,
    )
    assert got["Scan_number"] == 2


def test_cv_passes_cycles_through_without_subtracting():
    """The endpoint docstring claims it subtracts one; the body does not, and
    four stations' data was produced without the subtraction."""
    got = built(
        "CV", Vinit__V=0.0, Vapex1__V=1.0, Vapex2__V=-1.0, Vfinal__V=0.0,
        ScanRate__V_s=1.0, AcqInterval__s=0.1, Cycles=4,
    )
    assert got["N_Cycles"] == 4


def test_cv_record_every_de_falls_back_to_the_easy_biologic_default():
    """No endpoint supplies AcqInterval__V for CV, so every CV ever run used
    easy-biologic's 0.01."""
    got = built(
        "CV", Vinit__V=0.0, Vapex1__V=1.0, Vapex2__V=-1.0, Vfinal__V=0.0,
        ScanRate__V_s=1.0, AcqInterval__s=0.1, Cycles=1,
    )
    assert got["Record_every_dE"] == 0.01


def test_cv_measurement_window_defaults_match_easy_biologic():
    got = built(
        "CV", Vinit__V=0.0, Vapex1__V=1.0, Vapex2__V=-1.0, Vfinal__V=0.0,
        ScanRate__V_s=1.0, AcqInterval__s=0.1, Cycles=1,
    )
    assert got["Average_over_dE"] is False
    assert got["Begin_measuring_I"] == 0.5
    assert got["End_measuring_I"] == 1.0


def test_cv_scan_rate_is_passed_in_the_unit_easy_biologic_passed():
    """PDF section 7.3.2 labels Scan_Rate "slew rate array (mV/s)" while
    easy-biologic passes V/s unscaled, and the stations' CVs sweep at the
    requested rate -- so the label is a documentation error. Preserved
    deliberately: rescaling here would make every future CV 1000x off.
    """
    got = built(
        "CV", Vinit__V=0.0, Vapex1__V=1.0, Vapex2__V=-1.0, Vfinal__V=0.0,
        ScanRate__V_s=0.02, AcqInterval__s=0.1, Cycles=1,
    )
    assert got["Scan_Rate"] == [0.02] * 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_technique.py -v`
Expected: FAIL — `ImportError: cannot import name 'Param' from ... technique`

- [ ] **Step 3: Write minimal implementation**

Rewrite `technique.py`. Keep `SweepMode` exactly as it is today (it is an action-param vocabulary). Structure:

```python
Param = NamedTuple("Param", [("label", str), ("kind", str), ("arity", int)])

_KIND_CAST = {"float": float, "int": int, "bool": bool}


@dataclass
class BiologicTechnique:
    technique_name: str
    ecc_stem: str
    tech_id: int
    param_table: dict[str, Param]
    defaults: dict[str, Any]
    build: Callable[[dict], dict[str, Any]]

    @property
    def column_plan(self) -> tuple[str, ...]:
        return tuple(data.COLUMNS[self.technique_name])


def entries(technique, action_params) -> list[tuple[str, Any, int]]:
    """Expand a build's output into (label, value, index) triples.

    Casts each value to its declared ECC kind, because the DLL has one setter
    per type and a float sent through `BL_DefineIntParameter` sets a different
    parameter than the caller named.
    """
    out: list[tuple[str, Any, int]] = []
    for label, value in technique.build(action_params).items():
        try:
            param = technique.param_table[label]
        except KeyError:
            raise TechniqueError(
                f"{technique.technique_name}: {label!r} is not a declared "
                f"parameter of {technique.ecc_stem}.ecc"
            )
        values = value if isinstance(value, list) else [value]
        if len(values) > param.arity:
            raise TechniqueError(
                f"{technique.technique_name}: {label} takes at most "
                f"{param.arity} values, got {len(values)}"
            )
        cast = _KIND_CAST[param.kind]
        out.extend((label, cast(v), i) for i, v in enumerate(values))
    return out
```

Then a `_ranges(p)` helper returning `{"I_Range": ec_irange(p["IRange"]), "E_Range": ec_erange(p["ERange"]), "Bandwidth": ec_bandwidth(p["Bandwidth"])}` for the techniques whose endpoints expose them, and a `_steps(p, value_key, duration_key)` helper that wraps scalars into lists, raises `TechniqueError` naming `Duration_step` when the two lengths differ, and returns `(values, durations, [False] * n, n - 1)`.

Param tables, from PDF §7.2.2 / §7.3.2 / §7.5.2 / §7.6.2 — arity 20 for the CA/CP step arrays, 5 for CV's, 1 otherwise:

- `OCV`: `Rest_time_T` float, `Record_every_dE` float, `Record_every_dT` float.
- `CA`: `Voltage_step` float×20, `vs_initial` bool×20, `Duration_step` float×20, `Step_number` int, `Record_every_dT` float, `Record_every_dI` float, `N_Cycles` int, `I_Range` int, `E_Range` int, `Bandwidth` int.
- `CP`: as CA but `Current_step` float×20 and `Record_every_dE` in place of `Record_every_dI`.
- `CV`: `vs_initial` bool×5, `Voltage_step` float×5, `Scan_Rate` float×5, `Scan_number` int, `Record_every_dE` float, `Average_over_dE` bool, `N_Cycles` int, `Begin_measuring_I` float, `End_measuring_I` float, `I_Range` int, `E_Range` int, `Bandwidth` int.

Builds:

```python
def _build_ocv(p):
    return {
        "Rest_time_T": p["Tval__s"],
        "Record_every_dT": p["AcqInterval__s"],
        "Record_every_dE": p["AcqInterval__V"],
    }


def _build_ca(p):
    steps, durations, vs_initial, last = _steps(p, "Vval__V", "Tval__s")
    return {
        "Voltage_step": steps,
        "vs_initial": vs_initial,
        "Duration_step": durations,
        "Step_number": last,
        "Record_every_dT": p["AcqInterval__s"],
        "Record_every_dI": p["AcqInterval__A"],
        "N_Cycles": p["N_Cycles"],
        **_ranges(p),
    }


def _build_cv(p):
    # PDF section 7.3.2: [Ei, E1, E2, Ei, Ef], and Scan_number is fixed at 2.
    profile = [p["Vinit__V"], p["Vapex1__V"], p["Vapex2__V"], p["Vinit__V"], p["Vfinal__V"]]
    return {
        "vs_initial": [p["vs_initial"]] * 5,
        "Voltage_step": profile,
        "Scan_Rate": [p["ScanRate__V_s"]] * 5,
        "Scan_number": 2,
        "Record_every_dE": p["AcqInterval__V"],
        "Average_over_dE": p["Average_over_dE"],
        "N_Cycles": p["Cycles"],
        "Begin_measuring_I": p["Begin_measuring_I"],
        "End_measuring_I": p["End_measuring_I"],
        **_ranges(p),
    }
```

`_build_cp` mirrors `_build_ca` with `Ival__A`/`Record_every_dE`/`AcqInterval__V`.

Defaults: `OCV {"AcqInterval__V": 0.01}`; `CA {"N_Cycles": 0, "vs_initial": False}`; `CP {"N_Cycles": 0, "vs_initial": False}`; `CV {"AcqInterval__V": 0.01, "Average_over_dE": False, "Begin_measuring_I": 0.5, "End_measuring_I": 1.0, "vs_initial": False}`.

`BIOTECHS` is assembled at the bottom from the `BiologicTechnique` instances, as it is today.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_technique.py -v`
Expected: PASS (22 tests). `test_the_registry_keys_are_the_names_the_endpoints_resolve` will still fail until Task 8 and Task 11 add PEIS/GEIS/CAOCV — mark it `xfail` with reason `"PEIS/GEIS land in Task 8, CAOCV in Task 11"` and remove the marker in Task 11.

- [ ] **Step 5: Format and commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/pstat/biologic/technique.py helao/hexagon/tests/test_biologic_technique.py
git status --short --branch
git add helao/deploy/hte/drivers/pstat/biologic/technique.py helao/hexagon/tests/test_biologic_technique.py
git commit -m "feat(biologic): ECC parameter tables for OCV, CA, CP and CV

Each technique carries its .ecc stem, a PDF-transcribed parameter table with
array widths, the defaults easy-biologic supplied for keys no endpoint sets,
and a build callable -- CA's Step_number is len-1 and CV's profile is five
points from four scalars, neither of which a flat map can express.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: `technique.py` — PEIS and GEIS, and the sweep-mode fix

**Files:**
- Modify: `helao/deploy/hte/drivers/pstat/biologic/technique.py`
- Test: `helao/hexagon/tests/test_biologic_technique_eis.py`

**Interfaces:**
- Consumes: Task 7's `BiologicTechnique`, `Param`, `entries`, `_ranges`.
- Produces: `BIOTECHS["PEIS"]`, `BIOTECHS["GEIS"]`; `ec_sweep(value) -> bool`.

**This task changes what the instrument does.** `SweepMode` has never reached it: the ECC parameter `sweep` is boolean and documented "TRUE for linear points spacing" (PDF §7.11.2), and easy-biologic casts the action value with `bool(...)` at `lib/ec_lib.py:777`, so `bool("log")` is `True`. Every PEIS and GEIS run on all four stations has swept linearly while the recorded `SweepMode` said `log`.

Decided: fix the coercion — `"lin"` → `True`, `"log"` → `False` — and leave the endpoint default at `"log"`. So the default sweep becomes logarithmic, and new spectra are not frequency-comparable with the archive. Task 18 records this in the at-station gate notes.

- [ ] **Step 1: Write the failing test**

```python
"""PEIS/GEIS parameters, and the sweep flag that never worked."""

import pytest

from helao.deploy.hte.drivers.pstat.biologic import vendor
from helao.deploy.hte.drivers.pstat.biologic.technique import (
    BIOTECHS,
    SweepMode,
    ec_sweep,
)

PEIS_ARGS = dict(
    Vinit__V=0.05, Vamp__V=0.01, Finit__Hz=1000.0, Ffinal__Hz=1e6,
    FrequencyNumber=60, Duration__s=0.0, AcqInterval__s=0.1,
    SweepMode="log", Repeats=10, DelayFraction=0.1,
    IRange="AUTO", ERange="AUTO", Bandwidth="BW4",
)

GEIS_ARGS = dict(
    Iinit__A=1e-3, Iamp__A=1e-4, Finit__Hz=1000.0, Ffinal__Hz=1e6,
    FrequencyNumber=60, Duration__s=0.0, AcqInterval__s=0.1,
    SweepMode="log", Repeats=10, DelayFraction=0.1,
    IRange="AUTO", ERange="AUTO", Bandwidth="BW4",
)


def built(name, **overrides):
    tech = BIOTECHS[name]
    args = {**tech.defaults, **(PEIS_ARGS if name == "PEIS" else GEIS_ARGS), **overrides}
    return tech.build(args)


# --- the fix ----------------------------------------------------------------


def test_lin_is_true_because_the_pdf_says_true_means_linear():
    assert ec_sweep("lin") is True
    assert ec_sweep(SweepMode.LINEAR) is True


def test_log_is_false():
    """bool("log") is True, which is why every station swept linearly."""
    assert ec_sweep("log") is False
    assert ec_sweep(SweepMode.LOG) is False


def test_an_unrecognised_sweep_mode_raises_rather_than_defaulting():
    with pytest.raises(ValueError):
        ec_sweep("logarithmic")


def test_a_bare_bool_is_refused_so_the_old_shape_cannot_slip_through():
    with pytest.raises(ValueError):
        ec_sweep(True)


def test_peis_sends_sweep_false_for_the_endpoint_default():
    assert built("PEIS")["sweep"] is False


def test_peis_sends_sweep_true_for_lin():
    assert built("PEIS", SweepMode="lin")["sweep"] is True


def test_geis_uses_the_same_coercion():
    assert built("GEIS")["sweep"] is False
    assert built("GEIS", SweepMode="lin")["sweep"] is True


# --- PEIS -------------------------------------------------------------------


def test_peis_duplicates_the_bias_into_initial_and_final():
    """PDF section 7.11.2 takes a start and an end step; HELAO exposes one
    bias, so both carry it and Step_number is 0."""
    got = built("PEIS", Vinit__V=0.25)
    assert got["Initial_Voltage_step"] == 0.25
    assert got["Final_Voltage_step"] == 0.25
    assert got["Step_number"] == 0


def test_peis_maps_every_endpoint_parameter():
    got = built("PEIS")
    assert got["Amplitude_Voltage"] == 0.01
    assert got["Initial_frequency"] == 1000.0
    assert got["Final_frequency"] == 1e6
    assert got["Frequency_number"] == 60
    assert got["Duration_step"] == 0.0
    assert got["Record_every_dT"] == 0.1
    assert got["Average_N_times"] == 10
    assert got["Wait_for_steady"] == 0.1


def test_peis_defaults_match_what_easy_biologic_supplied():
    got = built("PEIS")
    assert got["vs_initial"] is False
    assert got["vs_final"] is False
    assert got["Correction"] is False
    assert got["Record_every_dI"] == 0.001


def test_peis_carries_the_three_hardware_ranges():
    got = built("PEIS", IRange="m1", ERange="v10", Bandwidth="BW5")
    assert got["I_Range"] == vendor.I_RANGE.I_RANGE_1mA
    assert got["E_Range"] == vendor.E_RANGE.E_RANGE_10V
    assert got["Bandwidth"] == vendor.BANDWIDTH.BW_5


def test_peis_stem_and_id():
    assert BIOTECHS["PEIS"].ecc_stem == "peis"
    assert BIOTECHS["PEIS"].tech_id == vendor.TECH_ID.PEIS


# --- GEIS -------------------------------------------------------------------


def test_geis_duplicates_the_current_bias_and_records_on_potential():
    got = built("GEIS", Iinit__A=2e-3)
    assert got["Initial_Current_step"] == 2e-3
    assert got["Final_Current_step"] == 2e-3
    assert got["Amplitude_Current"] == 1e-4
    assert got["Record_every_dE"] == 0.001
    assert "Record_every_dI" not in got


def test_geis_stem_and_id():
    assert BIOTECHS["GEIS"].ecc_stem == "geis"
    assert BIOTECHS["GEIS"].tech_id == vendor.TECH_ID.GEIS


def test_geis_does_not_derive_a_current_range_from_the_amplitude():
    """easy-biologic called set_current_range(2 * amplitude), which only warns
    when a range is supplied -- and the endpoint always supplies one."""
    got = built("GEIS", Iamp__A=1.0, IRange="u1")
    assert got["I_Range"] == vendor.I_RANGE.I_RANGE_1uA


# --- both -------------------------------------------------------------------


@pytest.mark.parametrize("name", ["PEIS", "GEIS"])
def test_the_eis_column_plans_are_the_frozen_sixteen(name):
    assert len(BIOTECHS[name].column_plan) == 16


@pytest.mark.parametrize("name", ["PEIS", "GEIS"])
def test_every_built_label_is_declared_in_the_param_table(name):
    tech = BIOTECHS[name]
    assert set(built(name)) <= set(tech.param_table)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_technique_eis.py -v`
Expected: FAIL — `ImportError: cannot import name 'ec_sweep'`

- [ ] **Step 3: Write minimal implementation**

Add to `technique.py`:

```python
def ec_sweep(value) -> bool:
    """The ECC ``sweep`` flag for a ``SweepMode``.

    PDF section 7.11.2 declares ``sweep`` boolean, "TRUE for linear points
    spacing". easy-biologic cast the action value with ``bool(...)``, and
    ``bool("log")`` is ``True`` -- so every PEIS and GEIS run swept linearly
    while the recorded ``SweepMode`` said ``log``.

    A bare bool is refused rather than passed through: accepting one would let
    the old ``bool(value)`` call site keep working and silently mean linear.
    """
    if isinstance(value, bool):
        raise ValueError(
            "sweep takes a SweepMode ('lin'/'log'), not a bool -- bool('log') "
            "is True, which is what this function exists to stop"
        )
    return SweepMode(value) is SweepMode.LINEAR
```

Parameter tables from PDF §7.11.2 (PEIS) and §7.13.2 (GEIS), all arity 1:

- shared: `vs_initial` bool, `vs_final` bool, `Duration_step` float, `Step_number` int, `Record_every_dT` float, `Final_frequency` float, `Initial_frequency` float, `sweep` bool, `Frequency_number` int, `Average_N_times` int, `Correction` bool, `Wait_for_steady` float, `I_Range` int, `E_Range` int, `Bandwidth` int.
- `PEIS` adds `Initial_Voltage_step` float, `Final_Voltage_step` float, `Amplitude_Voltage` float, `Record_every_dI` float.
- `GEIS` adds `Initial_Current_step` float, `Final_Current_step` float, `Amplitude_Current` float, `Record_every_dE` float.

Builds:

```python
def _build_peis(p):
    return {
        "vs_initial": p["vs_initial"],
        "vs_final": p["vs_initial"],
        "Initial_Voltage_step": p["Vinit__V"],
        "Final_Voltage_step": p["Vinit__V"],
        "Duration_step": p["Duration__s"],
        "Step_number": 0,
        "Record_every_dT": p["AcqInterval__s"],
        "Record_every_dI": p["AcqInterval__A"],
        "Final_frequency": p["Ffinal__Hz"],
        "Initial_frequency": p["Finit__Hz"],
        "sweep": ec_sweep(p["SweepMode"]),
        "Amplitude_Voltage": p["Vamp__V"],
        "Frequency_number": p["FrequencyNumber"],
        "Average_N_times": p["Repeats"],
        "Correction": p["Correction"],
        "Wait_for_steady": p["DelayFraction"],
        **_ranges(p),
    }
```

`_build_geis` mirrors it with `Iinit__A`/`Iamp__A` and `Record_every_dE: p["AcqInterval__V"]`.

Defaults — the values easy-biologic supplied for keys no endpoint sets: `PEIS {"vs_initial": False, "Correction": False, "AcqInterval__A": 0.001}`; `GEIS {"vs_initial": False, "Correction": False, "AcqInterval__V": 0.001}`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_technique.py helao/hexagon/tests/test_biologic_technique_eis.py -v`
Expected: PASS (22 + 19 tests), with `test_the_registry_keys_are_the_names_the_endpoints_resolve` still `xfail` pending CAOCV.

- [ ] **Step 5: Format and commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/pstat/biologic/technique.py helao/hexagon/tests/test_biologic_technique_eis.py
git status --short --branch
git add helao/deploy/hte/drivers/pstat/biologic/technique.py helao/hexagon/tests/test_biologic_technique_eis.py
git commit -m "fix(biologic): SweepMode reaches the instrument for the first time

The ECC sweep flag is boolean, TRUE meaning linear. easy-biologic cast the
action value with bool(), and bool('log') is True -- so every PEIS and GEIS
run swept linearly while the record said log. 'lin' is now True and 'log'
False; a bare bool is refused so the old shape cannot slip back in.

BEHAVIOUR CHANGE: with the endpoint default of 'log', new spectra are
logarithmically spaced and are not frequency-comparable with the archive.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: `technique.py` — TTL as real techniques, and load verification

**Files:**
- Modify: `helao/deploy/hte/drivers/pstat/biologic/technique.py`
- Test: `helao/hexagon/tests/test_biologic_ttl.py`

**Interfaces:**
- Consumes: Task 7's `entries`, `Param`, `BiologicTechnique`.
- Produces: `LoadStep = NamedTuple("LoadStep", ecc_stem: str, tech_id: int, params: list[tuple[str, Any, int]])`; `LoadPlan` dataclass with `steps: list[LoadStep]` and `.tech_ids -> list[int]`; `plan_for(technique, action_params, ttl_params) -> LoadPlan`; `TTL_TECHS: dict[str, BiologicTechnique]`.

There is no trigger *call* in EClib1 — Trigger In (id 152) and Trigger Out (id 151) are techniques, loaded ahead of the measurement. easy-biologic does this inside `program.py::_run` from a `ttl_params` dict and never confirms the load; the driver (Task 14) reads the channel's technique list back through `GetTechniqueInfos` and fails setup if the trigger is not at index 0.

The `ttl_params` shape `BiologicExec` builds — `{"ttl": "none"|"in"|"out", "ttl_logic": 1, "ttl_duration": float}` — is consumed unchanged, so the executor and every endpoint stay untouched. `ttl_logic` is hardcoded to `1` by the executor rather than taken from the `TTLwait`/`TTLsend` bitmask; that is existing behaviour and is preserved here, not corrected.

- [ ] **Step 1: Write the failing test**

```python
"""TTL is two techniques, loaded first. There is no trigger call in EClib1."""

import pytest

from helao.deploy.hte.drivers.pstat.biologic import vendor
from helao.deploy.hte.drivers.pstat.biologic.technique import (
    BIOTECHS,
    TechniqueError,
    plan_for,
)

CA = dict(
    Vval__V=0.5, Tval__s=1.0, AcqInterval__s=0.01, AcqInterval__A=10.0,
    IRange="AUTO", ERange="AUTO", Bandwidth="BW4",
)
NO_TTL = {"ttl": "none", "ttl_logic": 1, "ttl_duration": 1.0}
TTL_IN = {"ttl": "in", "ttl_logic": 1, "ttl_duration": 1.0}
TTL_OUT = {"ttl": "out", "ttl_logic": 1, "ttl_duration": 2.5}


def plan(ttl, **overrides):
    tech = BIOTECHS["CA"]
    return plan_for(tech, {**tech.defaults, **CA, **overrides}, ttl)


def labels(step):
    return {label for label, _, _ in step.params}


def value(step, label):
    return next(v for lab, v, _ in step.params if lab == label)


def test_no_ttl_loads_one_technique():
    p = plan(NO_TTL)
    assert len(p.steps) == 1
    assert p.steps[0].ecc_stem == "ca"
    assert p.tech_ids == [vendor.TECH_ID.CA]


def test_ttl_in_prepends_trigger_in():
    p = plan(TTL_IN)
    assert [s.ecc_stem for s in p.steps] == ["TI", "ca"]
    assert p.tech_ids == [vendor.TECH_ID.TI, vendor.TECH_ID.CA]


def test_ttl_out_prepends_trigger_out():
    p = plan(TTL_OUT)
    assert [s.ecc_stem for s in p.steps] == ["TO", "ca"]
    assert p.tech_ids == [vendor.TECH_ID.TO, vendor.TECH_ID.CA]


def test_trigger_in_sends_only_the_logic_parameter():
    p = plan(TTL_IN)
    assert labels(p.steps[0]) == {"Trigger_Logic"}
    assert value(p.steps[0], "Trigger_Logic") == 1


def test_trigger_out_also_sends_a_duration():
    p = plan(TTL_OUT)
    assert labels(p.steps[0]) == {"Trigger_Logic", "Trigger_Duration"}
    assert value(p.steps[0], "Trigger_Duration") == pytest.approx(2.5)


def test_trigger_duration_is_a_single_and_logic_an_int():
    p = plan(TTL_OUT)
    assert isinstance(value(p.steps[0], "Trigger_Duration"), float)
    assert isinstance(value(p.steps[0], "Trigger_Logic"), int)


def test_an_unrecognised_ttl_mode_is_refused():
    """A typo must not silently run without the trigger the caller asked for."""
    with pytest.raises(TechniqueError, match="sideways"):
        plan({"ttl": "sideways", "ttl_logic": 1, "ttl_duration": 1.0})


def test_a_missing_ttl_dict_means_no_trigger():
    tech = BIOTECHS["CA"]
    p = plan_for(tech, {**tech.defaults, **CA}, None)
    assert len(p.steps) == 1


def test_the_measurement_keeps_its_own_parameters_when_a_trigger_is_added():
    p = plan(TTL_OUT)
    assert "Voltage_step" in labels(p.steps[1])
    assert "Trigger_Logic" not in labels(p.steps[1])


def test_the_trigger_is_always_at_index_zero():
    """The driver reads the technique list back and asserts exactly this."""
    for ttl in (TTL_IN, TTL_OUT):
        assert plan(ttl).tech_ids[0] in (vendor.TECH_ID.TI, vendor.TECH_ID.TO)


def test_ttl_works_for_every_technique_whose_endpoint_offers_it():
    """Every run_* endpoint except run_PEIS/run_GEIS' siblings takes TTLwait
    and TTLsend, so no technique may reject a trigger."""
    for name in ("OCV", "CA", "CP", "CV", "PEIS", "GEIS"):
        tech = BIOTECHS[name]
        args = {**tech.defaults, **_MINIMAL[name]}
        assert plan_for(tech, args, TTL_IN).tech_ids[0] == vendor.TECH_ID.TI


_MINIMAL = {
    "OCV": dict(Tval__s=1.0, AcqInterval__s=0.1),
    "CA": CA,
    "CP": dict(
        Ival__A=1e-3, Tval__s=1.0, AcqInterval__s=0.01, AcqInterval__V=0.001,
        IRange="AUTO", ERange="AUTO", Bandwidth="BW4",
    ),
    "CV": dict(
        Vinit__V=0.0, Vapex1__V=1.0, Vapex2__V=-1.0, Vfinal__V=0.0,
        ScanRate__V_s=1.0, AcqInterval__s=0.1, Cycles=1,
        IRange="AUTO", ERange="AUTO", Bandwidth="BW4",
    ),
    "PEIS": dict(
        Vinit__V=0.0, Vamp__V=0.01, Finit__Hz=1000.0, Ffinal__Hz=1e6,
        FrequencyNumber=60, Duration__s=0.0, AcqInterval__s=0.1,
        SweepMode="log", Repeats=10, DelayFraction=0.1,
        IRange="AUTO", ERange="AUTO", Bandwidth="BW4",
    ),
    "GEIS": dict(
        Iinit__A=1e-3, Iamp__A=1e-4, Finit__Hz=1000.0, Ffinal__Hz=1e6,
        FrequencyNumber=60, Duration__s=0.0, AcqInterval__s=0.1,
        SweepMode="log", Repeats=10, DelayFraction=0.1,
        IRange="AUTO", ERange="AUTO", Bandwidth="BW4",
    ),
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_ttl.py -v`
Expected: FAIL — `ImportError: cannot import name 'plan_for'`

- [ ] **Step 3: Write minimal implementation**

Add to `technique.py`:

```python
LoadStep = NamedTuple(
    "LoadStep", [("ecc_stem", str), ("tech_id", int), ("params", list)]
)


@dataclass
class LoadPlan:
    """The ordered technique list to load onto one channel.

    EClib1 has no unload: `BL_LoadTechnique(..., first=True)` is what clears a
    channel, and `last=True` closes the list. The driver derives both from a
    step's position here rather than from the caller.
    """

    steps: list[LoadStep]

    @property
    def tech_ids(self) -> list[int]:
        return [step.tech_id for step in self.steps]


#: Trigger In / Trigger Out, PDF sections 7.32 and 7.33. Not calls -- techniques,
#: which is why they need `.ecc` files and a slot in the load order.
TECH_TI = BiologicTechnique(
    technique_name="TI",
    ecc_stem="TI",
    tech_id=vendor.TECH_ID.TI,
    param_table={"Trigger_Logic": Param("Trigger_Logic", "int", 1)},
    defaults={},
    build=lambda p: {"Trigger_Logic": p["ttl_logic"]},
)

TECH_TO = BiologicTechnique(
    technique_name="TO",
    ecc_stem="TO",
    tech_id=vendor.TECH_ID.TO,
    param_table={
        "Trigger_Logic": Param("Trigger_Logic", "int", 1),
        "Trigger_Duration": Param("Trigger_Duration", "float", 1),
    },
    defaults={},
    build=lambda p: {
        "Trigger_Logic": p["ttl_logic"],
        "Trigger_Duration": p["ttl_duration"],
    },
)

TTL_TECHS = {"in": TECH_TI, "out": TECH_TO}


def plan_for(technique, action_params, ttl_params=None) -> LoadPlan:
    """The load order for one technique, with a trigger ahead of it if asked."""
    steps: list[LoadStep] = []
    mode = (ttl_params or {}).get("ttl", "none")
    if mode != "none":
        try:
            trigger = TTL_TECHS[mode]
        except KeyError:
            raise TechniqueError(
                f"unknown ttl mode {mode!r}; expected 'none', 'in' or 'out'"
            )
        steps.append(
            LoadStep(trigger.ecc_stem, trigger.tech_id, entries(trigger, ttl_params))
        )
    steps.append(
        LoadStep(
            technique.ecc_stem, technique.tech_id, entries(technique, action_params)
        )
    )
    return LoadPlan(steps)
```

`TI`/`TO` are **not** added to `BIOTECHS` — that dict is what the endpoints resolve, and no endpoint runs a bare trigger.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_ttl.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Format and commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/pstat/biologic/technique.py helao/hexagon/tests/test_biologic_ttl.py
git status --short --branch
git add helao/deploy/hte/drivers/pstat/biologic/technique.py helao/hexagon/tests/test_biologic_ttl.py
git commit -m "feat(biologic): assemble TTL as Trigger In/Out techniques at index 0

EClib1 has no trigger call; TI (152) and TO (151) are techniques loaded ahead
of the measurement. The executor's ttl_params dict is consumed unchanged, and
an unrecognised mode is refused rather than run without the trigger.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: `technique.py` — linked-technique plans and LOOP

**Files:**
- Modify: `helao/deploy/hte/drivers/pstat/biologic/technique.py`
- Test: `helao/hexagon/tests/test_biologic_plan.py`

**Interfaces:**
- Consumes: Task 9's `LoadStep`, `LoadPlan`, `plan_for`, `entries`.
- Produces: `PlanEntry(name: str, params: dict)`; `PlanLoop(start: int, end: int, n: int)`; `PlanTechnique` with `technique_name = "PLAN"`, `column_plan`, `expand(ttl_params) -> LoadPlan`; `plan_technique(entries: list[PlanEntry], loops: list[PlanLoop]) -> PlanTechnique`; `TECH_LOOP`.

`PlanEntry`/`PlanLoop` mirror the eclib2 backend's payload shape deliberately: `/BIOLOGIC/run_plan` will exist on both backends after Task 15, and a sequence library that can target either is worth more than a shaped-for-eclib payload.

**The load-bearing subtlety.** Loop bounds are given over *plan entries*; the channel holds a **flattened** technique list. A prepended TTL shifts every index by one, CAOCV occupies two slots, and a LOOP technique occupies a slot of its own — so `protocol_number` must be the *loaded* index of the entry at `start`, computed after expansion, not the plan index. Getting it wrong repeats the wrong span and the instrument never complains.

`loop_N_times = -1` is the PDF's "mandatory goto, unlimited" and is refused: an action that never terminates parks the orchestrator with nothing reporting a fault.

- [ ] **Step 1: Write the failing test**

```python
"""Plan expansion, and the entry-index to loaded-index mapping."""

import pytest

from helao.deploy.hte.drivers.pstat.biologic import vendor
from helao.deploy.hte.drivers.pstat.biologic.technique import (
    PlanEntry,
    PlanLoop,
    TechniqueError,
    plan_technique,
)

OCV = dict(Tval__s=1.0, AcqInterval__s=0.1)
CA = dict(
    Vval__V=0.5, Tval__s=1.0, AcqInterval__s=0.01, AcqInterval__A=10.0,
    IRange="AUTO", ERange="AUTO", Bandwidth="BW4",
)
TTL_IN = {"ttl": "in", "ttl_logic": 1, "ttl_duration": 1.0}


def expand(entries, loops=(), ttl=None):
    return plan_technique(list(entries), list(loops)).expand(ttl)


def loop_params(step):
    return {label: value for label, value, _ in step.params}


def test_a_two_entry_plan_loads_two_techniques_in_order():
    plan = expand([PlanEntry("OCV", OCV), PlanEntry("CA", CA)])
    assert plan.tech_ids == [vendor.TECH_ID.OCV, vendor.TECH_ID.CA]


def test_each_entry_carries_its_own_ranges():
    """One plan may run two techniques at different current ranges."""
    plan = expand(
        [PlanEntry("CA", {**CA, "IRange": "u10"}), PlanEntry("CA", {**CA, "IRange": "m10"})]
    )
    first = {label: v for label, v, _ in plan.steps[0].params}
    second = {label: v for label, v, _ in plan.steps[1].params}
    assert first["I_Range"] == vendor.I_RANGE.I_RANGE_10uA
    assert second["I_Range"] == vendor.I_RANGE.I_RANGE_10mA


def test_a_loop_appends_a_loop_technique_after_the_span():
    plan = expand(
        [PlanEntry("OCV", OCV), PlanEntry("CA", CA)], [PlanLoop(start=0, end=1, n=3)]
    )
    assert plan.tech_ids == [
        vendor.TECH_ID.OCV, vendor.TECH_ID.CA, vendor.TECH_ID.LOOP,
    ]
    assert loop_params(plan.steps[2]) == {"loop_N_times": 3, "protocol_number": 0}


def test_protocol_number_is_the_loaded_index_not_the_plan_index():
    """A prepended TTL shifts every loaded index by one."""
    plan = expand(
        [PlanEntry("OCV", OCV), PlanEntry("CA", CA)],
        [PlanLoop(start=0, end=1, n=2)],
        ttl=TTL_IN,
    )
    assert plan.tech_ids[0] == vendor.TECH_ID.TI
    assert loop_params(plan.steps[-1])["protocol_number"] == 1


def test_a_loop_over_a_multi_technique_entry_wraps_all_of_it():
    """CAOCV occupies two slots. A loop over that one entry must return to the
    CA, not to the OCV half."""
    plan = expand(
        [PlanEntry("OCV", OCV), PlanEntry("CAOCV", _CAOCV)],
        [PlanLoop(start=1, end=1, n=2)],
    )
    assert plan.tech_ids[:3] == [
        vendor.TECH_ID.OCV, vendor.TECH_ID.CA, vendor.TECH_ID.OCV,
    ]
    assert loop_params(plan.steps[-1])["protocol_number"] == 1


def test_a_loop_lands_after_the_last_technique_of_its_end_entry():
    plan = expand(
        [PlanEntry("CAOCV", _CAOCV), PlanEntry("CA", CA)],
        [PlanLoop(start=0, end=0, n=2)],
    )
    # CA, OCV (the CAOCV pair), LOOP, then the trailing CA.
    assert plan.tech_ids == [
        vendor.TECH_ID.CA, vendor.TECH_ID.OCV, vendor.TECH_ID.LOOP,
        vendor.TECH_ID.CA,
    ]


def test_two_nested_loops_both_resolve():
    plan = expand(
        [PlanEntry("OCV", OCV), PlanEntry("CA", CA), PlanEntry("OCV", OCV)],
        [PlanLoop(start=1, end=1, n=2), PlanLoop(start=0, end=2, n=3)],
    )
    assert plan.tech_ids.count(vendor.TECH_ID.LOOP) == 2
    inner, outer = plan.steps[2], plan.steps[-1]
    assert loop_params(inner)["protocol_number"] == 1
    assert loop_params(outer)["protocol_number"] == 0


def test_unlimited_goto_is_refused():
    with pytest.raises(TechniqueError, match="-1"):
        expand([PlanEntry("CA", CA)], [PlanLoop(start=0, end=0, n=-1)])


def test_a_zero_repeat_loop_is_refused():
    with pytest.raises(TechniqueError, match="loop_N_times"):
        expand([PlanEntry("CA", CA)], [PlanLoop(start=0, end=0, n=0)])


def test_straddling_spans_are_refused():
    with pytest.raises(TechniqueError, match="nest"):
        expand(
            [PlanEntry("OCV", OCV), PlanEntry("CA", CA), PlanEntry("OCV", OCV)],
            [PlanLoop(start=0, end=1, n=2), PlanLoop(start=1, end=2, n=2)],
        )


def test_an_out_of_range_span_is_refused():
    with pytest.raises(TechniqueError, match="range"):
        expand([PlanEntry("CA", CA)], [PlanLoop(start=0, end=5, n=2)])


def test_a_reversed_span_is_refused():
    with pytest.raises(TechniqueError, match="range"):
        expand(
            [PlanEntry("OCV", OCV), PlanEntry("CA", CA)],
            [PlanLoop(start=1, end=0, n=2)],
        )


def test_an_unknown_technique_name_is_refused_at_build_time():
    """The endpoint builds the plan before ctx.begin(), so an unbuildable plan
    fails the call rather than starting an action that aborts with the cell
    already claimed."""
    with pytest.raises(TechniqueError, match="ZRA"):
        expand([PlanEntry("ZRA", {})])


def test_an_empty_plan_is_refused():
    with pytest.raises(TechniqueError, match="empty"):
        expand([])


def test_the_plan_column_plan_is_the_union_of_its_entries():
    tech = plan_technique([PlanEntry("CA", CA), PlanEntry("PEIS", _PEIS)], [])
    assert set(tech.column_plan) == set(_COLUMNS["CA"]) | set(_COLUMNS["PEIS"])


def test_a_single_entry_plan_emits_exactly_that_technique_columns():
    tech = plan_technique([PlanEntry("CA", CA)], [])
    assert set(tech.column_plan) == set(_COLUMNS["CA"])


_CAOCV = dict(
    CA_Vval__V_list=[0.5], CA_Tval__s_list=[1.0], CA_AcqInterval__s=0.01,
    CA_AcqInterval__A=10.0, CA_IRange="AUTO", CA_ERange="AUTO",
    CA_Bandwidth="BW4", OCV_Tval__s=1.0, OCV_AcqInterval__s=0.1,
    OCV_AcqInterval__V=10.0,
)

_PEIS = dict(
    Vinit__V=0.0, Vamp__V=0.01, Finit__Hz=1000.0, Ffinal__Hz=1e6,
    FrequencyNumber=60, Duration__s=0.0, AcqInterval__s=0.1,
    SweepMode="log", Repeats=10, DelayFraction=0.1,
    IRange="AUTO", ERange="AUTO", Bandwidth="BW4",
)

from helao.deploy.hte.drivers.pstat.biologic.data import COLUMNS as _COLUMNS  # noqa: E402
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_plan.py -v`
Expected: FAIL — `ImportError: cannot import name 'PlanEntry'`. The two CAOCV tests will additionally need Task 11; mark them `xfail(reason="CAOCV lands in Task 11")` and drop the markers there.

- [ ] **Step 3: Write minimal implementation**

Add to `technique.py`:

```python
PlanEntry = NamedTuple("PlanEntry", [("name", str), ("params", dict)])
PlanLoop = NamedTuple("PlanLoop", [("start", int), ("end", int), ("n", int)])

TECH_LOOP = BiologicTechnique(
    technique_name="LOOP",
    ecc_stem="loop",
    tech_id=vendor.TECH_ID.LOOP,
    param_table={
        "loop_N_times": Param("loop_N_times", "int", 1),
        "protocol_number": Param("protocol_number", "int", 1),
    },
    defaults={},
    build=lambda p: {
        "loop_N_times": p["loop_N_times"],
        "protocol_number": p["protocol_number"],
    },
)


@dataclass
class PlanTechnique:
    """Several techniques on one channel as a single loaded experiment.

    `technique_name` is `"PLAN"` so `data.decode` is called per *segment* with
    the name of whatever technique that segment came from -- the driver reads
    `DataInfo.TechniqueID` and looks the name up, rather than assuming one
    technique for the whole action.
    """

    technique_name: str
    plan_entries: list[PlanEntry]
    loops: list[PlanLoop]

    @property
    def column_plan(self) -> tuple[str, ...]:
        seen: list[str] = []
        for entry in self.plan_entries:
            for column in data.COLUMNS[entry.name]:
                if column not in seen:
                    seen.append(column)
        return tuple(seen)

    def expand(self, ttl_params=None) -> LoadPlan:
        ...
```

`expand` in order:

1. Build each entry's own `LoadPlan` via `sub_steps(entry)` — which is `plan_for(BIOTECHS[entry.name], merged_params, None).steps` for a plain technique, and Task 11's two-step expansion for `CAOCV`. An unknown `entry.name` raises `TechniqueError` naming it.
2. Record `first_loaded[i]` and `last_loaded[i]` per plan entry while concatenating, offset by `1` if a trigger was prepended.
3. Validate every span before emitting anything: `0 <= start <= end < len(plan_entries)` else `TechniqueError("... out of range")`; `n >= 1` else `TechniqueError("loop_N_times must be >= 1; -1 is the PDF's unlimited goto and would never terminate")`; and spans must nest — sort by `start`, and for any two overlapping spans require one to contain the other, else `TechniqueError("loop spans must nest, not straddle")`.
4. Emit LOOP steps in innermost-first order, each inserted **after** `last_loaded[span.end]`, with `protocol_number = first_loaded[span.start]` and `loop_N_times = span.n`. Each inserted LOOP shifts every later index, so recompute offsets as you insert rather than precomputing them all.

`plan_technique(entries, loops)` refuses an empty entry list (`TechniqueError("plan is empty")`) and returns `PlanTechnique("PLAN", entries, loops)`.

Extend `plan_for` so a `PlanTechnique` is handled: if the technique has an `expand` attribute, return `technique.expand(ttl_params)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_plan.py -v`
Expected: PASS (14 passed, 2 xfailed).

- [ ] **Step 5: Format and commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/pstat/biologic/technique.py helao/hexagon/tests/test_biologic_plan.py
git status --short --branch
git add helao/deploy/hte/drivers/pstat/biologic/technique.py helao/hexagon/tests/test_biologic_plan.py
git commit -m "feat(biologic): linked-technique plans with LOOP repeats

Loop bounds are given over plan entries while the channel holds a flattened
list, so protocol_number is the loaded index computed after expansion -- a
prepended trigger, a two-technique entry and each inserted LOOP all shift it.
loop_N_times of -1 is refused; it never terminates.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: `technique.py` — CAOCV as a two-technique entry

**Files:**
- Modify: `helao/deploy/hte/drivers/pstat/biologic/technique.py`
- Test: `helao/hexagon/tests/test_biologic_caocv.py`

**Interfaces:**
- Consumes: Task 7's CA/OCV techniques, Task 10's `sub_steps`.
- Produces: `BIOTECHS["CAOCV"]` as a `PlanTechnique`-backed entry whose `expand` yields two `LoadStep`s; `caocv_sub_params(action_params) -> tuple[dict, dict]`.

`run_CAOCV`'s endpoint keys and recorded `action_params` are unchanged: `CA_Vval__V_list`, `CA_Tval__s_list`, `CA_AcqInterval__s`, `CA_AcqInterval__A`, `CA_IRange`, `CA_ERange`, `CA_Bandwidth`, `OCV_Tval__s`, `OCV_AcqInterval__s`, `OCV_AcqInterval__V`. The endpoint body still sets `CA_AcqInterval__A = 10.0` and `OCV_AcqInterval__V = 10.0` before dispatch.

**Decided behaviour change: `CA_ERange` now reaches the hardware.** `CAOCV.__init__` in easy-biologic did `ch_params["voltage_range"] = get_voltage_range(max(abs(voltages)))` — an unconditional overwrite — so the recorded `CA_ERange` has never been applied; the instrument got `v2_5`/`v5`/`v10` derived from the voltage list. Every other technique honours its `ERange`, and CAOCV stops being the exception. A default of `AUTO` therefore now reaches the hardware where a derived fixed range used to, which can change the measured resolution on a CA step.

- [ ] **Step 1: Write the failing test**

```python
"""CAOCV is a CA followed by an OCV, loaded as one experiment."""

import pytest

from helao.deploy.hte.drivers.pstat.biologic import data, vendor
from helao.deploy.hte.drivers.pstat.biologic.technique import (
    BIOTECHS,
    TechniqueError,
    caocv_sub_params,
    plan_for,
)

ARGS = dict(
    CA_Vval__V_list=[0.4, 0.6], CA_Tval__s_list=[1.0, 2.0],
    CA_AcqInterval__s=0.02, CA_AcqInterval__A=10.0,
    CA_IRange="m10", CA_ERange="v5", CA_Bandwidth="BW5",
    OCV_Tval__s=5.0, OCV_AcqInterval__s=0.25, OCV_AcqInterval__V=10.0,
)


def plan(**overrides):
    tech = BIOTECHS["CAOCV"]
    return plan_for(tech, {**tech.defaults, **ARGS, **overrides}, None)


def params_of(step):
    return {label: v for label, v, _ in step.params}


def test_caocv_loads_ca_then_ocv():
    assert plan().tech_ids == [vendor.TECH_ID.CA, vendor.TECH_ID.OCV]


def test_the_ca_half_gets_the_ca_prefixed_parameters():
    ca = params_of(plan().steps[0])
    assert ca["Voltage_step"] == [0.4, 0.6]
    assert ca["Duration_step"] == [1.0, 2.0]
    assert ca["Step_number"] == 1
    assert ca["Record_every_dT"] == 0.02
    assert ca["Record_every_dI"] == 10.0


def test_the_ocv_half_gets_the_ocv_prefixed_parameters():
    ocv = params_of(plan().steps[1])
    assert ocv["Rest_time_T"] == 5.0
    assert ocv["Record_every_dT"] == 0.25
    assert ocv["Record_every_dE"] == 10.0


def test_ca_erange_reaches_the_hardware():
    """easy-biologic overwrote this from max(abs(voltages)); every other
    technique honours its ERange and CAOCV no longer differs."""
    assert params_of(plan().steps[0])["E_Range"] == vendor.E_RANGE.E_RANGE_5V


def test_ca_erange_auto_is_not_replaced_by_a_derived_range():
    ca = params_of(plan(CA_ERange="AUTO")["steps"][0] if False else plan(CA_ERange="AUTO").steps[0])
    assert ca["E_Range"] == vendor.E_RANGE.E_RANGE_AUTO


def test_ca_irange_and_bandwidth_come_from_the_ca_prefixed_keys():
    ca = params_of(plan().steps[0])
    assert ca["I_Range"] == vendor.I_RANGE.I_RANGE_10mA
    assert ca["Bandwidth"] == vendor.BANDWIDTH.BW_5


def test_the_ocv_half_sends_no_hardware_ranges():
    ocv = params_of(plan().steps[1])
    assert not {"I_Range", "E_Range", "Bandwidth"} & set(ocv)


def test_sub_params_strips_the_prefixes():
    ca, ocv = caocv_sub_params({**BIOTECHS["CAOCV"].defaults, **ARGS})
    assert ca["Vval__V"] == [0.4, 0.6]
    assert ca["Tval__s"] == [1.0, 2.0]
    assert ca["IRange"] == "m10"
    assert ocv["Tval__s"] == 5.0
    assert "CA_Vval__V_list" not in ca


def test_mismatched_ca_lists_are_refused():
    with pytest.raises(TechniqueError, match="Duration_step"):
        plan(CA_Vval__V_list=[0.1, 0.2], CA_Tval__s_list=[1.0])


def test_the_column_plan_is_the_frozen_dc_set():
    assert set(BIOTECHS["CAOCV"].column_plan) == set(data.COLUMNS["CA"])


def test_a_ttl_trigger_still_goes_ahead_of_both_halves():
    tech = BIOTECHS["CAOCV"]
    p = plan_for(
        tech,
        {**tech.defaults, **ARGS},
        {"ttl": "out", "ttl_logic": 1, "ttl_duration": 1.0},
    )
    assert p.tech_ids == [vendor.TECH_ID.TO, vendor.TECH_ID.CA, vendor.TECH_ID.OCV]
```

Fix the awkward line in `test_ca_erange_auto_is_not_replaced_by_a_derived_range` to plain `ca = params_of(plan(CA_ERange="AUTO").steps[0])` when transcribing.

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_caocv.py -v`
Expected: FAIL — `ImportError: cannot import name 'caocv_sub_params'`

- [ ] **Step 3: Write minimal implementation**

```python
#: `CA_`/`OCV_`-prefixed action key -> the sub-technique's own key.
_CAOCV_RENAME = {"Vval__V_list": "Vval__V", "Tval__s_list": "Tval__s"}


def caocv_sub_params(p) -> tuple[dict, dict]:
    """Split CAOCV's flat action params into a CA dict and an OCV dict.

    The two `_list` keys are renamed because the CA build takes `Vval__V` and
    `Tval__s` whether they are scalars or lists; everything else keeps its
    name with the prefix removed.
    """
    def strip(prefix, defaults):
        out = dict(defaults)
        for key, value in p.items():
            if key.startswith(prefix):
                bare = key[len(prefix):]
                out[_CAOCV_RENAME.get(bare, bare)] = value
        return out

    return (
        strip("CA_", BIOTECHS["CA"].defaults),
        strip("OCV_", BIOTECHS["OCV"].defaults),
    )
```

`BIOTECHS["CAOCV"]` becomes an object whose `expand(ttl_params)` builds the trigger (if any) then `entries(BIOTECHS["CA"], ca)` and `entries(BIOTECHS["OCV"], ocv)` as two `LoadStep`s, with `technique_name = "CAOCV"` and `column_plan` from `data.COLUMNS["CAOCV"]`. Task 10's `sub_steps(entry)` calls the same `expand`, which is what makes a `PlanEntry("CAOCV", ...)` occupy two loaded slots.

Nothing derives a voltage range. Delete the notion entirely rather than leaving a dead helper.

- [ ] **Step 4: Remove the xfail markers Tasks 7 and 10 left**

Drop `xfail` from `test_the_registry_keys_are_the_names_the_endpoints_resolve` (Task 7) and from the two CAOCV tests in `test_biologic_plan.py` (Task 10).

- [ ] **Step 5: Run the whole technique suite**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_technique.py helao/hexagon/tests/test_biologic_technique_eis.py helao/hexagon/tests/test_biologic_ttl.py helao/hexagon/tests/test_biologic_plan.py helao/hexagon/tests/test_biologic_caocv.py -v`
Expected: PASS, zero xfail.

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/pstat/biologic/technique.py helao/hexagon/tests/test_biologic_caocv.py helao/hexagon/tests/test_biologic_technique.py helao/hexagon/tests/test_biologic_plan.py
git status --short --branch
git add helao/deploy/hte/drivers/pstat/biologic/technique.py helao/hexagon/tests/test_biologic_caocv.py helao/hexagon/tests/test_biologic_technique.py helao/hexagon/tests/test_biologic_plan.py
git commit -m "feat(biologic): CAOCV as a two-technique entry, honouring CA_ERange

easy-biologic overwrote voltage_range from max(abs(voltages)), so the
recorded CA_ERange never reached the instrument. It does now, which is a
behaviour change on CA steps: AUTO reaches the hardware where a derived
fixed range used to.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: `technique.py` — CALIMIT, CPLIMIT, SPEIS, SGEIS

**Files:**
- Modify: `helao/deploy/hte/drivers/pstat/biologic/technique.py`
- Test: `helao/hexagon/tests/test_biologic_technique_new.py`

**Interfaces:**
- Consumes: Tasks 7–8's helpers.
- Produces: `BIOTECHS["CALIMIT"]`, `["CPLIMIT"]`, `["SPEIS"]`, `["SGEIS"]`; `LimitTest(variable: str, above: bool, logic: str, active: bool)`; `encode_test(test: LimitTest) -> int`; `ExitCond` (`IntEnum`: `NEXT_STEP = 0`, `NEXT_TECHNIQUE = 1`, `STOP = 2`).

New endpoint parameter names, used by Task 15:

- `run_CALIMIT`: CA's keys plus `Test1`/`Test2`/`Test3` (each `dict` or absent), `ExitCondition: int = 0`, `Cycles: int = 0`.
- `run_CPLIMIT`: CP's keys plus the same.
- `run_SPEIS`: `Vinit__V`, `Vfinal__V`, `StepNumber`, then PEIS's `Vamp__V`, `Finit__Hz`, `Ffinal__Hz`, `FrequencyNumber`, `Duration__s`, `AcqInterval__s`, `SweepMode`, `Repeats`, `DelayFraction`, `IRange`, `ERange`, `Bandwidth`.
- `run_SGEIS`: `Iinit__A`, `Ifinal__A`, `StepNumber`, then GEIS's equivalents.

- [ ] **Step 1: Read the `Test*_Config` bitfield table off the rendered page, not the text layer**

`pdftotext` flattens the bitfield header (PDF §7.37.2, page 161) into four labels over six columns — `Variable | (blank) | Sign | Logic | Active` above `31 ... 5 | 4 | 3 | 2 | 1 | 0` — which does not determine which bit is which.

Run:
```bash
pdftoppm -f 161 -l 161 -r 150 -png \
  "/mnt/k/experiments/eche/Installation packages/EC-Lab Development Package/EC-Lab Development Package.pdf" \
  /tmp/claude-1000/*/scratchpad/calimit
```
Then read the rendered image and write the bit positions into the test below as literals before implementing. **Do not infer them.** An incorrectly packed limit is a cell driven past the threshold that was supposed to stop it, and every other mistake in this plan is a data mistake.

If the page number has shifted, locate it with `pdftotext -layout ... - | grep -n "Test configuration format"` and convert the printed "N / 187" footer to the PDF page.

- [ ] **Step 2: Write the failing test**

```python
"""CALIMIT/CPLIMIT limits, and the staircase EIS pair.

The bit positions in `test_encode_test_packs_the_documented_bitfield` are
transcribed from the rendered PDF page, not from its text layer.
"""

import pytest

from helao.deploy.hte.drivers.pstat.biologic import data, vendor
from helao.deploy.hte.drivers.pstat.biologic.technique import (
    BIOTECHS,
    ExitCond,
    LimitTest,
    TechniqueError,
    encode_test,
)

LIMIT_ARGS = dict(
    Vval__V=[0.5], Tval__s=[10.0], AcqInterval__s=0.01, AcqInterval__A=10.0,
    IRange="AUTO", ERange="AUTO", Bandwidth="BW4", Cycles=0,
    ExitCondition=int(ExitCond.NEXT_TECHNIQUE),
    Test1={"variable": "I", "above": True, "value": 1e-3, "logic": "AND", "active": True},
)

SPEIS_ARGS = dict(
    Vinit__V=0.0, Vfinal__V=0.5, StepNumber=10, Vamp__V=0.01,
    Finit__Hz=1000.0, Ffinal__Hz=1e6, FrequencyNumber=60, Duration__s=0.0,
    AcqInterval__s=0.1, SweepMode="log", Repeats=10, DelayFraction=0.1,
    IRange="AUTO", ERange="AUTO", Bandwidth="BW4",
)

SGEIS_ARGS = dict(
    Iinit__A=0.0, Ifinal__A=1e-3, StepNumber=10, Iamp__A=1e-4,
    Finit__Hz=1000.0, Ffinal__Hz=1e6, FrequencyNumber=60, Duration__s=0.0,
    AcqInterval__s=0.1, SweepMode="log", Repeats=10, DelayFraction=0.1,
    IRange="AUTO", ERange="AUTO", Bandwidth="BW4",
)


def built(name, args, **overrides):
    tech = BIOTECHS[name]
    return tech.build({**tech.defaults, **args, **overrides})


# --- the bitfield -----------------------------------------------------------


def test_encode_test_packs_the_documented_bitfield():
    """Bit positions read off PDF section 7.37.2's rendered table. Replace the
    literals below with what that page shows before implementing."""
    VARIABLE_SHIFT = 5   # <- confirm against the rendered page
    SIGN_BIT = 2         # <- confirm
    LOGIC_BIT = 1        # <- confirm
    ACTIVE_BIT = 0       # <- confirm

    packed = encode_test(
        LimitTest(variable="I", above=True, logic="AND", active=True)
    )
    assert packed >> VARIABLE_SHIFT == 3          # I (Current) = 3
    assert (packed >> SIGN_BIT) & 1 == 1          # ">" = 1
    assert (packed >> LOGIC_BIT) & 1 == 1         # AND = 1
    assert (packed >> ACTIVE_BIT) & 1 == 1        # active = 1


def test_the_four_variables_have_the_documented_codes():
    codes = {
        v: encode_test(LimitTest(v, above=False, logic="OR", active=True)) >> 5
        for v in ("E", "AUX1", "AUX2", "I")
    }
    assert codes == {"E": 0, "AUX1": 1, "AUX2": 2, "I": 3}


def test_an_inactive_test_still_encodes_its_variable():
    packed = encode_test(LimitTest("E", above=False, logic="OR", active=False))
    assert packed & 1 == 0


def test_below_and_or_are_the_zero_encodings():
    assert encode_test(LimitTest("E", above=False, logic="OR", active=False)) == 0


def test_an_unknown_variable_is_refused():
    with pytest.raises(TechniqueError, match="AUX3"):
        encode_test(LimitTest("AUX3", above=True, logic="AND", active=True))


def test_an_unknown_logic_is_refused():
    with pytest.raises(TechniqueError, match="XOR"):
        encode_test(LimitTest("E", above=True, logic="XOR", active=True))


# --- the dependency rules PDF section 7.37.2 states -------------------------


def test_test2_without_test1_is_refused():
    """The PDF says Test2 is ignored if Test1 is inactive -- ignored, not
    refused, which is worse: the limit the caller asked for does not exist."""
    with pytest.raises(TechniqueError, match="Test1"):
        built(
            "CALIMIT", LIMIT_ARGS, Test1=None,
            Test2={"variable": "E", "above": True, "value": 1.0, "logic": "AND", "active": True},
        )


def test_test3_without_test2_is_refused():
    with pytest.raises(TechniqueError, match="Test2"):
        built(
            "CALIMIT", LIMIT_ARGS,
            Test3={"variable": "E", "above": True, "value": 1.0, "logic": "AND", "active": True},
        )


def test_no_tests_at_all_is_allowed():
    got = built("CALIMIT", LIMIT_ARGS, Test1=None)
    assert got["Test1_Config"] == [0]
    assert got["Test1_Value"] == [0.0]


# --- CALIMIT / CPLIMIT ------------------------------------------------------


def test_calimit_reuses_cps_column_plan():
    assert set(BIOTECHS["CALIMIT"].column_plan) == set(data.COLUMNS["CP"])
    assert set(BIOTECHS["CPLIMIT"].column_plan) == set(data.COLUMNS["CP"])


def test_calimit_step_number_is_len_minus_one():
    """PDF section 7.37.2: "Number of steps minus 1"."""
    got = built("CALIMIT", LIMIT_ARGS, Vval__V=[0.1, 0.2, 0.3], Tval__s=[1.0, 2.0, 3.0])
    assert got["Step_number"] == 2


def test_calimit_sends_voltage_steps_and_cplimit_sends_current_steps():
    ca = built("CALIMIT", LIMIT_ARGS)
    assert "Voltage_step" in ca and "Current_step" not in ca
    cp = built(
        "CPLIMIT",
        {**LIMIT_ARGS, "Ival__A": [1e-3], "AcqInterval__V": 0.001},
    )
    assert "Current_step" in cp and "Voltage_step" not in cp


def test_the_limit_arrays_are_per_step_and_twenty_wide():
    tech = BIOTECHS["CALIMIT"]
    for label in (
        "Test1_Config", "Test1_Value", "Test2_Config", "Test2_Value",
        "Test3_Config", "Test3_Value", "Exit_Cond",
    ):
        assert tech.param_table[label].arity == 20


def test_the_limit_value_carries_the_unit_of_its_variable():
    got = built("CALIMIT", LIMIT_ARGS)
    assert got["Test1_Value"] == [pytest.approx(1e-3)]


def test_exit_condition_is_broadcast_to_every_step():
    got = built(
        "CALIMIT", LIMIT_ARGS, Vval__V=[0.1, 0.2], Tval__s=[1.0, 2.0],
        ExitCondition=int(ExitCond.STOP),
    )
    assert got["Exit_Cond"] == [int(ExitCond.STOP)] * 2


def test_an_unknown_exit_condition_is_refused():
    with pytest.raises(TechniqueError, match="7"):
        built("CALIMIT", LIMIT_ARGS, ExitCondition=7)


def test_calimit_stems_and_ids():
    assert (BIOTECHS["CALIMIT"].ecc_stem, BIOTECHS["CALIMIT"].tech_id) == (
        "calimit", vendor.TECH_ID.CALIMIT,
    )
    assert (BIOTECHS["CPLIMIT"].ecc_stem, BIOTECHS["CPLIMIT"].tech_id) == (
        "cplimit", vendor.TECH_ID.CPLIMIT,
    )


# --- SPEIS / SGEIS ----------------------------------------------------------


def test_speis_sweeps_between_two_distinct_biases():
    """The difference from PEIS: Initial_ and Final_ are not the same value,
    and Step_number is the number of steps between them."""
    got = built("SPEIS", SPEIS_ARGS)
    assert got["Initial_Voltage_step"] == 0.0
    assert got["Final_Voltage_step"] == 0.5
    assert got["Step_number"] == 10


def test_sgeis_sweeps_between_two_currents():
    got = built("SGEIS", SGEIS_ARGS)
    assert got["Initial_Current_step"] == 0.0
    assert got["Final_Current_step"] == 1e-3
    assert got["Step_number"] == 10


def test_staircase_step_number_is_bounded_by_the_pdf_range():
    """PDF section 7.12.2: [0..98]."""
    with pytest.raises(TechniqueError, match="98"):
        built("SPEIS", SPEIS_ARGS, StepNumber=99)


def test_the_staircase_pair_uses_the_fixed_sweep_coercion():
    assert built("SPEIS", SPEIS_ARGS)["sweep"] is False
    assert built("SGEIS", SGEIS_ARGS, SweepMode="lin")["sweep"] is True


def test_the_staircase_column_plans_add_step_to_the_eis_set():
    for name in ("SPEIS", "SGEIS"):
        assert set(BIOTECHS[name].column_plan) == set(data.COLUMNS["PEIS"]) | {"step"}


def test_staircase_stems_and_ids():
    assert (BIOTECHS["SPEIS"].ecc_stem, BIOTECHS["SPEIS"].tech_id) == (
        "seisp", vendor.TECH_ID.SPEIS,
    )
    assert (BIOTECHS["SGEIS"].ecc_stem, BIOTECHS["SGEIS"].tech_id) == (
        "seisg", vendor.TECH_ID.SGEIS,
    )


def test_every_new_technique_only_emits_declared_labels():
    for name, args in (
        ("CALIMIT", LIMIT_ARGS),
        ("CPLIMIT", {**LIMIT_ARGS, "Ival__A": [1e-3], "AcqInterval__V": 0.001}),
        ("SPEIS", SPEIS_ARGS),
        ("SGEIS", SGEIS_ARGS),
    ):
        assert set(built(name, args)) <= set(BIOTECHS[name].param_table)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_technique_new.py -v`
Expected: FAIL — `ImportError: cannot import name 'LimitTest'`

- [ ] **Step 4: Write minimal implementation**

`LimitTest` is a `NamedTuple(variable, above, logic, active)` plus the value carried alongside; `encode_test` packs it with the bit positions confirmed in Step 1 and raises `TechniqueError` naming an unknown variable or logic.

Param tables:

- `CALIMIT` = CA's table with `Record_every_dI` retained, plus `Test1_Config` int×20, `Test1_Value` float×20, `Test2_Config`, `Test2_Value`, `Test3_Config`, `Test3_Value`, `Exit_Cond` int×20. `CPLIMIT` = CP's table plus the same.
- `SPEIS` = PEIS's table (`Initial_Voltage_step`/`Final_Voltage_step` now carry different values) — no new labels. `SGEIS` = GEIS's.

Builds: `_build_calimit(p)` starts from `_build_ca(p)`, overrides `N_Cycles` with `p["Cycles"]`, and adds the six limit arrays plus `Exit_Cond`, each broadcast to `len(steps)`. A `None`/absent `TestN` encodes as config `0`, value `0.0`. Validate the PDF's dependency rules (`Test3` requires `Test2` requires `Test1`) and raise rather than let the firmware ignore a limit. Validate `ExitCondition` against `ExitCond`.

`_build_speis(p)` is `_build_peis(p)` with `Final_Voltage_step = p["Vfinal__V"]` and `Step_number = p["StepNumber"]`, bounds-checked to `0..98`. `_build_sgeis` likewise from `_build_geis`.

Add `"CALIMIT"`, `"CPLIMIT"`, `"SPEIS"`, `"SGEIS"` to `BIOTECHS`.

- [ ] **Step 5: Run the whole technique suite**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_technique.py helao/hexagon/tests/test_biologic_technique_eis.py helao/hexagon/tests/test_biologic_ttl.py helao/hexagon/tests/test_biologic_plan.py helao/hexagon/tests/test_biologic_caocv.py helao/hexagon/tests/test_biologic_technique_new.py -v`
Expected: PASS.

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/pstat/biologic/technique.py helao/hexagon/tests/test_biologic_technique_new.py
git status --short --branch
git add helao/deploy/hte/drivers/pstat/biologic/technique.py helao/hexagon/tests/test_biologic_technique_new.py
git commit -m "feat(biologic): add CALIMIT, CPLIMIT, SPEIS and SGEIS

Test*_Config bit positions transcribed from the rendered PDF page, not its
text layer, which flattens the bitfield header ambiguously. The PDF's
Test3-needs-Test2-needs-Test1 rule is enforced rather than left to the
firmware to ignore, because an ignored limit is a cell driven past the
threshold that was meant to stop it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: `driver.py` — connection lifecycle and status

**Files:**
- Modify (rewrite, part 1): `helao/deploy/hte/drivers/pstat/biologic/driver.py`
- Test: `helao/hexagon/tests/test_biologic_driver_lifecycle.py`

**Interfaces:**
- Consumes: `eclib_client.EclibClient`/`EclibError` (Task 4), `vendor` (Task 1), `sim` (Task 3).
- Produces: `BiologicDriver(HelaoDriver)` with `__init__(config: dict = {})`, `connect()`, `get_status(channel=None)`, `disconnect()`, `reset()`, `shutdown()`; attributes `ready`, `address`, `num_channels`, `sdk_path`, `simulate`, `device_name`, `channel` (the single claim, `None` when free), `board_type`.

Config keys read: `address` (default `"192.168.200.240"`, unchanged), `num_channels` (default `12`, unchanged), `sdk_path` (default `vendor.DEFAULT_SDK_PATH`), `simulate` (default `False`), `force_load_firmware` (default `False`), `timeout` (default `5`).

**No device I/O in `__init__`** — that is the P3a-2 constructor-connect fix and `test_biologic_disconnected_construct.py` enforces it. The action server calls `connect()` at startup.

- [ ] **Step 1: Write the failing test**

```python
"""Connection lifecycle against the simulated DLL."""

import pytest

from helao.core.drivers.helao_driver import (
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)
from helao.deploy.hte.drivers.pstat.biologic import sim, vendor
from helao.deploy.hte.drivers.pstat.biologic.driver import BiologicDriver

CONFIG = {
    "address": "192.168.200.100",
    "num_channels": 2,
    "simulate": True,
    "sdk_path": "/unused",
}


@pytest.fixture
def driver():
    sim.set_sim_config(sim.SimConfig())
    d = BiologicDriver(dict(CONFIG))
    try:
        yield d
    finally:
        d.shutdown()
        sim.set_sim_config(sim.SimConfig())


@pytest.fixture
def connected(driver):
    assert driver.connect().response == DriverResponseType.success
    return driver


def test_it_is_a_helao_driver():
    assert issubclass(BiologicDriver, HelaoDriver)


def test_construction_does_no_device_io():
    """P3a-2: the server constructs the driver, then calls connect()."""
    d = BiologicDriver(dict(CONFIG))
    assert d.ready is False
    assert d.channel is None
    assert d.get_status().status == DriverStatus.uninitialized


def test_construction_needs_no_sdk_and_no_instrument():
    d = BiologicDriver({"address": "10.0.0.1", "sdk_path": "/nonexistent"})
    assert d.ready is False


def test_the_config_defaults_are_the_ones_the_station_configs_rely_on():
    d = BiologicDriver({})
    assert d.address == "192.168.200.240"
    assert d.num_channels == 12
    assert d.sdk_path == vendor.DEFAULT_SDK_PATH


def test_connect_reports_ok_and_records_the_board_type(connected):
    assert connected.ready is True
    assert connected.board_type == vendor.BOARD_TYPE.PREMIUM


def test_connect_logs_a_device_name_that_names_the_firmware(connected):
    assert connected.device_name != "unknown"


def test_firmware_is_not_loaded_when_the_kernel_is_already_there(driver):
    """The vendor example forces a reload on every connect, which reflashes a
    production instrument."""
    sim.set_sim_config(sim.SimConfig(kernel_loaded=True))
    calls = []
    driver.connect()
    driver._client._call = lambda name, *a: calls.append(name)
    assert "BL_LoadFirmware" not in calls


def test_firmware_is_loaded_when_the_channel_reports_none(driver):
    sim.set_sim_config(sim.SimConfig(kernel_loaded=False))
    resp = driver.connect()
    assert resp.response == DriverResponseType.success
    assert sim.firmware_loads() == 1


def test_force_load_firmware_reloads_even_when_present():
    sim.set_sim_config(sim.SimConfig(kernel_loaded=True))
    d = BiologicDriver({**CONFIG, "force_load_firmware": True})
    try:
        d.connect()
        assert sim.firmware_loads() == 1
    finally:
        d.shutdown()


def test_a_busy_instrument_reports_busy_not_error(driver):
    """ERR_GEN_ECLAB_LOADED means EC-Lab is holding it. The old driver matched
    on the string "In use by another script"; this keys on the code."""
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_Connect": -9}))
    resp = driver.connect()
    assert resp.response == DriverResponseType.failed
    assert resp.status == DriverStatus.busy


def test_any_other_connect_failure_reports_error(driver):
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_Connect": -102}))
    resp = driver.connect()
    assert resp.status == DriverStatus.error


def test_a_failed_connect_leaves_the_driver_reconnectable(driver):
    """`connection_raised` was set before the attempt, so a throwing connect
    stranded the driver until the process restarted."""
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_Connect": -102}))
    assert driver.connect().status == DriverStatus.error
    sim.set_sim_config(sim.SimConfig())
    assert driver.connect().response == DriverResponseType.success


def test_a_second_connect_on_a_live_connection_is_a_successful_no_op(connected):
    assert connected.connect().response == DriverResponseType.success
    assert connected.ready is True


def test_get_status_reports_every_channel_when_given_none(connected):
    resp = connected.get_status()
    assert set(resp.data) == {0, 1}
    assert resp.status == DriverStatus.ok


def test_get_status_reports_one_channel_when_given_an_index(connected):
    resp = connected.get_status(channel=1)
    assert set(resp.data) == {1}


def test_get_status_on_a_nonexistent_channel_is_uninitialized(connected):
    resp = connected.get_status(channel=7)
    assert resp.status == DriverStatus.uninitialized
    assert resp.data == {}


def test_get_status_reports_busy_while_a_channel_runs(connected):
    sim.set_sim_config(sim.SimConfig(polls_until_stop=99))
    connected._client.start_channel(0)
    assert connected.get_status().status == DriverStatus.busy


def test_disconnect_clears_ready_and_the_claim(connected):
    assert connected.disconnect().response == DriverResponseType.success
    assert connected.ready is False
    assert connected.channel is None


def test_reset_reconnects_and_reports_the_reconnect_result(connected):
    assert connected.reset().response == DriverResponseType.success
    assert connected.ready is True


def test_reset_reports_failure_when_the_reconnect_fails(connected):
    """The old reset() built a success response and then reconnected in a
    finally, so a failed reconnect reported success."""
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_Connect": -102}))
    resp = connected.reset()
    assert resp.response == DriverResponseType.failed
    assert connected.ready is False


def test_shutdown_is_safe_on_a_driver_that_never_connected():
    BiologicDriver(dict(CONFIG)).shutdown()


def test_shutdown_is_idempotent(connected):
    connected.shutdown()
    connected.shutdown()
    assert connected.ready is False


def test_firmware_messages_are_drained_at_connect(connected, caplog):
    sim.push_message(0, "I_Range out of range, clamped")
    with caplog.at_level("WARNING"):
        connected.get_status(channel=0)
    assert any("clamped" in r.message for r in caplog.records)
```

- [ ] **Step 2: Add `firmware_loads()` to `sim.py`**

A module-level counter incremented by the fake `BL_LoadFirmware`, reset by `set_sim_config`. Add one test to `test_biologic_sim.py`:

```python
def test_firmware_loads_are_counted():
    dll = sim.load_dll()
    idn = ctypes.c_int32()
    info = vendor.DeviceInfo()
    dll["BL_Connect"](b"1.2.3.4", 5, ctypes.byref(idn), ctypes.byref(info))
    chans, results = vendor.ChannelsArray(), vendor.ResultsArray()
    chans[0] = True
    assert sim.firmware_loads() == 0
    dll["BL_LoadFirmware"](
        idn.value, chans, results, len(results), False, True,
        b"kernel4.bin", b"vmp_iv_0395_aa.xlx",
    )
    assert sim.firmware_loads() == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_driver_lifecycle.py -v`
Expected: FAIL — the rewritten `driver.py` does not exist yet, so the import of `BiologicDriver` resolves to the old easy-biologic one and `test_construction_needs_no_sdk_and_no_instrument` fails on `sdk_path`.

- [ ] **Step 4: Write minimal implementation**

Rewrite `driver.py`'s header and connection half. `__init__` stores config, sets `self.ready = False`, `self.channel = None`, `self.board_type = None`, `self._client = None`, `self._tracker = None`, `self._technique = None`. `connect()`:

1. If `self.ready and self._client and self._client.test_connection()`: return success (idempotent).
2. Build `EclibClient(sdk_path=self.sdk_path, simulate=self.simulate)`.
3. `info = client.connect(self.address, self.timeout)`; set `self.device_name = f"{info.DeviceCode}/fw{info.FirmwareVersion}"`.
4. `self.board_type = client.board_type(0)`; log it and `vendor.board_family(self.board_type)`.
5. `ch = client.channel_info(0)`; if `self.force_load_firmware or not _kernel_loaded(ch)`: `kernel, fpga = vendor.firmware_assets(self.board_type)` then `client.load_firmware(0, kernel, fpga, force=self.force_load_firmware)`.
6. `self.ready = True`, drain messages into the log, return success.

On `EclibError`: `DriverStatus.busy` when `exc.name == "ERR_GEN_ECLAB_LOADED"`, else `error`; tear the half-built client down so a retry works.

`_kernel_loaded(ch)` is `ch.FirmwareCode != 0` — a channel with no kernel reports 0. Put the reasoning in a comment; the vendor example's `is_kernel_loaded` property is the same check.

`get_status(channel=None)` keeps today's response shape exactly: `data` maps channel index to the raw `State` int, status is `busy` if any queried channel is non-`STOP`. Out-of-range channel → `uninitialized` with `{}`. Also drains `GetMessage` for the queried channels and logs anything non-empty at WARNING.

`disconnect()` closes the client, clears `ready`/`channel`/`board_type`. `reset()` disconnects then connects and **returns the connect's response**. `shutdown()` stops and cleans up a claimed channel then disconnects, tolerating a never-connected driver.

- [ ] **Step 5: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_driver_lifecycle.py helao/hexagon/tests/test_biologic_sim.py -v`
Expected: PASS (24 + 18 tests).

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/pstat/biologic/driver.py helao/deploy/hte/drivers/pstat/biologic/sim.py helao/hexagon/tests/test_biologic_driver_lifecycle.py helao/hexagon/tests/test_biologic_sim.py
git status --short --branch
git add helao/deploy/hte/drivers/pstat/biologic/driver.py helao/deploy/hte/drivers/pstat/biologic/sim.py helao/hexagon/tests/test_biologic_driver_lifecycle.py helao/hexagon/tests/test_biologic_sim.py
git commit -m "feat(biologic): connect without reflashing, and reset that reports honestly

Firmware loads only when the channel reports no kernel; the vendor example's
force=True reflashes on every connect. A busy instrument is identified by
ERR_GEN_ECLAB_LOADED rather than by matching a string in an exception, and a
failed connect no longer strands the driver -- connection_raised was set
before the attempt. reset() returns the reconnect's result instead of a
success built before it ran.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: `driver.py` — setup, start, get_data, stop, cleanup

**Files:**
- Modify (rewrite, part 2): `helao/deploy/hte/drivers/pstat/biologic/driver.py`
- Test: `helao/hexagon/tests/test_biologic_driver.py`

**Interfaces:**
- Consumes: Task 13's driver, `technique.plan_for`/`BIOTECHS`, `data.decode`/`RunTracker`.
- Produces: `BiologicDriver.setup(technique, action_params={}, output_dir=None)`, `start_channel(channel=0, ttl_params=None)`, `async get_data(channel=0)`, `stop(channel=None)`, `cleanup(channel)`; `MAX_DRAINS_PER_CALL` re-exported for tests.

Response shapes are unchanged from today, because `BiologicExec` reads them: `start_channel` returns `data={"start_time": ...}` with `status=busy`; `get_data` returns `message` in `{"measuring", "done"}` and column-oriented `data`; `setup` returns `message="setup complete"`.

`get_data`'s `"starting"` tracker state maps to `message="measuring"` — `BiologicExec._poll` ends the action on the exact string `"done"`, and a third value would leak a new vocabulary into the executor.

- [ ] **Step 1: Write the failing test**

```python
"""setup/start/get_data/stop/cleanup against the simulated DLL."""

import asyncio

import pytest

from helao.core.drivers.helao_driver import DriverResponseType, DriverStatus
from helao.deploy.hte.drivers.pstat.biologic import data, sim, vendor
from helao.deploy.hte.drivers.pstat.biologic import technique as bt
from helao.deploy.hte.drivers.pstat.biologic.driver import BiologicDriver

CONFIG = {
    "address": "192.168.200.100", "num_channels": 2,
    "simulate": True, "sdk_path": "/unused",
}

CA = dict(
    Vval__V=0.5, Tval__s=1.0, AcqInterval__s=0.01, AcqInterval__A=10.0,
    IRange="AUTO", ERange="AUTO", Bandwidth="BW4", channel=0,
)


@pytest.fixture
def driver():
    sim.set_sim_config(sim.SimConfig())
    d = BiologicDriver(dict(CONFIG))
    d.connect()
    try:
        yield d
    finally:
        d.shutdown()
        sim.set_sim_config(sim.SimConfig())


def setup(driver, name="CA", **overrides):
    return driver.setup(
        technique=bt.BIOTECHS[name], action_params={**CA, **overrides}
    )


def run_to_completion(driver, channel=0, limit=50):
    """Poll until the driver says done, returning the concatenated columns."""
    collected: dict[str, list] = {}
    for _ in range(limit):
        resp = asyncio.run(driver.get_data(channel))
        for key, values in (resp.data or {}).items():
            collected.setdefault(key, []).extend(values)
        if resp.message == "done":
            return collected, resp
    raise AssertionError("never finished")


# --- setup ------------------------------------------------------------------


def test_setup_claims_the_channel(driver):
    assert setup(driver).response == DriverResponseType.success
    assert driver.channel == 0


def test_setup_refuses_a_second_claim_and_names_the_holder(driver):
    setup(driver)
    resp = driver.setup(technique=bt.BIOTECHS["CA"], action_params={**CA, "channel": 1})
    assert resp.response == DriverResponseType.failed
    assert resp.status == DriverStatus.busy
    assert "0" in (resp.message or "")


def test_setup_refuses_a_channel_outside_num_channels(driver):
    resp = driver.setup(technique=bt.BIOTECHS["CA"], action_params={**CA, "channel": 9})
    assert resp.status == DriverStatus.error


def test_setup_resolves_the_ecc_by_board_type(driver):
    sim.set_sim_config(sim.SimConfig(board_type=vendor.BOARD_TYPE.ESSENTIAL))
    d = BiologicDriver(dict(CONFIG))
    d.connect()
    try:
        setup(d)
        assert sim.loaded_ecc_files() == ["ca.ecc"]
    finally:
        d.shutdown()


def test_setup_on_a_premium_board_loads_the_four_suffixed_ecc(driver):
    setup(driver)
    assert sim.loaded_ecc_files() == ["ca4.ecc"]


def test_setup_loads_the_trigger_first_when_ttl_is_requested(driver):
    driver.setup(
        technique=bt.BIOTECHS["CA"],
        action_params={**CA, "TTLwait": 1},
    )
    driver.start_channel(0, {"ttl": "in", "ttl_logic": 1, "ttl_duration": 1.0})
    assert sim.loaded_ecc_files() == ["TI4.ecc", "ca4.ecc"]


def test_setup_fails_when_the_technique_list_reads_back_wrong(driver):
    """easy-biologic loaded and hoped. If the trigger is not at index 0 the
    measurement would run untriggered."""
    sim.set_sim_config(sim.SimConfig(technique_ids_override=[vendor.TECH_ID.CA]))
    resp = driver.setup(technique=bt.BIOTECHS["CA"], action_params=CA)
    driver.start_channel(0, {"ttl": "in", "ttl_logic": 1, "ttl_duration": 1.0})
    assert resp.response == DriverResponseType.success  # setup alone is fine
    assert driver.get_status(0).status != DriverStatus.busy


def test_a_failed_setup_releases_the_claim(driver):
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_LoadTechnique": -300}))
    assert setup(driver).response == DriverResponseType.failed
    assert driver.channel is None


def test_setup_accepts_output_dir_and_ignores_it(driver):
    """Signature parity with the OLE backend, which ships vendor artifacts
    there. EClib1 writes no files."""
    resp = driver.setup(
        technique=bt.BIOTECHS["CA"], action_params=CA, output_dir="/tmp/nope"
    )
    assert resp.response == DriverResponseType.success


# --- start ------------------------------------------------------------------


def test_start_returns_a_start_time_and_busy(driver):
    setup(driver)
    resp = driver.start_channel(0)
    assert resp.status == DriverStatus.busy
    assert resp.data["start_time"] > 0


def test_start_without_setup_fails(driver):
    assert driver.start_channel(0).response == DriverResponseType.failed


def test_start_on_a_running_channel_fails(driver):
    sim.set_sim_config(sim.SimConfig(polls_until_stop=99))
    setup(driver)
    driver.start_channel(0)
    assert driver.start_channel(0).response == DriverResponseType.failed


# --- get_data ---------------------------------------------------------------


def test_the_first_poll_before_the_firmware_runs_is_not_done(driver):
    """StartChannel returns before the channel is running; the old driver's
    State == 0 test ended the action here."""
    sim.set_sim_config(sim.SimConfig(idle_polls_before_run=2))
    setup(driver)
    driver.start_channel(0)
    resp = asyncio.run(driver.get_data(0))
    assert resp.message == "measuring"


def test_a_ca_run_emits_exactly_the_frozen_columns(driver):
    setup(driver)
    driver.start_channel(0)
    columns, _ = run_to_completion(driver)
    assert set(columns) >= set(data.COLUMNS["CA"])


def test_the_underscore_prefixed_current_values_are_still_emitted(driver):
    setup(driver)
    driver.start_channel(0)
    columns, _ = run_to_completion(driver)
    assert "_State" in columns
    assert "_TimeBase" in columns


def test_every_column_has_the_same_length(driver):
    """A ragged dict makes the chart silently drop a trace."""
    setup(driver)
    driver.start_channel(0)
    columns, _ = run_to_completion(driver)
    lengths = {len(v) for v in columns.values()}
    assert len(lengths) == 1


def test_the_tail_is_drained_so_no_rows_are_lost(driver):
    sim.set_sim_config(sim.SimConfig(rows_per_poll=4, polls_until_stop=3))
    setup(driver)
    driver.start_channel(0)
    columns, _ = run_to_completion(driver)
    assert len(columns["t_s"]) == sim.rows_emitted()


def test_the_drain_is_bounded(driver):
    """A channel that keeps producing rows must not hold get_data forever."""
    sim.set_sim_config(sim.SimConfig(rows_per_poll=1, polls_until_stop=1, endless_tail=True))
    setup(driver)
    driver.start_channel(0)
    resp = asyncio.run(driver.get_data(0))
    for _ in range(3):
        resp = asyncio.run(driver.get_data(0))
    assert len(resp.data["t_s"]) <= data.MAX_DRAINS_PER_CALL + 1


def test_an_eis_run_emits_both_processes_into_one_column_set(driver):
    setup(driver, "PEIS", **_PEIS)
    driver.start_channel(0)
    columns, _ = run_to_completion(driver)
    assert set(columns) >= set(data.COLUMNS["PEIS"])
    assert set(columns["process"]) == {0, 1}


def test_dropped_points_are_warned_about_and_not_a_column(driver, caplog):
    sim.set_sim_config(sim.SimConfig(irq_skipped=7))
    setup(driver)
    driver.start_channel(0)
    with caplog.at_level("WARNING"):
        columns, _ = run_to_completion(driver)
    assert any("7" in r.message for r in caplog.records)
    assert "IRQskipped" not in columns


def test_get_data_on_an_unclaimed_channel_fails(driver):
    assert asyncio.run(driver.get_data(1)).response == DriverResponseType.failed


def test_get_data_does_not_block_the_event_loop(driver):
    """Every vendor call goes to the client's worker thread; get_data awaits
    it. easy-biologic's *_async were async def wrappers around blocking calls."""
    setup(driver)
    driver.start_channel(0)

    async def racer():
        ticks = 0

        async def tick():
            nonlocal ticks
            for _ in range(20):
                ticks += 1
                await asyncio.sleep(0)

        await asyncio.gather(driver.get_data(0), tick())
        return ticks

    assert asyncio.run(racer()) == 20


# --- stop / cleanup ---------------------------------------------------------


def test_stop_ends_the_claimed_channel(driver):
    sim.set_sim_config(sim.SimConfig(polls_until_stop=99))
    setup(driver)
    driver.start_channel(0)
    assert driver.stop(0).response == DriverResponseType.success
    assert driver.get_status(0).status == DriverStatus.ok


def test_stop_with_none_stops_the_claimed_channel(driver):
    sim.set_sim_config(sim.SimConfig(polls_until_stop=99))
    setup(driver)
    driver.start_channel(0)
    assert driver.stop(None).response == DriverResponseType.success


def test_stop_with_none_and_nothing_claimed_is_a_successful_no_op(driver):
    assert driver.stop(None).response == DriverResponseType.success


def test_stop_is_reentrant(driver):
    """The old driver guarded this with a `self.stopping` flag; the client's
    worker thread is what makes it non-reentrant now."""
    sim.set_sim_config(sim.SimConfig(polls_until_stop=99))
    setup(driver)
    driver.start_channel(0)
    assert driver.stop(0).response == DriverResponseType.success
    assert driver.stop(0).response == DriverResponseType.success


def test_cleanup_releases_the_claim(driver):
    setup(driver)
    assert driver.cleanup(0).response == DriverResponseType.success
    assert driver.channel is None


def test_cleanup_refuses_while_the_channel_runs(driver):
    sim.set_sim_config(sim.SimConfig(polls_until_stop=99))
    setup(driver)
    driver.start_channel(0)
    assert driver.cleanup(0).response == DriverResponseType.failed


def test_cleanup_allows_the_next_action_to_claim(driver):
    setup(driver)
    driver.cleanup(0)
    assert setup(driver, channel=1).response == DriverResponseType.success


def test_shutdown_stops_and_releases_a_running_channel(driver):
    sim.set_sim_config(sim.SimConfig(polls_until_stop=99))
    setup(driver)
    driver.start_channel(0)
    driver.shutdown()
    assert driver.channel is None
    assert driver.ready is False


_PEIS = dict(
    Vinit__V=0.0, Vamp__V=0.01, Finit__Hz=1000.0, Ffinal__Hz=1e6,
    FrequencyNumber=60, Duration__s=0.0, AcqInterval__s=0.1,
    SweepMode="log", Repeats=10, DelayFraction=0.1,
)
```

- [ ] **Step 2: Extend `sim.py` with the observability the tests need**

Add, each reset by `set_sim_config`: `loaded_ecc_files() -> list[str]`, `rows_emitted() -> int`, and `SimConfig` fields `idle_polls_before_run: int = 0`, `endless_tail: bool = False`, `irq_skipped: int = 0`, `technique_ids_override: list[int] | None = None`. Add one `test_biologic_sim.py` test per new knob asserting it takes effect.

- [ ] **Step 3: Run tests to verify they fail**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_driver.py -v`
Expected: FAIL — `AttributeError` on the old driver's `setup` signature / missing `_client`.

- [ ] **Step 4: Write minimal implementation**

`setup(technique, action_params, output_dir=None)`:

1. `channel = action_params.get("channel", -1)`; refuse `channel not in range(self.num_channels)` with `error`, and refuse a second claim with `busy` naming `self.channel`.
2. Coerce nothing here — the range strings are coerced inside the technique builds (Task 7's `_ranges`), which is where they belong now.
3. `plan = technique.plan_for(...)` — actually `bt.plan_for(technique, {**technique.defaults, **action_params}, self._pending_ttl)`. Store the built plan; the trigger is not known until `start_channel`, so `setup` builds the measurement-only plan and `start_channel` rebuilds with the TTL dict. Simpler and honest: `setup` stores `technique` and merged params, and `start_channel` does the loading. **Do it that way** — it is also what makes `test_setup_loads_the_trigger_first_when_ttl_is_requested` observable at start.
4. Claim the channel, store `self._technique`, `self._params`, return `message="setup complete"`.

On any exception: release the claim, return `failed`/`error`.

`start_channel(channel=0, ttl_params=None)`:

1. Refuse when unclaimed, when the channel is busy, or when the channel is in error.
2. `plan = bt.plan_for(self._technique, self._params, ttl_params)`.
3. For each `LoadStep`, `ecc = vendor.ecc_file(step.ecc_stem, self.board_type)`; `params = client.define_params(step.params)`; `client.load_technique(channel, os.path.join(self.sdk_path, ecc), params, first=(i == 0), last=(i == len(plan.steps) - 1))`.
4. `loaded = client.technique_ids(channel, len(plan.steps))`; if `loaded != plan.tech_ids`, raise — naming both lists. This is the verification easy-biologic never did.
5. Drain messages into the log. `self._tracker = data.RunTracker()`. `start_time = time.time()`; `client.start_channel(channel)`; return `busy` with `data={"start_time": start_time}`.

`async get_data(channel=0)`:

1. Refuse when `channel != self.channel` or unclaimed.
2. `values, info, records = await loop.run_in_executor(None, self._client.get_data, channel)`.
3. `state = self._tracker.observe(values, info)`.
4. Decode with `data.decode(self._segment_name(info), info, values, records, self._client.to_single, self._client.to_seconds, self.board_type)` — `_segment_name` maps `info.TechniqueID` back to a registry name so a plan's mixed segments each decode correctly, falling back to `self._technique.technique_name`.
5. If `state == "done"`, keep calling `get_data` while `self._tracker.should_drain(info)`, concatenating.
6. Union the decoded columns with `self._technique.column_plan`, filling `float("nan")` for anything a segment did not carry, so the dict is never ragged.
7. Append the `_`-prefixed `CurrentValues` fields, one value per row, exactly as today.
8. Log a WARNING naming `self._tracker.skipped` when it is non-zero and has grown.
9. Return `message="measuring"` for `"starting"` and `"measuring"`, `"done"` for `"done"`; `status` `busy`/`ok` to match.

`stop(channel=None)`: resolve `None` to `self.channel`; no-op success when nothing is claimed; `client.stop_channel`. `cleanup(channel)`: refuse while `RUN`; clear `channel`, `_technique`, `_params`, `_tracker`.

- [ ] **Step 5: Run the whole biologic test set**

Run: `for f in helao/hexagon/tests/test_biologic_*.py; do echo "== $f"; timeout 300 python -m pytest "$f" -q; done`
Expected: every file passes. Run it without `conda run` per the global constraints, with the `helao` env on `PATH`.

- [ ] **Step 6: Check pyright against the baseline**

Run: `conda run -n helao pyright helao/deploy/hte/drivers/pstat/biologic/ helao/deploy/hte/servers/action/biologic_server.py`
Expected: **≤ 40 errors**. Anything above that is new and belongs to this task.

- [ ] **Step 7: Format and commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/pstat/biologic/ helao/hexagon/tests/test_biologic_driver.py helao/hexagon/tests/test_biologic_sim.py
git status --short --branch
git add helao/deploy/hte/drivers/pstat/biologic/ helao/hexagon/tests/test_biologic_driver.py helao/hexagon/tests/test_biologic_sim.py
git commit -m "feat(biologic): single-channel setup/start/get_data/stop/cleanup

One claim at a time, refused with the holder named. start_channel reads the
loaded technique list back and fails if it is not what was asked for, which
is what makes a requested trigger verifiable. get_data awaits the client's
worker thread so the action server's event loop keeps running, drains a
bounded tail, and never returns a ragged column dict.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 15: `biologic_server.py` — four new endpoints, `run_plan` on both backends

**Files:**
- Modify: `helao/deploy/hte/servers/action/biologic_server.py`
- Modify: `helao/hexagon/tests/checklists/hte/_additions.json`
- Test: `helao/hexagon/tests/test_biologic_new_endpoints.py`

**Interfaces:**
- Consumes: `BIOTECHS` keys `CALIMIT`/`CPLIMIT`/`SPEIS`/`SGEIS` (Task 12), `plan_technique` (Task 10).
- Produces: routes `/BIOLOGIC/run_CALIMIT`, `/run_CPLIMIT`, `/run_SPEIS`, `/run_SGEIS`; `/BIOLOGIC/run_plan` registered for `eclib` as well as `eclib2`.

Four changes, plus one docstring correction:

1. Four new `@app.action()` endpoints, each shaped like `run_CA`/`run_PEIS` with the parameter names Task 12 fixed, each dispatching `BiologicExec(active=active, oneoff=False, technique=app.resolve_technique("<NAME>"))`. `run_CALIMIT`/`run_CPLIMIT` set `active.action.action_params["AcqInterval__A"]` (resp. `__V`) `= 10.0` in the body, matching `run_CA`.
2. The guard at `biologic_server.py:655` becomes `if getattr(app, "pstat_backend", None) in {"eclib", "eclib2"}:`, and the `run_plan` body branches on the backend for which `plan_technique` to call — `ec2tech.plan_technique` for `eclib2`, `bt.plan_technique` for `eclib`. Its docstring's "One `BL_LoadExperiment` for the whole plan" is eclib2-specific; reword to say the techniques are loaded as one linked experiment, without naming either SDK's call.
3. The four new techniques take no `TTLwait`/`TTLsend` for now — the TTL electrical leg is untested (Task 18) and adding an untested trigger to four brand-new endpoints widens the gate for no benefit. Note this in each docstring.
4. `run_CV`'s docstring claims it "Subtracts one from `Cycles`" and "derives `AcqInterval__V` from the time interval and scan rate". The body does neither, and Task 7 pinned the actual behaviour. Correct the docstring to describe what it does.

- [ ] **Step 1: Write the failing test**

```python
"""The new routes exist on eclib, carry the parameters the techniques need,
and run_plan is registered on both SDK-backed backends."""

import pytest

from helao.deploy.hte.drivers.pstat.biologic.technique import BIOTECHS


@pytest.fixture
def app(monkeypatch):
    from helao.helpers import config_loader
    from helao.deploy.hte.servers.action import biologic_server

    monkeypatch.setattr(
        config_loader,
        "CONFIG",
        {
            "servers": {
                "BIOLOGIC": {
                    "params": {
                        "pstat_backend": "eclib",
                        "address": "192.168.200.100",
                        "num_channels": 1,
                        "simulate": True,
                    }
                }
            }
        },
        raising=False,
    )
    return biologic_server.makeApp("BIOLOGIC")


def paths(app):
    return {route.path for route in app.routes}


def params_of(app, path):
    route = next(r for r in app.routes if r.path == path)
    return {p.name for p in route.dependant.query_params + route.dependant.body_params}


def test_the_four_new_routes_are_registered(app):
    assert {
        "/BIOLOGIC/run_CALIMIT",
        "/BIOLOGIC/run_CPLIMIT",
        "/BIOLOGIC/run_SPEIS",
        "/BIOLOGIC/run_SGEIS",
    } <= paths(app)


def test_run_plan_is_registered_on_eclib(app):
    assert "/BIOLOGIC/run_plan" in paths(app)


def test_the_seven_existing_routes_are_untouched(app):
    assert {
        f"/BIOLOGIC/run_{name}"
        for name in ("OCV", "CA", "CP", "CV", "PEIS", "GEIS", "CAOCV")
    } <= paths(app)


def test_run_protocol_is_still_olecom_only(app):
    assert "/BIOLOGIC/run_protocol" not in paths(app)


def test_every_new_route_resolves_a_registered_technique(app):
    for name in ("CALIMIT", "CPLIMIT", "SPEIS", "SGEIS"):
        assert name in BIOTECHS


def test_calimit_carries_the_limit_parameters(app):
    got = params_of(app, "/BIOLOGIC/run_CALIMIT")
    assert {"Test1", "Test2", "Test3", "ExitCondition", "Cycles"} <= got
    assert {"Vval__V", "Tval__s", "IRange", "ERange", "Bandwidth", "channel"} <= got


def test_cplimit_takes_current_steps_not_voltage(app):
    got = params_of(app, "/BIOLOGIC/run_CPLIMIT")
    assert "Ival__A" in got
    assert "Vval__V" not in got


def test_speis_takes_two_biases_and_a_step_count(app):
    got = params_of(app, "/BIOLOGIC/run_SPEIS")
    assert {"Vinit__V", "Vfinal__V", "StepNumber"} <= got


def test_sgeis_takes_two_currents_and_a_step_count(app):
    got = params_of(app, "/BIOLOGIC/run_SGEIS")
    assert {"Iinit__A", "Ifinal__A", "StepNumber"} <= got


def test_the_new_routes_do_not_advertise_ttl(app):
    """The trigger's electrical leg is untested; advertising it on four brand
    new endpoints widens the at-station gate for nothing."""
    for name in ("CALIMIT", "CPLIMIT", "SPEIS", "SGEIS"):
        got = params_of(app, f"/BIOLOGIC/run_{name}")
        assert not {"TTLwait", "TTLsend", "TTLduration"} & got


def test_run_cv_docstring_no_longer_claims_it_subtracts_a_cycle(app):
    route = next(r for r in app.routes if r.path == "/BIOLOGIC/run_CV")
    doc = route.endpoint.__doc__ or ""
    assert "Subtracts one" not in doc
    assert "derives" not in doc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_new_endpoints.py -v`
Expected: FAIL — the four new paths are absent and `run_plan` is not registered for `eclib`.

- [ ] **Step 3: Write the endpoints**

Follow `run_CA`'s shape exactly for `run_CALIMIT`/`run_CPLIMIT` and `run_PEIS`'s for `run_SPEIS`/`run_SGEIS`, with `@action_version(1)`, `action_abbr` of `"CALIM"`, `"CPLIM"`, `"SPEIS"`, `"SGEIS"`, and the parameter lists from Task 12. `Test1`/`Test2`/`Test3` are `Optional[dict] = Body(None, embed=True)`; document the accepted keys (`variable`, `above`, `value`, `logic`, `active`) in the docstring, since a dict has no schema to read them from.

- [ ] **Step 4: Add the checklist entries**

Append to `helao/hexagon/tests/checklists/hte/_additions.json` — four entries, `module` `"biologic_server.py"`, `date` `"2026-09-17"`, each `why` naming the technique and pointing at the design doc.

**Amend the existing `/BIOLOGIC/run_plan` entry rather than adding a second.** Its recorded `why` reads "eclib2 backend only, since neither sibling backend can load a multi-technique experiment in one call", which this change makes false. Rewrite it to say the route is registered on both SDK-backed backends (`eclib`, `eclib2`) and remains absent on `olecom`, whose multi-technique unit is an `.mps` covered by `run_protocol`.

- [ ] **Step 5: Regenerate and check the frozen route checklist**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_hte_route_checklist.py helao/hexagon/tests/test_checklist_additions.py -v`
Expected: PASS. If the frozen `biologic_server.json` needs regenerating, do it with the repo's existing freeze tool rather than by hand, and commit the regenerated file in this task.

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black helao/deploy/hte/servers/action/biologic_server.py helao/hexagon/tests/test_biologic_new_endpoints.py
git status --short --branch
git add helao/deploy/hte/servers/action/biologic_server.py helao/hexagon/tests/checklists/hte/ helao/hexagon/tests/test_biologic_new_endpoints.py
git commit -m "feat(biologic): expose CALIMIT, CPLIMIT, SPEIS, SGEIS and run_plan on eclib

run_plan's guard widens to both SDK-backed backends; its _additions.json why
is amended rather than duplicated, since it claimed no sibling backend could
load a multi-technique experiment. The four new routes deliberately omit TTL
until the trigger's electrical leg is verified at a station.

Also corrects run_CV's docstring, which described a Cycles subtraction and an
AcqInterval__V derivation the body has never done.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 16: delete the easy-biologic dependency

**Files:**
- Modify: `helao_dev_win-64.yml:14`, `helao_dev_linux-64.yml:14`
- Modify: `helao/hexagon/tests/test_biologic_disconnected_construct.py`
- Modify: `helao/hexagon/tests/test_hte_builds_on_linux.py`
- Modify: `helao/hexagon/tests/test_hardware_import_sweep.py`
- Modify: `helao/deploy/hte/experiments/HISPEC_exp.py:507` (comment)

**Interfaces:** none new. This task removes.

**Prerequisite P1 must be complete before this lands.** After it, the runtime golden cannot be captured with the old driver.

- [ ] **Step 1: Rewrite the hermeticity test to assert the new invariant**

`test_biologic_disconnected_construct.py` currently asserts four times that importing the driver does not pull `easy_biologic`, and monkeypatches fake `easy_biologic` modules so the resolver works. All of that becomes meaningless. Replace with:

```python
"""Importing and constructing the driver touches no DLL and no SDK path.

`biologic_server.py` is imported on Linux by the build tests and by every
capture script, and a station running the OLE backend has EC-Lab but not
necessarily an EClib1 install. Construction must therefore reach neither.
"""

import sys

from helao.deploy.hte.drivers.pstat.biologic.driver import BiologicDriver


def test_importing_the_driver_loads_no_dll():
    import helao.deploy.hte.drivers.pstat.biologic.vendor as vendor

    assert "ctypes" in sys.modules  # the module, not a loaded library
    assert not hasattr(vendor, "_DLL")


def test_constructing_reads_no_sdk_path():
    d = BiologicDriver({"address": "10.0.0.1", "sdk_path": "/definitely/not/here"})
    assert d.ready is False
    assert d._client is None


def test_constructing_claims_no_channel():
    assert BiologicDriver({}).channel is None


def test_the_technique_registry_imports_without_an_sdk():
    from helao.deploy.hte.drivers.pstat.biologic.technique import BIOTECHS

    assert len(BIOTECHS) == 11


def test_the_server_module_imports_on_linux():
    import helao.deploy.hte.servers.action.biologic_server as server

    assert "eclib" in server.BACKENDS


def test_no_module_in_the_package_imports_easy_biologic():
    """The dependency is gone from both env files; an import would be a
    ModuleNotFoundError at a station, not a caught one."""
    import pathlib

    root = pathlib.Path("helao/deploy/hte/drivers/pstat/biologic")
    offenders = [
        p.name for p in root.glob("*.py") if "easy_biologic" in p.read_text()
    ]
    assert offenders == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_disconnected_construct.py -v`
Expected: FAIL on `test_no_module_in_the_package_imports_easy_biologic` only if a stray reference survives; the rest should already pass from Tasks 13–14. If `test_the_technique_registry_imports_without_an_sdk` reports a count other than 11, reconcile against `BIOTECHS` — the 11 are OCV, CA, CP, CV, PEIS, GEIS, CAOCV, CALIMIT, CPLIMIT, SPEIS, SGEIS.

- [ ] **Step 3: Remove the dependency**

Delete the `https://github.com/onepunchdan/easy-biologic/archive/main.zip` line from `helao_dev_win-64.yml` and `helao_dev_linux-64.yml`. Leave the surrounding `pip:` block intact.

Check `pyproject.toml:18`, which mentions easy-biologic in a comment explaining why some pins are not reproducible from PyPI; update that comment so it no longer lists a dependency the project does not have.

- [ ] **Step 4: Delete the tests that only existed because of the dependency**

In `test_hte_builds_on_linux.py`: delete the test at line 108 that fails if `easy_biologic` ever becomes importable on Linux, and the comment at line 54 explaining the lazy import. Keep the `BUILDS` entry `("biologic_server", "hispec", "PSTAT")` and keep `WINDOWS_ONLY` empty.

In `test_hardware_import_sweep.py`: update the comment at line 43 — the sweep no longer works around a Windows-only runtime for this module.

In `HISPEC_exp.py:507`: the comment reads "use easy_biologic's BiologicDevice.load_techniques() method" and describes unbuilt trigger actions. Reword to name `run_plan`, which is the in-repo way to do that now.

- [ ] **Step 5: Verify nothing references it**

Run: `grep -rn "easy_biologic\|easy-biologic" helao/ *.yml *.toml`
Expected: only the smoke-script narrative comments in `helao/hexagon/tests/smoke/` (`biologic_canary.bat`, `biologic_diff.bat`, `golden_capture_biologic.py`, the two smoke configs), which describe the pre-rewrite state and are Task 18's to update. Nothing under `helao/deploy/` or in either env file.

- [ ] **Step 6: Run the full hexagon suite per file**

Run: `for f in helao/hexagon/tests/test_*.py; do timeout 300 python -m pytest "$f" -q || echo "FAILED $f"; done`
Expected: no `FAILED` lines. Compare the failure set against `unstable`'s known-failing tests before blaming this branch — `test_hte_is_native::test_the_sweep_sees_every_module` and the whole-session-only failures in `test_adapter_transport`/`test_reflex_host` are pre-existing.

- [ ] **Step 7: Format and commit**

```bash
conda run -n helao black helao/hexagon/tests/test_biologic_disconnected_construct.py helao/hexagon/tests/test_hte_builds_on_linux.py
git status --short --branch
git add helao_dev_win-64.yml helao_dev_linux-64.yml pyproject.toml helao/hexagon/tests/ helao/deploy/hte/experiments/HISPEC_exp.py
git commit -m "chore(biologic)!: drop the easy-biologic dependency

Both env files lose the pinned fork archive. The hermeticity test that
asserted the driver did not import easy_biologic is replaced by one asserting
it loads no DLL and reads no sdk_path, and the test that failed if
easy_biologic ever became importable on Linux is deleted.

BREAKING: every BioLogic station moves to the direct EClib1 driver on its
next launch. Rollback is a revert of this branch's merge; there is no config
key. Requires the runtime golden to have been captured beforehand.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 17: the real-SDK gate and the extended column contract

**Files:**
- Create: `helao/hexagon/tests/test_biologic_vendor_real_sdk.py`
- Modify: `helao/hexagon/tests/test_biologic_column_contract.py`
- Test: both of the above

**Interfaces:** none new.

Two gates. The first is the one that catches a PDF that disagrees with the DLL — which for this vendor is the expected case, not the exception. The second makes the frozen column sets a claim two independent drivers satisfy rather than one driver's declaration.

- [ ] **Step 1: Write the real-SDK test**

```python
"""Assert the transcription against an actual EClib1 install.

Opt-in: set HELAO_ECLIB1_SDK_PATH to a directory containing EClib64.dll and
the .ecc set. Skipped everywhere else, which is every CI run and every Linux
box -- so it is a station's gate, not a build's.

Mirrors test_biologic_eclib2_vendor_real_sdk.py. The point is narrow and
important: every number and label in `vendor.py` and `technique.py` came from
a PDF whose text layer has already been caught disagreeing with the shipped
code twice in this driver family. This is where that gets checked against the
binary.
"""

import os
import pathlib

import pytest

from helao.deploy.hte.drivers.pstat.biologic import vendor
from helao.deploy.hte.drivers.pstat.biologic.technique import BIOTECHS

SDK = os.environ.get("HELAO_ECLIB1_SDK_PATH")
pytestmark = pytest.mark.skipif(not SDK, reason="HELAO_ECLIB1_SDK_PATH not set")


def test_the_dll_is_where_the_config_default_expects_it():
    assert (pathlib.Path(SDK) / vendor.DLL_NAME).is_file()


def test_every_export_in_the_api_table_exists_in_the_dll():
    """load_dll binds every name and raises VendorError on a missing one."""
    vendor.load_dll(SDK)


def test_every_ecc_file_every_technique_can_ask_for_is_present():
    missing = []
    for tech in BIOTECHS.values():
        for board in (
            vendor.BOARD_TYPE.ESSENTIAL,
            vendor.BOARD_TYPE.PREMIUM,
            vendor.BOARD_TYPE.DIGICORE,
        ):
            name = vendor.ecc_file(tech.ecc_stem, board)
            if not (pathlib.Path(SDK) / name).is_file():
                missing.append(name)
    assert missing == []


def test_the_trigger_and_loop_ecc_files_are_present():
    for stem in ("TI", "TO", "loop"):
        for board in (
            vendor.BOARD_TYPE.ESSENTIAL,
            vendor.BOARD_TYPE.PREMIUM,
            vendor.BOARD_TYPE.DIGICORE,
        ):
            assert (pathlib.Path(SDK) / vendor.ecc_file(stem, board)).is_file()


def test_the_firmware_blobs_this_driver_would_load_are_present():
    for board in (vendor.BOARD_TYPE.ESSENTIAL, vendor.BOARD_TYPE.PREMIUM):
        kernel, fpga = vendor.firmware_assets(board)
        assert (pathlib.Path(SDK) / kernel).is_file()
        if fpga:
            assert (pathlib.Path(SDK) / fpga).is_file()


def test_get_error_msg_agrees_with_the_transcribed_names():
    """The DLL will translate its own codes; the names are ours."""
    from helao.deploy.hte.drivers.pstat.biologic.eclib_client import EclibClient

    client = EclibClient(sdk_path=SDK, simulate=False)
    try:
        for code in sorted(vendor.ERROR_NAMES):
            if code == 0:
                continue
            message = client.error_message(code)
            assert message, f"{code} ({vendor.ERROR_NAMES[code]}) has no message"
    finally:
        client.close()


@pytest.mark.skipif(
    not os.environ.get("HELAO_ECLIB1_ADDRESS"),
    reason="HELAO_ECLIB1_ADDRESS not set; this half needs an instrument",
)
def test_every_declared_parameter_label_is_one_the_dll_knows():
    """BL_GetParamInfos reports a loaded technique's real parameter list.
    This is what catches easy-biologic's `Step_nuber`-class typo in our own
    tables. Needs a connected instrument, since parameters are read back off
    a channel that has the technique loaded."""
    pytest.skip(
        "Station procedure, not an assertion this test can make unattended: "
        "load each technique on an idle channel via /BIOLOGIC/run_<name> with "
        "a zero-duration parameter set, then compare BL_GetParamInfos' labels "
        "against BIOTECHS[<name>].param_table. Record the result in the "
        "at-station gate notes."
    )
```

Add `error_message(code)` to `EclibClient` — `BL_GetErrorMsg` into a 256-byte buffer — plus a sim-backed test in `test_biologic_eclib_client.py`.

- [ ] **Step 2: Extend the column contract**

`test_biologic_column_contract.py` today compares the eclib registry's `field_map` values against the OLE registry's column plan, with `ECLIB_DERIVED_IN_CODE = {"X_ohm", "R_ohm"}` patching over the two columns the old driver derived in code rather than declaring. Both of those are now in `data.COLUMNS`, so:

- Replace `declared_eclib(name)` with `set(BIOTECHS[name].column_plan)` and delete `ECLIB_DERIVED_IN_CODE` — the declaration is now complete, and keeping the patch would let a dropped `X_ohm` pass.
- Keep `test_the_dc_column_set_is_the_frozen_one` and `test_the_eis_column_set_is_the_frozen_one` exactly as they are.
- Add a live half for eclib, mirroring the OLE one: run each of the seven shared techniques against `sim` and assert the emitted keys equal the declared plan. The existing docstring already explains why both halves are needed; extend it to say the static half is now proven by two drivers rather than one.
- Add a test that the four new techniques' plans are declared but explicitly **not** part of the cross-backend contract — the OLE backend has no CALIMIT/CPLIMIT/SPEIS/SGEIS and is not expected to grow them.

- [ ] **Step 3: Run both**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_column_contract.py helao/hexagon/tests/test_biologic_vendor_real_sdk.py -v`
Expected: the contract file passes; the real-SDK file reports all tests skipped on Linux.

- [ ] **Step 4: Format and commit**

```bash
conda run -n helao black helao/hexagon/tests/test_biologic_vendor_real_sdk.py helao/hexagon/tests/test_biologic_column_contract.py helao/deploy/hte/drivers/pstat/biologic/eclib_client.py
git status --short --branch
git add helao/hexagon/tests/test_biologic_vendor_real_sdk.py helao/hexagon/tests/test_biologic_column_contract.py helao/deploy/hte/drivers/pstat/biologic/eclib_client.py helao/hexagon/tests/test_biologic_eclib_client.py
git commit -m "test(biologic): assert the transcription against a real SDK install

Opt-in on HELAO_ECLIB1_SDK_PATH: every export, every .ecc the registry can
ask for, every firmware blob, every error code. The column contract drops its
X_ohm/R_ohm patch because data.COLUMNS now declares them, and grows a live
eclib half so the frozen sets are satisfied by two drivers rather than
declared by one.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 18: at-station gate, smoke-script updates, and the CLAUDE.md entry

**Files:**
- Modify: `helao/hexagon/tests/smoke/golden_capture_biologic.py`
- Modify: `helao/hexagon/tests/smoke/biologic_diff.bat`, `biologic_canary.bat`
- Modify: `helao/hexagon/tests/smoke/configs/biologic.yml`, `biologichex.yml`
- Create: `docs/superpowers/notes/2026-09-17-biologic-eclib1-station-gate.md`
- Modify: `CLAUDE.md`

**Interfaces:** none. Documentation and the station procedure.

- [ ] **Step 1: Update the smoke scripts' narrative and mechanics**

`golden_capture_biologic.py`'s docstring describes `BiologicDriver.__init__` unconditionally calling `connect()` and opening an `easy_biologic.BiologicDevice`. The first has been false since P3a-2 and the second is false as of Task 16. Rewrite those paragraphs: the driver now constructs without I/O, `connect()` is called by the server at startup, and `simulate: true` on the server params gives a hardware-free run — so the "no data without an instrument" finding the docstring records no longer holds, and `run_OCV` can be exercised off-station. Keep the note that the *golden* still needs the instrument.

`biologic_diff.bat`'s comments at lines 9, 184 and 198 refer to easy-biologic holding the TCP connection and to clearing `connection_raised`. Replace with the current mechanism: the client owns the connection and `close()` releases it, and there is no `connection_raised` flag any more.

Both smoke configs' comments name easy-biologic as the backend; say EClib1 over TCP instead. Add `sdk_path` to `biologic.yml`'s `BIOLOGIC` params with the default path, and add a `simulate: true` variant note.

- [ ] **Step 2: Write the station gate note**

Create `docs/superpowers/notes/2026-09-17-biologic-eclib1-station-gate.md` with:

- The ordered gate: golden captured pre-merge (P1); freeze branch (P3); `run_OCV` golden diff; then `run_CA`, `run_CV`, `run_PEIS`, `run_GEIS` on a dummy cell with columns compared against pre-rewrite records.
- **The behaviour changes to look for, not just pass/fail.** Three, each with what to expect:
  - **EIS sweep spacing.** `SweepMode` now reaches the instrument. With the endpoint default of `"log"`, a PEIS run's `f_Hz` column should be logarithmically spaced between `Finit__Hz` and `Ffinal__Hz`; before this release it was linear regardless. A linear `f_Hz` after the merge means the coercion did not take.
  - **CAOCV voltage range.** `CA_ERange` now applies. With the default `AUTO`, the CA step's resolution may differ from records produced when a range derived from the voltage list was used.
  - **CV `Record_every_dE`.** Should still be `0.01` — no endpoint supplies `AcqInterval__V`, and Task 7 preserved easy-biologic's default. A different recording density means the default was dropped.
- **The two untested legs**, stated as untested: the TTL electrical path (needs a second instrument or a scope; the technique-list read-back proves only that the trigger loaded), and the four new techniques plus `run_plan`, which have no station reference at all — acceptance is "runs, terminates, columns present, limits observed".
- **The board family the gate station is not.** Per P2: whichever family the gate station does not report has its layout tables asserted against the PDF and `BL_GetParamInfos` but never against a record. First launch on the other family is a separate gate.
- The `BL_GetParamInfos` label comparison from Task 17 Step 1, written out as a station procedure with the commands.

- [ ] **Step 3: Update `CLAUDE.md`**

The "BioLogic potentiostats: two backends" section says the server serves seven technique endpoints from either of two drivers. It is now eleven techniques plus `run_plan` from either of **three** SDK-backed drivers plus the OLE one. Rewrite that section to:

- State the four backends and what selects them, keeping the existing `eclib`-is-default and unrecognized-value-raises facts.
- Replace "eclib (default, `drivers/pstat/biologic/`, via easy-biologic over TCP)" with the direct EClib1 description, and add `sdk_path`.
- Carry forward the traps worth keeping, each in one line: the DLL's channel index is 0-based and `kbio`'s `- 1` is that layer's own convention; board type drives both the `.ecc` suffix and the record layout; `SweepMode` reaches the instrument as of this release and did not before; `loop_N_times = -1` is refused; the `Test*_Config` bitfield is transcribed from the rendered PDF page because its text layer is ambiguous; nothing from `Examples/Python/kbio/` may be vendored.
- Keep the existing OLE and eclib2 subsections unchanged.

- [ ] **Step 4: Verify the docs describe the code**

Run: `grep -n "easy-biologic\|easy_biologic" CLAUDE.md`
Expected: no hits except, if you choose to keep it, one historical note that the backend used to wrap it.

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_biologic_new_endpoints.py -q`
Expected: PASS — confirms the endpoint count CLAUDE.md now claims.

- [ ] **Step 5: Format and commit**

```bash
git status --short --branch
git add helao/hexagon/tests/smoke/ docs/superpowers/notes/2026-09-17-biologic-eclib1-station-gate.md CLAUDE.md
git commit -m "docs(biologic): station gate, and CLAUDE.md for four backends

The gate note names the three behaviour changes to look for rather than just
pass/fail, and states the two legs that stay untested: the TTL electrical
path, and the four new techniques which have no station reference.

The smoke scripts' docstrings described a constructor-connect fixed in P3a-2
and an easy-biologic connection that no longer exists.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

Checked against the spec:

- **Spec §3 architecture** — Tasks 1–14 create all seven modules. §3's three consequences (hermetic `enum.py`, no `blfind64.dll`, no vendor assets committed) are Task 2, Task 1's `test_blfind_is_not_in_the_api_table`, and the Global Constraints bullet plus Task 1's docstring.
- **Spec §4 technique layer** — Tasks 7–12. All 11 techniques, TTL bracketing with read-back, LOOP with the entry-to-loaded index mapping, the `-1` refusal, the per-technique `Step_number` conventions, the `Test*_Config` encoder.
- **Spec §5 data layer** — Tasks 5–6. Board-family mapping, all five layout differences, vendor time conversion, signed `P_W`, the three-part done-detection, `IRQskipped`, frozen columns.
- **Spec §6 defects** — 6.1 Task 6; 6.2 Task 9 + Task 14 Step 4; 6.3 Task 13 (all four sub-items); 6.4 Tasks 1, 5, 13; 6.5 Tasks 5, 12, 17; 6.6 Task 4 + Task 14's event-loop test; 6.7 Tasks 4, 13.
- **Spec §7 lifecycle** — Tasks 13–14.
- **Spec §8 testing and gates** — Tasks 3, 17, 18; §8.1's sequencing is Prerequisites P1–P3 plus Task 16's gate note and Task 18's ordered list; §8.2's three gaps are all in Task 18 Step 2; §8.3's conventions are Global Constraints plus Task 14 Step 6.

Two spec items that gained scope during planning, both recorded in the tasks that found them and neither in the spec: the `SweepMode` coercion defect (Task 8 — the spec predates it) and CAOCV's `CA_ERange` override (Task 11). **Amend the spec** to add both as §6.8 and §6.9 before starting Task 1, so the spec and plan do not disagree about what this change does.

Placeholder scan: no `TBD`/`TODO`/"similar to Task N". Two deliberate read-the-source steps carry explicit commands and a named artifact to read, rather than describing work to invent: Task 1 Step 5 (error codes against the PDF) and Task 12 Step 1 (the bitfield off a rendered page). Task 17's `test_every_declared_parameter_label_is_one_the_dll_knows` is a `pytest.skip` with the station procedure in its message, which is honest about what an unattended test cannot assert.

Type consistency: `to_single(word, board_type)` and `to_seconds(t_high, t_low, timebase, board_type)` keep those signatures in Tasks 4, 5 and 14. `LoadStep`/`LoadPlan`/`plan_for` are introduced in Task 9 and consumed unchanged in 10, 11 and 14. `entries(technique, action_params)` is Task 7's and is called in 8–12. `data.COLUMNS` is Task 5's and is read by `column_plan` in 7, 10, 11, 12 and by the contract test in 17. `sim.SimConfig` grows fields in Tasks 13 and 14, each with its own sim test.

One correction to make while transcribing: Task 11's `test_ca_erange_auto_is_not_replaced_by_a_derived_range` contains a garbled expression; the task says to write it as `ca = params_of(plan(CA_ERange="AUTO").steps[0])`.

## Global Constraints — addendum

- **Commit messages end with both attribution lines**, in this order:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01SunVypAxwHpNJ1ocfUKccE
  ```
  The commit blocks in Tasks 1–18 show the first line only; append the second.
