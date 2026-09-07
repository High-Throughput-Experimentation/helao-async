"""HELAO action params -> an ordered EClib2 technique plan.

``build_plan`` is declarative on purpose: it emits parameter *names* and values
and never touches the SDK, so the whole mapping is testable on Linux and the
executor (:mod:`sdk_client`) stays a dumb interpreter.

The plan is a *list* of techniques because two of the seven HELAO techniques do
not exist as single EClib2 techniques:

- PEIS/GEIS in EClib2 are sweep-only. Their DC bias and time-domain leg come
  from a CA/CP technique added just before them in the same experiment, which
  is what the vendor's own PEIS example does.
- CAOCV was an easy-biologic composite, never a vendor technique; it becomes CA
  then OCV.
"""

import pytest

from helao.hexagon.tests.biologic_eclib2_sample_params import params as _params
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import data as ec2data
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import technique as ec2tech


def _by_name(plan_tech, name):
    return [p for p in plan_tech.params if p.name == name]


def _one(plan_tech, name):
    hits = _by_name(plan_tech, name)
    assert len(hits) == 1, f"expected exactly one {name}, got {len(hits)}"
    return hits[0]


def test_the_registry_covers_exactly_the_eclib1_technique_set():
    assert set(ec2tech.TECHNIQUE_NAMES) == {
        "OCV",
        "CA",
        "CP",
        "CV",
        "PEIS",
        "GEIS",
        "CAOCV",
    }


def test_an_unknown_technique_raises():
    with pytest.raises(ValueError, match="VSCAN"):
        ec2tech.build_plan("VSCAN", {})


# --------------------------------------------------------------------------
# single-technique plans
# --------------------------------------------------------------------------


def test_ocv_is_one_technique_reading_the_ocv_columns():
    plan = ec2tech.build_plan("OCV", _params("OCV"))
    assert len(plan.techniques) == 1
    (ocv,) = plan.techniques
    assert ocv.identifier == "EC_SDK_TECHNIQUE_OCV"
    assert ocv.reader == "ocv"
    assert plan.columns == ec2data.OCV_COLUMNS
    assert _one(ocv, "EC_SDK_REST_TIME_IN_S").value == 2.0
    # Both record triggers are float *arrays* in the vendor Python layer, even
    # though the technique doc table calls them plain floats.
    assert _one(ocv, "EC_SDK_RECORD_EVERY_DT").value == [0.1]
    assert _one(ocv, "EC_SDK_RECORD_EVERY_DE").value == [10.0]
    assert _one(ocv, "EC_SDK_RECORD_EVERY_DT").kind == "float_array"


def test_ca_broadcasts_a_scalar_step_and_sets_step_number_as_count_minus_one():
    plan = ec2tech.build_plan("CA", _params("CA"))
    (ca,) = plan.techniques
    assert ca.identifier == "EC_SDK_TECHNIQUE_CA"
    assert ca.reader == "step"
    assert plan.columns == ec2data.STEP_COLUMNS
    assert _one(ca, "EC_SDK_VOLTAGE_STEP_IN_V").value == [0.5]
    assert _one(ca, "EC_SDK_DURATION_STEP_IN_S").value == [1.0]
    # "Number of step minus 1", per the CA parameter table.
    assert _one(ca, "EC_SDK_STEP_NUMBER").value == 0
    assert _one(ca, "EC_SDK_VS_INITIAL").value == ["EC_SDK_VS_EREF"]


def test_ca_accepts_a_multi_step_list():
    plan = ec2tech.build_plan(
        "CA", _params("CA", Vval__V=[0.2, 0.4, 0.6], Tval__s=[1.0, 2.0, 3.0])
    )
    (ca,) = plan.techniques
    assert _one(ca, "EC_SDK_VOLTAGE_STEP_IN_V").value == [0.2, 0.4, 0.6]
    assert _one(ca, "EC_SDK_STEP_NUMBER").value == 2
    assert _one(ca, "EC_SDK_VS_INITIAL").value == ["EC_SDK_VS_EREF"] * 3


def test_mismatched_step_and_duration_lengths_raise():
    # Silently zipping to the shorter list would drop a requested step, or run
    # one for the wrong duration.
    with pytest.raises(ValueError, match="same length"):
        ec2tech.build_plan("CA", _params("CA", Vval__V=[0.2, 0.4], Tval__s=[1.0]))


