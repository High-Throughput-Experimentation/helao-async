"""Sequence library for CCSI"""

__all__ = [
    "ECMS_series_CA",
    "ECMS_repeat_CV",

]

from typing import List
from typing import Optional, Union
from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__


def ECMS_series_CA(
    sequence_version: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,    
    reservoir_liquid_sample_no: int = 2,
    volume_ul_cell_liquid: float = 1400,
    liquid_forward_time: float = 50,
    liquid_backward_time: float = 20,  
    vacuum_time: float = 10,   
    CO2equilibrium_duration: float = 30,
    flowrate_sccm: float = 5.0,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration: float = 120,  
    WE_potential__V: List[float] = [-1.4, -1.6, -1.8, -1.9, -2.0],
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 7.8,
    CA_duration_sec: List[float] = [600, 600, 600, 600, 600],
    SampleRate: float = 1,
    IErange: str = "30mA",
    ref_offset__V: float = 0.0,
    liquid_drain_time: float = 60.0,   
    liquid_cleancell_time: float = 120,
):

    
    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ECMS_sub_unload_cell", {})
    epm.add_experiment(
        "ECMS_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for cycle, (potential, time) in enumerate(zip(WE_potential__V, CA_duration_sec)):
        print(f" ... cycle {cycle} potential:", potential, f" ... cycle {cycle} duration:", time)

        epm.add_experiment(
            "ECMS_sub_electrolyte_fill_cell",
            {
                "liquid_forward_time": liquid_forward_time,
                "liquid_backward_time": liquid_backward_time,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment("ECMS_sub_prevacuum_cell",{"vacuum_time": vacuum_time})

        epm.add_experiment(
            "ECMS_sub_headspace_purge_and_CO2baseline",
            {
                "CO2equilibrium_duration": CO2equilibrium_duration,
                "flowrate_sccm": flowrate_sccm,
                "flow_ramp_sccm": flow_ramp_sccm,
                "MS_baseline_duration": MS_baseline_duration
            },
        )
        
        epm.add_experiment(
            "ECMS_sub_CA",
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
        epm.add_experiment("ECMS_sub_headspace_flow_shutdown",{})
        epm.add_experiment("ECMS_sub_drain", {"liquid_drain_time": liquid_drain_time})      
        epm.add_experiment("ECMS_sub_electrolyte_clean_cell", {"liquid_backward_time": liquid_cleancell_time, "reservoir_liquid_sample_no":reservoir_liquid_sample_no})    
    epm.add_experiment("ECMS_sub_alloff", {})
    
    return epm.experiment_plan_list





def ECMS_repeat_CV(
    sequence_version: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,    
    reservoir_liquid_sample_no: int = 2,
    volume_ul_cell_liquid: float = 1400,
    liquid_forward_time: float = 50,
    liquid_backward_time: float = 20,   
    vacuum_time: float = 10,   
    CO2equilibrium_duration: float = 30,
    flowrate_sccm: float = 5.0,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration: float = 120,    
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    num_repeats: int = 1,
    WE_potential_init__V: float = 0.0,
    WE_potential_apex1__V: float = -1.0,
    WE_potential_apex2__V: float = -1.0,
    WE_potential_final__V: float = 0.0,
    ScanRate_V_s: float = 0.05,
    Cycles: int = 1,
    SampleRate: float = 0.1,
    IErange: str = "auto",
    ref_offset: float = 0.0,  
    liquid_drain_time: float = 60.0,    
    liquid_cleancell_time: float = 120,
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
    epm.add_experiment("ECMS_sub_unload_cell", {})
    epm.add_experiment(
        "ECMS_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add_experiment(
            "ECMS_sub_electrolyte_fill_cell",
            {
                "liquid_forward_time": liquid_forward_time,
                "liquid_backward_time": liquid_backward_time,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )
        epm.add_experiment("ECMS_sub_prevacuum_cell",{"vacuum_time": vacuum_time})

        epm.add_experiment(
            "ECMS_sub_headspace_purge_and_CO2baseline",
            {
                "CO2equilibrium_duration": CO2equilibrium_duration,
                "flowrate_sccm": flowrate_sccm,
                "flow_ramp_sccm": flow_ramp_sccm,
                "MS_baseline_duration": MS_baseline_duration
            },
        )

        epm.add_experiment(
            "ECMs_sub_CV",
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

        epm.add_experiment("ECMS_sub_headspace_flow_shutdown",{})
        epm.add_experiment("ECMS_sub_drain", {"liquid_drain_time": liquid_drain_time})        
        epm.add_experiment("ECMS_sub_electrolyte_clean_cell", {"liquid_backward_time": liquid_cleancell_time, "reservoir_liquid_sample_no":reservoir_liquid_sample_no})
    
    epm.add_experiment("ECMS_sub_alloff", {})
    return epm.experiment_plan_list








