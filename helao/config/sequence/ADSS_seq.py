"""
Sequence library for ADSS
"""

__all__ = [
           "ADSS_duaribilty_CAv1", 
          ]


from typing import List
from helaocore.schema import SequenceListMaker


SEQUENCES = __all__

def ADSS_duaribilty_CAv1(
              solid_custom_position: str = "cell1_we",
              solid_plate_id: int = 4534,
              solid_sample_no: int = 1,
              x_mm: float = 0.0, 
              y_mm: float = 0.0,
              liquid_custom_position: str = "elec_res1",
              liquid_sample_no: int = 3,
              pH: float = 9.53,
              CA_potentials_vsRHE: List[float] = [-0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
              CA_duration_sec: float = 1320, 
              aliquot_times_sec: List[float] = [60,600,1140],
              OCV_duration_sec: float = 60, 
              samplerate_sec: float = 1, 
              ref_vs_nhe: float = 0.21,
              filltime_sec: float = 10.0
              ):
           
    """tbd
        
       last functionality test: tbd"""

    pl = SequenceListMaker()
    potentials = [pot-1.0*ref_vs_nhe-0.059*pH  for pot in CA_potentials_vsRHE]
    
    
    pl.add_process(
                   "ADSS_slave_startup", 
                   {"x_mm":x_mm,
                    "y_mm":y_mm,
                    "solid_custom_position":solid_custom_position,
                    "solid_plate_id":solid_plate_id,
                    "solid_sample_no":solid_sample_no,
                    "liquid_custom_position":liquid_custom_position,
                    "liquid_sample_no":liquid_sample_no
                    }
                   )

    for cycle, potential in enumerate(potentials):
        print(f" ... cycle {cycle} potential:", potential)
        if cycle == 0:
            pl.add_process(
                           "ADSS_slave_fillfixed", 
                           {"fill_vol_ul":10000,
                            "filltime_sec":filltime_sec
                            }
                           )
            
        else:    
            pl.add_process(
                           "ADSS_slave_fill", 
                           {"fill_vol_ul":1000}
                          )


        pl.add_process(
                       "ADSS_slave_single_CA", 
                       {"CA_single_potential":potential,
                        "samplerate_sec":samplerate_sec,
                        "OCV_duration_sec":OCV_duration_sec,
                        "CA_duration_sec":CA_duration_sec,
                        "aliquot_times_sec":aliquot_times_sec
                        }
                       )

    pl.add_process(
                   "ADSS_slave_shutdown", 
                   {}
                   )

    return pl.process_list # returns complete process list
