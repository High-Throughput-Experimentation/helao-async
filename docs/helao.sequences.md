# helao.sequences package

## Submodules

## helao.sequences.ADSS_seq module

Sequence library for ADSS

### helao.sequences.ADSS_seq.ADSS_CA_cell_1potential(sequence_version=8, plate_id=5917, plate_sample_no=14050, same_sample=False, stay_sample=False, liquid_sample_no=220, liquid_sample_volume_ul=4000, CA_potential_vs=-0.2, potential_versus='oer', ph=9.53, ref_type='leakless', ref_offset_\_V=0.0, CA_duration_sec=1320, aliquot_tf=True, aliquot_times_sec=[60, 600, 1140], aliquot_volume_ul=200, insert_electrolyte_bool=False, insert_electrolyte_ul=0, insert_electrolyte_time_sec=1800, keep_electrolyte=False, use_electrolyte=False, OCV_duration=60, OCValiquot_times_sec=[20], samplerate_sec=1, led_illumination=False, led_dutycycle=1, led_wavelength='385', Syringe_rate_ulsec=300, Cell_draintime_s=60, ReturnLineWait_s=30, ReturnLineReverseWait_s=3, ResidualWait_s=15, flush_volume_ul=2000, clean=False, clean_volume_ul=5000, refill=False, refill_volume_ul=6000, water_refill_volume_ul=6000, PAL_Injector='LS 4', PAL_Injector_id='LS4_newsyringe040923')

tbd

last functionality test: tbd

### helao.sequences.ADSS_seq.ADSS_PA_CV_TRI(sequence_version=4, plate_id=6307, plate_id_ref_Pt=6173, plate_sample_no_list=[16304], LPL_list=[0.05, 0.55, 0.05, 0.55], UPL_list=[1.3, 0.8, 1.3, 0.8], same_sample=False, use_bubble_removal=True, use_current_electrolyte=False, pump_reversal_during_filling=False, keep_electrolyte_at_end=False, move_to_clean_and_clean=True, measure_ref_Pt_at_beginning=True, name_ref_Pt_at_beginning='builtin_ref_motorxy_2', measure_ref_Pt_at_end=True, name_ref_Pt_at_end='builtin_ref_motorxy_3', bubble_removal_OCV_t_s=10, bubble_removal_pump_reverse_t_s=15, bubble_removal_pump_forward_t_s=10, bubble_removal_RSD_threshold=0.2, bubble_removal_simple_threshold=0.3, bubble_removal_signal_change_threshold=0.01, bubble_removal_amplitude_threshold=0.05, purge_wait_initialN2_min=10, purge_wait_N2_to_O2_min=5, purge_wait_O2_to_N2_min=15, rinse_with_electrolyte_bf_prefill=True, rinse_with_electrolyte_bf_prefill_volume_uL=3000, rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec=30, rinse_with_electrolyte_bf_prefill_drain_time_sec=30, ph=1.24, liquid_sample_no=1053, liquid_sample_volume_ul=7000, Syringe_rate_ulsec=300, fill_recirculate_wait_time_sec=30, fill_recirculate_reverse_wait_time_sec=15, Inject_PA=True, phosphoric_sample_no=1261, phosphoric_location=[2, 3, 54], phosphoric_quantity_ul=90, inject_recirculate_wait_time_sec=60, ref_CV_cycles=[8], ref_Vinit_vsRHE=0.05, ref_Vapex1_vsRHE=1.3, ref_Vapex2_vsRHE=0.05, ref_Vfinal_vsRHE=0.05, ref_CV_scanrate_voltsec=0.1, ref_CV_samplerate_sec=0.01, cleaning_CV_cycles=[20], cleaning_Vinit_vsRHE=[0.05], cleaning_Vapex1_vsRHE=[1.5], cleaning_Vapex2_vsRHE=[0.05], cleaning_Vfinal_vsRHE=[0.05], cleaning_scanrate_voltsec=[0.2], cleaning_CV_samplerate_sec=0.02, testing_CV_scanrate_voltsec=0.1, testing_CV_samplerate_sec=0.01, CV_N2_cycles=[5], CV_O2_cycles=[5, 25, 50], OCP_samplerate_sec=0.5, gamry_i_range='auto', ref_type='leakless', ref_offset_\_V=-0.005, aliquot_init=True, aliquot_after_cleaningCV=[0], aliquote_after_CV_init=[1], aliquote_CV_O2=[1, 1, 1], aliquote_CV_final=[0], aliquot_volume_ul=100, PAL_Injector='LS 4', PAL_Injector_id='LS4_peek', cell_draintime_sec=60, ReturnLineReverseWait_sec=5, number_of_cleans=2, clean_volume_ul=12000, clean_recirculate_sec=60, clean_drain_sec=120)

This sequence is the most recent one for the TRI Pt dissolution project using ADSS.
Included features:
- scheduled aliquotes and injection of phosphoric acid
- track gas saturation with OCV during N2-O2 and O2-N2 switches
- automatic refill of syringes
- you can define number of cleaning cycles (to make sure we are cleaning off Co and Ni residues)
- include reference Pt measurements before and after sequence
- generating sample-LPL-UPL combinations
- bubble removal using OCV. bubble removal = reversal of pumps for some seconds

### helao.sequences.ADSS_seq.ADSS_PA_CV_TRI_new(sequence_version=6, plate_id=6307, plate_id_ref_Pt=6173, plate_sample_no_list=[16304], LPL_list=[0.05, 0.55, 0.05, 0.55], UPL_list=[1.3, 0.8, 1.3, 0.8], same_sample=False, aliquot_init=True, Inject_PA=True, use_bubble_removal=True, rinse_with_electrolyte_bf_prefill=True, use_current_electrolyte=False, pump_reversal_during_filling=False, keep_electrolyte_at_end=False, move_to_clean_and_clean=True, measure_ref_Pt_at_beginning=True, name_ref_Pt_at_beginning='builtin_ref_motorxy_2', measure_ref_Pt_at_end=True, name_ref_Pt_at_end='builtin_ref_motorxy_3', bubble_removal_OCV_t_s=10, bubble_removal_pump_reverse_t_s=15, bubble_removal_pump_forward_t_s=10, bubble_removal_RSD_threshold=0.2, bubble_removal_simple_threshold=0.3, bubble_removal_signal_change_threshold=0.01, bubble_removal_amplitude_threshold=0.05, purge_wait_initialN2_min=10, purge_wait_N2_to_O2_min=5, purge_wait_O2_to_N2_min=15, rinse_with_electrolyte_bf_prefill_volume_uL=3000, rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec=30, rinse_with_electrolyte_bf_prefill_drain_time_sec=30, ph=1.24, liquid_sample_no=1053, liquid_sample_volume_ul=7000, Syringe_rate_ulsec=300, fill_recirculate_wait_time_sec=30, fill_recirculate_reverse_wait_time_sec=15, phosphoric_sample_no=1261, phosphoric_location=[2, 3, 54], phosphoric_quantity_ul=90, inject_recirculate_wait_time_sec=60, phos_PAL_Injector='LS 5', phos_PAL_Injector_id='LS5_peek', ref_CV_cycles=[8], ref_Vinit_vsRHE=0.05, ref_Vapex1_vsRHE=1.3, ref_Vapex2_vsRHE=0.05, ref_Vfinal_vsRHE=0.05, ref_CV_scanrate_voltsec=0.1, ref_CV_samplerate_sec=0.01, cleaning_CV_cycles=[20], cleaning_Vinit_vsRHE=[0.05], cleaning_Vapex1_vsRHE=[1.5], cleaning_Vapex2_vsRHE=[0.05], cleaning_Vfinal_vsRHE=[0.05], cleaning_scanrate_voltsec=[0.2], cleaning_CV_samplerate_sec=0.02, testing_CV_scanrate_voltsec=0.1, testing_CV_samplerate_sec=0.01, CV_N2_cycles=[5], CV_O2_cycles=[5, 25, 50], OCP_samplerate_sec=0.5, gamry_i_range='auto', ref_type='leakless', ref_offset_\_V=-0.005, aliquot_after_cleaningCV=[0], aliquote_after_CV_init=[1], aliquote_CV_O2=[1, 1, 1], aliquote_CV_final=[0], aliquot_volume_ul=100, PAL_Injector='LS 4', PAL_Injector_id='LS4_peek', cell_draintime_sec=60, ReturnLineReverseWait_sec=5, number_of_cleans=2, clean_volume_ul=12000, clean_recirculate_sec=60, clean_drain_sec=120)

