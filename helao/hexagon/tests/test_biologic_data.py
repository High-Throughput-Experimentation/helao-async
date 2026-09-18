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
    assert names(vendor.TECH_ID.OCV, VMP3) == [
        "t_high",
        "t_low",
        "voltage",
        "voltage_ce",
    ]
    assert names(vendor.TECH_ID.OCV, VMP300) == ["t_high", "t_low", "voltage"]


def test_ocv_fourth_vmp3_column_is_ece_not_control():
    """easy-biologic names it `control`; PDF section 7.2.3 says Ece."""
    assert names(vendor.TECH_ID.OCV, VMP3)[3] == "voltage_ce"


def test_cv_has_a_leading_control_column_on_vmp3_only():
    assert names(vendor.TECH_ID.CV, VMP3) == [
        "t_high",
        "t_low",
        "control",
        "current",
        "voltage",
        "cycle",
    ]
    assert names(vendor.TECH_ID.CV, VMP300) == [
        "t_high",
        "t_low",
        "current",
        "voltage",
        "cycle",
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
        "t_high",
        "t_low",
        "voltage",
        "current",
        "cycle",
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
        "t_high",
        "t_low",
        "voltage",
        "current",
        "step",
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
        "process",
        "t_s",
        "Ewe_V",
        "I_A",
        "AbsEwe_V",
        "AbsI_A",
        "phase",
        "modulus",
        "Ece_V",
        "AbsEce_V",
        "AbsIce_A",
        "phase_ce",
        "modulus_ce",
        "f_Hz",
        "X_ohm",
        "R_ohm",
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
        0,
        1000,
        sim.encode_single(9.9),  # control / Ec
        sim.encode_single(3e-3),  # <I>
        sim.encode_single(0.7),  # <Ewe>
        4,
    ]
    info = Info(vendor.TECH_ID.CV, rows=1, cols=6)
    out = data.decode(
        "CV",
        info,
        Values(),
        records,
        to_single,
        to_seconds,
        vendor.BOARD_TYPE.ESSENTIAL,
    )
    assert out["Ewe_V"] == pytest.approx([0.7])
    assert out["I_A"] == pytest.approx([3e-3])
    assert out["cycle"] == [4]


def test_control_is_decoded_but_not_emitted():
    """It has no frozen column; emitting it would change the recorded set."""
    assert "control" not in data.COLUMNS["CV"]


def eis_p1_record(
    freq, abs_ewe, abs_i, phase, ewe, i, abs_ece, abs_ice, phase_ce, ece, t
):
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
    records = eis_p1_record(
        1000.0, 0.02, 0.004, phase, 0.3, 0.004, 0.01, 0.004, 0.1, 0.2, 7.5
    )
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
    out = data.decode(
        "SPEIS", info, Values(1e-3), records, to_single, to_seconds, BOARD
    )
    assert out["step"] == [3]
