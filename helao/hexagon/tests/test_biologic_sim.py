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


def test_fail_on_takes_effect_on_an_already_bound_call():
    """`fail_on` must be resolved per call, not cached the first time a name
    is bound -- an already-connected driver that calls `set_sim_config` after
    it has a live `FakeDll` (as a fault-injection test would) must still see
    the injected failure on its next call through that same name."""
    dll = sim.load_dll()
    idn, _ = connect(dll)
    parms = vendor.EccParams(0, None)
    assert dll["BL_LoadTechnique"](idn, 0, b"ca4.ecc", parms, True, True, False) == 0
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_LoadTechnique": -300}))
    assert dll["BL_LoadTechnique"](idn, 0, b"ca4.ecc", parms, True, True, False) == -300


def test_config_changes_after_connect_take_effect_immediately():
    """Every `SimConfig` field is read live, not just `fail_on` -- a test
    connects, loads a technique and starts a run, then perturbs config (here,
    `rows_per_poll`) on the same already-bound driver without reconnecting."""
    dll = sim.load_dll()
    idn, _ = connect(dll)
    parms = vendor.EccParams(0, None)
    dll["BL_LoadTechnique"](idn, 0, b"ca4.ecc", parms, True, True, False)
    dll["BL_StartChannel"](idn, 0)

    sim.set_sim_config(sim.SimConfig(rows_per_poll=3))

    buf, di, cv = vendor.DataBuffer(), vendor.DataInfo(), vendor.CurrentValues()
    dll["BL_GetData"](idn, 0, buf, ctypes.byref(di), ctypes.byref(cv))
    assert di.NbRows == 3


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
    assert (
        dll["BL_DefineSglParameter"](b"Duration_step", 2.5, 0, ctypes.byref(parm)) == 0
    )
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
    assert (
        dll["BL_ConvertTimeChannelNumericIntoSeconds"](
            words, ctypes.byref(out), ctypes.c_float(1e-3), 2
        )
        == 0
    )
    assert out.value == pytest.approx(1.0)


def test_convert_time_composes_both_words_before_scaling():
    """t_high and t_low are the two halves of one 64-bit tick count, composed
    before scaling -- not a raw tick added to a separately-scaled one."""
    dll = sim.load_dll()
    words = (ctypes.c_uint32 * 2)(1, 0)  # t_high=1, t_low=0
    out = ctypes.c_double()
    assert (
        dll["BL_ConvertTimeChannelNumericIntoSeconds"](
            words, ctypes.byref(out), ctypes.c_float(1e-3), 2
        )
        == 0
    )
    assert out.value == pytest.approx((1 << 32) * 1e-3)


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


def test_firmware_loads_are_counted():
    dll = sim.load_dll()
    idn = ctypes.c_int32()
    info = vendor.DeviceInfo()
    dll["BL_Connect"](b"1.2.3.4", 5, ctypes.byref(idn), ctypes.byref(info))
    chans, results = vendor.ChannelsArray(), vendor.ResultsArray()
    chans[0] = True
    assert sim.firmware_loads() == 0
    dll["BL_LoadFirmware"](
        idn.value,
        chans,
        results,
        len(results),
        False,
        True,
        b"kernel4.bin",
        b"vmp_iv_0395_aa.xlx",
    )
    assert sim.firmware_loads() == 1
