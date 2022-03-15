"""Sequence library for ANEC"""

__all__ = ["ANEC_repeat_CA_vsRHE", "ANEC_repeat_CA_vsRef"]


from typing import Optional
from helaocore.schema import ExperimentPlanMaker


SEQUENCES = __all__


def ANEC_repeat_CA_vsRHE(
    num_repeats: Optional[int] = 1,
    CA_potential_vsRHE: Optional[float] = 0.0,
    CA_duration_sec: Optional[float] = 0.1,
    solution_ph: Optional[float] = 9.0,
    ref_vs_nhe: Optional[float] = 0.21,
    SampleRate: Optional[float] = 0.01,
    TTLwait: Optional[int] = -1,
    TTLsend: Optional[int] = -1,
    IErange: Optional[str] = "auto",
    toolGC: Optional[str] = "HS 2",
    toolarchive: Optional[str] = "LS 3",
    volume_ul_GC: Optional[int] = 300,
    volume_ul_archive: Optional[int] = 500,
    wash1: Optional[bool] = True,
    wash2: Optional[bool] = True,
    wash3: Optional[bool] = True,
    wash4: Optional[bool] = False,
):
    """Repeat CA and aliquot sampling at the cell1_we position."""
    
    epm = ExperimentPlanMaker()
    for _ in range(num_repeats):
        epm.add_experiment(
            "ANEC_run_CA_vsRHE",
            {
                "CA_potential_vsRHE": CA_potential_vsRHE,
                "CA_duration_sec": CA_duration_sec,
                "solution_ph": solution_ph,
                "ref_vs_nhe": ref_vs_nhe,
                "SampleRate": SampleRate,
                "TTLwait": TTLwait,
                "TTLsend": TTLsend,
                "IErange": IErange,
                "toolGC": toolGC,
                "toolarchive": toolarchive,
                "volume_ul_GC": volume_ul_GC,
                "volume_ul_archive": volume_ul_archive,
                "wash1": wash1,
                "wash2": wash2,
                "wash3": wash3,
                "wash4": wash4,
            }
        )
    return epm.experiment_plan_list


def ANEC_repeat_CA_vsRef(
    num_repeats: Optional[int] = 1,
    CA_potential_vsRef: Optional[float] = 0.0,
    CA_duration_sec: Optional[float] = 0.1,
    ref_vs_nhe: Optional[float] = 0.21,
    SampleRate: Optional[float] = 0.01,
    TTLwait: Optional[int] = -1,
    TTLsend: Optional[int] = -1,
    IErange: Optional[str] = "auto",
    toolGC: Optional[str] = "HS 2",
    toolarchive: Optional[str] = "LS 3",
    volume_ul_GC: Optional[int] = 300,
    volume_ul_archive: Optional[int] = 500,
    wash1: Optional[bool] = True,
    wash2: Optional[bool] = True,
    wash3: Optional[bool] = True,
    wash4: Optional[bool] = False,
):
    """Repeat CA and aliquot sampling at the cell1_we position."""
    
    epm = ExperimentPlanMaker()
    for _ in range(num_repeats):
        epm.add_experiment(
            "ANEC_run_CA_vsRef",
            {
                "CA_potential_vsRef": CA_potential_vsRef,
                "CA_duration_sec": CA_duration_sec,
                "ref_vs_nhe": ref_vs_nhe,
                "SampleRate": SampleRate,
                "TTLwait": TTLwait,
                "TTLsend": TTLsend,
                "IErange": IErange,
                "toolGC": toolGC,
                "toolarchive": toolarchive,
                "volume_ul_GC": volume_ul_GC,
                "volume_ul_archive": volume_ul_archive,
                "wash1": wash1,
                "wash2": wash2,
                "wash3": wash3,
                "wash4": wash4,
            }
        )
    return epm.experiment_plan_list