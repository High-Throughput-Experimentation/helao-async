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
    steps = [
        (label, value, index) for label, value, index in got if label == "Voltage_step"
    ]
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
    """CA's step arrays are 100-wide (PDF 7.6.2), not 20 -- see M1."""
    with pytest.raises(TechniqueError, match="100"):
        flat("CA", Vval__V=[0.1] * 101, Tval__s=[1.0] * 101)


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


def test_ocv_time_interval_default_is_the_one_easy_biologic_supplied():
    """easy-biologic's OCV.__init__ defaults time_interval=1."""
    assert BIOTECHS["OCV"].defaults["AcqInterval__s"] == 1.0


def test_ocv_sends_no_hardware_range_parameters():
    """The endpoint exposes none, and OCV never drives the cell."""
    labels = {label for label, _, _ in flat("OCV", Tval__s=1.0)}
    assert not labels & {"I_Range", "E_Range", "Bandwidth"}


# --- CA ---------------------------------------------------------------------


def test_ca_time_interval_default_is_the_one_easy_biologic_supplied():
    """easy-biologic's CA.__init__ defaults time_interval=1.0."""
    assert BIOTECHS["CA"].defaults["AcqInterval__s"] == 1.0


def test_ca_current_interval_default_is_the_one_easy_biologic_supplied():
    """easy-biologic's CA.__init__ defaults current_interval=1e-3."""
    assert BIOTECHS["CA"].defaults["AcqInterval__A"] == 1e-3


def test_ca_vs_initial_default_is_the_one_easy_biologic_supplied():
    assert BIOTECHS["CA"].defaults["vs_initial"] is False


def test_ca_n_cycles_default_is_the_one_easy_biologic_supplied():
    assert BIOTECHS["CA"].defaults["N_Cycles"] == 0


def test_ca_wraps_the_scalar_step_and_sets_step_number_to_len_minus_one():
    got = built(
        "CA", Vval__V=0.7, Tval__s=3.0, AcqInterval__s=0.01, AcqInterval__A=10.0
    )
    assert got["Voltage_step"] == [0.7]
    assert got["Duration_step"] == [3.0]
    assert got["vs_initial"] == [False]
    assert got["Step_number"] == 0
    assert got["N_Cycles"] == 0
    assert got["Record_every_dT"] == 0.01
    assert got["Record_every_dI"] == 10.0


def test_ca_and_cp_step_arrays_are_100_wide_but_the_limit_variants_stay_20():
    """PDF 7.6.2 (CA) and 7.5 (CP) are `Array of 100`; CALIMIT (7.37) and
    CPLIMIT (7.36) are `Array of 20`. A shared width would either truncate a
    long CA/CP profile or over-declare the limit variants."""
    for label in ("Voltage_step", "vs_initial", "Duration_step"):
        assert BIOTECHS["CA"].param_table[label].arity == 100
    for label in ("Current_step", "vs_initial", "Duration_step"):
        assert BIOTECHS["CP"].param_table[label].arity == 100
    for label in ("Voltage_step", "vs_initial", "Duration_step"):
        assert BIOTECHS["CALIMIT"].param_table[label].arity == 20
    for label in ("Current_step", "vs_initial", "Duration_step"):
        assert BIOTECHS["CPLIMIT"].param_table[label].arity == 20


def test_ca_maps_the_three_range_enums_to_vendor_ints():
    got = built(
        "CA",
        Vval__V=0.0,
        Tval__s=1.0,
        AcqInterval__s=0.01,
        AcqInterval__A=10.0,
        IRange="m10",
        ERange="v5",
        Bandwidth="BW7",
    )
    assert got["I_Range"] == vendor.I_RANGE.I_RANGE_10mA
    assert got["E_Range"] == vendor.E_RANGE.E_RANGE_5V
    assert got["Bandwidth"] == vendor.BANDWIDTH.BW_7


def test_ca_accepts_a_list_of_steps_and_keeps_the_arrays_aligned():
    got = built(
        "CA",
        Vval__V=[0.1, 0.2, 0.3],
        Tval__s=[1.0, 2.0, 3.0],
        AcqInterval__s=0.01,
        AcqInterval__A=10.0,
    )
    assert got["Voltage_step"] == [0.1, 0.2, 0.3]
    assert got["Duration_step"] == [1.0, 2.0, 3.0]
    assert got["vs_initial"] == [False, False, False]
    assert got["Step_number"] == 2


def test_ca_refuses_mismatched_step_and_duration_lists():
    """The DLL would run the steps it has durations for and stop, silently."""
    with pytest.raises(TechniqueError, match="Duration_step"):
        built(
            "CA",
            Vval__V=[0.1, 0.2],
            Tval__s=[1.0],
            AcqInterval__s=0.01,
            AcqInterval__A=10.0,
        )