This sequence is the most recent one for the TRI Pt dissolution project using ADSS.
Included features:
- scheduled aliquotes and injection of phosphoric acid
- track gas saturation with OCV during N2-O2 and O2-N2 switches
- automatic refill of syringes
- you can define number of cleaning cycles (to make sure we are cleaning off Co and Ni residues)
- include reference Pt measurements before and after sequence
- generating sample-LPL-UPL combinations
- bubble removal using OCV. bubble removal = reversal of pumps for some seconds

### helao.sequences.ADSS_seq.ADSS_PA_CVs_CAs_CVs_autogasswitching(sequence_version=1, plate_id=6307, plate_sample_no=14050, same_sample=False, use_electrolyte=False, keep_electrolyte=False, liquid_sample_no=1053, liquid_sample_volume_ul=4000, phosphoric_sample_no=99999, phosphoric_location=[2, 2, 54], phosphoric_quantity_ul=0, recirculate_wait_time_m=5, postN2_recirculate_wait_time_m=5, CleaningCV_cycles=6, CleaningCV_Vinit_vsRHE=0.05, CleaningCV_Vapex2_vsRHE=1.5, CleaningCV_scanrate_voltsec=0.1, CV_cycles=[10, 3], Vinit_vsRHE=[0.05, 0.05, 0.05], Vapex1_vsRHE=[0.05, 0.05, 0.05], Vapex2_vsRHE=[1.2, 1.2, 1.2], Vfinal_vsRHE=[0.05, 0.05, 0.05], scanrate_voltsec=[0.1, 0.02, 0.02], CV_samplerate_sec=0.05, CA_potentials_vs=[0.6, 0.4], potential_versus='rhe', CA_duration_sec=[60, 60], CA_samplerate_sec=0.1, CV2_cycles=[3], CV2_Vinit_vsRHE=[0.05], CV2_Vapex1_vsRHE=[0.05], CV2_Vapex2_vsRHE=[1.2], CV2_Vfinal_vsRHE=[0.05], CV2_scanrate_voltsec=[0.02], CV2_samplerate_sec=0.05, gamry_i_range='auto', ph=1.24, ref_type='leakless', ref_offset_\_V=0.0, aliquot_init=True, aliquot_postCV=[1, 0, 0], aliquot_postCA=[1, 0], aliquot_volume_ul=100, Syringe_rate_ulsec=300, Cell_draintime_s=60, ReturnLineReverseWait_s=10, clean_cell=False, Clean_volume_ul=12000, CleanDrainWait_s=80, PAL_Injector='LS 4', PAL_Injector_id='LS4_peek')

tbd

last functionality test: tbd

### helao.sequences.ADSS_seq.ADSS_PA_CVs_CAs_CVs_cell_simple(sequence_version=8, plate_id=5917, plate_sample_no=[16304], same_sample=False, keep_electrolyte=False, use_electrolyte=False, Move_to_clean_and_clean=True, liquid_sample_no=220, liquid_sample_volume_ul=4000, recirculate_wait_time_m=0.5, recirculate_reverse_wait_time_s=1, CV_cycles=[5, 3, 3], Vinit_vsRHE=[1.23, 1.23, 1.23], Vapex1_vsRHE=[1.23, 1.23, 1.23], Vapex2_vsRHE=[0.6, 0.4, 0], Vfinal_vsRHE=[0.6, 0.4, 0], scanrate_voltsec=[0.02, 0.02, 0.02], CV_samplerate_sec=0.05, number_of_postCAs=2, CA_potentials_vs=[0.6, 0.4], potential_versus='rhe', CA_duration_sec=[60, 60], CA_samplerate_sec=0.1, CV2_cycles=[5, 3, 3], CV2_Vinit_vsRHE=[1.23, 1.23, 1.23], CV2_Vapex1_vsRHE=[1.23, 1.23, 1.23], CV2_Vapex2_vsRHE=[0.6, 0.4, 0], CV2_Vfinal_vsRHE=[0.6, 0.4, 0], CV2_scanrate_voltsec=[0.02, 0.02, 0.02], CV2_samplerate_sec=0.05, gamry_i_range='auto', ph=1.24, ref_type='leakless', ref_offset_\_V=0.0, aliquot_init=True, aliquot_postCV=[1, 0, 0], aliquot_postCA=[1, 0], aliquot_volume_ul=200, Syringe_rate_ulsec=300, Cell_draintime_s=60, ReturnLineReverseWait_s=10, Clean_volume_ul=12000, Clean_recirculate_s=30, Clean_drain_s=60, PAL_Injector='LS 4', PAL_Injector_id='LS4_peek')

tbd

last functionality test: tbd

### helao.sequences.ADSS_seq.ADSS_PA_CVs_CAs_cell(sequence_version=5, plate_id=5917, plate_sample_no=14050, same_sample=False, stay_sample=False, liquid_sample_no=220, liquid_sample_volume_ul=4000, recirculate_wait_time_m=0.5, CV_cycles=[5, 3, 3], Vinit_vsRHE=[1.23, 1.23, 1.23], Vapex1_vsRHE=[1.23, 1.23, 1.23], Vapex2_vsRHE=[0.6, 0.4, 0], Vfinal_vsRHE=[0.6, 0.4, 0], scanrate_voltsec=[0.02, 0.02, 0.02], CV_samplerate_sec=0.05, number_of_postCAs=2, CA_potentials_vs=[0.6, 0.4], potential_versus='rhe', CA_duration_sec=[60, 60], CA_samplerate_sec=0.1, gamry_i_range='auto', ph=9.53, ref_type='leakless', ref_offset_\_V=0.0, aliquot_postCV=[1, 0, 0], aliquot_postCA=[1, 0], aliquot_volume_ul=200, Syringe_rate_ulsec=300, Drain=False, Cell_draintime_s=60, ReturnLineWait_s=30, ReturnLineReverseWait_s=3, ResidualWait_s=15, flush_volume_ul=2000, clean=False, clean_volume_ul=5000, refill=False, refill_volume_ul=6000, water_refill_volume_ul=6000, PAL_Injector='LS 4', PAL_Injector_id='LS4_newsyringe040923')

tbd

last functionality test: tbd

### helao.sequences.ADSS_seq.ADSS_PA_CVs_testing(sequence_version=1, plate_id=6307, plate_sample_no=14050, second_sample_no=14050, same_sample=False, keep_electrolyte=False, keep_electrolyte_post=False, use_electrolyte=False, liquid_sample_no=220, liquid_sample_volume_ul=4000, recirculate_wait_time_m=5, CV_cycles=[10, 3], Vinit_vsRHE=[0.05, 0.05, 0.05], Vapex1_vsRHE=[0.05, 0.05, 0.05], Vapex2_vsRHE=[1.2, 1.2, 1.2], Vfinal_vsRHE=[0.05, 0.05, 0.05], scanrate_voltsec=[0.1, 0.02, 0.02], CV_samplerate_sec=0.05, potential_versus='rhe', CV2_cycles=[3], CV2_Vinit_vsRHE=[0.05], CV2_Vapex1_vsRHE=[0.05], CV2_Vapex2_vsRHE=[1.2], CV2_Vfinal_vsRHE=[0.05], CV2_scanrate_voltsec=[0.02], CV2_samplerate_sec=0.05, gamry_i_range='auto', ph=9.53, ref_type='leakless', ref_offset_\_V=0.0, Syringe_rate_ulsec=300, Cell_draintime_s=60, ReturnLineReverseWait_s=10, Clean_volume_ul=6000, CleanDrainWait_s=60, PAL_Injector='LS 4', PAL_Injector_id='LS4_newsyringe040923')

tbd

last functionality test: tbd

## helao.sequences.ANEC_seq module

Sequence library for ANEC

### helao.sequences.ANEC_seq.ANEC_CA_DOE_demo(sequence_version=1, plate_id=4534, solid_sample_no=1, WE_potential_\_V=0.0, WE_versus='ref', ref_type='leakless', pH=6.8, CA_duration_sec=0.1, SampleRate=0.01, IErange='auto', ref_offset_\_V=0.0, toolGC='HS 2', toolarchive='LS 3', volume_ul_GC=300, volume_ul_archive=500, wash1=True, wash2=True, wash3=True, wash4=False, liquidDrain_time=60.0)

Repeat CA and aliquot sampling at the cell1_we position.

Flush and fill cell, run CA, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds
3. run CA
4. mix product
5. Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_CA_DOE_demo_headspace(sequence_version=1, plate_id=4534, solid_sample_no=1, WE_potential_\_V=0.0, WE_versus='ref', ref_type='leakless', pH=6.8, CA_duration_sec=0.1, SampleRate=0.01, IErange='auto', ref_offset_\_V=0.0, toolGC='HS 2', volume_ul_GC=300, liquidDrain_time=60.0)

Repeat CA and aliquot sampling at the cell1_we position.

