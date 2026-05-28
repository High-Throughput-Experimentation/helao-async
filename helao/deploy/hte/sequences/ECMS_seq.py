"""Sequence library for AutoGDE / ECMS (electrochemistry + mass spectrometry).

Each public ``ECMS_*`` function builds an experiment list via
``ExperimentPlanMaker``. Sequences typically chain cell setup, headspace
purges, CO2 baselines, mass-spec calibration, and electrochemical actions
(CV/CA/pulseCA) for both single-pass and recirculating configurations.
"""

__all__ = [
    "ECMS_initiation",
    "ECMS_initiation_recirculation",
    "ECMS_initiation_recirculation_mixedreactant",
    "ECMS_repeat_CV",
    "ECMS_repeat_CV_recirculation",
    "ECMS_repeat_CV_recirculation_mixedreactant",
    "ECMS_CV_recirculation_mixedreactant",
    "ECMS_series_CA",
    "ECMS_series_CA_recirculation",
    "ECMS_series_CA_recirculation_mixedreactant",
    "ECMS_series_CA_recirculation_mixedthreereactant",
    "ECMS_series_pulseCA",
    "ECMS_MS_calibration_recirculation",
    "ECMS_MS_calibration",
    "ECMS_MS_pulsecalibration",
    "ECMS_series_CA_change_gasflow",
]

from typing import List
from helao.helpers.premodels import ExperimentPlanMaker
from helao.helpers.lib_decorators import sequence


SEQUENCES = __all__


