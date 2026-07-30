"""Sequence library for ADSS (Automated Droplet Screening Station).

Each public ``ADSS_*`` function builds and returns an experiment list via
``ExperimentPlanMaker``. Sequences typically chain cell load, electrolyte
fill, recirculation, electrochemical actions (OCV/CA/CV/CP), aliquot
sampling, drain, and cell-cleaning sub-experiments defined in the matching
ADSS experiment library.
"""

__all__ = [
    "ADSS_CA_cell_1potential",
    "ADSS_PA_CVs_CAs_cell",
    "ADSS_PA_CVs_CAs_CVs_autogasswitching",
    "ADSS_PA_CVs_CAs_CVs_cell_simple",
    "ADSS_PA_CVs_testing",
    "ADSS_PA_CV_TRI",
    "ADSS_PA_CV_TRI_new",
    "ADSS_PA_CV_single",
]

from helao.helpers.lib_decorators import sequence
from helao.helpers.premodels import ExperimentPlanMaker

SEQUENCES = __all__


@sequence(version=8)
def ADSS_CA_cell_1potential(
    # solid_custom_position: str = "cell1_we",
    plate_id: int = 5917,
    plate_sample_no: int = 14050,  #  instead of map select
    same_sample: bool = False,
    stay_sample: bool = False,
    # liquid_custom_position: str = "elec_res1",
    liquid_sample_no: int = 220,
    liquid_sample_volume_ul: float = 4000,
    CA_potential_vs: float = -0.2,
    potential_versus: str = "oer",
    ph: float = 9.53,
    ref_type: str = "leakless",
    ref_offset__V: float = 0.0,
    CA_duration_sec: float = 1320,
    aliquot_tf: bool = True,
    aliquot_times_sec: list[float] = [60, 600, 1140],
    aliquot_volume_ul: int = 200,
    insert_electrolyte_bool: bool = False,
    insert_electrolyte_ul: int = 0,
    insert_electrolyte_time_sec: float = 1800,
    keep_electrolyte: bool = False,
    use_electrolyte: bool = False,
    OCV_duration: float = 60,
    OCValiquot_times_sec: list[float] = [20],
    samplerate_sec: float = 1,
    led_illumination: bool = False,
    led_dutycycle: float = 1,
    led_wavelength: str = "385",
    Syringe_rate_ulsec: float = 300,
    Cell_draintime_s: float = 60,
    ReturnLineWait_s: float = 30,
    ReturnLineReverseWait_s: float = 3,
    ResidualWait_s: float = 15,
    flush_volume_ul: float = 2000,
    clean: bool = False,
    clean_volume_ul: float = 5000,
    refill: bool = False,
    refill_volume_ul: float = 6000,
    water_refill_volume_ul: float = 6000,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "LS4_newsyringe040923",
) -> list:
    """Single-potential CA run with OCV bookends and optional LED illumination.

    Loads a single sample, fills and recirculates the cell, runs an OCV
    measurement, a CA at ``CA_potential_vs``, another OCV, then drains,
    optionally flushes/cleans the cell and refills syringes. When
    ``led_illumination`` is true the OCV/CA steps use the ``*_photo`` variants.

    Args:
        plate_id: Plate id of the solid sample.
        plate_sample_no: Sample number on the plate.
        same_sample: If True, skip the move-to-sample step.
        stay_sample: If True, perform a flush+drain after the experiment.
        liquid_sample_no: Reservoir liquid sample number.
        liquid_sample_volume_ul: Cell fill volume (uL).
        CA_potential_vs: CA potential in the selected frame.
        potential_versus: Frame label (``"oer"``/``"rhe"``).
        ph: Solution pH.
        ref_type: Reference electrode type label.
        ref_offset__V: Reference electrode offset (V).
        CA_duration_sec: CA hold duration (s).
        aliquot_tf: Master switch for in-situ aliquots.
        aliquot_times_sec: CA-relative aliquot timestamps (s).
        aliquot_volume_ul: Aliquot volume (uL).
        insert_electrolyte_bool: Inject extra electrolyte mid-CA.
        insert_electrolyte_ul: Inserted electrolyte volume (uL).
        insert_electrolyte_time_sec: Insertion time relative to CA start (s).
        keep_electrolyte: Retain electrolyte at end of sequence.
        use_electrolyte: Reuse previously loaded electrolyte.
        OCV_duration: OCV duration (s).
        OCValiquot_times_sec: OCV-relative aliquot timestamps (s).
        samplerate_sec: Sample interval (s).
        led_illumination: Use photo-CA/OCV variants when True.
        led_dutycycle: LED toggle duty cycle (0-1).
        led_wavelength: LED wavelength string.
        Syringe_rate_ulsec: Syringe rate (uL/s).
        Cell_draintime_s: Drain duration (s).
        ReturnLineWait_s: Forward return-line wait (s).
        ReturnLineReverseWait_s: Reverse return-line wait (s).
        ResidualWait_s: Residual wait (s) passthrough.
        flush_volume_ul: Flush volume (uL) when ``stay_sample`` is True.
        clean: Move to clean cell and run cleaning.
        clean_volume_ul: Cleaning volume (uL).
        refill: Refill syringes at end of sequence.
        refill_volume_ul: Working solution refill volume (uL).
        water_refill_volume_ul: Water syringe refill volume (uL).
        PAL_Injector: PAL injector key.
        PAL_Injector_id: PAL injector identifier.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # for solid_sample_no in plate_sample_no_list:  # have to indent add expts if used

    if not same_sample:

        epm.add(
            "ADSS_sub_move_to_sample",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample_no,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )
    epm.add(
        "ADSS_sub_load",
        {
            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no,
            "previous_liquid": use_electrolyte,
            "liquid_custom_position": "cell1_we",
            "liquid_sample_no": liquid_sample_no,
            "liquid_sample_volume_ul": liquid_sample_volume_ul,
        },
    )
    # if led_illumination:
    #     epm.add(
    #         "ADSS_sub_cell_illumination",
    #         {
    #             "led_wavelength": led_wavelength,
    #             "illumination_on": led_illumination,
    #         }

    #     )
    if not use_electrolyte:

        epm.add(
            "ADSS_sub_cellfill_prefilled",
            {
                "Solution_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            },
        )
    # redundant?
    # epm.add(
    #     "ADSS_sub_load_liquid",
    #     {
    #         "liquid_custom_position": liquid_custom_position,
    #         "liquid_sample_no": liquid_sample_no,
    #     }
    # )
    # epm.add(
    #     "ADSS_sub_load_solid",
    #     {
    #         "solid_custom_position": solid_custom_position,
    #         "solid_plate_id": plate_id,
    #         "solid_sample_no": plate_sample_no,
    #     }
    # )
    epm.add("ADSS_sub_recirculate", {})

    if led_illumination:

        epm.add(
            "ADSS_sub_OCV_photo",
            {
                "Tval__s": OCV_duration,
                "SampleRate": samplerate_sec,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "led_wavelength": led_wavelength,
                "toggle_illum_duty": led_dutycycle,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": OCValiquot_times_sec,
                "aliquot_insitu": aliquot_tf,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
                "rinse_1": 1,
            },
        )
        epm.add(
            "ADSS_sub_CA_photo",
            {
                "CA_potential": CA_potential_vs,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "potential_versus": potential_versus,
                "samplerate_sec": samplerate_sec,
                "CA_duration_sec": CA_duration_sec,
                "led_wavelength": led_wavelength,
                "toggle_illum_duty": led_dutycycle,
                "insert_electrolyte_bool": insert_electrolyte_bool,
                "insert_electrolyte_volume_ul": insert_electrolyte_ul,
                "insert_electrolyte_time_sec": insert_electrolyte_time_sec,
                "electrolyte_sample_no": liquid_sample_no,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": aliquot_times_sec,
                "aliquot_insitu": aliquot_tf,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
            },
        )
        epm.add(
            "ADSS_sub_OCV_photo",
            {
                "Tval__s": OCV_duration,
                "SampleRate": samplerate_sec,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "led_wavelength": led_wavelength,
                "toggle_illum_duty": led_dutycycle,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": OCValiquot_times_sec,
                "aliquot_insitu": aliquot_tf,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
                "rinse_1": 1,
                # "rinse_4": 1,
            },
        )
        epm.add(
            "ADSS_sub_cell_illumination",
            {
                "led_wavelength": led_wavelength,
                "illumination_on": False,
            },
        )
    else:

        epm.add(
            "ADSS_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": samplerate_sec,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": OCValiquot_times_sec,
                "aliquot_insitu": aliquot_tf,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
                "rinse_1": 1,
            },
        )
        epm.add(
            "ADSS_sub_CA",
            {
                "CA_potential": CA_potential_vs,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "potential_versus": potential_versus,
                "samplerate_sec": samplerate_sec,
                "CA_duration_sec": CA_duration_sec,
                "insert_electrolyte_bool": insert_electrolyte_bool,
                "insert_electrolyte_volume_ul": insert_electrolyte_ul,
                "insert_electrolyte_time_sec": insert_electrolyte_time_sec,
                "electrolyte_sample_no": liquid_sample_no,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": aliquot_times_sec,
                "aliquot_insitu": aliquot_tf,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
            },
        )
        epm.add(
            "ADSS_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": samplerate_sec,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": OCValiquot_times_sec,
                "aliquot_insitu": True,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
                "rinse_1": 1,
                # "rinse_4": 1,
            },
        )

    if keep_electrolyte:
        epm.add(
            "ADSS_sub_keep_electrolyte",
            {
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
            },
        )

    else:
        epm.add(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
                #    "ResidualWait_s": ResidualWait_s,
            },
        )
    if stay_sample:
        epm.add(
            "ADSS_sub_cellfill_flush",
            {
                "Solution_volume_ul": flush_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
                "ReturnLineWait_s": ReturnLineWait_s,
            },
        )
        epm.add(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
                #        "ResidualWait_s": ResidualWait_s,
            },
        )
    if keep_electrolyte:
        epm.add("ADSS_sub_unload_solid", {})

    else:

        epm.add("ADSS_sub_unloadall_customs", {})

    if clean:

        epm.add("ADSS_sub_move_to_clean_cell", {})

        epm.add(
            "ADSS_sub_clean_cell",
            {
                "Clean_volume_ul": clean_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
                "ReturnLineWait_s": ReturnLineWait_s,
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
                #    "ResidualWait_s": ResidualWait_s,
            },
        )
    if refill:
        epm.add(
            "ADSS_sub_refill_syringes",
            {
                "Waterclean_volume_ul": water_refill_volume_ul,
                "Solution_volume_ul": refill_volume_ul,
                "Syringe_rate_ulsec": 300,
            },
        )

    #    epm.add("ADSS_sub_tray_unload",{})

    # epm.add("ADSS_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=5)
def ADSS_PA_CVs_CAs_cell(
    # solid_custom_position: str = "cell1_we",
    plate_id: int = 5917,
    plate_sample_no: int = 14050,  #  instead of map select
    same_sample: bool = False,
    stay_sample: bool = False,
    # liquid_custom_position: str = "elec_res1",
    liquid_sample_no: int = 220,
    liquid_sample_volume_ul: float = 4000,
    recirculate_wait_time_m: float = 0.5,
    CV_cycles: list[int] = [5, 3, 3],
    Vinit_vsRHE: list[float] = [1.23, 1.23, 1.23],  # Initial value in volts or amps.
    Vapex1_vsRHE: list[float] = [1.23, 1.23, 1.23],  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: list[float] = [0.6, 0.4, 0],  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: list[float] = [0.6, 0.4, 0],  # Final value in volts or amps.
    scanrate_voltsec: list[float] = [
        0.02,
        0.02,
        0.02,
    ],  # scan rate in volts/second or amps/second.
    CV_samplerate_sec: float = 0.05,
    # number_of_preCAs: int = 3,
    number_of_postCAs: int = 2,
    CA_potentials_vs: list[float] = [0.6, 0.4],
    potential_versus: str = "rhe",
    CA_duration_sec: list[float] = [60, 60],
    CA_samplerate_sec: float = 0.1,
    gamry_i_range: str = "auto",
    ph: float = 9.53,
    ref_type: str = "leakless",
    ref_offset__V: float = 0.0,
    aliquot_postCV: list[int] = [1, 0, 0],
    aliquot_postCA: list[int] = [1, 0],
    aliquot_volume_ul: int = 200,
    Syringe_rate_ulsec: float = 300,
    Drain: bool = False,
    Cell_draintime_s: float = 60,
    ReturnLineWait_s: float = 30,
    ReturnLineReverseWait_s: float = 3,
    ResidualWait_s: float = 15,
    flush_volume_ul: float = 2000,
    clean: bool = False,
    clean_volume_ul: float = 5000,
    refill: bool = False,
    refill_volume_ul: float = 6000,
    water_refill_volume_ul: float = 6000,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "LS4_newsyringe040923",
) -> list:
    """Run a series of CV sweeps followed by a series of CAs on one sample.

    Loads a sample, fills the cell, recirculates, then iterates through the
    parallel ``CV_cycles``/``Vinit_vsRHE``/``Vapex1_vsRHE``/``Vapex2_vsRHE``/
    ``Vfinal_vsRHE``/``scanrate_voltsec`` lists running one CV per index and
    taking an aliquot whenever ``aliquot_postCV[i] == 1``. The same loop is
    repeated for CAs at every entry of ``CA_potentials_vs`` with aliquots
    governed by ``aliquot_postCA``. The cell can optionally be drained,
    flushed, cleaned, and refilled at the end.

    Args:
        plate_id: Plate id of the solid sample.
        plate_sample_no: Sample number on the plate.
        same_sample: Skip the move-to-sample step.
        stay_sample: Flush+drain instead of full unload.
        liquid_sample_no: Reservoir liquid sample number.
        liquid_sample_volume_ul: Cell fill volume (uL).
        recirculate_wait_time_m: Recirculation duration (minutes).
        CV_cycles: Number of CV cycles per scan list entry.
        Vinit_vsRHE: Initial potentials vs RHE per CV (V).
        Vapex1_vsRHE: First-apex potentials vs RHE per CV (V).
        Vapex2_vsRHE: Second-apex potentials vs RHE per CV (V).
        Vfinal_vsRHE: Final potentials vs RHE per CV (V).
        scanrate_voltsec: Scan rates per CV (V/s).
        CV_samplerate_sec: CV sample interval (s).
        number_of_postCAs: Reserved hint (unused at runtime).
        CA_potentials_vs: CA potentials in the chosen frame.
        potential_versus: Frame label for CAs (``"rhe"``/``"oer"``).
        CA_duration_sec: Per-CA durations (s).
        CA_samplerate_sec: CA sample interval (s).
        gamry_i_range: Gamry current range string.
        ph: Solution pH.
        ref_type: Reference electrode type label.
        ref_offset__V: Reference electrode offset (V).
        aliquot_postCV: Per-CV aliquot flags (1/0).
        aliquot_postCA: Per-CA aliquot flags (1/0).
        aliquot_volume_ul: Aliquot volume (uL).
        Syringe_rate_ulsec: Syringe rate (uL/s).
        Drain: Drain the cell at the end.
        Cell_draintime_s: Drain duration (s).
        ReturnLineWait_s: Forward return-line wait (s).
        ReturnLineReverseWait_s: Reverse return-line wait (s).
        ResidualWait_s: Passthrough residual wait (s).
        flush_volume_ul: Flush volume (uL) for stay-sample flush.
        clean: Run a clean cell step.
        clean_volume_ul: Cleaning volume (uL).
        refill: Refill syringes at the end.
        refill_volume_ul: Refill volume for the working solution (uL).
        water_refill_volume_ul: Refill volume for water (uL).
        PAL_Injector: PAL injector key.
        PAL_Injector_id: PAL injector identifier.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # for solid_sample_no in plate_sample_no_list:  # have to indent add expts if used

    if not same_sample:

        epm.add(
            "ADSS_sub_move_to_sample",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample_no,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )
    epm.add(
        "ADSS_sub_load",
        {
            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no,
            # "previous_liquid": use_electrolyte,
            "liquid_custom_position": "cell1_we",
            "liquid_sample_no": liquid_sample_no,
            "liquid_sample_volume_ul": liquid_sample_volume_ul,
        },
    )
    # if led_illumination:
    #     epm.add(
    #         "ADSS_sub_cell_illumination",
    #         {
    #             "led_wavelength": led_wavelength,
    #             "illumination_on": led_illumination,
    #         }

    #     )
    # if not use_electrolyte:

    epm.add(
        "ADSS_sub_cellfill_prefilled",
        {
            "Solution_volume_ul": liquid_sample_volume_ul,
            "Syringe_rate_ulsec": Syringe_rate_ulsec,
        },
    )
    # redundant?
    # epm.add(
    #     "ADSS_sub_load_liquid",
    #     {
    #         "liquid_custom_position": liquid_custom_position,
    #         "liquid_sample_no": liquid_sample_no,
    #     }
    # )
    # epm.add(
    #     "ADSS_sub_load_solid",
    #     {
    #         "solid_custom_position": solid_custom_position,
    #         "solid_plate_id": plate_id,
    #         "solid_sample_no": plate_sample_no,
    #     }
    # )
    epm.add(
        "ADSS_sub_recirculate",
        {
            "wait_time_s": recirculate_wait_time_m * 60,
        },
    )
    washmod = 0

    for i, CV_cycle in enumerate(CV_cycles):

        epm.add(
            "ADSS_sub_CV",
            {
                "Vinit_vsRHE": Vinit_vsRHE[i],
                "Vapex1_vsRHE": Vapex1_vsRHE[i],
                "Vapex2_vsRHE": Vapex2_vsRHE[i],
                "Vfinal_vsRHE": Vfinal_vsRHE[i],
                "scanrate_voltsec": scanrate_voltsec[i],
                "SampleRate": CV_samplerate_sec,
                "cycles": CV_cycle,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
            },
        )
        if aliquot_postCV[i] == 1:
            washmod += 1
            washone = washmod % 4 % 3 % 2
            washtwo = (washmod + 1) % 4 % 3 % 2
            washthree = (washmod + 2) % 4 % 3 % 2
            washfour = (washmod + 3) % 4 % 3 % 2

            epm.add(
                "ADSS_sub_sample_aliquot",
                {
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "EquilibrationTime_s": 0,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": washone,
                    "rinse_2": washtwo,
                    "rinse_3": washthree,
                    "rinse_4": washfour,
                },
            )

    for i, CA_potential_vs in enumerate(CA_potentials_vs):

        epm.add(
            "ADSS_sub_CA",
            {
                "CA_potential": CA_potential_vs,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "potential_versus": potential_versus,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA_duration_sec[i],
                "gamry_i_range": gamry_i_range,
                "aliquot_insitu": False,
            },
        )
        if aliquot_postCA[i] == 1:
            washmod += 1
            washone = washmod % 4 % 3 % 2
            washtwo = (washmod + 1) % 4 % 3 % 2
            washthree = (washmod + 2) % 4 % 3 % 2
            washfour = (washmod + 3) % 4 % 3 % 2

            epm.add(
                "ADSS_sub_sample_aliquot",
                {
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "EquilibrationTime_s": 0,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": washone,
                    "rinse_2": washtwo,
                    "rinse_3": washthree,
                    "rinse_4": washfour,
                },
            )

    if Drain:
        epm.add(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
                #    "ResidualWait_s": ResidualWait_s,
            },
        )

    if stay_sample:
        epm.add(
            "ADSS_sub_cellfill_flush",
            {
                "Solution_volume_ul": flush_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
                "ReturnLineWait_s": ReturnLineWait_s,
            },
        )
        epm.add(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
                #        "ResidualWait_s": ResidualWait_s,
            },
        )
    # if keep_electrolyte:
    #     epm.add("ADSS_sub_unload_solid",{})

    # else:

    #     epm.add("ADSS_sub_unloadall_customs",{})

    if clean:

        epm.add("ADSS_sub_move_to_clean_cell", {})

        epm.add(
            "ADSS_sub_clean_cell",
            {
                "Clean_volume_ul": clean_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
                "ReturnLineWait_s": ReturnLineWait_s,
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
                #    "ResidualWait_s": ResidualWait_s,
            },
        )
    if refill:
        epm.add(
            "ADSS_sub_refill_syringes",
            {
                "Waterclean_volume_ul": water_refill_volume_ul,
                "Solution_volume_ul": refill_volume_ul,
                "Syringe_rate_ulsec": 300,
            },
        )

    #    epm.add("ADSS_sub_tray_unload",{})

    # epm.add("ADSS_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=8)
