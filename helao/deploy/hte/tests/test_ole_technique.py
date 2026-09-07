"""The OLE technique registry, and its agreement with the eclib registry.

The registry is what turns a HELAO action parameter into an .mps parameter
caption and an emitted column into an EC-Lab variable code. Both halves are
silent when wrong: a bad caption patches nothing and runs the template's
default on a real cell; a bad code returns a different quantity under the
right column name.
"""

import pytest

from pathlib import Path

from helao.deploy.hte.drivers.pstat.biologic.technique import BIOTECHS
from helao.deploy.hte.drivers.pstat.biologic_ole import technique as ot

TECHNIQUE_NAMES = ["OCV", "CA", "CP", "CV", "PEIS", "GEIS", "CAOCV"]
TEMPLATES = Path("helao/deploy/hte/drivers/pstat/biologic_ole/templates")
FIXTURES = Path("helao/deploy/hte/tests/fixtures/ole")


def test_every_eclib_technique_has_an_ole_counterpart():
    assert sorted(ot.OLE_TECHS) == sorted(BIOTECHS)


@pytest.mark.parametrize("name", TECHNIQUE_NAMES)
def test_resolve_returns_the_named_technique(name):
    assert ot.resolve(name).technique_name == name


def test_an_unknown_technique_names_itself_and_the_alternatives():
    with pytest.raises(ValueError, match="SWV"):
        ot.resolve("SWV")


@pytest.mark.parametrize("name", TECHNIQUE_NAMES)
def test_every_technique_names_a_template_file(name):
    assert ot.resolve(name).template.endswith(".mps")


#: X_ohm and R_ohm are part of the frozen EIS contract but are NOT in the
#: eclib registry's field_map -- that driver computes them in get_data from
#: modulus and phase, after remapping. The OLE side declares them in its
#: column plan instead, because it gets them straight off MeasureEisValue.
#: Same emitted columns, declared in different places.
ECLIB_DERIVED_IN_CODE = {"X_ohm", "R_ohm"}


def eclib_columns(name: str) -> set:
    columns = set(BIOTECHS[name].field_map.values())
    if "modulus" in columns:
        columns |= ECLIB_DERIVED_IN_CODE
    return columns


@pytest.mark.parametrize("name", TECHNIQUE_NAMES)
def test_emitted_columns_match_the_eclib_field_map(name):
    """The frozen contract: both backends emit the same column key set."""
    expected = eclib_columns(name)
    ole_columns = set(ot.columns(ot.resolve(name).column_plan))
    assert ole_columns == expected, {
        "only_eclib": sorted(expected - ole_columns),
        "only_ole": sorted(ole_columns - expected),
    }


@pytest.mark.parametrize("name", ["CA", "CP", "CV", "CAOCV"])
def test_dc_techniques_fetch_nothing_by_code(name):
    """A DC point costs one MeasureDcValue call and no MeasureValueByCode.

    `derived` means "not fetched by variable code" -- it holds both the three
    columns MeasureDcValue returns directly and the two computed from them.
    What matters is that `var_codes` is empty: P_W is |Ewe*I|, which is
    EC-Lab's own definition of variable 70, and cycle comes from the status
    array, so fetching either would cost a round trip per point to learn a
    number we already have.
    """
    plan = ot.resolve(name).column_plan
    assert plan.kind == "dc"
    assert plan.var_codes == {}
    assert {"P_W", "cycle"} <= set(plan.derived)


@pytest.mark.parametrize("name", ["PEIS", "GEIS"])
def test_eis_techniques_derive_the_impedance_pair_and_process(name):
    plan = ot.resolve(name).column_plan
    assert plan.kind == "eis"
    assert set(plan.derived) == {"X_ohm", "R_ohm", "process", "t_s", "f_Hz"}


def test_ocv_emits_only_time_and_potential():
    """MeasureDcValue's current is documented as always zero for OCV."""
    assert set(ot.columns(ot.resolve("OCV").column_plan)) == {"t_s", "Ewe_V"}


@pytest.mark.parametrize(
    "name,codes",
    [
        ("OCV", {11, 55}),
        ("CA", {24, 54}),
        ("CP", {25, 56}),
        ("CV", {6, 57}),
        ("PEIS", {29, 60}),
        ("GEIS", {30, 61}),
    ],
)
def test_both_technique_code_families_are_accepted(name, codes):
    """Appendix 7.1 lists each of these techniques twice, under two codes."""
    assert ot.resolve(name).technique_codes == frozenset(codes)