Flush and fill cell, run CA, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds
3. run CA
4. mix product
5. Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_CA_pretreat(sequence_version=1, num_repeats=1, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=1511, volume_ul_cell_liquid=1000, WE_potential_\_V=0.0, WE_versus='ref', ref_type='leakless', pH=6.8, CA_duration_sec=0.1, SampleRate=0.01, IErange='auto', ref_offset_\_V=0.0, liquid_flush_time=70.0, liquidDrain_time=50.0)

Repeat CA and aliquot sampling at the cell1_we position.

Flush and fill cell, run CA, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds
3. run CA
4. Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_OCV(sequence_version=1, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=1511, volume_ul_cell_liquid=1000, Tval_\_s=900.0, IErange='auto', toolarchive='LS 3', volume_ul_archive=500, liquidDrain_time=80.0, wash1=True, wash2=True, wash3=True, wash4=False)

running CA at different potentials and aliquot sampling at the cell1_we position.

Flush and fill cell, run CA, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds
3. run CA
4. mix product
5. Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_cleanup_disengage(sequence_version=1)

fulsh and sicharge the cell

### helao.sequences.ANEC_seq.ANEC_create_and_load_liquid_sample(volume_ml=0.84, source=['autoGDE'], partial_molarity=['unknown'], chemical=['unknown'], ph=7.8, supplier=['N/A'], lot_number=['N/A'], electrolyte_name='1M KHCO3', prep_date='2024-03-19', tray=2, slot=1, vial=[1, 2, 3, 4, 5])

### helao.sequences.ANEC_seq.ANEC_ferricyanide_protocol(sequence_version=2, plate_id=5740, solid_sample_no=1, reservoir_liquid_sample_no=1511, volume_ul_cell_liquid=1000, WE_potential_\_V=-0.8, WE_versus='ref', ref_type='leakless', pH=6.8, CA_duration_sec=120.0, SampleRate_CA=0.5, IErange='3mA', ref_offset_\_V=0.0, WE_potential_init_\_V=0.5, WE_potential_apex1_\_V=-1.0, WE_potential_apex2_\_V=0.5, WE_potential_final_\_V=0.5, ScanRate_V_s=0.1, Cycles=1, SampleRate_CV=0.1, liquidDrain_time=80.0, target_temperature_degc=[25.0], CV_only='yes')

Repeat CA and aliquot sampling at the cell1_we position.

Flush and fill cell, run CA, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds
3. run CA
4. mix product
5. Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_ferricyanide_simpleprotocol(sequence_version=2, num_repeats=1, plate_id=5740, solid_sample_no=1, reservoir_liquid_sample_no=1511, volume_ul_cell_liquid=1000, WE_potential_\_V=-0.8, WE_versus='ref', ref_type='leakless', pH=6.8, CA_duration_sec=120.0, SampleRate_CA=0.5, IErange='3mA', ref_offset_\_V=0.0, WE_potential_init_\_V=0.5, WE_potential_apex1_\_V=-1.0, WE_potential_apex2_\_V=0.5, WE_potential_final_\_V=0.5, ScanRate_V_s=0.1, Cycles=1, SampleRate_CV=0.1, target_temperature_degc=25.0)

Repeat CA and aliquot sampling at the cell1_we position.

Flush and fill cell, run CA, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds
3. run CA
4. mix product
5. Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_gasonly_CA(sequence_version=1, num_repeats=1, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=1511, volume_ul_cell_liquid=1000, WE_potential_\_V=0.0, WE_versus='ref', ref_type='leakless', pH=6.8, CA_duration_sec=0.1, SampleRate=0.01, IErange='auto', ref_offset_\_V=0.0, toolGC='HS 2', volume_ul_GC=300, liquid_flush_time=70.0, liquidDrain_time=60.0)

Repeat CA and aliquot sampling at the cell1_we position.

Flush and fill cell, run CA, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds
3. run CA
4. mix product
5. Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_heatOCV(sequence_version=1, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=1511, volume_ul_cell_liquid=1000, Tval_\_s=900.0, IErange='auto', liquid_flush_time=60.0, liquidDrain_time=60.0, target_temperature_degc=25.0)

running CA at different potentials and aliquot sampling at the cell1_we position.

Flush and fill cell, run CA, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds
3. run CA
4. mix product
5. Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_photo_CA(sequence_version=3, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=1511, volume_ul_cell_liquid=1000, WE_potential_\_V=[-0.9, -1.0, -1.1, -1.2, -1.3], WE_versus='ref', ref_type='leakless', pH=6.8, CA_duration_sec=[900, 900, 900, 900, 900], SampleRate=0.01, IErange='auto', gamrychannelwait=-1, gamrychannelsend=0, ref_offset_\_V=0.0, led_wavelengths_nm=450.0, led_type='front', led_date='01/01/2000', led_intensities_mw=9.0, led_name_CA='Thorlab_led', toggleCA_illum_duty=0.5, toggleCA_illum_period=1.0, toggleCA_dark_time_init=0, toggleCA_illum_time=-1, toolGC='HS 2', toolarchive='LS 3', volume_ul_GC=300, volume_ul_archive=500, wash1=True, wash2=True, wash3=True, wash4=False, liquid_flush_time=60.0, liquidDrain_time=80.0)

Repeat CA and aliquot sampling at the cell1_we position.

Flush and fill cell, run CA, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds
3. run CA
4. mix product
5. Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_photo_CAgasonly(sequence_version=3, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=1511, volume_ul_cell_liquid=1000, WE_potential_\_V=[-0.2, -0.3, -0.4, -0.5, -0.6], WE_versus='ref', ref_type='leakless', pH=6.8, CA_duration_sec=[600, 600, 600, 600, 600], SampleRate=0.01, IErange='auto', gamrychannelwait=-1, gamrychannelsend=0, ref_offset_\_V=0.0, led_wavelengths_nm=450.0, led_type='front', led_date='01/01/2000', led_intensities_mw=9.0, led_name_CA='Thorlab_led', toggleCA_illum_duty=0.5, toggleCA_illum_period=1.0, toggleCA_dark_time_init=0, toggleCA_illum_time=-1, toolGC='HS 2', volume_ul_GC=300, liquid_flush_time=60.0, liquidDrain_time=80.0)

Repeat CA and aliquot sampling at the cell1_we position.

Flush and fill cell, run CA, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds
3. run CA
4. mix product
5. Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_photo_CV(sequence_version=1, WE_versus='ref', ref_type='leakless', pH=6.8, num_repeats=1, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=1511, volume_ul_cell_liquid=1000, WE_potential_init_\_V=0.0, WE_potential_apex1_\_V=-1.0, WE_potential_apex2_\_V=-1.0, WE_potential_final_\_V=0.0, ScanRate_V_s=0.01, Cycles=1, SampleRate=0.01, IErange='auto', gamrychannelwait=-1, gamrychannelsend=0, ref_offset=0.0, led_wavelengths_nm=450.0, led_type='front', led_date='01/01/2000', led_intensities_mw=9.0, led_name_CA='Thorlab_led', toggleCA_illum_duty=0.5, toggleCA_illum_period=1.0, toggleCA_dark_time_init=0, toggleCA_illum_time=-1, liquid_flush_time=60.0, liquidDrain_time=80.0)

Repeat CV at the cell1_we position.

Flush and fill cell, run CV, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds

(3) run CV
(5) Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_repeat_CA(sequence_version=1, num_repeats=1, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=1511, volume_ul_cell_liquid=1000, WE_potential_\_V=0.0, WE_versus='ref', ref_type='leakless', pH=6.8, CA_duration_sec=0.1, SampleRate=0.01, IErange='auto', ref_offset_\_V=0.0, toolGC='HS 2', toolarchive='LS 3', volume_ul_GC=300, volume_ul_archive=500, wash1=True, wash2=True, wash3=True, wash4=False, liquid_flush_time=70.0, liquidDrain_time=60.0)

Repeat CA and aliquot sampling at the cell1_we position.

Flush and fill cell, run CA, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds
3. run CA
4. mix product
5. Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_repeat_CV(sequence_version=1, WE_versus='ref', ref_type='leakless', pH=6.8, num_repeats=1, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=1511, volume_ul_cell_liquid=1000, WE_potential_init_\_V=0.0, WE_potential_apex1_\_V=-1.0, WE_potential_apex2_\_V=-1.0, WE_potential_final_\_V=0.0, ScanRate_V_s=0.01, Cycles=1, SampleRate=0.01, IErange='auto', ref_offset=0.0, liquidDrain_time=80.0)

Repeat CV at the cell1_we position.

Flush and fill cell, run CV, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds

(3) run CV
(5) Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_repeat_HeatCA(sequence_version=1, num_repeats=1, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=1511, volume_ul_cell_liquid=1000, WE_potential_\_V=0.0, WE_versus='ref', ref_type='leakless', pH=6.8, CA_duration_sec=0.1, SampleRate=0.01, IErange='auto', ref_offset_\_V=0.0, toolGC='HS 2', toolarchive='LS 3', volume_ul_GC=300, volume_ul_archive=500, wash1=True, wash2=True, wash3=True, wash4=False, liquid_flush_time=70.0, liquidDrain_time=80.0, target_temperature_degc=25.0)

Repeat CA and aliquot sampling at the cell1_we position.

Flush and fill cell, run CA, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds
3. run CA
4. mix product
5. Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_repeat_TentHeatCA(sequence_version=1, num_repeats=1, plate_id=6284, solid_sample_no=1, reservoir_liquid_sample_no=1511, volume_ul_cell_liquid=1000, WE_potential_\_V=0.0, WE_versus='ref', ref_type='leakless', pH=6.8, CA_duration_sec=0.1, SampleRate=0.01, IErange='auto', ref_offset_\_V=0.0, toolGC='HS 2', toolarchive='LS 3', volume_ul_GC=300, volume_ul_archive=500, wash1=True, wash2=True, wash3=True, wash4=False, liquid_flush_time=70.0, liquidDrain_time=80.0, target_temperature_degc=25.0)

Repeat CA and aliquot sampling at the cell1_we position.

Flush and fill cell, run CA, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds
3. run CA
4. mix product
5. Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_repeat_TentHeatCAgasonly(sequence_version=1, num_repeats=1, plate_id=6284, solid_sample_no=1, reservoir_liquid_sample_no=1511, volume_ul_cell_liquid=1000, WE_potential_\_V=0.0, WE_versus='ref', ref_type='leakless', pH=6.8, CA_duration_sec=0.1, SampleRate=0.01, IErange='auto', ref_offset_\_V=0.0, toolGC='HS 2', volume_ul_GC=300, liquid_flush_time=70.0, liquidDrain_time=60.0, target_temperature_degc=25.0)

Repeat CA and aliquot sampling at the cell1_we position.

Flush and fill cell, run CA, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds
3. run CA
4. mix product
5. Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_sample_ready(sequence_version=2, num_repeats=1, plate_id=4534, solid_sample_no=1, z_move_mm=3.0, reservoir_liquid_sample_no=1511, volume_ul_cell_liquid=1000, WE_potential_\_V=0.0, WE_versus='ref', ref_type='leakless', pH=6.8, CA_duration_sec=0.1, SampleRate=0.01, IErange='auto', ref_offset_\_V=0.0, liquidDrain_time=80.0)

Repeat CA and aliquot sampling at the cell1_we position.

Flush and fill cell, run CA, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds
3. run CA
4. Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_series_CA(sequence_version=1, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=1511, volume_ul_cell_liquid=1000, WE_potential_\_V=[-0.9, -1.0, -1.1, -1.2, -1.3], WE_versus='ref', ref_type='leakless', pH=6.8, CA_duration_sec=[900, 900, 900, 900, 900], SampleRate=0.01, IErange='auto', ref_offset_\_V=0.0, toolGC='HS 2', toolarchive='LS 3', volume_ul_GC=300, volume_ul_archive=500, liquidDrain_time=80.0, wash1=True, wash2=True, wash3=True, wash4=False)

running CA at different potentials and aliquot sampling at the cell1_we position.

Flush and fill cell, run CA, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds
3. run CA
4. mix product
5. Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.ANEC_series_CAliquidOnly(sequence_version=1, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=1511, volume_ul_cell_liquid=1000, WE_potential_\_V=[-0.9, -1.0, -1.1, -1.2, -1.3], WE_versus='ref', ref_type='leakless', pH=6.8, CA_duration_sec=[900, 900, 900, 900, 900], SampleRate=0.01, IErange='auto', ref_offset_\_V=0.0, toolarchive='LS 3', volume_ul_archive=500, liquidDrain_time=80.0, wash1=True, wash2=True, wash3=True, wash4=False)

running CA at different potentials and aliquot sampling at the cell1_we position.

Flush and fill cell, run CA, and drain.

1. Fill cell with liquid for 90 seconds
2. Equilibrate for 15 seconds
3. run CA
4. mix product
5. Drain cell and purge with CO2 for 60 seconds

Args:
: exp (Experiment): Active experiment object supplied by Orchestrator
  toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
  volume_ul_GC: GC injection volume

### helao.sequences.ANEC_seq.GC_Archiveliquid_analysis(experiment_version=1, source_tray=2, source_slot=1, source_vial_from=1, source_vial_to=1, dest='Injector 1', volume_ul=2, GC_analysis_time=520.0)

Analyze archived liquid product by GC

### helao.sequences.ANEC_seq.HPLC_Archiveliquid_analysis(experiment_version=1, source_tray=2, source_slot=1, source_vial_from=1, source_vial_to=1, dest='LCInjector1', volume_ul=25)

Analyze archived liquid product by GC

## helao.sequences.CCSI_seq module

Sequence library for CCSI

### helao.sequences.CCSI_seq.CCSI_Solution_co2maintainconcentration(sequence_version=17, initial_gas_sample_no=2, pureco2_sample_no=1, Solution_volume_ul=[0, 0, 0], Solution_reservoir_sample_no=2, Solution_name='acetonitrile', total_sample_volume_ul=[5000, 5000, 5000], total_cell_volume_ul=12500, Waterclean_reservoir_sample_no=1, Waterclean_syringe_rate_ulsec=300, Waterclean_FillWait_s=15, syringe_rate_ulsec=80, LiquidFillWait_s=15, SyringePushWait_s=60, n2_push=False, co2_filltime_s=15, co2measure_duration=1200, co2measure_acqrate=0.5, flowrate_sccm=0.5, flowramp_sccm=0, target_co2_ppm=100000.0, maintain_fill_freq_s=10.0, recirculation_rate_uL_min=10000, clean_recirculation_rate_uL_min=20000, drainrecirc=True, SamplePurge_duration=300, recirculation_duration=150, drainclean_volume_ul=10000, n2flowrate_sccm=50, prerinse_cleans=2, perform_init=False, fixed_flushes=2, LiquidClean_full_rinses=5, LiquidClean_rinse_agitation=False, LiquidClean_rinse_agitation_wait=10, LiquidClean_rinse_agitation_duration=60, LiquidClean_rinse_agitation_rate=15000, rinsePurge_duration=300, rinse_recirc=True, rinsePurge_recirc_duration=150, LiquidCleanPurge_duration=210, LiquidCleanPurge_recirc_duration=150, FlushPurge_duration=30, flush_Manpurge1_duration=30, flush_Alphapurge1_duration=10, flush_Probepurge1_duration=45, flush_Sensorpurge1_duration=120, init_HSpurge1_duration=60, init_Manpurge1_duration=30, init_Alphapurge1_duration=30, init_Probepurge1_duration=45, init_Sensorpurge1_duration=120, init_DeltaDilute1_duration=60, init_HSpurge_duration=60, use_co2_check=True, check_co2measure_duration=10, clean_co2_ppm_thresh=1400, clean_co2measure_delay=120, max_repeats=5, purge_if='above', temp_monitor_time=0)

### helao.sequences.CCSI_seq.CCSI_Solution_testing_cleans(sequence_version=16, initial_gas_sample_no=2, pureco2_sample_no=1, Solution_volume_ul=[0, 0, 0], Solution_reservoir_sample_no=2, Solution_name='acetonitrile', total_sample_volume_ul=[5000], total_cell_volume_ul=12500, Waterclean_reservoir_sample_no=1, syringe_rate_ulsec=80, LiquidFillWait_s=15, SyringePushWait_s=5, n2_push=True, co2_filltime_s=15, co2measure_duration=1800, co2measure_acqrate=0.5, flowrate_sccm=0.5, flowramp_sccm=0, target_co2_ppm=100000.0, refill_freq_sec=10.0, recirculation_rate_uL_min=10000, clean_recirculation_rate_uL_min=20000, drainrecirc=True, SamplePurge_duration=300, recirculation_duration=150, drainclean_volume_ul=10000, n2flowrate_sccm=50, prerinse_clean=True, perform_init=False, fixed_flushes=2, LiquidClean_full_rinses=2, LiquidClean_rinse_agitation=False, LiquidClean_rinse_agitation_wait=10, LiquidClean_rinse_agitation_duration=60, LiquidClean_rinse_agitation_rate=10000, rinsePurge_duration=300, rinse_recirc=True, rinsePurge_recirc_duration=150, LiquidCleanPurge_duration=300, LiquidCleanPurge_recirc_duration=150, FlushPurge_duration=30, flush_Manpurge1_duration=30, flush_Alphapurge1_duration=10, flush_Probepurge1_duration=45, flush_Sensorpurge1_duration=120, init_HSpurge1_duration=60, init_Manpurge1_duration=30, init_Alphapurge1_duration=30, init_Probepurge1_duration=45, init_Sensorpurge1_duration=120, init_DeltaDilute1_duration=60, init_HSpurge_duration=60, use_co2_check=True, check_co2measure_duration=10, clean_co2_ppm_thresh=1400, clean_co2measure_delay=120, max_repeats=5, purge_if='above', temp_monitor_time=600)