def ADSS_PA_CVs_CAs_CVs_cell_simple(
    # solid_custom_position: str = "cell1_we",
    plate_id: int = 5917,
    plate_sample_no: list[int] = [16304],  #  instead of map select
    same_sample: bool = False,
    keep_electrolyte: bool = False,
    use_electrolyte: bool = False,
    Move_to_clean_and_clean: bool = True,
    # liquid_custom_position: str = "elec_res1",
    liquid_sample_no: int = 220,
    liquid_sample_volume_ul: float = 4000,
    recirculate_wait_time_m: float = 0.5,
    recirculate_reverse_wait_time_s: float = 1,
    CV_cycles: list[int] = [5, 3, 3],
    Vinit_vsRHE: list[float] = [1.23, 1.23, 1.23],  # Initial value in volts or amps.
    Vapex1_vsRHE: list[float] = [1.23, 1.23, 1.23],  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: list[float] = [0.6, 0.4, 0],  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: list[float] = [0.6, 0.4, 0],  # Final value in volts or amps.
    scanrate_voltsec: list[float] = [
        0.02,
        0.02,
        0.02,
    ],  # scan rate in volts/second or amps/second.
    CV_samplerate_sec: float = 0.05,
    # number_of_preCAs: int = 3,
    number_of_postCAs: int = 2,
    CA_potentials_vs: list[float] = [0.6, 0.4],
    potential_versus: str = "rhe",
    CA_duration_sec: list[float] = [60, 60],
    CA_samplerate_sec: float = 0.1,
    CV2_cycles: list[int] = [5, 3, 3],
    CV2_Vinit_vsRHE: list[float] = [
        1.23,
        1.23,
        1.23,
    ],  # Initial value in volts or amps.
    CV2_Vapex1_vsRHE: list[float] = [
        1.23,
        1.23,
        1.23,
    ],  # Apex 1 value in volts or amps.
    CV2_Vapex2_vsRHE: list[float] = [0.6, 0.4, 0],  # Apex 2 value in volts or amps.
    CV2_Vfinal_vsRHE: list[float] = [0.6, 0.4, 0],  # Final value in volts or amps.
    CV2_scanrate_voltsec: list[float] = [
        0.02,
        0.02,
        0.02,
    ],  # scan rate in volts/second or amps/second.
    CV2_samplerate_sec: float = 0.05,
    gamry_i_range: str = "auto",
    ph: float = 1.24,
    ref_type: str = "leakless",
    ref_offset__V: float = 0.0,
    aliquot_init: bool = True,
    aliquot_postCV: list[int] = [1, 0, 0],
    aliquot_postCA: list[int] = [1, 0],
    aliquot_volume_ul: int = 200,
    Syringe_rate_ulsec: float = 300,
    # Drain: bool = False,
    Cell_draintime_s: float = 60,
    # ReturnLineWait_s: float = 30,
    ReturnLineReverseWait_s: float = 10,
    # ResidualWait_s: float = 15,
    # flush_volume_ul: float = 2000,
    # clean: bool = False,
    # clean_volume_ul: float = 5000,
    # refill: bool = False,
    # refill_volume_ul: float = 6000,
    # water_refill_volume_ul: float = 6000,
    Clean_volume_ul: float = 12000,
    Clean_recirculate_s: float = 30,
    Clean_drain_s: float = 60,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "LS4_peek",
) -> list:
    """Iterate over a list of plate samples running CV-CA-CV with aliquots.

    For each entry in ``plate_sample_no`` the sequence loads the sample,
    refills electrolyte (unless reusing the current one), recirculates
    forward/reverse, takes an optional initial aliquot, runs the first CV
    list (one per index), then the CA list, then the second CV list
    (``CV2_*`` parameters), aliquoting after each step driven by the
    ``aliquot_post*`` flags. When ``Move_to_clean_and_clean`` is True the
    cell is cleaned between samples.

    Args:
        plate_id: Plate id holding the samples.
        plate_sample_no: List of plate sample numbers to iterate.
        same_sample: Skip the move-to-sample step.
        keep_electrolyte: Retain electrolyte at the end of each iteration.
        use_electrolyte: Reuse previously loaded electrolyte.
        Move_to_clean_and_clean: Move to the clean cell and run cleaning.
        liquid_sample_no: Reservoir liquid sample number.
        liquid_sample_volume_ul: Cell fill volume (uL).
        recirculate_wait_time_m: Forward recirculation duration (minutes).
        recirculate_reverse_wait_time_s: Reverse recirculation duration (s).
        CV_cycles: First CV-loop cycle counts.
        Vinit_vsRHE: First CV-loop initial potentials vs RHE (V).
        Vapex1_vsRHE: First CV-loop apex 1 potentials vs RHE (V).
        Vapex2_vsRHE: First CV-loop apex 2 potentials vs RHE (V).
        Vfinal_vsRHE: First CV-loop final potentials vs RHE (V).
        scanrate_voltsec: First CV-loop scan rates (V/s).
        CV_samplerate_sec: First CV sample interval (s).
        number_of_postCAs: Reserved hint (unused at runtime).
        CA_potentials_vs: CA potentials in the chosen frame.
        potential_versus: Frame label for CAs.
        CA_duration_sec: Per-CA durations (s).
        CA_samplerate_sec: CA sample interval (s).
        CV2_cycles: Second CV-loop cycle counts.
        CV2_Vinit_vsRHE: Second CV-loop initial potentials vs RHE (V).
        CV2_Vapex1_vsRHE: Second CV-loop apex 1 potentials vs RHE (V).
        CV2_Vapex2_vsRHE: Second CV-loop apex 2 potentials vs RHE (V).
        CV2_Vfinal_vsRHE: Second CV-loop final potentials vs RHE (V).
        CV2_scanrate_voltsec: Second CV-loop scan rates (V/s).
        CV2_samplerate_sec: Second CV sample interval (s).
        gamry_i_range: Gamry current range string.
        ph: Solution pH.
        ref_type: Reference electrode type label.
        ref_offset__V: Reference electrode offset (V).
        aliquot_init: Take an aliquot before electrochemistry starts.
        aliquot_postCV: Aliquot flag list applied to the CV loops.
        aliquot_postCA: Aliquot flag list applied to the CA loop.
        aliquot_volume_ul: Aliquot volume (uL).
        Syringe_rate_ulsec: Syringe rate (uL/s).
        Cell_draintime_s: Drain duration (s).
        ReturnLineReverseWait_s: Reverse return-line wait (s).
        Clean_volume_ul: Cleaning volume (uL).
        Clean_recirculate_s: Cleaning recirculation duration (s).
        Clean_drain_s: Cleaning drain duration (s).
        PAL_Injector: PAL injector key.
        PAL_Injector_id: PAL injector identifier.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # for solid_sample_no in plate_sample_no_list:  # have to indent add expts if used
    for sample in plate_sample_no:

        if not same_sample:

            epm.add(
                "ADSS_sub_move_to_sample",
                {
                    "solid_custom_position": "cell1_we",
                    "solid_plate_id": plate_id,
                    "solid_sample_no": sample,
                    "liquid_custom_position": "cell1_we",
                    "liquid_sample_no": liquid_sample_no,
                    "liquid_sample_volume_ul": liquid_sample_volume_ul,
                },
            )
        epm.add(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": sample,
                "previous_liquid": use_electrolyte,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )
        # if led_illumination:
        #     epm.add(
        #         "ADSS_sub_cell_illumination",
        #         {
        #             "led_wavelength": led_wavelength,
        #             "illumination_on": led_illumination,
        #         }

        #     )
        if not use_electrolyte:

            epm.add(
                "ADSS_sub_cellfill_prefilled",
                {
                    "Solution_volume_ul": liquid_sample_volume_ul,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                },
            )

        # pump recirculate forward
        epm.add(
            "ADSS_sub_recirculate",
            {
                "wait_time_s": recirculate_wait_time_m * 60,
            },
        )

        # pump recirculate reverse (for bubbles)
        epm.add(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "reverse",
                "wait_time_s": recirculate_reverse_wait_time_s,
            },
        )

        # pump recirculate forward
        epm.add(
            "ADSS_sub_recirculate",
            {
                "wait_time_s": 10,
            },
        )

        washmod = 0

        if aliquot_init:  # stops gas purge, takes aliquote, starts gas purge again

            washmod += 1
            washone = washmod % 4 % 3 % 2
            washtwo = (washmod + 1) % 4 % 3 % 2
            washthree = (washmod + 2) % 4 % 3 % 2
            washfour = (washmod + 3) % 4 % 3 % 2

            epm.add(
                "ADSS_sub_sample_aliquot",
                {
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "EquilibrationTime_s": 0,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": washone,
                    "rinse_2": washtwo,
                    "rinse_3": washthree,
                    "rinse_4": washfour,
                },
            )

        for i, CV_cycle in enumerate(CV_cycles):

            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": Vinit_vsRHE[i],
                    "Vapex1_vsRHE": Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": Vfinal_vsRHE[i],
                    "scanrate_voltsec": scanrate_voltsec[i],
                    "SampleRate": CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                },
            )
            if aliquot_postCV[i] == 1:

                washmod += 1
                washone = washmod % 4 % 3 % 2
                washtwo = (washmod + 1) % 4 % 3 % 2
                washthree = (washmod + 2) % 4 % 3 % 2
                washfour = (washmod + 3) % 4 % 3 % 2

                epm.add(
                    "ADSS_sub_sample_aliquot",
                    {
                        "aliquot_volume_ul": aliquot_volume_ul,
                        "EquilibrationTime_s": 0,
                        "PAL_Injector": PAL_Injector,
                        "PAL_Injector_id": PAL_Injector_id,
                        "rinse_1": washone,
                        "rinse_2": washtwo,
                        "rinse_3": washthree,
                        "rinse_4": washfour,
                    },
                )

        for i, CA_potential_vs in enumerate(CA_potentials_vs):

            epm.add(
                "ADSS_sub_CA",
                {
                    "CA_potential": CA_potential_vs,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "potential_versus": potential_versus,
                    "samplerate_sec": CA_samplerate_sec,
                    "CA_duration_sec": CA_duration_sec[i],
                    "gamry_i_range": gamry_i_range,
                    "aliquot_insitu": False,
                },
            )
            if aliquot_postCA[i] == 1:

                washmod += 1
                washone = washmod % 4 % 3 % 2
                washtwo = (washmod + 1) % 4 % 3 % 2
                washthree = (washmod + 2) % 4 % 3 % 2
                washfour = (washmod + 3) % 4 % 3 % 2

                epm.add(
                    "ADSS_sub_sample_aliquot",
                    {
                        "aliquot_volume_ul": aliquot_volume_ul,
                        "EquilibrationTime_s": 0,
                        "PAL_Injector": PAL_Injector,
                        "PAL_Injector_id": PAL_Injector_id,
                        "rinse_1": washone,
                        "rinse_2": washtwo,
                        "rinse_3": washthree,
                        "rinse_4": washfour,
                    },
                )

        # epm.add(
        #       "ADSS_sub_interrupt",
        #      {
        #         "reason":"Pause for injection of phosphoric"
        #    },
        # )

        for i, CV_cycle in enumerate(CV2_cycles):

            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": CV2_Vinit_vsRHE[i],
                    "Vapex1_vsRHE": CV2_Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": CV2_Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": CV2_Vfinal_vsRHE[i],
                    "scanrate_voltsec": CV2_scanrate_voltsec[i],
                    "SampleRate": CV2_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                },
            )
            if aliquot_postCV[i] == 1:

                washmod += 1
                washone = washmod % 4 % 3 % 2
                washtwo = (washmod + 1) % 4 % 3 % 2
                washthree = (washmod + 2) % 4 % 3 % 2
                washfour = (washmod + 3) % 4 % 3 % 2

                epm.add(
                    "ADSS_sub_sample_aliquot",
                    {
                        "aliquot_volume_ul": aliquot_volume_ul,
                        "EquilibrationTime_s": 0,
                        "PAL_Injector": PAL_Injector,
                        "PAL_Injector_id": PAL_Injector_id,
                        "rinse_1": washone,
                        "rinse_2": washtwo,
                        "rinse_3": washthree,
                        "rinse_4": washfour,
                    },
                )

        if keep_electrolyte:
            epm.add("ADSS_sub_unload_solid", {})

        else:

            epm.add("ADSS_sub_unloadall_customs", {})
            epm.add(
                "ADSS_sub_drain_cell",
                {
                    "DrainWait_s": Cell_draintime_s,
                    "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
                    #    "ResidualWait_s": ResidualWait_s,
                },
            )

        if Move_to_clean_and_clean:
            epm.add("ADSS_sub_move_to_clean_cell", {})
            epm.add(
                "ADSS_sub_clean_cell",
                {
                    "Clean_volume_ul": Clean_volume_ul,
                    "ReturnLineWait_s": Clean_recirculate_s,
                    "DrainWait_s": Clean_drain_s,
                },
            )

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=2)
def ADSS_CA_cell_multipotential(
    # solid_custom_position: str = "cell1_we",
    plate_id: int = 5917,
    plate_sample_no: int = 14050,  #  instead of map select
    same_sample: bool = False,
    stay_sample: bool = False,
    # liquid_custom_position: str = "elec_res1",
    liquid_sample_no: int = 220,
    liquid_sample_volume_ul: float = 4000,
    CA_potentials_vs: list[float] = [-0.5, 0.0, 0.5, 1.0],
    potential_versus: str = "oer",
    ph: float = 9.53,
    ref_type: str = "leakless",
    ref_offset__V: float = 0.0,
    CA_duration_sec: float = 1320,
    aliquot_times_sec: list[float] = [60, 600, 1140],
    aliquot_volume_ul: int = 200,
    OCV_duration: float = 60,
    OCValiquot_times_sec: list[float] = [20],
    samplerate_sec: float = 1,
    led_illumination: bool = False,
    led_dutycycle: float = 1,
    led_wavelength: str = "385",
    Syringe_rate_ulsec: float = 300,
    Cell_draintime_s: float = 60,
    ReturnLineWait_s: float = 30,
    ReturnLineReverseWait_s: float = 3,
    ResidualWait_s: float = 15,
    flush_volume_ul: float = 2000,
    clean: bool = False,
    clean_volume_ul: float = 5000,
    refill: bool = False,
    refill_volume_ul: float = 6000,
    water_refill_volume_ul: float = 6000,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "LS4_newsyringe040923",
) -> list:
    """Run an OCV/CA/OCV cycle at each potential in ``CA_potentials_vs``.

    Loads the sample (or uses the same one), fills the cell, then for each
    potential adds OCV before, CA at the potential, and OCV after. The
    ``led_illumination`` flag selects the ``*_photo`` variants. After the
    measurement the cell is drained and optionally flushed/cleaned/refilled.

    Args:
        plate_id: Plate id of the solid sample.
        plate_sample_no: Sample number on the plate.
        same_sample: Skip the move-to-sample step.
        stay_sample: Flush+drain after the experiment.
        liquid_sample_no: Reservoir liquid sample number.
        liquid_sample_volume_ul: Cell fill volume (uL).
        CA_potentials_vs: CA potentials to sweep through (V).
        potential_versus: Frame label for CAs (``"oer"``/``"rhe"``).
        ph: Solution pH.
        ref_type: Reference electrode type label.
        ref_offset__V: Reference electrode offset (V).
        CA_duration_sec: CA hold duration (s) for each potential.
        aliquot_times_sec: CA-relative aliquot timestamps (s).
        aliquot_volume_ul: Aliquot volume (uL).
        OCV_duration: OCV duration (s) before and after each CA.
        OCValiquot_times_sec: OCV-relative aliquot timestamps (s).
        samplerate_sec: Sample interval (s).
        led_illumination: Use photo-CA/OCV variants when True.
        led_dutycycle: LED toggle duty cycle (0-1).
        led_wavelength: LED wavelength string.
        Syringe_rate_ulsec: Syringe rate (uL/s).
        Cell_draintime_s: Drain duration (s).
        ReturnLineWait_s: Forward return-line wait (s).
        ReturnLineReverseWait_s: Reverse return-line wait (s).
        ResidualWait_s: Passthrough residual wait (s).
        flush_volume_ul: Flush volume (uL) when ``stay_sample`` is True.
        clean: Move-to-clean-cell and clean.
        clean_volume_ul: Cleaning volume (uL).
        refill: Refill syringes at end.
        refill_volume_ul: Refill volume for working solution (uL).
        water_refill_volume_ul: Refill volume for water (uL).
        PAL_Injector: PAL injector key.
        PAL_Injector_id: PAL injector identifier.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # for solid_sample_no in plate_sample_no_list:  # have to indent add expts if used

    if same_sample:
        epm.add(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample_no,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )
    else:
        epm.add(
            "ADSS_sub_sample_start",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample_no,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )
    if led_illumination:
        epm.add(
            "ADSS_sub_cell_illumination",
            {
                "led_wavelength": led_wavelength,
                "illumination_on": led_illumination,
            },
        )
    epm.add(
        "ADSS_sub_cellfill_prefilled",
        {
            "Solution_volume_ul": liquid_sample_volume_ul,
            "Syringe_rate_ulsec": Syringe_rate_ulsec,
        },
    )
    # redundant?
    # epm.add(
    #     "ADSS_sub_load_liquid",
    #     {
    #         "liquid_custom_position": liquid_custom_position,
    #         "liquid_sample_no": liquid_sample_no,
    #     }
    # )
    # epm.add(
    #     "ADSS_sub_load_solid",
    #     {
    #         "solid_custom_position": solid_custom_position,
    #         "solid_plate_id": plate_id,
    #         "solid_sample_no": plate_sample_no,
    #     }
    # )
    epm.add("ADSS_sub_recirculate", {})

    for CA_potential_vs in CA_potentials_vs:
        if led_illumination:

            epm.add(
                "ADSS_sub_OCV_photo",
                {
                    "Tval__s": OCV_duration,
                    "SampleRate": samplerate_sec,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "led_wavelength": led_wavelength,
                    "toggle_illum_duty": led_dutycycle,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "aliquot_times_sec": OCValiquot_times_sec,
                    "aliquot_insitu": True,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": 1,
                },
            )
            epm.add(
                "ADSS_sub_CA_photo",
                {
                    "CA_potential": CA_potential_vs,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "potential_versus": potential_versus,
                    "samplerate_sec": samplerate_sec,
                    "CA_duration_sec": CA_duration_sec,
                    "led_wavelength": led_wavelength,
                    "toggle_illum_duty": led_dutycycle,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "aliquot_times_sec": aliquot_times_sec,
                    "aliquot_insitu": True,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                },
            )
            epm.add(
                "ADSS_sub_OCV_photo",
                {
                    "Tval__s": OCV_duration,
                    "SampleRate": samplerate_sec,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "led_wavelength": led_wavelength,
                    "toggle_illum_duty": led_dutycycle,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "aliquot_times_sec": OCValiquot_times_sec,
                    "aliquot_insitu": True,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": 0,
                    "rinse_4": 1,
                },
            )
            epm.add(
                "ADSS_sub_cell_illumination",
                {
                    "led_wavelength": led_wavelength,
                    "illumination_on": False,
                },
            )
        else:

            epm.add(
                "ADSS_sub_OCV",
                {
                    "Tval__s": OCV_duration,
                    "SampleRate": samplerate_sec,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "aliquot_times_sec": OCValiquot_times_sec,
                    "aliquot_insitu": True,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": 1,
                },
            )
            epm.add(
                "ADSS_sub_CA",
                {
                    "CA_potential": CA_potential_vs,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "potential_versus": potential_versus,
                    "samplerate_sec": samplerate_sec,
                    "CA_duration_sec": CA_duration_sec,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "aliquot_times_sec": aliquot_times_sec,
                    "aliquot_insitu": True,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                },
            )
            epm.add(
                "ADSS_sub_OCV",
                {
                    "Tval__s": OCV_duration,
                    "SampleRate": samplerate_sec,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "aliquot_times_sec": OCValiquot_times_sec,
                    "aliquot_insitu": True,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": 0,
                    "rinse_4": 1,
                },
            )

    epm.add(
        "ADSS_sub_drain_cell",
        {
            "DrainWait_s": Cell_draintime_s,
            "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
            #    "ResidualWait_s": ResidualWait_s,
        },
    )
    if stay_sample:
        epm.add(
            "ADSS_sub_cellfill_flush",
            {
                "Solution_volume_ul": flush_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
                "ReturnLineWait_s": ReturnLineWait_s,
            },
        )
        epm.add(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
                #        "ResidualWait_s": ResidualWait_s,
            },
        )
    epm.add("ADSS_sub_unload_liquid", {})

    epm.add("ADSS_sub_unloadall_customs", {})

    if clean:

        epm.add("ADSS_sub_move_to_clean_cell", {})

        epm.add(
            "ADSS_sub_clean_cell",
            {
                "Clean_volume_ul": clean_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
                "ReturnLineWait_s": ReturnLineWait_s,
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
                #        "ResidualWait_s": ResidualWait_s,
            },
        )
    if refill:
        epm.add(
            "ADSS_sub_refill_syringes",
            {
                "Waterclean_volume_ul": water_refill_volume_ul,
                "Solution_volume_ul": refill_volume_ul,
                "Syringe_rate_ulsec": 300,
            },
        )

    #    epm.add("ADSS_sub_tray_unload",{})

    # epm.add("ADSS_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=1)
