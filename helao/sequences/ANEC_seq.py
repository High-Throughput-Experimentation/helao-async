"""Sequence library for ANEC"""

__all__ = ["ANEC_sample_ready", "ANEC_series_CA", "ANEC_series_CAliquidOnly", "ANEC_OCV","ANEC_photo_CA", "ANEC_photo_CAgasonly", "ANEC_photo_CV", "ANEC_cleanup_disengage","ANEC_repeat_CA", "ANEC_repeat_TentHeatCAgasonly","ANEC_heatOCV","ANEC_repeat_TentHeatCA","ANEC_repeat_HeatCA", "ANEC_repeat_CV", "ANEC_CA_pretreat", "ANEC_gasonly_CA", "ANEC_ferricyanide_simpleprotocol", "ANEC_ferricyanide_protocol", "ANEC_create_liquid_sample", "ANEC_create_liquid_tray", "GC_Archiveliquid_analysis", "HPLC_Archiveliquid_analysis"]

from typing import List
from typing import Optional
from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__

def ANEC_sample_ready(
    sequence_version: int = 2,
    num_repeats: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    z_move_mm: float = 3.0,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    liquidDrain_time: float = 80.0,
):
    """Repeat CA and aliquot sampling at the cell1_we position.

    Flush and fill cell, run CA, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()
    
    # move to solid sample
    epm.add_experiment(
        "ANEC_sub_startup",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no, "z_move_mm": z_move_mm},
    )
    
    #clean the cell & purge with CO2
    epm.add_experiment("ANEC_sub_normal_state", {})
    epm.add_experiment("ANEC_sub_cleanup", {"reservoir_liquid_sample_no": 1})
    epm.add_experiment("ANEC_sub_cleanup", {"reservoir_liquid_sample_no": 1})
    # housekeeping
    epm.add_experiment("ANEC_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add_experiment(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": 90,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_sub_CA",
            {
                "WE_potential__V": WE_potential__V,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": CA_duration_sec,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )


        epm.add_experiment("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.experiment_plan_list


def ANEC_series_CA(
    sequence_version: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: List[float] = [-0.9, -1.0, -1.1, -1.2, -1.3],
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: List[float] = [900, 900, 900, 900, 900],
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    toolGC: str = "HS 2",
    toolarchive: str = "LS 3",
    volume_ul_GC: int = 300,
    volume_ul_archive: int = 500,
    liquidDrain_time: float = 80.0,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
):
    """running CA at different potentials and aliquot sampling at the cell1_we position.

    Flush and fill cell, run CA, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) mix product
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ANEC_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for cycle, (potential, time) in enumerate(zip(WE_potential__V, CA_duration_sec)):
        print(f" ... cycle {cycle} potential:", potential, f" ... cycle {cycle} duration:", time)

        epm.add_experiment(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": 80,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_sub_CA",
            {
                "WE_potential__V": potential,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": time,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )

        epm.add_experiment(
            "ANEC_sub_aliquot",
            {
                "toolGC": toolGC,
                "toolarchive": toolarchive,
                "volume_ul_GC": volume_ul_GC,
                "volume_ul_archive": volume_ul_archive,
                "wash1": wash1,
                "wash2": wash2,
                "wash3": wash3,
                "wash4": wash4,
            },
        )

        epm.add_experiment("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    epm.add_experiment("ANEC_sub_alloff", {})
    
    return epm.experiment_plan_list

def ANEC_series_CAliquidOnly(
    sequence_version: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: List[float] = [-0.9, -1.0, -1.1, -1.2, -1.3],
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: List[float] = [900, 900, 900, 900, 900],
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    toolarchive: str = "LS 3",
    volume_ul_archive: int = 500,
    liquidDrain_time: float = 80.0,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
):
    """running CA at different potentials and aliquot sampling at the cell1_we position.

    Flush and fill cell, run CA, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) mix product
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ANEC_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for cycle, (potential, time) in enumerate(zip(WE_potential__V, CA_duration_sec)):
        print(f" ... cycle {cycle} potential:", potential, f" ... cycle {cycle} duration:", time)

        epm.add_experiment(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": 80,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_sub_CA",
            {
                "WE_potential__V": potential,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": time,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )

        epm.add_experiment(
            "ANEC_sub_liquidarchive",
            {
                "toolarchive": toolarchive,
                "volume_ul_archive": volume_ul_archive,
                "wash1": wash1,
                "wash2": wash2,
                "wash3": wash3,
                "wash4": wash4,
            },
        )

        epm.add_experiment("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    epm.add_experiment("ANEC_sub_alloff", {})
    
    return epm.experiment_plan_list

def ANEC_OCV(
    sequence_version: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    Tval__s: Optional[float] = 900.0,
    IErange: Optional[str] = "auto",
    toolarchive: str = "LS 3",
    volume_ul_archive: int = 500,
    liquidDrain_time: float = 80.0,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
):
    """running CA at different potentials and aliquot sampling at the cell1_we position.

    Flush and fill cell, run CA, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) mix product
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ANEC_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )



    epm.add_experiment(
        "ANEC_sub_flush_fill_cell",
        {
            "liquid_flush_time": 80,
            "co2_purge_time": 15,
            "equilibration_time": 1.0,
            "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
            "volume_ul_cell_liquid": volume_ul_cell_liquid,
        },
    )

    epm.add_experiment(
        "ANEC_sub_OCV",
        {
            "Tval__s": Tval__s,
            "IErange": IErange,
        },
    )

    epm.add_experiment(
        "ANEC_sub_liquidarchive",
        {
            "toolarchive": toolarchive,
            "volume_ul_archive": volume_ul_archive,
            "wash1": wash1,
            "wash2": wash2,
            "wash3": wash3,
            "wash4": wash4,
        },
    )

    epm.add_experiment("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})    
    return epm.experiment_plan_list

def ANEC_photo_CA(
    sequence_version: int = 3,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: List[float] = [-0.9, -1.0, -1.1, -1.2, -1.3],
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: List[float] = [900, 900, 900, 900, 900],
    SampleRate: float = 0.01,
    IErange: str = "auto",
    gamrychannelwait: int= -1,
    gamrychannelsend: int= 0,
    ref_offset__V: float = 0.0,
    led_wavelengths_nm: float = 450.0,
    led_type: str = "front",
    led_date: str = "01/01/2000",
    led_intensities_mw: float = 9.0,
    led_name_CA: str = "Thorlab_led",
    toggleCA_illum_duty: float = 0.5,
    toggleCA_illum_period: float = 1.0,
    toggleCA_dark_time_init: float = 0,
    toggleCA_illum_time: float = -1,
    toolGC: str = "HS 2",
    toolarchive: str = "LS 3",
    volume_ul_GC: int = 300,
    volume_ul_archive: int = 500,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
    liquid_flush_time: float = 60.0,
    liquidDrain_time: float = 80.0,
):
    """Repeat CA and aliquot sampling at the cell1_we position.

    Flush and fill cell, run CA, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) mix product
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ANEC_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for cycle, (potential, time) in enumerate(zip(WE_potential__V, CA_duration_sec)):
        print(f" ... cycle {cycle} potential:", potential, f" ... cycle {cycle} duration:", time)

        epm.add_experiment(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_sub_photo_CA",
            {
                "WE_potential__V": potential,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": time,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "gamrychannelwait": gamrychannelwait,
                "gamrychannelsend": gamrychannelsend,
                "illumination_source": led_name_CA,
                "illumination_wavelength": led_wavelengths_nm,
                "illumination_intensity": led_intensities_mw,
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "toggle_illum_duty": toggleCA_illum_duty,
                "toggle_illum_period": toggleCA_illum_period,
                "toggle_illum_time": toggleCA_illum_time,
                "toggle_dark_time_init": toggleCA_dark_time_init,
            },
        )

        epm.add_experiment(
            "ANEC_sub_aliquot",
            {
                "toolGC": toolGC,
                "toolarchive": toolarchive,
                "volume_ul_GC": volume_ul_GC,
                "volume_ul_archive": volume_ul_archive,
                "wash1": wash1,
                "wash2": wash2,
                "wash3": wash3,
                "wash4": wash4,
            },
        )

        epm.add_experiment("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})
    if len(WE_potential__V)>1:
        epm.add_experiment("ANEC_sub_alloff", {})
    return epm.experiment_plan_list

def ANEC_photo_CAgasonly(
    sequence_version: int = 3,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: List[float] = [-0.2, -0.3, -0.4, -0.5, -0.6],
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: List[float] = [600, 600, 600, 600, 600],
    SampleRate: float = 0.01,
    IErange: str = "auto",
    gamrychannelwait: int= -1,
    gamrychannelsend: int= 0,
    ref_offset__V: float = 0.0,
    led_wavelengths_nm: float = 450.0,
    led_type: str = "front",
    led_date: str = "01/01/2000",
    led_intensities_mw: float = 9.0,
    led_name_CA: str = "Thorlab_led",
    toggleCA_illum_duty: float = 0.5,
    toggleCA_illum_period: float = 1.0,
    toggleCA_dark_time_init: float = 0,
    toggleCA_illum_time: float = -1,
    toolGC: str = "HS 2",
    volume_ul_GC: int = 300,
    liquid_flush_time: float = 60.0,
    liquidDrain_time: float = 80.0,
):
    """Repeat CA and aliquot sampling at the cell1_we position.

    Flush and fill cell, run CA, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) mix product
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ANEC_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for cycle, (potential, time) in enumerate(zip(WE_potential__V, CA_duration_sec)):
        print(f" ... cycle {cycle} potential:", potential, f" ... cycle {cycle} duration:", time)

        epm.add_experiment(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_sub_photo_CA",
            {
                "WE_potential__V": potential,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": time,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "gamrychannelwait": gamrychannelwait,
                "gamrychannelsend": gamrychannelsend,
                "illumination_source": led_name_CA,
                "illumination_wavelength": led_wavelengths_nm,
                "illumination_intensity": led_intensities_mw,
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "toggle_illum_duty": toggleCA_illum_duty,
                "toggle_illum_period": toggleCA_illum_period,
                "toggle_illum_time": toggleCA_illum_time,
                "toggle_dark_time_init": toggleCA_dark_time_init,
            },
        )

        epm.add_experiment(
            "ANEC_sub_GC_preparation",
            {
                "toolGC": toolGC,
                "volume_ul_GC": volume_ul_GC,
            },
        )

        epm.add_experiment("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})
    if len(WE_potential__V)>1:
        epm.add_experiment("ANEC_sub_alloff", {})
    return epm.experiment_plan_list

def ANEC_photo_CV(
    sequence_version: int = 1,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    num_repeats: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential_init__V: float = 0.0,
    WE_potential_apex1__V: float = -1.0,
    WE_potential_apex2__V: float = -1.0,
    WE_potential_final__V: float = 0.0,
    ScanRate_V_s: float = 0.01,
    Cycles: int = 1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    gamrychannelwait: int= -1,
    gamrychannelsend: int= 0,
    ref_offset: float = 0.0,
    led_wavelengths_nm: float = 450.0,
    led_type: str = "front",
    led_date: str = "01/01/2000",
    led_intensities_mw: float = 9.0,
    led_name_CA: str = "Thorlab_led",
    toggleCA_illum_duty: float = 0.5,
    toggleCA_illum_period: float = 1.0,
    toggleCA_dark_time_init: float = 0,
    toggleCA_illum_time: float = -1,
    liquid_flush_time: float = 60.0,
    liquidDrain_time: float = 80.0,
):
    """Repeat CV at the cell1_we position.

    Flush and fill cell, run CV, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CV
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ANEC_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add_experiment(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_sub_photo_CV",
            {
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "WE_potential_init__V": WE_potential_init__V,
                "WE_potential_apex1__V": WE_potential_apex1__V,
                "WE_potential_apex2__V": WE_potential_apex2__V,
                "WE_potential_final__V": WE_potential_final__V,
                "ScanRate_V_s": ScanRate_V_s,
                "Cycles": Cycles,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "gamrychannelwait": gamrychannelwait,
                "gamrychannelsend": gamrychannelsend,
                "illumination_source": led_name_CA,
                "illumination_wavelength": led_wavelengths_nm,
                "illumination_intensity": led_intensities_mw,
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "toggle_illum_duty": toggleCA_illum_duty,
                "toggle_illum_period": toggleCA_illum_period,
                "toggle_illum_time": toggleCA_illum_time,
                "toggle_dark_time_init": toggleCA_dark_time_init,
            },
        )

        epm.add_experiment("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.experiment_plan_list

def ANEC_cleanup_disengage(
    sequence_version: int = 1
):
    """fulsh and sicharge the cell

    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ANEC_sub_cleanup", {})
    epm.add_experiment("ANEC_sub_cleanup", {})
    epm.add_experiment("ANEC_sub_alloff", {})
    epm.add_experiment("ANEC_sub_disengage", {})

    return epm.experiment_plan_list

def ANEC_CA_pretreat(
    sequence_version: int = 1,
    num_repeats: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    liquid_flush_time: float = 70.0,
    liquidDrain_time: float = 50.0,
):
    """Repeat CA and aliquot sampling at the cell1_we position.

    Flush and fill cell, run CA, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ANEC_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add_experiment(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_sub_CA",
            {
                "WE_potential__V": WE_potential__V,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": CA_duration_sec,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )


        epm.add_experiment("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.experiment_plan_list


def ANEC_repeat_CA(
    sequence_version: int = 1,
    num_repeats: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    toolGC: str = "HS 2",
    toolarchive: str = "LS 3",
    volume_ul_GC: int = 300,
    volume_ul_archive: int = 500,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
    liquid_flush_time: float = 70.0,
    liquidDrain_time: float = 60.0,
):
    """Repeat CA and aliquot sampling at the cell1_we position.

    Flush and fill cell, run CA, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) mix product
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ANEC_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add_experiment(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_sub_CA",
            {
                "WE_potential__V": WE_potential__V,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": CA_duration_sec,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )

        epm.add_experiment(
            "ANEC_sub_aliquot",
            {
                "toolGC": toolGC,
                "toolarchive": toolarchive,
                "volume_ul_GC": volume_ul_GC,
                "volume_ul_archive": volume_ul_archive,
                "wash1": wash1,
                "wash2": wash2,
                "wash3": wash3,
                "wash4": wash4,
            },
        )
        epm.add_experiment("ANEC_sub_heatoff",{})
        epm.add_experiment("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.experiment_plan_list

def ANEC_repeat_TentHeatCAgasonly(
    sequence_version: int = 1,
    num_repeats: int = 1,
    plate_id: int = 6284,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    toolGC: str = "HS 2",
    volume_ul_GC: int = 300,
    liquid_flush_time: float = 70.0,
    liquidDrain_time: float = 60.0,
    target_temperature_degc: float =25.0,
):
    """Repeat CA and aliquot sampling at the cell1_we position.

    Flush and fill cell, run CA, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) mix product
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ANEC_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):
        epm.add_experiment(
            "ANEC_sub_setheat",
            {
                "target_temperature_degc": target_temperature_degc,
            },
        )
        epm.add_experiment(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_sub_CA",
            {
                "WE_potential__V": WE_potential__V,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": CA_duration_sec,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )

        epm.add_experiment(
            "ANEC_sub_GC_preparation",
            {
                "toolGC": toolGC,
                "volume_ul_GC": volume_ul_GC,
            },
        )

        epm.add_experiment("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})
    epm.add_experiment("ANEC_sub_heatoff",{})
    return epm.experiment_plan_list

def ANEC_heatOCV(
    sequence_version: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    Tval__s: Optional[float] = 900.0,
    IErange: Optional[str] = "auto",
    liquid_flush_time: float = 60.0,
    liquidDrain_time: float = 60.0,
    target_temperature_degc: float =25.0,
):
    """running CA at different potentials and aliquot sampling at the cell1_we position.

    Flush and fill cell, run CA, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) mix product
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ANEC_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    epm.add_experiment(
        "ANEC_sub_setheat",
        {
            "target_temperature_degc": target_temperature_degc,
        },
    )
    epm.add_experiment(
        "ANEC_sub_flush_fill_cell",
        {
            "liquid_flush_time": liquid_flush_time,
            "co2_purge_time": 15,
            "equilibration_time": 1.0,
            "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
            "volume_ul_cell_liquid": volume_ul_cell_liquid,
        },
    )

    epm.add_experiment(
        "ANEC_sub_OCV",
        {
            "Tval__s": Tval__s,
            "IErange": IErange,
        },
    )


    epm.add_experiment("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time}) 
    epm.add_experiment("ANEC_sub_heatoff",{})
    return epm.experiment_plan_list


def ANEC_repeat_TentHeatCA(
    sequence_version: int = 1,
    num_repeats: int = 1,
    plate_id: int = 6284,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    toolGC: str = "HS 2",
    toolarchive: str = "LS 3",
    volume_ul_GC: int = 300,
    volume_ul_archive: int = 500,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
    liquid_flush_time: float = 70.0,
    liquidDrain_time: float = 80.0,
    target_temperature_degc: float =25.0,
):
    """Repeat CA and aliquot sampling at the cell1_we position.

    Flush and fill cell, run CA, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) mix product
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ANEC_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):
        epm.add_experiment(
            "ANEC_sub_setheat",
            {
                "target_temperature_degc": target_temperature_degc,
            },
        )
        epm.add_experiment(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_sub_CA",
            {
                "WE_potential__V": WE_potential__V,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": CA_duration_sec,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )

        epm.add_experiment(
            "ANEC_sub_aliquot",
            {
                "toolGC": toolGC,
                "toolarchive": toolarchive,
                "volume_ul_GC": volume_ul_GC,
                "volume_ul_archive": volume_ul_archive,
                "wash1": wash1,
                "wash2": wash2,
                "wash3": wash3,
                "wash4": wash4,
            },
        )

        epm.add_experiment("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})
    epm.add_experiment("ANEC_sub_heatoff",{})
    return epm.experiment_plan_list

def ANEC_repeat_HeatCA(
    sequence_version: int = 1,
    num_repeats: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    toolGC: str = "HS 2",
    toolarchive: str = "LS 3",
    volume_ul_GC: int = 300,
    volume_ul_archive: int = 500,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
    liquid_flush_time: float = 70.0,
    liquidDrain_time: float = 80.0,
    target_temperature_degc: float =25.0,
):
    """Repeat CA and aliquot sampling at the cell1_we position.

    Flush and fill cell, run CA, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) mix product
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ANEC_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add_experiment(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_sub_HeatCA",
            {
                "WE_potential__V": WE_potential__V,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": CA_duration_sec,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "target_temperature_degc": target_temperature_degc
            },
        )

        epm.add_experiment(
            "ANEC_sub_aliquot",
            {
                "toolGC": toolGC,
                "toolarchive": toolarchive,
                "volume_ul_GC": volume_ul_GC,
                "volume_ul_archive": volume_ul_archive,
                "wash1": wash1,
                "wash2": wash2,
                "wash3": wash3,
                "wash4": wash4,
            },
        )

        epm.add_experiment("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.experiment_plan_list

def ANEC_gasonly_CA(
    sequence_version: int = 1,
    num_repeats: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    toolGC: str = "HS 2",
    volume_ul_GC: int = 300,
    liquid_flush_time: float = 70.0,
    liquidDrain_time: float = 60.0,
):
    """Repeat CA and aliquot sampling at the cell1_we position.

    Flush and fill cell, run CA, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) mix product
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ANEC_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add_experiment(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_sub_CA",
            {
                "WE_potential__V": WE_potential__V,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": CA_duration_sec,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )

        epm.add_experiment(
            "ANEC_sub_GC_preparation",
            {
                "toolGC": toolGC,
                "volume_ul_GC": volume_ul_GC,
            },
        )

        epm.add_experiment("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.experiment_plan_list



def ANEC_repeat_CV(
    sequence_version: int = 1,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    num_repeats: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential_init__V: float = 0.0,
    WE_potential_apex1__V: float = -1.0,
    WE_potential_apex2__V: float = -1.0,
    WE_potential_final__V: float = 0.0,
    ScanRate_V_s: float = 0.01,
    Cycles: int = 1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset: float = 0.0,
    liquidDrain_time: float = 80.0,
):
    """Repeat CV at the cell1_we position.

    Flush and fill cell, run CV, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CV
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ANEC_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add_experiment(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": 80,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_sub_CV",
            {
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "WE_potential_init__V": WE_potential_init__V,
                "WE_potential_apex1__V": WE_potential_apex1__V,
                "WE_potential_apex2__V": WE_potential_apex2__V,
                "WE_potential_final__V": WE_potential_final__V,
                "ScanRate_V_s": ScanRate_V_s,
                "Cycles": Cycles,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )

        epm.add_experiment("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.experiment_plan_list

def ANEC_ferricyanide_simpleprotocol(
    sequence_version: int = 2,
    num_repeats: int = 1,
    plate_id: int = 5740,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = -0.8,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 120.0,
    SampleRate_CA: float = 0.5,
    IErange: str = "3mA",
    ref_offset__V: float = 0.0,
    WE_potential_init__V: float = 0.5,
    WE_potential_apex1__V: float = -1.0,
    WE_potential_apex2__V: float = 0.5,
    WE_potential_final__V: float = 0.5,
    ScanRate_V_s: float = 0.1,
    Cycles: int = 1,
    SampleRate_CV: float = 0.1,
    target_temperature_degc: float =25.0,
):
    """Repeat CA and aliquot sampling at the cell1_we position.

    Flush and fill cell, run CA, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) mix product
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ANEC_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):
        
        epm.add_experiment(
            "ANEC_sub_HeatCV",
            {
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "WE_potential_init__V": WE_potential_init__V,
                "WE_potential_apex1__V": WE_potential_apex1__V,
                "WE_potential_apex2__V": WE_potential_apex2__V,
                "WE_potential_final__V": WE_potential_final__V,
                "ScanRate_V_s": ScanRate_V_s,
                "Cycles": Cycles,
                "SampleRate": SampleRate_CV,
                "IErange": IErange,
                "target_temperature_degc": target_temperature_degc
            },
        )
        epm.add_experiment(
            "ANEC_sub_HeatCA",
            {
                "WE_potential__V": WE_potential__V,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": CA_duration_sec,
                "SampleRate": SampleRate_CA,
                "IErange": IErange,
                "target_temperature_degc": target_temperature_degc
            },
        )

    return epm.experiment_plan_list


def ANEC_ferricyanide_protocol(
    sequence_version: int = 2,
    plate_id: int = 5740,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = -0.8,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 120.0,
    SampleRate_CA: float = 0.5,
    IErange: str = "3mA",
    ref_offset__V: float = 0.0,
    WE_potential_init__V: float = 0.5,
    WE_potential_apex1__V: float = -1.0,
    WE_potential_apex2__V: float = 0.5,
    WE_potential_final__V: float = 0.5,
    ScanRate_V_s: float = 0.1,
    Cycles: int = 1,
    SampleRate_CV: float = 0.1,
    liquidDrain_time: float = 80.0,
    target_temperature_degc: List[float] =[25.0],
    CV_only: str = "yes"
):
    """Repeat CA and aliquot sampling at the cell1_we position.

    Flush and fill cell, run CA, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) mix product
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ANEC_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )
    epm.add_experiment(
        "ANEC_sub_flush_fill_cell",
        {
            "liquid_flush_time": 80,
            "co2_purge_time": 15,
            "equilibration_time": 1.0,
            "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
            "volume_ul_cell_liquid": volume_ul_cell_liquid,
        },
    )
    for cycle, temp in enumerate(target_temperature_degc):
        epm.add_experiment(
            "ANEC_sub_HeatCV",
            {
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "WE_potential_init__V": WE_potential_init__V,
                "WE_potential_apex1__V": WE_potential_apex1__V,
                "WE_potential_apex2__V": WE_potential_apex2__V,
                "WE_potential_final__V": WE_potential_final__V,
                "ScanRate_V_s": ScanRate_V_s,
                "Cycles": Cycles,
                "SampleRate": SampleRate_CV,
                "IErange": IErange,
                "target_temperature_degc": temp
            },
        )
        if CV_only== "no":
            epm.add_experiment(
                "ANEC_sub_HeatCA",
                {
                    "WE_potential__V": WE_potential__V,
                    "WE_versus": WE_versus,
                    "ref_type": ref_type,
                    "pH": pH,
                    "ref_offset__V": ref_offset__V,
                    "CA_duration_sec": CA_duration_sec,
                    "SampleRate": SampleRate_CA,
                    "IErange": IErange,
                    "target_temperature_degc": temp
                },
            )
    epm.add_experiment("ANEC_sub_heatoff",{})
    epm.add_experiment("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.experiment_plan_list

def ANEC_create_liquid_sample(
    sequence_version: int = 1,
    no_of_samples: int = 5,
    volume_ml: float = 0.84,
    source: List[str] = ["autoGDE"],
    partial_molarity: List[str] = ["unknown"],
    chemical: List[str] = ["unknown"],
    ph: float = 7.8,
    supplier: List[str] = ["N/A"],
    lot_number: List[str] = ["N/A"],
    electrolyte_name: str = "1M KHCO3",
    prep_date: str = "2024-03-19",
    

):
    epm = ExperimentPlanMaker()
    for _ in range(no_of_samples):
        epm.add_experiment(
            "create_liquid_sample",
            {"volume_ml": volume_ml, "source": source, "partial_molarity":partial_molarity, "chemical":chemical, "ph":ph, "supplier":supplier, "lot_number":lot_number,"electrolyte_name":electrolyte_name, "prep_date":prep_date},
        )

    return epm.experiment_plan_list

def ANEC_create_liquid_tray(
    sequence_version: int = 1,
    liquid_sample_no: List[int] = [1, 1, 1, 1, 1],
    machine_name: str = "hte-ecms-01",
    slot: int = 1,
    vial: List[int] = [1, 2, 3, 4, 5],
    

):
    epm = ExperimentPlanMaker()
    for num, (sample_no, vial_no) in enumerate(zip(liquid_sample_no, vial)):
        epm.add_experiment(
            "load_liquid_sample",
            {"liquid_sample_no": sample_no, "machine_name": machine_name, "tray":2, "slot":slot, "vial":vial_no},
        )

    return epm.experiment_plan_list

def GC_Archiveliquid_analysis(
    experiment_version: int = 1,
    source_tray: int = 2,
    source_slot: int = 1,
    source_vial_from: int = 1,
    source_vial_to: int = 1,
    dest: str = "Injector 1",
    volume_ul: int = 2,
    GC_analysis_time: float = 520.0
):
    """
    Analyze archived liquid product by GC
    """

    epm = ExperimentPlanMaker()

    for source_vial in range(source_vial_from, source_vial_to+1):
        epm.add_experiment(
            "ANEC_sub_GCLiquid_analysis",
            {
                "source_tray": source_tray,
                "source_slot": source_slot,
                "source_vial": source_vial,
                "dest": dest,
                "volume_ul": volume_ul,
                "GC_analysis_time": GC_analysis_time
            },
        )

    return epm.experiment_plan_list

def HPLC_Archiveliquid_analysis(
    experiment_version: int = 1,
    source_tray: int = 2,
    source_slot: int = 1,
    source_vial_from: int = 1,
    source_vial_to: int = 1,
    dest: str = "LCInjector1",
    volume_ul: int = 25,
):
    """
    Analyze archived liquid product by GC
    """

    epm = ExperimentPlanMaker()

    for source_vial in range(source_vial_from, source_vial_to+1):
        epm.add_experiment(
            "ANEC_sub_HPLCLiquid_analysis",
            {
                "source_tray": source_tray,
                "source_slot": source_slot,
                "source_vial": source_vial,
                "dest": dest,
                "volume_ul": volume_ul,
                "wash1": True,
                "wash2": True,
                "wash3": True,
                "wash4": False,
            },
        )

    return epm.experiment_plan_list