### helao.sequences.CCSI_seq.CCSI_cleancycles(sequence_version=1, drain_first=False, prerinse_cleans=2, LiquidClean_full_rinses=5, perform_init=False, fixed_flushes=2, Waterclean_reservoir_sample_no=1, Waterclean_syringe_rate_ulsec=300, Waterclean_FillWait_s=15, co2measure_acqrate=0.5, recirculation_rate_uL_min=10000, clean_recirculation_rate_uL_min=20000, drainrecirc=True, SamplePurge_duration=300, recirculation_duration=150, drainclean_volume_ul=10000, n2flowrate_sccm=50, LiquidClean_rinse_agitation=False, LiquidClean_rinse_agitation_wait=10, LiquidClean_rinse_agitation_duration=60, LiquidClean_rinse_agitation_rate=15000, rinsePurge_duration=300, rinse_recirc=True, rinsePurge_recirc_duration=150, LiquidCleanPurge_duration=210, LiquidCleanPurge_recirc_duration=150, FlushPurge_duration=30, flush_Manpurge1_duration=30, flush_Alphapurge1_duration=10, flush_Probepurge1_duration=45, flush_Sensorpurge1_duration=120, init_HSpurge1_duration=60, init_Manpurge1_duration=30, init_Alphapurge1_duration=30, init_Probepurge1_duration=45, init_Sensorpurge1_duration=120, init_DeltaDilute1_duration=60, init_HSpurge_duration=60, use_co2_check=True, check_co2measure_duration=10, clean_co2_ppm_thresh=1400, clean_co2measure_delay=120, max_repeats=5, purge_if='above', temp_monitor_time=0)

### helao.sequences.CCSI_seq.CCSI_initialization(sequence_version=5, headspace_purge_cycles=6, HSpurge1_duration=60, Manpurge1_duration=10, Alphapurge1_duration=10, Probepurge1_duration=10, Sensorpurge1_duration=15, DeltaDilute1_duration=10, HSpurge_duration=20, CO2measure_duration=20, CO2measure_acqrate=1, CO2threshold=9000, Waterclean_volume_ul=10000, Syringe_rate_ulsec=500, LiquidCleanWait_s=15, use_co2_check=True, need_fill=False, clean_injects=True, drainrecirc=True, recirculation_rate_uL_min=10000)

### helao.sequences.CCSI_seq.CCSI_leaktest(sequence_version=2, headspace_purge_cycles=5, HSpurge1_duration=60, Manpurge1_duration=10, Alphapurge1_duration=10, Probepurge1_duration=10, Sensorpurge1_duration=15, DeltaDilute1_duration=10, HSpurge_duration=20, CO2measure_duration=600, CO2measure_acqrate=1, recirculate=True, recirculation_rate_uL_min=10000)

### helao.sequences.CCSI_seq.CCSI_priming(sequence_version=1, Solution_volume_ul=[2000], Solution_reservoir_sample_no=2, Solution_name='', total_sample_volume_ul=5000, Waterclean_reservoir_sample_no=1, syringe_rate_ulsec=300, LiquidFillWait_s=20, co2measure_duration=300, co2measure_acqrate=1, drainclean_volume_ul=10000, headspace_purge_cycles=2, headspace_co2measure_duration=30, clean_co2measure_duration=120, LiquidCleanPurge_duration=60, clean_co2_ppm_thresh=51500, max_repeats=5, purge_if=0.03, HSpurge_duration=15, DeltaDilute1_duration=15, drainrecirc=True, recirculation_rate_uL_min=10000, need_fill=False)

## helao.sequences.ECHEUVIS_seq module

### helao.sequences.ECHEUVIS_seq.ECHEUVIS_CA_led(sequence_version=5, plate_id=1, plate_sample_no_list=[2], reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', solution_ph=9.53, measurement_area=0.071, liquid_volume_ml=1.0, ref_vs_nhe=0.21, CA_potential_vsRHE=1.23, CA_duration_sec=15, CA_samplerate_sec=0.05, OCV_duration=1, gamry_i_range='auto', led_type='front', led_date='01/01/2000', led_names=['doric_wled'], led_wavelengths_nm=[-1], led_intensities_mw=[0.432], led_name_CA='doric_wled', toggleCA_illum_duty=0.5, toggleCA_illum_period=1.0, toggleCA_dark_time_init=0, toggleCA_illum_time=-1, toggleSpec_duty=0.167, toggleSpec_period=0.6, toggleSpec_init_delay=0.0, toggleSpec_time=-1, spec_ref_duration=2, spec_int_time_ms=15, spec_n_avg=1, spec_technique='T_UVVIS', calc_ev_parts=[1.5, 2.0, 2.5, 3.0], calc_bin_width=3, calc_window_length=45, calc_poly_order=4, calc_lower_wl=370.0, calc_upper_wl=1020.0, use_z_motor=False, cell_engaged_z=2.5, cell_disengaged_z=0, cell_vent_wait=10.0, cell_fill_wait=30.0)

### helao.sequences.ECHEUVIS_seq.ECHEUVIS_CP_led(sequence_version=5, plate_id=1, plate_sample_no_list=[2], reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', solution_ph=9.53, measurement_area=0.071, liquid_volume_ml=1.0, ref_vs_nhe=0.21, CP_current=1e-06, CP_duration_sec=15, CP_samplerate_sec=0.05, gamry_i_range='auto', led_type='front', led_date='01/01/2000', led_names=['doric_wled'], led_wavelengths_nm=[-1], led_intensities_mw=[0.432], led_name_CP='doric_wled', toggleCP_illum_duty=0.5, toggleCP_illum_period=1.0, toggleCP_dark_time_init=0.0, toggleCP_illum_time=-1, toggleSpec_duty=0.167, toggleSpec_period=0.6, toggleSpec_init_delay=0.0, toggleSpec_time=-1, spec_ref_duration=2, spec_int_time_ms=15, spec_n_avg=1, spec_technique='T_UVVIS', calc_ev_parts=[1.5, 2.0, 2.5, 3.0], calc_bin_width=3, calc_window_length=45, calc_poly_order=4, calc_lower_wl=370.0, calc_upper_wl=1020.0, use_z_motor=False, cell_engaged_z=2.5, cell_disengaged_z=0, cell_vent_wait=10.0, cell_fill_wait=30.0)

### helao.sequences.ECHEUVIS_seq.ECHEUVIS_CV_led(sequence_version=5, plate_id=1, plate_sample_no_list=[2], reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', solution_ph=9.53, measurement_area=0.071, liquid_volume_ml=1.0, ref_vs_nhe=0.21, CV_Vinit_vsRHE=1.23, CV_Vapex1_vsRHE=0.73, CV_Vapex2_vsRHE=1.73, CV_Vfinal_vsRHE=1.73, CV_scanrate_voltsec=0.02, CV_samplerate_mV=1, CV_cycles=1, preCV_duration=3, gamry_i_range='auto', led_type='front', led_date='01/01/2000', led_names=['doric_wled'], led_wavelengths_nm=[-1], led_intensities_mw=[0.432], led_name_CV='doric_wled', toggleCV_illum_duty=0.667, toggleCV_illum_period=3.0, toggleCV_dark_time_init=0, toggleCV_illum_time=-1, toggleSpec_duty=0.167, toggleSpec_period=0.6, toggleSpec_init_delay=0.0, toggleSpec_time=-1, spec_ref_duration=2, spec_int_time_ms=15, spec_n_avg=1, spec_technique='T_UVVIS', calc_ev_parts=[1.5, 2.0, 2.5, 3.0], calc_bin_width=3, calc_window_length=45, calc_poly_order=4, calc_lower_wl=370.0, calc_upper_wl=1020.0, use_z_motor=False, cell_engaged_z=2.5, cell_disengaged_z=0, cell_vent_wait=10.0, cell_fill_wait=30.0)

