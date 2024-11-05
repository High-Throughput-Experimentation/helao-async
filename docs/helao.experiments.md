# helao.experiments package

## Submodules

## helao.experiments.ADSS_exp module

## helao.experiments.ANEC_exp module

## helao.experiments.CCSI_exp_old module

## helao.experiments.CSIL_exp module

Action library for CCSI

server_key must be a FastAPI action server defined in config

### helao.experiments.CSIL_exp.CCSI_leaktest_co2(experiment, experiment_version=2, co2measure_duration=600, co2measure_acqrate=1, recirculate=True, recirculation_rate_uL_min=10000)

### helao.experiments.CSIL_exp.CCSI_sub_alloff(experiment, experiment_version=1)

Args:
: experiment (Experiment): Experiment object provided by Orch

### helao.experiments.CSIL_exp.CCSI_sub_cellfill(experiment, experiment_version=8, Solution_description='KOH', Solution_reservoir_sample_no=2, Solution_volume_ul=500, Waterclean_reservoir_sample_no=1, Waterclean_volume_ul=2500, Syringe_rate_ulsec=300, SyringePushWait_s=6, LiquidFillWait_s=15, WaterFillWait_s=15, previous_liquid=False, n2_push=False, co2_fill_after_n2push=False, co2_filltime_s=30)

### helao.experiments.CSIL_exp.CCSI_sub_clean_inject(experiment, experiment_version=9, Waterclean_volume_ul=10000, Syringe_rate_ulsec=500, LiquidCleanWait_s=15, co2measure_duration=20, co2measure_acqrate=1, use_co2_check=True, need_fill=False, co2_ppm_thresh=41000, purge_if='below', max_repeats=5, LiquidCleanPurge_duration=60, DeltaDilute1_duration=0, drainrecirc=True, recirculation_rate_uL_min=10000)

### helao.experiments.CSIL_exp.CCSI_sub_co2maintainconcentration(experiment, experiment_version=3, pureco2_sample_no=1, co2measure_duration=300, co2measure_acqrate=0.5, flowrate_sccm=0.5, flowramp_sccm=0, target_co2_ppm=100000.0, headspace_scc=7.5, refill_freq_sec=60.0, recirculation_rate_uL_min=10000)

### helao.experiments.CSIL_exp.CCSI_sub_drain(experiment, experiment_version=8, HSpurge_duration=20, DeltaDilute1_duration=0, initialization=False, recirculation=False, recirculation_duration=20, recirculation_rate_uL_min=10000)

### helao.experiments.CSIL_exp.CCSI_sub_flowflush(experiment, experiment_version=4, co2measure_duration=3600, co2measure_acqrate=0.5, flowrate_sccm=0.3, flowramp_sccm=0, recirculation_rate_uL_min=10000)

### helao.experiments.CSIL_exp.CCSI_sub_headspace_measure(experiment, experiment_version=1, recirculation_rate_uL_min=10000, co2measure_duration=10, co2measure_acqrate=0.5)

### helao.experiments.CSIL_exp.CCSI_sub_headspace_purge_and_measure(experiment, experiment_version=7, HSpurge_duration=20, DeltaDilute1_duration=0, initialization=False, recirculation_rate_uL_min=10000, co2measure_duration=20, co2measure_acqrate=0.1, co2_ppm_thresh=90000, purge_if='below', max_repeats=5)

### helao.experiments.CSIL_exp.CCSI_sub_initialization_end_state(experiment, experiment_version=1)

### helao.experiments.CSIL_exp.CCSI_sub_initialization_firstpart(experiment, experiment_version=4, HSpurge1_duration=60, Manpurge1_duration=10, Alphapurge1_duration=10, Probepurge1_duration=10, Sensorpurge1_duration=15, recirculation_rate_uL_min=10000)

### helao.experiments.CSIL_exp.CCSI_sub_load_gas(experiment, experiment_version=2, reservoir_gas_sample_no=1, volume_ul_cell_gas=1000)

Add gas volume to cell position.

### helao.experiments.CSIL_exp.CCSI_sub_load_liquid(experiment, experiment_version=3, reservoir_liquid_sample_no=1, volume_ul_cell_liquid=1000, water_True_False=False, combine_True_False=False)