def test_caocv_accepts_both_its_constituent_techniques():
    assert ot.resolve("CAOCV").technique_codes >= {24, 54, 11, 55}


@pytest.mark.parametrize("name", TECHNIQUE_NAMES)
def test_every_action_parameter_the_eclib_registry_maps_is_also_mapped(name):
    """A parameter eclib forwards but OLE drops would silently run a default.

    ERange is the one exception, and it is handled rather than dropped: it is
    not a single .mps row but a symmetric min/max pair, so the driver applies
    it through `erange_rows`. `test_erange_is_applied_as_a_min_max_pair`
    covers it.
    """
    eclib_keys = set(BIOTECHS[name].parameter_map)
    ole_keys = set(ot.resolve(name).parameter_map)
    handled_elsewhere = {"ERange", "CA_ERange"}
    if name == "CV":
        # EC-Lab's CV has no dE (mV) row at all -- see the registry comment.
        handled_elsewhere = handled_elsewhere | {"AcqInterval__V"}
    assert eclib_keys - ole_keys <= handled_elsewhere, sorted(
        eclib_keys - ole_keys - handled_elsewhere
    )


def test_erange_is_applied_as_a_min_max_pair():
    """EC-Lab has no 'E range' row; the window is two symmetric rows."""
    assert ot.erange_rows("v2_5") == {
        "E range min (V)": "-2.500",
        "E range max (V)": "2.500",
    }
    assert ot.erange_rows("v10") == {
        "E range min (V)": "-10.000",
        "E range max (V)": "10.000",
    }


def test_auto_erange_writes_nothing_rather_than_guessing():
    """AUTO has no numeric equivalent; the template's own window stands."""
    assert ot.erange_rows("AUTO") == {}
    assert ot.erange_rows("nonsense") == {}


def test_cv_does_not_map_a_voltage_recording_interval():
    """EC-Lab's CV has no `dE (mV)` row; Step percent and N govern it.

    Pinned as a test rather than left implicit, because the obvious fix --
    inventing a `dE (mV)` mapping -- silently changes the sampling of every
    CV the station runs.
    """
    assert "AcqInterval__V" not in ot.resolve("CV").parameter_map


#: Every technique in the registry has a real GUI-authored template
#: committed, so the caption guard below covers the whole surface.
TEMPLATED = ["OCV", "CA", "CP", "CV", "PEIS", "GEIS", "CAOCV"]


@pytest.mark.parametrize("name", TEMPLATED)
def test_every_caption_exists_in_the_real_template(name):
    """The guard the whole registry rests on, and it runs on Linux.

    Each caption is read off a GUI-authored EC-Lab v11.72 file rather than
    inferred. A caption that drifts -- or a template replaced by one from a
    different EC-Lab version that renamed a row -- fails here instead of at a
    station, where the symptom is an experiment that ran on the template's
    defaults with nothing to show it.
    """
    from helao.deploy.hte.drivers.pstat.biologic_ole import mps_template as mt

    tech = ot.resolve(name)
    doc = mt.load(TEMPLATES / tech.template)
    for key, param in tech.parameter_map.items():
        mt.get_param(doc, param.param_id, technique=param.technique)
        if param.unit_param_id:
            mt.get_param(doc, param.unit_param_id, technique=param.technique)


@pytest.mark.parametrize("name", TEMPLATED)
def test_the_erange_pair_exists_in_every_real_template(name):
    """erange_rows writes both, and OCV has them despite having no I Range."""
    from helao.deploy.hte.drivers.pstat.biologic_ole import mps_template as mt

    doc = mt.load(TEMPLATES / ot.resolve(name).template)
    for caption in ("E range min (V)", "E range max (V)"):
        mt.get_param(doc, caption)


def test_caocv_is_the_only_two_technique_template():
    from helao.deploy.hte.drivers.pstat.biologic_ole import mps_template as mt

    counts = {
        name: mt.n_techniques(mt.load(TEMPLATES / ot.resolve(name).template))
        for name in TEMPLATED
    }
    assert counts.pop("CAOCV") == 2
    assert set(counts.values()) == {1}, counts