### helao.sequences.ECHEUVIS_seq.ECHEUVIS_diagnostic_CV(sequence_version=1, plate_id=0, solid_sample_no=0, reservoir_electrolyte='OER10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', solution_ph=9.53, measurement_area=0.071, liquid_volume_ml=1.0, ref_vs_nhe=0.21, led_type='front', led_date='01/01/2000', led_names=['doric_wled'], led_wavelengths_nm=[-1], led_intensities_mw=[0.432], led_name_CA='doric_wled', toggleCA_illum_duty=1.0, toggleCA_illum_period=1.0, toggleCA_dark_time_init=0, toggleCA_illum_time=-1, toggleSpec_duty=0.5, toggleSpec_period=0.25, toggleSpec_init_delay=0.0, toggleSpec_time=-1, spec_n_avg=1, cell_engaged_z=2.5, cell_disengaged_z=0, cell_vent_wait=10.0, cell_fill_wait=30.0)

### helao.sequences.ECHEUVIS_seq.ECHEUVIS_multiCA_led(sequence_version=5, plate_id=1, plate_sample_no_list=[2], reservoir_electrolyte='OER10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', solution_ph=9.53, measurement_area=0.071, liquid_volume_ml=1.0, ref_vs_nhe=0.21, CA_potential_vsRHE=[0.8, 0.6, 0.4, 0.2], CA_duration_sec=300, CA_samplerate_sec=0.05, OCV_duration_sec=5, gamry_i_range='auto', led_type='front', led_date='01/01/2000', led_names=['doric_wled'], led_wavelengths_nm=[-1], led_intensities_mw=[0.432], led_name_CA='doric_wled', toggleCA_illum_duty=1.0, toggleCA_illum_period=1.0, toggleCA_dark_time_init=0, toggleCA_illum_time=-1, toggleSpec_duty=0.5, toggleSpec_period=0.25, toggleSpec_init_delay=0.0, toggleSpec_time=-1, spec_ref_duration=5, spec_int_time_ms=13, spec_n_avg=5, spec_technique='T_UVVIS', random_start_potential=True, use_z_motor=False, cell_engaged_z=2.5, cell_disengaged_z=0, cell_vent_wait=10.0, cell_fill_wait=30.0)

### helao.sequences.ECHEUVIS_seq.ECHEUVIS_postseq(sequence_version=1, analysis_seq_uuid='', plate_id=0, recent=False)

## helao.sequences.ECHE_seq module

Sequence library for ECHE

### helao.sequences.ECHE_seq.ECHE_4CA_led_1CV_led(sequence_version=4, plate_id=1, plate_sample_no_list=[2], reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', solution_ph=9.53, ref_type='inhouse', ref_offset_\_V=0.0, measurement_area=0.071, liquid_volume_ml=1.0, ref_vs_nhe=0.21, CA1_potential=1.23, CA1_duration_sec=15, CA2_potential=1.23, CA2_duration_sec=4, CA3_potential=1.23, CA3_duration_sec=4, CA4_potential=1.23, CA4_duration_sec=4, CA_samplerate_sec=0.05, CV_Vinit_vsRHE=1.23, CV_Vapex1_vsRHE=0.73, CV_Vapex2_vsRHE=1.73, CV_Vfinal_vsRHE=1.73, CV_scanrate_voltsec=0.02, CV_samplerate_mV=1, CV_cycles=1, preCV_duration=3, OCV_duration=1, gamry_i_range='auto', gamrychannelwait=-1, gamrychannelsend=0, led_type='front', led_date='01/01/2000', led_names=['doric_led1', 'doric_led2', 'doric_led3', 'doric_led4'], led_wavelengths_nm=[385, 450, 515, 595], led_intensities_mw=[-1, -1, -1, -1], led_name_CA1='doric_led1', led_name_CA2='doric_led2', led_name_CA3='doric_led3', led_name_CA4='doric_led4', led_name_CV='doric_led1', toggleCA_illum_duty=0.5, toggleCA_illum_period=1.0, toggleCA_dark_time_init=0, toggleCA_illum_time=-1, toggleCV_illum_duty=0.667, toggleCV_illum_period=3.0, toggleCV_dark_time_init=0, toggleCV_illum_time=-1)

### helao.sequences.ECHE_seq.ECHE_CA(sequence_version=4, plate_id=1, plate_sample_no_list=[2], reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', solution_ph=9.53, measurement_area=0.071, liquid_volume_ml=1.0, ref_type='inhouse', ref_offset_\_V=0.0, CA_potential=1.23, CA_duration_sec=4, CA_samplerate_sec=0.05, OCV_duration=1, gamry_i_range='auto')

### helao.sequences.ECHE_seq.ECHE_CA_led(sequence_version=4, plate_id=1, plate_sample_no_list=[2], reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', solution_ph=9.53, measurement_area=0.071, liquid_volume_ml=1.0, ref_type='inhouse', ref_offset_\_V=0.0, CA_potential=1.23, CA_duration_sec=15, CA_samplerate_sec=0.05, OCV_duration=1, gamry_i_range='auto', gamrychannelwait=-1, gamrychannelsend=0, led_type='front', led_date='01/01/2000', led_names=['doric_led1', 'doric_led2', 'doric_led3', 'doric_led4'], led_wavelengths_nm=[385, 450, 515, 595], led_intensities_mw=[-1, -1, -1, -1], led_name_CA='doric_led1', toggleCA_illum_duty=0.5, toggleCA_illum_period=1.0, toggleCA_dark_time_init=0, toggleCA_illum_time=-1)

### helao.sequences.ECHE_seq.ECHE_CP(sequence_version=3, plate_id=1, plate_sample_no_list=[2], reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', solution_ph=9.53, measurement_area=0.071, liquid_volume_ml=1.0, ref_type='inhouse', ref_offset_\_V=0.0, CP_current=1e-06, CP_duration_sec=4, CP_samplerate_sec=0.05, gamry_i_range='auto')

### helao.sequences.ECHE_seq.ECHE_CP_led(sequence_version=3, plate_id=1, plate_sample_no_list=[2], reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', solution_ph=9.53, measurement_area=0.071, liquid_volume_ml=1.0, ref_type='inhouse', ref_offset_\_V=0.0, CP_current=1e-06, CP_duration_sec=15, CP_samplerate_sec=0.05, gamry_i_range='auto', gamrychannelwait=-1, gamrychannelsend=0, led_name_CP='doric_led1', led_type='front', led_date='01/01/2000', led_names=['doric_led1', 'doric_led2', 'doric_led3', 'doric_led4'], led_wavelengths_nm=[385, 450, 515, 595], led_intensities_mw=[-1, -1, -1, -1], toggleCP_illum_duty=0.5, toggleCP_illum_period=1.0, toggleCP_dark_time_init=0.0, toggleCP_illum_time=-1)

### helao.sequences.ECHE_seq.ECHE_CV(sequence_version=4, plate_id=1, plate_sample_no_list=[2], reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', solution_ph=9.53, measurement_area=0.071, liquid_volume_ml=1.0, ref_type='inhouse', ref_offset_\_V=0.0, CV1_Vinit_vsRHE=0.7, CV1_Vapex1_vsRHE=1, CV1_Vapex2_vsRHE=0, CV1_Vfinal_vsRHE=0, CV1_scanrate_voltsec=0.02, CV1_samplerate_mV=1, CV1_cycles=1, preCV_duration=3, gamry_i_range='auto')

### helao.sequences.ECHE_seq.ECHE_CV_CA_CV(sequence_version=4, plate_id=1, plate_sample_no_list=[2], reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', solution_ph=9.53, ref_type='inhouse', ref_offset_\_V=0.0, measurement_area=0.071, liquid_volume_ml=1.0, CV1_Vinit_vsRHE=1.23, CV1_Vapex1_vsRHE=0.73, CV1_Vapex2_vsRHE=1.73, CV1_Vfinal_vsRHE=1.73, CV1_scanrate_voltsec=0.02, CV1_samplerate_mV=1, CV1_cycles=1, preCV_duration=3, OCV_duration=1, CA2_potential=1.23, CA2_duration_sec=4, CA_samplerate_sec=0.05, CV3_Vinit_vsRHE=1.23, CV3_Vapex1_vsRHE=0.73, CV3_Vapex2_vsRHE=1.73, CV3_Vfinal_vsRHE=1.73, CV3_scanrate_voltsec=0.02, CV3_samplerate_mV=1, CV3_cycles=1, gamry_i_range='auto')