Add liquid volume to cell position.

1. create liquid sample using volume_ul_cell and liquid_sample_no

### helao.experiments.CSIL_exp.CCSI_sub_load_solid(experiment, experiment_version=1, solid_plate_id=4534, solid_sample_no=1)

### helao.experiments.CSIL_exp.CCSI_sub_monitorcell(experiment, experiment_version=1, co2measure_duration=1200, co2measure_acqrate=1, recirculation=False, recirculation_rate_uL_min=10000)

### helao.experiments.CSIL_exp.CCSI_sub_n2clean(experiment, experiment_version=10, Waterclean_reservoir_sample_no=1, waterclean_volume_ul=10000, Syringe_rate_ulsec=300, LiquidFillWait_s=15, n2_push=True, n2flowrate_sccm=50, drain_HSpurge_duration=300, drain_recirculation_duration=150, flush_HSpurge1_duration=30, flush_HSpurge_duration=60, DeltaDilute1_duration=0, Manpurge1_duration=30, Alphapurge1_duration=10, Probepurge1_duration=30, Sensorpurge1_duration=30, recirculation=True, recirculation_rate_uL_min=10000, initialization=False, co2measure_delay=120, co2measure_duration=5, co2measure_acqrate=0.5, use_co2_check=False, co2_ppm_thresh=1400, purge_if='above', max_repeats=2)

### helao.experiments.CSIL_exp.CCSI_sub_n2drain(experiment, experiment_version=4, n2flowrate_sccm=10, HSpurge_duration=240, DeltaDilute1_duration=0, initialization=False, drain_recirculation=True, recirculation_duration=120, recirculation_rate_uL_min=10000)

### helao.experiments.CSIL_exp.CCSI_sub_n2flush(experiment, experiment_version=5, flush_cycles=0, n2flowrate_sccm=10, HSpurge1_duration=60, HSpurge_duration=20, DeltaDilute1_duration=0, Manpurge1_duration=30, Alphapurge1_duration=10, Probepurge1_duration=30, Sensorpurge1_duration=30, recirculation=True, recirculation_rate_uL_min=20000, initialization=False, co2measure_delay=120, co2measure_duration=20, co2measure_acqrate=0.5, use_co2_check=False, co2_ppm_thresh=1000, purge_if='above', max_repeats=5)

### helao.experiments.CSIL_exp.CCSI_sub_n2headspace(experiment, experiment_version=1, n2flowrate_sccm=50, HSpurge_duration=120, recirculation=True, recirculation_duration=60, recirculation_rate_uL_min=10000)

### helao.experiments.CSIL_exp.CCSI_sub_n2rinse(experiment, experiment_version=2, rinse_cycles=3, Waterclean_reservoir_sample_no=1, waterclean_volume_ul=10000, Syringe_rate_ulsec=300, LiquidFillWait_s=15, rinse_agitation=False, rinse_agitation_wait=30, rinse_agitation_duration=30, n2_push=True, n2flowrate_sccm=50, drain_HSpurge_duration=300, drain_recirculation_duration=150, recirculation=False, recirculation_rate_uL_min=10000)

### helao.experiments.CSIL_exp.CCSI_sub_peripumpoff(experiment, experiment_version=1)

### helao.experiments.CSIL_exp.CCSI_sub_refill_clean(experiment, experiment_version=2, Waterclean_volume_ul=5000, Syringe_rate_ulsec=1000)

### helao.experiments.CSIL_exp.CCSI_sub_unload_cell(experiment, experiment_version=1)

Unload Sample at ‘cell1_we’ position.

## helao.experiments.ECHEUVIS_exp module

Experiment library for ECHE+UVIS
server_key must be a FastAPI action server defined in config

### helao.experiments.ECHEUVIS_exp.ECHEUVIS_analysis_stability(experiment, experiment_version=2, sequence_uuid='', plate_id=0, recent=True, params={})

