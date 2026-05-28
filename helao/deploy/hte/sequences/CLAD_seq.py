"""Sequence library for Closed Loop Accelerated Durability (CLAD).

Exposes the :func:`CLAD_seq` program that drives the ADSS deployment through
reference setup, cell cleaning, and a multi-potential CA loop for each sample.
"""

from helao.helpers.premodels import ExperimentPlanMaker
from helao.helpers.lib_decorators import sequence

SEQUENCES = ["CLAD_seq"]


@sequence(version=1)
def CLAD_seq(
    solid_plate_id: int = 6307,
    plate_sample_no_list: list = [],
    ca_potential_list: list = [0.6, 0.7, 0.8],
    ca_sample_rate_s: float = 0.02,
    ca_duration_s: float = 90.0,
    electrolyte_sample_no: int = 1053,
    electrolyte_ph: float = 1.24,
    reference_offset_V: float = -0.005,
    reference_position: str = "builtin_ref_motorxy_2",
    drain_duration_s: float = 45.0,
    fill_volume_ul: float = 7000.0,
    fill_rate_ul_s: float = 300.0,
    fill_recirc_fwd_duration_s: float = 30.0,
    fill_recirc_rev_duration_s: float = 15.0,
    rinse_recirc_duration_s: float = 30.0,
    rinse_volume_ul: float = 3000.0,  # rinse with electrolyte
    clean_recirc_duration_s: float = 60.0,
    clean_volume_ul: float = 12000.0,  # clean with water
    clean_drain_duration_s: float = 120.0,
    ocv_duration_s: float = 30.0,
    ocv_sample_rate_s: float = 0.1,
    ocv_bubble_check: bool = True,
    number_of_cleans: int = 2,
    gamry_i_range: str = "auto",
    gas_sample_no: int = 2,
    gas_volume_ml: float = 1.0,
    bubbler_gas: str = "O2",
    aliquot_volume_ul: int = 100,
    enable_aliquots: bool = True,
    pal_injector: str = "LS 4",
    pal_injector_id: str = "LS4_peek",
) -> list:
    """Closed-loop accelerated-durability sequence over a list of plate samples.

    For each sample number in ``plate_sample_no_list`` the sequence:

    1. Drains, unloads, and primes the cell.
    2. Performs a reference setup followed by an OCV bubble check
       (with optional post-OCV aliquot).
    3. Cleans the cell ``number_of_cleans`` times using nitric and water,
       refilling the respective syringes after each cycle.
    4. Flushes with electrolyte, drains, then refills the work syringe.
    5. Loads the next sample assembly, recirculates with alternating
       direction, and runs an OCV bubble check.
    6. Runs CA at each potential in ``ca_potential_list``, taking an aliquot
       after every CA when ``enable_aliquots`` is true.
    7. Drains/unloads, runs another reference measurement, and parks the
       ADSS in standby.

    The sequence ends with a filled cell at the reference sample position.

    Args:
        solid_plate_id: Plate id holding the working-electrode samples.
        plate_sample_no_list: Plate sample numbers to iterate through.
        ca_potential_list: CA potentials (V) to apply per sample.
        ca_sample_rate_s: CA sample interval in seconds.
        ca_duration_s: CA hold duration in seconds.
        electrolyte_sample_no: Liquid sample number used as the electrolyte.
        electrolyte_ph: pH of the electrolyte.
        reference_offset_V: Reference electrode offset (V).
        reference_position: Builtin reference position name.
        drain_duration_s: Cell drain wait time (s).
        fill_volume_ul: Cell fill volume per phase (uL).
        fill_rate_ul_s: Syringe fill rate (uL/s).
        fill_recirc_fwd_duration_s: Forward recirculation duration (s) after fill.
        fill_recirc_rev_duration_s: Reverse recirculation duration (s) after fill.
        rinse_recirc_duration_s: Rinse recirculation duration (s).
        rinse_volume_ul: Rinse volume (uL).
        clean_recirc_duration_s: Cleaning recirculation duration (s).
        clean_volume_ul: Cleaning volume (uL).
        clean_drain_duration_s: Drain time after cleaning (s).
        ocv_duration_s: OCV duration (s) used in reference/bubble checks.
        ocv_sample_rate_s: OCV sample interval (s).
        ocv_bubble_check: Whether to enable bubble check during OCV.
        number_of_cleans: How many clean cycles to run per sample.
        gamry_i_range: Gamry current range string.
        gas_sample_no: Gas sample number loaded for the experiment.
        gas_volume_ml: Gas volume associated with the load.
        bubbler_gas: Bubbler gas label.
        aliquot_volume_ul: Aliquot volume (uL) when enabled.
        enable_aliquots: Master switch for post-CA aliquoting.
        pal_injector: PAL injector key.
        pal_injector_id: PAL injector identifier.

    Returns:
        List of planned experiments to be dispatched by the orchestrator.
    """

    epm = ExperimentPlanMaker()

    washmod = 1
    for sample_no in plate_sample_no_list:
        # phase 0: initial fill on ref -- finishes with filled cell, no samples loaded
        epm.add(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": drain_duration_s,
                "ReturnLineReverseWait_s": 5,
            },
        )
        epm.add("ADSS_sub_unloadall_customs", {})
        epm.add(
            "CLAD_sub_setup_cell",
            {
                "rinse_recirc_duration_s": rinse_recirc_duration_s,
                "rinse_volume_ul": rinse_volume_ul,
                "fill_rate_ul_s": fill_rate_ul_s,
                "drain_wait_duration_s": drain_duration_s,
            },
        )

        # phase 1: reference measurement -- finishes with empty cell, no samples loaded
        epm.add(
            "CLAD_sub_reference_setup",
            {
                "reference_position": reference_position,
                "liquid_sample_no": electrolyte_sample_no,
                "electrolyte_ph": electrolyte_ph,
                "fill_volume_ul": fill_volume_ul,
                "fill_rate_ul_s": fill_rate_ul_s,
                "fill_recirc_fwd_duration_s": fill_recirc_fwd_duration_s,
                "fill_recirc_rev_duration_s": fill_recirc_rev_duration_s,
                "ocv_duration_s": ocv_duration_s,
                "ocv_sample_rate_s": ocv_sample_rate_s,
                "reference_offset_V": reference_offset_V,
                "gamry_i_range": gamry_i_range,
            },
        )
        epm.add(
            "CLAD_sub_OCV_bubble_check",
            {
                "ocv_duration_s": ocv_duration_s,
                "ocv_sample_rate_s": ocv_sample_rate_s,
                "electrolyte_ph": electrolyte_ph,
                "reference_offset_V": reference_offset_V,
                "gamry_i_range": gamry_i_range,
                "bubble_check": ocv_bubble_check,
                "aliquot_post_ocv": enable_aliquots,
                "run_use": "ref",
            },
        )
        washmod += 1  # increment washmod after each aliquot

        ## CLEAN CELL WITH NITRIC ACID AND WATER
        epm.add("ADSS_sub_move_to_clean_cell", {})
        for _ in range(number_of_cleans):
            epm.add(
                "CLAD_sub_clean_cell",
                {
                    "nitric_volume_ul": rinse_volume_ul,
                    "water_volume_ul": clean_volume_ul,
                    "ReturnLineWait_s": clean_recirc_duration_s,
                    "DrainWait_s": clean_drain_duration_s,
                },
            )

            epm.add(
                "CLAD_sub_refill_syringe",
                {
                    "syringe": "clean",
                    "fill_volume_ul": rinse_volume_ul,  # use rinse volume for nitric
                    "Syringe_rate_ulsec": 300,
                },
            )

            epm.add(
                "CLAD_sub_refill_syringe",
                {
                    "syringe": "water",
                    "fill_volume_ul": clean_volume_ul,  # use clean volume for water
                    "Syringe_rate_ulsec": 300,
                },
            )

        # FLUSH WITH ELECTROLYTE TO REMOVE CLEANING WATER
        epm.add(
            "CLAD_sub_fill_cell",
            {
                "fill_volume_ul": fill_volume_ul,
                "fill_rate_ul_s": fill_rate_ul_s,
            },
        )
        epm.add(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "forward",
                "wait_duration_s": fill_recirc_fwd_duration_s,
            },
        )
        epm.add(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": drain_duration_s,
                "ReturnLineReverseWait_s": 5,
            },
        )
        epm.add(
            "CLAD_sub_refill_syringe",
            {
                "syringe": "work",
                "fill_volume_ul": fill_volume_ul,
                "Syringe_rate_ulsec": fill_rate_ul_s,
            },
        )
        epm.add("ADSS_sub_unloadall_customs", {})

        # phase 2: sample measurement
        epm.add(
            "CLAD_sub_load_assembly",
            {
                "solid_plate_id": solid_plate_id,
                "solid_sample_no": sample_no,
                "liquid_sample_no": electrolyte_sample_no,
                "fill_volume_ul": fill_volume_ul,
                "fill_rate_ul_s": fill_rate_ul_s,
                "gas_sample_no": gas_sample_no,
                "gas_volume_ml": gas_volume_ml,
                "bubbler_gas": bubbler_gas,
            },
        )

        epm.add(
            "CLAD_sub_recirculate_alternating",
            {
                "forward_duration_s": fill_recirc_fwd_duration_s,
                "reverse_duration_s": fill_recirc_rev_duration_s,
            },
        )
        epm.add(
            "CLAD_sub_OCV_bubble_check",
            {
                "ocv_duration_s": ocv_duration_s,
                "ocv_sample_rate_s": ocv_sample_rate_s,
                "electrolyte_ph": electrolyte_ph,
                "reference_offset_V": reference_offset_V,
                "gamry_i_range": gamry_i_range,
                "bubble_check": ocv_bubble_check,
                "aliquot_post_ocv": False,
                "run_use": "data",
            },
        )

        for ca_potential in ca_potential_list:
            epm.add(
                "ADSS_sub_CA",
                {
                    "CA_potential": ca_potential,
                    "CA_duration_sec": ca_duration_s,
                    "samplerate_sec": ca_sample_rate_s,
                    "ph": electrolyte_ph,
                    "potential_versus": "rhe",
                    "ref_type": "leakless",
                    "ref_offset__V": reference_offset_V,
                    "electrolyte_sample_no": electrolyte_sample_no,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "aliquot_post": enable_aliquots,
                    "washmod_in": washmod,
                    "PAL_Injector": pal_injector,
                    "PAL_Injector_id": pal_injector_id,
                },
            )
            washmod += 1

        # phase 3: reference measurement -- finishes with empty cell, no samples loaded
        epm.add(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": drain_duration_s,
                "ReturnLineReverseWait_s": 5,
            },
        )
        epm.add("ADSS_sub_unloadall_customs", {})
        epm.add(
            "CLAD_sub_setup_cell",
            {
                "rinse_recirc_duration_s": rinse_recirc_duration_s,
                "rinse_volume_ul": rinse_volume_ul,
                "fill_rate_ul_s": fill_rate_ul_s,
                "drain_wait_duration_s": drain_duration_s,
            },
        )
        epm.add(
            "CLAD_sub_reference_setup",
            {
                "reference_position": reference_position,
                "liquid_sample_no": electrolyte_sample_no,
                "electrolyte_ph": electrolyte_ph,
                "fill_volume_ul": fill_volume_ul,
                "fill_rate_ul_s": fill_rate_ul_s,
                "fill_recirc_fwd_duration_s": fill_recirc_fwd_duration_s,
                "fill_recirc_rev_duration_s": fill_recirc_rev_duration_s,
                "ocv_duration_s": ocv_duration_s,
                "ocv_sample_rate_s": ocv_sample_rate_s,
                "reference_offset_V": reference_offset_V,
                "gamry_i_range": gamry_i_range,
            },
        )
        epm.add(
            "CLAD_sub_OCV_bubble_check",
            {
                "ocv_duration_s": ocv_duration_s,
                "ocv_sample_rate_s": ocv_sample_rate_s,
                "electrolyte_ph": electrolyte_ph,
                "reference_offset_V": reference_offset_V,
                "gamry_i_range": gamry_i_range,
                "bubble_check": ocv_bubble_check,
                "aliquot_post_ocv": False,
                "run_use": "ref",
            },
        )
        epm.add("CLAD_sub_standby", {})

    # sequence ends on filled cell, reference sample position
    return epm.planned_experiments
