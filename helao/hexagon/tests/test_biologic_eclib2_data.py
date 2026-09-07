"""EClib2 row structs -> HELAO's emitted columns.

This is the parity gate that makes the EClib2 backend a drop-in: the column
names are the ones ``biologic/technique.py``'s ``field_map`` values already
publish to the visualizers and experiments, and several of them do not exist in
EClib2 at all -- ``P_W``, ``modulus``, ``modulus_ce``, ``X_ohm``, ``R_ohm`` and
``process`` are all derived here, exactly as easy-biologic derived them.

Rows are duck-typed on attribute names, so these tests use plain stand-ins
rather than the vendor dataclasses (which need the SDK to import).
"""

import math
from dataclasses import dataclass

import pytest

from helao.deploy.hte.drivers.pstat.biologic_eclib2 import data as ec2data


@dataclass
class FakeOcv:
    time: float
    ewe: float


@dataclass
class FakeStep:
    """Stands in for CaData / CpData / CvData.

    Note the vendor Python layer names these ``ewe_average``/``i_average`` on
    all three, even though the HTML docs call the CA/CP ones ``ewe``/``i``.
    """

    time: float
    ewe_average: float
    i_average: float
    cycle: int


@dataclass
class FakeEis:
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


def test_ocv_rows_emit_only_the_two_columns_eclib1_emitted():
    table = ec2data.ocv_rows([FakeOcv(0.0, 1.5), FakeOcv(0.1, 1.6)])
    assert table == {"t_s": [0.0, 0.1], "Ewe_V": [1.5, 1.6]}


def test_step_rows_derive_power_which_eclib2_does_not_report():
    table = ec2data.step_rows(
        [FakeStep(0.0, 2.0, 0.5, 0), FakeStep(0.1, 3.0, -0.25, 1)]
    )
    assert table["t_s"] == [0.0, 0.1]
    assert table["Ewe_V"] == [2.0, 3.0]
    assert table["I_A"] == [0.5, -0.25]
    assert table["cycle"] == [0, 1]
    # P_W is Ewe * I, sign included -- easy-biologic reported it and the
    # visualizers read it.
    assert table["P_W"] == [1.0, -0.75]


def test_step_rows_emit_exactly_the_eclib1_step_columns():
    table = ec2data.step_rows([FakeStep(0.0, 1.0, 1.0, 0)])
    assert set(table) == {"t_s", "Ewe_V", "I_A", "P_W", "cycle"}


def test_eis_rows_map_every_field_map_column():
    row = FakeEis(
        frequency=1000.0,
        mod_ewe=0.02,
        mod_iwe=0.004,
        phase_we=0.5,
        ewe_dc=0.3,
        iwe_dc=0.001,
        e_range_we=5.0,
        mod_ece=0.04,
        mod_ice=0.008,
        phase_ce=-0.25,
        ece_dc=0.6,
        ice_dc=0.002,
        e_range_ce=5.0,
        time_in_s=12.5,
    )
    table = ec2data.eis_rows([row])
    assert table["f_Hz"] == [1000.0]
    assert table["t_s"] == [12.5]
    assert table["Ewe_V"] == [0.3]
    assert table["I_A"] == [0.001]
    assert table["AbsEwe_V"] == [0.02]
    assert table["AbsI_A"] == [0.004]
    assert table["phase"] == [0.5]
    assert table["Ece_V"] == [0.6]
    assert table["AbsEce_V"] == [0.04]
    assert table["AbsIce_A"] == [0.008]
    assert table["phase_ce"] == [-0.25]
    # |Z| is not an EClib2 field; it is |Ewe| / |I|.
    assert table["modulus"] == [pytest.approx(5.0)]
    assert table["modulus_ce"] == [pytest.approx(5.0)]
    # An EIS row is frequency-domain, which is what process 1 meant in EClib1.
    assert table["process"] == [1]


def test_eis_rows_derive_the_cartesian_impedance_the_driver_used_to_add():
    table = ec2data.eis_rows(
        [
            FakeEis(
                1.0, 0.02, 0.004, 0.5, 0.0, 0.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5.0, 0.0
            )
        ]
    )
    assert table["R_ohm"] == [pytest.approx(5.0 * math.cos(0.5))]
    assert table["X_ohm"] == [pytest.approx(-5.0 * math.sin(0.5))]