### helao.experiments.ECHEUVIS_exp.ECHEUVIS_sub_CA_led(experiment, experiment_version=6, CA_potential_vsRHE=0.0, solution_ph=9.53, reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', measurement_area=0.071, ref_electrode_type='NHE', ref_vs_nhe=0.21, samplerate_sec=0.1, CA_duration_sec=60, gamry_i_range='auto', gamrychannelwait=-1, gamrychannelsend=0, illumination_source='doric_wled', illumination_wavelength=0.0, illumination_intensity=0.0, illumination_intensity_date='n/a', illumination_side='front', toggle_dark_time_init=0.0, toggle_illum_duty=0.5, toggle_illum_period=2.0, toggle_illum_time=-1, toggle2_source='spec_trig', toggle2_init_delay=0.0, toggle2_duty=0.5, toggle2_period=2.0, toggle2_time=-1, spec_int_time_ms=15, spec_n_avg=10, spec_technique='T_UVVIS', comment='')

last functionality test: -

### helao.experiments.ECHEUVIS_exp.ECHEUVIS_sub_CP_led(experiment, experiment_version=6, CP_current=0.0, solution_ph=9.53, reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', measurement_area=0.071, ref_electrode_type='NHE', ref_vs_nhe=0.21, samplerate_sec=0.1, CP_duration_sec=60, gamry_i_range='auto', gamrychannelwait=-1, gamrychannelsend=0, illumination_source='doric_wled', illumination_wavelength=0.0, illumination_intensity=0.0, illumination_intensity_date='n/a', illumination_side='front', toggle_dark_time_init=0.0, toggle_illum_duty=0.5, toggle_illum_period=2.0, toggle_illum_time=-1, toggle2_source='spec_trig', toggle2_init_delay=0.0, toggle2_duty=0.5, toggle2_period=2.0, toggle2_time=-1, spec_int_time_ms=15, spec_n_avg=10, spec_technique='T_UVVIS', comment='')

last functionality test: -

### helao.experiments.ECHEUVIS_exp.ECHEUVIS_sub_CV_led(experiment, experiment_version=6, Vinit_vsRHE=0.0, Vapex1_vsRHE=1.0, Vapex2_vsRHE=-1.0, Vfinal_vsRHE=0.0, scanrate_voltsec=0.02, samplerate_sec=0.1, cycles=1, gamry_i_range='auto', gamrychannelwait=-1, gamrychannelsend=0, solution_ph=0, reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', measurement_area=0.071, ref_electrode_type='NHE', ref_vs_nhe=0.21, illumination_source='doric_wled', illumination_wavelength=0.0, illumination_intensity=0.0, illumination_intensity_date='n/a', illumination_side='front', toggle_dark_time_init=0.0, toggle_illum_duty=0.5, toggle_illum_period=2.0, toggle_illum_time=-1, toggle2_source='spec_trig', toggle2_init_delay=0.0, toggle2_duty=0.5, toggle2_period=2.0, toggle2_time=-1, spec_int_time_ms=15, spec_n_avg=10, spec_technique='T_UVVIS', comment='')

last functionality test: -

### helao.experiments.ECHEUVIS_exp.ECHEUVIS_sub_OCV_led(experiment, experiment_version=6, solution_ph=9.53, reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', measurement_area=0.071, ref_electrode_type='NHE', ref_vs_nhe=0.21, samplerate_sec=0.1, OCV_duration_sec=0.0, gamry_i_range='auto', gamrychannelwait=-1, gamrychannelsend=0, illumination_source='doric_wled', illumination_wavelength=0.0, illumination_intensity=0.0, illumination_intensity_date='n/a', illumination_side='front', toggle_dark_time_init=0.0, toggle_illum_duty=0.5, toggle_illum_period=2.0, toggle_illum_time=-1, toggle2_source='spec_trig', toggle2_init_delay=0.0, toggle2_duty=0.5, toggle2_period=2.0, toggle2_time=-1, spec_int_time_ms=15, spec_n_avg=10, spec_technique='T_UVVIS', comment='')

last functionality test: -

### helao.experiments.ECHEUVIS_exp.ECHEUVIS_sub_disengage(experiment, experiment_version=1, clear_we=True, clear_ce=False, z_height=0, vent_wait=10.0)

