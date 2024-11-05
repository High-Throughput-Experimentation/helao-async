# helao.servers package

## Subpackages

* [helao.servers.action package](helao.servers.action.md)
  * [Submodules](helao.servers.action.md#submodules)
  * [helao.servers.action.analysis_server module](helao.servers.action.md#module-helao.servers.action.analysis_server)
    * [`makeApp()`](helao.servers.action.md#helao.servers.action.analysis_server.makeApp)
  * [helao.servers.action.andor_server module](helao.servers.action.md#helao-servers-action-andor-server-module)
  * [helao.servers.action.biologic_server module](helao.servers.action.md#helao-servers-action-biologic-server-module)
  * [helao.servers.action.calc_server module](helao.servers.action.md#module-helao.servers.action.calc_server)
    * [`makeApp()`](helao.servers.action.md#helao.servers.action.calc_server.makeApp)
  * [helao.servers.action.cam_server module](helao.servers.action.md#module-helao.servers.action.cam_server)
    * [`makeApp()`](helao.servers.action.md#helao.servers.action.cam_server.makeApp)
  * [helao.servers.action.co2sensor_server module](helao.servers.action.md#module-helao.servers.action.co2sensor_server)
    * [`makeApp()`](helao.servers.action.md#helao.servers.action.co2sensor_server.makeApp)
  * [helao.servers.action.cpsim_server module](helao.servers.action.md#helao-servers-action-cpsim-server-module)
  * [helao.servers.action.dbpack_server module](helao.servers.action.md#module-helao.servers.action.dbpack_server)
    * [`makeApp()`](helao.servers.action.md#helao.servers.action.dbpack_server.makeApp)
  * [helao.servers.action.diapump_server module](helao.servers.action.md#module-helao.servers.action.diapump_server)
    * [`makeApp()`](helao.servers.action.md#helao.servers.action.diapump_server.makeApp)
  * [helao.servers.action.galil_io module](helao.servers.action.md#helao-servers-action-galil-io-module)
  * [helao.servers.action.galil_motion module](helao.servers.action.md#helao-servers-action-galil-motion-module)
  * [helao.servers.action.gamry_server module](helao.servers.action.md#helao-servers-action-gamry-server-module)
  * [helao.servers.action.gamry_server2 module](helao.servers.action.md#helao-servers-action-gamry-server2-module)
  * [helao.servers.action.gpsim_server module](helao.servers.action.md#helao-servers-action-gpsim-server-module)
  * [helao.servers.action.kinesis_server module](helao.servers.action.md#module-helao.servers.action.kinesis_server)
    * [`makeApp()`](helao.servers.action.md#helao.servers.action.kinesis_server.makeApp)
  * [helao.servers.action.mfc_server module](helao.servers.action.md#module-helao.servers.action.mfc_server)
    * [`makeApp()`](helao.servers.action.md#helao.servers.action.mfc_server.makeApp)
  * [helao.servers.action.nidaqmx_server module](helao.servers.action.md#module-helao.servers.action.nidaqmx_server)
    * [`makeApp()`](helao.servers.action.md#helao.servers.action.nidaqmx_server.makeApp)
  * [helao.servers.action.o2sensor_server module](helao.servers.action.md#helao-servers-action-o2sensor-server-module)
  * [helao.servers.action.pal_server module](helao.servers.action.md#module-helao.servers.action.pal_server)
    * [`makeApp()`](helao.servers.action.md#helao.servers.action.pal_server.makeApp)
  * [helao.servers.action.spec_server module](helao.servers.action.md#module-helao.servers.action.spec_server)
    * [`makeApp()`](helao.servers.action.md#helao.servers.action.spec_server.makeApp)
  * [helao.servers.action.syringe_server module](helao.servers.action.md#module-helao.servers.action.syringe_server)
    * [`makeApp()`](helao.servers.action.md#helao.servers.action.syringe_server.makeApp)
  * [helao.servers.action.tec_server module](helao.servers.action.md#module-helao.servers.action.tec_server)
    * [`makeApp()`](helao.servers.action.md#helao.servers.action.tec_server.makeApp)
  * [helao.servers.action.ws_simulator module](helao.servers.action.md#module-helao.servers.action.ws_simulator)
    * [`makeApp()`](helao.servers.action.md#helao.servers.action.ws_simulator.makeApp)
  * [Module contents](helao.servers.action.md#module-helao.servers.action)
* [helao.servers.operator package](helao.servers.operator.md)
  * [Submodules](helao.servers.operator.md#submodules)
  * [helao.servers.operator.bokeh_operator module](helao.servers.operator.md#module-helao.servers.operator.bokeh_operator)
    * [`BokehOperator`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator)
      * [`BokehOperator.IOloop()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.IOloop)
      * [`BokehOperator.__init__()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.__init__)
      * [`BokehOperator.add_dynamic_inputs()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.add_dynamic_inputs)
      * [`BokehOperator.add_experiment_to_sequence()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.add_experiment_to_sequence)
      * [`BokehOperator.append_experiment()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.append_experiment)
      * [`BokehOperator.callback_add_expplan()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_add_expplan)
      * [`BokehOperator.callback_append_exp()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_append_exp)
      * [`BokehOperator.callback_append_seq()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_append_seq)
      * [`BokehOperator.callback_changed_plateid()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_changed_plateid)
      * [`BokehOperator.callback_changed_sampleno()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_changed_sampleno)
      * [`BokehOperator.callback_clear_actions()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_clear_actions)
      * [`BokehOperator.callback_clear_experiments()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_clear_experiments)
      * [`BokehOperator.callback_clear_expplan()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_clear_expplan)
      * [`BokehOperator.callback_clear_sequences()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_clear_sequences)
      * [`BokehOperator.callback_clicked_pmplot()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_clicked_pmplot)
      * [`BokehOperator.callback_copy_sequence_comment()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_copy_sequence_comment)
      * [`BokehOperator.callback_copy_sequence_comment2()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_copy_sequence_comment2)
      * [`BokehOperator.callback_copy_sequence_label()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_copy_sequence_label)
      * [`BokehOperator.callback_copy_sequence_label2()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_copy_sequence_label2)
      * [`BokehOperator.callback_enqueue_seqspec()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_enqueue_seqspec)
      * [`BokehOperator.callback_estop_orch()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_estop_orch)
      * [`BokehOperator.callback_experiment_select()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_experiment_select)
      * [`BokehOperator.callback_plate_sample_no_list_file()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_plate_sample_no_list_file)
      * [`BokehOperator.callback_prepend_exp()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_prepend_exp)
      * [`BokehOperator.callback_prepend_seq()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_prepend_seq)
      * [`BokehOperator.callback_reload_seqspec()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_reload_seqspec)
      * [`BokehOperator.callback_seqspec_select()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_seqspec_select)
      * [`BokehOperator.callback_sequence_select()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_sequence_select)
      * [`BokehOperator.callback_skip_exp()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_skip_exp)
      * [`BokehOperator.callback_start_orch()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_start_orch)
      * [`BokehOperator.callback_stop_orch()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_stop_orch)
      * [`BokehOperator.callback_to_seqtab()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_to_seqtab)
      * [`BokehOperator.callback_toggle_stepact()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_toggle_stepact)
      * [`BokehOperator.callback_toggle_stepexp()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_toggle_stepexp)
      * [`BokehOperator.callback_toggle_stepseq()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_toggle_stepseq)
      * [`BokehOperator.callback_update_tables()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.callback_update_tables)
      * [`BokehOperator.cleanup_session()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.cleanup_session)
      * [`BokehOperator.find_input()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.find_input)
      * [`BokehOperator.find_param_private_input()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.find_param_private_input)
      * [`BokehOperator.find_plot()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.find_plot)
      * [`BokehOperator.flip_stepwise_flag()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.flip_stepwise_flag)
      * [`BokehOperator.get_actions()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.get_actions)
      * [`BokehOperator.get_active_actions()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.get_active_actions)
      * [`BokehOperator.get_elements_plateid()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.get_elements_plateid)
      * [`BokehOperator.get_experiment_lib()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.get_experiment_lib)
      * [`BokehOperator.get_experiments()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.get_experiments)
      * [`BokehOperator.get_last_exp_pars()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.get_last_exp_pars)
      * [`BokehOperator.get_last_seq_pars()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.get_last_seq_pars)
      * [`BokehOperator.get_orch_status_summary()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.get_orch_status_summary)
      * [`BokehOperator.get_pm()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.get_pm)
      * [`BokehOperator.get_sample_infos()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.get_sample_infos)
      * [`BokehOperator.get_samples()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.get_samples)
      * [`BokehOperator.get_seqspec_lib()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.get_seqspec_lib)
      * [`BokehOperator.get_sequence_lib()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.get_sequence_lib)
      * [`BokehOperator.get_sequences()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.get_sequences)
      * [`BokehOperator.populate_experimentmodel()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.populate_experimentmodel)
      * [`BokehOperator.populate_sequence()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.populate_sequence)
      * [`BokehOperator.prepend_experiment()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.prepend_experiment)
      * [`BokehOperator.read_params()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.read_params)
      * [`BokehOperator.refresh_inputs()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.refresh_inputs)
      * [`BokehOperator.update_error()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.update_error)
      * [`BokehOperator.update_exp_doc()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.update_exp_doc)
      * [`BokehOperator.update_exp_param_layout()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.update_exp_param_layout)
      * [`BokehOperator.update_input_value()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.update_input_value)
      * [`BokehOperator.update_pm_plot()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.update_pm_plot)
      * [`BokehOperator.update_queuecount_labels()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.update_queuecount_labels)
      * [`BokehOperator.update_selector_layout()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.update_selector_layout)
      * [`BokehOperator.update_seq_doc()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.update_seq_doc)
      * [`BokehOperator.update_seq_param_layout()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.update_seq_param_layout)
      * [`BokehOperator.update_seqspec_doc()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.update_seqspec_doc)
      * [`BokehOperator.update_seqspec_param_layout()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.update_seqspec_param_layout)
      * [`BokehOperator.update_stepwise_toggle()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.update_stepwise_toggle)
      * [`BokehOperator.update_tables()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.update_tables)
      * [`BokehOperator.update_xysamples()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.update_xysamples)
      * [`BokehOperator.write_params()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.write_params)
      * [`BokehOperator.xy_to_sample()`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.BokehOperator.xy_to_sample)
    * [`return_experiment_lib`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_experiment_lib)
      * [`return_experiment_lib.args`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_experiment_lib.args)
      * [`return_experiment_lib.argtypes`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_experiment_lib.argtypes)
      * [`return_experiment_lib.defaults`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_experiment_lib.defaults)
      * [`return_experiment_lib.doc`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_experiment_lib.doc)
      * [`return_experiment_lib.experiment_name`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_experiment_lib.experiment_name)
      * [`return_experiment_lib.index`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_experiment_lib.index)
      * [`return_experiment_lib.model_computed_fields`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_experiment_lib.model_computed_fields)
      * [`return_experiment_lib.model_config`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_experiment_lib.model_config)
      * [`return_experiment_lib.model_fields`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_experiment_lib.model_fields)
    * [`return_sequence_lib`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_sequence_lib)
      * [`return_sequence_lib.args`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_sequence_lib.args)
      * [`return_sequence_lib.argtypes`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_sequence_lib.argtypes)
      * [`return_sequence_lib.defaults`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_sequence_lib.defaults)
      * [`return_sequence_lib.doc`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_sequence_lib.doc)
      * [`return_sequence_lib.index`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_sequence_lib.index)
      * [`return_sequence_lib.model_computed_fields`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_sequence_lib.model_computed_fields)
      * [`return_sequence_lib.model_config`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_sequence_lib.model_config)
      * [`return_sequence_lib.model_fields`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_sequence_lib.model_fields)
      * [`return_sequence_lib.sequence_name`](helao.servers.operator.md#helao.servers.operator.bokeh_operator.return_sequence_lib.sequence_name)
  * [helao.servers.operator.finish_analysis module](helao.servers.operator.md#helao-servers-operator-finish-analysis-module)
  * [helao.servers.operator.gcld_operator module](helao.servers.operator.md#module-helao.servers.operator.gcld_operator)
    * [`ana_constructor()`](helao.servers.operator.md#helao.servers.operator.gcld_operator.ana_constructor)
    * [`gen_ts()`](helao.servers.operator.md#helao.servers.operator.gcld_operator.gen_ts)
    * [`main()`](helao.servers.operator.md#helao.servers.operator.gcld_operator.main)
    * [`num_uploads()`](helao.servers.operator.md#helao.servers.operator.gcld_operator.num_uploads)
    * [`qc_constructor()`](helao.servers.operator.md#helao.servers.operator.gcld_operator.qc_constructor)
    * [`seq_constructor()`](helao.servers.operator.md#helao.servers.operator.gcld_operator.seq_constructor)
    * [`wait_for_orch()`](helao.servers.operator.md#helao.servers.operator.gcld_operator.wait_for_orch)
  * [helao.servers.operator.gcld_operator_test module](helao.servers.operator.md#helao-servers-operator-gcld-operator-test-module)
  * [helao.servers.operator.helao_operator module](helao.servers.operator.md#module-helao.servers.operator.helao_operator)
    * [`HelaoOperator`](helao.servers.operator.md#helao.servers.operator.helao_operator.HelaoOperator)
      * [`HelaoOperator.__init__()`](helao.servers.operator.md#helao.servers.operator.helao_operator.HelaoOperator.__init__)
      * [`HelaoOperator.add_experiment()`](helao.servers.operator.md#helao.servers.operator.helao_operator.HelaoOperator.add_experiment)
      * [`HelaoOperator.add_sequence()`](helao.servers.operator.md#helao.servers.operator.helao_operator.HelaoOperator.add_sequence)
      * [`HelaoOperator.get_active_experiment()`](helao.servers.operator.md#helao.servers.operator.helao_operator.HelaoOperator.get_active_experiment)
      * [`HelaoOperator.get_active_sequence()`](helao.servers.operator.md#helao.servers.operator.helao_operator.HelaoOperator.get_active_sequence)
      * [`HelaoOperator.orch_state()`](helao.servers.operator.md#helao.servers.operator.helao_operator.HelaoOperator.orch_state)
      * [`HelaoOperator.request()`](helao.servers.operator.md#helao.servers.operator.helao_operator.HelaoOperator.request)
      * [`HelaoOperator.start()`](helao.servers.operator.md#helao.servers.operator.helao_operator.HelaoOperator.start)
      * [`HelaoOperator.stop()`](helao.servers.operator.md#helao.servers.operator.helao_operator.HelaoOperator.stop)
  * [Module contents](helao.servers.operator.md#module-helao.servers.operator)
* [helao.servers.visualizer package](helao.servers.visualizer.md)
  * [Submodules](helao.servers.visualizer.md#submodules)
  * [helao.servers.visualizer.action_visualizer module](helao.servers.visualizer.md#module-helao.servers.visualizer.action_visualizer)
    * [`makeBokehApp()`](helao.servers.visualizer.md#helao.servers.visualizer.action_visualizer.makeBokehApp)
  * [helao.servers.visualizer.biologic_vis module](helao.servers.visualizer.md#module-helao.servers.visualizer.biologic_vis)
    * [`C_biovis`](helao.servers.visualizer.md#helao.servers.visualizer.biologic_vis.C_biovis)
      * [`C_biovis.IOloop_data()`](helao.servers.visualizer.md#helao.servers.visualizer.biologic_vis.C_biovis.IOloop_data)
      * [`C_biovis.__init__()`](helao.servers.visualizer.md#helao.servers.visualizer.biologic_vis.C_biovis.__init__)
      * [`C_biovis.add_points()`](helao.servers.visualizer.md#helao.servers.visualizer.biologic_vis.C_biovis.add_points)
      * [`C_biovis.callback_input_max_points()`](helao.servers.visualizer.md#helao.servers.visualizer.biologic_vis.C_biovis.callback_input_max_points)
      * [`C_biovis.callback_selector_change()`](helao.servers.visualizer.md#helao.servers.visualizer.biologic_vis.C_biovis.callback_selector_change)
      * [`C_biovis.cleanup_session()`](helao.servers.visualizer.md#helao.servers.visualizer.biologic_vis.C_biovis.cleanup_session)
      * [`C_biovis.reset_plot()`](helao.servers.visualizer.md#helao.servers.visualizer.biologic_vis.C_biovis.reset_plot)
      * [`C_biovis.update_input_value()`](helao.servers.visualizer.md#helao.servers.visualizer.biologic_vis.C_biovis.update_input_value)
  * [helao.servers.visualizer.co2_vis module](helao.servers.visualizer.md#module-helao.servers.visualizer.co2_vis)
    * [`C_co2`](helao.servers.visualizer.md#helao.servers.visualizer.co2_vis.C_co2)
      * [`C_co2.IOloop_data()`](helao.servers.visualizer.md#helao.servers.visualizer.co2_vis.C_co2.IOloop_data)
      * [`C_co2.__init__()`](helao.servers.visualizer.md#helao.servers.visualizer.co2_vis.C_co2.__init__)
      * [`C_co2.add_points()`](helao.servers.visualizer.md#helao.servers.visualizer.co2_vis.C_co2.add_points)
      * [`C_co2.callback_input_max_points()`](helao.servers.visualizer.md#helao.servers.visualizer.co2_vis.C_co2.callback_input_max_points)
      * [`C_co2.callback_input_update_rate()`](helao.servers.visualizer.md#helao.servers.visualizer.co2_vis.C_co2.callback_input_update_rate)
      * [`C_co2.cleanup_session()`](helao.servers.visualizer.md#helao.servers.visualizer.co2_vis.C_co2.cleanup_session)
      * [`C_co2.reset_plot()`](helao.servers.visualizer.md#helao.servers.visualizer.co2_vis.C_co2.reset_plot)
      * [`C_co2.update_input_value()`](helao.servers.visualizer.md#helao.servers.visualizer.co2_vis.C_co2.update_input_value)
  * [helao.servers.visualizer.gamry_vis module](helao.servers.visualizer.md#module-helao.servers.visualizer.gamry_vis)
    * [`C_potvis`](helao.servers.visualizer.md#helao.servers.visualizer.gamry_vis.C_potvis)
      * [`C_potvis.IOloop_data()`](helao.servers.visualizer.md#helao.servers.visualizer.gamry_vis.C_potvis.IOloop_data)
      * [`C_potvis.__init__()`](helao.servers.visualizer.md#helao.servers.visualizer.gamry_vis.C_potvis.__init__)
      * [`C_potvis.add_points()`](helao.servers.visualizer.md#helao.servers.visualizer.gamry_vis.C_potvis.add_points)
      * [`C_potvis.callback_input_max_points()`](helao.servers.visualizer.md#helao.servers.visualizer.gamry_vis.C_potvis.callback_input_max_points)
      * [`C_potvis.callback_input_max_prev()`](helao.servers.visualizer.md#helao.servers.visualizer.gamry_vis.C_potvis.callback_input_max_prev)
      * [`C_potvis.callback_selector_change()`](helao.servers.visualizer.md#helao.servers.visualizer.gamry_vis.C_potvis.callback_selector_change)
      * [`C_potvis.callback_stop_measure()`](helao.servers.visualizer.md#helao.servers.visualizer.gamry_vis.C_potvis.callback_stop_measure)
      * [`C_potvis.cleanup_session()`](helao.servers.visualizer.md#helao.servers.visualizer.gamry_vis.C_potvis.cleanup_session)
      * [`C_potvis.reset_plot()`](helao.servers.visualizer.md#helao.servers.visualizer.gamry_vis.C_potvis.reset_plot)
      * [`C_potvis.update_input_value()`](helao.servers.visualizer.md#helao.servers.visualizer.gamry_vis.C_potvis.update_input_value)
  * [helao.servers.visualizer.gpsim_live_vis module](helao.servers.visualizer.md#module-helao.servers.visualizer.gpsim_live_vis)
    * [`C_gpsimlivevis`](helao.servers.visualizer.md#helao.servers.visualizer.gpsim_live_vis.C_gpsimlivevis)
      * [`C_gpsimlivevis.IOloop_data()`](helao.servers.visualizer.md#helao.servers.visualizer.gpsim_live_vis.C_gpsimlivevis.IOloop_data)
      * [`C_gpsimlivevis.__init__()`](helao.servers.visualizer.md#helao.servers.visualizer.gpsim_live_vis.C_gpsimlivevis.__init__)
      * [`C_gpsimlivevis.add_points()`](helao.servers.visualizer.md#helao.servers.visualizer.gpsim_live_vis.C_gpsimlivevis.add_points)
      * [`C_gpsimlivevis.callback_input_update_rate()`](helao.servers.visualizer.md#helao.servers.visualizer.gpsim_live_vis.C_gpsimlivevis.callback_input_update_rate)
      * [`C_gpsimlivevis.cleanup_session()`](helao.servers.visualizer.md#helao.servers.visualizer.gpsim_live_vis.C_gpsimlivevis.cleanup_session)
      * [`C_gpsimlivevis.update_input_value()`](helao.servers.visualizer.md#helao.servers.visualizer.gpsim_live_vis.C_gpsimlivevis.update_input_value)
  * [helao.servers.visualizer.live_visualizer module](helao.servers.visualizer.md#module-helao.servers.visualizer.live_visualizer)
    * [`makeBokehApp()`](helao.servers.visualizer.md#helao.servers.visualizer.live_visualizer.makeBokehApp)
  * [helao.servers.visualizer.mfc_vis module](helao.servers.visualizer.md#module-helao.servers.visualizer.mfc_vis)
    * [`C_mfc`](helao.servers.visualizer.md#helao.servers.visualizer.mfc_vis.C_mfc)
      * [`C_mfc.IOloop_data()`](helao.servers.visualizer.md#helao.servers.visualizer.mfc_vis.C_mfc.IOloop_data)
      * [`C_mfc.__init__()`](helao.servers.visualizer.md#helao.servers.visualizer.mfc_vis.C_mfc.__init__)
      * [`C_mfc.add_points()`](helao.servers.visualizer.md#helao.servers.visualizer.mfc_vis.C_mfc.add_points)
      * [`C_mfc.callback_input_max_points()`](helao.servers.visualizer.md#helao.servers.visualizer.mfc_vis.C_mfc.callback_input_max_points)
      * [`C_mfc.callback_input_update_rate()`](helao.servers.visualizer.md#helao.servers.visualizer.mfc_vis.C_mfc.callback_input_update_rate)
      * [`C_mfc.cleanup_session()`](helao.servers.visualizer.md#helao.servers.visualizer.mfc_vis.C_mfc.cleanup_session)
      * [`C_mfc.reset_plot()`](helao.servers.visualizer.md#helao.servers.visualizer.mfc_vis.C_mfc.reset_plot)
      * [`C_mfc.update_input_value()`](helao.servers.visualizer.md#helao.servers.visualizer.mfc_vis.C_mfc.update_input_value)
  * [helao.servers.visualizer.nidaqmx_vis module](helao.servers.visualizer.md#module-helao.servers.visualizer.nidaqmx_vis)
    * [`C_nidaqmxvis`](helao.servers.visualizer.md#helao.servers.visualizer.nidaqmx_vis.C_nidaqmxvis)
      * [`C_nidaqmxvis.IOloop_data()`](helao.servers.visualizer.md#helao.servers.visualizer.nidaqmx_vis.C_nidaqmxvis.IOloop_data)
      * [`C_nidaqmxvis.__init__()`](helao.servers.visualizer.md#helao.servers.visualizer.nidaqmx_vis.C_nidaqmxvis.__init__)
      * [`C_nidaqmxvis.add_points()`](helao.servers.visualizer.md#helao.servers.visualizer.nidaqmx_vis.C_nidaqmxvis.add_points)
      * [`C_nidaqmxvis.callback_input_max_points()`](helao.servers.visualizer.md#helao.servers.visualizer.nidaqmx_vis.C_nidaqmxvis.callback_input_max_points)
      * [`C_nidaqmxvis.cleanup_session()`](helao.servers.visualizer.md#helao.servers.visualizer.nidaqmx_vis.C_nidaqmxvis.cleanup_session)
      * [`C_nidaqmxvis.reset_plot()`](helao.servers.visualizer.md#helao.servers.visualizer.nidaqmx_vis.C_nidaqmxvis.reset_plot)
      * [`C_nidaqmxvis.update_input_value()`](helao.servers.visualizer.md#helao.servers.visualizer.nidaqmx_vis.C_nidaqmxvis.update_input_value)
  * [helao.servers.visualizer.oersim_vis module](helao.servers.visualizer.md#module-helao.servers.visualizer.oersim_vis)
    * [`C_oersimvis`](helao.servers.visualizer.md#helao.servers.visualizer.oersim_vis.C_oersimvis)
      * [`C_oersimvis.IOloop_data()`](helao.servers.visualizer.md#helao.servers.visualizer.oersim_vis.C_oersimvis.IOloop_data)
      * [`C_oersimvis.__init__()`](helao.servers.visualizer.md#helao.servers.visualizer.oersim_vis.C_oersimvis.__init__)
      * [`C_oersimvis.add_points()`](helao.servers.visualizer.md#helao.servers.visualizer.oersim_vis.C_oersimvis.add_points)
      * [`C_oersimvis.callback_input_max_points()`](helao.servers.visualizer.md#helao.servers.visualizer.oersim_vis.C_oersimvis.callback_input_max_points)
      * [`C_oersimvis.cleanup_session()`](helao.servers.visualizer.md#helao.servers.visualizer.oersim_vis.C_oersimvis.cleanup_session)
      * [`C_oersimvis.reset_plot()`](helao.servers.visualizer.md#helao.servers.visualizer.oersim_vis.C_oersimvis.reset_plot)
      * [`C_oersimvis.update_input_value()`](helao.servers.visualizer.md#helao.servers.visualizer.oersim_vis.C_oersimvis.update_input_value)
  * [helao.servers.visualizer.pal_vis module](helao.servers.visualizer.md#module-helao.servers.visualizer.pal_vis)
    * [`C_palvis`](helao.servers.visualizer.md#helao.servers.visualizer.pal_vis.C_palvis)
      * [`C_palvis.IOloop_data()`](helao.servers.visualizer.md#helao.servers.visualizer.pal_vis.C_palvis.IOloop_data)
      * [`C_palvis.__init__()`](helao.servers.visualizer.md#helao.servers.visualizer.pal_vis.C_palvis.__init__)
      * [`C_palvis.add_points()`](helao.servers.visualizer.md#helao.servers.visualizer.pal_vis.C_palvis.add_points)
      * [`C_palvis.callback_inheritance()`](helao.servers.visualizer.md#helao.servers.visualizer.pal_vis.C_palvis.callback_inheritance)
      * [`C_palvis.callback_input_max_smps()`](helao.servers.visualizer.md#helao.servers.visualizer.pal_vis.C_palvis.callback_input_max_smps)
      * [`C_palvis.cleanup_session()`](helao.servers.visualizer.md#helao.servers.visualizer.pal_vis.C_palvis.cleanup_session)
      * [`C_palvis.reset_plot()`](helao.servers.visualizer.md#helao.servers.visualizer.pal_vis.C_palvis.reset_plot)
      * [`C_palvis.update_inheritance_selector()`](helao.servers.visualizer.md#helao.servers.visualizer.pal_vis.C_palvis.update_inheritance_selector)
      * [`C_palvis.update_input_value()`](helao.servers.visualizer.md#helao.servers.visualizer.pal_vis.C_palvis.update_input_value)
    * [`async_partial()`](helao.servers.visualizer.md#helao.servers.visualizer.pal_vis.async_partial)
  * [helao.servers.visualizer.pressure_vis module](helao.servers.visualizer.md#module-helao.servers.visualizer.pressure_vis)
    * [`C_pressure`](helao.servers.visualizer.md#helao.servers.visualizer.pressure_vis.C_pressure)
      * [`C_pressure.IOloop_data()`](helao.servers.visualizer.md#helao.servers.visualizer.pressure_vis.C_pressure.IOloop_data)
      * [`C_pressure.__init__()`](helao.servers.visualizer.md#helao.servers.visualizer.pressure_vis.C_pressure.__init__)
      * [`C_pressure.add_points()`](helao.servers.visualizer.md#helao.servers.visualizer.pressure_vis.C_pressure.add_points)
      * [`C_pressure.callback_input_max_points()`](helao.servers.visualizer.md#helao.servers.visualizer.pressure_vis.C_pressure.callback_input_max_points)
      * [`C_pressure.callback_input_update_rate()`](helao.servers.visualizer.md#helao.servers.visualizer.pressure_vis.C_pressure.callback_input_update_rate)
      * [`C_pressure.cleanup_session()`](helao.servers.visualizer.md#helao.servers.visualizer.pressure_vis.C_pressure.cleanup_session)
      * [`C_pressure.reset_plot()`](helao.servers.visualizer.md#helao.servers.visualizer.pressure_vis.C_pressure.reset_plot)
      * [`C_pressure.update_input_value()`](helao.servers.visualizer.md#helao.servers.visualizer.pressure_vis.C_pressure.update_input_value)
  * [helao.servers.visualizer.spec_vis module](helao.servers.visualizer.md#module-helao.servers.visualizer.spec_vis)
    * [`C_specvis`](helao.servers.visualizer.md#helao.servers.visualizer.spec_vis.C_specvis)
      * [`C_specvis.IOloop_data()`](helao.servers.visualizer.md#helao.servers.visualizer.spec_vis.C_specvis.IOloop_data)
      * [`C_specvis.__init__()`](helao.servers.visualizer.md#helao.servers.visualizer.spec_vis.C_specvis.__init__)
      * [`C_specvis.add_points()`](helao.servers.visualizer.md#helao.servers.visualizer.spec_vis.C_specvis.add_points)
      * [`C_specvis.callback_input_downsample()`](helao.servers.visualizer.md#helao.servers.visualizer.spec_vis.C_specvis.callback_input_downsample)
      * [`C_specvis.callback_input_max_spectra()`](helao.servers.visualizer.md#helao.servers.visualizer.spec_vis.C_specvis.callback_input_max_spectra)
      * [`C_specvis.cleanup_session()`](helao.servers.visualizer.md#helao.servers.visualizer.spec_vis.C_specvis.cleanup_session)
      * [`C_specvis.reset_plot()`](helao.servers.visualizer.md#helao.servers.visualizer.spec_vis.C_specvis.reset_plot)
      * [`C_specvis.update_input_value()`](helao.servers.visualizer.md#helao.servers.visualizer.spec_vis.C_specvis.update_input_value)
  * [helao.servers.visualizer.syringe_vis module](helao.servers.visualizer.md#module-helao.servers.visualizer.syringe_vis)
    * [`C_syringe`](helao.servers.visualizer.md#helao.servers.visualizer.syringe_vis.C_syringe)
      * [`C_syringe.IOloop_data()`](helao.servers.visualizer.md#helao.servers.visualizer.syringe_vis.C_syringe.IOloop_data)
      * [`C_syringe.__init__()`](helao.servers.visualizer.md#helao.servers.visualizer.syringe_vis.C_syringe.__init__)
      * [`C_syringe.add_points()`](helao.servers.visualizer.md#helao.servers.visualizer.syringe_vis.C_syringe.add_points)
      * [`C_syringe.callback_input_max_points()`](helao.servers.visualizer.md#helao.servers.visualizer.syringe_vis.C_syringe.callback_input_max_points)
      * [`C_syringe.callback_input_update_rate()`](helao.servers.visualizer.md#helao.servers.visualizer.syringe_vis.C_syringe.callback_input_update_rate)
      * [`C_syringe.cleanup_session()`](helao.servers.visualizer.md#helao.servers.visualizer.syringe_vis.C_syringe.cleanup_session)
      * [`C_syringe.reset_plot()`](helao.servers.visualizer.md#helao.servers.visualizer.syringe_vis.C_syringe.reset_plot)
      * [`C_syringe.update_input_value()`](helao.servers.visualizer.md#helao.servers.visualizer.syringe_vis.C_syringe.update_input_value)
  * [helao.servers.visualizer.tec_vis module](helao.servers.visualizer.md#module-helao.servers.visualizer.tec_vis)
    * [`C_tec`](helao.servers.visualizer.md#helao.servers.visualizer.tec_vis.C_tec)
      * [`C_tec.IOloop_data()`](helao.servers.visualizer.md#helao.servers.visualizer.tec_vis.C_tec.IOloop_data)
      * [`C_tec.__init__()`](helao.servers.visualizer.md#helao.servers.visualizer.tec_vis.C_tec.__init__)
      * [`C_tec.add_points()`](helao.servers.visualizer.md#helao.servers.visualizer.tec_vis.C_tec.add_points)
      * [`C_tec.callback_input_max_points()`](helao.servers.visualizer.md#helao.servers.visualizer.tec_vis.C_tec.callback_input_max_points)
      * [`C_tec.callback_input_update_rate()`](helao.servers.visualizer.md#helao.servers.visualizer.tec_vis.C_tec.callback_input_update_rate)
      * [`C_tec.cleanup_session()`](helao.servers.visualizer.md#helao.servers.visualizer.tec_vis.C_tec.cleanup_session)
      * [`C_tec.reset_plot()`](helao.servers.visualizer.md#helao.servers.visualizer.tec_vis.C_tec.reset_plot)
      * [`C_tec.update_input_value()`](helao.servers.visualizer.md#helao.servers.visualizer.tec_vis.C_tec.update_input_value)
  * [helao.servers.visualizer.temp_vis module](helao.servers.visualizer.md#module-helao.servers.visualizer.temp_vis)
    * [`C_temperature`](helao.servers.visualizer.md#helao.servers.visualizer.temp_vis.C_temperature)
      * [`C_temperature.IOloop_data()`](helao.servers.visualizer.md#helao.servers.visualizer.temp_vis.C_temperature.IOloop_data)
      * [`C_temperature.__init__()`](helao.servers.visualizer.md#helao.servers.visualizer.temp_vis.C_temperature.__init__)
      * [`C_temperature.add_points()`](helao.servers.visualizer.md#helao.servers.visualizer.temp_vis.C_temperature.add_points)
      * [`C_temperature.callback_input_max_points()`](helao.servers.visualizer.md#helao.servers.visualizer.temp_vis.C_temperature.callback_input_max_points)
      * [`C_temperature.callback_input_update_rate()`](helao.servers.visualizer.md#helao.servers.visualizer.temp_vis.C_temperature.callback_input_update_rate)
      * [`C_temperature.cleanup_session()`](helao.servers.visualizer.md#helao.servers.visualizer.temp_vis.C_temperature.cleanup_session)
      * [`C_temperature.reset_plot()`](helao.servers.visualizer.md#helao.servers.visualizer.temp_vis.C_temperature.reset_plot)
      * [`C_temperature.update_input_value()`](helao.servers.visualizer.md#helao.servers.visualizer.temp_vis.C_temperature.update_input_value)
  * [helao.servers.visualizer.wssim_live_vis module](helao.servers.visualizer.md#module-helao.servers.visualizer.wssim_live_vis)
    * [`C_simlivevis`](helao.servers.visualizer.md#helao.servers.visualizer.wssim_live_vis.C_simlivevis)
      * [`C_simlivevis.IOloop_data()`](helao.servers.visualizer.md#helao.servers.visualizer.wssim_live_vis.C_simlivevis.IOloop_data)
      * [`C_simlivevis.__init__()`](helao.servers.visualizer.md#helao.servers.visualizer.wssim_live_vis.C_simlivevis.__init__)
      * [`C_simlivevis.add_points()`](helao.servers.visualizer.md#helao.servers.visualizer.wssim_live_vis.C_simlivevis.add_points)
      * [`C_simlivevis.callback_input_max_points()`](helao.servers.visualizer.md#helao.servers.visualizer.wssim_live_vis.C_simlivevis.callback_input_max_points)
      * [`C_simlivevis.callback_input_update_rate()`](helao.servers.visualizer.md#helao.servers.visualizer.wssim_live_vis.C_simlivevis.callback_input_update_rate)
      * [`C_simlivevis.cleanup_session()`](helao.servers.visualizer.md#helao.servers.visualizer.wssim_live_vis.C_simlivevis.cleanup_session)
      * [`C_simlivevis.update_input_value()`](helao.servers.visualizer.md#helao.servers.visualizer.wssim_live_vis.C_simlivevis.update_input_value)
  * [Module contents](helao.servers.visualizer.md#module-helao.servers.visualizer)

## Submodules

## helao.servers.base module

### *class* helao.servers.base.Active(base, activeparams)

Bases: `object`

The Active class represents an active action within a server. It manages the lifecycle of an action, including initialization, execution, data logging, and finalization. The class provides methods to handle various aspects of an action, such as starting executors, logging data, handling errors, and managing file connections.

Attributes:
: base: The base server instance.
  active_uuid: The unique identifier for the active action.
  action: The current action being managed.
  action_list: A list of all actions associated with this active instance.
  listen_uuids: A list of UUIDs to listen for data logging.
  num_data_queued: The number of data items queued for logging.
  num_data_written: The number of data items written to files.
  file_conn_dict: A dictionary mapping file connection keys to FileConn instances.
  manual_stop: A flag indicating if the action should be manually stopped.
  action_loop_running: A flag indicating if the action loop is currently running.
  action_task: The asyncio task for the action loop.

Methods:
: \_\_init_\_(self, base, activeparams: ActiveParams):
  : Initializes the Active instance with the given base server and active parameters.
  <br/>
  executor_done_callback(self, futr):
  : Callback function to handle the completion of an executor.
  <br/>
  start_executor(self, executor: Executor):
  : Starts the executor for the action.
  <br/>
  oneoff_executor(self, executor: Executor):
  : Executes a one-off action using the executor.
  <br/>
  update_act_file(self):
  : Updates the action file with the current action state.
  <br/>
  myinit(self):
  : Initializes the data logger and action file.
  <br/>
  init_datafile(self, header, file_type, json_data_keys, file_sample_label, filename, file_group: HloFileGroup, file_conn_key: str = None, action: Action = None):
  : Initializes a data file with the given parameters.
  <br/>
  finish_hlo_header(self, file_conn_keys: List[UUID] = None, realtime: float = None):
  : Adds a timestamp to the data file header.
  <br/>
  add_status(self, action=None):
  : Sends the status of the most recent active action.
  <br/>
  set_estop(self, action: Action = None):
  : Sets the emergency stop status for the action.
  <br/>
  set_error(self, error_code: ErrorCodes = None, action: Action = None):
  : Sets the error status for the action.
  <br/>
  get_realtime(self, epoch_ns: float = None, offset: float = None) -> float:
  : Gets the current real-time with optional epoch and offset.
  <br/>
  get_realtime_nowait(self, epoch_ns: float = None, offset: float = None) -> float:
  : Gets the current real-time without waiting.
  <br/>
  write_live_data(self, output_str: str, file_conn_key: UUID):
  : Appends lines to the file connection.
  <br/>
  enqueue_data_dflt(self, datadict: dict):
  : Enqueues data to a default file connection key.
  <br/>
  enqueue_data(self, datamodel: DataModel, action: Action = None):
  : Enqueues data to the data queue.
  <br/>
  enqueue_data_nowait(self, datamodel: DataModel, action: Action = None):
  : Enqueues data to the data queue without waiting.
  <br/>
  assemble_data_msg(self, datamodel: DataModel, action: Action = None) -> DataPackageModel:
  : Assembles a data message for the given data model and action.
  <br/>
  add_new_listen_uuid(self, new_uuid: UUID):
  : Adds a new UUID to the data logger UUID list.
  <br/>
  \_get_action_for_file_conn_key(self, file_conn_key: UUID):
  : Gets the action associated with the given file connection key.
  <br/>
  log_data_set_output_file(self, file_conn_key: UUID):
  : Sets the output file for logging data.
  <br/>
  log_data_task(self):
  : Subscribes to the data queue and writes data to the file.
  <br/>
  write_file(self, output_str: str, file_type: str, filename: str = None, file_group: HloFileGroup = HloFileGroup.aux_files, header: str = None, sample_str: str = None, file_sample_label: str = None, json_data_keys: str = None, action: Action = None):
  : Writes a complete file with the given parameters.
  <br/>
  write_file_nowait(self, output_str: str, file_type: str, filename: str = None, file_group: HloFileGroup = HloFileGroup.aux_files, header: str = None, sample_str: str = None, file_sample_label: str = None, json_data_keys: str = None, action: Action = None):
  : Writes a complete file with the given parameters without waiting.
  <br/>
  set_sample_action_uuid(self, sample: SampleUnion, action_uuid: UUID):
  : Sets the action UUID for the given sample.
  <br/>
  append_sample(self, samples: List[SampleUnion], IO: str, action: Action = None):
  : Adds samples to the input or output sample list.
  <br/>
  split_and_keep_active(self):
  : Splits the current action and keeps it active.
  <br/>
  split_and_finish_prev_uuids(self):
  : Splits the current action and finishes previous UUIDs.
  <br/>
  finish_all(self):
  : Finishes all actions.
  <br/>
  split(self, uuid_list: Optional[List[UUID]] = None, new_fileconnparams: Optional[FileConnParams] = None) -> List[UUID]:
  : Splits the current action and finishes previous actions in the UUID list.
  <br/>
  substitute(self):
  : Closes all file connections.
  <br/>
  finish(self, finish_uuid_list: List[UUID] = None) -> Action:
  : Finishes the actions in the UUID list and performs cleanup.
  <br/>
  track_file(self, file_type: str, file_path: str, samples: List[SampleUnion], action: Action = None):
  : Adds auxiliary files to the file dictionary.
  <br/>
  relocate_files(self):
  : Copies auxiliary files to the experiment directory.
  <br/>
  finish_manual_action(self):
  : Finishes a manual action and writes the sequence and experiment meta files.
  <br/>
  send_nonblocking_status(self, retry_limit: int = 3):
  : Sends the non-blocking status to clients.
  <br/>
  action_loop_task(self, executor: Executor):
  : The main loop for executing an action.
  <br/>
  stop_action_task(self):
  : Stops the action loop task.

#### \_\_init_\_(base, activeparams)

Initializes an instance of the class.

Args:
: base: The base instance.
  activeparams (ActiveParams): The active parameters.

Attributes:
: base: The base instance.
  active_uuid: The UUID of the active action.
  action: The active action.
  action_list: A list of all actions for this active instance, with the most recent one at position 0.
  listen_uuids: A list of UUIDs to listen to.
  num_data_queued: The number of data items queued.
  num_data_written: The number of data items written.
  file_conn_dict (Dict[str, FileConn]): A dictionary mapping file connection keys to FileConn instances.
  manual_stop: A flag indicating whether the action has been manually stopped.
  action_loop_running: A flag indicating whether the action loop is running.
  action_task: The task associated with the action.

Notes:
: - Updates the timestamp and UUID of the action if they are None.
  - Sets the action to dummy or simulation mode based on the world configuration.
  - Initializes the action with a time offset.
  - Adds the action UUID to the list of listen UUIDs.
  - Prints a message if the action is a manual action.
  - Checks if the root save directory is specified and sets the save flags accordingly.
  - Adds auxiliary listen UUIDs from the active parameters.
  - Initializes file connections from the active parameters and updates the action’s file connection keys.
  - Prints messages indicating the save flags for the action.

#### *async* action_loop_task(executor)

Asynchronous task that manages the execution of an action loop.

This method handles the lifecycle of an action, including pre-execution setup,
execution, polling for ongoing actions, manual stopping, and post-execution cleanup.
It also manages the registration and deregistration of executors, and handles
non-blocking actions.

Args:
: executor (Executor): The executor responsible for running the action.

Returns:
: The result of the action’s finish method.

Raises:
: Exception: If any exception occurs during the execution or polling of the action.

#### add_new_listen_uuid(new_uuid)

Adds a new UUID to the listen_uuids list.

Args:
: new_uuid (UUID): The new UUID to be added to the list.

#### *async* add_status(action=None)

Adds the given action to the status list and logs the action.

If the action is not provided, it defaults to self.action.

Args:
: action (Optional[Action]): The action to be added to the status list. If None, defaults to self.action.

Returns:
: None

Side Effects:
: - Logs a message indicating the action being added to the status list.
  - If the action is blocking, it waits until the action is added to the status queue.

#### *async* append_sample(samples, IO, action=None)

Append samples to the specified action’s input or output list.

Args:
: samples (List[SampleUnion]): A list of samples to be appended.
  IO (str): Specifies whether the samples are to be appended to the input (‘in’) or output (‘out’) list.
  action (Action, optional): The action to which the samples will be appended. If not provided, the current action is used.

Returns:
: None

Notes:
: - If the samples list is empty, the function returns immediately.
  - Samples of type NoneSample are skipped.
  - The action_uuid of each sample is updated to the current action’s UUID.
  - If a sample’s inheritance is None, it is set to SampleInheritance.allow_both.
  - If a sample’s status is None, it is set to [SampleStatus.preserved].
  - The function broadcasts the status when a sample is added for operator table updates.

#### assemble_data_msg(datamodel, action=None)

Assembles a data message package from the given data model and action.

* **Return type:**
  `DataPackageModel`

Args:
: datamodel (DataModel): The data model containing the data to be packaged.
  action (Action, optional): The action associated with the data. If not provided,
  <br/>
  > the default action of the instance will be used.

Returns:
: DataPackageModel: A data package model containing the action UUID, action name,
  : data model, and any errors from the data model.

#### *async* enqueue_data(datamodel, action=None)

Asynchronously enqueues data into the data queue.

Args:
: datamodel (DataModel): The data model instance containing the data to be enqueued.
  action (Action, optional): The action associated with the data. If not provided,
  <br/>
  > the default action will be used.

Returns:
: None

#### *async* enqueue_data_dflt(datadict)

Asynchronously enqueues data using the default file connection key.

Args:
: datadict (dict): The data dictionary to be enqueued.

Returns:
: None

#### enqueue_data_nowait(datamodel, action=None)

Enqueues a data message into the queue without waiting.

Args:
: datamodel (DataModel): The data model to be enqueued.
  action (Action, optional): The action associated with the data. Defaults to None.

Raises:
: queue.Full: If the queue is full and the data cannot be enqueued.

Notes:
: If action is not provided, the method uses the instance’s self.action.
  Increments self.num_data_queued if datamodel.data is not empty.

#### executor_done_callback(futr)

Callback function to handle the completion of a future.

This function is called when a future is done. It attempts to retrieve the
result of the future. If an exception occurred during the execution of the
future, it catches the exception and prints the traceback.

Args:
: futr (concurrent.futures.Future): The future object that has completed.

#### *async* finish(finish_uuid_list=None)

Finish the actions specified by the given UUIDs or finish all actions if no UUIDs are provided.

This method updates the status of the specified actions to finished, sends global parameters if required,
and ensures that all actions are properly finalized. It also handles the closing of data streams and files,
updates the database, and processes any queued actions.

* **Return type:**
  [`Action`](helao.helpers.md#helao.helpers.premodels.Action)

Args:
: finish_uuid_list (List[UUID], optional): A list of UUIDs of the actions to be finished. If None, all actions will be finished.

Returns:
: Action: The most recent action of the active.

Raises:
: Exception: If any error occurs during the finishing process.

#### *async* finish_all()

#### finish_hlo_header(file_conn_keys=None, realtime=None)

Finalizes the HLO header for the given file connection keys.

This method updates the epoch_ns field in the HLO header of each file
connection specified by file_conn_keys with the provided realtime value.
If realtime is not provided, the current real-time value is used. If
file_conn_keys is not provided, the method will update the HLO header for
all file connections associated with the actions in self.action_list.

Args:
: file_conn_keys (List[UUID], optional): A list of file connection keys
  : to update. If None, all file connection keys from self.action_list
    will be used. Defaults to None.
  <br/>
  realtime (float, optional): The real-time value to set in the HLO header.
  : If None, the current real-time value will be used. Defaults to None.

#### *async* finish_manual_action()

Finalizes the most recent manual action in the action list.

This method checks if the most recent action in the action list is a manual action.
If it is, it creates a deep copy of the action and updates its status to finished.
It then clears the samples and files associated with the action.

The method proceeds to add all actions in the action list to the experiment model
and adds the experiment to the sequence model. Finally, it writes the experiment
and sequence metadata files for the manual operation.

Returns:
: None

#### *async* get_realtime(epoch_ns=None, offset=None)

Asynchronously retrieves the real-time value.

* **Return type:**
  `float`

Args:
: epoch_ns (float, optional): The epoch time in nanoseconds. Defaults to None.
  offset (float, optional): The offset to be applied to the real-time value. Defaults to None.

Returns:
: float: The real-time value with the applied offset.

#### get_realtime_nowait(epoch_ns=None, offset=None)

Retrieve the current real-time value without waiting.

* **Return type:**
  `float`

Args:
: epoch_ns (float, optional): The epoch time in nanoseconds. Defaults to None.
  offset (float, optional): The offset to be applied to the epoch time. Defaults to None.

Returns:
: float: The current real-time value.

#### init_datafile(header, file_type, json_data_keys, file_sample_label, filename, file_group, file_conn_key=None, action=None)

Initializes a data file with the provided parameters and generates the necessary file information.

Args:
: header (Union[dict, list, str, None]): The header information for the file. Can be a dictionary, list, string, or None.
  file_type (str): The type of the file.
  json_data_keys (list): List of keys for JSON data.
  file_sample_label (Union[list, str, None]): Labels for the file samples. Can be a list, string, or None.
  filename (str): The name of the file. If None, a filename will be generated.
  file_group (HloFileGroup): The group to which the file belongs (e.g., heloa_files or aux_files).
  file_conn_key (str, optional): The connection key for the file. Defaults to None.
  action (Action, optional): The action associated with the file. Defaults to None.

Returns:
: tuple: A tuple containing the header (str) and file information (FileInfo).

#### *async* log_data_set_output_file(file_conn_key)

Asynchronously logs data and sets up an output file for a given file connection key.

Args:
: file_conn_key (UUID): The unique identifier for the file connection.

Returns:
: None

This method performs the following steps:
1. Logs the creation of a file for the given file connection key.
2. Retrieves the action associated with the file connection key.
3. Adds missing information to the header if necessary.
4. Initializes the data file with the appropriate header and metadata.
5. Creates the output file and sets up the file connection.
6. Writes the header to the new file if it exists.

#### *async* log_data_task()

Asynchronous task to log data messages from a data queue.

This method subscribes to a data queue and processes incoming data messages.
It checks if data logging is enabled, verifies the status of the data, and
writes the data to the appropriate output files.

The method handles the following:
- Subscribes to the data queue.
- Filters data messages based on action UUIDs.
- Checks the status of the data and skips messages with certain statuses.
- Retrieves the appropriate action for each data message.
- Creates output files if they do not exist.
- Writes data to the output files in JSON format or as raw data.
- Handles errors and exceptions during the logging process.

Exceptions:
: asyncio.CancelledError: Raised when the task is cancelled.
  Exception: Catches all other exceptions and logs the error message and traceback.

Returns:
: None

#### *async* myinit()

Asynchronous initialization method for setting up logging and directories.

This method performs the following tasks:
1. Creates a task for logging data.
2. If the action requires saving, it creates necessary directories and updates the action file.
3. Prints a message indicating the initialization status.
4. Adds the current status.

Returns:
: None

#### *async* oneoff_executor(executor)

Executes a one-off task using the provided executor.

Args:
: executor (Executor): The executor instance to run the task.

Returns:
: The result of the action loop task executed by the provided executor.

#### *async* relocate_files()

Asynchronously relocates files from their current locations to new paths.

This method iterates over the file paths listed in self.action.AUX_file_paths
and moves each file to a new directory specified by combining self.base.helaodirs.save_root
and self.action.action_output_dir. If the source path and the new path are different,
the file is copied to the new location using async_copy.

Returns:
: None

#### *async* send_nonblocking_status(retry_limit=3)

Sends a non-blocking status update to all clients in self.base.status_clients.

This method attempts to send a status update to each client up to retry_limit times.
If the update is successful, a success message is printed. If the update fails after
the specified number of retries, an error message is printed.

Args:
: retry_limit (int): The maximum number of retry attempts for sending the status update.
  : Defaults to 3.

Returns:
: None

#### *async* set_error(error_code=None, action=None)

Sets the error status and error code for the given action.

Args:
: error_code (ErrorCodes, optional): The error code to set. Defaults to None.
  action (Action, optional): The action to update. Defaults to None, in which case self.action is used.

Side Effects:
: - Appends HloStatus.errored to the experiment_status of the action.
  - Sets the error_code of the action to the provided error_code or ErrorCodes.unspecified if not provided.
  - Prints an error message with the action’s UUID and name.

#### set_estop(action=None)

Sets the emergency stop (E-STOP) status for the given action.

Parameters:
action (Action, optional): The action to set the E-STOP status for.

> If None, the current action is used.

Returns:
None

#### set_sample_action_uuid(sample, action_uuid)

Sets the action UUID for a given sample and its parts if the sample is of type ‘assembly’.

Args:
: sample (SampleUnion): The sample object for which the action UUID is to be set.
  action_uuid (UUID): The action UUID to be assigned to the sample.

Returns:
: None

#### *async* split(uuid_list=None, new_fileconnparams=None)

Splits the current action into a new action, creating new file connections
and updating the action status accordingly.

* **Return type:**
  `List`[`UUID`]

Args:
: uuid_list (Optional[List[UUID]]): List of UUIDs to finish. If None, all actions except the current one will be finished.
  new_fileconnparams (Optional[FileConnParams]): Parameters for the new file connection. If None, the previous file connection parameters will be used.

Returns:
: List[UUID]: List of new file connection keys.

Raises:
: Exception: If the split operation fails.

#### *async* split_and_finish_prev_uuids()

Asynchronously splits and finishes previous UUIDs.

This method calls the split method with uuid_list set to None,
which processes and finalizes any previous UUIDs.

Returns:
: None

#### *async* split_and_keep_active()

Asynchronously splits and keeps active.

This method calls the split method with an empty uuid_list.

Returns:
: None

#### start_executor(executor)

Starts the executor task and manages its execution.

Args:
: executor (Executor): The executor instance to be started.

Returns:
: dict: A dictionary representation of the action associated with the executor.

Notes:
: - If the executor does not allow concurrency, the action UUID is appended to the local queue before running the task.
  - The executor task is created and started using the event loop.
  - A callback is added to handle the completion of the executor task.
  - A message indicating the start of the executor task is printed.

#### stop_action_task()

Stops the current action task.

This method sets the manual_stop flag to True and stops the action loop
by setting action_loop_running to False. It also logs a message indicating
that a stop action request has been received.

#### *async* substitute()

#### *async* track_file(file_type, file_path, samples, action=None)

Tracks a file by adding its information to the associated action.

* **Return type:**
  `None`

Args:
: file_type (str): The type of the file being tracked.
  file_path (str): The path to the file being tracked.
  samples (List[SampleUnion]): A list of samples associated with the file.
  action (Action, optional): The action associated with the file. If not provided,
  <br/>
  > the current action will be used.

Returns:
: None

#### *async* update_act_file()

Asynchronously updates the action file by writing the current action.

This method calls the write_act method of the base object, passing the
current action as an argument. It ensures that the action file is updated
with the latest action data.

Returns:
: None

#### *async* write_file(output_str, file_type, filename=None, file_group=HloFileGroup.aux_files, header=None, sample_str=None, file_sample_label=None, json_data_keys=None, action=None)

> Asynchronously writes a string to a file with specified parameters.

> output_str
> : The string content to be written to the file.

> file_type
> : The type of the file to be written.

> filename
> : The name of the file. If not provided, a default name will be used.

> file_group
> : The group to which the file belongs. Default is HloFileGroup.aux_files.

> header
> : The header content to be written at the beginning of the file.

> sample_str
> : A sample string related to the file content.

> file_sample_label
> : A label for the file sample.

> json_data_keys
> : JSON data keys related to the file content.

> action
> : The action context in which the file is being written. If not provided, 
>   the current action context will be used.

> str or None
> : The path to the written file if the action’s save_data attribute is True,
>   otherwise None.

> - The method ensures the output directory exists before writing the file.
> - Handles different OS path conventions (Windows and POSIX).
> - Writes the header and output string to the file, separated by ‘%%

‘.

#### write_file_nowait(output_str, file_type, filename=None, file_group=HloFileGroup.aux_files, header=None, sample_str=None, file_sample_label=None, json_data_keys=None, action=None)

Writes a file asynchronously without waiting for the operation to complete.

Args:
: output_str (str): The string content to be written to the file.
  file_type (str): The type of the file to be written.
  filename (str, optional): The name of the file. Defaults to None.
  file_group (HloFileGroup, optional): The group to which the file belongs. Defaults to HloFileGroup.aux_files.
  header (str, optional): The header content to be written at the beginning of the file. Defaults to None.
  sample_str (str, optional): The sample string associated with the file. Defaults to None.
  file_sample_label (str, optional): The label for the file sample. Defaults to None.
  json_data_keys (str, optional): The JSON data keys associated with the file. Defaults to None.
  action (Action, optional): The action associated with the file writing operation. Defaults to None.

Returns:
: str: The path to the written file if the action’s save_data attribute is True, otherwise None.

#### *async* write_live_data(output_str, file_conn_key)

Asynchronously writes a string to a live data file connection.

Args:
: output_str (str): The string to be written to the file. A newline character
  : will be appended if it is not already present.
  <br/>
  file_conn_key (UUID): The unique identifier for the file connection in the
  : file connection dictionary.

Returns:
: None

### *class* helao.servers.base.ActiveParams(\*\*data)

Bases: `BaseModel`, `HelaoDict`

ActiveParams is a model that represents the parameters for an active action.

Attributes:
: action (Action): The Action object for this action.
  file_conn_params_dict (Dict[UUID, FileConnParams]): A dictionary keyed by file_conn_key of FileConnParams for all files of active.
  aux_listen_uuids (List[UUID]): A list of UUIDs for auxiliary listeners.

Config:
: arbitrary_types_allowed (bool): Allows arbitrary types for model attributes.

Methods:
: validate_action(cls, v): Validator method for the action attribute.

#### *class* Config

Bases: `object`

#### arbitrary_types_allowed *= True*

#### action *: [`Action`](helao.helpers.md#helao.helpers.premodels.Action)*

#### aux_listen_uuids *: `List`[`UUID`]*

#### file_conn_params_dict *: `Dict`[`UUID`, `FileConnParams`]*

#### model_computed_fields *: ClassVar[Dict[str, ComputedFieldInfo]]* *= {}*

A dictionary of computed field names and their corresponding ComputedFieldInfo objects.

#### model_config *: ClassVar[ConfigDict]* *= {'arbitrary_types_allowed': True}*

Configuration for the model, should be a dictionary conforming to [ConfigDict][pydantic.config.ConfigDict].

#### model_fields *: ClassVar[Dict[str, FieldInfo]]* *= {'action': FieldInfo(annotation=Action, required=True), 'aux_listen_uuids': FieldInfo(annotation=List[UUID], required=False, default=[]), 'file_conn_params_dict': FieldInfo(annotation=Dict[UUID, FileConnParams], required=False, default={})}*

Metadata about the fields defined on the model,
mapping of field names to [FieldInfo][pydantic.fields.FieldInfo] objects.

This replaces Model._\_fields_\_ from Pydantic V1.

#### *classmethod* validate_action(v)

Validates the given action.

Args:
: v: The action to be validated.

Returns:
: The validated action.

### *class* helao.servers.base.Base(fastapp, dyn_endpoints=None)

Bases: `object`

Base class for managing server configurations, endpoints, and actions.

Attributes:
: server (MachineModel): The server machine model.
  fastapp (FastAPI): The FastAPI application instance.
  dyn_endpoints (callable, optional): Dynamic endpoints initializer.
  server_cfg (dict): Server configuration.
  server_params (dict): Server parameters.
  world_cfg (dict): Global configuration.
  orch_key (str, optional): Orchestrator key.
  orch_host (str, optional): Orchestrator host.
  orch_port (int, optional): Orchestrator port.
  run_type (str, optional): Run type.
  helaodirs (HelaoDirs): Directory paths for Helao.
  actives (Dict[UUID, object]): Active actions.
  last_10_active (list): Last 10 active actions.
  executors (dict): Running executors.
  actionservermodel (ActionServerModel): Action server model.
  status_q (MultisubscriberQueue): Status queue.
  data_q (MultisubscriberQueue): Data queue.
  live_q (MultisubscriberQueue): Live queue.
  live_buffer (dict): Live buffer.
  status_clients (set): Status clients.
  local_action_task_queue (list): Local action task queue.
  status_publisher (WsPublisher): Status WebSocket publisher.
  data_publisher (WsPublisher): Data WebSocket publisher.
  live_publisher (WsPublisher): Live WebSocket publisher.
  ntp_server (str): NTP server.
  ntp_response (NTPResponse, optional): NTP response.
  ntp_offset (float, optional): NTP offset.
  ntp_last_sync (float, optional): Last NTP sync time.
  aiolock (asyncio.Lock): Asyncio lock.
  endpoint_queues (dict): Endpoint queues.
  local_action_queue (Queue): Local action queue.
  fast_urls (list): FastAPI URLs.
  ntp_last_sync_file (str, optional): NTP last sync file path.
  ntplockpath (str, optional): NTP lock file path.
  ntplock (FileLock, optional): NTP file lock.
  aloop (asyncio.AbstractEventLoop, optional): Asyncio event loop.
  dumper (aiodebug.hang_inspection.HangInspector, optional): Hang inspector.
  dumper_task (asyncio.Task, optional): Hang inspector task.
  sync_ntp_task_run (bool): NTP sync task running flag.
  ntp_syncer (asyncio.Task, optional): NTP sync task.
  bufferer (asyncio.Task, optional): Live buffer task.
  status_LOGGER (asyncio.Task, optional): Status logger task.

Methods:
: \_\_init_\_(self, fastapp, dyn_endpoints=None): Initialize the Base class.
  exception_handler(self, loop, context): Handle exceptions in the event loop.
  myinit(self): Initialize the event loop and tasks.
  dyn_endpoints_init(self): Initialize dynamic endpoints.
  endpoint_queues_init(self): Initialize endpoint queues.
  print_message(self, 
  <br/>
  ```
  *
  ```
  <br/>
  args, 
  <br/>
  ```
  **
  ```
  <br/>
  kwargs): Print a message with server context.
  init_endpoint_status(self, dyn_endpoints=None): Initialize endpoint status.
  get_endpoint_urls(self): Get a list of all endpoints on this server.
  \_get_action(self, frame) -> Action: Get the action from the current frame.
  setup_action(self) -> Action: Setup an action.
  setup_and_contain_action(self, json_data_keys: List[str], action_abbr: str, file_type: str, hloheader: HloHeaderModel): Setup and contain an action.
  contain_action(self, activeparams: ActiveParams): Contain an action.
  get_active_info(self, action_uuid: UUID): Get active action information.
  get_ntp_time(self): Get the current time from the NTP server.
  send_statuspackage(self, client_servkey: str, client_host: str, client_port: int, action_name: str = None): Send a status package to a client.
  send_nbstatuspackage(self, client_servkey: str, client_host: str, client_port: int, actionmodel: ActionModel): Send a non-blocking status package to a client.
  attach_client(self, client_servkey: str, client_host: str, client_port: int, retry_limit=5): Attach a client for status updates.
  detach_client(self, client_servkey: str, client_host: str, client_port: int): Detach a client from status updates.
  ws_status(self, websocket: WebSocket): Handle WebSocket status subscriptions.
  ws_data(self, websocket: WebSocket): Handle WebSocket data subscriptions.
  ws_live(self, websocket: WebSocket): Handle WebSocket live subscriptions.
  live_buffer_task(self): Task to update the live buffer.
  put_lbuf(self, live_dict): Put data into the live buffer.
  put_lbuf_nowait(self, live_dict): Put data into the live buffer without waiting.
  get_lbuf(self, live_key): Get data from the live buffer.
  log_status_task(self, retry_limit: int = 5): Task to log status changes and send updates to clients.
  detach_subscribers(self): Detach all subscribers.
  get_realtime(self, epoch_ns: float = None, offset: float = None) -> float: Get the current real-time.
  get_realtime_nowait(self, epoch_ns: float = None, offset: float = None) -> float: Get the current real-time without waiting.
  sync_ntp_task(self, resync_time: int = 1800): Task to regularly sync with the NTP server.
  shutdown(self): Shutdown the server and tasks.
  write_act(self, action): Write action metadata to a file.
  write_exp(self, experiment, manual=False): Write experiment metadata to a file.
  write_seq(self, sequence, manual=False): Write sequence metadata to a file.
  append_exp_to_seq(self, exp, seq): Append experiment metadata to a sequence file.
  new_file_conn_key(self, key: str) -> UUID: Generate a new file connection key.
  dflt_file_conn_key(self): Get the default file connection key.
  replace_status(self, status_list: List[HloStatus], old_status: HloStatus, new_status: HloStatus): Replace a status in the status list.
  get_main_error(self, errors) -> ErrorCodes: Get the main error from a list of errors.
  stop_executor(self, executor_id: str): Stop an executor.
  stop_all_executor_prefix(self, action_name: str, match_vars: dict = {}): Stop all executors with a given prefix.

#### \_\_init_\_(fastapp, dyn_endpoints=None)

Initialize the server object.

Args:
: fastapp: The FastAPI application instance.
  dyn_endpoints (optional): Dynamic endpoints for the server.

Raises:
: ValueError: If the root directory is not defined or ‘run_type’ is missing in the configuration.

#### *async* append_exp_to_seq(exp, seq)

Appends experiment details to a sequence file in YAML format.

Args:
: exp: An object containing experiment details such as experiment_uuid,
  : experiment_name, experiment_output_dir, orch_key, orch_host, and orch_port.
  <br/>
  seq: An object representing the sequence to which the experiment details
  : will be appended. It should have methods get_sequence_dir() and
    sequence_timestamp.

Writes:
: A YAML formatted string containing the experiment details to a file named
  with the sequence timestamp in the sequence directory.

#### *async* attach_client(client_servkey, client_host, client_port, retry_limit=5)

Attach a client to the status subscriber list.

This method attempts to attach a client to the server’s status subscriber list.
It retries the attachment process up to retry_limit times if it fails.

Args:
: client_servkey (str): The service key of the client.
  client_host (str): The host address of the client.
  client_port (int): The port number of the client.
  retry_limit (int, optional): The number of times to retry the attachment process. Defaults to 5.

Returns:
: bool: True if the client was successfully attached, False otherwise.

#### *async* contain_action(activeparams)

Handles the containment of an action by either substituting an existing action
or creating a new one, and maintains a record of the last 10 active actions.

Args:
: activeparams (ActiveParams): The parameters of the action to be contained.

Returns:
: Active: The active action instance that has been contained.

#### detach_client(client_servkey, client_host, client_port)

Detaches a client from receiving status updates.

Parameters:
client_servkey (str): The service key of the client.
client_host (str): The host address of the client.
client_port (int): The port number of the client.

Removes the client identified by the combination of service key, host,
and port from the list of clients receiving status updates. If the client
is not found in the list, a message indicating that the client is not
subscribed will be printed.

#### *async* detach_subscribers()

Asynchronously detaches subscribers by signaling the termination of
status and data queues and then waits for a short period.

This method performs the following actions:
1. Puts a StopAsyncIteration exception into the status_q queue.
2. Puts a StopAsyncIteration exception into the data_q queue.
3. Waits for 1 second to allow the queues to process the termination signal.

Returns:
: None

#### dflt_file_conn_key()

Generates a default file connection key.

This method returns a new file connection key using the string representation
of None.

Returns:
: str: A new file connection key.

#### dyn_endpoints_init()

Initializes dynamic endpoints by gathering asynchronous tasks.

This method uses asyncio.gather to concurrently initialize the status
of dynamic endpoints.

Returns:
: None

#### endpoint_queues_init()

Initializes endpoint queues for the server.

This method iterates over the URLs in self.fast_urls and checks if the
path of each URL starts with the server’s name. If it does, it extracts
the endpoint name from the URL path and initializes a queue for that
endpoint, storing it in self.endpoint_queues.

Returns:
: None

#### exception_handler(loop, context)

Handles exceptions raised by coroutines in the event loop.

This method is intended to be used as an exception handler for asyncio event loops.
It logs the exception details and sets an emergency stop (E-STOP) flag on all active actions.

Args:
: loop (asyncio.AbstractEventLoop): The event loop where the exception occurred.
  context (dict): A dictionary containing information about the exception, including
  <br/>
  > the exception object itself under the key “exception”.

Logs:
: - The context of the exception.
  - The formatted exception traceback.
  - A message indicating that the E-STOP flag is being set on active actions.

#### get_active_info(action_uuid)

Retrieve the active action information for a given action UUID.

Args:
: action_uuid (UUID): The unique identifier of the action to retrieve.

Returns:
: dict: A dictionary containing the action information if the action UUID is found.
  None: If the action UUID is not found, returns None and logs an error message.

#### get_endpoint_urls()

Return a list of all endpoints on this server.

This method iterates over all routes in the FastAPI application (self.fastapp.routes)
and constructs a list of dictionaries, each representing an endpoint. Each dictionary
contains the following keys:

- “path”: The path of the route.
- “name”: The name of the route.
- “params”: A dictionary of parameters for the route, where each key is the parameter
  name and the value is another dictionary with the following keys:
  > - “outer_type”: The outer type of the parameter.
  > - “type”: The type of the parameter.
  > - “required”: A boolean indicating if the parameter is required.
  > - “default”: The default value of the parameter, or None if there is no default.

Returns:
: list: A list of dictionaries, each representing an endpoint with its path, name,
  : and parameters.

#### get_lbuf(live_key)

Retrieve the live buffer associated with the given key.

Args:
: live_key (str): The key to identify the live buffer.

Returns:
: object: The live buffer associated with the given key.

#### get_main_error(errors)

Determines the main error from a list of errors or a single error.

* **Return type:**
  `ErrorCodes`

Args:
: errors (Union[List[ErrorCodes], ErrorCodes]): A list of error codes or a single error code.

Returns:
: ErrorCodes: The first non-none error code found in the list, or the single error code if not a list.

#### *async* get_ntp_time()

Asynchronously retrieves the current time from an NTP server and updates the
instance variables with the response.

This method acquires a lock to ensure thread safety while accessing the NTP
server. It sends a request to the specified NTP server and updates the
following instance variables based on the response:
- ntp_response: The full response from the NTP server.
- ntp_last_sync: The original time from the NTP response.
- ntp_offset: The offset time from the NTP response.

If the request to the NTP server fails, it logs a timeout message and sets
ntp_last_sync to the current time and ntp_offset to 0.0.

Additionally, it logs the ntp_offset and ntp_last_sync values. If a file path
for ntp_last_sync_file is provided, it waits until the file is not in use,
then writes the ntp_last_sync and ntp_offset values to the file.

Raises:
: ntplib.NTPException: If there is an error in the NTP request.

Returns:
: None

#### *async* get_realtime(epoch_ns=None, offset=None)

Asynchronously retrieves the real-time value.

* **Return type:**
  `float`

Args:
: epoch_ns (float, optional): The epoch time in nanoseconds. Defaults to None.
  offset (float, optional): The offset to be applied to the epoch time. Defaults to None.

Returns:
: float: The real-time value.

#### get_realtime_nowait(epoch_ns=None, offset=None)

Calculate the real-time in nanoseconds, optionally adjusted by an offset.

Parameters:
epoch_ns (float, optional): The epoch time in nanoseconds. If None, the current time is used.
offset (float, optional): The offset in seconds to adjust the time. If None, the instance’s NTP offset is used.

Returns:
float: The calculated real-time in nanoseconds.

* **Return type:**
  `float`

#### *async* init_endpoint_status(dyn_endpoints=None)

Initializes the endpoint status for the server.

This method performs the following tasks:
1. If dyn_endpoints is a callable, it invokes it with the fastapp instance.
2. Iterates through the routes of the fastapp instance and updates the

> actionservermodel.endpoints dictionary with the endpoint names that
> start with the server’s name.
1. Sorts the status of each endpoint.
2. Prints a message indicating the number of endpoints found for status monitoring.
3. Retrieves and stores the URLs of the endpoints.
4. Initializes the endpoint queues.

Args:
: dyn_endpoints (Optional[Callable]): A callable that takes the fastapp
  : instance as an argument. Default is None.

#### *async* live_buffer_task()

Asynchronous task that processes messages from a live queue and updates the live buffer.

This method subscribes to the live queue and iterates over incoming messages.
Each message is used to update the live buffer.

The method logs a message indicating that the live buffer task has been created.

Returns:
: None

#### *async* log_status_task(retry_limit=5)

Asynchronous task to log and send status updates to clients.

This task subscribes to a status queue and processes incoming status messages.
It updates the internal action server model with the new status, sends the status
to subscribed clients, and handles retries in case of failures.

Args:
: retry_limit (int): The number of retry attempts for sending status updates to clients. Default is 5.

Raises:
: Exception: If an error occurs during the execution of the task, it logs the error and traceback.

#### myinit()

Initializes the asynchronous event loop and various tasks for the server.

This method performs the following actions:
- Retrieves the current running event loop.
- Enables logging of slow callbacks that take longer than a specified interval.
- Starts the hang inspection to dump coroutine stack traces when the event loop hangs.
- Creates a task to stop the hang inspection.
- Sets a custom exception handler for the event loop.
- Gathers NTP time if it has not been synced yet.
- Initializes and starts tasks for NTP synchronization, live buffering, and status logging.

Attributes:
: aloop (asyncio.AbstractEventLoop): The current running event loop.
  dumper (aiodebug.hang_inspection.HangInspector): The hang inspection instance.
  dumper_task (asyncio.Task): The task to stop the hang inspection.
  sync_ntp_task_run (bool): Flag indicating if the NTP sync task has run.
  ntp_syncer (asyncio.Task): The task for NTP synchronization.
  bufferer (asyncio.Task): The task for live buffering.
  status_LOGGER (asyncio.Task): The task for logging status.

#### new_file_conn_key(key)

Generates a UUID based on the MD5 hash of the provided key string.

* **Return type:**
  `UUID`

Args:
: key (str): The input string to be hashed and converted to a UUID.

Returns:
: UUID: A UUID object generated from the MD5 hash of the input string.

#### print_message(\*args, \*\*kwargs)

Print a message with the server configuration and server name.

Args:
: ```
  *
  ```
  <br/>
  args: Variable length argument list.
  <br/>
  ```
  **
  ```
  <br/>
  kwargs: Arbitrary keyword arguments.

Keyword Args:
: log_dir (str): Directory where logs are stored.

#### *async* put_lbuf(live_dict)

Asynchronously puts a dictionary with updated timestamps into the live queue.

Args:
: live_dict (dict): A dictionary where each key-value pair will be updated with the current time.

Returns:
: None

#### put_lbuf_nowait(live_dict)

Puts a dictionary with current timestamps into the live queue without waiting.

Args:
: live_dict (dict): A dictionary where each key-value pair will be updated
  : with the current time and then put into the live queue.

#### replace_status(status_list, old_status, new_status)

Replaces an old status with a new status in the given status list. If the old status
is not found in the list, the new status is appended to the list.

Args:
: status_list (List[HloStatus]): The list of statuses to be modified.
  old_status (HloStatus): The status to be replaced.
  new_status (HloStatus): The status to replace with.

Returns:
: None

#### *async* send_nbstatuspackage(client_servkey, client_host, client_port, actionmodel)

Sends a non-blocking status package to a specified client.

Args:
: client_servkey (str): The server key of the client.
  client_host (str): The host address of the client.
  client_port (int): The port number of the client.
  actionmodel (ActionModel): The action model to be sent.

Returns:
: tuple: A tuple containing the response and error code from the dispatcher.

#### *async* send_statuspackage(client_servkey, client_host, client_port, action_name=None)

Asynchronously sends a status package to a specified client.

Args:
: client_servkey (str): The service key of the client.
  client_host (str): The host address of the client.
  client_port (int): The port number of the client.
  action_name (str, optional): The name of the action to include in the status package. Defaults to None.

Returns:
: tuple: A tuple containing the response and error code from the private dispatcher.

#### setup_action()

Sets up and returns an Action object.

This method retrieves the current frame’s caller frame and uses it to
initialize and return an Action object.

* **Return type:**
  [`Action`](helao.helpers.md#helao.helpers.premodels.Action)

Returns:
: Action: The initialized Action object.

#### *async* setup_and_contain_action(json_data_keys=[], action_abbr=None, file_type='helao_\_file', hloheader=HloHeaderModel(hlo_version='2024.04.18', action_name=None, column_headings=[], optional={}, epoch_ns=None))

Asynchronously sets up and contains an action.

This method initializes an action with the provided parameters and then
contains it using the contain_action method.

Args:
: json_data_keys (List[str], optional): A list of JSON data keys. Defaults to an empty list.
  action_abbr (str, optional): An abbreviation for the action. Defaults to None.
  file_type (str, optional): The type of file. Defaults to “helao_\_file”.
  hloheader (HloHeaderModel, optional): The header model for HLO. Defaults to an instance of HloHeaderModel.

Returns:
: ActiveParams: The active parameters after containing the action.

#### *async* shutdown()

Asynchronously shuts down the server.

This method performs the following actions:
1. Sets the sync_ntp_task_run flag to False to stop NTP synchronization.
2. Detaches all subscribers by calling detach_subscribers.
3. Cancels the status_LOGGER task.
4. Cancels the ntp_syncer task.

Returns:
: None

#### stop_all_executor_prefix(action_name, match_vars={})

Stops all executors whose keys start with the given action name prefix.

Args:
: action_name (str): The prefix of the executor keys to match.
  match_vars (dict, optional): A dictionary of variable names and values to further filter the executors.
  <br/>
  > Only executors whose variables match the provided values will be stopped. Defaults to an empty dictionary.

Returns:
: None

#### stop_executor(executor_id)

Stops the executor task associated with the given executor ID.

This method attempts to stop the action task of the specified executor by signaling it to end its polling loop.
If the executor ID is not found among the active executors, an error message is printed.

Args:
: executor_id (str): The ID of the executor to stop.

Returns:
: dict: A dictionary indicating whether the stop signal was successfully sent.
  : The dictionary contains a single key “signal_stop” with a boolean value:
    - True if the stop signal was successfully sent.
    - False if the executor ID was not found.

#### *async* sync_ntp_task(resync_time=1800)

Periodically synchronizes the system time with an NTP server.

This asynchronous task runs in a loop, checking the last synchronization
time from a file and determining if a resynchronization is needed based
on the provided resync_time interval. If the time since the last
synchronization exceeds resync_time, it triggers an NTP time sync.
The task can be cancelled gracefully.

Args:
: resync_time (int): The interval in seconds to wait before
  : resynchronizing the time. Default is 1800 seconds (30 minutes).

Raises:
: asyncio.CancelledError: If the task is cancelled during execution.

#### *async* write_act(action)

Asynchronously writes action metadata to a YAML file if saving is enabled.

Args:
: action (Action): The action object containing metadata to be saved.

The function constructs the output file path and name based on the action’s
timestamp and other attributes. If the directory does not exist, it creates
it. The metadata is then written to a YAML file in the specified directory.

If saving is disabled for the action, a message indicating this is printed.

Raises:
: OSError: If there is an issue creating the directory or writing the file.

#### *async* write_exp(experiment, manual=False)

Asynchronously writes the experiment data to a YAML file.

Args:
: experiment (Experiment): The experiment object containing the data to be written.
  manual (bool, optional): If True, saves the file in the DIAG directory. Defaults to False.

Writes:
: A YAML file containing the experiment data to the specified directory.

#### *async* write_seq(sequence, manual=False)

Asynchronously writes a sequence to a YAML file.

Args:
: sequence (Sequence): The sequence object to be written.
  manual (bool, optional): If True, the sequence will be saved in the “DIAG” directory.
  <br/>
  > If False, it will be saved in the default save_root directory.
  > Defaults to False.

Writes:
: A YAML file containing the sequence data to the specified directory.

#### *async* ws_data(websocket)

Handle WebSocket connections for data subscribers.

This asynchronous method accepts a WebSocket connection, subscribes to a data queue,
and sends compressed data messages to the WebSocket client. If an exception occurs,
it logs the error and removes the subscriber from the data queue.

Args:
: websocket (WebSocket): The WebSocket connection instance.

Raises:
: Exception: If any exception occurs during the WebSocket communication.

#### *async* ws_live(websocket)

Handle a new WebSocket connection for live data streaming.

This coroutine accepts a WebSocket connection, subscribes to the live data queue,
and sends compressed live data messages to the client. If an exception occurs,
it logs the error and removes the subscriber from the live data queue.

Args:
: websocket (WebSocket): The WebSocket connection instance.

Raises:
: Exception: If an error occurs during the WebSocket communication or data processing.

#### *async* ws_status(websocket)

Handle WebSocket connections for status updates.

This asynchronous method accepts a WebSocket connection, subscribes to
status updates, and sends compressed status messages to the client. If an
exception occurs, it logs the error and removes the subscriber from the
status queue.

Args:
: websocket (WebSocket): The WebSocket connection instance.

Raises:
: Exception: If an error occurs during the WebSocket communication.

### *class* helao.servers.base.DummyBase

Bases: `object`

A dummy base class for demonstration purposes.

Attributes:
: live_buffer (dict): A dictionary to store live buffer data.
  actionservermodel (ActionServerModel): An instance of ActionServerModel.

Methods:
: \_\_init_\_(): Initializes the DummyBase instance.
  print_message(message: str): Prints a message with a dummy server name.
  async put_lbuf(message: dict): Asynchronously updates the live buffer with the given message.
  get_lbuf(buf_key: str): Retrieves the value and timestamp from the live buffer for the given key.

#### \_\_init_\_()

Initializes the base server with default settings.

Attributes:
: live_buffer (dict): A dictionary to store live data.
  actionservermodel (ActionServerModel): An instance of ActionServerModel initialized with a dummy server and machine name, and a unique action UUID.

#### get_lbuf(buf_key)

Retrieve the value and timestamp from the live buffer for a given key.

* **Return type:**
  `tuple`

Args:
: buf_key (str): The key to look up in the live buffer.

Returns:
: tuple: A tuple containing the value and timestamp associated with the given key.

#### print_message(message)

Prints a message to the console.

* **Return type:**
  `None`

Args:
: message (str): The message to be printed.

#### *async* put_lbuf(message)

Updates the live buffer with the provided message.

* **Return type:**
  `None`

Args:
: message (dict): A dictionary containing key-value pairs to be added to the live buffer.

## helao.servers.base_api module

### *class* helao.servers.base_api.BaseAPI(config, server_key, server_title, description, version, driver_class=None, dyn_endpoints=None, poller_class=None)

Bases: [`HelaoFastAPI`](helao.helpers.md#helao.helpers.server_api.HelaoFastAPI)

BaseAPI class extends HelaoFastAPI to provide additional functionality for handling
middleware, exception handling, startup and shutdown events, WebSocket connections,
and various endpoints for configuration, status, and control.

Attributes:
: base (Base): An instance of the Base class.
  driver (Optional[HelaoDriver]): An optional driver instance.
  poller (Optional[DriverPoller]): An optional poller instance.

Methods:
: \_\_init_\_(config, server_key, server_title, description, version, driver_class=None, dyn_endpoints=None, poller_class=None):
  : Initializes the BaseAPI instance with the given configuration and parameters.
  <br/>
  app_entry(request: Request, call_next):
  : Middleware function to handle incoming HTTP requests and manage action queuing.
  <br/>
  custom_http_exception_handler(request, exc):
  : Custom exception handler for HTTP exceptions.
  <br/>
  startup_event():
  : Event handler for application startup.
  <br/>
  add_default_head_endpoints():
  : Adds default HEAD endpoints for all POST routes.
  <br/>
  websocket_status(websocket: WebSocket):
  : WebSocket endpoint to broadcast status messages.
  <br/>
  websocket_data(websocket: WebSocket):
  : WebSocket endpoint to broadcast status dictionaries.
  <br/>
  websocket_live(websocket: WebSocket):
  : WebSocket endpoint to broadcast live buffer dictionaries.
  <br/>
  get_config():
  : Endpoint to retrieve the server configuration.
  <br/>
  get_status():
  : Endpoint to retrieve the server status.
  <br/>
  attach_client(client_servkey: str, client_host: str, client_port: int):
  : Endpoint to attach a client to the server.
  <br/>
  stop_executor(executor_id: str):
  : Endpoint to stop a specific executor.
  <br/>
  get_all_urls():
  : Endpoint to retrieve all URLs on the server.
  <br/>
  get_lbuf():
  : Endpoint to retrieve the live buffer.
  <br/>
  list_executors():
  : Endpoint to list all executors.
  <br/>
  \_raise_exception():
  : Endpoint to raise a test exception for debugging.
  <br/>
  \_raise_async_exception():
  : Endpoint to raise a test asynchronous exception for debugging.
  <br/>
  resend_active(action_uuid: str):
  : Endpoint to resend the last active action.
  <br/>
  post_shutdown():
  : Endpoint to initiate server shutdown.
  <br/>
  shutdown_event():
  : Event handler for application shutdown.
  <br/>
  estop(action: Action, switch: bool):
  : Endpoint to handle emergency stop (estop) actions.

#### \_\_init_\_(config, server_key, server_title, description, version, driver_class=None, dyn_endpoints=None, poller_class=None)

Initialize the BaseAPI server.

> config (dict): Configuration dictionary for the server.
> server_key (str): Unique key identifying the server.
> server_title (str): Title of the server.
> description (str): Description of the server.
> version (str): Version of the server.
> driver_class (type, optional): Class of the driver to be used. Defaults to None.
> dyn_endpoints (list, optional): List of dynamic endpoints. Defaults to None.
> poller_class (type, optional): Class of the poller to be used. Defaults to None.

#### base *: [`Base`](#helao.servers.base.Base)*

## helao.servers.orch module

### *class* helao.servers.orch.Orch(fastapp)

Bases: [`Base`](#helao.servers.base.Base)

Orch class is responsible for orchestrating sequences, experiments, and actions in a distributed system. It manages the lifecycle of these entities, handles exceptions, and communicates with various servers to dispatch and monitor actions.

Attributes:
: experiment_lib (dict): Library of available experiments.
  experiment_codehash_lib (dict): Library of experiment code hashes.
  sequence_lib (dict): Library of available sequences.
  sequence_codehash_lib (dict): Library of sequence code hashes.
  use_db (bool): Flag indicating if a database is used.
  syncer (HelaoSyncer): Syncer object for database synchronization.
  sequence_dq (zdeque): Deque for sequences.
  experiment_dq (zdeque): Deque for experiments.
  action_dq (zdeque): Deque for actions.
  dispatch_buffer (list): Buffer for dispatching actions.
  nonblocking (list): List of non-blocking actions.
  last_dispatched_action_uuid (UUID): UUID of the last dispatched action.
  last_50_action_uuids (list): List of the last 50 action UUIDs.
  last_action_uuid (str): UUID of the last action.
  last_interrupt (float): Timestamp of the last interrupt.
  active_experiment (Experiment): Currently active experiment.
  last_experiment (Experiment): Last executed experiment.
  active_sequence (Sequence): Currently active sequence.
  active_seq_exp_counter (int): Counter for active sequence experiments.
  last_sequence (Sequence): Last executed sequence.
  bokehapp (Server): Bokeh server instance.
  orch_op (BokehOperator): Bokeh operator instance.
  op_enabled (bool): Flag indicating if the operator is enabled.
  heartbeat_interval (int): Interval for heartbeat monitoring.
  globalstatusmodel (GlobalStatusModel): Global status model.
  interrupt_q (asyncio.Queue): Queue for interrupts.
  incoming_status (asyncio.Queue): Queue for incoming statuses.
  incoming (GlobalStatusModel): Incoming status model.
  init_success (bool): Flag indicating if initialization was successful.
  loop_task (asyncio.Task): Task for the dispatch loop.
  wait_task (asyncio.Task): Task for waiting.
  current_wait_ts (float): Timestamp of the current wait.
  last_wait_ts (float): Timestamp of the last wait.
  globstat_q (MultisubscriberQueue): Queue for global status.
  globstat_clients (set): Set of global status clients.
  current_stop_message (str): Current stop message.
  step_thru_actions (bool): Flag for stepping through actions.
  step_thru_experiments (bool): Flag for stepping through experiments.
  step_thru_sequences (bool): Flag for stepping through sequences.
  status_summary (dict): Summary of statuses.
  global_params (dict): Global parameters.

Methods:
: exception_handler(loop, context): Handles exceptions in the event loop.
  myinit(): Initializes the orchestrator.
  endpoint_queues_init(): Initializes endpoint queues.
  register_action_uuid(action_uuid): Registers an action UUID.
  track_action_uuid(action_uuid): Tracks an action UUID.
  start_operator(): Starts the Bokeh operator.
  makeBokehApp(doc, orch): Creates a Bokeh application.
  wait_for_interrupt(): Waits for an interrupt.
  subscribe_all(retry_limit): Subscribes to all FastAPI servers.
  update_nonblocking(actionmodel, server_host, server_port): Updates non-blocking actions.
  clear_nonblocking(): Clears non-blocking actions.
  update_status(actionservermodel): Updates the status.
  ws_globstat(websocket): Subscribes to global status queue and sends messages to websocket client.
  globstat_broadcast_task(): Consumes the global status queue.
  unpack_sequence(sequence_name, sequence_params): Unpacks a sequence.
  get_sequence_codehash(sequence_name): Gets the code hash of a sequence.
  seq_unpacker(): Unpacks the sequence.
  loop_task_dispatch_sequence(): Dispatches the sequence.
  loop_task_dispatch_experiment(): Dispatches the experiment.
  loop_task_dispatch_action(): Dispatches the action.
  dispatch_loop_task(): Parses experiment and action queues and dispatches actions.
  orch_wait_for_all_actions(): Waits for all actions to finish.
  start(): Begins experimenting with experiment and action queues.
  start_loop(): Starts the orchestrator loop.
  estop_loop(reason): Emergency stops the orchestrator loop.
  stop_loop(): Stops the orchestrator loop.
  estop_actions(switch): Emergency stops all actions.
  skip(): Clears the current action queue while running.
  intend_skip(): Intends to skip the current action.
  stop(): Stops experimenting with experiment and action queues.
  intend_stop(): Intends to stop the orchestrator.
  intend_estop(): Intends to emergency stop the orchestrator.
  intend_none(): Resets the loop intent.
  clear_estop(): Clears the emergency stop.
  clear_error(): Clears the error statuses.
  clear_sequences(): Clears the sequence queue.
  clear_experiments(): Clears the experiment queue.
  clear_actions(): Clears the action queue.
  add_sequence(sequence): Adds a sequence to the queue.
  add_experiment(seq, experimentmodel, prepend, at_index): Adds an experiment to the queue.
  list_sequences(limit): Lists the sequences in the queue.
  list_experiments(limit): Lists the experiments in the queue.
  list_all_experiments(): Lists all experiments in the queue.
  drop_experiment_inds(inds): Drops experiments by index.
  get_experiment(last): Gets the active or last experiment.
  get_sequence(last): Gets the active or last sequence.
  list_active_actions(): Lists the active actions.
  list_actions(limit): Lists the actions in the queue.
  supplement_error_action(check_uuid, sup_action): Supplements an error action.
  remove_experiment(by_index, by_uuid): Removes an experiment by index or UUID.
  replace_action(sup_action, by_index, by_uuid, by_action_order): Replaces an action in the queue.
  append_action(sup_action): Appends an action to the queue.
  finish_active_sequence(): Finishes the active sequence.
  finish_active_experiment(): Finishes the active experiment.
  write_active_experiment_exp(): Writes the active experiment.
  write_active_sequence_seq(): Writes the active sequence.
  shutdown(): Shuts down the orchestrator.
  update_operator(msg): Updates the operator.
  start_wait(active): Starts a wait action.
  dispatch_wait_task(active, print_every_secs): Dispatches a wait task.
  active_action_monitor(): Monitors active actions.
  ping_action_servers(): Pings action servers.
  action_server_monitor(): Monitors action servers.

#### \_\_init_\_(fastapp)

Initializes the orchestrator server.

Args:
: fastapp: The FastAPI application instance.

#### *async* action_server_monitor()

Monitors the status of action servers in a continuous loop.

This asynchronous method continuously pings action servers to update their status
and notifies the operator with the updated status summary at regular intervals
defined by heartbeat_interval.

The loop runs indefinitely, sleeping for heartbeat_interval seconds between
each iteration.

Returns:
: None

#### *async* active_action_monitor()

Monitors the status of active actions in a loop and stops the process if any
required endpoints become unavailable.

This asynchronous method continuously checks the status of active actions
and verifies the availability of required endpoints. If any endpoints are
found to be unavailable, it stops the process and updates the operator.

The method performs the following steps in a loop:
1. Checks if the loop state is started.
2. Retrieves the list of active endpoints.
3. Verifies the availability of unique active endpoints.
4. If any endpoints are unavailable, stops the process and updates the operator.
5. Sleeps for a specified heartbeat interval before repeating the loop.

Attributes:
: globalstatusmodel (GlobalStatusModel): The global status model containing
  : the loop state and active actions.
  <br/>
  heartbeat_interval (int): The interval (in seconds) to wait between each
  : iteration of the monitoring loop.
  <br/>
  current_stop_message (str): The message to display when stopping the process.

Returns:
: None

#### *async* add_experiment(seq, experimentmodel, prepend=False, at_index=None)

Adds an experiment to the sequence.

Args:
: seq (Sequence): The sequence to which the experiment will be added.
  experimentmodel (Experiment): The experiment model to be added.
  prepend (bool, optional): If True, the experiment will be added to the front of the queue. Defaults to False.
  at_index (int, optional): If provided, the experiment will be inserted at the specified index. Defaults to None.

Returns:
: str: The UUID of the added experiment.

Raises:
: TypeError: If the experimentmodel is not an instance of Experiment.

#### *async* add_sequence(sequence)

Adds a sequence to the sequence deque and initializes its UUID and codehash if not already set.

Args:
: sequence (Sequence): The sequence object to be added.

Returns:
: str: The UUID of the added sequence.

#### append_action(sup_action)

Add action to end of current action queue.

#### *async* clear_actions()

Asynchronously clears the action queue.

This method prints a message indicating that the action queue is being cleared
and then clears the action deque.

Returns:
: None

#### *async* clear_error()

Asynchronously clears the error state.

This method resets the error dictionary by clearing errored UUIDs
and updates the global status model to reflect that the errors
have been cleared. It also sends a message to the interrupt queue
indicating that the errors have been cleared.

Returns:
: None

#### *async* clear_estop()

Asynchronously clears the emergency stop (estop) state.

This method performs the following actions:
1. Logs a message indicating that estopped UUIDs are being cleared.
2. Clears the estopped status from the global status model.
3. Releases the estop state for all action servers.
4. Sets the orchestration status from estopped back to stopped.
5. Puts a “cleared_estop” message into the interrupt queue.

Returns:
: None

#### *async* clear_experiments()

Asynchronously clears the experiment queue.

This method prints a message indicating that the experiment queue is being cleared
and then clears the deque containing the experiments.

Returns:
: None

#### *async* clear_nonblocking()

Asynchronously clears non-blocking action IDs by sending stop requests to the respective servers.

This method iterates over the non-blocking actions and sends a stop_executor request to each server
to stop the corresponding executor. It collects the responses and error codes from each request.

Returns:
: list of tuples: A list of tuples where each tuple contains the response and error code from a server.

#### *async* clear_sequences()

Asynchronously clears the sequence queue.

This method logs a message indicating that the sequence queue is being cleared
and then clears the sequence deque.

Returns:
: None

#### *async* dispatch_loop_task()

The main dispatch loop task for the operator orchestrator. This asynchronous
method manages the dispatching of actions, experiments, and sequences based
on the current state of the orchestrator and the contents of the respective
queues.

The loop continues running as long as the orchestrator’s loop state is
LoopStatus.started and there are items in the action, experiment, or
sequence queues. It handles the following tasks:

- Resuming paused action lists.
- Checking driver states and retrying if necessary.
- Dispatching actions, experiments, and sequences based on the current state.
- Handling emergency stops and step-through modes.
- Updating the operator with the current state and progress.

The loop will stop if:
- An emergency stop is triggered.
- All queues are empty.
- An error occurs during dispatching.

Upon stopping, it ensures that any active experiment or sequence is finished
properly.

Returns:
: bool: True if the loop completes successfully, False if an exception occurs.

Raises:
: Exception: If an unexpected error occurs during the loop execution.

#### *async* dispatch_wait_task(active, print_every_secs=5)

Handles long wait actions as a separate task to prevent HTTP timeout.

Args:
: active (Active): The active action instance containing action parameters.
  print_every_secs (int, optional): Interval in seconds to print wait status. Defaults to 5.

Returns:
: finished_action: The result of the finished action.

#### drop_experiment_inds(inds)

Remove experiments from the experiment queue at the specified indices.

Args:
: inds (List[int]): A list of indices of the experiments to be removed.

Returns:
: List: A list of all remaining experiments after the specified experiments have been removed.

#### endpoint_queues_init()

Initializes endpoint queues for the server.

This method iterates over the list of fast URLs and checks if the path
starts with the server’s name. For each matching URL, it creates a new
queue and assigns it to the endpoint_queues dictionary with the URL’s
name as the key.

#### *async* estop_actions(switch)

Asynchronously sends an emergency stop (estop) command to all servers.

This method sends an estop command to all action servers registered in the global status model.
The estop command can be triggered during an active experiment or based on the last experiment.
If no experiment is active or available, a new experiment with estop status is created.

Args:
: switch (bool): The state of the estop switch. True to activate estop, False to deactivate.

Raises:
: Exception: If the estop command fails for any action server, an exception is caught and logged.

#### *async* estop_loop(reason='')

Asynchronously handles the emergency stop (E-STOP) procedure for the orchestrator.

This method performs the following actions:
1. Logs an emergency stop message with an optional reason.
2. Sets the global status model’s loop state to ‘estopped’.
3. Forces the stop of all running actions associated with this orchestrator.
4. Resets the loop intention to none.
5. Updates the current stop message with “E-STOP” and the optional reason.
6. Notifies the operator of the emergency stop status.

Args:
: reason (str, optional): An optional reason for the emergency stop. Defaults to an empty string.

#### exception_handler(loop, context)

Handles exceptions raised by coroutines in the event loop.

This method is called when an exception is raised in a coroutine
that is being executed by the event loop. It logs the exception
details and sets the E-STOP flag on all active actions.

Args:
: loop (asyncio.AbstractEventLoop): The event loop where the exception occurred.
  context (dict): A dictionary containing information about the exception,
  <br/>
  > including the exception object itself under the key “exception”.

Logs:
: - The exception message and traceback.
  - A message indicating that the E-STOP flag is being set on active actions.

#### *async* finish_active_experiment()

Finalizes the currently active experiment by performing the following steps:

1. Waits for all actions to complete.
2. Stops any non-blocking action executors.
3. Updates the status of the active experiment to ‘finished’.
4. Adds the finished experiment to the active sequence.
5. Writes the updated sequence and experiment data to storage.
6. Initiates a task to move the experiment directory if a database server exists.

This method ensures that all necessary cleanup and state updates are performed
before marking the experiment as finished and moving on to the next one.

#### *async* finish_active_sequence()

Completes the currently active sequence by performing the following steps:

1. Waits for all actions to complete using orch_wait_for_all_actions.
2. Updates the status of the active sequence from HloStatus.active to HloStatus.finished.
3. Writes the active sequence to a persistent storage using write_seq.
4. Deep copies the active sequence to last_sequence.
5. Updates the local buffer with the sequence UUID, name, and status.
6. Resets the active sequence and related counters.
7. Clears the dispatched actions counter in the global status model.
8. Initiates a task to move the sequence directory if a database server exists.

This method ensures that the sequence is properly finalized and all related
resources are cleaned up.

#### get_experiment(last=False)

Retrieve the current or last experiment.

* **Return type:**
  [`Experiment`](helao.helpers.md#helao.helpers.premodels.Experiment)

Args:
: last (bool): If True, retrieve the last experiment. If False, retrieve the active experiment.

Returns:
: Experiment: The experiment object if it exists, otherwise an empty dictionary.

#### get_sequence(last=False)

Retrieve the current or last sequence.

* **Return type:**
  [`Sequence`](helao.helpers.md#helao.helpers.premodels.Sequence)

Args:
: last (bool): If True, retrieve the last sequence. If False, retrieve the active sequence.

Returns:
: Sequence: The sequence object if available, otherwise an empty dictionary.

#### get_sequence_codehash(sequence_name)

Retrieve the UUID code hash for a given sequence name.

* **Return type:**
  `UUID`

Args:
: sequence_name (str): The name of the sequence.

Returns:
: UUID: The UUID code hash associated with the sequence name.

#### *async* globstat_broadcast_task()

Asynchronous task that subscribes to the globstat_q queue and
periodically sleeps for a short duration.

This method continuously listens to the globstat_q queue and
performs a non-blocking sleep for 0.01 seconds on each iteration.

Returns:
: None

#### *async* intend_estop()

Asynchronously sets the loop intent to emergency stop (estop) and puts the
updated loop intent into the interrupt queue.

This method updates the loop_intent attribute of the globalstatusmodel
to LoopIntent.estop and then places this intent into the interrupt_q
queue to signal an emergency stop.

Returns:
: None

#### *async* intend_none()

Sets the loop intent to ‘none’ and puts this intent into the interrupt queue.

This method updates the global status model’s loop intent to indicate that no
specific loop action is intended. It then places this updated intent into the
interrupt queue to signal other parts of the system.

Returns:
: None

#### *async* intend_skip()

Asynchronously sets the loop intent to ‘skip’ and puts this intent into the interrupt queue.

This method updates the global status model’s loop intent to ‘skip’ and then places this intent
into the interrupt queue to signal that the current loop should be skipped.

Returns:
: None

#### *async* intend_stop()

Asynchronously sets the loop intent to stop and puts this intent into the interrupt queue.

This method updates the loop_intent attribute of the globalstatusmodel to LoopIntent.stop
and then places this intent into the interrupt_q queue to signal that the loop should stop.

Returns:
: None

#### list_actions(limit=10)

List a limited number of actions from the action queue.

Args:
: limit (int, optional): The maximum number of actions to list. Defaults to 10.

Returns:
: list: A list of action models from the action queue, up to the specified limit.

#### list_active_actions()

List all active actions.

Returns:
: list: A list of status models representing the active actions.

#### list_all_experiments()

List all experiments with their indices.

Returns:
: list of tuple: A list of tuples where each tuple contains the index of the 
  experiment and the experiment name.

#### list_experiments(limit=10)

List a limited number of experiments.

Args:
: limit (int, optional): The maximum number of experiments to list. Defaults to 10.

Returns:
: list: A list of experiments, each obtained by calling get_exp() on elements of self.experiment_dq.

#### list_sequences(limit=10)

List sequences from the sequence deque up to a specified limit.

Args:
: limit (int, optional): The maximum number of sequences to list. Defaults to 10.

Returns:
: list: A list of sequences, each obtained by calling the get_seq method on the elements of the sequence deque.

#### *async* loop_task_dispatch_action()

Asynchronously dispatches actions based on the current loop intent and action queue.

This method processes actions in the action queue (action_dq) according to the
current loop intent (loop_intent) and loop state (loop_state). It handles
different loop intents such as stop, skip, and estop, and dispatches actions
accordingly. The method also manages action start conditions and updates global
parameters based on action results.

* **Return type:**
  `ErrorCodes`

Returns:
: ErrorCodes: The error code indicating the result of the action dispatch process.

Loop Intents:
: - LoopIntent.stop: Stops the orchestrator after all actions are finished.
  - LoopIntent.skip: Clears the action queue and skips to the next experiment.
  - LoopIntent.estop: Clears the action queue and sets the loop state to estopped.
  - Default: Dispatches actions based on their start conditions.

Action Start Conditions:
: - ActionStartCondition.no_wait: Dispatches the action unconditionally.
  - ActionStartCondition.wait_for_endpoint: Waits for the endpoint to become available.
  - ActionStartCondition.wait_for_server: Waits for the server to become available.
  - ActionStartCondition.wait_for_orch: Waits for the orchestrator to become available.
  - ActionStartCondition.wait_for_previous: Waits for the previous action to finish.
  - ActionStartCondition.wait_for_all: Waits for all actions to finish.

Raises:
: Exception: If an error occurs during action dispatching.
  asyncio.exceptions.TimeoutError: If a timeout occurs during action dispatching.

Notes:
: - This method uses an asyncio lock (aiolock) to ensure thread safety during
    action dispatching.
  - The method updates global parameters based on the results of dispatched actions.
  - If an action dispatch fails, the method stops the orchestrator and re-queues
    the action.

#### *async* loop_task_dispatch_experiment()

Asynchronously dispatches a new experiment from the experiment queue and processes its actions.

This method performs the following steps:
1. Retrieves a new experiment from the experiment queue.
2. Copies global parameters to the experiment parameters.
3. Initializes the experiment and updates the global status model.
4. Unpacks the actions for the experiment and assigns necessary attributes.
5. Adds the unpacked actions to the action queue.
6. Writes the active experiment to a temporary storage.
7. Optionally uploads the initial active experiment JSON to S3.

* **Return type:**
  `ErrorCodes`

Returns:
: ErrorCodes: The error code indicating the result of the operation.

#### *async* loop_task_dispatch_sequence()

Asynchronously dispatches a sequence from the sequence queue and initializes it.

This method performs the following steps:
1. Retrieves a new sequence from the sequence queue (sequence_dq).
2. Sets the new sequence as the active sequence and updates its status to “active”.
3. Configures the sequence based on the world configuration (world_cfg).
4. Initializes the sequence with a time offset and sets the orchestrator.
5. Populates the sequence parameters from global experiment parameters.
6. Unpacks the sequence into an experiment plan list if not already populated.
7. Writes the sequence to a local buffer and optionally uploads it to S3.
8. Creates a task to unpack the sequence and waits for a short duration.

* **Return type:**
  `ErrorCodes`

Returns:
: ErrorCodes: The error code indicating the result of the operation.

#### makeBokehApp(doc, orch)

Initializes a Bokeh application for visualization and sets up a BokehOperator.

Args:
: doc (bokeh.document.Document): The Bokeh document to be used for the application.
  orch (Orchestrator): The orchestrator instance to be used by the BokehOperator.

Returns:
: bokeh.document.Document: The modified Bokeh document with the BokehOperator attached.

#### myinit()

Initializes the asynchronous event loop and sets up various tasks and handlers.

This method performs the following actions:
- Retrieves the current running event loop.
- Sets a custom exception handler for the event loop.
- Initiates an NTP time synchronization if it hasn’t been done yet.
- Creates and schedules tasks for NTP synchronization, live buffering, endpoint status initialization,

> status logging, global status broadcasting, heartbeat monitoring, and action server monitoring.
- Retrieves and stores endpoint URLs.
- Starts the operator if the operation is enabled.
- Subscribes to all necessary status updates.

Attributes:
: aloop (asyncio.AbstractEventLoop): The current running event loop.
  sync_ntp_task_run (bool): Flag indicating if the NTP sync task is running.
  ntp_syncer (asyncio.Task): Task for synchronizing NTP time.
  bufferer (asyncio.Task): Task for live buffering.
  fast_urls (list): List of endpoint URLs.
  status_logger (asyncio.Task): Task for logging status.
  status_subscriber (asyncio.Task): Task for subscribing to all status updates.
  globstat_broadcaster (asyncio.Task): Task for broadcasting global status.
  heartbeat_monitor (asyncio.Task): Task for monitoring active actions.
  driver_monitor (asyncio.Task): Task for monitoring the action server.

#### *async* orch_wait_for_all_actions()

Waits for all actions to complete.

This asynchronous method continuously checks the status of actions and waits
until all actions are idle. If any actions are still active, it waits for a
status update and prints a message if the wait time exceeds 10 seconds.

Returns:
: None

#### *async* ping_action_servers()

Periodically monitor all action servers and return their status.

This asynchronous method iterates through the configured action servers,
excluding those with “bokeh” or “demovis” in their configuration, and
attempts to retrieve their status using the async_private_dispatcher.
The status of each server is summarized and returned in a dictionary.

Returns:
: dict: A dictionary where the keys are server keys and the values are
  : tuples containing the status string (“busy”, “idle”, or “unreachable”)
    and the driver status.

Raises:
: aiohttp.client_exceptions.ClientConnectorError: If there is an issue
  : connecting to a server.

#### register_action_uuid(action_uuid)

Registers a new action UUID in the list of the last 50 action UUIDs.

This method ensures that the list of action UUIDs does not exceed 50 entries.
If the list is full, the oldest UUID is removed before adding the new one.

Args:
: action_uuid (str): The UUID of the action to be registered.

#### remove_experiment(by_index=None, by_uuid=None)

Removes an experiment from the experiment queue.

Parameters:
by_index (int, optional): The index of the experiment to remove.
by_uuid (UUID, optional): The UUID of the experiment to remove.

If both parameters are provided, by_index will take precedence.
If neither parameter is provided, a message will be printed and the method will return None.

Raises:
IndexError: If the index is out of range.
KeyError: If the UUID is not found in the experiment queue.

#### replace_action(sup_action, by_index=None, by_uuid=None, by_action_order=None)

Substitute a queued action with a new action.

Parameters:
sup_action (Action): The new action to replace the existing one.
by_index (int, optional): The index of the action to be replaced.
by_uuid (UUID, optional): The UUID of the action to be replaced.
by_action_order (int, optional): The action order of the action to be replaced.

Returns:
None

#### *async* seq_unpacker()

Asynchronously unpacks and processes experiments from the active sequence.

Iterates through the list of experiments in the active sequence’s experiment plan.
For each experiment, it assigns a data request ID if available and adds the experiment
to the sequence. Updates the global status model to indicate the loop state has started
after processing the first experiment.

Args:
: None

Returns:
: None

#### *async* shutdown()

Asynchronously shuts down the server by performing the following actions:

1. Detaches all subscribers.
2. Cancels the status logger.
3. Cancels the NTP syncer.
4. Cancels the status subscriber.

This method ensures that all ongoing tasks are properly terminated and resources are released.

#### *async* skip()

Asynchronously skips the current action in the orchestrator.

If the orchestrator’s loop state is LoopStatus.started, it will attempt to skip the current action by calling intend_skip().
Otherwise, it will print a message indicating that the orchestrator is not running and clear the action queue.

Returns:
: None

#### *async* start()

Starts the orchestration loop if it is currently stopped. If there are any
actions, experiments, or sequences in the queue, it resumes from a paused
state. Otherwise, it notifies that the experiment list is empty. If the loop
is already running, it notifies that it is already running. Finally, it clears
the current stop message and updates the operator status.

Returns:
: None

#### *async* start_loop()

#### start_operator()

Starts the Bokeh server for the operator.

This method initializes and starts a Bokeh server instance using the
configuration specified in self.server_cfg and self.server_params.
It sets up the server to serve a Bokeh application at a specified port
and address, and optionally launches a web browser to display the
application.

Parameters:
None

Returns:
None

#### start_wait(active)

Initiates and starts an asynchronous wait task for the given active object.

Args:
: active (Active): The active object for which the wait task is to be started.

Returns:
: None

#### *async* stop()

Stops the orchestrator based on its current loop state.

If the loop state is LoopStatus.started, it will attempt to stop the orchestrator
by calling intend_stop(). If the loop state is LoopStatus.estopped, it will
print a message indicating that the E-STOP flag was raised and there is nothing to stop.
Otherwise, it will print a message indicating that the orchestrator is not running.

#### *async* stop_loop()

Asynchronously stops the loop by intending to stop.

This method calls the intend_stop coroutine to signal that the loop should stop.

#### *async* subscribe_all(retry_limit=15)

Attempts to subscribe to all servers listed in the configuration, excluding
those with “bokeh” or “demovis” in their configuration.

This method tries to attach the client to each server by sending an
“attach_client” request. If the connection fails, it retries up to
retry_limit times with a 2-second delay between attempts.

Args:
: retry_limit (int): The number of retry attempts for each server.
  : Default is 15.

Side Effects:
: Updates self.init_success to True if all subscriptions are successful.
  Logs messages indicating the success or failure of each subscription attempt.

Raises:
: aiohttp.client_exceptions.ClientConnectorError: If the connection to a server fails.

Notes:
: - If any server fails to subscribe after the specified retries,
    self.init_success is set to False.
  - The method logs detailed messages about the subscription process.

#### supplement_error_action(check_uuid, sup_action)

Supplements an errored action with a new action.

This method checks if the provided UUID is in the list of errored actions.
If it is, it creates a new action based on the supplied action, updates its
order and retry count, and appends it to the action deque for reprocessing.
If the UUID is not found in the list of errored actions, it prints an error message.

Args:
: check_uuid (UUID): The UUID of the action to check.
  sup_action (Action): The new action to supplement the errored action.

Returns:
: None

#### track_action_uuid(action_uuid)

Tracks the last dispatched action UUID.

Args:
: action_uuid (str): The UUID of the action to be tracked.

#### unpack_sequence(sequence_name, sequence_params)

Unpacks and returns a sequence of experiments based on the given sequence name and parameters.

* **Return type:**
  `List`[[`Experiment`](helao.helpers.md#helao.helpers.premodels.Experiment)]

Args:
: sequence_name (str): The name of the sequence to unpack.
  sequence_params (dict): A dictionary of parameters to pass to the sequence function.

Returns:
: List[Experiment]: A list of Experiment objects corresponding to the unpacked sequence.
  : Returns an empty list if the sequence name is not found in the sequence library.

#### *async* update_nonblocking(actionmodel, server_host, server_port)

Asynchronously updates the non-blocking action list based on the action status.

This method registers the action UUID, constructs a server execution ID, and
updates the non-blocking list depending on the action status. It also triggers
the orchestrator dispatch loop by putting an empty object in the interrupt queue.

Args:
: actionmodel (Action): The action model containing details of the action.
  server_host (str): The host address of the server.
  server_port (int): The port number of the server.

Returns:
: dict: A dictionary indicating the success of the operation.

#### *async* update_operator(msg)

Asynchronously updates the operator with a given message.

Args:
: msg: The message to be sent to the operator.

Returns:
: None

Raises:
: None

#### *async* update_status(actionservermodel=None)

Asynchronously updates the status of the action server and the global status model.

Args:
: actionservermodel (ActionServerModel, optional): The model containing the status of the action server. Defaults to None.

Returns:
: bool: True if the status was successfully updated, False otherwise.

This method performs the following steps:
1. Prints a message indicating the receipt of the status from the server.
2. If the actionservermodel is None, returns False.
3. Acquires an asynchronous lock to ensure thread safety.
4. Updates the global status model with the new action server model and sorts the new status dictionary.
5. Registers the action UUID from the action server model.
6. Updates the local buffer with the recent non-active actions.
7. Checks if any action is in an emergency stop (estop) state or has errored.
8. Updates the orchestration state based on the current status of actions.
9. Pushes the updated global status model to the interrupt queue.
10. Updates the operator with the new status.

Note:
: The method assumes that self.aiolock, self.globalstatusmodel, self.interrupt_q, and self.update_operator are defined elsewhere in the class.

#### *async* wait_for_interrupt()

Asynchronously waits for an interrupt message from the interrupt queue.

This method retrieves at least one status message from the interrupt_q queue.
If the message is an instance of GlobalStatusModel, it updates the incoming attribute.
It then continues to clear the interrupt_q queue, processing any remaining messages
and putting their JSON representation into the globstat_q queue.

Returns:
: None

#### *async* write_active_experiment_exp()

Asynchronously writes the active experiment data to the experiment log.

This method calls the write_exp method with the current active experiment
data to log it.

Returns:
: None

#### *async* write_active_sequence_seq()

Asynchronously writes the active sequence to storage.

If the active sequence experiment counter is greater than 1, it appends
the current active experiment to the active sequence. Otherwise, it writes
the active sequence directly.

Returns:
: None

#### *async* ws_globstat(websocket)

Handle WebSocket connections for global status updates.

This asynchronous method accepts a WebSocket connection, subscribes to global status updates,
and sends these updates to the connected WebSocket client in real-time. If an exception occurs,
it logs the error and removes the subscription.

Args:
: websocket (WebSocket): The WebSocket connection instance.

Raises:
: Exception: If an error occurs during the WebSocket communication or subscription handling.

## helao.servers.orch_api module

### *class* helao.servers.orch_api.OrchAPI(config, server_key, server_title, description, version, driver_class=None, poller_class=None)

Bases: [`HelaoFastAPI`](helao.helpers.md#helao.helpers.server_api.HelaoFastAPI)

#### \_\_init_\_(config, server_key, server_title, description, version, driver_class=None, poller_class=None)

Initialize the OrchAPI server.

> config (dict): Configuration dictionary for the server.
> server_key (str): Unique key identifying the server.
> server_title (str): Title of the server.
> description (str): Description of the server.
> version (str): Version of the server.
> driver_class (Optional[type], optional): Class for the driver. Defaults to None.
> poller_class (Optional[type], optional): Class for the poller. Defaults to None.

### *class* helao.servers.orch_api.WaitExec(\*args, \*\*kwargs)

Bases: [`Executor`](helao.helpers.md#helao.helpers.executor.Executor)

WaitExec is an executor class that performs a wait action for a specified duration.

Attributes:
: poll_rate (float): The rate at which the poll method is called.
  duration (float): The duration to wait, in seconds.
  print_every_secs (int): The interval at which status messages are printed, in seconds.
  start_time (float): The start time of the wait action.
  last_print_time (float): The last time a status message was printed.

Methods:
: \_exec(): Logs the wait action and returns a result dictionary.
  \_poll(): Periodically checks the elapsed time and updates the status.
  \_post_exec(): Logs the completion of the wait action and returns a result dictionary.

#### \_\_init_\_(\*args, \*\*kwargs)

Initializes the WaitExec class.

Args:
: ```
  *
  ```
  <br/>
  args: Variable length argument list.
  <br/>
  ```
  **
  ```
  <br/>
  kwargs: Arbitrary keyword arguments.
  <br/>
  > - print_every_secs (int, optional): Interval in seconds for printing messages. Defaults to 5.

Attributes:
: poll_rate (float): The rate at which the poll occurs, in seconds.
  duration (int): The duration to wait, retrieved from action parameters.
  print_every_secs (int): Interval in seconds for printing messages.
  start_time (float): The start time of the wait execution.
  last_print_time (float): The last time a message was printed.

### *class* helao.servers.orch_api.checkcond(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

checkcond is an enumeration that represents different types of conditions.

Attributes:
: equals (str): Represents a condition where values are equal.
  below (str): Represents a condition where a value is below a certain threshold.
  above (str): Represents a condition where a value is above a certain threshold.
  isnot (str): Represents a condition where values are not equal.
  uncond (str): Represents an unconditional state.

#### above *= 'above'*

#### below *= 'below'*

#### equals *= 'equals'*

#### isnot *= 'isnot'*

#### uncond *= 'uncond'*

## helao.servers.vis module

This module contains the implementation of the HelaoVis and Vis classes for the Helao visualization server.

Classes:
: HelaoVis(HelaoBokehAPI): A server class that extends the HelaoBokehAPI to provide visualization capabilities.
  Vis: A class to represent the visualization server.

HelaoVis:

Vis:
: server (MachineModel): An instance of MachineModel representing the server.
  server_cfg (dict): Configuration dictionary for the server.
  world_cfg (dict): Global configuration dictionary.
  doc (Document): Bokeh document instance.
  helaodirs (HelaoDirs): Directories used by the Helao system.
  <br/>
  \_\_init_\_(bokehapp: HelaoBokehAPI):
  print_message(
  <br/>
  ```
  *
  ```
  <br/>
  args, 
  <br/>
  ```
  **
  ```
  <br/>
  kwargs):

### *class* helao.servers.vis.HelaoVis(config, server_key, doc)

Bases: [`HelaoBokehAPI`](helao.helpers.md#helao.helpers.server_api.HelaoBokehAPI)

HelaoVis is a server class that extends the HelaoBokehAPI to provide visualization capabilities.

Attributes:
: vis (Vis): An instance of the Vis class for handling visualization tasks.

Methods:
: \_\_init_\_(config, server_key, doc):
  : Initialize the Vis server with the given configuration, server key, and documentation object.

#### \_\_init_\_(config, server_key, doc)

Initialize the Vis server.

Args:
: config (dict): Configuration dictionary for the server.
  server_key (str): Unique key identifying the server.
  doc (object): Documentation object for the server.

### *class* helao.servers.vis.Vis(bokehapp)

Bases: `object`

A class to represent the visualization server.

### Attributes

server
: An instance of MachineModel representing the server.

server_cfg
: Configuration dictionary for the server.

world_cfg
: Global configuration dictionary.

doc
: Bokeh document instance.

helaodirs
: Directories used by the Helao system.

### Methods

\_\_init_\_(bokehapp: HelaoBokehAPI)
: Initializes the Vis instance with the given Bokeh application.

print_message(

```
*
```

args, 

```
**
```

kwargs)
: Prints a message using the server configuration and log directory.

#### \_\_init_\_(bokehapp)

Initializes the visualization server.

Args:
: bokehapp (HelaoBokehAPI): An instance of the HelaoBokehAPI class.

Raises:
: ValueError: If the root directory is not defined in the configuration.

#### print_message(\*args, \*\*kwargs)

Prints a message with the server configuration and server name.

Parameters:

```
*
```

args: Variable length argument list.

```
**
```

kwargs: Arbitrary keyword arguments.

Returns:
None

## Module contents
