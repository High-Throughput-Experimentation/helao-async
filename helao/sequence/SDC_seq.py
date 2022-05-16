"""
Sequence library for SDC
"""

__all__ = [
    "SDC_4CA_led_1CV_led",
    "SDC_CV_CA_CV",
    "SDC_CV",
    "SDC_CV_led",
    "SDC_CA",
    "SDC_CA_led",
    "SDC_background",
    "SDC_CP",
    "SDC_CP_led",
    "SDC_movetosample",
    "SDC_move",

]


from helaocore.schema import ExperimentPlanMaker
from helaocore.model.electrolyte import Electrolyte


SEQUENCES = __all__

def SDC_4CA_led_1CV_led(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    reservoir_bubbler_gas: str = "O2",
    ph: float = 9.53,
    droplet_size_cm2: float = .071,  #3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    ref_vs_nhe: float = 0.21,
    CA1_potential_vsRHE: float = 1.23,
    CA1_duration_sec: float = 15,
    CA2_potential_vsRHE: float = 1.23,
    CA2_duration_sec: float = 4,
    CA3_potential_vsRHE: float = 1.23,
    CA3_duration_sec: float = 4,
    CA4_potential_vsRHE: float = 1.23,
    CA4_duration_sec: float = 4,
    CA_samplerate_sec: float = 0.05,
    CV_Vinit_vsRHE: float = 1.23,
    CV_Vapex1_vsRHE: float = 0.73,
    CV_Vapex2_vsRHE: float = 1.73,
    CV_Vfinal_vsRHE: float = 1.73,
    CV_scanrate_voltsec: float = 0.02,
    CV_samplerate_mV: float = 1,
    CV_cycles: int = 1,
    IErange: str = "auto",
    led_typenamesdate: list = ["led"],
    led_wavelengths_nm: list = [0],
    led_intensities_mw: list = [0],
    led_number_CA1: int = 1,
    led_number_CA2: int = 2,
    led_number_CA3: int = 3,
    led_number_CA4: int = 4,
    led_number_CV: int = 1,
    t_onCA: float = 500,
    t_offCA: float = 500,
    t_offsetCA: float = 0,
    t_onCV: float = 2000,
    t_offCV: float = 1000,
    t_offsetCV: float = 0,
):

    pl = ExperimentPlanMaker()

    # (1) house keeping
    pl.add_experiment("SDC_slave_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        pl.add_experiment(
            "SDC_slave_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "reservoir_bubbler_gas":     reservoir_bubbler_gas,
               "liquid_volume_ml": liquid_volume_ml,
            },
        )
        # CA1
        pl.add_experiment(
            "SDC_slave_CA_led",
            {
                "CA_potential_vsRHE": CA1_potential_vsRHE,
                "ph": ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no, #currently liquid sample database number
                "reservoir_bubbler_gas": reservoir_bubbler_gas,
                "droplet_size_cm2": droplet_size_cm2,
                "reference_electrode_type": "NHE",
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA1_duration_sec,
                "IErange": IErange,
                "led": led_typenamesdate[led_number_CA1],
                "wavelength_nm": led_wavelengths_nm[led_number_CA1],
                "wavelength_intensity_mw": led_intensities_mw[led_number_CA1],
                "wavelength_intensity_date": led_typenamesdate[5],
                "led_side_illumination": led_typenamesdate[0],
                "t_on": t_onCA,
                "t_off": t_offCA,
                "t_offset": t_offsetCA,
            },
        )
        # CA2
        pl.add_experiment(
            "SDC_slave_CA_led",
            {
                "CA_potential_vsRHE": CA2_potential_vsRHE,
                "ph": ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no, #currently liquid sample database number
                "reservoir_bubbler_gas": reservoir_bubbler_gas,
                "droplet_size_cm2": droplet_size_cm2,
                "reference_electrode_type": "NHE",
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA2_duration_sec,
                "IErange": IErange,
                "led": led_typenamesdate[led_number_CA2],
                "wavelength_nm": led_wavelengths_nm[led_number_CA2],
                "wavelength_intensity_mw": led_intensities_mw[led_number_CA2],
                "wavelength_intensity_date": led_typenamesdate[5],
                "led_side_illumination": led_typenamesdate[0],
                "t_on": t_onCA,
                "t_off": t_offCA,
                "t_offset": t_offsetCA,
            },
        )
        # CA3
        pl.add_experiment(
            "SDC_slave_CA_led",
            {
                "CA_potential_vsRHE": CA3_potential_vsRHE,
                "ph": ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no, #currently liquid sample database number
                "reservoir_bubbler_gas": reservoir_bubbler_gas,
                "droplet_size_cm2": droplet_size_cm2,
                "reference_electrode_type": "NHE",
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA3_duration_sec,
                "IErange": IErange,
                "led": led_typenamesdate[led_number_CA3],
                "wavelength_nm": led_wavelengths_nm[led_number_CA3],
                "wavelength_intensity_mw": led_intensities_mw[led_number_CA3],
                "wavelength_intensity_date": led_typenamesdate[5],
                "led_side_illumination": led_typenamesdate[0],
                "t_on": t_onCA,
                "t_off": t_offCA,
                "t_offset": t_offsetCA,
            },
        )
        # CA4
        pl.add_experiment(
            "SDC_slave_CA_led",
            {
                "CA_potential_vsRHE": CA4_potential_vsRHE,
                "ph": ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no, #currently liquid sample database number
                "reservoir_bubbler_gas": reservoir_bubbler_gas,
                "droplet_size_cm2": droplet_size_cm2,
                "reference_electrode_type": "NHE",
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA4_duration_sec,
                "IErange": IErange,
                "led": led_typenamesdate[led_number_CA4],
                "wavelength_nm": led_wavelengths_nm[led_number_CA4],
                "wavelength_intensity_mw": led_intensities_mw[led_number_CA4],
                "wavelength_intensity_date": led_typenamesdate[5],
                "led_side_illumination": led_typenamesdate[0],
                "t_on": t_onCA,
                "t_off": t_offCA,
                "t_offset": t_offsetCA,
            },
        )

        # CV1
        pl.add_experiment(
            "SDC_slave_CV_led",
            {
                "Vinit_vsRHE": CV_Vinit_vsRHE,
                "Vapex1_vsRHE": CV_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV_Vfinal_vsRHE,
                "scanrate_voltsec": CV_scanrate_voltsec,
                "samplerate_sec": CV_samplerate_mV / (CV_scanrate_voltsec * 1000),
                "cycles": CV_cycles,
                "IErange": IErange,
                "ph": ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no, #currently liquid sample database number
                "reservoir_bubbler_gas": reservoir_bubbler_gas,
                "droplet_size_cm2": droplet_size_cm2,
                "reference_electrode_type": "NHE",
                "ref_vs_nhe": ref_vs_nhe,
                "led": led_typenamesdate[led_number_CV],
                "wavelength_nm": led_wavelengths_nm[led_number_CV],
                "wavelength_intensity_mw": led_intensities_mw[led_number_CV],
                "wavelength_intensity_date": led_typenamesdate[5],
                "led_side_illumination": led_typenamesdate[0],
                "t_on": t_onCV,
                "t_off": t_offCV,
                "t_offset": t_offsetCV,
            },
        )

        pl.add_experiment("SDC_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list


def SDC_CV_CA_CV(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    reservoir_bubbler_gas: str = "O2",
    ph: float = 9.53,
    droplet_size_cm2: float = .071,  #3mm diameter droplet    reference_electrode_type: str = "NHE",
    liquid_volume_ml: float = 1.0,
    ref_vs_nhe: float = 0.21,
    CV1_Vinit_vsRHE: float = 1.23,
    CV1_Vapex1_vsRHE: float = 0.73,
    CV1_Vapex2_vsRHE: float = 1.73,
    CV1_Vfinal_vsRHE: float = 1.73,
    CV1_scanrate_voltsec: float = 0.02,
    CV1_samplerate_mV: float = 1,
    CV1_cycles: int = 1,
    CA2_potential_vsRHE: float = 1.23,
    CA2_duration_sec: float = 4,
    CA_samplerate_sec: float = 0.05,
    CV3_Vinit_vsRHE: float = 1.23,
    CV3_Vapex1_vsRHE: float = 0.73,
    CV3_Vapex2_vsRHE: float = 1.73,
    CV3_Vfinal_vsRHE: float = 1.73,
    CV3_scanrate_voltsec: float = 0.02,
    CV3_samplerate_mV: float = 1,
    CV3_cycles: int = 1,
    IErange: str = "auto",
):

    pl = ExperimentPlanMaker()

    # (1) house keeping
    pl.add_experiment("SDC_slave_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        pl.add_experiment(
            "SDC_slave_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "reservoir_bubbler_gas":     reservoir_bubbler_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )

        # CV1
        pl.add_experiment(
            "SDC_slave_CV",
            {
                "Vinit_vsRHE": CV1_Vinit_vsRHE,
                "Vapex1_vsRHE": CV1_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV1_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV1_Vfinal_vsRHE,
                "scanrate_voltsec": CV1_scanrate_voltsec,
                "samplerate_sec": CV1_samplerate_mV / (CV1_scanrate_voltsec * 1000),
                "cycles": CV1_cycles,
                "IErange": IErange,
                "ph": ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no, #currently liquid sample database number
                "reservoir_bubbler_gas": reservoir_bubbler_gas,
                "droplet_size_cm2": droplet_size_cm2,
                "reference_electrode_type": "NHE",
                "ref_vs_nhe": ref_vs_nhe,
            },
        )

        # CA2
        pl.add_experiment(
            "SDC_slave_CA",
            {
                "CA_potential_vsRHE": CA2_potential_vsRHE,
                "ph": ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no, #currently liquid sample database number
                "reservoir_bubbler_gas": reservoir_bubbler_gas,
                "droplet_size_cm2": droplet_size_cm2,
                "reference_electrode_type": "NHE",
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA2_duration_sec,
                "IErange": IErange,
            },
        )

        # CV3
        pl.add_experiment(
            "SDC_slave_CV",
            {
                "Vinit_vsRHE": CV3_Vinit_vsRHE,
                "Vapex1_vsRHE": CV3_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV3_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV3_Vfinal_vsRHE,
                "scanrate_voltsec": CV3_scanrate_voltsec,
                "samplerate_sec": CV3_samplerate_mV / (CV3_scanrate_voltsec * 1000),
                "cycles": CV3_cycles,
                "IErange": IErange,
                "ph": ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no, #currently liquid sample database number
                "reservoir_bubbler_gas": reservoir_bubbler_gas,
                "droplet_size_cm2": droplet_size_cm2,
                "reference_electrode_type": "NHE",
                "ref_vs_nhe": ref_vs_nhe,
            },
        )

        pl.add_experiment("SDC_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list

def SDC_CV(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    reservoir_bubbler_gas: str = "O2",
    ph: float = 9.53,
    droplet_size_cm2: float = .071,  #3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    ref_vs_nhe: float = 0.21,
    CV1_Vinit_vsRHE: float = .7,
    CV1_Vapex1_vsRHE: float = 1,
    CV1_Vapex2_vsRHE: float = 0,
    CV1_Vfinal_vsRHE: float = 0,
    CV1_scanrate_voltsec: float = 0.02,
    CV1_samplerate_mV: float = 1,
    CV1_cycles: int = 1,
    IErange: str = "auto",
):

    pl = ExperimentPlanMaker()

    # (1) house keeping
    pl.add_experiment("SDC_slave_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        pl.add_experiment(
            "SDC_slave_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "reservoir_bubbler_gas":     reservoir_bubbler_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )

        # CV1
        pl.add_experiment(
            "SDC_slave_CV",
            {
                "Vinit_vsRHE": CV1_Vinit_vsRHE,
                "Vapex1_vsRHE": CV1_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV1_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV1_Vfinal_vsRHE,
                "scanrate_voltsec": CV1_scanrate_voltsec,
                "samplerate_sec": CV1_samplerate_mV / (CV1_scanrate_voltsec * 1000),
                "cycles": CV1_cycles,
                "IErange": IErange,
                "ph": ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no, #currently liquid sample database number
                "reservoir_bubbler_gas": reservoir_bubbler_gas,
                "droplet_size_cm2": droplet_size_cm2,
                "reference_electrode_type": "NHE",
                "ref_vs_nhe": ref_vs_nhe,
            },
        )

        pl.add_experiment("SDC_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list

def SDC_CA(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    reservoir_bubbler_gas: str = "O2",
    ph: float = 9.53,
    droplet_size_cm2: float = .071,  #3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    ref_vs_nhe: float = 0.21,
    CA_potential_vsRHE: float = 1.23,
    CA_duration_sec: float = 4,
    CA_samplerate_sec: float = 0.05,
    IErange: str = "auto",
):

    pl = ExperimentPlanMaker()

    # (1) house keeping
    pl.add_experiment("SDC_slave_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        pl.add_experiment(
            "SDC_slave_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "reservoir_bubbler_gas":     reservoir_bubbler_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )

        # CA1
        pl.add_experiment(
            "SDC_slave_CA",
            {
                "CA_potential_vsRHE": CA_potential_vsRHE,
                "ph": ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no, #currently liquid sample database number
                "reservoir_bubbler_gas": reservoir_bubbler_gas,
                "droplet_size_cm2": droplet_size_cm2,
                "reference_electrode_type": "NHE",
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA_duration_sec,
                "IErange": IErange,
            },
        )


        pl.add_experiment("SDC_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list

def SDC_CA_led(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    reservoir_bubbler_gas: str = "O2",
    ph: float = 9.53,
    droplet_size_cm2: float = .071,  #3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    ref_vs_nhe: float = 0.21,
    CA_potential_vsRHE: float = 1.23,
    CA_duration_sec: float = 15,
    CA_samplerate_sec: float = 0.05,
    IErange: str = "auto",
    led_typenamesdate: list = ["led"],
    led_wavelengths_nm: list = [0],
    led_intensities_mw: list = [0],
    led_number_CA: int = 1,
    t_onCA: float = 500,
    t_offCA: float = 500,
    t_offsetCA: float = 0,
):

    pl = ExperimentPlanMaker()

    # (1) house keeping
    pl.add_experiment("SDC_slave_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        pl.add_experiment(
            "SDC_slave_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "reservoir_bubbler_gas":     reservoir_bubbler_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )
        # CA1
        pl.add_experiment(
            "SDC_slave_CA_led",
            {
                "CA_potential_vsRHE": CA_potential_vsRHE,
                "ph": ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no, #currently liquid sample database number
                "reservoir_bubbler_gas": reservoir_bubbler_gas,
                "droplet_size_cm2": droplet_size_cm2,
                "reference_electrode_type": "NHE",
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA_duration_sec,
                "IErange": IErange,
                "led": led_typenamesdate[led_number_CA],
                "wavelength_nm": led_wavelengths_nm[led_number_CA],
                "wavelength_intensity_mw": led_intensities_mw[led_number_CA],
                "wavelength_intensity_date": led_typenamesdate[5],
                "led_side_illumination": led_typenamesdate[0],
                "t_on": t_onCA,
                "t_off": t_offCA,
                "t_offset": t_offsetCA,
            },
        )

        pl.add_experiment("SDC_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list

def SDC_CV_led(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    reservoir_bubbler_gas: str = "O2",
    ph: float = 9.53,
    droplet_size_cm2: float = .071,  #3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    ref_vs_nhe: float = 0.21,
    CV_Vinit_vsRHE: float = 1.23,
    CV_Vapex1_vsRHE: float = 0.73,
    CV_Vapex2_vsRHE: float = 1.73,
    CV_Vfinal_vsRHE: float = 1.73,
    CV_scanrate_voltsec: float = 0.02,
    CV_samplerate_mV: float = 1,
    CV_cycles: int = 1,
    IErange: str = "auto",
    led_typenamesdate: list = ["led"],
    led_wavelengths_nm: list = [0],
    led_intensities_mw: list = [0],
    led_number_CV: int = 1,
    t_onCV: float = 2000,
    t_offCV: float = 1000,
    t_offsetCV: float = 0,
):

    pl = ExperimentPlanMaker()

    # (1) house keeping
    pl.add_experiment("SDC_slave_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        pl.add_experiment(
            "SDC_slave_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "reservoir_bubbler_gas":     reservoir_bubbler_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )
        
        # CV1
        pl.add_experiment(
            "SDC_slave_CV_led",
            {
                "Vinit_vsRHE": CV_Vinit_vsRHE,
                "Vapex1_vsRHE": CV_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV_Vfinal_vsRHE,
                "scanrate_voltsec": CV_scanrate_voltsec,
                "samplerate_sec": CV_samplerate_mV / (CV_scanrate_voltsec * 1000),
                "cycles": CV_cycles,
                "IErange": IErange,
                "ph": ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no, #currently liquid sample database number
                "reservoir_bubbler_gas": reservoir_bubbler_gas,
                "droplet_size_cm2": droplet_size_cm2,
                "reference_electrode_type": "NHE",
                "ref_vs_nhe": ref_vs_nhe,
                "led": led_typenamesdate[led_number_CV],
                "wavelength_nm": led_wavelengths_nm[led_number_CV],
                "wavelength_intensity_mw": led_intensities_mw[led_number_CV],
                "wavelength_intensity_date": led_typenamesdate[5],
                "led_side_illumination": led_typenamesdate[0],
                "t_on": t_onCV,
                "t_off": t_offCV,
                "t_offset": t_offsetCV,
            },
        )

        pl.add_experiment("SDC_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list


def SDC_background(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    liquid_volume_ml: float = 1.0,
    ref_vs_nhe: float = 0.21,
    CP_current: float = 0,
    background_duration_sec: float = 15,
    IErange: str = "auto",
    CP_samplerate_sec: float = 0.05,
    t_on: float = 1000,
    t_off: float = 0,
    t_offset: float = 50,

):

    pl = ExperimentPlanMaker()

    # (1) house keeping
    pl.add_experiment("SDC_slave_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        pl.add_experiment(
            "SDC_slave_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
#                "reservoir_bubbler_gas":     reservoir_bubbler_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )
        # CP1
        pl.add_experiment(
            "SDC_slave_background",
            {
                "CP_current": CP_current,
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": CP_samplerate_sec,
                "background_duration_sec": background_duration_sec,
                "IErange": IErange,
                "t_on": t_on,
                "t_off": t_off,
                "t_offset": t_offset,
            },
        )

        pl.add_experiment("SDC_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list

def SDC_CP(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    reservoir_bubbler_gas: str = "O2",
    ph: float = 9.53,
    droplet_size_cm2: float = .071,  #3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    reference_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    CP_current: float = .000001,
    CP_duration_sec: float = 4,
    CP_samplerate_sec: float = 0.05,
    IErange: str = "auto",
):

    pl = ExperimentPlanMaker()

    # (1) house keeping
    pl.add_experiment("SDC_slave_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        pl.add_experiment(
            "SDC_slave_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "reservoir_bubbler_gas":     reservoir_bubbler_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )

        # CP1
        pl.add_experiment(
            "SDC_slave_CP",
            {
                "CP_current" : CP_current,
                "ph": ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no, #currently liquid sample database number
                "reservoir_bubbler_gas": reservoir_bubbler_gas,
                "droplet_size_cm2": droplet_size_cm2,
                "reference_electrode_type": "NHE",
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": CP_samplerate_sec,
                "CP_duration_sec": CP_duration_sec,
                "IErange": IErange,
            },
        )


        pl.add_experiment("SDC_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list

def SDC_CP_led(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    reservoir_bubbler_gas: str = "O2",
    ph: float = 9.53,
    droplet_size_cm2: float = .071,  #3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    reference_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    CP_current: float = .000001,
    CP_duration_sec: float = 15,
    CP_samplerate_sec: float = 0.05,
    IErange: str = "auto",
    led_number_CP: int = 1,
    led_typenamesdate: list = ["led"],
    led_wavelengths_nm: list = [0],
    led_intensities_mw: list = [0],
    t_onCP: float = 500,
    t_offCP: float = 500,
    t_offsetCP: float = 0,

):

    pl = ExperimentPlanMaker()

    # (1) house keeping
    pl.add_experiment("SDC_slave_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        pl.add_experiment(
            "SDC_slave_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "reservoir_bubbler_gas":     reservoir_bubbler_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )
        # CP1
        pl.add_experiment(
            "SDC_slave_CP_led",
            {
                "CP_current": CP_current,
                "ph": ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no, #currently liquid sample database number
                "reservoir_bubbler_gas": reservoir_bubbler_gas,
                "droplet_size_cm2": droplet_size_cm2,
                "reference_electrode_type": "NHE",
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": CP_samplerate_sec,
                "CP_duration_sec": CP_duration_sec,
                "IErange": IErange,
                "led": led_typenamesdate[led_number_CP],
                "wavelength_nm": led_wavelengths_nm[led_number_CP],
                "wavelength_intensity_mw": led_intensities_mw[led_number_CP],
                "wavelength_intensity_date": led_typenamesdate[5],
                "led_side_illumination": led_typenamesdate[0],
                "t_on": t_onCP,
                "t_off": t_offCP,
                "t_offset": t_offsetCP,
            },
        )

        pl.add_experiment("SDC_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list

def SDC_movetosample(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no: int = 1,

):

    pl = ExperimentPlanMaker()


    pl.add_experiment(
        "SDC_slave_movetosample",
        {
#            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no,
        },
    )

    pl.add_experiment("SDC_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list

def SDC_move(
    sequence_version: int = 1,
    move_x_mm: float = 1.0,
    move_y_mm: float = 1.0,
):

    pl = ExperimentPlanMaker()


    pl.add_experiment(
        "SDC_slave_move",
        {
            "x_mm": move_x_mm,
            "y_mm": move_y_mm,
        },
    )

    pl.add_experiment("SDC_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list