### helao.experiments.ECHEUVIS_exp.ECHEUVIS_sub_engage(experiment, experiment_version=1, flow_we=True, flow_ce=True, z_height=1.5, fill_wait=10.0, calibrate_intensity=False, max_integration_time=150, illumination_source='doric_wled')

### helao.experiments.ECHEUVIS_exp.ECHEUVIS_sub_interrupt(experiment, experiment_version=1, reason='wait')

### helao.experiments.ECHEUVIS_exp.ECHEUVIS_sub_shutdown(experiment)

Unload custom position and disable IR emitter.

### helao.experiments.ECHEUVIS_exp.ECHEUVIS_sub_startup(experiment)

Unload custom position and enable IR emitter.

## helao.experiments.ECHE_exp module

Experiment library for ECHE
server_key must be a FastAPI action server defined in config

### helao.experiments.ECHE_exp.ECHE_sub_CA(experiment, experiment_version=3, CA_potential=0.0, potential_versus='rhe', ref_type='inhouse', ref_offset_\_V=0.0, solution_ph=9.53, reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', measurement_area=0.071, samplerate_sec=0.1, CA_duration_sec=60, gamry_i_range='auto', comment='')

last functionality test: -

### helao.experiments.ECHE_exp.ECHE_sub_CA_led(experiment, experiment_version=4, CA_potential=0.0, potential_versus='rhe', ref_type='inhouse', ref_offset_\_V=0.0, solution_ph=9.53, reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', measurement_area=0.071, samplerate_sec=0.1, CA_duration_sec=60, gamry_i_range='auto', gamrychannelwait=-1, gamrychannelsend=0, illumination_source='doric_led1', illumination_wavelength=0.0, illumination_intensity=0.0, illumination_intensity_date='n/a', illumination_side='front', toggle_dark_time_init=0.0, toggle_illum_duty=0.5, toggle_illum_period=2.0, toggle_illum_time=-1, comment='')

last functionality test: -

### helao.experiments.ECHE_exp.ECHE_sub_CP(experiment, experiment_version=3, CP_current=0.0, solution_ph=9.53, reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', measurement_area=0.071, ref_type='inhouse', ref_offset_\_V=0.0, samplerate_sec=0.1, CP_duration_sec=60, gamry_i_range='auto', comment='')

last functionality test: -

### helao.experiments.ECHE_exp.ECHE_sub_CP_led(experiment, experiment_version=4, CP_current=0.0, solution_ph=9.53, reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', measurement_area=0.071, ref_type='inhouse', ref_offset_\_V=0.0, samplerate_sec=0.1, CP_duration_sec=60, gamry_i_range='auto', gamrychannelwait=-1, gamrychannelsend=0, illumination_source='doric_led1', illumination_wavelength=0.0, illumination_intensity=0.0, illumination_intensity_date='n/a', illumination_side='front', toggle_dark_time_init=0.0, toggle_illum_duty=0.5, toggle_illum_period=2.0, toggle_illum_time=-1, comment='')

last functionality test: -

### helao.experiments.ECHE_exp.ECHE_sub_CV(experiment, experiment_version=3, Vinit_vsRHE=0.0, Vapex1_vsRHE=1.0, Vapex2_vsRHE=-1.0, Vfinal_vsRHE=0.0, scanrate_voltsec=0.02, samplerate_sec=0.1, cycles=1, gamry_i_range='auto', solution_ph=0, reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', measurement_area=0.071, ref_type='inhouse', ref_offset_\_V=0.0, comment='')

last functionality test: -

### helao.experiments.ECHE_exp.ECHE_sub_CV_led(experiment, experiment_version=4, Vinit_vsRHE=0.0, Vapex1_vsRHE=1.0, Vapex2_vsRHE=-1.0, Vfinal_vsRHE=0.0, scanrate_voltsec=0.02, samplerate_sec=0.1, cycles=1, gamry_i_range='auto', gamrychannelwait=-1, gamrychannelsend=0, solution_ph=0, reservoir_electrolyte='SLF10', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', measurement_area=0.071, ref_type='inhouse', ref_offset_\_V=0.0, illumination_source='doric_led1', illumination_wavelength=0.0, illumination_intensity=0.0, illumination_intensity_date='n/a', illumination_side='front', toggle_dark_time_init=0.0, toggle_illum_duty=0.5, toggle_illum_period=2.0, toggle_illum_time=-1, comment='')