def test_caocv_scoping_is_not_optional():
    """Both of its blocks carry `E range min (V)`, `E range max (V)`, `record`.

    Unscoped, every one of those patches lands in the CA block and the OCV
    step silently keeps the template's values.
    """
    from helao.deploy.hte.drivers.pstat.biologic_ole import mps_template as mt

    doc = mt.load(TEMPLATES / "CAOCV.mps")
    for caption in ("E range min (V)", "E range max (V)", "record"):
        mt.get_param(doc, caption, technique=0)
        mt.get_param(doc, caption, technique=1)


def test_every_caocv_parameter_declares_its_block():
    for key, param in ot.resolve("CAOCV").parameter_map.items():
        assert param.technique in (0, 1), (key, param.technique)
        assert param.technique == (0 if key.startswith("CA_") else 1), key


def test_the_templates_agree_on_one_eclab_version():
    """A template from another build may have renamed a row silently."""
    from helao.deploy.hte.drivers.pstat.biologic_ole import mps_template as mt

    versions = set()
    for path in sorted(TEMPLATES.glob("*.mps")):
        for line in mt.load(path).lines:
            if line.startswith("EC-LAB for windows"):
                versions.add(line.strip())
                break
    assert len(versions) == 1, versions


def test_captions_are_case_sensitive_and_inconsistent_across_techniques():
    """CV spells it `Step percent`; LSV spells it `step percent`.

    Both are real, in files from the same EC-Lab build. This is why every
    caption is read from a template rather than derived from a convention.
    """
    from helao.deploy.hte.drivers.pstat.biologic_ole import mps_template as mt

    cv = mt.load(FIXTURES / "CV.mps")
    lsv = mt.load(FIXTURES / "LSV.mps")
    assert mt.get_param(cv, "Step percent") == "50"
    assert mt.get_param(lsv, "step percent") == "50"
    with pytest.raises(mt.MpsParameterNotFound):
        mt.get_param(cv, "step percent")


def test_the_scan_rate_scales_to_the_unit_the_template_carries():
    """The real file holds `dE/dt 20.000` with `dE/dt unit mV/s`."""
    assert ot.scale_to_unit(0.02, "V/s") == ("20.000", "mV/s")


def test_no_technique_maps_erange_to_a_single_caption():
    """Writing 'AUTO' into a field EC-Lab reads as a voltage is the trap."""
    for tech in ot.OLE_TECHS.values():
        assert "ERange" not in tech.parameter_map, tech.technique_name
        assert "CA_ERange" not in tech.parameter_map, tech.technique_name


def test_a_scaled_parameter_declares_a_unit_row_and_a_base_unit():
    """EC-Lab writes a current as a magnitude row plus a unit row."""
    param = ot.resolve("CP").parameter_map["Ival__A"]
    assert param.param_id == "Is"
    assert param.unit_param_id == "unit Is"
    assert param.base_unit == "A"


def test_geis_spells_its_amplitude_unit_row_with_two_spaces():
    """`unit  Ia` is EC-Lab's own spelling, not a typo here."""
    assert ot.resolve("GEIS").parameter_map["Iamp__A"].unit_param_id == "unit  Ia"


def test_scale_to_unit_keeps_a_microamp_out_of_the_third_decimal():
    """Unscaled, 1 uA formats to 0.000 -- the whole reason this exists."""
    assert ot.scale_to_unit(1e-6, "A") == ("1.000", "µA")
    assert ot.scale_to_unit(-2.5e-3, "A") == ("-2.500", "mA")
    assert ot.scale_to_unit(1.0, "A") == ("1.000", "A")
    assert ot.scale_to_unit(1e6, "Hz") == ("1.000", "MHz")
    assert ot.scale_to_unit(1000.0, "Hz") == ("1.000", "kHz")
    assert ot.scale_to_unit(0.0, "A") == ("0.000", "A")


def test_the_micro_prefix_is_the_single_latin1_byte():
    """0xB5, not the UTF-8 two-byte sequence EC-Lab would not recognise."""
    _, unit = ot.scale_to_unit(1e-6, "A")
    assert unit.encode("latin-1") == b"\xb5A"


def test_every_irange_spelling_uses_the_latin1_micro_sign():
    for alias in ("u1", "u10", "u100"):
        assert ot.IRANGE_VALUES[alias].encode("latin-1").count(b"\xb5") == 1