### helao.sequences.ECHE_seq.ECHE_CV_led(sequence_version=4, plate_id=1, plate_sample_no_list=[2], reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', solution_ph=9.53, measurement_area=0.071, liquid_volume_ml=1.0, ref_type='inhouse', ref_offset_\_V=0.0, CV_Vinit_vsRHE=1.23, CV_Vapex1_vsRHE=0.73, CV_Vapex2_vsRHE=1.73, CV_Vfinal_vsRHE=1.73, CV_scanrate_voltsec=0.02, CV_samplerate_mV=1, CV_cycles=1, preCV_duration=3, gamry_i_range='auto', gamrychannelwait=-1, gamrychannelsend=0, led_type='front', led_date='01/01/2000', led_names=['doric_led1', 'doric_led2', 'doric_led3', 'doric_led4'], led_wavelengths_nm=[385, 450, 515, 595], led_intensities_mw=[-1, -1, -1, -1], led_name_CV='doric_led1', toggleCV_illum_duty=0.667, toggleCV_illum_period=3.0, toggleCV_dark_time_init=0, toggleCV_illum_time=-1)

### helao.sequences.ECHE_seq.ECHE_CVs_CAs(sequence_version=1, plate_id=6307, plate_sample_no_list=[2], reservoir_electrolyte='perchloric acid', reservoir_liquid_sample_no=27, solution_bubble_gas='O2', solution_ph=1.24, ref_type='inhouse', ref_offset_\_V=0.0, measurement_area=0.071, liquid_volume_ml=1.0, CV1_Vinit_vsRHE=1.23, CV1_Vapex1_vsRHE=1.23, CV1_Vapex2_vsRHE=0.6, CV1_Vfinal_vsRHE=0.6, CV1_scanrate_voltsec=0.02, CV1_samplerate_mV=1, CV1_cycles=5, CV2_Vinit_vsRHE=1.23, CV2_Vapex1_vsRHE=1.23, CV2_Vapex2_vsRHE=0.4, CV2_Vfinal_vsRHE=0.4, CV2_scanrate_voltsec=0.02, CV2_samplerate_mV=1, CV2_cycles=3, CV3_Vinit_vsRHE=1.23, CV3_Vapex1_vsRHE=1.23, CV3_Vapex2_vsRHE=0, CV3_Vfinal_vsRHE=0, CV3_scanrate_voltsec=0.02, CV3_samplerate_mV=1, CV3_cycles=3, preCV_duration=3, OCV_duration=1, CA1_potential=0.6, CA1_duration_sec=300, CA2_potential=0.4, CA2_duration_sec=300, CA_samplerate_sec=0.05, gamry_i_range='auto')

### helao.sequences.ECHE_seq.ECHE_cleanCVs_regCVs_CAs(sequence_version=1, plate_id=6307, plate_sample_no_list=[2], reservoir_electrolyte='perchloric acid', reservoir_liquid_sample_no=27, solution_bubble_gas='O2', solution_ph=1.24, ref_type='inhouse', ref_offset_\_V=0.0, measurement_area=0.071, liquid_volume_ml=1.0, CVcln_Vinit_vsRHE=1.23, CVcln_Vapex1_vsRHE=1.23, CVcln_Vapex2_vsRHE=0, CVcln_Vfinal_vsRHE=0, CVcln_scanrate_voltsec=0.1, CVcln_samplerate_mV=1, CVcln_cycles=20, CV1_Vinit_vsRHE=1.23, CV1_Vapex1_vsRHE=1.23, CV1_Vapex2_vsRHE=0.6, CV1_Vfinal_vsRHE=0.6, CV1_scanrate_voltsec=0.02, CV1_samplerate_mV=1, CV1_cycles=5, CV2_Vinit_vsRHE=1.23, CV2_Vapex1_vsRHE=1.23, CV2_Vapex2_vsRHE=0.4, CV2_Vfinal_vsRHE=0.4, CV2_scanrate_voltsec=0.02, CV2_samplerate_mV=1, CV2_cycles=3, CV3_Vinit_vsRHE=1.23, CV3_Vapex1_vsRHE=1.23, CV3_Vapex2_vsRHE=0, CV3_Vfinal_vsRHE=0, CV3_scanrate_voltsec=0.02, CV3_samplerate_mV=1, CV3_cycles=3, preCV_duration=3, OCV_duration=1, CA1_potential=0.6, CA1_duration_sec=300, CA2_potential=0.4, CA2_duration_sec=300, CA_samplerate_sec=0.05, gamry_i_range='auto')

### helao.sequences.ECHE_seq.ECHE_move(sequence_version=1, move_x_mm=1.0, move_y_mm=1.0)

### helao.sequences.ECHE_seq.ECHE_movetosample(sequence_version=1, plate_id=1, plate_sample_no=1)

## helao.sequences.ECMS_seq module

Sequence library for AutoGDE

### helao.sequences.ECMS_seq.ECMS_CV_recirculation_mixedreactant(sequence_version=3, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=2, volume_ul_cell_liquid=2090, liquid_backward_time=35, CO2equilibrium_duration=30, CO2flowrate_sccm=[10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 10], Califlowrate_sccm=[0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 0], flow_ramp_sccm=0, MS_baseline_duration_1=90, MS_baseline_duration_2=180, WE_versus='ref', ref_type='leakless', pH=7.8, WE_potential_init_\_V=-0.5, WE_potential_apex1_\_V=-2.0, WE_potential_apex2_\_V=-0.5, WE_potential_final_\_V=-0.5, ScanRate_V_s_1=0.02, Cycles=1, SampleRate=0.1, IErange='30mA', ref_offset=0.0, MS_equilibrium_time=120.0, cleaning_times=0, liquid_fill_time=22.5, tube_clear_time=15, tube_clear_delaytime=40.0, liquid_drain_time=170.0)

### helao.sequences.ECMS_seq.ECMS_MS_calibration(sequence_version=1, reservoir_liquid_sample_no=2, volume_ul_cell_liquid=600, liquid_backward_time=80, CO2equilibrium_duration=30, flowrate_sccm=20.0, flow_ramp_sccm=0, MS_baseline_duration_1=120, CO2flowrate_sccm=[19, 18, 17, 16, 15], Califlowrate_sccm=[1, 2, 3, 4, 5], MSsignal_quilibrium_time_initial=480, MSsignal_quilibrium_time=300, liquid_drain_time=60.0)

### helao.sequences.ECMS_seq.ECMS_MS_calibration_recirculation(sequence_version=2, reservoir_liquid_sample_no=2, liquid_fill_time=15, volume_ul_cell_liquid=600, liquid_backward_time=80, CO2equilibrium_duration=30, flowrate_sccm=20.0, flow_ramp_sccm=0, MS_baseline_duration_1=120, CO2flowrate_sccm=[19, 18, 17, 16, 15], Califlowrate_sccm=[1, 2, 3, 4, 5], MSsignal_quilibrium_time_initial=480, MSsignal_quilibrium_time=300, liquid_drain_time=60.0, tube_clear_time=20)

### helao.sequences.ECMS_seq.ECMS_MS_pulsecalibration(sequence_version=1, reservoir_liquid_sample_no=2, volume_ul_cell_liquid=600, liquid_backward_time=80, CO2equilibrium_duration=30, flowrate_sccm=19.0, Califlowrate_sccm=1, flow_ramp_sccm=0, MS_baseline_duration_1=60, MSsignal_quilibrium_time=10, calibration_cycles=15)

### helao.sequences.ECMS_seq.ECMS_initiation(sequence_version=2, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=2, volume_ul_cell_liquid=600, liquid_backward_time=80, vacuum_time=15, CO2equilibrium_duration=30, flowrate_sccm=3.0, flow_ramp_sccm=0, MS_baseline_duration_1=120, MS_baseline_duration_2=90, liquid_drain_time=60.0)

### helao.sequences.ECMS_seq.ECMS_initiation_recirculation(sequence_version=2, plate_id=4534, solid_sample_no=1, liquid_fill_time=15, reservoir_liquid_sample_no=2, volume_ul_cell_liquid=600, liquid_backward_time=80, vacuum_time=15, CO2equilibrium_duration=30, flowrate_sccm=3.0, flow_ramp_sccm=0, MS_baseline_duration_1=120, MS_baseline_duration_2=90, tube_clear_time=20, liquid_drain_time=60.0)

### helao.sequences.ECMS_seq.ECMS_initiation_recirculation_mixedreactant(sequence_version=2, plate_id=4534, solid_sample_no=1, liquid_fill_time=15, reservoir_liquid_sample_no=2, volume_ul_cell_liquid=600, liquid_backward_time=80, vacuum_time=15, CO2equilibrium_duration=30, CO2flowrate_sccm=5.0, Califlowrate_sccm=5.0, flow_ramp_sccm=0, MS_baseline_duration_1=120, MS_baseline_duration_2=180, tube_clear_time=20, liquid_drain_time=60.0)