def test_a_zero_current_modulus_yields_nan_rather_than_raising():
    # At very low signal |I| can come back as exactly 0. easy-biologic's
    # divide produced inf/nan; raising here would abort a live acquisition
    # over one bad row.
    table = ec2data.eis_rows(
        [FakeEis(1.0, 0.02, 0.0, 0.5, 0.0, 0.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5.0, 0.0)]
    )
    assert math.isnan(table["modulus"][0])
    assert math.isnan(table["modulus_ce"][0])
    assert math.isnan(table["R_ohm"][0])
    assert math.isnan(table["X_ohm"][0])


def test_eis_rows_emit_exactly_the_eclib1_eis_columns():
    table = ec2data.eis_rows(
        [FakeEis(1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 5.0, 1.0, 1.0, 0.0, 0.0, 0.0, 5.0, 0.0)]
    )
    assert set(table) == set(ec2data.EIS_COLUMNS)


def test_empty_rows_still_yield_the_full_column_set():
    # A poll that returns no rows must not change the shape of the emitted
    # table, or a consumer keyed on columns sees them appear and disappear.
    assert ec2data.ocv_rows([]) == {c: [] for c in ec2data.OCV_COLUMNS}
    assert ec2data.step_rows([]) == {c: [] for c in ec2data.STEP_COLUMNS}
    assert ec2data.eis_rows([]) == {c: [] for c in ec2data.EIS_COLUMNS}


def test_concat_pads_missing_columns_so_a_composite_is_one_table():
    # PEIS in EClib2 is sweep-only; its DC bias comes from a CA technique run
    # just before it in the same experiment. EClib1 emitted both legs as one
    # table with a `process` flag, so the composite has to be reassembled.
    ca = ec2data.step_rows([FakeStep(0.0, 0.3, 0.001, 0)])
    eis = ec2data.eis_rows(
        [
            FakeEis(
                1.0,
                0.02,
                0.004,
                0.5,
                0.3,
                0.001,
                5.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                5.0,
                1.0,
            )
        ]
    )
    table = ec2data.concat([ca, eis], columns=ec2data.EIS_COLUMNS)

    assert set(table) == set(ec2data.EIS_COLUMNS)
    assert all(len(v) == 2 for v in table.values())
    # The CA leg is the time-domain leg: process 0, no frequency.
    assert table["process"] == [0, 1]
    assert math.isnan(table["f_Hz"][0])
    assert table["f_Hz"][1] == 1.0
    # Columns both legs share carry real values in both rows.
    assert table["t_s"] == [0.0, 1.0]
    assert table["Ewe_V"] == [0.3, 0.3]


def test_concat_marks_a_leg_without_a_process_column_as_time_domain():
    ca = ec2data.step_rows([FakeStep(0.0, 0.3, 0.001, 0)])
    assert "process" not in ca
    table = ec2data.concat([ca], columns=ec2data.EIS_COLUMNS)
    assert table["process"] == [0]


def test_concat_drops_columns_outside_the_requested_contract():
    # CAOCV publishes the step columns only; an OCV leg's extra columns (there
    # are none) and a step leg's must not widen the emitted table.
    ocv = ec2data.ocv_rows([FakeOcv(0.0, 1.5)])
    ca = ec2data.step_rows([FakeStep(0.1, 0.3, 0.001, 0)])
    table = ec2data.concat([ca, ocv], columns=ec2data.STEP_COLUMNS)
    assert set(table) == set(ec2data.STEP_COLUMNS)
    assert table["t_s"] == [0.1, 0.0]
    # OCV reports no current, so the OCV row's I_A/P_W/cycle are absent.
    assert table["I_A"][0] == 0.001
    assert math.isnan(table["I_A"][1])
    assert math.isnan(table["P_W"][1])


def test_concat_of_nothing_is_an_empty_table_of_the_right_shape():
    assert ec2data.concat([], columns=ec2data.STEP_COLUMNS) == {
        c: [] for c in ec2data.STEP_COLUMNS
    }


def test_the_column_contract_matches_the_eclib1_backend_exactly():
    # Spelled out rather than imported from biologic/technique.py, which pulls
    # in biologic/enum.py and thus easy_biologic at import time. If the EClib1
    # field_map ever changes, this is the test that should fail.
    assert set(ec2data.OCV_COLUMNS) == {"t_s", "Ewe_V"}
    assert set(ec2data.STEP_COLUMNS) == {"t_s", "Ewe_V", "I_A", "P_W", "cycle"}
    assert set(ec2data.EIS_COLUMNS) == {
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
        # Derived by the EClib1 driver's get_data, not by its field_map.
        "X_ohm",
        "R_ohm",
    }
