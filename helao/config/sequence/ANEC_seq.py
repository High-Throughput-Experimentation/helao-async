"""Sequence library for ANEC"""

__all__ = ["ANEC_repeat_CA_vsRef"]


from typing import Optional
from helaocore.schema import ExperimentPlanMaker


SEQUENCES = __all__


def ANEC_repeat_CA_vsRef(
    num_repeats: int = 1,
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1,

    volume_ul_cell_liquid: float = 1000,

    CA_potential_vsRef: float = 0.0,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_vs_nhe: float = 0.21,

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
    
    epm.add_experiment(
        "ANEC_slave_unload_cell",
        {
        }
    )

    epm.add_experiment(
        "ANEC_slave_normal_state",
        {
        }
    )

    epm.add_experiment(
        "ANEC_slave_load_solid",
        {
        "solid_plate_id":solid_plate_id,
        "solid_sample_no":solid_sample_no
        }
    )

    for _ in range(num_repeats):

        epm.add_experiment(
            "ANEC_slave_flush_fill_cell",
            {
             "liquid_flush_time":90,
             "co2_purge_time":15,
             "equilibration_time":1.0,
             "reservoir_liquid_sample_no":reservoir_liquid_sample_no,
             "volume_ul_cell_liquid":volume_ul_cell_liquid,


            }
        )

        epm.add_experiment(
            "ANEC_slave_CA_vsRef",
            {
            "CA_potential_vsRef":CA_potential_vsRef,
            "CA_duration_sec":CA_duration_sec,
            "SampleRate":SampleRate,
            "IErange":IErange,
            }
        )


        epm.add_experiment(
            "ANEC_slave_aliquot",
            {
            "toolGC":toolGC,
            "toolarchive":toolarchive,
            "volume_ul_GC":volume_ul_GC,
            "volume_ul_archive":volume_ul_archive,
            "wash1":wash1,
            "wash2":wash2,
            "wash3":wash3,
            "wash4":wash4,
            }
        )


        epm.add_experiment(
            "ANEC_slave_drain_cell",
            {
             "drain_time":60.0
            }
        )

        epm.add_experiment(
            "ANEC_slave_normal_state",
            {
            }
        )


    return epm.experiment_plan_list