last functionality test: -

### helao.experiments.ECHE_exp.ECHE_sub_OCV(experiment, experiment_version=1, Tval_\_s=1, SampleRate=0.05)

### helao.experiments.ECHE_exp.ECHE_sub_add_liquid(experiment, experiment_version=2, solid_custom_position='cell1_we', reservoir_liquid_sample_no=1, solution_bubble_gas='O2', liquid_volume_ml=1.0)

### helao.experiments.ECHE_exp.ECHE_sub_load_solid(experiment, experiment_version=1, solid_custom_position='cell1_we', solid_plate_id=4534, solid_sample_no=1)

last functionality test: -

### helao.experiments.ECHE_exp.ECHE_sub_movetosample(experiment, experiment_version=1, solid_plate_id=4534, solid_sample_no=1)

Sub experiment
last functionality test: -

### helao.experiments.ECHE_exp.ECHE_sub_preCV(experiment, experiment_version=1, CA_potential=0.0, samplerate_sec=0.05, CA_duration_sec=3)

last functionality test: 11/29/2021

### helao.experiments.ECHE_exp.ECHE_sub_rel_move(experiment, experiment_version=1, offset_x_mm=1.0, offset_y_mm=1.0)

Sub experiment
last functionality test: -

### helao.experiments.ECHE_exp.ECHE_sub_shutdown(experiment)

Sub experiment

last functionality test: -

### helao.experiments.ECHE_exp.ECHE_sub_startup(experiment, experiment_version=2, solid_custom_position='cell1_we', solid_plate_id=4534, solid_sample_no=1, reservoir_liquid_sample_no=1, solution_bubble_gas='N2', liquid_volume_ml=1.0)

Sub experiment
last functionality test: -

### helao.experiments.ECHE_exp.ECHE_sub_unloadall_customs(experiment)

last functionality test: -

## helao.experiments.ECMS_exp module

Action library for AutoGDE

server_key must be a FastAPI action server defined in config

### helao.experiments.ECMS_exp.ECMS_sub_CA(experiment, experiment_version=1, WE_potential_\_V=0.0, WE_versus='ref', CA_duration_sec=0.1, SampleRate=0.01, IErange='auto', ref_offset_\_V=0.0, ref_type='leakless', pH=6.8, MS_equilibrium_time=90.0)

### helao.experiments.ECMS_exp.ECMS_sub_CV(experiment, experiment_version=1, WE_versus='ref', ref_type='leakless', pH=6.8, WE_potential_init_\_V=0.0, WE_potential_apex1_\_V=-1.0, WE_potential_apex2_\_V=-0.5, WE_potential_final_\_V=-0.5, ScanRate_V_s=0.01, Cycles=1, SampleRate=0.01, IErange='auto', ref_offset_\_V=0.0, MS_equilibrium_time=90.0)

### helao.experiments.ECMS_exp.ECMS_sub_alloff(experiment, experiment_version=1)

Args:
: experiment (Experiment): Experiment object provided by Orch

### helao.experiments.ECMS_exp.ECMS_sub_cali(experiment, experiment_version=1, CO2flowrate_sccm=20.0, Califlowrate_sccm=0.0, flow_ramp_sccm=0, MSsignal_quilibrium_time=300)

prevacuum the cell gas phase side to make the electrolyte contact with GDE

### helao.experiments.ECMS_exp.ECMS_sub_clean_cell_recirculation(experiment, experiment_version=1, cleaning_times=2, liquid_fill_time=30, volume_ul_cell_liquid=1, liquid_backward_time=80, reservoir_liquid_sample_no=2, tube_clear_delaytime=40.0, tube_clear_time=20, liquid_drain_time=80)

Add electrolyte volume to cell position.

1. create liquid sample using volume_ul_cell and liquid_sample_no