### helao.sequences.ECMS_seq.ECMS_repeat_CV(sequence_version=2, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=2, volume_ul_cell_liquid=600, liquid_backward_time=100, CO2equilibrium_duration=30, flowrate_sccm=3.0, flow_ramp_sccm=0, MS_baseline_duration_1=90, MS_baseline_duration_2=90, WE_versus='ref', ref_type='leakless', pH=7.8, num_repeats=1, WE_potential_init_\_V=-1.3, WE_potential_apex1_\_V=-2.0, WE_potential_apex2_\_V=-1.3, WE_potential_final_\_V=-1.3, ScanRate_V_s_1=0.05, ScanRate_V_s_2=0.02, Cycles=3, SampleRate=0.1, IErange='auto', ref_offset=0.0, MS_equilibrium_time=120.0, liquid_drain_time=60.0)

### helao.sequences.ECMS_seq.ECMS_repeat_CV_recirculation(sequence_version=2, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=2, volume_ul_cell_liquid=600, liquid_backward_time=80, CO2equilibrium_duration=30, flowrate_sccm=3.0, flow_ramp_sccm=0, MS_baseline_duration_1=90, MS_baseline_duration_2=90, WE_versus='ref', ref_type='leakless', pH=7.8, num_repeats=1, WE_potential_init_\_V=-1.3, WE_potential_apex1_\_V=-2.0, WE_potential_apex2_\_V=-1.3, WE_potential_final_\_V=-1.3, ScanRate_V_s_1=0.05, ScanRate_V_s_2=0.02, Cycles=3, SampleRate=0.1, IErange='auto', ref_offset=0.0, MS_equilibrium_time=120.0, cleaning_times=1, liquid_fill_time=7, tube_clear_time=20, tube_clear_delaytime=40.0, liquid_drain_time=80.0)

### helao.sequences.ECMS_seq.ECMS_repeat_CV_recirculation_mixedreactant(sequence_version=2, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=2, volume_ul_cell_liquid=600, liquid_backward_time=80, CO2equilibrium_duration=30, CO2flowrate_sccm=1.2, Califlowrate_sccm=1.8, flow_ramp_sccm=0, MS_baseline_duration_1=90, MS_baseline_duration_2=180, WE_versus='ref', ref_type='leakless', pH=7.8, num_repeats=1, WE_potential_init_\_V=-1.3, WE_potential_apex1_\_V=-2.0, WE_potential_apex2_\_V=-1.3, WE_potential_final_\_V=-1.3, ScanRate_V_s_1=0.05, ScanRate_V_s_2=0.02, Cycles=3, SampleRate=0.1, IErange='auto', ref_offset=0.0, MS_equilibrium_time=120.0, cleaning_times=1, liquid_fill_time=7, tube_clear_time=20, tube_clear_delaytime=40.0, liquid_drain_time=80.0)

### helao.sequences.ECMS_seq.ECMS_series_CA(sequence_version=2, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=2, volume_ul_cell_liquid=600, liquid_backward_time=100, CO2equilibrium_duration=30, flowrate_sccm=3.0, flow_ramp_sccm=0, MS_baseline_duration_1=90, MS_baseline_duration_2=90, WE_potential_\_V=[-1.4, -1.6, -1.8, -1.9, -2.0], WE_versus='ref', ref_type='leakless', pH=7.8, CA_duration_sec=[600, 600, 600, 600, 600], SampleRate=1, IErange='auto', ref_offset_\_V=0.0, MS_equilibrium_time=120.0, liquid_drain_time=60.0)

### helao.sequences.ECMS_seq.ECMS_series_CA_recirculation(sequence_version=3, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=2, volume_ul_cell_liquid=600, liquid_backward_time=80, CO2equilibrium_duration=30, flowrate_sccm=3.0, flow_ramp_sccm=0, MS_baseline_duration_1=90, MS_baseline_duration_2=90, WE_potential_\_V=[-1.4, -1.6, -1.8, -1.9, -2.0], WE_versus='ref', ref_type='leakless', pH=7.8, CA_duration_sec=[600, 600, 600, 600, 600], SampleRate=1, IErange='auto', ref_offset_\_V=0.0, MS_equilibrium_time=120.0, cleaning_times=1, liquid_fill_time=7, liquid_drain_time=60.0, tube_clear_time=20, tube_clear_delaytime=40.0)

### helao.sequences.ECMS_seq.ECMS_series_CA_recirculation_mixedreactant(sequence_version=3, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=2, volume_ul_cell_liquid=600, liquid_backward_time=80, CO2equilibrium_duration=30, CO2flowrate_sccm=1.2, Califlowrate_sccm=1.8, flow_ramp_sccm=0, MS_baseline_duration_1=90, MS_baseline_duration_2=180, WE_potential_\_V=[-1.4, -1.6, -1.8, -1.9, -2.0], WE_versus='ref', ref_type='leakless', pH=7.8, CA_duration_sec=[600, 600, 600, 600, 600], SampleRate=1, IErange='auto', ref_offset_\_V=0.0, MS_equilibrium_time=120.0, cleaning_times=1, liquid_fill_time=7, liquid_drain_time=60.0, tube_clear_time=20, tube_clear_delaytime=40.0)

### helao.sequences.ECMS_seq.ECMS_series_pulseCA(sequence_version=2, plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=2, volume_ul_cell_liquid=600, liquid_backward_time=100, CO2equilibrium_duration=30, flowrate_sccm=3.0, flow_ramp_sccm=0, MS_baseline_duration_1=90, MS_baseline_duration_2=90, WE_pulsepotential_\_V=[-1.5, -1.6, -1.8, -1.9, -2.0], WE_versus='ref', ref_type='leakless', pH=7.8, SampleRate=1, IErange='auto', ref_offset_\_V=0.0, MS_equilibrium_time=120.0, liquid_drain_time=60.0, Vinit_\_V=0.0, Tinit_\_s=5.0, Tstep_\_s=5.0, Cycles=60, AcqInterval_\_s=0.01, run_OCV=False, Tocv_\_s=60.0)

## helao.sequences.ICPMS_seq module

### helao.sequences.ICPMS_seq.ICPMS_postseq(sequence_version=1, sequence_zip_path='')

## helao.sequences.OERSIM_seq module

Sequence library for CCSI

### helao.sequences.OERSIM_seq.OERSIM_activelearn(sequence_version=1, init_random_points=5, stop_condition='max_iters', thresh_value=10)

Active-learning sequence using EI acquisition with various stop conditions.

## helao.sequences.TEST_seq module

Sequence library for Orchestrator testing

### helao.sequences.TEST_seq.TEST_consecutive_noblocking(sequence_version=1, wait_time=3.0, cycles=5, dummy_list=[[0.0, 1.0], [2.0, 3.0]], \*args, \*\*kwrags)

## helao.sequences.UVIS_DR_seq module

Sequence library for UVIS

### helao.sequences.UVIS_DR_seq.UVIS_DR(sequence_version=3, plate_id=1, plate_sample_no_list=[2], reference_mode='internal', custom_position='cell1_we', spec_n_avg=1, spec_int_time_ms=10, duration_sec=-1, specref_code=1, led_type='front', led_date='n/a', led_names=['doric_wled'], led_wavelengths_nm=[-1], led_intensities_mw=[-1], toggle_is_shutter=True, calc_ev_parts=[1.5, 2.0, 2.5, 3.0], calc_bin_width=3, calc_window_length=45, calc_poly_order=4, calc_lower_wl=370.0, calc_upper_wl=1020.0)

## helao.sequences.UVIS_TR_seq module

Sequence library for UVIS

### helao.sequences.UVIS_TR_seq.UVIS_TR(sequence_version=3, plate_id=1, plate_sample_no_list=[2], reference_mode='internal', custom_position='cell1_we', spec_n_avg=1, spec_int_time_ms=10, duration_sec=-1, specref_code=1, led_type='front', led_date='n/a', led_names=['wl_source'], led_wavelengths_nm=[-1], led_intensities_mw=[-1], toggle_is_shutter=True, calc_ev_parts=[1.5, 2.0, 2.5, 3.0], calc_bin_width=3, calc_window_length=45, calc_poly_order=4, calc_lower_wl=370.0, calc_upper_wl=1020.0)

## helao.sequences.UVIS_T_seq module

Sequence library for UVIS

### helao.sequences.UVIS_T_seq.UVIS_T(sequence_version=5, plate_id=1, plate_sample_no_list=[2], reference_mode='internal', custom_position='cell1_we', spec_n_avg=5, spec_int_time_ms=13, duration_sec=-1, specref_code=1, led_type='front', led_date='n/a', led_names=['doric_wled'], led_wavelengths_nm=[-1], led_intensities_mw=[0.432], toggle_is_shutter=False, analysis_seq_uuid='', use_z_motor=False, cell_engaged_z=1.5, cell_disengaged_z=0)

### helao.sequences.UVIS_T_seq.UVIS_T_postseq(sequence_version=1, analysis_seq_uuid='', plate_id=0, recent=False)

## Module contents
