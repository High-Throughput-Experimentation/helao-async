"""Sequence library for ANEC"""

__all__ = ["ANEC_daily_ready", "ANEC_repeat_CA", "ANEC_repeat_CV", "ANEC_CA_pretreat", "ANEC_photo_CA", "ANEC_gasonly_CA", "GC_Archiveliquid_analysis", "HPLC_Archiveliquid_analysis"]


from typing import Optional
from helaocore.schema import ExperimentPlanMaker


SEQUENCES = __all__

def ANEC_daily_ready(
    sequence_version: int = 1,
    num_repeats: int = 1,
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
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
    
    #clean the cell & purge with CO2
    epm.add_experiment("ANEC_slave_normal_state", {})
    epm.add_experiment("ANEC_slave_cleanup", {"reservoir_liquid_sample_no": 1})
    epm.add_experiment("ANEC_slave_cleanup", {"reservoir_liquid_sample_no": 1})
    # housekeeping
    epm.add_experiment("ANEC_slave_unload_cell", {})

    #epm.add_experiment("ANEC_slave_normal_state", {})

    epm.add_experiment(
        "ANEC_slave_load_solid",
        {"solid_plate_id": solid_plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add_experiment(
            "ANEC_slave_flush_fill_cell",
            {
                "liquid_flush_time": 90,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_slave_CA",
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


        epm.add_experiment("ANEC_slave_drain_cell", {"drain_time": 50.0})

    return epm.experiment_plan_list


def ANEC_CA_pretreat(
    sequence_version: int = 1,
    num_repeats: int = 1,
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
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
    epm.add_experiment("ANEC_slave_unload_cell", {})

    #epm.add_experiment("ANEC_slave_normal_state", {})

    epm.add_experiment(
        "ANEC_slave_load_solid",
        {"solid_plate_id": solid_plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add_experiment(
            "ANEC_slave_flush_fill_cell",
            {
                "liquid_flush_time": 90,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_slave_CA",
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


        epm.add_experiment("ANEC_slave_drain_cell", {"drain_time": 50.0})

    return epm.experiment_plan_list


def ANEC_repeat_CA(
    sequence_version: int = 1,
    num_repeats: int = 1,
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1,
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
    epm.add_experiment("ANEC_slave_unload_cell", {})

    #epm.add_experiment("ANEC_slave_normal_state", {})

    epm.add_experiment(
        "ANEC_slave_load_solid",
        {"solid_plate_id": solid_plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add_experiment(
            "ANEC_slave_flush_fill_cell",
            {
                "liquid_flush_time": 80,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_slave_CA",
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
            "ANEC_slave_aliquot",
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

        epm.add_experiment("ANEC_slave_drain_cell", {"drain_time": 50.0})

    return epm.experiment_plan_list

def ANEC_gasonly_CA(
    sequence_version: int = 1,
    num_repeats: int = 1,
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1,
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
    epm.add_experiment("ANEC_slave_unload_cell", {})

    #epm.add_experiment("ANEC_slave_normal_state", {})

    epm.add_experiment(
        "ANEC_slave_load_solid",
        {"solid_plate_id": solid_plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add_experiment(
            "ANEC_slave_flush_fill_cell",
            {
                "liquid_flush_time": 80,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_slave_CA",
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
            "ANEC_slave_GC_preparation",
            {
                "toolGC": toolGC,
                "volume_ul_GC": volume_ul_GC,
            },
        )

        epm.add_experiment("ANEC_slave_drain_cell", {"drain_time": 50.0})

    return epm.experiment_plan_list

def ANEC_photo_CA(
    sequence_version: int = 1,
    num_repeats: int = 1,
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1,
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
    epm.add_experiment("ANEC_slave_unload_cell", {})

    #epm.add_experiment("ANEC_slave_normal_state", {})

    epm.add_experiment(
        "ANEC_slave_load_solid",
        {"solid_plate_id": solid_plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add_experiment(
            "ANEC_slave_flush_fill_cell",
            {
                "liquid_flush_time": 80,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_slave_photo_CA",
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
            "ANEC_slave_aliquot",
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

        epm.add_experiment("ANEC_slave_drain_cell", {"drain_time": 50.0})

    return epm.experiment_plan_list

def ANEC_repeat_CV(
    sequence_version: int = 1,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    num_repeats: int = 1,
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1,
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
    epm.add_experiment("ANEC_slave_unload_cell", {})

    #epm.add_experiment("ANEC_slave_normal_state", {})

    epm.add_experiment(
        "ANEC_slave_load_solid",
        {"solid_plate_id": solid_plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add_experiment(
            "ANEC_slave_flush_fill_cell",
            {
                "liquid_flush_time": 80,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment(
            "ANEC_slave_CV",
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

        epm.add_experiment("ANEC_slave_drain_cell", {"drain_time": 50.0})

    return epm.experiment_plan_list

def GC_Archiveliquid_analysis(
    experiment_version: int = 1,
    source_tray: int = 2,
    source_slot: int = 1,
    source_vial_from: int = 1,
    source_vial_to: int = 1,
    dest: str = "Injector 1",
    volume_ul: int = 2,
):
    """
    Analyze archived liquid product by GC
    """

    epm = ExperimentPlanMaker()

    for source_vial in range(source_vial_from, source_vial_to+1):
        epm.add_experiment(
            "ANEC_slave_GCLiquid_analysis",
            {
                "source_tray": source_tray,
                "source_slot": source_slot,
                "source_vial": source_vial,
                "dest": dest,
                "volume_ul": volume_ul,
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
            "ANEC_slave_HPLCLiquid_analysis",
            {
                "source_tray": source_tray,
                "source_slot": source_slot,
                "source_vial": source_vial,
                "dest": dest,
                "volume_ul": volume_ul,
            },
        )

    return epm.experiment_plan_list