### helao.experiments.ECMS_exp.ECMS_sub_drain(experiment, experiment_version=1, liquid_drain_time=30)

### helao.experiments.ECMS_exp.ECMS_sub_drain_recirculation(experiment, experiment_version=1, tube_clear_time=20, liquid_drain_time=80)

Add electrolyte volume to cell position.

1. create liquid sample using volume_ul_cell and liquid_sample_no

### helao.experiments.ECMS_exp.ECMS_sub_electrolyte_fill_cell(experiment, experiment_version=1, liquid_backward_time=10, reservoir_liquid_sample_no=1, volume_ul_cell_liquid=1)

Add electrolyte volume to cell position.

1. create liquid sample using volume_ul_cell and liquid_sample_no

### helao.experiments.ECMS_exp.ECMS_sub_electrolyte_fill_cell_recirculation(experiment, experiment_version=1, liquid_backward_time=80, reservoir_liquid_sample_no=2, volume_ul_cell_liquid=1.0)

Add electrolyte volume to cell position.

1. create liquid sample using volume_ul_cell and liquid_sample_no

### helao.experiments.ECMS_exp.ECMS_sub_electrolyte_fill_recirculationreservoir(experiment, experiment_version=1, liquid_fill_time=30)

### helao.experiments.ECMS_exp.ECMS_sub_electrolyte_recirculation_off(experiment, experiment_version=1)

Add electrolyte volume to cell position.

1. create liquid sample using volume_ul_cell and liquid_sample_no

### helao.experiments.ECMS_exp.ECMS_sub_electrolyte_recirculation_on(experiment, experiment_version=1)

Add electrolyte volume to cell position.

1. create liquid sample using volume_ul_cell and liquid_sample_no

### helao.experiments.ECMS_exp.ECMS_sub_final_clean_cell(experiment, experiment_version=1, liquid_backward_time_1=300, liquid_backward_time_2=300, reservoir_liquid_sample_no=1, volume_ul_cell_liquid=1)

Add electrolyte volume to cell position.

1. create liquid sample using volume_ul_cell and liquid_sample_no

### helao.experiments.ECMS_exp.ECMS_sub_headspace_purge_and_CO2baseline(experiment, experiment_version=1, CO2equilibrium_duration=30, flowrate_sccm=5.0, flow_ramp_sccm=0, MS_baseline_duration=300)

prevacuum the cell gas phase side to make the electrolyte contact with GDE

### helao.experiments.ECMS_exp.ECMS_sub_load_gas(experiment, experiment_version=2, reservoir_gas_sample_no=1, volume_ul_cell_gas=1000)

Add gas volume to cell position.

### helao.experiments.ECMS_exp.ECMS_sub_load_liquid(experiment, experiment_version=2, reservoir_liquid_sample_no=1, volume_ul_cell_liquid=1000, water_True_False=False, combine_True_False=False)

Add liquid volume to cell position.

1. create liquid sample using volume_ul_cell and liquid_sample_no

### helao.experiments.ECMS_exp.ECMS_sub_load_solid(experiment, experiment_version=1, solid_plate_id=4534, solid_sample_no=1)

### helao.experiments.ECMS_exp.ECMS_sub_normal_state(experiment, experiment_version=1)

Set ECMS to ‘normal’ state.

All experiments begin and end in the following ‘normal’ state:
- separate (old) MFC for CO2 is ON to bypass GDE cell but go to MS.

Args:
: experiment (Experiment): Experiment object provided by Orch

### helao.experiments.ECMS_exp.ECMS_sub_prevacuum_cell(experiment, experiment_version=2, vacuum_time=10)

prevacuum the cell gas phase side to make the electrolyte contact with GDE

### helao.experiments.ECMS_exp.ECMS_sub_pulseCA(experiment, experiment_version=2, Vinit_\_V=0.0, Tinit_\_s=0.5, Vstep_\_V=0.5, Tstep_\_s=0.5, Cycles=5, AcqInterval_\_s=0.01, run_OCV=False, Tocv_\_s=60.0, IErange='auto', WE_versus='ref', ref_offset_\_V=0.0, ref_type='leakless', pH=6.8, MS_equilibrium_time=90.0)