@sequence(version=2)
def ECMS_initiation(
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 2,
    volume_ul_cell_liquid: float = 600,
    # liquid_forward_time: float = 20,
    liquid_backward_time: float = 80,
    vacuum_time: float = 15,
    CO2equilibrium_duration: float = 30,
    flowrate_sccm: float = 3.0,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration_1: float = 120,
    MS_baseline_duration_2: float = 90,
    liquid_drain_time: float = 60.0,
) -> list:
    """ECMS cell setup: load sample, vacuum, fill, CO2 baseline, drain.

    Performs the standard pre-run housekeeping followed by two CO2 baseline acquisitions at fast and slow flow rates.

    Args:
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        liquid_backward_time: Parameter passed through to the sub-experiments.
        vacuum_time: Parameter passed through to the sub-experiments.
        CO2equilibrium_duration: Parameter passed through to the sub-experiments.
        flowrate_sccm: Parameter passed through to the sub-experiments.
        flow_ramp_sccm: Parameter passed through to the sub-experiments.
        MS_baseline_duration_1: Parameter passed through to the sub-experiments.
        MS_baseline_duration_2: Parameter passed through to the sub-experiments.
        liquid_drain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ECMS_sub_unload_cell", {})
    epm.add(
        "ECMS_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    epm.add("ECMS_sub_prevacuum_cell", {"vacuum_time": vacuum_time})

    epm.add(
        "ECMS_sub_electrolyte_fill_cell",
        {
            # "liquid_forward_time": liquid_forward_time,
            "liquid_backward_time": liquid_backward_time,
            "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
            "volume_ul_cell_liquid": volume_ul_cell_liquid,
        },
    )

    # achiving faster equilibrium time with faster CO2 flow rate
    epm.add(
        "ECMS_sub_headspace_purge_and_CO2baseline",
        {
            "CO2equilibrium_duration": CO2equilibrium_duration,
            "flowrate_sccm": 10.0,
            "flow_ramp_sccm": flow_ramp_sccm,
            "MS_baseline_duration": MS_baseline_duration_1,
        },
    )

    epm.add(
        "ECMS_sub_headspace_purge_and_CO2baseline",
        {
            "CO2equilibrium_duration": 1.0,
            "flowrate_sccm": flowrate_sccm,
            "flow_ramp_sccm": flow_ramp_sccm,
            "MS_baseline_duration": MS_baseline_duration_2,
        },
    )

    epm.add("ECMS_sub_normal_state", {})
    epm.add("ECMS_sub_drain", {"liquid_drain_time": liquid_drain_time})
    return epm.planned_experiments


@sequence(version=2)
def ECMS_initiation_recirculation(
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    liquid_fill_time: float = 15,
    reservoir_liquid_sample_no: int = 2,
    volume_ul_cell_liquid: float = 600,
    liquid_backward_time: float = 80,
    vacuum_time: float = 15,
    CO2equilibrium_duration: float = 30,
    flowrate_sccm: float = 3.0,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration_1: float = 120,
    MS_baseline_duration_2: float = 90,
    tube_clear_time: float = 20,
    liquid_drain_time: float = 60.0,
) -> list:
    """ECMS cell setup variant with electrolyte recirculation reservoir fill.

    Same shape as :func:`ECMS_initiation` but fills a recirculation reservoir before the cell and drains via the recirculation loop.

    Args:
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        liquid_fill_time: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        liquid_backward_time: Parameter passed through to the sub-experiments.
        vacuum_time: Parameter passed through to the sub-experiments.
        CO2equilibrium_duration: Parameter passed through to the sub-experiments.
        flowrate_sccm: Parameter passed through to the sub-experiments.
        flow_ramp_sccm: Parameter passed through to the sub-experiments.
        MS_baseline_duration_1: Parameter passed through to the sub-experiments.
        MS_baseline_duration_2: Parameter passed through to the sub-experiments.
        tube_clear_time: Parameter passed through to the sub-experiments.
        liquid_drain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ECMS_sub_unload_cell", {})
    epm.add(
        "ECMS_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )
    epm.add(
        "ECMS_sub_electrolyte_fill_recirculationreservoir",
        {
            "liquid_fill_time": liquid_fill_time,
        },
    )
    epm.add("ECMS_sub_prevacuum_cell", {"vacuum_time": vacuum_time})

    epm.add(
        "ECMS_sub_electrolyte_fill_cell_recirculation",
        {
            "liquid_backward_time": liquid_backward_time,
            "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
            "volume_ul_cell_liquid": volume_ul_cell_liquid,
        },
    )

    # achiving faster equilibrium time with faster CO2 flow rate
    epm.add(
        "ECMS_sub_headspace_purge_and_CO2baseline",
        {
            "CO2equilibrium_duration": CO2equilibrium_duration,
            "flowrate_sccm": 10.0,
            "flow_ramp_sccm": flow_ramp_sccm,
            "MS_baseline_duration": MS_baseline_duration_1,
        },
    )

    epm.add(
        "ECMS_sub_headspace_purge_and_CO2baseline",
        {
            "CO2equilibrium_duration": 1.0,
            "flowrate_sccm": flowrate_sccm,
            "flow_ramp_sccm": flow_ramp_sccm,
            "MS_baseline_duration": MS_baseline_duration_2,
        },
    )

    epm.add("ECMS_sub_normal_state", {})
    epm.add(
        "ECMS_sub_drain_recirculation",
        {"tube_clear_time": tube_clear_time, "liquid_drain_time": liquid_drain_time},
    )
    return epm.planned_experiments


@sequence(version=2)
def ECMS_initiation_recirculation_mixedreactant(
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    liquid_fill_time: float = 15,
    reservoir_liquid_sample_no: int = 2,
    volume_ul_cell_liquid: float = 600,
    liquid_backward_time: float = 80,
    vacuum_time: float = 15,
    CO2equilibrium_duration: float = 30,
    CO2flowrate_sccm: float = 5.0,
    Califlowrate_sccm: float = 5.0,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration_1: float = 120,
    MS_baseline_duration_2: float = 180,
    tube_clear_time: float = 20,
    liquid_drain_time: float = 60.0,
) -> list:
    """ECMS recirculation setup with mixed reactant calibration baseline.

    Like :func:`ECMS_initiation_recirculation` but replaces the second CO2 baseline with a ``ECMS_sub_cali`` mixed-reactant calibration.

    Args:
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        liquid_fill_time: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        liquid_backward_time: Parameter passed through to the sub-experiments.
        vacuum_time: Parameter passed through to the sub-experiments.
        CO2equilibrium_duration: Parameter passed through to the sub-experiments.
        CO2flowrate_sccm: Parameter passed through to the sub-experiments.
        Califlowrate_sccm: Parameter passed through to the sub-experiments.
        flow_ramp_sccm: Parameter passed through to the sub-experiments.
        MS_baseline_duration_1: Parameter passed through to the sub-experiments.
        MS_baseline_duration_2: Parameter passed through to the sub-experiments.
        tube_clear_time: Parameter passed through to the sub-experiments.
        liquid_drain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ECMS_sub_unload_cell", {})
    epm.add(
        "ECMS_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )
    epm.add(
        "ECMS_sub_electrolyte_fill_recirculationreservoir",
        {
            "liquid_fill_time": liquid_fill_time,
        },
    )
    epm.add("ECMS_sub_prevacuum_cell", {"vacuum_time": vacuum_time})

    epm.add(
        "ECMS_sub_electrolyte_fill_cell_recirculation",
        {
            "liquid_backward_time": liquid_backward_time,
            "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
            "volume_ul_cell_liquid": volume_ul_cell_liquid,
        },
    )

    # achiving faster equilibrium time with faster CO2 flow rate
    epm.add(
        "ECMS_sub_headspace_purge_and_CO2baseline",
        {
            "CO2equilibrium_duration": CO2equilibrium_duration,
            "flowrate_sccm": 10.0,
            "flow_ramp_sccm": flow_ramp_sccm,
            "MS_baseline_duration": MS_baseline_duration_1,
        },
    )

    epm.add(
        "ECMS_sub_cali",
        {
            "CO2flowrate_sccm": CO2flowrate_sccm,
            "Califlowrate_sccm": Califlowrate_sccm,
            "MSsignal_quilibrium_time": MS_baseline_duration_2,
        },
    )

    epm.add("ECMS_sub_normal_state", {})
    epm.add(
        "ECMS_sub_drain_recirculation",
        {"tube_clear_time": tube_clear_time, "liquid_drain_time": liquid_drain_time},
    )
    return epm.planned_experiments


@sequence(version=2)
def ECMS_repeat_CV(
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 2,
    volume_ul_cell_liquid: float = 600,
    # liquid_forward_time: float = 0,
    liquid_backward_time: float = 100,
    # vacuum_time: float = 10,
    CO2equilibrium_duration: float = 30,
    flowrate_sccm: float = 3.0,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration_1: float = 90,
    MS_baseline_duration_2: float = 90,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 7.8,
    num_repeats: int = 1,
    WE_potential_init__V: float = -1.3,
    WE_potential_apex1__V: float = -2.0,
    WE_potential_apex2__V: float = -1.3,
    WE_potential_final__V: float = -1.3,
    ScanRate_V_s_1: float = 0.05,
    ScanRate_V_s_2: float = 0.02,
    Cycles: int = 3,
    SampleRate: float = 0.1,
    IErange: str = "auto",
    ref_offset: float = 0.0,
    MS_equilibrium_time: float = 120.0,
    liquid_drain_time: float = 60.0,
    # electrolyte_recirculation: str = "on",
    # liquid_cleancell_time: float = 120,
) -> list:
    """Repeat CV sweeps at two scan rates with CO2 baselines per cycle.

    For ``num_repeats`` iterations: fill, run two CO2 baselines, then run CV at ``ScanRate_V_s_1`` and CV at ``ScanRate_V_s_2``, return to normal state and drain.

    Args:
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        liquid_backward_time: Parameter passed through to the sub-experiments.
        CO2equilibrium_duration: Parameter passed through to the sub-experiments.
        flowrate_sccm: Parameter passed through to the sub-experiments.
        flow_ramp_sccm: Parameter passed through to the sub-experiments.
        MS_baseline_duration_1: Parameter passed through to the sub-experiments.
        MS_baseline_duration_2: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        num_repeats: Parameter passed through to the sub-experiments.
        WE_potential_init__V: Parameter passed through to the sub-experiments.
        WE_potential_apex1__V: Parameter passed through to the sub-experiments.
        WE_potential_apex2__V: Parameter passed through to the sub-experiments.
        WE_potential_final__V: Parameter passed through to the sub-experiments.
        ScanRate_V_s_1: Parameter passed through to the sub-experiments.
        ScanRate_V_s_2: Parameter passed through to the sub-experiments.
        Cycles: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset: Parameter passed through to the sub-experiments.
        MS_equilibrium_time: Parameter passed through to the sub-experiments.
        liquid_drain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ECMS_sub_unload_cell", {})
    epm.add(
        "ECMS_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    # epm.add("ECMS_sub_prevacuum_cell",{"vacuum_time": vacuum_time})

    for _ in range(num_repeats):
        epm.add(
            "ECMS_sub_electrolyte_fill_cell",
            {
                # "liquid_forward_time": liquid_forward_time,
                "liquid_backward_time": liquid_backward_time,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        # achiving faster equilibrium time with faster CO2 flow rate
        epm.add(
            "ECMS_sub_headspace_purge_and_CO2baseline",
            {
                "CO2equilibrium_duration": CO2equilibrium_duration,
                "flowrate_sccm": 10.0,
                "flow_ramp_sccm": flow_ramp_sccm,
                "MS_baseline_duration": MS_baseline_duration_1,
            },
        )

        epm.add(
            "ECMS_sub_headspace_purge_and_CO2baseline",
            {
                "CO2equilibrium_duration": 1.0,
                "flowrate_sccm": flowrate_sccm,
                "flow_ramp_sccm": flow_ramp_sccm,
                "MS_baseline_duration": MS_baseline_duration_2,
            },
        )

        # =============================================================================
        #         if electrolyte_recirculation =="on":
        #             epm.add("ECMS_sub_electrolyte_recirculation_on", {})
        # =============================================================================

        epm.add(
            "ECMS_sub_CV",
            {
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "WE_potential_init__V": WE_potential_init__V,
                "WE_potential_apex1__V": WE_potential_apex1__V,
                "WE_potential_apex2__V": WE_potential_apex2__V,
                "WE_potential_final__V": WE_potential_final__V,
                "ScanRate_V_s": ScanRate_V_s_1,
                "Cycles": Cycles,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "MS_equilibrium_time": MS_equilibrium_time,
            },
        )

        epm.add(
            "ECMS_sub_CV",
            {
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "WE_potential_init__V": WE_potential_init__V,
                "WE_potential_apex1__V": WE_potential_apex1__V,
                "WE_potential_apex2__V": WE_potential_apex2__V,
                "WE_potential_final__V": WE_potential_final__V,
                "ScanRate_V_s": ScanRate_V_s_2,
                "Cycles": Cycles,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "MS_equilibrium_time": MS_equilibrium_time,
            },
        )

        # =============================================================================
        #         if electrolyte_recirculation =="on":
        #             epm.add("ECMS_sub_electrolyte_recirculation_off", {})
        # =============================================================================

        epm.add("ECMS_sub_normal_state", {})
        epm.add("ECMS_sub_drain", {"liquid_drain_time": liquid_drain_time})
        # epm.add("ECMS_sub_electrolyte_clean_cell", {"liquid_backward_time": liquid_cleancell_time, "reservoir_liquid_sample_no":reservoir_liquid_sample_no})

    # epm.add("ECMS_sub_alloff", {})
    return epm.planned_experiments


# =============================================================================
@sequence(version=2)
def ECMS_repeat_CV_recirculation(
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 2,
    volume_ul_cell_liquid: float = 600,
    # liquid_forward_time: float = 0,
    liquid_backward_time: float = 80,
    # vacuum_time: float = 10,
    CO2equilibrium_duration: float = 30,
    flowrate_sccm: float = 3.0,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration_1: float = 90,
    MS_baseline_duration_2: float = 90,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 7.8,
    num_repeats: int = 1,
    WE_potential_init__V: float = -1.3,
    WE_potential_apex1__V: float = -2.0,
    WE_potential_apex2__V: float = -1.3,
    WE_potential_final__V: float = -1.3,
    ScanRate_V_s_1: float = 0.05,
    ScanRate_V_s_2: float = 0.02,
    Cycles: int = 3,
    SampleRate: float = 0.1,
    IErange: str = "auto",
    ref_offset: float = 0.0,
    MS_equilibrium_time: float = 120.0,
    cleaning_times: int = 1,
    liquid_fill_time: float = 7,
    tube_clear_time: float = 20,
    tube_clear_delaytime: float = 40.0,
    liquid_drain_time: float = 80.0,
    # liquid_cleancell_time: float = 120,
) -> list:
    """Recirculating-cell variant of :func:`ECMS_repeat_CV` with cleaning cycles.

    Adds ``cleaning_times`` clean cycles between CVs and uses the recirculation drain.

    Args:
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        liquid_backward_time: Parameter passed through to the sub-experiments.
        CO2equilibrium_duration: Parameter passed through to the sub-experiments.
        flowrate_sccm: Parameter passed through to the sub-experiments.
        flow_ramp_sccm: Parameter passed through to the sub-experiments.
        MS_baseline_duration_1: Parameter passed through to the sub-experiments.
        MS_baseline_duration_2: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        num_repeats: Parameter passed through to the sub-experiments.
        WE_potential_init__V: Parameter passed through to the sub-experiments.
        WE_potential_apex1__V: Parameter passed through to the sub-experiments.
        WE_potential_apex2__V: Parameter passed through to the sub-experiments.
        WE_potential_final__V: Parameter passed through to the sub-experiments.
        ScanRate_V_s_1: Parameter passed through to the sub-experiments.
        ScanRate_V_s_2: Parameter passed through to the sub-experiments.
        Cycles: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset: Parameter passed through to the sub-experiments.
        MS_equilibrium_time: Parameter passed through to the sub-experiments.
        cleaning_times: Parameter passed through to the sub-experiments.
        liquid_fill_time: Parameter passed through to the sub-experiments.
        tube_clear_time: Parameter passed through to the sub-experiments.
        tube_clear_delaytime: Parameter passed through to the sub-experiments.
        liquid_drain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ECMS_sub_unload_cell", {})
    epm.add(
        "ECMS_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    # epm.add("ECMS_sub_prevacuum_cell",{"vacuum_time": vacuum_time})

    for _ in range(num_repeats):
        epm.add(
            "ECMS_sub_electrolyte_fill_recirculationreservoir",
            {
                "liquid_fill_time": liquid_fill_time,
            },
        )

        epm.add(
            "ECMS_sub_electrolyte_fill_cell_recirculation",
            {
                "liquid_backward_time": liquid_backward_time,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )
        # achiving faster equilibrium time with faster CO2 flow rate
        epm.add(
            "ECMS_sub_headspace_purge_and_CO2baseline",
            {
                "CO2equilibrium_duration": CO2equilibrium_duration,
                "flowrate_sccm": 10.0,
                "flow_ramp_sccm": flow_ramp_sccm,
                "MS_baseline_duration": MS_baseline_duration_1,
            },
        )
        epm.add("ECMS_sub_electrolyte_recirculation_on", {})

        epm.add(
            "ECMS_sub_headspace_purge_and_CO2baseline",
            {
                "CO2equilibrium_duration": 1.0,
                "flowrate_sccm": flowrate_sccm,
                "flow_ramp_sccm": flow_ramp_sccm,
                "MS_baseline_duration": MS_baseline_duration_2,
            },
        )

        epm.add(
            "ECMS_sub_CV",
            {
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "WE_potential_init__V": WE_potential_init__V,
                "WE_potential_apex1__V": WE_potential_apex1__V,
                "WE_potential_apex2__V": WE_potential_apex2__V,
                "WE_potential_final__V": WE_potential_final__V,
                "ScanRate_V_s": ScanRate_V_s_1,
                "Cycles": Cycles,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "MS_equilibrium_time": MS_equilibrium_time,
            },
        )

        epm.add(
            "ECMS_sub_CV",
            {
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "WE_potential_init__V": WE_potential_init__V,
                "WE_potential_apex1__V": WE_potential_apex1__V,
                "WE_potential_apex2__V": WE_potential_apex2__V,
                "WE_potential_final__V": WE_potential_final__V,
                "ScanRate_V_s": ScanRate_V_s_2,
                "Cycles": Cycles,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "MS_equilibrium_time": MS_equilibrium_time,
            },
        )

        epm.add("ECMS_sub_electrolyte_recirculation_off", {})

        epm.add("ECMS_sub_normal_state", {})
        epm.add(
            "ECMS_sub_drain_recirculation",
            {
                "tube_clear_time": tube_clear_time,
                "liquid_drain_time": liquid_drain_time,
            },
        )
        epm.add(
            "ECMS_sub_clean_cell_recirculation",
            {
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
                "liquid_backward_time": liquid_backward_time,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "tube_clear_time": tube_clear_time,
                "liquid_drain_time": liquid_drain_time,
                "liquid_fill_time": liquid_fill_time + 1.0,
                "cleaning_times": cleaning_times,
                "tube_clear_delaytime": tube_clear_delaytime,
            },
        )

        # epm.add("ECMS_sub_electrolyte_clean_cell", {"liquid_backward_time": liquid_cleancell_time, "reservoir_liquid_sample_no":reservoir_liquid_sample_no})

    # epm.add("ECMS_sub_alloff", {})
    return epm.planned_experiments


# def ECMS_repeat_CV_recirculation(
#     sequence_version: int = 1,
#     plate_id: int = 4534,
#     solid_sample_no: int = 1,
#     reservoir_liquid_sample_no: int = 2,
#     volume_ul_cell_liquid: float = 600,
#     #liquid_forward_time: float = 0,
#     liquid_backward_time: float = 100,
#     #vacuum_time: float = 10,
#     CO2equilibrium_duration: float = 30,
#     flowrate_sccm: float = 3.0,
#     flow_ramp_sccm: float = 0,
#     MS_baseline_duration_1: float = 90,
#     MS_baseline_duration_2: float = 90,
#     WE_versus: str = "ref",
#     ref_type: str = "leakless",
#     pH: float = 7.8,
#     num_repeats: int = 1,
#     WE_potential_init__V: float = -1.3,
#     WE_potential_apex1__V: float = -2.0,
#     WE_potential_apex2__V: float = -1.3,
#     WE_potential_final__V: float = -1.3,
#     ScanRate_V_s_1: float = 0.05,
#     ScanRate_V_s_2: float = 0.02,
#     Cycles: int = 3,
#     SampleRate: float = 0.1,
#     IErange: str = "auto",
#     ref_offset: float = 0.0,
#     MS_equilibrium_time: float = 120.0,
#     liquid_drain_time: float = 60.0,
#     #liquid_cleancell_time: float = 120,
# ):
#
#     epm = ExperimentPlanMaker()
#
#     # housekeeping
#     epm.add("ECMS_sub_unload_cell", {})
#     epm.add(
#         "ECMS_sub_load_solid",
#         {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
#     )
#
#     #epm.add("ECMS_sub_prevacuum_cell",{"vacuum_time": vacuum_time})
#
#     for _ in range(num_repeats):
#         epm.add(
#             "ECMS_sub_electrolyte_fill_cell",
#             {
#                 #"liquid_forward_time": liquid_forward_time,
#                 "liquid_backward_time": liquid_backward_time,
#                 "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
#                 "volume_ul_cell_liquid": volume_ul_cell_liquid,
#             },
#         )
# #achiving faster equilibrium time with faster CO2 flow rate
#         epm.add(
#             "ECMS_sub_headspace_purge_and_CO2baseline",
#             {
#                 "CO2equilibrium_duration": CO2equilibrium_duration,
#                 "flowrate_sccm": 20.0,
#                 "flow_ramp_sccm": flow_ramp_sccm,
#                 "MS_baseline_duration": MS_baseline_duration_1
#             },
#         )
#         epm.add("ECMS_sub_electrolyte_recirculation_on", {})
#
#         epm.add(
#             "ECMS_sub_headspace_purge_and_CO2baseline",
#             {
#                 "CO2equilibrium_duration": 1.0,
#                 "flowrate_sccm": flowrate_sccm,
#                 "flow_ramp_sccm": flow_ramp_sccm,
#                 "MS_baseline_duration": MS_baseline_duration_2
#             },
#         )
#
#
#
#         epm.add(
#             "ECMS_sub_CV",
#             {
#                 "WE_versus": WE_versus,
#                 "ref_type": ref_type,
#                 "pH": pH,
#                 "WE_potential_init__V": WE_potential_init__V,
#                 "WE_potential_apex1__V": WE_potential_apex1__V,
#                 "WE_potential_apex2__V": WE_potential_apex2__V,
#                 "WE_potential_final__V": WE_potential_final__V,
#                 "ScanRate_V_s": ScanRate_V_s_1,
#                 "Cycles": Cycles,
#                 "SampleRate": SampleRate,
#                 "IErange": IErange,
#                 "MS_equilibrium_time": MS_equilibrium_time,
#             },
#         )
#
#         epm.add(
#             "ECMS_sub_CV",
#             {
#                 "WE_versus": WE_versus,
#                 "ref_type": ref_type,
#                 "pH": pH,
#                 "WE_potential_init__V": WE_potential_init__V,
#                 "WE_potential_apex1__V": WE_potential_apex1__V,
#                 "WE_potential_apex2__V": WE_potential_apex2__V,
#                 "WE_potential_final__V": WE_potential_final__V,
#                 "ScanRate_V_s": ScanRate_V_s_2,
#                 "Cycles": Cycles,
#                 "SampleRate": SampleRate,
#                 "IErange": IErange,
#                 "MS_equilibrium_time": MS_equilibrium_time,
#             },
#         )
#
#         epm.add("ECMS_sub_electrolyte_recirculation_off", {})
#
#         epm.add("ECMS_sub_normal_state",{})
#         epm.add("ECMS_sub_drain_recirculation", {"liquid_drain_time": liquid_drain_time})
#         #epm.add("ECMS_sub_electrolyte_clean_cell", {"liquid_backward_time": liquid_cleancell_time, "reservoir_liquid_sample_no":reservoir_liquid_sample_no})
#
#     #epm.add("ECMS_sub_alloff", {})
#     return epm.planned_experiments
# =============================================================================


@sequence(version=2)
def ECMS_repeat_CV_recirculation_mixedreactant(
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 2,
    volume_ul_cell_liquid: float = 600,
    # liquid_forward_time: float = 0,
    liquid_backward_time: float = 80,
    # vacuum_time: float = 10,
    CO2equilibrium_duration: float = 30,
    CO2flowrate_sccm: float = 1.2,
    Califlowrate_sccm: float = 1.8,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration_1: float = 90,
    MS_baseline_duration_2: float = 180,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 7.8,
    num_repeats: int = 1,
    WE_potential_init__V: float = -1.3,
    WE_potential_apex1__V: float = -2.0,
    WE_potential_apex2__V: float = -1.3,
    WE_potential_final__V: float = -1.3,
    ScanRate_V_s_1: float = 0.05,
    ScanRate_V_s_2: float = 0.02,
    Cycles: int = 3,
    SampleRate: float = 0.1,
    IErange: str = "auto",
    ref_offset: float = 0.0,
    MS_equilibrium_time: float = 120.0,
    cleaning_times: int = 1,
    liquid_fill_time: float = 7,
    tube_clear_time: float = 20,
    tube_clear_delaytime: float = 40.0,
    liquid_drain_time: float = 80.0,
    # liquid_cleancell_time: float = 120,
) -> list:
    """Recirculating CV protocol using a mixed-reactant calibration baseline.

    Adapts :func:`ECMS_repeat_CV_recirculation` to take a calibration baseline at each iteration.

    Args:
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        liquid_backward_time: Parameter passed through to the sub-experiments.
        CO2equilibrium_duration: Parameter passed through to the sub-experiments.
        CO2flowrate_sccm: Parameter passed through to the sub-experiments.
        Califlowrate_sccm: Parameter passed through to the sub-experiments.
        flow_ramp_sccm: Parameter passed through to the sub-experiments.
        MS_baseline_duration_1: Parameter passed through to the sub-experiments.
        MS_baseline_duration_2: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        num_repeats: Parameter passed through to the sub-experiments.
        WE_potential_init__V: Parameter passed through to the sub-experiments.
        WE_potential_apex1__V: Parameter passed through to the sub-experiments.
        WE_potential_apex2__V: Parameter passed through to the sub-experiments.
        WE_potential_final__V: Parameter passed through to the sub-experiments.
        ScanRate_V_s_1: Parameter passed through to the sub-experiments.
        ScanRate_V_s_2: Parameter passed through to the sub-experiments.
        Cycles: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset: Parameter passed through to the sub-experiments.
        MS_equilibrium_time: Parameter passed through to the sub-experiments.
        cleaning_times: Parameter passed through to the sub-experiments.
        liquid_fill_time: Parameter passed through to the sub-experiments.
        tube_clear_time: Parameter passed through to the sub-experiments.
        tube_clear_delaytime: Parameter passed through to the sub-experiments.
        liquid_drain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ECMS_sub_unload_cell", {})
    epm.add(
        "ECMS_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    # epm.add("ECMS_sub_prevacuum_cell",{"vacuum_time": vacuum_time})

    for _ in range(num_repeats):
        epm.add(
            "ECMS_sub_electrolyte_fill_recirculationreservoir",
            {
                "liquid_fill_time": liquid_fill_time,
            },
        )

        epm.add(
            "ECMS_sub_electrolyte_fill_cell_recirculation",
            {
                "liquid_backward_time": liquid_backward_time,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )
        # achiving faster equilibrium time with faster CO2 flow rate
        epm.add(
            "ECMS_sub_headspace_purge_and_CO2baseline",
            {
                "CO2equilibrium_duration": CO2equilibrium_duration,
                "flowrate_sccm": 10.0,
                "flow_ramp_sccm": flow_ramp_sccm,
                "MS_baseline_duration": MS_baseline_duration_1,
            },
        )
        epm.add("ECMS_sub_electrolyte_recirculation_on", {})

        epm.add(
            "ECMS_sub_cali",
            {
                "CO2flowrate_sccm": CO2flowrate_sccm,
                "Califlowrate_sccm": Califlowrate_sccm,
                "MSsignal_quilibrium_time": MS_baseline_duration_2,
            },
        )

        epm.add(
            "ECMS_sub_CV",
            {
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "WE_potential_init__V": WE_potential_init__V,
                "WE_potential_apex1__V": WE_potential_apex1__V,
                "WE_potential_apex2__V": WE_potential_apex2__V,
                "WE_potential_final__V": WE_potential_final__V,
                "ScanRate_V_s": ScanRate_V_s_1,
                "Cycles": Cycles,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "MS_equilibrium_time": MS_equilibrium_time,
            },
        )

        epm.add(
            "ECMS_sub_CV",
            {
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "WE_potential_init__V": WE_potential_init__V,
                "WE_potential_apex1__V": WE_potential_apex1__V,
                "WE_potential_apex2__V": WE_potential_apex2__V,
                "WE_potential_final__V": WE_potential_final__V,
                "ScanRate_V_s": ScanRate_V_s_2,
                "Cycles": Cycles,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "MS_equilibrium_time": MS_equilibrium_time,
            },
        )

        epm.add("ECMS_sub_electrolyte_recirculation_off", {})

        epm.add("ECMS_sub_normal_state", {})
        epm.add(
            "ECMS_sub_drain_recirculation",
            {
                "tube_clear_time": tube_clear_time,
                "liquid_drain_time": liquid_drain_time,
            },
        )
        epm.add(
            "ECMS_sub_clean_cell_recirculation",
            {
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
                "liquid_backward_time": liquid_backward_time,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "tube_clear_time": tube_clear_time,
                "liquid_drain_time": liquid_drain_time,
                "liquid_fill_time": liquid_fill_time + 1.0,
                "cleaning_times": cleaning_times,
                "tube_clear_delaytime": tube_clear_delaytime,
            },
        )

        # epm.add("ECMS_sub_electrolyte_clean_cell", {"liquid_backward_time": liquid_cleancell_time, "reservoir_liquid_sample_no":reservoir_liquid_sample_no})

    # epm.add("ECMS_sub_alloff", {})
    return epm.planned_experiments


@sequence(version=3)
def ECMS_CV_recirculation_mixedreactant(
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 2,
    volume_ul_cell_liquid: float = 2090,
    # liquid_forward_time: float = 0,
    liquid_backward_time: float = 35,
    # vacuum_time: float = 10,
    CO2equilibrium_duration: float = 30,
    CO2flowrate_sccm: List[float] = [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 10],
    Califlowrate_sccm: List[float] = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 0],
    flow_ramp_sccm: float = 0,
    MS_baseline_duration_1: float = 90,
    MS_baseline_duration_2: float = 180,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 7.8,
    WE_potential_init__V: float = -0.5,
    WE_potential_apex1__V: float = -2.0,
    WE_potential_apex2__V: float = -0.5,
    WE_potential_final__V: float = -0.5,
    ScanRate_V_s_1: float = 0.02,
    Cycles: int = 1,
    SampleRate: float = 0.1,
    IErange: str = "30mA",
    ref_offset: float = 0.0,
    MS_equilibrium_time: float = 120.0,
    cleaning_times: int = 0,
    liquid_fill_time: float = 22.5,
    tube_clear_time: float = 15,
    tube_clear_delaytime: float = 40.0,
    liquid_drain_time: float = 170.0,
    # liquid_cleancell_time: float = 120,
) -> list:
    """Single CV pass with mixed-reactant calibration baseline (recirculating cell).

    One-shot variant of the recirculating mixed-reactant CV protocol.

    Args:
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        liquid_backward_time: Parameter passed through to the sub-experiments.
        CO2equilibrium_duration: Parameter passed through to the sub-experiments.
        CO2flowrate_sccm: Parameter passed through to the sub-experiments.
        Califlowrate_sccm: Parameter passed through to the sub-experiments.
        flow_ramp_sccm: Parameter passed through to the sub-experiments.
        MS_baseline_duration_1: Parameter passed through to the sub-experiments.
        MS_baseline_duration_2: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        WE_potential_init__V: Parameter passed through to the sub-experiments.
        WE_potential_apex1__V: Parameter passed through to the sub-experiments.
        WE_potential_apex2__V: Parameter passed through to the sub-experiments.
        WE_potential_final__V: Parameter passed through to the sub-experiments.
        ScanRate_V_s_1: Parameter passed through to the sub-experiments.
        Cycles: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset: Parameter passed through to the sub-experiments.
        MS_equilibrium_time: Parameter passed through to the sub-experiments.
        cleaning_times: Parameter passed through to the sub-experiments.
        liquid_fill_time: Parameter passed through to the sub-experiments.
        tube_clear_time: Parameter passed through to the sub-experiments.
        tube_clear_delaytime: Parameter passed through to the sub-experiments.
        liquid_drain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ECMS_sub_unload_cell", {})
    epm.add(
        "ECMS_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    # epm.add("ECMS_sub_prevacuum_cell",{"vacuum_time": vacuum_time})

    epm.add(
        "ECMS_sub_electrolyte_fill_recirculationreservoir",
        {
            "liquid_fill_time": liquid_fill_time,
        },
    )

    epm.add(
        "ECMS_sub_electrolyte_fill_cell_recirculation",
        {
            "liquid_backward_time": liquid_backward_time,
            "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
            "volume_ul_cell_liquid": volume_ul_cell_liquid,
        },
    )
    # achiving faster equilibrium time with faster CO2 flow rate
    epm.add(
        "ECMS_sub_headspace_purge_and_CO2baseline",
        {
            "CO2equilibrium_duration": CO2equilibrium_duration,
            "flowrate_sccm": 10.0,
            "flow_ramp_sccm": flow_ramp_sccm,
            "MS_baseline_duration": MS_baseline_duration_1,
        },
    )
    epm.add("ECMS_sub_electrolyte_recirculation_on", {})

    for cycle, (CO2flowrate, Califlowrate) in enumerate(
        zip(CO2flowrate_sccm, Califlowrate_sccm)
    ):

        epm.add(
            "ECMS_sub_cali",
            {
                "CO2flowrate_sccm": CO2flowrate,
                "Califlowrate_sccm": Califlowrate,
                "MSsignal_quilibrium_time": MS_baseline_duration_2,
            },
        )

        epm.add(
            "ECMS_sub_CV",
            {
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "WE_potential_init__V": WE_potential_init__V,
                "WE_potential_apex1__V": WE_potential_apex1__V,
                "WE_potential_apex2__V": WE_potential_apex2__V,
                "WE_potential_final__V": WE_potential_final__V,
                "ScanRate_V_s": ScanRate_V_s_1,
                "Cycles": Cycles,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "MS_equilibrium_time": MS_equilibrium_time,
            },
        )

    epm.add("ECMS_sub_electrolyte_recirculation_off", {})

    epm.add("ECMS_sub_normal_state", {})
    epm.add(
        "ECMS_sub_drain_recirculation",
        {"tube_clear_time": tube_clear_time, "liquid_drain_time": liquid_drain_time},
    )
    epm.add(
        "ECMS_sub_clean_cell_recirculation",
        {
            "volume_ul_cell_liquid": volume_ul_cell_liquid,
            "liquid_backward_time": liquid_backward_time,
            "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
            "tube_clear_time": tube_clear_time,
            "liquid_drain_time": liquid_drain_time,
            "liquid_fill_time": liquid_fill_time + 1.0,
            "cleaning_times": cleaning_times,
            "tube_clear_delaytime": tube_clear_delaytime,
        },
    )

    # epm.add("ECMS_sub_electrolyte_clean_cell", {"liquid_backward_time": liquid_cleancell_time, "reservoir_liquid_sample_no":reservoir_liquid_sample_no})

    # epm.add("ECMS_sub_alloff", {})
    return epm.planned_experiments


@sequence(version=2)
def ECMS_series_CA(
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 2,
    volume_ul_cell_liquid: float = 600,
    # liquid_forward_time: float = 0,
    liquid_backward_time: float = 100,
    # vacuum_time: float = 10,
    CO2equilibrium_duration: float = 30,
    flowrate_sccm: float = 3.0,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration_1: float = 90,
    MS_baseline_duration_2: float = 90,
    WE_potential__V: List[float] = [-1.4, -1.6, -1.8, -1.9, -2.0],
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 7.8,
    CA_duration_sec: List[float] = [600, 600, 600, 600, 600],
    SampleRate: float = 1,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    MS_equilibrium_time: float = 120.0,
    liquid_drain_time: float = 60.0,
    # electrolyte_recirculation: str = "on",
    # liquid_cleancell_time: float = 120,
) -> list:
    """Run a CA series sweeping through ``WE_potential__V`` values.

    For each potential: fill, run CO2 baselines, run CA, then drain.

    Args:
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        liquid_backward_time: Parameter passed through to the sub-experiments.
        CO2equilibrium_duration: Parameter passed through to the sub-experiments.
        flowrate_sccm: Parameter passed through to the sub-experiments.
        flow_ramp_sccm: Parameter passed through to the sub-experiments.
        MS_baseline_duration_1: Parameter passed through to the sub-experiments.
        MS_baseline_duration_2: Parameter passed through to the sub-experiments.
        WE_potential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        CA_duration_sec: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        MS_equilibrium_time: Parameter passed through to the sub-experiments.
        liquid_drain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ECMS_sub_unload_cell", {})
    epm.add(
        "ECMS_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )
    # epm.add("ECMS_sub_prevacuum_cell",{"vacuum_time": vacuum_time})

    for cycle, (potential, time) in enumerate(zip(WE_potential__V, CA_duration_sec)):
        print(
            f" ... cycle {cycle} potential:",
            potential,
            f" ... cycle {cycle} duration:",
            time,
        )
        epm.add(
            "ECMS_sub_electrolyte_fill_cell",
            {
                # "liquid_forward_time": liquid_forward_time,
                "liquid_backward_time": liquid_backward_time,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )
        # achiving faster equilibrium time with faster CO2 flow rate
        epm.add(
            "ECMS_sub_headspace_purge_and_CO2baseline",
            {
                "CO2equilibrium_duration": CO2equilibrium_duration,
                "flowrate_sccm": 10.0,
                "flow_ramp_sccm": flow_ramp_sccm,
                "MS_baseline_duration": MS_baseline_duration_1,
            },
        )

        epm.add(
            "ECMS_sub_headspace_purge_and_CO2baseline",
            {
                "CO2equilibrium_duration": 1.0,
                "flowrate_sccm": flowrate_sccm,
                "flow_ramp_sccm": flow_ramp_sccm,
                "MS_baseline_duration": MS_baseline_duration_2,
            },
        )

        # =============================================================================
        #         if electrolyte_recirculation =="on":
        #             epm.add("ECMS_sub_electrolyte_recirculation_on", {})
        # =============================================================================

        epm.add(
            "ECMS_sub_CA",
            {
                "WE_potential__V": potential,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": time,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "MS_equilibrium_time": MS_equilibrium_time,
            },
        )
        # =============================================================================
        #         if electrolyte_recirculation =="on":
        #             epm.add("ECMS_sub_electrolyte_recirculation_off", {})
        # =============================================================================

        epm.add("ECMS_sub_normal_state", {})
        epm.add("ECMS_sub_drain", {"liquid_drain_time": liquid_drain_time})
    return epm.planned_experiments


# =============================================================================
# def ECMS_series_CA_recirculation(
#     sequence_version: int = 1,
#     plate_id: int = 4534,
#     solid_sample_no: int = 1,
#     reservoir_liquid_sample_no: int = 2,
#     volume_ul_cell_liquid: float = 600,
#     #liquid_forward_time: float = 0,
#     liquid_backward_time: float = 100,
#     #vacuum_time: float = 10,
#     CO2equilibrium_duration: float = 30,
#     flowrate_sccm: float = 3.0,
#     flow_ramp_sccm: float = 0,
#     MS_baseline_duration_1: float = 90,
#     MS_baseline_duration_2: float = 90,
#     WE_potential__V: List[float] = [-1.4, -1.6, -1.8, -1.9, -2.0],
#     WE_versus: str = "ref",
#     ref_type: str = "leakless",
#     pH: float = 7.8,
#     CA_duration_sec: List[float] = [600, 600, 600, 600, 600],
#     SampleRate: float = 1,
#     IErange: str = "auto",
#     ref_offset__V: float = 0.0,
#     MS_equilibrium_time: float = 120.0,
#     liquid_drain_time: float = 60.0,
#     #liquid_cleancell_time: float = 120,
# ):
#
#
#     epm = ExperimentPlanMaker()
#
#     # housekeeping
#     epm.add("ECMS_sub_unload_cell", {})
#     epm.add(
#         "ECMS_sub_load_solid",
#         {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
#     )
#     #epm.add("ECMS_sub_prevacuum_cell",{"vacuum_time": vacuum_time})
#
#     for cycle, (potential, time) in enumerate(zip(WE_potential__V, CA_duration_sec)):
#         print(f" ... cycle {cycle} potential:", potential, f" ... cycle {cycle} duration:", time)
#         epm.add(
#             "ECMS_sub_electrolyte_fill_cell",
#             {
#                 #"liquid_forward_time": liquid_forward_time,
#                 "liquid_backward_time": liquid_backward_time,
#                 "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
#                 "volume_ul_cell_liquid": volume_ul_cell_liquid,
#             },
#         )
# #achiving faster equilibrium time with faster CO2 flow rate
#         epm.add(
#             "ECMS_sub_headspace_purge_and_CO2baseline",
#             {
#                 "CO2equilibrium_duration": CO2equilibrium_duration,
#                 "flowrate_sccm": 20.0,
#                 "flow_ramp_sccm": flow_ramp_sccm,
#                 "MS_baseline_duration": MS_baseline_duration_1
#             },
#         )
#         epm.add("ECMS_sub_electrolyte_recirculation_on", {})
#
#         epm.add(
#             "ECMS_sub_headspace_purge_and_CO2baseline",
#             {
#                 "CO2equilibrium_duration": 1.0,
#                 "flowrate_sccm": flowrate_sccm,
#                 "flow_ramp_sccm": flow_ramp_sccm,
#                 "MS_baseline_duration": MS_baseline_duration_2
#             },
#         )
#
#
#         epm.add(
#             "ECMS_sub_CA",
#             {
#                 "WE_potential__V": potential,
#                 "WE_versus": WE_versus,
#                 "ref_type": ref_type,
#                 "pH": pH,
#                 "ref_offset__V": ref_offset__V,
#                 "CA_duration_sec": time,
#                 "SampleRate": SampleRate,
#                 "IErange": IErange,
#                 "MS_equilibrium_time": MS_equilibrium_time,
#             },
#         )
#         epm.add("ECMS_sub_electrolyte_recirculation_off", {})
#
#         epm.add("ECMS_sub_normal_state",{})
#         epm.add("ECMS_sub_drain_recirculation", {"liquid_drain_time": liquid_drain_time})
#     return epm.planned_experiments
# =============================================================================
@sequence(version=3)
def ECMS_series_CA_recirculation(
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 2,
    volume_ul_cell_liquid: float = 600,
    # liquid_forward_time: float = 0,
    liquid_backward_time: float = 80,
    # vacuum_time: float = 10,
    CO2equilibrium_duration: float = 30,
    flowrate_sccm: float = 3.0,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration_1: float = 90,
    MS_baseline_duration_2: float = 90,
    WE_potential__V: List[float] = [-1.4, -1.6, -1.8, -1.9, -2.0],
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 7.8,
    CA_duration_sec: List[float] = [600, 600, 600, 600, 600],
    SampleRate: float = 1,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    MS_equilibrium_time: float = 120.0,
    cleaning_times: int = 1,
    liquid_fill_time: float = 7,
    liquid_drain_time: float = 60.0,
    tube_clear_time: float = 20,
    tube_clear_delaytime: float = 40.0,
    # liquid_cleancell_time: float = 120,
) -> list:
    """Recirculating-cell variant of :func:`ECMS_series_CA`.

    Adds the recirculation reservoir fill and drain and inserts cleaning cycles.

    Args:
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        liquid_backward_time: Parameter passed through to the sub-experiments.
        CO2equilibrium_duration: Parameter passed through to the sub-experiments.
        flowrate_sccm: Parameter passed through to the sub-experiments.
        flow_ramp_sccm: Parameter passed through to the sub-experiments.
        MS_baseline_duration_1: Parameter passed through to the sub-experiments.
        MS_baseline_duration_2: Parameter passed through to the sub-experiments.
        WE_potential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        CA_duration_sec: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        MS_equilibrium_time: Parameter passed through to the sub-experiments.
        cleaning_times: Parameter passed through to the sub-experiments.
        liquid_fill_time: Parameter passed through to the sub-experiments.
        liquid_drain_time: Parameter passed through to the sub-experiments.
        tube_clear_time: Parameter passed through to the sub-experiments.
        tube_clear_delaytime: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ECMS_sub_unload_cell", {})
    epm.add(
        "ECMS_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )
    # epm.add("ECMS_sub_prevacuum_cell",{"vacuum_time": vacuum_time})

    for cycle, (potential, time) in enumerate(zip(WE_potential__V, CA_duration_sec)):
        print(
            f" ... cycle {cycle} potential:",
            potential,
            f" ... cycle {cycle} duration:",
            time,
        )
        epm.add(
            "ECMS_sub_electrolyte_fill_recirculationreservoir",
            {
                "liquid_fill_time": liquid_fill_time,
            },
        )

        epm.add(
            "ECMS_sub_electrolyte_fill_cell_recirculation",
            {
                "liquid_backward_time": liquid_backward_time,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )
        # achiving faster equilibrium time with faster CO2 flow rate
        epm.add(
            "ECMS_sub_headspace_purge_and_CO2baseline",
            {
                "CO2equilibrium_duration": CO2equilibrium_duration,
                "flowrate_sccm": 10.0,
                "flow_ramp_sccm": flow_ramp_sccm,
                "MS_baseline_duration": MS_baseline_duration_1,
            },
        )
        epm.add("ECMS_sub_electrolyte_recirculation_on", {})

        epm.add(
            "ECMS_sub_headspace_purge_and_CO2baseline",
            {
                "CO2equilibrium_duration": 1.0,
                "flowrate_sccm": flowrate_sccm,
                "flow_ramp_sccm": flow_ramp_sccm,
                "MS_baseline_duration": MS_baseline_duration_2,
            },
        )

        epm.add(
            "ECMS_sub_CA",
            {
                "WE_potential__V": potential,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": time,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "MS_equilibrium_time": MS_equilibrium_time,
            },
        )
        epm.add("ECMS_sub_electrolyte_recirculation_off", {})

        epm.add("ECMS_sub_normal_state", {})
        epm.add(
            "ECMS_sub_drain_recirculation",
            {
                "tube_clear_time": tube_clear_time,
                "liquid_drain_time": liquid_drain_time,
            },
        )
        epm.add(
            "ECMS_sub_clean_cell_recirculation",
            {
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
                "liquid_backward_time": liquid_backward_time,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "tube_clear_time": tube_clear_time,
                "liquid_drain_time": liquid_drain_time,
                "liquid_fill_time": liquid_fill_time + 1.0,
                "cleaning_times": cleaning_times,
                "tube_clear_delaytime": tube_clear_delaytime,
            },
        )

    return epm.planned_experiments


@sequence(version=3)
def ECMS_series_CA_recirculation_mixedreactant(
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 2,
    volume_ul_cell_liquid: float = 600,
    # liquid_forward_time: float = 0,
    liquid_backward_time: float = 80,
    # vacuum_time: float = 10,
    CO2equilibrium_duration: float = 30,
    CO2flowrate_sccm: float = 1.2,
    Califlowrate_sccm: float = 1.8,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration_1: float = 90,
    MS_baseline_duration_2: float = 180,
    WE_potential__V: List[float] = [-1.4, -1.6, -1.8, -1.9, -2.0],
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 7.8,
    CA_duration_sec: List[float] = [600, 600, 600, 600, 600],
    SampleRate: float = 1,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    MS_equilibrium_time: float = 120.0,
    cleaning_times: int = 1,
    liquid_fill_time: float = 7,
    liquid_drain_time: float = 60.0,
    tube_clear_time: float = 20,
    tube_clear_delaytime: float = 40.0,
    # liquid_cleancell_time: float = 120,
) -> list:
    """Recirculating CA series with mixed-reactant calibration baselines.

    Same loop as :func:`ECMS_series_CA_recirculation` but with ``ECMS_sub_cali`` baselines.

    Args:
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        liquid_backward_time: Parameter passed through to the sub-experiments.
        CO2equilibrium_duration: Parameter passed through to the sub-experiments.
        CO2flowrate_sccm: Parameter passed through to the sub-experiments.
        Califlowrate_sccm: Parameter passed through to the sub-experiments.
        flow_ramp_sccm: Parameter passed through to the sub-experiments.
        MS_baseline_duration_1: Parameter passed through to the sub-experiments.
        MS_baseline_duration_2: Parameter passed through to the sub-experiments.
        WE_potential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        CA_duration_sec: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        MS_equilibrium_time: Parameter passed through to the sub-experiments.
        cleaning_times: Parameter passed through to the sub-experiments.
        liquid_fill_time: Parameter passed through to the sub-experiments.
        liquid_drain_time: Parameter passed through to the sub-experiments.
        tube_clear_time: Parameter passed through to the sub-experiments.
        tube_clear_delaytime: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ECMS_sub_unload_cell", {})
    epm.add(
        "ECMS_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )
    # epm.add("ECMS_sub_prevacuum_cell",{"vacuum_time": vacuum_time})

    for cycle, (potential, time) in enumerate(zip(WE_potential__V, CA_duration_sec)):
        print(
            f" ... cycle {cycle} potential:",
            potential,
            f" ... cycle {cycle} duration:",
            time,
        )
        epm.add(
            "ECMS_sub_electrolyte_fill_recirculationreservoir",
            {
                "liquid_fill_time": liquid_fill_time,
            },
        )

        epm.add(
            "ECMS_sub_electrolyte_fill_cell_recirculation",
            {
                "liquid_backward_time": liquid_backward_time,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )
        # achiving faster equilibrium time with faster CO2 flow rate
        epm.add(
            "ECMS_sub_headspace_purge_and_CO2baseline",
            {
                "CO2equilibrium_duration": CO2equilibrium_duration,
                "flowrate_sccm": 10.0,
                "flow_ramp_sccm": flow_ramp_sccm,
                "MS_baseline_duration": MS_baseline_duration_1,
            },
        )
        epm.add("ECMS_sub_electrolyte_recirculation_on", {})

        epm.add(
            "ECMS_sub_cali",
            {
                "CO2flowrate_sccm": CO2flowrate_sccm,
                "Califlowrate_sccm": Califlowrate_sccm,
                "MSsignal_quilibrium_time": MS_baseline_duration_2,
            },
        )

        epm.add(
            "ECMS_sub_CA",
            {
                "WE_potential__V": potential,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": time,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "MS_equilibrium_time": MS_equilibrium_time,
            },
        )
        epm.add("ECMS_sub_electrolyte_recirculation_off", {})

        epm.add("ECMS_sub_normal_state", {})
        epm.add(
            "ECMS_sub_drain_recirculation",
            {
                "tube_clear_time": tube_clear_time,
                "liquid_drain_time": liquid_drain_time,
            },
        )
        epm.add(
            "ECMS_sub_clean_cell_recirculation",
            {
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
                "liquid_backward_time": liquid_backward_time,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "tube_clear_time": tube_clear_time,
                "liquid_drain_time": liquid_drain_time,
                "liquid_fill_time": liquid_fill_time + 1.0,
                "cleaning_times": cleaning_times,
                "tube_clear_delaytime": tube_clear_delaytime,
            },
        )

    return epm.planned_experiments


@sequence(version=1)
def ECMS_series_CA_recirculation_mixedthreereactant(
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1,
    volume_ul_cell_liquid: float = 2090,
    # liquid_forward_time: float = 0,
    liquid_backward_time: float = 35,
    # vacuum_time: float = 10,
    CO2equilibrium_duration: float = 30,
    CO2flowrate_sccm: List[float] = [6.0, 6.0, 6.0, 6.0, 6.0],
    Califlowrate_sccm: List[float] = [0.0, 1.0, 2.0, 3.0, 4.0],  # O2
    Califlowrate_two_sccm: List[float] = [4.0, 3.0, 2.0, 1.0, 0.0],  # Ar
    flow_ramp_sccm: float = 0,
    MS_baseline_duration_1: float = 90,
    MS_baseline_duration_2: float = 180,
    WE_potential__V: List[float] = [-1.9],
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 7.8,
    CA_duration_sec: List[float] = [600],
    SampleRate: float = 1,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    MS_equilibrium_time: float = 120.0,
    cleaning_times: int = 1,
    liquid_fill_time: float = 9,
    liquid_drain_time: float = 65.0,
    tube_clear_time: float = 10,
    tube_clear_delaytime: float = 40.0,
    # liquid_cleancell_time: float = 120,
) -> list:
    """Recirculating CA series with a three-reactant calibration baseline.

    Three-gas variant of the mixed-reactant CA protocol.

    Args:
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        liquid_backward_time: Parameter passed through to the sub-experiments.
        CO2equilibrium_duration: Parameter passed through to the sub-experiments.
        CO2flowrate_sccm: Parameter passed through to the sub-experiments.
        Califlowrate_sccm: Parameter passed through to the sub-experiments.
        MS_baseline_duration_1: Parameter passed through to the sub-experiments.
        MS_baseline_duration_2: Parameter passed through to the sub-experiments.
        WE_potential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        CA_duration_sec: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        MS_equilibrium_time: Parameter passed through to the sub-experiments.
        cleaning_times: Parameter passed through to the sub-experiments.
        liquid_fill_time: Parameter passed through to the sub-experiments.
        liquid_drain_time: Parameter passed through to the sub-experiments.
        tube_clear_time: Parameter passed through to the sub-experiments.
        tube_clear_delaytime: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ECMS_sub_unload_cell", {})
    epm.add(
        "ECMS_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )
    # epm.add("ECMS_sub_prevacuum_cell",{"vacuum_time": vacuum_time})

    for cycle, (potential, time) in enumerate(zip(WE_potential__V, CA_duration_sec)):
        print(
            f" ... cycle {cycle} potential:",
            potential,
            f" ... cycle {cycle} duration:",
            time,
        )
        for conditionnumber, (CO2_flow, O2_flow, Ar_flow) in enumerate(
            zip(CO2flowrate_sccm, Califlowrate_sccm, Califlowrate_two_sccm)
        ):
            epm.add(
                "ECMS_sub_electrolyte_fill_recirculationreservoir",
                {
                    "liquid_fill_time": liquid_fill_time,
                },
            )

            epm.add(
                "ECMS_sub_electrolyte_fill_cell_recirculation",
                {
                    "liquid_backward_time": liquid_backward_time,
                    "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                    "volume_ul_cell_liquid": volume_ul_cell_liquid,
                },
            )
            # achiving faster equilibrium time with faster CO2 flow rate
            epm.add(
                "ECMS_sub_headspace_purge_and_CO2baseline",
                {
                    "CO2equilibrium_duration": CO2equilibrium_duration,
                    "flowrate_sccm": 10.0,
                    "flow_ramp_sccm": flow_ramp_sccm,
                    "MS_baseline_duration": MS_baseline_duration_1,
                },
            )
            epm.add("ECMS_sub_electrolyte_recirculation_on", {})

            epm.add(
                "ECMS_sub_threegascali",
                {
                    "CO2flowrate_sccm": CO2_flow,
                    "Califlowrate_sccm": O2_flow,
                    "Califlowrate_two_sccm": Ar_flow,
                    "MSsignal_quilibrium_time": MS_baseline_duration_2,
                },
            )

            epm.add(
                "ECMS_sub_CA",
                {
                    "WE_potential__V": potential,
                    "WE_versus": WE_versus,
                    "ref_type": ref_type,
                    "pH": pH,
                    "ref_offset__V": ref_offset__V,
                    "CA_duration_sec": time,
                    "SampleRate": SampleRate,
                    "IErange": IErange,
                    "MS_equilibrium_time": MS_equilibrium_time,
                },
            )
            epm.add("ECMS_sub_electrolyte_recirculation_off", {})

            epm.add("ECMS_sub_normal_state", {})
            epm.add(
                "ECMS_sub_drain_recirculation",
                {
                    "tube_clear_time": tube_clear_time,
                    "liquid_drain_time": liquid_drain_time,
                },
            )
            epm.add(
                "ECMS_sub_clean_cell_recirculation",
                {
                    "volume_ul_cell_liquid": volume_ul_cell_liquid,
                    "liquid_backward_time": liquid_backward_time,
                    "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                    "tube_clear_time": tube_clear_time,
                    "liquid_drain_time": liquid_drain_time,
                    "liquid_fill_time": liquid_fill_time + 1.0,
                    "cleaning_times": cleaning_times,
                    "tube_clear_delaytime": tube_clear_delaytime,
                },
            )

    return epm.planned_experiments


@sequence(version=2)
def ECMS_series_pulseCA(
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 2,
    volume_ul_cell_liquid: float = 600,
    # liquid_forward_time: float = 0,
    liquid_backward_time: float = 100,
    CO2equilibrium_duration: float = 30,
    flowrate_sccm: float = 3.0,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration_1: float = 90,
    MS_baseline_duration_2: float = 90,
    WE_pulsepotential__V: List[float] = [-1.5, -1.6, -1.8, -1.9, -2.0],
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 7.8,
    SampleRate: float = 1,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    MS_equilibrium_time: float = 120.0,
    liquid_drain_time: float = 60.0,
    Vinit__V: float = 0.0,
    Tinit__s: float = 5.0,
    Tstep__s: float = 5.0,
    Cycles: int = 60,
    AcqInterval__s: float = 0.01,  # acquisition rate
    run_OCV: bool = False,
    Tocv__s: float = 60.0,
) -> list:
    """Pulsed CA series alternating between potentials in a recirculating cell.

    Runs sequence of pulsed CA segments separated by recovery holds.

    Args:
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        liquid_backward_time: Parameter passed through to the sub-experiments.
        CO2equilibrium_duration: Parameter passed through to the sub-experiments.
        flowrate_sccm: Parameter passed through to the sub-experiments.
        flow_ramp_sccm: Parameter passed through to the sub-experiments.
        MS_baseline_duration_1: Parameter passed through to the sub-experiments.
        MS_baseline_duration_2: Parameter passed through to the sub-experiments.
        WE_pulsepotential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        MS_equilibrium_time: Parameter passed through to the sub-experiments.
        liquid_drain_time: Parameter passed through to the sub-experiments.
        Vinit__V: Parameter passed through to the sub-experiments.
        Tinit__s: Parameter passed through to the sub-experiments.
        Tstep__s: Parameter passed through to the sub-experiments.
        Cycles: Parameter passed through to the sub-experiments.
        AcqInterval__s: Parameter passed through to the sub-experiments.
        Tocv__s: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ECMS_sub_unload_cell", {})
    epm.add(
        "ECMS_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )
    # epm.add("ECMS_sub_prevacuum_cell",{"vacuum_time": vacuum_time})

    for cycle, potential in enumerate(WE_pulsepotential__V):
        epm.add(
            "ECMS_sub_electrolyte_fill_cell",
            {
                # "liquid_forward_time": liquid_forward_time,
                "liquid_backward_time": liquid_backward_time,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )
        # achiving faster equilibrium time with faster CO2 flow rate
        epm.add(
            "ECMS_sub_headspace_purge_and_CO2baseline",
            {
                "CO2equilibrium_duration": CO2equilibrium_duration,
                "flowrate_sccm": 10.0,
                "flow_ramp_sccm": flow_ramp_sccm,
                "MS_baseline_duration": MS_baseline_duration_1,
            },
        )

        epm.add(
            "ECMS_sub_headspace_purge_and_CO2baseline",
            {
                "CO2equilibrium_duration": 1.0,
                "flowrate_sccm": flowrate_sccm,
                "flow_ramp_sccm": flow_ramp_sccm,
                "MS_baseline_duration": MS_baseline_duration_2,
            },
        )

        epm.add(
            "ECMS_sub_pulseCA",
            {
                "Vinit__V": Vinit__V,
                "Vstep__V": potential,
                "Tinit__s": Tinit__s,
                "Tstep__s": Tstep__s,
                "Cycles": Cycles,
                "AcqInterval__s": AcqInterval__s,
                "Tocv__s": Tocv__s,
                "run_OCV": run_OCV,
            },
        )
        epm.add("ECMS_sub_normal_state", {})
        epm.add("ECMS_sub_drain", {"liquid_drain_time": liquid_drain_time})
    return epm.planned_experiments


@sequence(version=2)
def ECMS_MS_calibration_recirculation(
    reservoir_liquid_sample_no: int = 2,
    liquid_fill_time: float = 15,
    volume_ul_cell_liquid: float = 600,
    # liquid_forward_time: float = 20,
    liquid_backward_time: float = 80,
    CO2equilibrium_duration: float = 30,
    flowrate_sccm: float = 20.0,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration_1: float = 120,
    CO2flowrate_sccm: List[float] = [19, 18, 17, 16, 15],
    Califlowrate_sccm: List[float] = [1, 2, 3, 4, 5],
    MSsignal_quilibrium_time_initial: float = 480,
    MSsignal_quilibrium_time: float = 300,
    liquid_drain_time: float = 60.0,
    tube_clear_time: float = 20,
) -> list:
    """Calibrate the mass spec in the recirculating ECMS configuration.

    Cycles through calibration mixtures and records the resulting MS signal levels.

    Args:
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        liquid_fill_time: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        liquid_backward_time: Parameter passed through to the sub-experiments.
        CO2equilibrium_duration: Parameter passed through to the sub-experiments.
        flowrate_sccm: Parameter passed through to the sub-experiments.
        flow_ramp_sccm: Parameter passed through to the sub-experiments.
        MS_baseline_duration_1: Parameter passed through to the sub-experiments.
        CO2flowrate_sccm: Parameter passed through to the sub-experiments.
        Califlowrate_sccm: Parameter passed through to the sub-experiments.
        MSsignal_quilibrium_time_initial: Parameter passed through to the sub-experiments.
        MSsignal_quilibrium_time: Parameter passed through to the sub-experiments.
        liquid_drain_time: Parameter passed through to the sub-experiments.
        tube_clear_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    epm.add(
        "ECMS_sub_electrolyte_fill_recirculationreservoir",
        {
            "liquid_fill_time": liquid_fill_time,
        },
    )

    epm.add(
        "ECMS_sub_electrolyte_fill_cell_recirculation",
        {
            "liquid_backward_time": liquid_backward_time,
            "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
            "volume_ul_cell_liquid": volume_ul_cell_liquid,
        },
    )
    # achiving faster equilibrium time with faster CO2 flow rate
    epm.add(
        "ECMS_sub_headspace_purge_and_CO2baseline",
        {
            "CO2equilibrium_duration": CO2equilibrium_duration,
            "flowrate_sccm": flowrate_sccm,
            "flow_ramp_sccm": flow_ramp_sccm,
            "MS_baseline_duration": 30.0,
        },
    )

    epm.add("ECMS_sub_electrolyte_recirculation_on", {})
    epm.add(
        "ECMS_sub_headspace_purge_and_CO2baseline",
        {
            "CO2equilibrium_duration": 1.0,
            "flowrate_sccm": flowrate_sccm,
            "flow_ramp_sccm": flow_ramp_sccm,
            "MS_baseline_duration": MS_baseline_duration_1,
        },
    )
    for run, (co2gas, caligas) in enumerate(zip(CO2flowrate_sccm, Califlowrate_sccm)):
        if run == 0:
            epm.add(
                "ECMS_sub_cali",
                {
                    "CO2flowrate_sccm": co2gas,
                    "Califlowrate_sccm": caligas,
                    "MSsignal_quilibrium_time": MSsignal_quilibrium_time_initial,
                },
            )
        else:
            epm.add(
                "ECMS_sub_cali",
                {
                    "CO2flowrate_sccm": co2gas,
                    "Califlowrate_sccm": caligas,
                    "MSsignal_quilibrium_time": MSsignal_quilibrium_time,
                },
            )

    epm.add("ECMS_sub_electrolyte_recirculation_off", {})
    epm.add("ECMS_sub_normal_state", {})
    epm.add(
        "ECMS_sub_drain_recirculation",
        {"tube_clear_time": tube_clear_time, "liquid_drain_time": liquid_drain_time},
    )

    return epm.planned_experiments


# =============================================================================
# def ECMS_MS_calibration_recirculation(
#     sequence_version: int = 1,
#     reservoir_liquid_sample_no: int = 2,
#     volume_ul_cell_liquid: float = 600,
#     #liquid_forward_time: float = 20,
#     liquid_backward_time: float = 80,
#     CO2equilibrium_duration: float = 30,
#     flowrate_sccm: float = 20.0,
#     flow_ramp_sccm: float = 0,
#     MS_baseline_duration_1: float = 120,
#     CO2flowrate_sccm: List[float] = [19, 18, 17, 16, 15],
#     Califlowrate_sccm: List[float] = [1, 2, 3, 4, 5],
#     MSsignal_quilibrium_time_initial: float = 480,
#     MSsignal_quilibrium_time: float = 300,
#     liquid_drain_time: float = 60.0,
#
# ):
#
#
#     epm = ExperimentPlanMaker()
#
#
#     epm.add(
#         "ECMS_sub_electrolyte_fill_cell",
#         {
#             #"liquid_forward_time": liquid_forward_time,
#             "liquid_backward_time": liquid_backward_time,
#             "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
#             "volume_ul_cell_liquid": volume_ul_cell_liquid,
#         },
#     )
# #achiving faster equilibrium time with faster CO2 flow rate
#     epm.add(
#         "ECMS_sub_headspace_purge_and_CO2baseline",
#         {
#             "CO2equilibrium_duration": CO2equilibrium_duration,
#             "flowrate_sccm": flowrate_sccm,
#             "flow_ramp_sccm": flow_ramp_sccm,
#             "MS_baseline_duration": 30.0
#         },
#     )
#
#     epm.add("ECMS_sub_electrolyte_recirculation_on", {})
#     epm.add(
#         "ECMS_sub_headspace_purge_and_CO2baseline",
#         {
#             "CO2equilibrium_duration": 1.0,
#             "flowrate_sccm": flowrate_sccm,
#             "flow_ramp_sccm": flow_ramp_sccm,
#             "MS_baseline_duration": MS_baseline_duration_1
#         },
#     )
#     for run, (co2gas, caligas) in enumerate(zip(CO2flowrate_sccm, Califlowrate_sccm)):
#         if run==0:
#             epm.add(
#                 "ECMS_sub_cali",
#                 {
#                     "CO2flowrate_sccm": co2gas,
#                     "Califlowrate_sccm": caligas,
#                     "MSsignal_quilibrium_time": MSsignal_quilibrium_time_initial,
#                 },
#             )
#         else:
#             epm.add(
#                 "ECMS_sub_cali",
#                 {
#                     "CO2flowrate_sccm": co2gas,
#                     "Califlowrate_sccm": caligas,
#                     "MSsignal_quilibrium_time": MSsignal_quilibrium_time,
#                 },
#             )
#
#     epm.add("ECMS_sub_electrolyte_recirculation_off", {})
#     epm.add("ECMS_sub_normal_state",{})
#     epm.add("ECMS_sub_drain", {"liquid_drain_time": liquid_drain_time})
#
#     return epm.planned_experiments
# =============================================================================


@sequence(version=1)
def ECMS_MS_calibration(
    reservoir_liquid_sample_no: int = 2,
    volume_ul_cell_liquid: float = 600,
    # liquid_forward_time: float = 20,
    liquid_backward_time: float = 80,
    CO2equilibrium_duration: float = 30,
    flowrate_sccm: float = 20.0,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration_1: float = 120,
    CO2flowrate_sccm: List[float] = [19, 18, 17, 16, 15],
    Califlowrate_sccm: List[float] = [1, 2, 3, 4, 5],
    MSsignal_quilibrium_time_initial: float = 480,
    MSsignal_quilibrium_time: float = 300,
    liquid_drain_time: float = 60.0,
) -> list:
    """Calibrate the mass spec in the non-recirculating configuration.

    Single-pass variant of the MS calibration sequence.

    Args:
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        liquid_backward_time: Parameter passed through to the sub-experiments.
        CO2equilibrium_duration: Parameter passed through to the sub-experiments.
        flowrate_sccm: Parameter passed through to the sub-experiments.
        flow_ramp_sccm: Parameter passed through to the sub-experiments.
        MS_baseline_duration_1: Parameter passed through to the sub-experiments.
        CO2flowrate_sccm: Parameter passed through to the sub-experiments.
        Califlowrate_sccm: Parameter passed through to the sub-experiments.
        MSsignal_quilibrium_time_initial: Parameter passed through to the sub-experiments.
        MSsignal_quilibrium_time: Parameter passed through to the sub-experiments.
        liquid_drain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    epm.add(
        "ECMS_sub_electrolyte_fill_cell",
        {
            # "liquid_forward_time": liquid_forward_time,
            "liquid_backward_time": liquid_backward_time,
            "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
            "volume_ul_cell_liquid": volume_ul_cell_liquid,
        },
    )
    # achiving faster equilibrium time with faster CO2 flow rate
    epm.add(
        "ECMS_sub_headspace_purge_and_CO2baseline",
        {
            "CO2equilibrium_duration": CO2equilibrium_duration,
            "flowrate_sccm": flowrate_sccm,
            "flow_ramp_sccm": flow_ramp_sccm,
            "MS_baseline_duration": MS_baseline_duration_1,
        },
    )
    for run, (co2gas, caligas) in enumerate(zip(CO2flowrate_sccm, Califlowrate_sccm)):
        if run == 0:
            epm.add(
                "ECMS_sub_cali",
                {
                    "CO2flowrate_sccm": co2gas,
                    "Califlowrate_sccm": caligas,
                    "MSsignal_quilibrium_time": MSsignal_quilibrium_time_initial,
                },
            )
        else:
            epm.add(
                "ECMS_sub_cali",
                {
                    "CO2flowrate_sccm": co2gas,
                    "Califlowrate_sccm": caligas,
                    "MSsignal_quilibrium_time": MSsignal_quilibrium_time,
                },
            )
    epm.add("ECMS_sub_normal_state", {})
    epm.add("ECMS_sub_drain", {"liquid_drain_time": liquid_drain_time})

    return epm.planned_experiments


@sequence(version=1)
def ECMS_MS_pulsecalibration(
    reservoir_liquid_sample_no: int = 2,
    volume_ul_cell_liquid: float = 600,
    # liquid_forward_time: float = 20,
    liquid_backward_time: float = 80,
    CO2equilibrium_duration: float = 30,
    flowrate_sccm: float = 19.0,
    Califlowrate_sccm: float = 1,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration_1: float = 60,
    # Califlowrate_sccm: List[float] = [1, 2, 3, 4, 5],
    # MSsignal_quilibrium_time_initial: float = 480,
    MSsignal_quilibrium_time: float = 10,
    calibration_cycles: int = 15,
    # liquid_drain_time: float = 60.0,
) -> list:
    """Pulsed MS calibration alternating gas mixtures.

    Calibrates the MS by toggling between calibration gases.

    Args:
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        liquid_backward_time: Parameter passed through to the sub-experiments.
        CO2equilibrium_duration: Parameter passed through to the sub-experiments.
        flowrate_sccm: Parameter passed through to the sub-experiments.
        Califlowrate_sccm: Parameter passed through to the sub-experiments.
        flow_ramp_sccm: Parameter passed through to the sub-experiments.
        MS_baseline_duration_1: Parameter passed through to the sub-experiments.
        MSsignal_quilibrium_time: Parameter passed through to the sub-experiments.
        calibration_cycles: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # =============================================================================
    #     epm.add(
    #         "ECMS_sub_electrolyte_fill_cell",
    #         {
    #             #"liquid_forward_time": liquid_forward_time,
    #             "liquid_backward_time": liquid_backward_time,
    #             "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
    #             "volume_ul_cell_liquid": volume_ul_cell_liquid,
    #         },
    #     )
    # =============================================================================
    # achiving faster equilibrium time with faster CO2 flow rate
    epm.add(
        "ECMS_sub_headspace_purge_and_CO2baseline",
        {
            "CO2equilibrium_duration": CO2equilibrium_duration,
            "flowrate_sccm": flowrate_sccm,
            "flow_ramp_sccm": flow_ramp_sccm,
            "MS_baseline_duration": MS_baseline_duration_1,
        },
    )
    for run in range(calibration_cycles):
        epm.add(
            "ECMS_sub_pulsecali",
            {
                "Califlowrate_sccm": Califlowrate_sccm,
                "MSsignal_quilibrium_time": MSsignal_quilibrium_time,
            },
        )
        epm.add(
            "ECMS_sub_pulsecali",
            {
                "Califlowrate_sccm": 0.0,
                "MSsignal_quilibrium_time": MSsignal_quilibrium_time,
            },
        )
    return epm.planned_experiments


@sequence(version=1)
def ECMS_series_CA_change_gasflow(
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    # =============================================================================
    #     reservoir_liquid_sample_no: int = 2,
    #     volume_ul_cell_liquid: float = 600,
    #     #liquid_forward_time: float = 0,
    #     liquid_backward_time: float = 80,
    # =============================================================================
    # vacuum_time: float = 10,
    CO2equilibrium_duration: float = 10,
    flowrate_sccm: float = 10.0,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration_1: float = 30,
    # MS_baseline_duration_2: float = 90,
    WE_potential__V: List[float] = [-0.5, -1.0],
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 7.8,
    CA_duration_sec: List[float] = [60, 60],
    SampleRate: float = 1,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    postCA_MS_equilibrium_time: float = 10.0,
    CA_flow_change_duration_sec: List[float] = [60.0, 60.0, 60.0],
    CA_CO2_flow_rate_sccm: List[float] = [0.0, 10.0, 0.0],
    # =============================================================================
    #     cleaning_times: int =1,
    #     liquid_fill_time: float = 7,
    #     liquid_drain_time: float = 60.0,
    #     tube_clear_time: float = 20,
    #     tube_clear_delaytime: float = 40.0,
    # =============================================================================
    # liquid_cleancell_time: float = 120,
    PreExp_CO2flowrate_sccm: List[float] = [0.0, 10.0],
    PreExp_Califlowrate2_sccm: List[float] = [10.0, 0.0],
    # MSsignal_quilibrium_time_initial: float = 480,
    PreExp_MSsignal_quilibrium_time: float = 100,
) -> list:
    """Run a CA series while stepping through CO2 flow rates.

    Allows the operator to study the flow-rate dependence of the products with one sequence.

    Args:
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        CO2equilibrium_duration: Parameter passed through to the sub-experiments.
        flowrate_sccm: Parameter passed through to the sub-experiments.
        flow_ramp_sccm: Parameter passed through to the sub-experiments.
        MS_baseline_duration_1: Parameter passed through to the sub-experiments.
        WE_potential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        CA_duration_sec: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        postCA_MS_equilibrium_time: Parameter passed through to the sub-experiments.
        CA_flow_change_duration_sec: Parameter passed through to the sub-experiments.
        CA_CO2_flow_rate_sccm: Parameter passed through to the sub-experiments.
        PreExp_CO2flowrate_sccm: Parameter passed through to the sub-experiments.
        PreExp_Califlowrate2_sccm: Parameter passed through to the sub-experiments.
        PreExp_MSsignal_quilibrium_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ECMS_sub_unload_cell", {})
    epm.add(
        "ECMS_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )
    # epm.add("ECMS_sub_prevacuum_cell",{"vacuum_time": vacuum_time})
    epm.add(
        "ECMS_sub_headspace_purge_and_CO2baseline",
        {
            "CO2equilibrium_duration": CO2equilibrium_duration,
            "flowrate_sccm": flowrate_sccm,
            "flow_ramp_sccm": flow_ramp_sccm,
            "MS_baseline_duration": MS_baseline_duration_1,
        },
    )
    for run, (co2gas, caligas2) in enumerate(
        zip(PreExp_CO2flowrate_sccm, PreExp_Califlowrate2_sccm)
    ):
        epm.add(
            "ECMS_sub_inertgascali",
            {
                "CO2flowrate_sccm": co2gas,
                "Califlowrate_two_sccm": caligas2,
                "MSsignal_quilibrium_time": PreExp_MSsignal_quilibrium_time,
            },
        )

    for cycle, (potential, time) in enumerate(zip(WE_potential__V, CA_duration_sec)):
        # =============================================================================
        #         epm.add(
        #             "ECMS_sub_electrolyte_fill_recirculationreservoir",
        #             {
        #                 "liquid_fill_time": liquid_fill_time,
        #             },
        #         )
        #
        #
        #         epm.add(
        #             "ECMS_sub_electrolyte_fill_cell_recirculation",
        #             {
        #                 "liquid_backward_time": liquid_backward_time,
        #                 "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
        #                 "volume_ul_cell_liquid": volume_ul_cell_liquid,
        #             },
        #         )
        # =============================================================================
        # achiving faster equilibrium time with faster CO2 flow rate

        # =============================================================================
        #         epm.add("ECMS_sub_electrolyte_recirculation_on", {})
        #
        #         epm.add(
        #             "ECMS_sub_headspace_purge_and_CO2baseline",
        #             {
        #                 "CO2equilibrium_duration": 1.0,
        #                 "flowrate_sccm": flowrate_sccm,
        #                 "flow_ramp_sccm": flow_ramp_sccm,
        #                 "MS_baseline_duration": MS_baseline_duration_2
        #             },
        #         )
        # =============================================================================

        epm.add(
            "ECMS_sub_CA_CO2flow",
            {
                "WE_potential__V": potential,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": time,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "MS_equilibrium_time": postCA_MS_equilibrium_time,
                "total_MFC_flow_rate_sccm": flowrate_sccm,
                "flow_change_duration_sec": CA_flow_change_duration_sec,
                "CO2_flow_rate_sccm": CA_CO2_flow_rate_sccm,
            },
        )
        # epm.add("ECMS_sub_electrolyte_recirculation_off", {})

        epm.add(
            "ECMS_sub_inertgascali",
            {
                "CO2flowrate_sccm": flowrate_sccm,
                "Califlowrate_two_sccm": 0.0,
                "MSsignal_quilibrium_time": PreExp_MSsignal_quilibrium_time,
            },
        )

    epm.add("ECMS_sub_normal_state", {})
    # epm.add("ECMS_sub_drain_recirculation", {"tube_clear_time": tube_clear_time, "liquid_drain_time":liquid_drain_time})
    # epm.add("ECMS_sub_clean_cell_recirculation", {"volume_ul_cell_liquid": volume_ul_cell_liquid, "liquid_backward_time":liquid_backward_time, "reservoir_liquid_sample_no":reservoir_liquid_sample_no, "tube_clear_time":tube_clear_time, "liquid_drain_time":liquid_drain_time, "liquid_fill_time": liquid_fill_time + 1.0, "cleaning_times": cleaning_times, "tube_clear_delaytime": tube_clear_delaytime})

    return epm.planned_experiments