def test_ca_pins_the_per_step_array_mode_flags_it_actually_supplies():
    plan = ec2tech.build_plan("CA", _params("CA"))
    (ca,) = plan.techniques
    # A single dt for all steps -> array mode off. The real member name is
    # ..._ARRAY_MODE; the docs' "EC_SDK_RECORD_EVERY_DT_MODE" does not exist.
    assert _one(ca, "EC_SDK_RECORD_EVERY_DT_ARRAY_MODE").value is False
    assert _one(ca, "EC_SDK_RECORD_EVERY_DI_ARRAY_MODE").value is False


def test_ca_turns_on_array_mode_when_given_one_interval_per_step():
    plan = ec2tech.build_plan(
        "CA",
        _params(
            "CA",
            Vval__V=[0.2, 0.4],
            Tval__s=[1.0, 1.0],
            AcqInterval__s=[0.01, 0.02],
        ),
    )
    (ca,) = plan.techniques
    assert _one(ca, "EC_SDK_RECORD_EVERY_DT").value == [0.01, 0.02]
    assert _one(ca, "EC_SDK_RECORD_EVERY_DT_ARRAY_MODE").value is True


def test_cp_uses_the_current_step_parameter_and_a_voltage_record_trigger():
    plan = ec2tech.build_plan("CP", _params("CP"))
    (cp,) = plan.techniques
    assert cp.identifier == "EC_SDK_TECHNIQUE_CP"
    assert cp.reader == "step"
    assert _one(cp, "EC_SDK_CURRENT_STEP_IN_A").value == [1e-4]
    assert _one(cp, "EC_SDK_RECORD_EVERY_DE").value == [0.01]
    assert _one(cp, "EC_SDK_VS_INITIAL").value == ["EC_SDK_VS_IREF"]


def test_cv_collapses_four_voltages_into_one_array_in_ei_e1_e2_ef_order():
    plan = ec2tech.build_plan("CV", _params("CV"))
    (cv,) = plan.techniques
    assert cv.identifier == "EC_SDK_TECHNIQUE_CV"
    assert cv.reader == "step"
    # EClib1 had four scalar params; EClib2 wants [Ei, E1, E2, Ef] exactly.
    assert _one(cv, "EC_SDK_VOLTAGE_STEP_IN_V").value == [0.0, 0.25, -0.25, 0.0]
    assert _one(cv, "EC_SDK_VS_INITIAL").value == ["EC_SDK_VS_EREF"] * 4


def test_cv_broadcasts_one_scan_rate_across_all_four_phases():
    plan = ec2tech.build_plan("CV", _params("CV"))
    (cv,) = plan.techniques
    assert _one(cv, "EC_SDK_SCAN_RATE_IN_V_PER_S").value == [0.5] * 4


def test_cv_carries_the_cycle_count_and_the_current_averaging_window():
    plan = ec2tech.build_plan("CV", _params("CV"))
    (cv,) = plan.techniques
    assert _one(cv, "EC_SDK_N_CYCLES").value == 1
    assert _one(cv, "EC_SDK_RECORD_EVERY_DE").value == [0.01]
    # EClib1 exposed no measuring window; the vendor CV example's values are
    # the documented default rather than an invented one.
    assert _one(cv, "EC_SDK_BEGIN_MEASURING_I").value == pytest.approx(
        ec2tech.CV_DEFAULT_BEGIN_MEASURING_I
    )
    assert _one(cv, "EC_SDK_END_MEASURING_I").value == pytest.approx(
        ec2tech.CV_DEFAULT_END_MEASURING_I
    )


def test_the_cv_measuring_window_is_overridable():
    plan = ec2tech.build_plan(
        "CV", _params("CV", BeginMeasuringI=0.25, EndMeasuringI=0.75)
    )
    (cv,) = plan.techniques
    assert _one(cv, "EC_SDK_BEGIN_MEASURING_I").value == 0.25
    assert _one(cv, "EC_SDK_END_MEASURING_I").value == 0.75


# --------------------------------------------------------------------------
# composites
# --------------------------------------------------------------------------


def test_peis_is_a_ca_bias_leg_followed_by_the_sweep():
    plan = ec2tech.build_plan("PEIS", _params("PEIS"))
    assert [t.identifier for t in plan.techniques] == [
        "EC_SDK_TECHNIQUE_CA",
        "EC_SDK_TECHNIQUE_PEIS",
    ]
    ca, peis = plan.techniques
    assert ca.reader == "step"
    assert peis.reader == "eis"
    assert plan.columns == ec2data.EIS_COLUMNS
    # EClib2's PEIS has no DC potential parameter at all -- the bias is the CA.
    assert _one(ca, "EC_SDK_VOLTAGE_STEP_IN_V").value == [0.3]
    assert _one(ca, "EC_SDK_DURATION_STEP_IN_S").value == [0.5]
    assert _one(ca, "EC_SDK_RECORD_EVERY_DT").value == [0.05]
    assert not _by_name(peis, "EC_SDK_VOLTAGE_STEP_IN_V")