### helao.experiments.ECMS_exp.ECMS_sub_pulsecali(experiment, experiment_version=1, Califlowrate_sccm=0.0, flow_ramp_sccm=0, MSsignal_quilibrium_time=300)

prevacuum the cell gas phase side to make the electrolyte contact with GDE

### helao.experiments.ECMS_exp.ECMS_sub_unload_cell(experiment, experiment_version=1)

Unload Sample at ‘cell1_we’ position.

## helao.experiments.HISPEC_EXP module

Experiment library for HISPEC
server_key must be a FastAPI action server defined in config

### helao.experiments.HISPEC_EXP.HISPEC_sub_SpEC(experiment, experiment_version=1, Vinit_vsRHE=0.0, Vapex1_vsRHE=1.0, Vapex2_vsRHE=-1.0, Vfinal_vsRHE=0.0, scanrate_voltsec=0.02, samplerate_sec=0.1, cycles=1, gamry_i_range='auto', gamrychannelwait=-1, gamrychannelsend=0, solution_ph=0, ref_vs_nhe=0.21, toggle1_source='spec_trig', toggle1_init_delay=0.0, toggle1_duty=0.5, toggle1_period=2.0, toggle1_time=-1, comment='')

last functionality test: -

## helao.experiments.ICPMS_exp module

### helao.experiments.ICPMS_exp.ICPMS_analysis_concentration(experiment, experiment_version=1, sequence_zip_path='', params={})

## helao.experiments.OERSIM_exp module

Experiment library for Orchestrator testing
server_key must be a FastAPI action server defined in config

### helao.experiments.OERSIM_exp.OERSIM_sub_activelearn(experiment, experiment_version=1, init_random_points=5, stop_condition='max_iters', thresh_value=10, repeat_experiment_kwargs={})

### helao.experiments.OERSIM_exp.OERSIM_sub_decision(experiment, experiment_version=1, stop_condition='max_iters', thresh_value=10, repeat_experiment_name='OERSIM_sub_activelearn', repeat_experiment_params={}, repeat_experiment_kwargs={})

### helao.experiments.OERSIM_exp.OERSIM_sub_load_plate(experiment, experiment_version=1, plate_id=0, init_random_points=5)

### helao.experiments.OERSIM_exp.OERSIM_sub_measure_CP(experiment, experiment_version=1, init_random_points=5)

## helao.experiments.TEST_exp module

Experiment library for Orchestrator testing
server_key must be a FastAPI action server defined in config

### helao.experiments.TEST_exp.TEST_sub_conditional_stop(experiment, experiment_version=1)

### helao.experiments.TEST_exp.TEST_sub_noblocking(experiment, experiment_version=1, wait_time=3.0)

## helao.experiments.UVIS_exp module

Experiment library for UVIS
server_key must be a FastAPI action server defined in config

### helao.experiments.UVIS_exp.UVIS_analysis_dry(experiment, experiment_version=2, sequence_uuid='', plate_id=0, recent=True, params={})

### helao.experiments.UVIS_exp.UVIS_calc_abs(experiment, experiment_version=2, ev_parts=[1.5, 2.0, 2.5, 3.0], bin_width=3, window_length=45, poly_order=4, lower_wl=370.0, upper_wl=1020.0, max_mthd_allowed=1.2, max_limit=0.99, min_mthd_allowed=-0.2, min_limit=0.01)

Calculate absorption from sequence info.

### helao.experiments.UVIS_exp.UVIS_sub_load_solid(experiment, experiment_version=1, solid_custom_position='cell1_we', solid_plate_id=4534, solid_sample_no=1)

Load solid sample onto measurement position.

### helao.experiments.UVIS_exp.UVIS_sub_measure(experiment, experiment_version=1, spec_type='T', spec_n_avg=1, spec_int_time_ms=10, duration_sec=-1, toggle_source='doric_wled', toggle_is_shutter=False, illumination_wavelength=-1, illumination_intensity=-1, illumination_intensity_date='n/a', illumination_side='front', reference_mode='internal', technique_name='T_UVVIS', run_use='data', comment='')

