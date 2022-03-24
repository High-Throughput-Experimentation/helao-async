"""
Sequence library for SDC
"""

__all__ = [
    "SDC_4CA_toggle_1CV_toggle",
    "SDC_CV_CA_CV",
]


from helaocore.schema import ExperimentPlanMaker


SEQUENCES = __all__


def SDC_4CA_toggle_1CV_toggle(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_liquid_sample_no: int = 1,
    ph: float = 9.53,
    ref_vs_nhe: float = 0.21,
    CA1_potential_vsRHE: float = 1.23,
    CA1_duration_sec: float = 15,
    CA2_potential_vsRHE: float = 1.23,
    CA2_duration_sec: float = 4,
    CA3_potential_vsRHE: float = 1.23,
    CA3_duration_sec: float = 4,
    CA4_potential_vsRHE: float = 1.23,
    CA4_duration_sec: float = 4,
    CV_Vinit_vsRHE: float = 1.23,
    CV_Vapex1_vsRHE: float = 0.73,
    CV_Vapex2_vsRHE: float = 1.73,
    CV_Vfinal_vsRHE: float = 1.73,
    CV_scanrate_voltsec: float = 0.02,
    CV_samplerate_mV: float = 1,
    CV_cycles: int = 1,
    IErange: str = "auto",
    liquid_volume_ml: float = 1.0,
    samplerate_sec: float = 0.05,
    wavelength_nm1: float = 385,
    wavelength_nm2: float = 455,
    wavelength_nm3: float = 515,
    wavelength_nm4: float = 590,
    wavelength_intensity_mw1: float = 1.715,
    wavelength_intensity_mw2: float = 1.478,
    wavelength_intensity_mw3: float = 0.585,
    wavelength_intensity_mw4: float = 0.366,
    t_onCA: float = 500,
    t_offCA: float = 500,
    t_onCV: float = 2000,
    t_offCV: float = 1000,
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
                "liquid_volume_ml": liquid_volume_ml,
            },
        )
        # CA1
        pl.add_experiment(
            "SDC_slave_CA_toggle",
            {
                "CA_potential_vsRHE": CA1_potential_vsRHE,
                "ph": ph,
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": samplerate_sec,
                "CA_duration_sec": CA1_duration_sec,
                "IErange": IErange,
                "led": "doric_led1",
                "wavelength_nm": wavelength_nm1,
                "wavelength_intensity_mw": wavelength_intensity_mw1,
                "t_on": t_onCA,
                "t_off": t_offCA,
            },
        )
        # CA2
        pl.add_experiment(
            "SDC_slave_CA_toggle",
            {
                "CA_potential_vsRHE": CA2_potential_vsRHE,
                "ph": ph,
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": samplerate_sec,
                "CA_duration_sec": CA2_duration_sec,
                "IErange": IErange,
                "led": "doric_led2",
                "wavelength_nm": wavelength_nm2,
                "wavelength_intensity_mw": wavelength_intensity_mw2,
                "t_on": t_onCA,
                "t_off": t_offCA,
            },
        )
        # CA3
        pl.add_experiment(
            "SDC_slave_CA_toggle",
            {
                "CA_potential_vsRHE": CA3_potential_vsRHE,
                "ph": ph,
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": samplerate_sec,
                "CA_duration_sec": CA3_duration_sec,
                "IErange": IErange,
                "led": "doric_led3",
                "wavelength_nm": wavelength_nm3,
                "wavelength_intensity_mw": wavelength_intensity_mw3,
                "t_on": t_onCA,
                "t_off": t_offCA,
            },
        )
        # CA4
        pl.add_experiment(
            "SDC_slave_CA_toggle",
            {
                "CA_potential_vsRHE": CA4_potential_vsRHE,
                "ph": ph,
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": samplerate_sec,
                "CA_duration_sec": CA4_duration_sec,
                "IErange": IErange,
                "led": "doric_led4",
                "wavelength_nm": wavelength_nm4,
                "wavelength_intensity_mw": wavelength_intensity_mw4,
                "t_on": t_onCA,
                "t_off": t_offCA,
            },
        )

        # CV1
        pl.add_experiment(
            "SDC_slave_CV_toggle",
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
                "ref_vs_nhe": ref_vs_nhe,
                "led": "doric_led1",
                "wavelength_nm": wavelength_nm1,
                "wavelength_intensity_mw": wavelength_intensity_mw1,
                "t_on": t_onCV,
                "t_off": t_offCV,
            },
        )

        pl.add_experiment("SDC_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list


def SDC_CV_CA_CV(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_liquid_sample_no: int = 1,
    ph: float = 9.53,
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
    CV3_Vinit_vsRHE: float = 1.23,
    CV3_Vapex1_vsRHE: float = 0.73,
    CV3_Vapex2_vsRHE: float = 1.73,
    CV3_Vfinal_vsRHE: float = 1.73,
    CV3_scanrate_voltsec: float = 0.02,
    CV3_samplerate_mV: float = 1,
    CV3_cycles: int = 1,
    IErange: str = "auto",
    liquid_volume_ml: float = 1.0,
    samplerate_sec: float = 0.05,
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
                "ref_vs_nhe": ref_vs_nhe,
            },
        )

        # CA2
        pl.add_experiment(
            "SDC_slave_CA",
            {
                "CA_potential_vsRHE": CA2_potential_vsRHE,
                "ph": ph,
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": samplerate_sec,
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
                "ref_vs_nhe": ref_vs_nhe,
            },
        )

        pl.add_experiment("SDC_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list