def test_peis_maps_the_sweep_parameters_including_the_renamed_ones():
    plan = ec2tech.build_plan("PEIS", _params("PEIS"))
    _, peis = plan.techniques
    assert _one(peis, "EC_SDK_INITIAL_FREQUENCY_IN_HZ").value == 1e6
    assert _one(peis, "EC_SDK_FINAL_FREQUENCY_IN_HZ").value == 1.0
    assert _one(peis, "EC_SDK_FREQUENCY_NUMBER").value == 30
    assert _one(peis, "EC_SDK_AMPLITUDE_VOLTAGE_IN_V").value == 0.02
    # Repeats -> AVERAGE_N_TIMES, DelayFraction -> WAIT_FOR_STEADY.
    assert _one(peis, "EC_SDK_AVERAGE_N_TIMES").value == 1
    assert _one(peis, "EC_SDK_WAIT_FOR_STEADY_IN_SINE_PERIOD").value == 0.1


@pytest.mark.parametrize(
    "caption,member",
    [
        ("log", "EC_SDK_SWEEP_LOG"),
        ("lin", "EC_SDK_SWEEP_LINEAR"),
        ("LOG", "EC_SDK_SWEEP_LOG"),
        ("LINEAR", "EC_SDK_SWEEP_LINEAR"),
    ],
)
def test_the_sweep_mode_caption_maps_to_the_vendor_enum(caption, member):
    plan = ec2tech.build_plan("PEIS", _params("PEIS", SweepMode=caption))
    _, peis = plan.techniques
    got = _one(peis, "EC_SDK_SWEEP_MODE")
    assert got.value == member
    assert got.kind == "enum"


def test_an_unknown_sweep_mode_raises():
    with pytest.raises(ValueError, match="spiral"):
        ec2tech.build_plan("PEIS", _params("PEIS", SweepMode="spiral"))


def test_geis_is_a_cp_bias_leg_followed_by_the_sweep():
    plan = ec2tech.build_plan("GEIS", _params("GEIS"))
    assert [t.identifier for t in plan.techniques] == [
        "EC_SDK_TECHNIQUE_CP",
        "EC_SDK_TECHNIQUE_GEIS",
    ]
    cp, geis = plan.techniques
    assert _one(cp, "EC_SDK_CURRENT_STEP_IN_A").value == [1e-4]
    # The GEIS current amplitude is AMPLITUDE_CURRENT_IN_AMP. The technique
    # doc table calls it EC_SDK_ANALOG_GAIN, which is not a real member.
    assert _one(geis, "EC_SDK_AMPLITUDE_CURRENT_IN_AMP").value == 2e-5
    assert not _by_name(geis, "EC_SDK_ANALOG_GAIN")
    assert plan.columns == ec2data.EIS_COLUMNS


def test_drift_correction_is_off_unless_asked_for():
    plan = ec2tech.build_plan("PEIS", _params("PEIS"))
    _, peis = plan.techniques
    assert _one(peis, "EC_SDK_ENABLE_DRIFT_CORRECTION").value is False

    plan = ec2tech.build_plan("PEIS", _params("PEIS", DriftCorrection=True))
    _, peis = plan.techniques
    assert _one(peis, "EC_SDK_ENABLE_DRIFT_CORRECTION").value is True


def test_caocv_is_a_ca_then_an_ocv_sharing_the_step_columns():
    plan = ec2tech.build_plan("CAOCV", _params("CAOCV"))
    assert [t.identifier for t in plan.techniques] == [
        "EC_SDK_TECHNIQUE_CA",
        "EC_SDK_TECHNIQUE_OCV",
    ]
    ca, ocv = plan.techniques
    assert _one(ca, "EC_SDK_VOLTAGE_STEP_IN_V").value == [0.4, 0.6]
    assert _one(ca, "EC_SDK_DURATION_STEP_IN_S").value == [1.0, 2.0]
    assert _one(ca, "EC_SDK_STEP_NUMBER").value == 1
    assert _one(ocv, "EC_SDK_REST_TIME_IN_S").value == 3.0
    # CAOCV published the step columns, so the OCV leg's rows are padded there
    # rather than the action emitting two shapes.
    assert plan.columns == ec2data.STEP_COLUMNS


# --------------------------------------------------------------------------
# ranges, and refusing to guess
# --------------------------------------------------------------------------