### helao.experiments.UVIS_exp.UVIS_sub_movetosample(experiment, experiment_version=1, solid_plate_id=4534, solid_sample_no=1)

### helao.experiments.UVIS_exp.UVIS_sub_relmove(experiment, experiment_version=1, offset_x_mm=1.0, offset_y_mm=1.0)

### helao.experiments.UVIS_exp.UVIS_sub_setup_ref(experiment, experiment_version=1, reference_mode='internal', solid_custom_position='cell1_we', solid_plate_id=1, solid_sample_no=2, specref_code=1)

Determine initial and final reference measurements and move to position.

### helao.experiments.UVIS_exp.UVIS_sub_shutdown(experiment)

### helao.experiments.UVIS_exp.UVIS_sub_startup(experiment, experiment_version=2, solid_custom_position='cell1_we', solid_plate_id=4534, solid_sample_no=1)

### helao.experiments.UVIS_exp.UVIS_sub_unloadall_customs(experiment)

Clear samples from measurement position.

## helao.experiments.samples_exp module

### helao.experiments.samples_exp.create_and_load_liquid_sample(experiment, experiment_version=1, volume_ml=1.0, source=['source1', 'source2'], partial_molarity=['partial_molarity1', 'partial_molarity2'], chemical=['chemical1', 'chemical2'], ph=7.0, supplier=['supplier1', 'supplier2'], lot_number=['lot1', 'lot2'], electrolyte_name='name', prep_date='2000-01-01', comment='comment', tray=0, slot=0, vial=0)

creates a custom liquid sample
input fields contain json strings

### helao.experiments.samples_exp.create_assembly_sample(experiment, experiment_version=1, liquid_sample_nos=[1, 2], gas_sample_nos=[1, 2], solid_plate_ids=[1, 2], solid_sample_nos=[1, 2], volume_ml=1.0, comment='comment')

creates a custom assembly sample
from local samples
input fields contain json strings
Args:

> liquid_sample_nos: liquid sample numbers from local liquid sample db
> gas_sample_nos: liquid sample numbers from local gas sample db
> solid_plate_ids: plate ids
> solid_sample_nos: sample_no on plate (one plate_id for each sample_no)

### helao.experiments.samples_exp.create_gas_sample(experiment, experiment_version=1, volume_ml=1.0, source=['source1', 'source2'], partial_molarity=['partial_molarity1', 'partial_molarity2'], chemical=['chemical1', 'chemical2'], supplier=['supplier1', 'supplier2'], lot_number=['lot1', 'lot2'], prep_date='2000-01-01', comment='comment')

creates a custom gas sample
input fields contain json strings

### helao.experiments.samples_exp.create_liquid_sample(experiment, experiment_version=1, volume_ml=1.0, source=['source1', 'source2'], partial_molarity=['partial_molarity1', 'partial_molarity2'], chemical=['chemical1', 'chemical2'], ph=7.0, supplier=['supplier1', 'supplier2'], lot_number=['lot1', 'lot2'], electrolyte_name='name', prep_date='2000-01-01', comment='comment')

creates a custom liquid sample
input fields contain json strings

### helao.experiments.samples_exp.generate_sample_no_list(experiment, experiment_version=1, plate_id=1, sample_code=0, skip_n_samples=0, direction=None, sample_nos=[], sample_nos_operator='', platemap_xys=[(None, None)], platemap_xys_operator='')

tbd

### helao.experiments.samples_exp.load_liquid_sample(experiment, experiment_version=1, liquid_sample_no=0, machine_name='hte-xxxx-xx', tray=0, slot=0, vial=0)

### helao.experiments.samples_exp.orch_sub_wait(experiment, experiment_version=2, wait_time_s=10)

### helao.experiments.samples_exp.sort_plate_sample_no_list(experiment, experiment_version=1, plate_sample_no_list=[2])

tbd

## helao.experiments.simulatews_exp module

Action library for websocket simulator

server_key must be a FastAPI action server defined in config

### helao.experiments.simulatews_exp.SIM_websocket_data(experiment, experiment_version=1, wait_time=3.0, data_duration=5.0)

Produces two data acquisition processes.

## Module contents
