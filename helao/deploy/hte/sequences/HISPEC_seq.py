SEQUENCES = [
    # "ECHEUVIS_CA_led",
    # "ECHEUVIS_CP_led",
    # "ECHEUVIS_CV_led",
    "ECHEUVIS_postseq",
    "HISPEC_CV",
    "HISPEC_EIS_only",
]

from helao.core.models.electrolyte import Electrolyte
from helao.helpers.lib_decorators import sequence
from helao.helpers.premodels import ExperimentPlanMaker


@sequence(version=3)
def HISPEC_CV(
    plate_id: int = 1,  # @Dan - what is this? -- plate_id is the ID of the material library in our database. it's first assigned to a substrate after which we can use this ID to track the library's deposition, annealing, and experiment history
    plate_sample_no_list: list = [
        2
    ],  # @Dan - what is this? -- the sample_no is uniquely assigned to an x,y location on a material library according to its plate map which was defined at the synthesis step
    cycles: int = 1,
    Ival__A: float = 0.0015 * 0.045,
    scanrate_voltsec: float = 0.01,
    cell_fill_wait: float = 60.0,
    Tval__s: float = 60,
    CP_Tval__s: float = 60,
    reservoir_electrolyte: Electrolyte = Electrolyte.hispeca,  # @Ben -- this is an enum for a common abbreviation we give to our electrolytes used in our screening protocols, they typically have an integer pH at the end, see helao.core.models.electrolyte and add one there if needed
    reservoir_liquid_sample_no: int = 1,  # @Dan -- what is this? -- this is the liquid sample number in the liquid sample database, you will need to 'create' a liquid sample for the electrolyte you're using, so that the cell is filled with a liquid sample that inherits the reservoir attributes
    solution_bubble_gas: str = "None",
    solution_ph: float = 0,
    Flow_during_SpEC: bool = False,
    samplerate_sec: float = 0.1,
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
    IRange: str = "m1",
    ERange: str = "v2_5",
    Bandwidth: str = "BW5",
    ref_vs_nhe: float = 0,
    toggle1_source: str = "spec_trig",
    toggle1_init_delay: float = 0.0,
    toggle1_duty: float = 0.01,
    Vamp__V: float = 0.01,  # Amplitude value in volts
    Finit__Hz: float = 40000,  # Initial frequency in Hz.
    Ffinal__Hz: float = 1000,  # Final frequency in Hz.
    FrequencyNumber: int = 60,
    Duration__s: float = 0,  # Duration in seconds.
    AcqInterval__s: float = 0.1,
    AcqInterval_CA_CP__s: float = 0.5,  # Time between data acq in seconds.
    SweepMode: str = "log",
    Repeats: int = 10,
    DelayFraction: float = 0.1,
    comment: str = "",
    measurement_area: float = 0.045,  # 2.4 mm diameter droplet
    liquid_volume_ml: float = 1.0,
    use_z_motor: bool = True,  # @Ben -- I think this should default to True
    cell_engaged_z: float = 3.5,  # # units of mm.
    cell_disengaged_z: float = 0,
    cell_vent_wait: float = 10.0,
    #######
    # Vinit_vsRHE: float = 0.0,  # Initial value in volts or amps.
    # Vapex1_vsRHE: float = 1.0,  # Apex 1 value in volts or amps.
    # Vapex2_vsRHE: float = -1.0,  # Apex 2 value in volts or amps. # temporarily uncommented to test a fixed V2
    # Vfinal_vsRHE: float = 0.0,  # Final value in volts or amps.
    # scanrate_voltsec: Optional[float] = 0.02,  # scan rate in volts/second or amps/second.
) -> list:
    """Build a HISPEC cyclic voltammetry / SpEC sequence over plate samples.

    For each sample in ``plate_sample_no_list`` the sequence unloads/disengages
    the cell, moves to the sample, optionally engages the cell with the
    z-motor, optionally stops electrolyte flow during the spectro-electrochemical
    (SpEC) measurement, then runs the sub-experiment stack: OCV, PEIS,
    CP, CA, and a SpEC scan. Global experiment parameters are threaded
    between sub-experiments to seed initial/apex potentials for the
    PEIS/CA/SpEC steps. The cell is finally left sealed and full of
    solution if the z-motor is in use, then a shutdown experiment runs.

    Args:
        plate_id: Material library plate identifier.
        plate_sample_no_list: Sample numbers on the plate to visit.
        cycles: Number of CV cycles in the SpEC scan.
        Ival__A: Current setpoint for the CP step, in amps.
        scanrate_voltsec: SpEC scan rate in V/s.
        cell_fill_wait: Seconds to wait after engaging the cell with flow.
        Tval__s: Duration in seconds for the OCV and CA steps.
        CP_Tval__s: Duration in seconds for the CP step.
        reservoir_electrolyte: Electrolyte enum identifying the reservoir.
        reservoir_liquid_sample_no: Liquid sample number to load into the cell.
        solution_bubble_gas: Gas used to bubble the reservoir solution.
        solution_ph: Solution pH passed to potential references.
        Flow_during_SpEC: If False, flow is stopped before the SpEC stack.
        samplerate_sec: SpEC data acquisition interval in seconds.
        gamrychannelwait: Gamry channel wait flag.
        gamrychannelsend: Gamry channel send flag.
        IRange: Gamry current range string.
        ERange: Gamry voltage range string.
        Bandwidth: Gamry bandwidth selection string.
        ref_vs_nhe: Reference electrode offset vs NHE in volts.
        toggle1_source: Toggle1 source name driving the spectrometer trigger.
        toggle1_init_delay: Initial delay for the toggle1 trigger, seconds.
        toggle1_duty: Duty cycle for the toggle1 trigger.
        Vamp__V: PEIS perturbation amplitude in volts.
        Finit__Hz: PEIS initial frequency in Hz.
        Ffinal__Hz: PEIS final frequency in Hz.
        FrequencyNumber: Number of PEIS frequencies in the sweep.
        Duration__s: PEIS total duration in seconds.
        AcqInterval__s: PEIS data acquisition interval, seconds.
        AcqInterval_CA_CP__s: CA/CP data acquisition interval, seconds.
        SweepMode: PEIS sweep mode (e.g. ``"log"``).
        Repeats: PEIS repeats per frequency.
        DelayFraction: PEIS settling delay fraction.
        comment: Free-form sequence comment.
        measurement_area: Geometric cell area in cm^2.
        liquid_volume_ml: Volume of liquid loaded into the cell.
        use_z_motor: Use the z-motor to engage/disengage the cell.
        cell_engaged_z: Cell engaged z-height in mm.
        cell_disengaged_z: Cell disengaged z-height in mm.
        cell_vent_wait: Wait time after venting the cell, in seconds.

    Returns:
        list: Ordered list of planned ``Experiment`` objects.
    """
    epm = ExperimentPlanMaker()
    epm.add("HISPEC_sub_unloadall_customs", {})
    epm.add(
        "HISPEC_sub_disengage",
        {
            "clear_we": True,
            "clear_ce": False,
            "z_height": cell_disengaged_z,
            "vent_wait": cell_vent_wait,
        },
    )

    for i, plate_sample in enumerate(plate_sample_no_list):
        if i > 0 and use_z_motor:
            epm.add(
                "HISPEC_sub_disengage",
                {
                    "clear_we": True,
                    "clear_ce": False,
                    "z_height": cell_disengaged_z,
                    "vent_wait": cell_vent_wait,
                },
            )

        epm.add(
            "HISPEC_sub_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "solution_bubble_gas": solution_bubble_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )

        if use_z_motor:
            epm.add(
                "HISPEC_sub_engage",
                {
                    "flow_we": True,
                    "flow_ce": True,
                    "z_height": cell_engaged_z,
                    "fill_wait": cell_fill_wait,
                },
            )
        else:
            if i == 0:  # initial sample
                epm.add(
                    "ECHEUVIS_sub_interrupt",
                    {"reason": "Restore flow and prepare for sample measurement."},
                )

        if not Flow_during_SpEC:
            epm.add("HISPEC_sub_stop_flow", {})

        epm.add(
            "HISPEC_sub_OCV",
            {
                "Tval__s": Tval__s,
                "SampleRate": 0.5,
            },
        )

        epm.add(
            "HISPEC_sub_PEIS",
            {
                # "Vinit_vsRHE": Vinit_vsRHE,
                "Vamp__V": Vamp__V,
                "Finit__Hz": Finit__Hz,
                "Ffinal__Hz": Ffinal__Hz,
                "FrequencyNumber": FrequencyNumber,
                "Duration__s": Duration__s,
                "AcqInterval__s": AcqInterval__s,
                "SweepMode": SweepMode,
                "Repeats": Repeats,
                "DelayFraction": DelayFraction,
                "TTLwait": -1,  # EIS step keeps TTL off
                "TTLsend": -1,
                "IRange": IRange,
                "ERange": ERange,
                "Bandwidth": Bandwidth,
                "solution_ph": solution_ph,
                "ref_vs_nhe": ref_vs_nhe,
            },
            from_global_exp_params={"min_offset_ocv": "Vinit__V"},
        )

        epm.add(
            "HISPEC_sub_CP",
            {
                "Ival__A": Ival__A,
                "Tval__s": CP_Tval__s,
                "AcqInterval__s": AcqInterval_CA_CP__s,
            },
        )

        epm.add(
            "HISPEC_sub_CA",
            {
                # "Ival__A" : Ival__A,
                "Tval__s": Tval__s,
                "AcqInterval__s": AcqInterval_CA_CP__s,
            },
            from_global_exp_params={"min_offset_ocv": "Vval__V"},
        )

        epm.add(
            "HISPEC_sub_SpEC",
            {
                # "Vinit_vsRHE": Vinit_vsRHE,
                # "Vapex1_vsRHE": Vapex1_vsRHE,
                # "Vapex2_vsRHE": Vapex2_vsRHE,
                # "Vfinal_vsRHE": Vfinal_vsRHE,
                "scanrate_voltsec": scanrate_voltsec,
                "samplerate_sec": samplerate_sec,
                "cycles": cycles,
                "gamrychannelwait": gamrychannelwait,
                "gamrychannelsend": gamrychannelsend,
                "IRange": IRange,
                "ERange": ERange,
                "Bandwidth": Bandwidth,
                "solution_ph": solution_ph,
                "ref_vs_nhe": ref_vs_nhe,
                "toggle1_source": toggle1_source,
                "toggle1_init_delay": toggle1_init_delay,
                "toggle1_duty": toggle1_duty,
                # "OCV_vsRef": Vapex2_vsRHE,
                # })
            },
            from_global_exp_params={
                "min_offset_ocv": "Vapex2_vsRHE",
                "CP_Ewe_V__mean_final_limited": "Vapex1_vsRHE",
            },
        )  # temporarily commented this out to test a fixed V2

    if use_z_motor:
        # unload, then leave cell sealed w/solution for storage
        epm.add(
            "ECHEUVIS_sub_engage",
            {
                "unload_first": True,
                "flow_we": False,
                "flow_ce": False,
                "z_height": cell_engaged_z,
                "fill_wait": cell_fill_wait,
            },
        )
    else:
        epm.add("ECHE_sub_unloadall_customs", {})
    # epm.add(
    #     "UVIS_calc_abs",
    #     {
    #         "ev_parts": calc_ev_parts,
    #         "bin_width": calc_bin_width,
    #         "window_length": calc_window_length,
    #         "poly_order": calc_poly_order,
    #         "lower_wl": calc_lower_wl,
    #         "upper_wl": calc_upper_wl,
    #         "skip_nspec": calc_skip_nspec,
    #     },
    # )
    epm.add("HISPEC_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=3)
def HISPEC_EIS_only(
    plate_id: int = 1,  # @Dan - what is this? -- plate_id is the ID of the material library in our database. it's first assigned to a substrate after which we can use this ID to track the library's deposition, annealing, and experiment history
    plate_sample_no_list: list = [
        2
    ],  # @Dan - what is this? -- the sample_no is uniquely assigned to an x,y location on a material library according to its plate map which was defined at the synthesis step
    reservoir_electrolyte: Electrolyte = Electrolyte.hispeca,  # @Ben -- this is an enum for a common abbreviation we give to our electrolytes used in our screening protocols, they typically have an integer pH at the end, see helao.core.models.electrolyte and add one there if needed
    reservoir_liquid_sample_no: int = 1,  # @Dan -- what is this? -- this is the liquid sample number in the liquid sample database, you will need to 'create' a liquid sample for the electrolyte you're using, so that the cell is filled with a liquid sample that inherits the reservoir attributes
    solution_bubble_gas: str = "None",
    solution_ph: float = 0,
    # Vinit__V: float = 0.0,  # Initial value in volts or amps.
    Vamp__V: float = 0.01,  # Amplitude value in volts
    Finit__Hz: float = 200000,  # Initial frequency in Hz.
    Ffinal__Hz: float = 1000,  # Final frequency in Hz.
    FrequencyNumber: int = 60,
    Duration__s: float = 0,  # Duration in seconds.
    AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
    SweepMode: str = "log",
    Repeats: int = 10,
    DelayFraction: float = 0.1,
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
    IRange: str = "m10",
    ERange: str = "v10",
    Bandwidth: str = "BW4",
    ref_vs_nhe: float = 0,
    comment: str = "",
    measurement_area: float = 0.071,  # 3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    use_z_motor: bool = True,  # @Ben -- I think this should default to True
    cell_engaged_z: float = 3.5,  # units of mm.
    cell_disengaged_z: float = 0,
    cell_vent_wait: float = 10.0,
    cell_fill_wait: float = 60,
) -> list:
    """Build a HISPEC sequence that runs only a PEIS impedance scan per sample.

    A startup experiment is added once, then for each sample the cell is
    disengaged (or paused with an interrupt if the z-motor is disabled),
    the sample is loaded, the cell is re-engaged, an OCV is captured to
    seed the PEIS initial voltage, and a PEIS scan is run. The cell is
    finally sealed with electrolyte for storage when the z-motor is used.

    Args:
        plate_id: Material library plate identifier.
        plate_sample_no_list: Sample numbers on the plate to visit.
        reservoir_electrolyte: Electrolyte enum for the reservoir.
        reservoir_liquid_sample_no: Liquid sample number to load.
        solution_bubble_gas: Gas used to bubble the reservoir solution.
        solution_ph: Solution pH passed to potential references.
        Vamp__V: PEIS perturbation amplitude in volts.
        Finit__Hz: PEIS initial frequency in Hz.
        Ffinal__Hz: PEIS final frequency in Hz.
        FrequencyNumber: Number of PEIS frequencies in the sweep.
        Duration__s: PEIS total duration in seconds.
        AcqInterval__s: PEIS data acquisition interval, seconds.
        SweepMode: PEIS sweep mode (e.g. ``"log"``).
        Repeats: PEIS repeats per frequency.
        DelayFraction: PEIS settling delay fraction.
        gamrychannelwait: Unused: the PEIS step runs with TTL off.
        gamrychannelsend: Unused: the PEIS step runs with TTL off.
        IRange: Gamry current range string.
        ERange: Gamry voltage range string.
        Bandwidth: Gamry bandwidth selection string.
        ref_vs_nhe: Reference electrode offset vs NHE in volts.
        comment: Free-form sequence comment.
        measurement_area: Geometric cell area in cm^2.
        liquid_volume_ml: Volume of liquid loaded into the cell.
        use_z_motor: Use the z-motor to engage/disengage the cell.
        cell_engaged_z: Cell engaged z-height in mm.
        cell_disengaged_z: Cell disengaged z-height in mm.
        cell_vent_wait: Wait time after venting the cell, in seconds.
        cell_fill_wait: Wait time after filling the cell, in seconds.

    Returns:
        list: Ordered list of planned ``Experiment`` objects.
    """
    epm = ExperimentPlanMaker()

    epm.add(
        "HISPEC_sub_startup", {}
    )  # @Ben -- if you use this experiment, you'll need to update the hispec.yml config to include ECHEUVIS_exp under experiment_libraries

    if use_z_motor:
        epm.add(
            "ECHEUVIS_sub_disengage",
            {
                "clear_we": True,
                "clear_ce": False,
                "z_height": cell_disengaged_z,
                "vent_wait": cell_vent_wait,
            },
        )
    else:
        epm.add(
            "ECHEUVIS_sub_interrupt",
            {"reason": "Stop flow and prepare for xy motion to starting sample."},
        )

    for i, plate_sample in enumerate(plate_sample_no_list):
        if i > 0 and use_z_motor:
            epm.add(
                "ECHEUVIS_sub_disengage",
                {
                    "clear_we": True,
                    "clear_ce": False,
                    "z_height": cell_disengaged_z,
                    "vent_wait": cell_vent_wait,
                },
            )

        epm.add(
            "ECHE_sub_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "solution_bubble_gas": solution_bubble_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )

        if use_z_motor:
            epm.add(
                "ECHEUVIS_sub_engage",
                {
                    "flow_we": True,
                    "flow_ce": True,
                    "z_height": cell_engaged_z,
                    "fill_wait": cell_fill_wait,
                    "calibrate_intensity": False,  # @Dan - kept this action but turned this flag to false to prevent it trying to access doric WLED - not sure if this will work... -- it should work because the references to doric_wled aren't going to be used
                    "max_integration_time": int(10),
                },
            )
        else:
            if i == 0:  # initial sample
                epm.add(
                    "ECHEUVIS_sub_interrupt",
                    {"reason": "Restore flow and prepare for sample measurement."},
                )

        epm.add(
            "ECHE_sub_OCV",
            {
                "Tval__s": 0.1,
                "SampleRate": 0.01,
            },
        )

        epm.add(
            "HISPEC_sub_PEIS",
            {
                # "Vinit_vsRHE": Vinit_vsRHE,
                # "Vapex1_vsRHE": Vapex1_vsRHE,
                "Vamp__V": Vamp__V,
                "Finit__Hz": Finit__Hz,
                "Ffinal__Hz": Ffinal__Hz,
                "FrequencyNumber": FrequencyNumber,
                "Duration__s": Duration__s,
                "AcqInterval__s": AcqInterval__s,
                "SweepMode": SweepMode,
                "Repeats": Repeats,
                "DelayFraction": DelayFraction,
                "TTLwait": -1,  # EIS step keeps TTL off
                "TTLsend": -1,
                "IRange": IRange,
                "ERange": ERange,
                "Bandwidth": Bandwidth,
                "solution_ph": solution_ph,
                "ref_vs_nhe": ref_vs_nhe,
            },
            from_global_exp_params={"Ewe_V__mean_final": "Vinit__V"},
        )

    if use_z_motor:
        # unload, then leave cell sealed w/solution for storage
        epm.add(
            "ECHEUVIS_sub_engage",
            {
                "unload_first": True,
                "flow_we": False,
                "flow_ce": False,
                "z_height": cell_engaged_z,
                "fill_wait": cell_fill_wait,
            },
        )
    else:
        epm.add("ECHE_sub_unloadall_customs", {})

    epm.add("HISPEC_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=1)
def ECHEUVIS_postseq(
    analysis_seq_uuid: str = "",
    plate_id: int = 0,
    recent: bool = False,
) -> list:
    """Build a post-sequence that runs the ECHEUVIS stability analysis.

    Args:
        analysis_seq_uuid: UUID of the source sequence to analyze.
        plate_id: Plate identifier scoping the analysis.
        recent: Restrict to the most recent matching run when True.

    Returns:
        list: Ordered list of planned ``Experiment`` objects.
    """
    epm = ExperimentPlanMaker()
    epm.add(
        "ECHEUVIS_analysis_stability",
        {
            "sequence_uuid": analysis_seq_uuid,
            "plate_id": plate_id,
            "recent": recent,
        },
    )

    return epm.planned_experiments  # returns complete experiment list