def test_ranges_are_absent_when_the_action_does_not_set_them():
    # Omitting them leaves the channel on whatever it already had, which is
    # what EClib1 did with a KEEP value. Inventing a range here would run the
    # cell at a scale nobody asked for.
    plan = ec2tech.build_plan("CA", _params("CA"))
    (ca,) = plan.techniques
    assert ca.irange is None
    assert ca.erange is None
    assert ca.bandwidth is None


def test_ranges_are_coerced_through_the_enum_layer():
    plan = ec2tech.build_plan(
        "CA", _params("CA", IRange="m10", ERange="v5", Bandwidth="BW5")
    )
    (ca,) = plan.techniques
    assert ca.irange == ("I_RANGE_MODE_FIXED", "EC_SDK_IRANGE_10mA")
    assert ca.erange == "EC_SDK_ERANGE_5"
    assert ca.bandwidth == "EC_SDK_BANDWIDTH_5"


def test_an_auto_current_range_becomes_a_mode_on_the_technique():
    plan = ec2tech.build_plan("CA", _params("CA", IRange="AUTO"))
    (ca,) = plan.techniques
    assert ca.irange == ("I_RANGE_MODE_AUTO", "EC_SDK_IRANGE_1mA")


def test_the_eis_ranges_land_on_both_legs_of_the_composite():
    # The bias leg and the sweep are separate technique handles, and
    # BL_SetIRange is per handle. Setting only the sweep would run the bias at
    # whatever the channel last held.
    plan = ec2tech.build_plan(
        "PEIS", _params("PEIS", IRange="m1", ERange="v10", Bandwidth="BW4")
    )
    for tech in plan.techniques:
        assert tech.irange == ("I_RANGE_MODE_FIXED", "EC_SDK_IRANGE_1mA")
        assert tech.erange == "EC_SDK_ERANGE_10"
        assert tech.bandwidth == "EC_SDK_BANDWIDTH_4"


def test_caocv_ranges_apply_only_to_the_ca_leg():
    # OCV disconnects the cell from the amplifier, so a range on it is
    # meaningless -- and CAOCV's param keys are CA-prefixed for that reason.
    plan = ec2tech.build_plan(
        "CAOCV", _params("CAOCV", CA_IRange="m1", CA_ERange="v5", CA_Bandwidth="BW5")
    )
    ca, ocv = plan.techniques
    assert ca.irange == ("I_RANGE_MODE_FIXED", "EC_SDK_IRANGE_1mA")
    assert ocv.irange is None
    assert ocv.erange is None
    assert ocv.bandwidth is None


@pytest.mark.parametrize(
    "name,missing",
    [
        ("OCV", "Tval__s"),
        ("CA", "Vval__V"),
        ("CP", "Ival__A"),
        ("CV", "ScanRate__V_s"),
        ("PEIS", "Finit__Hz"),
        ("GEIS", "Iamp__A"),
        ("CAOCV", "OCV_Tval__s"),
    ],
)
def test_a_missing_required_parameter_names_itself(name, missing):
    params = _params(name)
    del params[missing]
    with pytest.raises(ValueError, match=missing):
        ec2tech.build_plan(name, params)


def test_the_reader_for_a_returned_technique_identifier_is_resolvable():
    # BL_DownloadRawData reports which technique produced the buffer, and the
    # driver has to pick the matching BL_ProcessRawTo* from that alone.
    assert ec2tech.READER_BY_IDENTIFIER["EC_SDK_TECHNIQUE_OCV"] == "ocv"
    assert ec2tech.READER_BY_IDENTIFIER["EC_SDK_TECHNIQUE_CA"] == "step"
    assert ec2tech.READER_BY_IDENTIFIER["EC_SDK_TECHNIQUE_CP"] == "step"
    assert ec2tech.READER_BY_IDENTIFIER["EC_SDK_TECHNIQUE_CV"] == "step"
    assert ec2tech.READER_BY_IDENTIFIER["EC_SDK_TECHNIQUE_PEIS"] == "eis"
    assert ec2tech.READER_BY_IDENTIFIER["EC_SDK_TECHNIQUE_GEIS"] == "eis"


def test_every_plan_only_ever_uses_readers_the_data_layer_implements():
    for name in ec2tech.TECHNIQUE_NAMES:
        plan = ec2tech.build_plan(name, _params(name))
        for tech in plan.techniques:
            assert tech.reader in ec2tech.READERS


def test_every_emitted_parameter_kind_is_one_the_executor_can_dispatch():
    for name in ec2tech.TECHNIQUE_NAMES:
        plan = ec2tech.build_plan(name, _params(name))
        for tech in plan.techniques:
            for param in tech.params:
                assert param.kind in ec2tech.PARAM_KINDS
