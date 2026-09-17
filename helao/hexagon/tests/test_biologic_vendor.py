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


def test_param_type_values_match_the_pdf():
    assert (vendor.PARAM_INT, vendor.PARAM_BOOLEAN, vendor.PARAM_SINGLE) == (0, 1, 2)


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


def test_error_names_corrected_against_the_pdf():
    """PDF §5.4 corrections: the brief's draft table put communication,
    firmware and technique codes at the wrong hundreds offset (-101/-200/-300
    instead of -200/-300/-400) and missed the -101..-105 instrument family
    entirely; -14 and -15 also had the wrong constant name."""
    assert vendor.ERROR_NAMES[-7] == "ERR_GEN_NOCHANNELELECTED"
    assert vendor.ERROR_NAMES[-14] == "ERR_GEN_DEVICE_NOTALLOWED"
    assert vendor.ERROR_NAMES[-15] == "ERR_GEN_UPDATEPARAMETERS"
    assert vendor.ERROR_NAMES[-101] == "ERR_INSTR_VMEERROR"
    assert vendor.ERROR_NAMES[-200] == "ERR_COMM_COMMFAILED"
    assert vendor.ERROR_NAMES[-300] == "ERR_FIRM_FIRMFILENOTEXISTS"
    assert vendor.ERROR_NAMES[-400] == "ERR_TECH_ECCFILENOTEXISTS"


def test_import_loads_no_dll():
    """`biologic_server.py` imports this module on Linux."""
    import sys

    assert "helao.deploy.hte.drivers.pstat.biologic.vendor" in sys.modules
    assert vendor.load_dll.__module__ == vendor.__name__


def test_load_dll_reports_the_path_it_could_not_find(tmp_path):
    with pytest.raises(vendor.VendorError, match=str(tmp_path)):
        vendor.load_dll(str(tmp_path))