# --- CP ---------------------------------------------------------------------


def test_cp_time_interval_default_is_the_one_easy_biologic_supplied():
    """easy-biologic's CP.__init__ defaults time_interval=1.0."""
    assert BIOTECHS["CP"].defaults["AcqInterval__s"] == 1.0


def test_cp_voltage_interval_default_is_the_one_easy_biologic_supplied():
    """easy-biologic's CP.__init__ defaults voltage_interval=1e-3."""
    assert BIOTECHS["CP"].defaults["AcqInterval__V"] == 1e-3


def test_cp_vs_initial_default_is_the_one_easy_biologic_supplied():
    assert BIOTECHS["CP"].defaults["vs_initial"] is False


def test_cp_n_cycles_default_is_the_one_easy_biologic_supplied():
    assert BIOTECHS["CP"].defaults["N_Cycles"] == 0


def test_cp_sends_current_steps_and_records_on_potential():
    got = built(
        "CP", Ival__A=1e-3, Tval__s=4.0, AcqInterval__s=0.01, AcqInterval__V=0.001
    )
    assert got["Current_step"] == [1e-3]
    assert got["Duration_step"] == [4.0]
    assert got["Step_number"] == 0
    assert got["Record_every_dE"] == 0.001
    assert "Record_every_dI" not in got


def test_cp_does_not_derive_the_current_range_from_the_step():
    """easy-biologic's set_current_range() only warns when a range is given,
    and the endpoint always gives one -- so this path was already dead."""
    got = built(
        "CP",
        Ival__A=5.0,
        Tval__s=1.0,
        AcqInterval__s=0.01,
        AcqInterval__V=0.001,
        IRange="u10",
    )
    assert got["I_Range"] == vendor.I_RANGE.I_RANGE_10uA


# --- CV ---------------------------------------------------------------------


def test_cv_builds_the_five_point_profile_in_pdf_order():
    """PDF section 7.3.2: Voltage_step is [Ei, E1, E2, Ei, Ef]."""
    got = built(
        "CV",
        Vinit__V=0.0,
        Vapex1__V=1.0,
        Vapex2__V=-1.0,
        Vfinal__V=0.2,
        ScanRate__V_s=0.05,
        AcqInterval__s=0.1,
        Cycles=3,
    )
    assert got["Voltage_step"] == [0.0, 1.0, -1.0, 0.0, 0.2]
    assert got["Scan_Rate"] == [0.05] * 5
    assert got["vs_initial"] == [False] * 5


def test_cv_scan_number_is_the_fixed_two_the_pdf_requires():
    got = built(
        "CV",
        Vinit__V=0.0,
        Vapex1__V=1.0,
        Vapex2__V=-1.0,
        Vfinal__V=0.0,
        ScanRate__V_s=1.0,
        AcqInterval__s=0.1,
        Cycles=1,
    )
    assert got["Scan_number"] == 2


def test_cv_passes_cycles_through_without_subtracting():
    """The endpoint docstring claims it subtracts one; the body does not, and
    four stations' data was produced without the subtraction."""
    got = built(
        "CV",
        Vinit__V=0.0,
        Vapex1__V=1.0,
        Vapex2__V=-1.0,
        Vfinal__V=0.0,
        ScanRate__V_s=1.0,
        AcqInterval__s=0.1,
        Cycles=4,
    )
    assert got["N_Cycles"] == 4


def test_cv_record_every_de_falls_back_to_the_easy_biologic_default():
    """No endpoint supplies AcqInterval__V for CV, so every CV ever run used
    easy-biologic's 0.01."""
    got = built(
        "CV",
        Vinit__V=0.0,
        Vapex1__V=1.0,
        Vapex2__V=-1.0,
        Vfinal__V=0.0,
        ScanRate__V_s=1.0,
        AcqInterval__s=0.1,
        Cycles=1,
    )
    assert got["Record_every_dE"] == 0.01


def test_cv_measurement_window_defaults_match_easy_biologic():
    got = built(
        "CV",
        Vinit__V=0.0,
        Vapex1__V=1.0,
        Vapex2__V=-1.0,
        Vfinal__V=0.0,
        ScanRate__V_s=1.0,
        AcqInterval__s=0.1,
        Cycles=1,
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
        "CV",
        Vinit__V=0.0,
        Vapex1__V=1.0,
        Vapex2__V=-1.0,
        Vfinal__V=0.0,
        ScanRate__V_s=0.02,
        AcqInterval__s=0.1,
        Cycles=1,
    )
    assert got["Scan_Rate"] == [0.02] * 5