def test_variable_codes_are_the_documented_ones():
    """Appendix 7.2. A wrong code returns a different quantity, silently."""
    assert ot.VAR_CODES["t_s"] == 4
    assert ot.VAR_CODES["Ewe_V"] == 6
    assert ot.VAR_CODES["I_A"] == 8
    assert ot.VAR_CODES["Ece_V"] == 9
    assert ot.VAR_CODES["f_Hz"] == 32
    assert ot.VAR_CODES["AbsEwe_V"] == 33
    assert ot.VAR_CODES["AbsI_A"] == 34
    assert ot.VAR_CODES["phase"] == 35
    assert ot.VAR_CODES["modulus"] == 36
    assert ot.VAR_CODES["AbsEce_V"] == 96
    assert ot.VAR_CODES["AbsIce_A"] == 97
    assert ot.VAR_CODES["phase_ce"] == 98
    assert ot.VAR_CODES["modulus_ce"] == 99
    assert ot.VAR_CODES["P_W"] == 70
    assert ot.VAR_CODES["cycle"] == 24


def test_no_module_scope_vendor_import():
    import sys

    assert "comtypes" not in sys.modules


def test_bandwidth_is_written_as_an_integer():
    """ "BW4" loads fine and runs at the template's bandwidth instead."""
    assert ot.format_value("BW4", "bandwidth") == "4"
    assert ot.format_value("BW7", "bandwidth") == "7"
    assert ot.resolve("CA").parameter_map["Bandwidth"].fmt == "bandwidth"


def test_a_volts_parameter_landing_in_a_millivolt_row_is_scaled():
    assert ot.format_value(0.01, "V_to_mV") == "10.000"
    assert ot.resolve("PEIS").parameter_map["Vamp__V"].param_id == "Va (mV)"
    assert ot.resolve("PEIS").parameter_map["Vamp__V"].fmt == "V_to_mV"


def test_the_current_range_is_written_as_eclabs_display_string():
    """The real templates hold `Auto`, `100 µA`, `1 mA` -- not `u100`."""
    assert ot.format_value("AUTO", "irange") == "Auto"
    assert ot.format_value("u100", "irange") == "100 µA"
    assert ot.format_value("m1", "irange") == "1 mA"
    assert ot.resolve("CA").parameter_map["IRange"].fmt == "irange"


def test_an_irange_eclab_cannot_spell_is_refused():
    """KEEP and BOOSTER have no observed spelling; guessing one is worse."""
    for alias in ("KEEP", "BOOSTER", "nonsense"):
        with pytest.raises(ValueError, match=alias):
            ot.format_value(alias, "irange")


def test_the_sweep_mode_row_is_spacing_and_its_values_are_words():
    assert ot.resolve("PEIS").parameter_map["SweepMode"].param_id == "spacing"
    assert ot.format_value("log", "spacing") == "Logarithmic"
    assert ot.format_value("lin", "spacing") == "Linear"


from helao.deploy.hte.drivers.pstat.biologic_ole import mps_assemble as ma
from helao.deploy.hte.drivers.pstat.biologic_ole import mps_template as mt

# The real GUI-authored templates, and the real three-technique file the
# assembler is trying to reproduce.
TRIGGER_IN = mt.load(TEMPLATES / "TI.mps")
TRIGGER_OUT = mt.load(TEMPLATES / "TO.mps")
MAIN = mt.load(FIXTURES / "CV.mps")
REFERENCE = mt.load(FIXTURES / "TI_CV_TO.mps")


def test_the_real_trigger_templates_hold_one_technique_each():
    assert [b.name for b in mt.technique_blocks(TRIGGER_IN)] == ["Trigger In"]
    assert [b.name for b in mt.technique_blocks(TRIGGER_OUT)] == ["Trigger Out"]


def test_trigger_in_carries_a_channel_and_no_duration():
    assert mt.get_param(TRIGGER_IN, "Channel") == "-1"
    assert mt.get_param(TRIGGER_IN, "Trigger") == "Rising Edge"
    with pytest.raises(mt.MpsParameterNotFound):
        mt.get_param(TRIGGER_IN, "td (h:m:s)")


def test_trigger_out_carries_a_delay_and_no_channel():
    """Which is why TTLsend selects nothing -- see UNMAPPED_TTLSEND."""
    assert mt.get_param(TRIGGER_OUT, "td (h:m:s)") == "0:00:0.0010"
    with pytest.raises(mt.MpsParameterNotFound):
        mt.get_param(TRIGGER_OUT, "Channel")


def test_a_disabled_ttl_plan_is_inactive():
    assert ma.ttl_plan_from_params({"TTLwait": -1, "TTLsend": -1}).is_active is False


