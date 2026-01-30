"""Sequence library for Closed-loop ADSS
"""

__all__ = ["ADSS_AL_seq"]

from typing import List
from helao.helpers.premodels import ExperimentPlanMaker


def ADSS_AL_seq(
    sequence_version: int = 1,
    plate_id: int = 6307,
    plate_id_ref_Pt: int = 6173,
    plate_sample_no_list: List[int] = [
        16304
    ],
    use_bubble_removal: bool = True,
    rinse_with_electrolyte_bf_prefill: bool = True,
    use_current_electrolyte: bool = False,
    pump_reversal_during_filling: bool = False,
    keep_electrolyte_at_end: bool = False,
    move_to_clean_and_clean: bool = True,
    name_ref: str = "builtin_ref_motorxy_2",
    measure_ref_at_beginning: bool = True,
    measure_ref_at_end: bool = True,
    # bubble removal OCV
    bubble_removal_OCV_t_s: int = 10,
    bubble_removal_pump_reverse_t_s: int = 15,
    bubble_removal_pump_forward_t_s: int = 10,
    bubble_removal_RSD_threshold: float = 0.2,
    bubble_removal_simple_threshold: float = 0.3,
    bubble_removal_signal_change_threshold: float = 0.01,
    bubble_removal_amplitude_threshold: float = 0.05,
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
    # OCP info
    OCP_samplerate_sec: float = 0.5,
    # Pstat and ref info
    gamry_i_range: str = "auto",
    ref_type: str = "leakless",
    ref_offset__V: float = -0.005,
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
):
    epm = ExperimentPlanMaker()

    # I. initial rinse with electrolyte before pre-filling
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

    # II. ref measurement at beginning of sequence
    if measure_ref_at_beginning:
        epm.add(
            "ADSS_sub_move_to_ref_measurement",
            {"reference_position_name": name_ref},
        )

        epm.add(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id_ref_Pt,
                "solid_sample_no": 1, 
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
                    "bubbler_gas": "O2",
                    "RSD_threshold": bubble_removal_RSD_threshold,
                    "simple_threshold": bubble_removal_simple_threshold,
                    "signal_change_threshold": bubble_removal_signal_change_threshold,
                    "amplitude_threshold": bubble_removal_amplitude_threshold,
                    "bubble_pump_reverse_time_s": bubble_removal_pump_reverse_t_s,
                    "bubble_pump_forward_time_s": bubble_removal_pump_forward_t_s,
                },
                run_use="ref",
            )

        epm.add(
            "ADSS_sub_OCV",
            {
                "Tval__s": init_ocv_aliquot__t_s,
                "samplerate_sec": OCP_samplerate_sec,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
                "aliquot_post": True,
                "bubbler_gas": "O2",
            },
            run_use="ref",
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

    for sample_no in plate_sample_no_list:

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

        # washmod = 0

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

        for i, potential in enumerate(CA_potentials):

            washmod += 1
            postaliquot = True

            epm.add(
                "ADSS_sub_CA",
                {
                    "CA_potential": potential,
                    "potential_versus": potential_versus,
                    "samplerate_sec": CA_samplerate_sec,
                    "CA_duration_sec": CA_duration_sec[i],
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

        # set initial gas to O2
        epm.add(
            "ADSS_sub_gasvalve_N2flow",
            {
                "open": False,
            },
        )

        epm.add(
            "ADSS_sub_PAL_load_gas",
            {
                "bubbled_gas": "O2",
                "reservoir_gas_sample_no": 2,
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