def ADSS_PA_CVs_testing(
    # solid_custom_position: str = "cell1_we",
    plate_id: int = 6307,
    plate_sample_no: int = 14050,  #  instead of map select
    second_sample_no: int = 14050,
    same_sample: bool = False,
    keep_electrolyte: bool = False,
    keep_electrolyte_post: bool = False,
    use_electrolyte: bool = False,
    # liquid_custom_position: str = "elec_res1",
    liquid_sample_no: int = 220,
    liquid_sample_volume_ul: float = 4000,
    recirculate_wait_time_m: float = 5,
    CV_cycles: list[int] = [10, 3],
    Vinit_vsRHE: list[float] = [0.05, 0.05, 0.05],  # Initial value in volts or amps.
    Vapex1_vsRHE: list[float] = [0.05, 0.05, 0.05],  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: list[float] = [1.2, 1.2, 1.2],  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: list[float] = [0.05, 0.05, 0.05],  # Final value in volts or amps.
    scanrate_voltsec: list[float] = [
        0.1,
        0.02,
        0.02,
    ],  # scan rate in volts/second or amps/second.
    CV_samplerate_sec: float = 0.05,
    # number_of_preCAs: int = 3,
    # number_of_postCAs: int = 2,
    # CA_potentials_vs: list[float] = [0.6,0.4],
    potential_versus: str = "rhe",
    # CA_duration_sec: list[float] = [60,60],
    # CA_samplerate_sec: float = 0.1,
    CV2_cycles: list[int] = [3],
    CV2_Vinit_vsRHE: list[float] = [0.05],  # Initial value in volts or amps.
    CV2_Vapex1_vsRHE: list[float] = [0.05],  # Apex 1 value in volts or amps.
    CV2_Vapex2_vsRHE: list[float] = [1.2],  # Apex 2 value in volts or amps.
    CV2_Vfinal_vsRHE: list[float] = [0.05],  # Final value in volts or amps.
    CV2_scanrate_voltsec: list[float] = [
        0.02
    ],  # scan rate in volts/second or amps/second.
    CV2_samplerate_sec: float = 0.05,
    gamry_i_range: str = "auto",
    ph: float = 9.53,
    ref_type: str = "leakless",
    ref_offset__V: float = 0.0,
    # aliquot_postCV: list[int] = [1,0,0],
    # aliquot_postCA: list[int] = [1,0],
    # aliquot_volume_ul: int = 200,
    Syringe_rate_ulsec: float = 300,
    # Drain: bool = False,
    Cell_draintime_s: float = 60,
    # ReturnLineWait_s: float = 30,
    ReturnLineReverseWait_s: float = 10,
    Clean_volume_ul: float = 6000,
    CleanDrainWait_s: float = 60,
    # ResidualWait_s: float = 15,
    # flush_volume_ul: float = 2000,
    # clean: bool = False,
    # clean_volume_ul: float = 5000,
    # refill: bool = False,
    # refill_volume_ul: float = 6000,
    # water_refill_volume_ul: float = 6000,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "LS4_newsyringe040923",
) -> list:
    """Testing variant of the PA CV protocol with manual gas-switching pauses.

    Loads ``plate_sample_no`` (then optionally swaps to ``second_sample_no``),
    fills/recirculates, runs the first CV list pausing for an oxygen swap
    after the second CV, prompts the operator to inject phosphoric acid,
    runs the second CV list (``CV2_*``), then either keeps electrolyte or
    drains/cleans the cell. If draining a second sample is loaded and the
    first CV list is repeated with another interrupt to swap back to N2.

    Args:
        plate_id: Plate id holding the samples.
        plate_sample_no: Primary sample number.
        second_sample_no: Sample number used after the cleaning step.
        same_sample: Skip the initial move-to-sample step.
        keep_electrolyte: Retain electrolyte during the first phase.
        keep_electrolyte_post: Retain electrolyte during the second phase.
        use_electrolyte: Reuse previously loaded electrolyte.
        liquid_sample_no: Reservoir liquid sample number.
        liquid_sample_volume_ul: Cell fill volume (uL).
        recirculate_wait_time_m: Recirculation duration (minutes).
        CV_cycles: First CV-loop cycle counts.
        Vinit_vsRHE: First CV-loop initial potentials vs RHE (V).
        Vapex1_vsRHE: First CV-loop apex 1 potentials vs RHE (V).
        Vapex2_vsRHE: First CV-loop apex 2 potentials vs RHE (V).
        Vfinal_vsRHE: First CV-loop final potentials vs RHE (V).
        scanrate_voltsec: First CV-loop scan rates (V/s).
        CV_samplerate_sec: First CV sample interval (s).
        potential_versus: Frame label for any CA actions (unused in this loop).
        CV2_cycles: Second CV-loop cycle counts.
        CV2_Vinit_vsRHE: Second CV-loop initial potentials vs RHE (V).
        CV2_Vapex1_vsRHE: Second CV-loop apex 1 potentials vs RHE (V).
        CV2_Vapex2_vsRHE: Second CV-loop apex 2 potentials vs RHE (V).
        CV2_Vfinal_vsRHE: Second CV-loop final potentials vs RHE (V).
        CV2_scanrate_voltsec: Second CV-loop scan rates (V/s).
        CV2_samplerate_sec: Second CV sample interval (s).
        gamry_i_range: Gamry current range string.
        ph: Solution pH.
        ref_type: Reference electrode type label.
        ref_offset__V: Reference electrode offset (V).
        Syringe_rate_ulsec: Syringe rate (uL/s).
        Cell_draintime_s: Drain duration (s).
        ReturnLineReverseWait_s: Reverse return-line wait (s).
        Clean_volume_ul: Cleaning volume (uL).
        CleanDrainWait_s: Clean drain duration (s).
        PAL_Injector: PAL injector key.
        PAL_Injector_id: PAL injector identifier.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # for solid_sample_no in plate_sample_no_list:  # have to indent add expts if used

    if not same_sample:

        epm.add(
            "ADSS_sub_move_to_sample",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample_no,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )
    epm.add(
        "ADSS_sub_load",
        {
            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no,
            "previous_liquid": use_electrolyte,
            "liquid_custom_position": "cell1_we",
            "liquid_sample_no": liquid_sample_no,
            "liquid_sample_volume_ul": liquid_sample_volume_ul,
        },
    )
    # if led_illumination:
    #     epm.add(
    #         "ADSS_sub_cell_illumination",
    #         {
    #             "led_wavelength": led_wavelength,
    #             "illumination_on": led_illumination,
    #         }

    #     )
    if not use_electrolyte:

        epm.add(
            "ADSS_sub_cellfill_prefilled",
            {
                "Solution_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            },
        )

    epm.add(
        "ADSS_sub_recirculate",
        {
            "wait_time_s": recirculate_wait_time_m * 60,
        },
    )
    washmod = 0
    # N2clean cvs
    for i, CV_cycle in enumerate(CV_cycles):

        epm.add(
            "ADSS_sub_CV",
            {
                "Vinit_vsRHE": Vinit_vsRHE[i],
                "Vapex1_vsRHE": Vapex1_vsRHE[i],
                "Vapex2_vsRHE": Vapex2_vsRHE[i],
                "Vfinal_vsRHE": Vfinal_vsRHE[i],
                "scanrate_voltsec": scanrate_voltsec[i],
                "SampleRate": CV_samplerate_sec,
                "cycles": CV_cycle,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
            },
        )
        if i == 1:
            epm.add(
                "ADSS_sub_interrupt",
                {"reason": "Pause for switch to oxygen"},
            )
        # if aliquot_postCV[i] == 1:
        #     washmod += 1
        #     washone = washmod %4 %3 %2
        #     washtwo = (washmod + 1) %4 %3 %2
        #     washthree = (washmod + 2) %4 %3 %2
        #     washfour = (washmod + 3) %4 %3 %2

        #     epm.add(
        #         "ADSS_sub_sample_aliquot",
        #         {
        #             "aliquot_volume_ul": aliquot_volume_ul,
        #             "EquilibrationTime_s": 0,
        #             "PAL_Injector": PAL_Injector,
        #             "PAL_Injector_id": PAL_Injector_id,
        #             "rinse_1": washone,
        #             "rinse_2": washtwo,
        #             "rinse_3": washthree,
        #             "rinse_4": washfour,
        #         }
        #     )

    # for i, CA_potential_vs in enumerate(CA_potentials_vs):

    #     epm.add(
    #         "ADSS_sub_CA",
    #         {
    #             "CA_potential": CA_potential_vs,
    #             "ph": ph,
    #             "ref_type": ref_type,
    #             "ref_offset__V": ref_offset__V,
    #             "potential_versus": potential_versus,
    #             "samplerate_sec": CA_samplerate_sec,
    #             "CA_duration_sec": CA_duration_sec[i],
    #             "gamry_i_range": gamry_i_range,
    #             "aliquot_insitu": False,
    #         },
    #     )
    #     if aliquot_postCA[i] == 1:
    #         washmod += 1
    #         washone = washmod %4 %3 %2
    #         washtwo = (washmod + 1) %4 %3 %2
    #         washthree = (washmod + 2) %4 %3 %2
    #         washfour = (washmod + 3) %4 %3 %2

    #         epm.add(
    #             "ADSS_sub_sample_aliquot",
    #             {
    #                 "aliquot_volume_ul": aliquot_volume_ul,
    #                 "EquilibrationTime_s": 0,
    #                 "PAL_Injector": PAL_Injector,
    #                 "PAL_Injector_id": PAL_Injector_id,
    #                 "rinse_1": washone,
    #                 "rinse_2": washtwo,
    #                 "rinse_3": washthree,
    #                 "rinse_4": washfour,
    #             }
    #         )
    epm.add(
        "ADSS_sub_interrupt",
        {"reason": "Pause for injection of phosphoric"},
    )
    epm.add(
        "ADSS_sub_recirculate",
        {
            "wait_time_s": 10,
        },
    )

    for i, CV_cycle in enumerate(CV2_cycles):

        epm.add(
            "ADSS_sub_CV",
            {
                "Vinit_vsRHE": CV2_Vinit_vsRHE[i],
                "Vapex1_vsRHE": CV2_Vapex1_vsRHE[i],
                "Vapex2_vsRHE": CV2_Vapex2_vsRHE[i],
                "Vfinal_vsRHE": CV2_Vfinal_vsRHE[i],
                "scanrate_voltsec": CV2_scanrate_voltsec[i],
                "SampleRate": CV2_samplerate_sec,
                "cycles": CV_cycle,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
            },
        )
        # if aliquot_postCV[i] == 1:
        #     washmod += 1
        #     washone = washmod %4 %3 %2
        #     washtwo = (washmod + 1) %4 %3 %2
        #     washthree = (washmod + 2) %4 %3 %2
        #     washfour = (washmod + 3) %4 %3 %2

        #     epm.add(
        #         "ADSS_sub_sample_aliquot",
        #         {
        #             "aliquot_volume_ul": aliquot_volume_ul,
        #             "EquilibrationTime_s": 0,
        #             "PAL_Injector": PAL_Injector,
        #             "PAL_Injector_id": PAL_Injector_id,
        #             "rinse_1": washone,
        #             "rinse_2": washtwo,
        #             "rinse_3": washthree,
        #             "rinse_4": washfour,
        #         }
        #     )

    if keep_electrolyte:
        epm.add("ADSS_sub_unload_solid", {})

    else:

        epm.add("ADSS_sub_unloadall_customs", {})
        epm.add(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
                #    "ResidualWait_s": ResidualWait_s,
            },
        )
        epm.add("ADSS_sub_move_to_clean_cell", {})
        epm.add(
            "ADSS_sub_clean_cell",
            {
                "Clean_volume": Clean_volume_ul,
                "DrainWait_s": CleanDrainWait_s,
                #    "ResidualWait_s": ResidualWait_s,
            },
        )
        epm.add(
            "ADSS_sub_interrupt",
            {"reason": "Pause for switch to nitrogen"},
        )

        epm.add(
            "ADSS_sub_move_to_sample",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": second_sample_no,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )
        epm.add(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample_no,
                "previous_liquid": use_electrolyte,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )

        epm.add(
            "ADSS_sub_cellfill_prefilled",
            {
                "Solution_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            },
        )

        epm.add(
            "ADSS_sub_recirculate",
            {
                "wait_time_s": recirculate_wait_time_m * 60,
            },
        )
        washmod = 0
        # N2clean cvs
        for i, CV_cycle in enumerate(CV_cycles):

            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": Vinit_vsRHE[i],
                    "Vapex1_vsRHE": Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": Vfinal_vsRHE[i],
                    "scanrate_voltsec": scanrate_voltsec[i],
                    "SampleRate": CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                },
            )
            if i == 0:
                epm.add(
                    "ADSS_sub_interrupt",
                    {"reason": "Pause for switch to oxygen"},
                )
            if i == 1:
                break

        if keep_electrolyte_post:
            epm.add("ADSS_sub_unload_solid", {})

        else:

            epm.add("ADSS_sub_unloadall_customs", {})
            epm.add(
                "ADSS_sub_drain_cell",
                {
                    "DrainWait_s": Cell_draintime_s,
                    "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
                    #    "ResidualWait_s": ResidualWait_s,
                },
            )

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=1)
def ADSS_PA_CVs_CAs_CVs_autogasswitching(
    # solid_custom_position: str = "cell1_we",
    plate_id: int = 6307,
    plate_sample_no: int = 14050,  #  instead of map select
    same_sample: bool = False,
    use_electrolyte: bool = False,
    keep_electrolyte: bool = False,
    # liquid_custom_position: str = "elec_res1",
    liquid_sample_no: int = 1053,
    liquid_sample_volume_ul: float = 4000,
    phosphoric_sample_no: int = 99999,
    phosphoric_location: list[int] = [2, 2, 54],
    phosphoric_quantity_ul: int = 0,
    recirculate_wait_time_m: float = 5,
    postN2_recirculate_wait_time_m: float = 5,
    CleaningCV_cycles: int = 6,
    CleaningCV_Vinit_vsRHE: float = 0.05,
    CleaningCV_Vapex2_vsRHE: float = 1.5,
    CleaningCV_scanrate_voltsec: float = 0.1,
    CV_cycles: list[int] = [10, 3],
    Vinit_vsRHE: list[float] = [0.05, 0.05, 0.05],  # Initial value in volts or amps.
    Vapex1_vsRHE: list[float] = [0.05, 0.05, 0.05],  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: list[float] = [1.2, 1.2, 1.2],  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: list[float] = [0.05, 0.05, 0.05],  # Final value in volts or amps.
    scanrate_voltsec: list[float] = [
        0.1,
        0.02,
        0.02,
    ],  # scan rate in volts/second or amps/second.
    CV_samplerate_sec: float = 0.05,
    CA_potentials_vs: list[float] = [0.6, 0.4],
    potential_versus: str = "rhe",
    CA_duration_sec: list[float] = [60, 60],
    CA_samplerate_sec: float = 0.1,
    CV2_cycles: list[int] = [3],
    CV2_Vinit_vsRHE: list[float] = [0.05],  # Initial value in volts or amps.
    CV2_Vapex1_vsRHE: list[float] = [0.05],  # Apex 1 value in volts or amps.
    CV2_Vapex2_vsRHE: list[float] = [1.2],  # Apex 2 value in volts or amps.
    CV2_Vfinal_vsRHE: list[float] = [0.05],  # Final value in volts or amps.
    CV2_scanrate_voltsec: list[float] = [
        0.02
    ],  # scan rate in volts/second or amps/second.
    CV2_samplerate_sec: float = 0.05,
    gamry_i_range: str = "auto",
    ph: float = 1.24,
    ref_type: str = "leakless",
    ref_offset__V: float = 0.0,
    aliquot_init: bool = True,
    aliquot_postCV: list[int] = [1, 0, 0],
    aliquot_postCA: list[int] = [1, 0],
    aliquot_volume_ul: int = 100,
    Syringe_rate_ulsec: float = 300,
    # Drain: bool = False,
    Cell_draintime_s: float = 60,
    # ReturnLineWait_s: float = 30,
    ReturnLineReverseWait_s: float = 10,
    clean_cell: bool = False,
    Clean_volume_ul: float = 12000,
    CleanDrainWait_s: float = 80,
    # ResidualWait_s: float = 15,
    # flush_volume_ul: float = 2000,
    # clean: bool = False,
    # clean_volume_ul: float = 5000,
    # refill: bool = False,
    # refill_volume_ul: float = 6000,
    # water_refill_volume_ul: float = 6000,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "LS4_peek",
) -> list:
    """PA CV/CA protocol with automatic N2<->O2 gas switching valves.

    Optionally pauses for phosphoric-acid source setup, loads the sample,
    purges with N2 and runs cleaning CV cycles, switches to O2 and runs the
    main CV list, runs the CA list, transfers phosphoric acid into the cell,
    recirculates, runs the ``CV2_*`` list, and finally drains/cleans the
    cell. Aliquots are taken at each ``aliquot_post*`` flag and a wash
    counter rotates the rinse profile across aliquots.

    Args:
        plate_id: Plate id holding the sample.
        plate_sample_no: Sample number on the plate.
        same_sample: Skip the move-to-sample step.
        use_electrolyte: Reuse previously loaded electrolyte.
        keep_electrolyte: Retain electrolyte at end of run.
        liquid_sample_no: Reservoir liquid sample number.
        liquid_sample_volume_ul: Cell fill volume (uL).
        phosphoric_sample_no: Sample number for the phosphoric vial.
        phosphoric_location: ``[tray, slot, vial]`` location of the source.
        phosphoric_quantity_ul: Phosphoric acid injection volume (uL).
        recirculate_wait_time_m: Initial recirculation duration (minutes).
        postN2_recirculate_wait_time_m: Post-N2 recirculation duration (minutes).
        CleaningCV_cycles: N2 cleaning CV cycle count.
        CleaningCV_Vinit_vsRHE: Cleaning CV initial potential vs RHE (V).
        CleaningCV_Vapex2_vsRHE: Cleaning CV apex-2 potential vs RHE (V).
        CleaningCV_scanrate_voltsec: Cleaning CV scan rate (V/s).
        CV_cycles: Main CV-loop cycle counts.
        Vinit_vsRHE: Main CV initial potentials vs RHE (V).
        Vapex1_vsRHE: Main CV apex-1 potentials vs RHE (V).
        Vapex2_vsRHE: Main CV apex-2 potentials vs RHE (V).
        Vfinal_vsRHE: Main CV final potentials vs RHE (V).
        scanrate_voltsec: Main CV scan rates (V/s).
        CV_samplerate_sec: Main CV sample interval (s).
        CA_potentials_vs: CA potentials in the chosen frame.
        potential_versus: Frame label for CAs.
        CA_duration_sec: Per-CA durations (s).
        CA_samplerate_sec: CA sample interval (s).
        CV2_cycles: Second CV-loop cycle counts.
        CV2_Vinit_vsRHE: Second CV initial potentials vs RHE (V).
        CV2_Vapex1_vsRHE: Second CV apex-1 potentials vs RHE (V).
        CV2_Vapex2_vsRHE: Second CV apex-2 potentials vs RHE (V).
        CV2_Vfinal_vsRHE: Second CV final potentials vs RHE (V).
        CV2_scanrate_voltsec: Second CV scan rates (V/s).
        CV2_samplerate_sec: Second CV sample interval (s).
        gamry_i_range: Gamry current range string.
        ph: Solution pH.
        ref_type: Reference electrode type label.
        ref_offset__V: Reference electrode offset (V).
        aliquot_init: Take an initial aliquot before electrochemistry.
        aliquot_postCV: Aliquot flags for the main CV loop.
        aliquot_postCA: Aliquot flags for the CA loop.
        aliquot_volume_ul: Aliquot volume (uL).
        Syringe_rate_ulsec: Syringe rate (uL/s).
        Cell_draintime_s: Drain duration (s).
        ReturnLineReverseWait_s: Reverse return-line wait (s).
        clean_cell: Run a clean cell step at the end.
        Clean_volume_ul: Cleaning volume (uL).
        CleanDrainWait_s: Clean drain duration (s).
        PAL_Injector: PAL injector key.
        PAL_Injector_id: PAL injector identifier.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    if phosphoric_quantity_ul:
        # may need vial unload, also vial liquid load

        epm.add(
            "ADSS_sub_interrupt",
            {"reason": "this is where phosphoric source is set"},
        )

        # epm.add(
        #     "archive_custom_add_liquid",
        #     {},
        # )

    # need to put phosphoric into helao vial tracking

    # for solid_sample_no in plate_sample_no_list:  # have to indent add expts if used

    if not same_sample:

        epm.add(
            "ADSS_sub_move_to_sample",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample_no,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )
    epm.add(
        "ADSS_sub_load",
        {
            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no,
            "previous_liquid": use_electrolyte,
            "liquid_custom_position": "cell1_we",
            "liquid_sample_no": liquid_sample_no,
            "liquid_sample_volume_ul": liquid_sample_volume_ul,
        },
    )
    washmod = 0

    # if led_illumination:
    #     epm.add(
    #         "ADSS_sub_cell_illumination",
    #         {
    #             "led_wavelength": led_wavelength,
    #             "illumination_on": led_illumination,
    #         }

    #     )
    if not use_electrolyte:

        epm.add(
            "ADSS_sub_cellfill_prefilled",
            {
                "Solution_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            },
        )
    # N2 gas for initial cleaning
    epm.add(
        "ADSS_sub_gasvalve_N2flow",
        {
            "open": True,
        },
    )
    epm.add(
        "ADSS_sub_recirculate",
        {
            "wait_time_s": recirculate_wait_time_m * 60,
        },
    )

    if aliquot_init:

        washmod += 1
        washone = washmod % 4 % 3 % 2
        washtwo = (washmod + 1) % 4 % 3 % 2
        washthree = (washmod + 2) % 4 % 3 % 2
        washfour = (washmod + 3) % 4 % 3 % 2

        epm.add(
            "ADSS_sub_sample_aliquot",
            {
                "aliquot_volume_ul": aliquot_volume_ul,
                "EquilibrationTime_s": 0,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
                "rinse_1": washone,
                "rinse_2": washtwo,
                "rinse_3": washthree,
                "rinse_4": washfour,
            },
        )

    # N2clean cvs

    epm.add(
        "ADSS_sub_CV",
        {
            "Vinit_vsRHE": CleaningCV_Vinit_vsRHE,
            "Vapex1_vsRHE": CleaningCV_Vinit_vsRHE,
            "Vapex2_vsRHE": CleaningCV_Vapex2_vsRHE,
            "Vfinal_vsRHE": CleaningCV_Vinit_vsRHE,
            "scanrate_voltsec": CleaningCV_scanrate_voltsec,
            "SampleRate": CV_samplerate_sec,
            "cycles": CleaningCV_cycles,
            "gamry_i_range": gamry_i_range,
            "ph": ph,
            "ref_type": ref_type,
            "ref_offset__V": ref_offset__V,
            "aliquot_insitu": False,
        },
    )
    # switch back to oxygen
    epm.add(
        "ADSS_sub_gasvalve_N2flow",
        {
            "open": False,
        },
    )
    epm.add(
        "ADSS_sub_recirculate",
        {
            "wait_time_s": postN2_recirculate_wait_time_m * 60,
        },
    )

    # CV cycles of interest

    for i, CV_cycle in enumerate(CV_cycles):

        epm.add(
            "ADSS_sub_CV",
            {
                "Vinit_vsRHE": Vinit_vsRHE[i],
                "Vapex1_vsRHE": Vapex1_vsRHE[i],
                "Vapex2_vsRHE": Vapex2_vsRHE[i],
                "Vfinal_vsRHE": Vfinal_vsRHE[i],
                "scanrate_voltsec": scanrate_voltsec[i],
                "SampleRate": CV_samplerate_sec,
                "cycles": CV_cycle,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
            },
        )
        if aliquot_postCV[i] == 1:
            washmod += 1
            washone = washmod % 4 % 3 % 2
            washtwo = (washmod + 1) % 4 % 3 % 2
            washthree = (washmod + 2) % 4 % 3 % 2
            washfour = (washmod + 3) % 4 % 3 % 2

            epm.add(
                "ADSS_sub_sample_aliquot",
                {
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "EquilibrationTime_s": 0,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": washone,
                    "rinse_2": washtwo,
                    "rinse_3": washthree,
                    "rinse_4": washfour,
                },
            )

    for i, CA_potential_vs in enumerate(CA_potentials_vs):

        epm.add(
            "ADSS_sub_CA",
            {
                "CA_potential": CA_potential_vs,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "potential_versus": potential_versus,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA_duration_sec[i],
                "gamry_i_range": gamry_i_range,
                "aliquot_insitu": False,
            },
        )
        if aliquot_postCA[i] == 1:
            washmod += 1
            washone = washmod % 4 % 3 % 2
            washtwo = (washmod + 1) % 4 % 3 % 2
            washthree = (washmod + 2) % 4 % 3 % 2
            washfour = (washmod + 3) % 4 % 3 % 2

            epm.add(
                "ADSS_sub_sample_aliquot",
                {
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "EquilibrationTime_s": 0,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": washone,
                    "rinse_2": washtwo,
                    "rinse_3": washthree,
                    "rinse_4": washfour,
                },
            )
    # epm.add(
    #         "ADSS_sub_interrupt",
    #         {
    #             "reason":"Pause for injection of phosphoric",
    #         },
    #     )

    epm.add(
        "ADSS_sub_tranfer_liquid_in",
        {
            "destination": "cell1_we",
            "source_tray": phosphoric_location[0],
            "source_slot": phosphoric_location[1],
            "source_vial": phosphoric_location[2],
            "liquid_sample_no": phosphoric_sample_no,
            "aliquot_volume_ul": phosphoric_quantity_ul,
            "PAL_Injector": PAL_Injector,
            "PAL_Injector_id": PAL_Injector_id,
            "rinse_1": True,
            "rinse_2": False,
            "rinse_3": False,
            "rinse_4": True,
        },
    )

    epm.add(
        "ADSS_sub_recirculate",
        {
            "wait_time_s": 10,
        },
    )

    for i, CV_cycle in enumerate(CV2_cycles):

        epm.add(
            "ADSS_sub_CV",
            {
                "Vinit_vsRHE": CV2_Vinit_vsRHE[i],
                "Vapex1_vsRHE": CV2_Vapex1_vsRHE[i],
                "Vapex2_vsRHE": CV2_Vapex2_vsRHE[i],
                "Vfinal_vsRHE": CV2_Vfinal_vsRHE[i],
                "scanrate_voltsec": CV2_scanrate_voltsec[i],
                "SampleRate": CV2_samplerate_sec,
                "cycles": CV_cycle,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
            },
        )
        if aliquot_postCV[i] == 1:
            washmod += 1
            washone = washmod % 4 % 3 % 2
            washtwo = (washmod + 1) % 4 % 3 % 2
            washthree = (washmod + 2) % 4 % 3 % 2
            washfour = (washmod + 3) % 4 % 3 % 2

            epm.add(
                "ADSS_sub_sample_aliquot",
                {
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "EquilibrationTime_s": 0,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": washone,
                    "rinse_2": washtwo,
                    "rinse_3": washthree,
                    "rinse_4": washfour,
                },
            )

    if keep_electrolyte:
        epm.add("ADSS_sub_unload_solid", {})

    else:

        epm.add("ADSS_sub_unloadall_customs", {})
        epm.add(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
                #    "ResidualWait_s": ResidualWait_s,
            },
        )
        if clean_cell:
            epm.add("ADSS_sub_move_to_clean_cell", {})
            epm.add(
                "ADSS_sub_clean_cell",
                {
                    "Clean_volume": Clean_volume_ul,
                    "DrainWait_s": CleanDrainWait_s,
                    #    "ResidualWait_s": ResidualWait_s,
                },
            )

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=4)
def ADSS_PA_CV_TRI(
    # note: str = "need as many samples as you expect combinations of UPL and LPL",
    # sample info
    # solid_custom_position: str = "cell1_we",
    plate_id: int = 6307,
    plate_id_ref_Pt: int = 6173,
    plate_sample_no_list: list[int] = [
        16304
    ],  #  need as many samples as you expect combinations of UPL and LPL
    LPL_list: list[float] = [
        0.05,
        0.55,
        0.05,
        0.55,
    ],
    UPL_list: list[float] = [
        1.3,
        0.8,
        1.3,
        0.8,
    ],
    # side info
    same_sample: bool = False,
    use_bubble_removal: bool = True,
    use_current_electrolyte: bool = False,
    pump_reversal_during_filling: bool = False,
    keep_electrolyte_at_end: bool = False,
    move_to_clean_and_clean: bool = True,
    measure_ref_Pt_at_beginning: bool = True,
    name_ref_Pt_at_beginning: str = "builtin_ref_motorxy_2",
    measure_ref_Pt_at_end: bool = True,
    name_ref_Pt_at_end: str = "builtin_ref_motorxy_3",
    # bubble removal OCV
    bubble_removal_OCV_t_s: int = 10,
    bubble_removal_pump_reverse_t_s: int = 15,
    bubble_removal_pump_forward_t_s: int = 10,
    bubble_removal_RSD_threshold: float = 0.2,
    bubble_removal_simple_threshold: float = 0.3,
    bubble_removal_signal_change_threshold: float = 0.01,
    bubble_removal_amplitude_threshold: float = 0.05,
    # purge wait times
    purge_wait_initialN2_min: int = 10,
    purge_wait_N2_to_O2_min: int = 5,
    purge_wait_O2_to_N2_min: int = 15,
    # electrolyte info
    rinse_with_electrolyte_bf_prefill: bool = True,
    rinse_with_electrolyte_bf_prefill_volume_uL: float = 3000,
    rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec: float = 30,
    rinse_with_electrolyte_bf_prefill_drain_time_sec: float = 30,
    ph: float = 1.24,
    liquid_sample_no: int = 1053,
    liquid_sample_volume_ul: float = 7000,
    Syringe_rate_ulsec: float = 300,
    fill_recirculate_wait_time_sec: float = 30,
    fill_recirculate_reverse_wait_time_sec: float = 15,
    # phosphoric acid injection info
    Inject_PA: bool = True,
    phosphoric_sample_no: int = 1261,
    phosphoric_location: list[int] = [2, 3, 54],
    phosphoric_quantity_ul: int = 90,
    inject_recirculate_wait_time_sec: float = 60,
    # liquid_custom_position: str = "elec_res1",
    # Ref Pt measurement CVs
    ref_CV_cycles: list[int] = [8],
    ref_Vinit_vsRHE: list[float] = [0.05],  # Initial value in volts or amps.
    ref_Vapex1_vsRHE: list[float] = [1.3],  # Apex 1 value in volts or amps.
    ref_Vapex2_vsRHE: list[float] = [0.05],  # Apex 2 value in volts or amps.
    ref_Vfinal_vsRHE: list[float] = [0.05],  # Final value in volts or amps.
    ref_CV_scanrate_voltsec: list[float] = [
        0.1
    ],  # scan rate in volts/second or amps/second.
    ref_CV_samplerate_sec: float = 0.01,
    # cleaning CVs
    cleaning_CV_cycles: list[int] = [20],
    cleaning_Vinit_vsRHE: list[float] = [0.05],  # Initial value in volts or amps.
    cleaning_Vapex1_vsRHE: list[float] = [1.5],  # Apex 1 value in volts or amps.
    cleaning_Vapex2_vsRHE: list[float] = [0.05],  # Apex 2 value in volts or amps.
    cleaning_Vfinal_vsRHE: list[float] = [0.05],  # Final value in volts or amps.
    cleaning_scanrate_voltsec: list[float] = [
        0.2
    ],  # scan rate in volts/second or amps/second.
    cleaning_CV_samplerate_sec: float = 0.02,
    # testing CV info
    testing_CV_scanrate_voltsec: float = 0.1,
    testing_CV_samplerate_sec: float = 0.01,
    # CVs in N2 for background
    CV_N2_cycles: list[int] = [5],
    # CV_N2_Vinit_vsRHE: list[float] = [1.23, 1.23, 1.23],  # Initial value in volts or amps.
    # CV_N2_Vapex1_vsRHE: list[float] = [1.23, 1.23, 1.23],  # Apex 1 value in volts or amps.
    # CV_N2_Vapex2_vsRHE: list[float] = [0.6, 0.4, 0],  # Apex 2 value in volts or amps.
    # CV_N2_Vfinal_vsRHE: list[float] = [0.6, 0.4, 0],  # Final value in volts or amps.
    # CV_N2_scanrate_voltsec: list[float] = [0.02,0.02,0.02],  # scan rate in volts/second or amps/second.
    # CV_N2_samplerate_sec: float = 0.05,
    # CVs in O2 and with and without PA
    CV_O2_cycles: list[int] = [5, 25, 50],
    # CV_O2_Vinit_vsRHE: list[float] = [1.23, 1.23, 1.23],  # Initial value in volts or amps.
    # CV_O2_Vapex1_vsRHE: list[float] = [1.23, 1.23, 1.23],  # Apex 1 value in volts or amps.
    # CV_O2_Vapex2_vsRHE: list[float] = [0.6, 0.4, 0],  # Apex 2 value in volts or amps.
    # CV_O2_Vfinal_vsRHE: list[float] = [0.6, 0.4, 0],  # Final value in volts or amps.
    # CV_O2_scanrate_voltsec: list[float] = [0.02,0.02,0.02],  # scan rate in volts/second or amps/second.
    # CV_O2_samplerate_sec: float = 0.05,
    # OCP info
    OCP_samplerate_sec: float = 0.5,
    # Pstat and ref info
    gamry_i_range: str = "auto",
    ref_type: str = "leakless",
    ref_offset__V: float = -0.005,
    # aliquote info
    aliquot_init: bool = True,
    aliquot_after_cleaningCV: list[int] = [0],
    aliquote_after_CV_init: list[int] = [1],
    aliquote_CV_O2: list[int] = [1, 1, 1],
    aliquote_CV_final: list[int] = [0],
    aliquot_volume_ul: int = 100,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "LS4_peek",
    # cell drain info
    cell_draintime_sec: float = 60,
    ReturnLineReverseWait_sec: float = 5,
    # cell clean info
    number_of_cleans: int = 2,
    clean_volume_ul: float = 12000,
    clean_recirculate_sec: float = 60,
    clean_drain_sec: float = 120,
    # ResidualWait_s: float = 15,
    # flush_volume_ul: float = 2000,
    # clean: bool = False,
    # clean_volume_ul: float = 5000,
    # refill: bool = False,
    # refill_volume_ul: float = 6000,
    # water_refill_volume_ul: float = 6000,
) -> list:
    """TRI Pt-dissolution protocol cycling over (LPL, UPL, sample) triples.

    Features built into the experiment list:

    * Optional reference-Pt measurement at the beginning and end of the
      sequence using ``ADSS_sub_move_to_ref_measurement``.
    * Per-sample workflow: move/load, optional pre-fill electrolyte rinse,
      electrolyte fill, N2 saturation OCV (with optional bubble-removal
      OCV), cleaning CVs, background CVs in N2, gas swap to O2 with OCV,
      testing CVs in O2, phosphoric acid injection, recirculation, more
      testing CVs in O2, gas swap back to N2, final OCV, unload and drain.
    * Optional cleaning cycles between samples with automatic syringe
      refills, scaling the refill volume when cleaning volume exceeds 10 mL.
    * Aliquots scheduled by ``aliquot_after_cleaningCV``,
      ``aliquote_after_CV_init``, ``aliquote_CV_O2``, and ``aliquote_CV_final``.

    Args:
        plate_id: Plate id holding the working-electrode samples.
        plate_id_ref_Pt: Plate id used for the reference Pt sample.
        plate_sample_no_list: Sample numbers paired with LPL/UPL entries.
        LPL_list: Lower potential limits (vs RHE) per sample.
        UPL_list: Upper potential limits (vs RHE) per sample.
        same_sample: Skip the move-to-sample step.
        use_bubble_removal: Enable bubble-removal OCV checks.
        use_current_electrolyte: Reuse previously loaded electrolyte.
        pump_reversal_during_filling: Add a reverse pump leg during fills.
        keep_electrolyte_at_end: Retain electrolyte at the end of the run.
        move_to_clean_and_clean: Run a clean cell step between samples.
        measure_ref_Pt_at_beginning: Run the initial reference Pt block.
        name_ref_Pt_at_beginning: Reference position for the initial block.
        measure_ref_Pt_at_end: Run the final reference Pt block.
        name_ref_Pt_at_end: Reference position for the final block.
        bubble_removal_OCV_t_s: OCV duration during bubble checks (s).
        bubble_removal_pump_reverse_t_s: Reverse pump time during removal (s).
        bubble_removal_pump_forward_t_s: Forward pump time during removal (s).
        bubble_removal_RSD_threshold: RSD threshold for bubble detection.
        bubble_removal_simple_threshold: Simple threshold for bubble detection.
        bubble_removal_signal_change_threshold: Signal-change threshold.
        bubble_removal_amplitude_threshold: Amplitude threshold.
        purge_wait_initialN2_min: Initial N2 purge time (minutes).
        purge_wait_N2_to_O2_min: N2->O2 purge time (minutes).
        purge_wait_O2_to_N2_min: O2->N2 purge time (minutes).
        rinse_with_electrolyte_bf_prefill: Pre-fill rinse with electrolyte.
        rinse_with_electrolyte_bf_prefill_volume_uL: Rinse volume (uL).
        rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec: Rinse
            recirculation duration (s).
        rinse_with_electrolyte_bf_prefill_drain_time_sec: Rinse drain (s).
        ph: Solution pH.
        liquid_sample_no: Reservoir liquid sample number.
        liquid_sample_volume_ul: Cell fill volume (uL).
        Syringe_rate_ulsec: Syringe rate (uL/s).
        fill_recirculate_wait_time_sec: Forward fill recirculation time (s).
        fill_recirculate_reverse_wait_time_sec: Reverse fill recirculation (s).
        Inject_PA: Master switch for phosphoric-acid injection.
        phosphoric_sample_no: PAL sample number for phosphoric acid.
        phosphoric_location: ``[tray, slot, vial]`` of the source vial.
        phosphoric_quantity_ul: Injection volume (uL).
        inject_recirculate_wait_time_sec: Recirculation time post-injection (s).
        ref_CV_cycles: Reference CV cycle counts.
        ref_Vinit_vsRHE: Reference CV initial potentials vs RHE (V).
        ref_Vapex1_vsRHE: Reference CV apex-1 potentials vs RHE (V).
        ref_Vapex2_vsRHE: Reference CV apex-2 potentials vs RHE (V).
        ref_Vfinal_vsRHE: Reference CV final potentials vs RHE (V).
        ref_CV_scanrate_voltsec: Reference CV scan rates (V/s).
        ref_CV_samplerate_sec: Reference CV sample interval (s).
        cleaning_CV_cycles: Cleaning CV cycle counts.
        cleaning_Vinit_vsRHE: Cleaning CV initial potentials vs RHE (V).
        cleaning_Vapex1_vsRHE: Cleaning CV apex-1 potentials vs RHE (V).
        cleaning_Vapex2_vsRHE: Cleaning CV apex-2 potentials vs RHE (V).
        cleaning_Vfinal_vsRHE: Cleaning CV final potentials vs RHE (V).
        cleaning_scanrate_voltsec: Cleaning CV scan rates (V/s).
        cleaning_CV_samplerate_sec: Cleaning CV sample interval (s).
        testing_CV_scanrate_voltsec: Testing CV scan rate (V/s).
        testing_CV_samplerate_sec: Testing CV sample interval (s).
        CV_N2_cycles: Background N2 CV cycle counts.
        CV_O2_cycles: O2 testing CV cycle counts.
        OCP_samplerate_sec: OCV sample interval (s) during purges.
        gamry_i_range: Gamry current range string.
        ref_type: Reference electrode type label.
        ref_offset__V: Reference electrode offset (V).
        aliquot_init: Take an initial aliquot.
        aliquot_after_cleaningCV: Per-cleaning-CV aliquot flags.
        aliquote_after_CV_init: Per-background-CV aliquot flags.
        aliquote_CV_O2: Per-O2-CV aliquot flags.
        aliquote_CV_final: Final CV aliquot flags.
        aliquot_volume_ul: Aliquot volume (uL).
        PAL_Injector: PAL injector key.
        PAL_Injector_id: PAL injector identifier.
        cell_draintime_sec: Drain duration (s).
        ReturnLineReverseWait_sec: Reverse return-line wait (s).
        number_of_cleans: Number of clean cycles per cleaning pass.
        clean_volume_ul: Cleaning volume (uL).
        clean_recirculate_sec: Cleaning recirculation duration (s).
        clean_drain_sec: Cleaning drain duration (s).

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    ###################################################################
    # REF MEASUREMENT AT BEGINNING OF SEQUENCE
    ###################################################################

    # ref measurement at beginning of sequence
    if measure_ref_Pt_at_beginning:
        epm.add(
            "ADSS_sub_move_to_ref_measurement",
            {"reference_position_name": name_ref_Pt_at_beginning},
        )

        epm.add(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id_ref_Pt,
                "solid_sample_no": 1,  ################### can i use the sample id for all ref measurements?
                "previous_liquid": use_current_electrolyte,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )

        # rinse with electrolyte to remove cleaning liquid residuals
        if rinse_with_electrolyte_bf_prefill:
            epm.add(
                "ADSS_sub_cellfill_prefilled",
                {
                    "Solution_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                },
            )
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec,
                },
            )
            epm.add(
                "ADSS_sub_drain_cell",
                {
                    "DrainWait_s": rinse_with_electrolyte_bf_prefill_drain_time_sec,
                    "ReturnLineReverseWait_s": 5,
                    #    "ResidualWait_s": ResidualWait_s,
                },
            )
            epm.add(
                "ADSS_sub_refill_syringe",
                {
                    "syringe": "electrolyte",
                    "fill_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                },
            )

        # electrolyte filling for experiment
        epm.add(
            "ADSS_sub_cellfill_prefilled",
            {
                "Solution_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            },
        )

        # set initial gas to N2
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": True,
            },
        )

        # pump recirculate forward
        epm.add(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "forward",
                "wait_time_s": fill_recirculate_wait_time_sec,
            },
        )

        # pump recirculate reverse (for bubbles)
        if pump_reversal_during_filling:
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "reverse",
                    "wait_time_s": fill_recirculate_reverse_wait_time_sec,
                },
            )

            # pump recirculate forward
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": 5,
                },
            )

        # refill electrolyte syringe here so that ADSS can recirculate and N2 saturate while filling syringe
        if not use_current_electrolyte:
            epm.add(
                "ADSS_sub_refill_syringe",
                {
                    "syringe": "electrolyte",
                    "fill_volume_ul": liquid_sample_volume_ul,
                    "Syringe_rate_ulsec": 300,
                },
            )

        # check for bubbles that could interfere with echem measurments with OCV
        if use_bubble_removal:
            epm.add(
                "ADSS_sub_OCV",
                {
                    "check_bubble": True,
                    "Tval__s": bubble_removal_OCV_t_s,
                    "samplerate_sec": 0.1,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "run_use": "ref",
                    "RSD_threshold": bubble_removal_RSD_threshold,
                    "simple_threshold": bubble_removal_simple_threshold,
                    "signal_change_threshold": bubble_removal_signal_change_threshold,
                    "amplitude_threshold": bubble_removal_amplitude_threshold,
                    "bubble_pump_reverse_time_s": bubble_removal_pump_reverse_t_s,
                    "bubble_pump_forward_time_s": bubble_removal_pump_forward_t_s,
                },
            )

        # saturate electrolyte with N2 and measure OCV while saturation
        epm.add(
            "ADSS_sub_OCV",
            {
                "Tval__s": purge_wait_initialN2_min * 60,
                "samplerate_sec": OCP_samplerate_sec,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
                "run_use": "ref",
            },
        )

        # epm.add(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_initialN2_min * 60,
        #     }
        # )

        # start cleaning CVs in N2
        for i, CV_cycle in enumerate(cleaning_CV_cycles):
            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": cleaning_Vinit_vsRHE[i],
                    "Vapex1_vsRHE": cleaning_Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": cleaning_Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": cleaning_Vfinal_vsRHE[i],
                    "scanrate_voltsec": cleaning_scanrate_voltsec[i],
                    "SampleRate": cleaning_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "run_use": "ref",
                },
            )

        # start background CVs in N2
        for i, CV_cycle in enumerate(ref_CV_cycles):
            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": ref_Vinit_vsRHE,
                    "Vapex1_vsRHE": ref_Vapex1_vsRHE,
                    "Vapex2_vsRHE": ref_Vapex2_vsRHE,
                    "Vfinal_vsRHE": ref_Vfinal_vsRHE,
                    "scanrate_voltsec": ref_CV_scanrate_voltsec,
                    "SampleRate": ref_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "run_use": "ref",
                },
            )

        # switch from N2 to O2 and saturate
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": False,
            },
        )
        epm.add(
            "ADSS_sub_OCV",
            {
                "Tval__s": purge_wait_N2_to_O2_min * 60,
                "samplerate_sec": OCP_samplerate_sec,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
                "run_use": "ref",
            },
        )
        #        epm.add(
        #            "orch_sub_wait",
        #            {
        #                "wait_time_s": purge_wait_N2_to_O2_min * 60,
        #            }
        #        )

        # start O2 cycles
        for i, CV_cycle in enumerate(ref_CV_cycles):
            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": ref_Vinit_vsRHE,
                    "Vapex1_vsRHE": ref_Vapex1_vsRHE,
                    "Vapex2_vsRHE": ref_Vapex2_vsRHE,
                    "Vfinal_vsRHE": ref_Vfinal_vsRHE,
                    "scanrate_voltsec": ref_CV_scanrate_voltsec,
                    "SampleRate": ref_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "run_use": "ref",
                },
            )

        # switch from O2 to N2 and saturate
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": True,
            },
        )

        # unload sample
        epm.add("ADSS_sub_unloadall_customs", {})

        # drain cell
        epm.add(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": cell_draintime_sec,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_sec,
                #    "ResidualWait_s": ResidualWait_s,
            },
        )

        # clean cell
        if move_to_clean_and_clean:
            epm.add("ADSS_sub_move_to_clean_cell", {})
            for i in range(number_of_cleans):
                epm.add(
                    "ADSS_sub_clean_cell",
                    {
                        "Clean_volume_ul": clean_volume_ul,
                        "ReturnLineWait_s": clean_recirculate_sec,
                        "DrainWait_s": clean_drain_sec,
                    },
                )
                # if working with more than 10mL cleaning V, then by default a precleaning with 6mL is done. This would also be needed to refill
                if clean_volume_ul > 10000:
                    volume = 6000 + clean_volume_ul
                else:
                    volume = clean_volume_ul

                epm.add(
                    "ADSS_sub_refill_syringe",
                    {
                        "syringe": "waterclean",
                        "fill_volume_ul": volume,
                        "Syringe_rate_ulsec": 300,
                    },
                )

    ###################################################################
    # SEQUENCE FOR ACTUAL SAMPLE
    ###################################################################

    # for solid_sample_no in plate_sample_no_list:  # have to indent add expts if used
    for lpl, upl, sample_no in zip(LPL_list, UPL_list, plate_sample_no_list):
        print(
            "##########################################################\n"
            + "Current LPL is {} Vrhe\n".format(lpl)
            + "Current UPL is {} Vrhe\n".format(upl)
            + "Current Sample is {}\n".format(sample_no)
            + "##########################################################"
        )

        if not same_sample:

            epm.add(
                "ADSS_sub_move_to_sample",
                {
                    "solid_custom_position": "cell1_we",
                    "solid_plate_id": plate_id,
                    "solid_sample_no": sample_no,
                    "liquid_custom_position": "cell1_we",
                    "liquid_sample_no": liquid_sample_no,
                    "liquid_sample_volume_ul": liquid_sample_volume_ul,
                },
            )

        epm.add(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": sample_no,
                "previous_liquid": use_current_electrolyte,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )

        # rinse with electrolyte to remove cleaning liquid residuals
        if rinse_with_electrolyte_bf_prefill:
            epm.add(
                "ADSS_sub_cellfill_prefilled",
                {
                    "Solution_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                },
            )
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec,
                },
            )
            epm.add(
                "ADSS_sub_drain_cell",
                {
                    "DrainWait_s": rinse_with_electrolyte_bf_prefill_drain_time_sec,
                    "ReturnLineReverseWait_s": 5,
                    #    "ResidualWait_s": ResidualWait_s,
                },
            )
            epm.add(
                "ADSS_sub_refill_syringe",
                {
                    "syringe": "electrolyte",
                    "fill_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                },
            )

        # electrolyte filling for experiment
        if not use_current_electrolyte:
            epm.add(
                "ADSS_sub_cellfill_prefilled",
                {
                    "Solution_volume_ul": liquid_sample_volume_ul,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                },
            )

        # set initial gas to N2
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": True,
            },
        )

        # pump recirculate forward
        epm.add(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "forward",
                "wait_time_s": fill_recirculate_wait_time_sec,
            },
        )

        # pump recirculate reverse (for bubbles)
        if pump_reversal_during_filling:
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "reverse",
                    "wait_time_s": fill_recirculate_reverse_wait_time_sec,
                },
            )

            # pump recirculate forward
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": 5,
                },
            )

        # refill electrolyte syringe here so that ADSS can recirculate and N2 saturate while filling syringe
        if not use_current_electrolyte:
            epm.add(
                "ADSS_sub_refill_syringe",
                {
                    "syringe": "electrolyte",
                    "fill_volume_ul": liquid_sample_volume_ul,
                    "Syringe_rate_ulsec": 300,
                },
            )

        washmod = 0

        if aliquot_init:  # stops gas purge, takes aliquote, starts gas purge again

            washmod += 1
            washone = washmod % 4 % 3 % 2
            washtwo = (washmod + 1) % 4 % 3 % 2
            washthree = (washmod + 2) % 4 % 3 % 2
            washfour = (washmod + 3) % 4 % 3 % 2

            epm.add(
                "ADSS_sub_sample_aliquot",
                {
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "EquilibrationTime_s": 0,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": washone,
                    "rinse_2": washtwo,
                    "rinse_3": washthree,
                    "rinse_4": washfour,
                },
            )

        # check for bubbles that could interfere with echem measurments with OCV
        if use_bubble_removal:
            epm.add(
                "ADSS_sub_OCV",
                {
                    "check_bubble": True,
                    "Tval__s": bubble_removal_OCV_t_s,
                    "samplerate_sec": 0.1,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "RSD_threshold": bubble_removal_RSD_threshold,
                    "simple_threshold": bubble_removal_simple_threshold,
                    "signal_change_threshold": bubble_removal_signal_change_threshold,
                    "amplitude_threshold": bubble_removal_amplitude_threshold,
                    "bubble_pump_reverse_time_s": bubble_removal_pump_reverse_t_s,
                    "bubble_pump_forward_time_s": bubble_removal_pump_forward_t_s,
                },
            )

        # saturate electrolyte with N2
        epm.add(
            "ADSS_sub_OCV",
            {
                "Tval__s": purge_wait_initialN2_min * 60,
                "samplerate_sec": OCP_samplerate_sec,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
            },
        )

        # epm.add(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_initialN2_min * 60,
        #     }
        # )

        # start cleaning CVs in N2
        for i, CV_cycle in enumerate(cleaning_CV_cycles):
            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": cleaning_Vinit_vsRHE[i],
                    "Vapex1_vsRHE": cleaning_Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": cleaning_Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": cleaning_Vfinal_vsRHE[i],
                    "scanrate_voltsec": cleaning_scanrate_voltsec[i],
                    "SampleRate": cleaning_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                },
            )
            if aliquot_after_cleaningCV[i] == 1:

                washmod += 1
                washone = washmod % 4 % 3 % 2
                washtwo = (washmod + 1) % 4 % 3 % 2
                washthree = (washmod + 2) % 4 % 3 % 2
                washfour = (washmod + 3) % 4 % 3 % 2

                epm.add(
                    "ADSS_sub_sample_aliquot",
                    {
                        "aliquot_volume_ul": aliquot_volume_ul,
                        "EquilibrationTime_s": 0,
                        "PAL_Injector": PAL_Injector,
                        "PAL_Injector_id": PAL_Injector_id,
                        "rinse_1": washone,
                        "rinse_2": washtwo,
                        "rinse_3": washthree,
                        "rinse_4": washfour,
                    },
                )

        # start background CVs in N2
        for i, CV_cycle in enumerate(CV_N2_cycles):
            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": lpl,
                    "Vapex1_vsRHE": upl,
                    "Vapex2_vsRHE": lpl,
                    "Vfinal_vsRHE": lpl,
                    "scanrate_voltsec": testing_CV_scanrate_voltsec,
                    "SampleRate": testing_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                },
            )
            if aliquote_after_CV_init[i] == 1:

                washmod += 1
                washone = washmod % 4 % 3 % 2
                washtwo = (washmod + 1) % 4 % 3 % 2
                washthree = (washmod + 2) % 4 % 3 % 2
                washfour = (washmod + 3) % 4 % 3 % 2

                epm.add(
                    "ADSS_sub_sample_aliquot",
                    {
                        "aliquot_volume_ul": aliquot_volume_ul,
                        "EquilibrationTime_s": 0,
                        "PAL_Injector": PAL_Injector,
                        "PAL_Injector_id": PAL_Injector_id,
                        "rinse_1": washone,
                        "rinse_2": washtwo,
                        "rinse_3": washthree,
                        "rinse_4": washfour,
                    },
                )

        # switch from N2 to O2 and saturate
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": False,
            },
        )
        epm.add(
            "ADSS_sub_OCV",
            {
                "Tval__s": purge_wait_N2_to_O2_min * 60,
                "samplerate_sec": OCP_samplerate_sec,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
            },
        )

        # epm.add(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_N2_to_O2_min * 60,
        #     }
        # )

        # start O2 cycles
        for i, CV_cycle in enumerate(CV_O2_cycles):

            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": lpl,
                    "Vapex1_vsRHE": upl,
                    "Vapex2_vsRHE": lpl,
                    "Vfinal_vsRHE": lpl,
                    "scanrate_voltsec": testing_CV_scanrate_voltsec,
                    "SampleRate": testing_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                },
            )
            if aliquote_CV_O2[i] == 1:

                washmod += 1
                washone = washmod % 4 % 3 % 2
                washtwo = (washmod + 1) % 4 % 3 % 2
                washthree = (washmod + 2) % 4 % 3 % 2
                washfour = (washmod + 3) % 4 % 3 % 2

                epm.add(
                    "ADSS_sub_sample_aliquot",
                    {
                        "aliquot_volume_ul": aliquot_volume_ul,
                        "EquilibrationTime_s": 0,
                        "PAL_Injector": PAL_Injector,
                        "PAL_Injector_id": PAL_Injector_id,
                        "rinse_1": washone,
                        "rinse_2": washtwo,
                        "rinse_3": washthree,
                        "rinse_4": washfour,
                    },
                )

        # inject phosphoric acid
        if Inject_PA:
            washmod += 1
            washone = washmod % 4 % 3 % 2
            washtwo = (washmod + 1) % 4 % 3 % 2
            washthree = (washmod + 2) % 4 % 3 % 2
            washfour = (washmod + 3) % 4 % 3 % 2

            epm.add(
                "ADSS_sub_transfer_liquid_in",
                {
                    "destination": "cell1_we",
                    "source_tray": phosphoric_location[0],
                    "source_slot": phosphoric_location[1],
                    "source_vial": phosphoric_location[2],
                    "liquid_sample_no": phosphoric_sample_no,
                    "aliquot_volume_ul": phosphoric_quantity_ul,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": washone,
                    "rinse_2": washtwo,
                    "rinse_3": washthree,
                    "rinse_4": washfour,
                },
            )

            # recirculate to mix PA into electrolyte
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": inject_recirculate_wait_time_sec,
                },
            )

        # start O2 cycles with PA
        for i, CV_cycle in enumerate(CV_O2_cycles):

            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": lpl,
                    "Vapex1_vsRHE": upl,
                    "Vapex2_vsRHE": lpl,
                    "Vfinal_vsRHE": lpl,
                    "scanrate_voltsec": testing_CV_scanrate_voltsec,
                    "SampleRate": testing_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                },
            )

            if aliquote_CV_O2[i] == 1:

                washmod += 1
                washone = washmod % 4 % 3 % 2
                washtwo = (washmod + 1) % 4 % 3 % 2
                washthree = (washmod + 2) % 4 % 3 % 2
                washfour = (washmod + 3) % 4 % 3 % 2

                epm.add(
                    "ADSS_sub_sample_aliquot",
                    {
                        "aliquot_volume_ul": aliquot_volume_ul,
                        "EquilibrationTime_s": 0,
                        "PAL_Injector": PAL_Injector,
                        "PAL_Injector_id": PAL_Injector_id,
                        "rinse_1": washone,
                        "rinse_2": washtwo,
                        "rinse_3": washthree,
                        "rinse_4": washfour,
                    },
                )

        # switch from O2 to N2 and saturate
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": True,
            },
        )
        # measure OCP (default of OCV exp is to not take any aliquots)
        epm.add(
            "ADSS_sub_OCV",
            {
                "Tval__s": purge_wait_O2_to_N2_min * 60,
                "samplerate_sec": OCP_samplerate_sec,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
            },
        )

        # epm.add(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_O2_to_N2_m * 60,
        #     }
        # )

        # start background CVs in N2 with phosphoric acid
        for i, CV_cycle in enumerate(CV_N2_cycles):
            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": lpl,
                    "Vapex1_vsRHE": upl,
                    "Vapex2_vsRHE": lpl,
                    "Vfinal_vsRHE": lpl,
                    "scanrate_voltsec": testing_CV_scanrate_voltsec,
                    "SampleRate": testing_CV_scanrate_voltsec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                },
            )

            if aliquote_CV_final[i] == 1:

                washmod += 1
                washone = washmod % 4 % 3 % 2
                washtwo = (washmod + 1) % 4 % 3 % 2
                washthree = (washmod + 2) % 4 % 3 % 2
                washfour = (washmod + 3) % 4 % 3 % 2

                epm.add(
                    "ADSS_sub_sample_aliquot",
                    {
                        "aliquot_volume_ul": aliquot_volume_ul,
                        "EquilibrationTime_s": 0,
                        "PAL_Injector": PAL_Injector,
                        "PAL_Injector_id": PAL_Injector_id,
                        "rinse_1": washone,
                        "rinse_2": washtwo,
                        "rinse_3": washthree,
                        "rinse_4": washfour,
                    },
                )

        if keep_electrolyte_at_end:
            epm.add("ADSS_sub_unload_solid", {})

        else:

            epm.add("ADSS_sub_unloadall_customs", {})
            epm.add(
                "ADSS_sub_drain_cell",
                {
                    "DrainWait_s": cell_draintime_sec,
                    "ReturnLineReverseWait_s": ReturnLineReverseWait_sec,
                    #    "ResidualWait_s": ResidualWait_s,
                },
            )

        if move_to_clean_and_clean:
            epm.add("ADSS_sub_move_to_clean_cell", {})
            for i in range(number_of_cleans):
                epm.add(
                    "ADSS_sub_clean_cell",
                    {
                        "Clean_volume_ul": clean_volume_ul,
                        "ReturnLineWait_s": clean_recirculate_sec,
                        "DrainWait_s": clean_drain_sec,
                    },
                )
                # if working with more than 10mL cleaning V, then by default a precleaning with 6mL is done. This would also be needed to refill
                if clean_volume_ul > 10000:
                    volume = 6000 + clean_volume_ul
                else:
                    volume = clean_volume_ul

                epm.add(
                    "ADSS_sub_refill_syringe",
                    {
                        "syringe": "waterclean",
                        "fill_volume_ul": volume,
                        "Syringe_rate_ulsec": 300,
                    },
                )

    ###################################################################
    # REF MEASUREMENT AT END OF SEQUENCE
    ###################################################################

    # ref measurement at end of sequence
    if measure_ref_Pt_at_end:
        epm.add(
            "ADSS_sub_move_to_ref_measurement",
            {
                "reference_position_name": name_ref_Pt_at_end,
            },
        )

        epm.add(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id_ref_Pt,
                "solid_sample_no": 1,  ################### can i use the sample id for all ref measurements?
                "previous_liquid": use_current_electrolyte,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )

        # rinse with electrolyte to remove cleaning liquid residuals
        if rinse_with_electrolyte_bf_prefill:
            epm.add(
                "ADSS_sub_cellfill_prefilled",
                {
                    "Solution_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                },
            )
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec,
                },
            )
            epm.add(
                "ADSS_sub_drain_cell",
                {
                    "DrainWait_s": rinse_with_electrolyte_bf_prefill_drain_time_sec,
                    "ReturnLineReverseWait_s": 5,
                    #    "ResidualWait_s": ResidualWait_s,
                },
            )
            epm.add(
                "ADSS_sub_refill_syringe",
                {
                    "syringe": "electrolyte",
                    "fill_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                },
            )

        # electrolyte filling for experiment
        epm.add(
            "ADSS_sub_cellfill_prefilled",
            {
                "Solution_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            },
        )

        # set initial gas to N2
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": True,
            },
        )

        # pump recirculate forward
        epm.add(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "forward",
                "wait_time_s": fill_recirculate_wait_time_sec,
            },
        )

        # pump recirculate reverse (for bubbles)
        if pump_reversal_during_filling:
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "reverse",
                    "wait_time_s": fill_recirculate_reverse_wait_time_sec,
                },
            )

            # pump recirculate forward
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": 5,
                },
            )

        # refill electrolyte syringe here so that ADSS can recirculate and N2 saturate while filling syringe
        if not use_current_electrolyte:
            epm.add(
                "ADSS_sub_refill_syringe",
                {
                    "syringe": "electrolyte",
                    "fill_volume_ul": liquid_sample_volume_ul,
                    "Syringe_rate_ulsec": 300,
                },
            )

        # check for bubbles that could interfere with echem measurments with OCV
        if use_bubble_removal:
            epm.add(
                "ADSS_sub_OCV",
                {
                    "check_bubble": True,
                    "Tval__s": bubble_removal_OCV_t_s,
                    "samplerate_sec": 0.1,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "run_use": "ref",
                    "RSD_threshold": bubble_removal_RSD_threshold,
                    "simple_threshold": bubble_removal_simple_threshold,
                    "signal_change_threshold": bubble_removal_signal_change_threshold,
                    "amplitude_threshold": bubble_removal_amplitude_threshold,
                    "bubble_pump_reverse_time_s": bubble_removal_pump_reverse_t_s,
                    "bubble_pump_forward_time_s": bubble_removal_pump_forward_t_s,
                },
            )

        # saturate electrolyte with N2
        epm.add(
            "ADSS_sub_OCV",
            {
                "Tval__s": purge_wait_initialN2_min * 60,
                "samplerate_sec": OCP_samplerate_sec,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
                "run_use": "ref",
            },
        )

        # epm.add(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_initialN2_min * 60,
        #     }
        # )

        # start cleaning CVs in N2
        for i, CV_cycle in enumerate(cleaning_CV_cycles):
            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": cleaning_Vinit_vsRHE[i],
                    "Vapex1_vsRHE": cleaning_Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": cleaning_Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": cleaning_Vfinal_vsRHE[i],
                    "scanrate_voltsec": cleaning_scanrate_voltsec[i],
                    "SampleRate": cleaning_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "run_use": "ref",
                },
            )

        # start background CVs in N2
        for i, CV_cycle in enumerate(ref_CV_cycles):
            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": ref_Vinit_vsRHE,
                    "Vapex1_vsRHE": ref_Vapex1_vsRHE,
                    "Vapex2_vsRHE": ref_Vapex2_vsRHE,
                    "Vfinal_vsRHE": ref_Vfinal_vsRHE,
                    "scanrate_voltsec": ref_CV_scanrate_voltsec,
                    "SampleRate": ref_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "run_use": "ref",
                },
            )

        # switch from N2 to O2 and saturate
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": False,
            },
        )
        epm.add(
            "ADSS_sub_OCV",
            {
                "Tval__s": purge_wait_N2_to_O2_min * 60,
                "samplerate_sec": OCP_samplerate_sec,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
                "run_use": "ref",
            },
        )
        #        epm.add(
        #            "orch_sub_wait",
        #            {
        #                "wait_time_s": purge_wait_N2_to_O2_min * 60,
        #            }
        #        )

        # start O2 cycles
        for i, CV_cycle in enumerate(ref_CV_cycles):
            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": ref_Vinit_vsRHE,
                    "Vapex1_vsRHE": ref_Vapex1_vsRHE,
                    "Vapex2_vsRHE": ref_Vapex2_vsRHE,
                    "Vfinal_vsRHE": ref_Vfinal_vsRHE,
                    "scanrate_voltsec": ref_CV_scanrate_voltsec,
                    "SampleRate": ref_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "run_use": "ref",
                },
            )

        # switch from O2 to N2 and saturate
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": True,
            },
        )

        # unload sample
        epm.add("ADSS_sub_unloadall_customs", {})

        # drain cell
        epm.add(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": cell_draintime_sec,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_sec,
                #    "ResidualWait_s": ResidualWait_s,
            },
        )

        # clean cell
        if move_to_clean_and_clean:
            epm.add("ADSS_sub_move_to_clean_cell", {})
            for i in range(number_of_cleans):
                epm.add(
                    "ADSS_sub_clean_cell",
                    {
                        "Clean_volume_ul": clean_volume_ul,
                        "ReturnLineWait_s": clean_recirculate_sec,
                        "DrainWait_s": clean_drain_sec,
                    },
                )
                # if working with more than 10mL cleaning V, then by default a precleaning with 6mL is done. This would also be needed to refill
                if clean_volume_ul > 10000:
                    volume = 6000 + clean_volume_ul
                else:
                    volume = clean_volume_ul

                epm.add(
                    "ADSS_sub_refill_syringe",
                    {
                        "syringe": "waterclean",
                        "fill_volume_ul": volume,
                        "Syringe_rate_ulsec": 300,
                    },
                )

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=8)
def ADSS_PA_CV_TRI_new(
    # note: str = "need as many samples as you expect combinations of UPL and LPL",
    # sample info
    # solid_custom_position: str = "cell1_we",
    plate_id: int = 6307,
    plate_id_ref_Pt: int = 6173,
    plate_sample_no_list: list[int] = [
        16304
    ],  #  need as many samples as you expect combinations of UPL and LPL
    LPL_list: list[float] = [
        0.05,
        0.55,
        0.05,
        0.55,
    ],
    UPL_list: list[float] = [
        1.3,
        0.8,
        1.3,
        0.8,
    ],
    # side info
    same_sample: bool = False,
    aliquot_init: bool = True,
    Inject_PA: bool = True,
    use_bubble_removal: bool = True,
    rinse_with_electrolyte_bf_prefill: bool = True,
    use_current_electrolyte: bool = False,
    pump_reversal_during_filling: bool = False,
    keep_electrolyte_at_end: bool = False,
    move_to_clean_and_clean: bool = True,
    measure_ref_Pt_at_beginning: bool = True,
    name_ref_Pt_at_beginning: str = "builtin_ref_motorxy_2",
    measure_ref_Pt_at_end: bool = True,
    name_ref_Pt_at_end: str = "builtin_ref_motorxy_3",
    # bubble removal OCV
    bubble_removal_OCV_t_s: int = 10,
    bubble_removal_pump_reverse_t_s: int = 15,
    bubble_removal_pump_forward_t_s: int = 10,
    bubble_removal_RSD_threshold: float = 0.2,
    bubble_removal_simple_threshold: float = 0.3,
    bubble_removal_signal_change_threshold: float = 0.01,
    bubble_removal_amplitude_threshold: float = 0.05,
    # purge wait times
    purge_wait_initialN2_min: int = 10,
    purge_wait_N2_to_O2_min: int = 5,
    purge_wait_O2_to_N2_min: int = 15,
    # electrolyte info
    rinse_with_electrolyte_bf_prefill_volume_uL: float = 3000,
    rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec: float = 30,
    rinse_with_electrolyte_bf_prefill_drain_time_sec: float = 30,
    ph: float = 1.24,
    liquid_sample_no: int = 1053,
    liquid_sample_volume_ul: float = 7000,
    Syringe_rate_ulsec: float = 300,
    fill_recirculate_wait_time_sec: float = 30,
    fill_recirculate_reverse_wait_time_sec: float = 15,
    # phosphoric acid injection info
    phosphoric_sample_no: int = 1261,
    phosphoric_location: list[int] = [2, 3, 54],
    phosphoric_quantity_ul: int = 90,
    inject_recirculate_wait_time_sec: float = 60,
    # liquid_custom_position: str = "elec_res1",
    phos_PAL_Injector: str = "LS 5",
    phos_PAL_Injector_id: str = "LS5_peek",
    PAL_cleanvol_ul: int = 500,
    # Ref Pt measurement CVs
    ref_CV_cycles: list[int] = [8],
    ref_Vinit_vsRHE: list[float] = [0.05],  # Initial value in volts or amps.
    ref_Vapex1_vsRHE: list[float] = [1.3],  # Apex 1 value in volts or amps.
    ref_Vapex2_vsRHE: list[float] = [0.05],  # Apex 2 value in volts or amps.
    ref_Vfinal_vsRHE: list[float] = [0.05],  # Final value in volts or amps.
    ref_CV_scanrate_voltsec: list[float] = [
        0.1
    ],  # scan rate in volts/second or amps/second.
    ref_CV_samplerate_sec: float = 0.01,
    # cleaning CVs
    cleaning_CV_cycles: list[int] = [20],
    cleaning_Vinit_vsRHE: list[float] = [0.05],  # Initial value in volts or amps.
    cleaning_Vapex1_vsRHE: list[float] = [1.5],  # Apex 1 value in volts or amps.
    cleaning_Vapex2_vsRHE: list[float] = [0.05],  # Apex 2 value in volts or amps.
    cleaning_Vfinal_vsRHE: list[float] = [0.05],  # Final value in volts or amps.
    cleaning_scanrate_voltsec: list[float] = [
        0.2
    ],  # scan rate in volts/second or amps/second.
    cleaning_CV_samplerate_sec: float = 0.02,
    # testing CV info
    testing_CV_scanrate_voltsec: float = 0.1,
    testing_CV_samplerate_sec: float = 0.01,
    # CVs in N2 for background
    CV_N2_cycles: list[int] = [5],
    # CV_N2_Vinit_vsRHE: list[float] = [1.23, 1.23, 1.23],  # Initial value in volts or amps.
    # CV_N2_Vapex1_vsRHE: list[float] = [1.23, 1.23, 1.23],  # Apex 1 value in volts or amps.
    # CV_N2_Vapex2_vsRHE: list[float] = [0.6, 0.4, 0],  # Apex 2 value in volts or amps.
    # CV_N2_Vfinal_vsRHE: list[float] = [0.6, 0.4, 0],  # Final value in volts or amps.
    # CV_N2_scanrate_voltsec: list[float] = [0.02,0.02,0.02],  # scan rate in volts/second or amps/second.
    # CV_N2_samplerate_sec: float = 0.05,
    # CVs in O2 and with and without PA
    CV_O2_cycles: list[int] = [5, 25, 50],
    # CV_O2_Vinit_vsRHE: list[float] = [1.23, 1.23, 1.23],  # Initial value in volts or amps.
    # CV_O2_Vapex1_vsRHE: list[float] = [1.23, 1.23, 1.23],  # Apex 1 value in volts or amps.
    # CV_O2_Vapex2_vsRHE: list[float] = [0.6, 0.4, 0],  # Apex 2 value in volts or amps.
    # CV_O2_Vfinal_vsRHE: list[float] = [0.6, 0.4, 0],  # Final value in volts or amps.
    # CV_O2_scanrate_voltsec: list[float] = [0.02,0.02,0.02],  # scan rate in volts/second or amps/second.
    # CV_O2_samplerate_sec: float = 0.05,
    # OCP info
    OCP_samplerate_sec: float = 0.5,
    # Pstat and ref info
    gamry_i_range: str = "auto",
    ref_type: str = "leakless",
    ref_offset__V: float = -0.005,
    # aliquote info
    aliquot_after_cleaningCV: list[int] = [0],
    aliquote_after_CV_init: list[int] = [1],
    aliquote_CV_O2: list[int] = [1, 1, 1],
    aliquote_CV_final: list[int] = [0],
    aliquot_volume_ul: int = 100,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "LS4_peek",
    # cell drain info
    cell_draintime_sec: float = 60,
    ReturnLineReverseWait_sec: float = 5,
    # cell clean info
    number_of_cleans: int = 2,
    clean_volume_ul: float = 12000,
    clean_recirculate_sec: float = 60,
    clean_drain_sec: float = 120,
    # ResidualWait_s: float = 15,
    # flush_volume_ul: float = 2000,
    # clean: bool = False,
    # clean_volume_ul: float = 5000,
    # refill: bool = False,
    # refill_volume_ul: float = 6000,
    # water_refill_volume_ul: float = 6000,
) -> list:
    """Updated TRI Pt-dissolution protocol with a separate phosphoric injector.

    Same overall structure as :func:`ADSS_PA_CV_TRI` (reference Pt blocks,
    per-sample fill/clean/CV/CA loops with N2<->O2 saturation, scheduled
    aliquots, and optional cleaning between samples) with:

    * Aliquots and phosphoric injection moved into the experiment library so
      the orchestrator records them as their own actions.
    * A dedicated phosphoric PAL injector configured via ``phos_PAL_Injector``
      and ``phos_PAL_Injector_id``, plus a deep-clean cleaning volume
      ``PAL_cleanvol_ul``.
    * Optional flags ``aliquot_init``, ``Inject_PA``, ``use_bubble_removal``,
      ``rinse_with_electrolyte_bf_prefill`` to toggle sub-blocks.

    Args:
        plate_id: Plate id holding working-electrode samples.
        plate_id_ref_Pt: Plate id used for reference Pt samples.
        plate_sample_no_list: Sample numbers paired with LPL/UPL entries.
        LPL_list: Lower potential limits (vs RHE) per sample.
        UPL_list: Upper potential limits (vs RHE) per sample.
        same_sample: Skip move-to-sample.
        aliquot_init: Take an initial aliquot.
        Inject_PA: Master switch for phosphoric injection.
        use_bubble_removal: Enable bubble-removal OCV checks.
        rinse_with_electrolyte_bf_prefill: Pre-fill electrolyte rinse.
        use_current_electrolyte: Reuse previously loaded electrolyte.
        pump_reversal_during_filling: Add reverse pump leg during fills.
        keep_electrolyte_at_end: Retain electrolyte at end of run.
        move_to_clean_and_clean: Run a clean cell step between samples.
        measure_ref_Pt_at_beginning: Run the initial reference block.
        name_ref_Pt_at_beginning: Reference position name (initial).
        measure_ref_Pt_at_end: Run the final reference block.
        name_ref_Pt_at_end: Reference position name (final).
        bubble_removal_OCV_t_s: OCV duration during bubble checks (s).
        bubble_removal_pump_reverse_t_s: Reverse pump time (s).
        bubble_removal_pump_forward_t_s: Forward pump time (s).
        bubble_removal_RSD_threshold: RSD threshold.
        bubble_removal_simple_threshold: Simple threshold.
        bubble_removal_signal_change_threshold: Signal-change threshold.
        bubble_removal_amplitude_threshold: Amplitude threshold.
        purge_wait_initialN2_min: Initial N2 purge time (minutes).
        purge_wait_N2_to_O2_min: N2->O2 purge time (minutes).
        purge_wait_O2_to_N2_min: O2->N2 purge time (minutes).
        rinse_with_electrolyte_bf_prefill_volume_uL: Rinse volume (uL).
        rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec: Rinse
            recirculation duration (s).
        rinse_with_electrolyte_bf_prefill_drain_time_sec: Rinse drain (s).
        ph: Solution pH.
        liquid_sample_no: Reservoir liquid sample number.
        liquid_sample_volume_ul: Cell fill volume (uL).
        Syringe_rate_ulsec: Syringe rate (uL/s).
        fill_recirculate_wait_time_sec: Forward fill recirculation (s).
        fill_recirculate_reverse_wait_time_sec: Reverse fill recirculation (s).
        phosphoric_sample_no: PAL sample number for phosphoric acid.
        phosphoric_location: ``[tray, slot, vial]`` for phosphoric source.
        phosphoric_quantity_ul: Phosphoric injection volume (uL).
        inject_recirculate_wait_time_sec: Recirculation time post-injection (s).
        phos_PAL_Injector: PAL injector key for phosphoric.
        phos_PAL_Injector_id: PAL injector identifier for phosphoric.
        PAL_cleanvol_ul: PAL deep-clean volume (uL).
        ref_CV_cycles: Reference CV cycle counts.
        ref_Vinit_vsRHE: Reference CV initial potentials vs RHE (V).
        ref_Vapex1_vsRHE: Reference CV apex-1 potentials vs RHE (V).
        ref_Vapex2_vsRHE: Reference CV apex-2 potentials vs RHE (V).
        ref_Vfinal_vsRHE: Reference CV final potentials vs RHE (V).
        ref_CV_scanrate_voltsec: Reference CV scan rates (V/s).
        ref_CV_samplerate_sec: Reference CV sample interval (s).
        cleaning_CV_cycles: Cleaning CV cycle counts.
        cleaning_Vinit_vsRHE: Cleaning CV initial potentials vs RHE (V).
        cleaning_Vapex1_vsRHE: Cleaning CV apex-1 potentials vs RHE (V).
        cleaning_Vapex2_vsRHE: Cleaning CV apex-2 potentials vs RHE (V).
        cleaning_Vfinal_vsRHE: Cleaning CV final potentials vs RHE (V).
        cleaning_scanrate_voltsec: Cleaning CV scan rates (V/s).
        cleaning_CV_samplerate_sec: Cleaning CV sample interval (s).
        testing_CV_scanrate_voltsec: Testing CV scan rate (V/s).
        testing_CV_samplerate_sec: Testing CV sample interval (s).
        CV_N2_cycles: Background N2 CV cycle counts.
        CV_O2_cycles: O2 testing CV cycle counts.
        OCP_samplerate_sec: OCV sample interval (s) during purges.
        gamry_i_range: Gamry current range string.
        ref_type: Reference electrode type label.
        ref_offset__V: Reference electrode offset (V).
        aliquot_after_cleaningCV: Per-cleaning-CV aliquot flags.
        aliquote_after_CV_init: Per-background-CV aliquot flags.
        aliquote_CV_O2: Per-O2-CV aliquot flags.
        aliquote_CV_final: Final CV aliquot flags.
        aliquot_volume_ul: Aliquot volume (uL).
        PAL_Injector: PAL injector key.
        PAL_Injector_id: PAL injector identifier.
        cell_draintime_sec: Drain duration (s).
        ReturnLineReverseWait_sec: Reverse return-line wait (s).
        number_of_cleans: Number of clean cycles per cleaning pass.
        clean_volume_ul: Cleaning volume (uL).
        clean_recirculate_sec: Cleaning recirculation duration (s).
        clean_drain_sec: Cleaning drain duration (s).

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    if rinse_with_electrolyte_bf_prefill:
        epm.add("ADSS_sub_move_to_clean_cell", {})
        epm.add(
            "ADSS_sub_cellfill_prefilled_nosampleload",
            {
                "Solution_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            },
        )
        epm.add(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "forward",
                "wait_time_s": rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec,
            },
        )
        epm.add(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": rinse_with_electrolyte_bf_prefill_drain_time_sec,
                "ReturnLineReverseWait_s": 5,
                #    "ResidualWait_s": ResidualWait_s,
            },
        )
        epm.add(
            "ADSS_sub_refill_syringe",
            {
                "syringe": "electrolyte",
                "fill_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            },
        )

    ###################################################################
    # REF MEASUREMENT AT BEGINNING OF SEQUENCE
    ###################################################################

    # ref measurement at beginning of sequence
    if measure_ref_Pt_at_beginning:
        epm.add(
            "ADSS_sub_move_to_ref_measurement",
            {"reference_position_name": name_ref_Pt_at_beginning},
        )

        epm.add(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id_ref_Pt,
                "solid_sample_no": 1,  ################### can i use the sample id for all ref measurements?
                "previous_liquid": use_current_electrolyte,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )

        # electrolyte filling for experiment
        epm.add(
            "ADSS_sub_cellfill_prefilled",
            {
                "Solution_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            },
        )

        # set initial gas to N2
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": True,
            },
        )
        epm.add(
            "ADSS_sub_PAL_load_gas",
            {
                "bubbled_gas": "N2",
                "reservoir_gas_sample_no": 1,
            },
        )

        # pump recirculate forward
        epm.add(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "forward",
                "wait_time_s": fill_recirculate_wait_time_sec,
            },
        )

        # pump recirculate reverse (for bubbles)
        if pump_reversal_during_filling:
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "reverse",
                    "wait_time_s": fill_recirculate_reverse_wait_time_sec,
                },
            )

            # pump recirculate forward
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": 5,
                },
            )

        # refill electrolyte syringe here so that ADSS can recirculate and N2 saturate while filling syringe
        if not use_current_electrolyte:
            epm.add(
                "ADSS_sub_refill_syringe",
                {
                    "syringe": "electrolyte",
                    "fill_volume_ul": liquid_sample_volume_ul,
                    "Syringe_rate_ulsec": 300,
                },
            )

        # check for bubbles that could interfere with echem measurments with OCV
        if use_bubble_removal:
            epm.add(
                "ADSS_sub_OCV",
                {
                    "check_bubble": True,
                    "Tval__s": bubble_removal_OCV_t_s,
                    "samplerate_sec": 0.1,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "bubbler_gas": "N2",
                    "run_use": "ref",
                    "RSD_threshold": bubble_removal_RSD_threshold,
                    "simple_threshold": bubble_removal_simple_threshold,
                    "signal_change_threshold": bubble_removal_signal_change_threshold,
                    "amplitude_threshold": bubble_removal_amplitude_threshold,
                    "bubble_pump_reverse_time_s": bubble_removal_pump_reverse_t_s,
                    "bubble_pump_forward_time_s": bubble_removal_pump_forward_t_s,
                },
            )

        # saturate electrolyte with N2 and measure OCV while saturation
        epm.add(
            "ADSS_sub_OCV",
            {
                "Tval__s": purge_wait_initialN2_min * 60,
                "samplerate_sec": OCP_samplerate_sec,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
                "bubbler_gas": "N2",
                "run_use": "ref",
            },
        )

        # epm.add(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_initialN2_min * 60,
        #     }
        # )

        # start cleaning CVs in N2
        for i, CV_cycle in enumerate(cleaning_CV_cycles):
            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": cleaning_Vinit_vsRHE[i],
                    "Vapex1_vsRHE": cleaning_Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": cleaning_Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": cleaning_Vfinal_vsRHE[i],
                    "scanrate_voltsec": cleaning_scanrate_voltsec[i],
                    "SampleRate": cleaning_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "bubbler_gas": "N2",
                    "run_use": "ref",
                },
            )

        # start background CVs in N2
        for i, CV_cycle in enumerate(ref_CV_cycles):
            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": ref_Vinit_vsRHE,
                    "Vapex1_vsRHE": ref_Vapex1_vsRHE,
                    "Vapex2_vsRHE": ref_Vapex2_vsRHE,
                    "Vfinal_vsRHE": ref_Vfinal_vsRHE,
                    "scanrate_voltsec": ref_CV_scanrate_voltsec,
                    "SampleRate": ref_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "bubbler_gas": "N2",
                    "run_use": "ref",
                },
            )

        # switch from N2 to O2 and saturate
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": False,
            },
        )
        # need to remove N2 gas sample
        epm.add("ADSS_sub_unload_gas_only", {})
        # test need
        epm.add(
            "ADSS_sub_PAL_load_gas",
            {
                "bubbled_gas": "O2",
                "reservoir_gas_sample_no": 2,
            },
        )
        epm.add(
            "ADSS_sub_OCV",
            {
                "Tval__s": purge_wait_N2_to_O2_min * 60,
                "samplerate_sec": OCP_samplerate_sec,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
                "bubbler_gas": "O2",
                "run_use": "ref",
            },
        )
        #        epm.add(
        #            "orch_sub_wait",
        #            {
        #                "wait_time_s": purge_wait_N2_to_O2_min * 60,
        #            }
        #        )

        # start O2 cycles
        for i, CV_cycle in enumerate(ref_CV_cycles):
            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": ref_Vinit_vsRHE,
                    "Vapex1_vsRHE": ref_Vapex1_vsRHE,
                    "Vapex2_vsRHE": ref_Vapex2_vsRHE,
                    "Vfinal_vsRHE": ref_Vfinal_vsRHE,
                    "scanrate_voltsec": ref_CV_scanrate_voltsec,
                    "SampleRate": ref_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "bubbler_gas": "O2",
                    "run_use": "ref",
                },
            )

        # switch from O2 to N2 and saturate
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": True,
            },
        )
        # need to remove O2 gas sample
        epm.add("ADSS_sub_unload_gas_only", {})
        # test need
        epm.add(
            "ADSS_sub_PAL_load_gas",
            {
                "bubbled_gas": "N2",
                "reservoir_gas_sample_no": 1,
            },
        )

        # unload sample
        epm.add("ADSS_sub_unloadall_customs", {})

        # drain cell
        epm.add(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": cell_draintime_sec,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_sec,
                #    "ResidualWait_s": ResidualWait_s,
            },
        )

        # clean cell
        if move_to_clean_and_clean:
            epm.add("ADSS_sub_move_to_clean_cell", {})
            for i in range(number_of_cleans):
                epm.add(
                    "ADSS_sub_clean_cell",
                    {
                        "Clean_volume_ul": clean_volume_ul,
                        "ReturnLineWait_s": clean_recirculate_sec,
                        "DrainWait_s": clean_drain_sec,
                    },
                )
                # if working with more than 10mL cleaning V, then by default a precleaning with 6mL is done. This would also be needed to refill
                if clean_volume_ul > 10000:
                    volume = 6000 + clean_volume_ul
                else:
                    volume = clean_volume_ul

                epm.add(
                    "ADSS_sub_refill_syringe",
                    {
                        "syringe": "waterclean",
                        "fill_volume_ul": volume,
                        "Syringe_rate_ulsec": 300,
                    },
                )

            # rinse with electrolyte to remove cleaning liquid residuals
            if rinse_with_electrolyte_bf_prefill:
                epm.add(
                    "ADSS_sub_cellfill_prefilled_nosampleload",
                    {
                        "Solution_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                        "Syringe_rate_ulsec": Syringe_rate_ulsec,
                    },
                )
                epm.add(
                    "ADSS_sub_recirculate",
                    {
                        "direction_forward_or_reverse": "forward",
                        "wait_time_s": rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec,
                    },
                )
                epm.add(
                    "ADSS_sub_drain_cell",
                    {
                        "DrainWait_s": rinse_with_electrolyte_bf_prefill_drain_time_sec,
                        "ReturnLineReverseWait_s": 5,
                        #    "ResidualWait_s": ResidualWait_s,
                    },
                )
                epm.add(
                    "ADSS_sub_refill_syringe",
                    {
                        "syringe": "electrolyte",
                        "fill_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                        "Syringe_rate_ulsec": Syringe_rate_ulsec,
                    },
                )

    ###################################################################
    # SEQUENCE FOR ACTUAL SAMPLE
    ###################################################################

    # for solid_sample_no in plate_sample_no_list:  # have to indent add expts if used

    washmod = 0

    for lpl, upl, sample_no in zip(LPL_list, UPL_list, plate_sample_no_list):
        print(
            "##########################################################\n"
            + "Current LPL is {} Vrhe\n".format(lpl)
            + "Current UPL is {} Vrhe\n".format(upl)
            + "Current Sample is {}\n".format(sample_no)
            + "##########################################################"
        )

        if not same_sample:

            epm.add(
                "ADSS_sub_move_to_sample",
                {
                    "solid_custom_position": "cell1_we",
                    "solid_plate_id": plate_id,
                    "solid_sample_no": sample_no,
                    "liquid_custom_position": "cell1_we",
                    "liquid_sample_no": liquid_sample_no,
                    "liquid_sample_volume_ul": liquid_sample_volume_ul,
                },
            )

        epm.add(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": sample_no,
                "previous_liquid": use_current_electrolyte,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )

        # electrolyte filling for experiment
        if not use_current_electrolyte:
            epm.add(
                "ADSS_sub_cellfill_prefilled",
                {
                    "Solution_volume_ul": liquid_sample_volume_ul,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                },
            )
            previous_liquid_injected = ""

        # set initial gas to N2
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": True,
            },
        )
        epm.add(
            "ADSS_sub_PAL_load_gas",
            {
                "bubbled_gas": "N2",
                "reservoir_gas_sample_no": 1,
            },
        )

        # pump recirculate forward
        epm.add(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "forward",
                "wait_time_s": fill_recirculate_wait_time_sec,
            },
        )

        # pump recirculate reverse (for bubbles)
        if pump_reversal_during_filling:
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "reverse",
                    "wait_time_s": fill_recirculate_reverse_wait_time_sec,
                },
            )

            # pump recirculate forward
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": 5,
                },
            )

        # refill electrolyte syringe here so that ADSS can recirculate and N2 saturate while filling syringe
        if not use_current_electrolyte:
            epm.add(
                "ADSS_sub_refill_syringe",
                {
                    "syringe": "electrolyte",
                    "fill_volume_ul": liquid_sample_volume_ul,
                    "Syringe_rate_ulsec": 300,
                },
            )

        # washmod = 0

        if aliquot_init:  # stops gas purge, takes aliquote, starts gas purge again

            washmod += 1
            firstaliquot = True
        else:
            firstaliquot = False

        # check for bubbles that could interfere with echem measurments with OCV
        if use_bubble_removal:
            epm.add(
                "ADSS_sub_OCV",
                {
                    "check_bubble": True,
                    "Tval__s": bubble_removal_OCV_t_s,
                    "samplerate_sec": 0.1,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "RSD_threshold": bubble_removal_RSD_threshold,
                    "simple_threshold": bubble_removal_simple_threshold,
                    "signal_change_threshold": bubble_removal_signal_change_threshold,
                    "amplitude_threshold": bubble_removal_amplitude_threshold,
                    "bubble_pump_reverse_time_s": bubble_removal_pump_reverse_t_s,
                    "bubble_pump_forward_time_s": bubble_removal_pump_forward_t_s,
                    "bubbler_gas": "N2",
                },
            )

        # saturate electrolyte with N2
        epm.add(
            "ADSS_sub_OCV",
            {
                "Tval__s": purge_wait_initialN2_min * 60,
                "samplerate_sec": OCP_samplerate_sec,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
                "aliquot_pre": firstaliquot,
                "aliquot_volume_ul": aliquot_volume_ul,
                "washmod_in": washmod,
                "bubbler_gas": "N2",
            },
        )

        # epm.add(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_initialN2_min * 60,
        #     }
        # )

        # start cleaning CVs in N2
        for i, CV_cycle in enumerate(cleaning_CV_cycles):

            if aliquot_after_cleaningCV[i] == 1:
                washmod += 1
                postaliquot = True
            else:
                postaliquot = False

            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": cleaning_Vinit_vsRHE[i],
                    "Vapex1_vsRHE": cleaning_Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": cleaning_Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": cleaning_Vfinal_vsRHE[i],
                    "scanrate_voltsec": cleaning_scanrate_voltsec[i],
                    "SampleRate": cleaning_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "aliquot_post": postaliquot,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "washmod_in": washmod,
                    "bubbler_gas": "N2",
                },
            )

        # start background CVs in N2
        for i, CV_cycle in enumerate(CV_N2_cycles):

            if aliquote_after_CV_init[i] == 1:
                washmod += 1
                postaliquot = True
            else:
                postaliquot = False

            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": lpl,
                    "Vapex1_vsRHE": upl,
                    "Vapex2_vsRHE": lpl,
                    "Vfinal_vsRHE": lpl,
                    "scanrate_voltsec": testing_CV_scanrate_voltsec,
                    "SampleRate": testing_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "aliquot_post": postaliquot,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "washmod_in": washmod,
                    "bubbler_gas": "N2",
                },
            )

        # switch from N2 to O2 and saturate
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": False,
            },
        )
        # need to remove N2 gas sample
        epm.add("ADSS_sub_unload_gas_only", {})
        # test need
        epm.add(
            "ADSS_sub_PAL_load_gas",
            {
                "bubbled_gas": "O2",
                "reservoir_gas_sample_no": 2,
            },
        )

        epm.add(
            "ADSS_sub_OCV",
            {
                "Tval__s": purge_wait_N2_to_O2_min * 60,
                "samplerate_sec": OCP_samplerate_sec,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
                "bubbler_gas": "O2",
            },
        )

        # epm.add(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_N2_to_O2_min * 60,
        #     }
        # )

        # start O2 cycles
        for i, CV_cycle in enumerate(CV_O2_cycles):

            if aliquote_CV_O2[i] == 1:
                washmod += 1
                postaliquot = True
            else:
                postaliquot = False

            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": lpl,
                    "Vapex1_vsRHE": upl,
                    "Vapex2_vsRHE": lpl,
                    "Vfinal_vsRHE": lpl,
                    "scanrate_voltsec": testing_CV_scanrate_voltsec,
                    "SampleRate": testing_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "aliquot_post": postaliquot,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "washmod_in": washmod,
                    ####             "EquilibrationTime_s": 0,
                    "bubbler_gas": "O2",
                },
            )

        # inject phosphoric acid
        if Inject_PA:
            ################################# temporary manual injection of phos
            epm.add(
                "ADSS_sub_load_liquid_only",
                {
                    "liquid_sample_no": phosphoric_sample_no,
                    "liquid_custom_position": "cell1_we",
                    "liquid_sample_volume_ul": phosphoric_quantity_ul,
                    "combine_liquids": True,
                },
            )

            # epm.add(
            #     "ADSS_sub_interrupt",
            #     {
            #         "reason": "Manual injection of phosphoric",
            #     }
            # )

            ########################### actual syringe injection
            previous_liquid_injected = "phosphoric"
            washmod += 1
            washone = washmod % 4 % 3 % 2
            washtwo = (washmod + 1) % 4 % 3 % 2
            washthree = (washmod + 2) % 4 % 3 % 2
            washfour = (washmod + 3) % 4 % 3 % 2

            epm.add(
                "ADSS_sub_transfer_liquid_in",
                {
                    "destination": "cell1_we",
                    "source_tray": phosphoric_location[0],
                    "source_slot": phosphoric_location[1],
                    "source_vial": phosphoric_location[2],
                    "liquid_sample_no": phosphoric_sample_no,
                    "aliquot_volume_ul": phosphoric_quantity_ul,
                    "PAL_Injector": phos_PAL_Injector,
                    "PAL_Injector_id": phos_PAL_Injector_id,
                    # "rinse_1": washone,
                    # "rinse_2": washtwo,
                    # "rinse_3": washthree,
                    # "rinse_4": washfour,
                    "rinse_1": 0,
                    "rinse_2": 0,
                    "rinse_3": 1,  # was 0
                    "rinse_4": 0,
                },
            )
            ##################################
            # recirculate to mix PA into electrolyte
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": inject_recirculate_wait_time_sec,
                },
            )
        else:
            previous_liquid_injected = ""

        # start O2 cycles with PA
        for i, CV_cycle in enumerate(CV_O2_cycles):

            if aliquote_CV_O2[i] == 1:
                washmod += 1
                postaliquot = True
            else:
                postaliquot = False

            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": lpl,
                    "Vapex1_vsRHE": upl,
                    "Vapex2_vsRHE": lpl,
                    "Vfinal_vsRHE": lpl,
                    "scanrate_voltsec": testing_CV_scanrate_voltsec,
                    "SampleRate": testing_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "aliquot_post": postaliquot,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "washmod_in": washmod,
                    ####             "EquilibrationTime_s": 0,
                    "bubbler_gas": "O2",
                    "previous_liquid_injected": previous_liquid_injected,
                },
            )

        # switch from O2 to N2 and saturate
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": True,
            },
        )
        # need to remove O2 gas sample
        epm.add("ADSS_sub_unload_gas_only", {})
        # test need
        epm.add(
            "ADSS_sub_PAL_load_gas",
            {
                "bubbled_gas": "N2",
                "reservoir_gas_sample_no": 1,
            },
        )

        # measure OCP (default of OCV exp is to not take any aliquots)
        epm.add(
            "ADSS_sub_OCV",
            {
                "Tval__s": purge_wait_O2_to_N2_min * 60,
                "samplerate_sec": OCP_samplerate_sec,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
                "bubbler_gas": "N2",
                "previous_liquid_injected": previous_liquid_injected,
            },
        )

        # epm.add(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_O2_to_N2_m * 60,
        #     }
        # )

        # start background CVs in N2 with phosphoric acid
        for i, CV_cycle in enumerate(CV_N2_cycles):

            if aliquote_CV_final[i] == 1:
                washmod += 1
                postaliquot = True
            else:
                postaliquot = False

            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": lpl,
                    "Vapex1_vsRHE": upl,
                    "Vapex2_vsRHE": lpl,
                    "Vfinal_vsRHE": lpl,
                    "scanrate_voltsec": testing_CV_scanrate_voltsec,
                    "SampleRate": testing_CV_scanrate_voltsec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "aliquot_post": postaliquot,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "washmod_in": washmod,
                    ####             "EquilibrationTime_s": 0,
                    "bubbler_gas": "N2",
                    "previous_liquid_injected": previous_liquid_injected,
                },
            )

        if keep_electrolyte_at_end:
            epm.add("ADSS_sub_unload_solid", {})
            # unload gas too?
            epm.add("ADSS_sub_unload_gas_only", {})
        # test need
        else:

            epm.add("ADSS_sub_unloadall_customs", {})
            epm.add(
                "ADSS_sub_drain_cell",
                {
                    "DrainWait_s": cell_draintime_sec,
                    "ReturnLineReverseWait_s": ReturnLineReverseWait_sec,
                    #    "ResidualWait_s": ResidualWait_s,
                },
            )

        if move_to_clean_and_clean:
            epm.add("ADSS_sub_move_to_clean_cell", {})
            for i in range(number_of_cleans):
                epm.add(
                    "ADSS_sub_clean_cell",
                    {
                        "Clean_volume_ul": clean_volume_ul,
                        "ReturnLineWait_s": clean_recirculate_sec,
                        "DrainWait_s": clean_drain_sec,
                    },
                )
                # if working with more than 10mL cleaning V, then by default a precleaning with 6mL is done. This would also be needed to refill
                if clean_volume_ul > 10000:
                    volume = 6000 + clean_volume_ul
                else:
                    volume = clean_volume_ul

                epm.add(
                    "ADSS_sub_refill_syringe",
                    {
                        "syringe": "waterclean",
                        "fill_volume_ul": volume,
                        "Syringe_rate_ulsec": 300,
                    },
                )
            # rinse with electrolyte to remove cleaning liquid residuals
            if rinse_with_electrolyte_bf_prefill:
                epm.add(
                    "ADSS_sub_cellfill_prefilled_nosampleload",
                    {
                        "Solution_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                        "Syringe_rate_ulsec": Syringe_rate_ulsec,
                    },
                )
                epm.add(
                    "ADSS_sub_recirculate",
                    {
                        "direction_forward_or_reverse": "forward",
                        "wait_time_s": rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec,
                    },
                )
                epm.add(
                    "ADSS_sub_drain_cell",
                    {
                        "DrainWait_s": rinse_with_electrolyte_bf_prefill_drain_time_sec,
                        "ReturnLineReverseWait_s": 5,
                        #    "ResidualWait_s": ResidualWait_s,
                    },
                )
                epm.add(
                    "ADSS_sub_refill_syringe",
                    {
                        "syringe": "electrolyte",
                        "fill_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                        "Syringe_rate_ulsec": Syringe_rate_ulsec,
                    },
                )
    ################# extra clean of syringe used for phos injection
    # if Inject_PA:
    #     washmod += 1
    #     #determine last used rinse, then use next two
    #     remainder = washmod %4
    #     washone, washtwo, washthree, washfour = (0,)*4
    #     if remainder == 0:
    #         washone, washtwo = 1,1
    #     if remainder == 1:
    #         washone, washfour= 1,1
    #     if remainder == 2:
    #         washthree,washfour = 1,1
    #     if remainder ==3:
    #         washtwo, washthree=1,1
    #     washmod += 1

    #     epm.add(
    #     "ADSS_sub_PAL_deep_clean",
    #     {
    #         "clean_volume_ul": 200,
    #         "PAL_Injector": phos_PAL_Injector,
    #         # "rinse_1": washone,
    #         # "rinse_2": washtwo,
    #         # "rinse_3": washthree,
    #         # "rinse_4": washfour,
    #         "rinse_1": 1,
    #         "rinse_2": 0,
    #         "rinse_3": 1,
    #         "rinse_4": 1,
    #     }
    # )

    #     washmod += 1
    #     #determine last used rinse, then use next two
    #     remainder = washmod %4
    #     washone, washtwo, washthree, washfour = (0,)*4
    #     if remainder == 0:
    #         washone, washtwo = 1,1
    #     if remainder == 1:
    #         washone, washfour= 1,1
    #     if remainder == 2:
    #         washthree,washfour = 1,1
    #     if remainder ==3:
    #         washtwo, washthree=1,1
    #     washmod += 1

    #     epm.add(
    #     "ADSS_sub_PAL_tray_to_tray",  #hard-coded source and destination vials
    #     {
    #         "volume_ul": 500,
    #         "source_tray": 2,
    #         "source_slot": 3,
    #         "source_vial": 53,
    #         "dest_tray": 2,
    #         "dest_slot": 3,
    #         "dest_vial": 52,
    #         "PAL_Injector": phos_PAL_Injector,
    #         # "rinse_1": washone,
    #         # "rinse_2": washtwo,
    #         # "rinse_3": washthree,
    #         # "rinse_4": washfour,
    #         "rinse_1": 0,
    #         "rinse_2": 0,
    #         "rinse_3": 1,
    #         "rinse_4": 1,
    #     }
    #  )
    ########################

    ###################################################################
    # REF MEASUREMENT AT END OF SEQUENCE
    ###################################################################

    # ref measurement at end of sequence
    if measure_ref_Pt_at_end:
        epm.add(
            "ADSS_sub_move_to_ref_measurement",
            {
                "reference_position_name": name_ref_Pt_at_end,
            },
        )

        epm.add(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id_ref_Pt,
                "solid_sample_no": 1,  ################### can i use the sample id for all ref measurements?
                "previous_liquid": use_current_electrolyte,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )

        # electrolyte filling for experiment
        epm.add(
            "ADSS_sub_cellfill_prefilled",
            {
                "Solution_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            },
        )

        # set initial gas to N2
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": True,
            },
        )
        epm.add(
            "ADSS_sub_PAL_load_gas",
            {
                "bubbled_gas": "N2",
                "reservoir_gas_sample_no": 1,
            },
        )

        # pump recirculate forward
        epm.add(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "forward",
                "wait_time_s": fill_recirculate_wait_time_sec,
            },
        )

        # pump recirculate reverse (for bubbles)
        if pump_reversal_during_filling:
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "reverse",
                    "wait_time_s": fill_recirculate_reverse_wait_time_sec,
                },
            )

            # pump recirculate forward
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": 5,
                },
            )

        # refill electrolyte syringe here so that ADSS can recirculate and N2 saturate while filling syringe
        if not use_current_electrolyte:
            epm.add(
                "ADSS_sub_refill_syringe",
                {
                    "syringe": "electrolyte",
                    "fill_volume_ul": liquid_sample_volume_ul,
                    "Syringe_rate_ulsec": 300,
                },
            )

        # check for bubbles that could interfere with echem measurments with OCV
        if use_bubble_removal:
            epm.add(
                "ADSS_sub_OCV",
                {
                    "check_bubble": True,
                    "Tval__s": bubble_removal_OCV_t_s,
                    "samplerate_sec": 0.1,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "run_use": "ref",
                    "RSD_threshold": bubble_removal_RSD_threshold,
                    "simple_threshold": bubble_removal_simple_threshold,
                    "signal_change_threshold": bubble_removal_signal_change_threshold,
                    "amplitude_threshold": bubble_removal_amplitude_threshold,
                    "bubble_pump_reverse_time_s": bubble_removal_pump_reverse_t_s,
                    "bubble_pump_forward_time_s": bubble_removal_pump_forward_t_s,
                    "bubbler_gas": "N2",
                },
            )

        # saturate electrolyte with N2
        epm.add(
            "ADSS_sub_OCV",
            {
                "Tval__s": purge_wait_initialN2_min * 60,
                "samplerate_sec": OCP_samplerate_sec,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
                "bubbler_gas": "N2",
                "run_use": "ref",
            },
        )

        # epm.add(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_initialN2_min * 60,
        #     }
        # )

        # start cleaning CVs in N2
        for i, CV_cycle in enumerate(cleaning_CV_cycles):
            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": cleaning_Vinit_vsRHE[i],
                    "Vapex1_vsRHE": cleaning_Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": cleaning_Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": cleaning_Vfinal_vsRHE[i],
                    "scanrate_voltsec": cleaning_scanrate_voltsec[i],
                    "SampleRate": cleaning_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "bubbler_gas": "N2",
                    "run_use": "ref",
                },
            )

        # start background CVs in N2
        for i, CV_cycle in enumerate(ref_CV_cycles):
            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": ref_Vinit_vsRHE,
                    "Vapex1_vsRHE": ref_Vapex1_vsRHE,
                    "Vapex2_vsRHE": ref_Vapex2_vsRHE,
                    "Vfinal_vsRHE": ref_Vfinal_vsRHE,
                    "scanrate_voltsec": ref_CV_scanrate_voltsec,
                    "SampleRate": ref_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "bubbler_gas": "N2",
                    "run_use": "ref",
                },
            )

        # switch from N2 to O2 and saturate
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": False,
            },
        )
        # need to remove N2 gas sample
        epm.add("ADSS_sub_unload_gas_only", {})
        # test need
        epm.add(
            "ADSS_sub_PAL_load_gas",
            {
                "bubbled_gas": "O2",
                "reservoir_gas_sample_no": 2,
            },
        )

        epm.add(
            "ADSS_sub_OCV",
            {
                "Tval__s": purge_wait_N2_to_O2_min * 60,
                "samplerate_sec": OCP_samplerate_sec,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
                "bubbler_gas": "O2",
                "run_use": "ref",
            },
        )
        #        epm.add(
        #            "orch_sub_wait",
        #            {
        #                "wait_time_s": purge_wait_N2_to_O2_min * 60,
        #            }
        #        )

        # start O2 cycles
        for i, CV_cycle in enumerate(ref_CV_cycles):
            epm.add(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": ref_Vinit_vsRHE,
                    "Vapex1_vsRHE": ref_Vapex1_vsRHE,
                    "Vapex2_vsRHE": ref_Vapex2_vsRHE,
                    "Vfinal_vsRHE": ref_Vfinal_vsRHE,
                    "scanrate_voltsec": ref_CV_scanrate_voltsec,
                    "SampleRate": ref_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "bubbler_gas": "O2",
                    "run_use": "ref",
                },
            )

        # switch from O2 to N2 and saturate
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": True,
            },
        )

        # unload sample
        epm.add("ADSS_sub_unloadall_customs", {})

        # drain cell
        epm.add(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": cell_draintime_sec,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_sec,
                #    "ResidualWait_s": ResidualWait_s,
            },
        )

        # clean cell
        if move_to_clean_and_clean:
            epm.add("ADSS_sub_move_to_clean_cell", {})
            for i in range(number_of_cleans):
                epm.add(
                    "ADSS_sub_clean_cell",
                    {
                        "Clean_volume_ul": clean_volume_ul,
                        "ReturnLineWait_s": clean_recirculate_sec,
                        "DrainWait_s": clean_drain_sec,
                    },
                )
                # if working with more than 10mL cleaning V, then by default a precleaning with 6mL is done. This would also be needed to refill
                if clean_volume_ul > 10000:
                    volume = 6000 + clean_volume_ul
                else:
                    volume = clean_volume_ul

                epm.add(
                    "ADSS_sub_refill_syringe",
                    {
                        "syringe": "waterclean",
                        "fill_volume_ul": volume,
                        "Syringe_rate_ulsec": 300,
                    },
                )

            # rinse with electrolyte to remove cleaning liquid residuals
            if rinse_with_electrolyte_bf_prefill:
                epm.add(
                    "ADSS_sub_cellfill_prefilled_nosampleload",
                    {
                        "Solution_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                        "Syringe_rate_ulsec": Syringe_rate_ulsec,
                    },
                )
                epm.add(
                    "ADSS_sub_recirculate",
                    {
                        "direction_forward_or_reverse": "forward",
                        "wait_time_s": rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec,
                    },
                )
                epm.add(
                    "ADSS_sub_drain_cell",
                    {
                        "DrainWait_s": rinse_with_electrolyte_bf_prefill_drain_time_sec,
                        "ReturnLineReverseWait_s": 5,
                        #    "ResidualWait_s": ResidualWait_s,
                    },
                )
                epm.add(
                    "ADSS_sub_refill_syringe",
                    {
                        "syringe": "electrolyte",
                        "fill_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                        "Syringe_rate_ulsec": Syringe_rate_ulsec,
                    },
                )
    epm.add(
        "ADSS_sub_gasvalve_N2flow",
        {
            "open": False,
        },
    )

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=1)
def ADSS_PA_CV_single(
    # sample info
    plate_id: int = 6307,
    plate_sample_no: int = 16304,
    same_sample: bool = False,
    use_bubble_removal: bool = True,
    rinse_with_electrolyte_bf_prefill: bool = True,
    use_current_electrolyte: bool = False,
    pump_reversal_during_filling: bool = False,
    keep_electrolyte_at_end: bool = False,
    move_to_clean_and_clean: bool = True,
    # bubble removal OCV
    bubble_removal_OCV_t_s: int = 10,
    bubble_removal_pump_reverse_t_s: int = 15,
    bubble_removal_pump_forward_t_s: int = 10,
    bubble_removal_RSD_threshold: float = 0.2,
    bubble_removal_simple_threshold: float = 0.3,
    bubble_removal_signal_change_threshold: float = 0.01,
    bubble_removal_amplitude_threshold: float = 0.05,
    # purge wait times
    purge_wait_initialN2_min: int = 10,
    purge_wait_N2_to_O2_min: int = 5,
    # electrolyte info
    rinse_with_electrolyte_bf_prefill_volume_uL: float = 3000,
    rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec: float = 30,
    rinse_with_electrolyte_bf_prefill_drain_time_sec: float = 30,
    ph: float = 1.24,
    liquid_sample_no: int = 1053,
    liquid_sample_volume_ul: float = 7000,
    Syringe_rate_ulsec: float = 300,
    fill_recirculate_wait_time_sec: float = 30,
    fill_recirculate_reverse_wait_time_sec: float = 15,
    # CV parameters
    CV_cycles: int = 5,
    Vinit_vsRHE: float = 0.05,
    Vapex1_vsRHE: float = 1.3,
    Vapex2_vsRHE: float = 0.05,
    Vfinal_vsRHE: float = 0.05,
    CV_scanrate_voltsec: float = 0.1,
    CV_samplerate_sec: float = 0.01,
    # OCP info
    OCP_samplerate_sec: float = 0.5,
    # Pstat and ref info
    gamry_i_range: str = "auto",
    ref_type: str = "leakless",
    ref_offset__V: float = -0.005,
    # aliquot info
    aliquot_volume_ul: int = 100,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "LS4_peek",
    # cell drain info
    cell_draintime_sec: float = 60,
    ReturnLineReverseWait_sec: float = 5,
    # cell clean info
    number_of_cleans: int = 2,
    clean_volume_ul: float = 12000,
    clean_recirculate_sec: float = 60,
    clean_drain_sec: float = 120,
) -> list:
    """Single-sample, single-CV measurement with an aliquot afterwards.

    Optionally pre-rinses the cell with electrolyte, loads the requested
    sample, fills the cell and saturates with N2 (running an OCV check and
    optional bubble removal), swaps to O2 with another OCV, runs a single CV
    using ``Vinit_vsRHE``/``Vapex1_vsRHE``/``Vapex2_vsRHE``/``Vfinal_vsRHE``
    and the chosen scan rate, takes an aliquot, then drains and optionally
    cleans the cell. Derived from :func:`ADSS_PA_CV_TRI_new` without the
    reference Pt blocks.

    Args:
        plate_id: Plate id of the solid sample.
        plate_sample_no: Sample number on the plate.
        same_sample: Skip move-to-sample.
        use_bubble_removal: Enable bubble-removal OCV check.
        rinse_with_electrolyte_bf_prefill: Pre-fill electrolyte rinse.
        use_current_electrolyte: Reuse previously loaded electrolyte.
        pump_reversal_during_filling: Add reverse pump leg during fill.
        keep_electrolyte_at_end: Retain electrolyte at end of run.
        move_to_clean_and_clean: Run a clean cell step at the end.
        bubble_removal_OCV_t_s: OCV duration during bubble check (s).
        bubble_removal_pump_reverse_t_s: Reverse pump time (s).
        bubble_removal_pump_forward_t_s: Forward pump time (s).
        bubble_removal_RSD_threshold: RSD threshold.
        bubble_removal_simple_threshold: Simple threshold.
        bubble_removal_signal_change_threshold: Signal-change threshold.
        bubble_removal_amplitude_threshold: Amplitude threshold.
        purge_wait_initialN2_min: Initial N2 purge time (minutes).
        purge_wait_N2_to_O2_min: N2->O2 purge time (minutes).
        rinse_with_electrolyte_bf_prefill_volume_uL: Rinse volume (uL).
        rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec: Rinse
            recirculation duration (s).
        rinse_with_electrolyte_bf_prefill_drain_time_sec: Rinse drain (s).
        ph: Solution pH.
        liquid_sample_no: Reservoir liquid sample number.
        liquid_sample_volume_ul: Cell fill volume (uL).
        Syringe_rate_ulsec: Syringe rate (uL/s).
        fill_recirculate_wait_time_sec: Forward fill recirculation (s).
        fill_recirculate_reverse_wait_time_sec: Reverse fill recirculation (s).
        CV_cycles: Number of CV cycles.
        Vinit_vsRHE: CV initial potential vs RHE (V).
        Vapex1_vsRHE: CV apex-1 potential vs RHE (V).
        Vapex2_vsRHE: CV apex-2 potential vs RHE (V).
        Vfinal_vsRHE: CV final potential vs RHE (V).
        CV_scanrate_voltsec: CV scan rate (V/s).
        CV_samplerate_sec: CV sample interval (s).
        OCP_samplerate_sec: OCV sample interval (s) during purges.
        gamry_i_range: Gamry current range string.
        ref_type: Reference electrode type label.
        ref_offset__V: Reference electrode offset (V).
        aliquot_volume_ul: Aliquot volume (uL).
        PAL_Injector: PAL injector key.
        PAL_Injector_id: PAL injector identifier.
        cell_draintime_sec: Drain duration (s).
        ReturnLineReverseWait_sec: Reverse return-line wait (s).
        number_of_cleans: Number of clean cycles.
        clean_volume_ul: Cleaning volume (uL).
        clean_recirculate_sec: Cleaning recirculation duration (s).
        clean_drain_sec: Cleaning drain duration (s).

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    if rinse_with_electrolyte_bf_prefill:
        epm.add("ADSS_sub_move_to_clean_cell", {})
        epm.add(
            "ADSS_sub_cellfill_prefilled_nosampleload",
            {
                "Solution_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            },
        )
        epm.add(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "forward",
                "wait_time_s": rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec,
            },
        )
        epm.add(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": rinse_with_electrolyte_bf_prefill_drain_time_sec,
                "ReturnLineReverseWait_s": 5,
            },
        )
        epm.add(
            "ADSS_sub_refill_syringe",
            {
                "syringe": "electrolyte",
                "fill_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            },
        )

    ###################################################################
    # SEQUENCE FOR ACTUAL SAMPLE
    ###################################################################

    if not same_sample:
        epm.add(
            "ADSS_sub_move_to_sample",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample_no,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )

    epm.add(
        "ADSS_sub_load",
        {
            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no,
            "previous_liquid": use_current_electrolyte,
            "liquid_custom_position": "cell1_we",
            "liquid_sample_no": liquid_sample_no,
            "liquid_sample_volume_ul": liquid_sample_volume_ul,
        },
    )

    # electrolyte filling for experiment
    if not use_current_electrolyte:
        epm.add(
            "ADSS_sub_cellfill_prefilled",
            {
                "Solution_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            },
        )

    # set initial gas to N2
    epm.add(
        "ADSS_sub_gasvalve_N2flow",
        {
            "open": True,
        },
    )
    epm.add(
        "ADSS_sub_PAL_load_gas",
        {
            "bubbled_gas": "N2",
            "reservoir_gas_sample_no": 1,
        },
    )

    # pump recirculate forward
    epm.add(
        "ADSS_sub_recirculate",
        {
            "direction_forward_or_reverse": "forward",
            "wait_time_s": fill_recirculate_wait_time_sec,
        },
    )

    # pump recirculate reverse (for bubbles)
    if pump_reversal_during_filling:
        epm.add(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "reverse",
                "wait_time_s": fill_recirculate_reverse_wait_time_sec,
            },
        )

        # pump recirculate forward
        epm.add(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "forward",
                "wait_time_s": 5,
            },
        )

    # refill electrolyte syringe here so that ADSS can recirculate and N2 saturate while filling syringe
    if not use_current_electrolyte:
        epm.add(
            "ADSS_sub_refill_syringe",
            {
                "syringe": "electrolyte",
                "fill_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": 300,
            },
        )

    # check for bubbles that could interfere with echem measurments with OCV
    if use_bubble_removal:
        epm.add(
            "ADSS_sub_OCV",
            {
                "check_bubble": True,
                "Tval__s": bubble_removal_OCV_t_s,
                "samplerate_sec": 0.1,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
                "RSD_threshold": bubble_removal_RSD_threshold,
                "simple_threshold": bubble_removal_simple_threshold,
                "signal_change_threshold": bubble_removal_signal_change_threshold,
                "amplitude_threshold": bubble_removal_amplitude_threshold,
                "bubble_pump_reverse_time_s": bubble_removal_pump_reverse_t_s,
                "bubble_pump_forward_time_s": bubble_removal_pump_forward_t_s,
                "bubbler_gas": "N2",
            },
        )

    # saturate electrolyte with N2
    epm.add(
        "ADSS_sub_OCV",
        {
            "Tval__s": purge_wait_initialN2_min * 60,
            "samplerate_sec": OCP_samplerate_sec,
            "gamry_i_range": gamry_i_range,
            "ph": ph,
            "ref_type": ref_type,
            "ref_offset__V": ref_offset__V,
            "aliquot_insitu": False,
            "bubbler_gas": "N2",
        },
    )

    # switch from N2 to O2 and saturate
    epm.add(
        "ADSS_sub_gasvalve_N2flow",
        {
            "open": False,
        },
    )
    # need to remove N2 gas sample
    epm.add("ADSS_sub_unload_gas_only", {})
    # load O2 gas
    epm.add(
        "ADSS_sub_PAL_load_gas",
        {
            "bubbled_gas": "O2",
            "reservoir_gas_sample_no": 2,
        },
    )

    epm.add(
        "ADSS_sub_OCV",
        {
            "Tval__s": purge_wait_N2_to_O2_min * 60,
            "samplerate_sec": OCP_samplerate_sec,
            "gamry_i_range": gamry_i_range,
            "ph": ph,
            "ref_type": ref_type,
            "ref_offset__V": ref_offset__V,
            "aliquot_insitu": False,
            "bubbler_gas": "O2",
        },
    )

    # single CV measurement
    epm.add(
        "ADSS_sub_CV",
        {
            "Vinit_vsRHE": Vinit_vsRHE,
            "Vapex1_vsRHE": Vapex1_vsRHE,
            "Vapex2_vsRHE": Vapex2_vsRHE,
            "Vfinal_vsRHE": Vfinal_vsRHE,
            "scanrate_voltsec": CV_scanrate_voltsec,
            "SampleRate": CV_samplerate_sec,
            "cycles": CV_cycles,
            "gamry_i_range": gamry_i_range,
            "ph": ph,
            "ref_type": ref_type,
            "ref_offset__V": ref_offset__V,
            "aliquot_insitu": False,
            "bubbler_gas": "O2",
        },
    )

    # take aliquot after CV
    washmod = 0
    washmod += 1
    washone = washmod % 4 % 3 % 2
    washtwo = (washmod + 1) % 4 % 3 % 2
    washthree = (washmod + 2) % 4 % 3 % 2
    washfour = (washmod + 3) % 4 % 3 % 2

    epm.add(
        "ADSS_sub_sample_aliquot",
        {
            "aliquot_volume_ul": aliquot_volume_ul,
            "EquilibrationTime_s": 0,
            "PAL_Injector": PAL_Injector,
            "PAL_Injector_id": PAL_Injector_id,
            "rinse_1": washone,
            "rinse_2": washtwo,
            "rinse_3": washthree,
            "rinse_4": washfour,
        },
    )

    if keep_electrolyte_at_end:
        epm.add("ADSS_sub_unload_solid", {})
        # unload gas too
        epm.add("ADSS_sub_unload_gas_only", {})
    else:
        epm.add("ADSS_sub_unloadall_customs", {})
        epm.add(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": cell_draintime_sec,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_sec,
            },
        )

    if move_to_clean_and_clean:
        epm.add("ADSS_sub_move_to_clean_cell", {})
        for i in range(number_of_cleans):
            epm.add(
                "ADSS_sub_clean_cell",
                {
                    "Clean_volume_ul": clean_volume_ul,
                    "ReturnLineWait_s": clean_recirculate_sec,
                    "DrainWait_s": clean_drain_sec,
                },
            )
            # if working with more than 10mL cleaning V, then by default a precleaning with 6mL is done. This would also be needed to refill
            if clean_volume_ul > 10000:
                volume = 6000 + clean_volume_ul
            else:
                volume = clean_volume_ul

            epm.add(
                "ADSS_sub_refill_syringe",
                {
                    "syringe": "waterclean",
                    "fill_volume_ul": volume,
                    "Syringe_rate_ulsec": 300,
                },
            )
        # rinse with electrolyte to remove cleaning liquid residuals
        if rinse_with_electrolyte_bf_prefill:
            epm.add(
                "ADSS_sub_cellfill_prefilled_nosampleload",
                {
                    "Solution_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                },
            )
            epm.add(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec,
                },
            )
            epm.add(
                "ADSS_sub_drain_cell",
                {
                    "DrainWait_s": rinse_with_electrolyte_bf_prefill_drain_time_sec,
                    "ReturnLineReverseWait_s": 5,
                },
            )
            epm.add(
                "ADSS_sub_refill_syringe",
                {
                    "syringe": "electrolyte",
                    "fill_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                },
            )

    epm.add(
        "ADSS_sub_gasvalve_N2flow",
        {
            "open": False,
        },
    )

    return epm.planned_experiments  # returns complete experiment list
