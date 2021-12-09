"""
Sequence library for ADSS
"""

__all__ = [
           "ADSS_duaribilty_CAv1",
           "ADSS_tray_unload"
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
              CA_potentials_vsRHE: List[float] = [-0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
              ph: float = 9.53,
              ref_vs_nhe: float = 0.21,
              CA_duration_sec: float = 1320, 
              aliquot_times_sec: List[float] = [60,600,1140],
              OCV_duration_sec: float = 60, 
              samplerate_sec: float = 1, 
              filltime_sec: float = 10.0
              ):
           
    """tbd
        
       last functionality test: tbd"""

    pl = SequenceListMaker()
    
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

    for cycle, potential in enumerate(CA_potentials_vsRHE):
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
                       "ADSS_slave_CA", 
                       {"CA_potential":potential,
                        "ph":ph,
                        "ref_vs_nhe":ref_vs_nhe,
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


def ADSS_tray_unload(
                     tray: int = 2,
                     slot: int = 1,
                     survey_runs: int = 1,
                     main_runs: int = 3,
                     rack: int = 2,
                    ):
    """Unloads a selected tray from PAL position tray-slot and creates
    (1) json
    (2) csv
    (3) icpms
    exports.

    Parameters for ICPMS export are
    survey_runs: rough sweep over the whole mass range
    main_runs: sweep channel centered on element mass
    rack: position of the tray in the icpms instrument, usually 2.
    """
    pl = SequenceListMaker()
    
    pl.add_process(
                   "ADSS_slave_tray_unload", 
                   {"tray":tray,
                    "slot":slot,
                    "survey_runs":survey_runs,
                    "main_runs":main_runs,
                    "rack":rack,
                    }
                   )


    return pl.process_list # returns complete process list
