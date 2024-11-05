# helao.drivers package

## Subpackages

* [helao.drivers.data package](helao.drivers.data.md)
  * [Subpackages](helao.drivers.data.md#subpackages)
    * [helao.drivers.data.analyses package](helao.drivers.data.analyses.md)
      * [Submodules](helao.drivers.data.analyses.md#submodules)
      * [helao.drivers.data.analyses.base_analysis module](helao.drivers.data.analyses.md#module-helao.drivers.data.analyses.base_analysis)
      * [helao.drivers.data.analyses.echeuvis_stability module](helao.drivers.data.analyses.md#module-helao.drivers.data.analyses.echeuvis_stability)
      * [helao.drivers.data.analyses.icpms_local module](helao.drivers.data.analyses.md#module-helao.drivers.data.analyses.icpms_local)
      * [helao.drivers.data.analyses.uvis_bkgsubnorm module](helao.drivers.data.analyses.md#module-helao.drivers.data.analyses.uvis_bkgsubnorm)
      * [Module contents](helao.drivers.data.analyses.md#module-helao.drivers.data.analyses)
    * [helao.drivers.data.loaders package](helao.drivers.data.loaders.md)
      * [Submodules](helao.drivers.data.loaders.md#submodules)
      * [helao.drivers.data.loaders.localfs module](helao.drivers.data.loaders.md#module-helao.drivers.data.loaders.localfs)
      * [helao.drivers.data.loaders.pgs3 module](helao.drivers.data.loaders.md#module-helao.drivers.data.loaders.pgs3)
      * [Module contents](helao.drivers.data.loaders.md#module-helao.drivers.data.loaders)
  * [Submodules](helao.drivers.data.md#submodules)
  * [helao.drivers.data.HTEdata_legacy module](helao.drivers.data.md#helao-drivers-data-htedata-legacy-module)
  * [helao.drivers.data.analysis_driver module](helao.drivers.data.md#module-helao.drivers.data.analysis_driver)
    * [`HelaoAnalysisSyncer`](helao.drivers.data.md#helao.drivers.data.analysis_driver.HelaoAnalysisSyncer)
      * [`HelaoAnalysisSyncer.__init__()`](helao.drivers.data.md#helao.drivers.data.analysis_driver.HelaoAnalysisSyncer.__init__)
      * [`HelaoAnalysisSyncer.base`](helao.drivers.data.md#helao.drivers.data.analysis_driver.HelaoAnalysisSyncer.base)
      * [`HelaoAnalysisSyncer.batch_calc_dryuvis()`](helao.drivers.data.md#helao.drivers.data.analysis_driver.HelaoAnalysisSyncer.batch_calc_dryuvis)
      * [`HelaoAnalysisSyncer.batch_calc_echeuvis()`](helao.drivers.data.md#helao.drivers.data.analysis_driver.HelaoAnalysisSyncer.batch_calc_echeuvis)
      * [`HelaoAnalysisSyncer.batch_calc_icpms_local()`](helao.drivers.data.md#helao.drivers.data.analysis_driver.HelaoAnalysisSyncer.batch_calc_icpms_local)
      * [`HelaoAnalysisSyncer.enqueue_calc()`](helao.drivers.data.md#helao.drivers.data.analysis_driver.HelaoAnalysisSyncer.enqueue_calc)
      * [`HelaoAnalysisSyncer.get_loader()`](helao.drivers.data.md#helao.drivers.data.analysis_driver.HelaoAnalysisSyncer.get_loader)
      * [`HelaoAnalysisSyncer.running_tasks`](helao.drivers.data.md#helao.drivers.data.analysis_driver.HelaoAnalysisSyncer.running_tasks)
      * [`HelaoAnalysisSyncer.shutdown()`](helao.drivers.data.md#helao.drivers.data.analysis_driver.HelaoAnalysisSyncer.shutdown)
      * [`HelaoAnalysisSyncer.sync_ana()`](helao.drivers.data.md#helao.drivers.data.analysis_driver.HelaoAnalysisSyncer.sync_ana)
      * [`HelaoAnalysisSyncer.sync_exit_callback()`](helao.drivers.data.md#helao.drivers.data.analysis_driver.HelaoAnalysisSyncer.sync_exit_callback)
      * [`HelaoAnalysisSyncer.syncer()`](helao.drivers.data.md#helao.drivers.data.analysis_driver.HelaoAnalysisSyncer.syncer)
      * [`HelaoAnalysisSyncer.to_api()`](helao.drivers.data.md#helao.drivers.data.analysis_driver.HelaoAnalysisSyncer.to_api)
  * [helao.drivers.data.archive_driver module](helao.drivers.data.md#module-helao.drivers.data.archive_driver)
    * [`Archive`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive)
      * [`Archive.__init__()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.__init__)
      * [`Archive.action_startup_config()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.action_startup_config)
      * [`Archive.append_sample_status()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.append_sample_status)
      * [`Archive.assign_new_sample_status()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.assign_new_sample_status)
      * [`Archive.create_samples()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.create_samples)
      * [`Archive.custom_add_gas()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.custom_add_gas)
      * [`Archive.custom_add_liquid()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.custom_add_liquid)
      * [`Archive.custom_assembly_allowed()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.custom_assembly_allowed)
      * [`Archive.custom_dest_allowed()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.custom_dest_allowed)
      * [`Archive.custom_dilution_allowed()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.custom_dilution_allowed)
      * [`Archive.custom_is_destroyed()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.custom_is_destroyed)
      * [`Archive.custom_load()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.custom_load)
      * [`Archive.custom_query_sample()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.custom_query_sample)
      * [`Archive.custom_replace_sample()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.custom_replace_sample)
      * [`Archive.custom_unload()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.custom_unload)
      * [`Archive.custom_unloadall()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.custom_unloadall)
      * [`Archive.custom_update_position()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.custom_update_position)
      * [`Archive.destroy_sample()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.destroy_sample)
      * [`Archive.generate_plate_sample_no_list()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.generate_plate_sample_no_list)
      * [`Archive.load_config()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.load_config)
      * [`Archive.new_ref_samples()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.new_ref_samples)
      * [`Archive.selective_destroy_samples()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.selective_destroy_samples)
      * [`Archive.tray_export_csv()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.tray_export_csv)
      * [`Archive.tray_export_icpms()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.tray_export_icpms)
      * [`Archive.tray_export_json()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.tray_export_json)
      * [`Archive.tray_get_next_full()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.tray_get_next_full)
      * [`Archive.tray_load()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.tray_load)
      * [`Archive.tray_new_position()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.tray_new_position)
      * [`Archive.tray_query_sample()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.tray_query_sample)
      * [`Archive.tray_unload()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.tray_unload)
      * [`Archive.tray_unloadall()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.tray_unloadall)
      * [`Archive.tray_update_position()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.tray_update_position)
      * [`Archive.update_samples_from_db()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.update_samples_from_db)
      * [`Archive.update_samples_from_db_helper()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.update_samples_from_db_helper)
      * [`Archive.write_config()`](helao.drivers.data.md#helao.drivers.data.archive_driver.Archive.write_config)
  * [helao.drivers.data.calc_driver module](helao.drivers.data.md#module-helao.drivers.data.calc_driver)
    * [`Calc`](helao.drivers.data.md#helao.drivers.data.calc_driver.Calc)
      * [`Calc.__init__()`](helao.drivers.data.md#helao.drivers.data.calc_driver.Calc.__init__)
      * [`Calc.calc_uvis_abs()`](helao.drivers.data.md#helao.drivers.data.calc_driver.Calc.calc_uvis_abs)
      * [`Calc.check_co2_purge_level()`](helao.drivers.data.md#helao.drivers.data.calc_driver.Calc.check_co2_purge_level)
      * [`Calc.fill_syringe_volume_check()`](helao.drivers.data.md#helao.drivers.data.calc_driver.Calc.fill_syringe_volume_check)
      * [`Calc.gather_seq_data()`](helao.drivers.data.md#helao.drivers.data.calc_driver.Calc.gather_seq_data)
      * [`Calc.gather_seq_exps()`](helao.drivers.data.md#helao.drivers.data.calc_driver.Calc.gather_seq_exps)
      * [`Calc.get_seq_dict()`](helao.drivers.data.md#helao.drivers.data.calc_driver.Calc.get_seq_dict)
      * [`Calc.shutdown()`](helao.drivers.data.md#helao.drivers.data.calc_driver.Calc.shutdown)
    * [`handlenan_savgol_filter()`](helao.drivers.data.md#helao.drivers.data.calc_driver.handlenan_savgol_filter)
    * [`refadjust()`](helao.drivers.data.md#helao.drivers.data.calc_driver.refadjust)
    * [`squeeze_foms()`](helao.drivers.data.md#helao.drivers.data.calc_driver.squeeze_foms)
  * [helao.drivers.data.dbpack_driver module](helao.drivers.data.md#module-helao.drivers.data.dbpack_driver)
    * [`ActYml`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.ActYml)
      * [`ActYml.__init__()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.ActYml.__init__)
    * [`DBPack`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.DBPack)
      * [`DBPack.__init__()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.DBPack.__init__)
      * [`DBPack.add_yml_task()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.DBPack.add_yml_task)
      * [`DBPack.cleanup_root()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.DBPack.cleanup_root)
      * [`DBPack.finish_acts()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.DBPack.finish_acts)
      * [`DBPack.finish_exps()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.DBPack.finish_exps)
      * [`DBPack.finish_pending()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.DBPack.finish_pending)
      * [`DBPack.finish_yml()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.DBPack.finish_yml)
      * [`DBPack.list_pending()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.DBPack.list_pending)
      * [`DBPack.read_log()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.DBPack.read_log)
      * [`DBPack.rm()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.DBPack.rm)
      * [`DBPack.shutdown()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.DBPack.shutdown)
      * [`DBPack.update_log()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.DBPack.update_log)
      * [`DBPack.write_log()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.DBPack.write_log)
      * [`DBPack.yml_task()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.DBPack.yml_task)
    * [`ExpYml`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.ExpYml)
      * [`ExpYml.__init__()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.ExpYml.__init__)
      * [`ExpYml.create_process()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.ExpYml.create_process)
      * [`ExpYml.get_actions()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.ExpYml.get_actions)
      * [`ExpYml.parse_yml()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.ExpYml.parse_yml)
    * [`HelaoPath`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.HelaoPath)
      * [`HelaoPath.active`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.HelaoPath.active)
      * [`HelaoPath.cleanup()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.HelaoPath.cleanup)
      * [`HelaoPath.finished`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.HelaoPath.finished)
      * [`HelaoPath.relative`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.HelaoPath.relative)
      * [`HelaoPath.rename()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.HelaoPath.rename)
      * [`HelaoPath.status_idx`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.HelaoPath.status_idx)
      * [`HelaoPath.synced`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.HelaoPath.synced)
    * [`SeqYml`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.SeqYml)
      * [`SeqYml.__init__()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.SeqYml.__init__)
      * [`SeqYml.get_experiments()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.SeqYml.get_experiments)
      * [`SeqYml.parse_yml()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.SeqYml.parse_yml)
    * [`YmlOps`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.YmlOps)
      * [`YmlOps.__init__()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.YmlOps.__init__)
      * [`YmlOps.to_api()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.YmlOps.to_api)
      * [`YmlOps.to_finished()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.YmlOps.to_finished)
      * [`YmlOps.to_s3()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.YmlOps.to_s3)
      * [`YmlOps.to_synced()`](helao.drivers.data.md#helao.drivers.data.dbpack_driver.YmlOps.to_synced)
  * [helao.drivers.data.enum module](helao.drivers.data.md#module-helao.drivers.data.enum)
    * [`YmlType`](helao.drivers.data.md#helao.drivers.data.enum.YmlType)
      * [`YmlType.action`](helao.drivers.data.md#helao.drivers.data.enum.YmlType.action)
      * [`YmlType.experiment`](helao.drivers.data.md#helao.drivers.data.enum.YmlType.experiment)
      * [`YmlType.sequence`](helao.drivers.data.md#helao.drivers.data.enum.YmlType.sequence)
  * [helao.drivers.data.gpsim_driver module](helao.drivers.data.md#helao-drivers-data-gpsim-driver-module)
  * [helao.drivers.data.sync_driver module](helao.drivers.data.md#module-helao.drivers.data.sync_driver)
    * [`HelaoSyncer`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer)
      * [`HelaoSyncer.__init__()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.__init__)
      * [`HelaoSyncer.base`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.base)
      * [`HelaoSyncer.cleanup_root()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.cleanup_root)
      * [`HelaoSyncer.enqueue_yml()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.enqueue_yml)
      * [`HelaoSyncer.finish_pending()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.finish_pending)
      * [`HelaoSyncer.get_progress()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.get_progress)
      * [`HelaoSyncer.list_pending()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.list_pending)
      * [`HelaoSyncer.progress`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.progress)
      * [`HelaoSyncer.reset_sync()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.reset_sync)
      * [`HelaoSyncer.running_tasks`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.running_tasks)
      * [`HelaoSyncer.shutdown()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.shutdown)
      * [`HelaoSyncer.sync_exit_callback()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.sync_exit_callback)
      * [`HelaoSyncer.sync_process()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.sync_process)
      * [`HelaoSyncer.sync_yml()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.sync_yml)
      * [`HelaoSyncer.syncer()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.syncer)
      * [`HelaoSyncer.to_api()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.to_api)
      * [`HelaoSyncer.to_s3()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.to_s3)
      * [`HelaoSyncer.try_remove_empty()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.try_remove_empty)
      * [`HelaoSyncer.unsync_dir()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.unsync_dir)
      * [`HelaoSyncer.update_process()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoSyncer.update_process)
    * [`HelaoYml`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml)
      * [`HelaoYml.__init__()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.__init__)
      * [`HelaoYml.active_children`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.active_children)
      * [`HelaoYml.active_path`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.active_path)
      * [`HelaoYml.check_paths()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.check_paths)
      * [`HelaoYml.children`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.children)
      * [`HelaoYml.cleanup()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.cleanup)
      * [`HelaoYml.exists`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.exists)
      * [`HelaoYml.finished_children`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.finished_children)
      * [`HelaoYml.finished_path`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.finished_path)
      * [`HelaoYml.hlo_files`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.hlo_files)
      * [`HelaoYml.list_children()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.list_children)
      * [`HelaoYml.lock_files`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.lock_files)
      * [`HelaoYml.misc_files`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.misc_files)
      * [`HelaoYml.parent_path`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.parent_path)
      * [`HelaoYml.parts`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.parts)
      * [`HelaoYml.relative_path`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.relative_path)
      * [`HelaoYml.rename()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.rename)
      * [`HelaoYml.status`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.status)
      * [`HelaoYml.status_idx`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.status_idx)
      * [`HelaoYml.synced_children`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.synced_children)
      * [`HelaoYml.synced_path`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.synced_path)
      * [`HelaoYml.target`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.target)
      * [`HelaoYml.targetdir`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.targetdir)
      * [`HelaoYml.timestamp`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.timestamp)
      * [`HelaoYml.type`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.type)
      * [`HelaoYml.write_meta()`](helao.drivers.data.md#helao.drivers.data.sync_driver.HelaoYml.write_meta)
    * [`Progress`](helao.drivers.data.md#helao.drivers.data.sync_driver.Progress)
      * [`Progress.__init__()`](helao.drivers.data.md#helao.drivers.data.sync_driver.Progress.__init__)
      * [`Progress.api_done`](helao.drivers.data.md#helao.drivers.data.sync_driver.Progress.api_done)
      * [`Progress.dict`](helao.drivers.data.md#helao.drivers.data.sync_driver.Progress.dict)
      * [`Progress.list_unfinished_procs()`](helao.drivers.data.md#helao.drivers.data.sync_driver.Progress.list_unfinished_procs)
      * [`Progress.prg`](helao.drivers.data.md#helao.drivers.data.sync_driver.Progress.prg)
      * [`Progress.read_dict()`](helao.drivers.data.md#helao.drivers.data.sync_driver.Progress.read_dict)
      * [`Progress.remove_prg()`](helao.drivers.data.md#helao.drivers.data.sync_driver.Progress.remove_prg)
      * [`Progress.s3_done`](helao.drivers.data.md#helao.drivers.data.sync_driver.Progress.s3_done)
      * [`Progress.write_dict()`](helao.drivers.data.md#helao.drivers.data.sync_driver.Progress.write_dict)
      * [`Progress.yml`](helao.drivers.data.md#helao.drivers.data.sync_driver.Progress.yml)
      * [`Progress.ymlpath`](helao.drivers.data.md#helao.drivers.data.sync_driver.Progress.ymlpath)
  * [Module contents](helao.drivers.data.md#module-helao.drivers.data)
* [helao.drivers.io package](helao.drivers.io.md)
  * [Submodules](helao.drivers.io.md#submodules)
  * [helao.drivers.io.enum module](helao.drivers.io.md#module-helao.drivers.io.enum)
    * [`TriggerType`](helao.drivers.io.md#helao.drivers.io.enum.TriggerType)
      * [`TriggerType.blip`](helao.drivers.io.md#helao.drivers.io.enum.TriggerType.blip)
      * [`TriggerType.fallingedge`](helao.drivers.io.md#helao.drivers.io.enum.TriggerType.fallingedge)
      * [`TriggerType.risingedge`](helao.drivers.io.md#helao.drivers.io.enum.TriggerType.risingedge)
  * [helao.drivers.io.galil_io_driver module](helao.drivers.io.md#helao-drivers-io-galil-io-driver-module)
  * [helao.drivers.io.nidaqmx_driver module](helao.drivers.io.md#module-helao.drivers.io.nidaqmx_driver)
    * [`cNIMAX`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX)
      * [`cNIMAX.Heatloop()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.Heatloop)
      * [`cNIMAX.IOloop()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.IOloop)
      * [`cNIMAX.__init__()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.__init__)
      * [`cNIMAX.create_IVtask()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.create_IVtask)
      * [`cNIMAX.create_monitortask()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.create_monitortask)
      * [`cNIMAX.estop()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.estop)
      * [`cNIMAX.get_digital_in()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.get_digital_in)
      * [`cNIMAX.monitorloop()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.monitorloop)
      * [`cNIMAX.read_T()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.read_T)
      * [`cNIMAX.run_cell_IV()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.run_cell_IV)
      * [`cNIMAX.set_IO_signalq()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.set_IO_signalq)
      * [`cNIMAX.set_IO_signalq_nowait()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.set_IO_signalq_nowait)
      * [`cNIMAX.set_digital_out()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.set_digital_out)
      * [`cNIMAX.shutdown()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.shutdown)
      * [`cNIMAX.stop()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.stop)
      * [`cNIMAX.stop_heatloop()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.stop_heatloop)
      * [`cNIMAX.stop_monitor()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.stop_monitor)
      * [`cNIMAX.streamIV_callback()`](helao.drivers.io.md#helao.drivers.io.nidaqmx_driver.cNIMAX.streamIV_callback)
  * [Module contents](helao.drivers.io.md#module-helao.drivers.io)
* [helao.drivers.mfc package](helao.drivers.mfc.md)
  * [Submodules](helao.drivers.mfc.md#submodules)
  * [helao.drivers.mfc.alicat_driver module](helao.drivers.mfc.md#module-helao.drivers.mfc.alicat_driver)
    * [`AliCatMFC`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC)
      * [`AliCatMFC.__init__()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.__init__)
      * [`AliCatMFC.async_shutdown()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.async_shutdown)
      * [`AliCatMFC.estop()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.estop)
      * [`AliCatMFC.hold_cancel()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.hold_cancel)
      * [`AliCatMFC.hold_valve()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.hold_valve)
      * [`AliCatMFC.hold_valve_closed()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.hold_valve_closed)
      * [`AliCatMFC.list_gases()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.list_gases)
      * [`AliCatMFC.lock_display()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.lock_display)
      * [`AliCatMFC.make_fc_instance()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.make_fc_instance)
      * [`AliCatMFC.manual_query_status()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.manual_query_status)
      * [`AliCatMFC.poll_sensor_loop()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.poll_sensor_loop)
      * [`AliCatMFC.poll_signal_loop()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.poll_signal_loop)
      * [`AliCatMFC.set_flowrate()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.set_flowrate)
      * [`AliCatMFC.set_gas()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.set_gas)
      * [`AliCatMFC.set_gas_mixture()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.set_gas_mixture)
      * [`AliCatMFC.set_pressure()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.set_pressure)
      * [`AliCatMFC.shutdown()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.shutdown)
      * [`AliCatMFC.start_polling()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.start_polling)
      * [`AliCatMFC.stop_polling()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.stop_polling)
      * [`AliCatMFC.tare_pressure()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.tare_pressure)
      * [`AliCatMFC.tare_volume()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.tare_volume)
      * [`AliCatMFC.unlock_display()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.AliCatMFC.unlock_display)
    * [`MfcConstPresExec`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.MfcConstPresExec)
      * [`MfcConstPresExec.__init__()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.MfcConstPresExec.__init__)
      * [`MfcConstPresExec.eval_pressure()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.MfcConstPresExec.eval_pressure)
    * [`MfcExec`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.MfcExec)
      * [`MfcExec.__init__()`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.MfcExec.__init__)
    * [`PfcExec`](helao.drivers.mfc.md#helao.drivers.mfc.alicat_driver.PfcExec)
  * [Module contents](helao.drivers.mfc.md#module-helao.drivers.mfc)
* [helao.drivers.motion package](helao.drivers.motion.md)
  * [Submodules](helao.drivers.motion.md#submodules)
  * [helao.drivers.motion.enum module](helao.drivers.motion.md#module-helao.drivers.motion.enum)
    * [`MoveModes`](helao.drivers.motion.md#helao.drivers.motion.enum.MoveModes)
      * [`MoveModes.absolute`](helao.drivers.motion.md#helao.drivers.motion.enum.MoveModes.absolute)
      * [`MoveModes.homing`](helao.drivers.motion.md#helao.drivers.motion.enum.MoveModes.homing)
      * [`MoveModes.relative`](helao.drivers.motion.md#helao.drivers.motion.enum.MoveModes.relative)
    * [`TransformationModes`](helao.drivers.motion.md#helao.drivers.motion.enum.TransformationModes)
      * [`TransformationModes.instrxy`](helao.drivers.motion.md#helao.drivers.motion.enum.TransformationModes.instrxy)
      * [`TransformationModes.motorxy`](helao.drivers.motion.md#helao.drivers.motion.enum.TransformationModes.motorxy)
      * [`TransformationModes.platexy`](helao.drivers.motion.md#helao.drivers.motion.enum.TransformationModes.platexy)
  * [helao.drivers.motion.galil_motion_driver module](helao.drivers.motion.md#helao-drivers-motion-galil-motion-driver-module)
  * [helao.drivers.motion.kinesis_driver module](helao.drivers.motion.md#module-helao.drivers.motion.kinesis_driver)
    * [`KinesisMotor`](helao.drivers.motion.md#helao.drivers.motion.kinesis_driver.KinesisMotor)
      * [`KinesisMotor.__init__()`](helao.drivers.motion.md#helao.drivers.motion.kinesis_driver.KinesisMotor.__init__)
      * [`KinesisMotor.connect()`](helao.drivers.motion.md#helao.drivers.motion.kinesis_driver.KinesisMotor.connect)
      * [`KinesisMotor.disconnect()`](helao.drivers.motion.md#helao.drivers.motion.kinesis_driver.KinesisMotor.disconnect)
      * [`KinesisMotor.get_status()`](helao.drivers.motion.md#helao.drivers.motion.kinesis_driver.KinesisMotor.get_status)
      * [`KinesisMotor.move()`](helao.drivers.motion.md#helao.drivers.motion.kinesis_driver.KinesisMotor.move)
      * [`KinesisMotor.reset()`](helao.drivers.motion.md#helao.drivers.motion.kinesis_driver.KinesisMotor.reset)
      * [`KinesisMotor.setup()`](helao.drivers.motion.md#helao.drivers.motion.kinesis_driver.KinesisMotor.setup)
      * [`KinesisMotor.stop()`](helao.drivers.motion.md#helao.drivers.motion.kinesis_driver.KinesisMotor.stop)
    * [`KinesisPoller`](helao.drivers.motion.md#helao.drivers.motion.kinesis_driver.KinesisPoller)
      * [`KinesisPoller.get_data()`](helao.drivers.motion.md#helao.drivers.motion.kinesis_driver.KinesisPoller.get_data)
    * [`MoveModes`](helao.drivers.motion.md#helao.drivers.motion.kinesis_driver.MoveModes)
      * [`MoveModes.absolute`](helao.drivers.motion.md#helao.drivers.motion.kinesis_driver.MoveModes.absolute)
      * [`MoveModes.relative`](helao.drivers.motion.md#helao.drivers.motion.kinesis_driver.MoveModes.relative)
  * [Module contents](helao.drivers.motion.md#module-helao.drivers.motion)
* [helao.drivers.pstat package](helao.drivers.pstat.md)
  * [Subpackages](helao.drivers.pstat.md#subpackages)
    * [helao.drivers.pstat.biologic package](helao.drivers.pstat.biologic.md)
      * [Submodules](helao.drivers.pstat.biologic.md#submodules)
      * [helao.drivers.pstat.biologic.driver module](helao.drivers.pstat.biologic.md#helao-drivers-pstat-biologic-driver-module)
      * [helao.drivers.pstat.biologic.technique module](helao.drivers.pstat.biologic.md#helao-drivers-pstat-biologic-technique-module)
      * [Module contents](helao.drivers.pstat.biologic.md#module-helao.drivers.pstat.biologic)
    * [helao.drivers.pstat.gamry package](helao.drivers.pstat.gamry.md)
      * [Submodules](helao.drivers.pstat.gamry.md#submodules)
      * [helao.drivers.pstat.gamry.device module](helao.drivers.pstat.gamry.md#module-helao.drivers.pstat.gamry.device)
      * [helao.drivers.pstat.gamry.driver module](helao.drivers.pstat.gamry.md#helao-drivers-pstat-gamry-driver-module)
      * [helao.drivers.pstat.gamry.dtaq module](helao.drivers.pstat.gamry.md#module-helao.drivers.pstat.gamry.dtaq)
      * [helao.drivers.pstat.gamry.range module](helao.drivers.pstat.gamry.md#module-helao.drivers.pstat.gamry.range)
      * [helao.drivers.pstat.gamry.signal module](helao.drivers.pstat.gamry.md#module-helao.drivers.pstat.gamry.signal)
      * [helao.drivers.pstat.gamry.sink module](helao.drivers.pstat.gamry.md#module-helao.drivers.pstat.gamry.sink)
      * [helao.drivers.pstat.gamry.technique module](helao.drivers.pstat.gamry.md#module-helao.drivers.pstat.gamry.technique)
      * [Module contents](helao.drivers.pstat.gamry.md#module-helao.drivers.pstat.gamry)
  * [Submodules](helao.drivers.pstat.md#submodules)
  * [helao.drivers.pstat.cpsim_driver module](helao.drivers.pstat.md#helao-drivers-pstat-cpsim-driver-module)
  * [helao.drivers.pstat.enum module](helao.drivers.pstat.md#module-helao.drivers.pstat.enum)
    * [`Gamry_IErange_IFC1010`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_IFC1010)
      * [`Gamry_IErange_IFC1010.auto`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_IFC1010.auto)
      * [`Gamry_IErange_IFC1010.mode10`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_IFC1010.mode10)
      * [`Gamry_IErange_IFC1010.mode11`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_IFC1010.mode11)
      * [`Gamry_IErange_IFC1010.mode12`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_IFC1010.mode12)
      * [`Gamry_IErange_IFC1010.mode4`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_IFC1010.mode4)
      * [`Gamry_IErange_IFC1010.mode5`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_IFC1010.mode5)
      * [`Gamry_IErange_IFC1010.mode6`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_IFC1010.mode6)
      * [`Gamry_IErange_IFC1010.mode7`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_IFC1010.mode7)
      * [`Gamry_IErange_IFC1010.mode8`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_IFC1010.mode8)
      * [`Gamry_IErange_IFC1010.mode9`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_IFC1010.mode9)
    * [`Gamry_IErange_PCI4G300`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G300)
      * [`Gamry_IErange_PCI4G300.auto`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G300.auto)
      * [`Gamry_IErange_PCI4G300.mode10`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G300.mode10)
      * [`Gamry_IErange_PCI4G300.mode11`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G300.mode11)
      * [`Gamry_IErange_PCI4G300.mode3`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G300.mode3)
      * [`Gamry_IErange_PCI4G300.mode4`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G300.mode4)
      * [`Gamry_IErange_PCI4G300.mode5`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G300.mode5)
      * [`Gamry_IErange_PCI4G300.mode6`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G300.mode6)
      * [`Gamry_IErange_PCI4G300.mode7`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G300.mode7)
      * [`Gamry_IErange_PCI4G300.mode8`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G300.mode8)
      * [`Gamry_IErange_PCI4G300.mode9`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G300.mode9)
    * [`Gamry_IErange_PCI4G750`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G750)
      * [`Gamry_IErange_PCI4G750.auto`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G750.auto)
      * [`Gamry_IErange_PCI4G750.mode10`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G750.mode10)
      * [`Gamry_IErange_PCI4G750.mode11`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G750.mode11)
      * [`Gamry_IErange_PCI4G750.mode3`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G750.mode3)
      * [`Gamry_IErange_PCI4G750.mode4`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G750.mode4)
      * [`Gamry_IErange_PCI4G750.mode5`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G750.mode5)
      * [`Gamry_IErange_PCI4G750.mode6`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G750.mode6)
      * [`Gamry_IErange_PCI4G750.mode7`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G750.mode7)
      * [`Gamry_IErange_PCI4G750.mode8`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G750.mode8)
      * [`Gamry_IErange_PCI4G750.mode9`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_PCI4G750.mode9)
    * [`Gamry_IErange_REF600`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_REF600)
      * [`Gamry_IErange_REF600.auto`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_REF600.auto)
      * [`Gamry_IErange_REF600.mode1`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_REF600.mode1)
      * [`Gamry_IErange_REF600.mode10`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_REF600.mode10)
      * [`Gamry_IErange_REF600.mode11`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_REF600.mode11)
      * [`Gamry_IErange_REF600.mode2`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_REF600.mode2)
      * [`Gamry_IErange_REF600.mode3`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_REF600.mode3)
      * [`Gamry_IErange_REF600.mode4`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_REF600.mode4)
      * [`Gamry_IErange_REF600.mode5`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_REF600.mode5)
      * [`Gamry_IErange_REF600.mode6`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_REF600.mode6)
      * [`Gamry_IErange_REF600.mode7`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_REF600.mode7)
      * [`Gamry_IErange_REF600.mode8`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_REF600.mode8)
      * [`Gamry_IErange_REF600.mode9`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_REF600.mode9)
    * [`Gamry_IErange_dflt`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt)
      * [`Gamry_IErange_dflt.auto`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt.auto)
      * [`Gamry_IErange_dflt.mode0`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt.mode0)
      * [`Gamry_IErange_dflt.mode1`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt.mode1)
      * [`Gamry_IErange_dflt.mode10`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt.mode10)
      * [`Gamry_IErange_dflt.mode11`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt.mode11)
      * [`Gamry_IErange_dflt.mode12`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt.mode12)
      * [`Gamry_IErange_dflt.mode13`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt.mode13)
      * [`Gamry_IErange_dflt.mode14`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt.mode14)
      * [`Gamry_IErange_dflt.mode15`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt.mode15)
      * [`Gamry_IErange_dflt.mode2`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt.mode2)
      * [`Gamry_IErange_dflt.mode3`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt.mode3)
      * [`Gamry_IErange_dflt.mode4`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt.mode4)
      * [`Gamry_IErange_dflt.mode5`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt.mode5)
      * [`Gamry_IErange_dflt.mode6`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt.mode6)
      * [`Gamry_IErange_dflt.mode7`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt.mode7)
      * [`Gamry_IErange_dflt.mode8`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt.mode8)
      * [`Gamry_IErange_dflt.mode9`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_IErange_dflt.mode9)
    * [`Gamry_modes`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_modes)
      * [`Gamry_modes.CA`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_modes.CA)
      * [`Gamry_modes.CP`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_modes.CP)
      * [`Gamry_modes.CV`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_modes.CV)
      * [`Gamry_modes.EIS`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_modes.EIS)
      * [`Gamry_modes.LSV`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_modes.LSV)
      * [`Gamry_modes.OCV`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_modes.OCV)
      * [`Gamry_modes.RCA`](helao.drivers.pstat.md#helao.drivers.pstat.enum.Gamry_modes.RCA)
  * [helao.drivers.pstat.gamry_driver module](helao.drivers.pstat.md#helao-drivers-pstat-gamry-driver-module)
  * [Module contents](helao.drivers.pstat.md#module-helao.drivers.pstat)
* [helao.drivers.pump package](helao.drivers.pump.md)
  * [Submodules](helao.drivers.pump.md#submodules)
  * [helao.drivers.pump.legato_driver module](helao.drivers.pump.md#module-helao.drivers.pump.legato_driver)
  * [helao.drivers.pump.simdos_driver module](helao.drivers.pump.md#module-helao.drivers.pump.simdos_driver)
  * [Module contents](helao.drivers.pump.md#module-helao.drivers.pump)
* [helao.drivers.robot package](helao.drivers.robot.md)
  * [Submodules](helao.drivers.robot.md#submodules)
  * [helao.drivers.robot.enum module](helao.drivers.robot.md#module-helao.drivers.robot.enum)
    * [`CAMS`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS)
      * [`CAMS.archive`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS.archive)
      * [`CAMS.deepclean`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS.deepclean)
      * [`CAMS.injection_custom_GC_gas_start`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS.injection_custom_GC_gas_start)
      * [`CAMS.injection_custom_GC_gas_wait`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS.injection_custom_GC_gas_wait)
      * [`CAMS.injection_custom_GC_liquid_start`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS.injection_custom_GC_liquid_start)
      * [`CAMS.injection_custom_GC_liquid_wait`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS.injection_custom_GC_liquid_wait)
      * [`CAMS.injection_custom_HPLC`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS.injection_custom_HPLC)
      * [`CAMS.injection_tray_GC_gas_start`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS.injection_tray_GC_gas_start)
      * [`CAMS.injection_tray_GC_gas_wait`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS.injection_tray_GC_gas_wait)
      * [`CAMS.injection_tray_GC_liquid_start`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS.injection_tray_GC_liquid_start)
      * [`CAMS.injection_tray_GC_liquid_wait`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS.injection_tray_GC_liquid_wait)
      * [`CAMS.injection_tray_HPLC`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS.injection_tray_HPLC)
      * [`CAMS.none`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS.none)
      * [`CAMS.transfer_custom_custom`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS.transfer_custom_custom)
      * [`CAMS.transfer_custom_tray`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS.transfer_custom_tray)
      * [`CAMS.transfer_tray_custom`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS.transfer_tray_custom)
      * [`CAMS.transfer_tray_tray`](helao.drivers.robot.md#helao.drivers.robot.enum.CAMS.transfer_tray_tray)
    * [`GCsampletype`](helao.drivers.robot.md#helao.drivers.robot.enum.GCsampletype)
      * [`GCsampletype.gas`](helao.drivers.robot.md#helao.drivers.robot.enum.GCsampletype.gas)
      * [`GCsampletype.liquid`](helao.drivers.robot.md#helao.drivers.robot.enum.GCsampletype.liquid)
      * [`GCsampletype.none`](helao.drivers.robot.md#helao.drivers.robot.enum.GCsampletype.none)
    * [`PALtools`](helao.drivers.robot.md#helao.drivers.robot.enum.PALtools)
      * [`PALtools.HS1`](helao.drivers.robot.md#helao.drivers.robot.enum.PALtools.HS1)
      * [`PALtools.HS2`](helao.drivers.robot.md#helao.drivers.robot.enum.PALtools.HS2)
      * [`PALtools.LS1`](helao.drivers.robot.md#helao.drivers.robot.enum.PALtools.LS1)
      * [`PALtools.LS2`](helao.drivers.robot.md#helao.drivers.robot.enum.PALtools.LS2)
      * [`PALtools.LS3`](helao.drivers.robot.md#helao.drivers.robot.enum.PALtools.LS3)
      * [`PALtools.LS4`](helao.drivers.robot.md#helao.drivers.robot.enum.PALtools.LS4)
      * [`PALtools.LS5`](helao.drivers.robot.md#helao.drivers.robot.enum.PALtools.LS5)
    * [`Spacingmethod`](helao.drivers.robot.md#helao.drivers.robot.enum.Spacingmethod)
      * [`Spacingmethod.custom`](helao.drivers.robot.md#helao.drivers.robot.enum.Spacingmethod.custom)
      * [`Spacingmethod.geometric`](helao.drivers.robot.md#helao.drivers.robot.enum.Spacingmethod.geometric)
      * [`Spacingmethod.linear`](helao.drivers.robot.md#helao.drivers.robot.enum.Spacingmethod.linear)
  * [helao.drivers.robot.pal_driver module](helao.drivers.robot.md#module-helao.drivers.robot.pal_driver)
    * [`GCsampletype`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.GCsampletype)
      * [`GCsampletype.gas`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.GCsampletype.gas)
      * [`GCsampletype.liquid`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.GCsampletype.liquid)
      * [`GCsampletype.none`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.GCsampletype.none)
    * [`PAL`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL)
      * [`PAL.__init__()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.__init__)
      * [`PAL.check_tool()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.check_tool)
      * [`PAL.estop()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.estop)
      * [`PAL.kill_PAL()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.kill_PAL)
      * [`PAL.kill_PAL_cygwin()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.kill_PAL_cygwin)
      * [`PAL.kill_PAL_local()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.kill_PAL_local)
      * [`PAL.method_ANEC_GC()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.method_ANEC_GC)
      * [`PAL.method_ANEC_aliquot()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.method_ANEC_aliquot)
      * [`PAL.method_arbitrary()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.method_arbitrary)
      * [`PAL.method_archive()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.method_archive)
      * [`PAL.method_deepclean()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.method_deepclean)
      * [`PAL.method_injection_custom_GC()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.method_injection_custom_GC)
      * [`PAL.method_injection_custom_HPLC()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.method_injection_custom_HPLC)
      * [`PAL.method_injection_tray_GC()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.method_injection_tray_GC)
      * [`PAL.method_injection_tray_HPLC()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.method_injection_tray_HPLC)
      * [`PAL.method_transfer_custom_custom()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.method_transfer_custom_custom)
      * [`PAL.method_transfer_custom_tray()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.method_transfer_custom_tray)
      * [`PAL.method_transfer_tray_custom()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.method_transfer_tray_custom)
      * [`PAL.method_transfer_tray_tray()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.method_transfer_tray_tray)
      * [`PAL.set_IO_signalq()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.set_IO_signalq)
      * [`PAL.set_IO_signalq_nowait()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.set_IO_signalq_nowait)
      * [`PAL.shutdown()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.shutdown)
      * [`PAL.stop()`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PAL.stop)
    * [`PALposition`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALposition)
      * [`PALposition.error`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALposition.error)
      * [`PALposition.model_computed_fields`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALposition.model_computed_fields)
      * [`PALposition.model_config`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALposition.model_config)
      * [`PALposition.model_fields`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALposition.model_fields)
      * [`PALposition.position`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALposition.position)
      * [`PALposition.samples_final`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALposition.samples_final)
      * [`PALposition.samples_initial`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALposition.samples_initial)
      * [`PALposition.slot`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALposition.slot)
      * [`PALposition.tray`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALposition.tray)
      * [`PALposition.vial`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALposition.vial)
    * [`PALtools`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALtools)
      * [`PALtools.HS1`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALtools.HS1)
      * [`PALtools.HS2`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALtools.HS2)
      * [`PALtools.LS1`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALtools.LS1)
      * [`PALtools.LS2`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALtools.LS2)
      * [`PALtools.LS3`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALtools.LS3)
      * [`PALtools.LS4`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALtools.LS4)
      * [`PALtools.LS5`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.PALtools.LS5)
    * [`Spacingmethod`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.Spacingmethod)
      * [`Spacingmethod.custom`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.Spacingmethod.custom)
      * [`Spacingmethod.geometric`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.Spacingmethod.geometric)
      * [`Spacingmethod.linear`](helao.drivers.robot.md#helao.drivers.robot.pal_driver.Spacingmethod.linear)
  * [Module contents](helao.drivers.robot.md#module-helao.drivers.robot)
* [helao.drivers.sensor package](helao.drivers.sensor.md)
  * [Submodules](helao.drivers.sensor.md#submodules)
  * [helao.drivers.sensor.axiscam_driver module](helao.drivers.sensor.md#module-helao.drivers.sensor.axiscam_driver)
    * [`AxisCam`](helao.drivers.sensor.md#helao.drivers.sensor.axiscam_driver.AxisCam)
      * [`AxisCam.__init__()`](helao.drivers.sensor.md#helao.drivers.sensor.axiscam_driver.AxisCam.__init__)
      * [`AxisCam.acquire_image()`](helao.drivers.sensor.md#helao.drivers.sensor.axiscam_driver.AxisCam.acquire_image)
      * [`AxisCam.shutdown()`](helao.drivers.sensor.md#helao.drivers.sensor.axiscam_driver.AxisCam.shutdown)
    * [`AxisCamExec`](helao.drivers.sensor.md#helao.drivers.sensor.axiscam_driver.AxisCamExec)
      * [`AxisCamExec.__init__()`](helao.drivers.sensor.md#helao.drivers.sensor.axiscam_driver.AxisCamExec.__init__)
      * [`AxisCamExec.write_image()`](helao.drivers.sensor.md#helao.drivers.sensor.axiscam_driver.AxisCamExec.write_image)
  * [helao.drivers.sensor.cm0134_driver module](helao.drivers.sensor.md#helao-drivers-sensor-cm0134-driver-module)
  * [helao.drivers.sensor.sprintir_driver module](helao.drivers.sensor.md#module-helao.drivers.sensor.sprintir_driver)
  * [Module contents](helao.drivers.sensor.md#module-helao.drivers.sensor)
* [helao.drivers.spec package](helao.drivers.spec.md)
  * [Subpackages](helao.drivers.spec.md#subpackages)
    * [helao.drivers.spec.andor package](helao.drivers.spec.andor.md)
      * [Submodules](helao.drivers.spec.andor.md#submodules)
      * [helao.drivers.spec.andor.driver module](helao.drivers.spec.andor.md#helao-drivers-spec-andor-driver-module)
      * [helao.drivers.spec.andor.test_funcs module](helao.drivers.spec.andor.md#helao-drivers-spec-andor-test-funcs-module)
      * [Module contents](helao.drivers.spec.andor.md#module-helao.drivers.spec.andor)
  * [Submodules](helao.drivers.spec.md#submodules)
  * [helao.drivers.spec.enum module](helao.drivers.spec.md#module-helao.drivers.spec.enum)
    * [`ReferenceMode`](helao.drivers.spec.md#helao.drivers.spec.enum.ReferenceMode)
      * [`ReferenceMode.blank`](helao.drivers.spec.md#helao.drivers.spec.enum.ReferenceMode.blank)
      * [`ReferenceMode.builtin`](helao.drivers.spec.md#helao.drivers.spec.enum.ReferenceMode.builtin)
      * [`ReferenceMode.internal`](helao.drivers.spec.md#helao.drivers.spec.enum.ReferenceMode.internal)
    * [`SpecTrigType`](helao.drivers.spec.md#helao.drivers.spec.enum.SpecTrigType)
      * [`SpecTrigType.external`](helao.drivers.spec.md#helao.drivers.spec.enum.SpecTrigType.external)
      * [`SpecTrigType.internal`](helao.drivers.spec.md#helao.drivers.spec.enum.SpecTrigType.internal)
      * [`SpecTrigType.off`](helao.drivers.spec.md#helao.drivers.spec.enum.SpecTrigType.off)
    * [`SpecType`](helao.drivers.spec.md#helao.drivers.spec.enum.SpecType)
      * [`SpecType.R`](helao.drivers.spec.md#helao.drivers.spec.enum.SpecType.R)
      * [`SpecType.T`](helao.drivers.spec.md#helao.drivers.spec.enum.SpecType.T)
  * [helao.drivers.spec.spectral_products_driver module](helao.drivers.spec.md#module-helao.drivers.spec.spectral_products_driver)
    * [`SM303`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303)
      * [`SM303.IOloop()`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303.IOloop)
      * [`SM303.__init__()`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303.__init__)
      * [`SM303.acquire_spec_adv()`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303.acquire_spec_adv)
      * [`SM303.acquire_spec_extrig()`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303.acquire_spec_extrig)
      * [`SM303.close_spec_connection()`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303.close_spec_connection)
      * [`SM303.continuous_read()`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303.continuous_read)
      * [`SM303.estop()`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303.estop)
      * [`SM303.read_data()`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303.read_data)
      * [`SM303.set_IO_signalq()`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303.set_IO_signalq)
      * [`SM303.set_IO_signalq_nowait()`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303.set_IO_signalq_nowait)
      * [`SM303.set_extedge_mode()`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303.set_extedge_mode)
      * [`SM303.set_integration_time()`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303.set_integration_time)
      * [`SM303.set_trigger_mode()`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303.set_trigger_mode)
      * [`SM303.setup_sm303()`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303.setup_sm303)
      * [`SM303.shutdown()`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303.shutdown)
      * [`SM303.stop()`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303.stop)
      * [`SM303.unset_external_trigger()`](helao.drivers.spec.md#helao.drivers.spec.spectral_products_driver.SM303.unset_external_trigger)
  * [Module contents](helao.drivers.spec.md#module-helao.drivers.spec)
* [helao.drivers.temperature_control package](helao.drivers.temperature_control.md)
  * [Submodules](helao.drivers.temperature_control.md#submodules)
  * [helao.drivers.temperature_control.mecom_driver module](helao.drivers.temperature_control.md#module-helao.drivers.temperature_control.mecom_driver)
    * [`MeerstetterTEC`](helao.drivers.temperature_control.md#helao.drivers.temperature_control.mecom_driver.MeerstetterTEC)
      * [`MeerstetterTEC.__init__()`](helao.drivers.temperature_control.md#helao.drivers.temperature_control.mecom_driver.MeerstetterTEC.__init__)
      * [`MeerstetterTEC.disable()`](helao.drivers.temperature_control.md#helao.drivers.temperature_control.mecom_driver.MeerstetterTEC.disable)
      * [`MeerstetterTEC.enable()`](helao.drivers.temperature_control.md#helao.drivers.temperature_control.mecom_driver.MeerstetterTEC.enable)
      * [`MeerstetterTEC.get_data()`](helao.drivers.temperature_control.md#helao.drivers.temperature_control.mecom_driver.MeerstetterTEC.get_data)
      * [`MeerstetterTEC.poll_sensor_loop()`](helao.drivers.temperature_control.md#helao.drivers.temperature_control.mecom_driver.MeerstetterTEC.poll_sensor_loop)
      * [`MeerstetterTEC.session()`](helao.drivers.temperature_control.md#helao.drivers.temperature_control.mecom_driver.MeerstetterTEC.session)
      * [`MeerstetterTEC.set_temp()`](helao.drivers.temperature_control.md#helao.drivers.temperature_control.mecom_driver.MeerstetterTEC.set_temp)
      * [`MeerstetterTEC.shutdown()`](helao.drivers.temperature_control.md#helao.drivers.temperature_control.mecom_driver.MeerstetterTEC.shutdown)
    * [`TECMonExec`](helao.drivers.temperature_control.md#helao.drivers.temperature_control.mecom_driver.TECMonExec)
      * [`TECMonExec.__init__()`](helao.drivers.temperature_control.md#helao.drivers.temperature_control.mecom_driver.TECMonExec.__init__)
    * [`TECWaitExec`](helao.drivers.temperature_control.md#helao.drivers.temperature_control.mecom_driver.TECWaitExec)
      * [`TECWaitExec.__init__()`](helao.drivers.temperature_control.md#helao.drivers.temperature_control.mecom_driver.TECWaitExec.__init__)
  * [Module contents](helao.drivers.temperature_control.md#module-helao.drivers.temperature_control)
* [helao.drivers.test_station package](helao.drivers.test_station.md)
  * [Subpackages](helao.drivers.test_station.md#subpackages)
    * [helao.drivers.test_station.leancat package](helao.drivers.test_station.leancat.md)
      * [Subpackages](helao.drivers.test_station.leancat.md#subpackages)
      * [Submodules](helao.drivers.test_station.leancat.md#submodules)
      * [helao.drivers.test_station.leancat.driver module](helao.drivers.test_station.leancat.md#helao-drivers-test-station-leancat-driver-module)
      * [Module contents](helao.drivers.test_station.leancat.md#module-helao.drivers.test_station.leancat)
  * [Module contents](helao.drivers.test_station.md#module-helao.drivers.test_station)

## Submodules

## helao.drivers.helao_driver module

This module defines the core classes and methods for the Helao driver framework.

Classes:
: DriverStatus (StrEnum): Enumerated driver status strings for DriverResponse objects.
  DriverResponseType (StrEnum): Success or failure flag for a public driver method’s response.
  DriverResponse (dataclass): Standardized response for all public driver methods.
  HelaoDriver (ABC): Generic class for Helao drivers without base.py dependency.
  DriverPoller: Generic class for Helao driver polling with optional base dependency.

Functions:
: HelaoDriver.connect(self) -> DriverResponse: Open connection to resource.
  HelaoDriver.get_status(self) -> DriverResponse: Return current driver status.
  HelaoDriver.stop(self) -> DriverResponse: General stop method, abort all active methods e.g. motion, I/O, compute.
  HelaoDriver.reset(self) -> DriverResponse: Reinitialize driver, force-close old connection if necessary.
  HelaoDriver.disconnect(self) -> DriverResponse: Release connection to resource.
  DriverPoller.get_data(self) -> DriverResponse: Method to be implemented by subclasses to return a dictionary of polled values.

### *class* helao.drivers.helao_driver.DriverPoller(driver, wait_time=0.05)

Bases: `object`

A class to handle polling of a HelaoDriver at regular intervals.

### Attributes:

driver
: The driver instance to be polled.

wait_time
: The time interval (in seconds) between each poll.

last_update
: The timestamp of the last successful poll.

live_dict
: A dictionary to store the live data from the driver.

polling
: A flag indicating whether polling is currently active.

### Methods:

\_\_init_\_(driver: HelaoDriver, wait_time: float = 0.05) -> None
: Initializes the DriverPoller with the given driver and wait time.

async \_start_polling()
: Starts the polling process by raising a signal.

async \_stop_polling()
: Stops the polling process by raising a signal.

async \_poll_signal_loop()
: An internal loop that waits for polling signals to start or stop polling.

async \_poll_sensor_loop()
: An internal loop that performs the actual polling of the driver at regular intervals.

get_data() -> DriverResponse
: A placeholder method to retrieve data from the driver. Should be implemented by subclasses.

#### \_\_init_\_(driver, wait_time=0.05)

Initializes the HelaoDriver instance.

Args:
: driver (HelaoDriver): The driver instance to be used.
  wait_time (float, optional): The wait time between polling operations. Defaults to 0.05 seconds.

Attributes:
: driver (HelaoDriver): The driver instance to be used.
  wait_time (float): The wait time between polling operations.
  aloop (asyncio.AbstractEventLoop): The running event loop.
  live_dict (dict): A dictionary to store live data.
  last_update (datetime.datetime): The timestamp of the last update.
  polling (bool): A flag indicating whether polling is active.
  poll_signalq (asyncio.Queue): A queue for polling signals.
  poll_signal_task (asyncio.Task): The task for the polling signal loop.
  polling_task (asyncio.Task): The task for the polling sensor loop.
  \_base_hook (Optional[Callable]): A base hook for additional functionality.

#### driver *: [`HelaoDriver`](#helao.drivers.helao_driver.HelaoDriver)*

#### get_data()

Retrieves data from the driver.

This method is intended to be overridden by subclasses to provide
specific data retrieval functionality. By default, it logs a message
indicating that the method has not been implemented and returns an
empty DriverResponse object.

* **Return type:**
  [`DriverResponse`](#helao.drivers.helao_driver.DriverResponse)

Returns:
: DriverResponse: An empty response object indicating no data.

#### last_update *: `datetime`*

#### live_dict *: `dict`*

#### polling *: `bool`*

#### wait_time *: `float`*

### *class* helao.drivers.helao_driver.DriverResponse(response=DriverResponseType.not_implemented, message='', data=<factory>, status=DriverStatus.unknown)

Bases: `object`

DriverResponse class encapsulates the response from a driver operation.

Attributes:
: response (DriverResponseType): The type of response from the driver.
  message (str): A message associated with the response.
  data (dict): Additional data related to the response.
  status (DriverStatus): The status of the driver response.
  timestamp (datetime): The timestamp when the response was created.

Methods:
: \_\_post_init_\_(): Initializes the timestamp attribute after the object is created.
  timestamp_str(): Returns the timestamp as a formatted string.

#### \_\_init_\_(response=DriverResponseType.not_implemented, message='', data=<factory>, status=DriverStatus.unknown)

#### data *: `dict`*

#### message *: `str`* *= ''*

#### response *: [`DriverResponseType`](#helao.drivers.helao_driver.DriverResponseType)* *= 'not_implemented'*

#### status *: [`DriverStatus`](#helao.drivers.helao_driver.DriverStatus)* *= 'unknown'*

#### timestamp *: `datetime`*

#### *property* timestamp_str

### *class* helao.drivers.helao_driver.DriverResponseType(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `StrEnum`

DriverResponseType is an enumeration that represents the possible outcomes of a method execution in the driver.

Attributes:
: success (str): Indicates that the method executed successfully.
  failed (str): Indicates that the method did not execute successfully.
  not_implemented (str): Indicates that the method is not implemented.

#### failed *= 'failed'*

#### not_implemented *= 'not_implemented'*

#### success *= 'success'*

### *class* helao.drivers.helao_driver.DriverStatus(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `StrEnum`

DriverStatus is an enumeration representing the various states a driver can be in.

Attributes:
: ok (str): Indicates the driver is working as expected.
  busy (str): Indicates the driver is operating or using a resource.
  error (str): Indicates the driver returned a low-level error.
  uninitialized (str): Indicates the driver connection to the device has not been established.
  unknown (str): Indicates the driver is in an unknown state.

#### busy *= 'busy'*

#### error *= 'error'*

#### ok *= 'ok'*

#### uninitialized *= 'uninitialized'*

#### unknown *= 'unknown'*

### *class* helao.drivers.helao_driver.HelaoDriver(config={})

Bases: `ABC`

HelaoDriver is an abstract base class that defines the interface for a driver in the Helao system.

Attributes:
: timestamp (datetime): The timestamp when the driver instance was created.
  config (dict): Configuration dictionary for the driver.

Methods:
: connect() -> DriverResponse:
  : Open connection to resource.
  <br/>
  get_status() -> DriverResponse:
  : Return current driver status.
  <br/>
  stop() -> DriverResponse:
  : General stop method, abort all active methods e.g. motion, I/O, compute.
  <br/>
  reset() -> DriverResponse:
  : Reinitialize driver, force-close old connection if necessary.
  <br/>
  disconnect() -> DriverResponse:
  : Release connection to resource.

Properties:
: \_created_at (str):
  : Instantiation timestamp formatted as “YYYY-MM-DD HH:MM:SS,mmm”.
  <br/>
  \_uptime (str):
  : Driver uptime formatted as “YYYY-MM-DD HH:MM:SS,mmm”.

#### \_\_init_\_(config={})

Initializes the HelaoDriver instance.

Args:
: config (dict, optional): Configuration dictionary for the driver. Defaults to an empty dictionary.

Attributes:
: timestamp (datetime): The timestamp when the instance is created.
  config (dict): The configuration dictionary for the driver.

#### config *: `dict`*

#### *abstract* connect()

Open connection to resource.

* **Return type:**
  [`DriverResponse`](#helao.drivers.helao_driver.DriverResponse)

#### *abstract* disconnect()

Release connection to resource.

* **Return type:**
  [`DriverResponse`](#helao.drivers.helao_driver.DriverResponse)

#### *abstract* get_status()

Return current driver status.

* **Return type:**
  [`DriverResponse`](#helao.drivers.helao_driver.DriverResponse)

#### *abstract* reset()

Reinitialize driver, force-close old connection if necessary.

* **Return type:**
  [`DriverResponse`](#helao.drivers.helao_driver.DriverResponse)

#### *abstract* stop()

General stop method, abort all active methods e.g. motion, I/O, compute.

* **Return type:**
  [`DriverResponse`](#helao.drivers.helao_driver.DriverResponse)

#### timestamp *: `datetime`*

## Module contents
