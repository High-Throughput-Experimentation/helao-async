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
]


from helaocore.schema import ExperimentPlanMaker


SEQUENCES = __all__


def SDC_4CA_led_1CV_led(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_liquid_sample_no: int = 1,
    reservoir_bubbler_gas: str = "O2",
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
    CA1_doric_led: str = "doric_led1",
    CA1_wavelength_nm: float = 385,
    wavelength_intensity_mwled1: float = 1.715,
    CA2_doric_led: str = "doric_led2",
    CA2_wavelength_nm: float = 455,
    wavelength_intensity_mwled2: float = 1.478,
    CA3_doric_led: str = "doric_led3",
    CA3_wavelength_nm: float = 515,
    wavelength_intensity_mwled3: float = 0.585,
    CA4_doric_led: str = "doric_led4",
    CA4_wavelength_nm: float = 590,
    wavelength_intensity_mwled4: float = 0.366,
    CV_doric_led: str = "doric_led1",
    CV_wavelength_nm: float = 385,
    wavelength_intensity_date: str = "n/a",
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
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": samplerate_sec,
                "CA_duration_sec": CA1_duration_sec,
                "IErange": IErange,
                "led": CA1_doric_led,
                "wavelength_nm": CA1_wavelength_nm,
                "wavelength_intensity_mw": wavelength_intensity_mwled1,
                "wavelength_intensity_date": wavelength_intensity_date,
                "t_on": t_onCA,
                "t_off": t_offCA,
            },
        )
        # CA2
        pl.add_experiment(
            "SDC_slave_CA_led",
            {
                "CA_potential_vsRHE": CA2_potential_vsRHE,
                "ph": ph,
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": samplerate_sec,
                "CA_duration_sec": CA2_duration_sec,
                "IErange": IErange,
                "led": CA2_doric_led,
                "wavelength_nm": CA2_wavelength_nm,
                "wavelength_intensity_mw": wavelength_intensity_mwled2,
                "wavelength_intensity_date": wavelength_intensity_date,
                "t_on": t_onCA,
                "t_off": t_offCA,
            },
        )
        # CA3
        pl.add_experiment(
            "SDC_slave_CA_led",
            {
                "CA_potential_vsRHE": CA3_potential_vsRHE,
                "ph": ph,
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": samplerate_sec,
                "CA_duration_sec": CA3_duration_sec,
                "IErange": IErange,
                "led": CA3_doric_led,
                "wavelength_nm": CA3_wavelength_nm,
                "wavelength_intensity_mw": wavelength_intensity_mwled3,
                "wavelength_intensity_date": wavelength_intensity_date,
               "t_on": t_onCA,
                "t_off": t_offCA,
            },
        )
        # CA4
        pl.add_experiment(
            "SDC_slave_CA_led",
            {
                "CA_potential_vsRHE": CA4_potential_vsRHE,
                "ph": ph,
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": samplerate_sec,
                "CA_duration_sec": CA4_duration_sec,
                "IErange": IErange,
                "led": CA4_doric_led,
                "wavelength_nm": CA4_wavelength_nm,
                "wavelength_intensity_mw": wavelength_intensity_mwled4,
                "wavelength_intensity_date": wavelength_intensity_date,
                "t_on": t_onCA,
                "t_off": t_offCA,
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
                "ref_vs_nhe": ref_vs_nhe,
                "led": CV_doric_led,
                "wavelength_nm": CV_wavelength_nm,
                "wavelength_intensity_mw": wavelength_intensity_mwled1,
                "wavelength_intensity_date": wavelength_intensity_date,
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
    reservoir_bubbler_gas: str = "O2",
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

def SDC_CV(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_liquid_sample_no: int = 1,
    reservoir_bubbler_gas: str = "O2",
    ph: float = 9.53,
    ref_vs_nhe: float = 0.21,
    CV1_Vinit_vsRHE: float = .7,
    CV1_Vapex1_vsRHE: float = 1,
    CV1_Vapex2_vsRHE: float = 0,
    CV1_Vfinal_vsRHE: float = 0,
    CV1_scanrate_voltsec: float = 0.02,
    CV1_samplerate_mV: float = 1,
    CV1_cycles: int = 1,
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
                "ref_vs_nhe": ref_vs_nhe,
            },
        )

        pl.add_experiment("SDC_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list

def SDC_CA(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_liquid_sample_no: int = 1,
    reservoir_bubbler_gas: str = "O2",
    ph: float = 9.53,
    ref_vs_nhe: float = 0.21,
    CA1_potential_vsRHE: float = 1.23,
    CA1_duration_sec: float = 4,
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
                "reservoir_bubbler_gas":     reservoir_bubbler_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )

        # CA1
        pl.add_experiment(
            "SDC_slave_CA",
            {
                "CA_potential_vsRHE": CA1_potential_vsRHE,
                "ph": ph,
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": samplerate_sec,
                "CA_duration_sec": CA1_duration_sec,
                "IErange": IErange,
            },
        )


        pl.add_experiment("SDC_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list

def SDC_CA_led(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_liquid_sample_no: int = 1,
    reservoir_bubbler_gas: str = "O2",
    ph: float = 9.53,
    ref_vs_nhe: float = 0.21,
    CA1_potential_vsRHE: float = 1.23,
    CA1_duration_sec: float = 15,
    IErange: str = "auto",
    liquid_volume_ml: float = 1.0,
    samplerate_sec: float = 0.05,
    doric_led: str = "doric_led1",
    CA1_wavelength_nm: float = 385,
    wavelength_intensity_mwled1: float = 1.715,
    wavelength_intensity_mwled2: float = 1.478,
    wavelength_intensity_mwled3: float = 0.585,
    wavelength_intensity_mwled4: float = 0.366,
    wavelength_intensity_date: str = "n/a",
    t_onCA: float = 500,
    t_offCA: float = 500,

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
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": samplerate_sec,
                "CA_duration_sec": CA1_duration_sec,
                "IErange": IErange,
                "led": doric_led,
                "wavelength_nm": CA1_wavelength_nm,
                "wavelength_intensity_mw": wavelength_intensity_mwled1,
                "wavelength_intensity_date": wavelength_intensity_date,
                "t_on": t_onCA,
                "t_off": t_offCA,
            },
        )

        pl.add_experiment("SDC_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list

def SDC_CV_led(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_liquid_sample_no: int = 1,
    reservoir_bubbler_gas: str = "O2",
    ph: float = 9.53,
    ref_vs_nhe: float = 0.21,
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
    doric_led: str = "doric_led1",
    CV_wavelength_nm: float = 385,
    wavelength_intensity_mwled1: float = 1.715,
    wavelength_intensity_mwled2: float = 1.478,
    wavelength_intensity_mwled3: float = 0.585,
    wavelength_intensity_mwled4: float = 0.366,
    wavelength_intensity_date: str = "n/a",
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
                "ref_vs_nhe": ref_vs_nhe,
                "led": doric_led,
                "wavelength_nm": CV_wavelength_nm,
                "wavelength_intensity_mw": wavelength_intensity_mwled1,
                "wavelength_intensity_date": wavelength_intensity_date,
                "t_on": t_onCV,
                "t_off": t_offCV,
            },
        )

        pl.add_experiment("SDC_slave_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list
