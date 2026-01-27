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
                "Tval__s": purge_wait_N2_to_O2_min * 60,
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