def test_an_absent_ttl_key_reads_as_disabled():
    assert ma.ttl_plan_from_params({}).is_active is False


def test_either_direction_activates_the_plan():
    assert ma.ttl_plan_from_params({"TTLwait": 0}).is_active is True
    assert ma.ttl_plan_from_params({"TTLsend": 3}).is_active is True


def test_an_inactive_plan_returns_the_main_document_unchanged():
    out = ma.assemble(MAIN, ma.TtlPlan(), TRIGGER_IN, TRIGGER_OUT)
    assert mt.render(out) == mt.render(MAIN)


def test_ttlwait_prepends_a_trigger_in_technique():
    plan = ma.TtlPlan(wait=2)
    out = ma.assemble(MAIN, plan, TRIGGER_IN, TRIGGER_OUT)
    assert [b.name for b in mt.technique_blocks(out)] == [
        "Trigger In",
        "Cyclic Voltammetry",
    ]


def test_ttlsend_appends_a_trigger_out_technique():
    plan = ma.TtlPlan(send=1)
    out = ma.assemble(MAIN, plan, TRIGGER_IN, TRIGGER_OUT)
    assert [b.name for b in mt.technique_blocks(out)] == [
        "Cyclic Voltammetry",
        "Trigger Out",
    ]


def test_both_directions_reproduce_the_reference_block_order():
    """The assembled file must match a GUI-authored TI -> CV -> TO."""
    out = ma.assemble(MAIN, ma.TtlPlan(wait=2, send=1), TRIGGER_IN, TRIGGER_OUT)
    assert [b.name for b in mt.technique_blocks(out)] == [
        b.name for b in mt.technique_blocks(REFERENCE)
    ]


def test_the_header_appears_exactly_once():
    """Each template is a whole .mps; splicing documents would repeat it."""
    out = mt.render(
        ma.assemble(MAIN, ma.TtlPlan(wait=2, send=1), TRIGGER_IN, TRIGGER_OUT)
    )
    assert out.count("EC-LAB SETTING FILE") == 1
    assert out.count("Number of linked techniques") == 1


def test_the_in_channel_lands_on_trigger_in(triggered_out=None):
    out = ma.assemble(MAIN, ma.TtlPlan(wait=2), TRIGGER_IN, TRIGGER_OUT)
    assert mt.get_param(out, "Channel", technique=0) == "2"


def test_the_duration_lands_on_trigger_outs_delay_row():
    out = ma.assemble(MAIN, ma.TtlPlan(send=1, duration=2.5), TRIGGER_IN, TRIGGER_OUT)
    assert mt.get_param(out, "td (h:m:s)", technique=1) == "0:00:2.5000"


def test_configuring_one_trigger_leaves_the_others_trigger_row_alone():
    """Both blocks carry a `Trigger` row; a first-match patch hits the wrong one."""
    out = ma.assemble(MAIN, ma.TtlPlan(wait=2, send=1), TRIGGER_IN, TRIGGER_OUT)
    assert mt.get_param(out, "Trigger", technique=0) == "Rising Edge"
    assert mt.get_param(out, "Trigger", technique=2) == "Rising Edge"


def test_techniques_are_renumbered_consecutively_from_one():
    out = mt.render(
        ma.assemble(MAIN, ma.TtlPlan(wait=2, send=1), TRIGGER_IN, TRIGGER_OUT)
    )
    numbers = [
        int(line.split(":")[1])
        for line in out.splitlines()
        if line.startswith("Technique :")
    ]
    assert numbers == [1, 2, 3]


def test_the_linked_technique_count_header_is_updated():
    out = mt.render(
        ma.assemble(MAIN, ma.TtlPlan(wait=2, send=1), TRIGGER_IN, TRIGGER_OUT)
    )
    assert "Number of linked techniques : 3" in out


def test_the_assembled_file_keeps_crlf_throughout():
    out = mt.render(
        ma.assemble(MAIN, ma.TtlPlan(wait=2, send=1), TRIGGER_IN, TRIGGER_OUT)
    )
    raw = out.encode(mt.ENCODING)
    assert raw.count(b"\r\n") == raw.count(b"\n") > 0


def test_a_trigger_template_with_more_than_one_technique_is_refused():
    with pytest.raises(ValueError, match="exactly one technique"):
        ma.assemble(MAIN, ma.TtlPlan(wait=0), REFERENCE, TRIGGER_OUT)
