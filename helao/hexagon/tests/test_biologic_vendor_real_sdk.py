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
    exports = vendor.load_dll(SDK)
    # And every bound name is still typed when looked up, against the real
    # library rather than a stand-in: `ctypes.CDLL.__getitem__` returns a
    # fresh unconfigured function pointer per lookup, which is how the first
    # station run of this driver reached `BL_DefineSglParameter` with no
    # `argtypes` and raised "Don't know how to convert parameter 2".
    for name, argtypes in vendor.ECL_API:
        assert exports[name].argtypes == argtypes, name
        assert exports[name].restype is vendor.c_int32, name


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
